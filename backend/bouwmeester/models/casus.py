"""Casus model - het inhoudelijke werk dat start als een lead de trechter uit is.

Een lead is een contact of organisatie met informatie die door de trechter
loopt. Een casus is wat daarna begint: eigen fases, eigen team en
issues (onderzoeksvragen en ander werk) met taken. Eén lead levert hooguit één casus
op; de lead blijft daarna als geschiedenis staan, alleen-lezen.

Casussen bevatten de vertrouwelijkste informatie: de casus zelf gaat nooit
naar buiten. Van een afgeronde casus gaat alleen een tekst naar buiten die
iemand daarvoor schreef en vrijgaf (public_title, public_resultaat,
public_lessen); zie services/publieke_casussen.py.
"""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bouwmeester.core.database import Base

if TYPE_CHECKING:
    from bouwmeester.models.casus_soort import CasusSoort
    from bouwmeester.models.initiatief import Initiatief
    from bouwmeester.models.issue import Issue
    from bouwmeester.models.lead import Lead
    from bouwmeester.models.person import Person


class Casus(Base):
    __tablename__ = "casus"

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
    # verplicht (de route bewaakt dat), zodat iedereen ziet waarom hij stilligt
    # en wanneer hij er weer uit komt.
    koelkast_sinds: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    koelkast_reden: Mapped[str | None] = mapped_column(Text, nullable=True)
    koelkast_verwacht_terug: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Wat het team leerde, vastgelegd bij het afronden. Blijft binnen.
    lessen: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Naar buiten: een afgeronde casus in gewone taal (een naam, wat het
    # opleverde, en de lessen voor buiten). Alleen deze teksten gaan ooit naar
    # buiten, als iemand ze vrijgeeft (published_at); de rest van de casus
    # blijft binnen. Niet meer in de laatste fase (een fasewijziging, of een
    # fase erachter in de funnel) is niet meer vrijgegeven.
    public_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_resultaat: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_lessen: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
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
