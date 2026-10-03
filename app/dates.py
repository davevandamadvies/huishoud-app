"""Datumhulpjes: tijdzone van het huishouden en Nederlandse weergave."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Europe/Amsterdam")

_WEEKDAYS = (
    "maandag",
    "dinsdag",
    "woensdag",
    "donderdag",
    "vrijdag",
    "zaterdag",
    "zondag",
)
_MONTHS = (
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
)


def today() -> date:
    """De datum van vandaag in de tijdzone van het huishouden."""
    return datetime.now(TIMEZONE).date()


def dutch_date(value: date) -> str:
    """Bijv. 'zaterdag 3 oktober'."""
    return f"{_WEEKDAYS[value.weekday()]} {value.day} {_MONTHS[value.month - 1]}"
