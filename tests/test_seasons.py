from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import completion, reminder_content, reminders, seasons, tasks
from app.dates import today
from app.models import User
from app.recurrence import (
    RecurrenceType,
    Rule,
    describe_season,
    format_months,
    into_season,
    next_due,
    parse_months,
)
from tests.factories import make_task

GARDEN = frozenset(range(3, 11))  # mrt–okt
WINTER = frozenset({10, 11, 12, 1, 2})  # okt–feb


def test_parse_and_format_months() -> None:
    assert parse_months("3,4,5") == {3, 4, 5}
    assert parse_months("") is None
    assert parse_months(",".join(str(m) for m in range(1, 13))) is None
    assert parse_months("0,13,x") is None
    assert format_months({5, 3}) == "3,5"
    assert format_months(set(range(1, 13))) is None


@pytest.mark.parametrize(
    ("season", "text"),
    [
        (GARDEN, "mrt–okt"),
        (WINTER, "okt–feb"),
        (frozenset({3, 4, 9}), "mrt–apr, sep"),
        (frozenset({11}), "nov"),
        (None, None),
    ],
)
def test_describe_season(season, text) -> None:
    assert describe_season(season) == text


@pytest.mark.parametrize(
    ("day", "season", "expected"),
    [
        (date(2026, 6, 15), GARDEN, date(2026, 6, 15)),
        (date(2026, 11, 3), GARDEN, date(2027, 3, 1)),
        (date(2026, 1, 20), GARDEN, date(2026, 3, 1)),
        (date(2026, 5, 3), WINTER, date(2026, 10, 1)),
        (date(2026, 12, 3), WINTER, date(2026, 12, 3)),
        (date(2026, 3, 1), WINTER, date(2026, 10, 1)),
        (date(2026, 3, 1), None, date(2026, 3, 1)),
    ],
)
def test_into_season(day: date, season, expected: date) -> None:
    assert into_season(day, season) == expected


def test_next_due_shifts_into_season() -> None:
    rule = Rule(RecurrenceType.INTERVAL, 7)
    assert next_due(rule, date(2026, 10, 28), None, GARDEN) == date(2027, 3, 1)
    assert next_due(rule, date(2026, 10, 10), None, GARDEN) == date(2026, 10, 17)


def test_completion_uses_season(db: Session, user: User) -> None:
    task = make_task(db, name="Gras", due=today(), season_months="3,4,5,6,7,8,9,10")
    day = today()
    result = completion.complete(db, user, task, performer_ids=[user.id])
    expected = into_season(day + timedelta(days=7), GARDEN)
    assert result.next_occurrence.due_date == expected


def test_recurrence_text_includes_season(db: Session) -> None:
    task = make_task(db, name="Gras", season_months="3,4,5,6,7,8,9,10")
    assert task.recurrence_text == "Elke 7 dagen · pauze nov–feb"


def _form(category_id: int, **extra) -> dict:
    return {
        "name": "Gras maaien",
        "category_id": str(category_id),
        "recurrence_type": "interval",
        "interval_every": "7",
        "interval_unit": "days",
        **extra,
    }


def test_plan_sheet_warns_outside_season(client: TestClient, db: Session) -> None:
    task = make_task(db, name="Gras", season_months="3,4,5,6,7,8,9,10")
    out = date(today().year + 1, 1, 10)
    response = client.get(
        f"/taken/{task.id}/inplannen/controle", params={"planned_date": out.isoformat()}
    )
    assert "Buiten het seizoen (mrt–okt)" in response.text
    inside = date(today().year + 1, 5, 10)
    response = client.get(
        f"/taken/{task.id}/inplannen/controle",
        params={"planned_date": inside.isoformat()},
    )
    assert "seizoen" not in response.text


