"""opmerkingen en bijlagen op een taak

Revision ID: 5963435ec76f
Revises: f7a9c1e36b42
Create Date: 2026-10-30

Twee nieuwe tabellen voor het taakdetail: opmerkingen (task_comment) en
bijlagen (task_attachment). Alleen toevoegingen; bestaande tabellen en
gegevens blijven ongemoeid. Beide gaan met hun taak mee (CASCADE); een
opmerking blijft staan als de auteur verdwijnt (SET NULL).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5963435ec76f"
down_revision: str | None = "f7a9c1e36b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_comment",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["author_id"], ["person.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_task_comment_task_id"), "task_comment", ["task_id"], unique=False
    )
    op.create_index(
        op.f("ix_task_comment_author_id"), "task_comment", ["author_id"], unique=False
    )
    op.create_table(
        "task_attachment",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("bestandsnaam", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("bestandsgrootte", sa.Integer(), nullable=True),
        sa.Column("pad", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_task_attachment_task_id"), "task_attachment", ["task_id"], unique=False
    )


def downgrade() -> None:
    # Verwijdert bewust de opmerkingen en bijlagen (de bestanden op schijf
    # niet): die bestonden voor deze migratie niet.
    op.drop_index(op.f("ix_task_attachment_task_id"), table_name="task_attachment")
    op.drop_table("task_attachment")
    op.drop_index(op.f("ix_task_comment_author_id"), table_name="task_comment")
    op.drop_index(op.f("ix_task_comment_task_id"), table_name="task_comment")
    op.drop_table("task_comment")
