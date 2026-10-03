"""taken en uitvoeringen

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03 16:45:09.674397

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column(
            "recurrence_type",
            sa.Enum(
                "interval",
                "fixed_date",
                "once",
                name="recurrence_type",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("interval_every", sa.Integer(), nullable=True),
        sa.Column(
            "interval_unit",
            sa.Enum(
                "days",
                "weeks",
                "months",
                name="interval_unit",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("default_points", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "interval_unit IN ('days', 'weeks', 'months')",
            name=op.f("ck_tasks_interval_unit"),
        ),
        sa.CheckConstraint(
            "recurrence_type = 'once' OR interval_every >= 1",
            name=op.f("ck_tasks_interval"),
        ),
        sa.CheckConstraint(
            "recurrence_type IN ('interval', 'fixed_date', 'once')",
            name=op.f("ck_tasks_recurrence_type"),
        ),
        sa.CheckConstraint(
            "default_points IS NULL OR default_points BETWEEN 1 AND 100",
            name=op.f("ck_tasks_points"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_tasks_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_tasks_owner_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_tasks_category_id"), ["category_id"], unique=False
        )

    op.create_table(
        "occurrences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "planned",
                "done",
                "skipped",
                name="status",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("planned_date", sa.Date(), nullable=True),
        sa.Column("points", sa.Integer(), nullable=True),
        sa.Column("completed_on", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("cost_cents", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('open', 'planned', 'done', 'skipped')",
            name=op.f("ck_occurrences_status"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_occurrences_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_occurrences")),
    )
    with op.batch_alter_table("occurrences", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_occurrences_due_date"), ["due_date"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_occurrences_task_id"), ["task_id"], unique=False
        )
        batch_op.create_index(
            "uq_occurrences_one_pending_per_task",
            ["task_id"],
            unique=True,
            sqlite_where=sa.text("status IN ('open', 'planned')"),
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("occurrences", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_occurrences_one_pending_per_task",
            sqlite_where=sa.text("status IN ('open', 'planned')"),
        )
        batch_op.drop_index(batch_op.f("ix_occurrences_task_id"))
        batch_op.drop_index(batch_op.f("ix_occurrences_due_date"))

    op.drop_table("occurrences")
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_tasks_category_id"))

    op.drop_table("tasks")