def test_plan_sheet_suggests_date_in_season(client: TestClient, db: Session) -> None:
    month = today().month
    season = str(month % 12 + 2 if month % 12 + 2 <= 12 else (month % 12 + 2) - 12)
    task = make_task(db, name="Snoeien", season_months=season)
    html = client.get(f"/taken/{task.id}/inplannen").text
    expected = into_season(today() + timedelta(days=1), parse_months(season))
    assert f'value="{expected.isoformat()}"' in html


def test_no_task_reminders_outside_season(db: Session, user: User) -> None:
    from app.reminder_scheduler import task_reason

    preference = reminders.get(db, user)
    preference.task_late_daily = True
    task = make_task(
        db, name="Gras", due=date(2026, 10, 20), season_months="3,4,5,6,7,8,9,10"
    )
    occurrence = tasks.pending_occurrence(db, task)
    # De reden bestaat nog, maar de planner slaat taken buiten seizoen over.
    assert task_reason(occurrence, date(2026, 11, 5), preference) == "late"


def test_scheduler_skips_out_of_season(db: Session, user: User, vapid) -> None:
    import httpx

    from app import push, reminder_scheduler
    from tests.push_helpers import Browser

    browser = Browser()
    push.subscribe(
        db,
        user,
        endpoint="https://fcm.googleapis.com/fcm/send/x",
        p256dh=browser.p256dh,
        auth=browser.auth_b64,
        label="Telefoon",
    )
    preference = reminders.get(db, user)
    preference.task_late_daily = True
    preference.update_enabled = False
    db.add(preference)
    db.commit()
    make_task(db, name="Gras", due=date(2026, 10, 20), season_months="3,4,5,6,7,8,9,10")
    transport = httpx.MockTransport(lambda request: httpx.Response(201))
    assert (
        reminder_scheduler.run(db, datetime(2026, 11, 5, 8, 30), transport=transport)
        == 0
    )
    assert (
        reminder_scheduler.run(db, datetime(2026, 10, 25, 8, 30), transport=transport)
        == 1
    )


def test_update_ignores_late_tasks_out_of_season(db: Session, user: User) -> None:
    make_task(db, name="Gras", due=date(2026, 10, 20), season_months="3,4,5,6,7,8,9,10")
    make_task(db, name="Ramen", due=date(2026, 11, 1))
    message = reminder_content.update_message(
        db,
        user,
        date(2026, 11, 5),
        0,
        lookahead=3,
        only_mine=False,
        muted=set(),
        pending=reminder_content.pending_occurrences(db),
    )
    assert "1 loopt achter (Ramen)" in message.body


def test_season_notes(db: Session) -> None:
    make_task(db, name="Gras maaien", season_months="3,4,5,6,7,8,9,10")
    make_task(db, name="Heg snoeien", season_months="5,6,7,8,9")
    make_task(db, name="Stofzuigen")
    october = seasons.notes(db, date(2026, 10, 4))
    assert [n.text for n in october] == [
        "Gras maaien kan nog tot eind oktober. Daarna pauzeert de taak tot maart."
    ]
    april = seasons.notes(db, date(2026, 4, 4))
    assert [n.text for n in april] == ["Seizoen begint in mei: Heg snoeien."]


def test_season_notes_are_grouped(db: Session) -> None:
    for name in ("Gras maaien", "Gazon bemesten", "Ramen buiten", "Heg"):
        make_task(db, name=name, season_months="3,4,5,6,7,8,9,10")
    make_task(db, name="Bladeren", season_months="10")
    texts = [n.text for n in seasons.notes(db, date(2026, 10, 4))]
    assert texts == [
        "Gazon bemesten, Gras maaien, Heg en nog 1 kunnen nog tot eind oktober. "
        "Daarna pauzeren ze tot maart.",
        "Bladeren kan nog tot eind oktober. Daarna pauzeert de taak tot oktober.",
    ]


def test_planning_shows_season_notes(client: TestClient, db: Session) -> None:
    month = today().month
    make_task(db, name="Klusje", season_months=str(month))
    assert "Klusje kan nog tot eind" in client.get("/planning").text
