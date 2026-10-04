"""Planner voor herinneringen, draait binnen de app.

Een achtergrondtaak kijkt elke minuut (tijdzone Europe/Amsterdam) wat er
volgens de voorkeuren van elke gebruiker verstuurd moet worden.

- Niet dubbel: elke verzending krijgt eerst een rij in `reminder_log` met
  een unieke sleutel (gebruiker, soort, onderwerp, dag, tijdstip).
- Ingehaald: een tijdstip dat tijdens een herstart is gemist, gaat hooguit
  15 minuten later alsnog weg.
- Fouten worden gelogd en houden de app niet tegen.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import httpx
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import push, reminder_content, reminders
from app.dates import TIMEZONE
from app.db import new_session
from app.models import (
    Occurrence,
    PushSubscription,
    ReminderLog,
    ReminderPreference,
    User,
    UserStatus,
)
from app.recurrence import RecurrenceType, in_season
from app.settings import get_settings

logger = logging.getLogger(__name__)

CATCH_UP = timedelta(minutes=15)


def local_now() -> datetime:
    """Huidige tijd in de tijdzone van het huishouden (zonder tzinfo)."""
    return datetime.now(TIMEZONE).replace(tzinfo=None, microsecond=0)


@dataclass(frozen=True)
class Slot:
    day: date  # de dag waar het tijdstip bij hoort
    slot: str  # het ingestelde tijdstip, HH:MM
    index: int  # 0, 1 of 2: het hoeveelste tijdstip van die dag


def due_slots(
    preference: ReminderPreference,
    now: datetime,
    times: list[time],
    weekdays: set[int] | None,
) -> Iterator[Slot]:
    """Tijdstippen die nu (of hooguit 15 minuten geleden) aan de beurt zijn."""
    for day in (now.date() - timedelta(days=1), now.date()):
        if weekdays is not None and day.weekday() not in weekdays:
            continue
        for index, moment in enumerate(times):
            at = datetime.combine(day, moment)
            if at <= now < at + CATCH_UP:
                yield Slot(day, reminders.format_time(moment), index)


def task_reason(
    occurrence: Occurrence, day: date, preference: ReminderPreference
) -> str | None:
    """Waarom deze taak vandaag een losse melding krijgt (of None)."""
    effective = occurrence.effective_date
    if effective is None:
        return None
    task = occurrence.task
    if (
        task.recurrence_type == RecurrenceType.FIXED_DATE
        and task.first_reminder_days
        and effective == day + timedelta(days=task.first_reminder_days)
    ):
        return "first"
    if effective < day:
        return "late" if preference.task_late_daily else None
    if effective == day and preference.task_on_day:
        return "due"
    if preference.task_days_before and effective == day + timedelta(
        days=preference.task_days_before
    ):
        return "before"
    return None


def _claim(db: Session, user: User, kind: str, subject: str, slot: Slot) -> bool:
    """Leg de verzending vast; False als hij al eerder is gedaan."""
    already = db.scalar(
        select(
            exists().where(
                ReminderLog.user_id == user.id,
                ReminderLog.kind == kind,
                ReminderLog.subject == subject,
                ReminderLog.day == slot.day,
                ReminderLog.slot == slot.slot,
            )
        )
    )
    if already:
        return False
    try:
        with db.begin_nested():
            db.add(
                ReminderLog(
                    user_id=user.id,
                    kind=kind,
                    subject=subject,
                    day=slot.day,
                    slot=slot.slot,
                )
            )
    except IntegrityError:
        return False
    db.commit()
    return True


def _send(
    db: Session,
    user: User,
    message: reminder_content.Message,
    transport: httpx.BaseTransport | None,
) -> None:
    subscriptions = push.subscriptions_for(db, user)
    if not subscriptions:
        return
    try:
        push.send(db, subscriptions, message.payload(), transport=transport)
    except Exception:
        db.rollback()
        logger.exception("Herinnering versturen mislukt (gebruiker %s)", user.id)


def run(
    db: Session,
    now: datetime,
    *,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """Eén ronde: verstuur wat nu aan de beurt is. Geeft het aantal meldingen."""
    if not get_settings().push_enabled:
        return 0
    everyone = list(
        db.scalars(
            select(User).where(User.status == UserStatus.ACTIVE).order_by(User.id)
        )
    )
    with_device = set(db.scalars(select(PushSubscription.user_id).distinct()))
    users = [u for u in everyone if u.id in with_device]
    if not users:
        return 0
    pending = reminder_content.pending_occurrences(db)
    sent = 0
    for user in users:
        preference = reminders.get(db, user)
        muted = reminders.muted_category_ids(db, user)
        times = reminders.times(preference)

        if preference.update_enabled:
            for slot in due_slots(preference, now, times, reminders.days(preference)):
                if not _claim(db, user, "update", "update", slot):
                    continue
                message = reminder_content.update_message(
                    db,
                    user,
                    slot.day,
                    slot.index,
                    lookahead=preference.lookahead_days,
                    only_mine=preference.only_mine,
                    muted=muted,
                    pending=pending,
                )
                _send(db, user, message, transport)
                sent += 1

        # Losse meldingen komen op het eerste tijdstip, elke dag.
        for slot in due_slots(preference, now, times[:1], None):
            for occurrence in pending:
                if occurrence.task.category_id in muted:
                    continue
                if not in_season(slot.day, occurrence.task.season):
                    continue  # buiten het seizoen geen herinneringen
                if user not in reminder_content.recipients(occurrence, everyone):
                    continue
                reason = task_reason(occurrence, slot.day, preference)
                if reason is None:
                    continue
                if not _claim(db, user, "task", str(occurrence.id), slot):
                    continue
                message = reminder_content.task_message(occurrence, slot.day, reason)
                _send(db, user, message, transport)
                sent += 1
    return sent


def tick() -> None:
    with new_session() as db:
        count = run(db, local_now())
    if count:
        logger.info("Herinneringen verstuurd: %d", count)


async def loop() -> None:
    """Elke minuut een ronde, net na het begin van de minuut."""
    while True:
        await asyncio.sleep(60 - datetime.now().second + 1)
        try:
            await asyncio.to_thread(tick)
        except Exception:
            logger.exception("Planner voor herinneringen: ronde mislukt")


@contextlib.asynccontextmanager
async def running() -> AsyncIterator[None]:
    """Start de planner (als push is ingesteld) en stop hem netjes."""
    settings = get_settings()
    if not settings.push_enabled or settings.app_env == "test":
        if settings.app_env != "test":
            logger.info("Herinneringen staan uit: VAPID-sleutels ontbreken.")
        yield
        return
    task = asyncio.create_task(loop(), name="herinneringen")
    logger.info("Planner voor herinneringen gestart.")
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
