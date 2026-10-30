"""API routes voor opmerkingen en bijlagen op een taak.

Eigen router naast tasks.py, zodat het taakdetail (opmerkingen, bijlagen)
los staat van de taak zelf. Toegang: wie de taak mag zien, mag meepraten en
bijlagen toevoegen. Een casustaak is zo zichtbaar als haar casus (404
buiten een zichtbaar initiatief); een node-taak volgt de org-scope.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bouwmeester.api.deps import validate_list
from bouwmeester.core.auth import OptionalUser
from bouwmeester.core.database import get_db
from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    get_initiatief_context,
    require_initiatief_visible,
)
from bouwmeester.core.org_context import (
    OrgContext,
    check_resource_org_scope,
    get_org_context,
)
from bouwmeester.core.permissions import PermissionContext, get_permission_context
from bouwmeester.core.storage import (
    blob_download,
    delete_blob,
    read_upload_content,
    store_upload,
    validate_upload,
)
from bouwmeester.models.casus import Casus
from bouwmeester.models.task import Task
from bouwmeester.models.task_attachment import TaskAttachment
from bouwmeester.models.task_comment import TaskComment
from bouwmeester.schema.notification import NotificationCreate
from bouwmeester.schema.task_comment import (
    TaskAttachmentResponse,
    TaskCommentCreate,
    TaskCommentResponse,
)
from bouwmeester.services.activity_service import log_activity
from bouwmeester.services.mention_helper import sync_and_notify_mentions
from bouwmeester.services.notification_service import NotificationService

router = APIRouter(prefix="/tasks/{task_id}", tags=["task-comments"])


async def _get_visible_task(
    db: AsyncSession,
    task_id: UUID,
    org_ctx: OrgContext,
    init_ctx: InitiatiefContext,
    perm_ctx: PermissionContext,
) -> Task:
    """De taak, als de aanvrager hem mag zien.

    Een casustaak volgt de casus: zichtbaar voor wie het initiatief ziet,
    anders 404 (zoals issues en stories; geen rol vereist). Een node-taak
    volgt de gewone regel: task:read plus de org-scope.
    """
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Taak niet gevonden")
    if task.casus_id is not None:
        casus = await db.get(Casus, task.casus_id)
        require_initiatief_visible(
            casus.initiatief_id if casus else None,
            init_ctx,
            detail="Taak niet gevonden",
        )
        return task
    if not perm_ctx.has_permission("task:read"):
        raise HTTPException(status_code=403, detail="Onvoldoende rechten")
    await check_resource_org_scope(db, "task", task_id, org_ctx)
    return task


# ---------------------------------------------------------------------------
# Opmerkingen
# ---------------------------------------------------------------------------


@router.get("/comments", response_model=list[TaskCommentResponse])
async def list_comments(
    task_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
    org_ctx: OrgContext = Depends(get_org_context),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[TaskCommentResponse]:
    """Opmerkingen op een taak, oudste eerst: zo lees je het gesprek."""
    await _get_visible_task(db, task_id, org_ctx, init_ctx, perm_ctx)
    stmt = (
        select(TaskComment)
        .where(TaskComment.task_id == task_id)
        .options(selectinload(TaskComment.author))
        .order_by(TaskComment.created_at.asc())
    )
    return validate_list(
        TaskCommentResponse, list((await db.execute(stmt)).scalars().all())
    )


@router.post(
    "/comments",
    response_model=TaskCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_comment(
    task_id: UUID,
    data: TaskCommentCreate,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
    org_ctx: OrgContext = Depends(get_org_context),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> TaskCommentResponse:
    """Plaats een opmerking. De toegewezene krijgt een melding, genoemden ook."""
    task = await _get_visible_task(db, task_id, org_ctx, init_ctx, perm_ctx)
    author_id = current_user.id if current_user else None
    comment = TaskComment(task_id=task_id, author_id=author_id, content=data.content)
    db.add(comment)
    await db.flush()
    await db.refresh(comment, attribute_names=["author", "created_at"])

    if task.assignee_id and task.assignee_id != author_id:
        await NotificationService(db).send(
            NotificationCreate(
                person_id=task.assignee_id,
                type="task_comment_added",
                title=f"Nieuwe opmerking op taak '{task.title}'",
                message=f"Nieuwe opmerking op taak '{task.title}'",
                sender_id=author_id,
                related_task_id=task.id,
            )
        )
    await sync_and_notify_mentions(
        db,
        "task_comment",
        comment.id,
        data.content,
        f"taak '{task.title}'",
        sender_id=author_id,
        source_task_id=task.id,
        exclude_person_id=task.assignee_id,
    )
    await log_activity(
        db,
        current_user,
        None,
        "task_comment.added",
        details={"task_id": str(task_id), "task_title": task.title},
    )
    return TaskCommentResponse.model_validate(comment)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    task_id: UUID,
    comment_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
    org_ctx: OrgContext = Depends(get_org_context),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> None:
    """Alleen de auteur of een beheerder verwijdert een opmerking."""
    task = await _get_visible_task(db, task_id, org_ctx, init_ctx, perm_ctx)
    comment = await db.get(TaskComment, comment_id)
    if comment is None or comment.task_id != task_id:
        raise HTTPException(status_code=404, detail="Opmerking niet gevonden")
    actor_id = current_user.id if current_user else None
    if not init_ctx.is_admin and (actor_id is None or comment.author_id != actor_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Alleen de auteur of een beheerder kan deze opmerking verwijderen",
        )
    await db.delete(comment)
    await log_activity(
        db,
        current_user,
        None,
        "task_comment.deleted",
        details={"task_id": str(task_id), "task_title": task.title},
    )


# ---------------------------------------------------------------------------
# Bijlagen
# ---------------------------------------------------------------------------


@router.get("/attachments", response_model=list[TaskAttachmentResponse])
async def list_attachments(
    task_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
    org_ctx: OrgContext = Depends(get_org_context),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> list[TaskAttachmentResponse]:
    await _get_visible_task(db, task_id, org_ctx, init_ctx, perm_ctx)
    stmt = (
        select(TaskAttachment)
        .where(TaskAttachment.task_id == task_id)
        .order_by(TaskAttachment.created_at.asc())
    )
    return validate_list(
        TaskAttachmentResponse, list((await db.execute(stmt)).scalars().all())
    )


@router.post(
    "/attachments",
    response_model=TaskAttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    task_id: UUID,
    file: UploadFile,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
    org_ctx: OrgContext = Depends(get_org_context),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> TaskAttachmentResponse:
    """Upload een bijlage; dezelfde controles op inhoud als bij een lead."""
    task = await _get_visible_task(db, task_id, org_ctx, init_ctx, perm_ctx)
    content_type = file.content_type or "application/octet-stream"
    content = await read_upload_content(file)
    validate_upload(content, content_type)
    filename, relative_path = await store_upload(
        content,
        file.filename or "bijlage",
        prefix="taken",
        item_id=task_id,
        content_type=content_type,
    )
    attachment = TaskAttachment(
        task_id=task_id,
        bestandsnaam=filename,
        content_type=content_type,
        bestandsgrootte=len(content),
        pad=f"taken/{relative_path}",
    )
    db.add(attachment)
    await db.flush()
    await db.refresh(attachment)
    await log_activity(
        db,
        current_user,
        None,
        "task_attachment.uploaded",
        details={
            "task_id": str(task_id),
            "task_title": task.title,
            "filename": filename,
        },
    )
    return TaskAttachmentResponse.model_validate(attachment)


async def _get_attachment(
    db: AsyncSession, task_id: UUID, attachment_id: UUID
) -> TaskAttachment:
    attachment = await db.get(TaskAttachment, attachment_id)
    if attachment is None or attachment.task_id != task_id:
        raise HTTPException(status_code=404, detail="Bijlage niet gevonden")
    return attachment


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(
    task_id: UUID,
    attachment_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
    org_ctx: OrgContext = Depends(get_org_context),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> Response:
    await _get_visible_task(db, task_id, org_ctx, init_ctx, perm_ctx)
    attachment = await _get_attachment(db, task_id, attachment_id)
    return await blob_download(
        attachment.pad,
        attachment.bestandsnaam,
        attachment.content_type or "application/octet-stream",
    )


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    task_id: UUID,
    attachment_id: UUID,
    current_user: OptionalUser,
    db: AsyncSession = Depends(get_db),
    perm_ctx: PermissionContext = Depends(get_permission_context),
    org_ctx: OrgContext = Depends(get_org_context),
    init_ctx: InitiatiefContext = Depends(get_initiatief_context),
) -> None:
    task = await _get_visible_task(db, task_id, org_ctx, init_ctx, perm_ctx)
    attachment = await _get_attachment(db, task_id, attachment_id)
    pad, naam = attachment.pad, attachment.bestandsnaam
    await db.delete(attachment)
    await db.flush()
    await delete_blob(pad)
    await log_activity(
        db,
        current_user,
        None,
        "task_attachment.deleted",
        details={"task_id": str(task_id), "task_title": task.title, "filename": naam},
    )
