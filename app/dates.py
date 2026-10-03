"""Datumhulpjes: tijdzone van het huishouden en Nederlandse weergave."""

from datetime import date, datetime, time
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


_SHORT_MONTHS = (
    "jan",
    "feb",
    "mrt",
    "apr",
    "mei",
    "jun",
    "jul",
    "aug",
    "sep",
    "okt",
    "nov",
    "dec",
)


def short_date(value: date) -> str:
    """Bijv. '3 okt'."""
    return f"{value.day} {_SHORT_MONTHS[value.month - 1]}"


def due_label(due: date | None, reference: date) -> tuple[str, str]:
    """Korte tekst en toon ('late', 'soon', 'later', 'none') voor een datum."""
    if due is None:
        return "nog geen datum", "none"
    days = (due - reference).days
    if days < 0:
        late = -days
        return (f"{late} dag te laat" if late == 1 else f"{late} dagen te laat"), "late"
    if days == 0:
        return "vandaag", "soon"
    if days == 1:
        return "morgen", "soon"
    if days <= 30:
        return f"over {days} d", "later"
    return short_date(due), "later"


_SHORT_WEEKDAYS = ("ma", "di", "wo", "do", "vr", "za", "zo")


def short_weekday(value: date) -> str:
    """Bijv. 'za'."""
    return _SHORT_WEEKDAYS[value.weekday()]


def plan_label(planned: date, at: time | None, reference: date) -> str:
    """Bijv. 'gepland 10:00' (vandaag), 'gepland morgen', 'gepland za 10:00'."""
    clock = f" {at.strftime('%H:%M')}" if at else ""
    days = (planned - reference).days
    if days == 0:
        return f"gepland{clock}" if clock else "gepland vandaag"
    if days == 1:
        return f"gepland morgen{clock}"
    if 1 < days < 7:
        return f"gepland {short_weekday(planned)}{clock}"
    return f"gepland {short_date(planned)}{clock}"
