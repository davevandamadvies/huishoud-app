"""PWA: manifest, service worker en offline-pagina (publiek, zonder login)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.templating import STATIC_DIR, templates

router = APIRouter(include_in_schema=False)

THEME_COLOR = "#1f7a55"
BACKGROUND_COLOR = "#fafaf8"

MANIFEST = {
    "id": "/",
    "name": "Huishoud",
    "short_name": "Huishoud",
    "description": "Huishoudtaken plannen en bijhouden, samen.",
    "lang": "nl",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "orientation": "portrait",
    "theme_color": THEME_COLOR,
    "background_color": BACKGROUND_COLOR,
    "icons": [
        {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
        {
            "src": "/static/icons/maskable-512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "maskable",
        },
    ],
}


@router.get("/manifest.webmanifest")
def manifest() -> JSONResponse:
    return JSONResponse(
        MANIFEST,
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/sw.js")
def service_worker() -> Response:
    # Op de root geserveerd, zodat de scope de hele app is.
    return Response(
        (STATIC_DIR / "js" / "sw.js").read_bytes(),
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@router.get("/offline")
def offline(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "pages/offline.html", {"page_title": "Offline", "hide_nav": True}
    )
