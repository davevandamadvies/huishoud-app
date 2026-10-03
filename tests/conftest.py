import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import sessions
from app.auth import SESSION_COOKIE
from app.db import Base, get_engine, new_session, reset_engine_cache
from app.models import User
from app.settings import get_settings
from tests.factories import make_user

# Tests draaien nooit met productie-instellingen.
os.environ["APP_ENV"] = "test"
os.environ.pop("INITIAL_ADMIN_SUB", None)
for _name in ("BASE_URL", "OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"):
    os.environ.pop(_name, None)

BASE_URL = "https://testserver"


@pytest.fixture
def db_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Lege SQLite-database per test (zelfde PRAGMA's als in productie)."""
    url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("BASE_URL", BASE_URL)
    get_settings.cache_clear()
    reset_engine_cache()
    yield url
    reset_engine_cache()
    get_settings.cache_clear()


@pytest.fixture
def db(db_url: str) -> Iterator[Session]:
    Base.metadata.create_all(get_engine())
    with new_session() as session:
        yield session


@pytest.fixture
def user(db: Session) -> User:
    return make_user(db, name="Dave")


def login_as(client: TestClient, db: Session, user: User) -> TestClient:
    token = sessions.create_session(db, user)
    db.commit()
    client.cookies.set(SESSION_COOKIE, token)
    return client


@pytest.fixture
def anon_client(db: Session) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app(), base_url=BASE_URL, follow_redirects=False) as client:
        yield client


@pytest.fixture
def client(anon_client: TestClient, db: Session, user: User) -> TestClient:
    """Ingelogde client (sessiecookie van `user`)."""
    return login_as(anon_client, db, user)


HTMX_HEADERS = {"Origin": BASE_URL, "HX-Request": "true"}
