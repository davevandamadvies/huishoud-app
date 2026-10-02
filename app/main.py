from fastapi import FastAPI

from app.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    docs_enabled = settings.app_env == "dev"
    app = FastAPI(
        title="huishoud-app",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
