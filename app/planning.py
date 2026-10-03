"""Plannen: inplannen, verzetten en annuleren van een uitvoering.

- Inplannen maakt de openstaande uitvoering "gepland" (of een nieuwe, als de
  taak niet openstond). Nooit stapelen blijft gelden.
- De vervaldatum blijft bewaard: na afvinken rekent de herhaling vanaf de
  afvinkdatum (interval) of de vervaldatum (vaste datum), niet vanaf de plandatum.
- Een geplande keer die voorbij is blijft gepland en telt als "te laat".
"""

from dataclasses import dataclass
from datetime import date, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, tasks
from app.dates import today
from app.models import (
    Occurrence,
    OccurrenceOwner,
    OccurrenceStatus,
    Task,
    User,
)

MAX_DAYS_AHEAD = 366


class PlanningError(Exception):
    """Plannen niet mogelijk; de tekst is geschikt voor de gebruiker."""


@dataclass
class PlanInput:
    planned_date: date
    planned_time: time | None = None
    owner_ids: tuple[int, ...] = ()
    points: int | None = None


def _validate(db: Session, data: PlanInput, current: date | None = None) -> list[User]:
    # Een al geplande datum in het verleden mag blijven staan bij het verzetten
    # van alleen tijd of eigenaren.
    if data.planned_date < today() and data.planned_date != current:
        raise PlanningError("Kies een datum vanaf vandaag.")
    if data.planned_date > today() + timedelta(days=MAX_DAYS_AHEAD):
        raise PlanningError("Plannen kan tot maximaal een jaar vooruit.")
    if data.points is not None and not 1 <= data.points <= 100:
        raise PlanningError("Punten: een heel getal van 1 tot 100, of leeg.")
    ids = list(dict.fromkeys(data.owner_ids))
    if not ids:
        return []
    owners = list(db.scalars(select(User).where(User.id.in_(ids))))
    if len(owners) != len(ids) or not all(u.is_active for u in owners):
        raise PlanningError("Kies alleen actieve gebruikers als eigenaar.")
    return sorted(owners, key=lambda u: u.id)


def _snapshot(occurrence: Occurrence) -> dict:
    return {
        "planned_date": _iso(occurrence.planned_date),
        "planned_time": occurrence.planned_time.strftime("%H:%M")
        if occurrence.planned_time
        else None,
        "owners": [o.user_id for o in occurrence.owners],
        "points": occurrence.points,
    }


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _apply(occurrence: Occurrence, data: PlanInput, owners: list[User]) -> None:
    occurrence.status = OccurrenceStatus.PLANNED
    occurrence.planned_date = data.planned_date
    occurrence.planned_time = data.planned_time
    occurrence.points = data.points
    occurrence.owners = [OccurrenceOwner(user_id=u.id) for u in owners]


def plan(db: Session, actor: User, task: Task, data: PlanInput) -> Occurrence:
    if task.is_archived:
        raise PlanningError("Deze taak staat in het archief.")
    owners = _validate(db, data)
    occurrence = tasks.pending_occurrence(db, task)
    if occurrence is not None and occurrence.status == OccurrenceStatus.PLANNED:
        raise PlanningError("Deze taak is al ingepland; verzet hem in plaats daarvan.")
    if occurrence is None:
        occurrence = Occurrence(task_id=task.id)
        db.add(occurrence)
    if data.points is None:
        data = PlanInput(
            data.planned_date, data.planned_time, data.owner_ids, task.default_points
        )
    _apply(occurrence, data, owners)
    db.flush()
    audit.record(
        db,
        "occurrence.plan",
        actor=actor,
        object_type="occurrence",
        object_id=occurrence.id,
        new={"task_id": task.id, **_snapshot(occurrence)},
    )
    db.commit()
    return occurrence


def reschedule(
    db: Session, actor: User, occurrence: Occurrence, data: PlanInput
) -> None:
    if occurrence.status != OccurrenceStatus.PLANNED:
        raise PlanningError("Deze taak is niet ingepland.")
    owners = _validate(db, data, current=occurrence.planned_date)
    old = _snapshot(occurrence)
    _apply(occurrence, data, owners)
    db.flush()
    new = _snapshot(occurrence)
    if old != new:
        audit.record(
            db,
            "occurrence.reschedule",
            actor=actor,
            object_type="occurrence",
            object_id=occurrence.id,
            old=old,
            new=new,
        )
    db.commit()


def cancel(db: Session, actor: User, occurrence: Occurrence) -> None:
    """Terug naar open. Zonder vervaldatum vervalt de uitvoering helemaal."""
    if occurrence.status != OccurrenceStatus.PLANNED:
        raise PlanningError("Deze taak is niet ingepland.")
    audit.record(
        db,
        "occurrence.cancel_plan",
        actor=actor,
        object_type="occurrence",
        object_id=occurrence.id,
        old=_snapshot(occurrence),
    )
    if occurrence.due_date is None:
        db.delete(occurrence)
    else:
        occurrence.status = OccurrenceStatus.OPEN
        occurrence.planned_date = None
        occurrence.planned_time = None
        occurrence.points = None
        occurrence.owners = []
    db.commit()
