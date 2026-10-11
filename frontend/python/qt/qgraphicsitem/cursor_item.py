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


class CursorItem(QGraphicsItem):
    """A user's cursor: a flat-coloured pointer with a name tag, constant size on screen."""

    CURSOR_SCALE = 1.0
    _ARROW_POINTS: list[tuple[float, float]] = [(0, 0), (0, 17), (4.5, 13), (8.5, 21), (11.5, 19.5), (7.5, 12), (13, 12)]

    def __init__(self, name: str, color: str):
        super().__init__()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setZValue(1000)
        self._show_name = True
        self.placed = False  # set once the first position is known
        self._font = QFont()
        self._arrow = QPolygonF([QPointF(x * self.CURSOR_SCALE, y * self.CURSOR_SCALE) for x, y in self._ARROW_POINTS])
        self.set_profile(name, color)

    def set_name_visible(self, visible: bool) -> None:
        self.prepareGeometryChange()
        self._show_name = visible
        self.update()

    def set_profile(self, name: str, color: str) -> None:
        self.prepareGeometryChange()
        self.user_name = name
        self.user_color = QColor(color)
        self._body_brush = QBrush(self.user_color)
        text_color = QColor("black") if self.user_color.lightness() > 150 else QColor("white")
        self._pen = QPen(text_color, 1)
        metrics = QFontMetricsF(self._font)
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
        """Paint the cursor and its name tag."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(self._pen)
        painter.setBrush(self._body_brush)
        painter.drawPolygon(self._arrow)

        if self.user_name and self._show_name:
            painter.drawRoundedRect(self._label, 4, 4)
            painter.drawText(self._label, Qt.AlignmentFlag.AlignCenter, self.user_name)