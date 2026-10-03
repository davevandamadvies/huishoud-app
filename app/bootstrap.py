"""Eerste beheerder aanmaken vanuit de configuratie (geen open registratie)."""

import logging

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app import audit
from app.models import Role, User, UserStatus
from app.settings import Settings

logger = logging.getLogger(__name__)


def ensure_initial_admin(db: Session, settings: Settings) -> User | None:
    """Maakt de eerste beheerder aan als er nog geen beheerder bestaat.

    Bestaat er al een gebruiker met deze `sub`, dan wordt die beheerder.
    Doet niets als er al een beheerder is of INITIAL_ADMIN_SUB ontbreekt.
    """
    if db.scalar(select(User.id).where(User.role == Role.ADMIN).limit(1)):
        return None
    sub = settings.initial_admin_sub
    if not sub:
        logger.warning(
            "Er is nog geen beheerder en INITIAL_ADMIN_SUB is niet ingesteld."
        )
        return None

    user = db.scalar(select(User).where(User.oidc_sub == sub))
    if user is None:
        user = User(
            display_name=settings.initial_admin_name,
            oidc_sub=sub,
            role=Role.ADMIN,
            status=UserStatus.ACTIVE,
        )
        db.add(user)
        db.flush()
        audit.record(
            db,
            "user.bootstrap_admin",
            object_type="user",
            object_id=user.id,
            new={"display_name": user.display_name, "role": user.role.value},
        )
    else:
        old = {"role": user.role.value, "status": user.status.value}
        user.role = Role.ADMIN
        user.status = UserStatus.ACTIVE
        audit.record(
            db,
            "user.bootstrap_admin",
            object_type="user",
            object_id=user.id,
            old=old,
            new={"role": user.role.value, "status": user.status.value},
        )
    db.commit()
    logger.info("Eerste beheerder ingesteld (gebruiker %s).", user.id)
    return user


def run_bootstrap(db: Session, settings: Settings) -> None:
    """Bij het opstarten; slaat over als de migraties nog niet gedraaid zijn."""
    if not inspect(db.get_bind()).has_table(User.__tablename__):
        logger.warning(
            "Database is nog niet gemigreerd; draai eerst 'alembic upgrade head'."
        )
        return
    ensure_initial_admin(db, settings)
