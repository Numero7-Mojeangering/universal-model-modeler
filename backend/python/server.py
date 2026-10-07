import json
import os
import re
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from typing import Any, Literal, cast

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from database import Database
from migrations import migrate
from models.catalogue import DEFAULT_COLOR, DEFAULT_SHAPE, CatalogueDEM
from models.entity import Entity, EntityDEM, Property, PropertyDEM, RelationDEM
from models.layout import LayoutDEM
from schemas import (
    EntityIn,
    EntityPatch,
    JsonDict,
    LayoutIn,
    PropertyCreate,
    PropertyIn,
    RelationIn,
    RenameIn,
    StyleIn,
    entity_dict,
    relation_dict,
)

db = Database(os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:password@localhost:5432/postgres"))
entities = EntityDEM(db)
properties = PropertyDEM(db)
relations = RelationDEM(db)
layouts = LayoutDEM(db)
catalogue = CatalogueDEM(db)


@dataclass
class Presence:
    """A connected user's cursor and look. Lives only in memory."""

    id: int
    name: str = "anonymous"
    color: str = "#888888"
    x: float | None = None
    y: float | None = None
    inside: bool = False  # False while the cursor is outside the editor view

    def to_dict(self) -> JsonDict:
        return asdict(self)


COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")


def apply_presence(presence: Presence, message: JsonDict) -> bool:
    """Update the presence from a client message; return True if it changed."""
    kind = message.get("event")
    if kind == "profile":
        name = str(message.get("name", "")).strip()[:32]
        color = str(message.get("color", ""))
        if name:
            presence.name = name
        if COLOR_PATTERN.fullmatch(color):
            presence.color = color
        return True
    if kind == "cursor":
        x, y = message.get("x"), message.get("y")
        presence.inside = bool(message.get("inside"))
        if presence.inside and isinstance(x, (int, float)) and isinstance(y, (int, float)):
            presence.x, presence.y = float(x), float(y)
        return True
    return False


class Hub:
    """Pushes every change to all connected clients and relays their cursors."""

    def __init__(self):
        self.clients: dict[WebSocket, Presence] = {}
        self._next_id = 1

    async def connect(self, ws: WebSocket) -> Presence:
        await ws.accept()
        presence = Presence(id=self._next_id)
        self._next_id += 1
        others = [p.to_dict() for p in self.clients.values()]
        self.clients[ws] = presence
        await ws.send_json({"event": "presence.snapshot", "users": others})
        return presence

    def disconnect(self, ws: WebSocket) -> Presence | None:
        return self.clients.pop(ws, None)

    async def broadcast(self, event: JsonDict, exclude: WebSocket | None = None) -> None:
        for ws in list(self.clients):
            if ws is exclude:
                continue
            try:
                await ws.send_json(event)
            except Exception:
                self.disconnect(ws)


hub = Hub()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.create_tables()
    migrate(db)
    yield
    db.close()


app = FastAPI(title="umm", lifespan=lifespan)


@app.exception_handler(IntegrityError)
async def integrity_error(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": "Constraint violated (missing entity or duplicate)"}, status_code=409)


def _entity_or_404(entity_id: int) -> Entity:
    entity = entities.get(entity_id)
    if entity is None:
        raise HTTPException(404, "Entity not found")
    return entity


async def _publish_entity(entity_id: int) -> JsonDict:
    """Send the entity's full current state to all clients."""
    data = entity_dict(_entity_or_404(entity_id), properties.of(entity_id), layouts.get(entity_id))
    await hub.broadcast({"event": "entity.upsert", "entity": data})
    return data


def _types() -> JsonDict:
    return {
        "entity_types": [
            {"name": s.type_name, "shape": s.shape, "color": s.color} for s in catalogue.entity_types()
        ],
        "relation_types": catalogue.relation_types(),
        "property_names": catalogue.property_names(),
    }


async def _publish_types(changed: bool) -> None:
    if changed:
        await hub.broadcast({"event": "types.updated", **_types()})


@app.get("/types")
async def get_types() -> JsonDict:
    return _types()


def _usage() -> JsonDict:
    """Every catalogue entry with the number of times it is used."""
    entity_counts = Counter(e.type for e in entities.all())
    relation_counts = Counter(r.type for r in relations.all())
    property_counts = Counter(p.name for p in properties.all())
    return {
        "entity_types": [
            {"name": s.type_name, "shape": s.shape, "color": s.color, "count": entity_counts[s.type_name]}
            for s in catalogue.entity_types()
        ],
        "relation_types": [{"name": n, "count": relation_counts[n]} for n in catalogue.relation_types()],
        "property_names": [{"name": n, "count": property_counts[n]} for n in catalogue.property_names()],
    }


@app.get("/catalogue")
async def get_catalogue() -> JsonDict:
    return _usage()


@app.delete("/catalogue/{kind}/{name:path}", status_code=204)
async def delete_catalogue_entry(kind: Literal["entity", "relation", "property"], name: str) -> None:
    """Delete a type or property name that nothing uses any more."""
    key = {"entity": "entity_types", "relation": "relation_types", "property": "property_names"}[kind]
    entry = next((e for e in _usage()[key] if e["name"] == name), None)
    if entry is None:
        raise HTTPException(404, f"'{name}' is not in the catalogue")
    if entry["count"]:
        raise HTTPException(409, f"'{name}' is still used {entry['count']} time(s); remove those first")
    remove = {
        "entity": catalogue.remove_entity_type,
        "relation": catalogue.remove_relation_type,
        "property": catalogue.remove_property_name,
    }[kind]
    remove(name)
    await _publish_types(True)


@app.put("/types/entity/{name:path}/style")
async def set_entity_style(name: str, body: StyleIn) -> JsonDict:
    if not catalogue.set_entity_style(name, body.shape, body.color):
        raise HTTPException(404, "Entity type not found")
    await _publish_types(True)
    return _types()


@app.get("/graph")
async def get_graph() -> JsonDict:
    props: defaultdict[int, list[Property]] = defaultdict(list)
    for p in properties.all():
        props[p.entity_id].append(p)
    layout_by_id = {layout.entity_id: layout for layout in layouts.all()}
    return {
        "entities": [entity_dict(e, props[e.id], layout_by_id.get(e.id)) for e in entities.all()],
        "relations": [relation_dict(r) for r in relations.all()],
        **_types(),
    }


@app.post("/entities", status_code=201)
async def create_entity(body: EntityIn) -> JsonDict:
    await _publish_types(catalogue.add_entity_type(body.type, body.shape, body.color))
    entity = entities.create(body.type)
    layouts.set(entity.id, body.x, body.y)
    return await _publish_entity(entity.id)


@app.patch("/entities/{entity_id}")
async def edit_entity(entity_id: int, body: EntityPatch) -> JsonDict:
    await _publish_types(
        catalogue.add_entity_type(body.type, body.shape or DEFAULT_SHAPE, body.color or DEFAULT_COLOR)
    )
    entities.set_type(_entity_or_404(entity_id), body.type)
    return await _publish_entity(entity_id)


@app.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(entity_id: int) -> None:
    entities.remove(_entity_or_404(entity_id))
    await hub.broadcast({"event": "entity.deleted", "id": entity_id})


@app.post("/entities/{entity_id}/properties", status_code=201)
async def create_property(entity_id: int, body: PropertyCreate) -> JsonDict:
    _entity_or_404(entity_id)
    if any(p.name == body.name for p in properties.of(entity_id)):
        raise HTTPException(409, f"This entity already has a property named '{body.name}'")
    await _publish_types(catalogue.add_property_name(body.name))
    properties.create(entity_id, body.name, body.value)
    return await _publish_entity(entity_id)


@app.put("/entities/{entity_id}/properties/{name:path}")
async def set_property(entity_id: int, name: str, body: PropertyIn) -> JsonDict:
    _entity_or_404(entity_id)
    if properties.set_value(entity_id, name, body.value) is None:
        raise HTTPException(404, "Property not found")
    return await _publish_entity(entity_id)


@app.put("/property-names/{name:path}")
async def rename_property_name(name: str, body: RenameIn) -> JsonDict:
    """Rename a property name on every entity that uses it."""
    if not catalogue.has_property_name(name):
        raise HTTPException(404, "Property name not found")
    if body.name != name and catalogue.has_property_name(body.name):
        raise HTTPException(409, f"A property named '{body.name}' already exists")
    catalogue.rename_property_name(name, body.name)
    await _publish_types(True)
    for prop in properties.named(body.name):
        await _publish_entity(prop.entity_id)
    return _types()


@app.delete("/entities/{entity_id}/properties/{name:path}")
async def delete_property(entity_id: int, name: str) -> JsonDict:
    _entity_or_404(entity_id)
    if not properties.remove(entity_id, name):
        raise HTTPException(404, "Property not found")
    return await _publish_entity(entity_id)


@app.put("/entities/{entity_id}/layout")
async def set_layout(entity_id: int, body: LayoutIn) -> JsonDict:
    _entity_or_404(entity_id)
    layouts.set(entity_id, body.x, body.y)
    return await _publish_entity(entity_id)


@app.post("/relations", status_code=201)
async def create_relation(body: RelationIn) -> JsonDict:
    await _publish_types(catalogue.add_relation_type(body.type))
    data = relation_dict(relations.create(body.source_id, body.target_id, body.type))
    await hub.broadcast({"event": "relation.created", "relation": data})
    return data


@app.delete("/relations", status_code=204)
async def delete_relation(source_id: int, target_id: int, type: str) -> None:
    if not relations.remove(source_id, target_id, type):
        raise HTTPException(404, "Relation not found")
    await hub.broadcast(
        {"event": "relation.deleted", "relation": {"source_id": source_id, "target_id": target_id, "type": type}}
    )


@app.websocket("/ws")
async def live(ws: WebSocket) -> None:
    presence = await hub.connect(ws)
    try:
        while True:
            text = await ws.receive_text()
            try:
                raw: Any = json.loads(text)
            except ValueError:
                continue
            if isinstance(raw, dict) and apply_presence(presence, cast(JsonDict, raw)):
                await hub.broadcast({"event": "presence.update", "user": presence.to_dict()}, exclude=ws)
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(ws)
        await hub.broadcast({"event": "presence.left", "id": presence.id})


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
