from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import completion, vehicles
from app.dates import today
from app.models import AuditLog, Category, OdometerReading, Task, User, Vehicle
from app.seed import seed_tasks
from tests.conftest import HTMX_HEADERS
from tests.factories import make_category, make_task


@pytest.fixture
def car(db: Session, user: User) -> Vehicle:
    return vehicles.create(db, user, "Auto")


def test_format_and_parse_km() -> None:
    assert vehicles.format_km(45210) == "45.210 km"
    assert vehicles.parse_km("45.210") == 45210
    assert vehicles.parse_km(" 45 210 km") == 45210
    with pytest.raises(vehicles.VehicleError):
        vehicles.parse_km("veel")
    with pytest.raises(vehicles.VehicleError):
        vehicles.parse_km("3000000")


def test_create_validates_name(db: Session, user: User, car: Vehicle) -> None:
    with pytest.raises(vehicles.VehicleError):
        vehicles.create(db, user, "auto")
    with pytest.raises(vehicles.VehicleError):
        vehicles.create(db, user, "  ")
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "vehicle.create"))
    assert entry.new_value == {"name": "Auto"}


def test_reading_validation(db: Session, user: User, car: Vehicle) -> None:
    day = today()
    vehicles.add_reading(db, user, car, 45000, day - timedelta(days=20))
    vehicles.add_reading(db, user, car, 46000, day - timedelta(days=5))
    with pytest.raises(vehicles.VehicleError, match="Lager dan een eerdere"):
        vehicles.add_reading(db, user, car, 44000, day)
    with pytest.raises(vehicles.VehicleError, match="Hoger dan een latere"):
        vehicles.add_reading(db, user, car, 47000, day - timedelta(days=10))
    with pytest.raises(vehicles.VehicleError, match="toekomst"):
        vehicles.add_reading(db, user, car, 47000, day + timedelta(days=1))
    # Tussenstand op de juiste plek mag wel
    vehicles.add_reading(db, user, car, 45500, day - timedelta(days=10))
    assert vehicles.latest(db, car).km == 46000


def test_km_per_day(db: Session, user: User, car: Vehicle) -> None:
    day = today()
    assert vehicles.km_per_day(db, car) is None
    vehicles.add_reading(db, user, car, 10000, day - timedelta(days=100))
    assert vehicles.km_per_day(db, car) is None  # één stand
    vehicles.add_reading(db, user, car, 14000, day)
    assert vehicles.km_per_day(db, car) == pytest.approx(40.0)


def test_km_per_day_needs_two_weeks(db: Session, user: User, car: Vehicle) -> None:
    vehicles.add_reading(db, user, car, 10000, today() - timedelta(days=10))
    vehicles.add_reading(db, user, car, 10500, today())
    assert vehicles.km_per_day(db, car) is None


def test_km_per_day_uses_last_year(db: Session, user: User, car: Vehicle) -> None:
    day = today()
    vehicles.add_reading(db, user, car, 0, day - timedelta(days=800))
    vehicles.add_reading(db, user, car, 50000, day - timedelta(days=100))
    vehicles.add_reading(db, user, car, 52000, day)
    assert vehicles.km_per_day(db, car) == pytest.approx(20.0)


def test_needing_update(db: Session, user: User, car: Vehicle) -> None:
    assert vehicles.needing_update(db) == []  # geen taken
    make_task(db, name="Olie", vehicle_id=car.id)
    assert [r.vehicle for r in vehicles.needing_update(db)] == [car]
    vehicles.add_reading(db, user, car, 1000, today() - timedelta(days=31))
    assert len(vehicles.needing_update(db)) == 1
    vehicles.add_reading(db, user, car, 1500, today() - timedelta(days=2))
    assert vehicles.needing_update(db) == []


def test_complete_with_km(db: Session, user: User, car: Vehicle) -> None:
    task = make_task(db, name="Olie", vehicle_id=car.id, due=today())
    result = completion.complete(db, user, task, performer_ids=[user.id], km=46000)
    assert result.occurrence.km == 46000
    assert vehicles.latest(db, car).km == 46000


def test_complete_with_lower_km_fails(db: Session, user: User, car: Vehicle) -> None:
    vehicles.add_reading(db, user, car, 50000, today() - timedelta(days=3))
    task = make_task(db, name="Olie", vehicle_id=car.id, due=today())
    with pytest.raises(completion.CompletionError, match="Lager"):
        completion.complete(db, user, task, performer_ids=[user.id], km=40000)


def test_same_reading_is_not_stored_twice(
    db: Session, user: User, car: Vehicle
) -> None:
    vehicles.add_reading(db, user, car, 46000, today())
    task = make_task(db, name="Olie", vehicle_id=car.id, due=today())
    completion.complete(db, user, task, performer_ids=[user.id], km=46000)
    assert len(vehicles.readings(db, car)) == 1


