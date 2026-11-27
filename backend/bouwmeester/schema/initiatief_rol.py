"""Schemas voor rollen in een initiatief en het werk per persoon."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

RolStatus = Literal["concept", "open", "belegd"]


def _tekst(v: str | None) -> str | None:
    """Leeg betekent niets."""
    if v is None:
        return None
    v = v.strip()
    return v or None


def _regels(v: list[str] | None) -> list[str] | None:
    """Lege en dubbele regels vallen weg; een regel is hooguit 500 tekens."""
    if v is None:
        return None
    schoon = list(dict.fromkeys(r.strip() for r in v if r and r.strip()))
    if any(len(r) > 500 for r in schoon):
        raise ValueError("Een regel is hooguit 500 tekens")
    return schoon


def _naam(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        raise ValueError("Een rol heeft een naam")
    return v


class _RolVelden(BaseModel):
    @field_validator("doel", "toelichting", "feedback", check_fields=False)
    @classmethod
    def _check_tekst(cls, v: str | None) -> str | None:
        return _tekst(v)

    @field_validator("aanspreekbaar_op", "domein", check_fields=False)
    @classmethod
    def _check_regels(cls, v: list[str] | None) -> list[str] | None:
        return _regels(v)

    @field_validator("naam", check_fields=False)
    @classmethod
    def _check_naam(cls, v: str | None) -> str | None:
        return _naam(v)


class RolCreate(_RolVelden):
    naam: str = Field(min_length=1, max_length=150)
    doel: str | None = Field(None, max_length=2000)
    aanspreekbaar_op: list[str] = Field(default_factory=list, max_length=30)
    domein: list[str] = Field(default_factory=list, max_length=30)
    toelichting: str | None = Field(None, max_length=20000)
    feedback: str | None = Field(None, max_length=20000)
    # Weglaten: concept, of belegd als er een vervuller bij zit.
    status: RolStatus | None = None
    vervuller_id: UUID | None = None


class RolUpdate(_RolVelden):
    """Weglaten laat een veld staan; null of leeg wist het (behalve de naam).

    Status: concept en open wisselen vrij. Open zetten bij een belegde rol is
    opnieuw toewijzen: de vervuller gaat eraf en er begint een nieuwe ronde
    interesse. Een vervuller zetten maakt de rol belegd; de vervuller weghalen
    is ook opnieuw toewijzen.
    """

    naam: str | None = Field(None, min_length=1, max_length=150)
    doel: str | None = Field(None, max_length=2000)
    aanspreekbaar_op: list[str] | None = Field(None, max_length=30)
    domein: list[str] | None = Field(None, max_length=30)
    toelichting: str | None = Field(None, max_length=20000)
    feedback: str | None = Field(None, max_length=20000)
    status: Literal["concept", "open"] | None = None
    vervuller_id: UUID | None = None


class InteresseZetten(BaseModel):
    invulling: str | None = Field(None, max_length=2000)

    @field_validator("invulling")
    @classmethod
    def _check_invulling(cls, v: str | None) -> str | None:
        return _tekst(v)


class RaakvlakCreate(BaseModel):
    rol_id: UUID
    omschrijving: str | None = Field(None, max_length=500)

    @field_validator("omschrijving")
    @classmethod
    def _check(cls, v: str | None) -> str | None:
        return _tekst(v)


class RaakvlakUpdate(BaseModel):
    omschrijving: str | None = Field(None, max_length=500)

    @field_validator("omschrijving")
    @classmethod
    def _check(cls, v: str | None) -> str | None:
        return _tekst(v)


class FocusZetten(BaseModel):
    focus: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("focus")
    @classmethod
    def _check(cls, v: list[str]) -> list[str] | None:
        return _regels(v)


class CirkelUpdate(BaseModel):
    doel: str | None = Field(None, max_length=2000)
    focus: list[str] | None = Field(None, max_length=20)

    @field_validator("doel")
    @classmethod
    def _check_doel(cls, v: str | None) -> str | None:
        return _tekst(v)

    @field_validator("focus")
    @classmethod
    def _check_focus(cls, v: list[str] | None) -> list[str] | None:
        return _regels(v)


class PersoonKort(BaseModel):
    id: UUID
    naam: str

    model_config = ConfigDict(from_attributes=True)


class RolKort(BaseModel):
    id: UUID
    naam: str


class CirkelResponse(BaseModel):
    id: UUID
    initiatief_id: UUID
    parent_id: UUID | None = None
    naam: str
    doel: str | None = None
    focus: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class InteresseResponse(BaseModel):
    person: PersoonKort
    ronde: int
    invulling: str | None = None
    vastgelegd_door: PersoonKort | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RaakvlakResponse(BaseModel):
    """Een raakvlak gezien vanaf één rol: `rol` is de andere kant."""

    id: UUID
    rol: RolKort
    omschrijving: str | None = None


class RolResponse(BaseModel):
    id: UUID
    initiatief_id: UUID
    cirkel_id: UUID
    naam: str
    status: RolStatus
    doel: str | None = None
    aanspreekbaar_op: list[str] = Field(default_factory=list)
    domein: list[str] = Field(default_factory=list)
    toelichting: str | None = None
    feedback: str | None = None
    vervuller: PersoonKort | None = None
    # False als de vervuller het initiatief niet meer kan zien: dan staat
    # de rol in de praktijk open.
    vervuller_is_lid: bool = True
    ronde: int
    # Interesse in de huidige ronde, en die van eerdere rondes apart.
    interesse: list[InteresseResponse] = Field(default_factory=list)
    eerdere_interesse: list[InteresseResponse] = Field(default_factory=list)
    raakvlakken: list[RaakvlakResponse] = Field(default_factory=list)
    sort_order: int
    created_at: datetime
    updated_at: datetime | None = None


class WerkRol(BaseModel):
    id: UUID
    naam: str
    doel: str | None = None


class WerkInteresse(BaseModel):
    rol_id: UUID
    rol_naam: str
    invulling: str | None = None


class WerkLead(BaseModel):
    id: UUID
    title: str
    stage: str
    # eigenaar (assignee) of aanbrenger (brought_by), of allebei
    als: list[str]


class WerkCasus(BaseModel):
    id: UUID
    title: str
    fase: str
    rol: str


class WerkIssue(BaseModel):
    id: UUID
    title: str
    status: str
    is_onderzoeksvraag: bool
    # Leeg bij een vraag van het initiatief zelf.
    casus_id: UUID | None = None
    casus_title: str | None = None


class WerkTaak(BaseModel):
    id: UUID
    title: str
    status: str
    priority: str
    deadline: date | None = None
    casus_id: UUID | None = None
    casus_title: str | None = None
    issue_id: UUID | None = None


class PersoonWerkResponse(BaseModel):
    """Wat een persoon binnen één initiatief draagt."""

    person: PersoonKort
    is_lid: bool
    focus: list[str] = Field(default_factory=list)
    rollen: list[WerkRol] = Field(default_factory=list)
    # Interesse in rollen die nu open zijn, in hun huidige ronde.
    interesse: list[WerkInteresse] = Field(default_factory=list)
    leads: list[WerkLead] = Field(default_factory=list)
    casussen: list[WerkCasus] = Field(default_factory=list)
    issues: list[WerkIssue] = Field(default_factory=list)
    open_taken: list[WerkTaak] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Import en export
# ---------------------------------------------------------------------------


class ExportRol(_RolVelden):
    naam: str = Field(min_length=1, max_length=150)
    status: RolStatus = "concept"
    doel: str | None = Field(None, max_length=2000)
    aanspreekbaar_op: list[str] = Field(default_factory=list, max_length=30)
    domein: list[str] = Field(default_factory=list, max_length=30)
    toelichting: str | None = Field(None, max_length=20000)
    feedback: str | None = Field(None, max_length=20000)
    # Een e-mailadres, zodat het bestand tussen omgevingen werkt.
    vervuller_email: str | None = Field(None, max_length=320)


class ExportRaakvlak(BaseModel):
    rol_a: str = Field(min_length=1, max_length=150)
    rol_b: str = Field(min_length=1, max_length=150)
    omschrijving: str | None = Field(None, max_length=500)


class ExportCirkel(BaseModel):
    doel: str | None = Field(None, max_length=2000)
    focus: list[str] = Field(default_factory=list, max_length=20)


class RollenExport(BaseModel):
    """Het bestand voor export en import. Versie 1."""

    versie: Literal[1] = 1
    cirkel: ExportCirkel = Field(default_factory=ExportCirkel)
    rollen: list[ExportRol] = Field(default_factory=list, max_length=200)
    raakvlakken: list[ExportRaakvlak] = Field(default_factory=list, max_length=1000)


class ImportResultaat(BaseModel):
    aangemaakt: int = 0
    bijgewerkt: int = 0
    raakvlakken: int = 0
    # Wat niet lukte, per regel uitgelegd; de rest is wel geïmporteerd.
    meldingen: list[str] = Field(default_factory=list)
