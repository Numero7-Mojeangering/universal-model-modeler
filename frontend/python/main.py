import sys

import requests
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from api import Api, AuthError, NeedsPassword, UntrustedCertificate, describe_error
from login_dialog import LoginDialog, SetPasswordDialog
from main_window import MainWindow

DEFAULT_SERVER = "https://127.0.0.1:8000"


def make_api(url: str, settings: QSettings) -> Api:
    api = Api(url)
    pin = settings.value(f"pins/{api.host_key.replace(':', '_')}")
    if pin:
        api.set_pin(str(pin))
    return api


def ask_trust(exc: UntrustedCertificate) -> bool:
    if exc.changed:
        text = (
            "The server's certificate is not the one you trusted before. Someone may be intercepting the "
            "connection, or the server's certificate was replaced.\n\nNew fingerprint (SHA-256):\n"
            f"{exc.fingerprint}\n\nTrust it only if the server's administrator confirms this fingerprint."
        )
    else:
        text = (
            "This server's certificate is not issued by a trusted authority.\n\nFingerprint (SHA-256):\n"
            f"{exc.fingerprint}\n\nTrust it only if it matches the one shown in the server's console."
        )
    box = QMessageBox(QMessageBox.Icon.Warning, "Unknown server certificate", text)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    box.button(QMessageBox.StandardButton.Yes).setText("Trust")
    return box.exec() == QMessageBox.StandardButton.Yes


def ensure_trusted(api: Api, settings: QSettings) -> bool:
    """Reach the server, asking the user to confirm a certificate nobody vouches for."""
    while True:
        try:
            api.check_server()
            return True
        except UntrustedCertificate as exc:
            if not ask_trust(exc):
                return False
            api.set_pin(exc.fingerprint)
            settings.setValue(f"pins/{api.host_key.replace(':', '_')}", exc.fingerprint)
        except requests.RequestException as exc:
            QMessageBox.critical(None, "umm", f"Cannot reach the server:\n{exc}")
            return False


def sign_in(settings: QSettings) -> Api | None:
    url = sys.argv[1] if len(sys.argv) > 1 else str(settings.value("server", DEFAULT_SERVER))
    username = str(settings.value("username", ""))
    if username:  # the secret store may still hold this device's session
        api = make_api(url, settings)
        try:
            if ensure_trusted(api, settings) and api.restore(username):
                return api
        except requests.RequestException:
            pass
    dialog = LoginDialog(url, username)
    while dialog.exec() == QDialog.DialogCode.Accepted:
        api = make_api(dialog.server, settings)
        if not ensure_trusted(api, settings):
            continue
        try:
            try:
                api.login(dialog.username, dialog.password)
            except NeedsPassword:
                chooser = SetPasswordDialog(dialog.username)
                if chooser.exec() != QDialog.DialogCode.Accepted:
                    continue
                api.register(dialog.username, chooser.password)
                api.login(dialog.username, chooser.password)
        except (AuthError, requests.RequestException) as exc:
            dialog.show_error(describe_error(exc))
            continue
        settings.setValue("server", dialog.server)
        settings.setValue("username", dialog.username.lower())
        return api
    return None


def main():
    app = QApplication(sys.argv)
    api = sign_in(QSettings("umm", "client"))
    if api is None:
        sys.exit(0)
    window = MainWindow(api)
    window.resize(1200, 800)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
