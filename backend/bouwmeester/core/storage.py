"""Shared file-storage utilities for bijlagen (attachments)."""

from __future__ import annotations

import logging
import os
import shutil
import uuid as _uuid
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import Response

if TYPE_CHECKING:
    from fastapi import UploadFile

logger = logging.getLogger(__name__)


def data_root() -> Path:
    """Return the writable runtime data directory.

    Resolution order:
    1. ``DATA_PATH`` env var (explicit override)
    2. ``/data`` (container default — made group-writable for arbitrary
       UIDs in the Dockerfile, unlike the read-only ``/app`` code tree)

    Used for generated runtime state that must survive process restarts
    but cannot be written into the immutable image layer.
    """
    data_path = os.environ.get("DATA_PATH")
    if data_path:
        return Path(data_path)
    return Path("/data")


def kabinet_yaml_path() -> Path:
    """Return the writable path for the scraped ``kabinet.yaml``.

    The worker scrapes rijksoverheid.nl and overwrites this file daily, so
    it cannot live in the read-only ``/app`` code tree (the deployed
    container runs as an arbitrary, non-owning UID and gets ``EACCES`` on
    write — see ``backend/bouwmeester/data/kabinet.yaml`` shipped only as a
    seed). On first run we copy the in-image seed into the writable data
    dir so ``write_kabinet_yaml``'s "0 entries → keep existing YAML"
    data-loss guard still has a baseline to fall back to.
    """
    target = data_root() / "kabinet.yaml"
    if not target.exists():
        seed = Path(__file__).resolve().parent.parent / "data" / "kabinet.yaml"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if seed.exists():
                shutil.copyfile(seed, target)
        except OSError:
            logger.warning(
                "Kon kabinet.yaml-seed niet naar %s kopiëren; scrape begint "
                "zonder baseline",
                target,
            )
    return target


def bijlagen_root() -> Path:
    """Return the root directory for bijlagen storage.

    Resolution order:
    1. ``BIJLAGEN_ROOT`` env var (explicit override)
    2. ``DATA_PATH`` env var + ``/bijlagen``
    3. ``/data/bijlagen`` (container default)
    """
    explicit = os.environ.get("BIJLAGEN_ROOT")
    if explicit:
        return Path(explicit)
    data_path = os.environ.get("DATA_PATH")
    if data_path:
        return Path(data_path) / "bijlagen"
    return Path("/data/bijlagen")


# Magic-byte signatures for content-type verification.
_MAGIC_SIGNATURES: dict[bytes, set[str]] = {
    b"%PDF": {"application/pdf"},
    b"PK": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.oasis.opendocument.text",
    },
    b"\xd0\xcf\x11\xe0": {"application/msword"},
    b"\x89PNG": {"image/png"},
    b"\xff\xd8\xff": {"image/jpeg"},
    b"GIF87a": {"image/gif"},
    b"GIF89a": {"image/gif"},
    b"RIFF": {"image/webp"},  # WebP starts with RIFF....WEBP
}


# Broad allowlist for chat and lead attachments.
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "text/plain",
    "text/csv",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "application/zip",
}

# Stricter allowlist for bron (document) attachments - no animated images.
BRON_ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.oasis.opendocument.text",
    "text/plain",
    "image/png",
    "image/jpeg",
}

MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB


def verify_content_type(
    content: bytes, claimed: str, *, signatuur_verplicht: bool = False
) -> bool:
    """Check that *content* magic bytes are consistent with *claimed* MIME type.

    Returns ``True`` when the content matches (or for ``text/plain`` where
    magic-byte detection is unreliable).  Returns ``False`` when a magic
    signature is found that contradicts the claimed type.

    With ``signatuur_verplicht`` the content must start with a signature of
    the claimed type: content without a known signature fails, and so does
    a type without one. For files that go outside (the onderzoeksverslag on
    the public page), where "unknown passes" is too loose.
    """
    if signatuur_verplicht:
        return any(
            content[: len(sig)] == sig and claimed in allowed_types
            for sig, allowed_types in _MAGIC_SIGNATURES.items()
        )

    if claimed == "text/plain":
        return True

    for sig, allowed_types in _MAGIC_SIGNATURES.items():
        if content[: len(sig)] == sig:
            return claimed in allowed_types
    # No matching signature found — allow (defensive; unknown formats pass)
    return True


