"""API routes for corpus nodes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.api.deps import require_deleted, require_found, validate_list
from bouwmeester.core.auth import OptionalUser
from bouwmeester.core.authority import (
    require_can_change_resource_role,
    require_can_grant_resource_role,
)
from bouwmeester.core.database import get_db
from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    get_initiatief_context,
)
from bouwmeester.core.org_context import (
    OrgContext,
    check_resource_org_scope,
    get_org_context,
)
from bouwmeester.core.permissions import (
    PermissionContext,
    get_permission_context,
    require_permission,
)
from bouwmeester.models.person import Person
from bouwmeester.repositories.corpus_node import CorpusNodeRepository
from bouwmeester.repositories.opdracht import OpdrachtRepository
from bouwmeester.repositories.resource_permission import ResourcePermissionRepository
from bouwmeester.repositories.task import TaskRepository
from bouwmeester.schema.bron import BronResponse, BronUpdate
from bouwmeester.schema.corpus_node import (
    BeleidskompasProgress,
    CorpusNodeCreate,
    CorpusNodeResponse,
    CorpusNodeUpdate,
    CorpusNodeWithEdges,
    FinancieelSummary,
    NodeStatusRecord,
    NodeTitleRecord,
    NodeType,
)
from bouwmeester.schema.edge import EdgeResponse
from bouwmeester.schema.graph import (
    GraphNeighborsResponse,
    GraphViewResponse,
    NeighborEntry,
)
from bouwmeester.schema.opdracht import (
    FinancieelOverzicht,
    OpdrachtResponse,
)
from bouwmeester.schema.person import (
    NodeStakeholderCreate,
    NodeStakeholderResponse,
    NodeStakeholderUpdate,
)
from bouwmeester.schema.tag import NodeTagCreate, NodeTagResponse, TagCreate
from bouwmeester.schema.task import TaskResponse
from bouwmeester.services.activity_service import (
    ActivityService,
    log_activity,
    resolve_actor,
)
from bouwmeester.services.financieel_service import FinancieelService
from bouwmeester.services.mention_helper import sync_and_notify_mentions
from bouwmeester.services.node_service import NodeService
from bouwmeester.services.notification_service import NotificationService

# Resolve forward reference to EdgeResponse in CorpusNodeWithEdges.
CorpusNodeWithEdges.model_rebuild()

router = APIRouter(prefix="/nodes", tags=["nodes"])


@router.get("", response_model=list[CorpusNodeResponse])
async def list_nodes(
    current_user: OptionalUser,
    node_type: NodeType | None = None,
    search: str | None = Query(None, max_length=200),
    include_unconnected_pi: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
) -> list[CorpusNodeResponse]:
    """List all corpus nodes, optionally filtered by node_type and/or title search.

    By default, politieke_input nodes without any edges are hidden.
    Pass ``include_unconnected_pi=true`` to include them.
    """
    service = NodeService(db)
    node_type_str = node_type.value if node_type else None
    nodes = await service.get_all(
        skip=skip,
        limit=limit,
        node_type=node_type_str,
        search=search,
        include_unconnected_pi=include_unconnected_pi,
        org_ctx=org_ctx,
    )
    responses = validate_list(CorpusNodeResponse, nodes)

    # Enrich dossier nodes with beleidskompas progress
    dossier_ids = [r.id for r in responses if r.node_type == "dossier"]
    if dossier_ids:
        repo = CorpusNodeRepository(db)
        progress_map = await repo.get_beleidskompas_progress(dossier_ids)
        for r in responses:
            if r.node_type == "dossier" and r.id in progress_map:
                completed, total = progress_map[r.id]
                r.beleidskompas_progress = BeleidskompasProgress(
                    completed_steps=completed,
                    total_steps=total,
                )

    # Enrich instrument nodes with financial summary
    instrument_ids = [r.id for r in responses if r.node_type == "instrument"]
    if instrument_ids:
        opdracht_repo = OpdrachtRepository(db)
        budget_map = await opdracht_repo.get_budget_summaries(
            instrument_ids, org_ctx=org_ctx
        )
        for r in responses:
            if r.node_type == "instrument" and r.id in budget_map:
                budget, gerealiseerd = budget_map[r.id]
                r.financieel_summary = FinancieelSummary(
                    totaal_budget=budget,
                    totaal_gerealiseerd=gerealiseerd,
                )

    return responses


@router.post("", response_model=CorpusNodeResponse, status_code=status.HTTP_201_CREATED)
async def create_node(
    data: CorpusNodeCreate,
    current_user: OptionalUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("node:create")),
) -> CorpusNodeResponse:
    """Create a new corpus node. Syncs mentions and logs activity."""
    service = NodeService(db)
    node = await service.create(data)

    await sync_and_notify_mentions(
        db,
        "node",
        node.id,
        data.description,
        node.title,
        source_node_id=node.id,
    )

    await log_activity(
        db,
        current_user,
        actor_id,
        "node.created",
        node_id=node.id,
        details={"title": node.title, "node_type": node.node_type},
    )

    return CorpusNodeResponse.model_validate(node)


@router.get("/{id}", response_model=CorpusNodeWithEdges)
async def get_node(
    id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
) -> CorpusNodeWithEdges:
    """Get a single node by ID, including its incoming and outgoing edges."""
    service = NodeService(db)
    node = require_found(await service.get(id, org_ctx=org_ctx), "Node")
    edges_from = [EdgeResponse.model_validate(e) for e in node.edges_from]
    edges_to = [EdgeResponse.model_validate(e) for e in node.edges_to]
    return CorpusNodeWithEdges(
        id=node.id,
        title=node.title,
        description=node.description,
        node_type=node.node_type,
        status=node.status,
        geldig_van=node.geldig_van,
        geldig_tot=node.geldig_tot,
        created_at=node.created_at,
        updated_at=node.updated_at,
        edge_count=len(edges_from) + len(edges_to),
        edges_from=edges_from,
        edges_to=edges_to,
    )


@router.put("/{id}", response_model=CorpusNodeResponse)
async def update_node(
    id: UUID,
    data: CorpusNodeUpdate,
    current_user: OptionalUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
    _perm=Depends(require_permission("node:update")),
) -> CorpusNodeResponse:
    """Update a corpus node. Notifies stakeholders of changes."""
    await check_resource_org_scope(db, "corpus_node", id, org_ctx)
    service = NodeService(db)
    node = require_found(await service.update(id, data), "Node")

    await sync_and_notify_mentions(
        db,
        "node",
        node.id,
        data.description,
        node.title,
        source_node_id=node.id,
    )

    # Notify stakeholders of this node update (excluding the actor)
    resolved_id, resolved_naam = await resolve_actor(current_user, actor_id, db)
    if resolved_id:
        actor = await db.get(Person, resolved_id)
        if actor:
            notif_svc = NotificationService(db)
            await notif_svc.notify_node_updated(node, actor)

    await ActivityService(db).log_event(
        "node.updated",
        actor_id=resolved_id,
        actor_naam=resolved_naam,
        node_id=node.id,
        details={"title": node.title},
    )

    return CorpusNodeResponse.model_validate(node)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    id: UUID,
    current_user: OptionalUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
    _perm=Depends(require_permission("node:delete")),
) -> None:
    """Delete a corpus node. Cleans up bijlage files for bron nodes."""
    await check_resource_org_scope(db, "corpus_node", id, org_ctx)
    service = NodeService(db)
    node = await service.get(id)
    node_title = node.title if node else None
    node_type = node.node_type if node else None

    # Note the bron's stored file before deleting the node, because CASCADE
    # removes the DB row but not the file.
    bijlage_path_to_delete: str | None = None
    if node and node.node_type == "bron":
        from sqlalchemy import select

        from bouwmeester.models.bron_bijlage import BronBijlage

        result = await db.execute(select(BronBijlage).where(BronBijlage.bron_id == id))
        bijlage = result.scalar_one_or_none()
        if bijlage:
            bijlage_path_to_delete = bijlage.pad

    # Clean up resource_permission rows (no FK cascade on polymorphic)
    from sqlalchemy import delete as sa_delete

    from bouwmeester.models.resource_permission import ResourcePermission

    await db.execute(
        sa_delete(ResourcePermission).where(
            ResourcePermission.resource_type == "corpus_node",
            ResourcePermission.resource_id == id,
        )
    )

    require_deleted(await service.delete(id), "Node")

    # Delete the file after DB deletion succeeds.
    if bijlage_path_to_delete:
        from bouwmeester.core.storage import delete_blob

        await delete_blob(bijlage_path_to_delete)

    await log_activity(
        db,
        current_user,
        actor_id,
        "node.deleted",
        details={"node_id": str(id), "title": node_title, "node_type": node_type},
    )


@router.get("/{id}/neighbors", response_model=GraphNeighborsResponse)
async def get_neighbors(
    id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
) -> GraphNeighborsResponse:
    """Get direct neighbors of a node (one hop) with their connecting edges."""
    await check_resource_org_scope(db, "corpus_node", id, org_ctx)
    service = NodeService(db)
    result = await service.get_neighbors(id)
    require_found(result["node"], "Node")
    return GraphNeighborsResponse(
        node=CorpusNodeResponse.model_validate(result["node"]),
        neighbors=[
            NeighborEntry(
                node=CorpusNodeResponse.model_validate(n["node"]),
                edge=EdgeResponse.model_validate(n["edge"]),
            )
            for n in result["neighbors"]
        ],
    )


@router.get("/{id}/graph", response_model=GraphViewResponse)
async def get_graph(
    id: UUID,
    current_user: OptionalUser,
    depth: int = Query(2, ge=1, le=5),
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
) -> GraphViewResponse:
    """Get a multi-hop subgraph around a node (configurable depth 1-5)."""
    await check_resource_org_scope(db, "corpus_node", id, org_ctx)
    service = NodeService(db)
    result = await service.get_graph(id, depth=depth)
    return GraphViewResponse(
        nodes=validate_list(CorpusNodeResponse, result["nodes"]),
        edges=validate_list(EdgeResponse, result["edges"]),
    )


@router.get("/{id}/tasks", response_model=list[TaskResponse])
async def get_node_tasks(
    id: UUID,
    current_user: OptionalUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[TaskResponse]:
    """List all tasks linked to a specific node.

    Een taak die ook op een casus staat, alleen voor wie het initiatief
    van die casus ziet.
    """
    await check_resource_org_scope(db, "corpus_node", id, org_ctx)
    service = NodeService(db)
    require_found(await service.get(id), "Node")

    task_repo = TaskRepository(db)
    tasks = await task_repo.get_by_node(
        id, skip=skip, limit=limit, org_ctx=org_ctx, init_ctx=init_ctx
    )
    return validate_list(TaskResponse, tasks)


@router.get("/{id}/stakeholders", response_model=list[NodeStakeholderResponse])
async def get_node_stakeholders(
    id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
) -> list[NodeStakeholderResponse]:
    """List stakeholders (eigenaar/betrokken/adviseur) of a node."""
    await check_resource_org_scope(db, "corpus_node", id, org_ctx)
    service = NodeService(db)
    require_found(await service.get(id), "Node")

    repo = ResourcePermissionRepository(db)
    perms = await repo.list_for_resource("corpus_node", id)
    return [
        NodeStakeholderResponse(id=rp.id, person=rp.person, rol=rp.rol) for rp in perms
    ]


@router.post(
    "/{id}/stakeholders",
    response_model=NodeStakeholderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_node_stakeholder(
    id: UUID,
    data: NodeStakeholderCreate,
    current_user: OptionalUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> NodeStakeholderResponse:
    """Add a person as stakeholder on a node with a role."""
    service = NodeService(db)
    node = require_found(await service.get(id), "Node")
    require_found(await db.get(Person, data.person_id), "Person")
    await require_can_grant_resource_role(
        db,
        perm_ctx,
        resource_type="corpus_node",
        resource_id=id,
        rol=data.rol,
        target_person_id=data.person_id,
    )

    repo = ResourcePermissionRepository(db)
    rp = await repo.create_permission(data.person_id, "corpus_node", id, data.rol)

    resolved_id, resolved_naam = await resolve_actor(current_user, actor_id, db)

    notif_svc = NotificationService(db)
    await notif_svc.notify_stakeholder_added(
        node,
        data.person_id,
        data.rol,
        actor_id=resolved_id,
    )

    person = await db.get(Person, data.person_id)
    await ActivityService(db).log_event(
        "stakeholder.added",
        actor_id=resolved_id,
        actor_naam=resolved_naam,
        node_id=id,
        details={
            "person_id": str(data.person_id),
            "person_naam": person.naam if person else None,
            "rol": data.rol,
        },
    )

    await db.commit()

    return NodeStakeholderResponse(id=rp.id, person=rp.person, rol=rp.rol)


@router.put(
    "/{id}/stakeholders/{stakeholder_id}",
    response_model=NodeStakeholderResponse,
)
async def update_node_stakeholder(
    id: UUID,
    stakeholder_id: UUID,
    data: NodeStakeholderUpdate,
    current_user: OptionalUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> NodeStakeholderResponse:
    """Update a stakeholder's role on a node."""
    repo = ResourcePermissionRepository(db)
    rp = require_found(
        await repo.get_with_person(stakeholder_id),
        "Stakeholder",
    )

    if rp.resource_type != "corpus_node" or rp.resource_id != id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stakeholder not found",
        )
    await require_can_change_resource_role(db, perm_ctx, rp, new_rol=data.rol)

    old_rol = rp.rol
    rp.rol = data.rol
    await db.flush()
    await db.refresh(rp)

    if old_rol != data.rol:
        service = NodeService(db)
        node = await service.get(id)
        if node:
            notif_svc = NotificationService(db)
            await notif_svc.notify_stakeholder_role_changed(
                node, rp.person_id, old_rol, data.rol
            )

    person = await db.get(Person, rp.person_id)
    await log_activity(
        db,
        current_user,
        actor_id,
        "stakeholder.updated",
        node_id=id,
        details={
            "person_id": str(rp.person_id),
            "person_naam": person.naam if person else None,
            "old_rol": old_rol,
            "new_rol": data.rol,
        },
    )

    await db.commit()

    return NodeStakeholderResponse(id=rp.id, person=rp.person, rol=rp.rol)


