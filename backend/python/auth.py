import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta
from functools import cache
from typing import Literal

import opaquepy
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from starlette.datastructures import Headers

from accounts import password_record, revoke_sessions
from hub import UNAUTHORIZED_CLOSE_CODE
from models.session import DeviceSession
from models.user import User, as_utc, utcnow
from schemas import (
    JsonDict,
    LoginFinish,
    LoginStart,
    ProfilePatch,
    RegisterFinish,
    RegisterStart,
    UserCreate,
    UserPatch,
    user_dict,
)
from security import (
    DEVICE_PROOF_LABEL,
    NonceCache,
    RateLimiter,
    b64decode,
    is_fresh,
    new_token,
    opaque_setup,
    signing_message,
    token_hash,
    verify_signature,
)
from services import hub, sessions, users

ACCESS_TTL = timedelta(minutes=10)
REFRESH_TTL = timedelta(days=30)
MAX_ATTEMPTS = 5  # login attempts without success before the account is locked
LOCK_TIME = timedelta(minutes=15)
PENDING_SECONDS = 60

nonces = NonceCache()
ip_limiter = RateLimiter(limit=30, window=60)


def unauthorized() -> HTTPException:
    return HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"})


@dataclass
class Auth:
    user: User
    session: DeviceSession


def request_target(scope: dict) -> str:
    """Path and query exactly as the client sent them; the client signs the same string."""
    path = (scope.get("raw_path") or scope["path"].encode()).decode("latin-1")
    query = scope.get("query_string", b"").decode("latin-1")
    return f"{path}?{query}" if query else path


def verify_signed(
    headers: Headers, method: str, target: str, body: bytes, kind: Literal["access", "refresh"]
) -> tuple[DeviceSession, bool]:
    """Check a request signed with a device key. The bool tells that a rotated-out refresh token was replayed."""
    scheme, _, token = headers.get("authorization", "").partition(" ")
    timestamp = headers.get("x-umm-timestamp", "")
    nonce = headers.get("x-umm-nonce", "")
    signature = headers.get("x-umm-signature", "")
    if scheme != "Bearer" or not token or not nonce or not signature or not is_fresh(timestamp):
        raise unauthorized()
    digest = token_hash(token)
    replayed = False
    if kind == "access":
        session = sessions.by_access(digest)
    else:
        session = sessions.by_refresh(digest)
        if session is None:
            session, replayed = sessions.by_previous_refresh(digest), True
    if session is None:
        raise unauthorized()
    if not verify_signature(session.device_key, signing_message(method, target, timestamp, nonce, body, token), signature):
        raise unauthorized()
    if not nonces.accept(nonce):
        raise unauthorized()
    if not replayed:
        expires = session.access_expires if kind == "access" else session.refresh_expires
        if as_utc(expires) <= utcnow():
            raise unauthorized()
    return session, replayed


def _auth_for(session: DeviceSession) -> Auth:
    user = users.get(session.user_id)
    if user is None or user.disabled:
        raise unauthorized()
    return Auth(user, session)


async def authenticated(request: Request) -> Auth:
    body = await request.body()
    session, _ = verify_signed(request.headers, request.method, request_target(request.scope), body, "access")
    return _auth_for(session)


async def authenticate_ws(ws: WebSocket) -> Auth | None:
    """Same check for the WebSocket handshake; closes the connection when it fails."""
    try:
        session, _ = verify_signed(ws.headers, "GET", request_target(ws.scope), b"", "access")
        return _auth_for(session)
    except HTTPException:
        await ws.close(code=UNAUTHORIZED_CLOSE_CODE)
        return None


async def admin_only(auth: Auth = Depends(authenticated)) -> Auth:
    if not auth.user.is_admin:
        raise HTTPException(403, "Administrators only")
    return auth


def limit_by_ip(request: Request) -> None:
    if not ip_limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(429, "Too many requests, slow down")


