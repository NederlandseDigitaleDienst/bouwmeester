"""Service layer for Notification operations."""

import asyncio
import logging
from collections import defaultdict
from datetime import date
from uuid import UUID

from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.models.corpus_node import CorpusNode
from bouwmeester.models.notification import Notification
from bouwmeester.models.opdracht import Opdracht
from bouwmeester.models.person import Person
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.models.task import Task
from bouwmeester.repositories.notification import NotificationRepository
from bouwmeester.schema.notification import NotificationCreate

logger = logging.getLogger(__name__)

# Strong references to in-flight background tasks. asyncio.create_task only
# holds a weak reference to its task, so without this set the GC can collect
# the task before it has a chance to run, which silently drops the Mattermost
# DM with no exception and no log line.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


async def _mattermost_send_background(notification_id: UUID) -> None:
    """Send a notification to Mattermost in a background task.

    Uses its own DB session so the caller's request is not blocked.
    """
    logger.info("Mattermost background send starting for %s", notification_id)
    try:
        from bouwmeester.core.database import async_session
        from bouwmeester.services.mattermost_service import MattermostService

        async with async_session() as session:
            mm = MattermostService(session)
            try:
                if not await mm.is_enabled():
                    logger.debug(
                        "Mattermost disabled, skipping send for %s", notification_id
                    )
                    return
                notification = await session.get(Notification, notification_id)
                if notification:
                    sent = await mm.send_notification(notification)
                    logger.info(
                        "Mattermost send for %s: %s",
                        notification_id,
                        "ok" if sent else "skipped/failed",
                    )
                else:
                    logger.warning(
                        "Notification %s not found for Mattermost send",
                        notification_id,
                    )
            finally:
                await mm.close()
    except Exception:
        logger.exception(
            "Mattermost background send failed for notification %s",
            notification_id,
        )


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = NotificationRepository(session)

    async def send(self, data: NotificationCreate) -> Notification:
        """Create a notification and schedule Mattermost forwarding.

        This is the single entry point external code should use to send
        notifications.  Internal helper methods may still use repo.create
        + _send_to_mattermost directly when they need finer control.
        """
        notification = await self.repo.create(data)
        self._send_to_mattermost(notification)
        return notification

    def _send_to_mattermost(self, notification: Notification) -> None:
        """Schedule Mattermost forwarding after the current transaction commits.

        The notification must already be flushed (have an id) before calling this.
        The background task uses its own DB session, so we defer it until
        after_commit to guarantee the notification is visible to the new session.
        """
        notification_id = notification.id
        sync_session = self.session.sync_session

        @event.listens_for(sync_session, "after_commit", once=True)
        def _after_commit(session):  # noqa: ARG001
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # No running event loop (e.g. in sync tests) — skip silently.
                return
            task = loop.create_task(_mattermost_send_background(notification_id))
            _BACKGROUND_TASKS.add(task)
            task.add_done_callback(_BACKGROUND_TASKS.discard)
            logger.debug("Scheduled Mattermost send for %s", notification_id)

    async def notify_task_assigned(
        self, task: Task, assignee: Person, actor_id: UUID | None = None
    ) -> Notification | None:
        # Don't notify if the actor is the assignee (self-assignment)
        if actor_id and assignee.id == actor_id:
            return None
        data = NotificationCreate(
            person_id=assignee.id,
            type="task_assigned",
            title=f"Nieuwe taak toegewezen: {task.title}",
            message=f"De taak '{task.title}' is aan je toegewezen.",
            related_node_id=task.node_id,
            related_task_id=task.id,
        )
        notification = await self.repo.create(data)
        self._send_to_mattermost(notification)
        return notification

    async def notify_task_overdue(self, task: Task) -> Notification | None:
        if task.assignee_id is None:
            return None
        data = NotificationCreate(
            person_id=task.assignee_id,
            type="task_overdue",
            title=f"Taak te laat: {task.title}",
            message=f"De deadline voor taak '{task.title}' is verstreken.",
            related_node_id=task.node_id,
            related_task_id=task.id,
        )
        notification = await self.repo.create(data)
        self._send_to_mattermost(notification)
        return notification

    async def notify_node_updated(
        self, node: CorpusNode, actor: Person
    ) -> list[Notification]:
        """Notify all stakeholders of a node update (except the actor)."""
        stmt = select(ResourcePermission).where(
            ResourcePermission.resource_type == "corpus_node",
            ResourcePermission.resource_id == node.id,
            ResourcePermission.person_id != actor.id,
        )
        result = await self.session.execute(stmt)
        stakeholders = result.scalars().all()

        notifications = []
        for sh in stakeholders:
            data = NotificationCreate(
                person_id=sh.person_id,
                type="node_updated",
                title=f"Node bijgewerkt: {node.title}",
                message=f"'{node.title}' is bijgewerkt door {actor.naam}.",
                related_node_id=node.id,
            )
            notification = await self.repo.create(data)
            self._send_to_mattermost(notification)
            notifications.append(notification)
        return notifications

    async def notify_coverage_needed(
        self, absent_person: Person, nodes: list[CorpusNode]
    ) -> list[Notification]:
        """Notify relevant people that coverage is needed because someone is absent."""
        if not nodes:
            return []

        node_ids = [node.id for node in nodes]
        node_map = {node.id: node for node in nodes}

        stmt = select(ResourcePermission).where(
            ResourcePermission.resource_type == "corpus_node",
            ResourcePermission.resource_id.in_(node_ids),
            ResourcePermission.person_id != absent_person.id,
        )
        result = await self.session.execute(stmt)
        all_stakeholders = result.scalars().all()

        stakeholders_by_node: dict[UUID, list[ResourcePermission]] = defaultdict(list)
        for sh in all_stakeholders:
            stakeholders_by_node[sh.resource_id].append(sh)

        notifications = []
        for node_id, stakeholders in stakeholders_by_node.items():
            node = node_map[node_id]
            for sh in stakeholders:
                data = NotificationCreate(
                    person_id=sh.person_id,
                    type="coverage_needed",
                    title=f"Vervanging nodig: {node.title}",
                    message=(
                        f"{absent_person.naam} is afwezig. "
                        f"Vervanging is nodig voor '{node.title}'."
                    ),
                    related_node_id=node.id,
                )
                notification = await self.repo.create(data)
                self._send_to_mattermost(notification)
                notifications.append(notification)
        return notifications

    async def notify_parlementair_item_imported(
        self,
        item_node: CorpusNode,
        affected_nodes: list[CorpusNode],
        item_type: str = "motie",
    ) -> list[Notification]:
        """Notify stakeholders about a new parliamentary item."""
        if not affected_nodes:
            return []

        type_labels: dict[str, str] = {
            "motie": "aangenomen motie",
            "kamervraag": "kamervraag",
            "toezegging": "toezegging",
            "amendement": "amendement",
        }
        type_label = type_labels.get(item_type, item_type)

        node_ids = [node.id for node in affected_nodes]
        node_map = {node.id: node for node in affected_nodes}

        stmt = select(ResourcePermission).where(
            ResourcePermission.resource_type == "corpus_node",
            ResourcePermission.resource_id.in_(node_ids),
        )
        result = await self.session.execute(stmt)
        all_stakeholders = result.scalars().all()

        stakeholders_by_node: dict[UUID, list[ResourcePermission]] = defaultdict(list)
        for sh in all_stakeholders:
            stakeholders_by_node[sh.resource_id].append(sh)

        notifications = []
        notified_person_ids: set[UUID] = set()

        for node_id, stakeholders in stakeholders_by_node.items():
            node = node_map[node_id]
            for sh in stakeholders:
                if sh.person_id in notified_person_ids:
                    continue
                notified_person_ids.add(sh.person_id)

                data = NotificationCreate(
                    person_id=sh.person_id,
                    type="politieke_input_imported",
                    title=f"Nieuw(e) {type_label}: {item_node.title}",
                    message=(
                        f"{type_label.capitalize()} '{item_node.title}' is mogelijk "
                        f"relevant voor '{node.title}'. "
                        f"Beoordeel de voorgestelde verbindingen."
                    ),
                    related_node_id=item_node.id,
                )
                notification = await self.repo.create(data)
                self._send_to_mattermost(notification)
                notifications.append(notification)

        return notifications

    async def notify_task_completed(
        self, task: Task, actor_id: UUID | None = None
    ) -> list[Notification]:
        """Notify assignee + node stakeholders when a task is completed."""
        notifications: list[Notification] = []
        notified_ids: set[UUID] = set()

        # Skip the person who completed the task
        if actor_id:
            notified_ids.add(actor_id)

        # Notify assignee
        if task.assignee_id and task.assignee_id not in notified_ids:
            notified_ids.add(task.assignee_id)
            data = NotificationCreate(
                person_id=task.assignee_id,
                type="task_completed",
                title=f"Taak afgerond: {task.title}",
                message=f"De taak '{task.title}' is afgerond.",
                related_node_id=task.node_id,
                related_task_id=task.id,
            )
            notification = await self.repo.create(data)
            self._send_to_mattermost(notification)
            notifications.append(notification)

        # Notify node stakeholders
        if task.node_id:
            stmt = select(ResourcePermission).where(
                ResourcePermission.resource_type == "corpus_node",
                ResourcePermission.resource_id == task.node_id,
                ResourcePermission.person_id.notin_(notified_ids),
            )
            result = await self.session.execute(stmt)
            for sh in result.scalars().all():
                notified_ids.add(sh.person_id)
                data = NotificationCreate(
                    person_id=sh.person_id,
                    type="task_completed",
                    title=f"Taak afgerond: {task.title}",
                    message=f"De taak '{task.title}' is afgerond.",
                    related_node_id=task.node_id,
                    related_task_id=task.id,
                )
                notification = await self.repo.create(data)
                self._send_to_mattermost(notification)
                notifications.append(notification)

        return notifications

    async def notify_task_reassigned(
        self, task: Task, old_assignee_id: UUID, new_assignee: Person
    ) -> list[Notification]:
        """Notify old assignee (reassigned) and new assignee (assigned)."""
        notifications: list[Notification] = []

        # Notify old assignee
        data = NotificationCreate(
            person_id=old_assignee_id,
            type="task_reassigned",
            title=f"Taak overgedragen: {task.title}",
            message=f"De taak '{task.title}' is overgedragen aan {new_assignee.naam}.",
            related_node_id=task.node_id,
            related_task_id=task.id,
        )
        notification = await self.repo.create(data)
        self._send_to_mattermost(notification)
        notifications.append(notification)

        # Notify new assignee
        data = NotificationCreate(
            person_id=new_assignee.id,
            type="task_assigned",
            title=f"Nieuwe taak toegewezen: {task.title}",
            message=f"De taak '{task.title}' is aan je toegewezen.",
            related_node_id=task.node_id,
            related_task_id=task.id,
        )
        notification = await self.repo.create(data)
        self._send_to_mattermost(notification)
        notifications.append(notification)

        return notifications

    async def notify_edge_created(
        self,
        from_node: CorpusNode,
        to_node: CorpusNode,
        actor_id: UUID | None = None,
    ) -> list[Notification]:
        """Notify stakeholders of both nodes about a new edge."""
        node_ids = [from_node.id, to_node.id]
        stmt = select(ResourcePermission).where(
            ResourcePermission.resource_type == "corpus_node",
            ResourcePermission.resource_id.in_(node_ids),
        )
        result = await self.session.execute(stmt)
        all_stakeholders = result.scalars().all()

        notifications: list[Notification] = []
        notified_ids: set[UUID] = set()
        if actor_id:
            notified_ids.add(actor_id)

        for sh in all_stakeholders:
            if sh.person_id in notified_ids:
                continue
            notified_ids.add(sh.person_id)
            data = NotificationCreate(
                person_id=sh.person_id,
                type="edge_created",
                title=f"Nieuwe verbinding: {from_node.title} — {to_node.title}",
                message=(
                    f"Er is een verbinding gelegd tussen "
                    f"'{from_node.title}' en '{to_node.title}'."
                ),
                related_node_id=from_node.id,
            )
            notification = await self.repo.create(data)
            self._send_to_mattermost(notification)
            notifications.append(notification)

        return notifications

    async def notify_stakeholder_added(
        self,
        node: CorpusNode,
        person_id: UUID,
        rol: str,
        actor_id: UUID | None = None,
    ) -> Notification | None:
        """Notify a person that they were added as stakeholder."""
        # Don't notify if person added themselves
        if actor_id and person_id == actor_id:
            return None
        data = NotificationCreate(
            person_id=person_id,
            type="stakeholder_added",
            title=f"Toegevoegd als {rol}: {node.title}",
            message=f"Je bent toegevoegd als {rol} aan '{node.title}'.",
            related_node_id=node.id,
        )
        notification = await self.repo.create(data)
        self._send_to_mattermost(notification)
        return notification

    async def notify_stakeholder_role_changed(
        self, node: CorpusNode, person_id: UUID, old_rol: str, new_rol: str
    ) -> Notification:
        """Notify a person that their stakeholder role changed."""
        data = NotificationCreate(
            person_id=person_id,
            type="stakeholder_role_changed",
            title=f"Rol gewijzigd: {node.title}",
            message=(
                f"Je rol bij '{node.title}' is gewijzigd van {old_rol} naar {new_rol}."
            ),
            related_node_id=node.id,
        )
        notification = await self.repo.create(data)
        self._send_to_mattermost(notification)
        return notification

    async def notify_team_manager(
        self,
        task: Task,
        eenheid_id: UUID,
        exclude_person_id: UUID | None = None,
        alleen_leden_van: UUID | None = None,
    ) -> Notification | None:
        """Notify the manager of an org unit about a task assignment.

        Met ``alleen_leden_van`` (een initiatief-id, bij een casustaak) alleen
        als de manager lid is: anders kan die de taak toch niet openen.
        """
        from bouwmeester.repositories.organisatie_eenheid import (
            OrganisatieEenheidRepository,
        )

        manager = await OrganisatieEenheidRepository(self.session).get_unit_manager(
            eenheid_id
        )
        manager_id = manager.id if manager else None

        if not manager_id:
            return None

        # Don't notify if the manager is the same as the assignee
        if exclude_person_id and manager_id == exclude_person_id:
            return None

        if alleen_leden_van is not None:
            from bouwmeester.repositories.initiatief import InitiatiefRepository

            if not await InitiatiefRepository(self.session).is_member(
                alleen_leden_van, manager_id
            ):
                return None

        data = NotificationCreate(
            person_id=manager_id,
            type="task_assigned",
            title=f"Nieuwe taak in je eenheid: {task.title}",
            message=f"De taak '{task.title}' is toegewezen binnen jouw eenheid.",
            related_node_id=task.node_id,
            related_task_id=task.id,
        )
        notification = await self.repo.create(data)
        self._send_to_mattermost(notification)
        return notification

    async def notify_direct_message(
        self,
        recipient: Person,
        sender: Person,
        message: str,
    ) -> tuple[Notification, Notification]:
        """Send a direct message. Returns (recipient_root, sender_root)."""
        is_agent = recipient.is_agent
        notif_type = "agent_prompt" if is_agent else "direct_message"
        label = "Prompt" if is_agent else "Bericht"

        # Recipient's root (unread)
        recipient_data = NotificationCreate(
            person_id=recipient.id,
            type=notif_type,
            title=f"{label} van {sender.naam}",
            message=message,
            sender_id=sender.id,
        )
        recipient_root = await self.repo.create(recipient_data)
        await self.session.flush()
        recipient_root.thread_id = recipient_root.id
        await self.session.flush()

        self._send_to_mattermost(recipient_root)

        # Sender's root (read — they sent it)
        sender_data = NotificationCreate(
            person_id=sender.id,
            type=notif_type,
            title=f"{label} aan {recipient.naam}",
            message=message,
            sender_id=sender.id,
            thread_id=recipient_root.id,
        )
        sender_root = await self.repo.create(sender_data)
        sender_root.is_read = True
        await self.session.flush()

        return recipient_root, sender_root

    async def notify_reply(
        self,
        recipient_id: UUID,
        sender: Person,
        message: str,
        thread_id: UUID,
        related_node_id: UUID | None = None,
        related_task_id: UUID | None = None,
    ) -> Notification:
        """Create a reply notification. Returns the reply."""
        data = NotificationCreate(
            person_id=recipient_id,
            type="direct_message",
            title=f"Reactie van {sender.naam}",
            message=message,
            sender_id=sender.id,
            parent_id=thread_id,
            related_node_id=related_node_id,
            related_task_id=related_task_id,
        )
        reply = await self.repo.create(data)
        self._send_to_mattermost(reply)
        return reply

    async def notify_mention(
        self,
        mentioned_person_id: UUID,
        source_type: str,
        source_title: str,
        source_node_id: UUID | None = None,
        source_task_id: UUID | None = None,
        source_lead_id: UUID | None = None,
        sender_id: UUID | None = None,
    ) -> Notification:
        """Notify a person they were @mentioned."""
        data = NotificationCreate(
            person_id=mentioned_person_id,
            type="mention",
            title=f"Je bent genoemd in: {source_title}",
            message=f"Je bent vermeld in '{source_title}'.",
            sender_id=sender_id,
            related_node_id=source_node_id,
            related_task_id=source_task_id,
            related_lead_id=source_lead_id,
        )
        notification = await self.repo.create(data)
        self._send_to_mattermost(notification)
        return notification

    async def notify_access_request(self, email: str, naam: str) -> list[Notification]:
        """Notify all admin users about a new access request."""
        from bouwmeester.repositories.role import PersonRoleRepository

        admins = await PersonRoleRepository(self.session).get_super_admins()

        notifications: list[Notification] = []
        for admin in admins:
            data = NotificationCreate(
                person_id=admin.id,
                type="access_request",
                title=f"Nieuw toegangsverzoek: {naam}",
                message=f"{naam} ({email}) vraagt toegang aan tot Bouwmeester.",
            )
            notification = await self.repo.create(data)
            self._send_to_mattermost(notification)
            notifications.append(notification)
        return notifications

    async def notify_placement_request(
        self, person_naam: str, eenheid_id: UUID, eenheid_naam: str
    ) -> list[Notification]:
        """Notify everyone who may decide the request, and all admins.

        That is every manager of the eenheid or of an eenheid above it
        (``core.authority.member_manager_ids``), not just the direct one.
        """
        from bouwmeester.core.authority import member_manager_ids

        notifications: list[Notification] = []
        notified_ids: set[UUID] = set()

        for manager_id in await member_manager_ids(self.session, eenheid_id):
            notified_ids.add(manager_id)
            data = NotificationCreate(
                person_id=manager_id,
                type="placement_request",
                title=f"Teamverzoek: {person_naam}",
                message=(f"{person_naam} wil toegevoegd worden aan '{eenheid_naam}'."),
            )
            notification = await self.repo.create(data)
            self._send_to_mattermost(notification)
            notifications.append(notification)

        # Also notify all admins
        from bouwmeester.repositories.role import PersonRoleRepository

        admins = await PersonRoleRepository(self.session).get_super_admins()
        for admin in admins:
            if admin.id not in notified_ids:
                notified_ids.add(admin.id)
                data = NotificationCreate(
                    person_id=admin.id,
                    type="placement_request",
                    title=f"Teamverzoek: {person_naam}",
                    message=(
                        f"{person_naam} wil toegevoegd worden aan '{eenheid_naam}'."
                    ),
                )
                notification = await self.repo.create(data)
                self._send_to_mattermost(notification)
                notifications.append(notification)

        return notifications

    async def notify_opdracht_assigned(
        self, opdracht: Opdracht, actor_id: UUID | None = None
    ) -> list[Notification]:
        """Notify verantwoordelijke + instrument stakeholders."""
        notifications: list[Notification] = []
        notified_ids: set[UUID] = set()

        if actor_id:
            notified_ids.add(actor_id)

        # Notify verantwoordelijke
        verant_id = opdracht.verantwoordelijke_id
        if verant_id and verant_id not in notified_ids:
            notified_ids.add(verant_id)
            data = NotificationCreate(
                person_id=opdracht.verantwoordelijke_id,
                type="opdracht_created",
                title=f"Nieuwe opdracht: {opdracht.titel}",
                message=f"Je bent verantwoordelijke voor opdracht '{opdracht.titel}'.",
                related_node_id=opdracht.instrument_id,
            )
            notification = await self.repo.create(data)
            self._send_to_mattermost(notification)
            notifications.append(notification)

        # Notify instrument stakeholders
        if opdracht.instrument_id:
            stmt = select(ResourcePermission).where(
                ResourcePermission.resource_type == "corpus_node",
                ResourcePermission.resource_id == opdracht.instrument_id,
                ResourcePermission.person_id.notin_(notified_ids),
            )
            result = await self.session.execute(stmt)
            for sh in result.scalars().all():
                notified_ids.add(sh.person_id)
                data = NotificationCreate(
                    person_id=sh.person_id,
                    type="opdracht_created",
                    title=f"Nieuwe opdracht: {opdracht.titel}",
                    message=(
                        f"Opdracht '{opdracht.titel}' is aangemaakt "
                        f"voor een instrument waar je stakeholder bent."
                    ),
                    related_node_id=opdracht.instrument_id,
                )
                notification = await self.repo.create(data)
                self._send_to_mattermost(notification)
                notifications.append(notification)

        return notifications

    async def notify_opdracht_status_changed(
        self,
        opdracht: Opdracht,
        old_status: str,
        actor_id: UUID | None = None,
    ) -> list[Notification]:
        """Notify verantwoordelijke + stakeholders when opdracht status changes."""
        notifications: list[Notification] = []
        notified_ids: set[UUID] = set()

        if actor_id:
            notified_ids.add(actor_id)

        # Notify verantwoordelijke
        verant_id = opdracht.verantwoordelijke_id
        if verant_id and verant_id not in notified_ids:
            notified_ids.add(verant_id)
            data = NotificationCreate(
                person_id=verant_id,
                type="opdracht_status_changed",
                title=f"Opdracht status gewijzigd: {opdracht.titel}",
                message=(
                    f"Status van '{opdracht.titel}' is gewijzigd "
                    f"van '{old_status}' naar '{opdracht.status}'."
                ),
                related_node_id=opdracht.instrument_id,
            )
            notification = await self.repo.create(data)
            self._send_to_mattermost(notification)
            notifications.append(notification)

        # Notify instrument stakeholders
        if opdracht.instrument_id:
            stmt = select(ResourcePermission).where(
                ResourcePermission.resource_type == "corpus_node",
                ResourcePermission.resource_id == opdracht.instrument_id,
                ResourcePermission.person_id.notin_(notified_ids),
            )
            result = await self.session.execute(stmt)
            for sh in result.scalars().all():
                notified_ids.add(sh.person_id)
                data = NotificationCreate(
                    person_id=sh.person_id,
                    type="opdracht_status_changed",
                    title=f"Opdracht status gewijzigd: {opdracht.titel}",
                    message=(
                        f"Status van '{opdracht.titel}' is gewijzigd "
                        f"van '{old_status}' naar '{opdracht.status}'."
                    ),
                    related_node_id=opdracht.instrument_id,
                )
                notification = await self.repo.create(data)
                self._send_to_mattermost(notification)
                notifications.append(notification)

        return notifications

    async def get_notifications(
        self,
        person_id: UUID,
        unread_only: bool = False,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Notification]:
        return await self.repo.get_by_person(
            person_id, unread_only=unread_only, skip=skip, limit=limit
        )

    async def mark_read(self, notification_id: UUID) -> Notification | None:
        return await self.repo.mark_read(notification_id)

    async def mark_all_read(self, person_id: UUID) -> int:
        return await self.repo.mark_all_read(person_id)

    async def count_unread(self, person_id: UUID) -> int:
        return await self.repo.count_unread(person_id)

    async def get_dashboard_stats(self, person_id: UUID) -> dict[str, int]:
        """Return dashboard statistics for a person."""
        # Total corpus nodes
        node_result = await self.session.execute(select(func.count(CorpusNode.id)))
        corpus_node_count = node_result.scalar_one()

        # Open tasks assigned to this person
        open_result = await self.session.execute(
            select(func.count(Task.id)).where(
                Task.assignee_id == person_id,
                Task.status.in_(["open", "in_progress"]),
            )
        )
        open_task_count = open_result.scalar_one()

        # Overdue tasks assigned to this person
        today = date.today()
        overdue_result = await self.session.execute(
            select(func.count(Task.id)).where(
                Task.assignee_id == person_id,
                Task.deadline < today,
                Task.status.notin_(["done", "cancelled"]),
            )
        )
        overdue_task_count = overdue_result.scalar_one()

        # Active opdracht budget for this person (as verantwoordelijke)
        opdracht_result = await self.session.execute(
            select(func.coalesce(func.sum(Opdracht.budget), 0)).where(
                Opdracht.verantwoordelijke_id == person_id,
                Opdracht.status == "actief",
            )
        )
        active_opdracht_budget = float(opdracht_result.scalar_one())

        return {
            "corpus_node_count": corpus_node_count,
            "open_task_count": open_task_count,
            "overdue_task_count": overdue_task_count,
            "active_opdracht_budget": active_opdracht_budget,
        }
