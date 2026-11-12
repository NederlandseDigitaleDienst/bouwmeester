"""stemmingsuitslag van een debat

Revision ID: d8f3b6a20e57
Revises: c4e8a2d61f93
Create Date: 2026-11-12

Een kolom op debat_sessie waarin staat welke dossiers bij het debat horen
en, per dag met stemmingen, welk bericht de uitslag in het kanaal is.
Alleen een toevoeging; leeg voor elk debat dat nog niet gevolgd is.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d8f3b6a20e57"
down_revision: str | None = "c4e8a2d61f93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "debat_sessie",
        sa.Column("stemmingen", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("debat_sessie", "stemmingen")
