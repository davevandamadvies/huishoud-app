"""HTML-pagina's (server-side gerenderd, mobile-first)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.auth import CurrentUser, current_user
from app.dates import today
from app.templating import templates

router = APIRouter(
    default_response_class=HTMLResponse,
    include_in_schema=False,
    dependencies=[Depends(current_user)],
)


@router.get("/")
def today_page(request: Request, user: CurrentUser) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "pages/today.html",
        {
            "user": user,
            "page_title": "Vandaag",
            "active_nav": "today",
            "today": today(),
            "week_done": 0,
            "week_total": 0,
        },
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
router.add_api_route("/taken", _placeholder("tasks", "Taken"), methods=["GET"])
router.add_api_route("/scores", _placeholder("scores", "Scores"), methods=["GET"])


@router.get("/meer")
def more_page(request: Request, user: CurrentUser) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "pages/more.html",
        {"user": user, "page_title": "Instellingen", "active_nav": "more"},
    )
