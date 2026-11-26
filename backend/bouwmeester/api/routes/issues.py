"""API routes voor issues (onderzoeksvragen), in een casus of zonder casus.

Een vraag hoort altijd bij een initiatief en meestal bij een casus. Dezelfde
routes staan op twee plekken:

- ``/casussen/{casus_id}/issues``: vragen van een casus. Zelfde toegangsregel
  als de casus: wie de casus ziet, mag de vragen zien; wijzigen vraagt
  dezelfde rol als de casus (bijdrager, eigenaar of trekker).
- ``/initiatieven/{initiatief_id}/vragen``: vragen zonder casus. Wie het
  initiatief ziet, ziet ze; wijzigen vraagt bijdrager of eigenaar.

Bij verwijderen van een casusvraag blijven de taken op de casus staan
(issue_id wordt leeg). Een vraag zonder casus met taken verwijder je niet:
de taken hebben dan geen plek meer.

Een vraag verhuist met ``casus_id`` naar een casus van hetzelfde initiatief,
of met ``casus_id: null`` uit zijn casus naar het initiatief. De taken gaan
mee.

Een afgeronde onderzoeksvraag kan naar buiten (`/publiek`): vrijgeven vraagt
een bijdrager of eigenaar van het initiatief, intrekken iedereen die de vraag
wijzigt. Zie services/publieke_vragen.py voor wat er dan naar buiten gaat.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.api.deps import require_deleted, require_found
from bouwmeester.core.auth import OptionalUser
from bouwmeester.core.authority import (
    require_can_change_casus,
    require_can_publish_issue,
)
from bouwmeester.core.database import get_db
from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    get_initiatief_context,
    require_initiatief_member,
    require_initiatief_visible,
)
from bouwmeester.core.permissions import PermissionContext, get_permission_context
from bouwmeester.core.storage import delete_blob
from bouwmeester.core.werkplek import InitiatiefWerk, Werkplek
from bouwmeester.models.casus import Casus
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.repositories.casus import verslag_paden
from bouwmeester.repositories.issue import (
    IssueRepository,
    verslag_terug_naar_binnen,
)
from bouwmeester.schema.issue import (
    IssueCreate,
    IssuePubliek,
    IssueReorder,
    IssueResponse,
    IssueUpdate,
)
from bouwmeester.services import casus_kanaal_service as kanaal
from bouwmeester.services.activity_service import log_activity


async def _get_casus(
    db: AsyncSession, casus_id: UUID, init_ctx: InitiatiefContext
) -> Casus:
    casus = await db.get(Casus, casus_id)
    if casus is None:
        raise HTTPException(status_code=404, detail="Casus niet gevonden")
    require_initiatief_visible(
        casus.initiatief_id, init_ctx, detail="Casus niet gevonden"
    )
    return casus


async def casus_plek(
    casus_id: UUID,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> Werkplek:
    """De plek uit het pad /casussen/{casus_id}/...: de casus."""
    return await _get_casus(db, casus_id, init_ctx)


async def initiatief_plek(
    initiatief_id: UUID,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> Werkplek:
    """De plek uit het pad /initiatieven/{initiatief_id}/vragen/...."""
    if await db.get(Initiatief, initiatief_id) is None:
        raise HTTPException(status_code=404, detail="Initiatief niet gevonden")
    require_initiatief_visible(
        initiatief_id, init_ctx, detail="Initiatief niet gevonden"
    )
    return InitiatiefWerk(initiatief_id=initiatief_id)


def _hoort_bij(issue, plek: Werkplek) -> bool:
    if plek.id is not None:
        return issue.casus_id == plek.id
    return issue.casus_id is None and issue.initiatief_id == plek.initiatief_id


async def issue_in_plek(repo: IssueRepository, plek: Werkplek, issue_id: UUID):
    """De vraag, als hij op deze plek staat; anders 404."""
    issue = await repo.get(issue_id)
    if issue is None or not _hoort_bij(issue, plek):
        raise HTTPException(status_code=404, detail="Onderzoeksvraag niet gevonden")
    return issue


def plek_details(plek: Werkplek) -> dict:
    """Waar de vraag staat, voor het activiteitenlog."""
    if plek.id is None:
        return {"casus_id": None, "initiatief_id": str(plek.initiatief_id)}
    return {"casus_id": str(plek.id), "casus_title": plek.title}


async def _with_counts(repo: IssueRepository, issues) -> list[IssueResponse]:
    counts = await repo.counts([i.id for i in issues])
    out = []
    for i in issues:
        resp = IssueResponse.model_validate(i)
        resp.task_count, resp.task_done_count = counts.get(i.id, (0, 0))
        out.append(resp)
    return out


async def _bewaar(db: AsyncSession, issue) -> None:
    """Opslaan en opnieuw lezen: updated_at zet de database zelf, en in een
    async sessie kan het antwoord dat niet meer achteraf ophalen."""
    await db.flush()
    await db.refresh(issue)
    await db.refresh(issue, attribute_names=["assignee"])


PlekDep = Callable[..., Awaitable[Werkplek]]


def maak_router(prefix: str, plek_dep: PlekDep, *, met_volgorde: bool) -> APIRouter:
    """De vraagroutes onder een prefix, met de plek uit `plek_dep`."""
    router = APIRouter(prefix=prefix, tags=["issues"])

    @router.get("", response_model=list[IssueResponse])
    async def list_issues(
        current_user: OptionalUser,
        plek: Werkplek = Depends(plek_dep),
        db: AsyncSession = Depends(get_db),
    ) -> list[IssueResponse]:
        repo = IssueRepository(db)
        return await _with_counts(repo, await repo.list_for_plek(plek))

    @router.post("", response_model=IssueResponse, status_code=status.HTTP_201_CREATED)
    async def create_issue(
        data: IssueCreate,
        current_user: OptionalUser,
        plek: Werkplek = Depends(plek_dep),
        db: AsyncSession = Depends(get_db),
        perm_ctx: PermissionContext = Depends(get_permission_context),
    ) -> IssueResponse:
        await require_can_change_casus(db, perm_ctx, current_user, plek)
        if plek.id is None:
            # Een vraag zonder casus hoort bij een initiatief dat met
            # casussen werkt, zoals het starten van een casus
            # (casussen.py). Bestaande vragen blijven te zien en te wijzigen.
            init = await db.get(Initiatief, plek.initiatief_id)
            if init is None or not init.casussen_enabled:
                raise HTTPException(
                    status_code=400,
                    detail="Casussen staan niet aan voor dit initiatief",
                )
        if data.assignee_id is not None:
            await require_initiatief_member(db, plek.initiatief_id, data.assignee_id)
        repo = IssueRepository(db)
        issue = await repo.create_in_plek(plek, data)
        await log_activity(
            db,
            current_user,
            None,
            "issue.created",
            details={**plek_details(plek), "title": issue.title},
        )
        if plek.id is not None:
            # Alleen een casus heeft een kanaal; een losse vraag niet.
            actor = current_user.naam if current_user else None
            await kanaal.meld(
                db, plek.id, kanaal.bericht_issue_nieuw(plek, issue, actor)
            )
        return (await _with_counts(repo, [issue]))[0]

    if met_volgorde:

        @router.put("/reorder", response_model=list[IssueResponse])
        async def reorder_issues(
            data: IssueReorder,
            current_user: OptionalUser,
            plek: Werkplek = Depends(plek_dep),
            db: AsyncSession = Depends(get_db),
            perm_ctx: PermissionContext = Depends(get_permission_context),
        ) -> list[IssueResponse]:
            await require_can_change_casus(db, perm_ctx, current_user, plek)
            repo = IssueRepository(db)
            try:
                issues = await repo.reorder(plek.id, data.issue_ids)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            return await _with_counts(repo, issues)

    @router.put("/{issue_id}", response_model=IssueResponse)
    async def update_issue(
        issue_id: UUID,
        data: IssueUpdate,
        current_user: OptionalUser,
        plek: Werkplek = Depends(plek_dep),
        db: AsyncSession = Depends(get_db),
        init_ctx: InitiatiefContext = Depends(get_initiatief_context),
        perm_ctx: PermissionContext = Depends(get_permission_context),
    ) -> IssueResponse:
        """Werk een vraag bij. Met `casus_id` verhuist hij.

        Verhuizen kan alleen binnen hetzelfde initiatief: naar een zichtbare
        casus, of met `casus_id: null` uit de casus naar het initiatief. Dan
        blijft de kring van wie het werk ziet dezelfde, en blijven eigenaar
        en uitvoerders van de taken geldig. De taken gaan mee.
        """
        await require_can_change_casus(db, perm_ctx, current_user, plek)
        repo = IssueRepository(db)
        existing = await issue_in_plek(repo, plek, issue_id)

        # Het initiatief komt van de plek (de casus, of het initiatief uit
        # het pad), nooit alleen van de vraag: een vraag die een oude versie
        # van de app in een casus aanmaakte, heeft initiatief_id leeg, en
        # dan zou de ledencontrole hieronder niets toetsen.
        initiatief_id = plek.initiatief_id
        verhuist = "casus_id" in data.model_fields_set and data.casus_id != plek.id
        nieuwe_plek: Werkplek | None = None
        if verhuist and data.casus_id is not None:
            nieuwe_plek = await _get_casus(db, data.casus_id, init_ctx)
            if nieuwe_plek.initiatief_id != initiatief_id:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Een issue verhuist alleen naar een casus van hetzelfde "
                        "initiatief"
                    ),
                )
        elif verhuist:
            if initiatief_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="Deze casus hoort bij geen initiatief; de vraag blijft erin",
                )
            nieuwe_plek = InitiatiefWerk(initiatief_id=initiatief_id)
        if nieuwe_plek is not None:
            await require_can_change_casus(db, perm_ctx, current_user, nieuwe_plek)
        if "assignee_id" in data.model_fields_set and data.assignee_id is not None:
            await require_initiatief_member(db, initiatief_id, data.assignee_id)

        old_status = existing.status
        was_vrijgegeven = existing.published_at is not None
        if nieuwe_plek is not None:
            await repo.move_to_casus(existing, nieuwe_plek.id, initiatief_id)
        velden = IssueUpdate(
            **data.model_dump(exclude_unset=True, exclude={"casus_id"})
        )
        issue = require_found(await repo.update(issue_id, velden), "Issue")
        hier = nieuwe_plek or plek
        details: dict = {**plek_details(hier), "title": issue.title}
        if nieuwe_plek is not None:
            details["old_casus_id"] = str(plek.id) if plek.id else None
            if plek.id is not None:
                details["old_casus_title"] = plek.title
        if old_status != issue.status:
            details["old_status"], details["new_status"] = old_status, issue.status
        if was_vrijgegeven and issue.published_at is None:
            # Heropend of geen onderzoeksvraag meer: niet langer naar buiten.
            details["niet_meer_vrijgegeven"] = True
        await log_activity(db, current_user, None, "issue.updated", details=details)
        resp = (await _with_counts(repo, [issue]))[0]
        if hier.id is not None and old_status != "done" and issue.status == "done":
            actor = current_user.naam if current_user else None
            await kanaal.meld(
                db,
                hier.id,
                kanaal.bericht_issue_afgerond(
                    hier, issue, resp.task_done_count, resp.task_count, actor
                ),
            )
        return resp

    @router.put("/{issue_id}/publiek", response_model=IssueResponse)
    async def publish_issue(
        issue_id: UUID,
        data: IssuePubliek,
        current_user: OptionalUser,
        plek: Werkplek = Depends(plek_dep),
        db: AsyncSession = Depends(get_db),
        perm_ctx: PermissionContext = Depends(get_permission_context),
    ) -> IssueResponse:
        """Geef een afgeronde onderzoeksvraag vrij voor buiten, of pas de tekst aan.

        Alleen de publieke vraag en het antwoord gaan naar buiten. Opnieuw
        opslaan van een vrijgegeven vraag houdt het moment van vrijgeven.
        """
        await require_can_publish_issue(db, perm_ctx, current_user, plek)
        repo = IssueRepository(db)
        issue = await issue_in_plek(repo, plek, issue_id)
        if not issue.is_onderzoeksvraag:
            raise HTTPException(
                status_code=400, detail="Alleen een onderzoeksvraag gaat naar buiten"
            )
        if issue.status != "done":
            raise HTTPException(
                status_code=400,
                detail="Rond de onderzoeksvraag eerst af, dan kan hij naar buiten",
            )
        issue.public_title = data.public_title.strip()
        issue.public_answer = data.public_answer.strip()
        eerste_keer = issue.published_at is None
        if eerste_keer:
            issue.published_at = datetime.now(UTC)
        await _bewaar(db, issue)
        await log_activity(
            db,
            current_user,
            None,
            "issue.published" if eerste_keer else "issue.public_text_updated",
            details={
                **plek_details(plek),
                "title": issue.title,
                "public_title": issue.public_title,
            },
        )
        return (await _with_counts(repo, [issue]))[0]

    @router.delete("/{issue_id}/publiek", response_model=IssueResponse)
    async def unpublish_issue(
        issue_id: UUID,
        current_user: OptionalUser,
        plek: Werkplek = Depends(plek_dep),
        db: AsyncSession = Depends(get_db),
        perm_ctx: PermissionContext = Depends(get_permission_context),
    ) -> IssueResponse:
        """Trek een vrijgegeven vraag in. De tekst blijft bewaard, binnen; het
        akkoord op het verslag vervalt."""
        await require_can_change_casus(db, perm_ctx, current_user, plek)
        repo = IssueRepository(db)
        issue = await issue_in_plek(repo, plek, issue_id)
        if issue.published_at is not None:
            issue.published_at = None
            # Het akkoord op het verslag gold voor de vraag buiten.
            await verslag_terug_naar_binnen(db, issue.id)
            await _bewaar(db, issue)
            await log_activity(
                db,
                current_user,
                None,
                "issue.unpublished",
                details={**plek_details(plek), "title": issue.title},
            )
        return (await _with_counts(repo, [issue]))[0]

    @router.delete("/{issue_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_issue(
        issue_id: UUID,
        current_user: OptionalUser,
        plek: Werkplek = Depends(plek_dep),
        db: AsyncSession = Depends(get_db),
        perm_ctx: PermissionContext = Depends(get_permission_context),
    ) -> None:
        """Verwijder een vraag. In een casus blijven de taken los op de casus;
        zonder casus kan het alleen als er geen taken onder hangen."""
        await require_can_change_casus(db, perm_ctx, current_user, plek)
        repo = IssueRepository(db)
        existing = await issue_in_plek(repo, plek, issue_id)
        if plek.id is None and await repo.heeft_taken(existing.id):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Er hangen nog taken onder deze vraag. Verwijder ze, of hang "
                    "ze eerst onder een andere vraag"
                ),
            )
        title = existing.title
        # Het verslag gaat via de cascade mee, het bestand niet: dat ruimen
        # we na de commit op.
        paden = await verslag_paden(db, issue_id=existing.id)
        require_deleted(await repo.delete(issue_id), "Issue")
        await log_activity(
            db,
            current_user,
            None,
            "issue.deleted",
            details={**plek_details(plek), "title": title},
        )
        if paden:
            await db.commit()
            for pad in paden:
                await delete_blob(pad)

    return router


router = maak_router("/casussen/{casus_id}/issues", casus_plek, met_volgorde=True)
initiatief_router = maak_router(
    "/initiatieven/{initiatief_id}/vragen", initiatief_plek, met_volgorde=False
)
