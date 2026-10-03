from datetime import time, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import planning, tasks
from app.dates import plan_label, today
from app.models import OccurrenceStatus, User
from app.planning import PlanInput
from tests.conftest import HTMX_HEADERS
from tests.factories import make_task, make_user


def post_plan(client: TestClient, task_id: int, **data: object):  # noqa: ANN201
    return client.post(f"/taken/{task_id}/inplannen", data=data, headers=HTMX_HEADERS)


def test_plan_sheet_defaults(client: TestClient, db: Session, user: User) -> None:
    task = make_task(db, name="Auto wassen", owner=user)
    html = client.get(f"/taken/{task.id}/inplannen").text
    assert 'role="dialog"' in html and "Inplannen: Auto wassen" in html
    assert f'value="{(today() + timedelta(days=1)).isoformat()}"' in html
    # De vaste eigenaar staat voorgeselecteerd
    assert f'name="owner" value="{user.id}" checked' in html
    assert "Planning annuleren" not in html


def test_plan_via_sheet(client: TestClient, db: Session, user: User) -> None:
    partner = make_user(db, name="Partner")
    task = make_task(db, due=today())
    day = (today() + timedelta(days=2)).isoformat()
    r = post_plan(
        client,
        task.id,
        planned_date=day,
        planned_time="10:00",
        owner=[str(user.id), str(partner.id)],
        after="event",
    )
    assert r.status_code == 200 and r.text == ""
    assert r.headers["hx-trigger"] == "occurrences-changed"
    occ = tasks.pending_occurrence(db, task)
    db.refresh(occ)
    assert occ.status == OccurrenceStatus.PLANNED
    assert occ.planned_time == time(10, 0)
    assert len(occ.owners) == 2


def test_plan_error_rerenders_sheet(client: TestClient, db: Session) -> None:
    task = make_task(db)
    r = post_plan(
        client, task.id, planned_date=(today() - timedelta(days=1)).isoformat()
    )
    assert 'role="alert"' in r.text and "vanaf vandaag" in r.text
    r = post_plan(client, task.id, planned_date="morgen")
    assert "Kies een datum" in r.text
    r = post_plan(
        client, task.id, planned_date=today().isoformat(), planned_time="25:99"
    )
    assert "geldige tijd" in r.text


def test_reschedule_via_sheet_keeps_points(
    client: TestClient, db: Session, user: User
) -> None:
    task = make_task(db, due=today())
    planning.plan(db, user, task, PlanInput(today() + timedelta(days=1), points=7))
    html = client.get(f"/taken/{task.id}/inplannen").text
    assert "Verzetten:" in html and "Planning annuleren" in html
    r = post_plan(
        client, task.id, planned_date=(today() + timedelta(days=5)).isoformat()
    )
    assert r.status_code == 200
    occ = tasks.pending_occurrence(db, task)
    db.refresh(occ)
    assert occ.planned_date == today() + timedelta(days=5)
    assert occ.points == 7


def test_cancel_via_sheet(client: TestClient, db: Session, user: User) -> None:
    task = make_task(db, due=today() + timedelta(days=3))
    planning.plan(db, user, task, PlanInput(today() + timedelta(days=1)))
    r = client.post(
        f"/taken/{task.id}/planning-annuleren",
        data={"after": "refresh"},
        headers=HTMX_HEADERS,
    )
    assert r.headers["hx-refresh"] == "true"
    occ = tasks.pending_occurrence(db, task)
    db.refresh(occ)
    assert occ.status == OccurrenceStatus.OPEN


def test_cancel_without_plan_is_409(client: TestClient, db: Session) -> None:
    task = make_task(db, due=today())
    r = client.post(f"/taken/{task.id}/planning-annuleren", headers=HTMX_HEADERS)
    assert r.status_code == 409


def test_complete_sheet_offers_plan_and_preselects_owners(
    client: TestClient, db: Session, user: User
) -> None:
    partner = make_user(db, name="Partner")
    task = make_task(db, due=today())
    html = client.get(f"/taken/{task.id}/afronden").text
    assert "Liever inplannen" in html
    planning.plan(db, user, task, PlanInput(today(), owner_ids=(partner.id,)))
    html = client.get(f"/taken/{task.id}/afronden").text
    assert f'value="{partner.id}" checked' in html
    assert f'value="{user.id}" checked' not in html


def test_task_page_planned_card(client: TestClient, db: Session, user: User) -> None:
    task = make_task(db, due=today() + timedelta(days=9))
    html = client.get(f"/taken/{task.id}").text
    assert ">Inplannen<" in html
    planning.plan(
        db, user, task, PlanInput(today() + timedelta(days=1), time(9, 30), (user.id,))
    )
    html = client.get(f"/taken/{task.id}").text
    assert "Gepland" in html and "09:30" in html and ">Verzetten<" in html


def test_today_shows_plan_and_owner(
    client: TestClient, db: Session, user: User
) -> None:
    partner = make_user(db, name="Partner")
    task = make_task(db, name="Dakgoten", due=today() + timedelta(days=30), owner=user)
    planning.plan(
        db,
        user,
        task,
        PlanInput(today() + timedelta(days=2), time(10, 0), (partner.id,)),
    )
    html = client.get("/").text
    assert "Dakgoten" in html
    assert "· Partner" in html  # eigenaar van deze keer gaat voor de vaste eigenaar
    assert plan_label(today() + timedelta(days=2), time(10, 0), today()) in html


def test_plan_label() -> None:
    ref = today()
    assert plan_label(ref, None, ref) == "gepland vandaag"
    assert plan_label(ref, time(10, 0), ref) == "gepland 10:00"
    assert plan_label(ref + timedelta(days=1), None, ref) == "gepland morgen"
    assert plan_label(ref + timedelta(days=30), time(8, 5), ref).endswith(" 08:05")
