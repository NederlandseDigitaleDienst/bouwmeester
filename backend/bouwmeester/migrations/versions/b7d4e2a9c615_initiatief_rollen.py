"""initiatief: rollen in een cirkel, met interesse, raakvlakken en focus

Revision ID: b7d4e2a9c615
Revises: 0162015de145
Create Date: 2026-11-27

Rollen per initiatief, losjes naar Holacracy. Een initiatief heeft één
ankercirkel (parent_id leeg); subcirkels kunnen er later in. Een rol heeft
een status (concept, open, belegd), hooguit één vervuller en een ronde voor
de interesse bij het toewijzen. Raakvlakken koppelen twee rollen. Per persoon
in een initiatief een eigen focus. Per initiatief aan of uit met
rollen_enabled.

Alleen toevoegingen: een kolom met standaard false en vijf nieuwe tabellen.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b7d4e2a9c615"
down_revision: str | None = "0162015de145"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def _id() -> sa.Column:
    return sa.Column(
        "id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True
    )


def _created() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def upgrade() -> None:
    op.add_column(
        "initiatief",
        sa.Column(
            "rollen_enabled", sa.Boolean(), server_default="false", nullable=False
        ),
    )

    op.create_table(
        "initiatief_cirkel",
        _id(),
        sa.Column(
            "initiatief_id",
            UUID,
            sa.ForeignKey("initiatief.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_id",
            UUID,
            sa.ForeignKey("initiatief_cirkel.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("naam", sa.String(150), nullable=False),
        sa.Column("doel", sa.Text(), nullable=True),
        sa.Column("focus", sa.JSON(), server_default="[]", nullable=False),
        _created(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_initiatief_cirkel_initiatief_id", "initiatief_cirkel", ["initiatief_id"]
    )
    op.create_index(
        "ix_initiatief_cirkel_parent_id", "initiatief_cirkel", ["parent_id"]
    )
    op.create_index(
        "uq_initiatief_cirkel_anker",
        "initiatief_cirkel",
        ["initiatief_id"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NULL"),
    )

    op.create_table(
        "initiatief_rol",
        _id(),
        sa.Column(
            "initiatief_id",
            UUID,
            sa.ForeignKey("initiatief.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cirkel_id",
            UUID,
            sa.ForeignKey("initiatief_cirkel.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("naam", sa.String(150), nullable=False),
        sa.Column("status", sa.String(16), server_default="concept", nullable=False),
        sa.Column("doel", sa.Text(), nullable=True),
        sa.Column("aanspreekbaar_op", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("domein", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("toelichting", sa.Text(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column(
            "vervuller_id",
            UUID,
            sa.ForeignKey("person.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ronde", sa.Integer(), server_default="1", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        _created(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('concept', 'open', 'belegd')",
            name="ck_initiatief_rol_status",
        ),
    )
    for kolom in ("initiatief_id", "cirkel_id", "vervuller_id"):
        op.create_index(f"ix_initiatief_rol_{kolom}", "initiatief_rol", [kolom])
    # Hoofdletters tellen niet: "Case" en "CASE" zijn dezelfde rol.
    op.create_index(
        "uq_initiatief_rol_naam",
        "initiatief_rol",
        ["initiatief_id", sa.text("lower(naam)")],
        unique=True,
    )

    op.create_table(
        "initiatief_rol_interesse",
        _id(),
        sa.Column(
            "rol_id",
            UUID,
            sa.ForeignKey("initiatief_rol.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "person_id",
            UUID,
            sa.ForeignKey("person.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ronde", sa.Integer(), nullable=False),
        sa.Column("invulling", sa.Text(), nullable=True),
        sa.Column(
            "vastgelegd_door_id",
            UUID,
            sa.ForeignKey("person.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _created(),
        sa.UniqueConstraint(
            "rol_id", "person_id", "ronde", name="uq_initiatief_rol_interesse"
        ),
    )
    for kolom in ("rol_id", "person_id", "vastgelegd_door_id"):
        op.create_index(
            f"ix_initiatief_rol_interesse_{kolom}", "initiatief_rol_interesse", [kolom]
        )

    op.create_table(
        "initiatief_rol_raakvlak",
        _id(),
        sa.Column(
            "rol_a_id",
            UUID,
            sa.ForeignKey("initiatief_rol.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "rol_b_id",
            UUID,
            sa.ForeignKey("initiatief_rol.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("omschrijving", sa.Text(), nullable=True),
        _created(),
        sa.UniqueConstraint("rol_a_id", "rol_b_id", name="uq_initiatief_rol_raakvlak"),
        sa.CheckConstraint(
            "rol_a_id < rol_b_id", name="ck_initiatief_rol_raakvlak_paar"
        ),
    )
    for kolom in ("rol_a_id", "rol_b_id"):
        op.create_index(
            f"ix_initiatief_rol_raakvlak_{kolom}", "initiatief_rol_raakvlak", [kolom]
        )

    op.create_table(
        "initiatief_persoon_focus",
        sa.Column(
            "initiatief_id",
            UUID,
            sa.ForeignKey("initiatief.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "person_id",
            UUID,
            sa.ForeignKey("person.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("focus", sa.JSON(), server_default="[]", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_initiatief_persoon_focus_person_id",
        "initiatief_persoon_focus",
        ["person_id"],
    )


def downgrade() -> None:
    # De indexen gaan mee met hun tabel.
    op.drop_table("initiatief_persoon_focus")
    op.drop_table("initiatief_rol_raakvlak")
    op.drop_table("initiatief_rol_interesse")
    op.drop_table("initiatief_rol")
    op.drop_table("initiatief_cirkel")
    op.drop_column("initiatief", "rollen_enabled")
