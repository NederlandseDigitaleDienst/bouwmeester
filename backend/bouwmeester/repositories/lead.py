"""Repository for Lead CRUD and queries."""

from datetime import UTC, date, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

from bouwmeester.core.initiatief_context import (
    InitiatiefContext,
    apply_initiatief_filter,
)
from bouwmeester.models.lead import Lead
from bouwmeester.models.lead_activity import LeadActivity
from bouwmeester.models.lead_column import LeadColumn
from bouwmeester.models.tag import LeadTag, Tag
from bouwmeester.repositories.base import BaseRepository
from bouwmeester.schema.lead import LeadCreate, LeadUpdate
from bouwmeester.schema.lead_column import DEFAULT_ACTIVE_SLUGS, DEFAULT_SLUGS


def _non_active_subq():
    """Slugs whose column has is_active_stage=False (per-initiatief).

    Returns a correlated subquery: a stage is "non-active" when it
    matches a `lead_column` row with `is_active_stage=False` for the
    same `initiatief_id`. Used to exclude terminal/inbox-like stages
    from "overdue"/"stale" filters.
    """
    return select(LeadColumn.slug).where(
        LeadColumn.initiatief_id == Lead.initiatief_id,
        LeadColumn.is_active_stage.is_(False),
    )


def _lead_options():
    """Standard eager-load options for lead queries."""
    return [
        selectinload(Lead.assignee),
        selectinload(Lead.brought_by),
        selectinload(Lead.organisatie_eenheid),
        selectinload(Lead.initiatief),
        selectinload(Lead.casus),
        selectinload(Lead.attachments),
        selectinload(Lead.lead_tags).selectinload(LeadTag.tag),
    ]


class StageNotInColumnsError(ValueError):
    """Raised when a write tries to set a stage that has no matching column."""


