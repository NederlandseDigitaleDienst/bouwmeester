"""casus: Mattermost-kanaal met voortgangsberichten

Revision ID: f3a8c5e1d927
Revises: 23a62e0a8edb
Create Date: 2026-11-03

Een kanaal kan ook aan een casus hangen (scope_type casus). Bouwmeester zet
daar de voortgang neer: fase, nieuwe en afgeronde onderzoeksvragen. De
schakelaar daarvoor staat per kanaal, in casus_updates_enabled.

Start uit een lead een casus, dan verhuist het kanaal van de lead mee. Voor
casussen die al bestaan doet deze migratie dat in één keer, zodat er geen
kanaal meer notities zet op een lead die alleen-lezen is. De voortgang staat
in zo'n kanaal uit: dat zet het team zelf aan, en alleen in een privékanaal.

Elk voortgangsbericht komt ook in casus_kanaalbericht, met of zonder kanaal,
zodat bij de casus te zien is wat er in het kanaal staat of zou staan.

Verdwijnt een casus, dan gaat alleen een kanaal terug naar de lead dat er
vandaan kwam (van_de_lead); wat het team zelf aan de casus hing, wordt
ontkoppeld.

Alleen toevoegingen: twee kolommen met standaard false, een nieuwe tabel,
en het verhuizen van koppelingen van een lead met casus.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f3a8c5e1d927"
down_revision: str | None = "23a62e0a8edb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mattermost_channel_link",
        sa.Column(
            "casus_updates_enabled",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment=(
                "Post de voortgang van de casus in dit kanaal: fase en "
                "onderzoeksvragen. Alleen bij een privékanaal aan een casus."
            ),
        ),
    )
    op.add_column(
        "mattermost_channel_link",
        sa.Column(
            "van_de_lead",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment=(
                "Kwam bij de casusstart mee van de lead. Alleen zo'n kanaal gaat "
                "terug naar de lead als de casus verdwijnt; de rest wordt ontkoppeld."
            ),
        ),
    )
    op.execute(
        """
        UPDATE mattermost_channel_link AS l
        SET scope_type = 'casus', scope_id = c.id,
            casus_updates_enabled = false, van_de_lead = true
        FROM casus AS c
        WHERE l.scope_type = 'lead' AND l.scope_id = c.lead_id
        """
    )

    op.create_table(
        "casus_kanaalbericht",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "casus_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("casus.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tekst",
            sa.Text(),
            nullable=False,
            comment="Het bericht in Mattermost-markdown.",
        ),
        sa.Column(
            "kanalen",
            postgresql.JSON(),
            nullable=False,
            comment=(
                "De kanalen met voortgang aan op het moment van het bericht: "
                "[{id, naam}]. Leeg als er geen was."
            ),
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            comment="geen_kanaal|wacht|verstuurd|mislukt|uit",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_casus_kanaalbericht_casus_id", "casus_kanaalbericht", ["casus_id"]
    )


def downgrade() -> None:
    # De bewaarde berichten gaan bewust mee weg; in Mattermost blijven ze staan.
    op.drop_index("ix_casus_kanaalbericht_casus_id", table_name="casus_kanaalbericht")
    op.drop_table("casus_kanaalbericht")
    # Kanalen die van de lead kwamen, terug naar die lead. Wat het team zelf
    # aan een casus hing, en koppelingen aan een casus die niet meer bestaat,
    # gaan bewust weg: zonder scope casus horen ze nergens bij.
    op.execute(
        """
        UPDATE mattermost_channel_link AS l
        SET scope_type = 'lead', scope_id = c.lead_id
        FROM casus AS c
        WHERE l.scope_type = 'casus' AND l.scope_id = c.id AND l.van_de_lead
        """
    )
    op.execute("DELETE FROM mattermost_channel_link WHERE scope_type = 'casus'")
    op.drop_column("mattermost_channel_link", "van_de_lead")
    op.drop_column("mattermost_channel_link", "casus_updates_enabled")
