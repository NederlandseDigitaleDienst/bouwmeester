"""API routes for people."""

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bouwmeester.api.deps import require_deleted, require_found
from bouwmeester.core.api_key import generate_api_key, hash_api_key
from bouwmeester.core.auth import OptionalUser
from bouwmeester.core.authority import (
    require_can_delete_person,
    require_can_edit_person,
    require_can_place,
)
from bouwmeester.core.database import get_db
from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    get_initiatief_context,
)
from bouwmeester.core.org_context import OrgContext, apply_org_filter, get_org_context
from bouwmeester.core.permissions import (
    PermissionContext,
    SuperAdminUser,
    get_permission_context,
    require_permission,
)
from bouwmeester.core.query_utils import find_person_by_email, normalize_email
from bouwmeester.models.corpus_node import CorpusNode
from bouwmeester.models.organisatie_eenheid import OrganisatieEenheid
from bouwmeester.models.person import Person
from bouwmeester.models.person_email import PersonEmail
from bouwmeester.models.person_organisatie import PersonOrganisatieEenheid
from bouwmeester.models.person_phone import PersonPhone
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.models.task import Task
from bouwmeester.repositories.person import PersonRepository
from bouwmeester.repositories.task import apply_casus_filter
from bouwmeester.schema.person import (
    PHONE_LABELS,
    ApiKeyResponse,
    DuplicateCheckHit,
    PersonCreate,
    PersonCreateResponse,
    PersonDetailResponse,
    PersonEmailCreate,
    PersonEmailResponse,
    PersonMergeRequest,
    PersonOrganisatieCreate,
    PersonOrganisatieResponse,
    PersonOrganisatieUpdate,
    PersonPhoneCreate,
    PersonPhoneResponse,
    PersonResponse,
    PersonStakeholderNode,
    PersonSummaryResponse,
    PersonTaskSummary,
    PersonUpdate,
)
from bouwmeester.services.activity_service import log_activity

router = APIRouter(prefix="/people", tags=["people"])


def _editable_person(*, identity: bool):
    """Dependency: load the person from the path and check the caller may edit.

    ``identity`` guards email addresses (see ``require_can_edit_person``).
    """

    async def _load(
        id: UUID,
        perm_ctx: PermissionContext = Depends(require_permission("people:update")),
        db: AsyncSession = Depends(get_db),
    ) -> Person:
        person = require_found(await db.get(Person, id), "Person")
        await require_can_edit_person(db, perm_ctx, person, identity=identity)
        return person

    return _load


profile_editable_person = _editable_person(identity=False)
identity_editable_person = _editable_person(identity=True)


async def _require_can_place(
    db: AsyncSession,
    perm_ctx: PermissionContext,
    person_id: UUID,
    eenheid_id: UUID,
    *,
    ending: bool = False,
) -> tuple[Person, OrganisatieEenheid]:
    """Load person and eenheid and check the caller may change the placement."""
    person = require_found(await db.get(Person, person_id), "Person")
    eenheid = require_found(
        await db.get(OrganisatieEenheid, eenheid_id), "Organisatie-eenheid"
    )
    await require_can_place(db, perm_ctx, person, eenheid, ending=ending)
    return person, eenheid


async def _find_name_duplicates(
    naam: str, db: AsyncSession, limit: int = 10
) -> list[Person]:
    """Find active persons whose name matches all words via word-boundary regex.

    Each word in ``naam`` must appear at the start of a word in the stored name
    (PostgreSQL ``\\m`` anchor).  Used by both the create-person 409 check and
    the ``/check-duplicates`` endpoint so the algorithm is consistent.
    """
    words = naam.strip().split()
    if not words:
        return []

    stmt = (
        select(Person)
        .options(selectinload(Person.emails))
        .where(
            *[Person.naam.op("~*")(rf"\m{re.escape(w)}") for w in words],
            Person.is_active == True,  # noqa: E712
        )
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("", response_model=list[PersonResponse])
async def list_people(
    current_user: OptionalUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("people:read")),
) -> list[PersonResponse]:
    """List all people (users and agents)."""
    repo = PersonRepository(db)
    people = await repo.get_all(skip=skip, limit=limit)
    result = []
    for p in people:
        resp = PersonResponse.model_validate(p)
        resp.has_api_key = p.api_key_hash is not None
        result.append(resp)
    return result


