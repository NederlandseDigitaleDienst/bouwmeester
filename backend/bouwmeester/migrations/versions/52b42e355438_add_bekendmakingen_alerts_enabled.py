"""Add bekendmakingen_alerts_enabled

Officiële bekendmakingen (Staatscourant, Staatsblad, Tractatenblad) als
derde bron naast kamerstukken en vakpers. Een eigen vinkje per kanaal,
standaard uit: wie kamerstukken of nieuws volgt heeft niet vanzelf om
vastgestelde regelingen en vergunningen gevraagd.

Revision ID: 52b42e355438
Revises: f7a9c1e36b42
Create Date: 2026-10-17

"""

import sqlalchemy as sa
from alembic import op

revision: str = "52b42e355438"
down_revision: str | None = "f7a9c1e36b42"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "mattermost_channel_link",
        sa.Column(
            "bekendmakingen_alerts_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment=(
                "Stuur officiële bekendmakingen (regelgeving, beleidsregels, "
                "besluiten en kennisgevingen uit de Staatscourant, het "
                "Staatsblad en het Tractatenblad) die op een zoekterm matchen "
                "naar dit kanaal. "
                "Apart van kamerstukken en nieuws: een vastgestelde regeling "
                "is een ander gesprek dan een voorstel of een artikel."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("mattermost_channel_link", "bekendmakingen_alerts_enabled")