class LeadRepository(BaseRepository[Lead]):
    model = Lead

    async def _validate_stage(
        self, stage: str | None, initiatief_id: UUID | None
    ) -> None:
        """Reject writes that target a stage not defined for this initiatief.

        Orphan leads (no initiatief) fall back to the 7 default slugs.
        """
        if stage is None:
            return
        if initiatief_id is None:
            if stage not in DEFAULT_SLUGS:
                raise StageNotInColumnsError(stage)
            return
        stmt = select(LeadColumn.id).where(
            LeadColumn.initiatief_id == initiatief_id,
            LeadColumn.slug == stage,
        )
        result = await self.session.execute(stmt.limit(1))
        if result.first() is None:
            raise StageNotInColumnsError(stage)

    async def get(
        self, id: UUID, init_ctx: InitiatiefContext | None = None
    ) -> Lead | None:
        stmt = select(Lead).where(Lead.id == id).options(*_lead_options())
        stmt = apply_initiatief_filter(stmt, Lead.initiatief_id, init_ctx)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_detail(
        self, id: UUID, init_ctx: InitiatiefContext | None = None
    ) -> Lead | None:
        from bouwmeester.models.lead_node import LeadNode

        stmt = (
            select(Lead)
            .where(Lead.id == id)
            .options(
                selectinload(Lead.assignee),
                selectinload(Lead.brought_by),
                selectinload(Lead.organisatie_eenheid),
                selectinload(Lead.initiatief),
                selectinload(Lead.casus),
                selectinload(Lead.attachments),
                selectinload(Lead.activities).selectinload(LeadActivity.author),
                selectinload(Lead.linked_nodes).selectinload(LeadNode.node),
                selectinload(Lead.lead_tags).selectinload(LeadTag.tag),
            )
        )
        stmt = apply_initiatief_filter(stmt, Lead.initiatief_id, init_ctx)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        stage: str | None = None,
        tag: str | None = None,
        assignee_id: UUID | None = None,
        init_ctx: InitiatiefContext | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        next_action_filter: str | None = None,
        sort_by: str | None = None,
        initiatief_id: UUID | None = None,
    ) -> list[Lead]:
        stmt = select(Lead).options(*_lead_options()).offset(skip).limit(limit)
        if initiatief_id is not None:
            stmt = stmt.where(Lead.initiatief_id == initiatief_id)
        if stage is not None:
            stmt = stmt.where(Lead.stage == stage)
        if tag is not None:
            stmt = stmt.where(
                Lead.id.in_(
                    select(LeadTag.lead_id)
                    .join(Tag, LeadTag.tag_id == Tag.id)
                    .where(Tag.name == tag)
                )
            )
        if assignee_id is not None:
            stmt = stmt.where(Lead.assignee_id == assignee_id)

        # Date filters on created_at
        if date_from is not None:
            stmt = stmt.where(func.date(Lead.created_at) >= date_from)
        if date_to is not None:
            stmt = stmt.where(func.date(Lead.created_at) <= date_to)

        # Next action date filters
        if next_action_filter is not None:
            today = date.today()
            if next_action_filter == "overdue":
                stmt = stmt.where(
                    Lead.next_action_date < today,
                    or_(
                        and_(
                            Lead.initiatief_id.isnot(None),
                            Lead.stage.notin_(_non_active_subq()),
                        ),
                        and_(
                            Lead.initiatief_id.is_(None),
                            Lead.stage.in_(DEFAULT_ACTIVE_SLUGS),
                        ),
                    ),
                )
            elif next_action_filter == "today":
                stmt = stmt.where(Lead.next_action_date == today)
            elif next_action_filter == "this_week":
                stmt = stmt.where(
                    Lead.next_action_date >= today,
                    Lead.next_action_date <= today + timedelta(days=7),
                )

        stmt = apply_initiatief_filter(stmt, Lead.initiatief_id, init_ctx)

        # Sorting
        sort_columns = {
            "created_at": Lead.created_at.desc(),
            "updated_at": Lead.updated_at.desc().nulls_last(),
            "next_action_date": Lead.next_action_date.asc().nulls_last(),
            "stage": Lead.stage.asc(),
        }
        if sort_by and sort_by in sort_columns:
            stmt = stmt.order_by(sort_columns[sort_by])
        else:
            stmt = stmt.order_by(Lead.sort_order.asc(), Lead.created_at.desc())

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, data: LeadCreate, author_id: UUID | None = None) -> Lead:
        await self._validate_stage(data.stage, data.initiatief_id)
        dump = data.model_dump()
        # Only set created_at if explicitly provided (for backdating)
        if dump.get("created_at") is None:
            dump.pop("created_at", None)
        lead = Lead(**dump)
        self.session.add(lead)
        await self.session.flush()

        # Auto-create "Lead aangemaakt" activity
        activity = LeadActivity(
            lead_id=lead.id,
            author_id=author_id,
            content="Lead aangemaakt",
            activity_type="note",
        )
        self.session.add(activity)
        await self.session.flush()

        await self.session.refresh(
            lead,
            attribute_names=[
                "assignee",
                "brought_by",
                "organisatie_eenheid",
                "initiatief",
                "attachments",
                "lead_tags",
            ],
        )
        return lead

    async def update(self, id: UUID, data: LeadUpdate) -> Lead | None:
        lead = await self.session.get(Lead, id)
        if lead is None:
            return None
        update_data = data.model_dump(exclude_unset=True)
        # If either the stage or the initiatief changes, validate against the
        # destination initiatief's columns (or the new initiatief_id if both
        # change in the same payload).
        if "stage" in update_data or "initiatief_id" in update_data:
            target_stage = update_data.get("stage", lead.stage)
            target_init = update_data.get("initiatief_id", lead.initiatief_id)
            await self._validate_stage(target_stage, target_init)
        for key, value in update_data.items():
            setattr(lead, key, value)
        await self.session.flush()
        # Re-fetch with all eager loads to avoid lazy-loading errors
        return await self.get(id)

    async def move(
        self, id: UUID, stage: str, author_id: UUID | None = None
    ) -> Lead | None:
        lead = await self.session.get(Lead, id)
        if lead is None:
            return None
        await self._validate_stage(stage, lead.initiatief_id)
        old_stage = lead.stage
        lead.stage = stage
        await self.session.flush()

        # Auto-create stage_change activity
        activity = LeadActivity(
            lead_id=lead.id,
            author_id=author_id,
            content=f"Stage gewijzigd: {old_stage} -> {stage}",
            activity_type="stage_change",
            metadata_={"from": old_stage, "to": stage},
        )
        self.session.add(activity)
        await self.session.flush()

        # Re-fetch with all eager loads to avoid lazy-loading errors
        return await self.get(id)

    async def reorder(self, lead_ids: list[UUID], stage: str) -> list[Lead]:
        for idx, lead_id in enumerate(lead_ids):
            lead = await self.session.get(Lead, lead_id)
            if lead is not None and lead.stage == stage:
                lead.sort_order = idx
        await self.session.flush()
        # Return updated leads in the new order
        stmt = (
            select(Lead)
            .where(Lead.stage == stage, Lead.id.in_(lead_ids))
            .options(*_lead_options())
            .order_by(Lead.sort_order.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_contact_names_batch(
        self, lead_ids: list[UUID]
    ) -> dict[UUID, list[str]]:
        """Get contact person names for multiple leads in one query."""
        from bouwmeester.models.person import Person
        from bouwmeester.models.resource_permission import ResourcePermission

        if not lead_ids:
            return {}
        stmt = (
            select(ResourcePermission.resource_id, Person.naam)
            .join(Person, ResourcePermission.person_id == Person.id)
            .where(
                ResourcePermission.resource_type == "lead",
                ResourcePermission.resource_id.in_(lead_ids),
                ResourcePermission.rol == "contactpersoon",
            )
            .order_by(Person.naam)
        )
        result = await self.session.execute(stmt)
        contact_map: dict[UUID, list[str]] = {}
        for resource_id, naam in result.all():
            contact_map.setdefault(resource_id, []).append(naam)
        return contact_map

    async def delete(self, id: UUID) -> bool:
        lead = await self.session.get(Lead, id)
        if lead is None:
            return False
        await self.session.delete(lead)
        await self.session.flush()
        return True

    async def find_similar(
        self,
        title: str,
        organization: str | None = None,
        exclude_id: UUID | None = None,
        init_ctx: InitiatiefContext | None = None,
    ) -> list[Lead]:
        """Find leads with similar title or organization using trigram similarity."""
        conditions = []
        # Title similarity (trigram) - pg_trgm is available
        conditions.append(func.similarity(Lead.title, title) > 0.3)

        # Organization match
        if organization:
            conditions.append(func.similarity(Lead.organization, organization) > 0.4)

        stmt = select(Lead).where(or_(*conditions)).options(*_lead_options())
        if exclude_id:
            stmt = stmt.where(Lead.id != exclude_id)
        stmt = apply_initiatief_filter(stmt, Lead.initiatief_id, init_ctx)
        stmt = stmt.order_by(func.similarity(Lead.title, title).desc()).limit(5)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def merge(self, source_id: UUID, target_id: UUID) -> Lead | None:
        """Merge source lead into target lead, then delete source."""
        from bouwmeester.models.lead_attachment import LeadAttachment
        from bouwmeester.models.lead_node import LeadNode
        from bouwmeester.models.resource_permission import ResourcePermission

        source = await self.get_detail(source_id)
        target = await self.get_detail(target_id)
        if not source or not target:
            return None

        # Move activities from source to target
        stmt = select(LeadActivity).where(LeadActivity.lead_id == source_id)
        result = await self.session.execute(stmt)
        for activity in result.scalars().all():
            activity.lead_id = target_id

        # Move contacts from source to target (skip duplicates)
        stmt = select(ResourcePermission).where(
            ResourcePermission.resource_type == "lead",
            ResourcePermission.resource_id == source_id,
        )
        result = await self.session.execute(stmt)
        # Get existing target contacts
        target_stmt = select(ResourcePermission).where(
            ResourcePermission.resource_type == "lead",
            ResourcePermission.resource_id == target_id,
        )
        target_result = await self.session.execute(target_stmt)
        existing_contacts = {
            (c.person_id, c.rol) for c in target_result.scalars().all()
        }
        for contact in result.scalars().all():
            if (contact.person_id, contact.rol) not in existing_contacts:
                contact.resource_id = target_id
            else:
                await self.session.delete(contact)

        # Move attachments from source to target
        stmt = select(LeadAttachment).where(LeadAttachment.lead_id == source_id)
        result = await self.session.execute(stmt)
        for attachment in result.scalars().all():
            attachment.lead_id = target_id

        # Move tags from source to target (skip duplicates)
        stmt = select(LeadTag).where(LeadTag.lead_id == source_id)
        result = await self.session.execute(stmt)
        existing_tags = {lt.tag_id for lt in target.lead_tags}
        for lead_tag in result.scalars().all():
            if lead_tag.tag_id not in existing_tags:
                lead_tag.lead_id = target_id
            else:
                await self.session.delete(lead_tag)

        # Move linked nodes from source to target (skip duplicates)
        stmt = select(LeadNode).where(LeadNode.lead_id == source_id)
        result = await self.session.execute(stmt)
        existing_nodes = {ln.node_id for ln in target.linked_nodes}
        for lead_node in result.scalars().all():
            if lead_node.node_id not in existing_nodes:
                lead_node.lead_id = target_id
            else:
                await self.session.delete(lead_node)

        # Add merge activity
        merge_activity = LeadActivity(
            lead_id=target_id,
            content=f"Samengevoegd met lead: {source.title}",
            activity_type="note",
        )
        self.session.add(merge_activity)

        # Append source description to target if target has none
        if source.description and not target.description:
            target.description = source.description
        elif source.description and target.description:
            target.description = (
                f"{target.description}\n\n---\nSamengevoegd:\n{source.description}"
            )

        # Delete source lead
        await self.session.delete(source)
        await self.session.flush()

        return await self.get(target_id)

    async def get_timeline(
        self,
        init_ctx: InitiatiefContext | None = None,
        stage: str | None = None,
        assignee_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 500,
        initiatief_id: UUID | None = None,
    ) -> list[dict]:
        """Build a chronological timeline of all lead events.

        Combines lead creation events and activity events into a single
        list sorted by timestamp descending.
        """
        from datetime import datetime

        # Pre-compute date boundaries once
        dt_from = (
            datetime.combine(date_from, datetime.min.time()).replace(tzinfo=UTC)
            if date_from is not None
            else None
        )
        dt_to = (
            datetime.combine(date_to, datetime.max.time()).replace(tzinfo=UTC)
            if date_to is not None
            else None
        )

        # 1. Query visible leads with optional filters
        lead_stmt = select(Lead).options(
            selectinload(Lead.assignee),
        )
        if initiatief_id is not None:
            lead_stmt = lead_stmt.where(Lead.initiatief_id == initiatief_id)
        if stage is not None:
            lead_stmt = lead_stmt.where(Lead.stage == stage)
        if assignee_id is not None:
            lead_stmt = lead_stmt.where(Lead.assignee_id == assignee_id)
        if dt_from is not None:
            lead_stmt = lead_stmt.where(Lead.created_at >= dt_from)
        if dt_to is not None:
            lead_stmt = lead_stmt.where(Lead.created_at <= dt_to)
        lead_stmt = apply_initiatief_filter(lead_stmt, Lead.initiatief_id, init_ctx)
        result = await self.session.execute(lead_stmt)
        leads = list(result.scalars().all())

        if not leads:
            return []

        lead_map = {lead.id: lead for lead in leads}
        lead_ids = list(lead_map.keys())

        # 2. Build "created" events from leads
        events: list[dict] = []
        for lead in leads:
            events.append(
                {
                    "id": f"created-{lead.id}",
                    "lead_id": lead.id,
                    "lead_title": lead.title,
                    "event_type": "created",
                    "timestamp": lead.created_at,
                    "actor_naam": None,
                    "content": lead.description,
                    "from_stage": None,
                    "to_stage": None,
                    "organization": lead.organization,
                    "stage": lead.stage,
                    "assignee_naam": (lead.assignee.naam if lead.assignee else None),
                }
            )

        # 3. Query activities for those leads (with SQL-level date filter)
        activity_stmt = (
            select(LeadActivity)
            .where(LeadActivity.lead_id.in_(lead_ids))
            .options(selectinload(LeadActivity.author))
        )
        if dt_from is not None:
            activity_stmt = activity_stmt.where(LeadActivity.created_at >= dt_from)
        if dt_to is not None:
            activity_stmt = activity_stmt.where(LeadActivity.created_at <= dt_to)
        act_result = await self.session.execute(activity_stmt)
        activities = list(act_result.scalars().all())

        for act in activities:
            lead = lead_map.get(act.lead_id)
            if lead is None:
                continue
            metadata = act.metadata_ or {}
            events.append(
                {
                    "id": str(act.id),
                    "lead_id": act.lead_id,
                    "lead_title": lead.title,
                    "event_type": act.activity_type,
                    "timestamp": act.created_at,
                    "actor_naam": (act.author.naam if act.author else None),
                    "content": act.content,
                    "from_stage": metadata.get("from"),
                    "to_stage": metadata.get("to"),
                    "organization": lead.organization,
                    "stage": lead.stage,
                    "assignee_naam": (lead.assignee.naam if lead.assignee else None),
                }
            )

        # 4. Sort by timestamp descending and apply limit
        events.sort(key=lambda e: e["timestamp"], reverse=True)
        return events[:limit]

    async def get_metrics(
        self,
        init_ctx: InitiatiefContext | None = None,
        initiatief_id: UUID | None = None,
    ) -> dict:
        def scoped(stmt):
            stmt = apply_initiatief_filter(stmt, Lead.initiatief_id, init_ctx)
            if initiatief_id is not None:
                stmt = stmt.where(Lead.initiatief_id == initiatief_id)
            return stmt

        # Total count
        total_stmt = select(func.count()).select_from(Lead)
        total_stmt = scoped(total_stmt)
        total = (await self.session.execute(total_stmt)).scalar_one()

        # Count per stage
        stage_stmt = select(Lead.stage, func.count()).group_by(Lead.stage)
        stage_stmt = scoped(stage_stmt)
        stage_result = await self.session.execute(stage_stmt)
        by_stage = {row[0]: row[1] for row in stage_result.all()}

        # Stale count: next_action_date < today and not in terminal/inbox stages.
        # Active-stage filter is per-initiatief (lead_column.is_active_stage);
        # orphan leads (initiatief_id IS NULL) fall back to the default set.
        stale_stmt = (
            select(func.count())
            .select_from(Lead)
            .where(
                Lead.next_action_date < date.today(),
                or_(
                    and_(
                        Lead.initiatief_id.isnot(None),
                        Lead.stage.notin_(_non_active_subq()),
                    ),
                    and_(
                        Lead.initiatief_id.is_(None),
                        Lead.stage.in_(DEFAULT_ACTIVE_SLUGS),
                    ),
                ),
            )
        )
        stale_stmt = scoped(stale_stmt)
        stale_count = (await self.session.execute(stale_stmt)).scalar_one()

        return {
            "total": total,
            "by_stage": by_stage,
            "stale_count": stale_count,
        }
