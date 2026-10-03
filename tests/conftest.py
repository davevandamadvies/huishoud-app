from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db import Base, get_engine, new_session, reset_engine_cache
from app.settings import get_settings


@pytest.fixture
def db_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Lege SQLite-database per test (zelfde PRAGMA's als in productie)."""
    url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
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
