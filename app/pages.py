"""HTML-pagina's (server-side gerenderd, mobile-first)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import categories, today_view
from app.auth import CurrentUser, current_user
from app.dates import due_label, today
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
        "due_label": due_label,
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


router.add_api_route("/planning", _placeholder("planning", "Planning"), methods=["GET"])
router.add_api_route("/scores", _placeholder("scores", "Scores"), methods=["GET"])


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
        },
    )
