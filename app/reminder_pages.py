"""Schermen onder Instellingen → "Mijn reminders"."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import categories, reminders
from app.auth import CurrentUser, current_user
from app.db import get_db
from app.forms import Form, FormData
from app.models import User
from app.templating import templates

router = APIRouter(
    prefix="/reminders",
    default_response_class=HTMLResponse,
    include_in_schema=False,
    dependencies=[Depends(current_user)],
)

DB = Annotated[Session, Depends(get_db)]

SECTIONS: dict[str, tuple[str, Callable[[Session, User, FormData], object]]] = {
    "update": ("Update", reminders.save_update),
    "taken": ("Losse meldingen", reminders.save_tasks),
    "categorieen": ("Categorieën", reminders.save_categories),
}


def _values(db: Session, user: User) -> dict:
    preference = reminders.get(db, user)
    times = preference.update_times.split(",")
    return {
        "update_enabled": preference.update_enabled,
        "frequency": reminders.frequency_key(preference.update_days),
        "days": set(preference.update_days),
        "times": times + [""] * (reminders.MAX_TIMES - len(times)),
        "lookahead_days": preference.lookahead_days,
        "scope": "mine" if preference.only_mine else "household",
        "task_on_day": preference.task_on_day,
        "task_days_before": preference.task_days_before,
        "task_late_daily": preference.task_late_daily,
        "muted": reminders.muted_category_ids(db, user),
    }


def _values_from_form(form: FormData) -> dict:
    """Ingevulde waarden terugzetten na een fout."""
    times = form.get_all("time")[: reminders.MAX_TIMES]

    def number(name: str) -> int | None:
        raw = form.get_str(name)
        return int(raw) if raw.isdigit() else None

    return {
        "update_enabled": "update_enabled" in form,
        "frequency": form.get_str("frequency"),
        "days": set(form.get_all("day")),
        "times": times + [""] * (reminders.MAX_TIMES - len(times)),
        "lookahead_days": number("lookahead_days"),
        "scope": form.get_str("scope"),
        "task_on_day": "task_on_day" in form,
        "task_days_before": number("task_days_before"),
        "task_late_daily": "task_late_daily" in form,
        "muted": set(),
    }


def _section(slug: str) -> str:
    if slug not in SECTIONS:
        raise HTTPException(status_code=404)
    return slug


def _render(
    request: Request,
    db: Session,
    user: User,
    slug: str,
    template: str,
    values: dict,
    **context: object,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        template,
        {
            "user": user,
            "page_title": SECTIONS[slug][0],
            "active_nav": "more",
            "slug": slug,
            "v": values,
            "errors": {},
            "frequencies": reminders.FREQUENCIES,
            "day_names": reminders.DAY_NAMES,
            "lookahead_choices": reminders.LOOKAHEAD_CHOICES,
            "days_before_choices": reminders.DAYS_BEFORE_CHOICES,
            "categories": categories.list_categories(db),
            **context,
        },
    )


@router.get("/{slug}")
def page(request: Request, user: CurrentUser, db: DB, slug: str) -> HTMLResponse:
    slug = _section(slug)
    return _render(
        request, db, user, slug, "pages/reminder_section.html", _values(db, user)
    )


@router.post("/{slug}")
def save(
    request: Request, user: CurrentUser, db: DB, form: Form, slug: str
) -> HTMLResponse:
    slug = _section(slug)
    try:
        SECTIONS[slug][1](db, user, form)
    except reminders.ReminderFormError as exc:
        db.rollback()
        values = _values_from_form(form)
        if slug == "categorieen":
            values["muted"] = reminders.muted_category_ids(db, user)
        return _render(
            request,
            db,
            user,
            slug,
            "partials/reminder_form.html",
            values,
            errors=exc.errors,
        )
    return _render(
        request,
        db,
        user,
        slug,
        "partials/reminder_form.html",
        _values(db, user),
        message="Opgeslagen.",
    )
