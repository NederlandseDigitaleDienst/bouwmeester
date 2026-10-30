"""API routes voor casussoorten.

Soorten horen bij een initiatief en hangen als tags aan casussen. Toegang:
- lijst: wie het initiatief ziet; daarbuiten 404, het bestaan lekt niet;
- beheren (aanmaken, wijzigen, verwijderen, volgorde): alleen de eigenaar,
  net als de andere instellingen;
- soorten van een casus zetten: wie de casus ziet, net als de casus
  bewerken. Alleen soorten van het eigen initiatief, anders 400.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.api.deps import require_found
from bouwmeester.api.routes.initiatief import _require_access
from bouwmeester.core.auth import OptionalUser
from bouwmeester.core.database import get_db
from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    get_initiatief_context,
    require_initiatief_visible,
)
from bouwmeester.core.permissions import PermissionContext, get_permission_context
from bouwmeester.models.casus import Casus
from bouwmeester.repositories.casus_soort import CasusSoortRepository
from bouwmeester.repositories.initiatief import InitiatiefRepository
from bouwmeester.schema.casus_soort import (
    CasusSoortCreate,
    CasusSoortenZetten,
    CasusSoortReorder,
    CasusSoortResponse,
    CasusSoortSummary,
    CasusSoortUpdate,
)
from bouwmeester.services.activity_service import log_activity

router = APIRouter(tags=["casussoorten"])

NIET_GEVONDEN = "Initiatief niet gevonden"
BESTAAT_AL = "Deze soort bestaat al"


async def _zichtbaar_initiatief(
    db: AsyncSession, initiatief_id: UUID, init_ctx: InitiatiefContext
) -> InitiatiefRepository:
    repo = InitiatiefRepository(db)
    if await repo.get_by_id(initiatief_id) is None:
        raise HTTPException(status_code=404, detail=NIET_GEVONDEN)
    require_initiatief_visible(initiatief_id, init_ctx, detail=NIET_GEVONDEN)
    return repo


async def _eigenaar(
    db: AsyncSession,
    initiatief_id: UUID,
    init_ctx: InitiatiefContext,
    current_user,
    perm_ctx: PermissionContext,
) -> None:
    """Eerst zichtbaar (anders 404), dan eigenaar (anders 403)."""
    repo = await _zichtbaar_initiatief(db, initiatief_id, init_ctx)
    await _require_access(repo, initiatief_id, current_user, perm_ctx, "eigenaar")


def _response(soort, counts: dict[UUID, int]) -> CasusSoortResponse:
    resp = CasusSoortResponse.model_validate(soort)
    resp.casus_count = counts.get(soort.id, 0)
    return resp


@router.get(
    "/initiatieven/{initiatief_id}/casussoorten",
    response_model=list[CasusSoortResponse],
)
async def list_casussoorten(
    initiatief_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[CasusSoortResponse]:
    await _zichtbaar_initiatief(db, initiatief_id, init_ctx)
    repo = CasusSoortRepository(db)
    counts = await repo.casus_counts(initiatief_id)
    return [_response(s, counts) for s in await repo.list_for_initiatief(initiatief_id)]


@router.post(
    "/initiatieven/{initiatief_id}/casussoorten",
    response_model=CasusSoortResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_casussoort(
    initiatief_id: UUID,
    data: CasusSoortCreate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> CasusSoortResponse:
    await _eigenaar(db, initiatief_id, init_ctx, current_user, perm_ctx)
    repo = CasusSoortRepository(db)
    if await repo.naam_bestaat(initiatief_id, data.naam):
        raise HTTPException(status_code=409, detail=BESTAAT_AL)
    # Twee gelijke verzoeken tegelijk komen allebei langs de controle; de
    # database vangt de tweede, en dat is ook een 409, geen 500.
    try:
        async with db.begin_nested():
            soort = await repo.create(initiatief_id, data)
    except IntegrityError:
        raise HTTPException(status_code=409, detail=BESTAAT_AL)
    await log_activity(
        db,
        current_user,
        None,
        "casussoort.created",
        details={"initiatief_id": str(initiatief_id), "naam": soort.naam},
    )
    return _response(soort, {})


@router.post(
    "/initiatieven/{initiatief_id}/casussoorten/reorder",
    response_model=list[CasusSoortResponse],
)
async def reorder_casussoorten(
    initiatief_id: UUID,
    data: CasusSoortReorder,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> list[CasusSoortResponse]:
    await _eigenaar(db, initiatief_id, init_ctx, current_user, perm_ctx)
    repo = CasusSoortRepository(db)
    try:
        soorten = await repo.reorder(initiatief_id, data.soort_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    counts = await repo.casus_counts(initiatief_id)
    return [_response(s, counts) for s in soorten]


@router.put(
    "/initiatieven/{initiatief_id}/casussoorten/{soort_id}",
    response_model=CasusSoortResponse,
)
async def update_casussoort(
    initiatief_id: UUID,
    soort_id: UUID,
    data: CasusSoortUpdate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> CasusSoortResponse:
    await _eigenaar(db, initiatief_id, init_ctx, current_user, perm_ctx)
    repo = CasusSoortRepository(db)
    soort = require_found(
        await repo.get_in_initiatief(initiatief_id, soort_id), "Casussoort"
    )
    if data.naam and await repo.naam_bestaat(
        initiatief_id, data.naam, behalve=soort.id
    ):
        raise HTTPException(status_code=409, detail=BESTAAT_AL)
    oude_naam = soort.naam
    try:
        async with db.begin_nested():
            soort = await repo.update(soort, data)
    except IntegrityError:
        raise HTTPException(status_code=409, detail=BESTAAT_AL)
    await log_activity(
        db,
        current_user,
        None,
        "casussoort.updated",
        details={
            "initiatief_id": str(initiatief_id),
            "naam": soort.naam,
            **({"oude_naam": oude_naam} if oude_naam != soort.naam else {}),
        },
    )
    return _response(soort, await repo.casus_counts(initiatief_id))


@router.delete(
    "/initiatieven/{initiatief_id}/casussoorten/{soort_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_casussoort(
    initiatief_id: UUID,
    soort_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> None:
    """Verwijder een soort; hij verdwijnt ook van alle casussen."""
    await _eigenaar(db, initiatief_id, init_ctx, current_user, perm_ctx)
    repo = CasusSoortRepository(db)
    soort = require_found(
        await repo.get_in_initiatief(initiatief_id, soort_id), "Casussoort"
    )
    naam = soort.naam
    await repo.delete(soort)
    await log_activity(
        db,
        current_user,
        None,
        "casussoort.deleted",
        details={"initiatief_id": str(initiatief_id), "naam": naam},
    )


@router.put(
    "/casussen/{casus_id}/soorten",
    response_model=list[CasusSoortSummary],
)
async def zet_casussoorten(
    casus_id: UUID,
    data: CasusSoortenZetten,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[CasusSoortSummary]:
    """Vervang de soorten van een casus. Alleen soorten van zijn initiatief."""
    casus = await db.get(Casus, casus_id)
    if casus is None:
        raise HTTPException(status_code=404, detail="Casus niet gevonden")
    require_initiatief_visible(
        casus.initiatief_id, init_ctx, detail="Casus niet gevonden"
    )
    repo = CasusSoortRepository(db)
    toegestaan = (
        {s.id for s in await repo.list_for_initiatief(casus.initiatief_id)}
        if casus.initiatief_id
        else set()
    )
    vreemd = [sid for sid in data.soort_ids if sid not in toegestaan]
    if vreemd:
        raise HTTPException(
            status_code=400,
            detail="Een of meer soorten horen niet bij het initiatief van deze casus",
        )
    await repo.zet_voor_casus(casus_id, data.soort_ids)
    soorten = await repo.voor_casus(casus_id)
    await log_activity(
        db,
        current_user,
        None,
        "casus.soorten_gezet",
        details={
            "casus_id": str(casus_id),
            "title": casus.title,
            "soorten": [s.naam for s in soorten],
        },
    )
    return [CasusSoortSummary.model_validate(s) for s in soorten]
