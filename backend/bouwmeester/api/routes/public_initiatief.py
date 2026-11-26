"""Public (unauthenticated) endpoints for an initiatief community page.

Elke tekst gaat hier door `verwijzingen_als_tekst`: een @- of #-verwijzing
uit de editor zet anders een naam en een intern id op de pagina. Nieuwe
publieke tekst weigert zo'n verwijzing al bij het schrijven; dit vangt wat
van daarvoor is, en de beschrijving van het initiatief, die voor binnen
geschreven wordt.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bouwmeester.core.database import get_db
from bouwmeester.core.storage import blob_download
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.initiatief_update import InitiatiefUpdatePost
from bouwmeester.models.issue import Issue
from bouwmeester.models.lead import Lead
from bouwmeester.models.lead_column import LeadColumn
from bouwmeester.models.lead_update import LeadUpdatePost
from bouwmeester.schema.initiatief_update import (
    InitiatiefUpdatePostPublicResponse,
    PubliekeCasusBuiten,
    PubliekeVraagBuiten,
)
from bouwmeester.schema.lead_update import LeadUpdatePostPublicResponse
from bouwmeester.schema.publieke_tekst import verwijzingen_als_tekst as _tekst
from bouwmeester.services.publieke_casussen import (
    als_casus_buiten,
    is_casus_buiten_bij,
    laatste_fase,
    vrijgegeven_casussen,
)
from bouwmeester.services.publieke_vragen import (
    als_vraag_buiten,
    is_buiten_bij,
    publiek_verslag_bestand,
    vrijgegeven_vragen,
)

router = APIRouter(prefix="/public/initiatieven", tags=["public-initiatief"])


class PublicCasus(BaseModel):
    """Lead-derived public summary; only fields the eigenaar wrote for outside."""

    titel: str
    samenvatting: str | None = None
    updates: list[LeadUpdatePostPublicResponse] = []


class PublicInitiatiefResponse(BaseModel):
    naam: str
    slug: str
    beschrijving: str | None = None
    kleur: str | None = None
    updates: list[InitiatiefUpdatePostPublicResponse] = []
    casussen: list[PublicCasus] = []
    # Beantwoorde onderzoeksvragen: alleen de vrijgegeven publieke tekst,
    # nooit de casus waar ze bij horen.
    beantwoorde_vragen: list[PubliekeVraagBuiten] = []
    # Afgeronde casussen met hun lessen: alleen de tekst die het team voor
    # buiten schreef en vrijgaf.
    afgeronde_casussen: list[PubliekeCasusBuiten] = []

    model_config = ConfigDict(from_attributes=True)


@router.get("/by-slug/{slug}", response_model=PublicInitiatiefResponse)
async def get_public_initiatief(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> PublicInitiatiefResponse:
    """Naam, beschrijving en kleur, de gepubliceerde updates, de lopende
    casussen van leads die daarvoor zijn opengezet, en de beantwoorde vragen
    en afgeronde casussen die iemand vrijgaf.

    Returns 404 (not 403) when slug is unknown OR public_page_enabled is
    false. Hiding existence on disabled pages is intentional — leaks no
    information about which initiatieven exist internally.

    Two-step query keeps timing roughly constant between "slug doesn't
    exist" and "exists but private": both bail before any relation loads.
    """
    lookup = await db.execute(select(Initiatief).where(Initiatief.slug == slug))
    initiatief = lookup.scalar_one_or_none()
    if initiatief is None or not initiatief.public_page_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pagina niet gevonden"
        )

    detail = await db.execute(
        select(Initiatief)
        .where(Initiatief.id == initiatief.id)
        .options(
            selectinload(Initiatief.updates).selectinload(
                InitiatiefUpdatePost.published_by
            ),
            selectinload(Initiatief.updates)
            .selectinload(InitiatiefUpdatePost.vragen)
            .selectinload(Issue.casus),
            selectinload(Initiatief.updates)
            .selectinload(InitiatiefUpdatePost.vragen)
            .selectinload(Issue.verslag),
            selectinload(Initiatief.updates).selectinload(
                InitiatiefUpdatePost.casussen
            ),
        )
    )
    initiatief = detail.scalar_one()

    laatste = laatste_fase(initiatief)
    published_updates = sorted(
        (u for u in initiatief.updates if u.published_at is not None),
        key=lambda u: u.published_at,
        reverse=True,
    )

    # Lopende casussen: leads waar de eigenaar/contributor expliciet een
    # publieks-titel heeft geschreven, de toggle aan zette, en de stage
    # behoort tot een kolom die per-initiatief als publiek-zichtbaar is
    # gemarkeerd (LeadColumn.is_public_visible).
    public_slugs_subq = select(LeadColumn.slug).where(
        LeadColumn.initiatief_id == initiatief.id,
        LeadColumn.is_public_visible.is_(True),
    )
    leads_result = await db.execute(
        select(Lead)
        .where(
            Lead.initiatief_id == initiatief.id,
            Lead.public_visible.is_(True),
            Lead.public_title.is_not(None),
            Lead.stage.in_(public_slugs_subq),
        )
        .options(selectinload(Lead.updates).selectinload(LeadUpdatePost.published_by))
        .order_by(Lead.created_at.desc())
    )
    casussen: list[PublicCasus] = []
    for lead in leads_result.scalars().all():
        published = sorted(
            (u for u in lead.updates if u.published_at is not None and u.body_public),
            key=lambda u: u.published_at,
            reverse=True,
        )
        casussen.append(
            PublicCasus(
                titel=_tekst(lead.public_title) or "",
                samenvatting=_tekst(lead.public_summary),
                updates=[
                    LeadUpdatePostPublicResponse(
                        titel=_tekst(u.titel) or "",
                        body_public=_tekst(u.body_public),
                        published_at=u.published_at,
                        published_by_naam=(
                            u.published_by.naam if u.published_by else None
                        ),
                    )
                    for u in published
                ],
            )
        )

    return PublicInitiatiefResponse(
        naam=initiatief.naam,
        slug=initiatief.slug or "",
        beschrijving=_tekst(initiatief.beschrijving),
        kleur=initiatief.kleur,
        updates=[
            InitiatiefUpdatePostPublicResponse(
                titel=_tekst(u.titel) or "",
                body=_tekst(u.body),
                published_at=u.published_at,
                published_by_naam=(u.published_by.naam if u.published_by else None),
                vragen=[
                    als_vraag_buiten(v)
                    for v in u.vragen
                    if is_buiten_bij(v, initiatief.id)
                ],
                casussen=[
                    als_casus_buiten(c)
                    for c in u.casussen
                    if is_casus_buiten_bij(c, initiatief.id, laatste)
                ],
            )
            for u in published_updates
        ],
        casussen=casussen,
        beantwoorde_vragen=[
            als_vraag_buiten(v) for v in await vrijgegeven_vragen(db, initiatief.id)
        ],
        afgeronde_casussen=[
            als_casus_buiten(c) for c in await vrijgegeven_casussen(db, initiatief)
        ],
    )


@router.get("/by-slug/{slug}/verslagen/{verslag_id}")
async def download_publiek_verslag(
    slug: str,
    verslag_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Een onderzoeksverslag van de publieke pagina, als download.

    Alleen als de pagina aan staat, iemand akkoord gaf voor het verslag en
    de vraag zelf naar buiten mag. In alle andere gevallen dezelfde 404,
    zoals bij de pagina zelf. Altijd als bijlage, nooit in de browser
    geopend (nosniff zet de middleware).
    """
    lookup = await db.execute(select(Initiatief).where(Initiatief.slug == slug))
    initiatief = lookup.scalar_one_or_none()
    if initiatief is None or not initiatief.public_page_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pagina niet gevonden"
        )
    verslag = await publiek_verslag_bestand(db, initiatief.id, verslag_id)
    if verslag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verslag niet gevonden"
        )
    return await blob_download(verslag.pad, verslag.bestandsnaam, verslag.content_type)
