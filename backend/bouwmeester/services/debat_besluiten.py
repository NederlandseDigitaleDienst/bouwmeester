"""The decisions of a procedurevergadering, per agendapunt, in one message.

A procedurevergadering is the chairman going through the agenda while the
committee agrees, plans a briefing, moves a debate or asks for a letter.
Debat Direct gives it a start and an end and nothing in between, so the
transcription puts forty minutes of the chairman under one message and its
continuations: a wall of text in which nobody finds whether their debate
was moved.

This puts it in order. While the meeting runs, a few times, the model reads
what was said so far and one message says per agendapunt what was decided,
written again in place as more comes in. When the meeting is over the
final overview, with a short samenvatting, is posted as a new message at
the bottom of the channel, and the one that grew is taken away. Both are
pinned.

The text of the transcription stays as it is. It is what people can follow
live, and it is what is left when the model is away: then this message is
simply not there, or stays as it was, and nothing else changes.

Everything that was done is kept on the sessie (`DebatSessie.besluiten`)
and a message is remembered the moment it exists, so a restart does not
post it a second time.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.models.debat_sessie import DebatSessie, DebatSpreekbeurt
from bouwmeester.services import debat_direct as dd
from bouwmeester.services.debat_kanaal_service import AMSTERDAM
from bouwmeester.services.debat_transcript_service import (
    AFTER_END,
    MESSAGE_MAX,
    load_turns,
)
from bouwmeester.services.llm.base import (
    BaseLLMService,
    DebatAgendapunt,
    DebatBesluitenResult,
)
from bouwmeester.services.mattermost_service import (
    MattermostService,
    PostNotFoundError,
)
from bouwmeester.services.mattermost_utils import escape_mattermost_prose

logger = logging.getLogger(__name__)

# How often the overview is made again while the meeting runs. The chairman
# goes through an agendapunt in a minute or two; more often than this is
# model calls for one sentence more.
EVERY = timedelta(minutes=3)
# And only when this much more was said: a pause is no reason for a call.
MIN_GROWTH = 300
# How long one reading may take. The worker reads the questions of other
# debates in the same round.
TIMEOUT = 90.0
# After a reading that failed: wait this long, twice as long after every
# failure, at most `RETRY_MAX`.
RETRY_FIRST = timedelta(minutes=1)
RETRY_MAX = timedelta(minutes=8)
# Readings at the end before giving up on the final overview. The text of
# the transcription is all there anyway.
FINAL_ATTEMPTS = 4

_HEAD_RUNNING = "📋 **Besluiten tot nu toe**"
_HEAD_FINAL = "📋 **Besluiten van de procedurevergadering**"
_FOOTER = (
    "_Samengevat uit de ondertiteling. Kan fouten bevatten; "
    "de besluitenlijst van de commissie is leidend._"
)
_NAME_IN_KOP = re.compile(r"\*\*(.+?)\*\*")


def _hhmm(moment: datetime) -> str:
    return moment.astimezone(AMSTERDAM).strftime("%H:%M")


def render_besluiten(
    punten: list[DebatAgendapunt],
    *,
    af: bool,
    samenvatting: str = "",
    bijgewerkt: datetime | None = None,
) -> str:
    """The message: per agendapunt a bold line, the decisions as bullets."""
    if af:
        head = _HEAD_FINAL
    else:
        head = _HEAD_RUNNING + (
            f" · bijgewerkt {_hhmm(bijgewerkt)}" if bijgewerkt else ""
        )
    lines = [head]
    if af and samenvatting:
        lines.append(escape_mattermost_prose(" ".join(samenvatting.split())))
    blocks: list[str] = []
    for punt in punten:
        nummer = f"{escape_mattermost_prose(punt.nummer)}. " if punt.nummer else ""
        block = [f"**{nummer}{escape_mattermost_prose(punt.onderwerp)}**"]
        if punt.besluiten:
            block += [
                f"- {escape_mattermost_prose(' '.join(b.split()))}"
                for b in punt.besluiten
            ]
        else:
            block.append("- _geen besluit gehoord_")
        blocks.append("\n".join(block))
    if not blocks:
        blocks.append("_Nog geen agendapunt besproken._")
    message = "\n\n".join(["\n".join(lines), *blocks, _FOOTER])
    if len(message) > MESSAGE_MAX:
        room = MESSAGE_MAX - len(_FOOTER) - 10
        message = message[:room].rsplit("\n", 1)[0] + "\n…\n\n" + _FOOTER
    return message


def _speaker(turn) -> str:  # type: ignore[no-untyped-def]
    """Who a turn is of, for the model: the chairman, or the name in its
    first line."""
    if turn.chair or turn.closing:
        return "Voorzitter"
    found = _NAME_IN_KOP.search(turn.kop or "")
    return found.group(1) if found else "Lid"


async def meeting_text(
    session: AsyncSession, sessie_id: uuid.UUID, parts: list[str]
) -> str:
    """Everything said in the meeting so far, one paragraph per turn."""
    paragraphs: list[str] = []
    for part in parts:
        for turn in await load_turns(session, sessie_id, part):
            text = turn.text.strip()
            if text:
                paragraphs.append(f"[{_speaker(turn)}] {text}")
    return "\n\n".join(paragraphs)


async def meeting_is_over(
    session: AsyncSession, sessie_id: uuid.UUID, parts: list[str], now: datetime
) -> bool:
    """Whether every part ended long enough ago that no text can follow."""
    if not parts:
        return False
    rows = (
        await session.execute(
            select(
                DebatSpreekbeurt.debat_direct_id, DebatSpreekbeurt.event_start
            ).where(
                DebatSpreekbeurt.sessie_id == sessie_id,
                DebatSpreekbeurt.event_type == dd.EVENT_DEBATE_END,
            )
        )
    ).all()
    ends: dict[str, datetime] = {}
    for part, start in rows:
        ends[part] = max(ends.get(part, start), start)
    if any(part not in ends for part in parts):
        return False
    return now > max(ends.values()) + AFTER_END


def _moment(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else None


class DebatBesluiten:
    """Keeps the overview of one procedurevergadering up to date."""

    def __init__(
        self,
        session: AsyncSession,
        mattermost: MattermostService,
        llm: Callable[[], Awaitable[BaseLLMService | None]],
    ) -> None:
        self.session = session
        self.mattermost = mattermost
        # Asked for only when a reading is due: nearly every round has none.
        self._llm = llm

    async def update(
        self,
        sessie_id: uuid.UUID,
        onderwerp: str,
        agenda: Callable[[], Awaitable[list[str]]],
        now: datetime,
    ) -> bool:
        """Do what is due for this meeting. ``True`` when a message changed.

        The caller has decided that this is a procedurevergadering.
        `agenda` gives its agendapunten; asked only when a reading is due.
        """
        sessie = await self.session.get(DebatSessie, sessie_id, populate_existing=True)
        if sessie is None or sessie.channel_id is None:
            return False
        state = dict(sessie.besluiten or {})
        if state.get("af"):
            return False
        niet_voor = _moment(state.get("niet_voor"))
        if niet_voor is not None and now < niet_voor:
            return False

        parts = list(sessie.debat_direct_ids or [])
        af = await meeting_is_over(self.session, sessie_id, parts, now)
        tekst = await meeting_text(self.session, sessie_id, parts)
        if not tekst:
            if af:
                # Over without a word read: nothing to put in order.
                await self._keep(sessie, {**state, "af": True})
            return False
        if not af:
            gelezen_at = _moment(state.get("gelezen_at"))
            grown = len(tekst) - int(state.get("gelezen_tot") or 0)
            if grown < MIN_GROWTH:
                return False
            if gelezen_at is not None and now - gelezen_at < EVERY:
                return False

        llm = await self._llm()
        if llm is None:
            return False
        eerder = [
            DebatAgendapunt.model_validate(p)
            for p in state.get("agendapunten") or []
            if isinstance(p, dict)
        ]
        try:
            result = await asyncio.wait_for(
                llm.vat_procedurevergadering_samen(
                    onderwerp=onderwerp,
                    agenda=await agenda(),
                    tekst=tekst,
                    eerder=eerder,
                    af=af,
                ),
                timeout=TIMEOUT,
            )
        except TimeoutError:
            result = DebatBesluitenResult(fout="te_traag")
        if result.fout:
            logger.warning(
                "Besluiten van procedurevergadering %s niet te lezen (%s)",
                sessie_id,
                result.fout,
            )
            await self._failed(sessie, state, now, af)
            return False

        state.update(
            gelezen_tot=len(tekst),
            gelezen_at=now.isoformat(),
            agendapunten=[p.model_dump() for p in result.agendapunten],
            pogingen=0,
            niet_voor=None,
        )
        if af:
            return await self._final(sessie, state, result)
        if not result.agendapunten:
            await self._keep(sessie, state)
            return False
        return await self._running(sessie, state, result, now)

    async def _running(
        self,
        sessie: DebatSessie,
        state: dict,
        result: DebatBesluitenResult,
        now: datetime,
    ) -> bool:
        message = render_besluiten(result.agendapunten, af=False, bijgewerkt=now)
        post_id = state.get("post_id")
        if state.get("weg"):
            # Someone took the message away. Not posted again: the final
            # overview comes at the end all the same.
            await self._keep(sessie, state)
            return False
        if post_id:
            if not await self.mattermost.update_post(post_id, message):
                try:
                    await self.mattermost.get_post(post_id)
                except PostNotFoundError:
                    state.update(post_id=None, weg=True)
                    await self._keep(sessie, state)
                    return False
                # Written on the next reading. What was read is kept, so
                # a Mattermost that is down is not a model call per round.
                await self._keep(sessie, state)
                return False
            await self._keep(sessie, state)
            return True
        post_id = await self.mattermost.send_channel_message(sessie.channel_id, message)
        if not post_id:
            await self._keep(sessie, state)
            return False
        # At once: a message that exists has to be known, or a restart
        # posts it a second time.
        state["post_id"] = post_id
        await self._keep(sessie, state)
        await self.mattermost.pin_post(post_id)
        return True

    async def _final(
        self, sessie: DebatSessie, state: dict, result: DebatBesluitenResult
    ) -> bool:
        if not result.agendapunten and not state.get("post_id"):
            # Nothing decided that the model could find, and nothing in the
            # channel that says otherwise. The transcript is there.
            await self._keep(sessie, {**state, "af": True})
            return False
        if not state.get("eind_post_id"):
            message = render_besluiten(
                result.agendapunten, af=True, samenvatting=result.samenvatting
            )
            post_id = await self.mattermost.send_channel_message(
                sessie.channel_id, message
            )
            if not post_id:
                # The reading is kept; the next round posts it again from
                # the model, which is the same text or better.
                await self._keep(sessie, state)
                return False
            state["eind_post_id"] = post_id
            await self._keep(sessie, state)
            await self.mattermost.pin_post(post_id)
        live = state.get("post_id")
        if live:
            # The one that grew says the same, less well, higher up.
            if not await self._remove(live):
                await self._keep(sessie, state)
                return True
            state["post_id"] = None
        state["af"] = True
        await self._keep(sessie, state)
        return True

    async def _failed(
        self, sessie: DebatSessie, state: dict, now: datetime, af: bool
    ) -> None:
        pogingen = int(state.get("pogingen") or 0) + 1
        wait = min(RETRY_FIRST * 2 ** (pogingen - 1), RETRY_MAX)
        state.update(pogingen=pogingen, niet_voor=(now + wait).isoformat())
        if af and pogingen >= FINAL_ATTEMPTS:
            # The overview that grew stays as it was, and so does the
            # transcript; there is nothing better to put in its place.
            logger.warning(
                "Eindoverzicht van procedurevergadering %s opgegeven na %d pogingen",
                sessie.id,
                pogingen,
            )
            state["af"] = True
        await self._keep(sessie, state)

    async def _remove(self, post_id: str) -> bool:
        """Take a message away. ``True`` also when it was gone already."""
        if await self.mattermost.delete_post(post_id):
            return True
        try:
            await self.mattermost.get_post(post_id)
        except PostNotFoundError:
            return True
        return False

    async def _keep(self, sessie: DebatSessie, state: dict) -> None:
        # A new dict: a JSON column only notices a value that is replaced.
        sessie.besluiten = dict(state)
        await self.session.commit()
