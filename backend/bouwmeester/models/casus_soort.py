"""Casussoort: een soort casus per initiatief, als tag aan een casus.

De soorten beheert de eigenaar in de instellingen van het initiatief; aan
een casus hangen er nul of meer (koppeltabel casus_casus_soort). Een eigen
tabel en geen tekstlijst: hernoemen werkt dan meteen op alle casussen, en
verwijderen haalt de soort overal weg.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bouwmeester.core.database import Base

if TYPE_CHECKING:
    from bouwmeester.models.initiatief import Initiatief


class CasusSoort(Base):
    __tablename__ = "casus_soort"
    __table_args__ = (
        UniqueConstraint(
            "initiatief_id", "naam", name="uq_casus_soort_initiatief_naam"
        ),
        Index("ix_casus_soort_initiatief_sort", "initiatief_id", "sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    initiatief_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("initiatief.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    naam: Mapped[str] = mapped_column(String(100), nullable=False)
    # Wat deze soort betekent; staat bij het kiezen en als tooltip op het label.
    uitleg: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Een nldd-tag-kleur uit schema.lead_column.LEAD_COLUMN_COLORS, zoals bij
    # de funnel-kolommen. Pydantic valideert hem bij elke schrijfactie.
    kleur: Mapped[str] = mapped_column(nullable=False, server_default="neutral")
    # In detail, in de instellingen: hoe ver brengen we een casus van deze
    # soort, wat je nagaat bij de start en wat af moet zijn aan het einde
    # (korte regels, op volgorde). Bij het starten en in de laatste fase
    # loopt het team de lijst na; de casus houdt een momentopname.
    hoe_ver: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_eisen: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    eind_eisen: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    initiatief: Mapped["Initiatief"] = relationship("Initiatief")


class CasusCasusSoort(Base):
    """Koppeling casus en soort. Weg met de casus of de soort (CASCADE)."""

    __tablename__ = "casus_casus_soort"

    casus_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("casus.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    casus_soort_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("casus_soort.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
