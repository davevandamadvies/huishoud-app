from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime, utcnow
from app.models.user import User


class Vehicle(Base):
    """Voertuig met een kilometerstand (bijv. de auto)."""

    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


class OdometerReading(Base):
    """Kilometerstand op een dag."""

    __tablename__ = "odometer_readings"
    __table_args__ = (
        Index("ix_odometer_readings_vehicle_day", "vehicle_id", "read_on"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE")
    )
    read_on: Mapped[date] = mapped_column(Date)
    km: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    vehicle: Mapped[Vehicle] = relationship()
    user: Mapped[User | None] = relationship()
