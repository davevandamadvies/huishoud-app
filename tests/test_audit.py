from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.models import AuditLog
from tests.factories import make_user


def test_record_with_actor(db: Session) -> None:
    user = make_user(db)
    audit.record(
        db,
        "task.update",
        actor=user,
        object_type="task",
        object_id=7,
        old={"name": "a"},
        new={"name": "b"},
    )
    db.commit()
    entry = db.scalars(select(AuditLog)).one()
    assert entry.actor_id == user.id
    assert entry.object_id == "7"
    assert entry.old_value == {"name": "a"}
    assert entry.new_value == {"name": "b"}
    assert entry.created_at is not None


def test_record_without_actor(db: Session) -> None:
    audit.record(db, "auth.denied", new={"reason": "unknown_sub"})
    db.commit()
    entry = db.scalars(select(AuditLog)).one()
    assert entry.actor_id is None


def test_actor_deletion_keeps_history(db: Session) -> None:
    user = make_user(db)
    audit.record(db, "x", actor=user)
    db.commit()
    db.delete(user)
    db.commit()
    assert db.scalars(select(AuditLog)).one().actor_id is None
