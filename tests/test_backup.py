import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import backup
from app.models import AuditLog, Role
from app.settings import get_settings
from tests.conftest import login_as
from tests.factories import make_task, make_user


@pytest.fixture
def backup_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_url: str) -> Path:
    folder = tmp_path / "backups"
    monkeypatch.setenv("BACKUP_DIR", str(folder))
    monkeypatch.setenv("BACKUP_KEEP", "3")
    get_settings.cache_clear()
    return folder


def _tasks_in(path: Path) -> list[str]:
    with sqlite3.connect(path) as connection:
        return [row[0] for row in connection.execute("SELECT name FROM tasks")]


def test_copy_contains_the_data(db: Session, backup_dir: Path) -> None:
    make_task(db, name="Ramen")
    target = backup.copy_to(backup_dir / "kopie.db")
    assert _tasks_in(target) == ["Ramen"]
    assert not list(backup_dir.glob("*.part"))


def test_nightly_backup_once_per_day(db: Session, backup_dir: Path) -> None:
    night = datetime(2026, 10, 4, 3, 15)
    assert backup.run_if_due(night - timedelta(minutes=1)) is None
    made = backup.run_if_due(night)
    assert made == backup_dir / "huishoud-2026-10-04.db"
    assert backup.run_if_due(night + timedelta(hours=5)) is None


def test_missed_night_is_caught_up(db: Session, backup_dir: Path) -> None:
    # De app stond om 03:15 uit en start om 10:00.
    assert backup.run_if_due(datetime(2026, 10, 4, 10, 0)) is not None


def test_old_backups_are_pruned(db: Session, backup_dir: Path) -> None:
    for offset in range(5):
        backup.run_if_due(datetime(2026, 10, 1, 4, 0) + timedelta(days=offset))
    days = [b.day for b in backup.list_backups()]
    assert days == [date(2026, 10, 5), date(2026, 10, 4), date(2026, 10, 3)]


def test_unrelated_files_are_ignored(db: Session, backup_dir: Path) -> None:
    backup_dir.mkdir()
    (backup_dir / "notities.txt").write_text("x")
    (backup_dir / "huishoud-kapot.db").write_text("x")
    assert backup.list_backups() == []


def test_disabled_without_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/huishoud")
    get_settings.cache_clear()
    try:
        assert not backup.enabled()
        assert backup.run_if_due(datetime(2026, 10, 4, 4, 0)) is None
        with pytest.raises(backup.BackupError):
            backup.copy_to(Path("x.db"))
    finally:
        get_settings.cache_clear()


def test_human_size() -> None:
    assert backup.human_size(300) == "1 kB"
    assert backup.human_size(2_621_440) == "2,5 MB"


# ---- Scherm ----


@pytest.fixture
def admin_client(anon_client: TestClient, db: Session, backup_dir: Path) -> TestClient:
    admin = make_user(db, name="Beheerder", role=Role.ADMIN)
    return login_as(anon_client, db, admin)


def test_page_lists_backups(admin_client: TestClient, db: Session) -> None:
    backup.run_if_due(datetime(2026, 10, 4, 4, 0))
    text = admin_client.get("/beheer/back-up").text
    assert "Nu downloaden" in text
    assert "4 oktober" in text


def test_download_returns_a_fresh_copy(
    admin_client: TestClient, db: Session, tmp_path: Path
) -> None:
    make_task(db, name="Ramen")
    response = admin_client.get("/beheer/back-up/download")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    copy = tmp_path / "download.db"
    copy.write_bytes(response.content)
    assert _tasks_in(copy) == ["Ramen"]
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "backup.download"))
    assert entry is not None


def test_only_admins(client: TestClient, backup_dir: Path) -> None:
    assert client.get("/beheer/back-up").status_code == 403
    assert client.get("/beheer/back-up/download").status_code == 403


def test_settings_link_only_for_admin(admin_client: TestClient) -> None:
    assert 'href="/beheer/back-up"' in admin_client.get("/meer").text


def test_scheduler_does_not_start_in_tests(db_url: str) -> None:
    import asyncio

    async def check() -> None:
        async with backup.running():
            assert "back-up" not in {t.get_name() for t in asyncio.all_tasks()}

    asyncio.run(check())
