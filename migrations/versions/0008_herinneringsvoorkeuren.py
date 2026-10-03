"""herinneringsvoorkeuren

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-03 19:51:44.319687

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "reminder_muted_categories",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_reminder_muted_categories_category_id_categories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_reminder_muted_categories_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "category_id", name=op.f("pk_reminder_muted_categories")
        ),
    )
    op.create_table(
        "reminder_preferences",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("update_enabled", sa.Boolean(), nullable=False),
        sa.Column("update_days", sa.String(length=7), nullable=False),
        sa.Column("update_times", sa.String(length=17), nullable=False),
        sa.Column("lookahead_days", sa.Integer(), nullable=False),
        sa.Column("only_mine", sa.Boolean(), nullable=False),
        sa.Column("task_on_day", sa.Boolean(), nullable=False),
        sa.Column("task_days_before", sa.Integer(), nullable=False),
        sa.Column("task_late_daily", sa.Boolean(), nullable=False),
        sa.Column("quiet_enabled", sa.Boolean(), nullable=False),
        sa.Column("quiet_start", sa.String(length=5), nullable=False),
        sa.Column("quiet_end", sa.String(length=5), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_reminder_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_reminder_preferences")),
    )
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("first_reminder_days", sa.Integer(), nullable=True)
        )

    # Startvulling: de APK krijgt een eerste herinnering vanaf 60 dagen vooraf.
    op.execute(
        "UPDATE tasks SET first_reminder_days = 60 "
        "WHERE name = 'APK' AND recurrence_type = 'fixed_date' "
        "AND first_reminder_days IS NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_column("first_reminder_days")

    op.drop_table("reminder_preferences")
    op.drop_table("reminder_muted_categories")
