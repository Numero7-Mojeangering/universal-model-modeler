from typing import Any, TypeVar

from sqlalchemy import Table, create_engine, inspect, select
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.schema import AddConstraint

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

    def table_columns(self, name: str) -> set[str]:
        """Column names of an existing table; empty if the table does not exist."""
        inspector = inspect(self.engine)
        if not inspector.has_table(name):
            return set()
        return {column["name"] for column in inspector.get_columns(name)}

    def drop_table(self, table: Table) -> None:
        """Drop a table if it exists."""
        table.drop(self.engine, checkfirst=True)

    def ensure_foreign_key(self, table: Table, name: str) -> None:
        """Add a foreign key declared on the model to a table that already exists."""
        if any(fk["name"] == name for fk in inspect(self.engine).get_foreign_keys(table.name)):
            return
        constraint = next(c for c in table.foreign_key_constraints if c.name == name)
        with self.engine.begin() as connection:
            connection.execute(AddConstraint(constraint))

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

    def rename_key(self, model: type[T], old_key: Any, attribute: str, new_value: Any) -> bool:
        """Change a primary key value; foreign keys with ON UPDATE CASCADE follow. False if `old_key` is unknown."""
        with self._session_factory.begin() as session:
            obj = session.get(model, old_key)
            if obj is None:
                return False
            setattr(obj, attribute, new_value)
        return True

    def delete(self, obj: Base) -> None:
        """Delete the object's row."""
        with self._session_factory.begin() as session:
            session.delete(session.merge(obj))

    def close(self) -> None:
        """Close all connections."""
        self.engine.dispose()
