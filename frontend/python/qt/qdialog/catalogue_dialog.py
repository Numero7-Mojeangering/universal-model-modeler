from collections.abc import Callable

import requests
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from api import Api
from data import UsageInfo
from qt.icons import icon

# kind (as the server names it), tab title, what the count counts
KINDS = [
    ("entity", "Entity types", "entities"),
    ("relation", "Relation types", "relations"),
    ("property", "Property types", "properties"),
]
COUNT_ROLE = Qt.ItemDataRole.UserRole + 1


def _bound(fn: Callable[..., object], *args: object) -> Callable[..., None]:
    def slot(*_: object) -> None:
        fn(*args)

    return slot


class CatalogueDialog(QDialog):
    """Lists the entity types, relation types and property types; unused ones can be deleted."""

    def __init__(self, parent: QWidget, api: Api):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle("Delete types")
        self.resize(420, 420)
        self.lists: dict[str, QListWidget] = {}
        self.buttons: dict[str, QPushButton] = {}
        tabs = QTabWidget()
        for kind, title, _noun in KINDS:
            page = QWidget()
            box = QVBoxLayout(page)
            entries = QListWidget()
            button = QPushButton(icon("delete"), "Delete")
            button.setEnabled(False)
            entries.currentItemChanged.connect(_bound(self._sync_button, kind))
            button.clicked.connect(_bound(self._delete, kind))
            box.addWidget(entries)
            box.addWidget(button)
            tabs.addTab(page, title)
            self.lists[kind] = entries
            self.buttons[kind] = button
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(close)
        self.refresh()

    def refresh(self) -> None:
        try:
            data = self.api.catalogue()
        except requests.RequestException as exc:
            QMessageBox.warning(self, "Delete types", f"Could not load the types: {exc}")
            return
        groups: dict[str, list[UsageInfo]] = {
            "entity": [*data["entity_types"]],
            "relation": [*data["relation_types"]],
            "property": [*data["property_types"]],
        }
        colors = {e["name"]: e["color"] for e in data["entity_types"]}
        for kind, _title, noun in KINDS:
            entries = self.lists[kind]
            entries.clear()
            for entry in groups[kind]:
                used = f"{entry['count']} {noun}" if entry["count"] else "unused"
                item = QListWidgetItem(f"{entry['name']}   ({used})")
                item.setData(Qt.ItemDataRole.UserRole, entry["name"])
                item.setData(COUNT_ROLE, entry["count"])
                if kind == "entity":
                    item.setIcon(self._swatch(colors[entry["name"]]))
                entries.addItem(item)
            self._sync_button(kind)

    @staticmethod
    def _swatch(color: str) -> QIcon:
        pixmap = QPixmap(QSize(14, 14))
        pixmap.fill(QColor(color))
        return QIcon(pixmap)

    def _sync_button(self, kind: str) -> None:
        item = self.lists[kind].currentItem()
        button = self.buttons[kind]
        count = int(item.data(COUNT_ROLE))
        button.setEnabled(count == 0)
        button.setToolTip("" if count == 0 else f"Still used {count} time(s): remove those first")

    def _delete(self, kind: str) -> None:
        item = self.lists[kind].currentItem()
        try:
            self.api.delete_catalogue_entry(kind, str(item.data(Qt.ItemDataRole.UserRole)))
        except requests.HTTPError as exc:
            detail = exc.response.json().get("detail", str(exc)) if exc.response is not None else str(exc)
            QMessageBox.warning(self, "Delete types", str(detail))
        except requests.RequestException as exc:
            QMessageBox.warning(self, "Delete types", f"Request failed: {exc}")
        self.refresh()
