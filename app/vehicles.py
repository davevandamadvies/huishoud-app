"""Voertuigen en kilometerstanden (fase 5)."""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.dates import today
from app.db import utcnow
from app.models import OdometerReading, Task, User, Vehicle

MAX_KM = 2_000_000
STALE_AFTER_DAYS = 30
AVERAGE_WINDOW_DAYS = 365
MIN_SPAN_DAYS = 14


class VehicleError(Exception):
    """Ongeldige invoer; de tekst is geschikt voor de gebruiker."""


def format_km(km: int) -> str:
    """45210 → '45.210 km'."""
    return f"{km:,} km".replace(",", ".")


def parse_km(raw: str) -> int:
    """'45.210', '45210' of '45 210' → 45210."""
    cleaned = raw.strip().replace(".", "").replace(" ", "").replace("km", "")
    if not cleaned.isdigit():
        raise VehicleError("Vul de kilometerstand in als heel getal, bijv. 45210.")
    km = int(cleaned)
    if km > MAX_KM:
        raise VehicleError("Die kilometerstand is te hoog.")
    return km


def list_vehicles(db: Session, *, archived: bool = False) -> list[Vehicle]:
    condition = (
        Vehicle.archived_at.is_not(None) if archived else Vehicle.archived_at.is_(None)
    )
    return list(db.scalars(select(Vehicle).where(condition).order_by(Vehicle.name)))


def _clean_name(db: Session, name: str, vehicle: Vehicle | None = None) -> str:
    name = " ".join(name.split())
    if not name:
        raise VehicleError("Vul een naam in.")
    if len(name) > 50:
        raise VehicleError("De naam mag maximaal 50 tekens zijn.")
    clash = db.scalar(select(Vehicle).where(func.lower(Vehicle.name) == name.lower()))
    if clash is not None and clash is not vehicle:
        raise VehicleError("Er is al een voertuig met die naam.")
    return name


def create(db: Session, actor: User, name: str) -> Vehicle:
    vehicle = Vehicle(name=_clean_name(db, name))
    db.add(vehicle)
    db.flush()
    audit.record(
        db,
        "vehicle.create",
        actor=actor,
        object_type="vehicle",
        object_id=vehicle.id,
        new={"name": vehicle.name},
    )
    db.commit()
    return vehicle


def rename(db: Session, actor: User, vehicle: Vehicle, name: str) -> None:
    name = _clean_name(db, name, vehicle)
    if name == vehicle.name:
        return
    audit.record(
        db,
        "vehicle.update",
        actor=actor,
        object_type="vehicle",
        object_id=vehicle.id,
        old={"name": vehicle.name},
        new={"name": name},
    )
    vehicle.name = name
    db.commit()


def set_archived(db: Session, actor: User, vehicle: Vehicle, archived: bool) -> None:
    if vehicle.is_archived == archived:
        return
    vehicle.archived_at = utcnow() if archived else None
    action = "vehicle.archive" if archived else "vehicle.restore"
    audit.record(db, action, actor=actor, object_type="vehicle", object_id=vehicle.id)
    db.commit()


def readings(
    db: Session, vehicle: Vehicle, limit: int | None = None
) -> list[OdometerReading]:
    """Standen, nieuwste eerst."""
    query = (
        select(OdometerReading)
        .where(OdometerReading.vehicle_id == vehicle.id)
        .order_by(OdometerReading.read_on.desc(), OdometerReading.km.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    return list(db.scalars(query))


def latest(db: Session, vehicle: Vehicle) -> OdometerReading | None:
    found = readings(db, vehicle, limit=1)
    return found[0] if found else None


def add_reading(
    db: Session,
    actor: User,
    vehicle: Vehicle,
    km: int,
    read_on: date | None = None,
    *,
    commit: bool = True,
) -> OdometerReading:
    """Nieuwe stand; mag niet lager zijn dan een eerdere of hoger dan een latere."""
    read_on = read_on or today()
    if read_on > today():
        raise VehicleError("Een kilometerstand kan niet in de toekomst liggen.")
    if not 0 <= km <= MAX_KM:
        raise VehicleError("Die kilometerstand is niet geldig.")
    before = db.scalar(
        select(func.max(OdometerReading.km)).where(
            OdometerReading.vehicle_id == vehicle.id,
            OdometerReading.read_on <= read_on,
        )
    )
    if before is not None and km < before:
        raise VehicleError(
            f"Lager dan een eerdere stand ({format_km(before)}). Klopt het getal?"
        )
    after = db.scalar(
        select(func.min(OdometerReading.km)).where(
            OdometerReading.vehicle_id == vehicle.id,
            OdometerReading.read_on > read_on,
        )
    )
    if after is not None and km > after:
        raise VehicleError(
            f"Hoger dan een latere stand ({format_km(after)}). Klopt de datum?"
        )
    reading = OdometerReading(
        vehicle_id=vehicle.id, read_on=read_on, km=km, user_id=actor.id
    )
    db.add(reading)
    db.flush()
    audit.record(
        db,
        "vehicle.reading",
        actor=actor,
        object_type="vehicle",
        object_id=vehicle.id,
        new={"km": km, "read_on": read_on.isoformat()},
    )
    if commit:
        db.commit()
    return reading


def km_per_day(db: Session, vehicle: Vehicle, day: date | None = None) -> float | None:
    """Gemiddeld aantal km per dag over de laatste 12 maanden.

    Pas bruikbaar met minstens twee standen die 14 dagen uit elkaar liggen.
    """
    day = day or today()
    window = list(
        db.scalars(
            select(OdometerReading)
            .where(
                OdometerReading.vehicle_id == vehicle.id,
                OdometerReading.read_on >= day - timedelta(days=AVERAGE_WINDOW_DAYS),
                OdometerReading.read_on <= day,
            )
            .order_by(OdometerReading.read_on, OdometerReading.km)
        )
    )
    if len(window) < 2:
        return None
    first, last = window[0], window[-1]
    span = (last.read_on - first.read_on).days
    if span < MIN_SPAN_DAYS:
        return None
    return max(0.0, (last.km - first.km) / span)


@dataclass(frozen=True)
class Reminder:
    vehicle: Vehicle
    last: OdometerReading | None


def needing_update(db: Session, day: date | None = None) -> list[Reminder]:
    """Voertuigen met actieve taken waarvan de stand ouder is dan 30 dagen."""
    day = day or today()
    with_tasks = set(
        db.scalars(
            select(Task.vehicle_id).where(
                Task.vehicle_id.is_not(None), Task.archived_at.is_(None)
            )
        )
    )
    result = []
    for vehicle in list_vehicles(db):
        if vehicle.id not in with_tasks:
            continue
        last = latest(db, vehicle)
        if last is None or (day - last.read_on).days > STALE_AFTER_DAYS:
            result.append(Reminder(vehicle, last))
    return result
