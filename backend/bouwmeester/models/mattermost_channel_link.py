"""MattermostChannelLink - bindt een MM-kanaal aan een initiatief, lead of casus."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bouwmeester.core.database import Base

if TYPE_CHECKING:
    from bouwmeester.models.person import Person


SCOPE_INITIATIEF = "initiatief"
SCOPE_LEAD = "lead"
# Een casus leest niet mee: Bouwmeester post er de voortgang van de casus.
# Start uit een lead een casus, dan verhuist het kanaal van de lead mee.
SCOPE_CASUS = "casus"


class MattermostChannelLink(Base):
    """Eén kanaal hangt aan precies één initiatief, één lead of één casus.

    `scope_id` is polymorf — geen DB-FK omdat het naar `initiatief.id`,
    `lead.id` of `casus.id` kan wijzen. De route checkt scope_type vóór gebruik.
    """

    __tablename__ = "mattermost_channel_link"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    channel_id: Mapped[str] = mapped_column(
        String(26), unique=True, nullable=False, index=True
    )
    channel_name: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    team_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    scope_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="initiatief|lead|casus",
    )
    scope_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    auto_note_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    suggest_leads_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    parlementaire_alerts_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment=(
            "Stuur kamerstukken die op een zoekterm van dit initiatief "
            "matchen naar dit kanaal. Staat standaard uit: een kanaal dat "
            "voor leads is gekoppeld hoort niet ongevraagd elk kamerstuk "
            "te krijgen. De zoektermen zelf staan op het initiatief."
        ),
    )
    nieuws_alerts_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment=(
            "Stuur artikelen uit de vakpers die op een zoekterm matchen "
            "naar dit kanaal. Apart van de kamerstukken, want dat zijn "
            "andere stukken voor een ander gesprek: een kanaal dat de "
            "Kamer volgt heeft niet vanzelf om nieuws gevraagd."
        ),
    )
    casus_updates_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment=(
            "Post de voortgang van de casus in dit kanaal: fase en "
            "onderzoeksvragen. Alleen bij een privékanaal aan een casus."
        ),
    )
    van_de_lead: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment=(
            "Kwam bij de casusstart mee van de lead. Alleen zo'n kanaal gaat "
            "terug naar de lead als de casus verdwijnt; de rest wordt ontkoppeld."
        ),
    )
    last_seen_post_at: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment=(
            "Mattermost ms-timestamp van laatst verwerkte post (recovery na reconnect)"
        ),
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Bot is uit kanaal getrapt of kanaal is verwijderd",
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    created_by: Mapped[Optional["Person"]] = relationship(
        "Person", foreign_keys=[created_by_id]
    )
