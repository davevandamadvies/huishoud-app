"""HTML-pagina's (server-side gerenderd, mobile-first)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.dates import today
from app.templating import templates

router = APIRouter(default_response_class=HTMLResponse, include_in_schema=False)


@router.get("/")
def today_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "pages/today.html",
        {
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
router.add_api_route("/meer", _placeholder("more", "Instellingen"), methods=["GET"])
