import ipaddress
import os
import ssl
import sys
import threading
from pathlib import Path

import uvicorn

import console
import tls
from accounts import ADMIN_USERNAME, ensure_admin
from server import app
from services import init_db

TLS_CIPHERS = "ECDHE+AESGCM:ECDHE+CHACHA20"  # TLS 1.2 suites; TLS 1.3 suites are always AEAD


def is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def build_config(host: str, port: int, dev: bool) -> uvicorn.Config:
    """HTTPS with the given certificate or a self-signed one; plain HTTP only with --dev on this machine."""
    if dev:
        if not is_loopback(host):
            sys.exit("--dev serves without encryption, so it only works on 127.0.0.1 or localhost.")
        print(f"DEV MODE: no encryption. Listening on http://{host}:{port}")
        return uvicorn.Config(app, host=host, port=port, server_header=False)
    cert, key = os.environ.get("UMM_TLS_CERT"), os.environ.get("UMM_TLS_KEY")
    if bool(cert) != bool(key):
        sys.exit("Set both UMM_TLS_CERT and UMM_TLS_KEY, or neither.")
    if cert and key:
        cert_path, key_path = Path(cert), Path(key)
        print("Using the certificate from UMM_TLS_CERT.")
    else:
        names = [n.strip() for n in os.environ.get("UMM_TLS_NAMES", "").split(",") if n.strip()]
        cert_path, key_path = tls.self_signed(names)
        print(f"Self-signed certificate. Clients trust it by confirming this fingerprint:\n  {tls.fingerprint(cert_path)}")
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
        ssl_ciphers=TLS_CIPHERS,
        server_header=False,
    )
    config.load()
    if config.ssl is not None:
        config.ssl.minimum_version = ssl.TLSVersion.TLSv1_2
    print(f"Listening on https://{host}:{port}")
    return config


def main() -> None:
    host = os.environ.get("UMM_HOST", "127.0.0.1")
    port = int(os.environ.get("UMM_PORT", "8000"))
    init_db()
    password = ensure_admin()
    if password:
        console.show_secret("First start: the admin account was created.", ADMIN_USERNAME, password)

    config = build_config(host, port, dev="--dev" in sys.argv[1:])
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="uvicorn")
    thread.start()
    try:
        if console.run():
            server.should_exit = True
    except KeyboardInterrupt:
        server.should_exit = True
    thread.join()


if __name__ == "__main__":
    main()
