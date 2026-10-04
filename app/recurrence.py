"""Herhalingsregels (pure functies, geen database).

- interval: volgende vervaldatum = afvinkdatum + interval. Eerder of later
  afvinken schuift de volgende keer mee.
- vaste datum: de vervaldatum ligt vast (bijv. APK). Volgende = oude
  vervaldatum + interval, zo vaak als nodig tot ná de afvinkdatum.
- eenmalig: geen volgende keer.
- seizoen: valt de volgende datum buiten de actieve maanden, dan schuift
  hij naar de 1e van de eerste maand van het volgende seizoen.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum


class RecurrenceType(StrEnum):
    INTERVAL = "interval"
    FIXED_DATE = "fixed_date"
    ONCE = "once"


class IntervalUnit(StrEnum):
    DAYS = "days"
    WEEKS = "weeks"
    MONTHS = "months"


@dataclass(frozen=True)
class Rule:
    type: RecurrenceType
    every: int | None = None
    unit: IntervalUnit = IntervalUnit.DAYS

    def __post_init__(self) -> None:
        repeating = self.type != RecurrenceType.ONCE
        if repeating and (self.every is None or self.every < 1):
            raise ValueError("Een herhalende taak heeft een interval van minimaal 1.")


def add_interval(start: date, every: int, unit: IntervalUnit) -> date:
    """Tel een interval op; bij maanden valt 31 jan + 1 maand op 28/29 feb."""
    if unit == IntervalUnit.DAYS:
        return start + timedelta(days=every)
    if unit == IntervalUnit.WEEKS:
        return start + timedelta(weeks=every)
    month_index = start.month - 1 + every
    year, month = start.year + month_index // 12, month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def next_due(
    rule: Rule,
    completed_on: date,
    previous_due: date | None,
    season: frozenset[int] | None = None,
) -> date | None:
    """Vervaldatum van de volgende keer na afvinken op `completed_on`."""
    due = _next_due(rule, completed_on, previous_due)
    return None if due is None else into_season(due, season)


def _next_due(rule: Rule, completed_on: date, previous_due: date | None) -> date | None:
    if rule.type == RecurrenceType.ONCE:
        return None
    every = rule.every or 1  # altijd gezet voor herhalende regels
    if rule.type == RecurrenceType.INTERVAL or previous_due is None:
        return add_interval(completed_on, every, rule.unit)
    # Vaste datum: blijf op het ritme van de vorige vervaldatum. Er wordt steeds
    # vanaf die datum geteld (niet stap voor stap), zodat een gemiste periode
    # bij maandintervallen niet extra wegloopt.
    steps = 1
    candidate = add_interval(previous_due, every * steps, rule.unit)
    while candidate <= completed_on:
        steps += 1
        candidate = add_interval(previous_due, every * steps, rule.unit)
    return candidate


MONTH_ABBR = (
    "jan",
    "feb",
    "mrt",
    "apr",
    "mei",
    "jun",
    "jul",
    "aug",
    "sep",
    "okt",
    "nov",
    "dec",
)
MONTH_NAMES = (
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
)


def parse_months(value: str | None) -> frozenset[int] | None:
    """'3,4,5' → {3, 4, 5}; leeg of alle 12 → None (het hele jaar)."""
    if not value:
        return None
    months = frozenset(int(m) for m in value.split(",") if m.strip().isdigit())
    months = frozenset(m for m in months if 1 <= m <= 12)
    return months if months and len(months) < 12 else None


def format_months(months: frozenset[int] | set[int] | None) -> str | None:
    """Voor opslag: {3, 4} → '3,4'."""
    if not months or len(months) == 12:
        return None
    return ",".join(str(m) for m in sorted(months))


def in_season(day: date, season: frozenset[int] | None) -> bool:
    return season is None or day.month in season


def into_season(day: date, season: frozenset[int] | None) -> date:
    """Datum zelf als die in het seizoen valt, anders het volgende begin."""
    if season is None or day.month in season:
        return day
    year, month = day.year, day.month
    for _ in range(12):
        month += 1
        if month > 12:
            year, month = year + 1, 1
        if month in season:
            return date(year, month, 1)
    return day


def season_runs(season: frozenset[int]) -> list[tuple[int, int]]:
    """Aaneengesloten reeksen maanden (ook over de jaarwisseling)."""
    starts = [m for m in sorted(season) if (m - 2) % 12 + 1 not in season]
    runs = []
    for start in starts:
        end = start
        while end % 12 + 1 in season and end % 12 + 1 != start:
            end = end % 12 + 1
        runs.append((start, end))
    return runs


def describe_season(season: frozenset[int] | None) -> str | None:
    """Bijv. 'mrt–okt', 'okt–feb' of 'mrt–apr, sep'."""
    if season is None:
        return None
    parts = []
    for start, end in season_runs(season):
        if start == end:
            parts.append(MONTH_ABBR[start - 1])
        else:
            parts.append(f"{MONTH_ABBR[start - 1]}–{MONTH_ABBR[end - 1]}")
    return ", ".join(parts)


_SINGULAR = {
    IntervalUnit.DAYS: "Elke dag",
    IntervalUnit.WEEKS: "Elke week",
    IntervalUnit.MONTHS: "Elke maand",
}
_PLURAL = {
    IntervalUnit.DAYS: "dagen",
    IntervalUnit.WEEKS: "weken",
    IntervalUnit.MONTHS: "maanden",
}


def describe(rule: Rule) -> str:
    """Bijv. 'Elke 7 dagen', 'Elke week', 'Jaarlijks', 'Eenmalig'."""
    if rule.type == RecurrenceType.ONCE:
        return "Eenmalig"
    n, unit = rule.every or 1, rule.unit
    if unit == IntervalUnit.MONTHS and n % 12 == 0:
        text = "Jaarlijks" if n == 12 else f"Elke {n // 12} jaar"
    elif n == 1:
        text = _SINGULAR[unit]
    else:
        text = f"Elke {n} {_PLURAL[unit]}"
    if rule.type == RecurrenceType.FIXED_DATE:
        text += " (vaste datum)"
    return text
