from sqlalchemy.orm import Mapped, mapped_column

from database import Base, Database


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str] = mapped_column(unique=True)

    def __repr__(self) -> str:
        return f"User(id={self.id}, name={self.name!r}, email={self.email!r})"


class UserDEM:
    """Data Expert Manipulator: user-specific operations on top of the generic Database."""

    def __init__(self, db: Database):
        self.db = db

    def create(self, name: str, email: str) -> User:
        return self.db.add(User(name=name, email=email))

    def find_by_email(self, email: str) -> User | None:
        found = self.db.find_by(User, email=email)
        return found[0] if found else None

    def rename(self, user: User, new_name: str) -> User:
        user.name = new_name
        return self.db.update(user)
