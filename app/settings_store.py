"""Instellingen van het huishouden (in de database, niet uit de omgeving)."""

from sqlalchemy.orm import Session

from app import audit
from app.models import Setting, User

COMPETITION = "competition_enabled"
_DEFAULTS = {COMPETITION: "false"}


def get(db: Session, key: str) -> str:
    setting = db.get(Setting, key)
    return setting.value if setting is not None else _DEFAULTS[key]


def set_value(db: Session, actor: User, key: str, value: str) -> None:
    old = get(db, key)
    if old == value:
        return
    setting = db.get(Setting, key)
    if setting is None:
        db.add(Setting(key=key, value=value))
    else:
        setting.value = value
    audit.record(
        db,
        "setting.update",
        actor=actor,
        object_type="setting",
        object_id=key,
        old={"value": old},
        new={"value": value},
    )
    db.commit()


def competition_enabled(db: Session) -> bool:
    """Punten en scorebord zijn alleen actief als de competitie aan staat."""
    return get(db, COMPETITION) == "true"
