# Run the following things :

## Installing python
Goto python website and follow instructions to install python.

You have succeeded when you can do :
```bash
python
>>> exit()
```

## Installing the docker image of postgre
```bash
docker run --name umm-postgre -e POSTGRES_PASSWORD=password -p 5432:5432 -d postgres
```

# Installing python dependencies :
```bash
pip install sqlalchemy
```
```bash
py -m pip install "psycopg[binary]"
```
```bash
pip install fastapi "uvicorn[standard]>=0.29"
```
```bash
pip install opaquepy cryptography
```
```bash
pip install PySide6 requests keyring
```
opaquepy supports Python 3.9 to 3.13.

# Running the server :
```bash
cd backend/python
py main.py
```
On the first start the admin account is created and its generated password is printed once.
The console then accepts commands (`help`, `users`, `adduser`, `resetuser`, `resetadmin`, `quit`).

Encryption is always on (TLS 1.2+, TLS 1.3 when the client supports it):
- Without configuration the server creates a self-signed certificate in `data/` and prints its fingerprint.
  Clients show the fingerprint at first connection and pin it once the user confirms.
- With your own certificate: set `UMM_TLS_CERT` and `UMM_TLS_KEY` (PEM files).
- Extra names or addresses for the self-signed certificate: `UMM_TLS_NAMES=host1,1.2.3.4`.
- `UMM_HOST` and `UMM_PORT` choose the address (default `127.0.0.1:8000`).
- `py main.py --dev` serves plain HTTP, only on `127.0.0.1` or `localhost`.
- `data/` holds the server's secrets (OPAQUE setup, TLS key): back it up and keep it private.

# Running the frontend :
```bash
cd frontend/python
py main.py
```
Enter the server address in the sign-in dialog (for `--dev`: `http://127.0.0.1:8000`).

