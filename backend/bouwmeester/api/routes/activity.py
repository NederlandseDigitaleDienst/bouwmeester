"""API routes for activity feed and inbox."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.core.auth import OptionalUser, effective_person_id
from bouwmeester.core.database import get_db
from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    get_initiatief_context,
)
from bouwmeester.core.permissions import require_permission
from bouwmeester.schema.activity import ActivityFeedResponse, ActivityResponse
from bouwmeester.schema.inbox import InboxResponse
from bouwmeester.services.activity_service import ActivityService
from bouwmeester.services.inbox_service import InboxService

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("/feed", response_model=ActivityFeedResponse)
async def get_activity_feed(
    _perm=Depends(require_permission("audit:read")),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    event_type: str | None = Query(None, max_length=50, pattern=r"^[a-z][a-z_.]*$"),
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> ActivityFeedResponse:
    """Get paginated audit log. Filter by event_type or actor_id."""
    service = ActivityService(db)
    activities = await service.get_recent(
        skip=skip, limit=limit, event_type=event_type, actor_id=actor_id
    )
    # Note: items and total are fetched separately; count may differ slightly
    # under concurrent writes. Acceptable for audit log pagination.
    total = await service.count(event_type=event_type, actor_id=actor_id)
    return ActivityFeedResponse(
        items=[ActivityResponse.model_validate(a) for a in activities],
        total=total,
    )


@router.get("/inbox", response_model=InboxResponse)
async def get_inbox(
    current_user: OptionalUser,
    person_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> InboxResponse:
    """Get aggregated inbox for a person (tasks, notifications, deadlines).

    Casustaken volgen het initiatief van de casus, net als in /tasks/inbox.
    """
    pid = effective_person_id(current_user, person_id)
    service = InboxService(db)
    return await service.get_inbox(pid, init_ctx=init_ctx)
