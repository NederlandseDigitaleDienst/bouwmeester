"""Controles voor tekst die naar buiten gaat (vraag, casus, update).

Alles wat op de publieke pagina of in de mailbrief komt, schrijft iemand
bewust. Twee regels gelden overal: spaties eromheen gaan eraf vóór de
lengtecontrole (alleen spaties is leeg), en een @- of #-verwijzing uit de
editor wordt geweigerd, want die zet een naam, een taaktitel en een id in de
tekst.
"""

import re

# Een @- of #-verwijzing uit de editor: [@Naam](user:<id>), [#Taak](task:<id>).
_VERWIJZING = re.compile(r"\]\((?:user|org|node|task):", re.IGNORECASE)


def zonder_witruimte(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def geen_verwijzingen(value: str | None) -> str | None:
    if value and _VERWIJZING.search(value):
        raise ValueError(
            "Een publieke tekst mag geen verwijzing met @ of # bevatten: "
            "die noemt een persoon, organisatie of intern werk"
        )
    return value
