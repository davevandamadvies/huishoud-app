"""Afvinken: een uitvoering vastleggen en de volgende keer klaarzetten."""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import audit, settings_store, tasks
from app import points as app_points
from app.dates import today
from app.db import utcnow
from app.models import Occurrence, OccurrenceStatus, Performer, Task, User
from app.recurrence import next_due

# Hoe ver terug een afvinkdatum mag liggen (vergeten af te vinken).
MAX_DAYS_BACK = 60


class CompletionError(Exception):
    """Afvinken niet mogelijk; de tekst is geschikt voor de gebruiker."""


@dataclass
class CompletionResult:
    occurrence: Occurrence
    next_occurrence: Occurrence | None


def preview_next(db: Session, task: Task, completed_on: date) -> date | None:
    """Wat wordt de volgende vervaldatum als de taak nu wordt afgevinkt?"""
    pending = tasks.pending_occurrence(db, task)
    return next_due(task.rule, completed_on, pending.due_date if pending else None)


def complete(
    db: Session,
    actor: User,
    task: Task,
    *,
    performer_ids: list[int],
    completed_on: date | None = None,
    note: str | None = None,
    points: int | None = None,
) -> CompletionResult:
    if task.is_archived:
        raise CompletionError("Deze taak staat in het archief.")
    completed_on = completed_on or today()
    if completed_on > today():
        raise CompletionError("Afvinken kan niet in de toekomst.")
    if completed_on < today() - timedelta(days=MAX_DAYS_BACK):
        raise CompletionError(f"Afvinken kan tot {MAX_DAYS_BACK} dagen terug.")
    note = (note or "").strip() or None
    if note and len(note) > 500:
        raise CompletionError("De notitie mag maximaal 500 tekens zijn.")

    # Zonder competitie worden er geen punten geregistreerd.
    if not settings_store.competition_enabled(db):
        points = None
    try:
        app_points.validate(points)
    except app_points.PointsError as exc:
        raise CompletionError(str(exc)) from exc

    unique_ids = list(dict.fromkeys(performer_ids))
    if not unique_ids:
        raise CompletionError("Kies wie het heeft gedaan.")
    performers = db.scalars(select(User).where(User.id.in_(unique_ids))).all()
    if len(performers) != len(unique_ids) or not all(u.is_active for u in performers):
        raise CompletionError("Kies alleen actieve gebruikers.")

    # De openstaande uitvoering afronden, of een nieuwe vastleggen als de taak
    # niet openstond (ook toegestaan).
    occurrence = tasks.pending_occurrence(db, task)
    previous_due = occurrence.due_date if occurrence else None
    if occurrence is None:
        occurrence = Occurrence(task_id=task.id)
        db.add(occurrence)
    occurrence.status = OccurrenceStatus.DONE
    occurrence.completed_on = completed_on
    occurrence.completed_at = utcnow()
    occurrence.note = note
    occurrence.performers = [Performer(user_id=u.id) for u in performers]
    app_points.distribute(occurrence, points)
    db.flush()

    next_date = next_due(task.rule, completed_on, previous_due)
    next_occurrence = None
    if next_date is not None:
        next_occurrence = Occurrence(task_id=task.id, due_date=next_date)
        db.add(next_occurrence)
        db.flush()

    audit.record(
        db,
        "occurrence.complete",
        actor=actor,
        object_type="occurrence",
        object_id=occurrence.id,
        new={
            "task_id": task.id,
            "completed_on": completed_on.isoformat(),
            "performers": [u.id for u in performers],
            "points": points,
            "previous_due": previous_due.isoformat() if previous_due else None,
            "next_due": next_date.isoformat() if next_date else None,
        },
    )
    db.commit()
    return CompletionResult(occurrence, next_occurrence)


def history(db: Session, task: Task, limit: int = 10) -> list[Occurrence]:
    """Logboek: de laatst afgeronde uitvoeringen van een taak."""
    return list(
        db.scalars(
            select(Occurrence)
            .where(
                Occurrence.task_id == task.id,
                Occurrence.status == OccurrenceStatus.DONE,
            )
            .options(selectinload(Occurrence.performers).selectinload(Performer.user))
            .order_by(Occurrence.completed_on.desc(), Occurrence.id.desc())
            .limit(limit)
        )
    )


def default_points(db: Session, task: Task) -> int | None:
    """Voorstel in het afvinkpaneel: punten van de geplande keer, anders de taak."""
    pending = tasks.pending_occurrence(db, task)
    if pending is not None and pending.points is not None:
        return pending.points
    return task.default_points