@router.post(
    "",
    response_model=PersonCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_person(
    data: PersonCreate,
    current_user: OptionalUser,
    actor_id: UUID | None = Query(None),
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(require_permission("people:create")),
) -> PersonCreateResponse:
    """Create a person.

    Agents (is_agent=true) get an auto-generated API key (admin only).
    If a person with the same name already exists, returns 409 with the
    duplicates unless force=true is passed.
    """
    # Agent creation requires admin privileges (agents bypass email whitelist).
    if data.is_agent and not perm_ctx.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Alleen administrators kunnen agents aanmaken",
        )

    # Agent names must be unique among active agents
    if data.is_agent:
        existing = await db.execute(
            select(Person).where(
                Person.naam == data.naam,
                Person.is_agent == True,  # noqa: E712
                Person.is_active == True,  # noqa: E712
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Er bestaat al een agent met de naam '{data.naam}'",
            )

    # Check for duplicate names (non-agent persons) unless force=true.
    if not data.is_agent and not force:
        duplicates = await _find_name_duplicates(data.naam, db)
        if duplicates:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Er bestaan al personen met een vergelijkbare naam.",
                    "duplicates": [
                        {
                            "id": str(d.id),
                            "naam": d.naam,
                            "email": d.default_email,
                            "functie": d.functie,
                        }
                        for d in duplicates
                    ],
                },
            )

    repo = PersonRepository(db)
    person = await repo.create(data)

    # Auto-generate API key for agents.
    plaintext_key: str | None = None
    if data.is_agent:
        plaintext_key = generate_api_key()
        person.api_key_hash = hash_api_key(plaintext_key)
        await db.flush()

    # Also create a PersonEmail row if email was provided
    if data.email and await find_person_by_email(db, data.email) is not None:
        raise HTTPException(
            status_code=409, detail=f"E-mailadres '{data.email}' is al in gebruik"
        )
    if data.email:
        email_obj = PersonEmail(person_id=person.id, email=data.email, is_default=True)
        db.add(email_obj)
        await db.flush()
        await db.refresh(person, attribute_names=["emails"])

    await log_activity(
        db,
        current_user,
        actor_id,
        "person.created",
        details={"person_id": str(person.id), "naam": person.naam},
    )

    # Re-fetch with eager loading for response
    person = await repo.get(person.id)
    resp = PersonCreateResponse.model_validate(person)
    # Return plaintext key one-time on creation.
    if plaintext_key:
        resp.api_key = plaintext_key
        resp.has_api_key = True
    return resp


@router.get("/check-duplicates", response_model=list[DuplicateCheckHit])
async def check_duplicates(
    current_user: OptionalUser,
    naam: str = Query(..., min_length=2, max_length=500),
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("people:read")),
) -> list[DuplicateCheckHit]:
    """Check if persons with a similar name already exist.

    Uses the same word-boundary matching algorithm as the create-person
    duplicate guard, so the frontend can preview what the backend would block.
    """
    matches = await _find_name_duplicates(naam, db)
    return [
        DuplicateCheckHit(
            id=m.id,
            naam=m.naam,
            email=m.default_email,
            functie=m.functie,
        )
        for m in matches
    ]


@router.get("/search", response_model=list[PersonResponse])
async def search_people(
    current_user: OptionalUser,
    q: str = Query("", min_length=0, max_length=500),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("people:read")),
) -> list[PersonResponse]:
    """Search people by name. Returns all people if query is empty."""
    repo = PersonRepository(db)
    if not q.strip():
        people = await repo.get_all(limit=limit)
    else:
        people = await repo.search(q.strip(), limit=limit)
    result = []
    for p in people:
        resp = PersonResponse.model_validate(p)
        resp.has_api_key = p.api_key_hash is not None
        result.append(resp)
    return result


