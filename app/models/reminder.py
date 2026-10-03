from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, utcnow


class ReminderPreference(Base):
    """Herinneringsvoorkeuren van één gebruiker ("Mijn reminders").

    Zonder rij gelden de standaardwaarden (zie app/reminders.py).
    """

    __tablename__ = "reminder_preferences"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Update met de stand van het huishouden
    update_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    update_days: Mapped[str] = mapped_column(String(7), default="0123456")  # ma=0
    update_times: Mapped[str] = mapped_column(String(17), default="08:30")
    lookahead_days: Mapped[int] = mapped_column(Integer, default=3)
    only_mine: Mapped[bool] = mapped_column(Boolean, default=False)
    # Losse meldingen per taak
    task_on_day: Mapped[bool] = mapped_column(Boolean, default=False)
    task_days_before: Mapped[int] = mapped_column(Integer, default=0)  # 0 = niet
    task_late_daily: Mapped[bool] = mapped_column(Boolean, default=False)
    # Stille uren (HH:MM, mag over middernacht)
    quiet_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    quiet_start: Mapped[str] = mapped_column(String(5), default="22:00")
    quiet_end: Mapped[str] = mapped_column(String(5), default="07:00")
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow
    )


class ReminderMutedCategory(Base):
    """Categorie waarvoor een gebruiker geen herinneringen wil."""

    __tablename__ = "reminder_muted_categories"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True
    )
