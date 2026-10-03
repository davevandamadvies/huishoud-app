import hashlib
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dates import dutch_date
from app.main import app, create_app
from app.settings import get_settings

client = TestClient(app)

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


@pytest.mark.parametrize(
    ("path", "title", "active"),
    [
        ("/", "Vandaag", "/"),
        ("/planning", "Planning", "/planning"),
        ("/taken", "Taken", "/taken"),
        ("/scores", "Scores", "/scores"),
        ("/meer", "Instellingen", "/meer"),
    ],
)
def test_pages_render_with_navigation(path: str, title: str, active: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert f"<title>{title} · Huishoud</title>" in html
    assert f'<a href="{active}" aria-current="page">' in html
    assert html.count('aria-current="page"') == 1
    assert 'aria-label="Hoofdmenu"' in html


def test_assets_are_local_and_served() -> None:
    html = client.get("/").text
    for url in re.findall(r'(?:href|src)="(/static/[^"]+)"', html):
        assert client.get(url).status_code == 200, url
    assert "/static/vendor/htmx/htmx.min.js" in html
    assert "/static/css/app.css" in html
    # Geen externe bronnen
    assert not re.search(r'(?:href|src)="(?:https?:)?//', html)


class _InlineCodeFinder(HTMLParser):
    """Verzamelt inline scripts, style-elementen en style-attributen."""

    def __init__(self) -> None:
        super().__init__()
        self.found: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        names = {name for name, _ in attrs}
        if tag == "script" and "src" not in names:
            self.found.append("inline <script>")
        if tag == "style":
            self.found.append("<style>")
        if "style" in names:
            self.found.append(f"style-attribuut op <{tag}>")
        if any(name.startswith("on") or name.startswith("hx-on") for name in names):
            self.found.append(f"event-handler op <{tag}>")


def test_no_inline_scripts_or_styles() -> None:
    finder = _InlineCodeFinder()
    finder.feed(client.get("/").text)
    assert finder.found == []


def test_vendored_checksums_match_readme() -> None:
    readme = (STATIC / "vendor" / "README.md").read_text()
    rows = re.findall(r"\| `([^`]+)` \|[^\n]*\| `([0-9a-f]{64})` \|", readme)
    assert len(rows) == 3
    for relative, expected in rows:
        digest = hashlib.sha256((STATIC / "vendor" / relative).read_bytes()).hexdigest()
        assert digest == expected, relative


def test_dutch_date() -> None:
    assert dutch_date(date(2026, 10, 3)) == "zaterdag 3 oktober"
    assert dutch_date(date(2027, 1, 4)) == "maandag 4 januari"


def test_pages_not_in_openapi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    get_settings.cache_clear()
    try:
        dev_client = TestClient(create_app())
        paths = dev_client.get("/openapi.json").json()["paths"]
        # Docs in dev zonder CSP, zodat Swagger UI werkt
        docs = dev_client.get("/docs")
        assert "content-security-policy" not in docs.headers
    finally:
        get_settings.cache_clear()
    assert "/healthz" in paths
    assert "/" not in paths
    assert "/taken" not in paths
