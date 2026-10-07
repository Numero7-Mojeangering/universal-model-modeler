from typing import Annotated, Any, Literal

from pydantic import BaseModel, StringConstraints

from models.catalogue import DEFAULT_COLOR
from models.entity import Entity, Property, Relation
from models.layout import EntityLayout

Shape = Literal["box", "circle", "triangle", "hexagon", "diamond"]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
JsonDict = dict[str, Any]


class EntityIn(BaseModel):
    type: str
    x: float = 0.0
    y: float = 0.0
    shape: Shape = "box"  # style used only if the type is new
    color: Color = DEFAULT_COLOR


class EntityPatch(BaseModel):
    type: str
    shape: Shape | None = None  # style used only if the type is new
    color: Color | None = None


class StyleIn(BaseModel):
    shape: Shape
    color: Color


class PropertyIn(BaseModel):
    value: str | None = None


class PropertyCreate(BaseModel):
    name: Name
    value: str | None = None


class RenameIn(BaseModel):
    name: Name


class RelationIn(BaseModel):
    source_id: int
    target_id: int
    type: str


class LayoutIn(BaseModel):
    x: float
    y: float


def entity_dict(entity: Entity, properties: list[Property], layout: EntityLayout | None) -> JsonDict:
    """JSON shape of an entity, shared by the REST responses and the live events."""
    return {
        "id": entity.id,
        "type": entity.type,
        "properties": {p.name: p.value for p in sorted(properties, key=lambda p: p.name)},
        "layout": None if layout is None else {"x": layout.x, "y": layout.y},
    }


def relation_dict(relation: Relation) -> JsonDict:
    return {"source_id": relation.source_id, "target_id": relation.target_id, "type": relation.type}
