import datetime
import hashlib
import ipaddress
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from security import data_dir, write_secret

SELF_SIGNED_YEARS = 10  # clients pin the fingerprint, so expiry is not what protects them


def fingerprint(cert_path: Path) -> str:
    """SHA-256 of the certificate as AA:BB:..., the same text the client shows and pins."""
    der = x509.load_pem_x509_certificate(cert_path.read_bytes()).public_bytes(serialization.Encoding.DER)
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


def self_signed(names: list[str]) -> tuple[Path, Path]:
    """Create (once) a self-signed certificate for this machine and return its certificate and key files."""
    cert_path, key_path = data_dir() / "tls_cert.pem", data_dir() / "tls_key.pem"
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path
    key = ec.generate_private_key(ec.SECP256R1())
    hosts = {"localhost", socket.gethostname(), *names}
    alt_names: list[x509.GeneralName] = [x509.IPAddress(ipaddress.ip_address(a)) for a in ("127.0.0.1", "::1")]
    for host in sorted(hosts):
        try:
            alt_names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            alt_names.append(x509.DNSName(host))
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "umm")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365 * SELF_SIGNED_YEARS))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    write_secret(
        key_path,
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ),
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path
