"""regelritme per initiatief: de vaste overleggen van het team

Revision ID: 4519258668a9
Revises: e5c1a7d93b20
Create Date: 2026-11-18

Alleen een toevoeging: initiatief.overleggen, een lijst, standaard leeg.
Bestaande initiatieven en gegevens blijven ongemoeid.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4519258668a9"
down_revision: str | None = "e5c1a7d93b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "initiatief",
        sa.Column("overleggen", sa.JSON(), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    # Haalt bewust de vastgelegde overleggen weg: ze staan nergens anders.
    op.drop_column("initiatief", "overleggen")
