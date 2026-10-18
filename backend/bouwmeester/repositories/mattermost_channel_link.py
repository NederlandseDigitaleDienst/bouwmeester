"""Repository voor MattermostChannelLink."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.models.mattermost_channel_link import MattermostChannelLink


class MattermostChannelLinkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, link_id: UUID) -> MattermostChannelLink | None:
        stmt = select(MattermostChannelLink).where(MattermostChannelLink.id == link_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_channel_id(self, channel_id: str) -> MattermostChannelLink | None:
        stmt = select(MattermostChannelLink).where(
            MattermostChannelLink.channel_id == channel_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_scope(
        self, scope_type: str, scope_id: UUID
    ) -> list[MattermostChannelLink]:
        stmt = (
            select(MattermostChannelLink)
            .where(
                MattermostChannelLink.scope_type == scope_type,
                MattermostChannelLink.scope_id == scope_id,
            )
            .order_by(MattermostChannelLink.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_active(self) -> list[MattermostChannelLink]:
        """Alle gekoppelde kanalen die niet uitgeschakeld zijn (voor de
        websocket-loop om events op te filteren)."""
        stmt = select(MattermostChannelLink).where(
            MattermostChannelLink.disabled_at.is_(None)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        channel_id: str,
        channel_name: str,
        channel_display_name: str,
        team_id: str | None,
        scope_type: str,
        scope_id: UUID,
        auto_note_enabled: bool,
        suggest_leads_enabled: bool,
        created_by_id: UUID | None,
        parlementaire_alerts_enabled: bool = False,
        nieuws_alerts_enabled: bool = False,
    ) -> MattermostChannelLink:
        link = MattermostChannelLink(
            channel_id=channel_id,
            channel_name=channel_name,
            channel_display_name=channel_display_name,
            team_id=team_id,
            scope_type=scope_type,
            scope_id=scope_id,
            auto_note_enabled=auto_note_enabled,
            suggest_leads_enabled=suggest_leads_enabled,
            parlementaire_alerts_enabled=parlementaire_alerts_enabled,
            nieuws_alerts_enabled=nieuws_alerts_enabled,
            created_by_id=created_by_id,
        )
        self.session.add(link)
        await self.session.flush()
        await self.session.refresh(link)
        return link

    async def update_settings(
        self,
        link: MattermostChannelLink,
        *,
        auto_note_enabled: bool | None = None,
        suggest_leads_enabled: bool | None = None,
        parlementaire_alerts_enabled: bool | None = None,
        nieuws_alerts_enabled: bool | None = None,
        reenable: bool | None = None,
    ) -> MattermostChannelLink:
        if auto_note_enabled is not None:
            link.auto_note_enabled = auto_note_enabled
        if suggest_leads_enabled is not None:
            link.suggest_leads_enabled = suggest_leads_enabled
        if parlementaire_alerts_enabled is not None:
            link.parlementaire_alerts_enabled = parlementaire_alerts_enabled
        if nieuws_alerts_enabled is not None:
            link.nieuws_alerts_enabled = nieuws_alerts_enabled
        if reenable:
            link.disabled_at = None
        await self.session.flush()
        await self.session.refresh(link)
        return link

    async def update_last_seen(
        self, link: MattermostChannelLink, last_seen_post_at: int
    ) -> None:
        if link.last_seen_post_at is None or last_seen_post_at > link.last_seen_post_at:
            link.last_seen_post_at = last_seen_post_at
            await self.session.flush()

    async def delete(self, link: MattermostChannelLink) -> None:
        await self.session.delete(link)
        await self.session.flush()
