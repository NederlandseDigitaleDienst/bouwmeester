"""naar buiten: beantwoorde vragen, onderzoeksverslag en afgeronde casussen

Revision ID: 48e3ad641f05
Revises: 0162015de145
Create Date: 2026-11-19

Alleen toevoegingen:
- issue krijgt een publieke vraag en antwoord en een moment van vrijgeven;
  initiatief_update_vraag koppelt vragen aan een update.
- onderzoeksverslag: één bestand per vraag, met een eigen akkoord voor buiten.
- casus krijgt lessen (binnen), een publieke tekst en een moment van
  vrijgeven; initiatief_update_casus koppelt casussen aan een update.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "48e3ad641f05"
down_revision: str | None = "0162015de145"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _koppeltabel(naam: str, kolom: str, doel: str) -> None:
    op.create_table(
        naam,
        sa.Column("update_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(kolom, postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["update_id"], ["initiatief_update.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint([kolom], [f"{doel}.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("update_id", kolom),
    )
    op.create_index(op.f(f"ix_{naam}_{kolom}"), naam, [kolom], unique=False)


def upgrade() -> None:
    # Beantwoorde vragen naar buiten.
    op.add_column("issue", sa.Column("public_title", sa.Text(), nullable=True))
    op.add_column("issue", sa.Column("public_answer", sa.Text(), nullable=True))
    op.add_column(
        "issue",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_issue_published_at"), "issue", ["published_at"], unique=False
    )
    _koppeltabel("initiatief_update_vraag", "issue_id", "issue")

    # Het onderzoeksverslag bij een vraag.
    op.create_table(
        "onderzoeksverslag",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bestandsnaam", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("bestandsgrootte", sa.Integer(), nullable=False),
        sa.Column("pad", sa.String(), nullable=False),
        sa.Column("uploaded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("openbaar_op", sa.DateTime(timezone=True), nullable=True),
        sa.Column("openbaar_door_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["issue_id"], ["issue.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["person.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["openbaar_door_id"], ["person.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issue_id"),
    )
    op.create_index(
        op.f("ix_onderzoeksverslag_uploaded_by_id"),
        "onderzoeksverslag",
        ["uploaded_by_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_onderzoeksverslag_openbaar_door_id"),
        "onderzoeksverslag",
        ["openbaar_door_id"],
        unique=False,
    )

    # Afgeronde casussen en lessen naar buiten.
    op.add_column("casus", sa.Column("lessen", sa.Text(), nullable=True))
    op.add_column("casus", sa.Column("public_title", sa.Text(), nullable=True))
    op.add_column("casus", sa.Column("public_resultaat", sa.Text(), nullable=True))
    op.add_column("casus", sa.Column("public_lessen", sa.Text(), nullable=True))
    op.add_column(
        "casus",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_casus_published_at"), "casus", ["published_at"], unique=False
    )
    _koppeltabel("initiatief_update_casus", "casus_id", "casus")


def downgrade() -> None:
    op.drop_index(
        op.f("ix_initiatief_update_casus_casus_id"),
        table_name="initiatief_update_casus",
    )
    op.drop_table("initiatief_update_casus")
    op.drop_index(op.f("ix_casus_published_at"), table_name="casus")
    op.drop_column("casus", "published_at")
    op.drop_column("casus", "public_lessen")
    op.drop_column("casus", "public_resultaat")
    op.drop_column("casus", "public_title")
    op.drop_column("casus", "lessen")

    op.drop_index(
        op.f("ix_onderzoeksverslag_openbaar_door_id"), table_name="onderzoeksverslag"
    )
    op.drop_index(
        op.f("ix_onderzoeksverslag_uploaded_by_id"), table_name="onderzoeksverslag"
    )
    op.drop_table("onderzoeksverslag")

    op.drop_index(
        op.f("ix_initiatief_update_vraag_issue_id"),
        table_name="initiatief_update_vraag",
    )
    op.drop_table("initiatief_update_vraag")
    op.drop_index(op.f("ix_issue_published_at"), table_name="issue")
    op.drop_column("issue", "published_at")
    op.drop_column("issue", "public_answer")
    op.drop_column("issue", "public_title")
