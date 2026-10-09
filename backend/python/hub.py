from dataclasses import dataclass

from fastapi import WebSocket

from models.user import User
from schemas import JsonDict

UNAUTHORIZED_CLOSE_CODE = 4401


@dataclass
class Presence:
    """A connected user's cursor. Lives only in memory; the look comes from the user's account."""

    id: int
    user_id: int
    session_id: int
    name: str
    color: str
    x: float | None = None
    y: float | None = None
    inside: bool = False  # False while the cursor is outside the editor view

    def to_dict(self) -> JsonDict:
        return {"id": self.id, "name": self.name, "color": self.color, "x": self.x, "y": self.y, "inside": self.inside}


def apply_cursor(presence: Presence, message: JsonDict) -> bool:
    """Update the presence from a client message; return True if it changed."""
    if message.get("event") != "cursor":
        return False
    x, y = message.get("x"), message.get("y")
    presence.inside = bool(message.get("inside"))
    if presence.inside and isinstance(x, (int, float)) and isinstance(y, (int, float)):
        presence.x, presence.y = float(x), float(y)
    return True


class Hub:
    """Pushes every change to all connected clients and relays their cursors."""

    def __init__(self):
        self.clients: dict[WebSocket, Presence] = {}
        self._next_id = 1

    async def connect(self, ws: WebSocket, user: User, session_id: int) -> Presence:
        await ws.accept()
        presence = Presence(self._next_id, user.id, session_id, user.display_name, user.cursor_color)
        self._next_id += 1
        others = [p.to_dict() for p in self.clients.values()]
        self.clients[ws] = presence
        await ws.send_json({"event": "presence.snapshot", "users": others})
        await self.broadcast({"event": "presence.update", "user": presence.to_dict()}, exclude=ws)
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

    async def update_profile(self, user: User) -> None:
        """Show the user's new name and colour on every cursor they have open."""
        for presence in self.clients.values():
            if presence.user_id == user.id:
                presence.name, presence.color = user.display_name, user.cursor_color
                await self.broadcast({"event": "presence.update", "user": presence.to_dict()})

    async def close_sessions(self, session_ids: list[int]) -> None:
        """Cut the live connections of revoked sessions."""
        for ws, presence in list(self.clients.items()):
            if presence.session_id in session_ids:
                self.disconnect(ws)
                try:
                    await ws.close(code=UNAUTHORIZED_CLOSE_CODE)
                except Exception:
                    pass
                await self.broadcast({"event": "presence.left", "id": presence.id})
