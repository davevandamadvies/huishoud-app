"""stille uren weg

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-04 16:41:10.926794

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("reminder_preferences", schema=None) as batch_op:
        batch_op.drop_column("quiet_enabled")
        batch_op.drop_column("quiet_start")
        batch_op.drop_column("quiet_end")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("reminder_preferences", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "quiet_end",
                sa.VARCHAR(length=5),
                nullable=False,
                server_default="07:00",
            )
        )
        batch_op.add_column(
            sa.Column(
                "quiet_start",
                sa.VARCHAR(length=5),
                nullable=False,
                server_default="22:00",
            )
        )
        batch_op.add_column(
            sa.Column(
                "quiet_enabled", sa.BOOLEAN(), nullable=False, server_default=sa.true()
            )
        )
