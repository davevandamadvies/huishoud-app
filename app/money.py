"""Bedragen in euro's: invoer in Nederlandse of Engelse notatie, opslag in centen."""

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.models import Occurrence, OccurrenceStatus, Task, User

MAX_CENTS = 100_000 * 100
_AMOUNT = re.compile(r"^\d+(?:[.,]\d{1,2})?$")


class MoneyError(Exception):
    """Ongeldig bedrag; de tekst is geschikt voor de gebruiker."""


def parse_euro(raw: str) -> int | None:
    """'89,50', '89.50', '1.234,50', '€ 12' → centen; leeg → None."""
    text = raw.strip().replace("€", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "")  # punt als duizendtal, komma als decimaal
    elif text.count(".") == 1 and re.fullmatch(r"\d{1,3}\.\d{3}", text):
        text = text.replace(".", "")  # '1.234' = duizend tweehonderd...
    if not _AMOUNT.match(text):
        raise MoneyError("Vul een bedrag in, bijv. 89,50.")
    euros, _, cents = text.replace(",", ".").partition(".")
    amount = int(euros) * 100 + int((cents + "00")[:2])
    if amount > MAX_CENTS:
        raise MoneyError("Dat bedrag is te hoog (maximaal € 100.000).")
    return amount


def format_euro(cents: int | None) -> str:
    """12345 → '€ 123,45'; 123450 → '€ 1.234,50'."""
    if cents is None:
        return ""
    euros, rest = divmod(cents, 100)
    return f"€ {euros:,}".replace(",", ".") + f",{rest:02d}"


def input_value(cents: int | None) -> str:
    """Voor een invoerveld: 8950 → '89,50'."""
    if cents is None:
        return ""
    euros, rest = divmod(cents, 100)
    return f"{euros},{rest:02d}"


def correct(
    db: Session, actor: User, occurrence: Occurrence, cents: int | None
) -> None:
    """Kosten van een uitvoering achteraf aanpassen (met audit log)."""
    if occurrence.cost_cents == cents:
        return
    audit.record(
        db,
        "occurrence.cost",
        actor=actor,
        object_type="occurrence",
        object_id=occurrence.id,
        old={"cost_cents": occurrence.cost_cents},
        new={"cost_cents": cents},
    )
    occurrence.cost_cents = cents
    db.commit()


def task_totals(db: Session, task: Task, year: int) -> tuple[int, int]:
    """(kosten dit jaar, kosten altijd) in centen."""
    base = select(func.coalesce(func.sum(Occurrence.cost_cents), 0)).where(
        Occurrence.task_id == task.id, Occurrence.status == OccurrenceStatus.DONE
    )
    this_year = db.scalar(
        base.where(func.strftime("%Y", Occurrence.completed_on) == str(year))
    )
    return int(this_year or 0), int(db.scalar(base) or 0)
