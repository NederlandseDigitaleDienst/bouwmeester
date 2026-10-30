"""ResourcePermission model - unified resource-level access control.

Links a person OR an organisatie-eenheid to any resource with a role.
Replaces domain-specific junction tables with a single polymorphic table.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bouwmeester.core.database import Base


class ResourcePermission(Base):
    """Links a person or eenheid to a resource with a role."""

    __tablename__ = "resource_permission"
    __table_args__ = (
        UniqueConstraint(
            "person_id",
            "organisatie_eenheid_id",
            "resource_type",
            "resource_id",
            "rol",
            name="uq_resource_permission",
        ),
        CheckConstraint(
            "(person_id IS NOT NULL AND organisatie_eenheid_id IS NULL)"
            " OR "
            "(person_id IS NULL AND organisatie_eenheid_id IS NOT NULL)",
            name="ck_resource_permission_scope",
        ),
        CheckConstraint(
            "source IN ('manual', 'ai')",
            name="ck_resource_permission_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    organisatie_eenheid_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisatie_eenheid.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    resource_type: Mapped[str] = mapped_column(
        nullable=False,
        comment="corpus_node|initiatief|lead|opdracht|casus",
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Polymorphic FK - references the PK of the resource table",
    )
    rol: Mapped[str] = mapped_column(
        nullable=False,
        comment="eigenaar|betrokken|adviseur|indiener|contributor|viewer|contactpersoon|opdrachtgever|trekker|teamlid",
    )
    # AI matching metadata (nullable — only set for AI-generated links)
    source: Mapped[str | None] = mapped_column(
        nullable=True,
        server_default="manual",
        comment="manual|ai",
    )
    ai_confidence: Mapped[float | None] = mapped_column(
        Numeric(precision=3, scale=2), nullable=True
    )
    ai_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    person: Mapped["Person"] = relationship("Person", foreign_keys=[person_id])  # noqa: F821
    eenheid: Mapped["OrganisatieEenheid"] = relationship(  # noqa: F821
        "OrganisatieEenheid", foreign_keys=[organisatie_eenheid_id]
    )
