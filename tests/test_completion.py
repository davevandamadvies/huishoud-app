from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import completion, tasks
from app.dates import today
from app.models import AuditLog, Occurrence, OccurrenceStatus, User, UserStatus
from app.recurrence import IntervalUnit
from tests.conftest import HTMX_HEADERS
from tests.factories import make_task, make_user


def statuses(db: Session, task_id: int) -> list[tuple[str, date | None]]:
    db.expire_all()
    rows = db.scalars(
        select(Occurrence).where(Occurrence.task_id == task_id).order_by(Occurrence.id)
    )
    return [(o.status.value, o.due_date) for o in rows]


def test_complete_open_occurrence_schedules_next(db: Session, user: User) -> None:
    task = make_task(db, every=7, due=today() - timedelta(days=3))
    result = completion.complete(db, user, task, performer_ids=[user.id])
    assert result.occurrence.status == OccurrenceStatus.DONE
    assert result.occurrence.completed_on == today()
    # Interval telt vanaf het afvinken, niet vanaf de (gemiste) vervaldatum
    assert result.next_occurrence.due_date == today() + timedelta(days=7)
    assert [p.user_id for p in result.occurrence.performers] == [user.id]
    assert statuses(db, task.id) == [
        ("done", today() - timedelta(days=3)),
        ("open", today() + timedelta(days=7)),
    ]


def test_complete_unplanned_task(db: Session, user: User) -> None:
    task = make_task(db, every=14)
    completion.complete(db, user, task, performer_ids=[user.id])
    assert statuses(db, task.id) == [
        ("done", None),
        ("open", today() + timedelta(days=14)),
    ]


def test_fixed_date_keeps_rhythm(db: Session, user: User) -> None:
    due = today() + timedelta(days=30)
    task = make_task(db, every=12, recurrence="fixed_date", due=due)
    task.interval_unit = IntervalUnit.MONTHS
    db.commit()
    result = completion.complete(db, user, task, performer_ids=[user.id])
    assert result.next_occurrence.due_date == due.replace(year=due.year + 1)


def test_once_has_no_next(db: Session, user: User) -> None:
    task = make_task(db, every=None, recurrence="once", due=today())
    result = completion.complete(db, user, task, performer_ids=[user.id])
    assert result.next_occurrence is None
    assert tasks.pending_occurrence(db, task) is None


def test_together_and_backdated(db: Session, user: User) -> None:
    partner = make_user(db, name="Partner")
    task = make_task(db, every=7)
    yesterday = today() - timedelta(days=1)
    result = completion.complete(
        db,
        user,
        task,
        performer_ids=[user.id, partner.id, user.id],
        completed_on=yesterday,
        note="  samen gedaan ",
    )
    assert {p.user_id for p in result.occurrence.performers} == {user.id, partner.id}
    assert result.occurrence.note == "samen gedaan"
    assert result.next_occurrence.due_date == yesterday + timedelta(days=7)
    entry = db.scalars(select(AuditLog)).one()
    assert entry.action == "occurrence.complete"
    assert entry.new_value["completed_on"] == yesterday.isoformat()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"performer_ids": []}, "wie"),
        ({"performer_ids": [999]}, "actieve"),
        ({"completed_on": today() + timedelta(days=1)}, "toekomst"),
        ({"completed_on": today() - timedelta(days=61)}, "60 dagen"),
        ({"note": "x" * 501}, "500"),
    ],
)
def test_validation(db: Session, user: User, kwargs: dict, message: str) -> None:
    task = make_task(db)
    kwargs.setdefault("performer_ids", [user.id])
    with pytest.raises(completion.CompletionError, match=message):
        completion.complete(db, user, task, **kwargs)


def test_deactivated_performer_rejected(db: Session, user: User) -> None:
    old = make_user(db, status=UserStatus.DEACTIVATED)
    with pytest.raises(completion.CompletionError):
        completion.complete(db, user, make_task(db), performer_ids=[old.id])


def test_archived_task_rejected(db: Session, user: User) -> None:
    task = make_task(db)
    tasks.archive(db, user, task)
    with pytest.raises(completion.CompletionError, match="archief"):
        completion.complete(db, user, task, performer_ids=[user.id])


def test_history_and_delete_guard(db: Session, user: User) -> None:
    task = make_task(db)
    completion.complete(db, user, task, performer_ids=[user.id], note="eerste")
    log = completion.history(db, task)
    assert [o.note for o in log] == ["eerste"]
    with pytest.raises(tasks.TaskError):
        tasks.delete(db, user, task)


def test_preview(db: Session) -> None:
    task = make_task(db, every=3)
    assert completion.preview_next(db, task, date(2026, 10, 3)) == date(2026, 10, 6)


# ---- Schermen ----


def test_sheet_renders(client: TestClient, db: Session, user: User) -> None:
    task = make_task(db, name="Gras maaien", every=7)
    html = client.get(f"/taken/{task.id}/afronden").text
    assert 'role="dialog"' in html and "Gras maaien" in html
    assert f'value="{user.id}" checked' in html
    assert "Volgende keer" in html


def test_preview_partial(client: TestClient, db: Session) -> None:
    task = make_task(db, every=7)
    html = client.get(
        f"/taken/{task.id}/afronden/voorbeeld", params={"completed_on": "2026-10-01"}
    ).text
    assert "donderdag 8 oktober" in html


def test_complete_via_sheet(client: TestClient, db: Session, user: User) -> None:
    task = make_task(db, every=7, due=today())
    r = client.post(
        f"/taken/{task.id}/afronden",
        data={
            "performer": [str(user.id)],
            "completed_on": today().isoformat(),
            "note": "",
            "after": "event",
        },
        headers=HTMX_HEADERS,
    )
    assert r.status_code == 200 and r.text == ""
    assert r.headers["hx-trigger"] == "occurrences-changed"
    assert statuses(db, task.id)[-1] == ("open", today() + timedelta(days=7))


def test_complete_via_sheet_refresh_mode(
    client: TestClient, db: Session, user: User
) -> None:
    task = make_task(db)
    r = client.post(
        f"/taken/{task.id}/afronden",
        data={
            "performer": [str(user.id)],
            "completed_on": today().isoformat(),
            "after": "refresh",
        },
        headers=HTMX_HEADERS,
    )
    assert r.headers["hx-refresh"] == "true"


def test_complete_error_rerenders_sheet(client: TestClient, db: Session) -> None:
    task = make_task(db)
    r = client.post(
        f"/taken/{task.id}/afronden",
        data={"completed_on": today().isoformat()},
        headers=HTMX_HEADERS,
    )
    assert 'role="alert"' in r.text and "Kies wie" in r.text


def test_task_page_shows_logbook(client: TestClient, db: Session, user: User) -> None:
    task = make_task(db)
    completion.complete(db, user, task, performer_ids=[user.id], note="met nieuwe zak")
    html = client.get(f"/taken/{task.id}").text
    assert "Logboek" in html and "met nieuwe zak" in html
    assert "Afvinken" in html
    assert ">Verwijderen<" not in html
