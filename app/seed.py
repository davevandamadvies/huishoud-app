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
from app.models import Category, Task
from app.recurrence import IntervalUnit, RecurrenceType
from app.seed_data import TASKS

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
    for item in TASKS:
        if item.name.lower() in existing:
            continue
        db.add(
            Task(
                name=item.name,
                category=categories[item.category],
                recurrence_type=RecurrenceType(item.recurrence),
                interval_every=item.every,
                interval_unit=IntervalUnit(item.unit),
                default_points=item.points,
                notes=item.notes,
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
