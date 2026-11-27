"""de koelkast op de RegelReis: een casus die even stilligt

Revision ID: bd96339eda55
Revises: 4519258668a9
Create Date: 2026-11-18

Alleen toevoegingen: drie lege kolommen op casus en een check die ze bij
elkaar houdt. In de koelkast is koelkast_sinds gezet, met een reden en een
verwachte datum om er weer uit te komen; erbuiten zijn ze alle drie leeg.
Bestaande casussen staan niet in de koelkast en voldoen dus meteen.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bd96339eda55"
down_revision: str | None = "4519258668a9"
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
    # Dezelfde tekst als KOELKAST_CHECK in models/casus.py, hier vastgelegd
    # zoals hij bij deze revisie hoort.
    op.create_check_constraint(
        "ck_casus_koelkast",
        "casus",
        "(koelkast_sinds IS NULL AND koelkast_reden IS NULL"
        " AND koelkast_verwacht_terug IS NULL)"
        " OR (koelkast_sinds IS NOT NULL AND koelkast_reden IS NOT NULL"
        " AND btrim(koelkast_reden) <> '' AND koelkast_verwacht_terug IS NOT NULL)",
    )


def downgrade() -> None:
    # Haalt bewust weg wat in de koelkast staat: het staat nergens anders.
    op.drop_constraint("ck_casus_koelkast", "casus", type_="check")
    op.drop_column("casus", "koelkast_verwacht_terug")
    op.drop_column("casus", "koelkast_reden")
    op.drop_column("casus", "koelkast_sinds")
