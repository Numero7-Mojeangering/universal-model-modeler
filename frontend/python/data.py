from typing import TypedDict


class LayoutInfo(TypedDict):
    x: float
    y: float


class TypeInfo(TypedDict):
    """An entity type with its style."""

    name: str
    shape: str
    color: str


class EntityInfo(TypedDict):
    id: int
    type: str
    properties: dict[str, str | None]
    layout: LayoutInfo | None


class RelationInfo(TypedDict):
    source_id: int
    target_id: int
    type: str


class PresenceInfo(TypedDict):
    id: int
    name: str
    color: str
    x: float | None
    y: float | None
    inside: bool


class Graph(TypedDict):
    entities: list[EntityInfo]
    relations: list[RelationInfo]
    entity_types: list[TypeInfo]
    relation_types: list[str]
    property_names: list[str]


class UsageInfo(TypedDict):
    """A catalogue entry and how many entities, relations or properties use it."""

    name: str
    count: int


class EntityTypeUsage(TypedDict):
    name: str
    shape: str
    color: str
    count: int


class Catalogue(TypedDict):
    entity_types: list[EntityTypeUsage]
    relation_types: list[UsageInfo]
    property_names: list[UsageInfo]
