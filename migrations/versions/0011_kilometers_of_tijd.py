"""kilometers of tijd

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-04 15:18:50.686028

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("occurrences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("due_km", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("time_due_date", sa.Date(), nullable=True))

    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("km_interval", sa.Integer(), nullable=True))

    # Startvulling: olie verversen per 15.000 km of jaarlijks.
    op.execute(
        "UPDATE tasks SET km_interval = 15000 "
        "WHERE name = 'Olie verversen / onderhoudsbeurt' "
        "AND vehicle_id IS NOT NULL AND km_interval IS NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_column("km_interval")

    with op.batch_alter_table("occurrences", schema=None) as batch_op:
        batch_op.drop_column("time_due_date")
        batch_op.drop_column("due_km")
