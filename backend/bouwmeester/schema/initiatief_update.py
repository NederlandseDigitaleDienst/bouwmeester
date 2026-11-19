"""Pydantic schemas for InitiatiefUpdatePost."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from bouwmeester.schema.onderzoeksverslag import PubliekVerslag


class PubliekeVraag(BaseModel):
    """Een vrijgegeven onderzoeksvraag zoals hij naar buiten gaat.

    Alleen de publieke tekst: nooit de interne titel, toelichting of casus.
    """

    id: UUID
    vraag: str
    antwoord: str
    published_at: datetime
    # Het onderzoeksverslag, alleen als iemand akkoord gaf om het naar buiten
    # te brengen.
    verslag: PubliekVerslag | None = None


class PubliekeCasus(BaseModel):
    """Een vrijgegeven, afgeronde casus zoals hij naar buiten gaat.

    Alleen de tekst die iemand voor buiten schreef: nooit de interne titel,
    de beschrijving, het team of de lessen van binnen.
    """

    id: UUID
    titel: str
    resultaat: str
    lessen: str | None = None
    published_at: datetime


class KlaarVraag(BaseModel):
    """Voor de tab Updates: een afgeronde onderzoeksvraag, met wat binnen
    staat (titel, casus) en wat al buiten mag. Alleen voor leden."""

    id: UUID
    # Leeg bij een vraag van het initiatief zonder casus.
    casus_id: UUID | None = None
    casus_titel: str | None = None
    titel: str
    public_title: str | None = None
    public_answer: str | None = None
    published_at: datetime | None = None
    in_gepubliceerde_update: bool = False
    verslag_openbaar: bool = False


class KlaarCasus(BaseModel):
    """Voor de tab Updates: een afgeronde casus met zijn lessen (binnen) en
    de tekst voor buiten. Alleen voor leden."""

    id: UUID
    titel: str
    lessen: str | None = None
    public_title: str | None = None
    public_resultaat: str | None = None
    public_lessen: str | None = None
    published_at: datetime | None = None
    in_gepubliceerde_update: bool = False
    afgerond_op: datetime | None = None


class KlaarOmTeDelen(BaseModel):
    """Waar een update op kan voortbouwen: afgeronde onderzoeksvragen en
    afgeronde casussen van het initiatief."""

    vragen: list[KlaarVraag] = Field(default_factory=list)
    casussen: list[KlaarCasus] = Field(default_factory=list)


class VrijgegevenVraag(PubliekeVraag):
    """Voor de tab Updates: staat de vraag al in een gepubliceerde update?"""

    in_gepubliceerde_update: bool = False


class InitiatiefUpdatePostCreate(BaseModel):
    titel: str = Field(min_length=1, max_length=300)
    body: str | None = Field(None, max_length=50000)
    publish: bool = False  # if true, set published_at to now()
    # Vrijgegeven onderzoeksvragen van dit initiatief die de update meeneemt.
    vraag_ids: list[UUID] = Field(default_factory=list, max_length=200)
    # Vrijgegeven, afgeronde casussen van dit initiatief die de update meeneemt.
    casus_ids: list[UUID] = Field(default_factory=list, max_length=200)


class InitiatiefUpdatePostEdit(BaseModel):
    titel: str | None = Field(None, min_length=1, max_length=300)
    body: str | None = Field(None, max_length=50000)
    # Meegeven vervangt de hele lijst; weglaten laat hem staan.
    vraag_ids: list[UUID] | None = Field(None, max_length=200)
    casus_ids: list[UUID] | None = Field(None, max_length=200)


class InitiatiefUpdatePostResponse(BaseModel):
    id: UUID
    initiatief_id: UUID
    titel: str
    body: str | None = None
    published_at: datetime | None = None
    published_by_id: UUID | None = None
    published_by_naam: str | None = None
    vragen: list[PubliekeVraag] = Field(default_factory=list)
    casussen: list[PubliekeCasus] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PubliekeVraagBuiten(BaseModel):
    """Een beantwoorde vraag op de publieke pagina: de tekst, en het verslag
    als dat openbaar is."""

    vraag: str
    antwoord: str
    published_at: datetime
    verslag: PubliekVerslag | None = None


class PubliekeCasusBuiten(BaseModel):
    """Een afgeronde casus op de publieke pagina: alleen de tekst."""

    titel: str
    resultaat: str
    lessen: str | None = None
    published_at: datetime


class InitiatiefUpdatePostPublicResponse(BaseModel):
    """Subset of fields safe to expose on the public /c/:slug page."""

    titel: str
    body: str | None = None
    published_at: datetime
    published_by_naam: str | None = None
    vragen: list[PubliekeVraagBuiten] = Field(default_factory=list)
    casussen: list[PubliekeCasusBuiten] = Field(default_factory=list)
