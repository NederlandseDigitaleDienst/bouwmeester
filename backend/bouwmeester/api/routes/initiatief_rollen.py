"""API routes voor rollen in een initiatief en het werk per persoon.

Toegang:
- lezen (ook de cirkel en de export): wie het initiatief ziet; daarbuiten
  404, het bestaan lekt niet;
- beheren (rollen, status, toewijzen, interesse, raakvlakken, cirkel, focus,
  import): bijdrager of eigenaar;
- vervuller, wie interesse heeft en wie een focus krijgt, moeten het
  initiatief kunnen zien (anders 400);
- rollen alleen als ze aan staan voor het initiatief (anders 404).

Het werk per persoon (rollen, leads, casussen, issues, open taken) toont
alleen wat bij dit initiatief hoort, en alleen aan wie het initiatief ziet:
dezelfde regel als voor casuswerk (tests/test_casus_toegang.py).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.api.deps import require_found
from bouwmeester.api.routes.initiatief import _require_access
from bouwmeester.core.auth import OptionalUser
from bouwmeester.core.database import get_db
from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    get_initiatief_context,
    require_initiatief_member,
    require_initiatief_visible,
)
from bouwmeester.core.org_context import OrgContext, get_org_context
from bouwmeester.core.permissions import PermissionContext, get_permission_context
from bouwmeester.core.query_utils import find_person_by_email
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.initiatief_rol import InitiatiefRol
from bouwmeester.models.person import Person
from bouwmeester.models.person_email import PersonEmail
from bouwmeester.repositories.initiatief import InitiatiefRepository
from bouwmeester.repositories.initiatief_rol import InitiatiefRolRepository
from bouwmeester.schema.initiatief_rol import (
    CirkelResponse,
    CirkelUpdate,
    ExportCirkel,
    ExportRaakvlak,
    ExportRol,
    FocusZetten,
    ImportResultaat,
    InteresseResponse,
    InteresseZetten,
    PersoonKort,
    PersoonWerkResponse,
    RaakvlakCreate,
    RaakvlakResponse,
    RaakvlakUpdate,
    RolCreate,
    RolKort,
    RollenExport,
    RolResponse,
    RolUpdate,
)
from bouwmeester.services.activity_service import log_activity

router = APIRouter(tags=["initiatief-rollen"])

NIET_GEVONDEN = "Initiatief niet gevonden"
NIET_AAN = "Rollen staan niet aan voor dit initiatief"
BESTAAT_AL = "Deze rol bestaat al"


# ---------------------------------------------------------------------------
# Toegang en antwoorden
# ---------------------------------------------------------------------------


async def _zichtbaar(
    db: AsyncSession, initiatief_id: UUID, init_ctx: InitiatiefContext
) -> Initiatief:
    initiatief = await db.get(Initiatief, initiatief_id)
    if initiatief is None:
        raise HTTPException(status_code=404, detail=NIET_GEVONDEN)
    require_initiatief_visible(initiatief_id, init_ctx, detail=NIET_GEVONDEN)
    return initiatief


async def _rollen_zichtbaar(
    db: AsyncSession, initiatief_id: UUID, init_ctx: InitiatiefContext
) -> Initiatief:
    initiatief = await _zichtbaar(db, initiatief_id, init_ctx)
    if not initiatief.rollen_enabled:
        raise HTTPException(status_code=404, detail=NIET_AAN)
    return initiatief


async def _bijdrager(
    db: AsyncSession,
    initiatief_id: UUID,
    init_ctx: InitiatiefContext,
    current_user,
    perm_ctx: PermissionContext,
    *,
    rollen: bool = True,
) -> Initiatief:
    """Eerst zichtbaar (en aan), anders 404; dan bijdrager, anders 403."""
    initiatief = (
        await _rollen_zichtbaar(db, initiatief_id, init_ctx)
        if rollen
        else await _zichtbaar(db, initiatief_id, init_ctx)
    )
    await _require_access(
        InitiatiefRepository(db), initiatief_id, current_user, perm_ctx, "contributor"
    )
    return initiatief


class _Context:
    """Wat elk rolantwoord nodig heeft, één keer opgehaald per verzoek."""

    def __init__(self, leden, raakvlakken, namen):
        self.leden: set[UUID] = leden
        self.raakvlakken = raakvlakken
        self.namen: dict[UUID, str] = namen


async def _context(db: AsyncSession, initiatief_id: UUID) -> _Context:
    personen = await InitiatiefRepository(db).list_persons_with_access(initiatief_id)
    repo = InitiatiefRolRepository(db)
    rollen = await repo.list_for_initiatief(initiatief_id)
    return _Context(
        {p.id for p in personen},
        await repo.raakvlakken_per_rol(initiatief_id),
        {r.id: r.naam for r in rollen},
    )


def _cirkel_response(cirkel, initiatief: Initiatief) -> CirkelResponse:
    resp = CirkelResponse.model_validate(cirkel)
    # De ankercirkel heet zoals het initiatief, ook na hernoemen.
    if cirkel.parent_id is None:
        resp.naam = initiatief.naam
    return resp


def _response(rol: InitiatiefRol, ctx: _Context) -> RolResponse:
    huidig = [
        i for i in rol.interesse if i.ronde == rol.ronde and rol.status != "belegd"
    ]
    eerder = [i for i in rol.interesse if i not in huidig]
    return RolResponse(
        id=rol.id,
        initiatief_id=rol.initiatief_id,
        cirkel_id=rol.cirkel_id,
        naam=rol.naam,
        status=rol.status,
        doel=rol.doel,
        aanspreekbaar_op=rol.aanspreekbaar_op or [],
        domein=rol.domein or [],
        toelichting=rol.toelichting,
        feedback=rol.feedback,
        vervuller=PersoonKort.model_validate(rol.vervuller) if rol.vervuller else None,
        vervuller_is_lid=rol.vervuller_id is None or rol.vervuller_id in ctx.leden,
        ronde=rol.ronde,
        interesse=[InteresseResponse.model_validate(i) for i in huidig],
        eerdere_interesse=[InteresseResponse.model_validate(i) for i in eerder],
        raakvlakken=[
            RaakvlakResponse(
                id=rv.id,
                rol=RolKort(id=ander, naam=ctx.namen.get(ander, "")),
                omschrijving=rv.omschrijving,
            )
            for rv, ander in ctx.raakvlakken.get(rol.id, [])
        ],
        sort_order=rol.sort_order,
        created_at=rol.created_at,
        updated_at=rol.updated_at,
    )


async def _antwoord(db: AsyncSession, rol: InitiatiefRol) -> RolResponse:
    return _response(rol, await _context(db, rol.initiatief_id))


async def _rol_of_404(
    repo: InitiatiefRolRepository, initiatief_id: UUID, rol_id: UUID
) -> InitiatiefRol:
    return require_found(await repo.get_in_initiatief(initiatief_id, rol_id), "Rol")


# ---------------------------------------------------------------------------
# Cirkel
# ---------------------------------------------------------------------------


@router.get("/initiatieven/{initiatief_id}/cirkel", response_model=CirkelResponse)
async def get_cirkel(
    initiatief_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> CirkelResponse:
    initiatief = await _rollen_zichtbaar(db, initiatief_id, init_ctx)
    cirkel = await InitiatiefRolRepository(db).ankercirkel(initiatief)
    return _cirkel_response(cirkel, initiatief)


@router.put("/initiatieven/{initiatief_id}/cirkel", response_model=CirkelResponse)
async def update_cirkel(
    initiatief_id: UUID,
    data: CirkelUpdate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> CirkelResponse:
    initiatief = await _bijdrager(db, initiatief_id, init_ctx, current_user, perm_ctx)
    repo = InitiatiefRolRepository(db)
    cirkel = await repo.zet_cirkel(
        await repo.ankercirkel(initiatief), data.model_dump(exclude_unset=True)
    )
    await log_activity(
        db,
        current_user,
        None,
        "initiatief_cirkel.updated",
        details={"initiatief_id": str(initiatief_id)},
    )
    return _cirkel_response(cirkel, initiatief)


# ---------------------------------------------------------------------------
# Rollen
# ---------------------------------------------------------------------------


@router.get("/initiatieven/{initiatief_id}/rollen", response_model=list[RolResponse])
async def list_rollen(
    initiatief_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[RolResponse]:
    await _rollen_zichtbaar(db, initiatief_id, init_ctx)
    ctx = await _context(db, initiatief_id)
    rollen = await InitiatiefRolRepository(db).list_for_initiatief(initiatief_id)
    return [_response(r, ctx) for r in rollen]


@router.post(
    "/initiatieven/{initiatief_id}/rollen",
    response_model=RolResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_rol(
    initiatief_id: UUID,
    data: RolCreate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> RolResponse:
    initiatief = await _bijdrager(db, initiatief_id, init_ctx, current_user, perm_ctx)
    if data.vervuller_id is not None:
        await require_initiatief_member(db, initiatief_id, data.vervuller_id)
        rol_status = "belegd"
    elif data.status == "belegd":
        raise HTTPException(
            status_code=400, detail="Een belegde rol heeft een vervuller"
        )
    else:
        rol_status = data.status or "concept"
    repo = InitiatiefRolRepository(db)
    if await repo.naam_bestaat(initiatief_id, data.naam):
        raise HTTPException(status_code=409, detail=BESTAAT_AL)
    try:
        async with db.begin_nested():
            rol = await repo.create(
                initiatief,
                data.model_dump(),
                status=rol_status,
                vervuller_id=data.vervuller_id,
            )
    except IntegrityError:
        raise HTTPException(status_code=409, detail=BESTAAT_AL)
    await log_activity(
        db,
        current_user,
        None,
        "initiatief_rol.created",
        details={"initiatief_id": str(initiatief_id), "naam": rol.naam},
    )
    return await _antwoord(db, rol)


@router.put("/initiatieven/{initiatief_id}/rollen/{rol_id}", response_model=RolResponse)
async def update_rol(
    initiatief_id: UUID,
    rol_id: UUID,
    data: RolUpdate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> RolResponse:
    await _bijdrager(db, initiatief_id, init_ctx, current_user, perm_ctx)
    repo = InitiatiefRolRepository(db)
    rol = await _rol_of_404(repo, initiatief_id, rol_id)
    waarden = data.model_dump(exclude_unset=True)
    if data.naam and await repo.naam_bestaat(initiatief_id, data.naam, behalve=rol.id):
        raise HTTPException(status_code=409, detail=BESTAAT_AL)

    gebeurtenis = None
    if "vervuller_id" in waarden:
        nieuw = waarden["vervuller_id"]
        if nieuw is not None and nieuw != rol.vervuller_id:
            await require_initiatief_member(db, initiatief_id, nieuw)
            repo.wijs_toe(rol, nieuw)
            gebeurtenis = "toegewezen"
        elif nieuw is None and rol.status == "belegd":
            repo.opnieuw_toewijzen(rol)
            gebeurtenis = "opnieuw_open"
    if "status" in waarden and gebeurtenis is None:
        doel_status = waarden["status"]
        if doel_status == "open" and rol.status == "belegd":
            repo.opnieuw_toewijzen(rol)
            gebeurtenis = "opnieuw_open"
        elif doel_status == "concept" and rol.status == "belegd":
            raise HTTPException(
                status_code=400,
                detail="Een belegde rol gaat eerst terug naar open",
            )
        elif doel_status is not None and doel_status != rol.status:
            rol.status = doel_status
            gebeurtenis = doel_status

    await repo.zet_velden(rol, waarden)
    try:
        async with db.begin_nested():
            rol = await repo.ververs(rol)
    except IntegrityError:
        raise HTTPException(status_code=409, detail=BESTAAT_AL)
    details = {"initiatief_id": str(initiatief_id), "naam": rol.naam}
    if gebeurtenis:
        details["status"] = rol.status
        details["vervuller_id"] = str(rol.vervuller_id) if rol.vervuller_id else None
    await log_activity(
        db, current_user, None, "initiatief_rol.updated", details=details
    )
    return await _antwoord(db, rol)


@router.delete(
    "/initiatieven/{initiatief_id}/rollen/{rol_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_rol(
    initiatief_id: UUID,
    rol_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> None:
    await _bijdrager(db, initiatief_id, init_ctx, current_user, perm_ctx)
    repo = InitiatiefRolRepository(db)
    rol = await _rol_of_404(repo, initiatief_id, rol_id)
    naam = rol.naam
    await repo.delete(rol)
    await log_activity(
        db,
        current_user,
        None,
        "initiatief_rol.deleted",
        details={"initiatief_id": str(initiatief_id), "naam": naam},
    )


# ---------------------------------------------------------------------------
# Interesse
# ---------------------------------------------------------------------------


@router.put(
    "/initiatieven/{initiatief_id}/rollen/{rol_id}/interesse/{person_id}",
    response_model=RolResponse,
)
async def zet_interesse(
    initiatief_id: UUID,
    rol_id: UUID,
    person_id: UUID,
    data: InteresseZetten,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> RolResponse:
    """Leg interesse vast in de huidige ronde, ook voor een ander."""
    await _bijdrager(db, initiatief_id, init_ctx, current_user, perm_ctx)
    repo = InitiatiefRolRepository(db)
    rol = await _rol_of_404(repo, initiatief_id, rol_id)
    if rol.status != "open":
        raise HTTPException(
            status_code=400, detail="Interesse kan alleen bij een open rol"
        )
    await require_initiatief_member(db, initiatief_id, person_id)
    door_id = current_user.id if current_user is not None else None
    # Twee gelijke verzoeken tegelijk: de database vangt de tweede (409).
    try:
        async with db.begin_nested():
            rol = await repo.zet_interesse(rol, person_id, data.invulling, door_id)
    except IntegrityError:
        raise HTTPException(
            status_code=409, detail="Net al vastgelegd, probeer opnieuw"
        )
    await log_activity(
        db,
        current_user,
        None,
        "initiatief_rol.interesse_gezet",
        details={
            "initiatief_id": str(initiatief_id),
            "naam": rol.naam,
            "person_id": str(person_id),
        },
    )
    return await _antwoord(db, rol)


@router.delete(
    "/initiatieven/{initiatief_id}/rollen/{rol_id}/interesse/{person_id}",
    response_model=RolResponse,
)
async def verwijder_interesse(
    initiatief_id: UUID,
    rol_id: UUID,
    person_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> RolResponse:
    await _bijdrager(db, initiatief_id, init_ctx, current_user, perm_ctx)
    repo = InitiatiefRolRepository(db)
    rol = await _rol_of_404(repo, initiatief_id, rol_id)
    bijgewerkt = await repo.verwijder_interesse(rol, person_id)
    if bijgewerkt is None:
        raise HTTPException(status_code=404, detail="Interesse niet gevonden")
    await log_activity(
        db,
        current_user,
        None,
        "initiatief_rol.interesse_verwijderd",
        details={
            "initiatief_id": str(initiatief_id),
            "naam": bijgewerkt.naam,
            "person_id": str(person_id),
        },
    )
    return await _antwoord(db, bijgewerkt)


# ---------------------------------------------------------------------------
# Raakvlakken
# ---------------------------------------------------------------------------


@router.post(
    "/initiatieven/{initiatief_id}/rollen/{rol_id}/raakvlakken",
    response_model=RolResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_raakvlak(
    initiatief_id: UUID,
    rol_id: UUID,
    data: RaakvlakCreate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> RolResponse:
    await _bijdrager(db, initiatief_id, init_ctx, current_user, perm_ctx)
    repo = InitiatiefRolRepository(db)
    rol = await _rol_of_404(repo, initiatief_id, rol_id)
    ander = await _rol_of_404(repo, initiatief_id, data.rol_id)
    if ander.id == rol.id:
        raise HTTPException(
            status_code=400, detail="Een rol heeft geen raakvlak met zichzelf"
        )
    if await repo.raakvlak_tussen(rol.id, ander.id) is not None:
        raise HTTPException(status_code=409, detail="Dit raakvlak bestaat al")
    try:
        async with db.begin_nested():
            await repo.maak_raakvlak(rol.id, ander.id, data.omschrijving)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Dit raakvlak bestaat al")
    await log_activity(
        db,
        current_user,
        None,
        "initiatief_rol.raakvlak_gemaakt",
        details={
            "initiatief_id": str(initiatief_id),
            "rollen": [rol.naam, ander.naam],
        },
    )
    return await _antwoord(db, rol)


@router.put(
    "/initiatieven/{initiatief_id}/raakvlakken/{raakvlak_id}",
    status_code=status.HTTP_200_OK,
)
async def update_raakvlak(
    initiatief_id: UUID,
    raakvlak_id: UUID,
    data: RaakvlakUpdate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> dict:
    await _bijdrager(db, initiatief_id, init_ctx, current_user, perm_ctx)
    repo = InitiatiefRolRepository(db)
    rv = require_found(
        await repo.raakvlak_in_initiatief(initiatief_id, raakvlak_id), "Raakvlak"
    )
    rv.omschrijving = data.omschrijving
    await db.flush()
    return {"id": str(rv.id), "omschrijving": rv.omschrijving}


@router.delete(
    "/initiatieven/{initiatief_id}/raakvlakken/{raakvlak_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_raakvlak(
    initiatief_id: UUID,
    raakvlak_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> None:
    await _bijdrager(db, initiatief_id, init_ctx, current_user, perm_ctx)
    repo = InitiatiefRolRepository(db)
    rv = require_found(
        await repo.raakvlak_in_initiatief(initiatief_id, raakvlak_id), "Raakvlak"
    )
    await db.delete(rv)
    await db.flush()
    await log_activity(
        db,
        current_user,
        None,
        "initiatief_rol.raakvlak_verwijderd",
        details={"initiatief_id": str(initiatief_id)},
    )


# ---------------------------------------------------------------------------
# Export en import
# ---------------------------------------------------------------------------


@router.get("/initiatieven/{initiatief_id}/rollen/export", response_model=RollenExport)
async def export_rollen(
    initiatief_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> RollenExport:
    initiatief = await _rollen_zichtbaar(db, initiatief_id, init_ctx)
    repo = InitiatiefRolRepository(db)
    cirkel = await repo.ankercirkel(initiatief)
    rollen = await repo.list_for_initiatief(initiatief_id)
    namen = {r.id: r.naam for r in rollen}
    # Het standaardadres uit PersonEmail: dat vindt de import terug.
    vervuller_ids = {r.vervuller_id for r in rollen if r.vervuller_id}
    emails = {
        pid: email
        for pid, email in (
            await db.execute(
                select(PersonEmail.person_id, PersonEmail.email).where(
                    PersonEmail.person_id.in_(vervuller_ids),
                    PersonEmail.is_default.is_(True),
                )
            )
        ).all()
    }
    raakvlakken = []
    gezien: set[UUID] = set()
    for paren in (await repo.raakvlakken_per_rol(initiatief_id)).values():
        for rv, _ander in paren:
            if rv.id in gezien:
                continue
            gezien.add(rv.id)
            raakvlakken.append(
                ExportRaakvlak(
                    rol_a=namen[rv.rol_a_id],
                    rol_b=namen[rv.rol_b_id],
                    omschrijving=rv.omschrijving,
                )
            )
    return RollenExport(
        cirkel=ExportCirkel(doel=cirkel.doel, focus=cirkel.focus or []),
        rollen=[
            ExportRol(
                naam=r.naam,
                status=r.status,
                doel=r.doel,
                aanspreekbaar_op=r.aanspreekbaar_op or [],
                domein=r.domein or [],
                toelichting=r.toelichting,
                feedback=r.feedback,
                vervuller_email=emails.get(r.vervuller_id) if r.vervuller_id else None,
            )
            for r in rollen
        ],
        raakvlakken=raakvlakken,
    )


@router.post(
    "/initiatieven/{initiatief_id}/rollen/import", response_model=ImportResultaat
)
async def import_rollen(
    initiatief_id: UUID,
    data: RollenExport,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> ImportResultaat:
    """Voeg rollen toe of werk ze bij op naam. Er verdwijnt niets.

    Een vervuller komt mee als het e-mailadres bij iemand hoort die het
    initiatief kan zien; anders komt de rol open, met een melding.
    """
    initiatief = await _bijdrager(db, initiatief_id, init_ctx, current_user, perm_ctx)
    repo = InitiatiefRolRepository(db)
    init_repo = InitiatiefRepository(db)
    uit = ImportResultaat()

    cirkel = await repo.ankercirkel(initiatief)
    # Zonder cirkel in het bestand blijven doel en focus staan.
    if "cirkel" in data.model_fields_set:
        await repo.zet_cirkel(cirkel, data.cirkel.model_dump(exclude_unset=True))

    for item in data.rollen:
        vervuller_id = None
        if item.vervuller_email:
            person = await find_person_by_email(db, item.vervuller_email)
            if person is not None and await init_repo.is_member(
                initiatief_id, person.id
            ):
                vervuller_id = person.id
            else:
                uit.meldingen.append(
                    f"{item.naam}: {item.vervuller_email} is geen lid van "
                    "dit initiatief, de rol staat open"
                )
        waarden = item.model_dump(exclude={"status", "vervuller_email"})
        if vervuller_id is not None:
            rol_status = "belegd"
        elif item.status == "belegd":
            rol_status = "open"
        else:
            rol_status = item.status

        bestaand = await repo.op_naam(initiatief_id, item.naam)
        if bestaand is None:
            await repo.create(
                initiatief, waarden, status=rol_status, vervuller_id=vervuller_id
            )
            uit.aangemaakt += 1
        else:
            # Dezelfde regels als bij wijzigen: toewijzen maakt belegd, een
            # belegde rol zonder vervuller gaat opnieuw open (nieuwe ronde).
            await repo.zet_velden(bestaand, waarden)
            if vervuller_id is not None:
                repo.wijs_toe(bestaand, vervuller_id)
            elif bestaand.status == "belegd":
                repo.opnieuw_toewijzen(bestaand)
            else:
                bestaand.status = rol_status
            await repo.ververs(bestaand)
            uit.bijgewerkt += 1

    for rv in data.raakvlakken:
        a = await repo.op_naam(initiatief_id, rv.rol_a)
        b = await repo.op_naam(initiatief_id, rv.rol_b)
        if a is None or b is None:
            ontbreekt = rv.rol_a if a is None else rv.rol_b
            uit.meldingen.append(f"Raakvlak overgeslagen: rol {ontbreekt} bestaat niet")
            continue
        if a.id == b.id:
            uit.meldingen.append(f"Raakvlak overgeslagen: {rv.rol_a} met zichzelf")
            continue
        bestaand_rv = await repo.raakvlak_tussen(a.id, b.id)
        if bestaand_rv is None:
            await repo.maak_raakvlak(a.id, b.id, rv.omschrijving)
            uit.raakvlakken += 1
        else:
            bestaand_rv.omschrijving = rv.omschrijving
    await db.flush()

    await log_activity(
        db,
        current_user,
        None,
        "initiatief_rol.geimporteerd",
        details={
            "initiatief_id": str(initiatief_id),
            "aangemaakt": uit.aangemaakt,
            "bijgewerkt": uit.bijgewerkt,
        },
    )
    return uit


# ---------------------------------------------------------------------------
# Werk en focus per persoon
# ---------------------------------------------------------------------------


@router.put(
    "/initiatieven/{initiatief_id}/personen/{person_id}/focus",
    response_model=FocusZetten,
)
async def zet_focus(
    initiatief_id: UUID,
    person_id: UUID,
    data: FocusZetten,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> FocusZetten:
    await _bijdrager(db, initiatief_id, init_ctx, current_user, perm_ctx, rollen=False)
    await require_initiatief_member(db, initiatief_id, person_id)
    focus = await InitiatiefRolRepository(db).zet_focus(
        initiatief_id, person_id, data.focus
    )
    await log_activity(
        db,
        current_user,
        None,
        "initiatief_persoon.focus_gezet",
        details={"initiatief_id": str(initiatief_id), "person_id": str(person_id)},
    )
    return FocusZetten(focus=focus)


@router.get(
    "/initiatieven/{initiatief_id}/personen/{person_id}/werk",
    response_model=PersoonWerkResponse,
)
async def werk_van_persoon(
    initiatief_id: UUID,
    person_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    org_ctx: OrgContext = Depends(get_org_context),
) -> PersoonWerkResponse:
    initiatief = await _zichtbaar(db, initiatief_id, init_ctx)
    person = await db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Persoon niet gevonden")
    repo = InitiatiefRolRepository(db)
    is_lid = await InitiatiefRepository(db).is_member(initiatief_id, person_id)
    resp = PersoonWerkResponse(
        person=PersoonKort.model_validate(person),
        is_lid=is_lid,
        focus=await repo.focus_van(initiatief_id, person_id),
        leads=await repo.leads_van(initiatief_id, person_id),
        casussen=await repo.casussen_van(initiatief_id, person_id),
        issues=await repo.issues_van(initiatief_id, person_id),
        open_taken=await repo.open_taken_van(initiatief_id, person_id, org_ctx),
    )
    if initiatief.rollen_enabled:
        resp.rollen = await repo.rollen_van(initiatief_id, person_id)
        resp.interesse = await repo.interesse_van(initiatief_id, person_id)
    return resp
