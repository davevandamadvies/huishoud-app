"""herinneringslog

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-03 19:56:47.491510

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "reminder_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=40), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("slot", sa.String(length=5), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_reminder_log_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reminder_log")),
        sa.UniqueConstraint(
            "user_id",
            "kind",
            "subject",
            "day",
            "slot",
            name=op.f("uq_reminder_log_user_id"),
        ),
    )
    with op.batch_alter_table("reminder_log", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_reminder_log_user_id"), ["user_id"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("reminder_log", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_reminder_log_user_id"))

    op.drop_table("reminder_log")
