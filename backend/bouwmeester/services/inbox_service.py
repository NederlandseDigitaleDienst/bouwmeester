"""Service layer for Inbox aggregation."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.repositories.activity import ActivityRepository
from bouwmeester.repositories.task import TaskRepository
from bouwmeester.schema.inbox import InboxItem, InboxResponse


class InboxService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.task_repo = TaskRepository(session)
        self.activity_repo = ActivityRepository(session)

    async def get_inbox(self, person_id: UUID, *, init_ctx=None) -> InboxResponse:
        """Aggregate inbox items for a person.

        Includes:
        - Overdue tasks assigned to the person
        - Recently assigned tasks
        - Recent activity on nodes the person is involved with
        """
        items: list[InboxItem] = []

        # 1. Overdue tasks
        overdue_tasks = await self.task_repo.get_overdue(
            assignee_id=person_id, init_ctx=init_ctx
        )
        for task in overdue_tasks:
            items.append(
                InboxItem(
                    type="overdue_task",
                    title=f"Verlopen: {task.title}",
                    description=(
                        f"Deadline was {task.deadline}. Status: {task.status}."
                    ),
                    related_node_id=task.node_id,
                    related_task_id=task.id,
                    created_at=task.created_at,
                )
            )

        # 2. Recent task assignments (tasks assigned to this person, created recently)
        assigned_tasks = await self.task_repo.get_by_assignee(
            assignee_id=person_id, limit=20, init_ctx=init_ctx
        )
        for task in assigned_tasks:
            if task.status == "open":
                items.append(
                    InboxItem(
                        type="new_assignment",
                        title=f"Nieuwe taak: {task.title}",
                        description=task.description or "Geen beschrijving.",
                        related_node_id=task.node_id,
                        related_task_id=task.id,
                        created_at=task.created_at,
                    )
                )

        # 3. Recent node changes (activity where the person is the actor)
        recent_activity = await self.activity_repo.get_by_person(
            person_id=person_id, limit=10
        )
        for activity in recent_activity:
            if activity.node_id:
                items.append(
                    InboxItem(
                        type="node_change",
                        title=f"Activiteit: {activity.event_type}",
                        description=str(activity.details) if activity.details else "",
                        related_node_id=activity.node_id,
                        related_task_id=activity.task_id,
                        created_at=activity.created_at,
                    )
                )

        # Sort by created_at descending
        items.sort(key=lambda x: x.created_at, reverse=True)

        return InboxResponse(items=items, total=len(items))
