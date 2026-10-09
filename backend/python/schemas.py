from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, StringConstraints

from models.catalogue import DEFAULT_COLOR
from models.entity import Entity, Property, Relation
from models.layout import EntityLayout
from models.user import User

Shape = Literal["box", "circle", "triangle", "hexagon", "diamond"]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
JsonDict = dict[str, Any]
Username = Annotated[
    str,
    BeforeValidator(lambda v: v.strip().lower() if isinstance(v, str) else v),
    StringConstraints(pattern=r"^[a-z0-9_.-]{3,32}$"),
]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
Blob = Annotated[str, StringConstraints(max_length=4096)]  # a base64 protocol message


class StatusRequest(BaseModel):
    username: Username


class LoginStart(BaseModel):
    username: Username
    request: Blob


class LoginFinish(BaseModel):
    login_id: str
    request: Blob
    device_key: Blob  # the device's Ed25519 public key
    device_proof: Blob  # ties that key to this OPAQUE session


class RegisterStart(BaseModel):
    username: Username
    request: Blob


class RegisterFinish(BaseModel):
    username: Username
    request: Blob


class ProfilePatch(BaseModel):
    display_name: DisplayName | None = None
    cursor_color: Color | None = None


class UserCreate(BaseModel):
    username: Username
    display_name: DisplayName | None = None
    is_admin: bool = False


class UserPatch(BaseModel):
    disabled: bool | None = None
    is_admin: bool | None = None


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


def user_dict(user: User) -> JsonDict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "cursor_color": user.cursor_color,
        "is_admin": user.is_admin,
        "disabled": user.disabled,
        "has_password": user.opaque_record is not None,
    }


def relation_dict(relation: Relation) -> JsonDict:
    return {"source_id": relation.source_id, "target_id": relation.target_id, "type": relation.type}
