"""Rollen in een initiatief, losjes naar Holacracy.

Een initiatief heeft één ankercirkel (parent_id leeg); subcirkels kunnen er
later in. Een rol hoort bij een cirkel en heeft een doel, punten waarop hij
aanspreekbaar is, een domein, hooguit één vervuller en een status:
concept, open of belegd. Interesse hoort bij het toewijzen: per ronde, en
"opnieuw toewijzen" begint een nieuwe ronde. Raakvlakken koppelen twee
rollen met een regel uitleg. Een rol geeft geen toegang: dat blijft
ResourcePermission.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
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
    from bouwmeester.models.person import Person

ROL_STATUSSEN = ("concept", "open", "belegd")


class InitiatiefCirkel(Base):
    __tablename__ = "initiatief_cirkel"
    __table_args__ = (
        # Eén ankercirkel per initiatief.
        Index(
            "uq_initiatief_cirkel_anker",
            "initiatief_id",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
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
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("initiatief_cirkel.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    naam: Mapped[str] = mapped_column(String(150), nullable=False)
    doel: Mapped[str | None] = mapped_column(Text, nullable=True)
    focus: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class InitiatiefRol(Base):
    __tablename__ = "initiatief_rol"
    __table_args__ = (
        # Hoofdletters tellen niet: "Case" en "CASE" zijn dezelfde rol.
        Index(
            "uq_initiatief_rol_naam",
            "initiatief_id",
            func.lower(text("naam")),
            unique=True,
        ),
        CheckConstraint(
            "status IN ('concept', 'open', 'belegd')",
            name="ck_initiatief_rol_status",
        ),
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
    cirkel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("initiatief_cirkel.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    naam: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="concept", server_default="concept"
    )
    doel: Mapped[str | None] = mapped_column(Text, nullable=True)
    aanspreekbaar_op: Mapped[list] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    domein: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    toelichting: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Vrije tekst van het team over de rol zelf, zoals "opsplitsen" of
    # "samenvoegen met ...".
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    vervuller_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # De toewijzingsronde waar nieuwe interesse bij hoort.
    ronde: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    vervuller: Mapped["Person | None"] = relationship("Person", lazy="selectin")
    interesse: Mapped[list["InitiatiefRolInteresse"]] = relationship(
        "InitiatiefRolInteresse",
        back_populates="rol",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="InitiatiefRolInteresse.created_at",
    )


class InitiatiefRolInteresse(Base):
    """Iemand met interesse in een rol, in een toewijzingsronde."""

    __tablename__ = "initiatief_rol_interesse"
    __table_args__ = (
        UniqueConstraint(
            "rol_id", "person_id", "ronde", name="uq_initiatief_rol_interesse"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    rol_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("initiatief_rol.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ronde: Mapped[int] = mapped_column(Integer, nullable=False)
    invulling: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Interesse komt via allerlei kanalen binnen; wie het vastlegde, staat erbij.
    vastgelegd_door_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    rol: Mapped["InitiatiefRol"] = relationship(
        "InitiatiefRol", back_populates="interesse"
    )
    person: Mapped["Person"] = relationship(
        "Person", foreign_keys=[person_id], lazy="selectin"
    )
    vastgelegd_door: Mapped["Person | None"] = relationship(
        "Person", foreign_keys=[vastgelegd_door_id], lazy="selectin"
    )


class InitiatiefRolRaakvlak(Base):
    """Twee rollen met een raakvlak, en waar dat over gaat.

    Een paar telt één keer: rol_a_id is altijd de kleinste id.
    """

    __tablename__ = "initiatief_rol_raakvlak"
    __table_args__ = (
        UniqueConstraint("rol_a_id", "rol_b_id", name="uq_initiatief_rol_raakvlak"),
        CheckConstraint("rol_a_id < rol_b_id", name="ck_initiatief_rol_raakvlak_paar"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    rol_a_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("initiatief_rol.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rol_b_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("initiatief_rol.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    omschrijving: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class InitiatiefPersoonFocus(Base):
    """De persoonlijke focus van iemand binnen een initiatief, als vrije regels."""

    __tablename__ = "initiatief_persoon_focus"

    initiatief_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("initiatief.id", ondelete="CASCADE"),
        primary_key=True,
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    focus: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )
