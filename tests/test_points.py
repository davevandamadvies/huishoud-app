from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import completion, planning, settings_store, tasks
from app import points as app_points
from app.dates import today
from app.models import AuditLog, OccurrenceStatus, User
from app.planning import PlanInput
from tests.conftest import HTMX_HEADERS
from tests.factories import make_task, make_user


@pytest.fixture
def competition(db: Session, user: User) -> None:
    settings_store.set_value(db, user, settings_store.COMPETITION, "true")


@pytest.mark.parametrize(
    ("points", "people", "each"),
    [
        (5, 1, 5),
        (5, 2, 3),
        (4, 2, 2),
        (7, 3, 3),
        (1, 3, 1),
        (None, 2, None),
        (5, 0, None),
    ],
)
def test_share_rounds_up(points: int | None, people: int, each: int | None) -> None:
    assert app_points.share(points, people) == each


def test_complete_with_points_together(
    db: Session, user: User, competition: None
) -> None:
    partner = make_user(db, name="Partner")
    task = make_task(db, due=today())
    result = completion.complete(
        db, user, task, performer_ids=[user.id, partner.id], points=5
    )
    assert result.occurrence.points == 5
    assert [p.points for p in result.occurrence.performers] == [3, 3]


def test_no_points_without_competition(db: Session, user: User) -> None:
    task = make_task(db, due=today(), default_points=8)
    result = completion.complete(db, user, task, performer_ids=[user.id], points=8)
    assert result.occurrence.points is None
    assert result.occurrence.performers[0].points is None


def test_empty_points_means_none(db: Session, user: User, competition: None) -> None:
    task = make_task(db, default_points=8)
    result = completion.complete(db, user, task, performer_ids=[user.id], points=None)
    assert result.occurrence.points is None


def test_invalid_points_rejected(db: Session, user: User, competition: None) -> None:
    with pytest.raises(completion.CompletionError, match="Punten"):
        completion.complete(db, user, make_task(db), performer_ids=[user.id], points=0)


def test_default_points_suggestion(db: Session, user: User) -> None:
    task = make_task(db, due=today(), default_points=6)
    assert completion.default_points(db, task) == 6
    planning.plan(db, user, task, PlanInput(today() + timedelta(days=1), points=9))
    assert completion.default_points(db, task) == 9


def test_correct_points(db: Session, user: User, competition: None) -> None:
    partner = make_user(db, name="Partner")
    task = make_task(db)
    occ = completion.complete(
        db, user, task, performer_ids=[user.id, partner.id], points=8
    ).occurrence
    app_points.correct(db, user, occ, 10, "  vergeten mee te tellen ")
    assert occ.points == 10 and [p.points for p in occ.performers] == [5, 5]
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "points.change")).one()
    assert entry.old_value == {"points": 8}
    assert entry.new_value["points"] == 10
    assert entry.new_value["reason"] == "vergeten mee te tellen"


def test_correct_only_done(db: Session, user: User) -> None:
    task = make_task(db, due=today())
    with pytest.raises(app_points.PointsError, match="afgeronde"):
        app_points.correct(db, user, tasks.pending_occurrence(db, task), 5)


def test_plan_with_explicit_empty_points(
    db: Session, user: User, competition: None
) -> None:
    task = make_task(db, default_points=8)
    occ = planning.plan(
        db, user, task, PlanInput(today() + timedelta(days=1)), use_task_points=False
    )
    assert occ.points is None


# ---- Schermen ----


def test_sheet_shows_stepper_only_with_competition(
    client: TestClient, db: Session, user: User
) -> None:
    task = make_task(db, default_points=6)
    assert "data-stepper" not in client.get(f"/taken/{task.id}/afronden").text
    settings_store.set_value(db, user, settings_store.COMPETITION, "true")
    html = client.get(f"/taken/{task.id}/afronden").text
    assert "data-stepper" in html and 'name="points"' in html and 'value="6"' in html
    html = client.get(f"/taken/{task.id}/inplannen").text
    assert "data-stepper" in html


def test_complete_via_sheet_with_points(
    client: TestClient, db: Session, user: User, competition: None
) -> None:
    task = make_task(db, due=today())
    r = client.post(
        f"/taken/{task.id}/afronden",
        data={
            "performer": [str(user.id)],
            "completed_on": today().isoformat(),
            "points": "7",
        },
        headers=HTMX_HEADERS,
    )
    assert r.status_code == 200
    log = completion.history(db, task)
    assert log[0].points == 7


def test_plan_via_sheet_with_points(
    client: TestClient, db: Session, user: User, competition: None
) -> None:
    task = make_task(db, default_points=8)
    client.post(
        f"/taken/{task.id}/inplannen",
        data={"planned_date": (today() + timedelta(days=1)).isoformat(), "points": ""},
        headers=HTMX_HEADERS,
    )
    occ = tasks.pending_occurrence(db, task)
    db.refresh(occ)
    assert occ.status == OccurrenceStatus.PLANNED and occ.points is None


def test_lists_show_points(
    client: TestClient, db: Session, user: User, competition: None
) -> None:
    partner = make_user(db, name="Partner")
    make_task(db, name="Badkamer", due=today(), default_points=8)
    done = make_task(db, name="Gras", due=today())
    completion.complete(db, user, done, performer_ids=[user.id, partner.id], points=5)
    html = client.get("/").text
    assert ">8 p<" in html
    assert "+3 p.p." in html


def test_correct_via_logbook(
    client: TestClient, db: Session, user: User, competition: None
) -> None:
    task = make_task(db)
    occ = completion.complete(
        db, user, task, performer_ids=[user.id], points=4
    ).occurrence
    html = client.get(f"/taken/{task.id}").text
    assert "4 punten" in html and "aanpassen" in html
    r = client.post(
        f"/taken/{task.id}/logboek/{occ.id}/punten",
        data={"points": "6", "reason": "zwaarder dan gedacht"},
        headers=HTMX_HEADERS,
    )
    assert r.status_code == 204
    db.refresh(occ)
    assert occ.points == 6


def test_correct_via_logbook_requires_competition(
    client: TestClient, db: Session, user: User
) -> None:
    task = make_task(db)
    occ = completion.complete(db, user, task, performer_ids=[user.id]).occurrence
    r = client.post(
        f"/taken/{task.id}/logboek/{occ.id}/punten",
        data={"points": "6"},
        headers=HTMX_HEADERS,
    )
    assert r.status_code == 409
