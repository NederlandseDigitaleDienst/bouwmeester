"""Startvragen: wat je beantwoordt als je een casus start.

Per initiatief te beheren in de instellingen (initiatief.startvragen); leeg
betekent de standaardlijst hieronder. Elke vraag heeft een antwoordtype:
ja/nee, één keuze, meer keuzes of een vrij veld, en kan verplicht zijn en
op het casuskaartje staan.

De vraag of een casus intern is of een satellietcasus (CASUSTYPE_ID) is vast:
hij bepaalt of de acceptatiecriteria volgen. Tekst en antwoorden liggen vast,
weghalen kan niet; alleen de plek in de lijst en "op het kaartje" zijn vrij.
Zijn antwoord staat in startvoorwaarden.casustype, de andere antwoorden in
startvoorwaarden.antwoorden, als momentopname met de vraag zoals hij toen
luidde.
"""

import enum
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator, model_validator

CASUSTYPE_ID = "casustype"
ID_PATROON = r"^[a-z0-9_]{1,40}$"
MAX_VRAGEN = 30


class Antwoordtype(enum.StrEnum):
    ja_nee = "ja_nee"
    een_keuze = "een_keuze"
    meer_keuzes = "meer_keuzes"
    vrij = "vrij"


class Startvraag(BaseModel):
    """Eén startvraag zoals het initiatief hem stelt."""

    id: str = Field(pattern=ID_PATROON)
    vraag: str = Field(min_length=1, max_length=300)
    antwoordtype: Antwoordtype
    # Alleen bij een of meer keuzes: de keuzes, in volgorde.
    opties: list[str] = Field(default_factory=list, max_length=20)
    verplicht: bool = True
    op_kaartje: bool = False

    @field_validator("vraag")
    @classmethod
    def _strip_vraag(cls, vraag: str) -> str:
        vraag = vraag.strip()
        if not vraag:
            raise ValueError("Een vraag mag niet leeg zijn")
        return vraag

    @field_validator("opties")
    @classmethod
    def _strip_opties(cls, opties: list[str]) -> list[str]:
        schoon = list(dict.fromkeys(o.strip() for o in opties if o and o.strip()))
        if any(len(o) > 200 for o in schoon):
            raise ValueError("Een keuze is maximaal 200 tekens")
        return schoon

    @model_validator(mode="after")
    def _opties_passen_bij_type(self) -> "Startvraag":
        keuzes = (Antwoordtype.een_keuze, Antwoordtype.meer_keuzes)
        if self.antwoordtype in keuzes and len(self.opties) < 2:
            raise ValueError(f"'{self.vraag}' heeft minstens twee keuzes nodig")
        if self.antwoordtype not in keuzes and self.opties:
            raise ValueError(f"'{self.vraag}' heeft geen keuzes")
        if self.antwoordtype == Antwoordtype.vrij and self.op_kaartje:
            raise ValueError("Een vrij antwoord past niet op het kaartje")
        return self


CASUSTYPE_VRAAG = Startvraag(
    id=CASUSTYPE_ID,
    vraag="Is het een interne casus of een satellietcasus?",
    antwoordtype=Antwoordtype.een_keuze,
    opties=["Interne casus", "Satellietcasus"],
    verplicht=True,
    op_kaartje=True,
)

# De standaardlijst, zolang een initiatief geen eigen lijst heeft. "Is het
# ons terrein?" voegde niets toe en "Tot hoever brengen we het?" zegt de
# casussoort al; die twee zijn eruit.
DEFAULT_STARTVRAGEN: tuple[Startvraag, ...] = (
    CASUSTYPE_VRAAG,
    Startvraag(
        id="schakels",
        vraag="Op welke schakels maken we impact?",
        antwoordtype=Antwoordtype.meer_keuzes,
        opties=[
            "Ontwikkelen en simuleren van beleidswensen en wetsvoorstellen",
            "Uitvoeringstoets",
            "Behandeling in het wetgevingsproces",
            "Publiceren",
            "Regelbeheer",
            "Uitvoeringssystemen",
            "Dienstverlening",
            "Rechtsbescherming",
        ],
    ),
)


