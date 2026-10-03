import logging

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap import ensure_initial_admin, run_bootstrap
from app.db import new_session
from app.models import AuditLog, Role, User, UserStatus
from app.settings import Settings
from tests.factories import make_user


def _settings(**kwargs: object) -> Settings:
    return Settings(app_env="test", **kwargs)


def test_creates_first_admin(db: Session) -> None:
    user = ensure_initial_admin(
        db, _settings(initial_admin_sub="abc", initial_admin_name="Dave")
    )
    assert user is not None
    assert user.role == Role.ADMIN
    assert user.display_name == "Dave"
    entry = db.scalars(select(AuditLog)).one()
    assert entry.action == "user.bootstrap_admin"
    assert entry.object_id == str(user.id)


def test_noop_when_admin_exists(db: Session) -> None:
    make_user(db, role=Role.ADMIN)
    assert ensure_initial_admin(db, _settings(initial_admin_sub="abc")) is None
    assert db.scalar(select(User).where(User.oidc_sub == "abc")) is None


def test_promotes_existing_user(db: Session) -> None:
    existing = make_user(db, sub="abc", status=UserStatus.DEACTIVATED)
    user = ensure_initial_admin(db, _settings(initial_admin_sub="abc"))
    assert user is not None and user.id == existing.id
    assert user.role == Role.ADMIN
    assert user.status == UserStatus.ACTIVE


def test_without_sub_only_warns(db: Session, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assert ensure_initial_admin(db, _settings()) is None
    assert "INITIAL_ADMIN_SUB" in caplog.text
    assert db.scalar(select(User)) is None


def test_skips_unmigrated_database(
    db_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    with new_session() as session, caplog.at_level(logging.WARNING):
        run_bootstrap(session, _settings(initial_admin_sub="abc"))
    assert "alembic upgrade head" in caplog.text


def test_lifespan_runs_bootstrap(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.settings import get_settings

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("INITIAL_ADMIN_SUB", "lifespan-sub")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        assert client.get("/healthz").status_code == 200
    admin = db.scalar(select(User).where(User.oidc_sub == "lifespan-sub"))
    assert admin is not None and admin.is_admin
