"""Wat Bouwmeester over een casus in het Mattermost-kanaal zet.

Elk voortgangsbericht komt hier, ook als er geen kanaal aan de casus hangt
of Mattermost uit staat. Zo is bij de casus te zien wat er in het kanaal
staat, of zou staan. De berichten zelf maakt services/casus_kanaal_service.py.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from bouwmeester.core.database import Base

# Geen kanaal met voortgang aan: het bericht staat alleen hier.
STATUS_GEEN_KANAAL = "geen_kanaal"
# Wacht op de commit en de achtergrondtaak.
STATUS_WACHT = "wacht"
STATUS_VERSTUURD = "verstuurd"
# Niet in elk kanaal gelukt; de reden staat in de log.
STATUS_MISLUKT = "mislukt"
# Mattermost stond uit toen het bericht weg zou gaan.
STATUS_UIT = "uit"


class CasusKanaalbericht(Base):
    __tablename__ = "casus_kanaalbericht"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    casus_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("casus.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tekst: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Het bericht in Mattermost-markdown."
    )
    kanalen: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment=(
            "De kanalen met voortgang aan op het moment van het bericht: "
            "[{id, naam}]. Leeg als er geen was."
        ),
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="geen_kanaal|wacht|verstuurd|mislukt|uit",
    )
    # clock_timestamp en niet now(): twee berichten uit één transactie
    # krijgen zo elk hun eigen tijd en blijven op volgorde.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("clock_timestamp()"),
        nullable=False,
    )
