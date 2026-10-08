from typing import cast

from sqlalchemy import Table

from database import Database
from models.catalogue import CatalogueDEM
from models.entity import Entity, EntityDEM, Property, PropertyDEM, Relation, RelationDEM


def migrate(db: Database) -> None:
    """Upgrade tables created before the type catalogue existed. Safe to run on every start."""
    catalogue = CatalogueDEM(db)
    # The foreign keys below need every type already in use to be in the catalogue.
    for entity in EntityDEM(db).all():
        catalogue.add_entity_type(entity.type)
    for relation in RelationDEM(db).all():
        catalogue.add_relation_type(relation.type)
    for prop in PropertyDEM(db).all():
        catalogue.add_property_name(prop.name)
    db.ensure_foreign_key(cast(Table, Entity.__table__), "entity_type_fk")
    db.ensure_foreign_key(cast(Table, Relation.__table__), "relation_type_fk")
    db.ensure_foreign_key(cast(Table, Property.__table__), "property_name_fk")
