"""Onderzoeksverslag - het verslag bij een onderzoeksvraag, als bestand.

Eén verslag per vraag; een nieuw bestand vervangt het oude. Het bestand staat
in de bijlagenopslag (core.storage), net als bijlagen bij een taak.

Openbaar: wie het verslag naar buiten wil, bevestigt dat met een akkoord
(openbaar_op, openbaar_door_id). Op de publieke pagina staat het pas als de
vraag zelf ook naar buiten mag (services/publieke_vragen.py). Een nieuw
bestand vraagt een nieuw akkoord: het akkoord gold voor het oude.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bouwmeester.core.database import Base

if TYPE_CHECKING:
    from bouwmeester.models.issue import Issue
    from bouwmeester.models.person import Person


class Onderzoeksverslag(Base):
    __tablename__ = "onderzoeksverslag"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    issue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("issue.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    bestandsnaam: Mapped[str] = mapped_column(nullable=False)
    content_type: Mapped[str] = mapped_column(nullable=False)
    bestandsgrootte: Mapped[int] = mapped_column(nullable=False)
    pad: Mapped[str] = mapped_column(nullable=False)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Akkoord om het verslag naar buiten te brengen; leeg is binnen.
    openbaar_op: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    openbaar_door_id: Mapped[uuid.UUID | None] = mapped_column(
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

    issue: Mapped["Issue"] = relationship("Issue", back_populates="verslag")
    uploaded_by: Mapped[Optional["Person"]] = relationship(
        "Person", foreign_keys=[uploaded_by_id]
    )
    openbaar_door: Mapped[Optional["Person"]] = relationship(
        "Person", foreign_keys=[openbaar_door_id]
    )
