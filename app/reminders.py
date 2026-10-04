"""Herinneringsvoorkeuren per gebruiker ("Mijn reminders").

Elke gebruiker stelt zelf in wanneer de update komt (dagen, 1–3 tijdstippen),
hoe ver die vooruitkijkt, of er losse meldingen per taak komen en welke
categorieën meedoen. Er komen geen andere meldingen dan deze reminders, dus
ook geen stille uren: alles komt op de tijdstippen die je zelf kiest.
Zonder opgeslagen rij gelden de standaarden.
"""

from dataclasses import dataclass
from datetime import time

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import audit
from app.forms import FormData
from app.models import Category, ReminderMutedCategory, ReminderPreference, User

ALL_DAYS = "0123456"
WEEKDAYS = "01234"
WEEKEND = "56"
DAY_NAMES = ("ma", "di", "wo", "do", "vr", "za", "zo")
FREQUENCIES = {
    "elke-dag": ("Elke dag", ALL_DAYS),
    "werkdagen": ("Alleen werkdagen", WEEKDAYS),
    "weekend": ("Alleen weekend", WEEKEND),
    "eigen": ("Eigen keuze van dagen", None),
}
LOOKAHEAD_CHOICES = {0: "Alleen vandaag", 3: "3 dagen", 7: "7 dagen"}
DAYS_BEFORE_CHOICES = {0: "Niet", 1: "1 dag", 2: "2 dagen", 7: "7 dagen"}
MAX_TIMES = 3

DEFAULTS = {
    "update_enabled": True,
    "update_days": ALL_DAYS,
    "update_times": "08:30",
    "lookahead_days": 3,
    "only_mine": False,
    "task_on_day": False,
    "task_days_before": 0,
    "task_late_daily": False,
}


class ReminderFormError(Exception):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("Ongeldige invoer")
        self.errors = errors


def get(db: Session, user: User) -> ReminderPreference:
    """Opgeslagen voorkeuren, of (niet opgeslagen) standaardwaarden."""
    preference = db.get(ReminderPreference, user.id)
    if preference is None:
        preference = ReminderPreference(user_id=user.id, **DEFAULTS)
    return preference


def muted_category_ids(db: Session, user: User) -> set[int]:
    return set(
        db.scalars(
            select(ReminderMutedCategory.category_id).where(
                ReminderMutedCategory.user_id == user.id
            )
        )
    )


# ---- Hulpjes voor tijden en dagen ----


def parse_time(value: str) -> time:
    """'8:30' of '08:30' → time; ValueError bij iets anders."""
    hours, sep, minutes = value.strip().partition(":")
    if not sep or not hours.isdigit() or len(minutes) != 2 or not minutes.isdigit():
        raise ValueError(value)
    return time(int(hours), int(minutes))


def format_time(value: time) -> str:
    return value.strftime("%H:%M")


def times(preference: ReminderPreference) -> list[time]:
    return [parse_time(t) for t in preference.update_times.split(",") if t]


def days(preference: ReminderPreference) -> set[int]:
    return {int(d) for d in preference.update_days}


def frequency_key(day_string: str) -> str:
    for key, (_label, preset) in FREQUENCIES.items():
        if preset == day_string:
            return key
    return "eigen"


def days_label(day_string: str) -> str:
    key = frequency_key(day_string)
    if key != "eigen":
        return {"elke-dag": "Elke dag", "werkdagen": "Werkdagen", "weekend": "Weekend"}[
            key
        ]
    return ", ".join(DAY_NAMES[int(d)] for d in day_string)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " en " + items[-1]


# ---- Samenvattingen voor het overzicht ----


@dataclass(frozen=True)
class Summary:
    update: str
    tasks: str
    categories: str


def summary(db: Session, user: User) -> Summary:
    preference = get(db, user)
    if preference.update_enabled:
        update = f"{days_label(preference.update_days)} · " + _join(
            preference.update_times.split(",")
        )
    else:
        update = "Uit"
    parts = []
    if preference.task_on_day:
        parts.append("op de dag")
    if preference.task_days_before:
        parts.append(f"{DAYS_BEFORE_CHOICES[preference.task_days_before]} vooraf")
    if preference.task_late_daily:
        parts.append("bij te laat")
    tasks = " · ".join(parts).capitalize() if parts else "Uit"
    total = len(db.scalars(select(Category.id)).all())
    muted = len(muted_category_ids(db, user))
    return Summary(
        update=update,
        tasks=tasks,
        categories="Alle" if muted == 0 else f"{total - muted} van {total}",
    )


