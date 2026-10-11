from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QPainter, QPalette
from PySide6.QtWidgets import QApplication

from . import ressource_rc  # noqa: F401

ressource_rc.qt_resource_data

def icon(name: str) -> QIcon:
    """A Material Symbols icon tinted with the theme's button text colour."""
    pixmap = QIcon(f":/icons/{name}.svg").pixmap(QSize(48, 48))

    painter = QPainter(pixmap)
    try:
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceIn
        )
        painter.fillRect(
            pixmap.rect(),
            QApplication.palette().color(QPalette.ColorRole.ButtonText),
        )
    finally:
        painter.end()

    return QIcon(pixmap)