@router.delete(
    "/{id}/stakeholders/{stakeholder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_node_stakeholder(
    id: UUID,
    stakeholder_id: UUID,
    current_user: OptionalUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> None:
    """Remove a stakeholder from a node."""
    repo = ResourcePermissionRepository(db)
    rp = require_found(
        await repo.get_with_person(stakeholder_id),
        "Stakeholder",
    )

    if rp.resource_type != "corpus_node" or rp.resource_id != id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stakeholder not found",
        )
    await require_can_change_resource_role(db, perm_ctx, rp, new_rol=None)

    rp_person_id = str(rp.person_id)
    rp_rol = rp.rol
    person = await db.get(Person, rp.person_id)
    rp_person_naam = person.naam if person else None
    await repo.delete(stakeholder_id)

    await log_activity(
        db,
        current_user,
        actor_id,
        "stakeholder.removed",
        node_id=id,
        details={
            "person_id": rp_person_id,
            "person_naam": rp_person_naam,
            "rol": rp_rol,
        },
    )

    await db.commit()


@router.get("/{id}/tags", response_model=list[NodeTagResponse])
async def get_node_tags(
    id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
) -> list[NodeTagResponse]:
    """List all tags applied to a node."""
    from bouwmeester.repositories.tag import TagRepository

    await check_resource_org_scope(db, "corpus_node", id, org_ctx)
    service = NodeService(db)
    require_found(await service.get(id), "Node")

    tag_repo = TagRepository(db)
    node_tags = await tag_repo.get_by_node(id)
    return [NodeTagResponse.model_validate(nt) for nt in node_tags]


