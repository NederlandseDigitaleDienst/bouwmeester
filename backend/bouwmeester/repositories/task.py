"""Repository for Task CRUD and queries."""

from datetime import date
from uuid import UUID

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.orm import selectinload

from bouwmeester.core.initiatief_context import InitiatiefContext
from bouwmeester.core.org_context import OrgContext, apply_org_filter
from bouwmeester.models.casus import Casus
from bouwmeester.models.task import Task
from bouwmeester.models.task_comment import TaskComment
from bouwmeester.repositories.base import BaseRepository
from bouwmeester.schema.task import TaskCreate, TaskUpdate


def _task_options():
    """Standard eager-load options for task queries."""
    return [
        selectinload(Task.assignee),
        selectinload(Task.organisatie_eenheid),
        selectinload(Task.node),
        selectinload(Task.casus),
        selectinload(Task.issue),
        selectinload(Task.opdracht),
        selectinload(Task.subtasks).selectinload(Task.assignee),
    ]


def apply_casus_filter(stmt, init_ctx: InitiatiefContext | None):
    """Taken van een casus alleen binnen de zichtbare initiatieven.

    Een casustaak is zo vertrouwelijk als de casus. Elke lijst die taken
    teruggeeft, ook "mijn taken" en de inbox, laat casustaken buiten de
    zichtbare initiatieven weg. Wie uit een initiatief is gehaald, ziet dus
    ook de taken die nog op zijn naam staan niet meer. Taken zonder casus
    (aan een node) blijven zoals ze waren: daar geldt de org-scope.
    Zonder context (interne aanroep) wordt niets gefilterd.
    """
    if init_ctx is None or init_ctx.is_admin:
        return stmt
    if not init_ctx.is_authenticated:
        return stmt.where(Task.casus_id.is_(None))
    zichtbare_casussen = select(Casus.id).where(
        or_(
            Casus.initiatief_id.is_(None),
            Casus.initiatief_id.in_(init_ctx.visible_initiatief_ids),
        )
    )
    return stmt.where(
        or_(Task.casus_id.is_(None), Task.casus_id.in_(zichtbare_casussen))
    )


