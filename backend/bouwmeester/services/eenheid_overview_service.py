"""Service for eenheid task overview — batched queries, no N+1."""

from collections import defaultdict
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bouwmeester.core.initiatief_context import InitiatiefContext
from bouwmeester.models.org_parent import OrganisatieEenheidParent
from bouwmeester.models.organisatie_eenheid import OrganisatieEenheid
from bouwmeester.models.person import Person
from bouwmeester.models.person_organisatie import PersonOrganisatieEenheid
from bouwmeester.models.task import Task
from bouwmeester.repositories.org_tree import get_descendant_ids
from bouwmeester.repositories.task import apply_casus_filter
from bouwmeester.schema.task import (
    EenheidOverviewResponse,
    EenheidPersonTaskStats,
    EenheidSubeenheidStats,
    TaskResponse,
)


def _task_options():
    """Eager-load options so TaskResponse can serialize relationships."""
    return [
        selectinload(Task.assignee),
        selectinload(Task.organisatie_eenheid),
        selectinload(Task.node),
        selectinload(Task.casus),
        selectinload(Task.opdracht),
        selectinload(Task.subtasks).selectinload(Task.assignee),
    ]


class EenheidOverviewService:
    """Takenoverzicht van een eenheid.

    Casustaken tellen en staan er alleen in voor wie het initiatief van de
    casus kan zien (``init_ctx``), zoals in elke takenlijst. Ze hebben
    meestal geen eenheid en zouden anders bij "zonder eenheid" voor
    iedereen zichtbaar zijn.
    """

    def __init__(
        self, session: AsyncSession, init_ctx: InitiatiefContext | None = None
    ) -> None:
        self.session = session
        self.init_ctx = init_ctx

    def _zichtbaar(self, stmt):
        return apply_casus_filter(stmt, self.init_ctx)

    async def get_overview(
        self, organisatie_eenheid_id: UUID
    ) -> EenheidOverviewResponse:
        # Fetch the eenheid itself for type info
        eenheid = await self.session.get(OrganisatieEenheid, organisatie_eenheid_id)
        eenheid_type = eenheid.type if eenheid else ""

        all_unit_ids = await get_descendant_ids(self.session, organisatie_eenheid_id)

        no_unit_tasks, no_unit_count = await self._unassigned_no_unit(all_unit_ids)
        no_person_tasks, no_person_count = await self._unassigned_no_person(
            all_unit_ids,
        )
        by_person = await self._person_stats(organisatie_eenheid_id)
        by_subeenheid = await self._subeenheid_stats(
            organisatie_eenheid_id, all_unit_ids
        )

        return EenheidOverviewResponse(
            unassigned_count=no_unit_count + no_person_count,
            unassigned_no_unit=[TaskResponse.model_validate(t) for t in no_unit_tasks],
            unassigned_no_unit_count=no_unit_count,
            unassigned_no_person=[
                TaskResponse.model_validate(t) for t in no_person_tasks
            ],
            unassigned_no_person_count=no_person_count,
            by_person=by_person,
            by_subeenheid=by_subeenheid,
            eenheid_type=eenheid_type,
        )

    async def _unassigned_no_unit(
        self, unit_ids: list[UUID], limit: int = 20
    ) -> tuple[list[Task], int]:
        """Tasks with no organisatie_eenheid_id at all (visible at high levels)."""
        base = (
            Task.organisatie_eenheid_id.is_(None)
            & Task.assignee_id.is_(None)
            & Task.status.notin_(["done", "cancelled"])
        )
        count_stmt = self._zichtbaar(select(func.count()).select_from(Task).where(base))
        result = await self.session.execute(count_stmt)
        count = result.scalar_one()

        tasks_stmt = self._zichtbaar(
            select(Task)
            .where(base)
            .options(*_task_options())
            .order_by(Task.deadline.asc().nulls_last(), Task.created_at.desc())
            .limit(limit)
        )
        tasks_result = await self.session.execute(tasks_stmt)
        return list(tasks_result.scalars().all()), count

    async def _unassigned_no_person(
        self, unit_ids: list[UUID], limit: int = 20
    ) -> tuple[list[Task], int]:
        """Tasks within these units that have no assignee."""
        base = (
            Task.organisatie_eenheid_id.in_(unit_ids)
            & Task.assignee_id.is_(None)
            & Task.status.notin_(["done", "cancelled"])
        )
        count_stmt = self._zichtbaar(select(func.count()).select_from(Task).where(base))
        result = await self.session.execute(count_stmt)
        count = result.scalar_one()

        tasks_stmt = self._zichtbaar(
            select(Task)
            .where(base)
            .options(*_task_options())
            .order_by(Task.deadline.asc().nulls_last(), Task.created_at.desc())
            .limit(limit)
        )
        tasks_result = await self.session.execute(tasks_stmt)
        return list(tasks_result.scalars().all()), count

    async def _person_stats(self, eenheid_id: UUID) -> list[EenheidPersonTaskStats]:
        # Get people in this unit (active placements)
        people_stmt = (
            select(Person.id, Person.naam)
            .join(
                PersonOrganisatieEenheid,
                PersonOrganisatieEenheid.person_id == Person.id,
            )
            .where(
                PersonOrganisatieEenheid.organisatie_eenheid_id == eenheid_id,
                PersonOrganisatieEenheid.eind_datum.is_(None),
            )
            .order_by(Person.naam)
        )
        people_result = await self.session.execute(people_stmt)
        people = people_result.all()

        if not people:
            return []

        person_ids = [p.id for p in people]

        # Batch: get all task stats for these people in one query
        stats_stmt = self._zichtbaar(
            select(
                Task.assignee_id,
                Task.status,
                Task.deadline,
                func.count().label("cnt"),
            )
            .where(Task.assignee_id.in_(person_ids))
            .group_by(Task.assignee_id, Task.status, Task.deadline)
        )
        stats_result = await self.session.execute(stats_stmt)

        # Aggregate per person
        today = date.today()
        counts: dict[UUID, dict[str, int]] = defaultdict(
            lambda: {
                "open": 0,
                "in_progress": 0,
                "done": 0,
                "overdue": 0,
            }
        )
        for assignee_id, task_status, deadline, cnt in stats_result.all():
            c = counts[assignee_id]
            if task_status == "open":
                c["open"] += cnt
            elif task_status == "in_progress":
                c["in_progress"] += cnt
            elif task_status == "done":
                c["done"] += cnt
            if (
                task_status in ("open", "in_progress")
                and deadline is not None
                and deadline < today
            ):
                c["overdue"] += cnt

        return [
            EenheidPersonTaskStats(
                person_id=p.id,
                person_naam=p.naam,
                open_count=counts[p.id]["open"],
                in_progress_count=counts[p.id]["in_progress"],
                done_count=counts[p.id]["done"],
                overdue_count=counts[p.id]["overdue"],
            )
            for p in people
        ]

    async def _subeenheid_stats(
        self, parent_id: UUID, all_unit_ids: list[UUID]
    ) -> list[EenheidSubeenheidStats]:
        # Get direct children (via active temporal parent records)
        children_stmt = (
            select(OrganisatieEenheid)
            .join(
                OrganisatieEenheidParent,
                OrganisatieEenheidParent.eenheid_id == OrganisatieEenheid.id,
            )
            .where(
                OrganisatieEenheidParent.parent_id == parent_id,
                OrganisatieEenheidParent.geldig_tot.is_(None),
            )
            .order_by(OrganisatieEenheid.naam)
        )
        children_result = await self.session.execute(children_stmt)
        children = list(children_result.scalars().all())

        if not children:
            return []

        # Get descendants for each child using the shared utility
        child_id_sets: dict[UUID, list[UUID]] = {}
        for child in children:
            child_id_sets[child.id] = await get_descendant_ids(self.session, child.id)

        # Batch: get all task stats for all descendant units in one query
        stats_stmt = self._zichtbaar(
            select(
                Task.organisatie_eenheid_id,
                Task.status,
                func.count().label("cnt"),
            )
            .where(Task.organisatie_eenheid_id.in_(all_unit_ids))
            .group_by(Task.organisatie_eenheid_id, Task.status)
        )
        stats_result = await self.session.execute(stats_stmt)

        # Index stats by unit_id
        unit_stats: dict[UUID, dict[str, int]] = defaultdict(
            lambda: {"open": 0, "in_progress": 0, "done": 0}
        )
        for unit_id, task_status, cnt in stats_result.all():
            unit_stats[unit_id][task_status] = cnt

        # Aggregate per child (sum over its descendants)
        result: list[EenheidSubeenheidStats] = []
        for child in children:
            open_c = 0
            ip_c = 0
            done_c = 0
            for desc_id in child_id_sets[child.id]:
                s = unit_stats.get(desc_id, {})
                open_c += s.get("open", 0)
                ip_c += s.get("in_progress", 0)
                done_c += s.get("done", 0)

            result.append(
                EenheidSubeenheidStats(
                    eenheid_id=child.id,
                    eenheid_naam=child.naam,
                    eenheid_type=child.type,
                    open_count=open_c,
                    in_progress_count=ip_c,
                    done_count=done_c,
                )
            )

        return result
