import asyncio
import json
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

import services
from auth import authenticate_ws, authenticated, routers
from hub import apply_cursor
from models.catalogue import DEFAULT_COLOR, DEFAULT_SHAPE, CatalogueDEM
from models.entity import Entity, EntityDEM, Property, PropertyDEM, RelationDEM
from models.layout import LayoutDEM
from services import db, hub
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

entities = EntityDEM(db)
properties = PropertyDEM(db)
relations = RelationDEM(db)
layouts = LayoutDEM(db)
catalogue = CatalogueDEM(db)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    services.loop = asyncio.get_running_loop()
    yield
    db.close()


app = FastAPI(title="umm", lifespan=lifespan)
api = APIRouter(dependencies=[Depends(authenticated)])  # everything here needs a signed-in device


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
        "property_types": catalogue.property_types(),
    }


async def _publish_types(changed: bool) -> None:
    if changed:
        await hub.broadcast({"event": "types.updated", **_types()})


@api.get("/types")
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
        "property_types": [{"name": n, "count": property_counts[n]} for n in catalogue.property_types()],
    }


@api.get("/catalogue")
async def get_catalogue() -> JsonDict:
    return _usage()


@api.delete("/catalogue/{kind}/{name:path}", status_code=204)
async def delete_catalogue_entry(kind: Literal["entity", "relation", "property"], name: str) -> None:
    """Delete a type or property type that nothing uses any more."""
    key = {"entity": "entity_types", "relation": "relation_types", "property": "property_types"}[kind]
    entry = next((e for e in _usage()[key] if e["name"] == name), None)
    if entry is None:
        raise HTTPException(404, f"'{name}' is not in the catalogue")
    if entry["count"]:
        raise HTTPException(409, f"'{name}' is still used {entry['count']} time(s); remove those first")
    remove = {
        "entity": catalogue.remove_entity_type,
        "relation": catalogue.remove_relation_type,
        "property": catalogue.remove_property_type,
    }[kind]
    remove(name)
    await _publish_types(True)


@api.put("/types/entity/{name:path}/style")
async def set_entity_style(name: str, body: StyleIn) -> JsonDict:
    if not catalogue.set_entity_style(name, body.shape, body.color):
        raise HTTPException(404, "Entity type not found")
    await _publish_types(True)
    return _types()


@api.get("/graph")
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


@api.post("/entities", status_code=201)
async def create_entity(body: EntityIn) -> JsonDict:
    await _publish_types(catalogue.add_entity_type(body.type, body.shape, body.color))
    entity = entities.create(body.type)
    layouts.set(entity.id, body.x, body.y)
    return await _publish_entity(entity.id)


@api.patch("/entities/{entity_id}")
async def edit_entity(entity_id: int, body: EntityPatch) -> JsonDict:
    await _publish_types(
        catalogue.add_entity_type(body.type, body.shape or DEFAULT_SHAPE, body.color or DEFAULT_COLOR)
    )
    entities.set_type(_entity_or_404(entity_id), body.type)
    return await _publish_entity(entity_id)


@api.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(entity_id: int) -> None:
    entities.remove(_entity_or_404(entity_id))
    await hub.broadcast({"event": "entity.deleted", "id": entity_id})


@api.post("/entities/{entity_id}/properties", status_code=201)
async def create_property(entity_id: int, body: PropertyCreate) -> JsonDict:
    _entity_or_404(entity_id)
    if any(p.name == body.name for p in properties.of(entity_id)):
        raise HTTPException(409, f"This entity already has a property named '{body.name}'")
    await _publish_types(catalogue.add_property_type(body.name))
    properties.create(entity_id, body.name, body.value)
    return await _publish_entity(entity_id)


@api.put("/entities/{entity_id}/properties/{name:path}")
async def set_property(entity_id: int, name: str, body: PropertyIn) -> JsonDict:
    _entity_or_404(entity_id)
    if properties.set_value(entity_id, name, body.value) is None:
        raise HTTPException(404, "Property not found")
    return await _publish_entity(entity_id)


@api.put("/property-types/{name:path}")
async def rename_property_type(name: str, body: RenameIn) -> JsonDict:
    """Rename a property type on every entity that uses it."""
    if not catalogue.has_property_type(name):
        raise HTTPException(404, "Property type not found")
    if body.name != name and catalogue.has_property_type(body.name):
        raise HTTPException(409, f"A property type named '{body.name}' already exists")
    catalogue.rename_property_type(name, body.name)
    await _publish_types(True)
    for prop in properties.named(body.name):
        await _publish_entity(prop.entity_id)
    return _types()


@api.delete("/entities/{entity_id}/properties/{name:path}")
async def delete_property(entity_id: int, name: str) -> JsonDict:
    _entity_or_404(entity_id)
    if not properties.remove(entity_id, name):
        raise HTTPException(404, "Property not found")
    return await _publish_entity(entity_id)


@api.put("/entities/{entity_id}/layout")
async def set_layout(entity_id: int, body: LayoutIn) -> JsonDict:
    _entity_or_404(entity_id)
    layouts.set(entity_id, body.x, body.y)
    return await _publish_entity(entity_id)


@api.post("/relations", status_code=201)
async def create_relation(body: RelationIn) -> JsonDict:
    await _publish_types(catalogue.add_relation_type(body.type))
    data = relation_dict(relations.create(body.source_id, body.target_id, body.type))
    await hub.broadcast({"event": "relation.created", "relation": data})
    return data


@api.delete("/relations", status_code=204)
async def delete_relation(source_id: int, target_id: int, type: str) -> None:
    if not relations.remove(source_id, target_id, type):
        raise HTTPException(404, "Relation not found")
    await hub.broadcast(
        {"event": "relation.deleted", "relation": {"source_id": source_id, "target_id": target_id, "type": type}}
    )


@app.get("/health")
async def health() -> JsonDict:
    return {"status": "ok"}


@app.websocket("/ws")
async def live(ws: WebSocket) -> None:
    auth = await authenticate_ws(ws)
    if auth is None:
        return
    presence = await hub.connect(ws, auth.user, auth.session.id)
    try:
        while True:
            text = await ws.receive_text()
            try:
                raw: Any = json.loads(text)
            except ValueError:
                continue
            if isinstance(raw, dict) and apply_cursor(presence, cast(JsonDict, raw)):
                await hub.broadcast({"event": "presence.update", "user": presence.to_dict()}, exclude=ws)
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(ws)
        await hub.broadcast({"event": "presence.left", "id": presence.id})


app.include_router(api)
for router in routers:
    app.include_router(router)
