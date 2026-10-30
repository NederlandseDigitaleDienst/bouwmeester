"""Schemas voor casussoorten: soorten casus per initiatief, als tags.

Per soort twee lijsten eisen: wat je nagaat bij de start van een casus van
die soort, en wat af moet zijn aan het einde. Bij het starten en als de
casus in de laatste fase van de funnel komt, loopt het team ze na: per eis
een vinkje en een opmerking. Afvinken is geen poort; de casus kan door, ook
als niet alles af is. Beide lijsten beginnen leeg.
"""

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bouwmeester.schema.lead_column import LEAD_COLUMN_COLORS


def _kleur(kleur: str | None) -> str | None:
    if kleur is not None and kleur not in LEAD_COLUMN_COLORS:
        allowed = ", ".join(sorted(LEAD_COLUMN_COLORS))
        raise ValueError(f"kleur moet een van deze zijn: {allowed}")
    return kleur


def _uitleg(uitleg: str | None) -> str | None:
    """Leeg betekent geen uitleg."""
    if uitleg is None:
        return None
    uitleg = uitleg.strip()
    return uitleg or None


def _eisen(eisen: list[str] | None) -> list[str] | None:
    """Lege regels vallen weg, dubbele ook; een eis is hooguit 300 tekens."""
    if eisen is None:
        return None
    schoon = list(dict.fromkeys(e.strip() for e in eisen if e and e.strip()))
    if any(len(e) > 300 for e in schoon):
        raise ValueError("Een eis is hooguit 300 tekens")
    return schoon


def _naam(naam: str | None) -> str | None:
    if naam is None:
        return None
    naam = naam.strip()
    if not naam:
        raise ValueError("Een soort heeft een naam")
    return naam


class CasusSoortCreate(BaseModel):
    naam: str = Field(min_length=1, max_length=100)
    kleur: str = "neutral"
    uitleg: str | None = Field(None, max_length=500)
    hoe_ver: str | None = Field(None, max_length=10000)
    start_eisen: list[str] = Field(default_factory=list, max_length=30)
    eind_eisen: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("uitleg", "hoe_ver")
    @classmethod
    def _check_uitleg(cls, v: str | None) -> str | None:
        return _uitleg(v)

    @field_validator("start_eisen", "eind_eisen")
    @classmethod
    def _check_eisen(cls, v: list[str]) -> list[str] | None:
        return _eisen(v)

    @field_validator("naam")
    @classmethod
    def _check_naam(cls, v: str) -> str | None:
        return _naam(v)

    @field_validator("kleur")
    @classmethod
    def _check_kleur(cls, v: str) -> str | None:
        return _kleur(v)


class CasusSoortUpdate(BaseModel):
    naam: str | None = Field(None, min_length=1, max_length=100)
    kleur: str | None = None
    # Leeg of null wist de uitleg, en ook "hoe ver".
    uitleg: str | None = Field(None, max_length=500)
    hoe_ver: str | None = Field(None, max_length=10000)
    # Een lege lijst wist de eisen; weglaten laat ze staan.
    start_eisen: list[str] | None = Field(None, max_length=30)
    eind_eisen: list[str] | None = Field(None, max_length=30)

    @field_validator("uitleg", "hoe_ver")
    @classmethod
    def _check_uitleg(cls, v: str | None) -> str | None:
        return _uitleg(v)

    @field_validator("start_eisen", "eind_eisen")
    @classmethod
    def _check_eisen(cls, v: list[str] | None) -> list[str] | None:
        return _eisen(v)

    @field_validator("naam")
    @classmethod
    def _check_naam(cls, v: str | None) -> str | None:
        return _naam(v)

    @field_validator("kleur")
    @classmethod
    def _check_kleur(cls, v: str | None) -> str | None:
        return _kleur(v)


class CasusSoortReorder(BaseModel):
    soort_ids: list[UUID] = Field(max_length=200)


class CasusSoortenZetten(BaseModel):
    """De soorten van een casus, als geheel vervangen."""

    soort_ids: list[UUID] = Field(default_factory=list, max_length=50)


class CasusSoortSummary(BaseModel):
    """Een soort zoals hij op een casus staat, met zijn eisen: het startvenster
    en het afronden lopen ze na zonder de lijst van het initiatief op te halen."""

    id: UUID
    naam: str
    kleur: str
    uitleg: str | None = None
    start_eisen: list[str] = Field(default_factory=list)
    eind_eisen: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class CasusSoortResponse(CasusSoortSummary):
    initiatief_id: UUID
    sort_order: int
    hoe_ver: str | None = None
    # Op hoeveel casussen hij staat: de instellingen tonen het bij verwijderen.
    casus_count: int = 0
    created_at: datetime


class SoortEis(BaseModel):
    """Eén eis van een soort zoals het team hem naliep: vinkje en opmerking.

    De client stuurt soort_id, eis, akkoord en opmerking; de naam van de soort
    vult de server in (momentopname_eisen).
    """

    soort_id: UUID
    soort: str = ""
    eis: str = Field(min_length=1, max_length=300)
    akkoord: bool = False
    opmerking: str | None = Field(None, max_length=2000)


class _MetEisen(Protocol):
    id: UUID
    naam: str
    start_eisen: list
    eind_eisen: list


def momentopname_eisen(
    soorten: list[_MetEisen], lijst: str, ingevuld: list[SoortEis]
) -> list[dict[str, Any]]:
    """De start- of eindeisen van de soorten, met wat het team invulde.

    `lijst` is "start_eisen" of "eind_eisen". Alle eisen van de soorten staan
    erin, op volgorde van de soorten en van hun lijst; een eis die niemand
    aanvinkte, staat erin als niet akkoord. Een ingevulde eis die niet bij
    een van de soorten hoort, geeft ValueError. Uitkomst: JSON voor de casus,
    zodat een latere wijziging van de soort de casus niet verandert.
    """
    per_eis = {(e.soort_id, e.eis): e for e in ingevuld}
    geldig = {(s.id, eis) for s in soorten for eis in getattr(s, lijst) or []}
    for e in ingevuld:
        if (e.soort_id, e.eis) not in geldig:
            raise ValueError(
                f"Deze eis hoort niet bij de soorten van de casus: {e.eis}"
            )
    uit: list[dict[str, Any]] = []
    for s in soorten:
        for eis in getattr(s, lijst) or []:
            e = per_eis.get((s.id, eis))
            regel: dict[str, Any] = {
                "soort_id": str(s.id),
                "soort": s.naam,
                "eis": eis,
                "akkoord": bool(e and e.akkoord),
            }
            if e and e.opmerking and e.opmerking.strip():
                regel["opmerking"] = e.opmerking.strip()
            uit.append(regel)
    return uit
