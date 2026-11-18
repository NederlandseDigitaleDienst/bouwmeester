"""Mattermost-kanaalkoppelingen aan initiatieven, leads en casussen.

Routes:
  GET  /api/initiatieven/{id}/mattermost-channels
  POST /api/initiatieven/{id}/mattermost-channels
  GET  /api/leads/{id}/mattermost-channels
  POST /api/leads/{id}/mattermost-channels
  GET  /api/casussen/{id}/mattermost-channels
  POST /api/casussen/{id}/mattermost-channels
  GET  /api/casussen/{id}/kanaalberichten
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

from bouwmeester.api.routes.leads import _require_lead_open
from bouwmeester.core.auth import OptionalUser
from bouwmeester.core.authority import require_can_change_casus
from bouwmeester.core.database import get_db
from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    get_initiatief_context,
    require_initiatief_visible,
)
from bouwmeester.core.permissions import PermissionContext, get_permission_context
from bouwmeester.models.casus import Casus
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.mattermost_channel_link import (
    SCOPE_CASUS,
    SCOPE_INITIATIEF,
    SCOPE_LEAD,
    MattermostChannelLink,
)
from bouwmeester.repositories.mattermost_channel_link import (
    MattermostChannelLinkRepository,
)
from bouwmeester.schema.mattermost_channel_link import (
    CasusKanaalberichtResponse,
    MattermostChannelLinkCreate,
    MattermostChannelLinkResponse,
    MattermostChannelLinkUpdate,
    MattermostChannelSearchResult,
)
from bouwmeester.services.activity_service import log_activity
from bouwmeester.services.casus_kanaal_service import berichten_van_casus
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


async def _resolve_casus(
    db: AsyncSession, casus_id: UUID, init_ctx: InitiatiefContext
) -> Casus:
    """Haal de casus op, met de toegangsregel van de casus zelf (404)."""
    casus = await db.get(Casus, casus_id)
    if casus is None:
        raise _not_found()
    require_initiatief_visible(casus.initiatief_id, init_ctx)
    return casus


async def _mag_casuskanaal_beheren(
    db: AsyncSession,
    casus: Casus,
    current_user: OptionalUser,
    perm_ctx: PermissionContext,
) -> None:
    """403 voor wie in het initiatief alleen kijkt.

    Een kanaal aan een casus stuurt casusinhoud naar Mattermost. Dat valt
    onder het wijzigen van de casus: een bijdrager of eigenaar van het
    initiatief, of de trekker. Zien mag iedereen die het initiatief ziet;
    dat regelt `_resolve_casus` al, met 404 erbuiten.
    """
    await require_can_change_casus(db, perm_ctx, current_user, casus)


async def _privekanaal(db: AsyncSession, channel_id: str) -> dict:
    """Het kanaal zoals Mattermost het kent, als het een privékanaal is.

    Alleen een privékanaal krijgt de voortgang van een casus: daar kom je
    alleen in als iemand je uitnodigt, dus de inhoud komt niet bij wie
    toevallig in een open kanaal zit. De bot moet erin zitten, en de naam
    komt uit Mattermost, niet uit het verzoek.
    """
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
        kanaal = await service.get_channel(channel_id)
        if not kanaal or kanaal.get("delete_at"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dit kanaal is niet te vinden in Mattermost",
            )
        if kanaal.get("type") != "P":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Alleen een privékanaal kan de voortgang van een casus krijgen",
            )
        try:
            bot_erin = await service.is_bot_member_of_channel(channel_id)
        except MattermostUnavailableError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Mattermost is tijdelijk niet bereikbaar. Probeer het zo opnieuw."
                ),
            )
        if not bot_erin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "De bot zit niet in dit kanaal. Voeg hem eerst toe in Mattermost."
                ),
            )
        return kanaal
    finally:
        await service.close()


async def _log_casuskanaal(
    db: AsyncSession, current_user: OptionalUser, soort: str, link
) -> None:
    """Koppelen, voortgang aan of uit en ontkoppelen in het activiteitenlog."""
    await log_activity(
        db,
        current_user,
        None,
        soort,
        details={
            "casus_id": str(link.scope_id),
            "channel_id": link.channel_id,
            "kanaal": link.channel_display_name,
            "voortgang": link.casus_updates_enabled,
        },
    )


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
    if link.scope_type == SCOPE_CASUS:
        casus = await db.get(Casus, link.scope_id)
        if casus is None:
            return False
        return (
            casus.initiatief_id is None
            or casus.initiatief_id in init_ctx.visible_initiatief_ids
        )
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
    lead = await _resolve_lead(db, lead_id, init_ctx)
    # Een lead met een casus is alleen-lezen, en zijn kanaal is meegegaan
    # naar de casus. Een nieuw kanaal hoort dan ook bij de casus.
    await _require_lead_open(db, lead)
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
# Casus-scope endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/casussen/{casus_id}/mattermost-channels",
    response_model=list[MattermostChannelLinkResponse],
)
async def list_casus_channels(
    casus_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[MattermostChannelLinkResponse]:
    await _resolve_casus(db, casus_id, init_ctx)
    repo = MattermostChannelLinkRepository(db)
    links = await repo.list_for_scope(SCOPE_CASUS, casus_id)
    return await _met_teamnaam(db, links)


@router.post(
    "/casussen/{casus_id}/mattermost-channels",
    response_model=MattermostChannelLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_casus_channel(
    casus_id: UUID,
    data: MattermostChannelLinkCreate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> MattermostChannelLinkResponse:
    """Koppel een privékanaal aan een casus; daar komt de voortgang in.

    Een casus leest niet mee: geen notities, geen lead-suggesties en geen
    alerts, die horen bij een lead of initiatief.
    """
    casus = await _resolve_casus(db, casus_id, init_ctx)
    await _mag_casuskanaal_beheren(db, casus, current_user, perm_ctx)
    repo = MattermostChannelLinkRepository(db)
    existing = await repo.get_by_channel_id(data.channel_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dit kanaal is al gekoppeld",
        )
    kanaal = await _privekanaal(db, data.channel_id)
    naam = kanaal.get("name") or data.channel_name
    try:
        link = await repo.create(
            channel_id=data.channel_id,
            channel_name=naam,
            channel_display_name=kanaal.get("display_name") or naam,
            team_id=kanaal.get("team_id") or None,
            scope_type=SCOPE_CASUS,
            scope_id=casus_id,
            auto_note_enabled=False,
            suggest_leads_enabled=False,
            casus_updates_enabled=data.casus_updates_enabled
            if data.casus_updates_enabled is not None
            else True,
            created_by_id=current_user.id if current_user else None,
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dit kanaal is al gekoppeld",
        )
    # Wie casusinhoud naar welk kanaal stuurt, moet terug te vinden zijn.
    await _log_casuskanaal(db, current_user, "casus.kanaal_gekoppeld", link)
    return MattermostChannelLinkResponse.model_validate(link)


@router.get(
    "/casussen/{casus_id}/kanaalberichten",
    response_model=list[CasusKanaalberichtResponse],
)
async def list_casus_kanaalberichten(
    casus_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[CasusKanaalberichtResponse]:
    """Wat Bouwmeester over deze casus in het kanaal zette, nieuwste eerst.

    Ook de berichten die alleen hier staan, omdat er geen kanaal was of
    Mattermost uit stond.
    """
    await _resolve_casus(db, casus_id, init_ctx)
    berichten = await berichten_van_casus(db, casus_id)
    return [CasusKanaalberichtResponse.model_validate(b) for b in berichten]


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
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> MattermostChannelLinkResponse:
    repo = MattermostChannelLinkRepository(db)
    link = await repo.get(link_id)
    if link is None:
        raise _not_found()
    if not await _can_manage_link(db, link, init_ctx):
        raise _not_found()

    # Alleen de schakelaars die bij deze soort kanaal horen. Een casus leest
    # niet mee; een vlag die hier blijft hangen, gaat anders mee terug naar
    # de lead als de casus verdwijnt en zet daar meelezen aan.
    meelezen = (
        data.auto_note_enabled,
        data.suggest_leads_enabled,
        data.parlementaire_alerts_enabled,
        data.nieuws_alerts_enabled,
    )
    if link.scope_type == SCOPE_CASUS:
        if any(v is not None for v in meelezen):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Een kanaal aan een casus leest niet mee",
            )
        casus = await db.get(Casus, link.scope_id)
        if casus is not None:
            await _mag_casuskanaal_beheren(db, casus, current_user, perm_ctx)
        # Voortgang aan kan alleen in een privékanaal. Een kanaal dat van
        # de lead is meegekomen, kan open zijn.
        if data.casus_updates_enabled:
            await _privekanaal(db, link.channel_id)
    elif data.casus_updates_enabled is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Voortgang hoort alleen bij een kanaal aan een casus",
        )

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
        casus_updates_enabled=data.casus_updates_enabled,
        reenable=data.reenable,
    )
    if link.scope_type == SCOPE_CASUS and data.casus_updates_enabled is not None:
        await _log_casuskanaal(db, current_user, "casus.kanaal_voortgang", updated)
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
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> None:
    repo = MattermostChannelLinkRepository(db)
    link = await repo.get(link_id)
    if link is None:
        raise _not_found()
    if not await _can_manage_link(db, link, init_ctx):
        raise _not_found()
    if link.scope_type == SCOPE_CASUS:
        casus = await db.get(Casus, link.scope_id)
        if casus is not None:
            await _mag_casuskanaal_beheren(db, casus, current_user, perm_ctx)
        await _log_casuskanaal(db, current_user, "casus.kanaal_ontkoppeld", link)
    await repo.delete(link)
