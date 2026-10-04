"""Startvulling laden: `python -m app.seed` (veilig om opnieuw te draaien).

Bestaande taken met dezelfde naam worden overgeslagen. Taken krijgen geen
eerste vervaldatum: je weet niet wanneer ze laatst gedaan zijn, en anders
staan ze allemaal tegelijk op "te laat". Ze verschijnen onder Taken als
"nog geen datum" tot je ze afvinkt of een datum invult.
"""

import logging
import sys

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app import audit
from app.db import new_session
from app.models import Category, Task, Vehicle
from app.recurrence import IntervalUnit, RecurrenceType, format_months
from app.seed_data import AUTO_CATEGORY, TASKS

logger = logging.getLogger(__name__)


class SeedError(Exception):
    pass


def seed_tasks(db: Session) -> tuple[int, int]:
    """Voegt ontbrekende taken toe; geeft (toegevoegd, overgeslagen) terug."""
    categories = {c.name: c for c in db.scalars(select(Category))}
    missing = sorted({t.category for t in TASKS} - categories.keys())
    if missing:
        raise SeedError(f"Categorieën ontbreken: {', '.join(missing)}")
    existing = {n.lower() for n in db.scalars(select(func.lower(Task.name)))}

    added: list[str] = []
    vehicle: Vehicle | None = None
    for item in TASKS:
        if item.name.lower() in existing:
            continue
        if item.category == AUTO_CATEGORY and vehicle is None:
            vehicle = db.scalar(select(Vehicle).where(Vehicle.name == "Auto"))
            if vehicle is None:
                vehicle = Vehicle(name="Auto")
                db.add(vehicle)
        db.add(
            Task(
                name=item.name,
                vehicle=vehicle if item.category == AUTO_CATEGORY else None,
                km_interval=item.km if item.category == AUTO_CATEGORY else None,
                season_months=format_months(set(item.season or ())),
                category=categories[item.category],
                recurrence_type=RecurrenceType(item.recurrence),
                interval_every=item.every,
                interval_unit=IntervalUnit(item.unit),
                default_points=item.points,
                notes=item.notes,
                first_reminder_days=item.first_reminder_days,
            )
        )
        added.append(item.name)
    if added:
        audit.record(db, "task.seed", new={"added": len(added)})
    db.commit()
    return len(added), len(TASKS) - len(added)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with new_session() as db:
        if not inspect(db.get_bind()).has_table(Task.__tablename__):
            logger.error(
                "Database is nog niet gemigreerd: draai 'alembic upgrade head'."
            )
            return 1
        try:
            added, skipped = seed_tasks(db)
        except SeedError as exc:
            logger.error("%s", exc)
            return 1
    logger.info("Startvulling: %d taken toegevoegd, %d bestonden al.", added, skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
