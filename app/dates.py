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


def local_date(moment: datetime) -> date:
    """Tijdstip (UTC) als datum in de tijdzone van het huishouden."""
    return moment.astimezone(TIMEZONE).date()


def dutch_date(value: date, reference: date | None = None) -> str:
    """Bijv. 'zaterdag 3 oktober'; met jaartal als het niet dit jaar is."""
    text = f"{_WEEKDAYS[value.weekday()]} {value.day} {_MONTHS[value.month - 1]}"
    if value.year != (reference or today()).year:
        text += f" {value.year}"
    return text


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


def short_date(value: date, reference: date | None = None) -> str:
    """Bijv. '3 okt'; met jaartal als het niet dit jaar is ('3 okt 2027')."""
    text = f"{value.day} {_SHORT_MONTHS[value.month - 1]}"
    if value.year != (reference or today()).year:
        text += f" {value.year}"
    return text


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
    return short_date(due, reference), "later"


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
    return f"gepland {short_date(planned, reference)}{clock}"


def when_label(moment: datetime, reference: date) -> str:
    """Tijdstip in de tijdzone van het huishouden: 'vandaag 09:12', 'za 3 okt'."""
    local = moment.astimezone(TIMEZONE)
    days = (reference - local.date()).days
    clock = local.strftime("%H:%M")
    if days == 0:
        return f"vandaag {clock}"
    if days == 1:
        return f"gisteren {clock}"
    return f"{short_weekday(local.date())} {short_date(local.date(), reference)}"
