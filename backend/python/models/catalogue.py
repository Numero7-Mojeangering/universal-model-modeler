from sqlalchemy import ForeignKey, Text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, Database


class EntityType(Base):
    """Catalogue of the entity types that exist; kept even when no entity uses one."""

    __tablename__ = "entity_type"

    name: Mapped[str] = mapped_column(Text, primary_key=True)


class RelationType(Base):
    """Catalogue of the relation types that exist."""

    __tablename__ = "relation_type"

    name: Mapped[str] = mapped_column(Text, primary_key=True)


class PropertyType(Base):
    """Catalogue of the property types; renaming one renames it on every entity."""

    __tablename__ = "property_type"

    name: Mapped[str] = mapped_column(Text, primary_key=True)


NameRow = EntityType | RelationType | PropertyType


DEFAULT_SHAPE = "box"
DEFAULT_COLOR = "#fffbe6"


class EntityStyle(Base):
    """How entities of a type are drawn: shape and flat colour."""

    __tablename__ = "entity_style"

    type_name: Mapped[str] = mapped_column(
        Text, ForeignKey("entity_type.name", ondelete="CASCADE", onupdate="CASCADE"), primary_key=True
    )
    shape: Mapped[str] = mapped_column(Text)
    color: Mapped[str] = mapped_column(Text)


class CatalogueDEM:
    """Data Expert Manipulator for the type catalogues."""

    def __init__(self, db: Database):
        self.db = db

    def entity_types(self) -> list[EntityStyle]:
        """Every entity type with its style (the default style if none was saved)."""
        styles = {s.type_name: s for s in self.db.get_all(EntityStyle)}
        names = sorted(t.name for t in self.db.get_all(EntityType))
        return [styles.get(n) or EntityStyle(type_name=n, shape=DEFAULT_SHAPE, color=DEFAULT_COLOR) for n in names]

    def relation_types(self) -> list[str]:
        return sorted(t.name for t in self.db.get_all(RelationType))

    def add_entity_type(self, name: str, shape: str = DEFAULT_SHAPE, color: str = DEFAULT_COLOR) -> bool:
        """Register the type with its style; an existing type keeps its style. True if anything was created."""
        created = self._add(EntityType, EntityType(name=name), name)
        if self.db.get(EntityStyle, name) is None:
            try:
                self.db.add(EntityStyle(type_name=name, shape=shape, color=color))
                created = True
            except IntegrityError:
                pass
        return created

    def set_entity_style(self, name: str, shape: str, color: str) -> bool:
        """Change the style of an existing type; False if the type is unknown."""
        if self.db.get(EntityType, name) is None:
            return False
        style = self.db.get(EntityStyle, name)
        if style is None:
            self.db.add(EntityStyle(type_name=name, shape=shape, color=color))
        else:
            style.shape, style.color = shape, color
            self.db.update(style)
        return True

    def add_relation_type(self, name: str) -> bool:
        """Register the type; return True only if it was new."""
        return self._add(RelationType, RelationType(name=name), name)

    def property_types(self) -> list[str]:
        return sorted(n.name for n in self.db.get_all(PropertyType))

    def has_property_type(self, name: str) -> bool:
        return self.db.get(PropertyType, name) is not None

    def add_property_type(self, name: str) -> bool:
        """Register the type; return True only if it was new."""
        return self._add(PropertyType, PropertyType(name=name), name)

    def rename_property_type(self, old: str, new: str) -> bool:
        """Rename the type everywhere (the foreign key cascades); False if `old` is unknown."""
        return self.db.rename_key(PropertyType, old, "name", new)

    def remove_entity_type(self, name: str) -> bool:
        """Delete an unused type with its style (cascade); fails while entities use it."""
        return self._remove(EntityType, name)

    def remove_relation_type(self, name: str) -> bool:
        return self._remove(RelationType, name)

    def remove_property_type(self, name: str) -> bool:
        return self._remove(PropertyType, name)

    def _remove(self, model: type[NameRow], name: str) -> bool:
        row = self.db.get(model, name)
        if row is None:
            return False
        self.db.delete(row)
        return True

    def _add(self, model: type[NameRow], row: NameRow, name: str) -> bool:
        if self.db.get(model, name) is not None:
            return False
        try:
            self.db.add(row)
        except IntegrityError:  # registered concurrently by another request
            return False
        return True
