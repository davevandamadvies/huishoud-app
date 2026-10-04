from datetime import date, datetime, time
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime, utcnow
from app.models.category import Category
from app.models.user import User
from app.models.vehicle import Vehicle
from app.recurrence import (
    IntervalUnit,
    RecurrenceType,
    Rule,
    describe,
    describe_season,
    parse_months,
)


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


class Task(Base):
    """Taakdefinitie: wat er moet gebeuren en hoe vaak."""

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "recurrence_type = 'once' OR interval_every >= 1", name="interval"
        ),
        CheckConstraint(
            "default_points IS NULL OR default_points BETWEEN 1 AND 100",
            name="points",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )
    recurrence_type: Mapped[RecurrenceType] = mapped_column(
        _enum(RecurrenceType, "recurrence_type")
    )
    interval_every: Mapped[int | None] = mapped_column(Integer)
    interval_unit: Mapped[IntervalUnit] = mapped_column(
        _enum(IntervalUnit, "interval_unit"), default=IntervalUnit.DAYS
    )
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    default_points: Mapped[int | None] = mapped_column(Integer)
    # Alleen bij een vaste datum: eerste herinnering zoveel dagen vooraf.
    first_reminder_days: Mapped[int | None] = mapped_column(Integer)
    # Taak voor een voertuig (bijv. olie verversen); fase 5.
    vehicle_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL")
    )
    # Of elke zoveel km (wat het eerst komt); alleen met een voertuig.
    km_interval: Mapped[int | None] = mapped_column(Integer)
    # Actieve maanden, bijv. "3,4,5,6,7,8,9,10"; leeg = het hele jaar.
    season_months: Mapped[str | None] = mapped_column(String(30))
    notes: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow
    )

    category: Mapped[Category] = relationship()
    owner: Mapped[User | None] = relationship()
    vehicle: Mapped[Vehicle | None] = relationship()

    @property
    def rule(self) -> Rule:
        return Rule(self.recurrence_type, self.interval_every, self.interval_unit)

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    @property
    def season(self) -> frozenset[int] | None:
        return parse_months(self.season_months)

    @property
    def recurrence_text(self) -> str:
        """Bijv. 'Jaarlijks of elke 15.000 km' of 'Elke 7 dagen · mrt–okt'."""
        text = describe(self.rule)
        if self.km_interval and self.vehicle_id:
            text += f" of elke {self.km_interval:,} km".replace(",", ".")
        season = describe_season(self.season)
        if season:
            text += f" · {season}"
        return text


class OccurrenceStatus(StrEnum):
    OPEN = "open"
    PLANNED = "planned"
    DONE = "done"
    SKIPPED = "skipped"


class Occurrence(Base):
    """Uitvoering: één concreet moment waarop een taak (moet) gebeuren."""

    __tablename__ = "occurrences"
    __table_args__ = (
        # Nooit stapelen: per taak hooguit één openstaande of geplande uitvoering.
        Index(
            "uq_occurrences_one_pending_per_task",
            "task_id",
            unique=True,
            sqlite_where=text("status IN ('open', 'planned')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[OccurrenceStatus] = mapped_column(
        _enum(OccurrenceStatus, "status"), default=OccurrenceStatus.OPEN
    )
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    planned_date: Mapped[date | None] = mapped_column(Date)
    planned_time: Mapped[time | None] = mapped_column(Time)
    points: Mapped[int | None] = mapped_column(Integer)
    completed_on: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    note: Mapped[str | None] = mapped_column(Text)
    cost_cents: Mapped[int | None] = mapped_column(Integer)
    km: Mapped[int | None] = mapped_column(Integer)  # kilometerstand bij afvinken
    # Km-of-tijd: de km-grens en de vervaldatum volgens alleen de tijd. De
    # vervaldatum (due_date) is de vroegste van tijd en geschatte km-datum.
    due_km: Mapped[int | None] = mapped_column(Integer)
    time_due_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    task: Mapped[Task] = relationship()
    performers: Mapped[list["Performer"]] = relationship(
        cascade="all, delete-orphan", order_by="Performer.user_id"
    )
    owners: Mapped[list["OccurrenceOwner"]] = relationship(
        cascade="all, delete-orphan", order_by="OccurrenceOwner.user_id"
    )

    @property
    def is_pending(self) -> bool:
        return self.status in (OccurrenceStatus.OPEN, OccurrenceStatus.PLANNED)

    @property
    def effective_date(self) -> date | None:
        """Plandatum gaat voor de berekende vervaldatum."""
        return self.planned_date or self.due_date


class Performer(Base):
    """Wie een uitvoering daadwerkelijk heeft gedaan (0..n per uitvoering)."""

    __tablename__ = "occurrence_performers"

    occurrence_id: Mapped[int] = mapped_column(
        ForeignKey("occurrences.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    # Toegekende punten (fase 3); leeg = geen punten
    points: Mapped[int | None] = mapped_column(Integer)

    user: Mapped[User] = relationship()


class OccurrenceOwner(Base):
    """Eigenaar(s) van een geplande uitvoering (0..n): wie het zou doen.

    Los van Performer, die vastlegt wie het daadwerkelijk heeft gedaan.
    """

    __tablename__ = "occurrence_owners"

    occurrence_id: Mapped[int] = mapped_column(
        ForeignKey("occurrences.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True, index=True
    )

    user: Mapped[User] = relationship()
