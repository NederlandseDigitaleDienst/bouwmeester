"""Afgeronde casussen die naar buiten mogen, met hun lessen.

Casussen zijn nooit publiek. Van een afgeronde casus gaat alleen een tekst
naar buiten die iemand daarvoor schreef en bewust vrijgaf (public_title,
public_resultaat, public_lessen), en alleen zolang de casus in de laatste
fase van de funnel staat. Deze module is de enige plek die bepaalt welke
casussen dat zijn, net als services/publieke_vragen.py voor de vragen.
"""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.models.casus import Casus
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.schema.casus_fases import geldende_casus_fases
from bouwmeester.schema.initiatief_update import PubliekeCasus, PubliekeCasusBuiten


def laatste_fase(initiatief: Initiatief | None) -> str | None:
    """De id van de laatste fase van de funnel: daar is een casus afgerond."""
    if initiatief is None:
        return None
    fases = geldende_casus_fases(initiatief.casus_fases)
    return fases[-1].id if fases else None


def is_afgerond(casus: Casus, laatste: str | None) -> bool:
    return laatste is not None and casus.fase == laatste


def is_casus_buiten(casus: Casus, laatste: str | None) -> bool:
    """Mag deze casus nu naar buiten? Vrijgegeven, afgerond, met tekst."""
    return (
        casus.published_at is not None
        and is_afgerond(casus, laatste)
        and bool((casus.public_title or "").strip())
        and bool((casus.public_resultaat or "").strip())
    )


def is_casus_buiten_bij(casus: Casus, initiatief_id: UUID, laatste: str | None) -> bool:
    """is_casus_buiten, en de casus hoort bij dit initiatief."""
    return casus.initiatief_id == initiatief_id and is_casus_buiten(casus, laatste)


def trek_casus_in_als_niet_af(casus: Casus, laatste: str | None) -> bool:
    """Een vrijgegeven casus die uit de laatste fase gaat, gaat terug naar
    binnen. De tekst blijft bewaard; opnieuw afronden geeft hem niet vanzelf
    weer vrij. True als hij nu werd ingetrokken."""
    if casus.published_at is None or is_afgerond(casus, laatste):
        return False
    casus.published_at = None
    return True


def _buiten_filter(initiatief: Initiatief):
    return (
        Casus.initiatief_id == initiatief.id,
        Casus.fase == (laatste_fase(initiatief) or ""),
        Casus.published_at.is_not(None),
        func.length(func.trim(Casus.public_title)) > 0,
        func.length(func.trim(Casus.public_resultaat)) > 0,
    )


async def vrijgegeven_casussen(db: AsyncSession, initiatief: Initiatief) -> list[Casus]:
    """Alle casussen van dit initiatief die nu naar buiten mogen, nieuwste eerst."""
    stmt = (
        select(Casus)
        .where(*_buiten_filter(initiatief))
        .order_by(Casus.published_at.desc(), Casus.id)
    )
    return list((await db.execute(stmt)).scalars().all())


async def casussen_voor_update(
    db: AsyncSession, initiatief: Initiatief, casus_ids: list[UUID]
) -> list[Casus]:
    """De casussen die een update meeneemt; 400 als er één niet mag.

    Een onbekende casus, een casus van een ander initiatief en een niet
    vrijgegeven casus geven dezelfde melding.
    """
    uniek = list(dict.fromkeys(casus_ids))
    if not uniek:
        return []
    toegestaan = {c.id: c for c in await vrijgegeven_casussen(db, initiatief)}
    if any(cid not in toegestaan for cid in uniek):
        raise HTTPException(
            status_code=400,
            detail=(
                "Een update neemt alleen vrijgegeven, afgeronde casussen van "
                "dit initiatief mee"
            ),
        )
    return [toegestaan[cid] for cid in uniek]


def als_publieke_casus(casus: Casus) -> PubliekeCasus:
    return PubliekeCasus(
        id=casus.id,
        titel=casus.public_title or "",
        resultaat=casus.public_resultaat or "",
        lessen=casus.public_lessen or None,
        published_at=casus.published_at,
    )


def als_casus_buiten(casus: Casus) -> PubliekeCasusBuiten:
    return PubliekeCasusBuiten(
        titel=casus.public_title or "",
        resultaat=casus.public_resultaat or "",
        lessen=casus.public_lessen or None,
        published_at=casus.published_at,
    )
