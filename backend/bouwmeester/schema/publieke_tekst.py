"""Controles voor tekst die naar buiten gaat (vraag, casus, update).

Alles wat op de publieke pagina of in de mailbrief komt, schrijft iemand
bewust. Twee regels gelden overal: spaties eromheen gaan eraf vóór de
lengtecontrole (alleen spaties is leeg), en een @- of #-verwijzing uit de
editor wordt geweigerd, want die zet een naam, een taaktitel en een id in de
tekst.

Bij het schrijven weigert `geen_verwijzingen` zo'n verwijzing. Wat er al
eerder stond, of in een tekst die niet voor buiten geschreven is (de
beschrijving van het initiatief), maakt `verwijzingen_als_tekst` onschadelijk
op het moment dat het naar buiten gaat: de link met het id gaat eraf.
"""

import re

# Een @- of #-verwijzing uit de editor: [@Naam](user:<id>), [#Taak](task:<id>).
# Markdown laat spaties en punthaken toe voor het doel van een link, dus
# [@Naam]( user:<id>) en [@Naam](<user:<id>>) tellen ook.
_VERWIJZING = re.compile(r"\]\(\s*<?\s*(?:user|org|node|task):", re.IGNORECASE)

# De hele verwijzing: het label (dat \] of \[ kan bevatten, zie
# frontend/src/utils/mentions.ts) en het doel tot de sluitende haak.
_HELE_VERWIJZING = re.compile(
    r"\[((?:\\.|[^\]\\])*)\]\(\s*<?\s*(?:user|org|node|task):[^)]*\)",
    re.IGNORECASE,
)
# Wat daarna nog over is (een verwijzing zonder sluitende haak): alleen het
# doel eraf.
_REST_VAN_VERWIJZING = re.compile(
    r"\]\(\s*<?\s*(?:user|org|node|task):[^)\s]*\)?", re.IGNORECASE
)


def zonder_witruimte(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def geen_verwijzingen(value: str | None) -> str | None:
    if value and _VERWIJZING.search(value):
        raise ValueError(
            "Een publieke tekst mag geen verwijzing met @ of # bevatten: "
            "die noemt een persoon, organisatie of intern werk"
        )
    return value


def verwijzingen_als_tekst(value: str | None) -> str | None:
    """Een verwijzing wordt gewone tekst: het label blijft, het id gaat eraf.

    `[@Anne](user:<id>)` wordt `@Anne`. Voor alles wat naar buiten gaat, ook
    als het bij het schrijven al door `geen_verwijzingen` kwam: tekst van
    vóór die controle, en tekst die niet voor buiten geschreven is.
    """
    if not value:
        return value
    tekst = _HELE_VERWIJZING.sub(
        lambda m: re.sub(r"\\([\[\]\\])", r"\1", m.group(1)), value
    )
    return _REST_VAN_VERWIJZING.sub("]", tekst)
