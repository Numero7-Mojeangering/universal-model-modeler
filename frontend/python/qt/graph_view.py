from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QMouseEvent,
    QPainter,
    QPainterPath,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsView,
    QRubberBand,
)
from shiboken6 import isValid

from .overlay import ViewOverlay
from .scene import GraphScene

from .config import MIN_ZOOM, MAX_ZOOM

class GraphView(QGraphicsView):
    """Wheel zooms, middle drag pans, left or right drag box-selects, right click opens the menu."""

    cursor_moved = Signal(float, float)  # scene position of the mouse
    cursor_left = Signal()
    overlay: ViewOverlay | None = None  # class level: Qt sends events before __init__ finishes

    def __init__(self, scene: GraphScene):
        super().__init__(scene)
        self.graph_scene = scene
        self.setMouseTracking(True)
        self.viewport().setCursor(Qt.CursorShape.BlankCursor)  # the scene draws our own cursor
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        # Partial updates left trails behind moving items.
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        # Zoom is anchored by hand: the built-in anchor needs mouse tracking.
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self._pan_from: QPoint | None = None
        self._right_from: QPoint | None = None
        self._right_dragging = False
        self._fitting = False
        self._band = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
        self.horizontalScrollBar().valueChanged.connect(self._on_scroll)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    def attach_overlay(self, overlay: ViewOverlay) -> None:
        """Floating controls over the view; the custom cursor hides while the mouse is on them."""
        self.overlay = overlay
        overlay.entered.connect(self._on_overlay_entered)
        overlay.show()
        overlay.reposition()

    def _on_overlay_entered(self) -> None:
        self.graph_scene.local_cursor.setVisible(False)
        self.cursor_left.emit()

    def viewportEvent(self, event: QEvent) -> bool:
        if self.overlay is not None and event.type() == QEvent.Type.Resize:
            self.overlay.reposition()
        return super().viewportEvent(event)

    def _visible_rect(self) -> QRectF:
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def fit_scene_rect(self) -> None:
        """Keep the scene only one view larger than content and view, so scrollbars stay precise."""
        if self._fitting or not isValid(self.graph_scene):
            return
        visible = self._visible_rect()
        rect = self.graph_scene.content_rect().united(visible)
        pad = max(visible.width(), visible.height())
        self._fitting = True
        self.graph_scene.setSceneRect(rect.adjusted(-pad, -pad, pad, pad))
        self.centerOn(visible.center())
        self._fitting = False

    def _on_scroll(self) -> None:
        if self._fitting:
            return
        visible = self._visible_rect()
        margin = max(visible.width(), visible.height()) / 4
        if not self.sceneRect().adjusted(margin, margin, -margin, -margin).contains(visible):
            self.fit_scene_rect()  # panned near the edge: extend the scene

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.fit_scene_rect()

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 ** (event.angleDelta().y() / 120)
        current = self.transform().m11()
        factor = max(MIN_ZOOM / current, min(MAX_ZOOM / current, factor))
        anchor = event.position().toPoint()
        before = self.mapToScene(anchor)
        self.scale(factor, factor)
        after = self.mapToScene(anchor)
        self.translate(after.x() - before.x(), after.y() - before.y())
        self.fit_scene_rect()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_from = event.pos()
            return
        if event.button() == Qt.MouseButton.RightButton:
            if not bool(event.buttons() & Qt.MouseButton.LeftButton):  # else a left drag is in progress
                self._right_from = event.pos()
                self._right_dragging = False
            event.accept()
            return
        if self._right_from is not None:  # a right drag is in progress
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        scene_pos = self.mapToScene(event.pos())
        self.graph_scene.local_cursor.setPos(scene_pos)
        self.graph_scene.local_cursor.setVisible(True)
        self.cursor_moved.emit(scene_pos.x(), scene_pos.y())
        if self._pan_from is not None:
            delta = event.pos() - self._pan_from
            self._pan_from = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            return
        if self._right_from is not None:
            moved = (event.pos() - self._right_from).manhattanLength()
            if not self._right_dragging and moved >= QApplication.startDragDistance():
                self._right_dragging = True
                self._band.show()
            if self._right_dragging:
                self._band.setGeometry(QRect(self._right_from, event.pos()).normalized())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_from = None
            return
        if event.button() == Qt.MouseButton.RightButton and self._right_from is None:
            event.accept()  # ignored press, so it must not end the left drag
            return
        if event.button() == Qt.MouseButton.RightButton and self._right_from is not None:
            start, self._right_from = self._right_from, None
            if self._right_dragging:
                self._right_dragging = False
                self._band.hide()
                self._select_rect(QRect(start, event.pos()).normalized(), event)
            else:
                self.graph_scene.open_context(self.mapToScene(event.pos()), event.globalPosition().toPoint())
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.graph_scene.local_cursor.setVisible(False)
        self.cursor_left.emit()
        super().leaveEvent(event)

    def _select_rect(self, rect: QRect, event: QMouseEvent) -> None:
        path = QPainterPath()
        path.addPolygon(self.mapToScene(rect))
        add = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        operation = Qt.ItemSelectionOperation.AddToSelection if add else Qt.ItemSelectionOperation.ReplaceSelection
        self.graph_scene.setSelectionArea(
            path, operation, Qt.ItemSelectionMode.IntersectsItemShape, self.viewportTransform()
        )
