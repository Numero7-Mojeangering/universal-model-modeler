
from PySide6.QtGui import (
    QColor,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

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
