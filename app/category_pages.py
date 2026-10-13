"""Schermen voor categoriebeheer (alle gebruikers)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app import categories
from app.auth import CurrentUser, current_user
from app.db import get_db
from app.forms import Form
from app.models import Category, User
from app.palette import CATEGORY_COLORS, CATEGORY_ICONS, DEFAULT_COLOR, DEFAULT_ICON
from app.templating import templates

router = APIRouter(
    prefix="/categorieen",
    default_response_class=HTMLResponse,
    include_in_schema=False,
    dependencies=[Depends(current_user)],
)

DB = Annotated[Session, Depends(get_db)]


def _render(
    request: Request, template: str, user: User, **context: object
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        template,
        {
            "user": user,
            "active_nav": "more",
            "page_title": "Categorieën",
            "colors": CATEGORY_COLORS,
            "icons": CATEGORY_ICONS,
            **context,
        },
    )


def _panel(
    request: Request, user: User, db: Session, **context: object
) -> HTMLResponse:
    context.setdefault("form", {"color": DEFAULT_COLOR, "icon": DEFAULT_ICON})
    return _render(
        request,
        "partials/categories_panel.html",
        user,
        categories=categories.list_categories(db),
        **context,
    )


def _get(db: Session, category_id: int) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404)
    return category


@router.get("")
def list_page(request: Request, user: CurrentUser, db: DB) -> HTMLResponse:
    return _render(
        request,
        "pages/categories.html",
        user,
        categories=categories.list_categories(db),
        form={"color": DEFAULT_COLOR, "icon": DEFAULT_ICON},
    )


@router.post("")
def create(request: Request, user: CurrentUser, db: DB, form: Form) -> HTMLResponse:
    values = {
        "name": form.get_str("name"),
        "color": form.get_str("color"),
        "icon": form.get_str("icon") or DEFAULT_ICON,
    }
    try:
        category = categories.create(db, user, **values)
    except categories.CategoryError as exc:
        db.rollback()
        return _panel(request, user, db, form=values, error=str(exc))
    return _panel(request, user, db, message=f"{category.name} toegevoegd.")


@router.get("/{category_id}")
def edit_page(
    request: Request, category_id: int, user: CurrentUser, db: DB
) -> HTMLResponse:
    category = _get(db, category_id)
    return _render(
        request,
        "pages/category_edit.html",
        user,
        category=category,
        form={"name": category.name, "color": category.color, "icon": category.icon},
        page_title=category.name,
    )


@router.post("/{category_id}")
def update(
    request: Request, category_id: int, user: CurrentUser, db: DB, form: Form
) -> Response:
    category = _get(db, category_id)
    values = {
        "name": form.get_str("name"),
        "color": form.get_str("color"),
        "icon": form.get_str("icon") or DEFAULT_ICON,
    }
    try:
        categories.update(db, user, category, **values)
    except categories.CategoryError as exc:
        db.rollback()
        return _render(
            request,
            "partials/category_form.html",
            user,
            category=category,
            form=values,
            error=str(exc),
        )
    return Response(status_code=204, headers={"HX-Redirect": "/categorieen"})


@router.post("/{category_id}/verwijderen")
def delete(request: Request, category_id: int, user: CurrentUser, db: DB) -> Response:
    category = _get(db, category_id)
    try:
        categories.delete(db, user, category)
    except categories.CategoryError as exc:
        db.rollback()
        return _render(
            request,
            "partials/category_form.html",
            user,
            category=category,
            form={
                "name": category.name,
                "color": category.color,
                "icon": category.icon,
            },
            error=str(exc),
        )
    return Response(status_code=204, headers={"HX-Redirect": "/categorieen"})
