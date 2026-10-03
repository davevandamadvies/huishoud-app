"""categorieen

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03 16:41:00.318776

"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    categories = op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("color", sa.String(length=20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("name", name=op.f("uq_categories_name")),
    )
    # Startcategorieën (kleuren uit de UI-mockup, zie app/palette.py)
    now = datetime.now(UTC).replace(tzinfo=None)
    op.bulk_insert(
        categories,
        [
            {"name": name, "color": color, "position": i, "created_at": now}
            for i, (name, color) in enumerate(
                [
                    ("Schoonmaak", "blue"),
                    ("Huis & installaties", "orange"),
                    ("Auto", "purple"),
                    ("Tuin", "green"),
                    ("Planten", "teal"),
                    ("Techniek", "slate"),
                ]
            )
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("categories")
