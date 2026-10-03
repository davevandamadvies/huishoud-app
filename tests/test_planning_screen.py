from datetime import date, time, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import planning, planning_view, tasks
from app.dates import today
from app.models import User
from app.planning import PlanInput
from tests.factories import make_category, make_task, make_user


def plan(db: Session, user: User, task, day: date, at=None, owners=()) -> None:  # noqa: ANN001
    planning.plan(db, user, task, PlanInput(day, at, tuple(owners)))


def test_view_week_and_day(db: Session, user: User) -> None:
    day = today() + timedelta(days=7)  # ruim in de toekomst, binnen een jaar
    monday = day - timedelta(days=day.weekday())
    plan(db, user, make_task(db, name="Middag"), day, time(14, 0))
    plan(db, user, make_task(db, name="Ochtend"), day, time(9, 0))
    plan(db, user, make_task(db, name="Zonder tijd"), day)
    plan(db, user, make_task(db, name="Andere dag"), monday + timedelta(days=6))
    plan(db, user, make_task(db, name="Volgende week"), monday + timedelta(days=7))

    view = planning_view.build(db, day)
    assert [d.date for d in view.days] == [monday + timedelta(days=i) for i in range(7)]
    with_items = {d.date for d in view.days if d.has_items}
    assert with_items == {day, monday + timedelta(days=6)}
    assert [o.task.name for o in view.items] == ["Ochtend", "Middag", "Zonder tijd"]
    assert view.previous_week == day - timedelta(days=7)


def test_archived_and_unplanned_not_shown(db: Session, user: User) -> None:
    day = today() + timedelta(days=1)
    task = make_task(db, name="Weg")
    plan(db, user, task, day)
    tasks.archive(db, user, task)
    make_task(db, name="Alleen vervaldatum", due=day)
    assert planning_view.build(db, day).items == []


def test_plannable_tasks(db: Session, user: User) -> None:
    tuin = make_category(db, "Tuin")
    make_task(db, name="Gras maaien", category=tuin)
    make_task(db, name="Stofzuigen")
    planned = make_task(db, name="Al gepland")
    plan(db, user, planned, today() + timedelta(days=1))
    archived = make_task(db, name="Archief")
    tasks.archive(db, user, archived)
    names = [t.name for t in planning_view.plannable_tasks(db)]
    assert names == ["Gras maaien", "Stofzuigen"]
    assert [t.name for t in planning_view.plannable_tasks(db, search="GRAS")] == [
        "Gras maaien"
    ]
    assert [t.name for t in planning_view.plannable_tasks(db, category_id=tuin.id)] == [
        "Gras maaien"
    ]


def test_week_crosses_year_boundary(db: Session) -> None:
    view = planning_view.build(db, date(2026, 12, 31))
    assert view.days[0].date == date(2026, 12, 28)
    assert view.days[-1].date == date(2027, 1, 3)


def test_planning_page(client: TestClient, db: Session, user: User) -> None:
    partner = make_user(db, name="Partner")
    day = today() + timedelta(days=1)
    plan(
        db,
        user,
        make_task(db, name="Dakgoten"),
        day,
        time(10, 0),
        [user.id, partner.id],
    )
    plan(db, user, make_task(db, name="Bladeren ruimen"), day)
    html = client.get("/planning", params={"dag": day.isoformat()}).text
    assert "Dakgoten" in html and "10:00" in html and "Samen" in html
    assert "Bladeren ruimen" in html and "Nog niemand" in html
    assert 'aria-current="date"' in html
    assert "iets gepland" in html
    assert 'hx-trigger="occurrences-changed from:body"' in html
    assert "Plan een taak" in html


def test_planning_page_defaults_to_today(client: TestClient) -> None:
    html = client.get("/planning", params={"dag": "onzin"}).text
    assert "Niets gepland" in html


def test_planning_content_partial(client: TestClient) -> None:
    html = client.get("/planning/inhoud").text
    assert html.lstrip().startswith('<div id="planning-content"')


def test_pick_task_flow(client: TestClient, db: Session) -> None:
    make_task(db, name="Gras maaien")
    make_task(db, name="Ramen lappen")
    day = (today() + timedelta(days=2)).isoformat()
    html = client.get("/planning/kies", params={"datum": day}).text
    assert "Welke taak plan je in?" in html and "Gras maaien" in html
    html = client.get("/planning/kies/lijst", params={"datum": day, "q": "gras"}).text
    assert "Gras maaien" in html and "Ramen lappen" not in html
    assert f"inplannen?datum={day}" in html


def test_plan_sheet_uses_chosen_day(client: TestClient, db: Session) -> None:
    task = make_task(db)
    day = (today() + timedelta(days=4)).isoformat()
    html = client.get(f"/taken/{task.id}/inplannen", params={"datum": day}).text
    assert f'value="{day}"' in html
