"""Repository voor casussoorten en hun koppeling aan casussen."""

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from bouwmeester.models.casus_soort import CasusCasusSoort, CasusSoort
from bouwmeester.schema.casus_soort import CasusSoortCreate, CasusSoortUpdate


class CasusSoortRepository:
    def __init__(self, session):
        self.session = session

    async def list_for_initiatief(self, initiatief_id: UUID) -> list[CasusSoort]:
        stmt = (
            select(CasusSoort)
            .where(CasusSoort.initiatief_id == initiatief_id)
            .order_by(CasusSoort.sort_order.asc(), CasusSoort.naam.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def casus_counts(self, initiatief_id: UUID) -> dict[UUID, int]:
        stmt = (
            select(CasusCasusSoort.casus_soort_id, func.count())
            .join(CasusSoort, CasusSoort.id == CasusCasusSoort.casus_soort_id)
            .where(CasusSoort.initiatief_id == initiatief_id)
            .group_by(CasusCasusSoort.casus_soort_id)
        )
        return {sid: n for sid, n in (await self.session.execute(stmt)).all()}

    async def get_in_initiatief(
        self, initiatief_id: UUID, soort_id: UUID
    ) -> CasusSoort | None:
        soort = await self.session.get(CasusSoort, soort_id)
        if soort is None or soort.initiatief_id != initiatief_id:
            return None
        return soort

    async def naam_bestaat(
        self, initiatief_id: UUID, naam: str, behalve: UUID | None = None
    ) -> bool:
        """Hoofdletters tellen niet: "Wetgeving" en "wetgeving" zijn dezelfde."""
        stmt = select(CasusSoort.id).where(
            CasusSoort.initiatief_id == initiatief_id,
            func.lower(CasusSoort.naam) == naam.lower(),
        )
        if behalve is not None:
            stmt = stmt.where(CasusSoort.id != behalve)
        return (await self.session.execute(stmt)).first() is not None

    async def create(self, initiatief_id: UUID, data: CasusSoortCreate) -> CasusSoort:
        max_stmt = select(func.coalesce(func.max(CasusSoort.sort_order), -1)).where(
            CasusSoort.initiatief_id == initiatief_id
        )
        volgende = (await self.session.execute(max_stmt)).scalar_one() + 1
        soort = CasusSoort(
            initiatief_id=initiatief_id,
            naam=data.naam,
            kleur=data.kleur,
            uitleg=data.uitleg,
            hoe_ver=data.hoe_ver,
            start_eisen=data.start_eisen,
            eind_eisen=data.eind_eisen,
            sort_order=volgende,
        )
        self.session.add(soort)
        await self.session.flush()
        await self.session.refresh(soort)
        return soort

    async def update(self, soort: CasusSoort, data: CasusSoortUpdate) -> CasusSoort:
        for key, value in data.model_dump(exclude_unset=True).items():
            # Naam, kleur en de eisen blijven staan bij null; uitleg en
            # "hoe ver" mogen leeg worden.
            if value is not None or key in ("uitleg", "hoe_ver"):
                setattr(soort, key, value)
        await self.session.flush()
        await self.session.refresh(soort)
        return soort

    async def delete(self, soort: CasusSoort) -> None:
        await self.session.delete(soort)
        await self.session.flush()

    async def reorder(
        self, initiatief_id: UUID, soort_ids: list[UUID]
    ) -> list[CasusSoort]:
        soorten = await self.list_for_initiatief(initiatief_id)
        by_id = {s.id: s for s in soorten}
        if set(soort_ids) != set(by_id) or len(soort_ids) != len(by_id):
            raise ValueError(
                "soort_ids komt niet overeen met de soorten van dit initiatief"
            )
        for idx, sid in enumerate(soort_ids):
            by_id[sid].sort_order = idx
        await self.session.flush()
        return await self.list_for_initiatief(initiatief_id)

    async def voor_casus(self, casus_id: UUID) -> list[CasusSoort]:
        stmt = (
            select(CasusSoort)
            .join(CasusCasusSoort, CasusCasusSoort.casus_soort_id == CasusSoort.id)
            .where(CasusCasusSoort.casus_id == casus_id)
            .order_by(CasusSoort.sort_order.asc(), CasusSoort.naam.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def zet_voor_casus(self, casus_id: UUID, soort_ids: list[UUID]) -> None:
        """Vervang de soorten van een casus. De route controleert de ids.

        Bestand tegen twee gelijke verzoeken tegelijk (een dubbele klik): wat
        al gekoppeld is, wordt niet nog eens ingevoegd (ON CONFLICT DO
        NOTHING), en alleen wat eraf moet wordt verwijderd.
        """
        gewenst = list(dict.fromkeys(soort_ids))
        weg = delete(CasusCasusSoort).where(CasusCasusSoort.casus_id == casus_id)
        if gewenst:
            weg = weg.where(CasusCasusSoort.casus_soort_id.notin_(gewenst))
        await self.session.execute(weg)
        if gewenst:
            await self.session.execute(
                insert(CasusCasusSoort)
                .values(
                    [{"casus_id": casus_id, "casus_soort_id": sid} for sid in gewenst]
                )
                .on_conflict_do_nothing()
            )
        await self.session.flush()
