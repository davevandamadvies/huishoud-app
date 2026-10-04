"""winterinterval

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-04 15:33:58.915058

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("winter_every", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("winter_months", sa.String(length=30), nullable=True)
        )

    # Startvulling: planten krijgen in de winter minder vaak water.
    for name, every in (
        ("Kamerplanten water geven", 14),
        ("Kruiden op de vensterbank water geven", 5),
    ):
        op.execute(
            sa.text(
                "UPDATE tasks SET winter_every = :every "
                "WHERE name = :name AND recurrence_type = 'interval' "
                "AND winter_every IS NULL"
            ).bindparams(every=every, name=name)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_column("winter_months")
        batch_op.drop_column("winter_every")
