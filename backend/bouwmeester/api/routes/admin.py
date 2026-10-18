"""Admin API routes — whitelist, users, database backup, access requests."""

import asyncio
import io
import logging
import os
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.core.config import get_settings
from bouwmeester.core.database import get_db
from bouwmeester.core.encryption import decrypt_value, encrypt_value
from bouwmeester.core.permissions import AdminUser, SuperAdminUser
from bouwmeester.core.query_utils import normalize_email
from bouwmeester.core.whitelist import refresh_whitelist_cache, seed_admins_from_file
from bouwmeester.models.access_request import AccessRequest
from bouwmeester.models.app_config import AppConfig
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.mattermost_channel_link import (
    SCOPE_INITIATIEF,
    SCOPE_LEAD,
    MattermostChannelLink,
)
from bouwmeester.models.person import Person
from bouwmeester.models.whitelist_email import WhitelistEmail
from bouwmeester.models.worker_heartbeat import WorkerHeartbeat
from bouwmeester.schema.access_request import (
    AccessRequestResponse,
    AccessRequestReviewRequest,
)
from bouwmeester.schema.app_config import AppConfigResponse, AppConfigUpdate
from bouwmeester.schema.database_backup import (
    DatabaseBackupInfo,
    DatabaseResetRequest,
    DatabaseResetResult,
    DatabaseRestoreResult,
)
from bouwmeester.schema.whitelist import (
    AdminToggleRequest,
    AdminUserResponse,
    WhitelistEmailCreate,
    WhitelistEmailResponse,
)
from bouwmeester.schema.worker_health import (
    MattermostChannelOverview,
    MattermostChannelRights,
    WorkerHealthResponse,
    WorkerHeartbeatResponse,
)
from bouwmeester.services.activity_service import ActivityService
from bouwmeester.services.mattermost_service import (
    PERMISSION_CREATE_PRIVATE_CHANNEL,
    PERMISSION_CREATE_PUBLIC_CHANNEL,
    MattermostService,
    MattermostUnavailableError,
    vul_teamnaam_aan,
)

logger = logging.getLogger(__name__)

MAX_BACKUP_SIZE = 500 * 1024 * 1024  # 500 MB

router = APIRouter(prefix="/admin", tags=["admin"])

# ---------------------------------------------------------------------------
# Whitelist endpoints
# ---------------------------------------------------------------------------


