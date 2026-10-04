"""Seizoensmeldingen, bijv. 'Gras maaien kan nog tot eind oktober'."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Task
from app.recurrence import MONTH_NAMES, into_season

MAX_NAMES = 3


@dataclass(frozen=True)
class SeasonNote:
    text: str
    ending: bool


def _names(names: list[str]) -> str:
    if len(names) > MAX_NAMES:
        shown = names[:MAX_NAMES]
        return ", ".join(shown) + f" en nog {len(names) - MAX_NAMES}"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " en " + names[-1]


def notes(db: Session, day: date) -> list[SeasonNote]:
    """Taken waarvan het seizoen deze maand eindigt of volgende maand begint.

    Taken met dezelfde maanden worden samengenomen in één zin.
    """
    this_month = day.month
    next_month = this_month % 12 + 1
    first_of_next = date(day.year + (this_month == 12), next_month, 1)
    ending: dict[int, list[str]] = defaultdict(list)  # herstartmaand → namen
    starting: list[str] = []
    tasks = db.scalars(
        select(Task)
        .where(Task.archived_at.is_(None), Task.season_months.is_not(None))
        .order_by(Task.name)
    )
    for task in tasks:
        season = task.season
        if season is None:
            continue
        if this_month in season and next_month not in season:
            ending[into_season(first_of_next, season).month].append(task.name)
        elif this_month not in season and next_month in season:
            starting.append(task.name)

    result = []
    month_name = MONTH_NAMES[this_month - 1]
    for restart, names in sorted(ending.items()):
        plural = len(names) > 1
        can = "kunnen" if plural else "kan"
        pause = "pauzeren ze" if plural else "pauzeert de taak"
        text = (
            f"{_names(names)} {can} nog tot eind {month_name}. "
            f"Daarna {pause} tot {MONTH_NAMES[restart - 1]}."
        )
        result.append(SeasonNote(text, True))
    if starting:
        result.append(
            SeasonNote(
                f"Seizoen begint in {MONTH_NAMES[next_month - 1]}: {_names(starting)}.",
                False,
            )
        )
    return result
