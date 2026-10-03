import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app import (
    admin,
    auth,
    category_pages,
    pages,
    planning_pages,
    push_pages,
    pwa,
    reminder_pages,
    reminder_scheduler,
    task_pages,
)
from app.bootstrap import run_bootstrap
from app.db import new_session
from app.oidc import OIDCNotConfigured
from app.security import CSRFMiddleware, SecurityHeadersMiddleware
from app.settings import get_settings
from app.templating import STATIC_DIR

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    missing = settings.missing_auth_settings()
    if missing:
        # Niet crashen: de app blijft dicht (inloggen meldt dat het niet is
        # ingesteld) en /healthz blijft werken.
        logger.error("Inloggen is niet ingesteld; ontbrekend: %s", ", ".join(missing))
    with new_session() as db:
        run_bootstrap(db, settings)
    async with reminder_scheduler.running():
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    docs_enabled = settings.app_env == "dev"
    app = FastAPI(
        title="huishoud-app",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )
    app.add_middleware(CSRFMiddleware, expected_origin=lambda: get_settings().base_url)
    app.add_middleware(
        SecurityHeadersMiddleware,
        csp_exempt_paths=("/docs", "/redoc") if docs_enabled else (),
        hsts=settings.app_env == "prod"
        and (settings.base_url or "").startswith("https://"),
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(pwa.router)
    app.include_router(auth.router)
    app.include_router(pages.router)
    app.include_router(admin.router)
    app.include_router(category_pages.router)
    app.include_router(task_pages.router)
    app.include_router(planning_pages.router)
    app.include_router(push_pages.router)
    app.include_router(reminder_pages.router)

    @app.exception_handler(auth.NotAuthenticated)
    def _not_authenticated(request: Request, _exc: Exception) -> Response:
        return auth.not_authenticated_response(request)

    @app.exception_handler(auth.Forbidden)
    def _forbidden(request: Request, _exc: Exception) -> Response:
        return auth.forbidden_response(request)

    @app.exception_handler(OIDCNotConfigured)
    def _oidc_not_configured(request: Request, exc: Exception) -> Response:
        return auth.not_configured_response(request, exc)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
