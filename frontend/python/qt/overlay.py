from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QEnterEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from qt.icons import icon


class ViewOverlay(QFrame):
    """Controls floating in the top-right corner of the view: big navigation buttons and a foldable display panel."""

    entered = Signal()  # the mouse moved onto the overlay

    def __init__(self, parent: QWidget, navigate: list[QAction], display: list[QAction]):
        super().__init__(parent)
        self.setObjectName("overlay")
        self.setStyleSheet(
            "QFrame#overlay { background: palette(window); border: 1px solid palette(mid); border-radius: 6px; }"
        )
        self.setCursor(Qt.CursorShape.ArrowCursor)  # the view hides the OS cursor and draws its own

        row = QHBoxLayout()
        row.setSpacing(2)
        for action in navigate:
            row.addWidget(self._big_button(action))
        self.fold = QToolButton()
        self.fold.setText("Display")
        self.fold.setAutoRaise(True)
        self.fold.setIconSize(QSize(16, 16))
        self.fold.setMinimumHeight(32)
        self.fold.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.fold.clicked.connect(self._toggle)
        row.addWidget(self.fold)

        self.panel = QWidget()
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        for action in display:
            panel_layout.addWidget(self._eye_row(action))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)
        layout.addLayout(row)
        layout.addWidget(self.panel)
        self._set_open(False)

    @staticmethod
    def _big_button(action: QAction) -> QToolButton:
        button = QToolButton()
        button.setDefaultAction(action)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setIconSize(QSize(22, 22))
        button.setMinimumSize(32, 32)
        button.setAutoRaise(True)
        return button

    @staticmethod
    def _eye_row(action: QAction) -> QToolButton:
        """A checkable row: open eye when shown, closed eye when hidden."""
        row = QToolButton()
        row.setText(action.text())
        row.setCheckable(True)
        row.setChecked(action.isChecked())
        row.setAutoRaise(True)
        row.setIconSize(QSize(16, 16))
        row.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        def show_eye(shown: bool) -> None:
            row.setIcon(icon("visibility" if shown else "visibility_off"))

        row.toggled.connect(show_eye)
        row.toggled.connect(action.setChecked)
        action.toggled.connect(row.setChecked)
        show_eye(row.isChecked())
        return row

    def _toggle(self) -> None:
        self._set_open(not self.panel.isVisibleTo(self))

    def _set_open(self, is_open: bool) -> None:
        self.panel.setVisible(is_open)
        self.fold.setIcon(icon("expand_less" if is_open else "expand_more"))
        self.adjustSize()
        self.reposition()

    def reposition(self) -> None:
        """Keep the overlay in the top-right corner of its parent."""
        parent = self.parentWidget()
        if parent is not None:
            self.move(max(0, parent.width() - self.width() - 8), 8)
            self.raise_()

    def enterEvent(self, event: QEnterEvent) -> None:
        self.entered.emit()
        super().enterEvent(event)
