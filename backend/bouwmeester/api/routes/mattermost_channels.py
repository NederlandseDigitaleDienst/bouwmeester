"""Mattermost-kanaalkoppelingen aan initiatieven en leads.

Routes:
  GET  /api/initiatieven/{id}/mattermost-channels
  POST /api/initiatieven/{id}/mattermost-channels
  GET  /api/leads/{id}/mattermost-channels
  POST /api/leads/{id}/mattermost-channels
  GET  /api/mattermost-channels/search?q=...
  PATCH /api/mattermost-channels/{link_id}
  DELETE /api/mattermost-channels/{link_id}
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.core.auth import OptionalUser
from bouwmeester.core.database import get_db
from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    get_initiatief_context,
)
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.mattermost_channel_link import (
    SCOPE_INITIATIEF,
    SCOPE_LEAD,
    MattermostChannelLink,
)
from bouwmeester.repositories.mattermost_channel_link import (
    MattermostChannelLinkRepository,
)
from bouwmeester.schema.mattermost_channel_link import (
    MattermostChannelLinkCreate,
    MattermostChannelLinkResponse,
    MattermostChannelLinkUpdate,
    MattermostChannelSearchResult,
)
from bouwmeester.services.mattermost_service import vul_teamnaam_aan

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mattermost-channels"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Niet gevonden")


async def _resolve_initiatief(
    db: AsyncSession, initiatief_id: UUID, init_ctx: InitiatiefContext
) -> Initiatief:
    """Haal initiatief op en check toegang. 404 bij geen toegang."""
    if not init_ctx.is_admin and not init_ctx.is_authenticated:
        raise _not_found()
    if not init_ctx.is_admin and initiatief_id not in init_ctx.visible_initiatief_ids:
        raise _not_found()
    result = await db.execute(select(Initiatief).where(Initiatief.id == initiatief_id))
    initiatief = result.scalar_one_or_none()
    if initiatief is None:
        raise _not_found()
    return initiatief


async def _resolve_lead(
    db: AsyncSession, lead_id: UUID, init_ctx: InitiatiefContext
) -> Lead:
    """Haal lead op en check toegang via initiatief_id."""
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if lead is None:
        raise _not_found()
    if init_ctx.is_admin:
        return lead
    if not init_ctx.is_authenticated:
        raise _not_found()
    if (
        lead.initiatief_id is not None
        and lead.initiatief_id not in init_ctx.visible_initiatief_ids
    ):
        raise _not_found()
    return lead


async def _can_manage_link(
    db: AsyncSession,
    link: MattermostChannelLink,
    init_ctx: InitiatiefContext,
) -> bool:
    """Mag de huidige user deze koppeling beheren?

    Voor initiatief-scope: kanaal-koppeling beheren = het initiatief mogen
    zien (zelfde drempel als de UI-detailpagina).

    Voor lead-scope: laad de Lead en delegeer naar dezelfde regel als
    ``_resolve_lead`` — een lead met initiatief is alleen beheerbaar door
    iemand die dat initiatief mag zien; zonder initiatief is hij voor alle
    authenticated users toegankelijk (migratiepad).
    """
    if init_ctx.is_admin:
        return True
    if not init_ctx.is_authenticated:
        return False
    if link.scope_type == SCOPE_INITIATIEF:
        return link.scope_id in init_ctx.visible_initiatief_ids
    if link.scope_type == SCOPE_LEAD:
        lead = (
            await db.execute(select(Lead).where(Lead.id == link.scope_id))
        ).scalar_one_or_none()
        if lead is None:
            return False
        # TODO(post-migratie): drop deze tak zodra alle leads een
        # ``initiatief_id`` hebben. Tijdens de migratieperiode is een lead
        # zonder initiatief voor elke authenticated user toegankelijk; dat
        # spiegelt ``_check_lead_access`` in ``leads.py``.
        if lead.initiatief_id is None:
            return True
        return lead.initiatief_id in init_ctx.visible_initiatief_ids
    return False


# ---------------------------------------------------------------------------
# Initiatief-scope endpoints
# ---------------------------------------------------------------------------


async def _met_teamnaam(db, links: list) -> list[MattermostChannelLinkResponse]:
    """Vul de teamnaam aan, zodat twee gelijknamige kanalen te scheiden zijn.

    De invulling zelf staat in `vul_teamnaam_aan`, want het beheeroverzicht
    toont dezelfde kanalen met een eigen antwoordmodel en hoort niet een
    tweede keer op te halen waarom de naam niet opgeslagen wordt.
    """
    antwoorden = [MattermostChannelLinkResponse.model_validate(x) for x in links]
    return await vul_teamnaam_aan(db, antwoorden)


@router.get(
    "/initiatieven/{initiatief_id}/mattermost-channels",
    response_model=list[MattermostChannelLinkResponse],
)
async def list_initiatief_channels(
    initiatief_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[MattermostChannelLinkResponse]:
    await _resolve_initiatief(db, initiatief_id, init_ctx)
    repo = MattermostChannelLinkRepository(db)
    links = await repo.list_for_scope(SCOPE_INITIATIEF, initiatief_id)
    return await _met_teamnaam(db, links)


@router.post(
    "/initiatieven/{initiatief_id}/mattermost-channels",
    response_model=MattermostChannelLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_initiatief_channel(
    initiatief_id: UUID,
    data: MattermostChannelLinkCreate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> MattermostChannelLinkResponse:
    await _resolve_initiatief(db, initiatief_id, init_ctx)
    repo = MattermostChannelLinkRepository(db)
    existing = await repo.get_by_channel_id(data.channel_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dit kanaal is al gekoppeld",
        )
    try:
        link = await repo.create(
            channel_id=data.channel_id,
            channel_name=data.channel_name,
            channel_display_name=data.channel_display_name,
            team_id=data.team_id,
            scope_type=SCOPE_INITIATIEF,
            scope_id=initiatief_id,
            auto_note_enabled=data.auto_note_enabled
            if data.auto_note_enabled is not None
            else False,
            suggest_leads_enabled=data.suggest_leads_enabled
            if data.suggest_leads_enabled is not None
            else True,
            # Standaard uit: een kanaal dat voor leads wordt gekoppeld
            # hoort niet ongevraagd elk kamerstuk te krijgen. Aanzetten
            # gebeurt bewust, met het vinkje in het beheerpaneel.
            parlementaire_alerts_enabled=data.parlementaire_alerts_enabled
            if data.parlementaire_alerts_enabled is not None
            else False,
            # Idem voor de vakpers, en apart aan te zetten: dat zijn
            # andere stukken voor een ander gesprek.
            nieuws_alerts_enabled=data.nieuws_alerts_enabled
            if data.nieuws_alerts_enabled is not None
            else False,
            created_by_id=current_user.id if current_user else None,
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dit kanaal is al gekoppeld",
        )
    return MattermostChannelLinkResponse.model_validate(link)


# ---------------------------------------------------------------------------
# Lead-scope endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/leads/{lead_id}/mattermost-channels",
    response_model=list[MattermostChannelLinkResponse],
)
async def list_lead_channels(
    lead_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[MattermostChannelLinkResponse]:
    await _resolve_lead(db, lead_id, init_ctx)
    repo = MattermostChannelLinkRepository(db)
    links = await repo.list_for_scope(SCOPE_LEAD, lead_id)
    return await _met_teamnaam(db, links)


@router.post(
    "/leads/{lead_id}/mattermost-channels",
    response_model=MattermostChannelLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_lead_channel(
    lead_id: UUID,
    data: MattermostChannelLinkCreate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> MattermostChannelLinkResponse:
    await _resolve_lead(db, lead_id, init_ctx)
    repo = MattermostChannelLinkRepository(db)
    existing = await repo.get_by_channel_id(data.channel_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dit kanaal is al gekoppeld",
        )
    try:
        link = await repo.create(
            channel_id=data.channel_id,
            channel_name=data.channel_name,
            channel_display_name=data.channel_display_name,
            team_id=data.team_id,
            scope_type=SCOPE_LEAD,
            scope_id=lead_id,
            auto_note_enabled=data.auto_note_enabled
            if data.auto_note_enabled is not None
            else True,
            suggest_leads_enabled=data.suggest_leads_enabled
            if data.suggest_leads_enabled is not None
            else False,
            created_by_id=current_user.id if current_user else None,
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dit kanaal is al gekoppeld",
        )
    return MattermostChannelLinkResponse.model_validate(link)


# ---------------------------------------------------------------------------
# Cross-cutting endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/mattermost-channels/search",
    response_model=list[MattermostChannelSearchResult],
)
async def search_channels(
    current_user: OptionalUser,
    q: str = Query(..., min_length=2, max_length=64),
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[MattermostChannelSearchResult]:
    """Zoek MM-kanalen via de bot. Vereist authenticated user."""
    if not init_ctx.is_authenticated and not init_ctx.is_admin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    from bouwmeester.services.mattermost_service import MattermostService

    service = MattermostService(db)
    if not await service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mattermost is niet geconfigureerd",
        )
    results = await service.search_channels(q)
    return [MattermostChannelSearchResult.model_validate(r) for r in results]


@router.patch(
    "/mattermost-channels/{link_id}",
    response_model=MattermostChannelLinkResponse,
)
async def update_channel_link(
    link_id: UUID,
    data: MattermostChannelLinkUpdate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> MattermostChannelLinkResponse:
    repo = MattermostChannelLinkRepository(db)
    link = await repo.get(link_id)
    if link is None:
        raise _not_found()
    if not await _can_manage_link(db, link, init_ctx):
        raise _not_found()

    # Reenable mag alleen als de bot daadwerkelijk weer in het kanaal zit
    # — anders zet je `disabled_at=None` op een dode koppeling en raakt de
    # UI uit sync met Mattermost.
    if data.reenable:
        from bouwmeester.services.mattermost_service import (
            MattermostService,
            MattermostUnavailableError,
        )

        service = MattermostService(db)
        try:
            if not await service.is_enabled():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Mattermost is niet geconfigureerd",
                )
            try:
                is_member = await service.is_bot_member_of_channel(link.channel_id)
            except MattermostUnavailableError:
                # Tijdelijke MM-storing — niet interpreteren als "geen lid".
                # 503 zodat de UI de gebruiker kan vragen het later te
                # proberen, in plaats van ten onrechte 409 te tonen.
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(
                        "Mattermost is tijdelijk niet bereikbaar. "
                        "Probeer het zo opnieuw."
                    ),
                )
            if not is_member:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Bot is geen lid van dit kanaal. "
                        "Voeg de bot eerst toe in Mattermost en probeer opnieuw."
                    ),
                )
        finally:
            await service.close()

    updated = await repo.update_settings(
        link,
        auto_note_enabled=data.auto_note_enabled,
        suggest_leads_enabled=data.suggest_leads_enabled,
        parlementaire_alerts_enabled=data.parlementaire_alerts_enabled,
        nieuws_alerts_enabled=data.nieuws_alerts_enabled,
        reenable=data.reenable,
    )
    return MattermostChannelLinkResponse.model_validate(updated)


@router.delete(
    "/mattermost-channels/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_channel_link(
    link_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> None:
    repo = MattermostChannelLinkRepository(db)
    link = await repo.get(link_id)
    if link is None:
        raise _not_found()
    if not await _can_manage_link(db, link, init_ctx):
        raise _not_found()
    await repo.delete(link)
