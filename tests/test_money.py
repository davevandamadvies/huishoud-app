from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import completion, money
from app.dates import today
from app.models import AuditLog, Occurrence, OccurrenceStatus, User
from tests.conftest import HTMX_HEADERS
from tests.factories import make_task


@pytest.mark.parametrize(
    ("raw", "cents"),
    [
        ("89,50", 8950),
        ("89.50", 8950),
        ("€ 12", 1200),
        ("0,5", 50),
        ("1.234,50", 123450),
        ("1.234", 123400),
        ("1234.5", 123450),
        ("", None),
        ("  ", None),
    ],
)
def test_parse_euro(raw: str, cents: int | None) -> None:
    assert money.parse_euro(raw) == cents


@pytest.mark.parametrize("raw", ["abc", "12,345", "-5", "1,2,3", "100000,01"])
def test_parse_euro_invalid(raw: str) -> None:
    with pytest.raises(money.MoneyError):
        money.parse_euro(raw)


def test_format_euro() -> None:
    assert money.format_euro(8950) == "€ 89,50"
    assert money.format_euro(123450) == "€ 1.234,50"
    assert money.format_euro(5) == "€ 0,05"
    assert money.format_euro(None) == ""
    assert money.input_value(8950) == "89,50"


def test_complete_with_cost(db: Session, user: User) -> None:
    task = make_task(db, name="APK", due=today())
    result = completion.complete(
        db, user, task, performer_ids=[user.id], cost_cents=8950
    )
    assert result.occurrence.cost_cents == 8950


def test_correct_cost_is_audited(db: Session, user: User) -> None:
    task = make_task(db, name="APK", due=today())
    occurrence = completion.complete(db, user, task, performer_ids=[user.id]).occurrence
    money.correct(db, user, occurrence, 4500)
    money.correct(db, user, occurrence, 4500)  # geen wijziging, geen regel
    entries = db.scalars(
        select(AuditLog).where(AuditLog.action == "occurrence.cost")
    ).all()
    assert len(entries) == 1
    assert entries[0].new_value == {"cost_cents": 4500}


def test_task_totals(db: Session, user: User) -> None:
    task = make_task(db, name="APK")
    for completed, cents in (
        (date(today().year, 1, 2), 1000),
        (date(today().year - 1, 6, 1), 2500),
    ):
        db.add(
            Occurrence(
                task_id=task.id,
                status=OccurrenceStatus.DONE,
                completed_on=completed,
                cost_cents=cents,
            )
        )
    db.add(Occurrence(task_id=task.id, due_date=today(), cost_cents=999))
    db.commit()
    assert money.task_totals(db, task, today().year) == (1000, 3500)


def test_complete_sheet_has_cost(client: TestClient, db: Session, user: User) -> None:
    task = make_task(db, name="APK", due=today())
    assert 'name="cost"' in client.get(f"/taken/{task.id}/afronden").text
    response = client.post(
        f"/taken/{task.id}/afronden",
        data={
            "performer": [str(user.id)],
            "completed_on": today().isoformat(),
            "cost": "abc",
        },
        headers=HTMX_HEADERS,
    )
    assert "Vul een bedrag in" in response.text
    client.post(
        f"/taken/{task.id}/afronden",
        data={
            "performer": [str(user.id)],
            "completed_on": today().isoformat(),
            "cost": "89,50",
        },
        headers=HTMX_HEADERS,
    )
    cost = db.scalar(
        select(Occurrence.cost_cents).where(Occurrence.status == OccurrenceStatus.DONE)
    )
    assert cost == 8950
    page = client.get(f"/taken/{task.id}").text
    assert "€ 89,50" in page
    assert "kosten dit jaar € 89,50" in page


def test_correct_cost_via_logbook(client: TestClient, db: Session, user: User) -> None:
    task = make_task(db, name="APK", due=today() - timedelta(days=1))
    occurrence = completion.complete(db, user, task, performer_ids=[user.id]).occurrence
    url = f"/taken/{task.id}/logboek/{occurrence.id}/kosten"
    assert client.post(url, data={"cost": "x"}, headers=HTMX_HEADERS).status_code == 422
    response = client.post(url, data={"cost": "12,50"}, headers=HTMX_HEADERS)
    assert response.status_code == 204
    db.expire_all()
    assert occurrence.cost_cents == 1250
    other = make_task(db, name="Ander")
    wrong = f"/taken/{other.id}/logboek/{occurrence.id}/kosten"
    assert (
        client.post(wrong, data={"cost": "1"}, headers=HTMX_HEADERS).status_code == 404
    )
