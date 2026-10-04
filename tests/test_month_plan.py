"""Formulierblok 'Andere frequentie per maand' (seizoen + winter in één)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import tasks
from app.dates import today
from app.models import Task
from tests.conftest import HTMX_HEADERS
from tests.factories import make_category, make_task


def _form(category_id: int, states: dict[int, str] | None = None, **extra) -> dict:
    data = {
        "name": "Planten water",
        "category_id": str(category_id),
        "recurrence_type": "interval",
        "interval_every": "7",
        "interval_unit": "days",
    }
    if states is not None:
        data["month_plan"] = "1"
        for month in range(1, 13):
            data[f"month_{month}"] = states.get(month, "gewoon")
    return data | extra


def _post(client: TestClient, data: dict, task: Task | None = None):
    url = f"/taken/{task.id}" if task else "/taken"
    return client.post(url, data=data, headers=HTMX_HEADERS)


def test_off_stores_nothing(client: TestClient, db: Session) -> None:
    category = make_category(db)
    data = _form(category.id) | {"month_1": "pauze", "alt_every": "14"}
    assert _post(client, data).status_code == 204
    task = db.scalar(select(Task))
    assert (task.season_months, task.winter_every, task.winter_months) == (
        None,
        None,
        None,
    )


def test_pause_and_other_frequency(client: TestClient, db: Session) -> None:
    category = make_category(db)
    states = {12: "pauze", 1: "pauze", 11: "anders", 2: "anders"}
    assert _post(client, _form(category.id, states, alt_every="14")).status_code == 204
    task = db.scalar(select(Task))
    assert task.season_months == "2,3,4,5,6,7,8,9,10,11"
    assert (task.winter_every, task.winter_months) == (14, "2,11")
    assert (
        task.recurrence_text == "Elke 7 dagen · feb, nov elke 14 dagen · pauze dec–jan"
    )


def test_only_pause_is_a_season(client: TestClient, db: Session) -> None:
    category = make_category(db)
    states = {m: "pauze" for m in (11, 12, 1, 2)}
    _post(client, _form(category.id, states))
    task = db.scalar(select(Task))
    assert task.season_months == "3,4,5,6,7,8,9,10"
    assert task.winter_every is None


@pytest.mark.parametrize(
    ("states", "extra", "message"),
    [
        ({m: "pauze" for m in range(1, 13)}, {}, "Minstens één maand"),
        ({1: "anders"}, {}, "Vul de andere frequentie in"),
        ({1: "anders"}, {"alt_every": "0"}, "Vul de andere frequentie in"),
        ({1: "anders"}, {"recurrence_type": "fixed_date"}, "alleen bij"),
    ],
)
def test_validation(
    client: TestClient, db: Session, states: dict, extra: dict, message: str
) -> None:
    category = make_category(db)
    response = _post(client, _form(category.id, states, **extra))
    assert message in response.text
    assert db.scalar(select(Task)) is None
    assert 'name="month_plan" value="1" checked' in response.text  # blijft open


def test_pause_allowed_for_fixed_date(client: TestClient, db: Session) -> None:
    category = make_category(db)
    data = _form(category.id, {7: "pauze"}, recurrence_type="fixed_date")
    assert _post(client, data).status_code == 204


def test_existing_task_shows_states(client: TestClient, db: Session) -> None:
    task = make_task(
        db,
        name="Planten",
        season_months="3,4,5,6,7,8,9,10",
        winter_every=14,
        winter_months="3,10",
    )
    html = client.get(f"/taken/{task.id}").text
    assert 'name="month_plan" value="1" checked' in html
    assert 'aria-label="januari: pauze"' in html
    assert 'aria-label="oktober: anders"' in html
    assert 'aria-label="mei: gewoon"' in html
    assert 'value="14"' in html


def test_existing_winter_without_months_uses_default(
    client: TestClient, db: Session
) -> None:
    task = make_task(db, name="Kamerplanten", winter_every=14)
    html = client.get(f"/taken/{task.id}").text
    for month in ("november", "december", "januari", "februari"):
        assert f'aria-label="{month}: anders"' in html


def test_task_without_plan_is_closed(client: TestClient, db: Session) -> None:
    task = make_task(db, name="Stofzuigen")
    html = client.get(f"/taken/{task.id}").text
    assert 'name="month_plan" value="1">' in html  # niet aangevinkt
    assert html.index('class="field month-plan"') > html.index(
        'name="notes"'
    )  # onderaan


def test_new_pause_shifts_open_occurrence(client: TestClient, db: Session) -> None:
    category = make_category(db)
    out_of_season = date(today().year + 1, 1, 15)
    task = make_task(db, name="Gras maaien", category=category, due=out_of_season)
    states = {m: "pauze" for m in (11, 12, 1, 2)}
    _post(
        client,
        _form(
            category.id, states, name="Gras maaien", next_date=out_of_season.isoformat()
        ),
        task,
    )
    db.expire_all()
    assert tasks.pending_occurrence(db, task).due_date == date(today().year + 1, 3, 1)


def test_switching_off_clears_plan(client: TestClient, db: Session) -> None:
    category = make_category(db)
    task = make_task(
        db, name="Planten", category=category, season_months="3,4,5", winter_every=14
    )
    _post(client, _form(category.id), task)
    db.expire_all()
    assert (task.season_months, task.winter_every) == (None, None)