class TaskRepository(BaseRepository[Task]):
    model = Task

    async def get(self, id: UUID) -> Task | None:
        stmt = select(Task).where(Task.id == id).options(*_task_options())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        status: str | None = None,
        organisatie_eenheid_id: UUID | None = None,
        include_children: bool = False,
        opdracht_id: UUID | None = None,
        org_ctx: OrgContext | None = None,
        init_ctx: InitiatiefContext | None = None,
    ) -> list[Task]:
        stmt = select(Task).options(*_task_options()).offset(skip).limit(limit)
        if status is not None:
            stmt = stmt.where(Task.status == status)
        if organisatie_eenheid_id is not None:
            if include_children:
                unit_ids = await self._get_descendant_ids(organisatie_eenheid_id)
                stmt = stmt.where(Task.organisatie_eenheid_id.in_(unit_ids))
            else:
                stmt = stmt.where(Task.organisatie_eenheid_id == organisatie_eenheid_id)
        if opdracht_id is not None:
            stmt = stmt.where(Task.opdracht_id == opdracht_id)
        stmt = apply_org_filter(stmt, Task.organisatie_eenheid_id, org_ctx)
        stmt = apply_casus_filter(stmt, init_ctx)
        stmt = stmt.order_by(Task.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, data: TaskCreate) -> Task:
        task = Task(**data.model_dump())
        self.session.add(task)
        await self.session.flush()
        await self.session.refresh(
            task,
            attribute_names=[
                "assignee",
                "organisatie_eenheid",
                "node",
                "casus",
                "opdracht",
                "subtasks",
            ],
        )
        return task

    async def update(self, id: UUID, data: TaskUpdate) -> Task | None:
        task = await self.session.get(Task, id)
        if task is None:
            return None
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(task, key, value)
        await self.session.flush()
        await self.session.refresh(
            task,
            attribute_names=[
                "updated_at",
                "assignee",
                "organisatie_eenheid",
                "node",
                "casus",
                "opdracht",
                "subtasks",
            ],
        )
        return task

    async def get_by_opdracht(
        self,
        opdracht_id: UUID,
        skip: int = 0,
        limit: int = 100,
        org_ctx: OrgContext | None = None,
        init_ctx: InitiatiefContext | None = None,
    ) -> list[Task]:
        stmt = (
            select(Task)
            .where(Task.opdracht_id == opdracht_id)
            .options(*_task_options())
            .offset(skip)
            .limit(limit)
            .order_by(Task.created_at.desc())
        )
        stmt = apply_org_filter(stmt, Task.organisatie_eenheid_id, org_ctx)
        stmt = apply_casus_filter(stmt, init_ctx)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_assignee(
        self,
        assignee_id: UUID,
        skip: int = 0,
        limit: int = 100,
        org_ctx: OrgContext | None = None,
        init_ctx: InitiatiefContext | None = None,
    ) -> list[Task]:
        stmt = (
            select(Task)
            .where(Task.assignee_id == assignee_id)
            .options(*_task_options())
            .offset(skip)
            .limit(limit)
            .order_by(Task.created_at.desc())
        )
        # Exception: you always see your own tasks, so if the assignee
        # matches the current user we skip org filtering entirely.
        if org_ctx is not None and org_ctx.person_id == assignee_id:
            pass  # no org filter - user sees all their own tasks
        else:
            stmt = apply_org_filter(stmt, Task.organisatie_eenheid_id, org_ctx)
        # Casustaken wel altijd: eigen taken op een casus die je niet meer
        # mag zien, zie je niet.
        stmt = apply_casus_filter(stmt, init_ctx)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_node(
        self,
        node_id: UUID,
        skip: int = 0,
        limit: int = 100,
        org_ctx: OrgContext | None = None,
        init_ctx: InitiatiefContext | None = None,
    ) -> list[Task]:
        stmt = (
            select(Task)
            .where(Task.node_id == node_id)
            .options(*_task_options())
            .offset(skip)
            .limit(limit)
            .order_by(Task.created_at.desc())
        )
        stmt = apply_org_filter(stmt, Task.organisatie_eenheid_id, org_ctx)
        stmt = apply_casus_filter(stmt, init_ctx)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_casus(
        self,
        casus_id: UUID,
        skip: int = 0,
        limit: int = 100,
        org_ctx: OrgContext | None = None,
        init_ctx: InitiatiefContext | None = None,
    ) -> list[Task]:
        """Taken van een casus, met subtaken (de UI hangt die onder hun hoofdtaak).

        Volgorde: eerst op `order` (handmatig), dan op aanmaakdatum oplopend,
        zodat een casusteam de lijst leest zoals hij is opgebouwd.
        """
        stmt = (
            select(Task)
            .where(Task.casus_id == casus_id)
            .options(*_task_options())
            .offset(skip)
            .limit(limit)
            .order_by(Task.order.asc().nulls_last(), Task.created_at.asc())
        )
        stmt = apply_org_filter(stmt, Task.organisatie_eenheid_id, org_ctx)
        stmt = apply_casus_filter(stmt, init_ctx)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def comment_counts(self, task_ids: list[UUID]) -> dict[UUID, int]:
        """Per taak het aantal opmerkingen; taken zonder opmerking ontbreken.

        Alleen voor taken die de aanroeper al mag zien: dit filtert niet zelf.
        """
        if not task_ids:
            return {}
        stmt = (
            select(TaskComment.task_id, func.count(TaskComment.id))
            .where(TaskComment.task_id.in_(task_ids))
            .group_by(TaskComment.task_id)
        )
        return {tid: int(n) for tid, n in (await self.session.execute(stmt)).all()}

    async def get_overdue(
        self,
        assignee_id: UUID | None = None,
        *,
        org_ctx: OrgContext | None = None,
        init_ctx: InitiatiefContext | None = None,
    ) -> list[Task]:
        stmt = (
            select(Task)
            .where(
                Task.deadline < date.today(),
                Task.status.notin_(["done", "cancelled"]),
            )
            .options(*_task_options())
        )
        if assignee_id is not None:
            stmt = stmt.where(Task.assignee_id == assignee_id)
        # Skip org filter when listing the caller's own overdue tasks —
        # users always see their own tasks regardless of org-scope.
        if not (org_ctx is not None and org_ctx.person_id == assignee_id):
            stmt = apply_org_filter(stmt, Task.organisatie_eenheid_id, org_ctx)
        stmt = apply_casus_filter(stmt, init_ctx)
        stmt = stmt.order_by(Task.deadline.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_organisatie_eenheid(
        self,
        eenheid_id: UUID,
        include_children: bool = False,
        skip: int = 0,
        limit: int = 100,
        org_ctx: OrgContext | None = None,
        init_ctx: InitiatiefContext | None = None,
    ) -> list[Task]:
        if include_children:
            unit_ids = await self._get_descendant_ids(eenheid_id)
            stmt = select(Task).where(Task.organisatie_eenheid_id.in_(unit_ids))
        else:
            stmt = select(Task).where(Task.organisatie_eenheid_id == eenheid_id)
        stmt = (
            stmt.options(*_task_options())
            .offset(skip)
            .limit(limit)
            .order_by(Task.created_at.desc())
        )
        stmt = apply_org_filter(stmt, Task.organisatie_eenheid_id, org_ctx)
        stmt = apply_casus_filter(stmt, init_ctx)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_unassigned(
        self,
        organisatie_eenheid_id: UUID | None = None,
        *,
        org_ctx: OrgContext | None = None,
        init_ctx: InitiatiefContext | None = None,
    ) -> list[Task]:
        stmt = (
            select(Task)
            .where(
                Task.assignee_id.is_(None),
                Task.status.notin_(["done", "cancelled"]),
            )
            .options(*_task_options())
        )
        stmt = apply_org_filter(stmt, Task.organisatie_eenheid_id, org_ctx)
        stmt = apply_casus_filter(stmt, init_ctx)
        if organisatie_eenheid_id is not None:
            stmt = stmt.where(Task.organisatie_eenheid_id == organisatie_eenheid_id)
        stmt = stmt.order_by(Task.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_subtasks(
        self,
        parent_id: UUID,
        *,
        org_ctx: OrgContext | None = None,
        init_ctx: InitiatiefContext | None = None,
    ) -> list[Task]:
        stmt = (
            select(Task)
            .where(Task.parent_id == parent_id)
            .options(*_task_options())
            .order_by(Task.order.asc().nulls_last(), Task.created_at.asc())
        )
        stmt = apply_org_filter(stmt, Task.organisatie_eenheid_id, org_ctx)
        stmt = apply_casus_filter(stmt, init_ctx)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def reorder_subtasks(
        self, parent_id: UUID, task_ids: list[UUID]
    ) -> list[Task]:
        """Set order field on subtasks according to the given ID list.

        Returns the reordered subtask list.
        Raises ValueError if any task_id does not belong to the parent.
        """
        # Batch-fetch all referenced tasks in one query
        stmt = select(Task).where(Task.id.in_(task_ids))
        result = await self.session.execute(stmt)
        tasks_by_id = {t.id: t for t in result.scalars().all()}

        # Validate: every provided ID must be an actual subtask of this parent
        for tid in task_ids:
            task = tasks_by_id.get(tid)
            if task is None or task.parent_id != parent_id:
                raise ValueError(f"Task {tid} is not a subtask of {parent_id}")

        # Validate completeness: all subtasks of the parent must be included
        count_stmt = (
            select(func.count()).select_from(Task).where(Task.parent_id == parent_id)
        )
        actual_count = (await self.session.execute(count_stmt)).scalar_one()
        if len(task_ids) != actual_count:
            raise ValueError(
                f"Expected {actual_count} subtask(s) but received {len(task_ids)}"
            )

        # Build order lookup from the requested sequence
        for idx, tid in enumerate(task_ids):
            tasks_by_id[tid].order = idx

        await self.session.flush()
        return await self.get_subtasks(parent_id)

    async def get_distinct_work_types(
        self,
        *,
        org_ctx: OrgContext | None = None,
        init_ctx: InitiatiefContext | None = None,
    ) -> list[str]:
        """Return all distinct non-null work_type values, sorted alphabetically."""
        stmt = (
            select(distinct(Task.work_type))
            .where(Task.work_type.isnot(None))
            .where(Task.work_type != "")
            .order_by(Task.work_type)
        )
        stmt = apply_org_filter(stmt, Task.organisatie_eenheid_id, org_ctx)
        stmt = apply_casus_filter(stmt, init_ctx)
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]

    async def _get_descendant_ids(self, root_id: UUID) -> list[UUID]:
        """Get all descendant unit IDs (including root) using a recursive CTE."""
        from bouwmeester.repositories.org_tree import get_descendant_ids

        return await get_descendant_ids(self.session, root_id)
