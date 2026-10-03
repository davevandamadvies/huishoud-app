"""Inhoud van herinneringen: de stand van het huishouden en complimenten.

Bewust vriendelijk: bij een achterstand motiveren, nooit verwijten.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app import planning, scores, settings_store
from app.dates import TIMEZONE
from app.models import Occurrence, OccurrenceStatus, Task, User
from app.today_view import week_bounds

PENDING = (OccurrenceStatus.OPEN, OccurrenceStatus.PLANNED)
MAX_NAMES = 3
STREAK_LOOKBACK = 30


def pending_occurrences(db: Session) -> list[Occurrence]:
    """Openstaande en geplande uitvoeringen met een datum (niet gearchiveerd)."""
    return list(
        db.scalars(
            select(Occurrence)
            .join(Task, Task.id == Occurrence.task_id)
            .where(
                Occurrence.status.in_(PENDING),
                Task.archived_at.is_(None),
                or_(
                    Occurrence.due_date.is_not(None),
                    Occurrence.planned_date.is_not(None),
                ),
            )
            .options(
                joinedload(Occurrence.task).joinedload(Task.owner),
                selectinload(Occurrence.owners),
            )
        )
    )


def recipients(occurrence: Occurrence, everyone: list[User]) -> list[User]:
    """Eigenaren van deze keer, anders de vaste eigenaar, anders iedereen."""
    people = [u for u in planning.responsible(occurrence) if u.is_active]
    return people or everyone


# ---- Statistiek voor complimenten ----


def _late_on(db: Session, day: date) -> bool:
    """Liep er op `day` iets achter (vervaldatum voorbij, nog niet gedaan)?"""
    query = (
        select(Occurrence.id)
        .join(Task, Task.id == Occurrence.task_id)
        .where(
            Task.archived_at.is_(None),
            Occurrence.due_date < day,
            or_(
                Occurrence.status.in_(PENDING),
                Occurrence.completed_on > day,
            ),
            or_(Occurrence.planned_date.is_(None), Occurrence.planned_date < day),
        )
        .limit(1)
    )
    return db.scalar(query) is not None


def streak_without_backlog(db: Session, today: date) -> int:
    """Aantal dagen op rij (tot en met gisteren) zonder achterstand.

    Telt niet verder terug dan de eerste uitvoering in de app.
    """
    first = db.scalar(select(func.min(Occurrence.created_at)))
    if first is None:
        return 0
    history = (today - first.astimezone(TIMEZONE).date()).days
    days = 0
    for back in range(1, min(STREAK_LOOKBACK, history) + 1):
        if _late_on(db, today - timedelta(days=back)):
            break
        days += 1
    return days


def backlog_recently_cleared(db: Session, today: date) -> bool:
    """Is er de afgelopen twee dagen een te late taak weggewerkt?"""
    late_done = db.scalar(
        select(Occurrence.id)
        .where(
            Occurrence.status == OccurrenceStatus.DONE,
            Occurrence.completed_on >= today - timedelta(days=1),
            Occurrence.due_date.is_not(None),
            Occurrence.completed_on > Occurrence.due_date,
        )
        .limit(1)
    )
    return late_done is not None


def week_progress(
    db: Session, today: date, pending: list[Occurrence]
) -> tuple[int, int]:
    """(gedaan, totaal) voor deze week: afgevinkt + nog open tot zondag."""
    start, end = week_bounds(today)
    done = len(
        db.scalars(
            select(Occurrence.id).where(
                Occurrence.status == OccurrenceStatus.DONE,
                Occurrence.completed_on >= start,
                Occurrence.completed_on <= end,
            )
        ).all()
    )
    still_open = sum(1 for o in pending if o.effective_date and o.effective_date <= end)
    return done, done + still_open


# ---- Complimenten ----

COMPLIMENTS: dict[str, tuple[str, ...]] = {
    "cleared": (
        "De achterstand is weg, top!",
        "Alles weer bij, mooi ingehaald!",
        "Achterstand weggewerkt, lekker gedaan!",
    ),
    "streak": (
        "Al {n} dagen niets te laat 🌱",
        "{n} dagen op rij alles bij, knap!",
        "Al {n} dagen zonder achterstand, zo houden!",
    ),
    "week": (
        "Al {done} van {total} taken gedaan deze week, lekker bezig!",
        "{done} van {total} taken deze week al klaar, mooi werk!",
        "Deze week al {done} van {total} gedaan, goed bezig samen!",
    ),
    "all_done": (
        "Alles is bij, knap gedaan samen!",
        "Niets te laat, het huishouden loopt als een trein!",
        "Alles op schema, goed bezig!",
    ),
    "behind": (
        "Een paar dingetjes liggen nog te wachten, samen zijn ze zo gedaan.",
        "Er staat nog wat open, één taakje vandaag scheelt al.",
        "Even een paar taken inhalen en je bent weer helemaal bij.",
    ),
}


def pick(situation: str, day: date, slot_index: int, **values: object) -> str:
    """Kies een variant: per dag anders, en niet twee keer op dezelfde dag."""
    variants = COMPLIMENTS[situation]
    text = variants[(day.toordinal() + slot_index) % len(variants)]
    return text.format(**values)


def compliment(
    db: Session,
    today: date,
    slot_index: int,
    late_count: int,
    pending: list[Occurrence],
) -> str:
    done, total = week_progress(db, today, pending)
    high_week = total >= 3 and done / total >= 0.8
    if late_count:
        if high_week:
            return pick("week", today, slot_index, done=done, total=total)
        return pick("behind", today, slot_index)
    if backlog_recently_cleared(db, today):
        return pick("cleared", today, slot_index)
    streak = streak_without_backlog(db, today)
    if streak >= 3:
        return pick("streak", today, slot_index, n=streak)
    if high_week:
        return pick("week", today, slot_index, done=done, total=total)
    return pick("all_done", today, slot_index)


# ---- Teksten ----


def _taken(n: int) -> str:
    return "1 taak" if n == 1 else f"{n} taken"


def _names(occurrences: list[Occurrence]) -> str:
    names = sorted({o.task.name for o in occurrences})
    shown = ", ".join(names[:MAX_NAMES])
    if len(names) > MAX_NAMES:
        shown += f" +{len(names) - MAX_NAMES}"
    return shown


def period_label(lookahead: int) -> str:
    return "Vandaag" if lookahead == 0 else f"Komende {lookahead} dagen"


@dataclass
class Message:
    title: str
    body: str
    url: str
    tag: str
    occurrence_ids: list[int] = field(default_factory=list)

    def payload(self) -> dict:
        return {
            "title": self.title,
            "body": self.body,
            "url": self.url,
            "tag": self.tag,
        }


def update_message(
    db: Session,
    user: User,
    today: date,
    slot_index: int,
    *,
    lookahead: int,
    only_mine: bool,
    muted: set[int],
    pending: list[Occurrence],
) -> Message:
    def mine(o: Occurrence) -> bool:
        return user in planning.responsible(o)

    relevant = [o for o in pending if o.task.category_id not in muted]
    if only_mine:
        relevant = [o for o in relevant if mine(o)]
    horizon = today + timedelta(days=lookahead)
    upcoming = [o for o in relevant if today <= o.effective_date <= horizon]
    late = [o for o in relevant if o.effective_date < today]
    mine_today = [o for o in relevant if o.effective_date <= today and mine(o)]

    parts = [f"{period_label(lookahead)}: {_taken(len(upcoming))}"]
    if late:
        verb = "loopt" if len(late) == 1 else "lopen"
        parts.append(f"{len(late)} {verb} achter ({_names(late)})")
    if mine_today and not only_mine:
        parts.append(f"{len(mine_today)} voor jou vandaag")
    body = " · ".join(parts)

    if settings_store.competition_enabled(db):
        board = sorted(
            scores.standings(db, *scores.bounds(scores.Period.WEEK, today)),
            key=lambda s: -s.points,
        )
        if any(s.points for s in board):
            body += "\nWeekstand: " + " · ".join(
                f"{s.user.display_name} {s.points}" for s in board
            )

    title = compliment(db, today, slot_index, len(late), pending)
    return Message(title=title, body=body, url="/", tag="update")


def task_message(occurrence: Occurrence, today: date, reason: str) -> Message:
    """Losse melding over één taak."""
    task = occurrence.task
    effective = occurrence.effective_date
    if reason == "late":
        days = (today - effective).days
        body = (
            "Deze staat sinds gisteren open."
            if days == 1
            else f"Deze staat al {days} dagen open. Lukt het vandaag?"
        )
    elif effective == today:
        body = "Staat voor vandaag."
    else:
        days = (effective - today).days
        body = "Staat voor morgen." if days == 1 else f"Over {days} dagen."
    return Message(
        title=task.name,
        body=body,
        url=f"/taken/{task.id}",
        tag=f"taak-{task.id}",
        occurrence_ids=[occurrence.id],
    )
