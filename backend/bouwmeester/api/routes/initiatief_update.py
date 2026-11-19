"""API routes for InitiatiefUpdatePost (publication posts on an initiatief).

Een update kan beantwoorde onderzoeksvragen (`vraag_ids`) en afgeronde
casussen met hun lessen (`casus_ids`) meenemen: alleen wat vrijgegeven is
voor buiten, zie services/publieke_vragen.py en publieke_casussen.py. De tab
Updates begint bij `klaar-om-te-delen`: alles wat afgerond is, binnen en
buiten.
Een gepubliceerde update is ook als mailbrief te downloaden: een .eml die
Outlook opent als concept, zonder ontvangers. Bouwmeester verstuurt zelf
niets en bewaart geen adressen.
"""

import html
from datetime import UTC, datetime
from urllib.parse import quote, urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bouwmeester.api.deps import require_found
from bouwmeester.api.routes.initiatief import _require_access
from bouwmeester.core.auth import OptionalUser
from bouwmeester.core.config import get_settings
from bouwmeester.core.database import get_db
from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    get_initiatief_context,
    require_initiatief_visible,
)
from bouwmeester.core.permissions import (
    PermissionContext,
    get_permission_context,
)
from bouwmeester.models.casus import Casus
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.initiatief_update import (
    InitiatiefUpdateCasus,
    InitiatiefUpdatePost,
    InitiatiefUpdateVraag,
)
from bouwmeester.models.issue import Issue
from bouwmeester.repositories.initiatief import InitiatiefRepository
from bouwmeester.schema.initiatief_update import (
    InitiatiefUpdatePostCreate,
    InitiatiefUpdatePostEdit,
    InitiatiefUpdatePostResponse,
    KlaarCasus,
    KlaarOmTeDelen,
    KlaarVraag,
    VrijgegevenVraag,
)
from bouwmeester.services.eml_builder import build_outlook_draft_eml
from bouwmeester.services.markdown_min import markdown_to_html
from bouwmeester.services.publieke_casussen import (
    als_publieke_casus,
    casussen_voor_update,
    is_casus_buiten_bij,
    laatste_fase,
)
from bouwmeester.services.publieke_vragen import (
    als_publieke_vraag,
    is_buiten_bij,
    vragen_voor_update,
    vrijgegeven_vragen,
)

router = APIRouter(prefix="/initiatieven", tags=["initiatief-updates"])


