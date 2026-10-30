"""Initiatief model."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bouwmeester.core.database import Base


class Initiatief(Base):
    __tablename__ = "initiatief"
    __table_args__ = (
        UniqueConstraint("naam", name="uq_initiatief_naam"),
        UniqueConstraint("slug", name="uq_initiatief_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    naam: Mapped[str] = mapped_column(nullable=False)
    slug: Mapped[str | None] = mapped_column(nullable=True)
    beschrijving: Mapped[str | None] = mapped_column(Text, nullable=True)
    # One of the nldd-tag color names in schema.initiatief.INITIATIEF_COLORS
    # (five semantic roles plus the Rijkshuisstijl hue set), e.g. "lintblauw"
    # or "success". Never a hex value: the frontend passes this straight to
    # nldd-tag's `color` and nldd-icon's `color`, which ignore anything outside
    # their own set. Pydantic validates it on every write via InitiatiefCreate
    # and InitiatiefUpdate; there is no CHECK constraint behind it.
    kleur: Mapped[str | None] = mapped_column(nullable=True)
    funnel_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    public_page_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    score_strategisch_label: Mapped[str | None] = mapped_column(nullable=True)
    score_politiek_label: Mapped[str | None] = mapped_column(nullable=True)
    score_positie_label: Mapped[str | None] = mapped_column(nullable=True)
    # Definition of Done: teamstandaard, lijst eisen waaraan een issue moet
    # voldoen voordat het afgerond is. Leeg = de dummy-default uit schema/casus.py.
    dod_items: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # Acceptatiecriteria voor een nieuwe casus: wat het team bij het starten
    # naloopt. Per casus vastgelegd in casus.startvoorwaarden (afgevinkt, met
    # een opmerking per criterium). Leeg = geen criteria.
    acceptatiecriteria: Mapped[list] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    # De vragen bij het starten van een casus (schema/startvragen.py). Leeg =
    # de standaardlijst.
    startvragen: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # De casusfunnel: fases met naam, kleur, omschrijving en "door als"
    # (schema/casus_fases.py). Leeg = het voorstel.
    casus_fases: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person.id", ondelete="SET NULL"),
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
    created_by: Mapped["Person"] = relationship("Person", foreign_keys=[created_by_id])  # noqa: F821
    leads: Mapped[list["Lead"]] = relationship(  # noqa: F821
        "Lead",
        back_populates="initiatief",
    )
    updates: Mapped[list["InitiatiefUpdatePost"]] = relationship(  # noqa: F821
        "InitiatiefUpdatePost",
        back_populates="initiatief",
        cascade="all, delete-orphan",
        order_by="InitiatiefUpdatePost.created_at.desc()",
    )
    lead_columns: Mapped[list["LeadColumn"]] = relationship(  # noqa: F821
        "LeadColumn",
        back_populates="initiatief",
        cascade="all, delete-orphan",
        order_by="LeadColumn.sort_order",
    )
