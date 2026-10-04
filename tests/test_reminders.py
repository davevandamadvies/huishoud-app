from datetime import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import reminders
from app.forms import FormData
from app.models import AuditLog, ReminderPreference, Task, User
from app.seed_data import TASKS
from tests.conftest import HTMX_HEADERS
from tests.factories import make_category

FORM_HEADERS = {**HTMX_HEADERS, "Content-Type": "application/x-www-form-urlencoded"}


def form(**fields: object) -> FormData:
    data: dict[str, list[str]] = {}
    for key, value in fields.items():
        data[key] = [str(v) for v in value] if isinstance(value, list) else [str(value)]
    return FormData(data)


UPDATE = {
    "update_enabled": "1",
    "frequency": "elke-dag",
    "time": ["08:30", "", ""],
    "lookahead_days": "3",
    "scope": "household",
}


# ---- Standaardwaarden ----


def test_defaults_without_row(db: Session, user: User) -> None:
    preference = reminders.get(db, user)
    assert preference.update_enabled is True
    assert reminders.days(preference) == set(range(7))
    assert reminders.times(preference) == [time(8, 30)]
    assert preference.lookahead_days == 3
    assert preference.only_mine is False
    assert preference.task_on_day is False
    assert preference.task_days_before == 0
    assert preference.task_late_daily is False
    assert db.scalar(select(ReminderPreference)) is None


def test_summary_defaults(db: Session, user: User) -> None:
    make_category(db)
    s = reminders.summary(db, user)
    assert s.update == "Elke dag · 08:30"
    assert (s.tasks, s.categories) == ("Uit", "Alle")


# ---- Update ----


def test_save_update_with_three_times(db: Session, user: User) -> None:
    reminders.save_update(
        db, user, form(**UPDATE | {"time": ["19:00", "8:30", "12:15"]})
    )
    preference = db.get(ReminderPreference, user.id)
    assert preference.update_times == "08:30,12:15,19:00"
    assert reminders.summary(db, user).update == "Elke dag · 08:30, 12:15 en 19:00"


def test_duplicate_times_are_merged(db: Session, user: User) -> None:
    reminders.save_update(db, user, form(**UPDATE | {"time": ["08:30", "08:30"]}))
    assert db.get(ReminderPreference, user.id).update_times == "08:30"


@pytest.mark.parametrize(
    ("times", "message"),
    [
        (["", "", ""], "minstens één tijdstip"),
        (["25:00"], "geen geldige tijd"),
        (["8.30"], "geen geldige tijd"),
        (["08:3"], "geen geldige tijd"),
        (["07:00", "08:00", "09:00", "10:00"], "Maximaal 3"),
    ],
)
def test_update_time_validation(
    db: Session, user: User, times: list[str], message: str
) -> None:
    with pytest.raises(reminders.ReminderFormError) as exc:
        reminders.save_update(db, user, form(**UPDATE | {"time": times}))
    assert message in exc.value.errors["time"]


@pytest.mark.parametrize(
    ("frequency", "days", "expected", "label"),
    [
        ("werkdagen", [], "01234", "Werkdagen"),
        ("weekend", [], "56", "Weekend"),
        ("eigen", ["0", "2", "4"], "024", "ma, wo, vr"),
        ("eigen", ["5", "6"], "56", "Weekend"),
    ],
)
def test_update_days(
    db: Session,
    user: User,
    frequency: str,
    days: list[str],
    expected: str,
    label: str,
) -> None:
    reminders.save_update(
        db, user, form(**UPDATE | {"frequency": frequency, "day": days})
    )
    assert db.get(ReminderPreference, user.id).update_days == expected
    assert reminders.summary(db, user).update.startswith(label)


@pytest.mark.parametrize(
    "fields",
    [
        {"frequency": "eigen", "day": []},
        {"frequency": "eigen", "day": ["9", "x"]},
        {"frequency": "soms"},
    ],
)
def test_update_days_validation(db: Session, user: User, fields: dict) -> None:
    with pytest.raises(reminders.ReminderFormError) as exc:
        reminders.save_update(db, user, form(**UPDATE | fields))
    assert "frequency" in exc.value.errors


def test_lookahead_must_be_a_choice(db: Session, user: User) -> None:
    with pytest.raises(reminders.ReminderFormError) as exc:
        reminders.save_update(db, user, form(**UPDATE | {"lookahead_days": "5"}))
    assert "lookahead_days" in exc.value.errors


def test_update_off_and_only_mine(db: Session, user: User) -> None:
    fields = {k: v for k, v in UPDATE.items() if k != "update_enabled"}
    reminders.save_update(db, user, form(**fields | {"scope": "mine"}))
    preference = db.get(ReminderPreference, user.id)
    assert preference.update_enabled is False
    assert preference.only_mine is True
    assert reminders.summary(db, user).update == "Uit"


# ---- Losse meldingen ----


def test_save_tasks(db: Session, user: User) -> None:
    reminders.save_tasks(
        db,
        user,
        form(task_on_day="1", task_days_before="2", task_late_daily="1"),
    )
    s = reminders.summary(db, user)
    assert s.tasks == "Op de dag · 2 dagen vooraf · bij te laat"


