# Security model

## Goals
- The server never learns a user's password, even if it is compromised or malicious.
- Traffic between client and server is encrypted and authenticated.
- A stolen token is useless without the device it was issued to.
- Disabling a user or resetting a password cuts access immediately.

## Layers

### 1. Transport: TLS
- The backend always serves TLS 1.2+ (TLS 1.3 when the client supports it) with AEAD ciphers only.
- Certificate: the operator's own (`UMM_TLS_CERT`, `UMM_TLS_KEY`), or a self-signed ECDSA P-256 certificate created on first start.
- Self-signed trust: the client shows the SHA-256 fingerprint, the user compares it with the server console, and the client pins it. A different certificate later triggers a new warning.
- `--dev` disables TLS and is refused on any non-loopback address.

### 2. Password: OPAQUE (RFC 9807)
- Registration and login use an augmented password-authenticated key exchange (`opaquepy`, wrapping `opaque-ke`).
- The password and anything it can be derived from by the server never leave the client. The server stores only the OPAQUE password file.
- The server's long-term OPAQUE secret lives in `data/opaque_setup`, apart from the database. A database leak alone does not allow offline guessing.
- Unknown and disabled usernames get a dummy OPAQUE response, so login does not reveal which accounts exist. Accounts still waiting for a first password are the exception.

### 3. Device binding: Ed25519
- At login the client generates a new Ed25519 key. Its public key is bound to the OPAQUE session key through an HMAC proof, so it cannot be swapped in transit.
- Access tokens (10 minutes) and refresh tokens (30 days) are random 256-bit values. The server stores only their SHA-256 hashes.
- Every request and the WebSocket handshake carry: bearer token, timestamp, nonce, and an Ed25519 signature over method, path and query, body hash and token hash.
- The server rejects requests with a bad signature, a clock difference over 60 seconds, a reused nonce, or an expired token.
- Refresh tokens rotate on use. Presenting an already rotated token revokes the whole session.
- The private key and refresh token are stored in the OS keyring on the client.

## Accounts
- The admin account is created on an empty database with a generated password, printed once in the console.
- Other accounts are created by an admin. The user chooses their password at first login.
- Admins cannot disable, demote or delete their own account through the API.
- Disabling, deleting or resetting a user deletes their sessions and closes their live connections.
- The cursor name and colour come from the account. The server ignores name and colour sent over the WebSocket.

## Abuse limits
- Each login start counts as an attempt until a login succeeds. After 5 attempts the account is locked for 15 minutes.
- Public endpoints are limited to 30 requests per minute per client address.

## Secrets on the server (`data/`, mode 0600 where supported)
- `opaque_setup`: losing it invalidates every password.
- `tls_key.pem`, `tls_cert.pem`: the self-signed identity.

## Known limits
- The first person to log in with a new username sets its password. An admin should tell the user right after creating the account.
- Nonces and rate limits are kept in memory, so they work per process only. Run a single server process.
- Behind a reverse proxy, the rate limit sees the proxy's address. The signed path must reach the backend unchanged.
- WebSocket messages after the handshake are protected by TLS, not individually signed.
- A compromised client machine can use its own session.
