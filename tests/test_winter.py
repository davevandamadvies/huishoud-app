from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.recurrence import (
    DEFAULT_WINTER,
    IntervalUnit,
    RecurrenceType,
    Rule,
    describe,
    next_due,
)
from tests.factories import make_task

PLANTS = Rule(RecurrenceType.INTERVAL, 7, winter_every=14)


@pytest.mark.parametrize(
    ("completed", "expected"),
    [
        (date(2026, 7, 1), date(2026, 7, 8)),  # zomer
        (date(2026, 11, 1), date(2026, 11, 15)),  # winter
        (date(2026, 10, 31), date(2026, 11, 7)),  # laatste dag zonder winter
        (date(2027, 2, 28), date(2027, 3, 14)),  # laatste winterdag
        (date(2027, 3, 1), date(2027, 3, 8)),
    ],
)
def test_interval_of_completion_month(completed: date, expected: date) -> None:
    assert next_due(PLANTS, completed, None) == expected


def test_own_winter_months() -> None:
    rule = Rule(
        RecurrenceType.INTERVAL, 3, winter_every=5, winter_months=frozenset({12})
    )
    assert next_due(rule, date(2026, 11, 10), None) == date(2026, 11, 13)
    assert next_due(rule, date(2026, 12, 10), None) == date(2026, 12, 15)


def test_winter_ignored_for_fixed_date() -> None:
    rule = Rule(RecurrenceType.FIXED_DATE, 12, IntervalUnit.MONTHS, winter_every=6)
    assert next_due(rule, date(2026, 12, 1), date(2026, 12, 5)) == date(2027, 12, 5)


def test_describe() -> None:
    assert describe(PLANTS) == "Elke 7 dagen · nov–feb elke 14 dagen"
    weeks = Rule(RecurrenceType.INTERVAL, 1, IntervalUnit.WEEKS, winter_every=1)
    assert describe(weeks) == "Elke week · nov–feb elke 1 week"
    own = Rule(
        RecurrenceType.INTERVAL, 3, winter_every=5, winter_months=frozenset({12, 1, 2})
    )
    assert describe(own) == "Elke 3 dagen · dec–feb elke 5 dagen"


def test_task_rule_uses_default_winter(db: Session) -> None:
    task = make_task(db, name="Planten", winter_every=14)
    assert task.rule.winter_months == DEFAULT_WINTER
    assert task.recurrence_text == "Elke 7 dagen · nov–feb elke 14 dagen"
