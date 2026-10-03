"""Scherm Planning: weekstrip, dagoverzicht en "Plan een taak"."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import categories, planning, planning_view
from app.auth import CurrentUser, current_user
from app.dates import dutch_date, plan_label, short_weekday, today
from app.db import get_db
from app.models import User
from app.recurrence import describe
from app.templating import templates

router = APIRouter(
    prefix="/planning",
    default_response_class=HTMLResponse,
    include_in_schema=False,
    dependencies=[Depends(current_user)],
)

DB = Annotated[Session, Depends(get_db)]

_MONTHS = (
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
)


def _day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return today()


def _context(db: Session, user: User, day: date) -> dict:
    return {
        "user": user,
        "page_title": "Planning",
        "active_nav": "planning",
        "today": today(),
        "view": planning_view.build(db, day),
        "month_label": f"{_MONTHS[day.month - 1]} {day.year}",
        "dutch_date": dutch_date,
        "short_weekday": short_weekday,
        "plan_label": plan_label,
        "responsible": planning.responsible,
    }


@router.get("")
def planning_page(
    request: Request, user: CurrentUser, db: DB, dag: str = ""
) -> HTMLResponse:
    context = _context(db, user, _day(dag))
    return templates.TemplateResponse(request, "pages/planning.html", context)


@router.get("/inhoud")
def planning_content(
    request: Request, user: CurrentUser, db: DB, dag: str = ""
) -> HTMLResponse:
    context = _context(db, user, _day(dag))
    return templates.TemplateResponse(
        request, "partials/planning_content.html", context
    )


def _picker_context(
    db: Session, user: User, datum: str, q: str, categorie: int | None
) -> dict:
    return {
        "user": user,
        "day": _day(datum),
        "q": q,
        "selected_category": categorie,
        "categories": categories.list_categories(db),
        "tasks": planning_view.plannable_tasks(db, search=q, category_id=categorie),
        "describe": describe,
        "dutch_date": dutch_date,
    }


@router.get("/kies")
def pick_task(
    request: Request, user: CurrentUser, db: DB, datum: str = ""
) -> HTMLResponse:
    context = _picker_context(db, user, datum, "", None)
    return templates.TemplateResponse(request, "partials/pick_task_sheet.html", context)


@router.get("/kies/lijst")
def pick_task_list(
    request: Request,
    user: CurrentUser,
    db: DB,
    datum: str = "",
    q: str = "",
    categorie: str = "",
) -> HTMLResponse:
    category_id = int(categorie) if categorie.isdigit() else None
    context = _picker_context(db, user, datum, q.strip(), category_id)
    return templates.TemplateResponse(request, "partials/pick_task_list.html", context)
