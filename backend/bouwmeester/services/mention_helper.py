"""Helper to sync mentions from content and notify mentioned persons."""

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.repositories.initiatief import InitiatiefRepository
from bouwmeester.services.mention_service import MentionService
from bouwmeester.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


async def sync_and_notify_mentions(
    db: AsyncSession,
    source_type: str,
    source_id: UUID,
    content: str | None,
    entity_title: str,
    *,
    sender_id: UUID | None = None,
    source_node_id: UUID | None = None,
    source_task_id: UUID | None = None,
    source_lead_id: UUID | None = None,
    exclude_person_id: UUID | None = None,
    alleen_leden_van: UUID | None = None,
    ontvanger_ziet: Callable[[UUID], Awaitable[bool]] | None = None,
) -> None:
    """Sync mentions from content and send notifications to mentioned persons.

    Uses a savepoint so that mention/notification failures don't roll back
    the parent entity creation.

    Args:
        db: Database session.
        source_type: Type of entity ("node", "task", "organisatie", "notification").
        source_id: ID of the source entity.
        content: Text content to scan for mentions. No-op if None/empty.
        entity_title: Title shown in the notification.
        sender_id: Person who created the mention (optional).
        source_node_id: Related node ID for notification linking (optional).
        source_task_id: Related task ID for notification linking (optional).
        exclude_person_id: Person ID to skip notifying (e.g. the direct recipient).
        alleen_leden_van: Initiatief-id. Alleen wie lid is, krijgt een
            melding: de titel van een casustaak hoort niet bij mensen die de
            casus niet kunnen zien. De vermelding zelf wordt wel vastgelegd.
        ontvanger_ziet: Of een genoemde persoon de bron mag zien. Wie dat niet
            mag, krijgt geen melding: die zou de titel lezen van iets waar
            hij geen toegang toe heeft. De vermelding zelf wordt wel
            vastgelegd.
    """
    if not content:
        return

    try:
        async with db.begin_nested():
            mention_svc = MentionService(db)
            new_mentions = await mention_svc.sync_mentions(
                source_type, source_id, content, sender_id
            )

            notif_svc = NotificationService(db)
            init_repo = InitiatiefRepository(db)
            for m in new_mentions:
                if m.mention_type == "person":
                    if exclude_person_id and m.target_id == exclude_person_id:
                        continue
                    if alleen_leden_van is not None and not await init_repo.is_member(
                        alleen_leden_van, m.target_id
                    ):
                        continue
                    if ontvanger_ziet is not None and not await ontvanger_ziet(
                        m.target_id
                    ):
                        continue
                    await notif_svc.notify_mention(
                        m.target_id,
                        source_type,
                        entity_title,
                        source_node_id=source_node_id,
                        source_task_id=source_task_id,
                        source_lead_id=source_lead_id,
                        sender_id=sender_id,
                    )
    except Exception:
        logger.exception(
            "Failed to sync mentions for %s %s; parent entity preserved",
            source_type,
            source_id,
        )