@router.get("/whitelist", response_model=list[WhitelistEmailResponse])
async def list_whitelist(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> list[WhitelistEmailResponse]:
    """List all whitelisted email addresses (admin only)."""
    result = await db.execute(
        select(WhitelistEmail).order_by(WhitelistEmail.created_at.desc())
    )
    return [
        WhitelistEmailResponse.model_validate(row) for row in result.scalars().all()
    ]


@router.post(
    "/whitelist",
    response_model=WhitelistEmailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_whitelist_email(
    data: WhitelistEmailCreate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> WhitelistEmailResponse:
    """Add an email to the access whitelist. Returns 409 if already present."""
    email = normalize_email(data.email)

    existing = await db.execute(
        select(WhitelistEmail).where(WhitelistEmail.email == email)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"E-mailadres '{email}' staat al op de toegangslijst",
        )

    entry = WhitelistEmail(
        email=email,
        added_by=admin.default_email if admin else None,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)

    await refresh_whitelist_cache(db)

    return WhitelistEmailResponse.model_validate(entry)


@router.delete("/whitelist/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_whitelist_email(
    id: UUID,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove an email from the whitelist. Cannot remove your own email."""
    entry = await db.get(WhitelistEmail, id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Whitelist entry niet gevonden",
        )

    # Guard: prevent admin from removing their own email (lockout)
    admin_email = admin.default_email if admin else None
    if admin_email and entry.email == normalize_email(admin_email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Je kunt je eigen e-mailadres niet van de toegangslijst verwijderen",
        )

    await db.delete(entry)
    await db.flush()

    await refresh_whitelist_cache(db)


# ---------------------------------------------------------------------------
# User management endpoints
# ---------------------------------------------------------------------------


@router.get("/users", response_model=list[AdminUserResponse])
async def list_admin_users(
    admin: AdminUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[AdminUserResponse]:
    """List all human users (excluding agents) with admin status."""
    from bouwmeester.repositories.role import PersonRoleRepository

    result = await db.execute(
        select(Person)
        .where(Person.is_agent == False)  # noqa: E712
        .order_by(Person.naam)
        .offset(skip)
        .limit(limit)
    )
    persons = result.scalars().all()

    admin_person_ids = await PersonRoleRepository(db).get_super_admin_ids()

    responses = []
    for p in persons:
        resp = AdminUserResponse.model_validate(p)
        resp.is_admin = p.id in admin_person_ids
        responses.append(resp)
    return responses


@router.patch("/users/{id}", response_model=AdminUserResponse)
async def toggle_admin(
    id: UUID,
    data: AdminToggleRequest,
    admin: SuperAdminUser,
    db: AsyncSession = Depends(get_db),
) -> AdminUserResponse:
    """Grant or revoke admin status. Cannot revoke your own admin rights."""
    from datetime import date

    from bouwmeester.models.role import PersonRole

    person = await db.get(Person, id)
    if person is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Persoon niet gevonden",
        )

    # Guard: admin cannot remove their own admin status
    if admin and admin.id == id and not data.is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Je kunt je eigen admin-rechten niet intrekken",
        )

    # Find existing active super_admin role
    existing_role_result = await db.execute(
        select(PersonRole).where(
            PersonRole.person_id == id,
            PersonRole.role_id == "super_admin",
            PersonRole.eind_datum.is_(None),
        )
    )
    existing_role = existing_role_result.scalar_one_or_none()

    if data.is_admin and not existing_role:
        # Grant super_admin role
        db.add(
            PersonRole(
                person_id=id,
                role_id="super_admin",
                start_datum=date.today(),
                granted_by_id=admin.id if admin else None,
            )
        )
    elif not data.is_admin and existing_role:
        # Revoke super_admin role (close it)
        existing_role.eind_datum = date.today()

    await db.flush()
    await db.refresh(person)

    # Build response with is_admin derived from RBAC
    resp = AdminUserResponse.model_validate(person)
    resp.is_admin = data.is_admin
    return resp


# ---------------------------------------------------------------------------
# Access request endpoints
# ---------------------------------------------------------------------------


@router.get("/access-requests", response_model=list[AccessRequestResponse])
async def list_access_requests(
    admin: AdminUser,
    request_status: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> list[AccessRequestResponse]:
    """List access requests, optionally filtered by status."""
    stmt = select(AccessRequest).order_by(AccessRequest.requested_at.desc())
    if request_status:
        stmt = stmt.where(AccessRequest.status == request_status)
    result = await db.execute(stmt)
    return [AccessRequestResponse.model_validate(row) for row in result.scalars().all()]


@router.patch("/access-requests/{id}", response_model=AccessRequestResponse)
async def review_access_request(
    id: UUID,
    data: AccessRequestReviewRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> AccessRequestResponse:
    """Approve or deny an access request."""
    access_request = await db.get(AccessRequest, id)
    if access_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Toegangsverzoek niet gevonden",
        )

    if access_request.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dit verzoek is al beoordeeld",
        )

    access_request.reviewed_at = datetime.now(UTC)
    access_request.reviewed_by_id = admin.id if admin else None

    if data.action == "approve":
        access_request.status = "approved"

        # Add to whitelist
        email = normalize_email(access_request.email)
        existing = await db.execute(
            select(WhitelistEmail).where(WhitelistEmail.email == email)
        )
        if existing.scalar_one_or_none() is None:
            reviewer = admin.default_email if admin else None
            added_label = (
                f"access-request (by {reviewer})" if reviewer else "access-request"
            )
            entry = WhitelistEmail(
                email=email,
                added_by=added_label,
            )
            db.add(entry)

        await db.flush()
        await refresh_whitelist_cache(db)
    else:
        access_request.status = "denied"
        access_request.deny_reason = data.deny_reason
        await db.flush()

    await db.refresh(access_request)
    return AccessRequestResponse.model_validate(access_request)


# ---------------------------------------------------------------------------
# App configuration (LLM keys, model settings, etc.)
# ---------------------------------------------------------------------------

# Default config entries seeded on first admin visit.
_DEFAULT_CONFIG = [
    {
        "key": "ANTHROPIC_API_KEY",
        "value": "",
        "description": "Anthropic API-sleutel voor Claude (afrekening per token)",
        "is_secret": True,
    },
    {
        "key": "CLAUDE_CODE_OAUTH_TOKEN",
        "value": "",
        "description": (
            "Abonnementstoken uit `claude setup-token`. Gaat vóór op de "
            "API-sleutel: dezelfde modellen, maar op een abonnement in "
            "plaats van per token. Werkt alleen als de `claude`-binary in "
            "de image zit."
        ),
        "is_secret": True,
    },
    {
        "key": "LLM_MODEL",
        "value": "claude-haiku-4-5-20251001",
        "description": "Claude model-ID",
        "is_secret": False,
    },
    # VLAM-sleutel, model en base-URL staan bewust NIET in dit scherm: die
    # komen uit de omgeving (`zad env` voor sleutel en model, de ZAD-dienst
    # `vlam` voor het adres). Een tweede plek om ze te zetten was hier de
    # oorzaak van een storing — AppConfig gaat vóór de omgeving, dus een
    # maanden oude waarde in de database overrulede stil wat er in ZAD stond,
    # en de logs toonden een fout met het oude model terwijl het beheerscherm
    # de nieuwe waarde liet zien.
    #
    # VLAM_API_URL blijft wel beschikbaar als noodrem: klopt het adres dat
    # het platform injecteert niet, dan is VLAM zonder deze uitweg
    # onbereikbaar en is er geen weg terug via de UI.
    {
        "key": "VLAM_API_URL",
        "value": "",
        "description": (
            "VLAM-proxyadres. Leeg laten: de ZAD-dienst 'vlam' injecteert "
            "dit zelf. Alleen invullen om dat platformadres te overrulen. "
            "Sleutel en model komen uit de omgeving (zad env)."
        ),
        "is_secret": False,
    },
    {
        "key": "LLM_PROVIDER",
        "value": "claude",
        "description": "Standaard LLM-provider: 'claude' of 'vlam'",
        "is_secret": False,
    },
    # Mattermost integration
    {
        "key": "MATTERMOST_ENABLED",
        "value": "false",
        "description": "Mattermost-integratie inschakelen (true/false)",
        "is_secret": False,
    },
    {
        "key": "MATTERMOST_URL",
        "value": "",
        "description": "Mattermost server URL (bijv. https://mattermost.example.com)",
        "is_secret": False,
    },
    {
        "key": "MATTERMOST_BOT_TOKEN",
        "value": "",
        "description": "Mattermost bot access token",
        "is_secret": True,
    },
    {
        "key": "MATTERMOST_WEBHOOK_TOKEN",
        "value": "",
        "description": "Token voor slash-commando verificatie",
        "is_secret": True,
    },
    {
        "key": "MATTERMOST_NOTIFICATION_CHANNEL_ID",
        "value": "",
        "description": "Kanaal-ID voor broadcast-notificaties",
        "is_secret": False,
    },
    # FCC (Fortes Change Cloud) integration
    {
        "key": "FCC_ODATA_URL",
        "value": "",
        "description": "Fortes Change Cloud OData feed-URL",
        "is_secret": False,
    },
    {
        "key": "FCC_API_KEY",
        "value": "",
        "description": "FCC API-sleutel",
        "is_secret": True,
    },
    {
        "key": "FCC_SYNC_ENABLED",
        "value": "false",
        "description": "FCC synchronisatie aan/uit",
        "is_secret": False,
    },
    {
        "key": "FCC_PUSH_ENABLED",
        "value": "false",
        "description": "FCC push (schrijven naar FCC) aan/uit",
        "is_secret": False,
    },
    {
        "key": "FCC_USE_MOCK",
        "value": "false",
        "description": "Gebruik mock-data i.p.v. echte FCC-koppeling",
        "is_secret": False,
    },
    {
        "key": "FCC_PROJECT_ENTITY",
        "value": "Portfolio_item",
        "description": "OData entiteitnaam voor projecten in FCC",
        "is_secret": False,
    },
]


def _mask_secret(value: str) -> str:
    """Mask a secret value for display, showing only last 4 chars."""
    if not value or len(value) <= 4:
        return "****" if value else ""
    return "****" + value[-4:]


# Per-worker optimization flag. ON CONFLICT DO NOTHING ensures correctness
# even when multiple workers race to seed defaults simultaneously.
_defaults_seeded = False


async def _ensure_default_config(db: AsyncSession) -> None:
    """Create default config entries if they don't exist (runs once per worker)."""
    global _defaults_seeded  # noqa: PLW0603
    if _defaults_seeded:
        return

    from sqlalchemy.dialects.postgresql import insert

    for entry in _DEFAULT_CONFIG:
        stmt = (
            insert(AppConfig)
            .values(**entry)
            .on_conflict_do_nothing(index_elements=["key"])
        )
        await db.execute(stmt)
    await db.flush()
    _defaults_seeded = True


@router.get("/config", response_model=list[AppConfigResponse])
async def list_config(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> list[AppConfigResponse]:
    """List all configuration entries. Secret values are masked."""
    await _ensure_default_config(db)
    result = await db.execute(select(AppConfig).order_by(AppConfig.key))
    entries = []
    for row in result.scalars().all():
        resp = AppConfigResponse.model_validate(row)
        if row.is_secret:
            # Decrypt for masking (show last 4 chars of real value)
            plain = decrypt_value(row.value)
            resp.value = _mask_secret(plain)
        entries.append(resp)
    return entries


@router.patch(
    "/config/{key}",
    response_model=AppConfigResponse,
)
async def update_config(
    key: str,
    data: AppConfigUpdate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> AppConfigResponse:
    """Update a configuration value."""
    result = await db.execute(select(AppConfig).where(AppConfig.key == key))
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Configuratie '{key}' niet gevonden",
        )

    entry.value = encrypt_value(data.value) if entry.is_secret else data.value
    user_label = (admin.default_email or admin.naam) if admin else "anonymous"
    entry.updated_by = user_label
    await db.flush()
    await db.refresh(entry)

    # Clear caches so new values take effect immediately
    from bouwmeester.services.llm import clear_config_cache
    from bouwmeester.services.mattermost_service import clear_mattermost_config_cache

    clear_config_cache()
    clear_mattermost_config_cache()

    await ActivityService(db).log_event(
        "admin.config_update",
        actor_id=admin.id if admin else None,
        actor_naam=user_label,
        details={"key": key},
    )

    resp = AppConfigResponse.model_validate(entry)
    if entry.is_secret:
        resp.value = _mask_secret(decrypt_value(entry.value))
    return resp


# ---------------------------------------------------------------------------
# Database backup / restore
# ---------------------------------------------------------------------------


@router.get("/database/export")
async def export_database(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export full database as pg_dump (optionally age-encrypted)."""
    from bouwmeester.services.database_backup_service import (
        export_database as do_export,
    )

    user_label = (admin.default_email or admin.naam) if admin else "anonymous"
    logger.info("Database export requested by %s", user_label)

    try:
        file_bytes, filename = await asyncio.to_thread(do_export)
    except Exception:
        logger.exception("Database export failed (requested by %s)", user_label)
        raise HTTPException(
            status_code=500, detail="Database export mislukt. Zie server logs."
        )

    await ActivityService(db).log_event(
        "seed.database_export",
        actor_id=admin.id if admin else None,
        actor_naam=user_label,
        details={"description": "Database export uitgevoerd", "filename": filename},
    )

    logger.info(
        "Database export completed: %s (%s bytes, by %s)",
        filename,
        len(file_bytes),
        user_label,
    )
    media_type = (
        "application/octet-stream" if filename.endswith(".age") else "application/gzip"
    )
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/database/info", response_model=DatabaseBackupInfo)
async def export_database_info(
    admin: AdminUser,
) -> DatabaseBackupInfo:
    """Return metadata about the current database (revision, etc.)."""
    from bouwmeester.services.database_backup_service import _get_alembic_revision

    revision = await asyncio.to_thread(_get_alembic_revision)
    return DatabaseBackupInfo(
        exported_at=datetime.now(UTC).isoformat(),
        alembic_revision=revision,
        format_version=1,
        encrypted=bool(os.environ.get("AGE_SECRET_KEY", "")),
    )


@router.post("/database/import", response_model=DatabaseRestoreResult)
async def import_database(
    file: UploadFile,
    admin: SuperAdminUser,
    db: AsyncSession = Depends(get_db),
) -> DatabaseRestoreResult:
    """Upload a database backup and restore it."""
    from bouwmeester.services.database_backup_service import (
        import_database as do_import,
    )

    user_label = (admin.default_email or admin.naam) if admin else "anonymous"
    content = await file.read()
    if len(content) > MAX_BACKUP_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Bestand te groot (max {MAX_BACKUP_SIZE // 1024 // 1024} MB)",
        )
    logger.info(
        "Database import requested by %s (file: %s, %s bytes)",
        user_label,
        file.filename,
        len(content),
    )
    try:
        result = await asyncio.to_thread(do_import, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        logger.exception("Database import failed (requested by %s)", user_label)
        raise HTTPException(
            status_code=500, detail="Database import mislukt. Zie server logs."
        )

    # Ensure admin persons exist after import (import may have wiped them)
    admin_created = await seed_admins_from_file(db)
    if admin_created:
        logger.info("Created %d admin person stubs after import", admin_created)

    # Refresh whitelist cache — imported backup may contain different whitelist
    await refresh_whitelist_cache(db)

    # Log audit entry so the first activity record shows who imported the backup
    await ActivityService(db).log_event(
        "seed.database_import",
        actor_id=admin.id if admin else None,
        actor_naam=user_label,
        details={
            "description": "Database import uitgevoerd",
            "filename": file.filename,
            "tables_restored": result.tables_restored,
        },
    )

    logger.info(
        "Database import completed by %s: %s tables, revision %s→%s",
        user_label,
        result.tables_restored,
        result.alembic_revision_from,
        result.alembic_revision_to,
    )
    return result


# ---------------------------------------------------------------------------
# Database reset
# ---------------------------------------------------------------------------

# Tables to preserve during reset
_PRESERVED_TABLES = {
    "whitelist_email",
    "alembic_version",
    "http_sessions",
    "app_config",
}

# All model tables (order doesn't matter — TRUNCATE ... CASCADE handles FKs)
_ALL_MODEL_TABLES = [
    "access_request",
    "notification",
    "mention",
    "suggested_edge",
    "parlementair_item",
    "node_tag",
    "tag",
    "task",
    "resource_permission",
    "shared_access",
    "edge",
    "edge_type",
    "probleem",
    "effect",
    "beleidsoptie",
    "bron_bijlage",
    "bron",
    "dossier",
    "doel",
    "instrument",
    "beleidskader",
    "maatregel",
    "politieke_input",
    "corpus_node_title",
    "corpus_node_status",
    "corpus_node",
    "person_email",
    "person_phone",
    "person_organisatie_eenheid",
    "organisatie_eenheid_parent",
    "organisatie_eenheid_naam",
    "activity",
    "absence",
    "mattermost_link_code",
    "mattermost_user",
    "person",
    "organisatie_eenheid",
]


@router.post("/database/reset", response_model=DatabaseResetResult)
async def reset_database(
    data: DatabaseResetRequest,
    admin: SuperAdminUser,
    db: AsyncSession = Depends(get_db),
) -> DatabaseResetResult:
    """Wipe all data except whitelist, sessions, and alembic version.

    Re-creates admin person stubs so admins keep access after reset.
    """
    if data.confirm != "RESET":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Bevestig de reset door confirm op "RESET" te zetten.',
        )

    user_label = (admin.default_email or admin.naam) if admin else "anonymous"
    logger.warning("DATABASE RESET requested by %s", user_label)

    tables_to_clear = [t for t in _ALL_MODEL_TABLES if t not in _PRESERVED_TABLES]
    quoted = ", ".join(f'"{t}"' for t in tables_to_clear)
    await db.execute(text(f"TRUNCATE {quoted} CASCADE"))

    admin_created = await seed_admins_from_file(db)
    await refresh_whitelist_cache(db)

    # Log audit entry so the first activity record shows who reset the database
    await ActivityService(db).log_event(
        "seed.database_reset",
        actor_id=admin.id if admin else None,
        actor_naam=user_label,
        details={"description": "Database reset uitgevoerd"},
    )

    logger.warning(
        "DATABASE RESET completed by %s: %d tables cleared, %d admin stubs created",
        user_label,
        len(tables_to_clear),
        admin_created,
    )

    return DatabaseResetResult(
        success=True,
        tables_cleared=len(tables_to_clear),
        admin_persons_created=admin_created,
        message=f"Database gereset: {len(tables_to_clear)} tabellen gewist, "
        f"{admin_created} admin-accounts aangemaakt.",
    )


# ---------------------------------------------------------------------------
# Build / deploy info
# ---------------------------------------------------------------------------

# Process-level constants — these env vars are injected at Docker build time
# and never change during the container's lifetime, so we read them once.
_VERSION_INFO = {
    "git_sha": os.environ.get("GIT_SHA", ""),
    "build_time": os.environ.get("BUILD_TIME", ""),
    "repo_url": os.environ.get(
        "REPO_URL",
        "https://github.com/NederlandseDigitaleDienst/bouwmeester",
    ),
}


@router.get("/version")
async def version_info(admin: AdminUser) -> dict[str, str]:
    """Return backend git SHA, build time, and repo URL (admin only)."""
    return _VERSION_INFO


# ---------------------------------------------------------------------------
# Worker health
# ---------------------------------------------------------------------------

# Loops that tick exactly once and then stay silent by design. Their age says
# nothing about health, so age-based classification would always eventually
# call them down. `worker_singleton` ticks when the instance wins the lock and
# never again — a 15-day-old "lock verkregen" row is the healthy case.
_ONE_SHOT_LOOPS = frozenset({"worker_singleton"})

# Fallback cadence for a heartbeat row we don't recognise (a loop added
# without updating the map below). Deliberately short so it shows up.
_UNKNOWN_LOOP_CADENCE_SEC = 300.0


def _worker_expected_cadence_sec() -> dict[str, float]:
    """Per-loop expected cadence in seconds, read from the same settings the
    loops themselves sleep on.

    Hardcoding these drifted once already: the map claimed a 15-minute
    parlementair cadence while ``TK_POLL_INTERVAL_SECONDS`` defaulted to an
    hour, so a perfectly healthy loop showed up as "Vertraagd". Deriving them
    keeps the two in step. If ``last_tick_at`` is older than the cadence we
    mark the loop "stale"; older than 4× we mark it "down".
    """
    settings = get_settings()
    return {
        "parlementair": float(settings.TK_POLL_INTERVAL_SECONDS),
        # De tkconv-loop pollt sneller overdag dan 's nachts, dus de
        # verwachting is het tráágste interval: met de kantooruren-waarde
        # zou een gezonde loop elke nacht als "Vertraagd" verschijnen.
        "tkconv": float(settings.TKCONV_POLL_INTERVAL_NACHT_SECONDS),
        "mattermost_websocket": 90.0,  # idle-heartbeat is once per 60s
        "debat_tijdlijn": 90.0,  # ticks every few seconds, heartbeat once per 60s
        # The same heartbeat, but a round can take long: up to ten turns
        # per debate are each read by a model for several seconds.
        "debat_vragen": 180.0,
        "debat_aankondiging": float(settings.DEBAT_AANKONDIGING_INTERVAL_SECONDS),
        "opdracht_task": float(settings.OPDRACHT_TASK_INTERVAL_SECONDS),
        "fcc_sync": float(settings.FCC_POLL_INTERVAL_SECONDS),
        "mattermost_retry": float(settings.MATTERMOST_RETRY_INTERVAL_SECONDS),
        "overheidsorganisaties_daily": float(
            settings.OVERHEIDSORG_DAILY_INTERVAL_SECONDS
        ),
        "overheidsorganisaties_weekly": float(
            settings.OVERHEIDSORG_WEEKLY_INTERVAL_SECONDS
        ),
    }


def _expected_loops() -> list[str]:
    """Loop names we expect a heartbeat row for. If a row never appears, the
    loop never started (worker process probably crashed before
    ``await health_tick("…", "starting")``). One-shot entries are listed too
    so their absence is still visible."""
    return [*_worker_expected_cadence_sec(), *sorted(_ONE_SHOT_LOOPS)]


def _classify_health(
    status: str,
    seconds_since: float,
    expected_cadence: float,
    *,
    one_shot: bool = False,
) -> str:
    """Map (status, age) to a coarse health bucket for the UI."""
    if status == "disabled":
        return "disabled"
    if one_shot:
        # A one-shot ticks once and then stays silent by design, so its age
        # carries no signal at all — only the status does.
        return "healthy" if status == "ok" else "stale"
    # Age first: a loop that stopped ticking is "down" whatever its last
    # status said. An error tick that never refreshes means the process died
    # right after writing it, and that has to reach the red banner.
    if seconds_since > expected_cadence * 4:
        return "down"
    if status in ("error", "reconnecting"):
        return "stale"
    if seconds_since > expected_cadence:
        return "stale"
    return "healthy"


@router.get("/workers", response_model=WorkerHealthResponse)
async def workers_health(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> WorkerHealthResponse:
    """Return current heartbeat for every background worker loop.

    Surfaced in Beheer > Systeem so operators can see at a glance whether the
    worker process is alive without trailing container logs.
    """
    now = datetime.now(UTC)
    rows = (
        (await db.execute(select(WorkerHeartbeat).order_by(WorkerHeartbeat.loop_name)))
        .scalars()
        .all()
    )
    by_name = {row.loop_name: row for row in rows}
    cadences = _worker_expected_cadence_sec()

    out: list[WorkerHeartbeatResponse] = []
    for name in _expected_loops():
        one_shot = name in _ONE_SHOT_LOOPS
        cadence = cadences.get(name, _UNKNOWN_LOOP_CADENCE_SEC)
        row = by_name.get(name)
        if row is None:
            out.append(
                WorkerHeartbeatResponse(
                    loop_name=name,
                    status="never_started",
                    detail="No heartbeat row — worker process never reached this loop",
                    last_tick_at=None,
                    started_at=None,
                    seconds_since_last_tick=None,
                    health="down",
                    one_shot=one_shot,
                )
            )
            continue
        last = row.last_tick_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        seconds_since = (now - last).total_seconds()
        out.append(
            WorkerHeartbeatResponse(
                loop_name=row.loop_name,
                status=row.status,
                detail=row.detail,
                last_tick_at=last,
                started_at=row.started_at.replace(tzinfo=UTC)
                if row.started_at.tzinfo is None
                else row.started_at,
                seconds_since_last_tick=seconds_since,
                health=_classify_health(
                    row.status, seconds_since, cadence, one_shot=one_shot
                ),
                one_shot=one_shot,
            )
        )

    # Surface any unexpected loop names too — future-proofing if someone adds
    # a loop without updating the cadence map.
    known = set(_expected_loops())
    for name, row in by_name.items():
        if name in known:
            continue
        last = row.last_tick_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        seconds_since = (now - last).total_seconds()
        out.append(
            WorkerHeartbeatResponse(
                loop_name=row.loop_name,
                status=row.status,
                detail=row.detail,
                last_tick_at=last,
                started_at=row.started_at.replace(tzinfo=UTC)
                if row.started_at.tzinfo is None
                else row.started_at,
                seconds_since_last_tick=seconds_since,
                health=_classify_health(
                    row.status, seconds_since, _UNKNOWN_LOOP_CADENCE_SEC
                ),
            )
        )

    return WorkerHealthResponse(workers=out, server_now=now)


# ---------------------------------------------------------------------------
# Mattermost channel overview
# ---------------------------------------------------------------------------


@router.get("/mattermost-channels", response_model=list[MattermostChannelOverview])
async def mattermost_channel_overview(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> list[MattermostChannelOverview]:
    """Lijst alle gekoppelde Mattermost-kanalen met hun scope-label.

    Beheer > Systeem gebruikt dit om in één oogopslag te zien naar welke
    kanalen de bot meeleest en hoe lang het geleden is dat er een post is
    binnengekomen.
    """
    rows = (
        (
            await db.execute(
                select(MattermostChannelLink).order_by(
                    MattermostChannelLink.disabled_at.is_(None).desc(),
                    MattermostChannelLink.channel_display_name,
                )
            )
        )
        .scalars()
        .all()
    )

    # Bulk-resolve scope-labels in twee queries (1× per scope-type) ipv N+1.
    lead_ids = [r.scope_id for r in rows if r.scope_type == SCOPE_LEAD]
    init_ids = [r.scope_id for r in rows if r.scope_type == SCOPE_INITIATIEF]
    lead_titles: dict[UUID, str] = {}
    init_names: dict[UUID, str] = {}
    if lead_ids:
        result = await db.execute(
            select(Lead.id, Lead.title).where(Lead.id.in_(lead_ids))
        )
        lead_titles = {r.id: r.title for r in result.all()}
    if init_ids:
        result = await db.execute(
            select(Initiatief.id, Initiatief.naam).where(Initiatief.id.in_(init_ids))
        )
        init_names = {r.id: r.naam for r in result.all()}

    out: list[MattermostChannelOverview] = []
    for r in rows:
        if r.scope_type == SCOPE_LEAD:
            label = lead_titles.get(r.scope_id)
        elif r.scope_type == SCOPE_INITIATIEF:
            label = init_names.get(r.scope_id)
        else:
            label = None
        last_seen = None
        if r.last_seen_post_at is not None:
            last_seen = datetime.fromtimestamp(r.last_seen_post_at / 1000.0, tz=UTC)
        out.append(
            MattermostChannelOverview(
                id=r.id,
                channel_id=r.channel_id,
                channel_display_name=r.channel_display_name,
                channel_name=r.channel_name,
                team_id=r.team_id,
                scope_type=r.scope_type,
                scope_id=r.scope_id,
                scope_label=label,
                auto_note_enabled=r.auto_note_enabled,
                suggest_leads_enabled=r.suggest_leads_enabled,
                parlementaire_alerts_enabled=r.parlementaire_alerts_enabled,
                nieuws_alerts_enabled=r.nieuws_alerts_enabled,
                last_seen_post_at=last_seen,
                disabled_at=r.disabled_at,
                created_at=r.created_at,
            )
        )
    # Twee kanalen in verschillende teams mogen dezelfde naam dragen, en
    # dit overzicht zet ze onder elkaar. Zonder het team is niet te zien
    # welke regel over welk kanaal gaat. Dezelfde weg als de kanaalkaart.
    return await vul_teamnaam_aan(db, out)


@router.get("/mattermost-channel-rights", response_model=list[MattermostChannelRights])
async def mattermost_channel_rights(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> list[MattermostChannelRights]:
    """Per team: may the bot create a channel there?

    Creating a channel for a debate only works where the bot holds
    `create_public_channel`. Whether it does is a server setting an
    administrator can change per team, so this asks Mattermost instead of
    guessing. A 503 means the question could not be answered, which is
    something else than "no". An empty list means the bot is in no team.
    """
    service = MattermostService(db)
    try:
        if not await service.is_enabled():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Mattermost staat niet aan",
            )
        try:
            permissions = await service.team_permissions()
            # `team_namen` fails soft on a network error, but not on a
            # body that is no JSON; that is a ValueError.
            names = await service.team_namen()
        except (MattermostUnavailableError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="De rechten van de bot zijn niet op te vragen bij Mattermost",
            ) from exc
    finally:
        await service.close()

    return [
        MattermostChannelRights(
            team_id=team_id,
            team_name=names.get(team_id) or None,
            can_create_public_channel=PERMISSION_CREATE_PUBLIC_CHANNEL in granted,
            can_create_private_channel=PERMISSION_CREATE_PRIVATE_CHANNEL in granted,
        )
        for team_id, granted in sorted(permissions.items())
    ]


# ---------------------------------------------------------------------------
# Bijlagen: object storage check
# ---------------------------------------------------------------------------


@router.get("/bijlagen/opslag")
async def bijlagen_opslag(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Every file the attachment tables refer to, checked against the store."""
    from bouwmeester.core.blob_store import get_blob_store
    from bouwmeester.services.bijlagen_check import check_database_against_store

    checks = await check_database_against_store(db, get_blob_store())
    return {
        "objectopslag": get_settings().object_store_configured,
        "tabellen": [
            {
                "tabel": c.table,
                "totaal": c.total,
                "aanwezig": c.present,
                "ontbreekt": c.missing_count,
                "voorbeelden_ontbreekt": c.missing,
            }
            for c in checks
        ],
    }
