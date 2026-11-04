"""Task model - linked to a corpus_node and/or a casus."""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bouwmeester.core.database import Base

if TYPE_CHECKING:
    from bouwmeester.models.casus import Casus
    from bouwmeester.models.corpus_node import CorpusNode
    from bouwmeester.models.issue import Issue
    from bouwmeester.models.opdracht import Opdracht
    from bouwmeester.models.organisatie_eenheid import OrganisatieEenheid
    from bouwmeester.models.parlementair_item import ParlementairItem
    from bouwmeester.models.person import Person


class Task(Base):
    __tablename__ = "task"
    __table_args__ = (
        # Een taak hangt aan een corpus-node (bestaand gedrag) of aan een
        # casus. Zonder anker is hij nergens terug te vinden.
        CheckConstraint(
            "node_id IS NOT NULL OR casus_id IS NOT NULL",
            name="ck_task_anchor",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corpus_node.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    casus_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("casus.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Het issue waar de taak onder valt. Een subtaak hangt aan zijn hoofdtaak
    # (parent_id) en telt niet mee voor het issue.
    issue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("issue.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    organisatie_eenheid_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisatie_eenheid.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    parlementair_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parlementair_item.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    opdracht_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opdracht.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        default="open",
        server_default="open",
        comment="open|in_progress|done|cancelled",
    )
    priority: Mapped[str] = mapped_column(
        default="normaal",
        server_default="normaal",
        comment="laag|normaal|hoog|kritiek",
    )
    deadline: Mapped[date | None] = mapped_column(nullable=True)
    order: Mapped[int | None] = mapped_column(nullable=True, default=None)
    work_type: Mapped[str | None] = mapped_column(nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    node: Mapped[Optional["CorpusNode"]] = relationship(
        "CorpusNode",
        back_populates="tasks",
    )
    casus: Mapped[Optional["Casus"]] = relationship("Casus")
    issue: Mapped[Optional["Issue"]] = relationship("Issue", back_populates="tasks")
    assignee: Mapped[Optional["Person"]] = relationship("Person")
    organisatie_eenheid: Mapped[Optional["OrganisatieEenheid"]] = relationship(
        "OrganisatieEenheid",
    )
    parent: Mapped[Optional["Task"]] = relationship(
        "Task",
        remote_side=[id],
        back_populates="subtasks",
    )
    # Een afvinklijst: in de volgorde waarin ze zijn getypt, tenzij iemand
    # ze met de hand heeft geordend.
    subtasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by=lambda: (Task.order.asc().nulls_last(), Task.created_at.asc()),
    )
    parlementair_item: Mapped[Optional["ParlementairItem"]] = relationship(
        "ParlementairItem",
    )
    opdracht: Mapped[Optional["Opdracht"]] = relationship(
        "Opdracht",
        back_populates="tasks",
    )
