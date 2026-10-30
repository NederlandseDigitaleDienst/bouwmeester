"""Pydantic schemas voor Casus.

De fases en de startvoorwaarden zijn bewust dummies: ze volgen het werkproces
zoals besproken op 22 en 27 oktober 2026, maar de echte invulling komt later.
Alles wat hier als lijst staat is daarom op één plek te wijzigen.
"""

import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bouwmeester.schema.casus_fases import FASE_ID_PATROON
from bouwmeester.schema.casus_soort import CasusSoortSummary, SoortEis
from bouwmeester.schema.startvragen import StartAntwoord

# De fases van een casus staan per initiatief in de casusfunnel
# (schema/casus_fases.py); casus.fase is een fase-id uit die lijst.

# De lead-kolom van waaruit een casus mag starten. Dummy-regel: de standaard
# "gewonnen"-kolom. Heeft een initiatief die kolom niet (eigen kolommen), dan
# geldt de laatste kolom in de volgorde.
START_VANUIT_STAGE = "in_the_pocket"

# Rollen in het casusteam. Wie zo'n rol krijgt moet het initiatief van de
# casus kunnen zien; de route bewaakt dat.
CASUSTEAM_ROLLEN: frozenset[str] = frozenset({"trekker", "teamlid"})


class CasusAs(enum.StrEnum):
    onderzoeksvragen = "onderzoeksvragen"
    toepassing = "toepassing"


class CasusType(enum.StrEnum):
    """Een interne casus, of een satellietcasus (bij een partner)."""

    intern = "intern"
    satelliet = "satelliet"


class AcceptatieCriterium(BaseModel):
    """Eén acceptatiecriterium bij het starten van een casus."""

    criterium: str = Field(min_length=1, max_length=300)
    akkoord: bool = False
    opmerking: str | None = Field(None, max_length=2000)


class Startvoorwaarden(BaseModel):
    """De antwoorden bij het starten van een casus.

    De vragen zelf staan per initiatief in de instellingen
    (schema/startvragen.py). `casustype` is het antwoord op de vaste vraag,
    `antwoorden` de rest; de route toetst ze aan de vragen van het initiatief
    en legt de vraag erbij vast zoals hij toen luidde. Opslag: JSON op
    casus.startvoorwaarden.
    """

    casustype: CasusType | None = Field(
        None, description="Een interne casus of een satellietcasus"
    )
    antwoorden: list[StartAntwoord] = Field(default_factory=list, max_length=30)
    # Vervallen vraag: alleen nog bij oudere casussen ingevuld.
    as_: CasusAs | None = Field(
        None,
        alias="as",
        description="Vervallen: onderzoeksvragen of toepassing",
    )
    toelichting: str | None = Field(None, max_length=5000)
    # De acceptatiecriteria van het initiatief zoals het team ze bij de start
    # naliep: per criterium afgevinkt of niet, met een uitleg. Een momentopname:
    # verandert de lijst van het initiatief later, dan blijft dit staan.
    # Geen criteria: het veld blijft weg uit de opgeslagen JSON.
    acceptatiecriteria: list[AcceptatieCriterium] | None = Field(None, max_length=30)
    # De starteisen van de gekozen soorten, per eis afgevinkt of niet. De
    # route legt ze vast met alle eisen van die soorten erin
    # (momentopname_eisen); geen eisen: het veld blijft weg.
    start_eisen: list[SoortEis] | None = Field(None, max_length=300)

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def _criteria_bij_satelliet(self) -> "Startvoorwaarden":
        # De acceptatiecriteria zijn de lijst voor satellietcasussen.
        if self.acceptatiecriteria and self.casustype != CasusType.satelliet:
            raise ValueError("Acceptatiecriteria horen bij een satellietcasus")
        return self


class CasusStart(BaseModel):
    lead_id: UUID
    startvoorwaarden: Startvoorwaarden
    trekker_id: UUID | None = None
    teamlid_ids: list[UUID] = Field(default_factory=list)
    # Casussoorten van het initiatief; andere geven 400.
    soort_ids: list[UUID] = Field(default_factory=list, max_length=50)


class CasusUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = Field(None, max_length=10000)
    organization: str | None = Field(None, max_length=500)
    # Een fase-id uit de funnel van het initiatief; de route controleert dat.
    fase: str | None = Field(None, pattern=FASE_ID_PATROON)
    # De eindeisen van de soorten zoals het team ze naliep, meestal samen met
    # de stap naar de laatste fase. Geen poort: de fase gaat ook zonder.
    eind_eisen: list[SoortEis] | None = Field(None, max_length=300)


class CasusTeamCreate(BaseModel):
    person_id: UUID
    rol: str = Field("teamlid", pattern="^(trekker|teamlid)$")


class CasusTeamResponse(BaseModel):
    id: UUID
    person_id: UUID
    person_naam: str = ""
    person_functie: str | None = None
    rol: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CasusLeadSummary(BaseModel):
    id: UUID
    title: str
    stage: str
    organization: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CasusInitiatiefSummary(BaseModel):
    id: UUID
    naam: str
    kleur: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CasusResponse(BaseModel):
    id: UUID
    lead_id: UUID
    initiatief_id: UUID | None = None
    initiatief: CasusInitiatiefSummary | None = None
    title: str
    description: str | None = None
    organization: str | None = None
    fase: str
    startvoorwaarden: dict[str, Any] = Field(default_factory=dict)
    # De eindeisen zoals het team ze naliep (momentopname), anders leeg.
    eind_eisen: list[dict[str, Any]] = Field(default_factory=list)
    started_by_id: UUID | None = None
    trekker_naam: str | None = None
    team_count: int = 0
    # De soorten (tags) van de casus, uit die van het initiatief.
    soorten: list[CasusSoortSummary] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CasusDetailResponse(CasusResponse):
    lead: CasusLeadSummary | None = None
    team: list[CasusTeamResponse] = Field(default_factory=list)
