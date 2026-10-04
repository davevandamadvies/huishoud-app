"""HTML-pagina's (server-side gerenderd, mobile-first)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import (
    categories,
    planning,
    push,
    reminders,
    scores,
    settings_store,
    today_view,
    vehicles,
)
from app.auth import CurrentUser, current_user
from app.dates import due_label, plan_label, today, when_label
from app.db import get_db
from app.models import User
from app.templating import templates

DB = Annotated[Session, Depends(get_db)]

router = APIRouter(
    default_response_class=HTMLResponse,
    include_in_schema=False,
    dependencies=[Depends(current_user)],
)


def _today_context(db: Session, user: User) -> dict:
    day = today()
    return {
        "user": user,
        "page_title": "Vandaag",
        "active_nav": "today",
        "today": day,
        "view": today_view.build(db, day),
        "week_standings": scores.standings(db, *scores.bounds(scores.Period.WEEK, day))
        if settings_store.competition_enabled(db)
        else [],
        "due_label": due_label,
        "plan_label": plan_label,
        "responsible": planning.responsible,
        "vehicle_reminders": vehicles.needing_update(db, day),
        "format_km": vehicles.format_km,
    }


@router.get("/")
def today_page(request: Request, user: CurrentUser, db: DB) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "pages/today.html", _today_context(db, user)
    )


@router.get("/vandaag/lijsten")
def today_lists(request: Request, user: CurrentUser, db: DB) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "partials/today_lists.html", _today_context(db, user)
    )


def _placeholder(key: str, title: str):
    def page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "pages/placeholder.html",
            {"page_title": title, "active_nav": key},
        )

    return page


@router.get("/scores")
def scores_page(
    request: Request,
    user: CurrentUser,
    db: DB,
    periode: str = "week",
    categorie: str = "",
) -> HTMLResponse:
    try:
        period = scores.Period(periode)
    except ValueError:
        period = scores.Period.WEEK
    category_id = int(categorie) if categorie.isdigit() else None
    context = {
        "user": user,
        "page_title": "Scores",
        "active_nav": "scores",
        "periods": [
            (scores.Period.WEEK, "Week"),
            (scores.Period.MONTH, "Maand"),
            (scores.Period.TOTAL, "Totaal"),
        ],
        "period": period,
        "selected_category": category_id,
        "categories": categories.list_categories(db),
        "today": today(),
        "when_label": when_label,
    }
    if request.state.competition:
        context["board"] = scores.build(db, period, today(), category_id)
    return templates.TemplateResponse(request, "pages/scores.html", context)


@router.post("/instellingen/competitie")
def toggle_competition(request: Request, user: CurrentUser, db: DB) -> HTMLResponse:
    enabled = not settings_store.competition_enabled(db)
    settings_store.set_value(
        db, user, settings_store.COMPETITION, "true" if enabled else "false"
    )
    request.state.competition = enabled
    return templates.TemplateResponse(
        request, "partials/competition_switch.html", {"user": user}
    )


@router.get("/meer")
def more_page(request: Request, user: CurrentUser, db: DB) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "pages/more.html",
        {
            "user": user,
            "page_title": "Instellingen",
            "active_nav": "more",
            "category_count": len(categories.list_categories(db)),
            "reminders": reminders.summary(db, user),
            "device_count": len(push.subscriptions_for(db, user)),
            "vehicle_count": len(vehicles.list_vehicles(db)),
        },
    )
