"""Archive the channel of a debate once nobody needs it any more.

Every debate someone follows gets a channel of its own, so the sidebar of
whoever joins a few fills up within weeks. A channel is archived when two
things hold:

* the debate took place at least `AFTER_DEBATE` ago, which leaves room for
  the votes, usually the Tuesday after, and the votes per fractie the
  morning after that;
* nothing was said in it for `QUIET`: a channel where people still talk
  about the debate stays.

When the debate took place is read again from the TK API, for each channel
that looks done by the date on the sessie. That date is the one of when
the channel was set up, and 10% of activiteiten are moved or cancelled: a
debate that was moved to a later date keeps a channel of people waiting for
it. When the TK API cannot be read the channel waits for the next round.

Archived, not deleted: the messages stay, and a system admin can bring the
channel back. Just before, one message says why, so whoever opens it later
knows what happened. When the archiving fails, that message is taken away
again, so it never stands in a channel that stays open, and the channel is
tried again a day later.

A channel archived here is marked on the sessie (`kanaal_gearchiveerd_at`)
and never looked at again: one that an admin brought back stays.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.models.debat_sessie import DebatSessie
from bouwmeester.services import tk_activiteit
from bouwmeester.services.mattermost_service import MattermostService

logger = logging.getLogger(__name__)

AFTER_DEBATE = timedelta(days=30)
QUIET = timedelta(days=14)
# Debates set up longer ago than this are not looked at again. A debate
# moved by more than this is rare enough to leave to a human.
LOOK_BACK = timedelta(days=120)
# After an attempt that failed, the channel waits this long. Kept in the
# process only: a restart tries again sooner, which does no harm.
AFTER_FAILURE = timedelta(days=1)

_HTTP_TIMEOUT = 15.0

MESSAGE = (
    "🗄️ Dit kanaal wordt gearchiveerd. Het debat is meer dan "
    f"{AFTER_DEBATE.days} dagen geleden en hier is {QUIET.days} dagen niets "
    "gezegd. Een beheerder kan het kanaal terugzetten."
)

# Per channel, not before when it is tried again.
_failed: dict[str, datetime] = {}


@dataclass
class CleanupTickResult:
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


class DebateChannelCleanup:
    def __init__(
        self, session: AsyncSession, mattermost: MattermostService | None = None
    ) -> None:
        self.session = session
        self.mattermost = mattermost or MattermostService(session)

    async def close(self) -> None:
        await self.mattermost.close()

    async def tick(
        self, now: datetime | None = None, client: httpx.AsyncClient | None = None
    ) -> CleanupTickResult:
        now = now or datetime.now(UTC)
        result = CleanupTickResult()
        stmt = select(DebatSessie).where(
            DebatSessie.channel_id.is_not(None),
            DebatSessie.kanaal_gearchiveerd_at.is_(None),
            DebatSessie.aanvang.is_not(None),
            DebatSessie.aanvang <= now - AFTER_DEBATE,
            DebatSessie.aanvang >= now - LOOK_BACK,
        )
        sessies = list((await self.session.execute(stmt)).scalars().all())
        sessies = [s for s in sessies if _failed.get(s.channel_id, now) <= now]
        if not sessies or not await self.mattermost.is_enabled():
            return result
        own = client is None
        client = client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
        try:
            for sessie in sessies:
                result.checked += 1
                try:
                    await self._clean(sessie, now, client, result)
                except Exception:
                    # One channel that breaks must not stop the others.
                    await self.session.rollback()
                    result.errors += 1
                    logger.exception(
                        "Kanaal %s van sessie %s niet opgeruimd",
                        sessie.channel_id,
                        sessie.id,
                    )
        finally:
            if own:
                await client.aclose()
        return result

    async def _clean(
        self,
        sessie: DebatSessie,
        now: datetime,
        client: httpx.AsyncClient,
        result: CleanupTickResult,
    ) -> None:
        channel_id = sessie.channel_id
        assert channel_id is not None
        channel = await self.mattermost.get_channel(channel_id)
        if channel is None:
            # Not readable now; the next round looks again.
            return
        delete_at = channel.get("delete_at")
        if isinstance(delete_at, int) and delete_at > 0:
            # Archived by someone else. Marked, so it is not asked again.
            await self._mark(sessie, now)
            return
        last_post_at = channel.get("last_post_at")
        if not isinstance(last_post_at, int) or last_post_at > _ms(now - QUIET):
            return
        if not await self._debate_is_over(sessie, now, client):
            return

        post_id = await self.mattermost.send_channel_message(channel_id, MESSAGE)
        if not post_id:
            self._failure(channel_id, now, result, "melding niet geplaatst")
            return
        if not await self.mattermost.archive_channel(channel_id):
            # Not left standing in a channel that stays open.
            await self.mattermost.delete_post(post_id)
            self._failure(channel_id, now, result, "archiveren geweigerd")
            return
        await self._mark(sessie, now)
        result.archived += 1
        logger.info("Debatkanaal %s gearchiveerd", channel_id)

    async def _debate_is_over(
        self, sessie: DebatSessie, now: datetime, client: httpx.AsyncClient
    ) -> bool:
        """Whether the debate, as the TK API has it now, is long enough ago.

        A moved debate is followed to where it went, one step. Moved again,
        or moved without saying where: not over, as far as can be known.
        """
        try:
            activiteit = await tk_activiteit.fetch_activiteit(
                sessie.activiteit_id, client
            )
            if (
                activiteit is not None
                and activiteit.status == tk_activiteit.STATUS_MOVED
            ):
                if not activiteit.vervangen_door:
                    return False
                activiteit = await tk_activiteit.fetch_activiteit(
                    activiteit.vervangen_door[-1], client
                )
                if activiteit is None or activiteit.status == (
                    tk_activiteit.STATUS_MOVED
                ):
                    return False
        except tk_activiteit.TkApiError:
            logger.warning(
                "Activiteit %s niet te lezen; kanaal %s blijft deze ronde staan",
                sessie.activiteit_id,
                sessie.channel_id,
            )
            return False
        if activiteit is None:
            # Gone from the TK API altogether: nothing to wait for.
            return True
        if activiteit.status == tk_activiteit.STATUS_CANCELLED:
            return True
        return activiteit.aanvang is not None and activiteit.aanvang <= (
            now - AFTER_DEBATE
        )

    def _failure(
        self, channel_id: str, now: datetime, result: CleanupTickResult, why: str
    ) -> None:
        result.errors += 1
        _failed[channel_id] = now + AFTER_FAILURE
        logger.warning("Debatkanaal %s niet gearchiveerd: %s", channel_id, why)

    async def _mark(self, sessie: DebatSessie, now: datetime) -> None:
        sessie.kanaal_gearchiveerd_at = now
        await self.session.commit()


def reset() -> None:
    """Forget the channels that failed. For tests."""
    _failed.clear()
