"""Gegevens voor het scherm Vandaag: te laat, vandaag, binnenkort."""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import Occurrence, OccurrenceStatus, Performer, Task

SOON_DAYS = 7
PENDING = (OccurrenceStatus.OPEN, OccurrenceStatus.PLANNED)


@dataclass
class TodayView:
    late: list[Occurrence] = field(default_factory=list)
    today: list[Occurrence] = field(default_factory=list)
    done_today: list[Occurrence] = field(default_factory=list)
    soon: list[Occurrence] = field(default_factory=list)
    week_done: int = 0
    week_total: int = 0

    @property
    def is_empty(self) -> bool:
        return not (self.late or self.today or self.done_today or self.soon)


def week_bounds(day: date) -> tuple[date, date]:
    """Maandag t/m zondag van de week waarin `day` valt."""
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def build(db: Session, day: date) -> TodayView:
    view = TodayView()
    monday, sunday = week_bounds(day)
    horizon = max(day + timedelta(days=SOON_DAYS), sunday)

    pending = db.scalars(
        select(Occurrence)
        .join(Task)
        .where(Occurrence.status.in_(PENDING), Task.archived_at.is_(None))
        .options(
            joinedload(Occurrence.task).joinedload(Task.category),
            joinedload(Occurrence.task).joinedload(Task.owner),
        )
    ).all()
    for occ in sorted(
        pending, key=lambda o: (o.effective_date or date.max, o.task.name)
    ):
        when = occ.effective_date
        if when is None or when > horizon:
            continue
        if when < day:
            view.late.append(occ)
        elif when == day:
            view.today.append(occ)
        elif when <= day + timedelta(days=SOON_DAYS):
            view.soon.append(occ)
        if when <= sunday:
            view.week_total += 1

    done_this_week = db.scalars(
        select(Occurrence)
        .where(
            Occurrence.status == OccurrenceStatus.DONE,
            Occurrence.completed_on >= monday,
            Occurrence.completed_on <= sunday,
        )
        .options(
            joinedload(Occurrence.task).joinedload(Task.category),
            selectinload(Occurrence.performers).joinedload(Performer.user),
        )
        .order_by(Occurrence.completed_at)
    ).all()
    view.week_done = len(done_this_week)
    view.week_total += view.week_done
    view.done_today = [o for o in done_this_week if o.completed_on == day]
    return view
