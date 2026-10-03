from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import categories, tasks
from app.dates import due_label, today
from app.forms import FormData
from app.models import AuditLog, Occurrence, OccurrenceStatus, Task, User, UserStatus
from app.recurrence import IntervalUnit, RecurrenceType
from tests.conftest import HTMX_HEADERS
from tests.factories import make_category, make_task, make_user


def form(**values: str) -> FormData:
    return FormData({k: [v] for k, v in values.items()})


def valid(db: Session, **overrides: str) -> FormData:
    category = make_category(db)
    data = {
        "name": "Badkamer schoonmaken",
        "category_id": str(category.id),
        "recurrence_type": "interval",
        "interval_every": "7",
        "interval_unit": "days",
    } | overrides
    return form(**data)


# ---- Invoer ----


def test_parse_valid_form(db: Session, user: User) -> None:
    data = tasks.parse_form(
        db,
        valid(db, owner_id=str(user.id), default_points="8", next_date="2026-10-10"),
    )
    assert data.name == "Badkamer schoonmaken"
    assert data.recurrence_type == RecurrenceType.INTERVAL
    assert data.interval_every == 7 and data.interval_unit == IntervalUnit.DAYS
    assert data.owner_id == user.id and data.default_points == 8
    assert data.next_date == date(2026, 10, 10)


def test_once_ignores_interval(db: Session) -> None:
    data = tasks.parse_form(db, valid(db, recurrence_type="once", interval_every=""))
    assert data.interval_every is None


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"name": "  "}, "name"),
        ({"name": "x" * 101}, "name"),
        ({"category_id": "999"}, "category_id"),
        ({"recurrence_type": "soms"}, "recurrence_type"),
        ({"interval_every": "0"}, "interval_every"),
        ({"interval_every": "abc"}, "interval_every"),
        ({"interval_unit": "eeuwen"}, "interval_every"),
        ({"default_points": "0"}, "default_points"),
        ({"default_points": "101"}, "default_points"),
        ({"owner_id": "999"}, "owner_id"),
        ({"next_date": "31-12-2026"}, "next_date"),
    ],
)
def test_parse_errors(db: Session, override: dict, field: str) -> None:
    with pytest.raises(tasks.TaskFormError) as exc:
        tasks.parse_form(db, valid(db, **override))
    assert field in exc.value.errors


def test_deactivated_owner_rejected(db: Session) -> None:
    old = make_user(db, status=UserStatus.DEACTIVATED)
    with pytest.raises(tasks.TaskFormError):
        tasks.parse_form(db, valid(db, owner_id=str(old.id)))


# ---- Levenscyclus ----


def test_create_with_and_without_next_date(db: Session, user: User) -> None:
    a = tasks.create(db, user, tasks.parse_form(db, valid(db, next_date="2026-11-01")))
    b = tasks.create(db, user, tasks.parse_form(db, valid(db, name="Ander")))
    assert tasks.pending_occurrence(db, a).due_date == date(2026, 11, 1)
    assert tasks.pending_occurrence(db, b) is None
    assert db.scalars(select(AuditLog.action)).all() == ["task.create"] * 2


def test_update_changes_next_date(db: Session, user: User) -> None:
    task = tasks.create(db, user, tasks.parse_form(db, valid(db)))
    tasks.update(
        db, user, task, tasks.parse_form(db, valid(db, next_date="2026-12-01"))
    )
    assert tasks.pending_occurrence(db, task).due_date == date(2026, 12, 1)
    tasks.update(db, user, task, tasks.parse_form(db, valid(db, next_date="")))
    assert tasks.pending_occurrence(db, task) is None
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "task.update")).first()
    assert entry is not None and "next_date" in entry.new_value


def test_never_two_pending_occurrences(db: Session) -> None:
    task = make_task(db, due=date(2026, 10, 10))
    db.add(Occurrence(task_id=task.id, due_date=date(2026, 10, 17)))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    # Een afgeronde naast een open uitvoering mag wel
    db.add(Occurrence(task_id=task.id, status=OccurrenceStatus.DONE))
    db.commit()


def test_archive_and_restore(db: Session, user: User) -> None:
    task = make_task(db, due=date(2026, 10, 10))
    tasks.archive(db, user, task)
    assert task.is_archived
    assert tasks.pending_occurrence(db, task) is None
    assert [r.task for r in tasks.list_tasks(db)] == []
    assert [r.task for r in tasks.list_tasks(db, archived=True)] == [task]
    tasks.restore(db, user, task)
    assert not task.is_archived


