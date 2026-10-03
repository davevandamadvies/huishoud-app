"""Categorieën: lijst, aanmaken, wijzigen, verwijderen (met audit log)."""

from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.models import Category, User
from app.palette import CATEGORY_COLORS

# Wordt door de takenmodule gezet: telt taken per categorie (verwijderbeveiliging).
task_counter: Callable[[Session, int], int] = lambda _db, _category_id: 0  # noqa: E731


class CategoryError(Exception):
    """Wijziging niet toegestaan; de tekst is geschikt voor de gebruiker."""


def list_categories(db: Session) -> list[Category]:
    return list(db.scalars(select(Category).order_by(Category.position, Category.id)))


def _clean(db: Session, name: str, color: str, current: Category | None) -> str:
    name = " ".join(name.split())
    if not name:
        raise CategoryError("Vul een naam in.")
    if len(name) > 40:
        raise CategoryError("De naam mag maximaal 40 tekens zijn.")
    if color not in CATEGORY_COLORS:
        raise CategoryError("Kies een kleur.")
    existing = db.scalar(
        select(Category).where(func.lower(Category.name) == name.lower())
    )
    if existing is not None and existing is not current:
        raise CategoryError("Er is al een categorie met deze naam.")
    return name


def create(db: Session, actor: User, *, name: str, color: str) -> Category:
    name = _clean(db, name, color, None)
    position = (db.scalar(select(func.max(Category.position))) or 0) + 1
    category = Category(name=name, color=color, position=position)
    db.add(category)
    db.flush()
    audit.record(
        db,
        "category.create",
        actor=actor,
        object_type="category",
        object_id=category.id,
        new={"name": name, "color": color},
    )
    db.commit()
    return category


def update(
    db: Session, actor: User, category: Category, *, name: str, color: str
) -> None:
    name = _clean(db, name, color, category)
    old = {"name": category.name, "color": category.color}
    new = {"name": name, "color": color}
    if old == new:
        return
    category.name, category.color = name, color
    audit.record(
        db,
        "category.update",
        actor=actor,
        object_type="category",
        object_id=category.id,
        old=old,
        new=new,
    )
    db.commit()


def delete(db: Session, actor: User, category: Category) -> None:
    if task_counter(db, category.id):
        raise CategoryError(
            "Deze categorie heeft nog taken. Verplaats of archiveer die eerst."
        )
    audit.record(
        db,
        "category.delete",
        actor=actor,
        object_type="category",
        object_id=category.id,
        old={"name": category.name, "color": category.color},
    )
    db.delete(category)
    db.commit()