def validate_upload(
    content: bytes,
    content_type: str,
    allowed: set[str] | None = None,
    *,
    signatuur_verplicht: bool = False,
) -> None:
    """Validate content type against allowlist and magic bytes.

    Raises ``HTTPException`` with 400 status on validation failure.
    Uses *allowed* if given, otherwise falls back to ``ALLOWED_CONTENT_TYPES``.
    ``signatuur_verplicht``: see ``verify_content_type``.
    """
    if content_type not in (allowed or ALLOWED_CONTENT_TYPES):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Ongeldig bestandstype: {content_type}. "
                "Toegestaan: PDF, Word, ODT, TXT, PNG, JPEG, GIF, WebP."
            ),
        )
    if not verify_content_type(
        content, content_type, signatuur_verplicht=signatuur_verplicht
    ):
        raise HTTPException(
            status_code=400,
            detail="Bestandsinhoud komt niet overeen met het opgegeven bestandstype.",
        )


def sanitize_download_filename(name: str) -> str:
    """Strip characters that could cause header injection in Content-Disposition."""
    return name.replace('"', "").replace("\r", "").replace("\n", "")


async def store_upload(
    content: bytes,
    filename: str,
    *,
    prefix: str = "",
    item_id: _uuid.UUID | str | None = None,
    content_type: str | None = None,
) -> tuple[str, str]:
    """Store an uploaded file in the bijlagen store and return ``(name, pad)``.

    The object lands at ``<prefix>/<item_id>/<uuid>_<name>``. The returned
    ``pad`` leaves out *prefix*, because that is how each table has always
    stored it: relative to the root for bron, to ``chat/`` for chat. Leads
    keep the ``leads/`` in their column, so their callers add it back.

    Raises ``HTTPException(500)`` when the store refuses the write.
    """
    from bouwmeester.core.blob_store import get_blob_store

    safe_basename = Path(filename).name or "bijlage"
    safe_name = f"{_uuid.uuid4().hex}_{safe_basename}"
    pad = f"{item_id}/{safe_name}" if item_id is not None else safe_name
    key = f"{prefix}/{pad}" if prefix else pad
    try:
        await get_blob_store().put(key, content, content_type)
    except Exception:
        logger.exception("Failed to store upload %s", key)
        raise HTTPException(status_code=500, detail="Kan bestand niet opslaan.")
    return safe_basename, pad


def chat_key(pad: str) -> str:
    """The store key for a chat attachment, whose ``pad`` is relative to ``chat/``."""
    return f"chat/{pad}"


async def blob_available(key: str) -> bool:
    """Whether the file behind *key* exists. False for an invalid key too."""
    from bouwmeester.core.blob_store import InvalidKeyError, get_blob_store

    try:
        return await get_blob_store().size(key) is not None
    except InvalidKeyError:
        return False


async def read_blob(key: str) -> bytes | None:
    """The file behind *key*, or ``None`` when it is missing or the key is invalid."""
    from bouwmeester.core.blob_store import InvalidKeyError, get_blob_store

    try:
        return await get_blob_store().get(key)
    except InvalidKeyError:
        return None


async def delete_blob(key: str) -> None:
    """Remove the file behind *key*. Never raises: the DB row is already gone,
    and a file left behind is a smaller problem than a failed request."""
    from bouwmeester.core.blob_store import get_blob_store

    try:
        await get_blob_store().delete(key)
    except Exception:
        logger.warning("Kon bijlage %s niet verwijderen", key, exc_info=True)


async def blob_download(key: str, filename: str, media_type: str) -> Response:
    """A download response for the file behind *key*.

    Same headers as the ``FileResponse`` it replaces: the file is offered as
    an attachment under its original name, UTF-8 encoded when it needs to be.
    """
    from bouwmeester.core.blob_store import InvalidKeyError, get_blob_store

    try:
        data = await get_blob_store().get(key)
    except InvalidKeyError:
        raise HTTPException(status_code=400, detail="Ongeldig pad")
    if data is None:
        raise HTTPException(status_code=404, detail="Bestand niet gevonden")

    safe = sanitize_download_filename(filename)
    quoted = quote(safe)
    if quoted != safe:
        disposition = f"attachment; filename*=utf-8''{quoted}"
    else:
        disposition = f'attachment; filename="{safe}"'
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


async def read_upload_content(file: UploadFile, max_size: int | None = None) -> bytes:
    """Read an upload file in chunks, enforcing a size limit.

    Raises ``HTTPException`` with 400 status if the file exceeds *max_size*.
    Defaults to ``MAX_UPLOAD_SIZE`` when *max_size* is ``None``.
    """
    if max_size is None:
        max_size = MAX_UPLOAD_SIZE
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(8192):
        total += len(chunk)
        if total > max_size:
            max_mb = max_size // (1024 * 1024)
            raise HTTPException(
                status_code=400,
                detail=f"Bestand te groot. Maximum is {max_mb} MB.",
            )
        chunks.append(chunk)
    return b"".join(chunks)
