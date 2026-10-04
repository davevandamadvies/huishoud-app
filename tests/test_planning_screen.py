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
    # Woensdag van volgende week: nooit gelijk aan de zondag ("Andere dag").
    next_week = today() + timedelta(days=7)
    monday = next_week - timedelta(days=next_week.weekday())
    day = monday + timedelta(days=2)
    plan(db, user, make_task(db, name="Middag"), day, time(14, 0))
    plan(db, user, make_task(db, name="Ochtend"), day, time(9, 0))
    plan(db, user, make_task(db, name="Zonder tijd"), day)
    plan(db, user, make_task(db, name="Andere dag"), monday + timedelta(days=6))
    plan(db, user, make_task(db, name="Volgende week"), monday + timedelta(days=7))

    view = planning_view.build(db, day, planning_view.Mode.WEEK)
    assert [d.date for d in view.days] == [monday + timedelta(days=i) for i in range(7)]
    with_items = {d.date for d in view.days if d.has_items}
    assert with_items == {day, monday + timedelta(days=6)}
    assert [o.task.name for o in view.items] == ["Ochtend", "Middag", "Zonder tijd"]
    assert view.previous == day - timedelta(days=7)
    assert view.next == day + timedelta(days=7)


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
    view = planning_view.build(db, date(2026, 12, 31), planning_view.Mode.WEEK)
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


# ---- Maandweergave ----


def test_month_view_covers_whole_weeks(db: Session) -> None:
    view = planning_view.build(db, date(2026, 10, 4))  # standaard: maand
    assert view.mode == planning_view.Mode.MONTH
    assert view.days[0].date == date(2026, 9, 28)  # maandag vóór 1 okt
    assert view.days[-1].date == date(2026, 11, 1)  # zondag na 31 okt
    assert len(view.weeks) == 5 and all(len(w) == 7 for w in view.weeks)
    assert not view.days[0].in_month and view.days[3].in_month


def test_month_starting_on_monday(db: Session) -> None:
    view = planning_view.build(db, date(2026, 6, 15))  # 1 juni 2026 is maandag
    assert view.days[0].date == date(2026, 6, 1)
    assert view.days[-1].date == date(2026, 7, 5)


def test_february_leap_year(db: Session) -> None:
    view = planning_view.build(db, date(2028, 2, 10))
    assert date(2028, 2, 29) in [d.date for d in view.days if d.in_month]


def test_month_navigation(db: Session) -> None:
    view = planning_view.build(db, date(2026, 1, 31))
    assert view.previous == date(2025, 12, 31)
    assert view.next == date(2026, 2, 28)
    december = planning_view.build(db, date(2026, 12, 15))
    assert december.next == date(2027, 1, 15)


def test_month_items_and_dots(db: Session, user: User) -> None:
    day = today() + timedelta(days=1)
    for n in range(5):
        plan(db, user, make_task(db, name=f"Taak {n}"), day)
    view = planning_view.build(db, day)
    cell = next(d for d in view.days if d.date == day)
    assert len(cell.items) == 5
    assert len(cell.dots) == 3 and cell.more == 2
    assert len(view.items) == 5


def test_month_page(client: TestClient, db: Session, user: User) -> None:
    day = today() + timedelta(days=1)
    plan(db, user, make_task(db, name="Dakgoten"), day)
    html = client.get(f"/planning?dag={day.isoformat()}").text
    assert 'class="month-grid"' in html
    assert "1 taak" in html  # label van de dag voor schermlezers
    assert "Dakgoten" in html
    week = client.get(f"/planning?weergave=week&dag={day.isoformat()}").text
    assert 'class="weekstrip"' in week and 'class="month-grid"' not in week
    assert client.get("/planning?weergave=onzin").status_code == 200


def test_mode_kept_in_links(client: TestClient) -> None:
    html = client.get("/planning/inhoud?weergave=week").text
    assert "weergave=week&amp;dag=" in html
