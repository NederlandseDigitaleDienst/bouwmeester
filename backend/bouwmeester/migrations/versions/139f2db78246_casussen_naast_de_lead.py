"""casussen naast de lead, met soorten en inrichting per initiatief

Revision ID: 139f2db78246
Revises: 5963435ec76f
Create Date: 2026-10-30

Alleen toevoegingen; bestaande tabellen en gegevens blijven ongemoeid:

- casus: wat begint als een lead de trechter uit is. Eén casus per lead
  (uniek, RESTRICT: een lead met een casus is niet te verwijderen). Een
  casus ontstaat alleen door hem bewust te starten; deze migratie maakt
  er geen aan.
- casus_soort en casus_casus_soort: soorten casus per initiatief, als tags,
  met een uitleg, hoe ver we zo'n casus brengen en eisen bij start en eind.
- initiatief: drie lijsten (acceptatiecriteria, startvragen, casus_fases),
  standaard leeg; leeg betekent de standaard uit de code.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "139f2db78246"
down_revision: str | None = "5963435ec76f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "casus",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("lead_id", sa.UUID(), nullable=False),
        sa.Column("initiatief_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("organization", sa.String(), nullable=True),
        sa.Column(
            "fase",
            sa.String(),
            server_default="start",
            nullable=False,
            comment="fase-id uit initiatief.casus_fases (standaard start..besluiten)",
        ),
        sa.Column("startvoorwaarden", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("eind_eisen", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("started_by_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["initiatief_id"], ["initiatief.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["lead_id"], ["lead.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["started_by_id"], ["person.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_casus_lead_id"), "casus", ["lead_id"], unique=True)
    op.create_index(
        op.f("ix_casus_initiatief_id"), "casus", ["initiatief_id"], unique=False
    )
    op.create_index(
        op.f("ix_casus_started_by_id"), "casus", ["started_by_id"], unique=False
    )

    op.create_table(
        "casus_soort",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("initiatief_id", sa.UUID(), nullable=False),
        sa.Column("naam", sa.String(length=100), nullable=False),
        sa.Column("uitleg", sa.Text(), nullable=True),
        sa.Column("kleur", sa.String(), server_default="neutral", nullable=False),
        sa.Column("hoe_ver", sa.Text(), nullable=True),
        sa.Column("start_eisen", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("eind_eisen", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["initiatief_id"], ["initiatief.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "initiatief_id", "naam", name="uq_casus_soort_initiatief_naam"
        ),
    )
    op.create_index(
        op.f("ix_casus_soort_initiatief_id"),
        "casus_soort",
        ["initiatief_id"],
        unique=False,
    )
    op.create_index(
        "ix_casus_soort_initiatief_sort",
        "casus_soort",
        ["initiatief_id", "sort_order"],
        unique=False,
    )

    op.create_table(
        "casus_casus_soort",
        sa.Column("casus_id", sa.UUID(), nullable=False),
        sa.Column("casus_soort_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["casus_id"], ["casus.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["casus_soort_id"], ["casus_soort.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("casus_id", "casus_soort_id"),
    )
    op.create_index(
        op.f("ix_casus_casus_soort_casus_id"),
        "casus_casus_soort",
        ["casus_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_casus_casus_soort_casus_soort_id"),
        "casus_casus_soort",
        ["casus_soort_id"],
        unique=False,
    )

    for kolom in ("acceptatiecriteria", "startvragen", "casus_fases"):
        op.add_column(
            "initiatief",
            sa.Column(kolom, sa.JSON(), server_default="[]", nullable=False),
        )


def downgrade() -> None:
    # Verwijdert bewust de casussen, hun soorten en de inrichting per
    # initiatief: die bestonden voor deze migratie niet.
    for kolom in ("casus_fases", "startvragen", "acceptatiecriteria"):
        op.drop_column("initiatief", kolom)
    op.drop_table("casus_casus_soort")
    op.drop_table("casus_soort")
    op.drop_table("casus")
