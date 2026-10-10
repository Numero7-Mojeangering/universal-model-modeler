from typing import Any

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
    QComboBox,
    QFormLayout,
    QGraphicsView,
    QHBoxLayout,
    QPushButton,
    QRubberBand,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from data import EntityInfo, TypeInfo
from .overlay import ViewOverlay
from .scene import SHAPES, GraphScene

from .common import InspectorKey
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


class Inspector(QWidget):
    """Edits the type, its style and the properties of the selected entity."""

    type_edited = Signal(int, str)
    shape_edited = Signal(str, str)  # type, shape
    color_requested = Signal(str)  # type
    property_value_edited = Signal(int, str, str)  # entity id, name, value
    property_rename_requested = Signal(str, str)  # old name, new name (applies to every entity)
    property_added = Signal(int)
    property_removed = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.entity_id: int | None = None
        self._key: InspectorKey | None = None
        self._type = ""
        self._loading = False

        self.type_box = QComboBox()
        self.type_box.setEditable(True)
        self.type_box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.shape_box = QComboBox()
        self.shape_box.addItems(SHAPES)
        self.color_button = QPushButton("Color")
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Type", "Value"])
        self.table.horizontalHeader().setStretchLastSection(True)
        add_button, remove_button = QPushButton("Add property"), QPushButton("Remove property")

        form = QFormLayout()
        form.addRow("Type", self.type_box)
        form.addRow("Shape", self.shape_box)
        form.addRow("Color", self.color_button)
        buttons = QHBoxLayout()
        buttons.addWidget(add_button)
        buttons.addWidget(remove_button)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.table)
        layout.addLayout(buttons)

        self.type_box.activated.connect(self._type_done)
        type_line = self.type_box.lineEdit()
        if type_line is not None:
            type_line.editingFinished.connect(self._type_done)
        self.shape_box.activated.connect(self._shape_done)
        self.color_button.clicked.connect(self._color_clicked)
        self.table.cellChanged.connect(self._cell_changed)
        add_button.clicked.connect(self._add_clicked)
        remove_button.clicked.connect(self._remove_clicked)
        self.show_entity(None, None)

    @staticmethod
    def _key_of(info: EntityInfo, style: TypeInfo) -> InspectorKey:
        return (info["type"], style["shape"], style["color"], tuple(info["properties"].items()))

    def show_entity(self, info: EntityInfo | None, style: TypeInfo | None) -> None:
        self._loading = True
        self.entity_id = info["id"] if info else None
        self.setEnabled(info is not None)
        self.table.setRowCount(0)
        self._type = info["type"] if info else ""
        self.type_box.setCurrentText(self._type)
        self.shape_box.setCurrentText(style["shape"] if style else "box")
        self.color_button.setStyleSheet(f"background-color: {style['color']}" if style else "")
        self._key = self._key_of(info, style) if info and style else None
        if info:
            self.table.setRowCount(len(info["properties"]))
            for row, (name, value) in enumerate(info["properties"].items()):
                name_item = QTableWidgetItem(name)
                name_item.setData(Qt.ItemDataRole.UserRole, name)
                self.table.setItem(row, 0, name_item)
                self.table.setItem(row, 1, QTableWidgetItem(value or ""))
        self._loading = False

    def update_entity(self, info: EntityInfo, style: TypeInfo) -> None:
        """Refresh from a live update, only when something visible here changed."""
        if info["id"] == self.entity_id and self._key_of(info, style) != self._key:
            self.show_entity(info, style)

    def set_types(self, types: list[str]) -> None:
        """Fill the type dropdown with the types that already exist."""
        current = self.type_box.currentText()
        self.type_box.clear()
        self.type_box.addItems(types)
        self.type_box.setCurrentText(current)

    def _type_done(self, *_: Any) -> None:
        text = self.type_box.currentText().strip()
        if self.entity_id is None or not text or text == self._type:
            self.type_box.setCurrentText(self._type)
            return
        self._type = text
        self.type_edited.emit(self.entity_id, text)

    def _shape_done(self) -> None:
        if self.entity_id is not None:
            self.shape_edited.emit(self._type, self.shape_box.currentText())

    def _color_clicked(self) -> None:
        if self.entity_id is not None:
            self.color_requested.emit(self._type)

    def _cell_changed(self, row: int, column: int) -> None:
        if self._loading or self.entity_id is None:
            return
        name_item, value_item = self.table.item(row, 0), self.table.item(row, 1)
        if name_item is None or value_item is None:
            return
        old = str(name_item.data(Qt.ItemDataRole.UserRole))
        if column == 0:
            new = name_item.text().strip()
            self._loading = True
            name_item.setText(old)  # the live update shows the new name if the rename goes through
            self._loading = False
            if new and new != old:
                self.property_rename_requested.emit(old, new)
        else:
            self.property_value_edited.emit(self.entity_id, old, value_item.text())

    def _add_clicked(self) -> None:
        if self.entity_id is not None:
            self.property_added.emit(self.entity_id)

    def _remove_clicked(self) -> None:
        row = self.table.currentRow()
        name_item = self.table.item(row, 0) if row >= 0 else None
        if self.entity_id is not None and name_item is not None:
            self.property_removed.emit(self.entity_id, name_item.text())
