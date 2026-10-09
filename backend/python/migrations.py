from typing import cast

from sqlalchemy import Table

from database import Database
from models.catalogue import CatalogueDEM
from models.entity import Entity, EntityDEM, Property, PropertyDEM, Relation, RelationDEM
from models.user import User


def migrate_users(db: Database) -> None:
    """Replace the old users table, which had no logins. Run before the tables are created."""
    columns = db.table_columns("users")
    if columns and "username" not in columns:
        db.drop_table(cast(Table, User.__table__))


def migrate_property_types(db: Database) -> None:
    """Rename the property_name catalogue table and its foreign key. Run before the tables are created."""
    if db.table_columns("property_name") and not db.table_columns("property_type"):
        db.rename_table("property_name", "property_type")
    db.rename_foreign_key("property", "property_name_fk", "property_type_fk")


def migrate(db: Database) -> None:
    """Upgrade tables created before the type catalogue existed. Safe to run on every start."""
    catalogue = CatalogueDEM(db)
    # The foreign keys below need every type already in use to be in the catalogue.
    for entity in EntityDEM(db).all():
        catalogue.add_entity_type(entity.type)
    for relation in RelationDEM(db).all():
        catalogue.add_relation_type(relation.type)
    for prop in PropertyDEM(db).all():
        catalogue.add_property_type(prop.name)
    db.ensure_foreign_key(cast(Table, Entity.__table__), "entity_type_fk")
    db.ensure_foreign_key(cast(Table, Relation.__table__), "relation_type_fk")
    db.ensure_foreign_key(cast(Table, Property.__table__), "property_type_fk")
