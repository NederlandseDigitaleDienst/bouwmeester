"""Repository for omni full-text search across all entity types."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.core.initiatief_context import InitiatiefContext
from bouwmeester.core.org_context import OrgContext, org_filter_sql_clause
from bouwmeester.core.query_utils import escape_like
from bouwmeester.repositories.task import casus_filter_sql_clause
from bouwmeester.utils.tiptap import tiptap_to_plain


class SearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def full_text_search(
        self,
        query: str,
        result_types: list[str] | None = None,
        limit: int = 50,
        org_ctx: OrgContext | None = None,
        init_ctx: InitiatiefContext | None = None,
    ) -> list[dict]:
        """Search across all entity types using stored tsvector + GIN indexes.

        Returns unified results from corpus_node, task, person,
        organisatie_eenheid, parlementair_item, and tag tables.
        Taken van een casus alleen binnen de zichtbare initiatieven
        (``init_ctx``), zoals in elke takenlijst.
        """
        all_types = {
            "corpus_node",
            "task",
            "person",
            "organisatie_eenheid",
            "parlementair_item",
            "tag",
            "lead",
        }
        active_types = set(result_types) if result_types else all_types

        sub_queries = []

        # title_col per entity for ILIKE fallback
        entity_title_cols = {
            "corpus_node": "title",
            "task": "title",
            "person": "naam",
            "organisatie_eenheid": "naam",
            "parlementair_item": "titel",
            "tag": "name",
            "lead": "title",
        }

        def _where(title_col: str) -> str:
            # FTS for stemmed word matching, ILIKE for substring-in-title
            # fallback (handles abbreviations like "JenV" inside "MinJenV").
            fts = "search_vector @@ plainto_tsquery('dutch', :query)"
            return f"({fts} OR {title_col} ILIKE :ilike_pattern)"

        def _score(title_col: str) -> str:
            # FTS rank dominates; ILIKE-only matches get a low base score
            # so they appear below proper FTS hits.
            rank = "ts_rank(search_vector, plainto_tsquery('dutch', :query))"
            return (
                f"GREATEST({rank}, "
                f"CASE WHEN {title_col} ILIKE :ilike_pattern THEN 0.05 ELSE 0 END)"
            )

        def _org_sql(col: str = "organisatie_eenheid_id") -> str:
            return org_filter_sql_clause(col, org_ctx)

        if "corpus_node" in active_types:
            tc = entity_title_cols["corpus_node"]
            sub_queries.append(f"""
                SELECT
                    id,
                    'corpus_node' AS result_type,
                    title,
                    node_type AS subtitle,
                    description,
                    {_score(tc)} AS score
                FROM corpus_node
                WHERE {_where(tc)}{_org_sql()}
            """)

        casus_sql, casus_params = casus_filter_sql_clause(init_ctx)

        if "task" in active_types:
            tc = entity_title_cols["task"]
            sub_queries.append(f"""
                SELECT
                    id,
                    'task' AS result_type,
                    title,
                    status AS subtitle,
                    description,
                    {_score(tc)} AS score
                FROM task
                WHERE {_where(tc)}{_org_sql()}{casus_sql}
            """)

        if "person" in active_types:
            tc = entity_title_cols["person"]
            sub_queries.append(f"""
                SELECT
                    id,
                    'person' AS result_type,
                    naam AS title,
                    functie AS subtitle,
                    email AS description,
                    {_score(tc)} AS score
                FROM person
                WHERE {_where(tc)}
            """)

        if "organisatie_eenheid" in active_types:
            tc = entity_title_cols["organisatie_eenheid"]
            sub_queries.append(f"""
                SELECT
                    id,
                    'organisatie_eenheid' AS result_type,
                    naam AS title,
                    type AS subtitle,
                    beschrijving AS description,
                    {_score(tc)} AS score
                FROM organisatie_eenheid
                WHERE {_where(tc)}
            """)

        if "parlementair_item" in active_types:
            tc = entity_title_cols["parlementair_item"]
            sub_queries.append(f"""
                SELECT
                    id,
                    'parlementair_item' AS result_type,
                    titel AS title,
                    type AS subtitle,
                    onderwerp AS description,
                    {_score(tc)} AS score
                FROM parlementair_item
                WHERE {_where(tc)}
            """)

        if "tag" in active_types:
            tc = entity_title_cols["tag"]
            sub_queries.append(f"""
                SELECT
                    id,
                    'tag' AS result_type,
                    name AS title,
                    NULL AS subtitle,
                    description,
                    {_score(tc)} AS score
                FROM tag
                WHERE {_where(tc)}
            """)

        if "lead" in active_types:
            tc = entity_title_cols["lead"]
            sub_queries.append(f"""
                SELECT
                    id,
                    'lead' AS result_type,
                    title,
                    stage AS subtitle,
                    description,
                    {_score(tc)} AS score
                FROM lead
                WHERE {_where(tc)}{_org_sql()}
            """)

        if not sub_queries:
            return []

        union_sql = " UNION ALL ".join(sub_queries)
        full_sql = f"""
            SELECT * FROM ({union_sql}) AS combined
            ORDER BY score DESC
            LIMIT :limit
        """

        params: dict = {
            "query": query,
            "limit": limit,
            "ilike_pattern": f"%{escape_like(query.strip())}%",
        }
        if "task" in active_types:
            params.update(casus_params)
        if (
            org_ctx is not None
            and org_ctx.is_authenticated
            and not org_ctx.is_admin
            and org_ctx.visible_eenheid_ids
        ):
            all_visible = list(
                set(org_ctx.visible_eenheid_ids) | set(org_ctx.shared_eenheid_ids)
            )
            params["visible_eenheid_ids"] = [str(eid) for eid in all_visible]

        result = await self.session.execute(text(full_sql), params)
        rows = result.all()

        url_map = {
            "corpus_node": "/nodes/{id}",
            "task": "/tasks?task={id}",
            "person": "/people?person={id}",
            "organisatie_eenheid": "/organisatie?eenheid={id}",
            "parlementair_item": "/parlementair?item={id}",
            "tag": "/corpus?tag={id}",
            "lead": "/leads?lead={id}",
        }

        # Build results, converting TipTap JSON descriptions to plain text
        results = []
        for row in rows:
            url = url_map[row.result_type].format(id=row.id)
            description = tiptap_to_plain(row.description)
            results.append(
                {
                    "id": row.id,
                    "result_type": row.result_type,
                    "title": row.title,
                    "subtitle": row.subtitle,
                    "description": description,
                    "score": float(row.score),
                    "highlights": None,
                    "url": url,
                }
            )

        # Generate highlights for rows that have descriptions
        if results:
            ids_with_desc = [(i, r) for i, r in enumerate(results) if r["description"]]
            if ids_with_desc:
                await self._add_highlights(ids_with_desc, query)

        return results

    async def find_similar_nodes(
        self,
        title: str,
        description: str | None = None,
        exclude_node_id: str | None = None,
        limit: int = 5,
        org_ctx: OrgContext | None = None,
    ) -> list[dict]:
        """Find nodes with similar titles using trigram similarity + FTS.

        Returns a list of dicts with id, title, node_type, similarity score.
        Requires the pg_trgm extension.
        """
        params: dict = {"title": title, "limit": limit}

        exclude_clause = ""
        if exclude_node_id:
            exclude_clause = "AND id != :exclude_id"
            params["exclude_id"] = exclude_node_id

        org_clause = org_filter_sql_clause("organisatie_eenheid_id", org_ctx)
        if (
            org_ctx is not None
            and org_ctx.is_authenticated
            and not org_ctx.is_admin
            and org_ctx.visible_eenheid_ids
        ):
            all_visible = list(
                set(org_ctx.visible_eenheid_ids) | set(org_ctx.shared_eenheid_ids)
            )
            params["visible_eenheid_ids"] = [str(eid) for eid in all_visible]

        # Composite score: trigram similarity on title + optional FTS on description
        sql = f"""
            SELECT
                id,
                title,
                node_type,
                similarity(title, :title) AS trgm_score,
                CASE
                    WHEN search_vector @@ plainto_tsquery('dutch', :title)
                    THEN ts_rank(search_vector, plainto_tsquery('dutch', :title))
                    ELSE 0.0
                END AS fts_score,
                (similarity(title, :title) * 0.7
                 + CASE
                     WHEN search_vector @@ plainto_tsquery('dutch', :title)
                     THEN ts_rank(search_vector, plainto_tsquery('dutch', :title)) * 0.3
                     ELSE 0.0
                   END
                ) AS combined_score
            FROM corpus_node
            WHERE similarity(title, :title) > 0.15
            {exclude_clause}{org_clause}
            ORDER BY combined_score DESC
            LIMIT :limit
        """

        result = await self.session.execute(text(sql), params)
        rows = result.all()

        return [
            {
                "id": row.id,
                "title": row.title,
                "node_type": row.node_type,
                "similarity": round(float(row.combined_score), 3),
            }
            for row in rows
            if row.combined_score > 0.15
        ]

    async def _add_highlights(
        self, indexed_results: list[tuple[int, dict]], query: str
    ) -> None:
        """Add ts_headline highlights to results that have descriptions."""
        for _idx, result in indexed_results:
            desc = result["description"] or ""
            if not desc:
                continue
            hl_result = await self.session.execute(
                text("""
                    SELECT ts_headline(
                        'dutch',
                        :desc,
                        plainto_tsquery('dutch', :query),
                        'StartSel=<mark>,StopSel=</mark>,MaxWords=35,MinWords=15,MaxFragments=2'
                    ) AS headline
                """),
                {"desc": desc, "query": query},
            )
            headline = hl_result.scalar()
            if headline and "<mark>" in headline:
                result["highlights"] = [headline]
