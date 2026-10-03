"""Gebruikersbeheer (alleen beheerders)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import users
from app.auth import AdminUser, require_admin
from app.db import get_db
from app.forms import Form
from app.models import Role, User
from app.templating import templates

router = APIRouter(
    prefix="/beheer/gebruikers",
    default_response_class=HTMLResponse,
    include_in_schema=False,
    dependencies=[Depends(require_admin)],
)

DB = Annotated[Session, Depends(get_db)]
ROLE_LABELS = {Role.ADMIN: "Beheerder", Role.USER: "Gebruiker"}


def _render(
    request: Request, template: str, admin: User, **context: object
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        template,
        {
            "user": admin,
            "active_nav": "more",
            "page_title": "Gebruikers",
            "role_labels": ROLE_LABELS,
            **context,
        },
    )


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404)
    return user


@router.get("")
def list_page(request: Request, admin: AdminUser, db: DB) -> HTMLResponse:
    return _render(
        request, "pages/users.html", admin, users=users.list_users(db), form={}
    )


@router.post("")
def grant(request: Request, admin: AdminUser, db: DB, form: Form) -> HTMLResponse:
    values = {
        "oidc_sub": form.get_str("oidc_sub"),
        "display_name": form.get_str("display_name"),
        "role": form.get_str("role", Role.USER.value),
    }
    error = message = None
    try:
        new_user = users.grant_access(db, admin, **values)
        message = f"{new_user.display_name} heeft nu toegang."
        values = {}
    except users.UserAdminError as exc:
        db.rollback()
        error = str(exc)
    return _render(
        request,
        "partials/users_panel.html",
        admin,
        users=users.list_users(db),
        form=values,
        error=error,
        message=message,
    )


@router.get("/{user_id}")
def detail_page(
    request: Request, user_id: int, admin: AdminUser, db: DB
) -> HTMLResponse:
    target = _get_user(db, user_id)
    return _render(
        request,
        "pages/user_detail.html",
        admin,
        target=target,
        page_title=target.display_name,
    )


def _apply(
    request: Request, admin: User, db: Session, target: User, action, message: str
) -> HTMLResponse:
    error = None
    try:
        action()
    except users.UserAdminError as exc:
        db.rollback()
        db.refresh(target)
        error, message = str(exc), ""
    return _render(
        request,
        "partials/user_panel.html",
        admin,
        target=target,
        error=error,
        message=message or None,
    )


@router.post("/{user_id}/naam")
def rename(
    request: Request, user_id: int, admin: AdminUser, db: DB, form: Form
) -> HTMLResponse:
    target = _get_user(db, user_id)
    name = form.get_str("display_name")
    return _apply(
        request,
        admin,
        db,
        target,
        lambda: users.rename(db, admin, target, name),
        "Naam opgeslagen.",
    )


@router.post("/{user_id}/rol")
def change_role(
    request: Request, user_id: int, admin: AdminUser, db: DB, form: Form
) -> HTMLResponse:
    target = _get_user(db, user_id)
    role = form.get_str("role")
    return _apply(
        request,
        admin,
        db,
        target,
        lambda: users.change_role(db, admin, target, role),
        "Rol opgeslagen.",
    )


@router.post("/{user_id}/deactiveren")
def deactivate(
    request: Request, user_id: int, admin: AdminUser, db: DB
) -> HTMLResponse:
    target = _get_user(db, user_id)
    return _apply(
        request,
        admin,
        db,
        target,
        lambda: users.deactivate(db, admin, target),
        "Gedeactiveerd. Alle sessies zijn beëindigd.",
    )


@router.post("/{user_id}/activeren")
def activate(request: Request, user_id: int, admin: AdminUser, db: DB) -> HTMLResponse:
    target = _get_user(db, user_id)
    return _apply(
        request,
        admin,
        db,
        target,
        lambda: users.activate(db, admin, target),
        "Weer actief.",
    )
