
from typing import Any
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from data import EntityInfo, TypeInfo
from ..common import InspectorKey
from ..scene import SHAPES


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
