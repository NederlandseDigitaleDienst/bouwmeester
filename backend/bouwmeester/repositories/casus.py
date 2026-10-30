"""Repository voor Casus: starten vanuit een lead, lijst, detail, team."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    apply_initiatief_filter,
)
from bouwmeester.models.casus import Casus
from bouwmeester.models.lead import Lead
from bouwmeester.models.lead_column import LeadColumn
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.repositories.base import BaseRepository
from bouwmeester.schema.casus import CASUSTEAM_ROLLEN, START_VANUIT_STAGE, CasusUpdate


def _casus_options():
    return [
        selectinload(Casus.initiatief),
        selectinload(Casus.lead),
        selectinload(Casus.soorten),
    ]


class CasusRepository(BaseRepository[Casus]):
    model = Casus

    async def get(self, id: UUID) -> Casus | None:
        stmt = select(Casus).where(Casus.id == id).options(*_casus_options())
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_lead(self, lead_id: UUID) -> Casus | None:
        stmt = select(Casus).where(Casus.lead_id == lead_id).options(*_casus_options())
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_all(
        self,
        initiatief_id: UUID | None = None,
        *,
        init_ctx: InitiatiefContext | None = None,
    ) -> list[Casus]:
        stmt = (
            select(Casus).options(*_casus_options()).order_by(Casus.created_at.desc())
        )
        if initiatief_id is not None:
            stmt = stmt.where(Casus.initiatief_id == initiatief_id)
        stmt = apply_initiatief_filter(stmt, Casus.initiatief_id, init_ctx)
        return list((await self.session.execute(stmt)).scalars().all())

    async def start_stage_for_lead(self, lead: Lead) -> str:
        """De kolom van waaruit deze lead een casus mag worden (dummy-regel).

        De standaardkolom `in_the_pocket` als het initiatief die heeft, anders
        de laatste kolom in de volgorde. Leads zonder initiatief: de standaard.
        """
        if lead.initiatief_id is None:
            return START_VANUIT_STAGE
        stmt = (
            select(LeadColumn.slug)
            .where(LeadColumn.initiatief_id == lead.initiatief_id)
            .order_by(LeadColumn.sort_order.asc())
        )
        slugs = list((await self.session.execute(stmt)).scalars().all())
        if not slugs or START_VANUIT_STAGE in slugs:
            return START_VANUIT_STAGE
        return slugs[-1]

    async def start_from_lead(
        self,
        lead: Lead,
        *,
        startvoorwaarden: dict,
        started_by_id: UUID | None,
        fase: str = "start",
    ) -> Casus:
        casus = Casus(
            fase=fase,
            lead_id=lead.id,
            initiatief_id=lead.initiatief_id,
            title=lead.title,
            description=lead.description,
            organization=lead.organization,
            startvoorwaarden=startvoorwaarden,
            started_by_id=started_by_id,
        )
        self.session.add(casus)
        await self.session.flush()
        await self.session.refresh(
            casus, attribute_names=["initiatief", "lead", "soorten"]
        )
        return casus

    async def update(self, id: UUID, data: CasusUpdate) -> Casus | None:
        casus = await self.get(id)
        if casus is None:
            return None
        values = data.model_dump(exclude_unset=True, by_alias=True)
        for key, value in values.items():
            setattr(casus, key, value)
        await self.session.flush()
        await self.session.refresh(
            casus, attribute_names=["updated_at", "initiatief", "lead"]
        )
        return casus

    async def list_team(self, casus_id: UUID) -> list[ResourcePermission]:
        stmt = (
            select(ResourcePermission)
            .where(
                ResourcePermission.resource_type == "casus",
                ResourcePermission.resource_id == casus_id,
                ResourcePermission.rol.in_(CASUSTEAM_ROLLEN),
            )
            .options(selectinload(ResourcePermission.person))
            .order_by(
                ResourcePermission.rol.desc(), ResourcePermission.created_at.asc()
            )
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def team_summary(
        self, casus_ids: list[UUID]
    ) -> dict[UUID, tuple[str | None, int]]:
        """Per casus: (naam van de trekker, aantal teamleden incl. trekker)."""
        if not casus_ids:
            return {}
        stmt = (
            select(ResourcePermission)
            .where(
                ResourcePermission.resource_type == "casus",
                ResourcePermission.resource_id.in_(casus_ids),
                ResourcePermission.rol.in_(CASUSTEAM_ROLLEN),
            )
            .options(selectinload(ResourcePermission.person))
        )
        out: dict[UUID, tuple[str | None, int]] = {}
        for rp in (await self.session.execute(stmt)).scalars().all():
            trekker, n = out.get(rp.resource_id, (None, 0))
            if rp.rol == "trekker" and rp.person is not None:
                trekker = rp.person.naam
            out[rp.resource_id] = (trekker, n + 1)
        return out
