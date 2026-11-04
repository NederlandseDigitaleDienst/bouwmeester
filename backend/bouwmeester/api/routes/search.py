"""API routes for omni full-text search."""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.core.auth import OptionalUser
from bouwmeester.core.database import get_db
from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    get_initiatief_context,
)
from bouwmeester.core.org_context import OrgContext, get_org_context
from bouwmeester.core.permissions import PermissionContext, get_permission_context
from bouwmeester.repositories.search import SearchRepository
from bouwmeester.schema.search import (
    SearchResponse,
    SearchResult,
    SearchResultType,
    SimilarNodeItem,
    SimilarNodesResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])

# Maps each search result type to the permission required to see it
_TYPE_PERMISSION: dict[str, str] = {
    "corpus_node": "node:read",
    "task": "task:read",
    "person": "people:read",
    "organisatie_eenheid": "org:read",
    "parlementair_item": "node:read",
    "tag": "node:read",
    "lead": "lead:read",
}


@router.get("", response_model=SearchResponse)
async def search(
    current_user: OptionalUser,
    q: str = Query(..., min_length=1, max_length=500),
    result_types: list[SearchResultType] | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> SearchResponse:
    """Full-text search across nodes, tasks, people, and org units.

    Results are filtered by the user's RBAC permissions — entity types
    the user lacks read access for are excluded.
    """
    type_values = [rt.value for rt in result_types] if result_types else None

    # Filter to only types the user has permission for
    allowed_types = {
        t for t, perm in _TYPE_PERMISSION.items() if perm_ctx.has_permission(perm)
    }
    if type_values:
        type_values = [t for t in type_values if t in allowed_types]
    else:
        type_values = list(allowed_types) if not perm_ctx.is_super_admin else None

    if type_values is not None and not type_values:
        return SearchResponse(results=[], total=0, query=q)

    repo = SearchRepository(db)
    results = await repo.full_text_search(
        query=q,
        result_types=type_values,
        limit=limit,
        org_ctx=org_ctx,
        init_ctx=init_ctx,
    )
    return SearchResponse(
        results=[SearchResult(**r) for r in results],
        total=len(results),
        query=q,
    )


@router.get("/similar-nodes", response_model=SimilarNodesResponse)
async def find_similar_nodes(
    current_user: OptionalUser,
    title: str = Query(..., min_length=3, max_length=500),
    exclude_id: str | None = Query(None),
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
) -> SimilarNodesResponse:
    """Find corpus nodes with similar titles (trigram + FTS)."""
    repo = SearchRepository(db)
    items = await repo.find_similar_nodes(
        title=title,
        exclude_node_id=exclude_id,
        limit=limit,
        org_ctx=org_ctx,
    )
    return SimilarNodesResponse(items=[SimilarNodeItem(**i) for i in items])
