from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.models import Role, User, UserStatus
from tests.factories import make_user


def test_user_defaults(db: Session) -> None:
    user = make_user(db, name="dave")
    db.refresh(user)
    assert user.role == Role.USER
    assert user.status == UserStatus.ACTIVE
    assert user.is_active and not user.is_admin
    assert user.initial == "D"
    assert user.created_at.tzinfo is UTC


def test_oidc_sub_is_unique(db: Session) -> None:
    make_user(db, sub="same")
    db.add(User(display_name="X", oidc_sub="same"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_invalid_role_rejected_by_orm(db: Session) -> None:
    db.add(User(display_name="X", oidc_sub="x", role="superuser"))
    with pytest.raises(StatementError):
        db.commit()


def test_invalid_role_rejected_by_database(db: Session) -> None:
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO users (display_name, oidc_sub, role, status,"
                " avatar_color, created_at, updated_at) VALUES"
                " ('X', 'y', 'superuser', 'active', 1, '2026-01-01', '2026-01-01')"
            )
        )


def test_naive_datetime_rejected(db: Session) -> None:
    user = make_user(db)
    user.created_at = datetime(2026, 1, 1)  # noqa: DTZ001
    with pytest.raises(StatementError):
        db.commit()


def test_foreign_keys_enforced(db: Session) -> None:
    assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
