"""API routes for tasks."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.api.deps import require_deleted, require_found, validate_list
from bouwmeester.core.auth import OptionalUser, effective_person_id
from bouwmeester.core.database import get_db
from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    get_initiatief_context,
    require_initiatief_member,
    require_initiatief_visible,
)
from bouwmeester.core.org_context import (
    OrgContext,
    check_org_scope,
    check_resource_org_scope,
    get_org_context,
)
from bouwmeester.core.permissions import require_permission
from bouwmeester.core.storage import delete_blob
from bouwmeester.models.casus import Casus
from bouwmeester.models.issue import Issue
from bouwmeester.models.person import Person
from bouwmeester.models.task import Task
from bouwmeester.models.task_attachment import TaskAttachment
from bouwmeester.repositories.issue import IssueRepository
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


async def _resolve_casus_anchor(
    db: AsyncSession, data: TaskCreate | TaskUpdate, init_ctx: InitiatiefContext
) -> Casus | None:
    """Controleer casus_id en issue_id en vul casus_id aan.

    Een taak hangt onder een issue of los op de casus. Het issue moet van
    die casus zijn. De
    casus moet zichtbaar zijn: buiten een zichtbaar initiatief 404, ook via
    een issue, zodat het bestaan niet lekt. Geeft de casus terug.
    """
    if data.issue_id is not None:
        issue = await db.get(Issue, data.issue_id)
        if issue is None:
            raise HTTPException(status_code=404, detail="Onderzoeksvraag niet gevonden")
        if data.casus_id is not None and data.casus_id != issue.casus_id:
            raise HTTPException(
                status_code=400, detail="Onderzoeksvraag hoort niet bij deze casus"
            )
        data.casus_id = issue.casus_id
    if data.casus_id is None:
        return None
    casus = await db.get(Casus, data.casus_id)
    if casus is None:
        raise HTTPException(status_code=404, detail="Casus niet gevonden")
    require_initiatief_visible(
        casus.initiatief_id, init_ctx, detail="Casus niet gevonden"
    )
    return casus


async def _require_task_visible(
    db: AsyncSession, task, init_ctx: InitiatiefContext
) -> None:
    """Een casustaak is zo zichtbaar als haar casus: anders 404, geen 403."""
    if task.casus_id is None:
        return
    casus = await db.get(Casus, task.casus_id)
    initiatief_id = casus.initiatief_id if casus else None
    require_initiatief_visible(initiatief_id, init_ctx, detail="Task not found")


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


async def _require_parent_visible(
    db: AsyncSession, parent_id: UUID, org_ctx: OrgContext, init_ctx: InitiatiefContext
) -> Task:
    """De hoofdtaak van een subtaak moet bestaan en zichtbaar zijn.

    Zonder deze controle hing je een subtaak onder elke taak waarvan je het
    id kent. Zelfde regels als het openen van die taak: 404 buiten een
    zichtbare casus.
    """
    parent = await db.get(Task, parent_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="Hoofdtaak niet gevonden")
    await check_resource_org_scope(db, "task", parent_id, org_ctx)
    await _require_task_visible(db, parent, init_ctx)
    return parent


def _geen_subtaak_in_casus(parent: Task, casus_taak: bool) -> None:
    """Een taak in een casus heeft geen subtaken en hangt onder geen taak.

    In een casus is het werk een onderzoeksvraag met taken eronder; een
    stap die erbij hoort, is een eigen taak onder die vraag. Subtaken
    blijven er voor taken aan een node.
    """
    if parent.casus_id is not None or casus_taak:
        raise HTTPException(
            status_code=400, detail="Een taak in een casus heeft geen subtaken"
        )


async def _bijlage_paden(db: AsyncSession, task_id: UUID) -> list[str]:
    """Paden van de bijlagebestanden van een taak en al haar subtaken."""
    ids = [task_id, *await _onderliggende_ids(db, task_id)]
    result = await db.execute(
        select(TaskAttachment.pad).where(TaskAttachment.task_id.in_(ids))
    )
    return list(result.scalars().all())


async def _require_assignee_in_initiatief(
    db: AsyncSession, casus: Casus | None, assignee_id: UUID | None
) -> None:
    """Wie een casustaak doet, moet het initiatief van de casus kunnen zien.

    Anders krijgt iemand een taak op zijn naam die hij niet kan openen. De
    UI biedt alleen leden aan; dit is de bewaker.
    """
    if casus is None or assignee_id is None:
        return
    await require_initiatief_member(db, casus.initiatief_id, assignee_id)


@router.get("", response_model=list[TaskResponse])
async def list_tasks(
    current_user: OptionalUser,
    status_filter: TaskStatus | None = Query(None, alias="status"),
    node_id: UUID | None = Query(None),
    casus_id: UUID | None = Query(None),
    assignee_id: UUID | None = Query(None),
    organisatie_eenheid_id: UUID | None = Query(None),
    opdracht_id: UUID | None = Query(None),
    include_children: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[TaskResponse]:
    """List tasks with optional filters.

    Taken van een casus zijn zo vertrouwelijk als de casus: buiten een
    zichtbaar initiatief is het antwoord 404, zoals bij de casus zelf.
    """
    repo = TaskRepository(db)
    if opdracht_id is not None:
        tasks = await repo.get_by_opdracht(
            opdracht_id, skip=skip, limit=limit, org_ctx=org_ctx, init_ctx=init_ctx
        )
    elif node_id is not None:
        tasks = await repo.get_by_node(
            node_id, skip=skip, limit=limit, org_ctx=org_ctx, init_ctx=init_ctx
        )
    elif casus_id is not None:
        casus = await db.get(Casus, casus_id)
        if casus is None:
            return []
        require_initiatief_visible(
            casus.initiatief_id, init_ctx, detail="Casus niet gevonden"
        )
        tasks = await repo.get_by_casus(
            casus_id,
            skip=skip,
            limit=limit,
            org_ctx=org_ctx,
        )
    elif assignee_id is not None:
        tasks = await repo.get_by_assignee(
            assignee_id, skip=skip, limit=limit, org_ctx=org_ctx, init_ctx=init_ctx
        )
    elif organisatie_eenheid_id is not None:
        tasks = await repo.get_by_organisatie_eenheid(
            organisatie_eenheid_id,
            include_children=include_children,
            skip=skip,
            limit=limit,
            org_ctx=org_ctx,
            init_ctx=init_ctx,
        )
    else:
        tasks = await repo.get_all(
            skip=skip,
            limit=limit,
            status=status_filter,
            org_ctx=org_ctx,
            init_ctx=init_ctx,
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
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> TaskResponse:
    """Create a task linked to a node or a casus. Notifies assignee and manager.

    Op een casus: de casus moet zichtbaar zijn en wie de taak doet moet het
    initiatief kunnen zien.
    """
    check_org_scope(data.organisatie_eenheid_id, org_ctx)
    if data.parent_id is not None:
        # Een subtaak is een gewone taak met eigen kenmerken, zoals op main:
        # ze neemt niets over van de hoofdtaak. Alleen buiten een casus.
        parent = await _require_parent_visible(db, data.parent_id, org_ctx, init_ctx)
        _geen_subtaak_in_casus(
            parent, data.casus_id is not None or data.issue_id is not None
        )
    casus = await _resolve_casus_anchor(db, data, init_ctx)
    await _require_assignee_in_initiatief(db, casus, data.assignee_id)
    repo = TaskRepository(db)
    task = await repo.create(data)
    issue_repo = IssueRepository(db)
    await issue_repo.sync_status(task.issue_id)

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
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[TaskResponse]:
    """Get tasks assigned to the current user (or person_id in dev mode).

    No org_ctx filter: a user is always entitled to see tasks assigned to
    them, even in units they cannot otherwise browse. Casustaken zijn de
    uitzondering: die volgen het initiatief van de casus.
    """
    pid = effective_person_id(current_user, person_id)
    repo = TaskRepository(db)
    tasks = await repo.get_by_assignee(pid, skip=skip, limit=limit, init_ctx=init_ctx)
    return validate_list(TaskResponse, tasks)


@router.get("/inbox", response_model=InboxResponse)
async def get_task_inbox(
    current_user: OptionalUser,
    person_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> InboxResponse:
    """Get aggregated inbox data for a person (tasks, notifications, deadlines).

    Inbox is always self-scoped (own tasks/notifications), so no org_ctx.
    Casustaken volgen wel het initiatief van de casus.
    """
    pid = effective_person_id(current_user, person_id)
    service = InboxService(db)
    return await service.get_inbox(pid, init_ctx=init_ctx)


@router.get("/unassigned", response_model=list[TaskResponse])
async def get_unassigned_tasks(
    current_user: OptionalUser,
    organisatie_eenheid_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("task:read")),
    org_ctx: OrgContext = Depends(get_org_context),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[TaskResponse]:
    """List tasks that have no assignee, optionally filtered by org unit."""
    if organisatie_eenheid_id is not None:
        check_org_scope(organisatie_eenheid_id, org_ctx)
    repo = TaskRepository(db)
    tasks = await repo.get_unassigned(
        organisatie_eenheid_id, org_ctx=org_ctx, init_ctx=init_ctx
    )
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
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> TaskResponse:
    """Get a single task by ID, including assignee and node summaries."""
    await check_resource_org_scope(db, "task", id, org_ctx)
    repo = TaskRepository(db)
    task = require_found(await repo.get(id), "Task")
    await _require_task_visible(db, task, init_ctx)
    return TaskResponse.model_validate(task)


@router.get("/{id}/subtasks", response_model=list[TaskResponse])
async def get_task_subtasks(
    id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("task:read")),
    org_ctx: OrgContext = Depends(get_org_context),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[TaskResponse]:
    """List subtasks of a parent task."""
    await check_resource_org_scope(db, "task", id, org_ctx)
    repo = TaskRepository(db)
    parent = require_found(await repo.get(id), "Task")
    await _require_task_visible(db, parent, init_ctx)
    subtasks = await repo.get_subtasks(id, org_ctx=org_ctx, init_ctx=init_ctx)
    return [TaskResponse.model_validate(t) for t in subtasks]


@router.put("/{id}/subtasks/reorder", response_model=list[TaskResponse])
async def reorder_subtasks(
    id: UUID,
    data: ReorderRequest,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("task:update")),
    org_ctx: OrgContext = Depends(get_org_context),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[TaskResponse]:
    """Reorder subtasks of a parent task."""
    await check_resource_org_scope(db, "task", id, org_ctx)
    repo = TaskRepository(db)
    parent = require_found(await repo.get(id), "Task")
    await _require_task_visible(db, parent, init_ctx)
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
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> TaskResponse:
    """Update a task. Notifies on assignee change, completion, or org unit change.

    Een casustaak: alleen binnen een zichtbare casus, en wie de taak doet
    moet lid zijn van het initiatief. Dat geldt ook als de taak naar een
    andere casus verhuist of als alleen de uitvoerder verandert.
    """
    await check_resource_org_scope(db, "task", id, org_ctx)
    repo = TaskRepository(db)
    old_task = require_found(await repo.get(id), "Task")
    await _require_task_visible(db, old_task, init_ctx)
    if data.organisatie_eenheid_id is not None:
        check_org_scope(data.organisatie_eenheid_id, org_ctx)
    # Een taak in een casus heeft geen subtaken en hangt onder geen taak:
    # niet bij een nieuwe hoofdtaak, en niet als een subtaak of een taak met
    # subtaken naar een casus gaat.
    naar_casus = (
        getattr(data, "casus_id", None) is not None
        or getattr(data, "issue_id", None) is not None
    )
    in_casus_na = old_task.casus_id is not None or naar_casus
    nieuwe_parent = "parent_id" in data.model_fields_set and data.parent_id
    if nieuwe_parent:
        parent = await _require_parent_visible(db, data.parent_id, org_ctx, init_ctx)
        _geen_subtaak_in_casus(parent, in_casus_na)
    elif naar_casus and old_task.parent_id is not None:
        _geen_subtaak_in_casus(old_task, True)
    if naar_casus and await _onderliggende_ids(db, old_task.id):
        _geen_subtaak_in_casus(old_task, True)
    anker_velden = {"issue_id", "casus_id"}
    if anker_velden & data.model_fields_set:
        casus = await _resolve_casus_anchor(db, data, init_ctx)
    elif old_task.casus_id is not None:
        casus = await db.get(Casus, old_task.casus_id)
    else:
        casus = None
    assignee_na = (
        data.assignee_id
        if "assignee_id" in data.model_fields_set
        else old_task.assignee_id
    )
    await _require_assignee_in_initiatief(db, casus, assignee_na)

    # Capture old state before update
    old_assignee_id = old_task.assignee_id
    old_status = old_task.status
    old_org_unit_id = old_task.organisatie_eenheid_id

    issue_repo = IssueRepository(db)
    old_issue_id = old_task.issue_id
    task = require_found(await repo.update(id, data), "Task")
    # De status van het issue volgt de taken; bij een verhuizing beide.
    new_issue_id = task.issue_id
    await issue_repo.sync_status(new_issue_id)
    if old_issue_id != new_issue_id:
        await issue_repo.sync_status(old_issue_id)

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
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> None:
    """Delete a task permanently."""
    await check_resource_org_scope(db, "task", id, org_ctx)
    repo = TaskRepository(db)
    task = await repo.get(id)
    if task is not None:
        await _require_task_visible(db, task, init_ctx)
    task_title = task.title if task else None
    task_node_id = task.node_id if task else None
    issue_repo = IssueRepository(db)
    issue_id = task.issue_id if task else None
    # Bijlagen gaan in de database mee (CASCADE), hun bestanden niet: die
    # ruimen we hier zelf op, ook die van subtaken.
    bijlage_paden = await _bijlage_paden(db, id) if task else []
    require_deleted(await repo.delete(id), "Task")
    await issue_repo.sync_status(issue_id)
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