def test_delete_only_without_history(db: Session, user: User) -> None:
    task = make_task(db)
    db.add(Occurrence(task_id=task.id, status=OccurrenceStatus.DONE))
    db.commit()
    with pytest.raises(tasks.TaskError, match="logboek"):
        tasks.delete(db, user, task)
    other = make_task(db, due=date(2026, 10, 1))
    tasks.delete(db, user, other)
    assert db.get(Task, other.id) is None


def test_list_sorting_and_filters(db: Session) -> None:
    tuin = make_category(db, "Tuin")
    later = make_task(db, name="Later", due=date(2026, 12, 1))
    soon = make_task(db, name="Snel", due=date(2026, 10, 5), category=tuin)
    nodate = make_task(db, name="Zonder datum", notes="Monstera")
    assert [r.task for r in tasks.list_tasks(db)] == [soon, later, nodate]
    assert [r.task for r in tasks.list_tasks(db, category_id=tuin.id)] == [soon]
    assert [r.task for r in tasks.list_tasks(db, search="monst")] == [nodate]
    assert [r.task for r in tasks.list_tasks(db, search="SNEL")] == [soon]


def test_category_with_tasks_cannot_be_deleted(db: Session, user: User) -> None:
    task = make_task(db)
    with pytest.raises(categories.CategoryError):
        categories.delete(db, user, task.category)


@pytest.mark.parametrize(
    ("offset", "text", "tone"),
    [
        (-3, "3 dagen te laat", "late"),
        (-1, "1 dag te laat", "late"),
        (0, "vandaag", "soon"),
        (1, "morgen", "soon"),
        (12, "over 12 d", "later"),
    ],
)
def test_due_label(offset: int, text: str, tone: str) -> None:
    ref = date(2026, 10, 3)
    assert due_label(ref + timedelta(days=offset), ref) == (text, tone)


def test_due_label_far_and_none() -> None:
    assert due_label(date(2027, 3, 1), date(2026, 10, 3)) == ("1 mrt", "later")
    assert due_label(None, date(2026, 10, 3)) == ("nog geen datum", "none")


# ---- Schermen ----


def test_tasks_page(client: TestClient, db: Session) -> None:
    make_task(db, name="Gras maaien", due=today() - timedelta(days=2))
    make_task(db, name="Verpotten")
    html = client.get("/taken").text
    assert "Gras maaien" in html and "2 dagen te laat" in html
    assert "Verpotten" in html and "nog geen datum" in html
    assert 'href="/taken/nieuw"' in html


def test_search_partial(client: TestClient, db: Session) -> None:
    make_task(db, name="Gras maaien")
    make_task(db, name="Ramen lappen")
    html = client.get("/taken/lijst", params={"q": "gras"}).text
    assert "Gras maaien" in html and "Ramen lappen" not in html
    assert html.lstrip().startswith('<div id="task-list">')


def test_create_via_form(client: TestClient, db: Session) -> None:
    category = make_category(db)
    assert client.get("/taken/nieuw").status_code == 200
    r = client.post(
        "/taken",
        data={
            "name": "APK",
            "category_id": str(category.id),
            "recurrence_type": "fixed_date",
            "interval_every": "12",
            "interval_unit": "months",
            "next_date": "2027-03-15",
            "default_points": "5",
        },
        headers=HTMX_HEADERS,
    )
    assert r.status_code == 204 and r.headers["hx-redirect"] == "/taken"
    task = db.scalars(select(Task)).one()
    assert task.recurrence_type == RecurrenceType.FIXED_DATE
    assert tasks.pending_occurrence(db, task).due_date == date(2027, 3, 15)


def test_create_errors_shown_inline(client: TestClient, db: Session) -> None:
    category = make_category(db)
    r = client.post(
        "/taken",
        data={
            "name": "",
            "category_id": str(category.id),
            "recurrence_type": "interval",
            "interval_every": "0",
            "interval_unit": "days",
        },
        headers=HTMX_HEADERS,
    )
    assert r.status_code == 200
    assert 'id="name-error"' in r.text and 'id="interval_every-error"' in r.text
    assert 'aria-invalid="true"' in r.text


def test_edit_archive_delete_via_form(client: TestClient, db: Session) -> None:
    task = make_task(db, name="Oven", due=date(2026, 11, 1))
    html = client.get(f"/taken/{task.id}").text
    assert 'value="2026-11-01"' in html and "Verwijderen" in html
    r = client.post(f"/taken/{task.id}/archiveren", headers=HTMX_HEADERS)
    assert r.status_code == 204
    assert "Oven" in client.get("/taken?archief=1").text
    r = client.post(f"/taken/{task.id}/verwijderen", headers=HTMX_HEADERS)
    assert r.status_code == 204
    assert client.get(f"/taken/{task.id}").status_code == 404
