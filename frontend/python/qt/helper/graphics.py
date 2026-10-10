
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QGraphicsItem

import math

class GraphicsHelper:
    """Helper class for graphics-related calculations."""

    SHAPES = ["box", "circle", "triangle", "hexagon", "diamond"]
    PAD = 12

    @staticmethod
    def outer(shape: str, tw: float, th: float) -> tuple[float, float, float]:
        """Return (width, height, text centre y) of a shape that fits a text block."""
        if shape == "circle":
            d = math.hypot(tw, th) + GraphicsHelper.PAD
            return d, d, 0
        if shape == "diamond":
            return 2 * (tw + GraphicsHelper.PAD), 2 * (th + GraphicsHelper.PAD), 0
        if shape == "hexagon":
            return 1.8 * tw + 4 * GraphicsHelper.PAD, th + 2 * GraphicsHelper.PAD, 0
        if shape == "triangle":
            h = 2 * th + 2 * GraphicsHelper.PAD
            return 2 * tw + 2 * GraphicsHelper.PAD, h, h / 2 - 8 - th / 2
        return tw + 2 * GraphicsHelper.PAD, th + 2 * GraphicsHelper.PAD, 0


    @staticmethod
    def edge(item: QGraphicsItem, direction: QPointF) -> QPointF:
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