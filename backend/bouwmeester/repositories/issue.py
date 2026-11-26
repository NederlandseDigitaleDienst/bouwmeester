"""Repository voor Issue binnen een casus."""

from uuid import UUID

from sqlalchemy import and_, case, func, select, update
from sqlalchemy.orm import selectinload

from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    apply_initiatief_filter,
)
from bouwmeester.core.org_context import OrgContext, apply_org_filter
from bouwmeester.models.casus import Casus
from bouwmeester.models.issue import Issue
from bouwmeester.models.onderzoeksverslag import Onderzoeksverslag
from bouwmeester.models.task import Task
from bouwmeester.repositories.base import BaseRepository
from bouwmeester.schema.issue import IssueCreate, IssueUpdate


class IssueRepository(BaseRepository[Issue]):
    model = Issue

    async def get(self, id: UUID) -> Issue | None:
        stmt = select(Issue).where(Issue.id == id).options(selectinload(Issue.assignee))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def _op_plek(self, plek):
        """Filter op de vragen van een plek: een casus, of het initiatief."""
        if plek.id is not None:
            return Issue.casus_id == plek.id
        return and_(Issue.casus_id.is_(None), Issue.initiatief_id == plek.initiatief_id)

    async def list_for_plek(self, plek) -> list[Issue]:
        stmt = (
            select(Issue)
            .where(self._op_plek(plek))
            .options(selectinload(Issue.assignee))
            .order_by(Issue.sort_order.asc(), Issue.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def heeft_taken(self, issue_id: UUID) -> bool:
        stmt = select(func.count(Task.id)).where(Task.issue_id == issue_id)
        return bool((await self.session.execute(stmt)).scalar_one())

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

    async def create_in_plek(self, plek, data: IssueCreate) -> Issue:
        """Een nieuwe vraag achteraan in een casus of bij het initiatief."""
        max_stmt = select(func.coalesce(func.max(Issue.sort_order), -1)).where(
            self._op_plek(plek)
        )
        next_order = (await self.session.execute(max_stmt)).scalar_one() + 1
        issue = Issue(
            casus_id=plek.id,
            initiatief_id=plek.initiatief_id,
            sort_order=next_order,
            **data.model_dump(),
        )
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
        if trek_in_als_niet_af(issue):
            await verslag_terug_naar_binnen(self.session, issue.id)
        await self.session.flush()
        await self.session.refresh(issue)
        await self.session.refresh(issue, attribute_names=["assignee"])
        return issue

    async def move_to_casus(
        self, issue: Issue, casus_id: UUID | None, initiatief_id: UUID | None
    ) -> None:
        """Verhuis een issue naar een andere casus, met alles eronder.

        `casus_id` en `initiatief_id` zijn de nieuwe plek; de route bepaalt
        ze uit de casus of het initiatief, niet uit het issue zelf (zie
        hieronder). De taken onder het issue en hun subtaken krijgen de
        nieuwe casus. Met None gaat de vraag uit de casus naar het
        initiatief; de taken hangen dan alleen nog aan de vraag.

        Subtaken krijgen ook het issue_id van de vraag. Een subtaak zonder
        node en zonder casus heeft anders geen anker meer (ck_task_anchor),
        en de toegangsfilters (apply_casus_filter) herkennen werk van een
        initiatief aan casus_id of issue_id: zonder allebei zou de subtaak
        als node-taak voor de hele org-scope zichtbaar worden. Een subtaak
        telt niet mee voor de vraag (counts en sync_status kijken alleen
        naar hoofdtaken).

        Het issue krijgt ook het initiatief van de plek. Een vraag die een
        oude versie van de app aanmaakte, kan initiatief_id leeg hebben;
        zonder casus moet hij gevuld zijn (ck_issue_plek). Het issue komt
        achteraan op de nieuwe plek. Toegang controleert de route.
        """
        oud = issue.casus_id
        if oud == casus_id:
            return

        def zelfde_casus(kolom):
            return kolom.is_(None) if oud is None else kolom == oud

        # De taken met het issue_id van de vraag (ook subtaken die het al
        # hebben), en daarna alles wat eronder hangt.
        taken = list(
            (
                await self.session.execute(
                    select(Task.id).where(
                        zelfde_casus(Task.casus_id), Task.issue_id == issue.id
                    )
                )
            )
            .scalars()
            .all()
        )
        subtaken: list[UUID] = []
        rand = taken
        while rand:
            rand = list(
                (
                    await self.session.execute(
                        select(Task.id).where(
                            Task.parent_id.in_(rand), zelfde_casus(Task.casus_id)
                        )
                    )
                )
                .scalars()
                .all()
            )
            subtaken.extend(rand)

        if subtaken:
            # Eerst het anker, dan de casus: een oude subtaak heeft alleen een
            # casus_id, en zonder issue_id zou ck_task_anchor de stap uit de
            # casus weigeren. Een subtaak aan een node houdt die node als
            # anker; een taak hangt niet aan een node en een vraag tegelijk.
            await self.session.execute(
                update(Task)
                .where(Task.id.in_(subtaken), Task.node_id.is_(None))
                .values(issue_id=issue.id)
            )
        if taken or subtaken:
            await self.session.execute(
                update(Task)
                .where(Task.id.in_(taken + subtaken))
                .values(casus_id=casus_id)
            )
        if initiatief_id is not None:
            issue.initiatief_id = initiatief_id
        doel = (
            Issue.casus_id == casus_id
            if casus_id is not None
            else and_(Issue.casus_id.is_(None), Issue.initiatief_id == initiatief_id)
        )
        max_stmt = select(func.coalesce(func.max(Issue.sort_order), -1)).where(doel)
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

        Zichtbaarheid loopt via het initiatief van de vraag, net als
        CasusRepository.list_all via dat van de casus. Vragen zonder casus
        horen erbij. Het initiatief van een vraag is dat van haar casus, en
        alleen zonder casus issue.initiatief_id: een vraag die een oude
        versie van de app in een casus aanmaakte, heeft dat veld leeg.
        Losse taken zijn taken van een casus van dit initiatief zonder issue.
        Alleen hoofdtaken: een taak in een casus heeft geen subtaken (de
        filter op parent_id houdt het zo, ook voor oude gegevens).
        """
        taak_opties = (selectinload(Task.assignee),)
        initiatief_van_vraag = func.coalesce(Casus.initiatief_id, Issue.initiatief_id)
        # Ook de vragen zonder casus; die komen eerst.
        issue_stmt = (
            select(Issue)
            .outerjoin(Casus, Issue.casus_id == Casus.id)
            .where(initiatief_van_vraag == initiatief_id)
            .options(
                selectinload(Issue.casus),
                selectinload(Issue.assignee),
                selectinload(Issue.tasks).options(*taak_opties),
            )
            .order_by(
                Casus.title.asc().nulls_first(),
                Issue.sort_order.asc(),
                Issue.created_at.asc(),
            )
        )
        issue_stmt = apply_initiatief_filter(issue_stmt, initiatief_van_vraag, init_ctx)
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
            if trek_in_als_niet_af(issue):
                await verslag_terug_naar_binnen(self.session, issue.id)
            await self.session.flush()


def trek_in_als_niet_af(issue: Issue) -> bool:
    """Een vrijgegeven vraag die niet meer af is, gaat terug naar binnen.

    Heropend, door een taak weer open gezet, of geen onderzoeksvraag meer:
    dan klopt "beantwoord" niet meer. De publieke tekst blijft bewaard; wie
    de vraag opnieuw afrondt, geeft hem bewust opnieuw vrij. Geeft True als
    de vraag nu werd ingetrokken; de aanroeper zet dan met
    `verslag_terug_naar_binnen` ook het akkoord op het verslag terug.
    """
    if issue.published_at is None:
        return False
    if issue.status == "done" and issue.is_onderzoeksvraag:
        return False
    issue.published_at = None
    return True


async def verslag_terug_naar_binnen(session, issue_id: UUID) -> None:
    """Het akkoord op het verslag van deze vraag vervalt.

    Na intrekken of heropenen van de vraag: het akkoord gold voor een vraag
    die buiten stond. Wie de vraag opnieuw vrijgeeft, beslist opnieuw over
    het verslag. Het bestand blijft staan.
    """
    await session.execute(
        update(Onderzoeksverslag)
        .where(
            Onderzoeksverslag.issue_id == issue_id,
            Onderzoeksverslag.openbaar_op.is_not(None),
        )
        .values(openbaar_op=None, openbaar_door_id=None)
    )
