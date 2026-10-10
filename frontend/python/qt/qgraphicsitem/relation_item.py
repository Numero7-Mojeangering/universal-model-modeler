from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
    QTextOption
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QStyleOptionGraphicsItem,
    QWidget,
)

from data import RelationInfo

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .entity_item import EntityItem
from qt.helper.graphics import GraphicsHelper

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
            start = GraphicsHelper.edge(self.source, QPointF(1, -1))
            end = GraphicsHelper.edge(self.source, QPointF(-1, -1))
            c1, c2 = start + QPointF(40, -80), end + QPointF(-40, -80)
            path.moveTo(start)
            path.cubicTo(c1, c2, end)
            heading = end - c2
        else:
            start = GraphicsHelper.edge(self.source, self.target.pos() - self.source.pos())
            end = GraphicsHelper.edge(self.target, self.source.pos() - self.target.pos())
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
