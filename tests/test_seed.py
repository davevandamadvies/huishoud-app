import logging

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import seed
from app.models import AuditLog, Category, Occurrence, Task
from app.palette import CATEGORY_COLORS
from app.recurrence import IntervalUnit, RecurrenceType
from app.seed_data import TASKS

START_CATEGORIES = [
    "Schoonmaak",
    "Huis & installaties",
    "Auto",
    "Tuin",
    "Planten",
    "Techniek",
]


@pytest.fixture
def start_categories(db: Session) -> None:
    for i, name in enumerate(START_CATEGORIES):
        db.add(Category(name=name, color=list(CATEGORY_COLORS)[i], position=i))
    db.commit()


def test_seed_data_is_complete_and_valid() -> None:
    assert len(TASKS) == 45
    assert len({t.name.lower() for t in TASKS}) == 45
    assert {t.category for t in TASKS} == set(START_CATEGORIES)
    for t in TASKS:
        assert t.every and t.every >= 1
        assert t.points is None or 1 <= t.points <= 12
        assert len(t.name) <= 100
        if t.season:
            assert all(1 <= m <= 12 for m in t.season)
    # Geen persoonlijke gegevens (automerk/-model) in de startvulling
    assert not any("clio" in (t.name + (t.notes or "")).lower() for t in TASKS)


def test_seed_is_idempotent(db: Session, start_categories: None) -> None:
    assert seed.seed_tasks(db) == (45, 0)
    assert seed.seed_tasks(db) == (0, 45)
    assert db.scalar(select(func.count()).select_from(Task)) == 45
    # Geen vervaldatums: niets staat meteen op "te laat"
    assert db.scalar(select(func.count()).select_from(Occurrence)) == 0
    assert db.scalars(select(AuditLog.action)).all() == ["task.seed"]


def test_seed_skips_existing_names_case_insensitive(
    db: Session, start_categories: None
) -> None:
    category = db.scalar(select(Category).where(Category.name == "Schoonmaak"))
    db.add(
        Task(
            name="STOFZUIGEN HELE HUIS",
            category=category,
            recurrence_type=RecurrenceType.INTERVAL,
            interval_every=3,
        )
    )
    db.commit()
    assert seed.seed_tasks(db) == (44, 1)


def test_seed_special_tasks(db: Session, start_categories: None) -> None:
    seed.seed_tasks(db)
    apk = db.scalar(select(Task).where(Task.name == "APK"))
    assert apk.recurrence_type == RecurrenceType.FIXED_DATE
    assert (apk.interval_every, apk.interval_unit) == (12, IntervalUnit.MONTHS)
    olie = db.scalar(select(Task).where(Task.name.like("Olie verversen%")))
    assert "15.000 km" in olie.notes


def test_seed_requires_categories(db: Session) -> None:
    with pytest.raises(seed.SeedError, match="Categorieën ontbreken"):
        seed.seed_tasks(db)


def test_main_on_unmigrated_database(
    db_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        assert seed.main() == 1
    assert "alembic upgrade head" in caplog.text
