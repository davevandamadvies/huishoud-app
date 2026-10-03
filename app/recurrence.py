"""Herhalingsregels (pure functies, geen database).

- interval: volgende vervaldatum = afvinkdatum + interval. Eerder of later
  afvinken schuift de volgende keer mee.
- vaste datum: de vervaldatum ligt vast (bijv. APK). Volgende = oude
  vervaldatum + interval, zo vaak als nodig tot ná de afvinkdatum.
- eenmalig: geen volgende keer.
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


def next_due(rule: Rule, completed_on: date, previous_due: date | None) -> date | None:
    """Vervaldatum van de volgende keer na afvinken op `completed_on`."""
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
