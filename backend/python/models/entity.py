from sqlalchemy import BigInteger, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, Database
from models.catalogue import EntityType, PropertyType, RelationType


class Entity(Base):
    __tablename__ = "entity"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(Text, ForeignKey(EntityType.name, name="entity_type_fk", onupdate="CASCADE"))

    def __repr__(self) -> str:
        return f"Entity(id={self.id}, type={self.type!r})"


class Property(Base):
    __tablename__ = "property"

    entity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entity.id", ondelete="CASCADE"), primary_key=True, autoincrement=False
    )
    # One value per name per entity, so (entity_id, name) is the key.
    name: Mapped[str] = mapped_column(
        Text, ForeignKey(PropertyType.name, name="property_type_fk", onupdate="CASCADE"), primary_key=True
    )
    value: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"Property(entity_id={self.entity_id}, {self.name!r}={self.value!r})"


class Relation(Base):
    __tablename__ = "relation"

    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entity.id", ondelete="CASCADE"), primary_key=True, autoincrement=False
    )
    target_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entity.id", ondelete="CASCADE"), primary_key=True, autoincrement=False
    )
    type: Mapped[str] = mapped_column(
        Text, ForeignKey(RelationType.name, name="relation_type_fk", onupdate="CASCADE"), primary_key=True
    )

    def __repr__(self) -> str:
        return f"Relation({self.source_id} -{self.type}-> {self.target_id})"


class EntityDEM:
    """Data Expert Manipulator for entities."""

    def __init__(self, db: Database):
        self.db = db

    def create(self, type: str) -> Entity:
        return self.db.add(Entity(type=type))

    def get(self, entity_id: int) -> Entity | None:
        return self.db.get(Entity, entity_id)

    def all(self) -> list[Entity]:
        return self.db.get_all(Entity)

    def set_type(self, entity: Entity, type: str) -> Entity:
        entity.type = type
        return self.db.update(entity)

    def remove(self, entity: Entity) -> None:
        # Properties, relations and layout are removed by ON DELETE CASCADE.
        self.db.delete(entity)


class PropertyDEM:
    """Data Expert Manipulator for entity properties."""

    def __init__(self, db: Database):
        self.db = db

    def all(self) -> list[Property]:
        return self.db.get_all(Property)

    def of(self, entity_id: int) -> list[Property]:
        return self.db.find_by(Property, entity_id=entity_id)

    def named(self, name: str) -> list[Property]:
        return self.db.find_by(Property, name=name)

    def create(self, entity_id: int, name: str, value: str | None) -> Property:
        """Add a property; fails if the entity already has one with this name."""
        return self.db.add(Property(entity_id=entity_id, name=name, value=value))

    def set_value(self, entity_id: int, name: str, value: str | None) -> Property | None:
        """Change the value of an existing property; None if the entity has no such property."""
        existing = self.db.get(Property, (entity_id, name))
        if existing is None:
            return None
        existing.value = value
        return self.db.update(existing)

    def remove(self, entity_id: int, name: str) -> bool:
        existing = self.db.get(Property, (entity_id, name))
        if existing is None:
            return False
        self.db.delete(existing)
        return True


class RelationDEM:
    """Data Expert Manipulator for relations between entities."""

    def __init__(self, db: Database):
        self.db = db

    def all(self) -> list[Relation]:
        return self.db.get_all(Relation)

    def create(self, source_id: int, target_id: int, type: str) -> Relation:
        return self.db.add(Relation(source_id=source_id, target_id=target_id, type=type))

    def remove(self, source_id: int, target_id: int, type: str) -> bool:
        existing = self.db.get(Relation, (source_id, target_id, type))
        if existing is None:
            return False
        self.db.delete(existing)
        return True
