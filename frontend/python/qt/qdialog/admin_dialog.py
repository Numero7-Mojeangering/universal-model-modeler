from typing import Any, Callable

import requests
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from api import Api, AuthError, describe_error
from qt.helper.slot import slot_ignore_checked

class UsersDialog(QDialog):
    """Administrators create and manage accounts here."""

    def __init__(self, api: Api, parent: QWidget | None = None):
        super().__init__(parent)
        self.api = api
        self.rows: list[dict[str, Any]] = []
        self.setWindowTitle("Users")
        self.resize(520, 360)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Username", "Role", "Status"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        buttons = QHBoxLayout()
        for text, slot in [
            ("Add user", self._add),
            ("Reset password", self._reset_password),
            ("Disable / enable", self._toggle_disabled),
            ("Admin on / off", self._toggle_admin),
            ("Delete", self._delete),
        ]:
            button = QPushButton(text)
            button.clicked.connect(slot_ignore_checked(slot))
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        self._reload()

    def _run(self, fn: Callable[..., Any], *args: Any) -> Any:
        try:
            return fn(*args)
        except (requests.RequestException, AuthError) as exc:
            QMessageBox.warning(self, "Users", describe_error(exc))
            return None

    def _reload(self) -> None:
        rows = self._run(self.api.users)
        if rows is None:
            return
        self.rows = rows
        self.table.setRowCount(len(rows))
        for index, user in enumerate(rows):
            state = "disabled" if user["disabled"] else ("active" if user["has_password"] else "waiting for password")
            for column, text in enumerate([user["username"], "admin" if user["is_admin"] else "user", state]):
                self.table.setItem(index, column, QTableWidgetItem(text))

    def _selected(self) -> dict[str, Any] | None:
        row = self.table.currentRow()
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def _add(self) -> None:
        name, ok = QInputDialog.getText(self, "Add user", "Username (3-32 letters, digits, _ . -):")
        if not ok or not name.strip():
            return
        answer = QMessageBox.question(self, "Add user", "Make this user an administrator?")
        is_admin = answer == QMessageBox.StandardButton.Yes
        if self._run(self.api.create_user, name.strip().lower(), is_admin) is not None:
            QMessageBox.information(self, "Add user", "Created. The user chooses a password at their first login.")
            self._reload()

    def _reset_password(self) -> None:
        user = self._selected()
        if user and self._confirm(f"Reset the password of '{user['username']}'? They are signed out everywhere."):
            self._run(self.api.reset_user_password, user["id"])
            self._reload()

    def _toggle_disabled(self) -> None:
        user = self._selected()
        if user:
            self._run(self.api.set_user_flags, user["id"], not user["disabled"], None)
            self._reload()

    def _toggle_admin(self) -> None:
        user = self._selected()
        if user:
            self._run(self.api.set_user_flags, user["id"], None, not user["is_admin"])
            self._reload()

    def _delete(self) -> None:
        user = self._selected()
        if user and self._confirm(f"Delete '{user['username']}'?"):
            self._run(self.api.delete_user, user["id"])
            self._reload()

    def _confirm(self, text: str) -> bool:
        return QMessageBox.question(self, "Users", text) == QMessageBox.StandardButton.Yes
