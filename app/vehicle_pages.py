"""Schermen voor voertuigen en kilometerstanden."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import vehicles
from app.auth import CurrentUser, current_user
from app.dates import today
from app.db import get_db
from app.forms import Form
from app.models import User, Vehicle
from app.templating import templates

router = APIRouter(
    prefix="/voertuigen",
    default_response_class=HTMLResponse,
    include_in_schema=False,
    dependencies=[Depends(current_user)],
)

DB = Annotated[Session, Depends(get_db)]


@router.get("")
def list_page(request: Request, user: CurrentUser, db: DB) -> HTMLResponse:
    return _render(request, db, user, "pages/vehicles.html")


def _cards(db: Session) -> list[dict]:
    return [
        {
            "vehicle": v,
            "latest": vehicles.latest(db, v),
            "per_day": vehicles.km_per_day(db, v),
        }
        for v in vehicles.list_vehicles(db)
    ]


def _render(
    request: Request, db: Session, user: User, template: str, **context: object
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        template,
        {
            "user": user,
            "page_title": "Voertuigen",
            "active_nav": "more",
            "cards": _cards(db),
            "archived": vehicles.list_vehicles(db, archived=True),
            "today": today(),
            "format_km": vehicles.format_km,
            **context,
        },
    )


def _panel(
    request: Request, db: Session, user: User, **context: object
) -> HTMLResponse:
    return _render(request, db, user, "partials/vehicles_panel.html", **context)


def _get(db: Session, vehicle_id: int) -> Vehicle:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=404)
    return vehicle


@router.post("")
def create(request: Request, user: CurrentUser, db: DB, form: Form) -> HTMLResponse:
    try:
        vehicle = vehicles.create(db, user, form.get_str("name"))
    except vehicles.VehicleError as exc:
        db.rollback()
        return _panel(request, db, user, error=str(exc), name=form.get_str("name"))
    return _panel(request, db, user, message=f"{vehicle.name} toegevoegd.")


@router.post("/{vehicle_id}/stand")
def add_reading(
    request: Request, user: CurrentUser, db: DB, form: Form, vehicle_id: int
) -> HTMLResponse:
    vehicle = _get(db, vehicle_id)
    try:
        km = vehicles.parse_km(form.get_str("km"))
        try:
            read_on = date.fromisoformat(form.get_str("read_on"))
        except ValueError:
            read_on = today()
        vehicles.add_reading(db, user, vehicle, km, read_on)
    except vehicles.VehicleError as exc:
        db.rollback()
        return _panel(request, db, user, error=str(exc), error_vehicle=vehicle.id)
    return _panel(request, db, user, message=f"Stand van {vehicle.name} opgeslagen.")


@router.get("/{vehicle_id}")
def detail(
    request: Request, user: CurrentUser, db: DB, vehicle_id: int
) -> HTMLResponse:
    vehicle = _get(db, vehicle_id)
    return _render(
        request,
        db,
        user,
        "pages/vehicle_detail.html",
        vehicle=vehicle,
        readings=vehicles.readings(db, vehicle, limit=20),
        page_title=vehicle.name,
    )


@router.post("/{vehicle_id}")
def rename(
    request: Request, user: CurrentUser, db: DB, form: Form, vehicle_id: int
) -> HTMLResponse:
    vehicle = _get(db, vehicle_id)
    try:
        vehicles.rename(db, user, vehicle, form.get_str("name"))
    except vehicles.VehicleError as exc:
        db.rollback()
        db.refresh(vehicle)
        return _detail_form(request, db, user, vehicle, error=str(exc))
    return _detail_form(request, db, user, vehicle, message="Opgeslagen.")


@router.post("/{vehicle_id}/archiveren")
def archive(
    request: Request, user: CurrentUser, db: DB, vehicle_id: int
) -> HTMLResponse:
    vehicle = _get(db, vehicle_id)
    vehicles.set_archived(db, user, vehicle, not vehicle.is_archived)
    message = "Gearchiveerd." if vehicle.is_archived else "Teruggezet."
    return _detail_form(request, db, user, vehicle, message=message)


def _detail_form(
    request: Request, db: Session, user: User, vehicle: Vehicle, **context: object
) -> HTMLResponse:
    return _render(
        request,
        db,
        user,
        "partials/vehicle_form.html",
        vehicle=vehicle,
        **context,
    )
