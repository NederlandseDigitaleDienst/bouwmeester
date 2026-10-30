"""Lead model - sales/intake funnel lead."""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bouwmeester.core.database import Base

if TYPE_CHECKING:
    from bouwmeester.models.casus import Casus
    from bouwmeester.models.initiatief import Initiatief
    from bouwmeester.models.lead_activity import LeadActivity
    from bouwmeester.models.lead_attachment import LeadAttachment
    from bouwmeester.models.lead_node import LeadNode
    from bouwmeester.models.lead_update import LeadUpdatePost
    from bouwmeester.models.organisatie_eenheid import OrganisatieEenheid
    from bouwmeester.models.person import Person
    from bouwmeester.models.tag import LeadTag


class Lead(Base):
    __tablename__ = "lead"
    __table_args__ = (
        # Speeds up the per-initiatief stage filter that the kanbanbord,
        # de metrics-aggregatie, en de "non-active stage" subquery in de
        # overdue/stale filters elke keer raken.
        Index("ix_lead_initiatief_stage", "initiatief_id", "stage"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    organization: Mapped[str | None] = mapped_column(nullable=True)
    organisatie_eenheid_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisatie_eenheid.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    stage: Mapped[str] = mapped_column(
        default="inbox",
        server_default="inbox",
        comment="inbox|verkennen|eerste_gesprek|interne_check|follow_up|in_the_pocket|koelkast",
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    brought_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action_date: Mapped[date | None] = mapped_column(nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0, server_default="0")
    raw_intake_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    engagement_type: Mapped[str | None] = mapped_column(
        nullable=True,
        index=True,
        comment=(
            "intern_oppakken|voorbereiden_eigen_team|betrokken_houden|"
            "verkenning|nog_te_bepalen"
        ),
    )
    score_strategisch: Mapped[int | None] = mapped_column(nullable=True)
    score_politiek: Mapped[int | None] = mapped_column(nullable=True)
    score_positie: Mapped[int | None] = mapped_column(nullable=True)
    public_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    public_title: Mapped[str | None] = mapped_column(nullable=True)
    public_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    initiatief_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("initiatief.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    assignee: Mapped[Optional["Person"]] = relationship(
        "Person", foreign_keys=[assignee_id]
    )
    brought_by: Mapped[Optional["Person"]] = relationship(
        "Person", foreign_keys=[brought_by_id]
    )
    organisatie_eenheid: Mapped[Optional["OrganisatieEenheid"]] = relationship(
        "OrganisatieEenheid"
    )
    initiatief: Mapped[Optional["Initiatief"]] = relationship(
        "Initiatief", back_populates="leads"
    )
    activities: Mapped[list["LeadActivity"]] = relationship(
        "LeadActivity",
        back_populates="lead",
        cascade="all, delete-orphan",
    )
    attachments: Mapped[list["LeadAttachment"]] = relationship(
        "LeadAttachment",
        back_populates="lead",
        cascade="all, delete-orphan",
    )
    linked_nodes: Mapped[list["LeadNode"]] = relationship(
        "LeadNode",
        back_populates="lead",
        cascade="all, delete-orphan",
    )
    lead_tags: Mapped[list["LeadTag"]] = relationship(
        "LeadTag",
        back_populates="lead",
        cascade="all, delete-orphan",
    )
    updates: Mapped[list["LeadUpdatePost"]] = relationship(
        "LeadUpdatePost",
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="LeadUpdatePost.created_at.desc()",
    )
    # De casus die uit deze lead is gestart, als die er is. Daarna is de
    # lead alleen-lezen (zie _require_lead_open in routes/leads.py).
    casus: Mapped[Optional["Casus"]] = relationship(
        "Casus", back_populates="lead", uselist=False
    )