@router.get(
    "/match-email-organisatie",
    response_model=dict,
)
async def match_email_naar_organisatie(
    current_user: OptionalUser,
    email: str = Query(min_length=3, max_length=320),
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("people:read")),
) -> dict:
    """Geef de OrganisatieEenheid die bij een email-domein hoort (RIO).

    Gebruikt door de persoon-aanmaak-form: bij invoer van email zoekt de
    UI de organisatie waar de persoon bij hoort op basis van het domein.
    Returns 200 met `{matched: bool, organisatie_eenheid_id, organisatie_naam, domein}`.
    """
    from bouwmeester.models.org_email_domein import OrganisatieEmailDomein
    from bouwmeester.models.organisatie_eenheid import OrganisatieEenheid

    if "@" not in email:
        return {"matched": False, "domein": None}
    domein = email.rsplit("@", 1)[1].lower().strip()
    row = (
        await db.execute(
            select(OrganisatieEmailDomein, OrganisatieEenheid)
            .join(
                OrganisatieEenheid,
                OrganisatieEenheid.id == OrganisatieEmailDomein.organisatie_eenheid_id,
            )
            .where(OrganisatieEmailDomein.domein == domein)
        )
    ).first()
    if row is None:
        return {"matched": False, "domein": domein}
    _ed, eenheid = row
    return {
        "matched": True,
        "domein": domein,
        "organisatie_eenheid_id": str(eenheid.id),
        "organisatie_naam": eenheid.naam,
    }


@router.get("/expertise-values", response_model=list[str])
async def list_expertise_values(
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("people:read")),
) -> list[str]:
    """Return distinct expertise values used on existing persons.

    Used as suggestion source for the expertise CreatableSelect on the
    person edit/create form.
    """
    repo = PersonRepository(db)
    return await repo.list_expertise_values()


@router.get("/{id}/summary", response_model=PersonSummaryResponse)
async def get_person_summary(
    id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("people:read")),
    org_ctx: OrgContext = Depends(get_org_context),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> PersonSummaryResponse:
    """Compact summary: task counts, top open tasks, and stakeholder nodes."""
    repo = PersonRepository(db)
    require_found(await repo.get(id), "Person")

    def zichtbaar(stmt):
        # Org-scope tegen taken uit onzichtbare eenheden, casusfilter tegen
        # casustaken uit initiatieven die je niet ziet.
        return apply_casus_filter(
            apply_org_filter(stmt, Task.organisatie_eenheid_id, org_ctx), init_ctx
        )

    # Task counts (also scoped by org-context to avoid leaking task counts
    # from invisible eenheden)
    open_count_stmt = zichtbaar(
        select(func.count())
        .select_from(Task)
        .where(Task.assignee_id == id, Task.status.in_(["open", "in_progress"])),
    )
    done_count_stmt = zichtbaar(
        select(func.count())
        .select_from(Task)
        .where(Task.assignee_id == id, Task.status == "done"),
    )
    open_count = (await db.execute(open_count_stmt)).scalar() or 0
    done_count = (await db.execute(done_count_stmt)).scalar() or 0

    # Top open tasks (max 5, ordered by priority then deadline)
    open_tasks_stmt = zichtbaar(
        select(Task).where(
            Task.assignee_id == id, Task.status.in_(["open", "in_progress"])
        ),
    )
    open_tasks_stmt = open_tasks_stmt.order_by(
        # kritiek=0, hoog=1, normaal=2, laag=3
        func.array_position(["kritiek", "hoog", "normaal", "laag"], Task.priority),
        Task.deadline.asc().nullslast(),
    ).limit(5)
    open_tasks_result = await db.execute(open_tasks_stmt)
    open_tasks = [
        PersonTaskSummary.model_validate(t) for t in open_tasks_result.scalars().all()
    ]

    # Stakeholder nodes — filter cross-org via the linked CorpusNode's
    # organisatie_eenheid_id so a viewer only sees stakeholder rows on
    # nodes inside their visible scope.
    stakeholder_stmt = (
        select(ResourcePermission, CorpusNode)
        .join(CorpusNode, CorpusNode.id == ResourcePermission.resource_id)
        .where(
            ResourcePermission.resource_type == "corpus_node",
            ResourcePermission.person_id == id,
        )
    )
    stakeholder_stmt = apply_org_filter(
        stakeholder_stmt, CorpusNode.organisatie_eenheid_id, org_ctx
    )
    stakeholder_result = await db.execute(stakeholder_stmt)
    stakeholder_nodes = [
        PersonStakeholderNode(
            node_id=node.id,
            node_title=node.title,
            node_type=node.node_type,
            stakeholder_rol=rp.rol,
        )
        for rp, node in stakeholder_result.all()
    ]

    return PersonSummaryResponse(
        open_task_count=open_count,
        done_task_count=done_count,
        open_tasks=open_tasks,
        stakeholder_nodes=stakeholder_nodes,
    )


