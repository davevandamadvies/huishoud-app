"""Jinja2-templates met de gedeelde context voor alle pagina's."""

from dataclasses import dataclass
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.dates import dutch_date

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    path: str


NAV_ITEMS = (
    NavItem("today", "Vandaag", "/"),
    NavItem("planning", "Planning", "/planning"),
    NavItem("tasks", "Taken", "/taken"),
    NavItem("scores", "Scores", "/scores"),
    NavItem("more", "Meer", "/meer"),
)


def static_url(path: str) -> str:
    """Relatief pad naar een statisch bestand (werkt ook achter een proxy)."""
    return f"/static/{path}"


templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals.update(nav_items=NAV_ITEMS, static_url=static_url)
templates.env.filters["dutch_date"] = dutch_date