def controleer_lijst(vragen: list[Startvraag]) -> list[Startvraag]:
    """Een lijst uit de instellingen: unieke id's en de vaste vraag erin.

    De vaste vraag houdt zijn tekst en antwoorden; alleen plek en
    "op het kaartje" neemt hij over uit wat er binnenkomt.
    """
    if len(vragen) > MAX_VRAGEN:
        raise ValueError(f"Maximaal {MAX_VRAGEN} startvragen")
    ids = [v.id for v in vragen]
    if len(ids) != len(set(ids)):
        raise ValueError("Elke startvraag heeft een eigen id")
    if CASUSTYPE_ID not in ids:
        raise ValueError(
            "De vraag of het een interne casus of een satellietcasus is, blijft staan"
        )
    return [
        CASUSTYPE_VRAAG.model_copy(update={"op_kaartje": v.op_kaartje})
        if v.id == CASUSTYPE_ID
        else v
        for v in vragen
    ]


def geldende_startvragen(opgeslagen: list[Any] | None) -> list[Startvraag]:
    """De vragen die gelden: de eigen lijst, anders de standaardlijst."""
    if not opgeslagen:
        return list(DEFAULT_STARTVRAGEN)
    return [Startvraag.model_validate(v) for v in opgeslagen]


class StartAntwoord(BaseModel):
    """Het antwoord op één startvraag.

    De client stuurt `vraag_id` en `waarde`; vraag en antwoordtype vult de
    route aan uit de startvragen van het initiatief, als momentopname.
    """

    vraag_id: str = Field(pattern=ID_PATROON)
    vraag: str | None = Field(None, max_length=300)
    antwoordtype: Antwoordtype | None = None
    # Begrensd op wat een vraag kan vragen: een vrij antwoord, of keuzes
    # (maximaal 20, elk maximaal 200 tekens).
    waarde: (
        bool
        | Annotated[str, Field(max_length=5000)]
        | Annotated[list[Annotated[str, Field(max_length=200)]], Field(max_length=20)]
        | None
    ) = None


def _leeg(waarde: Any) -> bool:
    return waarde is None or waarde == "" or waarde == []


def controleer_antwoorden(
    vragen: list[Startvraag], antwoorden: list[StartAntwoord], casustype: str | None
) -> list[dict[str, Any]]:
    """Toets de antwoorden aan de vragen; geeft de momentopname terug.

    Per vraag een antwoord van het juiste type; een keuze uit de opties;
    verplichte vragen beantwoord. Onbekende vragen en de vaste vraag (die
    heeft zijn eigen veld) horen er niet tussen. ValueError bij een fout.
    """
    per_id: dict[str, StartAntwoord] = {}
    for a in antwoorden:
        if a.vraag_id in per_id:
            raise ValueError("Elke vraag krijgt één antwoord")
        per_id[a.vraag_id] = a
    bekend = {v.id for v in vragen}
    onbekend = [vid for vid in per_id if vid not in bekend or vid == CASUSTYPE_ID]
    if onbekend:
        raise ValueError(f"Onbekende startvraag: {onbekend[0]}")

    uit: list[dict[str, Any]] = []
    for v in vragen:
        if v.id == CASUSTYPE_ID:
            if v.verplicht and not casustype:
                raise ValueError(f"Beantwoord: {v.vraag}")
            continue
        a = per_id.get(v.id)
        waarde = a.waarde if a else None
        if isinstance(waarde, str):
            waarde = waarde.strip()
        if _leeg(waarde):
            if v.verplicht:
                raise ValueError(f"Beantwoord: {v.vraag}")
            continue
        if v.antwoordtype == Antwoordtype.ja_nee and not isinstance(waarde, bool):
            raise ValueError(f"'{v.vraag}' is een ja/nee-vraag")
        if v.antwoordtype == Antwoordtype.een_keuze and waarde not in v.opties:
            raise ValueError(f"Kies bij '{v.vraag}' een van de keuzes")
        if v.antwoordtype == Antwoordtype.meer_keuzes:
            if not isinstance(waarde, list) or any(w not in v.opties for w in waarde):
                raise ValueError(f"Kies bij '{v.vraag}' uit de keuzes")
            # In de volgorde van de keuzes, elke keuze één keer.
            waarde = [o for o in v.opties if o in waarde]
        if v.antwoordtype == Antwoordtype.vrij:
            if not isinstance(waarde, str):
                raise ValueError(f"'{v.vraag}' vraagt om tekst")
            if len(waarde) > 5000:
                raise ValueError(f"Het antwoord op '{v.vraag}' is te lang")
        uit.append(
            {
                "vraag_id": v.id,
                "vraag": v.vraag,
                "antwoordtype": v.antwoordtype.value,
                "waarde": waarde,
            }
        )
    return uit
