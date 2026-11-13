"""debatkanaal gearchiveerd

Revision ID: e5c1a7d93b20
Revises: d8f3b6a20e57
Create Date: 2026-11-12

Een kolom op debat_sessie met het moment waarop de bot het kanaal heeft
gearchiveerd. Daarna kijkt de bot er niet meer naar, zodat een kanaal dat
een beheerder terugzet ook teruggezet blijft. Alleen een toevoeging.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5c1a7d93b20"
down_revision: str | None = "d8f3b6a20e57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "debat_sessie",
        sa.Column("kanaal_gearchiveerd_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("debat_sessie", "kanaal_gearchiveerd_at")
