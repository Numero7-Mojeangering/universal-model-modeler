import math
import time
from typing import Any

from PySide6.QtCore import (
    QLineF,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QTimer,
    Signal
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QTransform,
)
from PySide6.QtWidgets import (
    QGraphicsScene,
    QGraphicsSceneContextMenuEvent,
    QGraphicsSceneMouseEvent,
    QGraphicsItem,
)

from shiboken6 import isValid

from data import EntityInfo, Graph, PresenceInfo, RelationInfo, TypeInfo

from qt.qgraphicsitem.entity_item import EntityItem
from qt.qgraphicsitem.relation_item import RelationItem
from qt.qgraphicsitem.cursor_item import CursorItem

class GraphScene(QGraphicsScene):
    """Holds the entity and relation items and keeps them in sync with the backend data."""

    entity_moved = Signal(int, float, float)
    link_requested = Signal(int, int)
    context_requested = Signal(object, QPoint, QPointF)

    def __init__(self):
        super().__init__()
        self.entities: dict[int, EntityItem] = {}
        self.relations: dict[Any, RelationItem] = {}
        self.cursors: dict[int, CursorItem] = {}
        self._targets: dict[int, QPointF] = {}  # where each remote cursor is gliding to
        self._glide = QTimer(self, interval=16)
        self._glide.timeout.connect(self._glide_step)
        self._glide_last = time.monotonic()
        self.local_cursor = CursorItem("", "#e0457b")
        self.local_cursor.setVisible(False)
        self.addItem(self.local_cursor)
        self.styles: dict[str, TypeInfo] = {}
        self.link_mode = False
        self.grid_visible = True
        self.names_visible = True
        self._link_source: EntityItem | None = None
        self.setSceneRect(-1000, -1000, 2000, 2000)  # the view resizes it to fit the content

    def style_of(self, type_: str) -> TypeInfo:
        return self.styles.get(type_) or {"name": type_, "shape": "box", "color": "#fffbe6"}

    def set_styles(self, types: list[TypeInfo]) -> None:
        """Apply the styles of the type catalogue to every entity."""
        self.styles = {t["name"]: t for t in types}
        for item in self.entities.values():
            item.update_info(item.info, self.style_of(item.info["type"]))

    def set_names_visible(self, visible: bool) -> None:
        self.names_visible = visible
        for item in [self.local_cursor, *self.cursors.values()]:
            item.set_name_visible(visible)

    def set_grid_visible(self, visible: bool) -> None:
        self.grid_visible = visible
        self.invalidate(self.sceneRect(), QGraphicsScene.SceneLayer.BackgroundLayer)

    def drawBackground(self, painter: QPainter, rect: QRectF | QRect) -> None:
        painter.fillRect(rect, QColor("#f4f4f4"))
        if not self.grid_visible:
            return
        scale = abs(painter.worldTransform().m11()) or 1.0
        minor = 50.0
        while minor * scale < 12:  # keep lines at least 12 px apart on screen
            minor *= 5
        first_x, last_x = math.floor(rect.left() / minor), math.ceil(rect.right() / minor)
        first_y, last_y = math.floor(rect.top() / minor), math.ceil(rect.bottom() / minor)
        light, strong = QPen(QColor("#e2e2e2"), 0), QPen(QColor("#c4c4c4"), 0)
        for i in range(first_x, last_x + 1):
            painter.setPen(strong if i % 5 == 0 else light)
            painter.drawLine(QLineF(i * minor, rect.top(), i * minor, rect.bottom()))
        for j in range(first_y, last_y + 1):
            painter.setPen(strong if j % 5 == 0 else light)
            painter.drawLine(QLineF(rect.left(), j * minor, rect.right(), j * minor))
        font = QFont()
        font.setPointSizeF(8 / scale)  # constant size on screen
        painter.setFont(font)
        painter.setPen(QColor("#999"))
        for i in range(first_x, last_x + 1):
            for j in range(first_y, last_y + 1):
                if i % 5 == 0 and j % 5 == 0:
                    painter.drawText(
                        QPointF(i * minor + 3 / scale, j * minor - 3 / scale), f"{int(i * minor)},{int(j * minor)}"
                    )

    def reset(self, graph: Graph) -> None:
        old_items: list[QGraphicsItem] = [*self.relations.values(), *self.entities.values()]
        self.entities.clear()  # emptied first: removing items can trigger view callbacks that read them
        self.relations.clear()
        for item in old_items:
            self.removeItem(item)  # keep the cursor items
        self._link_source = None
        for info in graph["entities"]:
            self.upsert_entity(info)
        for info in graph["relations"]:
            self.add_relation(info)

    def upsert_entity(self, info: EntityInfo) -> None:
        item = self.entities.get(info["id"])
        layout = info["layout"]
        if item is None:
            item = EntityItem(info, self.style_of(info["type"]))
            self.addItem(item)
            self.entities[info["id"]] = item
            if layout:
                item.setPos(layout["x"], layout["y"])
            else:
                item.setPos((info["id"] % 5) * 240, (info["id"] // 5 % 5) * 180)
            item.saved_pos = item.pos()
            return
        item.update_info(info, self.style_of(info["type"]))
        if layout and item is not self.mouseGrabberItem():
            item.setPos(layout["x"], layout["y"])
            item.saved_pos = item.pos()

    def remove_entity(self, entity_id: int) -> None:
        item = self.entities.pop(entity_id, None)
        if item is None:
            return
        for relation in list(item.relations):
            self.remove_relation(relation.info)
        self.removeItem(item)

    def add_relation(self, info: RelationInfo) -> None:
        key = (info["source_id"], info["target_id"], info["type"])
        source, target = self.entities.get(info["source_id"]), self.entities.get(info["target_id"])
        if key in self.relations or source is None or target is None:
            return
        item = RelationItem(info, source, target)
        self.addItem(item)
        self.relations[key] = item

    def remove_relation(self, info: RelationInfo) -> None:
        item = self.relations.pop((info["source_id"], info["target_id"], info["type"]), None)
        if item is not None:
            item.detach()
            self.removeItem(item)

    def content_rect(self) -> QRectF:
        """Bounds of the entities and relations, without the cursors."""
        rect = QRectF()
        l: list[QGraphicsItem] = [*self.entities.values(), *self.relations.values()]
        for item in l:
            if isValid(item):  # on shutdown the scene deletes its items before the view stops asking
                rect = rect.united(item.sceneBoundingRect())
        return rect

    def update_remote_cursor(self, info: PresenceInfo) -> None:
        item = self.cursors.get(info["id"])
        if item is None:
            item = CursorItem(info["name"], info["color"])
            item.set_name_visible(self.names_visible)
            self.addItem(item)
            self.cursors[info["id"]] = item
        else:
            item.set_profile(info["name"], info["color"])
        x, y = info["x"], info["y"]
        item.setVisible(x is not None and y is not None)
        if x is not None and y is not None:
            if item.placed:
                self._targets[info["id"]] = QPointF(x, y)
                if not self._glide.isActive():
                    self._glide_last = time.monotonic()
                    self._glide.start()
            else:
                item.setPos(x, y)
                item.placed = True
        item.setOpacity(1.0 if info["inside"] else 0.5)

    def _glide_step(self) -> None:
        """Move each remote cursor part of the way to its target; smooths the ~30 Hz stream."""
        now = time.monotonic()
        blend = 1 - math.exp(-(now - self._glide_last) / 0.05)  # about 50 ms to close most of the gap
        self._glide_last = now
        for user_id, target in list(self._targets.items()):
            item = self.cursors.get(user_id)
            if item is None:
                del self._targets[user_id]
                continue
            delta = target - item.pos()
            if abs(delta.x()) + abs(delta.y()) < 0.1:
                item.setPos(target)
                del self._targets[user_id]
            else:
                item.setPos(item.pos() + delta * blend)
        if not self._targets:
            self._glide.stop()

    def remove_remote_cursor(self, user_id: int) -> None:
        item = self.cursors.pop(user_id, None)
        self._targets.pop(user_id, None)
        if item is not None:
            self.removeItem(item)

    def clear_remote_cursors(self) -> None:
        for user_id in list(self.cursors):
            self.remove_remote_cursor(user_id)

    def set_link_mode(self, on: bool) -> None:
        self.link_mode = on
        self._link_source = None
        self.clearSelection()

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self.link_mode and event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.scenePos(), QTransform())
            if isinstance(item, EntityItem):
                if self._link_source is None:
                    self._link_source = item
                    item.setSelected(True)
                else:
                    source, self._link_source = self._link_source, None
                    self.clearSelection()
                    self.link_requested.emit(source.entity_id, item.entity_id)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        for item in self.entities.values():
            if item.pos() != item.saved_pos:
                item.saved_pos = item.pos()
                self.entity_moved.emit(item.entity_id, item.x(), item.y())

    def contextMenuEvent(self, event: QGraphicsSceneContextMenuEvent) -> None:
        # The view opens the menu itself, only for a right click that was not a drag.
        event.accept()

    def open_context(self, scene_pos: QPointF, global_pos: QPoint) -> None:
        item = self.itemAt(scene_pos, QTransform())
        if item is not None and not item.isSelected():
            self.clearSelection()
            item.setSelected(True)
        self.context_requested.emit(item, global_pos, scene_pos)
