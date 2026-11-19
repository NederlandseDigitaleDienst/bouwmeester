"""Waar werk bij hoort: een casus, of alleen een initiatief.

Een onderzoeksvraag hoort altijd bij een initiatief en meestal bij een casus.
Een vraag zonder casus en de taken eronder volgen de rechten van het
initiatief. Op de plekken die voor een casustaak de casus ophalen (zien,
wijzigen, uitvoerder lid van het initiatief) staat voor zo'n vraag een
InitiatiefWerk: het heeft wat die controles van een casus gebruiken
(initiatief_id, id en title), met id leeg. Zo is er geen trekker en tellen
alleen bijdrager en eigenaar van het initiatief.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.models.casus import Casus
from bouwmeester.models.issue import Issue


@dataclass(frozen=True)
class InitiatiefWerk:
    """Werk van een initiatief zonder casus: een vraag en zijn taken."""

    initiatief_id: UUID
    id: None = None
    title: str = "Zonder casus"


Werkplek = Casus | InitiatiefWerk


async def werkplek_van_issue(db: AsyncSession, issue: Issue) -> Werkplek | None:
    if issue.casus_id is not None:
        return await db.get(Casus, issue.casus_id)
    if issue.initiatief_id is not None:
        return InitiatiefWerk(initiatief_id=issue.initiatief_id)
    return None


async def werkplek_van_taak(db: AsyncSession, task) -> Werkplek | None:
    """De casus van een taak, of het initiatief van haar vraag zonder casus.

    None: een taak aan een node, zonder casus en zonder vraag.
    """
    if task.casus_id is not None:
        return await db.get(Casus, task.casus_id)
    if task.issue_id is not None:
        issue = await db.get(Issue, task.issue_id)
        if issue is not None:
            return await werkplek_van_issue(db, issue)
    return None