@router.post(
    "/{id}/tags",
    response_model=NodeTagResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_tag_to_node(
    id: UUID,
    data: NodeTagCreate,
    current_user: OptionalUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
    _perm=Depends(require_permission("tag:create")),
) -> NodeTagResponse:
    """Add a tag to a node.

    Creates the tag if tag_name is given and it doesn't exist.
    """
    from bouwmeester.repositories.tag import TagRepository

    await check_resource_org_scope(db, "corpus_node", id, org_ctx)
    service = NodeService(db)
    require_found(await service.get(id), "Node")

    tag_repo = TagRepository(db)

    # If tag_name is given, find or create tag
    if data.tag_name and not data.tag_id:
        existing = await tag_repo.get_by_name(data.tag_name)
        if existing:
            tag_id = existing.id
        else:
            new_tag = await tag_repo.create(TagCreate(name=data.tag_name))
            tag_id = new_tag.id
    elif data.tag_id:
        tag_id = data.tag_id
    else:
        raise HTTPException(status_code=400, detail="Provide tag_id or tag_name")

    node_tag = await tag_repo.add_tag_to_node(id, tag_id)
    tag = await tag_repo.get_by_id(tag_id)

    await log_activity(
        db,
        current_user,
        actor_id,
        "node_tag.added",
        node_id=id,
        details={"tag_id": str(tag_id), "tag_name": tag.name if tag else None},
    )

    return NodeTagResponse.model_validate(node_tag)


@router.delete("/{id}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_tag_from_node(
    id: UUID,
    tag_id: UUID,
    current_user: OptionalUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
    _perm=Depends(require_permission("tag:delete")),
) -> None:
    """Remove a tag from a node."""
    from bouwmeester.repositories.tag import TagRepository

    await check_resource_org_scope(db, "corpus_node", id, org_ctx)

    tag_repo = TagRepository(db)
    tag = await tag_repo.get_by_id(tag_id)
    tag_name = tag.name if tag else None
    require_deleted(await tag_repo.remove_tag_from_node(id, tag_id), "Tag link")

    await log_activity(
        db,
        current_user,
        actor_id,
        "node_tag.removed",
        node_id=id,
        details={"tag_id": str(tag_id), "tag_name": tag_name},
    )


@router.get("/{id}/history/titles", response_model=list[NodeTitleRecord])
async def get_node_title_history(
    id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
) -> list[NodeTitleRecord]:
    """Get temporal history of title changes for a node."""
    await check_resource_org_scope(db, "corpus_node", id, org_ctx)
    service = NodeService(db)
    require_found(await service.get(id), "Node")
    records = await service.get_title_history(id)
    return [NodeTitleRecord.model_validate(r) for r in records]


@router.get("/{id}/history/statuses", response_model=list[NodeStatusRecord])
async def get_node_status_history(
    id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
) -> list[NodeStatusRecord]:
    """Get temporal history of status changes for a node."""
    await check_resource_org_scope(db, "corpus_node", id, org_ctx)
    service = NodeService(db)
    require_found(await service.get(id), "Node")
    records = await service.get_status_history(id)
    return [NodeStatusRecord.model_validate(r) for r in records]


@router.get("/{id}/bron-detail", response_model=BronResponse | None)
async def get_node_bron_detail(
    id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
) -> BronResponse | None:
    """Get bron-specific detail fields for a bron node."""
    from sqlalchemy import select

    from bouwmeester.models.bron import Bron

    await check_resource_org_scope(db, "corpus_node", id, org_ctx)
    stmt = select(Bron).where(Bron.id == id)
    result = await db.execute(stmt)
    bron = result.scalar_one_or_none()
    if bron is None:
        return None
    return BronResponse.model_validate(bron)


@router.put("/{id}/bron-detail", response_model=BronResponse)
async def update_node_bron_detail(
    id: UUID,
    data: BronUpdate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
    _perm=Depends(require_permission("node:update")),
) -> BronResponse:
    """Update bron-specific detail fields for a bron node."""
    from sqlalchemy import select

    from bouwmeester.models.bron import Bron

    await check_resource_org_scope(db, "corpus_node", id, org_ctx)

    stmt = select(Bron).where(Bron.id == id)
    result = await db.execute(stmt)
    bron = result.scalar_one_or_none()
    if bron is None:
        raise HTTPException(status_code=404, detail="Bron detail not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(bron, field, value)

    await db.flush()

    return BronResponse.model_validate(bron)


@router.get("/{id}/financieel", response_model=FinancieelOverzicht)
async def get_node_financieel(
    id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("opdracht:read")),
    org_ctx: OrgContext = Depends(get_org_context),
) -> FinancieelOverzicht:
    """Get financial overview for a node (aggregated from opdrachten)."""
    await check_resource_org_scope(db, "corpus_node", id, org_ctx)
    service = NodeService(db)
    require_found(await service.get(id), "Node")
    fin_service = FinancieelService(db)
    return await fin_service.get_financieel_overzicht(id, org_ctx=org_ctx)


@router.get("/{id}/opdrachten", response_model=list[OpdrachtResponse])
async def get_node_opdrachten(
    id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("opdracht:read")),
    org_ctx: OrgContext = Depends(get_org_context),
) -> list[OpdrachtResponse]:
    """Get opdrachten linked to a node (via instrument_id or OpdrachtNode)."""
    await check_resource_org_scope(db, "corpus_node", id, org_ctx)
    service = NodeService(db)
    require_found(await service.get(id), "Node")
    repo = OpdrachtRepository(db)
    opdrachten = await repo.get_by_node(id, org_ctx=org_ctx)
    return validate_list(OpdrachtResponse, opdrachten)


@router.get("/{id}/parlementair-item")
async def get_node_parlementair_item(
    id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    org_ctx: OrgContext = Depends(get_org_context),
) -> dict | None:
    """Get linked parliamentary item data for a politieke_input node.

    Returns null if none.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from bouwmeester.models.parlementair_item import ParlementairItem

    await check_resource_org_scope(db, "corpus_node", id, org_ctx)
    stmt = (
        select(ParlementairItem)
        .where(ParlementairItem.corpus_node_id == id)
        .options(selectinload(ParlementairItem.suggested_edges))
    )
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if item is None:
        return None
    return {
        "type": item.type,
        "indieners": item.indieners or [],
        "document_url": item.document_url,
        "zaak_nummer": item.zaak_nummer,
        "bron": item.bron,
        "datum": str(item.datum) if item.datum else None,
        "deadline": str(item.deadline) if item.deadline else None,
        "ministerie": item.ministerie,
    }
