"""Casus model - het inhoudelijke werk dat start als een lead de trechter uit is.

Een lead is een contact of organisatie met informatie die door de trechter
loopt. Een casus is wat daarna begint: eigen fases, eigen team en
issues (onderzoeksvragen en ander werk) met taken. Eén lead levert hooguit één casus
op; de lead blijft daarna staan en bewerkbaar, maar wel in zijn kolom.

Casussen bevatten de vertrouwelijkste informatie en zijn nooit publiek.
"""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bouwmeester.core.database import Base

if TYPE_CHECKING:
    from bouwmeester.models.casus_soort import CasusSoort
    from bouwmeester.models.initiatief import Initiatief
    from bouwmeester.models.issue import Issue
    from bouwmeester.models.lead import Lead
    from bouwmeester.models.person import Person


# Alle drie leeg (niet in de koelkast) of alle drie gevuld, met een reden die
# niet alleen uit spaties bestaat. "IS NOT NULL" staat er los bij: een check
# met NULL als uitkomst gaat door.
KOELKAST_CHECK = (
    "(koelkast_sinds IS NULL AND koelkast_reden IS NULL"
    " AND koelkast_verwacht_terug IS NULL)"
    " OR (koelkast_sinds IS NOT NULL AND koelkast_reden IS NOT NULL"
    " AND btrim(koelkast_reden) <> '' AND koelkast_verwacht_terug IS NOT NULL)"
)


class Casus(Base):
    __tablename__ = "casus"
    __table_args__ = (
        # In de koelkast hoort een reden en een verwachte datum, erbuiten
        # geen van drieën. De route bewaakt dat ook; dit houdt het heel
        # buiten de route om. Dezelfde tekst staat in de migratie.
        CheckConstraint(
            KOELKAST_CHECK,
            name="ck_casus_koelkast",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # RESTRICT, geen CASCADE: een lead weggooien mag nooit stilletjes een
    # casus met al zijn werk meenemen. De lead-route weigert dat met een 409.
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    initiatief_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("initiatief.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    organization: Mapped[str | None] = mapped_column(nullable=True)
    # Een fase-id uit de casusfunnel van het initiatief (schema/casus_fases.py,
    # initiatief.casus_fases). Worden
    # later ingevuld; de kolomnamen zijn nu een ontwerpkeuze, geen besluit.
    fase: Mapped[str] = mapped_column(
        default="start",
        server_default="start",
        comment="fase-id uit initiatief.casus_fases (standaard start..besluiten)",
    )
    # Antwoorden op de startvoorwaarden, vrij JSON zodat de set kan groeien
    # zonder migratie. Validatie van de huidige (dummy) set zit in het schema.
    startvoorwaarden: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    # De eindeisen van de soorten zoals het team ze naliep toen de casus in
    # de laatste fase kwam: per eis een vinkje en een opmerking. Een
    # momentopname (schema.casus_soort.momentopname_eisen); leeg is nog niet
    # nagelopen, of de soorten hebben geen eindeisen.
    eind_eisen: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # De koelkast: een casus die even stilligt. De fase blijft staan, zodat
    # hij na de koelkast verder gaat waar hij was. In de koelkast is
    # koelkast_sinds gezet; de reden en de verwachte terugkeer zijn dan
    # verplicht (ck_casus_koelkast), zodat iedereen ziet waarom hij stilligt
    # en wanneer hij er weer uit komt. Zolang hij erin staat, staat de fase
    # vast (routes/casussen.py).
    koelkast_sinds: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    koelkast_reden: Mapped[str | None] = mapped_column(Text, nullable=True)
    koelkast_verwacht_terug: Mapped[date | None] = mapped_column(Date, nullable=True)
    started_by_id: Mapped[uuid.UUID | None] = mapped_column(
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
    lead: Mapped["Lead"] = relationship("Lead", back_populates="casus")
    # Soorten als tags, uit de soorten van het initiatief (zie casus_soort.py).
    soorten: Mapped[list["CasusSoort"]] = relationship(
        "CasusSoort",
        secondary="casus_casus_soort",
        order_by="CasusSoort.sort_order",
        viewonly=True,
    )
    initiatief: Mapped[Optional["Initiatief"]] = relationship("Initiatief")
    started_by: Mapped[Optional["Person"]] = relationship("Person")
    issues: Mapped[list["Issue"]] = relationship(
        "Issue",
        back_populates="casus",
        cascade="all, delete-orphan",
        order_by="Issue.sort_order.asc(), Issue.created_at.asc()",
    )
