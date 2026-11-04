"""Unified resource permission management routes.

Provides generic CRUD for the resource_permission table, used
by frontend components that manage stakeholders, members, and
contacts across all resource types.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
    check_resource_permission,
    get_permission_context,
    require_permission,
)
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.repositories.resource_permission import (
    ResourcePermissionRepository,
)
from bouwmeester.schema.resource_permission import (
    PersonResourcePermissionResponse,
    ResourcePermissionCreate,
    ResourcePermissionResponse,
    ResourcePermissionUpdate,
)
from bouwmeester.services.activity_service import log_activity
from bouwmeester.services.casus_team_service import (
    casusrollen_bijwerken,
    rangen_voor_rij,
)

router = APIRouter(
    prefix="/resource-permissions",
    tags=["resource-permissions"],
)

VALID_RESOURCE_TYPES = {
    "corpus_node",
    "initiatief",
    "lead",
    "opdracht",
}


def _validate_resource_type(resource_type: str) -> None:
    if resource_type not in VALID_RESOURCE_TYPES:
        raise HTTPException(
            400,
            f"Invalid resource_type: {resource_type}",
        )


async def _require_can_list_grants(
    perm: PermissionContext,
    db: AsyncSession,
    resource_type: str,
    resource_id: UUID,
    org_ctx: OrgContext,
) -> None:
    """Read gate for listing who holds which rol on a resource.

    An eigenaar of the resource, or someone with ``resource_permission:manage``
    who can see the resource.  Changing grants is decided in
    ``core.authority``.
    """
    if perm.is_super_admin:
        return
    has_resource = perm.person_id is not None and await check_resource_permission(
        db, perm.person_id, resource_type, resource_id, "resource_permission:manage"
    )
    if not has_resource and not perm.has_permission("resource_permission:manage"):
        raise HTTPException(403, "Onvoldoende rechten")
    await check_resource_org_scope(db, resource_type, resource_id, org_ctx)


def _to_response(rp: ResourcePermission) -> ResourcePermissionResponse:
    return ResourcePermissionResponse(
        id=rp.id,
        person_id=rp.person_id,
        person=rp.person,
        resource_type=rp.resource_type,
        resource_id=rp.resource_id,
        rol=rp.rol,
        created_at=rp.created_at,
    )


async def _resolve_resource_names(
    db: AsyncSession,
    permissions: list[ResourcePermission],
) -> dict[UUID, str]:
    """Batch-resolve display names for polymorphic resource_ids."""
    from bouwmeester.models.casus import Casus
    from bouwmeester.models.corpus_node import CorpusNode
    from bouwmeester.models.initiatief import Initiatief
    from bouwmeester.models.lead import Lead
    from bouwmeester.models.opdracht import Opdracht

    table_map: dict[str, tuple] = {
        "casus": (Casus, Casus.title),
        "corpus_node": (CorpusNode, CorpusNode.title),
        "initiatief": (Initiatief, Initiatief.naam),
        "lead": (Lead, Lead.title),
        "opdracht": (Opdracht, Opdracht.titel),
    }

    ids_by_type: dict[str, set[UUID]] = {}
    for rp in permissions:
        ids_by_type.setdefault(rp.resource_type, set()).add(rp.resource_id)

    names: dict[UUID, str] = {}
    for rtype, ids in ids_by_type.items():
        if rtype not in table_map:
            continue
        model, name_col = table_map[rtype]
        stmt = select(model.id, name_col).where(model.id.in_(ids))
        result = await db.execute(stmt)
        for rid, rname in result.all():
            names[rid] = rname or str(rid)

    return names


async def _zonder_onzichtbare_casussen(
    db: AsyncSession,
    permissions: list[ResourcePermission],
    init_ctx: InitiatiefContext,
) -> list[ResourcePermission]:
    """Laat casusrijen weg waarvan de kijker het initiatief niet ziet."""
    from bouwmeester.models.casus import Casus

    casus_ids = {rp.resource_id for rp in permissions if rp.resource_type == "casus"}
    if not casus_ids:
        return permissions
    stmt = select(Casus.id, Casus.initiatief_id).where(Casus.id.in_(casus_ids))
    initiatief_van = dict((await db.execute(stmt)).all())

    def zichtbaar(rp: ResourcePermission) -> bool:
        if rp.resource_type != "casus":
            return True
        if init_ctx.is_admin:
            return True
        initiatief_id = initiatief_van.get(rp.resource_id)
        return (
            init_ctx.is_authenticated
            and initiatief_id is not None
            and initiatief_id in init_ctx.visible_initiatief_ids
        )

    return [rp for rp in permissions if zichtbaar(rp)]


@router.get(
    "/by-person/{person_id}",
    response_model=list[PersonResourcePermissionResponse],
)
async def list_person_resource_permissions(
    person_id: UUID,
    _perm=Depends(require_permission("people:read")),
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
):
    """List all resource permissions for a person, with resolved names.

    Casusrollen (trekker, teamlid) alleen voor wie het initiatief van die
    casus ziet: een casus is buiten zijn initiatief onvindbaar, en dat
    geldt ook voor wie eraan werkt.
    """
    repo = ResourcePermissionRepository(db)
    perms = await repo.list_for_person(person_id)
    perms = await _zonder_onzichtbare_casussen(db, perms, init_ctx)
    names = await _resolve_resource_names(db, perms)
    return [
        PersonResourcePermissionResponse(
            id=rp.id,
            person_id=rp.person_id,
            person=rp.person,
            resource_type=rp.resource_type,
            resource_id=rp.resource_id,
            rol=rp.rol,
            created_at=rp.created_at,
            resource_name=names.get(rp.resource_id, str(rp.resource_id)),
        )
        for rp in perms
    ]


@router.get(
    "/{resource_type}/{resource_id}",
    response_model=list[ResourcePermissionResponse],
)
async def list_resource_permissions(
    resource_type: str,
    resource_id: UUID,
    perm: PermissionContext = Depends(get_permission_context),
    org_ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """List people and roles on a resource."""
    _validate_resource_type(resource_type)
    if not perm.is_authenticated:
        raise HTTPException(401, "Niet ingelogd")
    await _require_can_list_grants(perm, db, resource_type, resource_id, org_ctx)

    repo = ResourcePermissionRepository(db)
    perms = await repo.list_for_resource(resource_type, resource_id)
    return [_to_response(rp) for rp in perms]


@router.post(
    "/{resource_type}/{resource_id}",
    response_model=ResourcePermissionResponse,
)
async def add_resource_permission(
    resource_type: str,
    resource_id: UUID,
    data: ResourcePermissionCreate,
    perm: PermissionContext = Depends(get_permission_context),
    db: AsyncSession = Depends(get_db),
):
    """Add a person to a resource with a role."""
    _validate_resource_type(resource_type)
    if not perm.is_authenticated:
        raise HTTPException(401, "Niet ingelogd")
    await require_can_grant_resource_role(
        db,
        perm,
        resource_type=resource_type,
        resource_id=resource_id,
        rol=data.rol,
        target_person_id=data.person_id,
    )

    repo = ResourcePermissionRepository(db)
    try:
        rp = await repo.create_permission(
            person_id=data.person_id,
            resource_type=resource_type,
            resource_id=resource_id,
            rol=data.rol,
        )
    except IntegrityError:
        raise HTTPException(
            409,
            "Deze toekenning bestaat al",
        )

    await log_activity(
        db,
        None,
        perm.person_id,
        "resource_permission.added",
        details={
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "person_id": str(data.person_id),
            "rol": data.rol,
        },
    )

    return _to_response(rp)


@router.put(
    "/{rp_id}",
    response_model=ResourcePermissionResponse,
)
async def update_resource_permission(
    rp_id: UUID,
    data: ResourcePermissionUpdate,
    perm: PermissionContext = Depends(get_permission_context),
    db: AsyncSession = Depends(get_db),
):
    """Change a resource permission's role."""
    if not perm.is_authenticated:
        raise HTTPException(401, "Niet ingelogd")

    repo = ResourcePermissionRepository(db)
    rp = await repo.get_with_person(rp_id)
    if rp is None:
        raise HTTPException(404, "Toekenning niet gevonden")
    await require_can_change_resource_role(db, perm, rp, new_rol=data.rol)

    # Een initiatiefrij: de casusrollen volgen de rol, net als in de
    # initiatiefroutes (services.casus_team_service).
    voor = await rangen_voor_rij(db, rp) if rp.resource_type == "initiatief" else None
    rp.rol = data.rol
    await db.flush()
    if voor is not None:
        await casusrollen_bijwerken(db, rp.resource_id, voor, actor_id=perm.person_id)
    await db.refresh(rp)
    return _to_response(rp)


