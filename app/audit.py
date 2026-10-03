"""Audit log: vastleggen wie wat wanneer heeft gedaan."""

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record(
    db: Session,
    action: str,
    *,
    actor: User | None = None,
    object_type: str | None = None,
    object_id: object | None = None,
    old: Any = None,
    new: Any = None,
) -> AuditLog:
    """Voegt een regel toe aan de audit log (commit gebeurt door de aanroeper)."""
    entry = AuditLog(
        action=action,
        actor_id=actor.id if actor is not None else None,
        object_type=object_type,
        object_id=str(object_id) if object_id is not None else None,
        old_value=old,
        new_value=new,
    )
    db.add(entry)
    return entry
