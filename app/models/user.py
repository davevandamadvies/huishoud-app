from datetime import datetime
from enum import StrEnum

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime, utcnow


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DEACTIVATED = "deactivated"


def _enum(enum_cls: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
        length=20,
    )


class User(Base):
    """Gebruiker van de app, gekoppeld aan een Authelia-account via `sub`."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(50))
    oidc_sub: Mapped[str] = mapped_column(String(255), unique=True)
    role: Mapped[Role] = mapped_column(_enum(Role, "role"), default=Role.USER)
    status: Mapped[UserStatus] = mapped_column(
        _enum(UserStatus, "status"), default=UserStatus.ACTIVE
    )
    # Index in het avatarpalet in de CSS (.avatar-1, .avatar-2, ...)
    avatar_color: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow
    )

    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user")

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def initial(self) -> str:
        return self.display_name[:1].upper()


class UserSession(Base):
    """Server-side sessie. Alleen de hash van het token wordt opgeslagen."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    user: Mapped[User] = relationship(back_populates="sessions")
