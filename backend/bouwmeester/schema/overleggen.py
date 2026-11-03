"""Het ritme van een initiatief: de vaste overleggen van het team.

Per initiatief te beheren in de instellingen (initiatief.overleggen), alleen
door de eigenaar. Leeg betekent dat er nog niets is vastgelegd. Er is bewust
geen standaardlijst: hoe vaak een team samenkomt verschilt per initiatief.

Een overleg is tekst om te lezen, geen agenda. `wanneer` is vrij ("om de
week, di 9.00 tot 11.00"). `vastgesteld` staat uit als het overleg wel
besloten is maar het moment nog niet; de tab RegelRitme toont het dan als
open punt. De publieke pagina toont geen overleggen.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator

OVERLEG_ID_PATROON = r"^[a-z0-9_]{1,40}$"
MAX_OVERLEGGEN = 20


class Overleg(BaseModel):
    """Eén vast overleg van het team."""

    id: str = Field(pattern=OVERLEG_ID_PATROON)
    naam: str = Field(min_length=1, max_length=80)
    wanneer: str | None = Field(None, max_length=120)
    wie: str | None = Field(None, max_length=120)
    waarvoor: str | None = Field(None, max_length=500)
    vastgesteld: bool = True

    @field_validator("naam")
    @classmethod
    def _strip_naam(cls, naam: str) -> str:
        naam = naam.strip()
        if not naam:
            raise ValueError("Een overleg heeft een naam")
        return naam

    @field_validator("wanneer", "wie", "waarvoor")
    @classmethod
    def _strip_tekst(cls, tekst: str | None) -> str | None:
        if tekst is None:
            return None
        return tekst.strip() or None


def controleer_overleggen(overleggen: list[Overleg]) -> list[Overleg]:
    """Een lijst uit de instellingen: niet te lang, elk overleg een eigen id."""
    if len(overleggen) > MAX_OVERLEGGEN:
        raise ValueError(f"Maximaal {MAX_OVERLEGGEN} overleggen")
    ids = [o.id for o in overleggen]
    if len(ids) != len(set(ids)):
        raise ValueError("Elk overleg heeft een eigen id")
    return overleggen


def geldende_overleggen(opgeslagen: list[Any] | None) -> list[Overleg]:
    """De opgeslagen overleggen, of een lege lijst."""
    return [
        o if isinstance(o, Overleg) else Overleg.model_validate(o)
        for o in opgeslagen or []
    ]
