import sys

from PySide6.QtWidgets import QApplication

from api import Api
from main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    window = MainWindow(Api(url))
    window.resize(1200, 800)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
