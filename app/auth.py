"""Inloggen, uitloggen en de dependency voor de ingelogde gebruiker."""

import hmac
import json
import logging
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, sessions
from app.db import get_db
from app.models import User
from app.oidc import OIDCClient, OIDCError, get_oidc_client
from app.settings import get_settings
from app.templating import templates

logger = logging.getLogger(__name__)

# __Host-: alleen via HTTPS, geen Domain, Path=/ — niet te zetten door subdomeinen.
SESSION_COOKIE = "__Host-huishoud_session"
LOGIN_COOKIE = "__Host-huishoud_login"
_LOGIN_COOKIE_MAX_AGE = 600

router = APIRouter(prefix="/auth", include_in_schema=False)


class NotAuthenticated(Exception):
    """Geen geldige sessie; wordt omgezet in een redirect naar de login."""


def safe_next(target: str | None) -> str:
    """Alleen paden binnen de app als doel na het inloggen (geen open redirect)."""
    if (
        not target
        or not target.startswith("/")
        or target.startswith("//")
        or "\\" in target
        or target.startswith("/auth/")
    ):
        return "/"
    return target


def current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User:
    """De ingelogde, actieve gebruiker; rol en status komen vers uit de database."""
    session = sessions.get_active_session(db, request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise NotAuthenticated
    db.commit()  # verlenging van de sessie opslaan
    request.state.user = session.user
    return session.user


CurrentUser = Annotated[User, Depends(current_user)]


def not_authenticated_response(request: Request) -> Response:
    target = request.url.path
    if request.url.query:
        target += f"?{request.url.query}"
    login_url = f"/auth/login?next={quote(safe_next(target), safe='/')}"
    if request.headers.get("hx-request") == "true":
        response: Response = Response(
            status_code=401, headers={"HX-Redirect": login_url}
        )
    else:
        response = RedirectResponse(login_url, status_code=303)
    if SESSION_COOKIE in request.cookies:
        response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True)
    return response


def _page(
    request: Request, template: str, title: str, status: int, **context: object
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        template,
        {"page_title": title, "hide_nav": True, **context},
        status_code=status,
    )


def not_configured_response(request: Request, exc: Exception) -> HTMLResponse:
    logger.error("Inloggen niet ingesteld; ontbrekend: %s", exc)
    return _page(request, "pages/auth_error.html", "Inloggen", 503, reason="config")


@router.get("/login")
def login(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    oidc: Annotated[OIDCClient, Depends(get_oidc_client)],
    next: str = "/",
) -> Response:
    target = safe_next(next)
    if sessions.get_active_session(db, request.cookies.get(SESSION_COOKIE)):
        return RedirectResponse(target, status_code=303)
    try:
        login_request = oidc.start_login()
    except OIDCError as exc:
        logger.warning("Login starten mislukt: %s", exc)
        return _page(request, "pages/auth_error.html", "Inloggen", 502, reason="idp")

    response = RedirectResponse(login_request.url, status_code=303)
    response.set_cookie(
        LOGIN_COOKIE,
        json.dumps(
            {
                "state": login_request.state,
                "nonce": login_request.nonce,
                "verifier": login_request.code_verifier,
                "next": target,
            }
        ),
        max_age=_LOGIN_COOKIE_MAX_AGE,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/callback")
def callback(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    oidc: Annotated[OIDCClient, Depends(get_oidc_client)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    try:
        pending = json.loads(request.cookies.get(LOGIN_COOKIE, ""))
        expected_state = str(pending["state"])
    except (ValueError, KeyError, TypeError):
        pending, expected_state = None, ""

    def fail(reason: str, detail: str = "") -> Response:
        audit.record(db, "auth.failed", new={"reason": reason})
        db.commit()
        logger.warning("Inloggen mislukt (%s) %s", reason, detail)
        response = _page(
            request, "pages/auth_error.html", "Inloggen", 400, reason="failed"
        )
        response.delete_cookie(LOGIN_COOKIE, path="/", secure=True, httponly=True)
        return response

    if error:
        return fail("idp_error", error[:100])
    if not pending or not state or not hmac.compare_digest(state, expected_state):
        return fail("state_mismatch")
    if not code:
        return fail("missing_code")
    try:
        claims = oidc.finish_login(code, pending["verifier"], pending["nonce"])
    except OIDCError as exc:
        return fail("invalid_token", str(exc))

    sub = str(claims["sub"])
    user = db.scalar(select(User).where(User.oidc_sub == sub))
    if user is None or not user.is_active:
        reason = "unknown_account" if user is None else "deactivated"
        audit.record(
            db,
            "auth.denied",
            actor=user,
            new={"reason": reason, "sub": sub, "name": claims.get("name")},
        )
        db.commit()
        response = _page(request, "pages/no_access.html", "Geen toegang", 403, sub=sub)
        response.delete_cookie(LOGIN_COOKIE, path="/", secure=True, httponly=True)
        return response

    token = sessions.create_session(db, user)
    audit.record(db, "auth.login", actor=user, object_type="user", object_id=user.id)
    db.commit()

    response = RedirectResponse(safe_next(pending.get("next")), status_code=303)
    response.delete_cookie(LOGIN_COOKIE, path="/", secure=True, httponly=True)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=get_settings().session_max_age_days * 86400,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/logout")
def logout(request: Request, db: Annotated[Session, Depends(get_db)]) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    session = sessions.get_active_session(db, token)
    if session is not None:
        audit.record(db, "auth.logout", actor=session.user)
    sessions.revoke_session(db, token)
    db.commit()
    response = Response(status_code=204, headers={"HX-Redirect": "/auth/uitgelogd"})
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True)
    return response


@router.get("/uitgelogd")
def logged_out(request: Request) -> HTMLResponse:
    return _page(request, "pages/logged_out.html", "Uitgelogd", 200)
