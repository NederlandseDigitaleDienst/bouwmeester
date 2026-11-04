"""Repository voor Issue binnen een casus."""

from uuid import UUID

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import selectinload

from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    apply_initiatief_filter,
)
from bouwmeester.core.org_context import OrgContext, apply_org_filter
from bouwmeester.models.casus import Casus
from bouwmeester.models.issue import Issue
from bouwmeester.models.task import Task
from bouwmeester.repositories.base import BaseRepository
from bouwmeester.schema.issue import IssueCreate, IssueUpdate


class IssueRepository(BaseRepository[Issue]):
    model = Issue

    async def get(self, id: UUID) -> Issue | None:
        stmt = select(Issue).where(Issue.id == id).options(selectinload(Issue.assignee))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_casus(self, casus_id: UUID) -> list[Issue]:
        stmt = (
            select(Issue)
            .where(Issue.casus_id == casus_id)
            .options(selectinload(Issue.assignee))
            .order_by(Issue.sort_order.asc(), Issue.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def counts(self, issue_ids: list[UUID]) -> dict[UUID, tuple[int, int]]:
        """Per issue: (taken, taken af). Alleen hoofdtaken, geen subtaken."""
        if not issue_ids:
            return {}
        done_task = case((Task.status == "done", 1), else_=0)
        stmt = (
            select(
                Task.issue_id,
                func.count(Task.id),
                func.coalesce(func.sum(done_task), 0),
            )
            .where(Task.issue_id.in_(issue_ids), Task.parent_id.is_(None))
            .group_by(Task.issue_id)
        )
        return {
            iid: (int(n), int(d))
            for iid, n, d in (await self.session.execute(stmt)).all()
        }

    async def create_for_casus(self, casus_id: UUID, data: IssueCreate) -> Issue:
        max_stmt = select(func.coalesce(func.max(Issue.sort_order), -1)).where(
            Issue.casus_id == casus_id
        )
        next_order = (await self.session.execute(max_stmt)).scalar_one() + 1
        issue = Issue(casus_id=casus_id, sort_order=next_order, **data.model_dump())
        self.session.add(issue)
        await self.session.flush()
        await self.session.refresh(issue)
        await self.session.refresh(issue, attribute_names=["assignee"])
        return issue

    async def update(self, id: UUID, data: IssueUpdate) -> Issue | None:
        issue = await self.session.get(Issue, id)
        if issue is None:
            return None
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(issue, key, value)
        await self.session.flush()
        await self.session.refresh(issue)
        await self.session.refresh(issue, attribute_names=["assignee"])
        return issue

    async def move_to_casus(self, issue: Issue, casus_id: UUID) -> None:
        """Verhuis een issue naar een andere casus, met alles eronder.

        De taken onder het issue en hun subtaken krijgen de nieuwe casus.
        Het issue komt
        achteraan in de nieuwe casus. Toegang en initiatief controleert de
        route.
        """
        oud = issue.casus_id
        if oud == casus_id:
            return
        rand = list(
            (
                await self.session.execute(
                    select(Task.id).where(
                        Task.casus_id == oud, Task.issue_id == issue.id
                    )
                )
            )
            .scalars()
            .all()
        )
        task_ids = list(rand)
        while rand:
            rand = list(
                (
                    await self.session.execute(
                        select(Task.id).where(
                            Task.parent_id.in_(rand), Task.casus_id == oud
                        )
                    )
                )
                .scalars()
                .all()
            )
            task_ids.extend(rand)

        if task_ids:
            await self.session.execute(
                update(Task).where(Task.id.in_(task_ids)).values(casus_id=casus_id)
            )
        max_stmt = select(func.coalesce(func.max(Issue.sort_order), -1)).where(
            Issue.casus_id == casus_id
        )
        issue.sort_order = (await self.session.execute(max_stmt)).scalar_one() + 1
        issue.casus_id = casus_id
        await self.session.flush()

    async def reorder(self, casus_id: UUID, issue_ids: list[UUID]) -> list[Issue]:
        issues = await self.list_for_casus(casus_id)
        by_id = {i.id: i for i in issues}
        if set(issue_ids) != set(by_id) or len(issue_ids) != len(by_id):
            raise ValueError("issue_ids komt niet overeen met de issues van deze casus")
        for idx, iid in enumerate(issue_ids):
            by_id[iid].sort_order = idx
        await self.session.flush()
        return await self.list_for_casus(casus_id)

    async def list_backlog(
        self,
        initiatief_id: UUID,
        *,
        init_ctx: InitiatiefContext | None = None,
        org_ctx: OrgContext | None = None,
    ) -> tuple[list[Issue], list[Task]]:
        """De backlog van een initiatief: (issues met taken, losse taken).

        Zichtbaarheid loopt via de casus, net als CasusRepository.list_all.
        Losse taken zijn taken van een casus van dit initiatief zonder issue.
        Alleen hoofdtaken: een taak in een casus heeft geen subtaken (de
        filter op parent_id houdt het zo, ook voor oude gegevens).
        """
        taak_opties = (selectinload(Task.assignee),)
        issue_stmt = (
            select(Issue)
            .join(Casus, Issue.casus_id == Casus.id)
            .where(Casus.initiatief_id == initiatief_id)
            .options(
                selectinload(Issue.casus),
                selectinload(Issue.assignee),
                selectinload(Issue.tasks).options(*taak_opties),
            )
            .order_by(Casus.title.asc(), Issue.sort_order.asc(), Issue.created_at.asc())
        )
        issue_stmt = apply_initiatief_filter(issue_stmt, Casus.initiatief_id, init_ctx)
        issues = list((await self.session.execute(issue_stmt)).scalars().all())

        los_stmt = (
            select(Task)
            .join(Casus, Task.casus_id == Casus.id)
            .where(
                Casus.initiatief_id == initiatief_id,
                Task.issue_id.is_(None),
                Task.parent_id.is_(None),
            )
            .options(selectinload(Task.casus), *taak_opties)
            .order_by(
                Casus.title.asc(), Task.order.asc().nulls_last(), Task.created_at.asc()
            )
        )
        los_stmt = apply_initiatief_filter(los_stmt, Casus.initiatief_id, init_ctx)
        los_stmt = apply_org_filter(los_stmt, Task.organisatie_eenheid_id, org_ctx)
        losse = list((await self.session.execute(los_stmt)).scalars().all())
        return issues, losse

    async def sync_status(self, issue_id: UUID | None) -> None:
        """Leid de status van een issue af uit zijn hoofdtaken.

        Na elke wijziging aan een taak eronder:
        - alle taken afgerond: een afgerond issue blijft afgerond, anders in
          behandeling. Afronden gaat alleen met de hand, na de Definition of
          Done; klaar werk is nog geen afgerond issue;
        - minstens één taak in uitvoering of afgerond (niet allemaal): in
          behandeling, ook als het issue al afgerond was;
        - alle taken open: open als het issue op afgerond stond, anders blijft
          de status staan (wie hem met de hand op in behandeling zette, houdt dat).
        Geannuleerde taken en subtaken tellen niet mee. Zonder taken verandert
        er niets. Met de hand zetten blijft altijd kan; de volgende
        taakwijziging rekent opnieuw.
        """
        if issue_id is None:
            return
        issue = await self.session.get(Issue, issue_id)
        if issue is None:
            return
        stmt = select(Task.status).where(
            Task.issue_id == issue_id, Task.parent_id.is_(None)
        )
        statussen = [
            st
            for st in (await self.session.execute(stmt)).scalars().all()
            if st != "cancelled"
        ]
        if not statussen:
            return
        if all(st == "done" for st in statussen):
            nieuw = "done" if issue.status == "done" else "in_progress"
        elif any(st in ("in_progress", "done") for st in statussen):
            nieuw = "in_progress"
        elif issue.status == "done":
            nieuw = "open"
        else:
            return
        if issue.status != nieuw:
            issue.status = nieuw
            await self.session.flush()
