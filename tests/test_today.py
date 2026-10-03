from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import completion, tasks, today_view
from app.dates import today
from app.models import User
from tests.conftest import HTMX_HEADERS
from tests.factories import make_task, make_user


def names(occurrences: list) -> list[str]:
    return [o.task.name for o in occurrences]


def test_buckets(db: Session) -> None:
    day = date(2026, 10, 7)  # woensdag
    make_task(db, name="Laat", due=day - timedelta(days=3))
    make_task(db, name="Nu", due=day)
    make_task(db, name="Snel", due=day + timedelta(days=2))
    make_task(db, name="Grens", due=day + timedelta(days=7))
    make_task(db, name="Ver", due=day + timedelta(days=8))
    make_task(db, name="Zonder datum")
    view = today_view.build(db, day)
    assert names(view.late) == ["Laat"]
    assert names(view.today) == ["Nu"]
    assert names(view.soon) == ["Snel", "Grens"]


def test_archived_tasks_hidden(db: Session, user: User) -> None:
    day = date(2026, 10, 7)
    task = make_task(db, name="Weg", due=day)
    tasks.archive(db, user, task)
    assert today_view.build(db, day).is_empty


def test_week_progress(db: Session, user: User) -> None:
    day = today()
    monday, sunday = today_view.week_bounds(day)
    make_task(db, name="Deze week", due=sunday)
    make_task(db, name="Te laat", due=monday - timedelta(days=5))
    make_task(db, name="Volgende week", due=sunday + timedelta(days=1))
    done = make_task(db, name="Klaar", due=day)
    completion.complete(db, user, done, performer_ids=[user.id])
    view = today_view.build(db, day)
    assert view.week_done == 1
    # deze week + te laat + klaar (de volgende keer van "Klaar" valt na zondag
    # bij een interval van 7 dagen)
    assert view.week_total == 3
    assert names(view.done_today) == ["Klaar"]


def test_week_bounds() -> None:
    assert today_view.week_bounds(date(2026, 10, 7)) == (
        date(2026, 10, 5),
        date(2026, 10, 11),
    )
    assert today_view.week_bounds(date(2026, 10, 11))[0] == date(2026, 10, 5)


def test_today_page(client: TestClient, db: Session, user: User) -> None:
    partner = make_user(db, name="Partner")
    make_task(db, name="Ramen binnen lappen", due=today() - timedelta(days=3))
    make_task(db, name="Badkamer", due=today())
    make_task(db, name="Oliepeil", due=today() + timedelta(days=2), owner=user)
    html = client.get("/").text
    assert "Te laat" in html and "3 dagen te laat" in html
    assert "Badkamer" in html and "iedereen" in html
    assert "Binnenkort" in html and "over 2 d" in html and "· Dave" in html
    assert 'aria-label="Badkamer afvinken"' in html
    assert 'hx-trigger="occurrences-changed from:body"' in html
    assert partner.display_name not in html


def test_done_today_shown_struck_through(
    client: TestClient, db: Session, user: User
) -> None:
    partner = make_user(db, name="Partner")
    task = make_task(db, name="Gras maaien", due=today())
    completion.complete(db, user, task, performer_ids=[user.id, partner.id])
    html = client.get("/vandaag/lijsten").text
    assert "is-done" in html and "Gras maaien" in html and "samen" in html
    assert html.lstrip().startswith('<div id="today-lists"')


def test_empty_state(client: TestClient) -> None:
    html = client.get("/").text
    assert "Niks te doen" in html
    assert "Nog niets gepland deze week" in html


def test_complete_from_today_refreshes_lists(
    client: TestClient, db: Session, user: User
) -> None:
    task = make_task(db, name="Toilet", due=today())
    sheet = client.get(f"/taken/{task.id}/afronden").text
    assert 'name="after" value="event"' in sheet
    r = client.post(
        f"/taken/{task.id}/afronden",
        data={
            "performer": [str(user.id)],
            "completed_on": today().isoformat(),
            "after": "event",
        },
        headers=HTMX_HEADERS,
    )
    assert r.headers["hx-trigger"] == "occurrences-changed"
    html = client.get("/vandaag/lijsten").text
    assert "is-done" in html


def test_sheet_openers_do_not_inherit_outer_swap(
    client: TestClient, db: Session
) -> None:
    make_task(db, name="Badkamer", due=today())
    html = client.get("/").text
    assert 'hx-disinherit="*"' in html
    assert 'hx-target="#sheet" hx-swap="innerHTML"' in html
