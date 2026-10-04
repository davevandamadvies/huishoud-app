"""Taken: invoer controleren, aanmaken, wijzigen, archiveren, verwijderen."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app import audit, categories, vehicles
from app.db import utcnow
from app.forms import FormData
from app.models import Category, Occurrence, OccurrenceStatus, Task, User, Vehicle
from app.recurrence import (
    DEFAULT_WINTER,
    IntervalUnit,
    RecurrenceType,
    format_months,
    into_season,
)

PENDING = (OccurrenceStatus.OPEN, OccurrenceStatus.PLANNED)
FINISHED = (OccurrenceStatus.DONE, OccurrenceStatus.SKIPPED)


class TaskFormError(Exception):
    """Ongeldige invoer; `errors` koppelt veldnamen aan meldingen."""

    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(errors.values()))
        self.errors = errors


class TaskError(Exception):
    """Actie niet toegestaan; de tekst is geschikt voor de gebruiker."""


@dataclass
class TaskInput:
    name: str
    category_id: int
    recurrence_type: RecurrenceType
    interval_every: int | None
    interval_unit: IntervalUnit
    owner_id: int | None
    default_points: int | None
    notes: str | None
    next_date: date | None
    first_reminder_days: int | None = None
    vehicle_id: int | None = None
    km_interval: int | None = None
    season_months: str | None = None
    winter_every: int | None = None
    winter_months: str | None = None

    def audit_dict(self) -> dict:
        return {
            "name": self.name,
            "category_id": self.category_id,
            "recurrence_type": self.recurrence_type.value,
            "interval_every": self.interval_every,
            "interval_unit": self.interval_unit.value,
            "owner_id": self.owner_id,
            "default_points": self.default_points,
            "notes": self.notes,
            "first_reminder_days": self.first_reminder_days,
            "vehicle_id": self.vehicle_id,
            "km_interval": self.km_interval,
            "season_months": self.season_months,
            "winter_every": self.winter_every,
            "winter_months": self.winter_months,
        }


@dataclass
class TaskRow:
    task: Task
    pending: Occurrence | None

    @property
    def next_date(self) -> date | None:
        return self.pending.effective_date if self.pending else None


def _int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def parse_form(db: Session, form: FormData) -> TaskInput:
    errors: dict[str, str] = {}

    name = " ".join(form.get_str("name").split())
    if not name:
        errors["name"] = "Vul een naam in."
    elif len(name) > 100:
        errors["name"] = "De naam mag maximaal 100 tekens zijn."

    category_id = _int(form.get_str("category_id"))
    if category_id is None or db.get(Category, category_id) is None:
        errors["category_id"] = "Kies een categorie."

    try:
        recurrence = RecurrenceType(form.get_str("recurrence_type"))
    except ValueError:
        recurrence = RecurrenceType.INTERVAL
        errors["recurrence_type"] = "Kies hoe vaak de taak terugkomt."

    try:
        unit = IntervalUnit(form.get_str("interval_unit", "days"))
    except ValueError:
        unit = IntervalUnit.DAYS
        errors["interval_every"] = "Kies dagen, weken of maanden."

    every: int | None = None
    if recurrence != RecurrenceType.ONCE:
        every = _int(form.get_str("interval_every"))
        if every is None or not 1 <= every <= 3650:
            errors["interval_every"] = "Vul een interval in (een heel getal vanaf 1)."

    owner_id: int | None = None
    raw_owner = form.get_str("owner_id")
    if raw_owner:
        owner_id = _int(raw_owner)
        owner = db.get(User, owner_id) if owner_id is not None else None
        if owner is None or not owner.is_active:
            errors["owner_id"] = "Kies een actieve gebruiker of niemand."

    points: int | None = None
    raw_points = form.get_str("default_points")
    if raw_points:
        points = _int(raw_points)
        if points is None or not 1 <= points <= 100:
            errors["default_points"] = "Punten: een heel getal van 1 tot 100, of leeg."

    first_reminder: int | None = None
    raw_first = form.get_str("first_reminder_days")
    if recurrence == RecurrenceType.FIXED_DATE and raw_first:
        first_reminder = _int(raw_first)
        if first_reminder is None or not 1 <= first_reminder <= 365:
            errors["first_reminder_days"] = (
                "Eerste herinnering: een heel getal van 1 tot 365 dagen, of leeg."
            )

    vehicle_id: int | None = None
    raw_vehicle = form.get_str("vehicle_id")
    if raw_vehicle:
        vehicle_id = _int(raw_vehicle)
        vehicle = db.get(Vehicle, vehicle_id) if vehicle_id is not None else None
        if vehicle is None:
            errors["vehicle_id"] = "Kies een voertuig of geen."

    km_interval: int | None = None
    raw_km = form.get_str("km_interval").replace(".", "").replace(" ", "")
    if raw_km and vehicle_id is not None and recurrence == RecurrenceType.INTERVAL:
        km_interval = _int(raw_km)
        if km_interval is None or not 100 <= km_interval <= 500_000:
            errors["km_interval"] = "Kilometers: een heel getal van 100 tot 500.000."

    season = {
        int(m) for m in form.get_all("season") if m.isdigit() and 1 <= int(m) <= 12
    }
    season_months = format_months(season)

    winter_every: int | None = None
    winter_months: str | None = None
    raw_winter = form.get_str("winter_every")
    if raw_winter and recurrence == RecurrenceType.INTERVAL:
        winter_every = _int(raw_winter)
        if winter_every is None or not 1 <= winter_every <= 3650:
            errors["winter_every"] = "Winter: een heel getal vanaf 1, of leeg."
        months = {
            int(m)
            for m in form.get_all("winter_month")
            if m.isdigit() and 1 <= int(m) <= 12
        }
        if not months:
            errors["winter_every"] = "Kies minstens één wintermaand."
        elif len(months) == 12:
            errors["winter_every"] = "De winter kan niet het hele jaar zijn."
        elif months != set(DEFAULT_WINTER):
            winter_months = format_months(months)

    notes = form.get_str("notes") or None
    if notes and len(notes) > 2000:
        errors["notes"] = "Notities mogen maximaal 2000 tekens zijn."

    next_date: date | None = None
    raw_date = form.get_str("next_date")
    if raw_date:
        try:
            next_date = date.fromisoformat(raw_date)
        except ValueError:
            errors["next_date"] = "Vul een geldige datum in."

    if errors:
        raise TaskFormError(errors)
    return TaskInput(
        name=name,
        category_id=category_id or 0,
        recurrence_type=recurrence,
        interval_every=every,
        interval_unit=unit,
        owner_id=owner_id,
        default_points=points,
        notes=notes,
        next_date=next_date,
        first_reminder_days=first_reminder,
        vehicle_id=vehicle_id,
        km_interval=km_interval,
        season_months=season_months,
        winter_every=winter_every,
        winter_months=winter_months,
    )


def pending_occurrence(db: Session, task: Task) -> Occurrence | None:
    return db.scalar(
        select(Occurrence).where(
            Occurrence.task_id == task.id, Occurrence.status.in_(PENDING)
        )
    )


def list_tasks(
    db: Session,
    *,
    search: str = "",
    category_id: int | None = None,
    archived: bool = False,
) -> list[TaskRow]:
    query = (
        select(Task, Occurrence)
        .outerjoin(
            Occurrence,
            (Occurrence.task_id == Task.id) & Occurrence.status.in_(PENDING),
        )
        .options(joinedload(Task.category), joinedload(Task.owner))
        .where(
            Task.archived_at.is_not(None) if archived else Task.archived_at.is_(None)
        )
    )
    if search:
        pattern = f"%{search.lower()}%"
        query = query.where(
            or_(
                func.lower(Task.name).like(pattern),
                func.lower(Task.notes).like(pattern),
            )
        )
    if category_id is not None:
        query = query.where(Task.category_id == category_id)
    rows = [TaskRow(task, occ) for task, occ in db.execute(query).unique().all()]
    # Eerst taken met een datum (vroegste eerst), dan zonder datum op naam.
    rows.sort(
        key=lambda r: (
            r.next_date is None,
            r.next_date or date.max,
            r.task.name.lower(),
        )
    )
    return rows


def count_archived(db: Session) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(Task).where(Task.archived_at.is_not(None))
        )
        or 0
    )


def _apply(task: Task, data: TaskInput) -> None:
    task.name = data.name
    task.category_id = data.category_id
    task.recurrence_type = data.recurrence_type
    task.interval_every = data.interval_every
    task.interval_unit = data.interval_unit
    task.owner_id = data.owner_id
    task.default_points = data.default_points
    task.notes = data.notes
    task.first_reminder_days = data.first_reminder_days
    task.vehicle_id = data.vehicle_id
    task.km_interval = data.km_interval
    task.season_months = data.season_months
    task.winter_every = data.winter_every
    task.winter_months = data.winter_months


def _set_next_date(db: Session, task: Task, next_date: date | None) -> None:
    """Zet de vervaldatum van de openstaande uitvoering (of maak/verwijder die)."""
    pending = pending_occurrence(db, task)
    if pending is None:
        if next_date is not None:
            db.add(Occurrence(task_id=task.id, due_date=next_date))
    elif pending.status == OccurrenceStatus.OPEN:
        if next_date is None:
            db.delete(pending)
        else:
            pending.due_date = next_date
    else:  # gepland: de plandatum blijft leidend, alleen de vervaldatum wijzigt
        pending.due_date = next_date


def _shift_into_season(db: Session, task: Task) -> None:
    """Nieuw seizoen: een open uitvoering buiten het seizoen schuift mee."""
    pending = pending_occurrence(db, task)
    if pending is None or pending.status != OccurrenceStatus.OPEN:
        return
    if pending.due_date is not None:
        pending.due_date = into_season(pending.due_date, task.season)


def _time_due(occurrence: Occurrence | None) -> date | None:
    """Vervaldatum volgens de tijd (bij km-of-tijd zonder de km-schatting)."""
    if occurrence is None:
        return None
    return occurrence.time_due_date or occurrence.due_date


def _sync_km(
    db: Session, task: Task, next_date: date | None, old_interval: int | None = None
) -> None:
    """Km-of-tijd bijwerken na het opslaan van de taak."""
    db.flush()
    db.refresh(task, ["vehicle"])
    pending = pending_occurrence(db, task)
    if pending is None:
        return
    if pending.due_km is not None or task.km_interval:
        pending.time_due_date = next_date
        base = vehicles.last_done_km(db, task)
        if base is None and pending.due_km is not None and old_interval:
            base = pending.due_km - old_interval
        vehicles.start_km_count(db, task, pending, base)


def create(db: Session, actor: User, data: TaskInput) -> Task:
    task = Task()
    _apply(task, data)
    db.add(task)
    db.flush()
    _set_next_date(db, task, data.next_date)
    _sync_km(db, task, data.next_date)
    new = data.audit_dict() | {"next_date": _iso(data.next_date)}
    audit.record(
        db, "task.create", actor=actor, object_type="task", object_id=task.id, new=new
    )
    db.commit()
    return task


def update(db: Session, actor: User, task: Task, data: TaskInput) -> None:
    pending = pending_occurrence(db, task)
    old = _audit_snapshot(task, _time_due(pending))
    old_interval = task.km_interval
    old_season = task.season_months
    _apply(task, data)
    _set_next_date(db, task, data.next_date)
    _sync_km(db, task, data.next_date, old_interval)
    if task.season_months != old_season:
        _shift_into_season(db, task)
    new = data.audit_dict() | {"next_date": _iso(data.next_date)}
    if old != new:
        audit.record(
            db,
            "task.update",
            actor=actor,
            object_type="task",
            object_id=task.id,
            old={k: v for k, v in old.items() if new.get(k) != v},
            new={k: v for k, v in new.items() if old.get(k) != v},
        )
    db.commit()


def archive(db: Session, actor: User, task: Task) -> None:
    if task.is_archived:
        return
    task.archived_at = utcnow()
    # Een gearchiveerde taak staat nergens meer open.
    pending = pending_occurrence(db, task)
    if pending is not None:
        db.delete(pending)
    audit.record(db, "task.archive", actor=actor, object_type="task", object_id=task.id)
    db.commit()


def restore(db: Session, actor: User, task: Task) -> None:
    if not task.is_archived:
        return
    task.archived_at = None
    audit.record(db, "task.restore", actor=actor, object_type="task", object_id=task.id)
    db.commit()


def has_history(db: Session, task: Task) -> bool:
    return bool(
        db.scalar(
            select(Occurrence.id)
            .where(Occurrence.task_id == task.id, Occurrence.status.in_(FINISHED))
            .limit(1)
        )
    )


def delete(db: Session, actor: User, task: Task) -> None:
    if has_history(db, task):
        raise TaskError(
            "Deze taak heeft al een logboek. Archiveer hem in plaats daarvan."
        )
    audit.record(
        db,
        "task.delete",
        actor=actor,
        object_type="task",
        object_id=task.id,
        old=_audit_snapshot(task, None),
    )
    db.delete(task)
    db.commit()


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _audit_snapshot(task: Task, next_date: date | None) -> dict:
    return {
        "name": task.name,
        "category_id": task.category_id,
        "recurrence_type": task.recurrence_type.value,
        "interval_every": task.interval_every,
        "interval_unit": task.interval_unit.value,
        "owner_id": task.owner_id,
        "default_points": task.default_points,
        "notes": task.notes,
        "first_reminder_days": task.first_reminder_days,
        "vehicle_id": task.vehicle_id,
        "km_interval": task.km_interval,
        "season_months": task.season_months,
        "winter_every": task.winter_every,
        "winter_months": task.winter_months,
        "next_date": _iso(next_date),
    }


def _count_for_category(db: Session, category_id: int) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.category_id == category_id)
        )
        or 0
    )


categories.task_counter = _count_for_category
