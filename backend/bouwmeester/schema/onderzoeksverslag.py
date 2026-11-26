"""Pydantic schemas voor het onderzoeksverslag bij een onderzoeksvraag."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class OnderzoeksverslagResponse(BaseModel):
    """Het verslag zoals leden van het initiatief het zien."""

    id: UUID
    bestandsnaam: str
    content_type: str
    bestandsgrootte: int
    uploaded_by_naam: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    # Akkoord om naar buiten te gaan; leeg is binnen.
    openbaar_op: datetime | None = None
    openbaar_door_naam: str | None = None


class OpenbaarAkkoord(BaseModel):
    """Expliciet akkoord: "Dit verslag verschijnt op de publieke pagina.
    Akkoord?" Alleen `true` wordt aangenomen."""

    akkoord: Literal[True]


class PubliekVerslag(BaseModel):
    """Het verslag op de publieke pagina: alleen wat nodig is om het te
    downloaden. Geen uploader, geen pad."""

    id: UUID
    bestandsnaam: str
    content_type: str
    bestandsgrootte: int
