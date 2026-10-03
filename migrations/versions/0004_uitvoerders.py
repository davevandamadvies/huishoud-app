"""uitvoerders

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-03 16:50:31.611276

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "occurrence_performers",
        sa.Column("occurrence_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["occurrence_id"],
            ["occurrences.id"],
            name=op.f("fk_occurrence_performers_occurrence_id_occurrences"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_occurrence_performers_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "occurrence_id", "user_id", name=op.f("pk_occurrence_performers")
        ),
    )
    with op.batch_alter_table("occurrence_performers", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_occurrence_performers_user_id"), ["user_id"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("occurrence_performers", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_occurrence_performers_user_id"))

    op.drop_table("occurrence_performers")
