import base64
import hashlib
import hmac
import json
import secrets
import ssl
import time
from typing import Any, cast
from urllib.parse import quote, urlparse

import keyring
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from keyring.errors import KeyringError
from opaquepy import lib as opaque
from requests.adapters import HTTPAdapter
from requests.auth import AuthBase

from data import Catalogue, Graph

KEYRING_SERVICE = "umm"
DEVICE_PROOF_LABEL = b"umm-device-v1"
REFRESH_MARGIN = 30  # seconds before expiry when the access token is renewed


class AuthError(Exception):
    """Wrong credentials, or the server ended the session."""


class NeedsPassword(Exception):
    """The account exists but has no password yet; the user must choose one."""


class UntrustedCertificate(Exception):
    """The server's certificate is not trusted; the user must confirm its fingerprint."""

    def __init__(self, fingerprint: str, changed: bool):
        super().__init__(fingerprint)
        self.fingerprint = fingerprint
        self.changed = changed  # True if the user had trusted a different certificate before


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def format_fingerprint(der: bytes) -> str:
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


def server_fingerprint(host: str, port: int) -> str:
    """SHA-256 of the certificate the server presents, whether or not it is trusted."""
    pem = ssl.get_server_certificate((host, port), timeout=5)
    return format_fingerprint(ssl.PEM_cert_to_DER_cert(pem))


def signed_headers(key: Ed25519PrivateKey, token: str, method: str, target: str, body: bytes) -> dict[str, str]:
    """Prove with the device key that this exact request comes from the device the token was issued to."""
    timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
    token_digest = hashlib.sha256(token.encode()).hexdigest()
    parts = ["umm-v1", method.upper(), target, timestamp, nonce, hashlib.sha256(body).hexdigest(), token_digest]
    return {
        "Authorization": f"Bearer {token}",
        "X-Umm-Timestamp": timestamp,
        "X-Umm-Nonce": nonce,
        "X-Umm-Signature": _b64(key.sign("\n".join(parts).encode())),
    }


class _Signed(AuthBase):
    def __init__(self, key: Ed25519PrivateKey, token: str):
        self.key, self.token = key, token

    def __call__(self, r: requests.PreparedRequest) -> requests.PreparedRequest:
        body = r.body.encode() if isinstance(r.body, str) else (r.body or b"")
        r.headers.update(signed_headers(self.key, self.token, cast(str, r.method), cast(str, r.path_url), cast(bytes, body)))
        return r


class _PinnedAdapter(HTTPAdapter):
    """Accepts only the server certificate with this fingerprint, whoever signed it."""

    def __init__(self, fingerprint: str):
        self._fingerprint = fingerprint.replace(":", "")
        super().__init__()

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        kwargs["assert_fingerprint"] = self._fingerprint
        super().init_poolmanager(*args, **kwargs)


def _detail(response: requests.Response) -> str:
    try:
        return str(response.json()["detail"])
    except (ValueError, KeyError, TypeError):
        return response.reason or "Request failed"


def describe_error(exc: Exception) -> str:
    """Text for the user: what the server said, or the network error."""
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return _detail(exc.response)
    return str(exc)


