"""Gegevens voor het scherm Planning: weekstrip en dagoverzicht."""

from dataclasses import dataclass
from datetime import date, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import Occurrence, OccurrenceOwner, OccurrenceStatus, Task
from app.today_view import week_bounds


@dataclass
class Day:
    date: date
    has_items: bool


@dataclass
class PlanningView:
    day: date
    days: list[Day]
    items: list[Occurrence]

    @property
    def previous_week(self) -> date:
        return self.day - timedelta(days=7)

    @property
    def next_week(self) -> date:
        return self.day + timedelta(days=7)


def _planned(db: Session, start: date, end: date) -> list[Occurrence]:
    return list(
        db.scalars(
            select(Occurrence)
            .join(Task)
            .where(
                Occurrence.status == OccurrenceStatus.PLANNED,
                Occurrence.planned_date >= start,
                Occurrence.planned_date <= end,
                Task.archived_at.is_(None),
            )
            .options(
                joinedload(Occurrence.task).joinedload(Task.category),
                joinedload(Occurrence.task).joinedload(Task.owner),
                selectinload(Occurrence.owners).joinedload(OccurrenceOwner.user),
            )
        )
    )


def build(db: Session, day: date) -> PlanningView:
    monday, sunday = week_bounds(day)
    planned = _planned(db, monday, sunday)
    dates_with_items = {o.planned_date for o in planned}
    days = [
        Day(d, d in dates_with_items)
        for d in (monday + timedelta(days=i) for i in range(7))
    ]
    items = sorted(
        (o for o in planned if o.planned_date == day),
        key=lambda o: (o.planned_time is None, o.planned_time or time.max, o.task.name),
    )
    return PlanningView(day, days, items)


def plannable_tasks(
    db: Session, *, search: str = "", category_id: int | None = None
) -> list[Task]:
    """Actieve taken die nog niet zijn ingepland (voor "Plan een taak")."""
    planned_task_ids = select(Occurrence.task_id).where(
        Occurrence.status == OccurrenceStatus.PLANNED
    )
    query = (
        select(Task)
        .where(Task.archived_at.is_(None), Task.id.not_in(planned_task_ids))
        .options(joinedload(Task.category))
        .order_by(func.lower(Task.name))
    )
    if search:
        query = query.where(func.lower(Task.name).like(f"%{search.lower()}%"))
    if category_id is not None:
        query = query.where(Task.category_id == category_id)
    return list(db.scalars(query))