@router.get("/{id}", response_model=PersonDetailResponse)
async def get_person(
    id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("people:read")),
) -> PersonDetailResponse:
    """Get detailed person info including emails, phones, and org placements."""
    repo = PersonRepository(db)
    person = require_found(await repo.get(id), "Person")
    resp = PersonDetailResponse.model_validate(person)
    resp.has_api_key = person.api_key_hash is not None
    return resp


@router.put("/{id}", response_model=PersonDetailResponse)
async def update_person(
    id: UUID,
    data: PersonUpdate,
    current_user: OptionalUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    person: Person = Depends(profile_editable_person),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> PersonDetailResponse:
    """Update person fields (naam, functie, etc.)."""
    if "email" in data.model_fields_set and data.email != normalize_email(
        person.email or ""
    ):
        await require_can_edit_person(db, perm_ctx, person, identity=True)
    # Changing is_agent requires admin privileges (agents bypass email whitelist).
    if (
        data.is_agent is not None
        and data.is_agent != person.is_agent
        and not perm_ctx.is_super_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Alleen administrators kunnen de agent-status wijzigen",
        )

    repo = PersonRepository(db)
    require_found(await repo.update(id, data), "Person")

    # Re-fetch with eager loading for response
    person = require_found(await repo.get(id), "Person")

    await log_activity(
        db,
        current_user,
        actor_id,
        "person.updated",
        details={"person_id": str(person.id), "naam": person.naam},
    )

    resp = PersonDetailResponse.model_validate(person)
    resp.has_api_key = person.api_key_hash is not None
    return resp


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person(
    id: UUID,
    current_user: OptionalUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(require_permission("people:manage")),
) -> None:
    """Delete a person permanently."""
    repo = PersonRepository(db)
    person = require_found(await repo.get(id), "Person")
    await require_can_delete_person(db, perm_ctx, person)
    person_naam = person.naam
    require_deleted(await repo.delete(id), "Person")
    await log_activity(
        db,
        current_user,
        actor_id,
        "person.deleted",
        details={"person_id": str(id), "naam": person_naam},
    )


# --- API key management ---


@router.post("/{id}/rotate-api-key", response_model=ApiKeyResponse)
async def rotate_api_key(
    id: UUID,
    admin: SuperAdminUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyResponse:
    """Generate a new API key, replacing the previous one.

    The plaintext key is returned once — it cannot be retrieved afterwards.
    """
    person = require_found(await db.get(Person, id), "Person")
    if not person.is_agent:
        raise HTTPException(
            status_code=400,
            detail="API keys zijn alleen beschikbaar voor agents",
        )

    plaintext_key = generate_api_key()
    person.api_key_hash = hash_api_key(plaintext_key)
    await db.flush()

    await log_activity(
        db,
        admin,
        actor_id,
        "person.api_key_rotated",
        details={"person_id": str(person.id), "naam": person.naam},
    )

    return ApiKeyResponse(api_key=plaintext_key, person_id=person.id)


# --- Org placements ---


@router.get("/{id}/organisaties", response_model=list[PersonOrganisatieResponse])
async def list_person_organisaties(
    id: UUID,
    current_user: OptionalUser,
    actief: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    _perm=Depends(require_permission("people:read")),
) -> list[PersonOrganisatieResponse]:
    """List org unit placements for a person. Defaults to active placements only."""
    require_found(await db.get(Person, id), "Person")

    stmt = (
        select(PersonOrganisatieEenheid, OrganisatieEenheid.naam)
        .join(OrganisatieEenheid)
        .where(PersonOrganisatieEenheid.person_id == id)
    )
    if actief:
        stmt = stmt.where(PersonOrganisatieEenheid.eind_datum.is_(None))
    stmt = stmt.order_by(PersonOrganisatieEenheid.start_datum.desc())
    result = await db.execute(stmt)
    return [
        PersonOrganisatieResponse(
            id=row.PersonOrganisatieEenheid.id,
            person_id=row.PersonOrganisatieEenheid.person_id,
            organisatie_eenheid_id=row.PersonOrganisatieEenheid.organisatie_eenheid_id,
            organisatie_eenheid_naam=row.naam,
            dienstverband=row.PersonOrganisatieEenheid.dienstverband,
            functietitel=row.PersonOrganisatieEenheid.functietitel,
            bron=row.PersonOrganisatieEenheid.bron,
            start_datum=row.PersonOrganisatieEenheid.start_datum,
            eind_datum=row.PersonOrganisatieEenheid.eind_datum,
        )
        for row in result.all()
    ]


@router.post(
    "/{id}/organisaties",
    response_model=PersonOrganisatieResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_person_organisatie(
    id: UUID,
    data: PersonOrganisatieCreate,
    current_user: OptionalUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(require_permission("people:update")),
) -> PersonOrganisatieResponse:
    """Place a person in an org unit. Returns 409 if already active in that unit."""
    _, eenheid = await _require_can_place(db, perm_ctx, id, data.organisatie_eenheid_id)

    # Check for existing active placement in same org unit
    existing = await db.execute(
        select(PersonOrganisatieEenheid).where(
            PersonOrganisatieEenheid.person_id == id,
            PersonOrganisatieEenheid.organisatie_eenheid_id
            == data.organisatie_eenheid_id,
            PersonOrganisatieEenheid.eind_datum.is_(None),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="Persoon is al ingedeeld bij deze eenheid",
        )

    placement = PersonOrganisatieEenheid(
        person_id=id,
        organisatie_eenheid_id=data.organisatie_eenheid_id,
        dienstverband=data.dienstverband,
        start_datum=data.start_datum,
    )
    db.add(placement)
    await db.flush()
    await db.refresh(placement)

    await log_activity(
        db,
        current_user,
        actor_id,
        "person.organisatie_added",
        details={
            "person_id": str(id),
            "organisatie_eenheid_id": str(data.organisatie_eenheid_id),
            "organisatie_eenheid_naam": eenheid.naam,
            "dienstverband": data.dienstverband,
        },
    )

    return PersonOrganisatieResponse(
        id=placement.id,
        person_id=placement.person_id,
        organisatie_eenheid_id=placement.organisatie_eenheid_id,
        organisatie_eenheid_naam=eenheid.naam,
        dienstverband=placement.dienstverband,
        start_datum=placement.start_datum,
        eind_datum=placement.eind_datum,
    )


@router.put(
    "/{id}/organisaties/{placement_id}",
    response_model=PersonOrganisatieResponse,
)
async def update_person_organisatie(
    id: UUID,
    placement_id: UUID,
    data: PersonOrganisatieUpdate,
    current_user: OptionalUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(require_permission("people:update")),
) -> PersonOrganisatieResponse:
    """Update an org placement (e.g. set eind_datum to end placement)."""
    stmt = select(PersonOrganisatieEenheid).where(
        PersonOrganisatieEenheid.id == placement_id,
        PersonOrganisatieEenheid.person_id == id,
    )
    result = await db.execute(stmt)
    placement = require_found(result.scalar_one_or_none(), "Placement")
    update_data = data.model_dump(exclude_unset=True)
    # Only an earlier end date counts as ending; a later one would reopen it.
    ending = (
        set(update_data) == {"eind_datum"}
        and data.eind_datum is not None
        and (placement.eind_datum is None or data.eind_datum <= placement.eind_datum)
    )
    await _require_can_place(
        db, perm_ctx, id, placement.organisatie_eenheid_id, ending=ending
    )

    for key, value in update_data.items():
        setattr(placement, key, value)
    await db.flush()
    await db.refresh(placement)

    eenheid = await db.get(OrganisatieEenheid, placement.organisatie_eenheid_id)

    await log_activity(
        db,
        current_user,
        actor_id,
        "person.organisatie_updated",
        details={
            "person_id": str(id),
            "placement_id": str(placement_id),
            "organisatie_eenheid_naam": eenheid.naam if eenheid else None,
        },
    )
    return PersonOrganisatieResponse(
        id=placement.id,
        person_id=placement.person_id,
        organisatie_eenheid_id=placement.organisatie_eenheid_id,
        organisatie_eenheid_naam=eenheid.naam if eenheid else "",
        dienstverband=placement.dienstverband,
        start_datum=placement.start_datum,
        eind_datum=placement.eind_datum,
    )


@router.delete(
    "/{id}/organisaties/{placement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_person_organisatie(
    id: UUID,
    placement_id: UUID,
    current_user: OptionalUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(require_permission("people:update")),
) -> None:
    """Delete an org placement permanently."""
    stmt = select(PersonOrganisatieEenheid).where(
        PersonOrganisatieEenheid.id == placement_id,
        PersonOrganisatieEenheid.person_id == id,
    )
    result = await db.execute(stmt)
    placement = require_found(result.scalar_one_or_none(), "Placement")
    await _require_can_place(
        db, perm_ctx, id, placement.organisatie_eenheid_id, ending=True
    )
    await db.delete(placement)
    await db.flush()

    await log_activity(
        db,
        current_user,
        actor_id,
        "person.organisatie_removed",
        details={"person_id": str(id), "placement_id": str(placement_id)},
    )


# --- Emails ---


@router.post(
    "/{id}/emails",
    response_model=PersonEmailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_person_email(
    id: UUID,
    data: PersonEmailCreate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    _person: Person = Depends(identity_editable_person),
) -> PersonEmailResponse:
    """Add an email address to a person. First email auto-becomes default."""
    email = normalize_email(data.email)

    # Check uniqueness
    existing = await db.execute(select(PersonEmail).where(PersonEmail.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"E-mailadres '{email}' is al in gebruik",
        )

    # If this is the first email, auto-set as default
    count_result = await db.execute(
        select(func.count()).select_from(PersonEmail).where(PersonEmail.person_id == id)
    )
    is_first = (count_result.scalar() or 0) == 0

    email_obj = PersonEmail(
        person_id=id,
        email=email,
        is_default=data.is_default or is_first,
    )
    db.add(email_obj)

    # If setting as default, unset others with a bulk update
    if email_obj.is_default:
        await db.flush()  # flush to get email_obj.id assigned
        await db.execute(
            update(PersonEmail)
            .where(
                PersonEmail.person_id == id,
                PersonEmail.id != email_obj.id,
            )
            .values(is_default=False)
        )

    await db.flush()
    await db.refresh(email_obj)
    return PersonEmailResponse.model_validate(email_obj)


@router.delete(
    "/{id}/emails/{email_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_person_email(
    id: UUID,
    email_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    _person: Person = Depends(identity_editable_person),
) -> None:
    """Remove an email address. Auto-promotes another email to default if needed."""
    stmt = select(PersonEmail).where(
        PersonEmail.id == email_id,
        PersonEmail.person_id == id,
    )
    result = await db.execute(stmt)
    email_obj = require_found(result.scalar_one_or_none(), "Email")
    was_default = email_obj.is_default
    await db.delete(email_obj)
    await db.flush()

    # Auto-promote another email to default if we deleted the default
    if was_default:
        next_email = (
            await db.execute(
                select(PersonEmail)
                .where(PersonEmail.person_id == id)
                .order_by(PersonEmail.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if next_email:
            next_email.is_default = True
            await db.flush()


@router.post(
    "/{id}/emails/{email_id}/set-default",
    response_model=PersonEmailResponse,
)
async def set_default_email(
    id: UUID,
    email_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    _person: Person = Depends(identity_editable_person),
) -> PersonEmailResponse:
    """Set an email as the default for a person."""
    # Verify the target email exists and belongs to this person
    target = (
        await db.execute(
            select(PersonEmail).where(
                PersonEmail.id == email_id,
                PersonEmail.person_id == id,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Email niet gevonden")

    # Bulk unset all defaults, then set the target
    await db.execute(
        update(PersonEmail).where(PersonEmail.person_id == id).values(is_default=False)
    )
    await db.execute(
        update(PersonEmail)
        .where(PersonEmail.id == email_id, PersonEmail.person_id == id)
        .values(is_default=True)
    )

    await db.flush()
    await db.refresh(target)
    return PersonEmailResponse.model_validate(target)


# --- Phones ---


@router.post(
    "/{id}/phones",
    response_model=PersonPhoneResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_person_phone(
    id: UUID,
    data: PersonPhoneCreate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    _person: Person = Depends(profile_editable_person),
) -> PersonPhoneResponse:
    """Add a phone number to a person. First phone auto-becomes default."""

    if data.label not in PHONE_LABELS:
        raise HTTPException(
            status_code=422,
            detail=f"Label moet een van {list(PHONE_LABELS.keys())} zijn",
        )

    # If this is the first phone, auto-set as default
    count_result = await db.execute(
        select(func.count()).select_from(PersonPhone).where(PersonPhone.person_id == id)
    )
    is_first = (count_result.scalar() or 0) == 0

    phone_obj = PersonPhone(
        person_id=id,
        phone_number=data.phone_number,
        label=data.label,
        is_default=data.is_default or is_first,
    )
    db.add(phone_obj)

    # If setting as default, unset others with a bulk update
    if phone_obj.is_default:
        await db.flush()  # flush to get phone_obj.id assigned
        await db.execute(
            update(PersonPhone)
            .where(
                PersonPhone.person_id == id,
                PersonPhone.id != phone_obj.id,
            )
            .values(is_default=False)
        )

    await db.flush()
    await db.refresh(phone_obj)
    return PersonPhoneResponse.model_validate(phone_obj)


@router.delete(
    "/{id}/phones/{phone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_person_phone(
    id: UUID,
    phone_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    _person: Person = Depends(profile_editable_person),
) -> None:
    """Remove a phone number. Auto-promotes another to default if needed."""
    stmt = select(PersonPhone).where(
        PersonPhone.id == phone_id,
        PersonPhone.person_id == id,
    )
    result = await db.execute(stmt)
    phone_obj = require_found(result.scalar_one_or_none(), "Telefoon")
    was_default = phone_obj.is_default
    await db.delete(phone_obj)
    await db.flush()

    # Auto-promote another phone to default if we deleted the default
    if was_default:
        next_phone = (
            await db.execute(
                select(PersonPhone)
                .where(PersonPhone.person_id == id)
                .order_by(PersonPhone.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if next_phone:
            next_phone.is_default = True
            await db.flush()


@router.post(
    "/{id}/phones/{phone_id}/set-default",
    response_model=PersonPhoneResponse,
)
async def set_default_phone(
    id: UUID,
    phone_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    _person: Person = Depends(profile_editable_person),
) -> PersonPhoneResponse:
    """Set a phone number as the default for a person."""
    # Verify the target phone exists and belongs to this person
    target = (
        await db.execute(
            select(PersonPhone).where(
                PersonPhone.id == phone_id,
                PersonPhone.person_id == id,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Telefoonnummer niet gevonden")

    # Bulk unset all defaults, then set the target
    await db.execute(
        update(PersonPhone).where(PersonPhone.person_id == id).values(is_default=False)
    )
    await db.execute(
        update(PersonPhone)
        .where(PersonPhone.id == phone_id, PersonPhone.person_id == id)
        .values(is_default=True)
    )

    await db.flush()
    await db.refresh(target)
    return PersonPhoneResponse.model_validate(target)


# --- Merge ---


@router.post("/merge", status_code=status.HTTP_200_OK)
async def merge_persons(
    data: PersonMergeRequest,
    admin: SuperAdminUser,
    actor_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PersonDetailResponse:
    """Merge one or more source persons into a target person (admin only).

    Moves all foreign-key references from each source to target, then deletes
    the sources.  All operations happen in a single transaction.
    Returns the updated target person.
    """
    if not data.source_ids:
        raise HTTPException(
            status_code=400,
            detail="Minstens een bronpersoon vereist",
        )
    if data.target_id in data.source_ids:
        raise HTTPException(
            status_code=400,
            detail="Bron en doel mogen niet hetzelfde zijn",
        )

    # Lock target row first to prevent concurrent merges.
    target_row = await db.execute(
        select(Person).where(Person.id == data.target_id).with_for_update()
    )
    require_found(target_row.scalar_one_or_none(), "Doelpersoon")

    # Lock and collect all source persons (sorted by id for consistent lock order).
    sources: list[Person] = []
    for source_id in sorted(data.source_ids):
        row = await db.execute(
            select(Person).where(Person.id == source_id).with_for_update()
        )
        sources.append(require_found(row.scalar_one_or_none(), "Bronpersoon"))

    # Discover FK metadata once.
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text as sa_text

    def _get_fk_info(sync_conn):
        """Return (table, fk_col, unique_cols_involving_fk) tuples."""
        inspector = sa_inspect(sync_conn)
        fk_cols: list[tuple[str, str]] = []
        for table_name in inspector.get_table_names():
            for fk in inspector.get_foreign_keys(table_name):
                referred = fk["referred_table"]
                if referred == "person" and fk["referred_columns"] == ["id"]:
                    for col in fk["constrained_columns"]:
                        fk_cols.append((table_name, col))

        unique_sets: dict[tuple[str, str], list[list[str]]] = {}
        for table_name, fk_col in fk_cols:
            for uq in inspector.get_unique_constraints(table_name):
                if fk_col in uq["column_names"]:
                    key = (table_name, fk_col)
                    unique_sets.setdefault(key, []).append(uq["column_names"])
        return fk_cols, unique_sets

    conn = await db.connection()
    fk_cols, unique_sets = await conn.run_sync(_get_fk_info)

    # Merge each source into target within this single transaction.
    for source in sources:
        source_id = source.id

        for table_name, col_name in fk_cols:
            uq_col_lists = unique_sets.get((table_name, col_name))
            if uq_col_lists:
                for uq_cols in uq_col_lists:
                    other_cols = [c for c in uq_cols if c != col_name]
                    if not other_cols:
                        await db.execute(
                            sa_text(
                                f'DELETE FROM "{table_name}" '
                                f'WHERE "{col_name}" = :source '
                                f"AND EXISTS ("
                                f'  SELECT 1 FROM "{table_name}" t2 '
                                f'  WHERE t2."{col_name}" = :target'
                                f")"
                            ),
                            {"source": source_id, "target": data.target_id},
                        )
                    else:
                        match_clause = " AND ".join(
                            f's."{c}" = t."{c}"' for c in other_cols
                        )
                        await db.execute(
                            sa_text(
                                f'DELETE FROM "{table_name}" s '
                                f'USING "{table_name}" t '
                                f'WHERE s."{col_name}" = :source '
                                f'AND t."{col_name}" = :target '
                                f"AND {match_clause}"
                            ),
                            {"source": source_id, "target": data.target_id},
                        )

            await db.execute(
                sa_text(
                    f'UPDATE "{table_name}" SET "{col_name}" = :target '
                    f'WHERE "{col_name}" = :source'
                ),
                {"target": data.target_id, "source": source_id},
            )

        await db.delete(source)

    await db.flush()

    # Log one activity per merge with all source info.
    await log_activity(
        db,
        admin,
        actor_id,
        "person.merged",
        details={
            "source_ids": [str(s.id) for s in sources],
            "source_namen": [s.naam for s in sources],
            "target_id": str(data.target_id),
        },
    )

    repo = PersonRepository(db)
    target_person = require_found(await repo.get(data.target_id), "Doelpersoon")
    resp = PersonDetailResponse.model_validate(target_person)
    resp.has_api_key = target_person.api_key_hash is not None
    return resp
