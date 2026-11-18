"""regelritme per initiatief: overleggen, open punten en wensen

Revision ID: 4519258668a9
Revises: e5c1a7d93b20
Create Date: 2026-11-18

Alleen toevoegingen, drie lijsten op initiatief, standaard leeg: de vaste
overleggen van het team, de open punten en de wensen voor Bouwmeester.
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
    op.add_column(
        "initiatief",
        sa.Column("open_punten", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column(
        "initiatief",
        sa.Column("wensen", sa.JSON(), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    # Haalt bewust weg wat er is vastgelegd: het staat nergens anders.
    op.drop_column("initiatief", "wensen")
    op.drop_column("initiatief", "open_punten")
    op.drop_column("initiatief", "overleggen")
