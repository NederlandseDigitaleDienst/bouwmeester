"""Pydantic schemas for Initiatief."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bouwmeester.schema.casus import DEFAULT_DOD
from bouwmeester.schema.casus_fases import (
    DEFAULT_CASUS_FASES,
    CasusFaseDef,
    controleer_fases,
    geldende_casus_fases,
)
from bouwmeester.schema.startvragen import (
    Startvraag,
    controleer_lijst,
    geldende_startvragen,
)

# Canonical eenheid-rol type — used in schemas, routes, and repository
InitiatiefEenheidRol = Literal["eigenaar", "contributor", "viewer"]
EENHEID_ROL_RANK: dict[str, int] = {"eigenaar": 3, "contributor": 2, "viewer": 1}

# The closed set of nldd-tag color names an Initiatief.kleur may hold, the same
# set LeadColumn.color uses (schema.lead_column.LEAD_COLUMN_COLORS): five
# semantic roles plus the Rijkshuisstijl hues. The frontend passes this straight
# to nldd-tag's `color` and nldd-icon's `color`, which ignore anything outside
# their own set, so a hex or a CSS class here renders as no color at all.
# Mirrored by hand in frontend/src/types/index.ts (INITIATIEF_COLORS).
INITIATIEF_COLORS: frozenset[str] = frozenset(
    {
        # Semantic roles
        "neutral",
        "accent",
        "success",
        "warning",
        "critical",
        # Rijkshuisstijl
        "lintblauw",
        "donkerblauw",
        "hemelblauw",
        "lichtblauw",
        "paars",
        "violet",
        "robijnrood",
        "roze",
        "rood",
        "oranje",
        "donkergeel",
        "geel",
        "donkerbruin",
        "bruin",
        "donkergroen",
        "groen",
        "mosgroen",
        "mintgroen",
    }
)


def _validate_kleur(kleur: str | None) -> str | None:
    if kleur is not None and kleur not in INITIATIEF_COLORS:
        allowed = ", ".join(sorted(INITIATIEF_COLORS))
        raise ValueError(f"kleur must be one of: {allowed}")
    return kleur


class InitiatiefBase(BaseModel):
    naam: str = Field(min_length=1, max_length=200)
    beschrijving: str | None = Field(None, max_length=5000)
    kleur: str | None = Field(
        None, max_length=20, description="One of INITIATIEF_COLORS."
    )

    _validate_kleur = field_validator("kleur")(_validate_kleur)


class InitiatiefCreate(InitiatiefBase):
    pass


class InitiatiefUpdate(BaseModel):
    naam: str | None = Field(None, min_length=1, max_length=200)
    beschrijving: str | None = Field(None, max_length=5000)
    kleur: str | None = Field(
        None, max_length=20, description="One of INITIATIEF_COLORS."
    )

    _validate_kleur = field_validator("kleur")(_validate_kleur)


class InitiatiefSettingsUpdate(BaseModel):
    """Settings only mutable by an eigenaar."""

    slug: str | None = Field(None, min_length=1, max_length=80)
    funnel_enabled: bool | None = None
    public_page_enabled: bool | None = None
    score_strategisch_label: str | None = Field(None, max_length=120)
    score_politiek_label: str | None = Field(None, max_length=120)
    score_positie_label: str | None = Field(None, max_length=120)
    # Definition of Done: lijst eisen; leeg = de dummy-default (schema/casus.py).
    dod_items: list[str] | None = Field(None, max_length=30)
    # Acceptatiecriteria die je bij het starten van een casus naloopt.
    acceptatiecriteria: list[str] | None = Field(None, max_length=30)
    # De startvragen; een lege lijst zet de standaardlijst terug.
    startvragen: list[Startvraag] | None = None
    # De casusfunnel; een lege lijst zet het voorstel terug.
    casus_fases: list[CasusFaseDef] | None = None

    @field_validator("casus_fases")
    @classmethod
    def _check_casus_fases(
        cls, fases: list[CasusFaseDef] | None
    ) -> list[CasusFaseDef] | None:
        if not fases:
            return fases
        return controleer_fases(fases)

    @field_validator("startvragen")
    @classmethod
    def _check_startvragen(
        cls, vragen: list[Startvraag] | None
    ) -> list[Startvraag] | None:
        if not vragen:
            return vragen
        return controleer_lijst(vragen)

    @field_validator("dod_items")
    @classmethod
    def _strip_dod(cls, items: list[str] | None) -> list[str] | None:
        if items is None:
            return None
        cleaned = [i.strip() for i in items if i and i.strip()]
        if any(len(i) > 300 for i in cleaned):
            raise ValueError("Een DoD-eis is maximaal 300 tekens")
        return cleaned

    @field_validator("acceptatiecriteria")
    @classmethod
    def _strip_criteria(cls, items: list[str] | None) -> list[str] | None:
        if items is None:
            return None
        cleaned = [i.strip() for i in items if i and i.strip()]
        if any(len(i) > 300 for i in cleaned):
            raise ValueError("Een acceptatiecriterium is maximaal 300 tekens")
        return cleaned


class InitiatiefMemberCreate(BaseModel):
    person_id: UUID
    rol: str = "contributor"


class InitiatiefEenheidCreate(BaseModel):
    eenheid_id: UUID
    rol: InitiatiefEenheidRol = "contributor"


class InitiatiefEenheidUpdate(BaseModel):
    rol: InitiatiefEenheidRol


class InitiatiefPersoonResponse(BaseModel):
    """Een persoon die dit initiatief kan zien, direct of via een eenheid.

    `rol` is de directe rol (eigenaar/contributor/viewer) als die er is;
    `via_eenheden` de namen van gekoppelde eenheden waar de persoon in zit.
    Zo ziet het team wie erbij hoort en waarom.
    """

    id: UUID
    naam: str
    functie: str | None = None
    expertise: str | None = None
    is_agent: bool = False
    rol: str | None = None
    via_eenheden: list[str] = []

    model_config = ConfigDict(from_attributes=True)


class InitiatiefMemberResponse(BaseModel):
    initiatief_id: UUID
    person_id: UUID
    person_naam: str = ""
    rol: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InitiatiefEenheidResponse(BaseModel):
    initiatief_id: UUID
    eenheid_id: UUID
    eenheid_naam: str = ""
    rol: str = "contributor"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InitiatiefEenheidWithNameResponse(BaseModel):
    initiatief_id: UUID
    initiatief_naam: str = ""
    eenheid_id: UUID
    rol: str = "contributor"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InitiatiefResponse(BaseModel):
    id: UUID
    naam: str
    slug: str | None = None
    beschrijving: str | None = None
    kleur: str | None = None
    funnel_enabled: bool = False
    public_page_enabled: bool = False
    score_strategisch_label: str | None = None
    score_politiek_label: str | None = None
    score_positie_label: str | None = None
    dod_items: list[str] = Field(default_factory=list)
    acceptatiecriteria: list[str] = Field(default_factory=list)
    # De startvragen die gelden: de eigen lijst, anders de standaardlijst.
    startvragen: list[Startvraag] = Field(default_factory=list)
    # De casusfunnel die geldt: de eigen fases, anders het voorstel.
    casus_fases: list[CasusFaseDef] = Field(default_factory=list)
    created_by_id: UUID | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("startvragen", mode="before")
    @classmethod
    def _geldende_startvragen(cls, opgeslagen: list | None) -> list[Startvraag]:
        return geldende_startvragen(opgeslagen)

    @field_validator("casus_fases", mode="before")
    @classmethod
    def _geldende_casus_fases(cls, opgeslagen: list | None) -> list[CasusFaseDef]:
        return geldende_casus_fases(opgeslagen)


class InitiatiefListItemResponse(InitiatiefResponse):
    """An initiatief as the overview shows it: the record plus what is in it.

    The counts are what a card needs to say whether an initiatief is alive
    without opening it. `active_lead_count` counts leads whose stage sits in
    a column marked as an active stage, so the parked ones (koelkast, in the
    pocket) do not make a quiet initiatief look busy.
    """

    lead_count: int = 0
    active_lead_count: int = 0
    member_count: int = 0
    last_published_at: datetime | None = None


class InitiatiefDetailResponse(InitiatiefResponse):
    members: list[InitiatiefMemberResponse] = Field(default_factory=list)
    eenheden: list[InitiatiefEenheidResponse] = Field(default_factory=list)
    access_level: str | None = None
    # De standaardlijst die geldt zolang dod_items leeg is. Zo kunnen de
    # instellingen hem tonen en als begin van een eigen lijst gebruiken.
    dod_standaard: list[str] = Field(default_factory=lambda: list(DEFAULT_DOD))
    # Het voorstel voor de funnel, om naar terug te gaan vanuit de instellingen.
    casus_fases_voorstel: list[CasusFaseDef] = Field(
        default_factory=lambda: list(DEFAULT_CASUS_FASES)
    )
    # Of de funnel het voorstel is (geen eigen fases opgeslagen).
    casus_fases_is_voorstel: bool = True
