"""besluiten van een procedurevergadering

Revision ID: c4e8a2d61f93
Revises: 139f2db78246
Create Date: 2026-11-04

Een kolom op debat_sessie waarin staat hoe ver het overzicht van de
besluiten van een procedurevergadering is: welk bericht het is, hoeveel
tekst er gelezen is en of het eindoverzicht er staat. Alleen een
toevoeging; leeg voor elk ander debat.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4e8a2d61f93"
down_revision: str | None = "139f2db78246"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "debat_sessie",
        sa.Column("besluiten", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("debat_sessie", "besluiten")
