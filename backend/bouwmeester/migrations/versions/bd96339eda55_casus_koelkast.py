"""de koelkast op de RegelReis: een casus die even stilligt

Revision ID: bd96339eda55
Revises: e5c1a7d93b20
Create Date: 2026-11-18

Alleen toevoegingen: drie lege kolommen op casus. In de koelkast is
koelkast_sinds gezet, met een reden en een verwachte datum om er weer uit
te komen. Bestaande casussen staan niet in de koelkast.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bd96339eda55"
down_revision: str | None = "e5c1a7d93b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "casus",
        sa.Column("koelkast_sinds", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("casus", sa.Column("koelkast_reden", sa.Text(), nullable=True))
    op.add_column(
        "casus", sa.Column("koelkast_verwacht_terug", sa.Date(), nullable=True)
    )


def downgrade() -> None:
    # Haalt bewust weg wat in de koelkast staat: het staat nergens anders.
    op.drop_column("casus", "koelkast_verwacht_terug")
    op.drop_column("casus", "koelkast_reden")
    op.drop_column("casus", "koelkast_sinds")
