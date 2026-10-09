import asyncio
import os

from database import Database
from hub import Hub
from migrations import migrate, migrate_users
from models import layout, session  # noqa: F401  (importing registers the tables)
from models.session import SessionDEM
from models.user import UserDEM

db = Database(os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:password@localhost:5432/postgres"))
users = UserDEM(db)
sessions = SessionDEM(db)
hub = Hub()
loop: asyncio.AbstractEventLoop | None = None  # the server's event loop, set when it starts


def init_db() -> None:
    migrate_users(db)
    db.create_tables()
    migrate(db)


def close_sessions_threadsafe(session_ids: list[int]) -> None:
    """For code outside the event loop, such as the console."""
    if loop is not None and session_ids:
        asyncio.run_coroutine_threadsafe(hub.close_sessions(session_ids), loop)
