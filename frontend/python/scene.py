import math
import time
from typing import Any

from PySide6.QtCore import QLineF, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
    QTextOption,
    QTransform,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsSceneContextMenuEvent,
    QGraphicsSceneMouseEvent,
    QStyleOptionGraphicsItem,
    QWidget,
)
from shiboken6 import isValid

from data import EntityInfo, Graph, PresenceInfo, RelationInfo, TypeInfo

SHAPES = ["box", "circle", "triangle", "hexagon", "diamond"]
PAD = 12


def _outer(shape: str, tw: float, th: float) -> tuple[float, float, float]:
    """Return (width, height, text centre y) of a shape that fits a text block."""
    if shape == "circle":
        d = math.hypot(tw, th) + PAD
        return d, d, 0
    if shape == "diamond":
        return 2 * (tw + PAD), 2 * (th + PAD), 0
    if shape == "hexagon":
        return 1.8 * tw + 4 * PAD, th + 2 * PAD, 0
    if shape == "triangle":
        h = 2 * th + 30
        return 2 * tw + 30, h, h / 2 - 8 - th / 2
    return tw + 2 * PAD, th + 2 * PAD, 0


def _edge(item: QGraphicsItem, direction: QPointF) -> QPointF:
    """Scene point where a ray from the item's centre leaves its shape."""
    length = math.hypot(direction.x(), direction.y())
    if length == 0:
        return item.pos()
    d = QPointF(direction.x() / length, direction.y() / length)
    shape = item.shape()
    lo, hi = 0.0, max(item.boundingRect().width(), item.boundingRect().height())
    for _ in range(14):
        mid = (lo + hi) / 2
        if shape.contains(QPointF(d.x() * mid, d.y() * mid)):
            lo = mid
        else:
            hi = mid
    return item.pos() + d * hi


class EntityItem(QGraphicsItem):
    """An entity drawn as a shape with its type and properties inside."""

    def __init__(self, info: EntityInfo, style: TypeInfo):
        super().__init__()
        self.entity_id = info["id"]
        self.relations: list[RelationItem] = []
        self.saved_pos = QPointF()
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setZValue(1)
        self.update_info(info, style)

    def update_info(self, info: EntityInfo, style: TypeInfo) -> None:
        self.info = info
        self.shape_name = style["shape"]
        self.fill = QColor(style["color"])
        self.lines = [info["type"]] + [f"{k}: {v if v is not None else ''}" for k, v in info["properties"].items()]
        self.prepareGeometryChange()
        self._measure()
        self.update()
        for relation in self.relations:
            relation.refresh()

    def _measure(self) -> None:
        title_font = QFont()
        title_font.setBold(True)
        title_metrics = QFontMetricsF(title_font)
        body_metrics = QFontMetricsF(QFont())
        self._line_height = body_metrics.height()
        widths = [title_metrics.horizontalAdvance(self.lines[0])]
        widths += [body_metrics.horizontalAdvance(line) for line in self.lines[1:]]
        self._text_w = max(max(widths), 60.0)
        self._text_h = self._line_height * len(self.lines)
        w, h, self._text_cy = _outer(self.shape_name, self._text_w, self._text_h)
        self._size = (w, h)
        self._path = self._build_path(w, h)

    def _build_path(self, w: float, h: float) -> QPainterPath:
        path = QPainterPath()
        if self.shape_name == "circle":
            path.addEllipse(QRectF(-w / 2, -h / 2, w, h))
            return path
        if self.shape_name == "box":
            path.addRoundedRect(QRectF(-w / 2, -h / 2, w, h), 8, 8)
            return path
        points = {
            "diamond": [(0, -h / 2), (w / 2, 0), (0, h / 2), (-w / 2, 0)],
            "hexagon": [(-w / 2, 0), (-w / 4, -h / 2), (w / 4, -h / 2), (w / 2, 0), (w / 4, h / 2), (-w / 4, h / 2)],
            "triangle": [(0, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)],
        }[self.shape_name]
        path.addPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
        path.closeSubpath()
        return path

    def boundingRect(self) -> QRectF:
        w, h = self._size
        return QRectF(-w / 2 - 6, -h / 2 - 6, w + 12, h + 12)

    def shape(self) -> QPainterPath:
        return self._path

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = self.isSelected()
        painter.setPen(QPen(QColor("#1e6fd9") if selected else QColor("#444"), 2.5 if selected else 1.5))
        painter.setBrush(self.fill)
        painter.drawPath(self._path)
        text_color = QColor("#222") if self.fill.lightness() > 140 else QColor("white")
        top = self._text_cy - self._text_h / 2
        for i, line in enumerate(self.lines):
            font = QFont()
            font.setBold(i == 0)
            painter.setFont(font)
            painter.setPen(text_color)
            rect = QRectF(-self._text_w / 2, top + i * self._line_height, self._text_w, self._line_height)
            align = Qt.AlignmentFlag.AlignHCenter if i == 0 else Qt.AlignmentFlag.AlignLeft
            painter.drawText(rect, line, QTextOption(align | Qt.AlignmentFlag.AlignVCenter))

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for relation in self.relations:
                relation.refresh()
        return super().itemChange(change, value)


