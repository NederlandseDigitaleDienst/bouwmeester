"""onderzoeksvraag zonder casus, met een intern antwoord

Revision ID: 0162015de145
Revises: bd96339eda55
Create Date: 2026-11-18

Een onderzoeksvraag hoort altijd bij een initiatief en hoeft niet bij een
casus te horen. issue krijgt initiatief_id (gevuld uit de casus) en casus_id
mag leeg; ck_issue_plek eist een van de twee. Een taak mag dan ook alleen aan
een vraag hangen: ck_task_anchor telt issue_id mee. Daarnaast krijgt een
vraag een interne versie van het antwoord (issue.antwoord).

Oude subtaken onder een taak van een vraag (van voor de regel dat een taak
in een casus geen subtaken heeft) krijgen het issue_id van hun hoofdtaak.
Haal je de vraag uit de casus, dan blijft zo'n subtaak verankerd en volgt
ze het initiatief, net als de hoofdtaak (IssueRepository.move_to_casus doet
hetzelfde bij het verhuizen).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0162015de145"
down_revision: str | None = "bd96339eda55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "issue",
        sa.Column("initiatief_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        "UPDATE issue SET initiatief_id = casus.initiatief_id "
        "FROM casus WHERE casus.id = issue.casus_id"
    )
    # Een casus zonder initiatief kan bestaan; zijn vragen hebben dan geen
    # initiatief. Die blijven bij hun casus.
    op.create_foreign_key(
        "fk_issue_initiatief",
        "issue",
        "initiatief",
        ["initiatief_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_issue_initiatief_id", "issue", ["initiatief_id"])
    op.alter_column("issue", "casus_id", existing_type=postgresql.UUID(), nullable=True)
    op.create_check_constraint(
        "ck_issue_plek", "issue", "casus_id IS NOT NULL OR initiatief_id IS NOT NULL"
    )
    op.drop_constraint("ck_task_anchor", "task", type_="check")
    op.create_check_constraint(
        "ck_task_anchor",
        "task",
        "node_id IS NOT NULL OR casus_id IS NOT NULL OR issue_id IS NOT NULL",
    )
    # Subtaken (ook dieper) onder een taak van een vraag krijgen het issue_id
    # van de vraag. Een subtaak aan een node houdt alleen de node.
    op.execute(
        """
        WITH RECURSIVE onder (id, issue_id) AS (
            SELECT t.id, p.issue_id
            FROM task t JOIN task p ON p.id = t.parent_id
            WHERE t.issue_id IS NULL AND p.issue_id IS NOT NULL
            UNION
            SELECT t.id, onder.issue_id
            FROM task t JOIN onder ON t.parent_id = onder.id
            WHERE t.issue_id IS NULL
        )
        UPDATE task SET issue_id = onder.issue_id
        FROM onder
        WHERE task.id = onder.id AND task.node_id IS NULL
        """
    )
    op.add_column("issue", sa.Column("antwoord", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("issue", "antwoord")
    # Vragen zonder casus kunnen niet terug; de taken die alleen aan zo'n
    # vraag hangen evenmin.
    op.execute("DELETE FROM task WHERE node_id IS NULL AND casus_id IS NULL")
    op.execute("DELETE FROM issue WHERE casus_id IS NULL")
    # Subtaken in een casus hangen weer alleen aan hun hoofdtaak, zoals voor
    # deze migratie: het issue_id dat ze van hun hoofdtaak kregen, gaat eraf.
    # Ook bij een subtaak die het al had; voor de vraag telt een subtaak
    # niet mee, dus er gaat niets verloren.
    op.execute(
        "UPDATE task SET issue_id = NULL FROM task p "
        "WHERE p.id = task.parent_id AND task.issue_id IS NOT NULL "
        "AND task.casus_id IS NOT NULL AND task.node_id IS NULL"
    )
    op.drop_constraint("ck_task_anchor", "task", type_="check")
    op.create_check_constraint(
        "ck_task_anchor", "task", "node_id IS NOT NULL OR casus_id IS NOT NULL"
    )
    op.drop_constraint("ck_issue_plek", "issue", type_="check")
    op.alter_column(
        "issue", "casus_id", existing_type=postgresql.UUID(), nullable=False
    )
    op.drop_index("ix_issue_initiatief_id", table_name="issue")
    op.drop_constraint("fk_issue_initiatief", "issue", type_="foreignkey")
    op.drop_column("issue", "initiatief_id")