@router.delete("/{rp_id}")
async def delete_resource_permission(
    rp_id: UUID,
    perm: PermissionContext = Depends(get_permission_context),
    db: AsyncSession = Depends(get_db),
):
    """Remove a resource permission."""
    if not perm.is_authenticated:
        raise HTTPException(401, "Niet ingelogd")

    repo = ResourcePermissionRepository(db)
    rp = await repo.get_with_person(rp_id)
    if rp is None:
        raise HTTPException(404, "Toekenning niet gevonden")
    await require_can_change_resource_role(db, perm, rp, new_rol=None)

    await log_activity(
        db,
        None,
        perm.person_id,
        "resource_permission.removed",
        details={
            "resource_type": rp.resource_type,
            "resource_id": str(rp.resource_id),
            "person_id": str(rp.person_id) if rp.person_id else None,
            "eenheid_id": (
                str(rp.organisatie_eenheid_id) if rp.organisatie_eenheid_id else None
            ),
            "rol": rp.rol,
        },
    )

    initiatief_id, voor = rp.resource_id, None
    if rp.resource_type == "initiatief":
        voor = await rangen_voor_rij(db, rp)
    await repo.delete(rp_id)
    if voor is not None:
        await casusrollen_bijwerken(db, initiatief_id, voor, actor_id=perm.person_id)
    return {"ok": True}
