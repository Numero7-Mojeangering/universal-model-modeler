from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, Database
from models.user import utcnow


class DeviceSession(Base):
    """One login on one device. Its tokens only work together with the device's private key."""

    __tablename__ = "device_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_key: Mapped[str]  # base64 raw Ed25519 public key
    access_hash: Mapped[str] = mapped_column(index=True)  # SHA-256 of the token; the token itself is never stored
    access_expires: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refresh_hash: Mapped[str] = mapped_column(index=True)
    previous_refresh_hash: Mapped[str | None]  # a replay of this one means the refresh token was stolen
    refresh_expires: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SessionDEM:
    def __init__(self, db: Database):
        self.db = db

    def create(self, session: DeviceSession) -> DeviceSession:
        return self.db.add(session)

    def by_access(self, token_hash: str) -> DeviceSession | None:
        found = self.db.find_by(DeviceSession, access_hash=token_hash)
        return found[0] if found else None

    def by_refresh(self, token_hash: str) -> DeviceSession | None:
        found = self.db.find_by(DeviceSession, refresh_hash=token_hash)
        return found[0] if found else None

    def by_previous_refresh(self, token_hash: str) -> DeviceSession | None:
        found = self.db.find_by(DeviceSession, previous_refresh_hash=token_hash)
        return found[0] if found else None

    def of_user(self, user_id: int) -> list[DeviceSession]:
        return self.db.find_by(DeviceSession, user_id=user_id)

    def save(self, session: DeviceSession) -> DeviceSession:
        return self.db.update(session)

    def remove(self, session: DeviceSession) -> None:
        self.db.delete(session)

    def remove_of_user(self, user_id: int) -> list[int]:
        """Delete every session of a user; return their ids."""
        sessions = self.of_user(user_id)
        for session in sessions:
            self.db.delete(session)
        return [session.id for session in sessions]