def _to_response(post: InitiatiefUpdatePost) -> InitiatiefUpdatePostResponse:
    return InitiatiefUpdatePostResponse(
        id=post.id,
        initiatief_id=post.initiatief_id,
        titel=post.titel,
        body=post.body,
        published_at=post.published_at,
        published_by_id=post.published_by_id,
        published_by_naam=(post.published_by.naam if post.published_by else None),
        vragen=[
            als_publieke_vraag(v)
            for v in post.vragen
            if is_buiten_bij(v, post.initiatief_id)
        ],
        casussen=[als_publieke_casus(c) for c in _casussen_buiten(post)],
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


def _casussen_buiten(post: InitiatiefUpdatePost) -> list[Casus]:
    """De gekoppelde casussen die nu naar buiten mogen. Vraagt een geladen
    `post.initiatief` (voor de laatste fase) en `post.casussen`."""
    laatste = laatste_fase(post.initiatief)
    return [
        c for c in post.casussen if is_casus_buiten_bij(c, post.initiatief_id, laatste)
    ]


def _met_relaties(stmt):
    return stmt.options(
        selectinload(InitiatiefUpdatePost.published_by),
        selectinload(InitiatiefUpdatePost.initiatief),
        selectinload(InitiatiefUpdatePost.casussen),
        selectinload(InitiatiefUpdatePost.vragen).selectinload(Issue.casus),
        selectinload(InitiatiefUpdatePost.vragen).selectinload(Issue.verslag),
    )


async def _load_post(
    db: AsyncSession, initiatief_id: UUID, post_id: UUID
) -> InitiatiefUpdatePost | None:
    stmt = _met_relaties(
        select(InitiatiefUpdatePost).where(
            InitiatiefUpdatePost.id == post_id,
            InitiatiefUpdatePost.initiatief_id == initiatief_id,
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _herlaad(
    db: AsyncSession, post: InitiatiefUpdatePost
) -> InitiatiefUpdatePostResponse:
    """Antwoord met verse relaties, ook na een wijziging in deze request."""
    await db.flush()
    # Eerst de sleutels pakken: na expire zou elk attribuut een lazy load
    # zijn, en dat kan niet in een async sessie.
    initiatief_id, post_id = post.initiatief_id, post.id
    db.expire(post)
    fresh = await _load_post(db, initiatief_id, post_id)
    return _to_response(require_found(fresh, "Update"))


@router.get(
    "/{initiatief_id}/updates",
    response_model=list[InitiatiefUpdatePostResponse],
)
async def list_updates(
    initiatief_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> list[InitiatiefUpdatePostResponse]:
    """All updates (drafts + published) for members; viewers see same."""
    repo = InitiatiefRepository(db)
    require_found(await repo.get_by_id(initiatief_id), "Initiatief")
    await _require_access(repo, initiatief_id, current_user, perm_ctx, "viewer")

    stmt = _met_relaties(
        select(InitiatiefUpdatePost)
        .where(InitiatiefUpdatePost.initiatief_id == initiatief_id)
        .order_by(InitiatiefUpdatePost.created_at.desc())
    )
    result = await db.execute(stmt)
    return [_to_response(p) for p in result.scalars().all()]


@router.get(
    "/{initiatief_id}/vrijgegeven-vragen",
    response_model=list[VrijgegevenVraag],
)
async def list_vrijgegeven_vragen(
    initiatief_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> list[VrijgegevenVraag]:
    """De beantwoorde vragen die een update kan meenemen, nieuwste eerst.

    Alleen de publieke tekst, nooit de casus: wie de updates ziet, hoeft de
    casussen niet te kunnen zien. `in_gepubliceerde_update` zegt of de vraag
    al in een gepubliceerde update stond.
    """
    repo = InitiatiefRepository(db)
    require_found(await repo.get_by_id(initiatief_id), "Initiatief")
    await _require_access(repo, initiatief_id, current_user, perm_ctx, "viewer")

    vragen = await vrijgegeven_vragen(db, initiatief_id)
    al_gemeld = await _al_gemeld(db, initiatief_id, InitiatiefUpdateVraag.issue_id)
    return [
        VrijgegevenVraag(
            **als_publieke_vraag(v).model_dump(),
            in_gepubliceerde_update=v.id in al_gemeld,
        )
        for v in vragen
    ]


async def _al_gemeld(db: AsyncSession, initiatief_id: UUID, kolom) -> set[UUID]:
    """De vragen of casussen die al in een gepubliceerde update stonden.

    `kolom` is InitiatiefUpdateVraag.issue_id of InitiatiefUpdateCasus.casus_id.
    """
    koppel = kolom.class_
    stmt = (
        select(kolom)
        .join(InitiatiefUpdatePost, InitiatiefUpdatePost.id == koppel.update_id)
        .where(
            InitiatiefUpdatePost.initiatief_id == initiatief_id,
            InitiatiefUpdatePost.published_at.is_not(None),
        )
    )
    return set((await db.execute(stmt)).scalars().all())


@router.get("/{initiatief_id}/klaar-om-te-delen", response_model=KlaarOmTeDelen)
async def klaar_om_te_delen(
    initiatief_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> KlaarOmTeDelen:
    """Waar een update op voortbouwt: afgeronde onderzoeksvragen en afgeronde
    casussen met hun lessen, met per stuk wat al naar buiten mag.

    Bevat interne titels en lessen, dus alleen voor wie de casussen van het
    initiatief ziet (dezelfde regel als de backlog).
    """
    require_initiatief_visible(
        initiatief_id, init_ctx, detail="Initiatief niet gevonden"
    )
    initiatief = require_found(
        await InitiatiefRepository(db).get_by_id(initiatief_id), "Initiatief"
    )

    vraag_rijen = (
        await db.execute(
            select(Issue, Casus.title)
            .outerjoin(Casus, Casus.id == Issue.casus_id)
            .where(
                Issue.initiatief_id == initiatief_id,
                Issue.is_onderzoeksvraag.is_(True),
                Issue.status == "done",
            )
            .options(selectinload(Issue.verslag))
            .order_by(Issue.updated_at.desc().nulls_last(), Issue.created_at.desc())
        )
    ).all()
    gemelde_vragen = await _al_gemeld(db, initiatief_id, InitiatiefUpdateVraag.issue_id)

    laatste = laatste_fase(initiatief)
    casussen = (
        (
            await db.execute(
                select(Casus)
                .where(
                    Casus.initiatief_id == initiatief_id,
                    Casus.fase == (laatste or ""),
                )
                .order_by(Casus.updated_at.desc().nulls_last(), Casus.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    gemelde_casussen = await _al_gemeld(
        db, initiatief_id, InitiatiefUpdateCasus.casus_id
    )

    return KlaarOmTeDelen(
        vragen=[
            KlaarVraag(
                id=v.id,
                casus_id=v.casus_id,
                casus_titel=casus_titel,
                titel=v.title,
                public_title=v.public_title,
                public_answer=v.public_answer,
                published_at=v.published_at,
                in_gepubliceerde_update=v.id in gemelde_vragen,
                verslag_openbaar=(
                    v.verslag is not None and v.verslag.openbaar_op is not None
                ),
            )
            for v, casus_titel in vraag_rijen
        ],
        casussen=[
            KlaarCasus(
                id=c.id,
                titel=c.title,
                lessen=c.lessen,
                public_title=c.public_title,
                public_resultaat=c.public_resultaat,
                public_lessen=c.public_lessen,
                published_at=c.published_at,
                in_gepubliceerde_update=c.id in gemelde_casussen,
                afgerond_op=c.updated_at,
            )
            for c in casussen
        ],
    )


@router.post(
    "/{initiatief_id}/updates",
    response_model=InitiatiefUpdatePostResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_update(
    initiatief_id: UUID,
    data: InitiatiefUpdatePostCreate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> InitiatiefUpdatePostResponse:
    repo = InitiatiefRepository(db)
    initiatief = require_found(await repo.get_by_id(initiatief_id), "Initiatief")
    await _require_access(repo, initiatief_id, current_user, perm_ctx, "contributor")

    vragen = await vragen_voor_update(db, initiatief_id, data.vraag_ids)
    casussen = await casussen_voor_update(db, initiatief, data.casus_ids)
    post = InitiatiefUpdatePost(
        initiatief_id=initiatief_id,
        titel=data.titel,
        body=data.body,
        vragen=vragen,
        casussen=casussen,
    )
    if data.publish:
        post.published_at = datetime.now(UTC)
        post.published_by_id = current_user.id if current_user else None

    db.add(post)
    return await _herlaad(db, post)


@router.put(
    "/{initiatief_id}/updates/{post_id}",
    response_model=InitiatiefUpdatePostResponse,
)
async def edit_update(
    initiatief_id: UUID,
    post_id: UUID,
    data: InitiatiefUpdatePostEdit,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> InitiatiefUpdatePostResponse:
    repo = InitiatiefRepository(db)
    await _require_access(repo, initiatief_id, current_user, perm_ctx, "contributor")
    post = require_found(await _load_post(db, initiatief_id, post_id), "Update")
    payload = data.model_dump(exclude_unset=True, exclude={"vraag_ids", "casus_ids"})
    for key, value in payload.items():
        setattr(post, key, value)
    if data.vraag_ids is not None:
        post.vragen = await vragen_voor_update(db, initiatief_id, data.vraag_ids)
    if data.casus_ids is not None:
        post.casussen = await casussen_voor_update(db, post.initiatief, data.casus_ids)
    return await _herlaad(db, post)


@router.post(
    "/{initiatief_id}/updates/{post_id}/publish",
    response_model=InitiatiefUpdatePostResponse,
)
async def publish_update(
    initiatief_id: UUID,
    post_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> InitiatiefUpdatePostResponse:
    repo = InitiatiefRepository(db)
    await _require_access(repo, initiatief_id, current_user, perm_ctx, "contributor")
    post = require_found(await _load_post(db, initiatief_id, post_id), "Update")
    post.published_at = datetime.now(UTC)
    post.published_by_id = current_user.id if current_user else None
    return await _herlaad(db, post)


@router.post(
    "/{initiatief_id}/updates/{post_id}/unpublish",
    response_model=InitiatiefUpdatePostResponse,
)
async def unpublish_update(
    initiatief_id: UUID,
    post_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> InitiatiefUpdatePostResponse:
    repo = InitiatiefRepository(db)
    await _require_access(repo, initiatief_id, current_user, perm_ctx, "contributor")
    post = require_found(await _load_post(db, initiatief_id, post_id), "Update")
    # Keep published_by_id as audit trail of last publisher; republishing
    # overwrites it again.
    post.published_at = None
    return await _herlaad(db, post)


@router.delete(
    "/{initiatief_id}/updates/{post_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_update(
    initiatief_id: UUID,
    post_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> None:
    repo = InitiatiefRepository(db)
    await _require_access(repo, initiatief_id, current_user, perm_ctx, "contributor")
    post = await _load_post(db, initiatief_id, post_id)
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Update niet gevonden"
        )
    await db.delete(post)
    await db.flush()


# ---------------------------------------------------------------------------
# Mailbrief: .eml die Outlook opent als concept
# ---------------------------------------------------------------------------


def _publieke_link(initiatief: Initiatief) -> str | None:
    """De publieke pagina, als die aan staat en de frontend-URL klopt."""
    if not initiatief.public_page_enabled or not initiatief.slug:
        return None
    base = get_settings().FRONTEND_URL.rstrip("/")
    if urlparse(base).scheme not in ("http", "https"):
        return None
    return f"{base}/c/{quote(initiatief.slug)}"


def _mailbrief_html(
    initiatief: Initiatief, post: InitiatiefUpdatePost, link: str | None
) -> str:
    """De mailbrief: de update, de beantwoorde vragen en de link naar buiten.

    Alle tekst gaat door html.escape (de body via markdown_to_html, dat ook
    escapet): wat iemand typt, wordt nooit opmaak of een link in de mail.
    """
    delen = [f"<h2>{html.escape(post.titel)}</h2>"]
    if post.body:
        delen.append(markdown_to_html(post.body))
    vragen = [v for v in post.vragen if is_buiten_bij(v, post.initiatief_id)]
    if vragen:
        delen.append("<h3>Beantwoorde onderzoeksvragen</h3>")
        for v in vragen:
            delen.append(f"<p><strong>{html.escape(v.public_title or '')}</strong></p>")
            delen.append(markdown_to_html(v.public_answer or ""))
            if v.verslag is not None and v.verslag.openbaar_op is not None and link:
                delen.append(
                    "<p>Het onderzoeksverslag staat op de publieke pagina.</p>"
                )
    casussen = _casussen_buiten(post)
    if casussen:
        delen.append("<h3>Afgeronde casussen</h3>")
        for c in casussen:
            delen.append(f"<p><strong>{html.escape(c.public_title or '')}</strong></p>")
            delen.append(markdown_to_html(c.public_resultaat or ""))
            if c.public_lessen:
                delen.append("<p><em>Wat we leerden</em></p>")
                delen.append(markdown_to_html(c.public_lessen))
    if link:
        safe = html.escape(link, quote=True)
        delen.append(
            f"<p>Alle updates van {html.escape(initiatief.naam)} staan op "
            f'<a href="{safe}">{safe}</a>.</p>'
        )
    return "\n".join(delen)


def _mailbrief_tekst(
    initiatief: Initiatief, post: InitiatiefUpdatePost, link: str | None
) -> str:
    regels = [post.titel, ""]
    if post.body:
        regels += [post.body.strip(), ""]
    vragen = [v for v in post.vragen if is_buiten_bij(v, post.initiatief_id)]
    if vragen:
        regels += ["Beantwoorde onderzoeksvragen", ""]
        for v in vragen:
            regels += [v.public_title or "", v.public_answer or ""]
            if v.verslag is not None and v.verslag.openbaar_op is not None and link:
                regels.append("Het onderzoeksverslag staat op de publieke pagina.")
            regels.append("")
    casussen = _casussen_buiten(post)
    if casussen:
        regels += ["Afgeronde casussen", ""]
        for c in casussen:
            regels += [c.public_title or "", c.public_resultaat or ""]
            if c.public_lessen:
                regels += ["Wat we leerden:", c.public_lessen]
            regels.append("")
    if link:
        regels.append(f"Alle updates van {initiatief.naam} staan op {link}")
    return "\n".join(regels).strip() + "\n"


@router.get("/{initiatief_id}/updates/{post_id}/eml")
async def download_mailbrief(
    initiatief_id: UUID,
    post_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
) -> Response:
    """De gepubliceerde update als mailbrief, een concept voor Outlook.

    Zonder ontvangers: wie verstuurt, zet zelf de adressen erin (in BCC).
    Alleen voor een gepubliceerde update, want de mail wijst naar de
    publieke pagina en mag niets bevatten wat daar niet staat.
    """
    repo = InitiatiefRepository(db)
    initiatief = require_found(await repo.get_by_id(initiatief_id), "Initiatief")
    await _require_access(repo, initiatief_id, current_user, perm_ctx, "contributor")
    post = require_found(await _load_post(db, initiatief_id, post_id), "Update")
    if post.published_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Publiceer de update eerst, dan kan hij als mailbrief",
        )

    link = _publieke_link(initiatief)
    eml_bytes = build_outlook_draft_eml(
        # Eén regel: een regeleinde in een kop laat de mailbibliotheek
        # weigeren (geen header-injectie, wel een 500).
        subject=" ".join(f"{initiatief.naam}: {post.titel}".split()),
        to=[],
        body_html=_mailbrief_html(initiatief, post, link),
        body_text=_mailbrief_tekst(initiatief, post, link),
    )
    # Alleen ASCII in de bestandsnaam, zoals bij de mail van een lead-update.
    safe_title = "".join(
        c if (c.isascii() and (c.isalnum() or c in "-_")) else "-"
        for c in (post.titel or "update")
    )[:60]
    return Response(
        content=eml_bytes,
        media_type="message/rfc822",
        headers={
            "Content-Disposition": f'attachment; filename="mailbrief-{safe_title}.eml"'
        },
    )
