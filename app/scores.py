"""Scorebord: punten per persoon per periode en de laatste puntenregels."""

import calendar
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import (
    AuditLog,
    Occurrence,
    OccurrenceStatus,
    Performer,
    Task,
    User,
    UserStatus,
)
from app.today_view import week_bounds


class Period(StrEnum):
    WEEK = "week"
    MONTH = "maand"
    TOTAL = "totaal"


def bounds(period: Period, day: date) -> tuple[date | None, date | None]:
    if period == Period.WEEK:
        return week_bounds(day)
    if period == Period.MONTH:
        last = calendar.monthrange(day.year, day.month)[1]
        return day.replace(day=1), day.replace(day=last)
    return None, None


@dataclass
class Standing:
    user: User
    points: int


@dataclass
class Entry:
    """Regel in "Laatste punten": een afgevinkte taak of een puntwijziging."""

    when: datetime
    kind: str  # "done" of "change"
    task: Task | None
    users: list[User] = field(default_factory=list)
    points: int | None = None
    each: int | None = None
    old: int | None = None
    new: int | None = None
    actor: User | None = None


@dataclass
class Scoreboard:
    standings: list[Standing]
    entries: list[Entry]

    @property
    def leader(self) -> Standing | None:
        """De koploper, of None bij gelijke stand of nog geen punten."""
        ranked = sorted(self.standings, key=lambda s: s.points, reverse=True)
        if not ranked or ranked[0].points == 0:
            return None
        if len(ranked) > 1 and ranked[1].points == ranked[0].points:
            return None
        return ranked[0]

    @property
    def top(self) -> int:
        return max((s.points for s in self.standings), default=0)


def standings(
    db: Session,
    start: date | None,
    end: date | None,
    category_id: int | None = None,
) -> list[Standing]:
    query = (
        select(Performer.user_id, func.coalesce(func.sum(Performer.points), 0))
        .join(Occurrence, Occurrence.id == Performer.occurrence_id)
        .join(Task, Task.id == Occurrence.task_id)
        .where(Occurrence.status == OccurrenceStatus.DONE)
        .group_by(Performer.user_id)
    )
    if start is not None:
        query = query.where(Occurrence.completed_on >= start)
    if end is not None:
        query = query.where(Occurrence.completed_on <= end)
    if category_id is not None:
        query = query.where(Task.category_id == category_id)
    totals = dict(db.execute(query).all())
    users = db.scalars(
        select(User).where(User.status == UserStatus.ACTIVE).order_by(User.id)
    )
    return [Standing(u, int(totals.get(u.id, 0))) for u in users]


def _entries(
    db: Session,
    start: date | None,
    end: date | None,
    category_id: int | None,
    limit: int,
) -> list[Entry]:
    query = (
        select(Occurrence)
        .join(Task)
        .where(
            Occurrence.status == OccurrenceStatus.DONE,
            Occurrence.points.is_not(None),
        )
        .options(
            joinedload(Occurrence.task).joinedload(Task.category),
            selectinload(Occurrence.performers).joinedload(Performer.user),
        )
        .order_by(Occurrence.completed_at.desc())
        .limit(limit)
    )
    if start is not None:
        query = query.where(Occurrence.completed_on >= start)
    if end is not None:
        query = query.where(Occurrence.completed_on <= end)
    if category_id is not None:
        query = query.where(Task.category_id == category_id)
    entries = [
        Entry(
            when=o.completed_at or datetime.min.replace(tzinfo=UTC),
            kind="done",
            task=o.task,
            users=[p.user for p in o.performers],
            points=o.points,
            each=o.performers[0].points if o.performers else None,
        )
        for o in db.scalars(query)
    ]

    changes = db.scalars(
        select(AuditLog)
        .where(AuditLog.action == "points.change")
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    for log in changes:
        task_id = (log.new_value or {}).get("task_id")
        task = db.get(Task, task_id) if task_id else None
        if category_id is not None and (
            task is None or task.category_id != category_id
        ):
            continue
        local_day = log.created_at.date()
        if (start and local_day < start) or (end and local_day > end):
            continue
        entries.append(
            Entry(
                when=log.created_at,
                kind="change",
                task=task,
                old=(log.old_value or {}).get("points"),
                new=(log.new_value or {}).get("points"),
                actor=db.get(User, log.actor_id) if log.actor_id else None,
            )
        )
    entries.sort(key=lambda e: e.when, reverse=True)
    return entries[:limit]


def build(
    db: Session,
    period: Period,
    day: date,
    category_id: int | None = None,
    limit: int = 15,
) -> Scoreboard:
    start, end = bounds(period, day)
    return Scoreboard(
        standings(db, start, end, category_id),
        _entries(db, start, end, category_id, limit),
    )
