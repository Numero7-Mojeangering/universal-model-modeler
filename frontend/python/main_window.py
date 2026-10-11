import json
import random
from typing import Any, Callable

import requests
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFormLayout,
    QGraphicsItem,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRubberBand,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from api import Api
from catalogue_dialog import CatalogueDialog
from data import EntityInfo, TypeInfo
from icons import icon
from overlay import ViewOverlay
from scene import SHAPES, EntityItem, GraphScene, RelationItem

InspectorKey = tuple[str, str, str, tuple[tuple[str, str | None], ...]]
MIN_ZOOM, MAX_ZOOM = 0.05, 5.0
PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#008080", "#9a6324", "#e0457b"]


def _load_profile() -> tuple[str, str]:
    """The user's cursor name and colour, remembered between runs."""
    settings = QSettings("umm", "client")
    name = str(settings.value("name", "")) or f"user-{random.randint(1000, 9999)}"
    color = str(settings.value("color", ""))
    if not QColor(color).isValid():
        color = random.choice(PALETTE)
    return name, color


def _save_profile(name: str, color: str) -> None:
    settings = QSettings("umm", "client")
    settings.setValue("name", name)
    settings.setValue("color", color)


def _do(fn: Callable[..., object], *args: object) -> Callable[..., None]:
    """Slot that ignores the 'checked' argument Qt passes to triggered signals."""

    def slot(*_: object) -> None:
        fn(*args)

    return slot


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
        self.table.setHorizontalHeaderLabels(["Name", "Value"])
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


class ProfileDialog(QDialog):
    """Edit the cursor name and colour in one popup; change either or both."""

    def __init__(self, parent: QWidget, name: str, color: str):
        super().__init__(parent)
        self.setWindowTitle("Profile")
        self.color = color
        self.name_edit = QLineEdit(name)
        self.name_edit.setMaxLength(32)
        self.color_button = QPushButton()
        self.color_button.clicked.connect(self._pick_color)
        self._show_color()
        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Color", self.color_button)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(self.color), self, "Cursor color")
        if chosen.isValid():
            self.color = chosen.name()
            self._show_color()

    def _show_color(self) -> None:
        text_color = "black" if QColor(self.color).lightness() > 150 else "white"
        self.color_button.setText(self.color)
        self.color_button.setStyleSheet(f"background-color: {self.color}; color: {text_color}")


