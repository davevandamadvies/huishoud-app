"""Gegevens voor het scherm Planning: maand of week, en het dagoverzicht."""

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import Occurrence, OccurrenceOwner, OccurrenceStatus, Task
from app.today_view import week_bounds


class Mode(StrEnum):
    MONTH = "maand"
    WEEK = "week"


MAX_DOTS = 3


@dataclass
class Day:
    date: date
    items: list[Occurrence] = field(default_factory=list)
    in_month: bool = True

    @property
    def has_items(self) -> bool:
        return bool(self.items)

    @property
    def dots(self) -> list[Occurrence]:
        return self.items[:MAX_DOTS]

    @property
    def more(self) -> int:
        return max(0, len(self.items) - MAX_DOTS)


@dataclass
class PlanningView:
    day: date
    mode: Mode
    days: list[Day]  # week: 7 dagen; maand: hele weken rond de maand
    items: list[Occurrence]

    @property
    def weeks(self) -> list[list[Day]]:
        return [self.days[i : i + 7] for i in range(0, len(self.days), 7)]

    @property
    def previous(self) -> date:
        if self.mode == Mode.WEEK:
            return self.day - timedelta(days=7)
        return _shift_month(self.day, -1)

    @property
    def next(self) -> date:
        if self.mode == Mode.WEEK:
            return self.day + timedelta(days=7)
        return _shift_month(self.day, 1)


def _shift_month(day: date, months: int) -> date:
    """Zelfde dag in een andere maand (31 jan + 1 maand = 28/29 feb)."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def month_bounds(day: date) -> tuple[date, date]:
    """Maandag vóór de 1e t/m zondag na de laatste dag van de maand."""
    first = day.replace(day=1)
    last = day.replace(day=calendar.monthrange(day.year, day.month)[1])
    return week_bounds(first)[0], week_bounds(last)[1]


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


def _sort_key(occurrence: Occurrence) -> tuple:
    planned_time = occurrence.planned_time
    return (planned_time is None, planned_time or time.max, occurrence.task.name)


def items_by_day(db: Session, start: date, end: date) -> dict[date, list[Occurrence]]:
    """Wat er per dag in de agenda staat."""
    result: dict[date, list[Occurrence]] = defaultdict(list)
    for occurrence in _planned(db, start, end):
        result[occurrence.planned_date].append(occurrence)
    for day_items in result.values():
        day_items.sort(key=_sort_key)
    return result


def build(db: Session, day: date, mode: Mode = Mode.MONTH) -> PlanningView:
    if mode == Mode.WEEK:
        start, end = week_bounds(day)
    else:
        start, end = month_bounds(day)
    per_day = items_by_day(db, start, end)
    days = [
        Day(d, per_day.get(d, []), mode == Mode.WEEK or d.month == day.month)
        for d in (start + timedelta(days=i) for i in range((end - start).days + 1))
    ]
    return PlanningView(day, mode, days, per_day.get(day, []))


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
