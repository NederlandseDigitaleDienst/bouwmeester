"""Service layer for mention extraction, syncing, and notification."""

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.core.initiatief_context import InitiatiefContext
from bouwmeester.core.org_context import OrgContext, apply_org_filter
from bouwmeester.core.tiptap_markdown import extract_markdown_mentions
from bouwmeester.models.corpus_node import CorpusNode
from bouwmeester.models.mention import Mention
from bouwmeester.models.task import Task
from bouwmeester.repositories.mention import MentionRepository
from bouwmeester.repositories.task import apply_casus_filter
from bouwmeester.schema.mention import (
    MentionCreate,
    MentionReference,
    MentionSearchResult,
)


class MentionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = MentionRepository(session)

    @staticmethod
    def extract_mentions(description_json: str) -> list[dict]:
        """Extract mentions from a description, in either storage format.

        Returns list of dicts with keys: mention_type, target_id.
        mention_type is 'person' for @mentions, derived from attrs for #mentions.

        Both formats are read because both occur. The editor writes markdown
        (`[@Anne](user:<id>)`), and older rows still hold TipTap JSON. Reading
        only one of the two is silent: `sync_mentions` clears a row's mentions
        before re-extracting, so a format it cannot parse costs that row every
        notification without raising anything.
        """
        if not description_json:
            return []

        try:
            doc = json.loads(description_json)
        except (json.JSONDecodeError, TypeError):
            return extract_markdown_mentions(description_json)

        # A JSON string that is not a TipTap document (a bare number, or a
        # quoted string holding markdown) parses fine and walks to nothing.
        if not isinstance(doc, dict):
            return extract_markdown_mentions(description_json)

        mentions: list[dict] = []
        _walk_tiptap(doc, mentions)
        return mentions

    async def sync_mentions(
        self,
        source_type: str,
        source_id: UUID,
        description_json: str | None,
        created_by: UUID | None,
    ) -> list[Mention]:
        """Sync mentions for source. Returns only genuinely new mentions."""
        # Get existing mentions before deleting
        existing = await self.repo.get_by_source(source_type, source_id)
        existing_keys: set[tuple[str, str]] = {
            (m.mention_type, str(m.target_id)) for m in existing
        }

        await self.repo.delete_by_source(source_type, source_id)

        if not description_json:
            return []

        raw_mentions = self.extract_mentions(description_json)
        if not raw_mentions:
            return []

        # Deduplicate by (mention_type, target_id)
        seen: set[tuple[str, str]] = set()
        creates: list[MentionCreate] = []
        for m in raw_mentions:
            key = (m["mention_type"], m["target_id"])
            if key in seen:
                continue
            seen.add(key)
            creates.append(
                MentionCreate(
                    source_type=source_type,
                    source_id=source_id,
                    mention_type=m["mention_type"],
                    target_id=UUID(m["target_id"]),
                    created_by=created_by,
                )
            )

        if not creates:
            return []

        all_mentions = await self.repo.create_many(creates)

        # Only return mentions that didn't exist before (for notifications)
        return [
            m
            for m in all_mentions
            if (m.mention_type, str(m.target_id)) not in existing_keys
        ]

    # Only these source types should appear as public back-references.
    # DMs, org descriptions, and any future private source types are excluded.
    _PUBLIC_SOURCE_TYPES = ["node", "task"]

    async def get_references(
        self,
        target_id: UUID,
        *,
        org_ctx: OrgContext | None = None,
        init_ctx: InitiatiefContext | None = None,
    ) -> list[MentionReference]:
        """Get all places where target_id is mentioned, with source titles.

        Only includes public source types (nodes, tasks) — private content
        like DMs and org descriptions should not leak as back-references.
        Filters node/task sources cross-org via ``org_ctx``, and tasks of a
        casus outside the visible initiatieven via ``init_ctx``.
        """
        mentions = await self.repo.get_by_target(
            target_id, allowed_source_types=self._PUBLIC_SOURCE_TYPES
        )
        if not mentions:
            return []

        # Filter mentions to only those whose source node/task is visible
        # to the caller (cross-org and cross-initiatief leak prevention).
        if (org_ctx is not None and not org_ctx.is_admin) or (
            init_ctx is not None and not init_ctx.is_admin
        ):
            mentions = await self._filter_mentions_by_org(mentions, org_ctx, init_ctx)
            if not mentions:
                return []

        # Batch-fetch titles by source type to avoid N+1 queries
        titles = await self._get_source_titles_batch(mentions)

        refs: list[MentionReference] = []
        for m in mentions:
            title = titles.get((m.source_type, m.source_id))
            if title:
                refs.append(
                    MentionReference(
                        source_type=m.source_type,
                        source_id=m.source_id,
                        source_title=title,
                    )
                )
        return refs

    async def _get_source_titles_batch(
        self, mentions: list[Mention]
    ) -> dict[tuple[str, UUID], str]:
        """Fetch titles for all mentions in batched IN-clause queries."""
        # Group source IDs by type
        ids_by_type: dict[str, list[UUID]] = {}
        for m in mentions:
            ids_by_type.setdefault(m.source_type, []).append(m.source_id)

        titles: dict[tuple[str, UUID], str] = {}

        if "node" in ids_by_type:
            stmt = select(CorpusNode.id, CorpusNode.title).where(
                CorpusNode.id.in_(ids_by_type["node"])
            )
            for row in (await self.session.execute(stmt)).all():
                titles[("node", row[0])] = row[1]

        if "task" in ids_by_type:
            stmt = select(Task.id, Task.title).where(Task.id.in_(ids_by_type["task"]))
            for row in (await self.session.execute(stmt)).all():
                titles[("task", row[0])] = row[1]

        if "organisatie" in ids_by_type:
            from bouwmeester.models.organisatie_eenheid import OrganisatieEenheid

            stmt = select(OrganisatieEenheid.id, OrganisatieEenheid.naam).where(
                OrganisatieEenheid.id.in_(ids_by_type["organisatie"])
            )
            for row in (await self.session.execute(stmt)).all():
                titles[("organisatie", row[0])] = row[1]

        if "notification" in ids_by_type:
            from bouwmeester.models.notification import Notification

            stmt = select(Notification.id, Notification.title).where(
                Notification.id.in_(ids_by_type["notification"])
            )
            for row in (await self.session.execute(stmt)).all():
                titles[("notification", row[0])] = row[1]

        return titles

    async def _filter_mentions_by_org(
        self,
        mentions: list[Mention],
        org_ctx: OrgContext | None,
        init_ctx: InitiatiefContext | None = None,
    ) -> list[Mention]:
        """Drop mentions whose source node/task is outside the caller's scope.

        Org-scope for nodes and tasks; for a task of a casus also the
        initiatief of that casus.
        """
        node_ids = {m.source_id for m in mentions if m.source_type == "node"}
        task_ids = {m.source_id for m in mentions if m.source_type == "task"}

        visible_node_ids: set[UUID] = set()
        visible_task_ids: set[UUID] = set()

        if node_ids:
            stmt = apply_org_filter(
                select(CorpusNode.id).where(CorpusNode.id.in_(node_ids)),
                CorpusNode.organisatie_eenheid_id,
                org_ctx,
            )
            visible_node_ids = {
                row[0] for row in (await self.session.execute(stmt)).all()
            }

        if task_ids:
            stmt = apply_org_filter(
                select(Task.id).where(Task.id.in_(task_ids)),
                Task.organisatie_eenheid_id,
                org_ctx,
            )
            stmt = apply_casus_filter(stmt, init_ctx)
            visible_task_ids = {
                row[0] for row in (await self.session.execute(stmt)).all()
            }

        return [
            m
            for m in mentions
            if (m.source_type == "node" and m.source_id in visible_node_ids)
            or (m.source_type == "task" and m.source_id in visible_task_ids)
        ]

    async def search_mentionables(
        self,
        query: str,
        types: list[str] | None = None,
        limit: int = 10,
        *,
        org_ctx: OrgContext | None = None,
        init_ctx: InitiatiefContext | None = None,
    ) -> list[MentionSearchResult]:
        """Search across nodes, tasks, and tags for # mention suggestions."""
        results: list[MentionSearchResult] = []
        allowed = types or ["node", "task", "tag"]
        pattern = f"%{query}%"

        if "node" in allowed:
            stmt = select(CorpusNode).where(CorpusNode.title.ilike(pattern))
            stmt = apply_org_filter(stmt, CorpusNode.organisatie_eenheid_id, org_ctx)
            stmt = stmt.order_by(CorpusNode.title).limit(limit)
            rows = await self.session.execute(stmt)
            for n in rows.scalars().all():
                results.append(
                    MentionSearchResult(
                        id=str(n.id),
                        label=n.title,
                        type="node",
                        subtitle=n.node_type.replace("_", " "),
                    )
                )

        if "task" in allowed:
            stmt = select(Task).where(Task.title.ilike(pattern))
            stmt = apply_org_filter(stmt, Task.organisatie_eenheid_id, org_ctx)
            stmt = apply_casus_filter(stmt, init_ctx)
            stmt = stmt.order_by(Task.title).limit(limit)
            rows = await self.session.execute(stmt)
            for t in rows.scalars().all():
                results.append(
                    MentionSearchResult(
                        id=str(t.id),
                        label=t.title,
                        type="task",
                        subtitle=t.status.replace("_", " ") if t.status else None,
                    )
                )

        if "tag" in allowed:
            from bouwmeester.models.tag import Tag

            stmt = (
                select(Tag)
                .where(Tag.name.ilike(pattern))
                .order_by(Tag.name)
                .limit(limit)
            )
            rows = await self.session.execute(stmt)
            for tag in rows.scalars().all():
                results.append(
                    MentionSearchResult(
                        id=str(tag.id),
                        label=tag.name,
                        type="tag",
                    )
                )

        # Sort combined results by label and limit
        results.sort(key=lambda r: r.label.lower())
        return results[:limit]


def _walk_tiptap(node: dict | list, mentions: list[dict]) -> None:
    """Recursively walk TipTap JSON tree and extract mention nodes."""
    if isinstance(node, list):
        for item in node:
            _walk_tiptap(item, mentions)
        return

    if not isinstance(node, dict):
        return

    node_type = node.get("type")

    if node_type == "mention":
        attrs = node.get("attrs", {})
        target_id = attrs.get("id")
        # mentionType attr: person vs organisatie (default "person")
        mention_type = attrs.get("mentionType", "person")
        if target_id:
            mentions.append({"mention_type": mention_type, "target_id": str(target_id)})

    elif node_type == "hashtagMention":
        attrs = node.get("attrs", {})
        target_id = attrs.get("id")
        # mentionType is 'node', 'task', or 'tag'; default to 'node' for legacy data
        mention_type = attrs.get("mentionType", "node")
        if target_id:
            mentions.append({"mention_type": mention_type, "target_id": str(target_id)})

    # Recurse into content
    content = node.get("content")
    if content:
        _walk_tiptap(content, mentions)
