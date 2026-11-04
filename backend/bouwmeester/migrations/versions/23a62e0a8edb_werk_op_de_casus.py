"""werk op de casus: onderzoeksvragen en taken in een casus

Revision ID: 23a62e0a8edb
Revises: 139f2db78246
Create Date: 2026-10-30

Alleen toevoegingen; bestaande taken en gegevens blijven zoals ze zijn:

- issue: een onderzoeksvraag (of ander issue) op een casus, met een
  eigenaar, een status en de afgevinkte Definition of Done.
- task: twee nieuwe kolommen (casus_id, issue_id), standaard leeg. node_id
  mag leeg zijn, maar alleen voor een taak in een casus: ck_task_anchor
  eist een node of een casus. Elke bestaande taak heeft een node en
  voldoet dus; geen bestaande rij verandert.
- initiatief.dod_items: de eigen Definition of Done, standaard leeg (dan
  geldt de standaardlijst uit de code).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "23a62e0a8edb"
down_revision: str | None = "139f2db78246"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "issue",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("casus_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("toelichting", sa.Text(), nullable=True),
        sa.Column(
            "is_onderzoeksvraag", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column("assignee_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.String(),
            server_default="open",
            nullable=False,
            comment="open|in_progress|done",
        ),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("dod_checked", sa.JSON(), server_default="[]", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assignee_id"], ["person.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["casus_id"], ["casus.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_issue_casus_id"), "issue", ["casus_id"], unique=False)
    op.create_index(
        op.f("ix_issue_assignee_id"), "issue", ["assignee_id"], unique=False
    )

    op.add_column("task", sa.Column("casus_id", sa.UUID(), nullable=True))
    op.add_column("task", sa.Column("issue_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_task_casus_id"), "task", ["casus_id"], unique=False)
    op.create_index(op.f("ix_task_issue_id"), "task", ["issue_id"], unique=False)
    op.create_foreign_key(
        "fk_task_casus", "task", "casus", ["casus_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_task_issue", "task", "issue", ["issue_id"], ["id"], ondelete="SET NULL"
    )
    op.alter_column("task", "node_id", existing_type=sa.UUID(), nullable=True)
    op.create_check_constraint(
        "ck_task_anchor", "task", "node_id IS NOT NULL OR casus_id IS NOT NULL"
    )

    op.add_column(
        "initiatief",
        sa.Column("dod_items", sa.JSON(), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    # Taken in een casus hebben geen node; die gaan bewust mee weg, net als
    # de onderzoeksvragen. Taken aan een node blijven staan.
    op.drop_column("initiatief", "dod_items")
    op.execute("DELETE FROM task WHERE node_id IS NULL")
    op.drop_constraint("ck_task_anchor", "task", type_="check")
    op.alter_column("task", "node_id", existing_type=sa.UUID(), nullable=False)
    op.drop_constraint("fk_task_issue", "task", type_="foreignkey")
    op.drop_constraint("fk_task_casus", "task", type_="foreignkey")
    op.drop_index(op.f("ix_task_issue_id"), table_name="task")
    op.drop_index(op.f("ix_task_casus_id"), table_name="task")
    op.drop_column("task", "issue_id")
    op.drop_column("task", "casus_id")
    op.drop_table("issue")
