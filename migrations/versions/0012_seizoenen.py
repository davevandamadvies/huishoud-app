"""seizoenen

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-04 15:27:06.530014

"""

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SEED_SEASONS = {
    "Ramen buiten lappen": "3,4,5,6,7,8,9,10",
    "Radiatoren ontluchten": "9,10,11",
    "Dakgoten schoonmaken": "10,11,12",
    "Zonnepanelen visueel controleren": "4,5,6,7,8,9",
    "Gras maaien": "3,4,5,6,7,8,9,10",
    "Onkruid wieden": "4,5,6,7,8,9",
    "Heg snoeien": "5,6,7,8,9",
    "Gazon bemesten": "3,4,5,6,7,8,9,10",
    "Terras/tegels reinigen": "4,5,6",
    "Bladeren ruimen": "10,11,12",
    "Tuinmeubels opruimen/afdekken": "10,11",
    "Buitenkraan aftappen": "11",
    "Kamerplanten voeden": "3,4,5,6,7,8,9",
    "Verpotten (waar nodig)": "3,4",
}


def _as_date(value: object) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _into_season(day: date, season: set[int]) -> date:
    if day.month in season:
        return day
    year, month = day.year, day.month
    for _ in range(12):
        month += 1
        if month > 12:
            year, month = year + 1, 1
        if month in season:
            return date(year, month, 1)
    return day


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("season_months", sa.String(length=30), nullable=True)
        )

    # Startvulling: de seizoenen uit de beginlijst (alleen als nog leeg), en
    # een open uitvoering buiten het seizoen schuift naar het volgende begin.
    connection = op.get_bind()
    for name, months in SEED_SEASONS.items():
        row = connection.execute(
            sa.text(
                "SELECT id FROM tasks WHERE name = :name AND season_months IS NULL"
            ),
            {"name": name},
        ).first()
        if row is None:
            continue
        connection.execute(
            sa.text("UPDATE tasks SET season_months = :months WHERE id = :id"),
            {"months": months, "id": row.id},
        )
        season = {int(m) for m in months.split(",")}
        for occurrence in connection.execute(
            sa.text(
                "SELECT id, due_date FROM occurrences "
                "WHERE task_id = :id AND status = 'open' AND due_date IS NOT NULL"
            ),
            {"id": row.id},
        ).all():
            due = _as_date(occurrence.due_date)
            shifted = _into_season(due, season)
            if shifted != due:
                connection.execute(
                    sa.text("UPDATE occurrences SET due_date = :due WHERE id = :id"),
                    {"due": shifted.isoformat(), "id": occurrence.id},
                )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_column("season_months")
