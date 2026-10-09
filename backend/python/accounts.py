import secrets

import opaquepy

from models.user import User
from security import opaque_setup
from services import close_sessions_threadsafe, sessions, users

ADMIN_USERNAME = "admin"


def password_record(username: str, password: str) -> str:
    """Run both sides of OPAQUE registration here. Only for passwords the server itself generated."""
    request, state = opaquepy.register_client(password)
    response = opaquepy.register(opaque_setup(), request, username)
    return opaquepy.register_finish(opaquepy.register_client_finish(state, password, response))


def revoke_sessions(user_id: int) -> list[int]:
    """Log a user out everywhere. Return the session ids so their live connections can be cut."""
    return sessions.remove_of_user(user_id)


def reset_admin() -> tuple[User, str]:
    """Give the admin account a new generated password, creating the account if needed."""
    user = users.by_username(ADMIN_USERNAME) or users.create(ADMIN_USERNAME, is_admin=True)
    password = secrets.token_urlsafe(12)
    user.opaque_record = password_record(user.username, password)
    user.is_admin, user.disabled = True, False
    user.failed_attempts, user.locked_until = 0, None
    user = users.save(user)
    close_sessions_threadsafe(revoke_sessions(user.id))
    return user, password


def ensure_admin() -> str | None:
    """On an empty database, create the admin and return its generated password."""
    if users.all():
        return None
    return reset_admin()[1]
