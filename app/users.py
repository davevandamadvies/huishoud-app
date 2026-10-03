"""Gebruikersbeheer: regels en wijzigingen (met audit log)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, push, sessions
from app.models import Role, User, UserStatus

AVATAR_COLORS = 6


class UserAdminError(Exception):
    """Wijziging niet toegestaan; de tekst is geschikt voor de gebruiker."""


def list_users(db: Session) -> list[User]:
    return list(
        db.scalars(select(User).order_by(User.status, func.lower(User.display_name)))
    )


def _active_admin_count(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == Role.ADMIN, User.status == UserStatus.ACTIVE)
        )
        or 0
    )


def _is_last_active_admin(db: Session, user: User) -> bool:
    return user.is_admin and user.is_active and _active_admin_count(db) <= 1


def _clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise UserAdminError("Vul een naam in.")
    if len(name) > 50:
        raise UserAdminError("De naam mag maximaal 50 tekens zijn.")
    return name


def _parse_role(value: str) -> Role:
    try:
        return Role(value)
    except ValueError as exc:
        raise UserAdminError("Onbekende rol.") from exc


def grant_access(
    db: Session, actor: User, *, oidc_sub: str, display_name: str, role: str
) -> User:
    sub = oidc_sub.strip()
    if not sub or len(sub) > 255 or any(c.isspace() for c in sub):
        raise UserAdminError("Vul een geldig account-ID in.")
    if db.scalar(select(User.id).where(User.oidc_sub == sub)):
        raise UserAdminError("Dit account heeft al toegang.")
    count = db.scalar(select(func.count()).select_from(User)) or 0
    user = User(
        oidc_sub=sub,
        display_name=_clean_name(display_name),
        role=_parse_role(role),
        status=UserStatus.ACTIVE,
        avatar_color=count % AVATAR_COLORS + 1,
    )
    db.add(user)
    db.flush()
    audit.record(
        db,
        "user.grant_access",
        actor=actor,
        object_type="user",
        object_id=user.id,
        new={"display_name": user.display_name, "role": user.role.value, "sub": sub},
    )
    db.commit()
    return user


def rename(db: Session, actor: User, user: User, display_name: str) -> None:
    new = _clean_name(display_name)
    if new == user.display_name:
        return
    audit.record(
        db,
        "user.rename",
        actor=actor,
        object_type="user",
        object_id=user.id,
        old={"display_name": user.display_name},
        new={"display_name": new},
    )
    user.display_name = new
    db.commit()


def change_role(db: Session, actor: User, user: User, role: str) -> None:
    new = _parse_role(role)
    if new == user.role:
        return
    if new != Role.ADMIN and _is_last_active_admin(db, user):
        raise UserAdminError("Er moet minimaal één actieve beheerder blijven.")
    audit.record(
        db,
        "user.change_role",
        actor=actor,
        object_type="user",
        object_id=user.id,
        old={"role": user.role.value},
        new={"role": new.value},
    )
    user.role = new
    db.commit()


def deactivate(db: Session, actor: User, user: User) -> None:
    if not user.is_active:
        return
    if _is_last_active_admin(db, user):
        raise UserAdminError("Er moet minimaal één actieve beheerder blijven.")
    user.status = UserStatus.DEACTIVATED
    revoked = sessions.revoke_all_sessions(db, user)
    devices = push.remove_all_for_user(db, user)
    audit.record(
        db,
        "user.deactivate",
        actor=actor,
        object_type="user",
        object_id=user.id,
        old={"status": UserStatus.ACTIVE.value},
        new={
            "status": UserStatus.DEACTIVATED.value,
            "sessions_revoked": revoked,
            "push_subscriptions_removed": devices,
        },
    )
    db.commit()


def activate(db: Session, actor: User, user: User) -> None:
    if user.is_active:
        return
    user.status = UserStatus.ACTIVE
    audit.record(
        db,
        "user.activate",
        actor=actor,
        object_type="user",
        object_id=user.id,
        old={"status": UserStatus.DEACTIVATED.value},
        new={"status": UserStatus.ACTIVE.value},
    )
    db.commit()