def test_tasks_summary_only_late(db: Session, user: User) -> None:
    reminders.save_tasks(db, user, form(task_days_before="0", task_late_daily="1"))
    assert reminders.summary(db, user).tasks == "Bij te laat"


def test_days_before_must_be_a_choice(db: Session, user: User) -> None:
    with pytest.raises(reminders.ReminderFormError):
        reminders.save_tasks(db, user, form(task_days_before="3"))


# ---- Categorieën ----


def test_save_categories(db: Session, user: User) -> None:
    a, b, c = (make_category(db) for _ in range(3))
    reminders.save_categories(db, user, form(category=[a.id, c.id]))
    assert reminders.muted_category_ids(db, user) == {b.id}
    assert reminders.summary(db, user).categories == "2 van 3"
    reminders.save_categories(db, user, form(category=[a.id, b.id, c.id]))
    assert reminders.muted_category_ids(db, user) == set()


# ---- Audit log ----


def test_changes_are_audited(db: Session, user: User) -> None:
    reminders.save_update(db, user, form(**UPDATE | {"lookahead_days": "7"}))
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "reminders.change"))
    assert entry.actor_id == user.id
    assert entry.old_value == {"lookahead_days": 3, "section": "update"}
    assert entry.new_value == {"lookahead_days": 7, "section": "update"}


def test_saving_without_changes_is_not_audited(db: Session, user: User) -> None:
    reminders.save_update(db, user, form(**UPDATE))
    assert (
        db.scalar(select(AuditLog).where(AuditLog.action == "reminders.change")) is None
    )


def test_category_changes_are_audited(db: Session, user: User) -> None:
    a = make_category(db)
    make_category(db)
    reminders.save_categories(db, user, form(category=[a.id]))
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "reminders.change"))
    assert entry.new_value["section"] == "categories"


# ---- Schermen ----


def test_settings_show_reminder_summary(client: TestClient) -> None:
    text = client.get("/meer").text
    assert "Mijn reminders" in text
    assert "Elke dag · 08:30" in text
    assert "Losse meldingen" in text
    assert "Stille uren" not in text and "Bij te laat" not in text
    assert 'href="/reminders/update"' in text


@pytest.mark.parametrize("slug", ["update", "taken", "categorieen"])
def test_section_pages(client: TestClient, slug: str) -> None:
    response = client.get(f"/reminders/{slug}")
    assert response.status_code == 200
    assert 'hx-post="/reminders/' + slug + '"' in response.text


def test_unknown_section_is_404(client: TestClient) -> None:
    assert client.get("/reminders/onbekend").status_code == 404


def test_post_update_saves(client: TestClient, db: Session, user: User) -> None:
    body = urlencode(UPDATE | {"time": ["07:15", "20:00"]}, doseq=True)
    response = client.post("/reminders/update", content=body, headers=FORM_HEADERS)
    assert response.status_code == 200
    assert "Opgeslagen." in response.text
    db.expire_all()
    assert db.get(ReminderPreference, user.id).update_times == "07:15,20:00"


def test_post_update_shows_errors_and_keeps_input(client: TestClient) -> None:
    body = urlencode(UPDATE | {"time": ["07:15", "99:99"]}, doseq=True)
    response = client.post("/reminders/update", content=body, headers=FORM_HEADERS)
    assert "geen geldige tijd" in response.text
    assert 'value="07:15"' in response.text
    assert 'aria-invalid="true"' in response.text


def test_post_requires_csrf_headers(client: TestClient) -> None:
    assert client.post("/reminders/update", data=UPDATE).status_code == 403


def test_pages_require_login(anon_client: TestClient) -> None:
    response = anon_client.get("/reminders/update")
    assert response.status_code in (302, 303, 401)


# ---- Eerste herinnering bij een vaste datum ----


def _task_form(category_id: int, **extra: str) -> dict:
    return {
        "name": "APK",
        "category_id": str(category_id),
        "recurrence_type": "fixed_date",
        "interval_every": "12",
        "interval_unit": "months",
        **extra,
    }


def test_task_first_reminder_days(client: TestClient, db: Session) -> None:
    category = make_category(db)
    response = client.post(
        "/taken",
        data=_task_form(category.id, first_reminder_days="60"),
        headers=HTMX_HEADERS,
    )
    assert response.status_code == 204
    assert db.scalars(select(Task)).one().first_reminder_days == 60


def test_first_reminder_only_for_fixed_date(client: TestClient, db: Session) -> None:
    category = make_category(db)
    client.post(
        "/taken",
        data=_task_form(
            category.id, recurrence_type="interval", first_reminder_days="60"
        ),
        headers=HTMX_HEADERS,
    )
    assert db.scalars(select(Task)).one().first_reminder_days is None


def test_first_reminder_validation(client: TestClient, db: Session) -> None:
    category = make_category(db)
    response = client.post(
        "/taken",
        data=_task_form(category.id, first_reminder_days="400"),
        headers=HTMX_HEADERS,
    )
    assert "Eerste herinnering" in response.text
    assert db.scalar(select(Task)) is None


def test_seed_sets_apk_first_reminder() -> None:
    apk = next(t for t in TASKS if t.name == "APK")
    assert apk.first_reminder_days == 60


def test_quiet_hours_page_is_gone(client: TestClient) -> None:
    assert client.get("/reminders/stille-uren").status_code == 404
