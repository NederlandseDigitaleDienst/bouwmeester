"""Repository for Initiatief CRUD and member/eenheid management."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from bouwmeester.core.initiatief_context import InitiatiefContext
from bouwmeester.core.query_utils import escape_like
from bouwmeester.core.slug import is_valid_slug, slugify
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.initiatief_update import InitiatiefUpdatePost
from bouwmeester.models.lead import Lead
from bouwmeester.models.lead_column import LeadColumn
from bouwmeester.models.person import Person
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.repositories.base import BaseRepository
from bouwmeester.schema.initiatief import (
    EENHEID_ROL_RANK,
    InitiatiefCreate,
    InitiatiefSettingsUpdate,
    InitiatiefUpdate,
)


class InitiatiefRepository(BaseRepository[Initiatief]):
    model = Initiatief

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        search: str | None = None,
        init_ctx: InitiatiefContext | None = None,
    ) -> list[Initiatief]:
        stmt = select(Initiatief).offset(skip).limit(limit)
        if search:
            escaped = escape_like(search)
            pattern = f"%{escaped}%"
            stmt = stmt.where(Initiatief.naam.ilike(pattern, escape="\\"))
        if init_ctx and not init_ctx.is_admin and init_ctx.is_authenticated:
            stmt = stmt.where(Initiatief.id.in_(init_ctx.visible_initiatief_ids))
        stmt = stmt.order_by(Initiatief.naam)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_list_stats(self, ids: list[UUID]) -> dict[UUID, dict[str, Any]]:
        """Counts per initiatief for the overview, one grouped query each.

        Initiatieven without leads, members or updates are absent from the
        result; the caller defaults them to zero.
        """
        stats: dict[UUID, dict[str, Any]] = {i: {} for i in ids}
        if not ids:
            return stats

        lead_rows = await self.session.execute(
            select(
                Lead.initiatief_id,
                func.count(Lead.id),
                func.count(LeadColumn.id),
            )
            .outerjoin(
                LeadColumn,
                (LeadColumn.initiatief_id == Lead.initiatief_id)
                & (LeadColumn.slug == Lead.stage)
                & LeadColumn.is_active_stage.is_(True),
            )
            .where(Lead.initiatief_id.in_(ids))
            .group_by(Lead.initiatief_id)
        )
        for initiatief_id, total, active in lead_rows:
            stats[initiatief_id]["lead_count"] = total
            stats[initiatief_id]["active_lead_count"] = active

        member_rows = await self.session.execute(
            select(ResourcePermission.resource_id, func.count())
            .where(
                ResourcePermission.resource_type == "initiatief",
                ResourcePermission.resource_id.in_(ids),
                ResourcePermission.person_id.is_not(None),
            )
            .group_by(ResourcePermission.resource_id)
        )
        for initiatief_id, count in member_rows:
            stats[initiatief_id]["member_count"] = count

        update_rows = await self.session.execute(
            select(
                InitiatiefUpdatePost.initiatief_id,
                func.max(InitiatiefUpdatePost.published_at),
            )
            .where(
                InitiatiefUpdatePost.initiatief_id.in_(ids),
                InitiatiefUpdatePost.published_at.is_not(None),
            )
            .group_by(InitiatiefUpdatePost.initiatief_id)
        )
        for initiatief_id, last in update_rows:
            stats[initiatief_id]["last_published_at"] = last

        return stats

    async def get_detail(self, id: UUID) -> Initiatief | None:
        stmt = (
            select(Initiatief)
            .where(Initiatief.id == id)
            .options(selectinload(Initiatief.created_by))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Initiatief | None:
        stmt = select(Initiatief).where(Initiatief.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _slug_exists(self, slug: str, exclude_id: UUID | None = None) -> bool:
        stmt = select(Initiatief.id).where(Initiatief.slug == slug)
        if exclude_id is not None:
            stmt = stmt.where(Initiatief.id != exclude_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def _generate_unique_slug(
        self, naam: str, exclude_id: UUID | None = None
    ) -> str | None:
        base = slugify(naam)
        if not is_valid_slug(base):
            return None
        candidate = base
        suffix = 2
        while await self._slug_exists(candidate, exclude_id=exclude_id):
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    async def create(
        self, data: InitiatiefCreate, created_by_id: UUID | None = None
    ) -> Initiatief:
        dump = data.model_dump()
        dump["created_by_id"] = created_by_id
        dump["slug"] = await self._generate_unique_slug(data.naam)
        initiatief = Initiatief(**dump)
        self.session.add(initiatief)
        await self.session.flush()

        if created_by_id:
            rp = ResourcePermission(
                person_id=created_by_id,
                resource_type="initiatief",
                resource_id=initiatief.id,
                rol="eigenaar",
            )
            self.session.add(rp)
            await self.session.flush()

        # Seed the 7 default funnel-kolommen so the initiatief has a board
        # out of the box. Imported lazily to avoid a circular import.
        from bouwmeester.repositories.lead_column import LeadColumnRepository

        await LeadColumnRepository(self.session).seed_defaults(initiatief.id)

        await self.session.refresh(initiatief)
        return initiatief

    async def update(self, id: UUID, data: InitiatiefUpdate) -> Initiatief | None:
        initiatief = await self.session.get(Initiatief, id)
        if initiatief is None:
            return None
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(initiatief, key, value)
        await self.session.flush()
        await self.session.refresh(initiatief)
        return initiatief

    async def update_settings(
        self, id: UUID, data: InitiatiefSettingsUpdate
    ) -> Initiatief | None:
        initiatief = await self.session.get(Initiatief, id)
        if initiatief is None:
            return None
        payload = data.model_dump(exclude_unset=True)
        # If a slug is being assigned/changed, validate uniqueness.
        if "slug" in payload and payload["slug"] is not None:
            new_slug = payload["slug"]
            if not is_valid_slug(new_slug):
                from fastapi import HTTPException, status

                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Ongeldige slug. Gebruik alleen kleine letters, cijfers "
                        "en streepjes. Reservewoorden zijn niet toegestaan."
                    ),
                )
            if await self._slug_exists(new_slug, exclude_id=id):
                from fastapi import HTTPException, status

                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Deze slug is al in gebruik",
                )
        for key, value in payload.items():
            setattr(initiatief, key, value)
        await self.session.flush()
        await self.session.refresh(initiatief)
        return initiatief

    # -----------------------------------------------------------------------
    # Member (person-scoped) management via ResourcePermission
    # -----------------------------------------------------------------------

    async def add_member(
        self, initiatief_id: UUID, person_id: UUID, rol: str = "contributor"
    ) -> ResourcePermission:
        rp = ResourcePermission(
            person_id=person_id,
            resource_type="initiatief",
            resource_id=initiatief_id,
            rol=rol,
        )
        self.session.add(rp)
        await self.session.flush()
        await self.session.refresh(rp, attribute_names=["person"])
        return rp

    async def update_member_role(
        self, initiatief_id: UUID, person_id: UUID, rol: str
    ) -> ResourcePermission | None:
        stmt = (
            select(ResourcePermission)
            .where(
                ResourcePermission.resource_type == "initiatief",
                ResourcePermission.resource_id == initiatief_id,
                ResourcePermission.person_id == person_id,
            )
            .options(selectinload(ResourcePermission.person))
        )
        result = await self.session.execute(stmt)
        rp = result.scalar_one_or_none()
        if rp is None:
            return None
        rp.rol = rol
        await self.session.flush()
        await self.session.refresh(rp, attribute_names=["person"])
        return rp

    async def remove_member(self, initiatief_id: UUID, person_id: UUID) -> bool:
        stmt = select(ResourcePermission).where(
            ResourcePermission.resource_type == "initiatief",
            ResourcePermission.resource_id == initiatief_id,
            ResourcePermission.person_id == person_id,
        )
        result = await self.session.execute(stmt)
        rp = result.scalar_one_or_none()
        if rp is None:
            return False
        await self.session.delete(rp)
        await self.session.flush()
        return True

    # -----------------------------------------------------------------------
    # Eenheid (org-unit-scoped) management via ResourcePermission
    # -----------------------------------------------------------------------

    async def add_eenheid(
        self, initiatief_id: UUID, eenheid_id: UUID, rol: str = "contributor"
    ) -> ResourcePermission:
        rp = ResourcePermission(
            organisatie_eenheid_id=eenheid_id,
            resource_type="initiatief",
            resource_id=initiatief_id,
            rol=rol,
        )
        self.session.add(rp)
        await self.session.flush()
        await self.session.refresh(rp, attribute_names=["eenheid"])
        return rp

    async def update_eenheid_rol(
        self, initiatief_id: UUID, eenheid_id: UUID, rol: str
    ) -> ResourcePermission | None:
        stmt = select(ResourcePermission).where(
            ResourcePermission.resource_type == "initiatief",
            ResourcePermission.resource_id == initiatief_id,
            ResourcePermission.organisatie_eenheid_id == eenheid_id,
        )
        result = await self.session.execute(stmt)
        rp = result.scalar_one_or_none()
        if rp is None:
            return None
        rp.rol = rol
        await self.session.flush()
        await self.session.refresh(rp, attribute_names=["eenheid"])
        return rp

    async def remove_eenheid(self, initiatief_id: UUID, eenheid_id: UUID) -> bool:
        stmt = select(ResourcePermission).where(
            ResourcePermission.resource_type == "initiatief",
            ResourcePermission.resource_id == initiatief_id,
            ResourcePermission.organisatie_eenheid_id == eenheid_id,
        )
        result = await self.session.execute(stmt)
        rp = result.scalar_one_or_none()
        if rp is None:
            return False
        await self.session.delete(rp)
        await self.session.flush()
        return True

    async def list_eenheden(self, initiatief_id: UUID) -> list[ResourcePermission]:
        """List eenheid-scoped permissions for an initiatief."""
        stmt = (
            select(ResourcePermission)
            .where(
                ResourcePermission.resource_type == "initiatief",
                ResourcePermission.resource_id == initiatief_id,
                ResourcePermission.organisatie_eenheid_id.isnot(None),
            )
            .options(selectinload(ResourcePermission.eenheid))
            .order_by(ResourcePermission.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_eenheid(self, eenheid_id: UUID) -> list[ResourcePermission]:
        """List all initiatief permissions for a given eenheid."""
        stmt = (
            select(ResourcePermission)
            .where(
                ResourcePermission.resource_type == "initiatief",
                ResourcePermission.organisatie_eenheid_id == eenheid_id,
            )
            .order_by(ResourcePermission.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # -----------------------------------------------------------------------
    # Access checks
    # -----------------------------------------------------------------------

    async def is_member(self, initiatief_id: UUID, person_id: UUID) -> bool:
        """Check if person has access (direct or via eenheid)."""
        # Direct person permission
        direct = select(ResourcePermission.person_id).where(
            ResourcePermission.resource_type == "initiatief",
            ResourcePermission.resource_id == initiatief_id,
            ResourcePermission.person_id == person_id,
        )
        result = await self.session.execute(direct)
        if result.scalar_one_or_none() is not None:
            return True

        # Via eenheid membership
        from datetime import date

        from bouwmeester.models.person_organisatie import (
            PersonOrganisatieEenheid,
        )

        today = date.today()
        eenheid_stmt = (
            select(ResourcePermission.id)
            .join(
                PersonOrganisatieEenheid,
                PersonOrganisatieEenheid.organisatie_eenheid_id
                == ResourcePermission.organisatie_eenheid_id,
            )
            .where(
                ResourcePermission.resource_type == "initiatief",
                ResourcePermission.resource_id == initiatief_id,
                ResourcePermission.organisatie_eenheid_id.isnot(None),
                PersonOrganisatieEenheid.person_id == person_id,
                PersonOrganisatieEenheid.start_datum <= today,
                or_(
                    PersonOrganisatieEenheid.eind_datum.is_(None),
                    PersonOrganisatieEenheid.eind_datum >= today,
                ),
            )
        )
        result = await self.session.execute(eenheid_stmt)
        return result.scalar_one_or_none() is not None

    async def list_persons_with_access(self, initiatief_id: UUID) -> list[Person]:
        """Alle actieve personen die dit initiatief kunnen zien.

        Zelfde regel als `is_member` en `build_initiatief_context`: een
        directe resource_permission, of een actieve plaatsing in een eenheid
        met een resource_permission op het initiatief. Gesorteerd op naam.
        """
        from datetime import date

        from bouwmeester.models.person_organisatie import (
            PersonOrganisatieEenheid,
        )

        direct = select(ResourcePermission.person_id).where(
            ResourcePermission.resource_type == "initiatief",
            ResourcePermission.resource_id == initiatief_id,
            ResourcePermission.person_id.isnot(None),
        )
        today = date.today()
        via_eenheid = (
            select(PersonOrganisatieEenheid.person_id)
            .join(
                ResourcePermission,
                ResourcePermission.organisatie_eenheid_id
                == PersonOrganisatieEenheid.organisatie_eenheid_id,
            )
            .where(
                ResourcePermission.resource_type == "initiatief",
                ResourcePermission.resource_id == initiatief_id,
                PersonOrganisatieEenheid.start_datum <= today,
                or_(
                    PersonOrganisatieEenheid.eind_datum.is_(None),
                    PersonOrganisatieEenheid.eind_datum >= today,
                ),
            )
        )
        stmt = (
            select(Person)
            .where(
                Person.id.in_(direct.union(via_eenheid)),
                Person.is_active.is_(True),
            )
            .order_by(Person.naam)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def access_sources(
        self, initiatief_id: UUID
    ) -> tuple[dict[UUID, str], dict[UUID, list[str]]]:
        """Waar iemands toegang vandaan komt: directe rol en/of eenheden.

        Geeft (person_id -> directe rol, person_id -> namen van gekoppelde
        eenheden met een actieve plaatsing). Zelfde regel als
        `list_persons_with_access`; dit is de uitleg erbij.
        """
        from datetime import date

        from bouwmeester.models.organisatie_eenheid import OrganisatieEenheid
        from bouwmeester.models.person_organisatie import (
            PersonOrganisatieEenheid,
        )

        direct_stmt = select(
            ResourcePermission.person_id, ResourcePermission.rol
        ).where(
            ResourcePermission.resource_type == "initiatief",
            ResourcePermission.resource_id == initiatief_id,
            ResourcePermission.person_id.isnot(None),
        )
        direct = {
            pid: rol for pid, rol in (await self.session.execute(direct_stmt)).all()
        }

        today = date.today()
        via_stmt = (
            select(PersonOrganisatieEenheid.person_id, OrganisatieEenheid.naam)
            .join(
                ResourcePermission,
                ResourcePermission.organisatie_eenheid_id
                == PersonOrganisatieEenheid.organisatie_eenheid_id,
            )
            .join(
                OrganisatieEenheid,
                OrganisatieEenheid.id == ResourcePermission.organisatie_eenheid_id,
            )
            .where(
                ResourcePermission.resource_type == "initiatief",
                ResourcePermission.resource_id == initiatief_id,
                PersonOrganisatieEenheid.start_datum <= today,
                or_(
                    PersonOrganisatieEenheid.eind_datum.is_(None),
                    PersonOrganisatieEenheid.eind_datum >= today,
                ),
            )
            .order_by(OrganisatieEenheid.naam)
        )
        via: dict[UUID, list[str]] = {}
        for pid, naam in (await self.session.execute(via_stmt)).all():
            lijst = via.setdefault(pid, [])
            if naam not in lijst:
                lijst.append(naam)
        return direct, via

    async def count_eigenaren(self, initiatief_id: UUID) -> int:
        """Count eigenaren (person-scoped) for an initiatief."""
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(ResourcePermission)
            .where(
                ResourcePermission.resource_type == "initiatief",
                ResourcePermission.resource_id == initiatief_id,
                ResourcePermission.person_id.isnot(None),
                ResourcePermission.rol == "eigenaar",
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_member_role(self, initiatief_id: UUID, person_id: UUID) -> str | None:
        """Get the direct (person-scoped) role on an initiatief."""
        stmt = select(ResourcePermission.rol).where(
            ResourcePermission.resource_type == "initiatief",
            ResourcePermission.resource_id == initiatief_id,
            ResourcePermission.person_id == person_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_eenheid_access_level(
        self, initiatief_id: UUID, person_id: UUID
    ) -> str | None:
        """Get highest access via eenheid membership on an initiatief."""
        from datetime import date

        from bouwmeester.models.person_organisatie import (
            PersonOrganisatieEenheid,
        )

        today = date.today()
        stmt = (
            select(ResourcePermission.rol)
            .join(
                PersonOrganisatieEenheid,
                PersonOrganisatieEenheid.organisatie_eenheid_id
                == ResourcePermission.organisatie_eenheid_id,
            )
            .where(
                ResourcePermission.resource_type == "initiatief",
                ResourcePermission.resource_id == initiatief_id,
                ResourcePermission.organisatie_eenheid_id.isnot(None),
                PersonOrganisatieEenheid.person_id == person_id,
                PersonOrganisatieEenheid.start_datum <= today,
                or_(
                    PersonOrganisatieEenheid.eind_datum.is_(None),
                    PersonOrganisatieEenheid.eind_datum >= today,
                ),
            )
        )
        result = await self.session.execute(stmt)
        roles = result.scalars().all()
        if not roles:
            return None
        return max(roles, key=lambda r: EENHEID_ROL_RANK.get(r, 0))
