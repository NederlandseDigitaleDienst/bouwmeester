"""API routes voor issues binnen een casus.

Zelfde toegangsregel als de casus: wie de casus ziet, mag de issues zien en
bewerken. Bij verwijderen van een issue blijven de taken op de casus staan
(issue_id wordt leeg).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.api.deps import require_deleted, require_found
from bouwmeester.core.auth import OptionalUser
from bouwmeester.core.database import get_db
from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    get_initiatief_context,
    require_initiatief_member,
    require_initiatief_visible,
)
from bouwmeester.models.casus import Casus
from bouwmeester.repositories.issue import IssueRepository
from bouwmeester.schema.issue import (
    IssueCreate,
    IssueReorder,
    IssueResponse,
    IssueUpdate,
)
from bouwmeester.services.activity_service import log_activity

router = APIRouter(prefix="/casussen/{casus_id}/issues", tags=["issues"])


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


async def _with_counts(repo: IssueRepository, issues) -> list[IssueResponse]:
    counts = await repo.counts([i.id for i in issues])
    out = []
    for i in issues:
        resp = IssueResponse.model_validate(i)
        resp.task_count, resp.task_done_count = counts.get(i.id, (0, 0))
        out.append(resp)
    return out


@router.get("", response_model=list[IssueResponse])
async def list_issues(
    casus_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[IssueResponse]:
    await _get_casus(db, casus_id, init_ctx)
    repo = IssueRepository(db)
    return await _with_counts(repo, await repo.list_for_casus(casus_id))


@router.post("", response_model=IssueResponse, status_code=status.HTTP_201_CREATED)
async def create_issue(
    casus_id: UUID,
    data: IssueCreate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> IssueResponse:
    casus = await _get_casus(db, casus_id, init_ctx)
    if data.assignee_id is not None:
        await require_initiatief_member(db, casus.initiatief_id, data.assignee_id)
    repo = IssueRepository(db)
    issue = await repo.create_for_casus(casus_id, data)
    await log_activity(
        db,
        current_user,
        None,
        "issue.created",
        details={
            "casus_id": str(casus_id),
            "casus_title": casus.title,
            "title": issue.title,
        },
    )
    return (await _with_counts(repo, [issue]))[0]


@router.put("/reorder", response_model=list[IssueResponse])
async def reorder_issues(
    casus_id: UUID,
    data: IssueReorder,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[IssueResponse]:
    await _get_casus(db, casus_id, init_ctx)
    repo = IssueRepository(db)
    try:
        issues = await repo.reorder(casus_id, data.issue_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await _with_counts(repo, issues)


@router.put("/{issue_id}", response_model=IssueResponse)
async def update_issue(
    casus_id: UUID,
    issue_id: UUID,
    data: IssueUpdate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> IssueResponse:
    """Werk een issue bij. Met `casus_id` verhuist het naar een andere casus.

    Verhuizen kan alleen naar een zichtbare casus van hetzelfde initiatief:
    dan blijft de kring van wie het werk ziet dezelfde, en blijven eigenaar
    en uitvoerders van de taken geldig. De taken gaan mee.
    """
    casus = await _get_casus(db, casus_id, init_ctx)
    repo = IssueRepository(db)
    existing = require_found(await repo.get(issue_id), "Issue")
    if existing.casus_id != casus_id:
        raise HTTPException(status_code=404, detail="Onderzoeksvraag niet gevonden")

    nieuwe_casus: Casus | None = None
    if data.casus_id is not None and data.casus_id != casus_id:
        nieuwe_casus = await _get_casus(db, data.casus_id, init_ctx)
        if nieuwe_casus.initiatief_id != casus.initiatief_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Een issue verhuist alleen naar een casus van hetzelfde initiatief"
                ),
            )
    if "assignee_id" in data.model_fields_set and data.assignee_id is not None:
        await require_initiatief_member(db, casus.initiatief_id, data.assignee_id)

    old_status = existing.status
    if nieuwe_casus is not None:
        await repo.move_to_casus(existing, nieuwe_casus.id)
    velden = IssueUpdate(**data.model_dump(exclude_unset=True, exclude={"casus_id"}))
    issue = require_found(await repo.update(issue_id, velden), "Issue")
    details: dict = {
        "casus_id": str(issue.casus_id),
        "casus_title": (nieuwe_casus or casus).title,
        "title": issue.title,
    }
    if nieuwe_casus is not None:
        details["old_casus_id"], details["old_casus_title"] = str(casus_id), casus.title
    if old_status != issue.status:
        details["old_status"], details["new_status"] = old_status, issue.status
    await log_activity(db, current_user, None, "issue.updated", details=details)
    return (await _with_counts(repo, [issue]))[0]


@router.delete("/{issue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_issue(
    casus_id: UUID,
    issue_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> None:
    """Verwijder een issue. De taken eronder blijven los op de casus."""
    casus = await _get_casus(db, casus_id, init_ctx)
    repo = IssueRepository(db)
    existing = await repo.get(issue_id)
    if existing is None or existing.casus_id != casus_id:
        raise HTTPException(status_code=404, detail="Onderzoeksvraag niet gevonden")
    title = existing.title
    require_deleted(await repo.delete(issue_id), "Issue")
    await log_activity(
        db,
        current_user,
        None,
        "issue.deleted",
        details={"casus_id": str(casus_id), "casus_title": casus.title, "title": title},
    )
