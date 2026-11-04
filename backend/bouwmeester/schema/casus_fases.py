"""De casusfunnel: de fases waar een casus doorheen gaat.

Per initiatief te beheren in de instellingen (initiatief.casus_fases); leeg
betekent het voorstel hieronder. Elke fase heeft een vaste id (in
casus.fase), een naam, een kleur, een omschrijving van wat er in die fase
gebeurt en wanneer een casus door mag naar de volgende ("door als"; bij de
laatste fase is dat "klaar als").

Een fase weghalen waar nog casussen in staan kan niet: de route weigert dat
met 409, zodat geen casus in een fase komt te staan die niet meer bestaat.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from bouwmeester.schema.lead_column import LEAD_COLUMN_COLORS

FASE_ID_PATROON = r"^[a-z0-9_]{1,40}$"
MIN_FASES = 1
MAX_FASES = 12


class CasusFaseDef(BaseModel):
    """Eén fase van de casusfunnel zoals het initiatief hem hanteert."""

    id: str = Field(pattern=FASE_ID_PATROON)
    naam: str = Field(min_length=1, max_length=60)
    kleur: str = "neutral"
    omschrijving: str | None = Field(None, max_length=1000)
    door_als: str | None = Field(None, max_length=500)

    @field_validator("naam")
    @classmethod
    def _strip_naam(cls, naam: str) -> str:
        naam = naam.strip()
        if not naam:
            raise ValueError("Een fase heeft een naam")
        return naam

    @field_validator("kleur")
    @classmethod
    def _check_kleur(cls, kleur: str) -> str:
        if kleur not in LEAD_COLUMN_COLORS:
            allowed = ", ".join(sorted(LEAD_COLUMN_COLORS))
            raise ValueError(f"kleur moet een van deze zijn: {allowed}")
        return kleur

    @field_validator("omschrijving", "door_als")
    @classmethod
    def _strip_tekst(cls, tekst: str | None) -> str | None:
        if tekst is None:
            return None
        return tekst.strip() or None


# Het voorstel (Floris, 29 oktober 2026), zolang een initiatief geen eigen
# funnel heeft. De ids blijven gelijk aan wat er al in casus.fase stond;
# "Werken in ritme" heet nu Uitvoeren (id uitvoeren, migratie e4a7c2b9f316).
DEFAULT_CASUS_FASES: tuple[CasusFaseDef, ...] = (
    CasusFaseDef(
        id="start",
        naam="Start",
        kleur="lintblauw",
        omschrijving=(
            "Opstarten met de analist (bij satelliet die van het satellietteam), "
            "afspraken met de partner vastleggen, en de scope bepalen: welke wet "
            "of welke artikelen, wat valt erbuiten, wat is het eindpunt concreet."
        ),
        door_als="de analist aan boord is en de scope op papier staat.",
    ),
    CasusFaseDef(
        id="scherpstellen",
        naam="Scherpstellen",
        kleur="hemelblauw",
        omschrijving=(
            "Binnen die scope de onderzoeksvragen of de toepassingsvraag "
            "formuleren en uitschrijven in user stories met acceptatiecriteria."
        ),
        door_als="er minstens één story klaarstaat.",
    ),
    CasusFaseDef(
        id="uitvoeren",
        naam="Uitvoeren",
        kleur="geel",
        omschrijving="Taken oppakken, demo en scopeoverleg om de twee weken.",
        door_als="alle stories af zijn volgens de DoD en de acceptatiecriteria.",
    ),
    CasusFaseDef(
        id="afronden",
        naam="Afronden",
        kleur="oranje",
        omschrijving="Onderzoeksverslag, afsluitende demo, RFC’s bijgewerkt.",
        door_als="verslag en demo er zijn voor elke onderzoeksvraag.",
    ),
    CasusFaseDef(
        id="delen",
        naam="Delen",
        kleur="paars",
        omschrijving=(
            "Open voortgangsdemo, publieke roadmap bijwerken, lessen in de "
            "gedeelde documentatie."
        ),
        door_als="de casus van buiten te volgen is.",
    ),
    CasusFaseDef(
        id="besluiten",
        naam="Besluiten",
        kleur="success",
        omschrijving=(
            "Stoppen, doorzetten naar het volgende eindpunt, overdragen, of van "
            "intern naar satelliet."
        ),
        door_als="het besluit vastligt.",
    ),
)


def controleer_fases(fases: list[CasusFaseDef]) -> list[CasusFaseDef]:
    """Een funnel uit de instellingen: genoeg fases, unieke ids en namen."""
    if not MIN_FASES <= len(fases) <= MAX_FASES:
        raise ValueError(f"Een funnel heeft {MIN_FASES} tot {MAX_FASES} fases")
    ids = [f.id for f in fases]
    if len(ids) != len(set(ids)):
        raise ValueError("Elke fase heeft een eigen id")
    namen = [f.naam.lower() for f in fases]
    if len(namen) != len(set(namen)):
        raise ValueError("Twee fases met dezelfde naam")
    return fases


def geldende_casus_fases(opgeslagen: list[Any] | None) -> list[CasusFaseDef]:
    """De fases die gelden: de eigen funnel, anders het voorstel."""
    if not opgeslagen:
        return list(DEFAULT_CASUS_FASES)
    return [
        f if isinstance(f, CasusFaseDef) else CasusFaseDef.model_validate(f)
        for f in opgeslagen
    ]


def eerste_fase(opgeslagen: list[Any] | None) -> str:
    """Waar een nieuwe casus begint: de eerste fase van de funnel."""
    return geldende_casus_fases(opgeslagen)[0].id
