from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import sessions
from app.db import utcnow
from app.models import UserSession, UserStatus
from tests.factories import make_user


def test_create_and_lookup(db: Session) -> None:
    user = make_user(db)
    token = sessions.create_session(db, user)
    db.commit()
    found = sessions.get_active_session(db, token)
    assert found is not None
    assert found.user_id == user.id


def test_only_hash_is_stored(db: Session) -> None:
    user = make_user(db)
    token = sessions.create_session(db, user)
    db.commit()
    stored = db.scalars(select(UserSession.token_hash)).one()
    assert stored != token
    assert len(stored) == 64
    assert len(token) >= 40


def test_unknown_or_empty_token(db: Session) -> None:
    assert sessions.get_active_session(db, None) is None
    assert sessions.get_active_session(db, "") is None
    assert sessions.get_active_session(db, "onbekend") is None


def test_revoked_session_is_invalid(db: Session) -> None:
    user = make_user(db)
    token = sessions.create_session(db, user)
    db.commit()
    sessions.revoke_session(db, token)
    db.commit()
    assert sessions.get_active_session(db, token) is None


def test_expired_session_is_invalid(db: Session) -> None:
    user = make_user(db)
    token = sessions.create_session(db, user)
    db.commit()
    session = db.scalars(select(UserSession)).one()
    session.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert sessions.get_active_session(db, token) is None


def test_deactivated_user_has_no_session(db: Session) -> None:
    user = make_user(db)
    token = sessions.create_session(db, user)
    user.status = UserStatus.DEACTIVATED
    db.commit()
    assert sessions.get_active_session(db, token) is None


def test_session_slides_forward(db: Session) -> None:
    user = make_user(db)
    token = sessions.create_session(db, user)
    db.commit()
    session = db.scalars(select(UserSession)).one()
    old = utcnow() - timedelta(days=10)
    session.last_seen_at = old
    session.expires_at = old + timedelta(days=90)
    db.commit()

    found = sessions.get_active_session(db, token)
    assert found is not None
    assert found.last_seen_at > old
    assert found.expires_at > old + timedelta(days=95)


def test_revoke_all_sessions(db: Session) -> None:
    user = make_user(db)
    other = make_user(db)
    tokens = [sessions.create_session(db, user) for _ in range(3)]
    other_token = sessions.create_session(db, other)
    db.commit()

    assert sessions.revoke_all_sessions(db, user) == 3
    db.commit()
    assert all(sessions.get_active_session(db, t) is None for t in tokens)
    assert sessions.get_active_session(db, other_token) is not None