@cache
def _dummy_record() -> str:
    """Lets an unknown username answer like a real one, so usernames cannot be probed."""
    return password_record("dummy", secrets.token_urlsafe(16))


def _protocol_error() -> HTTPException:
    return HTTPException(400, "Malformed request")


@dataclass
class PendingLogin:
    state: str
    user_id: int | None
    expires: float


pending: dict[str, PendingLogin] = {}


def _tokens(user: User, access: str, refresh: str) -> JsonDict:
    return {
        "access_token": access,
        "access_expires_in": int(ACCESS_TTL.total_seconds()),
        "refresh_token": refresh,
        "user": user_dict(user),
    }


def _awaiting_password(username: str) -> User:
    user = users.by_username(username)
    if user is None or user.disabled or user.opaque_record is not None:
        raise HTTPException(403, "This account is not waiting for a password")
    return user


public = APIRouter(prefix="/auth", dependencies=[Depends(limit_by_ip)])


@public.post("/register/start")
async def register_start(body: RegisterStart) -> JsonDict:
    """First login of an account the admin created: the user chooses a password. The server never sees it."""
    user = _awaiting_password(body.username)
    try:
        return {"response": opaquepy.register(opaque_setup(), body.request, user.username)}
    except Exception:
        raise _protocol_error()


@public.post("/register/finish", status_code=204)
async def register_finish(body: RegisterFinish) -> None:
    user = _awaiting_password(body.username)
    try:
        user.opaque_record = opaquepy.register_finish(body.request)
    except Exception:
        raise _protocol_error()
    users.save(user)


@public.post("/login/start")
async def login_start(body: LoginStart) -> JsonDict:
    now = utcnow()
    user = users.by_username(body.username)
    if user is not None and user.disabled:
        user = None  # a disabled account looks like an unknown one
    if user is not None and user.opaque_record is None:
        return {"status": "needs_password"}
    record, user_id = _dummy_record(), None
    if user is not None and user.opaque_record is not None:
        if user.locked_until is not None:
            if as_utc(user.locked_until) > now:
                raise HTTPException(429, "Too many failed attempts, try again later")
            user.failed_attempts, user.locked_until = 0, None
        # A wrong password is only noticed by the client, so every start counts until a login succeeds.
        user.failed_attempts += 1
        if user.failed_attempts > MAX_ATTEMPTS:
            user.locked_until = now + LOCK_TIME
            users.save(user)
            raise HTTPException(429, "Too many failed attempts, try again later")
        users.save(user)
        record, user_id = user.opaque_record, user.id
    try:
        response, state = opaquepy.login(opaque_setup(), record, body.request, body.username)
    except Exception:
        raise _protocol_error()
    now_s = time.monotonic()
    for key in [k for k, p in pending.items() if p.expires < now_s]:
        del pending[key]
    if len(pending) > 10_000:
        raise HTTPException(503, "Busy, try again later")
    login_id = new_token()
    pending[login_id] = PendingLogin(state, user_id, now_s + PENDING_SECONDS)
    return {"status": "ok", "login_id": login_id, "response": response}


def _start_session(user: User, device_key: str) -> JsonDict:
    access, refresh = new_token(), new_token()
    now = utcnow()
    sessions.create(
        DeviceSession(
            user_id=user.id,
            device_key=device_key,
            access_hash=token_hash(access),
            access_expires=now + ACCESS_TTL,
            refresh_hash=token_hash(refresh),
            previous_refresh_hash=None,
            refresh_expires=now + REFRESH_TTL,
        )
    )
    return _tokens(user, access, refresh)


