from typing import Any, TypeVar

from sqlalchemy import create_engine, select
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# DEM (Data Expert Manipulator): one per model, in the model's file.
# Holds model-specific operations and calls Database.


class Base(DeclarativeBase):
    """Parent of all models."""


T = TypeVar("T", bound=Base)


class Database:
    """Generic worker for all database communication."""

    def __init__(self, url: str, echo: bool = False):
        """Set up the engine; echo prints the SQL."""
        self.engine = create_engine(url, echo=echo, connect_args={"connect_timeout": 5})
        self._session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def create_tables(self) -> None:
        """Create missing tables."""
        Base.metadata.create_all(self.engine)

    def add(self, obj: T) -> T:
        """Insert one object."""
        with self._session_factory.begin() as session:
            session.add(obj)
        return obj

    def add_many(self, objs: list[T]) -> list[T]:
        """Insert several objects in one transaction."""
        with self._session_factory.begin() as session:
            session.add_all(objs)
        return objs

    def get(self, model: type[T], obj_id: Any) -> T | None:
        """Get one object by primary key, or None."""
        with self._session_factory() as session:
            return session.get(model, obj_id)

    def get_all(self, model: type[T]) -> list[T]:
        """Get all objects of a model."""
        with self._session_factory() as session:
            return list(session.scalars(select(model)))

    def find_by(self, model: type[T], **filters: Any) -> list[T]:
        """Get objects matching all column=value filters."""
        with self._session_factory() as session:
            return list(session.scalars(select(model).filter_by(**filters)))

    def update(self, obj: T) -> T:
        """Save changes of an object; use the returned copy."""
        with self._session_factory.begin() as session:
            return session.merge(obj)

    def delete(self, obj: Base) -> None:
        """Delete the object's row."""
        with self._session_factory.begin() as session:
            session.delete(session.merge(obj))

    def close(self) -> None:
        """Close all connections."""
        self.engine.dispose()
