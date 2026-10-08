from typing import Any, cast
from urllib.parse import quote

import requests

from data import Catalogue, Graph


class Api:
    """REST calls to the backend. Changes come back to the UI through the WebSocket."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url.rstrip("/")
        self._http = requests.Session()

    @property
    def ws_url(self) -> str:
        return self.base_url.replace("http", "ws", 1) + "/ws"

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._http.request(method, self.base_url + path, timeout=5, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else None

    def graph(self) -> Graph:
        return cast(Graph, self._call("GET", "/graph"))

    def catalogue(self) -> Catalogue:
        return cast(Catalogue, self._call("GET", "/catalogue"))

    def delete_catalogue_entry(self, kind: str, name: str) -> Any:
        """Delete an unused entity type, relation type or property name (kind: entity, relation, property)."""
        return self._call("DELETE", f"/catalogue/{kind}/{quote(name, safe='')}")

    def create_entity(self, type: str, x: float, y: float, shape: str, color: str) -> Any:
        body = {"type": type, "x": x, "y": y, "shape": shape, "color": color}
        return self._call("POST", "/entities", json=body)

    def set_type(self, entity_id: int, type: str, shape: str | None = None, color: str | None = None) -> Any:
        body: dict[str, str] = {"type": type}
        if shape and color:  # style of the type, used only if the type is new
            body.update(shape=shape, color=color)
        return self._call("PATCH", f"/entities/{entity_id}", json=body)

    def delete_entity(self, entity_id: int):
        return self._call("DELETE", f"/entities/{entity_id}")

    def create_property(self, entity_id: int, name: str, value: str) -> Any:
        return self._call("POST", f"/entities/{entity_id}/properties", json={"name": name, "value": value})

    def set_property(self, entity_id: int, name: str, value: str) -> Any:
        return self._call("PUT", f"/entities/{entity_id}/properties/{quote(name, safe='')}", json={"value": value})

    def rename_property(self, old: str, new: str) -> Any:
        """Rename a property name on every entity that has it."""
        return self._call("PUT", f"/property-names/{quote(old, safe='')}", json={"name": new})

    def delete_property(self, entity_id: int, name: str):
        return self._call("DELETE", f"/entities/{entity_id}/properties/{quote(name, safe='')}")

    def set_layout(self, entity_id: int, x: float, y: float) -> Any:
        return self._call("PUT", f"/entities/{entity_id}/layout", json={"x": x, "y": y})

    def set_entity_style(self, type: str, shape: str, color: str) -> Any:
        return self._call("PUT", f"/types/entity/{quote(type, safe='')}/style", json={"shape": shape, "color": color})

    def create_relation(self, source_id: int, target_id: int, type: str):
        return self._call("POST", "/relations", json={"source_id": source_id, "target_id": target_id, "type": type})

    def delete_relation(self, source_id: int, target_id: int, type: str):
        return self._call(
            "DELETE", "/relations", params={"source_id": source_id, "target_id": target_id, "type": type}
        )