class MainWindow(QMainWindow):
    def __init__(self, api: Api):
        super().__init__()
        self.api = api
        self.entity_types: list[TypeInfo] = []
        self.relation_types: list[str] = []
        self.property_names: list[str] = []
        self.setWindowTitle("umm")

        self.graph_scene = GraphScene()
        self.view = GraphView(self.graph_scene)
        self.setCentralWidget(self.view)

        self.profile_name, self.profile_color = _load_profile()
        self.graph_scene.local_cursor.set_profile(self.profile_name, self.profile_color)
        self._cursor_pos: QPointF | None = None
        self._cursor_dirty = False
        self.inspector = Inspector()
        dock = QDockWidget("Inspector", self)
        dock.setWidget(self.inspector)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        self._build_toolbar()
        self._connect_signals()

        self.socket = QWebSocket()
        self.socket.connected.connect(self._on_connected)
        self.socket.disconnected.connect(self._schedule_reconnect)
        self.socket.errorOccurred.connect(self._schedule_reconnect)
        self.socket.textMessageReceived.connect(self._on_message)
        self.reconnect_timer = QTimer(self, singleShot=True, interval=2000)
        self.reconnect_timer.timeout.connect(self._open_socket)
        self.cursor_timer = QTimer(self, interval=33)  # about 30 cursor updates per second
        self.cursor_timer.timeout.connect(self._flush_cursor)
        self.cursor_timer.start()
        self._open_socket()

    def _action(
        self,
        text: str,
        icon_name: str,
        slot: Callable[..., object],
        checkable: bool = False,
        checked: bool = False,
    ) -> QAction:
        action = QAction(icon(icon_name), text, self)
        action.setToolTip(text)
        if checkable:
            action.setCheckable(True)
            action.setChecked(checked)
            action.toggled.connect(slot)
        else:
            action.triggered.connect(_do(slot))
        return action

    def _build_toolbar(self) -> None:
        """Edit actions on the left, Profile on the right; navigation and display live in the view overlay."""
        self.link_action = self._action("Link entities", "link", self._toggle_link_mode, checkable=True)
        add_action = self._action("Add entity", "add", self.add_entity)
        types_action = self._action("Delete types", "delete", self.manage_types)
        types_action.setToolTip("Delete unused entity types, relation types and property names")
        delete_key = self._action("Delete selected", "delete", self.delete_selected)
        delete_key.setShortcut(QKeySequence.StandardKey.Delete)
        self.addAction(delete_key)  # the Delete key still removes the selection; so does the right-click menu

        bar = QToolBar("Tools")
        bar.setMovable(False)
        bar.setIconSize(QSize(28, 28))
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(bar)
        bar.addAction(add_action)
        bar.addAction(self.link_action)
        bar.addSeparator()
        bar.addAction(types_action)  # used less: icon only and smaller
        delete_button = bar.widgetForAction(types_action)
        if isinstance(delete_button, QToolButton):
            delete_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            delete_button.setIconSize(QSize(20, 20))
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        bar.addAction(self._action("Profile", "account_circle", self.edit_profile))

        navigate = [
            self._action("Fit view", "fit_screen", self.fit_view),
            self._action("Refresh", "refresh", self.reload),
        ]
        display = [
            self._action("Grid", "grid_on", self.graph_scene.set_grid_visible, checkable=True, checked=True),
            self._action("User names", "badge", self.graph_scene.set_names_visible, checkable=True, checked=True),
        ]
        self.overlay = ViewOverlay(self.view.viewport(), navigate, display)
        self.view.attach_overlay(self.overlay)

    def _connect_signals(self) -> None:
        scene = self.graph_scene
        scene.entity_moved.connect(self._on_entity_moved)
        scene.link_requested.connect(self._on_link_requested)
        scene.context_requested.connect(self._on_context)
        scene.selectionChanged.connect(self._on_selection)
        self.view.cursor_moved.connect(self._on_cursor_moved)
        self.view.cursor_left.connect(self._on_cursor_left)
        self.inspector.type_edited.connect(self._on_type_edited)
        self.inspector.shape_edited.connect(self._on_shape_edited)
        self.inspector.color_requested.connect(self._pick_color)
        self.inspector.property_value_edited.connect(self._on_property_value_edited)
        self.inspector.property_rename_requested.connect(self._rename_property)
        self.inspector.property_added.connect(self.add_property)
        self.inspector.property_removed.connect(self._on_property_removed)

    def _on_type_edited(self, entity_id: int, text: str) -> None:
        self._set_type(entity_id, text)

    def _on_shape_edited(self, type_: str, shape: str) -> None:
        self._change_style(type_, shape=shape)

    def _on_property_removed(self, entity_id: int, name: str) -> None:
        self._call(self.api.delete_property, entity_id, name)

    def _call(self, fn: Callable[..., Any], *args: Any) -> Any:
        try:
            return fn(*args)
        except requests.RequestException as exc:
            message = str(exc)
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                try:
                    message = str(exc.response.json()["detail"])  # the server explains what was refused
                except (ValueError, KeyError):
                    pass
            self.statusBar().showMessage(f"Request failed: {message}", 6000)
            return None

    # --- live connection -------------------------------------------------

    def _open_socket(self) -> None:
        if self.socket.state() == QAbstractSocket.SocketState.UnconnectedState:
            self.statusBar().showMessage("Connecting...")
            self.socket.open(QUrl(self.api.ws_url))

    def _schedule_reconnect(self, *_: Any) -> None:
        self.graph_scene.clear_remote_cursors()
        self.statusBar().showMessage("Disconnected, retrying...")
        self.reconnect_timer.start()

    def _on_connected(self) -> None:
        self.statusBar().showMessage("Live", 3000)
        self._send_profile()
        self.reload()

    def _send(self, message: dict[str, Any]) -> None:
        if self.socket.state() == QAbstractSocket.SocketState.ConnectedState:
            self.socket.sendTextMessage(json.dumps(message))

    def _send_profile(self) -> None:
        self._send({"event": "profile", "name": self.profile_name, "color": self.profile_color})

    def _on_cursor_moved(self, x: float, y: float) -> None:
        self._cursor_pos = QPointF(x, y)
        self._cursor_dirty = True

    def _flush_cursor(self) -> None:
        if self._cursor_dirty and self._cursor_pos is not None:
            self._cursor_dirty = False
            self._send({"event": "cursor", "x": self._cursor_pos.x(), "y": self._cursor_pos.y(), "inside": True})

    def _on_cursor_left(self) -> None:
        self._cursor_dirty = False
        self._send({"event": "cursor", "inside": False})

    def edit_profile(self) -> None:
        dialog = ProfileDialog(self, self.profile_name, self.profile_color)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.name_edit.text().strip()
        if name:
            self.profile_name = name
        self.profile_color = dialog.color
        _save_profile(self.profile_name, self.profile_color)
        self.graph_scene.local_cursor.set_profile(self.profile_name, self.profile_color)
        self._send_profile()

    def reload(self) -> None:
        graph = self._call(self.api.graph)
        if graph is not None:
            self.entity_types = graph["entity_types"]
            self.relation_types = graph["relation_types"]
            self.property_names = graph["property_names"]
            self.graph_scene.set_styles(self.entity_types)
            self.graph_scene.reset(graph)
            self.inspector.show_entity(None, None)
            self._refresh_types()
            self.view.fit_scene_rect()

    def _refresh_types(self) -> None:
        self.inspector.set_types(self._type_names())

    def _type_names(self) -> list[str]:
        return [t["name"] for t in self.entity_types]

    def _on_message(self, text: str) -> None:
        message = json.loads(text)
        event = message["event"]
        scene = self.graph_scene
        if event.startswith("presence."):
            self._on_presence(event, message)
            return
        if event == "entity.upsert":
            scene.upsert_entity(message["entity"])
            info: EntityInfo = message["entity"]
            self.inspector.update_entity(info, scene.style_of(info["type"]))
            self.view.fit_scene_rect()
        elif event == "entity.deleted":
            scene.remove_entity(message["id"])
            if self.inspector.entity_id == message["id"]:
                self.inspector.show_entity(None, None)
        elif event == "relation.created":
            scene.add_relation(message["relation"])
        elif event == "relation.deleted":
            scene.remove_relation(message["relation"])
        elif event == "types.updated":
            self.entity_types = message["entity_types"]
            self.relation_types = message["relation_types"]
            self.property_names = message["property_names"]
            scene.set_styles(self.entity_types)
            self._refresh_inspector()
        self._refresh_types()

    def _on_presence(self, event: str, message: dict[str, Any]) -> None:
        scene = self.graph_scene
        if event == "presence.snapshot":
            scene.clear_remote_cursors()
            for user in message["users"]:
                scene.update_remote_cursor(user)
        elif event == "presence.update":
            scene.update_remote_cursor(message["user"])
        elif event == "presence.left":
            scene.remove_remote_cursor(message["id"])

    # --- user actions ----------------------------------------------------

    def _ask_type(
        self,
        title: str,
        existing: list[str],
        current: str = "",
        label: str = "Choose an existing type or type a new one:",
    ) -> str | None:
        """Pick a name from a catalogue, or type a new one."""
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setComboBoxItems(existing)
        dialog.setComboBoxEditable(True)
        dialog.setTextValue(current)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.textValue().strip() or None

    def add_entity(self, pos: QPointF | None = None) -> None:
        type_ = self._ask_type("Add entity", self._type_names())
        if type_ is None:
            return
        style = self._style_for(type_)
        if style is None:
            return
        pos = pos or self.view.mapToScene(self.view.viewport().rect().center())
        self._call(self.api.create_entity, type_, pos.x(), pos.y(), *style)

    def _style_for(self, type_: str) -> tuple[str, str] | None:
        """Style of a known type; for a new type, ask the user to define it."""
        known = self.graph_scene.styles.get(type_)
        if known is not None:
            return known["shape"], known["color"]
        shape, ok = QInputDialog.getItem(self, "New type", f"Shape for '{type_}':", SHAPES, 0, False)
        if not ok:
            return None
        color = QColorDialog.getColor(QColor("#fffbe6"), self, f"Color for '{type_}'")
        if not color.isValid():
            return None
        return shape, color.name()

    def _set_type(self, entity_id: int, type_: str) -> None:
        style = self._style_for(type_)
        if style is None:
            self._on_selection()  # put the inspector back to the real type
            return
        self._call(self.api.set_type, entity_id, type_, *style)

    def _change_style(self, type_: str, shape: str | None = None, color: str | None = None) -> None:
        current = self.graph_scene.style_of(type_)
        self._call(self.api.set_entity_style, type_, shape or current["shape"], color or current["color"])

    def _pick_color(self, type_: str) -> None:
        color = QColorDialog.getColor(QColor(self.graph_scene.style_of(type_)["color"]), self, f"Color for '{type_}'")
        if color.isValid():
            self._change_style(type_, color=color.name())

    def add_property(self, entity_id: int) -> None:
        item = self.graph_scene.entities.get(entity_id)
        if item is None:
            return
        taken = item.info["properties"]
        name = self._ask_type(
            "Add property",
            [n for n in self.property_names if n not in taken],
            label="Choose an existing property name or type a new one:",
        )
        if name is None:
            return
        if name in taken:
            QMessageBox.warning(self, "Add property", f"This entity already has a property named '{name}'.")
            return
        value, ok = QInputDialog.getText(self, "Add property", f"Value of '{name}':")
        if ok:
            self._call(self.api.create_property, entity_id, name, value)

    def _on_property_value_edited(self, entity_id: int, name: str, value: str) -> None:
        self._call(self.api.set_property, entity_id, name, value)

    def _rename_property(self, old: str, new: str) -> None:
        if new in self.property_names:
            QMessageBox.warning(self, "Rename property", f"A property named '{new}' already exists.")
            return
        answer = QMessageBox.question(
            self, "Rename property", f"Rename '{old}' to '{new}' on every entity that has it?"
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._call(self.api.rename_property, old, new)

    def _edit_type(self, entity_id: int) -> None:
        current = self.graph_scene.entities[entity_id].info["type"]
        text = self._ask_type("Edit type", self._type_names(), current)
        if text:
            self._set_type(entity_id, text)

    def _on_entity_moved(self, entity_id: int, x: float, y: float) -> None:
        if entity_id in self.graph_scene.entities:
            self._call(self.api.set_layout, entity_id, x, y)
            self.view.fit_scene_rect()

    def _toggle_link_mode(self, on: bool) -> None:
        self.graph_scene.set_link_mode(on)
        self.statusBar().showMessage("Click the source entity, then the target entity" if on else "", 0)

    def _on_link_requested(self, source_id: int, target_id: int) -> None:
        type_ = self._ask_type("Link entities", self.relation_types)
        if type_:
            self._call(self.api.create_relation, source_id, target_id, type_)
        self.link_action.setChecked(False)

    def delete_selected(self) -> None:
        items = self.graph_scene.selectedItems()
        entities = [i for i in items if isinstance(i, EntityItem)]
        relations = [i for i in items if isinstance(i, RelationItem)]
        if entities:
            answer = QMessageBox.question(
                self, "Delete", f"Delete {len(entities)} entity(ies) and all their relations?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        removed = {e.entity_id for e in entities}
        for entity_id in removed:
            self._call(self.api.delete_entity, entity_id)
        for relation in relations:
            if relation.info["source_id"] not in removed and relation.info["target_id"] not in removed:
                self._call(self.api.delete_relation, *relation.key)

    def manage_types(self) -> None:
        CatalogueDialog(self, self.api).exec()

    def fit_view(self) -> None:
        rect = self.graph_scene.content_rect()
        if not rect.isEmpty():
            self.view.fitInView(rect.adjusted(-40, -40, 40, 40), Qt.AspectRatioMode.KeepAspectRatio)
            self.view.fit_scene_rect()

    def _on_selection(self) -> None:
        selected = [i for i in self.graph_scene.selectedItems() if isinstance(i, EntityItem)]
        info = selected[0].info if len(selected) == 1 else None
        self.inspector.show_entity(info, self.graph_scene.style_of(info["type"]) if info else None)

    def _refresh_inspector(self) -> None:
        item = self.graph_scene.entities.get(self.inspector.entity_id) if self.inspector.entity_id else None
        if item is not None:
            self.inspector.update_entity(item.info, self.graph_scene.style_of(item.info["type"]))

    def _on_context(self, item: QGraphicsItem | None, global_pos: QPoint, scene_pos: QPointF) -> None:
        menu = QMenu(self)
        if isinstance(item, EntityItem):
            menu.addAction("Edit type...", _do(self._edit_type, item.entity_id))
            menu.addAction("Add property...", _do(self.add_property, item.entity_id))
            shapes = menu.addMenu("Type shape")
            for shape in SHAPES:
                shapes.addAction(shape, _do(self._change_style, item.info["type"], shape))
            menu.addAction("Type color...", _do(self._pick_color, item.info["type"]))
            menu.addSeparator()
            menu.addAction("Delete entity", _do(self.delete_selected))
        elif isinstance(item, RelationItem):
            menu.addAction("Delete relation", _do(self.delete_selected))
        else:
            menu.addAction("Add entity here...", _do(self.add_entity, scene_pos))
        menu.exec(global_pos)
