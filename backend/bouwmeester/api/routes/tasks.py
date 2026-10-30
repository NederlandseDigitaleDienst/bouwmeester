"""API routes for tasks."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.api.deps import require_deleted, require_found, validate_list
from bouwmeester.core.auth import OptionalUser, effective_person_id
from bouwmeester.core.database import get_db
from bouwmeester.core.org_context import (
    OrgContext,
    check_org_scope,
    check_resource_org_scope,
    get_org_context,
)
from bouwmeester.core.permissions import require_permission
from bouwmeester.core.storage import delete_blob
from bouwmeester.models.person import Person
from bouwmeester.models.task import Task
from bouwmeester.models.task_attachment import TaskAttachment
from bouwmeester.repositories.task import TaskRepository
from bouwmeester.schema.inbox import InboxResponse
from bouwmeester.schema.task import (
    EenheidOverviewResponse,
    ReorderRequest,
    TaskCreate,
    TaskResponse,
    TaskStatus,
    TaskUpdate,
)
from bouwmeester.services.activity_service import (
    ActivityService,
    log_activity,
    resolve_actor,
)
from bouwmeester.services.eenheid_overview_service import EenheidOverviewService
from bouwmeester.services.inbox_service import InboxService
from bouwmeester.services.mention_helper import sync_and_notify_mentions
from bouwmeester.services.notification_service import NotificationService

router = APIRouter(prefix="/tasks", tags=["tasks"])


async def _onderliggende_ids(db: AsyncSession, task_id: UUID) -> list[UUID]:
    """De ids van alle subtaken onder een taak, ook die van subtaken."""
    ids: list[UUID] = []
    rand = [task_id]
    while rand:
        rand = list(
            (await db.execute(select(Task.id).where(Task.parent_id.in_(rand))))
            .scalars()
            .all()
        )
        ids.extend(rand)
    return ids


async def _bijlage_paden(db: AsyncSession, task_id: UUID) -> list[str]:
    """Paden van de bijlagebestanden van een taak en al haar subtaken."""
    ids = [task_id, *await _onderliggende_ids(db, task_id)]
    result = await db.execute(
        select(TaskAttachment.pad).where(TaskAttachment.task_id.in_(ids))
    )
    return list(result.scalars().all())


@router.get("", response_model=list[TaskResponse])
async def list_tasks(
    current_user: OptionalUser,
    status_filter: TaskStatus | None = Query(None, alias="status"),
    node_id: UUID | None = Query(None),
    assignee_id: UUID | None = Query(None),
    organisatie_eenheid_id: UUID | None = Query(None),
    opdracht_id: UUID | None = Query(None),
    include_children: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
) -> list[TaskResponse]:
    """List tasks with optional filters."""
    repo = TaskRepository(db)
    if opdracht_id is not None:
        tasks = await repo.get_by_opdracht(
            opdracht_id, skip=skip, limit=limit, org_ctx=org_ctx
        )
    elif node_id is not None:
        tasks = await repo.get_by_node(node_id, skip=skip, limit=limit, org_ctx=org_ctx)
    elif assignee_id is not None:
        tasks = await repo.get_by_assignee(
            assignee_id, skip=skip, limit=limit, org_ctx=org_ctx
        )
    elif organisatie_eenheid_id is not None:
        tasks = await repo.get_by_organisatie_eenheid(
            organisatie_eenheid_id,
            include_children=include_children,
            skip=skip,
            limit=limit,
            org_ctx=org_ctx,
        )
    else:
        tasks = await repo.get_all(
            skip=skip,
            limit=limit,
            status=status_filter,
            org_ctx=org_ctx,
        )
    return validate_list(TaskResponse, tasks)


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    data: TaskCreate,
    current_user: OptionalUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("task:create")),
    org_ctx: OrgContext = Depends(get_org_context),
) -> TaskResponse:
    """Create a task linked to a node. Notifies assignee and team manager."""
    check_org_scope(data.organisatie_eenheid_id, org_ctx)
    repo = TaskRepository(db)
    task = await repo.create(data)

    await sync_and_notify_mentions(
        db,
        "task",
        task.id,
        data.description,
        task.title,
        sender_id=data.assignee_id,
        source_task_id=task.id,
        source_node_id=task.node_id,
    )

    resolved_id, resolved_naam = await resolve_actor(current_user, actor_id, db)

    # Notify assignee
    notif_svc = NotificationService(db)
    if task.assignee_id:
        assignee = await db.get(Person, task.assignee_id)
        if assignee:
            await notif_svc.notify_task_assigned(task, assignee, actor_id=resolved_id)

    # Notify team manager
    if task.organisatie_eenheid_id:
        await notif_svc.notify_team_manager(
            task, task.organisatie_eenheid_id, exclude_person_id=task.assignee_id
        )

    assignee_naam = assignee.naam if task.assignee_id and assignee else None
    await ActivityService(db).log_event(
        "task.created",
        actor_id=resolved_id,
        actor_naam=resolved_naam,
        task_id=task.id,
        node_id=task.node_id,
        details={
            "title": task.title,
            "priority": task.priority,
            "assignee_id": str(task.assignee_id) if task.assignee_id else None,
            "assignee_naam": assignee_naam,
        },
    )

    return TaskResponse.model_validate(task)


@router.get("/my", response_model=list[TaskResponse])
async def get_my_tasks(
    current_user: OptionalUser,
    person_id: UUID | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[TaskResponse]:
    """Get tasks assigned to the current user (or person_id in dev mode).

    No org_ctx filter: a user is always entitled to see tasks assigned to
    them, even in units they cannot otherwise browse.
    """
    pid = effective_person_id(current_user, person_id)
    repo = TaskRepository(db)
    tasks = await repo.get_by_assignee(pid, skip=skip, limit=limit)
    return validate_list(TaskResponse, tasks)


@router.get("/inbox", response_model=InboxResponse)
async def get_task_inbox(
    current_user: OptionalUser,
    person_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> InboxResponse:
    """Get aggregated inbox data for a person (tasks, notifications, deadlines).

    Inbox is always self-scoped (own tasks/notifications), so no org_ctx.
    """
    pid = effective_person_id(current_user, person_id)
    service = InboxService(db)
    return await service.get_inbox(pid)


@router.get("/unassigned", response_model=list[TaskResponse])
async def get_unassigned_tasks(
    current_user: OptionalUser,
    organisatie_eenheid_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("task:read")),
    org_ctx: OrgContext = Depends(get_org_context),
) -> list[TaskResponse]:
    """List tasks that have no assignee, optionally filtered by org unit."""
    if organisatie_eenheid_id is not None:
        check_org_scope(organisatie_eenheid_id, org_ctx)
    repo = TaskRepository(db)
    tasks = await repo.get_unassigned(organisatie_eenheid_id, org_ctx=org_ctx)
    return validate_list(TaskResponse, tasks)


@router.get("/work-types", response_model=list[str])
async def get_work_types(
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("task:read")),
    org_ctx: OrgContext = Depends(get_org_context),
) -> list[str]:
    """Return distinct work_type values for autocomplete."""
    repo = TaskRepository(db)
    return await repo.get_distinct_work_types(org_ctx=org_ctx)


@router.get("/eenheid-overview", response_model=EenheidOverviewResponse)
async def get_eenheid_overview(
    current_user: OptionalUser,
    organisatie_eenheid_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("task:read")),
    org_ctx: OrgContext = Depends(get_org_context),
) -> EenheidOverviewResponse:
    """Overview of tasks for an organisatie-eenheid."""
    check_org_scope(organisatie_eenheid_id, org_ctx)
    service = EenheidOverviewService(db)
    return await service.get_overview(organisatie_eenheid_id)


@router.get("/{id}", response_model=TaskResponse)
async def get_task(
    id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("task:read")),
    org_ctx: OrgContext = Depends(get_org_context),
) -> TaskResponse:
    """Get a single task by ID, including assignee and node summaries."""
    await check_resource_org_scope(db, "task", id, org_ctx)
    repo = TaskRepository(db)
    task = require_found(await repo.get(id), "Task")
    return TaskResponse.model_validate(task)


@router.get("/{id}/subtasks", response_model=list[TaskResponse])
async def get_task_subtasks(
    id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("task:read")),
    org_ctx: OrgContext = Depends(get_org_context),
) -> list[TaskResponse]:
    """List subtasks of a parent task."""
    await check_resource_org_scope(db, "task", id, org_ctx)
    repo = TaskRepository(db)
    subtasks = await repo.get_subtasks(id, org_ctx=org_ctx)
    return [TaskResponse.model_validate(t) for t in subtasks]


@router.put("/{id}/subtasks/reorder", response_model=list[TaskResponse])
async def reorder_subtasks(
    id: UUID,
    data: ReorderRequest,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("task:update")),
    org_ctx: OrgContext = Depends(get_org_context),
) -> list[TaskResponse]:
    """Reorder subtasks of a parent task."""
    await check_resource_org_scope(db, "task", id, org_ctx)
    repo = TaskRepository(db)
    require_found(await repo.get(id), "Task")
    try:
        subtasks = await repo.reorder_subtasks(id, data.task_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return [TaskResponse.model_validate(t) for t in subtasks]


@router.put("/{id}", response_model=TaskResponse)
async def update_task(
    id: UUID,
    data: TaskUpdate,
    current_user: OptionalUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("task:update")),
    org_ctx: OrgContext = Depends(get_org_context),
) -> TaskResponse:
    """Update a task. Notifies on assignee change, completion, or org unit change."""
    await check_resource_org_scope(db, "task", id, org_ctx)
    if data.organisatie_eenheid_id is not None:
        check_org_scope(data.organisatie_eenheid_id, org_ctx)
    repo = TaskRepository(db)

    # Capture old state before update
    old_task = await repo.get(id)
    old_assignee_id = old_task.assignee_id if old_task else None
    old_status = old_task.status if old_task else None
    old_org_unit_id = old_task.organisatie_eenheid_id if old_task else None

    task = require_found(await repo.update(id, data), "Task")

    await sync_and_notify_mentions(
        db,
        "task",
        task.id,
        data.description,
        task.title,
        sender_id=data.assignee_id,
        source_task_id=task.id,
        source_node_id=task.node_id,
    )

    resolved_id, resolved_naam = await resolve_actor(current_user, actor_id, db)
    notif_svc = NotificationService(db)

    # Detect assignee changes
    new_assignee_id = task.assignee_id
    if new_assignee_id and new_assignee_id != old_assignee_id:
        new_assignee = await db.get(Person, new_assignee_id)
        if new_assignee:
            if old_assignee_id:
                # Reassignment: notify both
                await notif_svc.notify_task_reassigned(
                    task, old_assignee_id, new_assignee
                )
            else:
                # First assignment
                await notif_svc.notify_task_assigned(
                    task,
                    new_assignee,
                    actor_id=resolved_id,
                )

    # Detect status → done
    if task.status == "done" and old_status != "done":
        await notif_svc.notify_task_completed(task, actor_id=resolved_id)

    # Detect org unit change
    new_org_unit_id = task.organisatie_eenheid_id
    if new_org_unit_id and new_org_unit_id != old_org_unit_id:
        await notif_svc.notify_team_manager(
            task, new_org_unit_id, exclude_person_id=task.assignee_id
        )

    # Build change details for audit log
    changes: dict = {}
    if old_status != task.status:
        changes["old_status"] = old_status
        changes["new_status"] = task.status
    if old_assignee_id != task.assignee_id:
        changes["old_assignee_id"] = str(old_assignee_id) if old_assignee_id else None
        changes["new_assignee_id"] = str(task.assignee_id) if task.assignee_id else None
        if task.assignee_id:
            new_person = await db.get(Person, task.assignee_id)
            changes["new_assignee_naam"] = new_person.naam if new_person else None

    await ActivityService(db).log_event(
        "task.updated",
        actor_id=resolved_id,
        actor_naam=resolved_naam,
        task_id=task.id,
        node_id=task.node_id,
        details={"title": task.title, **changes},
    )

    return TaskResponse.model_validate(task)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    id: UUID,
    current_user: OptionalUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("task:delete")),
    org_ctx: OrgContext = Depends(get_org_context),
) -> None:
    """Delete a task permanently."""
    await check_resource_org_scope(db, "task", id, org_ctx)
    repo = TaskRepository(db)
    task = await repo.get(id)
    task_title = task.title if task else None
    task_node_id = task.node_id if task else None
    # Bijlagen gaan in de database mee (CASCADE), hun bestanden niet: die
    # ruimen we hier zelf op, ook die van subtaken.
    bijlage_paden = await _bijlage_paden(db, id) if task else []
    require_deleted(await repo.delete(id), "Task")
    for pad in bijlage_paden:
        await delete_blob(pad)
    await log_activity(
        db,
        current_user,
        actor_id,
        "task.deleted",
        details={
            "task_id": str(id),
            "node_id": str(task_node_id) if task_node_id else None,
            "title": task_title,
        },
    )
