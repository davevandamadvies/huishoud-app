from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import completion, tasks, vehicles
from app.dates import today
from app.models import Occurrence, OccurrenceStatus, Task, User, Vehicle
from app.recurrence import IntervalUnit
from tests.conftest import HTMX_HEADERS
from tests.factories import make_category, make_task


@pytest.fixture
def car(db: Session, user: User) -> Vehicle:
    return vehicles.create(db, user, "Auto")


def oil(db: Session, car: Vehicle, **kwargs) -> Task:
    options = {"every": 12, "interval_unit": IntervalUnit.MONTHS, "km_interval": 15000}
    return make_task(db, name="Olie verversen", vehicle_id=car.id, **(options | kwargs))


def pending(db: Session, task: Task) -> Occurrence:
    db.expire_all()
    return tasks.pending_occurrence(db, task)


def drive(db: Session, user: User, car: Vehicle, per_day: int, days: int = 100) -> None:
    """Standen die een vast gemiddelde per dag geven (eindigend vandaag)."""
    start = 40000
    vehicles.add_reading(db, user, car, start, today() - timedelta(days=days))
    vehicles.add_reading(db, user, car, start + per_day * days, today())


def test_estimate_date(db: Session, user: User, car: Vehicle) -> None:
    drive(db, user, car, per_day=50)  # nu op 45.000
    assert vehicles.estimate_date(db, car, 46000) == today() + timedelta(days=20)
    assert vehicles.estimate_date(db, car, 44000) == today()  # al voorbij


def test_no_estimate_without_enough_readings(
    db: Session, user: User, car: Vehicle
) -> None:
    assert vehicles.estimate_date(db, car, 50000) is None
    vehicles.add_reading(db, user, car, 40000, today())
    assert vehicles.estimate_date(db, car, 50000) is None


def test_km_first(db: Session, user: User, car: Vehicle) -> None:
    drive(db, user, car, per_day=200)  # 45.000 → +15.000 in 75 dagen
    task = oil(db, car, due=today())
    completion.complete(db, user, task, performer_ids=[user.id], km=60000)
    occ = pending(db, task)
    assert occ.due_km == 75000
    assert occ.time_due_date == date(today().year + 1, today().month, today().day)
    assert occ.due_date == today() + timedelta(days=75)


def test_time_first(db: Session, user: User, car: Vehicle) -> None:
    drive(db, user, car, per_day=10)  # 15.000 km duurt 1.500 dagen
    task = oil(db, car, due=today())
    completion.complete(db, user, task, performer_ids=[user.id])
    occ = pending(db, task)
    assert occ.due_km == 41000 + 15000  # laatst bekende stand (41.000)
    assert occ.due_date == occ.time_due_date


def test_without_any_reading_only_time_counts(
    db: Session, user: User, car: Vehicle
) -> None:
    task = oil(db, car, due=today())
    completion.complete(db, user, task, performer_ids=[user.id])
    occ = pending(db, task)
    assert occ.due_km is None
    assert occ.due_date is not None


def test_new_reading_moves_due_date(db: Session, user: User, car: Vehicle) -> None:
    drive(db, user, car, per_day=10)
    task = oil(db, car, due=today())
    completion.complete(db, user, task, performer_ids=[user.id], km=41000)
    time_due = pending(db, task).due_date
    # Veel gereden: grens (56.000) al bijna bereikt
    vehicles.add_reading(db, user, car, 55500, today())
    assert pending(db, task).due_date < time_due
    vehicles.add_reading(db, user, car, 56100, today())
    assert pending(db, task).due_date == today()
    assert vehicles.km_left_label(pending(db, task)) == "km-grens bereikt"


def test_km_left_label(db: Session, user: User, car: Vehicle) -> None:
    drive(db, user, car, per_day=10)
    task = oil(db, car, due=today())
    completion.complete(db, user, task, performer_ids=[user.id], km=41000)
    assert vehicles.km_left_label(pending(db, task)) == "nog ~15.000 km"


def test_recurrence_text(db: Session, car: Vehicle) -> None:
    assert oil(db, car).recurrence_text == "Jaarlijks of elke 15.000 km"


def test_removing_km_interval_restores_time(
    client: TestClient, db: Session, user: User, car: Vehicle
) -> None:
    drive(db, user, car, per_day=200)
    task = oil(db, car, due=today())
    completion.complete(db, user, task, performer_ids=[user.id], km=60000)
    time_due = pending(db, task).time_due_date
    response = client.post(
        f"/taken/{task.id}",
        data={
            "name": task.name,
            "category_id": str(task.category_id),
            "recurrence_type": "interval",
            "interval_every": "12",
            "interval_unit": "months",
            "vehicle_id": str(car.id),
            "km_interval": "",
            "next_date": time_due.isoformat(),
        },
        headers=HTMX_HEADERS,
    )
    assert response.status_code in (200, 204)
    occ = pending(db, task)
    assert occ.due_km is None
    assert occ.due_date == time_due


def test_changing_km_interval_keeps_base(
    client: TestClient, db: Session, user: User, car: Vehicle
) -> None:
    drive(db, user, car, per_day=10)
    task = oil(db, car, due=today())
    completion.complete(db, user, task, performer_ids=[user.id], km=41000)
    client.post(
        f"/taken/{task.id}",
        data={
            "name": task.name,
            "category_id": str(task.category_id),
            "recurrence_type": "interval",
            "interval_every": "12",
            "interval_unit": "months",
            "vehicle_id": str(car.id),
            "km_interval": "20.000",
            "next_date": pending(db, task).time_due_date.isoformat(),
        },
        headers=HTMX_HEADERS,
    )
    assert pending(db, task).due_km == 61000


def test_km_interval_validation(client: TestClient, db: Session, car: Vehicle) -> None:
    category = make_category(db)
    response = client.post(
        "/taken",
        data={
            "name": "Olie",
            "category_id": str(category.id),
            "recurrence_type": "interval",
            "interval_every": "12",
            "interval_unit": "months",
            "vehicle_id": str(car.id),
            "km_interval": "5",
        },
        headers=HTMX_HEADERS,
    )
    assert "Kilometers: een heel getal" in response.text


def test_km_interval_ignored_without_vehicle(client: TestClient, db: Session) -> None:
    category = make_category(db)
    client.post(
        "/taken",
        data={
            "name": "Ramen",
            "category_id": str(category.id),
            "recurrence_type": "interval",
            "interval_every": "7",
            "interval_unit": "days",
            "km_interval": "15000",
        },
        headers=HTMX_HEADERS,
    )
    assert db.scalar(select(Task.km_interval)) is None


def test_lists_show_km_left(
    client: TestClient, db: Session, user: User, car: Vehicle
) -> None:
    drive(db, user, car, per_day=10)
    task = oil(db, car, due=today())
    completion.complete(db, user, task, performer_ids=[user.id], km=41000)
    assert "nog ~15.000 km" in client.get("/taken").text
    assert "nog ~15.000 km" in client.get(f"/taken/{task.id}").text


def test_planned_occurrence_keeps_plan_date(
    db: Session, user: User, car: Vehicle
) -> None:
    drive(db, user, car, per_day=10)
    task = oil(db, car, due=today())
    completion.complete(db, user, task, performer_ids=[user.id], km=41000)
    occ = pending(db, task)
    occ.status = OccurrenceStatus.PLANNED
    occ.planned_date = today() + timedelta(days=3)
    db.commit()
    vehicles.add_reading(db, user, car, 56500, today())
    occ = pending(db, task)
    assert occ.planned_date == today() + timedelta(days=3)
    assert occ.due_date == today()
