"""voertuigen en kilometerstand

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-04 15:09:44.698605

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehicles")),
        sa.UniqueConstraint("name", name=op.f("uq_vehicles_name")),
    )
    op.create_table(
        "odometer_readings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("read_on", sa.Date(), nullable=False),
        sa.Column("km", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_odometer_readings_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name=op.f("fk_odometer_readings_vehicle_id_vehicles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_odometer_readings")),
    )
    with op.batch_alter_table("odometer_readings", schema=None) as batch_op:
        batch_op.create_index(
            "ix_odometer_readings_vehicle_day", ["vehicle_id", "read_on"], unique=False
        )

    with op.batch_alter_table("occurrences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("km", sa.Integer(), nullable=True))

    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("vehicle_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_tasks_vehicle_id_vehicles"),
            "vehicles",
            ["vehicle_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Startvulling: taken in de categorie "Auto" horen bij het voertuig "Auto".
    connection = op.get_bind()
    has_auto_tasks = connection.execute(
        sa.text(
            "SELECT 1 FROM tasks JOIN categories ON categories.id = tasks.category_id "
            "WHERE categories.name = 'Auto' LIMIT 1"
        )
    ).first()
    if has_auto_tasks:
        connection.execute(
            sa.text(
                "INSERT INTO vehicles (name, created_at) "
                "SELECT 'Auto', CURRENT_TIMESTAMP "
                "WHERE NOT EXISTS (SELECT 1 FROM vehicles WHERE name = 'Auto')"
            )
        )
        connection.execute(
            sa.text(
                "UPDATE tasks SET vehicle_id = "
                "(SELECT id FROM vehicles WHERE name = 'Auto') "
                "WHERE vehicle_id IS NULL AND category_id IN "
                "(SELECT id FROM categories WHERE name = 'Auto')"
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_tasks_vehicle_id_vehicles"), type_="foreignkey"
        )
        batch_op.drop_column("vehicle_id")

    with op.batch_alter_table("occurrences", schema=None) as batch_op:
        batch_op.drop_column("km")

    with op.batch_alter_table("odometer_readings", schema=None) as batch_op:
        batch_op.drop_index("ix_odometer_readings_vehicle_day")

    op.drop_table("odometer_readings")
    op.drop_table("vehicles")
