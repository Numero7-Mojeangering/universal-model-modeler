from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QStyleOptionGraphicsItem,
    QWidget,
)

from data import EntityInfo, TypeInfo

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qt.qgraphicsitem.relation_item import RelationItem
from qt.helper.graphics import GraphicsHelper

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
        self._title_font = QFont()
        self._title_font.setBold(True)
        self._body_font = QFont()
        self._outline_pen = QPen(QColor("#444"), 1.5)
        self._selected_pen = QPen(QColor("#1e6fd9"), 2.5)
        self.update_info(info, style)

    def update_info(self, info: EntityInfo, style: TypeInfo) -> None:
        self.info = info
        self.shape_name = style["shape"]
        self.fill = QColor(style["color"])
        self._fill_brush = QBrush(self.fill)
        self._text_pen = QPen(QColor("#222") if self.fill.lightness() > 140 else QColor("white"), 1)
        self.lines = [info["type"]] + [f"{k}: {v if v is not None else ''}" for k, v in info["properties"].items()]
        self.prepareGeometryChange()
        self._measure()
        self.update()
        for relation in self.relations:
            relation.refresh()

    def _measure(self) -> None:
        title_metrics = QFontMetricsF(self._title_font)
        body_metrics = QFontMetricsF(self._body_font)
        self._line_height = body_metrics.height()
        widths = [title_metrics.horizontalAdvance(self.lines[0])]
        widths += [body_metrics.horizontalAdvance(line) for line in self.lines[1:]]
        self._text_w = max(max(widths), 60.0)
        self._text_h = self._line_height * len(self.lines)
        w, h, self._text_cy = GraphicsHelper.outer(self.shape_name, self._text_w, self._text_h)
        self._size = (w, h)
        self._path = self._build_path(w, h)
        top = self._text_cy - self._text_h / 2
        self._text_lines: list[tuple[QFont, QRectF, Qt.AlignmentFlag, str]] = []
        for i, line in enumerate(self.lines):
            font = self._title_font if i == 0 else self._body_font
            rect = QRectF(-self._text_w / 2, top + i * self._line_height, self._text_w, self._line_height)
            align = Qt.AlignmentFlag.AlignHCenter if i == 0 else Qt.AlignmentFlag.AlignLeft
            self._text_lines.append((font, rect, align | Qt.AlignmentFlag.AlignVCenter, line))

    def _build_path(self, w: float, h: float) -> QPainterPath:
        path = QPainterPath()
        if self.shape_name == "circle":
            path.addEllipse(QRectF(-w / 2, -h / 2, w, h))
            return path
        if self.shape_name == "box":
            path.addRoundedRect(QRectF(-w / 2, -h / 2, w, h), 8, 8)
            return path

        shape_dict: dict[str, list[tuple[float, float]]] = {
            "diamond": [(0, -h / 2), (w / 2, 0), (0, h / 2), (-w / 2, 0)],
            "hexagon": [(-w / 2, 0), (-w / 4, -h / 2), (w / 4, -h / 2), (w / 2, 0), (w / 4, h / 2), (-w / 4, h / 2)],
            "triangle": [(0, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)],
        }

        points: list[tuple[float, float]] = shape_dict[self.shape_name]
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
        painter.setPen(self._selected_pen if self.isSelected() else self._outline_pen)
        painter.setBrush(self._fill_brush)
        painter.drawPath(self._path)
        painter.setPen(self._text_pen)
        for font, rect, flags, line in self._text_lines:
            painter.setFont(font)
            painter.drawText(rect, flags, line)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for relation in self.relations:
                relation.refresh()
        return super().itemChange(change, value)
