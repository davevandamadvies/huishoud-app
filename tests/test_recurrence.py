from datetime import date

import pytest

from app.recurrence import (
    IntervalUnit,
    RecurrenceType,
    Rule,
    add_interval,
    describe,
    next_due,
)

D, W, M = IntervalUnit.DAYS, IntervalUnit.WEEKS, IntervalUnit.MONTHS
INTERVAL, FIXED, ONCE = (
    RecurrenceType.INTERVAL,
    RecurrenceType.FIXED_DATE,
    RecurrenceType.ONCE,
)


@pytest.mark.parametrize(
    ("start", "every", "unit", "expected"),
    [
        (date(2026, 10, 3), 7, D, date(2026, 10, 10)),
        (date(2026, 12, 28), 7, D, date(2027, 1, 4)),
        (date(2026, 10, 3), 2, W, date(2026, 10, 17)),
        (date(2026, 1, 31), 1, M, date(2026, 2, 28)),
        (date(2028, 1, 31), 1, M, date(2028, 2, 29)),  # schrikkeljaar
        (date(2028, 2, 29), 12, M, date(2029, 2, 28)),
        (date(2026, 11, 15), 3, M, date(2027, 2, 15)),
        (date(2028, 2, 28), 1, D, date(2028, 2, 29)),
    ],
)
def test_add_interval(
    start: date, every: int, unit: IntervalUnit, expected: date
) -> None:
    assert add_interval(start, every, unit) == expected


def test_interval_counts_from_completion() -> None:
    rule = Rule(INTERVAL, 7)
    due = date(2026, 10, 10)
    # Op tijd, te laat en te vroeg: altijd afvinkdatum + interval
    assert next_due(rule, date(2026, 10, 10), due) == date(2026, 10, 17)
    assert next_due(rule, date(2026, 10, 14), due) == date(2026, 10, 21)
    assert next_due(rule, date(2026, 10, 8), due) == date(2026, 10, 15)


def test_interval_without_previous_due() -> None:
    assert next_due(Rule(INTERVAL, 14), date(2026, 10, 3), None) == date(2026, 10, 17)


def test_fixed_date_keeps_rhythm() -> None:
    apk = Rule(FIXED, 12, M)
    due = date(2027, 3, 15)
    # Eerder (2 maanden van tevoren) of later afvinken: volgende blijft 15 maart
    assert next_due(apk, date(2027, 1, 20), due) == date(2028, 3, 15)
    assert next_due(apk, date(2027, 3, 20), due) == date(2028, 3, 15)


def test_fixed_date_skips_missed_periods() -> None:
    rule = Rule(FIXED, 1, M)
    assert next_due(rule, date(2026, 6, 10), date(2026, 3, 1)) == date(2026, 7, 1)


def test_fixed_date_month_end_does_not_drift() -> None:
    rule = Rule(FIXED, 1, M)
    first = next_due(rule, date(2026, 1, 31), date(2026, 1, 31))
    assert first == date(2026, 2, 28)
    # Tellen vanaf de oorspronkelijke datum: maart blijft de 31e
    assert next_due(rule, date(2026, 2, 28), date(2026, 1, 31)) == date(2026, 3, 31)


def test_fixed_date_completed_on_due_date() -> None:
    rule = Rule(FIXED, 7)
    assert next_due(rule, date(2026, 10, 10), date(2026, 10, 10)) == date(2026, 10, 17)


def test_once_has_no_next() -> None:
    assert next_due(Rule(ONCE), date(2026, 10, 3), date(2026, 10, 1)) is None


@pytest.mark.parametrize("every", [None, 0, -3])
def test_repeating_rule_requires_interval(every: int | None) -> None:
    with pytest.raises(ValueError, match="interval"):
        Rule(INTERVAL, every)


@pytest.mark.parametrize(
    ("rule", "text"),
    [
        (Rule(INTERVAL, 7), "Elke 7 dagen"),
        (Rule(INTERVAL, 1), "Elke dag"),
        (Rule(INTERVAL, 1, W), "Elke week"),
        (Rule(INTERVAL, 3, M), "Elke 3 maanden"),
        (Rule(INTERVAL, 12, M), "Jaarlijks"),
        (Rule(INTERVAL, 24, M), "Elke 2 jaar"),
        (Rule(FIXED, 12, M), "Jaarlijks (vaste datum)"),
        (Rule(ONCE), "Eenmalig"),
    ],
)
def test_describe(rule: Rule, text: str) -> None:
    assert describe(rule) == text
