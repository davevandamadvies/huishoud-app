from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import pages
from app.security import SecurityHeadersMiddleware
from app.settings import get_settings
from app.templating import STATIC_DIR


def create_app() -> FastAPI:
    settings = get_settings()
    docs_enabled = settings.app_env == "dev"
    app = FastAPI(
        title="huishoud-app",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.add_middleware(
        SecurityHeadersMiddleware,
        csp_exempt_paths=("/docs", "/redoc") if docs_enabled else (),
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(pages.router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