@public.post("/login/finish")
async def login_finish(body: LoginFinish) -> JsonDict:
    entry = pending.pop(body.login_id, None)
    if entry is None or entry.expires < time.monotonic() or entry.user_id is None:
        raise unauthorized()
    try:
        session_key = opaquepy.login_finish(body.request, entry.state)
    except Exception:
        raise unauthorized()
    user = users.get(entry.user_id)
    if user is None or user.disabled:
        raise unauthorized()
    try:
        public_key = b64decode(body.device_key)
        Ed25519PublicKey.from_public_bytes(public_key)
        proof = b64decode(body.device_proof)
    except ValueError:
        raise _protocol_error()
    expected = hmac.new(b64decode(session_key), DEVICE_PROOF_LABEL + public_key, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, proof):
        raise unauthorized()
    user.failed_attempts, user.locked_until = 0, None
    return _start_session(users.save(user), body.device_key)


@public.post("/refresh")
async def refresh(request: Request) -> JsonDict:
    body = await request.body()
    session, replayed = verify_signed(request.headers, "POST", request_target(request.scope), body, "refresh")
    if replayed:  # the token was already used once, so a copy of it exists somewhere else
        sessions.remove(session)
        await hub.close_sessions([session.id])
        raise unauthorized()
    user = users.get(session.user_id)
    if user is None or user.disabled:
        sessions.remove(session)
        raise unauthorized()
    access, refresh_token = new_token(), new_token()
    now = utcnow()
    session.previous_refresh_hash = session.refresh_hash
    session.access_hash, session.access_expires = token_hash(access), now + ACCESS_TTL
    session.refresh_hash, session.refresh_expires = token_hash(refresh_token), now + REFRESH_TTL
    sessions.save(session)
    return _tokens(user, access, refresh_token)


account = APIRouter(dependencies=[Depends(authenticated)])


@account.post("/auth/logout", status_code=204)
async def logout(auth: Auth = Depends(authenticated)) -> None:
    sessions.remove(auth.session)
    await hub.close_sessions([auth.session.id])


@account.get("/me")
async def get_me(auth: Auth = Depends(authenticated)) -> JsonDict:
    return user_dict(auth.user)


@account.patch("/me")
async def patch_me(body: ProfilePatch, auth: Auth = Depends(authenticated)) -> JsonDict:
    user = auth.user
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.cursor_color is not None:
        user.cursor_color = body.cursor_color
    user = users.save(user)
    await hub.update_profile(user)
    return user_dict(user)


admin = APIRouter(prefix="/admin", dependencies=[Depends(admin_only)])


def _other_user(user_id: int, auth: Auth) -> User:
    user = users.get(user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user.id == auth.user.id:
        raise HTTPException(400, "You cannot do this to your own account")
    return user


@admin.get("/users")
async def list_users() -> list[JsonDict]:
    return [user_dict(user) for user in users.all()]


@admin.post("/users", status_code=201)
async def create_user(body: UserCreate) -> JsonDict:
    if users.by_username(body.username) is not None:
        raise HTTPException(409, f"The username '{body.username}' is taken")
    return user_dict(users.create(body.username, body.display_name, body.is_admin))


@admin.patch("/users/{user_id}")
async def patch_user(user_id: int, body: UserPatch, auth: Auth = Depends(authenticated)) -> JsonDict:
    user = _other_user(user_id, auth)
    if body.is_admin is not None:
        user.is_admin = body.is_admin
    if body.disabled is not None:
        user.disabled = body.disabled
    user = users.save(user)
    if user.disabled:
        await hub.close_sessions(revoke_sessions(user.id))
    return user_dict(user)


@admin.post("/users/{user_id}/reset-password")
async def reset_password(user_id: int, auth: Auth = Depends(authenticated)) -> JsonDict:
    """The user sets a new password at their next login."""
    user = _other_user(user_id, auth)
    user.opaque_record, user.failed_attempts, user.locked_until = None, 0, None
    user = users.save(user)
    await hub.close_sessions(revoke_sessions(user.id))
    return user_dict(user)


@admin.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: int, auth: Auth = Depends(authenticated)) -> None:
    user = _other_user(user_id, auth)
    ids = revoke_sessions(user.id)
    users.remove(user)
    await hub.close_sessions(ids)


routers = [public, account, admin]
