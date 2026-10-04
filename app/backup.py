"""Back-up van de SQLite-database, binnen de app.

- Elke nacht om 03:15 (Europe/Amsterdam) een consistente kopie via de
  SQLite-backup-API (veilig terwijl de app draait, ook met WAL).
- De laatste BACKUP_KEEP kopieën blijven bewaard.
- Een gemiste nacht wordt ingehaald bij de volgende ronde (of start).
- De beheerder kan altijd een verse kopie downloaden.
"""

import asyncio
import contextlib
import logging
import re
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

from sqlalchemy.engine import make_url

from app.dates import TIMEZONE
from app.settings import Settings, get_settings

logger = logging.getLogger(__name__)

NIGHTLY_AT = time(3, 15)
CHECK_EVERY_SECONDS = 600
_NAME = re.compile(r"^huishoud-(\d{4}-\d{2}-\d{2})\.db$")


class BackupError(Exception):
    """Back-up niet mogelijk (bijv. geen SQLite)."""


def database_path(settings: Settings | None = None) -> Path | None:
    """Pad van het databasebestand, of None als het geen SQLite-bestand is."""
    url = make_url((settings or get_settings()).database_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        return None
    if url.database == ":memory:":
        return None
    return Path(url.database)


def enabled(settings: Settings | None = None) -> bool:
    return database_path(settings) is not None


def copy_to(target: Path) -> Path:
    """Maak een consistente kopie van de database in `target`."""
    source_path = database_path()
    if source_path is None:
        raise BackupError("Back-ups werken alleen met een SQLite-database.")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    source = sqlite3.connect(source_path)
    try:
        destination = sqlite3.connect(partial)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    partial.replace(target)
    return target


@dataclass(frozen=True)
class BackupFile:
    path: Path
    day: date
    size: int


def list_backups(settings: Settings | None = None) -> list[BackupFile]:
    """Nachtelijke back-ups, nieuwste eerst."""
    folder = Path((settings or get_settings()).backup_dir)
    if not folder.is_dir():
        return []
    found = []
    for path in folder.iterdir():
        match = _NAME.match(path.name)
        if match and path.is_file():
            found.append(
                BackupFile(path, date.fromisoformat(match[1]), path.stat().st_size)
            )
    return sorted(found, key=lambda b: b.day, reverse=True)


def prune(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    removed = 0
    for old in list_backups(settings)[settings.backup_keep :]:
        old.path.unlink(missing_ok=True)
        removed += 1
    return removed


def run_if_due(now: datetime) -> Path | None:
    """Maak de back-up van vandaag als het tijd is en hij er nog niet is."""
    settings = get_settings()
    if not enabled(settings) or now.time() < NIGHTLY_AT:
        return None
    target = Path(settings.backup_dir) / f"huishoud-{now.date().isoformat()}.db"
    if target.exists():
        return None
    copy_to(target)
    prune(settings)
    logger.warning("Back-up gemaakt: %s", target.name)
    return target


def local_now() -> datetime:
    return datetime.now(TIMEZONE).replace(tzinfo=None, microsecond=0)


def human_size(size: int) -> str:
    if size < 1024 * 1024:
        return f"{max(1, round(size / 1024))} kB"
    return f"{size / (1024 * 1024):.1f} MB".replace(".", ",")


async def _loop() -> None:
    while True:
        try:
            await asyncio.to_thread(run_if_due, local_now())
        except Exception:
            logger.exception("Back-up mislukt")
        await asyncio.sleep(CHECK_EVERY_SECONDS)


@contextlib.asynccontextmanager
async def running() -> AsyncIterator[None]:
    """Start de nachtelijke back-up (alleen SQLite, niet in tests)."""
    settings = get_settings()
    if settings.app_env == "test" or not enabled(settings):
        yield
        return
    task = asyncio.create_task(_loop(), name="back-up")
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