def test_km_ignored_for_tasks_without_vehicle(db: Session, user: User) -> None:
    task = make_task(db, due=today())
    result = completion.complete(db, user, task, performer_ids=[user.id], km=1)
    assert result.occurrence.km is None


# ---- Schermen ----


def test_vehicles_page_and_add_reading(
    client: TestClient, db: Session, car: Vehicle
) -> None:
    assert "Nog geen kilometerstand" in client.get("/voertuigen").text
    response = client.post(
        f"/voertuigen/{car.id}/stand",
        data={"km": "45.210", "read_on": today().isoformat()},
        headers=HTMX_HEADERS,
    )
    assert "Stand van Auto opgeslagen." in response.text
    assert "45.210 km" in response.text


def test_add_reading_error_is_shown(
    client: TestClient, db: Session, user: User, car: Vehicle
) -> None:
    vehicles.add_reading(db, user, car, 50000, today())
    response = client.post(
        f"/voertuigen/{car.id}/stand",
        data={"km": "40000", "read_on": today().isoformat()},
        headers=HTMX_HEADERS,
    )
    assert "Lager dan een eerdere stand (50.000 km)" in response.text


def test_create_vehicle_via_page(client: TestClient, db: Session) -> None:
    response = client.post("/voertuigen", data={"name": "Bus"}, headers=HTMX_HEADERS)
    assert "Bus toegevoegd." in response.text
    assert db.scalar(select(Vehicle.name)) == "Bus"


def test_detail_rename_and_archive(
    client: TestClient, db: Session, car: Vehicle
) -> None:
    assert client.get(f"/voertuigen/{car.id}").status_code == 200
    client.post(f"/voertuigen/{car.id}", data={"name": "Golf"}, headers=HTMX_HEADERS)
    response = client.post(f"/voertuigen/{car.id}/archiveren", headers=HTMX_HEADERS)
    assert "Gearchiveerd." in response.text
    db.expire_all()
    assert car.name == "Golf" and car.is_archived
    assert client.get("/voertuigen/999").status_code == 404


def test_complete_sheet_asks_km(
    client: TestClient, db: Session, user: User, car: Vehicle
) -> None:
    vehicles.add_reading(db, user, car, 45000, today())
    task = make_task(db, name="Olie", vehicle_id=car.id, due=today())
    html = client.get(f"/taken/{task.id}/afronden").text
    assert 'name="km"' in html
    assert "Laatst bekend: 45.000 km" in html
    other = make_task(db, name="Ramen", due=today())
    assert 'name="km"' not in client.get(f"/taken/{other.id}/afronden").text


def test_complete_via_sheet_with_km(
    client: TestClient, db: Session, user: User, car: Vehicle
) -> None:
    task = make_task(db, name="Olie", vehicle_id=car.id, due=today())
    response = client.post(
        f"/taken/{task.id}/afronden",
        data={
            "performer": [str(user.id)],
            "completed_on": today().isoformat(),
            "km": "abc",
        },
        headers=HTMX_HEADERS,
    )
    assert "heel getal" in response.text
    response = client.post(
        f"/taken/{task.id}/afronden",
        data={
            "performer": [str(user.id)],
            "completed_on": today().isoformat(),
            "km": "46.100",
        },
        headers=HTMX_HEADERS,
    )
    assert response.status_code == 200
    assert vehicles.latest(db, car).km == 46100


def test_today_shows_update_card(client: TestClient, db: Session, car: Vehicle) -> None:
    make_task(db, name="Olie", vehicle_id=car.id)
    assert "Kilometerstand Auto bijwerken" in client.get("/").text


def test_task_form_vehicle_select(
    client: TestClient, db: Session, car: Vehicle
) -> None:
    category = make_category(db)
    assert 'name="vehicle_id"' in client.get("/taken/nieuw").text
    response = client.post(
        "/taken",
        data={
            "name": "Olie",
            "category_id": str(category.id),
            "recurrence_type": "interval",
            "interval_every": "12",
            "interval_unit": "months",
            "vehicle_id": str(car.id),
        },
        headers=HTMX_HEADERS,
    )
    assert response.status_code == 204
    assert db.scalar(select(Task.vehicle_id)) == car.id


def test_seed_links_auto_tasks(db: Session) -> None:
    from app.palette import DEFAULT_COLOR

    for position, name in enumerate(
        ["Schoonmaak", "Huis & installaties", "Auto", "Tuin", "Planten", "Techniek"]
    ):
        db.add(Category(name=name, color=DEFAULT_COLOR, position=position))
    db.commit()
    seed_tasks(db)
    car = db.scalar(select(Vehicle))
    assert car.name == "Auto"
    linked = set(db.scalars(select(Task.name).where(Task.vehicle_id == car.id)))
    assert "APK" in linked and "Gras maaien" not in linked
    assert db.scalar(select(OdometerReading)) is None
