from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QPainter, QPalette
from PySide6.QtWidgets import QApplication

ICON_DIR = Path(__file__).parent / "icons"  # Google Material Symbols (outlined, 24px)


def icon(name: str) -> QIcon:
    """A Material Symbols icon tinted with the theme's button text colour."""
    pixmap = QIcon(str(ICON_DIR / f"{name}.svg")).pixmap(QSize(48, 48))
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QApplication.palette().color(QPalette.ColorRole.ButtonText))
    painter.end()
    return QIcon(pixmap)