# ---- Opslaan ----


def _snapshot(preference: ReminderPreference) -> dict:
    return {key: getattr(preference, key) for key in DEFAULTS}


def _save(
    db: Session, user: User, section: str, changes: dict[str, object]
) -> ReminderPreference:
    preference = get(db, user)
    old = _snapshot(preference)
    for key, value in changes.items():
        setattr(preference, key, value)
    new = _snapshot(preference)
    if preference not in db:
        db.add(preference)
    if old != new:
        audit.record(
            db,
            "reminders.change",
            actor=user,
            object_type="user",
            object_id=user.id,
            old={k: v for k, v in old.items() if new[k] != v} | {"section": section},
            new={k: v for k, v in new.items() if old[k] != v} | {"section": section},
        )
    db.commit()
    return preference


def _checked(form: FormData, name: str) -> bool:
    return form.get_str(name) in ("1", "on", "true")


def _choice(form: FormData, name: str, choices: dict[int, str]) -> int | None:
    raw = form.get_str(name)
    return int(raw) if raw.isdigit() and int(raw) in choices else None


def save_update(db: Session, user: User, form: FormData) -> ReminderPreference:
    errors: dict[str, str] = {}
    enabled = _checked(form, "update_enabled")

    frequency = form.get_str("frequency")
    if frequency not in FREQUENCIES:
        errors["frequency"] = "Kies hoe vaak je de update wilt."
        day_string = ALL_DAYS
    elif frequency == "eigen":
        picked = {d for d in form.get_all("day") if d in ALL_DAYS and len(d) == 1}
        day_string = "".join(sorted(picked))
        if not day_string:
            errors["frequency"] = "Kies minstens één dag."
    else:
        day_string = FREQUENCIES[frequency][1] or ALL_DAYS

    parsed: list[time] = []
    for raw in form.get_all("time"):
        if not raw:
            continue
        try:
            parsed.append(parse_time(raw))
        except ValueError:
            errors["time"] = f"'{raw}' is geen geldige tijd (uu:mm)."
            break
    parsed = sorted(set(parsed))
    if not errors.get("time"):
        if not parsed:
            errors["time"] = "Vul minstens één tijdstip in."
        elif len(parsed) > MAX_TIMES:
            errors["time"] = f"Maximaal {MAX_TIMES} tijdstippen per dag."

    lookahead = _choice(form, "lookahead_days", LOOKAHEAD_CHOICES)
    if lookahead is None:
        errors["lookahead_days"] = "Kies hoe ver de update vooruitkijkt."

    if errors:
        raise ReminderFormError(errors)
    return _save(
        db,
        user,
        "update",
        {
            "update_enabled": enabled,
            "update_days": day_string,
            "update_times": ",".join(format_time(t) for t in parsed),
            "lookahead_days": lookahead,
            "only_mine": form.get_str("scope") == "mine",
        },
    )


def save_tasks(db: Session, user: User, form: FormData) -> ReminderPreference:
    days_before = _choice(form, "task_days_before", DAYS_BEFORE_CHOICES)
    if days_before is None:
        raise ReminderFormError({"task_days_before": "Kies hoeveel dagen vooraf."})
    return _save(
        db,
        user,
        "tasks",
        {
            "task_on_day": _checked(form, "task_on_day"),
            "task_days_before": days_before,
            "task_late_daily": _checked(form, "task_late_daily"),
        },
    )


def save_categories(db: Session, user: User, form: FormData) -> None:
    all_ids = set(db.scalars(select(Category.id)))
    enabled = {int(v) for v in form.get_all("category") if v.isdigit()}
    muted = all_ids - enabled
    old = muted_category_ids(db, user)
    if muted == old:
        return
    db.execute(
        delete(ReminderMutedCategory).where(ReminderMutedCategory.user_id == user.id)
    )
    db.add_all(
        ReminderMutedCategory(user_id=user.id, category_id=cid) for cid in sorted(muted)
    )
    audit.record(
        db,
        "reminders.change",
        actor=user,
        object_type="user",
        object_id=user.id,
        old={"muted_categories": sorted(old), "section": "categories"},
        new={"muted_categories": sorted(muted), "section": "categories"},
    )
    db.commit()
