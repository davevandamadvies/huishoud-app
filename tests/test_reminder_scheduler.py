from datetime import date, datetime, time, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import push, reminder_content, reminder_scheduler, reminders, settings_store
from app.models import (
    Occurrence,
    OccurrenceOwner,
    OccurrenceStatus,
    Performer,
    ReminderLog,
    ReminderPreference,
    User,
)
from app.reminder_scheduler import Slot, due_slots, run, task_reason
from tests.factories import make_category, make_task, make_user
from tests.push_helpers import Browser

# Zaterdag 3 oktober 2026
TODAY = date(2026, 10, 3)
AT_0830 = datetime(2026, 10, 3, 8, 30)
ENDPOINT = "https://fcm.googleapis.com/fcm/send/"


def prefs(db: Session, user: User, **changes: object) -> ReminderPreference:
    preference = reminders.get(db, user)
    for key, value in changes.items():
        setattr(preference, key, value)
    db.add(preference)
    db.commit()
    return preference


class Outbox:
    """Nep-pushdienst: ontsleutelt wat er binnenkomt."""

    def __init__(self) -> None:
        self.browsers: dict[str, Browser] = {}
        self.messages: list[tuple[str, dict]] = []

    def device(self, db: Session, user: User) -> None:
        browser = Browser()
        endpoint = f"{ENDPOINT}{user.id}"
        self.browsers[endpoint] = browser
        push.subscribe(
            db,
            user,
            endpoint=endpoint,
            p256dh=browser.p256dh,
            auth=browser.auth_b64,
            label="Chrome op Android",
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        browser = self.browsers[str(request.url)]
        self.messages.append((str(request.url), browser.decrypt(request.content)))
        return httpx.Response(201)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def for_user(self, user: User) -> list[dict]:
        return [m for url, m in self.messages if url == f"{ENDPOINT}{user.id}"]


@pytest.fixture
def outbox(db: Session, user: User, vapid) -> Outbox:
    box = Outbox()
    box.device(db, user)
    return box


def go(db: Session, outbox: Outbox, now: datetime = AT_0830) -> int:
    return run(db, now, transport=outbox.transport)


# ---- Tijdstippen ----


def test_slot_at_exact_time(db: Session, user: User) -> None:
    preference = reminders.get(db, user)
    assert list(due_slots(preference, AT_0830, [time(8, 30)], None)) == [
        Slot(TODAY, "08:30", 0)
    ]


@pytest.mark.parametrize(
    ("minutes_late", "due"), [(-1, False), (0, True), (14, True), (15, False)]
)
def test_catch_up_window(db: Session, user: User, minutes_late: int, due: bool) -> None:
    preference = reminders.get(db, user)
    now = AT_0830 + timedelta(minutes=minutes_late)
    assert bool(list(due_slots(preference, now, [time(8, 30)], None))) is due


def test_weekdays_filter(db: Session, user: User) -> None:
    preference = reminders.get(db, user)
    # 3 oktober 2026 is een zaterdag (5)
    assert not list(due_slots(preference, AT_0830, [time(8, 30)], {0, 1, 2, 3, 4}))
    assert list(due_slots(preference, AT_0830, [time(8, 30)], {5, 6}))


def test_three_slots_have_their_own_index(db: Session, user: User) -> None:
    preference = reminders.get(db, user)
    times = [time(8, 30), time(12, 0), time(19, 0)]
    slots = list(due_slots(preference, datetime(2026, 10, 3, 19, 0), times, None))
    assert slots == [Slot(TODAY, "19:00", 2)]


def test_no_quiet_hours_late_and_early_slots(db: Session, user: User) -> None:
    """Geen stille uren: een tijdstip om 23:00 of 06:00 gaat gewoon dan weg."""
    preference = reminders.get(db, user)
    late = datetime(2026, 10, 3, 23, 0)
    assert list(due_slots(preference, late, [time(23, 0)], None)) == [
        Slot(TODAY, "23:00", 0)
    ]
    early = datetime(2026, 10, 3, 6, 0)
    assert list(due_slots(preference, early, [time(6, 0)], None)) == [
        Slot(TODAY, "06:00", 0)
    ]


def test_slot_just_before_midnight_caught_up_after(db: Session, user: User) -> None:
    preference = reminders.get(db, user)
    after_midnight = datetime(2026, 10, 4, 0, 5)
    assert list(due_slots(preference, after_midnight, [time(23, 55)], {5})) == [
        Slot(TODAY, "23:55", 0)
    ]


# ---- Versturen en niet dubbel ----


def test_update_is_sent_once(db: Session, user: User, outbox: Outbox) -> None:
    make_task(db, name="Ramen", due=TODAY + timedelta(days=1))
    assert go(db, outbox) == 1
    assert go(db, outbox) == 0
    assert go(db, outbox, AT_0830 + timedelta(minutes=10)) == 0
    assert len(outbox.for_user(user)) == 1
    assert db.scalar(select(func.count()).select_from(ReminderLog)) == 1


def test_missed_slot_is_caught_up_within_15_minutes(
    db: Session, user: User, outbox: Outbox
) -> None:
    assert go(db, outbox, AT_0830 + timedelta(minutes=16)) == 0
    assert go(db, outbox, AT_0830 + timedelta(minutes=14)) == 1


def test_each_time_of_day_is_sent(db: Session, user: User, outbox: Outbox) -> None:
    prefs(db, user, update_times="08:30,19:00")
    assert go(db, outbox) == 1
    assert go(db, outbox, datetime(2026, 10, 3, 19, 0)) == 1
    titles = [m["title"] for m in outbox.for_user(user)]
    assert titles[0] != titles[1]  # andere variant op dezelfde dag


def test_nothing_without_vapid(db: Session, user: User) -> None:
    assert run(db, AT_0830) == 0


def test_nothing_without_device(db: Session, user: User, vapid) -> None:
    assert run(db, AT_0830) == 0


def test_update_off(db: Session, user: User, outbox: Outbox) -> None:
    prefs(db, user, update_enabled=False)
    assert go(db, outbox) == 0


def test_update_not_on_unchosen_day(db: Session, user: User, outbox: Outbox) -> None:
    prefs(db, user, update_days=reminders.WEEKDAYS)
    assert go(db, outbox) == 0


def test_update_goes_to_everyone_who_enabled_it(
    db: Session, user: User, outbox: Outbox
) -> None:
    partner = make_user(db, name="Partner")
    outbox.device(db, partner)
    prefs(db, partner, update_times="09:00")
    assert go(db, outbox) == 1
    assert outbox.for_user(user) and not outbox.for_user(partner)


def test_send_errors_do_not_stop_the_run(
    db: Session, user: User, outbox: Outbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("stuk")

    monkeypatch.setattr(push, "send", broken)
    assert go(db, outbox) == 1  # vastgelegd, fout gelogd, niet opnieuw
    assert go(db, outbox) == 0


def test_payload_opens_today(db: Session, user: User, outbox: Outbox) -> None:
    go(db, outbox)
    message = outbox.for_user(user)[0]
    assert message["url"] == "/"
    assert message["tag"] == "update"


# ---- Losse meldingen ----


def test_task_reasons(db: Session, user: User) -> None:
    preference = reminders.get(db, user)
    preference.task_on_day = True
    preference.task_days_before = 2
    preference.task_late_daily = True

    def reason(due: date, **kwargs) -> str | None:
        task = make_task(db, name=f"T{due}", due=due, **kwargs)
        occurrence = db.scalar(select(Occurrence).where(Occurrence.task_id == task.id))
        return task_reason(occurrence, TODAY, preference)

    assert reason(TODAY) == "due"
    assert reason(TODAY + timedelta(days=2)) == "before"
    assert reason(TODAY + timedelta(days=1)) is None
    assert reason(TODAY - timedelta(days=3)) == "late"
    assert (
        reason(
            TODAY + timedelta(days=60),
            recurrence="fixed_date",
            every=12,
            first_reminder_days=60,
        )
        == "first"
    )


def test_late_reminders_only_when_enabled(db: Session, user: User) -> None:
    preference = reminders.get(db, user)
    task = make_task(db, due=TODAY - timedelta(days=1))
    occurrence = db.scalar(select(Occurrence).where(Occurrence.task_id == task.id))
    assert task_reason(occurrence, TODAY, preference) is None


def test_task_message_goes_to_owner(db: Session, user: User, outbox: Outbox) -> None:
    partner = make_user(db, name="Partner")
    outbox.device(db, partner)
    for person in (user, partner):
        prefs(db, person, task_on_day=True, update_enabled=False)
    task = make_task(db, name="Badkamer", due=TODAY, owner_id=partner.id)
    assert go(db, outbox) == 1
    message = outbox.for_user(partner)[0]
    assert message["title"] == "Badkamer"
    assert message["url"] == f"/taken/{task.id}"
    assert message["body"] == "Staat voor vandaag."
    assert not outbox.for_user(user)


def test_task_message_without_owner_goes_to_everyone(
    db: Session, user: User, outbox: Outbox
) -> None:
    partner = make_user(db, name="Partner")
    outbox.device(db, partner)
    for person in (user, partner):
        prefs(db, person, task_on_day=True, update_enabled=False)
    make_task(db, name="Ramen", due=TODAY)
    assert go(db, outbox) == 2


def test_planned_owners_go_before_fixed_owner(
    db: Session, user: User, outbox: Outbox
) -> None:
    partner = make_user(db, name="Partner")
    outbox.device(db, partner)
    for person in (user, partner):
        prefs(db, person, task_on_day=True, update_enabled=False)
    task = make_task(db, name="Ramen", owner_id=partner.id)
    occurrence = Occurrence(
        task_id=task.id,
        status=OccurrenceStatus.PLANNED,
        due_date=TODAY,
        planned_date=TODAY,
    )
    db.add(occurrence)
    db.flush()
    db.add(OccurrenceOwner(occurrence_id=occurrence.id, user_id=user.id))
    db.commit()
    go(db, outbox)
    assert outbox.for_user(user) and not outbox.for_user(partner)


def test_first_reminder_for_fixed_date_is_always_sent(
    db: Session, user: User, outbox: Outbox
) -> None:
    prefs(db, user, update_enabled=False)  # losse meldingen staan uit
    make_task(
        db,
        name="APK",
        recurrence="fixed_date",
        every=12,
        due=TODAY + timedelta(days=60),
        first_reminder_days=60,
    )
    assert go(db, outbox) == 1
    assert outbox.for_user(user)[0]["body"] == "Over 60 dagen."


def test_task_messages_use_first_time(db: Session, user: User, outbox: Outbox) -> None:
    prefs(db, user, task_on_day=True, update_enabled=False, update_times="06:00,12:00")
    make_task(db, name="Ramen", due=TODAY)
    assert go(db, outbox, datetime(2026, 10, 3, 6, 0)) == 1  # geen stille uren
    assert go(db, outbox, datetime(2026, 10, 3, 12, 0)) == 0


def test_muted_category_gets_no_task_messages(
    db: Session, user: User, outbox: Outbox
) -> None:
    from app.models import ReminderMutedCategory

    prefs(db, user, task_on_day=True, update_enabled=False)
    category = make_category(db)
    make_task(db, name="Gras maaien", category=category, due=TODAY)
    db.add(ReminderMutedCategory(user_id=user.id, category_id=category.id))
    db.commit()
    assert go(db, outbox) == 0


def test_late_task_message_text(db: Session, user: User, outbox: Outbox) -> None:
    prefs(db, user, task_late_daily=True, update_enabled=False)
    make_task(db, name="Ramen", due=TODAY - timedelta(days=4))
    go(db, outbox)
    assert (
        outbox.for_user(user)[0]["body"]
        == "Deze staat al 4 dagen open. Lukt het vandaag?"
    )
    assert go(db, outbox, AT_0830 + timedelta(days=1)) == 1  # dagelijks


# ---- Inhoud van de update ----


def message(db: Session, user: User, **kwargs) -> reminder_content.Message:
    options = {"lookahead": 3, "only_mine": False, "muted": set()} | kwargs
    return reminder_content.update_message(
        db,
        user,
        TODAY,
        0,
        pending=reminder_content.pending_occurrences(db),
        **options,
    )


def test_update_body_counts(db: Session, user: User) -> None:
    make_task(db, name="Stofzuigen", due=TODAY + timedelta(days=1))
    make_task(db, name="Was", due=TODAY + timedelta(days=3))
    make_task(db, name="Later", due=TODAY + timedelta(days=4))
    make_task(db, name="Ramen", due=TODAY - timedelta(days=2))
    make_task(db, name="Badkamer", due=TODAY - timedelta(days=1), owner_id=user.id)
    make_task(db, name="Toilet", due=TODAY, owner_id=user.id)
    assert message(db, user).body == (
        "Komende 3 dagen: 3 taken · 2 lopen achter (Badkamer, Ramen)"
        " · 2 voor jou vandaag"
    )


def test_update_today_only_and_singular(db: Session, user: User) -> None:
    make_task(db, name="Toilet", due=TODAY)
    make_task(db, name="Ramen", due=TODAY - timedelta(days=2))
    make_task(db, name="Morgen", due=TODAY + timedelta(days=1))
    assert message(db, user, lookahead=0).body == (
        "Vandaag: 1 taak · 1 loopt achter (Ramen)"
    )


def test_update_only_mine(db: Session, user: User) -> None:
    make_task(db, name="Toilet", due=TODAY, owner_id=user.id)
    make_task(db, name="Ramen", due=TODAY)
    assert message(db, user, only_mine=True).body == "Komende 3 dagen: 1 taak"


def test_update_respects_muted_categories(db: Session, user: User) -> None:
    garden = make_category(db, name="Tuin")
    make_task(db, name="Gras", category=garden, due=TODAY)
    make_task(db, name="Toilet", due=TODAY)
    assert message(db, user, muted={garden.id}).body == "Komende 3 dagen: 1 taak"


def test_many_late_names_are_shortened(db: Session, user: User) -> None:
    for name in ("A", "B", "C", "D", "E"):
        make_task(db, name=name, due=TODAY - timedelta(days=1))
    assert "5 lopen achter (A, B, C +2)" in message(db, user).body


def test_competition_line(db: Session, user: User) -> None:
    settings_store.set_value(db, user, settings_store.COMPETITION, "true")
    task = make_task(db, name="Toilet")
    occurrence = Occurrence(
        task_id=task.id,
        status=OccurrenceStatus.DONE,
        due_date=TODAY,
        completed_on=TODAY,
        points=5,
    )
    db.add(occurrence)
    db.flush()
    db.add(Performer(occurrence_id=occurrence.id, user_id=user.id, points=5))
    db.commit()
    assert message(db, user).body.endswith("\nWeekstand: Dave 5")


def test_no_competition_line_when_off(db: Session, user: User) -> None:
    assert "Weekstand" not in message(db, user).body


# ---- Complimenten ----


def title(db: Session, user: User, slot_index: int = 0) -> str:
    pending = reminder_content.pending_occurrences(db)
    late = sum(1 for o in pending if o.effective_date < TODAY)
    return reminder_content.compliment(db, TODAY, slot_index, late, pending)


def test_all_done_compliment(db: Session, user: User) -> None:
    make_task(db, due=TODAY + timedelta(days=2))
    assert title(db, user) in reminder_content.COMPLIMENTS["all_done"]


def test_behind_is_friendly(db: Session, user: User) -> None:
    make_task(db, due=TODAY - timedelta(days=2))
    text = title(db, user)
    assert text in reminder_content.COMPLIMENTS["behind"]
    assert "!" not in text  # rustig, geen uitroepen bij een achterstand


def done(db: Session, name: str, due: date, completed: date) -> None:
    task = make_task(db, name=name)
    db.add(
        Occurrence(
            task_id=task.id,
            status=OccurrenceStatus.DONE,
            due_date=due,
            completed_on=completed,
        )
    )
    db.commit()


def test_backlog_cleared_compliment(db: Session, user: User) -> None:
    done(db, "Ramen", TODAY - timedelta(days=5), TODAY)
    assert title(db, user) in reminder_content.COMPLIMENTS["cleared"]


def _age_history(db: Session, days: int) -> None:
    from app.db import utcnow

    for occurrence in db.scalars(select(Occurrence)):
        occurrence.created_at = utcnow() - timedelta(days=days)
    db.commit()


def test_streak_compliment(db: Session, user: User) -> None:
    make_task(db, due=TODAY + timedelta(days=1))
    _age_history(db, 10)
    streak = reminder_content.streak_without_backlog(db, TODAY)
    assert streak >= 3
    assert title(db, user) == reminder_content.pick("streak", TODAY, 0, n=streak)


def test_streak_stops_at_a_late_day(db: Session, user: User) -> None:
    # Was te laat van 25 sep tot 1 okt (afgevinkt op 1 okt)
    done(db, "Ramen", date(2026, 9, 25), date(2026, 10, 1))
    _age_history(db, 20)
    # 1 en 2 okt niets te laat (op 1 okt ingehaald), 30 sep wel
    assert reminder_content.streak_without_backlog(db, TODAY) == 2


def test_streak_without_history_is_zero(db: Session, user: User) -> None:
    assert reminder_content.streak_without_backlog(db, TODAY) == 0


def test_high_week_score_compliment(db: Session, user: User) -> None:
    for n in range(4):
        done(db, f"Klus {n}", TODAY - timedelta(days=1), TODAY - timedelta(days=1))
    make_task(db, name="Nog", due=TODAY + timedelta(days=1))
    # oud genoeg voor geen "achterstand weg", maar zonder reeks
    assert title(db, user) == reminder_content.pick("week", TODAY, 0, done=4, total=5)


def test_variants_differ_per_slot_and_per_day() -> None:
    a = reminder_content.pick("all_done", TODAY, 0)
    b = reminder_content.pick("all_done", TODAY, 1)
    c = reminder_content.pick("all_done", TODAY, 2)
    assert len({a, b, c}) == 3
    assert reminder_content.pick("all_done", TODAY + timedelta(days=1), 0) == b


def test_scheduler_does_not_start_in_tests(db_url: str, vapid) -> None:
    import asyncio

    async def check() -> None:
        async with reminder_scheduler.running():
            names = {t.get_name() for t in asyncio.all_tasks()}
            assert "herinneringen" not in names

    asyncio.run(check())
