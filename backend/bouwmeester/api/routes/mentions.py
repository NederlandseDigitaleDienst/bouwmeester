"""API routes for mention search and references."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.core.auth import OptionalUser
from bouwmeester.core.database import get_db
from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    get_initiatief_context,
)
from bouwmeester.core.org_context import OrgContext, get_org_context
from bouwmeester.schema.mention import MentionReference, MentionSearchResult
from bouwmeester.services.mention_service import MentionService

router = APIRouter(prefix="/mentions", tags=["mentions"])


@router.get("/search", response_model=list[MentionSearchResult])
async def search_mentionables(
    current_user: OptionalUser,
    q: str = Query("", min_length=0, max_length=500),
    types: str = Query("node,task,tag"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[MentionSearchResult]:
    """Search nodes, tasks, and tags for # mention suggestions."""
    service = MentionService(db)
    type_list = [t.strip() for t in types.split(",") if t.strip()]
    if not q.strip():
        return []
    return await service.search_mentionables(
        q.strip(), type_list, limit, org_ctx=org_ctx, init_ctx=init_ctx
    )


@router.get("/references/{target_id}", response_model=list[MentionReference])
async def get_references(
    target_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[MentionReference]:
    """Get all places where target_id is mentioned."""
    service = MentionService(db)
    return await service.get_references(target_id, org_ctx=org_ctx, init_ctx=init_ctx)
