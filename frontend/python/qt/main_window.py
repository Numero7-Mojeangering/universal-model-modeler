import json
from typing import Any, Callable

import requests
from PySide6.QtCore import QCryptographicHash, QPoint, QPointF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QColor,
    QKeySequence
)
from PySide6.QtNetwork import QAbstractSocket, QNetworkRequest
from PySide6.QtWebSockets import QWebSocket
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDockWidget,
    QGraphicsItem,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QWidget,
)

from qt.helper.slot import slot_ignore_checked

from api import Api, AuthError, describe_error
from data import EntityInfo, TypeInfo

from qt.scene import EntityItem, GraphScene, RelationItem
from qt.helper.graphics import GraphicsHelper
from .icons import icon
from .qwidget.inspector import Inspector
from .graph_view import GraphView
from .overlay import ViewOverlay
from .qdialog.profile_dialog import ProfileDialog
from .qdialog.admin_dialog import UsersDialog
from .qdialog.catalogue_dialog import CatalogueDialog

class MainWindow(QMainWindow):
    def __init__(self, api: Api):
        super().__init__()
        self.api = api
        self.entity_types: list[TypeInfo] = []
        self.relation_types: list[str] = []
        self.property_types: list[str] = []
        self.setWindowTitle("umm")

        self.graph_scene = GraphScene()
        self.view = GraphView(self.graph_scene)
        self.setCentralWidget(self.view)

        self.profile_name, self.profile_color = self._account_profile()
        self.graph_scene.local_cursor.set_profile(self.profile_name, self.profile_color)
        self._cursor_pos: QPointF | None = None
        self._cursor_dirty = False
        self.inspector = Inspector()
        self.inspector_dock = QDockWidget("Inspector", self)
        self.inspector_dock.setWidget(self.inspector)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.inspector_dock)

        self._build_toolbar()
        self._connect_signals()

        self.socket = QWebSocket()
        self.socket.connected.connect(self._on_connected)
        self.socket.disconnected.connect(self._schedule_reconnect)
        self.socket.errorOccurred.connect(self._schedule_reconnect)
        self.socket.sslErrors.connect(self._on_ssl_errors)
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
            action.triggered.connect(slot_ignore_checked(slot))
        return action

    def _build_toolbar(self) -> None:
        """Edit actions on the left, Profile on the right; navigation and display live in the view overlay."""
        self.link_action = self._action("Link entities", "link", self._toggle_link_mode, checkable=True)
        add_action = self._action("Add entity", "add", self.add_entity)
        types_action = self._action("Delete types", "delete", self.manage_types)
        types_action.setToolTip("Delete unused entity types, relation types and property types")
        delete_key = self._action("Delete selected", "delete", self.delete_selected)
        delete_key.setShortcut(QKeySequence.StandardKey.Delete)
        self.addAction(delete_key)  # the Delete key still removes the selection; so does the right-click menu
        reset_layout = self._action("Reset layout", "refresh", self.reset_layout)
        reset_layout.setShortcut(QKeySequence(Qt.Key.Key_F1))
        self.addAction(reset_layout)

        bar = QToolBar("Toolbar")
        self.toolbar = bar
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
        if self.api.user and self.api.user.get("is_admin"):
            bar.addAction(self._action("Users", "badge", self.manage_users))
        bar.addAction(self._action("Profile", "account_circle", self.edit_profile))
        bar.addAction(self._action("Sign out", "visibility_off", self.sign_out))

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
        except AuthError as exc:
            self._session_lost(str(exc))
            return None
        except requests.RequestException as exc:
            self.statusBar().showMessage(f"Request failed: {describe_error(exc)}", 6000)
            return None

    # --- live connection -------------------------------------------------

    def _open_socket(self) -> None:
        if self.socket.state() != QAbstractSocket.SocketState.UnconnectedState:
            return
        try:
            headers = self.api.ws_headers()
        except AuthError as exc:
            self._session_lost(str(exc))
            return
        except requests.RequestException:
            self._schedule_reconnect()
            return
        self.statusBar().showMessage("Connecting...")
        request = QNetworkRequest(QUrl(self.api.ws_url))
        for name, value in headers.items():
            request.setRawHeader(name.encode(), value.encode())
        self.socket.open(request)

    def _on_ssl_errors(self, errors: list[Any]) -> None:
        """A self-signed server is accepted only if its certificate is the one the user pinned."""
        pin = (self.api.pin or "").replace(":", "").upper()
        if pin and all(
            bytes(e.certificate().digest(QCryptographicHash.Algorithm.Sha256).toHex()).decode().upper() == pin
            for e in errors
        ):
            self.socket.ignoreSslErrors()

    def _session_lost(self, reason: str) -> None:
        self.reconnect_timer.stop()
        self.cursor_timer.stop()
        QMessageBox.warning(self, "Signed out", reason)
        self.close()

    def sign_out(self) -> None:
        self.reconnect_timer.stop()
        self.cursor_timer.stop()
        self.api.logout()
        self.close()

    def manage_users(self) -> None:
        UsersDialog(self.api, self).exec()

    def reset_layout(self) -> None:
        """F1: bring back the toolbar and the inspector if they were closed or moved."""
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)
        self.toolbar.show()
        self.inspector_dock.setFloating(False)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.inspector_dock)
        self.inspector_dock.show()

    def _schedule_reconnect(self, *_: Any) -> None:
        self.graph_scene.clear_remote_cursors()
        self.statusBar().showMessage("Disconnected, retrying...")
        self.reconnect_timer.start()

    def _on_connected(self) -> None:
        self.statusBar().showMessage("Live", 3000)
        self.reload()

    def _send(self, message: dict[str, Any]) -> None:
        if self.socket.state() == QAbstractSocket.SocketState.ConnectedState:
            self.socket.sendTextMessage(json.dumps(message))

    def _account_profile(self) -> tuple[str, str]:
        user = self.api.user or {}
        return str(user.get("display_name", "")), str(user.get("cursor_color", "#888888"))

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
        name = dialog.name_edit.text().strip() or self.profile_name
        if self._call(self.api.update_profile, name, dialog.color) is None:
            return
        self.profile_name, self.profile_color = self._account_profile()
        self.graph_scene.local_cursor.set_profile(self.profile_name, self.profile_color)

    def reload(self) -> None:
        graph = self._call(self.api.graph)
        if graph is not None:
            self.entity_types = graph["entity_types"]
            self.relation_types = graph["relation_types"]
            self.property_types = graph["property_types"]
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
            self.property_types = message["property_types"]
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
        shape, ok = QInputDialog.getItem(self, "New type", f"Shape for '{type_}':", GraphicsHelper.SHAPES, 0, False)
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
            [n for n in self.property_types if n not in taken],
            label="Choose an existing property type or type a new one:",
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
        if new in self.property_types:
            QMessageBox.warning(self, "Rename property", f"A property type named '{new}' already exists.")
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
            menu.addAction("Edit type...", slot_ignore_checked(self._edit_type, item.entity_id))
            menu.addAction("Add property...", slot_ignore_checked(self.add_property, item.entity_id))
            shapes = menu.addMenu("Type shape")
            for shape in GraphicsHelper.SHAPES:
                shapes.addAction(shape, slot_ignore_checked(self._change_style, item.info["type"], GraphicsHelper.SHAPES))
            menu.addAction("Type color...", slot_ignore_checked(self._pick_color, item.info["type"]))
            menu.addSeparator()
            menu.addAction("Delete entity", slot_ignore_checked(self.delete_selected))
        elif isinstance(item, RelationItem):
            menu.addAction("Delete relation", slot_ignore_checked(self.delete_selected))
        else:
            menu.addAction("Add entity here...", slot_ignore_checked(self.add_entity, scene_pos))
        menu.exec(global_pos)
