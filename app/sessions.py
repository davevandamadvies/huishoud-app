"""Server-side sessies: aanmaken, opzoeken, verlengen en intrekken.

Het token gaat alleen naar de browser (cookie); in de database staat
uitsluitend de SHA-256-hash, zodat een gelekte database geen geldige
sessies oplevert.
"""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import User, UserSession
from app.settings import get_settings

# Verlengen hoeft niet bij elk verzoek; één keer per uur is genoeg.
_EXTEND_AFTER = timedelta(hours=1)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _max_age() -> timedelta:
    return timedelta(days=get_settings().session_max_age_days)


def create_session(db: Session, user: User) -> str:
    """Maakt een sessie aan en geeft het (geheime) token terug."""
    token = secrets.token_urlsafe(32)
    now = utcnow()
    db.add(
        UserSession(
            token_hash=_hash(token),
            user_id=user.id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + _max_age(),
        )
    )
    return token


def get_active_session(db: Session, token: str | None) -> UserSession | None:
    """Geldige, niet-ingetrokken sessie van een actieve gebruiker, of None.

    Verlengt de sessie (glijdend venster) als dat nodig is.
    """
    if not token:
        return None
    session = db.scalar(
        select(UserSession).where(UserSession.token_hash == _hash(token))
    )
    now = utcnow()
    if (
        session is None
        or session.revoked_at is not None
        or session.expires_at <= now
        or not session.user.is_active
    ):
        return None
    if now - session.last_seen_at >= _EXTEND_AFTER:
        session.last_seen_at = now
        session.expires_at = now + _max_age()
    return session


def revoke_session(db: Session, token: str | None) -> None:
    if not token:
        return
    db.execute(
        update(UserSession)
        .where(UserSession.token_hash == _hash(token))
        .where(UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def revoke_all_sessions(db: Session, user: User) -> int:
    """Trekt alle sessies van een gebruiker in; geeft het aantal terug."""
    result = db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id)
        .where(UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    return result.rowcount
