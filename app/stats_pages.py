"""Scherm "Statistieken"."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import stats
from app.auth import CurrentUser, current_user
from app.dates import dutch_date, today
from app.db import get_db
from app.templating import templates

router = APIRouter(
    default_response_class=HTMLResponse,
    include_in_schema=False,
    dependencies=[Depends(current_user)],
)

DB = Annotated[Session, Depends(get_db)]


@router.get("/statistieken")
def page(
    request: Request, user: CurrentUser, db: DB, periode: str = "jaar"
) -> HTMLResponse:
    try:
        selected = stats.Range(periode)
    except ValueError:
        selected = stats.Range.YEAR
    return templates.TemplateResponse(
        request,
        "pages/stats.html",
        {
            "user": user,
            "page_title": "Statistieken",
            "active_nav": "scores",
            "ranges": stats.RANGE_LABELS,
            "selected": selected,
            "s": stats.build(db, selected, today()),
            "bars": stats.bars,
            "share": stats.share,
            "chart_height": stats.CHART_HEIGHT,
            "dutch_date": dutch_date,
        },
    )
