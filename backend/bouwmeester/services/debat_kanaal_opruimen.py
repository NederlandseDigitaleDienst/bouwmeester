"""Archive the channel of a debate once nobody needs it any more.

Every debate someone follows gets a channel of its own, so the sidebar of
whoever joins a few fills up within weeks. A channel is archived when two
things hold:

* the debate began at least `AFTER_DEBATE` ago, which leaves room for the
  votes, usually the Tuesday after, and the votes per fractie the morning
  after that;
* nothing was said in it for `QUIET`: a channel where people still talk
  about the debate stays.

Archived, not deleted: the messages stay, and a system admin can bring
the channel back. Just before, one message says why, so whoever opens it
later knows what happened. Should the archiving itself fail, that message
is the last one in the channel; it is recognised by its props and not
posted a second time.

Nothing is kept for this on the sessie: Mattermost knows whether a channel
is archived, and when something was last said in it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.models.debat_sessie import DebatSessie
from bouwmeester.services.mattermost_service import MattermostService

logger = logging.getLogger(__name__)

AFTER_DEBATE = timedelta(days=30)
QUIET = timedelta(days=14)
# Debates older than this are not looked at again. Anything still open by
# then was kept on purpose, or was archived and brought back by hand.
LOOK_BACK = timedelta(days=120)

# The props of the message that says the channel is archived.
PROP = "bouwmeester_archived"

MESSAGE = (
    "🗄️ Dit kanaal wordt gearchiveerd. Het debat is meer dan "
    f"{AFTER_DEBATE.days} dagen geleden en hier is {QUIET.days} dagen niets "
    "gezegd. Een beheerder kan het kanaal terugzetten."
)


@dataclass
class OpruimTickResult:
    checked: int = 0
    archived: int = 0
    errors: int = 0

    def summary(self) -> str:
        return (
            f"{self.checked} kanalen bekeken, {self.archived} gearchiveerd, "
            f"{self.errors} fouten"
        )


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


class DebatKanaalOpruimen:
    def __init__(
        self, session: AsyncSession, mattermost: MattermostService | None = None
    ) -> None:
        self.session = session
        self.mattermost = mattermost or MattermostService(session)

    async def close(self) -> None:
        await self.mattermost.close()

    async def tick(self, now: datetime | None = None) -> OpruimTickResult:
        now = now or datetime.now(UTC)
        result = OpruimTickResult()
        stmt = select(DebatSessie.id, DebatSessie.channel_id).where(
            DebatSessie.channel_id.is_not(None),
            DebatSessie.aanvang.is_not(None),
            DebatSessie.aanvang <= now - AFTER_DEBATE,
            DebatSessie.aanvang >= now - LOOK_BACK,
        )
        rows = (await self.session.execute(stmt)).all()
        if not rows or not await self.mattermost.is_enabled():
            return result
        for sessie_id, channel_id in rows:
            result.checked += 1
            try:
                if await self._archive_if_done(channel_id, now):
                    result.archived += 1
            except Exception:
                # One channel that breaks must not stop the others.
                result.errors += 1
                logger.exception(
                    "Kanaal %s van sessie %s niet opgeruimd", channel_id, sessie_id
                )
        return result

    async def _archive_if_done(self, channel_id: str, now: datetime) -> bool:
        channel = await self.mattermost.get_channel(channel_id)
        if channel is None:
            # Not readable now; the next round looks again.
            return False
        delete_at = channel.get("delete_at")
        if isinstance(delete_at, int) and delete_at > 0:
            # Archived already, by us or by someone else.
            return False
        last_post_at = channel.get("last_post_at")
        if not isinstance(last_post_at, int):
            return False
        if last_post_at > _ms(now - QUIET):
            if await self._notice_is_last(channel_id, last_post_at):
                # The message went out and the archiving failed: again,
                # without a second message.
                return await self.mattermost.archive_channel(channel_id)
            return False
        post_id = await self.mattermost.send_channel_message(
            channel_id, MESSAGE, props={PROP: True}
        )
        if not post_id:
            return False
        if not await self.mattermost.archive_channel(channel_id):
            return False
        logger.info("Debatkanaal %s gearchiveerd", channel_id)
        return True

    async def _notice_is_last(self, channel_id: str, last_post_at: int) -> bool:
        posts = await self.mattermost.get_channel_posts_since(
            channel_id, last_post_at - 1, per_page=5
        )
        if not posts:
            return False
        last = max(posts, key=lambda p: p.get("create_at") or 0)
        props = last.get("props")
        return isinstance(props, dict) and bool(props.get(PROP))
