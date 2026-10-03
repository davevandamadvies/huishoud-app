from itertools import count

from sqlalchemy.orm import Session

from app.models import Role, User, UserStatus

_seq = count(1)


def make_user(
    db: Session,
    *,
    name: str | None = None,
    role: Role = Role.USER,
    status: UserStatus = UserStatus.ACTIVE,
    sub: str | None = None,
) -> User:
    n = next(_seq)
    user = User(
        display_name=name or f"Gebruiker {n}",
        oidc_sub=sub or f"sub-{n}",
        role=role,
        status=status,
    )
    db.add(user)
    db.commit()
    return user
