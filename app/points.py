"""Punten: verdeling over uitvoerders en correcties achteraf."""

import math

from sqlalchemy.orm import Session

from app import audit
from app.models import Occurrence, OccurrenceStatus, User

MAX_POINTS = 100


class PointsError(Exception):
    """Ongeldige punten; de tekst is geschikt voor de gebruiker."""


def validate(points: int | None) -> int | None:
    if points is not None and not 1 <= points <= MAX_POINTS:
        raise PointsError(f"Punten: een heel getal van 1 tot {MAX_POINTS}, of leeg.")
    return points


def share(points: int | None, performers: int) -> int | None:
    """Punten per persoon: verdeeld en naar boven afgerond (5 / 2 = 3)."""
    if points is None or performers <= 0:
        return None
    return math.ceil(points / performers)


def distribute(occurrence: Occurrence, points: int | None) -> None:
    occurrence.points = points
    each = share(points, len(occurrence.performers))
    for performer in occurrence.performers:
        performer.points = each


def correct(
    db: Session,
    actor: User,
    occurrence: Occurrence,
    points: int | None,
    reason: str | None = None,
) -> None:
    """Punten van een afgeronde keer aanpassen (puntenmutatie in de audit log)."""
    if occurrence.status != OccurrenceStatus.DONE:
        raise PointsError("Alleen punten van een afgeronde taak zijn aan te passen.")
    validate(points)
    reason = (reason or "").strip() or None
    if reason and len(reason) > 200:
        raise PointsError("De reden mag maximaal 200 tekens zijn.")
    old = occurrence.points
    if old == points:
        return
    distribute(occurrence, points)
    audit.record(
        db,
        "points.change",
        actor=actor,
        object_type="occurrence",
        object_id=occurrence.id,
        old={"points": old},
        new={"points": points, "reason": reason, "task_id": occurrence.task_id},
    )
    db.commit()
