"""API routes voor casussen.

Een casus start vanuit een lead die de trechter uit is en leeft daarna los van
de lead. Toegang loopt via de initiatief-context, net als bij leads. Casussen
zijn nooit publiek.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.api.deps import require_found
from bouwmeester.core.auth import OptionalUser
from bouwmeester.core.authority import (
    require_can_change_casus,
    require_can_delete_casus,
    require_can_manage_casus_team,
    require_can_start_casus,
)
from bouwmeester.core.database import get_db
from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    get_initiatief_context,
    require_initiatief_member,
    require_initiatief_visible,
)
from bouwmeester.core.org_context import OrgContext, get_org_context
from bouwmeester.core.permissions import PermissionContext, get_permission_context
from bouwmeester.core.storage import delete_blob
from bouwmeester.models.casus import Casus
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.mattermost_channel_link import SCOPE_CASUS, SCOPE_LEAD
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.repositories.casus import CasusRepository, bijlage_paden_van_casussen
from bouwmeester.repositories.casus_soort import CasusSoortRepository
from bouwmeester.repositories.issue import IssueRepository
from bouwmeester.repositories.mattermost_channel_link import (
    MattermostChannelLinkRepository,
)
from bouwmeester.repositories.task import TaskRepository
from bouwmeester.schema.casus import (
    DEFAULT_DOD,
    CasusDetailResponse,
    CasusResponse,
    CasusStart,
    CasusTeamCreate,
    CasusTeamResponse,
    CasusUpdate,
)
from bouwmeester.schema.casus_fases import eerste_fase, geldende_casus_fases
from bouwmeester.schema.casus_soort import momentopname_eisen
from bouwmeester.schema.startvragen import (
    controleer_antwoorden,
    geldende_startvragen,
)
from bouwmeester.schema.task import (
    BacklogIssue,
    BacklogLosseTaak,
    BacklogResponse,
    BacklogTask,
)
from bouwmeester.services import casus_kanaal_service as kanaal
from bouwmeester.services.activity_service import log_activity

router = APIRouter(prefix="/casussen", tags=["casussen"])


def _check_initiatief_visible(
    initiatief_id: UUID | None, init_ctx: InitiatiefContext
) -> None:
    """404 buiten de zichtbare initiatieven (zie core.initiatief_context)."""
    require_initiatief_visible(initiatief_id, init_ctx, detail="Casus niet gevonden")


async def _get_casus(
    db: AsyncSession, casus_id: UUID, init_ctx: InitiatiefContext
) -> Casus:
    casus = await CasusRepository(db).get(casus_id)
    if casus is None:
        raise HTTPException(status_code=404, detail="Casus niet gevonden")
    _check_initiatief_visible(casus.initiatief_id, init_ctx)
    return casus


async def _require_team_candidate(
    db: AsyncSession, casus: Casus, person_id: UUID
) -> None:
    """Trekker en teamleden moeten het initiatief van de casus kunnen zien.

    Dezelfde regel als voor wie een taak doet: `require_initiatief_member`.
    """
    await require_initiatief_member(db, casus.initiatief_id, person_id)


def _actor(current_user) -> str | None:
    """Wie het deed, voor het bericht in het casuskanaal."""
    return current_user.naam if current_user else None


def _team_response(rp: ResourcePermission) -> CasusTeamResponse:
    return CasusTeamResponse(
        id=rp.id,
        person_id=rp.person_id,
        person_naam=rp.person.naam if rp.person else "",
        person_functie=rp.person.functie if rp.person else None,
        rol=rp.rol,
        created_at=rp.created_at,
    )


async def _with_summaries(
    repo: CasusRepository, casussen: list[Casus]
) -> list[CasusResponse]:
    ids = [c.id for c in casussen]
    team = await repo.team_summary(ids)
    issues = await repo.issue_counts(ids)
    out = []
    for c in casussen:
        resp = CasusResponse.model_validate(c)
        resp.trekker_naam, resp.team_count = team.get(c.id, (None, 0))
        resp.issue_count, resp.issue_done_count = issues.get(c.id, (0, 0))
        out.append(resp)
    return out


@router.get("", response_model=list[CasusResponse])
async def list_casussen(
    current_user: OptionalUser,
    initiatief_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[CasusResponse]:
    repo = CasusRepository(db)
    return await _with_summaries(
        repo, await repo.list_all(initiatief_id, init_ctx=init_ctx)
    )


@router.post(
    "", response_model=CasusDetailResponse, status_code=status.HTTP_201_CREATED
)
async def start_casus(
    data: CasusStart,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> CasusDetailResponse:
    """Start een casus vanuit een lead die de trechter uit is.

    Voorwaarden: de lead is zichtbaar, hoort bij een initiatief met
    casussen aan, staat in de startkolom (dummy-regel, zie schema/casus.py),
    heeft nog geen casus, en de startvragen van het initiatief zijn
    beantwoord (schema/startvragen.py; 422 anders). Trekker en teamleden
    moeten het initiatief kunnen zien.
    """
    lead = await db.get(Lead, data.lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead niet gevonden")
    _check_initiatief_visible(lead.initiatief_id, init_ctx)
    # Een casus hoort bij een initiatief dat ermee werkt. Een lead zonder
    # initiatief heeft geen schakelaar en dus geen casus: zo'n casus zou
    # voor iedere ingelogde gebruiker zichtbaar zijn.
    init = await db.get(Initiatief, lead.initiatief_id) if lead.initiatief_id else None
    if init is None or not init.casussen_enabled:
        raise HTTPException(
            status_code=400,
            detail="Casussen staan niet aan voor het initiatief van deze lead",
        )
    # Zien is niet genoeg: starten vraagt bijdrager of eigenaar.
    await require_can_start_casus(db, perm_ctx, current_user, init.id)
    repo = CasusRepository(db)
    if await repo.get_by_lead(lead.id) is not None:
        raise HTTPException(
            status_code=409, detail="Uit deze lead is al een casus gestart"
        )
    start_stage = await repo.start_stage_for_lead(lead)
    if lead.stage != start_stage:
        raise HTTPException(
            status_code=409,
            detail=f"Een casus start pas als de lead in de kolom '{start_stage}' staat",
        )

    team_ids = [pid for pid in [data.trekker_id, *data.teamlid_ids] if pid is not None]
    for pid in dict.fromkeys(team_ids):
        await _require_team_candidate(db, Casus(initiatief_id=lead.initiatief_id), pid)
    soort_repo = CasusSoortRepository(db)
    # De gekozen soorten, in de volgorde van de instellingen: hun starteisen
    # komen zo in de momentopname.
    gekozen = []
    if data.soort_ids:
        eigen = await soort_repo.list_for_initiatief(lead.initiatief_id)
        if any(sid not in {s.id for s in eigen} for sid in data.soort_ids):
            raise HTTPException(
                status_code=400,
                detail="Een of meer soorten horen niet bij het initiatief van de lead",
            )
        gekozen = [s for s in eigen if s.id in set(data.soort_ids)]

    vragen = geldende_startvragen(init.startvragen)
    sv = data.startvoorwaarden
    try:
        antwoorden = controleer_antwoorden(vragen, sv.antwoorden, sv.casustype)
        start_eisen = momentopname_eisen(gekozen, "start_eisen", sv.start_eisen or [])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    startvoorwaarden = sv.model_dump(
        by_alias=True, exclude_none=True, exclude={"start_eisen"}
    )
    # De momentopname: de vraag erbij zoals hij nu luidt, en alle starteisen
    # van de gekozen soorten met wat het team aanvinkte.
    startvoorwaarden["antwoorden"] = antwoorden
    if start_eisen:
        startvoorwaarden["start_eisen"] = start_eisen

    casus = await repo.start_from_lead(
        lead,
        startvoorwaarden=startvoorwaarden,
        started_by_id=current_user.id if current_user else None,
        # Een nieuwe casus begint in de eerste fase van de funnel.
        fase=eerste_fase(init.casus_fases),
    )
    seen: set[UUID] = set()
    for pid, rol in [
        (data.trekker_id, "trekker"),
        *[(t, "teamlid") for t in data.teamlid_ids],
    ]:
        if pid is None or pid in seen:
            continue
        seen.add(pid)
        db.add(
            ResourcePermission(
                person_id=pid, resource_type="casus", resource_id=casus.id, rol=rol
            )
        )
    await db.flush()
    if data.soort_ids:
        await soort_repo.zet_voor_casus(casus.id, data.soort_ids)
        await db.refresh(casus, attribute_names=["soorten"])

    # Het kanaal van de lead gaat mee: de lead is vanaf nu alleen-lezen, en
    # het gesprek loopt door bij de casus. De voortgang staat er uit: zo'n
    # kanaal is gekozen om berichten binnen te halen, niet om casusinhoud
    # naar buiten te sturen. Aanzetten doet het team bij de casus, en dat
    # kan alleen in een privékanaal.
    await MattermostChannelLinkRepository(db).verhuis(
        van=(SCOPE_LEAD, lead.id),
        naar=(SCOPE_CASUS, casus.id),
        casus_updates_enabled=False,
        van_de_lead=True,
    )

    await log_activity(
        db,
        current_user,
        None,
        "casus.started",
        details={
            "casus_id": str(casus.id),
            "lead_id": str(lead.id),
            "title": casus.title,
        },
    )
    return await _detail(repo, casus)


async def _detail(repo: CasusRepository, casus: Casus) -> CasusDetailResponse:
    base = (await _with_summaries(repo, [casus]))[0]
    resp = CasusDetailResponse(**base.model_dump())
    resp.lead = casus.lead
    resp.team = [_team_response(rp) for rp in await repo.list_team(casus.id)]
    eigen = casus.initiatief.dod_items if casus.initiatief else None
    resp.dod_items = list(eigen) if eigen else list(DEFAULT_DOD)
    return resp


@router.get("/backlog", response_model=BacklogResponse)
async def list_backlog(
    current_user: OptionalUser,
    initiatief_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    org_ctx: OrgContext = Depends(get_org_context),
) -> BacklogResponse:
    """De backlog van een initiatief: alle issues van al zijn casussen.

    Omgekeerd aan de casusweergave: per issue de casus erbij en de taken
    eronder. Sorteren en filteren gebeurt in de
    client; de lijst is klein genoeg. Staat vóór `/{casus_id}`, anders vangt
    die route het pad.
    """
    _check_initiatief_visible(initiatief_id, init_ctx)
    issues, losse = await IssueRepository(db).list_backlog(
        initiatief_id, init_ctx=init_ctx, org_ctx=org_ctx
    )
    out: list[BacklogIssue] = []
    for issue in issues:
        item = BacklogIssue.model_validate(issue)
        # Alleen hoofdtaken; een taak in een casus heeft geen subtaken.
        tasks = [
            BacklogTask.model_validate(t) for t in issue.tasks if t.parent_id is None
        ]
        tasks.sort(
            key=lambda t: (t.order if t.order is not None else 1 << 30, t.created_at)
        )
        item.tasks = tasks
        out.append(item)
    losse_taken = [BacklogLosseTaak.model_validate(t) for t in losse]
    # Het aantal opmerkingen per kaartje, in één query voor de hele backlog.
    kaartjes = [t for item in out for t in item.tasks] + losse_taken
    aantallen = await TaskRepository(db).comment_counts([t.id for t in kaartjes])
    for t in kaartjes:
        t.comment_count = aantallen.get(t.id, 0)
    return BacklogResponse(issues=out, losse_taken=losse_taken)


@router.get("/{casus_id}", response_model=CasusDetailResponse)
async def get_casus(
    casus_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> CasusDetailResponse:
    casus = await _get_casus(db, casus_id, init_ctx)
    return await _detail(CasusRepository(db), casus)


@router.put("/{casus_id}", response_model=CasusDetailResponse)
async def update_casus(
    casus_id: UUID,
    data: CasusUpdate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> CasusDetailResponse:
    bestaand = await _get_casus(db, casus_id, init_ctx)
    await require_can_change_casus(db, perm_ctx, current_user, bestaand)
    if data.fase is not None:
        # Alleen een fase uit de funnel van het initiatief.
        fases = geldende_casus_fases(
            bestaand.initiatief.casus_fases if bestaand.initiatief else None
        )
        if data.fase not in {f.id for f in fases}:
            raise HTTPException(
                status_code=400,
                detail="Deze fase staat niet in de casusfunnel van het initiatief",
            )
    # De eindeisen van de soorten zoals het team ze naliep: een momentopname,
    # en geen poort voor de fase.
    eind_eisen = None
    if data.eind_eisen is not None:
        try:
            eind_eisen = momentopname_eisen(
                bestaand.soorten, "eind_eisen", data.eind_eisen
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        data = CasusUpdate.model_validate(
            data.model_dump(exclude_unset=True, exclude={"eind_eisen"})
        )
    repo = CasusRepository(db)
    old = await repo.get(casus_id)
    old_fase = old.fase if old else None
    if eind_eisen is not None:
        # Vóór de update, zodat die hem meeschrijft en updated_at ververst.
        bestaand.eind_eisen = eind_eisen
    casus = require_found(await repo.update(casus_id, data), "Casus")
    details: dict = {"casus_id": str(casus.id), "title": casus.title}
    if eind_eisen is not None:
        details["eind_eisen_akkoord"] = sum(e["akkoord"] for e in eind_eisen)
        details["eind_eisen_totaal"] = len(eind_eisen)
    if old_fase != casus.fase:
        details["old_fase"], details["new_fase"] = old_fase, casus.fase
        await kanaal.meld(
            db,
            casus.id,
            kanaal.bericht_fase(casus, old_fase, casus.fase, _actor(current_user)),
        )
    await log_activity(db, current_user, None, "casus.updated", details=details)
    return await _detail(repo, casus)


@router.delete("/{casus_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_casus(
    casus_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> None:
    """Verwijder een casus met issues, taken en team. De lead wordt weer
    bewerkbaar.

    Alleen de eigenaar van het initiatief.
    """
    casus = await _get_casus(db, casus_id, init_ctx)
    await require_can_delete_casus(db, perm_ctx, current_user, casus)
    title = casus.title
    # Bijlagen van de taken gaan in de database mee (CASCADE), hun bestanden
    # niet: die ruimen we na de commit op, anders blijven ze staan.
    bijlage_paden = await bijlage_paden_van_casussen(db, [casus_id])
    # Het kanaal van de lead gaat terug naar de lead, die weer bewerkbaar
    # wordt. Wat het team zelf aan de casus hing, wordt ontkoppeld.
    await MattermostChannelLinkRepository(db).casus_weg(casus_id, casus.lead_id)
    await db.execute(
        sa_delete(ResourcePermission).where(
            ResourcePermission.resource_type == "casus",
            ResourcePermission.resource_id == casus_id,
        )
    )
    await db.delete(casus)
    await db.flush()
    await log_activity(
        db,
        current_user,
        None,
        "casus.deleted",
        details={"casus_id": str(casus_id), "title": title},
    )
    await db.commit()
    for pad in bijlage_paden:
        await delete_blob(pad)


@router.post(
    "/{casus_id}/team",
    response_model=CasusTeamResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_teamlid(
    casus_id: UUID,
    data: CasusTeamCreate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> CasusTeamResponse:
    casus = await _get_casus(db, casus_id, init_ctx)
    await require_can_manage_casus_team(db, perm_ctx, current_user, casus, rol=data.rol)
    await _require_team_candidate(db, casus, data.person_id)
    # Geen tweede rij voor dezelfde persoon en rol. Deze controle geeft de
    # nette melding; twee verzoeken tegelijk (een dubbelklik) komen er
    # allebei door, en die vangt de unieke index hieronder.
    bestaat = await db.scalar(
        select(ResourcePermission.id).where(
            ResourcePermission.resource_type == "casus",
            ResourcePermission.resource_id == casus_id,
            ResourcePermission.person_id == data.person_id,
            ResourcePermission.rol == data.rol,
        )
    )
    if bestaat is not None:
        raise HTTPException(
            status_code=409, detail="Deze persoon heeft die rol al op de casus"
        )
    rp = ResourcePermission(
        person_id=data.person_id,
        resource_type="casus",
        resource_id=casus_id,
        rol=data.rol,
    )
    try:
        async with db.begin_nested():
            db.add(rp)
            await db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=409, detail="Deze persoon heeft die rol al op de casus"
        ) from None
    await db.refresh(rp, attribute_names=["person"])
    await log_activity(
        db,
        current_user,
        None,
        "casus_team.added",
        details={
            "casus_id": str(casus_id),
            "person_id": str(data.person_id),
            "rol": data.rol,
        },
    )
    return _team_response(rp)


@router.delete("/{casus_id}/team/{rp_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_teamlid(
    casus_id: UUID,
    rp_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> None:
    casus = await _get_casus(db, casus_id, init_ctx)
    rp = await db.get(ResourcePermission, rp_id)
    if rp is None or rp.resource_type != "casus" or rp.resource_id != casus_id:
        raise HTTPException(status_code=404, detail="Teamlid niet gevonden")
    await require_can_manage_casus_team(
        db,
        perm_ctx,
        current_user,
        casus,
        rol=rp.rol,
        target_person_id=rp.person_id,
        verwijderen=True,
    )
    await db.delete(rp)
    await db.flush()
    await log_activity(
        db,
        current_user,
        None,
        "casus_team.removed",
        details={"casus_id": str(casus_id), "rp_id": str(rp_id)},
    )
