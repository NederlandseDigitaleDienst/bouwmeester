"""Beantwoorde onderzoeksvragen die naar buiten mogen.

Casussen zijn nooit publiek. Wat van een onderzoeksvraag naar buiten gaat, is
alleen de publieke tekst (vraag en antwoord) die iemand bewust vrijgaf, en
alleen zolang de vraag afgerond is. Deze module is de enige plek die bepaalt
welke vragen dat zijn; de tab Updates, de publieke pagina en de mailbrief
lezen allemaal hier.

Het onderzoeksverslag gaat mee als de vraag naar buiten mag en iemand akkoord
gaf voor het verslag zelf (openbaar_op). Trekt iemand de vraag in, dan gaat
het verslag vanzelf mee terug naar binnen.
"""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bouwmeester.models.casus import Casus
from bouwmeester.models.issue import Issue
from bouwmeester.models.onderzoeksverslag import Onderzoeksverslag
from bouwmeester.schema.initiatief_update import PubliekeVraag, PubliekeVraagBuiten
from bouwmeester.schema.onderzoeksverslag import PubliekVerslag


def is_buiten(issue: Issue) -> bool:
    """Mag deze vraag nu naar buiten? Vrijgegeven, afgerond, met tekst.

    Hetzelfde als _buiten_filter, maar dan voor een geladen vraag.
    """
    return (
        issue.published_at is not None
        and issue.status == "done"
        and issue.is_onderzoeksvraag
        and bool((issue.public_title or "").strip())
        and bool((issue.public_answer or "").strip())
    )


def is_buiten_bij(issue: Issue, initiatief_id: UUID) -> bool:
    """is_buiten, en de vraag hoort (nog) bij dit initiatief.

    Verhuizen kan nu alleen binnen een initiatief, maar een update toont
    nooit een vraag van een ander initiatief, ook niet als dat ooit kan.
    Vraagt een geladen `issue.casus`: hoort de vraag bij een casus, dan telt
    ook het initiatief van die casus.
    """
    if not is_buiten(issue) or issue.initiatief_id != initiatief_id:
        return False
    return issue.casus is None or issue.casus.initiatief_id == initiatief_id


def _van_initiatief(initiatief_id: UUID):
    """De vraag hoort bij dit initiatief, en zijn casus (als hij er een heeft)
    ook. Vraagt een outer join op Casus."""
    return (
        Issue.initiatief_id == initiatief_id,
        or_(Issue.casus_id.is_(None), Casus.initiatief_id == initiatief_id),
    )


def _buiten_filter():
    return (
        Issue.published_at.is_not(None),
        Issue.status == "done",
        Issue.is_onderzoeksvraag.is_(True),
        func.length(func.trim(Issue.public_title)) > 0,
        func.length(func.trim(Issue.public_answer)) > 0,
    )


async def vrijgegeven_vragen(db: AsyncSession, initiatief_id: UUID) -> list[Issue]:
    """Alle vragen van dit initiatief die nu naar buiten mogen, nieuwste eerst."""
    stmt = (
        select(Issue)
        .outerjoin(Casus, Casus.id == Issue.casus_id)
        .where(*_van_initiatief(initiatief_id), *_buiten_filter())
        .options(selectinload(Issue.verslag), selectinload(Issue.casus))
        .order_by(Issue.published_at.desc(), Issue.id)
    )
    return list((await db.execute(stmt)).scalars().all())


async def publiek_verslag_bestand(
    db: AsyncSession, initiatief_id: UUID, verslag_id: UUID
) -> Onderzoeksverslag | None:
    """Het verslag als het nu op de publieke pagina van dit initiatief staat.

    Akkoord gegeven, en de vraag mag naar buiten. Anders None, zonder
    onderscheid: wie raadt, leert niets over wat er binnen bestaat.
    """
    stmt = (
        select(Onderzoeksverslag)
        .join(Issue, Issue.id == Onderzoeksverslag.issue_id)
        .outerjoin(Casus, Casus.id == Issue.casus_id)
        .where(
            Onderzoeksverslag.id == verslag_id,
            Onderzoeksverslag.openbaar_op.is_not(None),
            *_van_initiatief(initiatief_id),
            *_buiten_filter(),
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def publiek_verslag(issue: Issue) -> PubliekVerslag | None:
    """Het verslag van een vraag die naar buiten mag, als het openbaar is.

    Vraagt een geladen `issue.verslag`.
    """
    v = issue.verslag
    if v is None or v.openbaar_op is None:
        return None
    return PubliekVerslag(
        id=v.id,
        bestandsnaam=v.bestandsnaam,
        content_type=v.content_type,
        bestandsgrootte=v.bestandsgrootte,
    )


async def vragen_voor_update(
    db: AsyncSession, initiatief_id: UUID, vraag_ids: list[UUID]
) -> list[Issue]:
    """De vragen die een update meeneemt; 400 als er één niet mag.

    Alleen vrijgegeven vragen van hetzelfde initiatief. Een onbekende vraag en
    een vraag van een ander initiatief geven dezelfde melding, zodat het
    bestaan van andermans vragen niet lekt.
    """
    uniek = list(dict.fromkeys(vraag_ids))
    if not uniek:
        return []
    toegestaan = {i.id: i for i in await vrijgegeven_vragen(db, initiatief_id)}
    if any(vid not in toegestaan for vid in uniek):
        raise HTTPException(
            status_code=400,
            detail=(
                "Een update neemt alleen vrijgegeven, beantwoorde "
                "onderzoeksvragen van dit initiatief mee"
            ),
        )
    return [toegestaan[vid] for vid in uniek]


def als_publieke_vraag(issue: Issue) -> PubliekeVraag:
    return PubliekeVraag(
        id=issue.id,
        vraag=issue.public_title or "",
        antwoord=issue.public_answer or "",
        published_at=issue.published_at,
        verslag=publiek_verslag(issue),
    )


def als_vraag_buiten(issue: Issue) -> PubliekeVraagBuiten:
    return PubliekeVraagBuiten(
        vraag=issue.public_title or "",
        antwoord=issue.public_answer or "",
        published_at=issue.published_at,
        verslag=publiek_verslag(issue),
    )
