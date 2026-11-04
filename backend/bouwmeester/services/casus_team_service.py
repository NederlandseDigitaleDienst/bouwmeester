"""Casusrollen volgen de rol op het initiatief.

Trekker geeft wijzigrechten op een casus, ook aan wie op het initiatief
alleen kijker is. Dat is bedoeld voor wie bewust als trekker is aangewezen.
Het mag niet zo zijn dat een bijdrager zichzelf trekker maakt en die
rechten houdt nadat hij kijker is gemaakt, of dat iemand die uit het
initiatief is gezet in een casusteam blijft staan (review #444, derde
ronde). Daarom, bij elke wijziging van een lidmaatschap of eenheidsrol:

- wie het initiatief niet meer ziet, gaat uit elk casusteam ervan;
- wie bijdrager of eigenaar was en nu lager staat, is geen trekker meer.

Alleen een rang die daadwerkelijk daalt telt. Een kijker die door een
eigenaar trekker is gemaakt, blijft trekker als er iets anders verandert.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.core.initiatief_context import initiatief_niveau
from bouwmeester.models.casus import Casus
from bouwmeester.models.person import Person
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.repositories.initiatief import InitiatiefRepository
from bouwmeester.schema.initiatief import EENHEID_ROL_RANK

BIJDRAGER = EENHEID_ROL_RANK["contributor"]


def _casusrollen(initiatief_id: UUID):
    return select(ResourcePermission).where(
        ResourcePermission.resource_type == "casus",
        ResourcePermission.resource_id.in_(
            select(Casus.id).where(Casus.initiatief_id == initiatief_id)
        ),
    )


async def personen_met_casusrol(db: AsyncSession, initiatief_id: UUID) -> list[UUID]:
    """Iedereen met een rij in een casusteam van dit initiatief."""
    stmt = _casusrollen(initiatief_id).with_only_columns(
        ResourcePermission.person_id.distinct()
    )
    return [pid for pid in (await db.execute(stmt)).scalars().all() if pid]


async def rangen(
    db: AsyncSession, initiatief_id: UUID, person_ids: list[UUID]
) -> dict[UUID, int]:
    """De rang (eigenaar 3, bijdrager 2, kijker 1, niets 0) per persoon."""
    uit: dict[UUID, int] = {}
    for pid in person_ids:
        person = await db.get(Person, pid)
        niveau = (
            await initiatief_niveau(db, initiatief_id, person)
            if person is not None
            else None
        )
        uit[pid] = EENHEID_ROL_RANK.get(niveau or "", 0)
    return uit


async def casusrollen_na_rolwijziging(
    db: AsyncSession, initiatief_id: UUID, rangen_voor: dict[UUID, int]
) -> list[tuple[UUID, UUID, str]]:
    """Pas de casusrollen aan op de nieuwe rang. Geeft (casus, persoon, rol)
    van elke verwijderde rij terug, zodat de route ze in het log kan zetten."""
    repo = InitiatiefRepository(db)
    weg: list[tuple[UUID, UUID, str]] = []
    for pid, voor in rangen_voor.items():
        if not await repo.is_member(initiatief_id, pid):
            stmt = _casusrollen(initiatief_id).where(
                ResourcePermission.person_id == pid
            )
        else:
            na = (await rangen(db, initiatief_id, [pid]))[pid]
            if not (voor >= BIJDRAGER > na):
                continue
            stmt = _casusrollen(initiatief_id).where(
                ResourcePermission.person_id == pid,
                ResourcePermission.rol == "trekker",
            )
        for rp in (await db.execute(stmt)).scalars().all():
            weg.append((rp.resource_id, pid, rp.rol))
            await db.delete(rp)
    if weg:
        await db.flush()
    return weg


async def rangen_voor_rij(db: AsyncSession, rp: ResourcePermission) -> dict[UUID, int]:
    """De rangen die een wijziging van deze initiatiefrij kan raken: de
    persoon zelf, of bij een eenheidsrij iedereen met een casusrol."""
    if rp.person_id is not None:
        return await rangen(db, rp.resource_id, [rp.person_id])
    return await rangen(
        db, rp.resource_id, await personen_met_casusrol(db, rp.resource_id)
    )


async def casusrollen_bijwerken(
    db: AsyncSession,
    initiatief_id: UUID,
    rangen_voor: dict[UUID, int],
    *,
    current_user=None,
    actor_id: UUID | None = None,
) -> None:
    """Na een rolwijziging: casusrollen die hun grond verloren gaan weg, met
    een regel in het log per rij. Voor de initiatiefroutes en de generieke
    toekenningsroutes, zodat beide paden hetzelfde doen."""
    from bouwmeester.services.activity_service import log_activity

    for casus_id, person_id, rol in await casusrollen_na_rolwijziging(
        db, initiatief_id, rangen_voor
    ):
        await log_activity(
            db,
            current_user,
            actor_id,
            "casus_team.removed",
            details={
                "casus_id": str(casus_id),
                "person_id": str(person_id),
                "rol": rol,
                "reden": "rol op het initiatief gewijzigd of ingetrokken",
            },
        )
