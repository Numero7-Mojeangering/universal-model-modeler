import base64
import hashlib
import os
import secrets
import time
from collections import defaultdict, deque
from functools import cache
from pathlib import Path

import opaquepy
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

DATA_DIR = Path(os.environ.get("UMM_DATA_DIR", Path(__file__).parent / "data"))
CLOCK_SKEW_SECONDS = 60
DEVICE_PROOF_LABEL = b"umm-device-v1"


def data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def write_secret(path: Path, data: bytes) -> None:
    """Write a file readable by the owner only."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


@cache
def opaque_setup() -> str:
    """The server's long-term OPAQUE secret. Kept in a file, apart from the database that holds the password files."""
    path = data_dir() / "opaque_setup"
    if not path.exists():
        write_secret(path, opaquepy.create_setup().encode())
    return path.read_text().strip()


def b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def signing_message(method: str, target: str, timestamp: str, nonce: str, body: bytes, token: str) -> bytes:
    """What a client signs for each request. Must stay identical to the client's version."""
    parts = ["umm-v1", method.upper(), target, timestamp, nonce, hashlib.sha256(body).hexdigest(), token_hash(token)]
    return "\n".join(parts).encode()


def verify_signature(device_key: str, message: bytes, signature: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(b64decode(device_key)).verify(b64decode(signature), message)
    except (InvalidSignature, ValueError):
        return False
    return True


def is_fresh(timestamp: str) -> bool:
    try:
        return abs(time.time() - int(timestamp)) <= CLOCK_SKEW_SECONDS
    except ValueError:
        return False


class NonceCache:
    """Rejects a signed request that is sent a second time."""

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}

    def accept(self, nonce: str) -> bool:
        now = time.time()
        if len(self._seen) > 10_000:
            self._seen = {n: t for n, t in self._seen.items() if t > now}
        if nonce in self._seen:
            return False
        self._seen[nonce] = now + 2 * CLOCK_SKEW_SECONDS
        return True


class RateLimiter:
    """At most `limit` hits per `window` seconds for each key."""

    def __init__(self, limit: int, window: float) -> None:
        self.limit, self.window = limit, window
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True