class Api:
    """REST calls to the backend. Changes come back to the UI through the WebSocket.

    Every call is signed with this device's private key; the server refuses a token used without it.
    """

    def __init__(self, base_url: str = "https://127.0.0.1:8000", pin: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.pin: str | None = None
        self._http = requests.Session()
        if pin:
            self.set_pin(pin)
        self.user: dict[str, Any] | None = None
        self._username = ""
        self._key: Ed25519PrivateKey | None = None
        self._access = ""
        self._access_expires = 0.0
        self._refresh = ""

    @property
    def ws_url(self) -> str:
        return self.base_url.replace("http", "ws", 1) + "/ws"

    @property
    def host_key(self) -> str:
        """host:port, which identifies the server for certificate pinning."""
        parsed = urlparse(self.base_url)
        return f"{parsed.hostname}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"

    def set_pin(self, fingerprint: str) -> None:
        """Trust only the certificate with this SHA-256 fingerprint."""
        self.pin = fingerprint
        self._http.mount("https://", _PinnedAdapter(fingerprint))
        self._http.verify = False  # the fingerprint check replaces the CA check

    def check_server(self) -> None:
        """Reach the server; raise UntrustedCertificate if its certificate has to be confirmed first."""
        try:
            self._http.get(self.base_url + "/health", timeout=5).raise_for_status()
        except requests.exceptions.SSLError as exc:
            host, port = self.host_key.rsplit(":", 1)
            raise UntrustedCertificate(server_fingerprint(host, int(port)), changed=self.pin is not None) from exc

    # --- accounts --------------------------------------------------------

    def _keyring_account(self, username: str) -> str:
        return f"{self.base_url}|{username}"

    def _persist(self) -> None:
        if self._key is None:
            return
        raw = self._key.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
        )
        secret = json.dumps({"key": _b64(raw), "refresh": self._refresh})
        try:
            keyring.set_password(KEYRING_SERVICE, self._keyring_account(self._username), secret)
        except KeyringError:
            pass  # no secret store on this machine: the user signs in again next time

    def _forget(self) -> None:
        try:
            keyring.delete_password(KEYRING_SERVICE, self._keyring_account(self._username))
        except KeyringError:
            pass
        self._key, self._access, self._refresh, self.user = None, "", "", None

    def _store_tokens(self, data: dict[str, Any]) -> None:
        self._access = data["access_token"]
        self._access_expires = time.time() + data["access_expires_in"]
        self._refresh = data["refresh_token"]
        self.user = data["user"]
        self._persist()

    def _public(self, path: str, body: dict[str, Any]) -> Any:
        """A call before sign-in. 401 and 429 become AuthError with the server's explanation."""
        response = self._http.post(self.base_url + path, json=body, timeout=10)
        if response.status_code in (401, 429):
            raise AuthError(_detail(response))
        response.raise_for_status()
        return response.json() if response.content else None

    def register(self, username: str, password: str) -> None:
        """Choose the first password. The server only receives a value from which it cannot recover it."""
        username = username.strip().lower()
        request, state = opaque.register_client(password)
        response = self._public("/auth/register/start", {"username": username, "request": request})
        finish = opaque.register_client_finish(state, password, response["response"])
        self._public("/auth/register/finish", {"username": username, "request": finish})

    def login(self, username: str, password: str) -> dict[str, Any]:
        username = username.strip().lower()
        request, state = opaque.login_client(password)
        start = self._public("/auth/login/start", {"username": username, "request": request})
        if start["status"] == "needs_password":
            raise NeedsPassword
        try:
            finish, session_key = opaque.login_client_finish(state, password, start["response"])
        except Exception as exc:
            raise AuthError("Wrong username or password") from exc
        key = Ed25519PrivateKey.generate()  # new device key for every login
        public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        proof = hmac.new(_unb64(session_key), DEVICE_PROOF_LABEL + public, hashlib.sha256).digest()
        data = self._public(
            "/auth/login/finish",
            {"login_id": start["login_id"], "request": finish, "device_key": _b64(public), "device_proof": _b64(proof)},
        )
        self._key, self._username = key, username
        self._store_tokens(data)
        return cast(dict[str, Any], data["user"])

    def restore(self, username: str) -> bool:
        """Sign in again from the secret store without asking for the password."""
        username = username.strip().lower()
        try:
            stored = keyring.get_password(KEYRING_SERVICE, self._keyring_account(username))
            if not stored:
                return False
            data = json.loads(stored)
            self._key = Ed25519PrivateKey.from_private_bytes(_unb64(data["key"]))
            self._refresh, self._username = data["refresh"], username
            self._refresh_tokens()
        except (KeyringError, ValueError, KeyError, AuthError):
            return False
        return True

    def logout(self) -> None:
        try:
            self._call("POST", "/auth/logout")
        except (requests.RequestException, AuthError):
            pass
        self._forget()

    def _refresh_tokens(self) -> None:
        if self._key is None or not self._refresh:
            raise AuthError("Not signed in")
        response = self._http.post(
            self.base_url + "/auth/refresh", auth=_Signed(self._key, self._refresh), timeout=10
        )
        if response.status_code in (401, 429):
            if response.status_code == 401:
                self._forget()
            raise AuthError("Your session ended, please sign in again" if response.status_code == 401 else _detail(response))
        response.raise_for_status()
        self._store_tokens(response.json())

    def _ensure_access(self) -> None:
        if self._key is None:
            raise AuthError("Not signed in")
        if time.time() >= self._access_expires - REFRESH_MARGIN:
            self._refresh_tokens()

    def ws_headers(self) -> dict[str, str]:
        """Signed headers for the WebSocket handshake."""
        self._ensure_access()
        return signed_headers(cast(Ed25519PrivateKey, self._key), self._access, "GET", urlparse(self.ws_url).path, b"")

    # --- requests --------------------------------------------------------

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        self._ensure_access()
        for attempt in range(2):
            auth = _Signed(cast(Ed25519PrivateKey, self._key), self._access)
            response = self._http.request(method, self.base_url + path, timeout=5, auth=auth, **kwargs)
            if response.status_code == 401 and attempt == 0:
                self._refresh_tokens()  # the access token may have just expired
                continue
            break
        if response.status_code == 401:
            self._forget()
            raise AuthError("Your session ended, please sign in again")
        response.raise_for_status()
        return response.json() if response.content else None

    def update_profile(self, display_name: str, cursor_color: str) -> dict[str, Any]:
        self.user = cast(dict[str, Any], self._call("PATCH", "/me", json={"display_name": display_name, "cursor_color": cursor_color}))
        return self.user

    def users(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._call("GET", "/admin/users"))

    def create_user(self, username: str, is_admin: bool) -> Any:
        return self._call("POST", "/admin/users", json={"username": username, "is_admin": is_admin})

    def set_user_flags(self, user_id: int, disabled: bool | None = None, is_admin: bool | None = None) -> Any:
        body = {k: v for k, v in {"disabled": disabled, "is_admin": is_admin}.items() if v is not None}
        return self._call("PATCH", f"/admin/users/{user_id}", json=body)

    def reset_user_password(self, user_id: int) -> Any:
        return self._call("POST", f"/admin/users/{user_id}/reset-password")

    def delete_user(self, user_id: int) -> Any:
        return self._call("DELETE", f"/admin/users/{user_id}")

    def graph(self) -> Graph:
        return cast(Graph, self._call("GET", "/graph"))

    def catalogue(self) -> Catalogue:
        return cast(Catalogue, self._call("GET", "/catalogue"))

    def delete_catalogue_entry(self, kind: str, name: str) -> Any:
        """Delete an unused entity type, relation type or property name (kind: entity, relation, property)."""
        return self._call("DELETE", f"/catalogue/{kind}/{quote(name, safe='')}")

    def create_entity(self, type: str, x: float, y: float, shape: str, color: str) -> Any:
        body = {"type": type, "x": x, "y": y, "shape": shape, "color": color}
        return self._call("POST", "/entities", json=body)

    def set_type(self, entity_id: int, type: str, shape: str | None = None, color: str | None = None) -> Any:
        body: dict[str, str] = {"type": type}
        if shape and color:  # style of the type, used only if the type is new
            body.update(shape=shape, color=color)
        return self._call("PATCH", f"/entities/{entity_id}", json=body)

    def delete_entity(self, entity_id: int):
        return self._call("DELETE", f"/entities/{entity_id}")

    def create_property(self, entity_id: int, name: str, value: str) -> Any:
        return self._call("POST", f"/entities/{entity_id}/properties", json={"name": name, "value": value})

    def set_property(self, entity_id: int, name: str, value: str) -> Any:
        return self._call("PUT", f"/entities/{entity_id}/properties/{quote(name, safe='')}", json={"value": value})

    def rename_property(self, old: str, new: str) -> Any:
        """Rename a property name on every entity that has it."""
        return self._call("PUT", f"/property-names/{quote(old, safe='')}", json={"name": new})

    def delete_property(self, entity_id: int, name: str):
        return self._call("DELETE", f"/entities/{entity_id}/properties/{quote(name, safe='')}")

    def set_layout(self, entity_id: int, x: float, y: float) -> Any:
        return self._call("PUT", f"/entities/{entity_id}/layout", json={"x": x, "y": y})

    def set_entity_style(self, type: str, shape: str, color: str) -> Any:
        return self._call("PUT", f"/types/entity/{quote(type, safe='')}/style", json={"shape": shape, "color": color})

    def create_relation(self, source_id: int, target_id: int, type: str):
        return self._call("POST", "/relations", json={"source_id": source_id, "target_id": target_id, "type": type})

    def delete_relation(self, source_id: int, target_id: int, type: str):
        return self._call(
            "DELETE", "/relations", params={"source_id": source_id, "target_id": target_id, "type": type}
        )
