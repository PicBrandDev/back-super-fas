import os
import tempfile

# Banco e uploads temporários (precisa vir antes de importar o app).
_tmp = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["SEED_PASSWORD"] = "senha-de-teste"
os.environ["UPLOAD_DIR"] = f"{_tmp}/uploads"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "senha-de-teste"


@pytest.fixture(scope="session")
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        yield c


def login(client: TestClient, email: str, password: str = PASSWORD) -> dict:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def master(client):
    return login(client, "admin@superfas.dev")


@pytest.fixture(scope="session")
def club_admin(client):
    return login(client, "vintage@superfas.dev")


@pytest.fixture(scope="session")
def sponsor(client):
    return login(client, "marca@superfas.dev")


@pytest.fixture(scope="session")
def fan(client):
    return login(client, "fa@superfas.dev")
