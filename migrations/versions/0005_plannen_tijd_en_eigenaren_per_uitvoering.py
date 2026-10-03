"""plannen: tijd en eigenaren per uitvoering

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03 17:23:49.939696

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "occurrence_owners",
        sa.Column("occurrence_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["occurrence_id"],
            ["occurrences.id"],
            name=op.f("fk_occurrence_owners_occurrence_id_occurrences"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_occurrence_owners_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "occurrence_id", "user_id", name=op.f("pk_occurrence_owners")
        ),
    )
    with op.batch_alter_table("occurrence_owners", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_occurrence_owners_user_id"), ["user_id"], unique=False
        )

    with op.batch_alter_table("occurrences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("planned_time", sa.Time(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("occurrences", schema=None) as batch_op:
        batch_op.drop_column("planned_time")

    with op.batch_alter_table("occurrence_owners", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_occurrence_owners_user_id"))

    op.drop_table("occurrence_owners")
