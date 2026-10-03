"""Scherm "Meldingen": push aanzetten per toestel, toestellen beheren, testen."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import push
from app.auth import CurrentUser, current_user
from app.db import get_db
from app.forms import Form
from app.models import PushSubscription, User
from app.settings import get_settings
from app.templating import templates

router = APIRouter(
    prefix="/meldingen",
    default_response_class=HTMLResponse,
    include_in_schema=False,
    dependencies=[Depends(current_user)],
)

DB = Annotated[Session, Depends(get_db)]


def device_label(user_agent: str) -> str:
    """Leesbare naam voor een toestel, zoals "Chrome op Android"."""
    ua = user_agent.lower()
    if "samsungbrowser" in ua:
        browser = "Samsung Internet"
    elif "edg/" in ua or "edga/" in ua:
        browser = "Edge"
    elif "firefox" in ua or "fxios" in ua:
        browser = "Firefox"
    elif "chrome" in ua or "crios" in ua:
        browser = "Chrome"
    elif "safari" in ua:
        browser = "Safari"
    else:
        browser = "Browser"
    for needle, system in (
        ("android", "Android"),
        ("iphone", "iPhone"),
        ("ipad", "iPad"),
        ("windows", "Windows"),
        ("mac os", "Mac"),
        ("linux", "Linux"),
    ):
        if needle in ua:
            return f"{browser} op {system}"
    return browser


def _panel(
    request: Request, user: User, db: Session, *, template: str, **context: object
) -> HTMLResponse:
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        template,
        {
            "user": user,
            "page_title": "Meldingen",
            "active_nav": "more",
            "push_enabled": settings.push_enabled,
            "vapid_public_key": settings.vapid_public_key,
            "devices": push.subscriptions_for(db, user),
            **context,
        },
    )


@router.get("")
def page(request: Request, user: CurrentUser, db: DB) -> HTMLResponse:
    return _panel(request, user, db, template="pages/notifications.html")


def _panel_partial(
    request: Request, user: User, db: Session, **context: object
) -> HTMLResponse:
    return _panel(request, user, db, template="partials/push_panel.html", **context)


@router.post("/abonneren")
def subscribe(request: Request, user: CurrentUser, db: DB, form: Form) -> HTMLResponse:
    if not get_settings().push_enabled:
        raise HTTPException(status_code=404)
    try:
        push.subscribe(
            db,
            user,
            endpoint=form.get_str("endpoint"),
            p256dh=form.get_str("p256dh"),
            auth=form.get_str("auth"),
            label=device_label(request.headers.get("user-agent", "")),
        )
    except push.PushError as exc:
        db.rollback()
        return _panel_partial(request, user, db, error=str(exc))
    return _panel_partial(
        request, user, db, message="Meldingen staan aan op dit toestel."
    )


@router.post("/afmelden")
def unsubscribe(
    request: Request, user: CurrentUser, db: DB, form: Form
) -> HTMLResponse:
    """Dit toestel afmelden (de browser stuurt zijn eigen endpoint mee)."""
    subscription = db.scalar(
        select(PushSubscription).where(
            PushSubscription.endpoint == form.get_str("endpoint"),
            PushSubscription.user_id == user.id,
        )
    )
    if subscription is not None:
        push.unsubscribe(db, user, subscription)
    return _panel_partial(
        request, user, db, message="Meldingen staan uit op dit toestel."
    )


@router.post("/{subscription_id}/verwijderen")
def remove(
    request: Request, user: CurrentUser, db: DB, subscription_id: int
) -> HTMLResponse:
    subscription = db.get(PushSubscription, subscription_id)
    if subscription is None or subscription.user_id != user.id:
        raise HTTPException(status_code=404)
    push.unsubscribe(db, user, subscription)
    return _panel_partial(request, user, db, message="Toestel verwijderd.")


@router.post("/test")
def test(request: Request, user: CurrentUser, db: DB) -> HTMLResponse:
    devices = push.subscriptions_for(db, user)
    if not get_settings().push_enabled or not devices:
        return _panel_partial(
            request, user, db, error="Zet eerst meldingen aan op een toestel."
        )
    result = push.send(
        db,
        devices,
        {
            "title": "Testmelding",
            "body": "Meldingen werken. Zo hoor je straks wat er te doen is.",
            "url": "/",
            "tag": "test",
        },
        ttl=600,
    )
    if result.sent:
        message = (
            "Testmelding verstuurd."
            if result.sent == 1
            else f"Testmelding verstuurd naar {result.sent} toestellen."
        )
        return _panel_partial(request, user, db, message=message)
    return _panel_partial(
        request,
        user,
        db,
        error="Versturen lukte niet. Zet meldingen opnieuw aan op dit toestel.",
    )
