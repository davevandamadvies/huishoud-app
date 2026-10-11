"""categorie symbool

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-11 17:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Startcategorieën (zie 0002) krijgen een passend symbool, de rest "tag".
START_ICONS = {
    "Schoonmaak": "sparkle",
    "Huis & installaties": "house",
    "Auto": "car",
    "Tuin": "leaf",
    "Planten": "plant",
    "Techniek": "router",
}


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("categories", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "icon", sa.String(length=20), nullable=False, server_default="tag"
            )
        )
    categories = sa.table("categories", sa.column("name"), sa.column("icon"))
    for name, icon in START_ICONS.items():
        op.execute(
            categories.update().where(categories.c.name == name).values(icon=icon)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("categories", schema=None) as batch_op:
        batch_op.drop_column("icon")
