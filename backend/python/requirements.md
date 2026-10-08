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
pip install fastapi "uvicorn[standard]"
```
```bash
pip install PySide6 requests
```

# Running the server :
```bash
cd backend/python
py main.py
```

# Running the frontend :
```bash
cd frontend/python
py main.py
```

