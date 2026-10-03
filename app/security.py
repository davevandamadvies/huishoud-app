"""Beveiligingsheaders voor elk antwoord."""

from collections.abc import Callable

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)

SECURITY_HEADERS = {
    "content-security-policy": CONTENT_SECURITY_POLICY,
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
    "x-frame-options": "DENY",
    "cross-origin-opener-policy": "same-origin",
    "permissions-policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    ),
}


class SecurityHeadersMiddleware:
    """Voegt vaste beveiligingsheaders toe (pure ASGI, ook voor statische bestanden)."""

    def __init__(self, app: ASGIApp, csp_exempt_paths: tuple[str, ...] = ()) -> None:
        self.app = app
        # Alleen voor de OpenAPI-docs in dev (die laden scripts van een CDN).
        self.csp_exempt_paths = csp_exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        skip_csp = scope["path"] in self.csp_exempt_paths

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                for name, value in SECURITY_HEADERS.items():
                    if skip_csp and name == "content-security-policy":
                        continue
                    if name.encode() not in present:
                        headers.append((name.encode(), value.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class CSRFMiddleware:
    """Weigert wijzigende verzoeken die niet van de app zelf komen.

    Vereist bij POST/PUT/PATCH/DELETE een Origin-header gelijk aan de eigen
    origin én de header `HX-Request: true` (die een andere site niet zonder
    CORS-toestemming kan meesturen). Aanvulling op SameSite-cookies.
    """

    def __init__(self, app: ASGIApp, expected_origin: Callable[[], str | None]) -> None:
        self.app = app
        self.expected_origin = expected_origin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        expected = self.expected_origin() or _origin_from_host(scope, headers)
        if headers.get("origin") != expected or headers.get("hx-request") != "true":
            response = PlainTextResponse("Verzoek geweigerd (CSRF).", status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _origin_from_host(scope: Scope, headers: Headers) -> str:
    return f"{scope.get('scheme', 'http')}://{headers.get('host', '')}"
