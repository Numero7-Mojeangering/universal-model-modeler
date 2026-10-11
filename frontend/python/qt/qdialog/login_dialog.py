from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

MIN_PASSWORD_LENGTH = 10


class LoginDialog(QDialog):
    """First step: server address and username. The password is asked in the next popup."""

    def __init__(self, server: str, username: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Sign in to umm")
        self.setMinimumWidth(380)
        self.server_edit = QLineEdit(server)
        self.user_edit = QLineEdit(username)
        self.error = QLabel()
        self.error.setStyleSheet("color: #c0392b")
        self.error.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Server", self.server_edit)
        form.addRow("Username", self.user_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        self.user_edit.setFocus()

    @property
    def server(self) -> str:
        return self.server_edit.text().strip()

    @property
    def username(self) -> str:
        return self.user_edit.text().strip()

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.user_edit.setFocus()


class PasswordDialog(QDialog):
    """Second step: the password of an account that already has one."""

    def __init__(self, username: str, error: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Password")
        self.setMinimumWidth(340)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        message = QLabel(error)
        message.setStyleSheet("color: #c0392b")
        message.setWordWrap(True)
        form = QFormLayout()
        form.addRow(f"Password for '{username}'", self.password_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Sign in")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(message)
        layout.addWidget(buttons)
        self.password_edit.setFocus()

    @property
    def password(self) -> str:
        return self.password_edit.text()


class SetPasswordDialog(QDialog):
    """First login of an account: choose the password. It never leaves this computer in a usable form."""

    def __init__(self, username: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Choose a password")
        self.setMinimumWidth(380)
        self.password_edit = QLineEdit()
        self.confirm_edit = QLineEdit()
        for edit in (self.password_edit, self.confirm_edit):
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.error = QLabel()
        self.error.setStyleSheet("color: #c0392b")
        form = QFormLayout()
        form.addRow("Password", self.password_edit)
        form.addRow("Repeat", self.confirm_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._check)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"'{username}' has no password yet. Choose one ({MIN_PASSWORD_LENGTH}+ characters)."))
        layout.addLayout(form)
        layout.addWidget(self.error)
        layout.addWidget(buttons)

    @property
    def password(self) -> str:
        return self.password_edit.text()

    def _check(self) -> None:
        if len(self.password) < MIN_PASSWORD_LENGTH:
            self.error.setText(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
        elif self.password != self.confirm_edit.text():
            self.error.setText("The two passwords differ.")
        else:
            self.accept()
