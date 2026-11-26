"""API routes voor het onderzoeksverslag bij een onderzoeksvraag.

Eén verslag per vraag, als bestand. Zelfde toegang als de vraag: wie de casus
(of bij een vraag zonder casus het initiatief) ziet, ziet en downloadt het
verslag; uploaden, vervangen en weghalen vraagt
dezelfde rol als de casus wijzigen. Openbaar maken vraagt een bijdrager of
eigenaar van het initiatief, net als een vraag vrijgeven, en een expliciet
akkoord. Een nieuw bestand vervangt het oude en zet het akkoord terug: dat
gold voor het oude bestand. Intrekken of heropenen van de vraag zet het
akkoord ook terug (repositories/issue.py): het gold voor de vraag buiten.
De inhoud moet beginnen met de signatuur van zijn type (PDF, Word, ODT).

Op de publieke pagina staat een openbaar verslag pas als de vraag zelf naar
buiten mag; zie services/publieke_vragen.py en de publieke downloadroute in
public_initiatief.py.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bouwmeester.api.routes.issues import (
    PlekDep,
    casus_plek,
    initiatief_plek,
    issue_in_plek,
    plek_details,
)
from bouwmeester.core.auth import OptionalUser
from bouwmeester.core.authority import (
    require_can_change_casus,
    require_can_publish_issue,
)
from bouwmeester.core.database import get_db
from bouwmeester.core.permissions import PermissionContext, get_permission_context
from bouwmeester.core.storage import (
    blob_download,
    delete_blob,
    read_upload_content,
    store_upload,
    validate_upload,
)
from bouwmeester.core.werkplek import Werkplek
from bouwmeester.models.onderzoeksverslag import Onderzoeksverslag
from bouwmeester.repositories.issue import IssueRepository
from bouwmeester.schema.onderzoeksverslag import (
    OnderzoeksverslagResponse,
    OpenbaarAkkoord,
)
from bouwmeester.services.activity_service import log_activity

# Een verslag is een document: PDF, Word of ODT. Geen afbeeldingen, geen
# tekst of zip: wat naar buiten kan, moet een lezer zonder risico openen.
VERSLAG_CONTENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.oasis.opendocument.text",
}


def _response(v: Onderzoeksverslag) -> OnderzoeksverslagResponse:
    return OnderzoeksverslagResponse(
        id=v.id,
        bestandsnaam=v.bestandsnaam,
        content_type=v.content_type,
        bestandsgrootte=v.bestandsgrootte,
        uploaded_by_naam=v.uploaded_by.naam if v.uploaded_by else None,
        created_at=v.created_at,
        updated_at=v.updated_at,
        openbaar_op=v.openbaar_op,
        openbaar_door_naam=v.openbaar_door.naam if v.openbaar_door else None,
    )


async def _laad(db: AsyncSession, issue_id: UUID) -> Onderzoeksverslag | None:
    stmt = (
        select(Onderzoeksverslag)
        .where(Onderzoeksverslag.issue_id == issue_id)
        .options(
            selectinload(Onderzoeksverslag.uploaded_by),
            selectinload(Onderzoeksverslag.openbaar_door),
        )
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _verplicht(db: AsyncSession, issue_id: UUID) -> Onderzoeksverslag:
    verslag = await _laad(db, issue_id)
    if verslag is None:
        raise HTTPException(status_code=404, detail="Geen onderzoeksverslag")
    return verslag


def _details(plek, issue, verslag: Onderzoeksverslag | None = None) -> dict:
    details = {
        **plek_details(plek),
        "issue_id": str(issue.id),
        "title": issue.title,
    }
    if verslag is not None:
        details["filename"] = verslag.bestandsnaam
    return details


def maak_router(prefix: str, plek_dep: PlekDep) -> APIRouter:
    """De verslagroutes onder de vraag, met de plek uit `plek_dep`."""
    router = APIRouter(prefix=prefix, tags=["onderzoeksverslag"])

    @router.get("", response_model=OnderzoeksverslagResponse | None)
    async def get_verslag(
        issue_id: UUID,
        current_user: OptionalUser,
        plek: Werkplek = Depends(plek_dep),
        db: AsyncSession = Depends(get_db),
    ) -> OnderzoeksverslagResponse | None:
        """Het verslag van deze vraag, of niets als er nog geen is."""
        await issue_in_plek(IssueRepository(db), plek, issue_id)
        verslag = await _laad(db, issue_id)
        return _response(verslag) if verslag else None

    @router.post("", response_model=OnderzoeksverslagResponse)
    async def upload_verslag(
        issue_id: UUID,
        file: UploadFile,
        current_user: OptionalUser,
        plek: Werkplek = Depends(plek_dep),
        db: AsyncSession = Depends(get_db),
        perm_ctx: PermissionContext = Depends(get_permission_context),
    ) -> OnderzoeksverslagResponse:
        """Upload het verslag, of vervang het bestaande.

        Vervangen zet het akkoord om naar buiten te gaan terug: dat gold voor het
        vorige bestand.
        """
        casus = plek
        await require_can_change_casus(db, perm_ctx, current_user, casus)
        issue = await issue_in_plek(IssueRepository(db), plek, issue_id)
        if not issue.is_onderzoeksvraag:
            raise HTTPException(
                status_code=400,
                detail="Een onderzoeksverslag hoort bij een onderzoeksvraag",
            )
        content_type = file.content_type or "application/octet-stream"
        if content_type not in VERSLAG_CONTENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail="Een onderzoeksverslag is een PDF-, Word- of ODT-bestand",
            )
        content = await read_upload_content(file)
        # Het verslag kan naar buiten: de inhoud moet beginnen zoals een
        # bestand van dit type begint, "onbekend" is niet genoeg.
        validate_upload(
            content,
            content_type,
            allowed=VERSLAG_CONTENT_TYPES,
            signatuur_verplicht=True,
        )
        naam, pad = await store_upload(
            content,
            file.filename or "onderzoeksverslag",
            prefix="verslagen",
            item_id=issue_id,
            content_type=content_type,
        )

        verslag = await _laad(db, issue_id)
        oud_pad = verslag.pad if verslag else None
        if verslag is None:
            verslag = Onderzoeksverslag(issue_id=issue_id)
            db.add(verslag)
        verslag.bestandsnaam = naam
        verslag.content_type = content_type
        verslag.bestandsgrootte = len(content)
        verslag.pad = f"verslagen/{pad}"
        verslag.uploaded_by_id = current_user.id if current_user else None
        verslag.openbaar_op = None
        verslag.openbaar_door_id = None
        await db.flush()
        verslag = await _verplicht(db, issue_id)
        await log_activity(
            db,
            current_user,
            None,
            "onderzoeksverslag.replaced" if oud_pad else "onderzoeksverslag.uploaded",
            details=_details(casus, issue, verslag),
        )
        antwoord = _response(verslag)
        if oud_pad:
            # Eerst vastleggen, dan het oude bestand weg: mislukt de commit,
            # dan wijst de rij niet naar een verdwenen bestand.
            await db.commit()
            await delete_blob(oud_pad)
        return antwoord

    @router.delete("", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_verslag(
        issue_id: UUID,
        current_user: OptionalUser,
        plek: Werkplek = Depends(plek_dep),
        db: AsyncSession = Depends(get_db),
        perm_ctx: PermissionContext = Depends(get_permission_context),
    ) -> None:
        """Haal het verslag weg, ook van de publieke pagina."""
        casus = plek
        await require_can_change_casus(db, perm_ctx, current_user, casus)
        issue = await issue_in_plek(IssueRepository(db), plek, issue_id)
        verslag = await _verplicht(db, issue_id)
        pad = verslag.pad
        details = _details(casus, issue, verslag)
        await db.delete(verslag)
        await db.flush()
        await log_activity(
            db, current_user, None, "onderzoeksverslag.deleted", details=details
        )
        # Eerst vastleggen, dan het bestand weg.
        await db.commit()
        await delete_blob(pad)

    @router.get("/download")
    async def download_verslag(
        issue_id: UUID,
        current_user: OptionalUser,
        plek: Werkplek = Depends(plek_dep),
        db: AsyncSession = Depends(get_db),
    ) -> Response:
        await issue_in_plek(IssueRepository(db), plek, issue_id)
        verslag = await _verplicht(db, issue_id)
        return await blob_download(
            verslag.pad, verslag.bestandsnaam, verslag.content_type
        )

    @router.put("/openbaar", response_model=OnderzoeksverslagResponse)
    async def maak_openbaar(
        issue_id: UUID,
        data: OpenbaarAkkoord,
        current_user: OptionalUser,
        plek: Werkplek = Depends(plek_dep),
        db: AsyncSession = Depends(get_db),
        perm_ctx: PermissionContext = Depends(get_permission_context),
    ) -> OnderzoeksverslagResponse:
        """Akkoord om het verslag naar buiten te brengen.

        Op de publieke pagina staat het pas als de vraag ook vrijgegeven is.
        """
        casus = plek
        await require_can_publish_issue(db, perm_ctx, current_user, casus)
        issue = await issue_in_plek(IssueRepository(db), plek, issue_id)
        verslag = await _verplicht(db, issue_id)
        if verslag.openbaar_op is None:
            verslag.openbaar_op = datetime.now(UTC)
            verslag.openbaar_door_id = current_user.id if current_user else None
            await db.flush()
            await log_activity(
                db,
                current_user,
                None,
                "onderzoeksverslag.openbaar",
                details=_details(casus, issue, verslag),
            )
        return _response(await _verplicht(db, issue_id))

    @router.delete("/openbaar", response_model=OnderzoeksverslagResponse)
    async def trek_openbaar_in(
        issue_id: UUID,
        current_user: OptionalUser,
        plek: Werkplek = Depends(plek_dep),
        db: AsyncSession = Depends(get_db),
        perm_ctx: PermissionContext = Depends(get_permission_context),
    ) -> OnderzoeksverslagResponse:
        """Het verslag gaat terug naar binnen; het bestand blijft staan."""
        casus = plek
        await require_can_change_casus(db, perm_ctx, current_user, casus)
        issue = await issue_in_plek(IssueRepository(db), plek, issue_id)
        verslag = await _verplicht(db, issue_id)
        if verslag.openbaar_op is not None:
            verslag.openbaar_op = None
            verslag.openbaar_door_id = None
            await db.flush()
            await log_activity(
                db,
                current_user,
                None,
                "onderzoeksverslag.niet_openbaar",
                details=_details(casus, issue, verslag),
            )
        return _response(await _verplicht(db, issue_id))

    return router


router = maak_router("/casussen/{casus_id}/issues/{issue_id}/verslag", casus_plek)
initiatief_router = maak_router(
    "/initiatieven/{initiatief_id}/vragen/{issue_id}/verslag", initiatief_plek
)
