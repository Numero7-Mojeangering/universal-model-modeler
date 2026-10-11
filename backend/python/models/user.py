import random
from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, Database

CURSOR_PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#008080", "#9a6324", "#e0457b"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(moment: datetime) -> datetime:
    """Some databases hand back datetimes without a timezone; they are always UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)  # lowercase; the login name
    display_name: Mapped[str]  # shown next to the user's cursor
    cursor_color: Mapped[str]  # "#rrggbb", the colour of the user's cursor
    opaque_record: Mapped[str | None]  # OPAQUE password file; None until the user sets a password
    is_admin: Mapped[bool] = mapped_column(default=False)
    disabled: Mapped[bool] = mapped_column(default=False)
    failed_attempts: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def __repr__(self) -> str:
        return f"User(id={self.id}, username={self.username!r}, is_admin={self.is_admin})"


class UserDEM:
    """Data Expert Manipulator: user-specific operations on top of the generic Database."""

    def __init__(self, db: Database):
        self.db = db

    def create(self, username: str, display_name: str | None = None, is_admin: bool = False) -> User:
        user = User(
            username=username,
            display_name=display_name or username,
            cursor_color=random.choice(CURSOR_PALETTE),
            opaque_record=None,
            is_admin=is_admin,
        )
        return self.db.add(user)

    def get(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def by_username(self, username: str) -> User | None:
        found = self.db.find_by(User, username=username)
        return found[0] if found else None

    def all(self) -> list[User]:
        return sorted(self.db.get_all(User), key=lambda user: user.username)

    def save(self, user: User) -> User:
        return self.db.update(user)

    def remove(self, user: User) -> None:
        self.db.delete(user)