class RelationItem(QGraphicsItem):
    """A relation drawn as an arrow from its source entity to its target entity."""

    def __init__(self, info: RelationInfo, source: EntityItem, target: EntityItem):
        super().__init__()
        self.info = info
        self.source = source
        self.target = target
        self._path = QPainterPath()
        self._arrow = QPolygonF()
        self._label_rect = QRectF()
        source.relations.append(self)
        if target is not source:
            target.relations.append(self)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.refresh()

    @property
    def key(self) -> tuple[int, int, str]:
        return (self.info["source_id"], self.info["target_id"], self.info["type"])

    def detach(self) -> None:
        for item in {self.source, self.target}:
            if self in item.relations:
                item.relations.remove(self)

    def refresh(self) -> None:
        self.prepareGeometryChange()
        path = QPainterPath()
        if self.source is self.target:
            start = _edge(self.source, QPointF(1, -1))
            end = _edge(self.source, QPointF(-1, -1))
            c1, c2 = start + QPointF(40, -80), end + QPointF(-40, -80)
            path.moveTo(start)
            path.cubicTo(c1, c2, end)
            heading = end - c2
        else:
            start = _edge(self.source, self.target.pos() - self.source.pos())
            end = _edge(self.target, self.source.pos() - self.target.pos())
            path.moveTo(start)
            path.lineTo(end)
            heading = end - start
        angle = math.atan2(heading.y(), heading.x())
        wing = [end - QPointF(math.cos(angle + s) * 12, math.sin(angle + s) * 12) for s in (-math.pi / 6, math.pi / 6)]
        self._arrow = QPolygonF([end, wing[0], wing[1]])
        self._path = path
        metrics = QFontMetricsF(QFont())
        w, h = metrics.horizontalAdvance(self.info["type"]), metrics.height()
        mid = path.pointAtPercent(0.5)
        self._label_rect = QRectF(mid.x() - w / 2 - 3, mid.y() - h / 2, w + 6, h)
        self.update()

    def boundingRect(self) -> QRectF:
        rect = self._path.boundingRect().united(self._label_rect).united(self._arrow.boundingRect())
        return rect.adjusted(-10, -10, 10, 10)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        clickable = stroker.createStroke(self._path)
        clickable.addRect(self._label_rect)
        return clickable

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = self.isSelected()
        color = QColor("#1e6fd9") if selected else QColor("#555")
        painter.setPen(QPen(color, 2.2 if selected else 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._path)
        painter.setBrush(color)
        painter.drawPolygon(self._arrow)
        painter.setBrush(QColor("#f4f4f4"))
        painter.setPen(QPen(color, 1))
        painter.drawRect(self._label_rect)
        painter.setPen(QColor("#222"))
        painter.drawText(self._label_rect, self.info["type"], QTextOption(Qt.AlignmentFlag.AlignCenter))


class CursorItem(QGraphicsItem):
    """A user's cursor: a flat-coloured pointer with a name tag, constant size on screen."""

    def __init__(self, name: str, color: str):
        super().__init__()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setZValue(1000)
        self._show_name = True
        self.placed = False  # set once the first position is known
        self.set_profile(name, color)

    def set_name_visible(self, visible: bool) -> None:
        self.prepareGeometryChange()
        self._show_name = visible
        self.update()

    def set_profile(self, name: str, color: str) -> None:
        self.prepareGeometryChange()
        self.user_name = name
        self.user_color = QColor(color)
        metrics = QFontMetricsF(QFont())
        self._label = QRectF(14, 16, metrics.horizontalAdvance(name) + 10, metrics.height() + 4)
        self.update()

    def boundingRect(self) -> QRectF:
        if not self._show_name:
            return QRectF(-2, -2, 20, 26)
        return QRectF(-2, -2, max(20.0, self._label.right() + 4), self._label.bottom() + 4)

    def shape(self) -> QPainterPath:
        return QPainterPath()  # never picked by clicks

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        points = [(0, 0), (0, 17), (4.5, 13), (8.5, 21), (11.5, 19.5), (7.5, 12), (13, 12)]
        painter.setPen(QPen(QColor("white"), 1.5))
        painter.setBrush(self.user_color)
        painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
        if not self.user_name or not self._show_name:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self._label, 4, 4)
        painter.setPen(QColor("black") if self.user_color.lightness() > 150 else QColor("white"))
        painter.drawText(self._label, self.user_name, QTextOption(Qt.AlignmentFlag.AlignCenter))


class GraphScene(QGraphicsScene):
    """Holds the entity and relation items and keeps them in sync with the backend data."""

    entity_moved = Signal(int, float, float)
    link_requested = Signal(int, int)
    context_requested = Signal(object, QPoint, QPointF)

    def __init__(self):
        super().__init__()
        self.entities: dict[int, EntityItem] = {}
        self.relations: dict[tuple, RelationItem] = {}
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

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
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
        old_items = [*self.relations.values(), *self.entities.values()]
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
        for item in [*self.entities.values(), *self.relations.values()]:
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
