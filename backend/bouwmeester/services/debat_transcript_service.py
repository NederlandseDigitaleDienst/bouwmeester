"""Put what is said under the message of who says it.

The timeline posts one message per turn at speaking, with only a first
line: who and when. This reads the subtitles of the stream, files each line
under the turn it was spoken in, and writes the message again with the text
below the first line. A turn that goes on gets a message that grows.

Everything is kept in the database first and written to Mattermost from
there. Every line is a row with the turn it belongs to; the text of a turn
is its lines in order. A turn holds how much of that is in the channel, so
a message that could not be written is simply written on the next round,
and a restart continues where the reading stood.

Which turn a line belongs to is first decided by time. Around a change of
speaker the voices decide again (`debat_stemmen_service`), and a line can
move to the turn before or after. Then both messages are written anew.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import case, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import aggregate_order_by, insert
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.models.debat_markering import DebatMarkering
from bouwmeester.models.debat_sessie import (
    DebatOndertitel,
    DebatSessie,
    DebatSpreekbeurt,
)
from bouwmeester.services import debat_audio as audio
from bouwmeester.services import debat_direct as dd
from bouwmeester.services import debat_subtitles as subs
from bouwmeester.services.debat_statusregel import SCHEIDING, voeg_samen
from bouwmeester.services.debat_transcript import (
    append_text,
    fit_messages,
    place_cues,
    render,
    render_closing,
    split_text,
    text_key,
)
from bouwmeester.services.debat_vraag_service import (
    statusblok_voor_post,
    vervang_statusblok,
)
from bouwmeester.services.mattermost_service import (
    MattermostService,
    PostNotFoundError,
)

logger = logging.getLogger(__name__)

_SPEAKING = (dd.EVENT_SPEAKER, dd.EVENT_INTERRUPTER)
_CLOSING = (dd.EVENT_SUSPENDED, dd.EVENT_DEBATE_END)
# Messages the chairman's words go under. Kept here and not imported from
# the timeline, which imports this module.
_CHAIR_OPENS = (
    dd.EVENT_CHAIRMAN,
    dd.EVENT_DEBATE_START,
    dd.EVENT_CONTINUED,
    dd.EVENT_CHAIRMAN_CHANGE,
)
# How far back the subtitles are read when a debate is first seen. The same
# patience the timeline has for what it missed.
READ_BACK = timedelta(minutes=10)
# Files per round. A round normally brings three; this is for catching up,
# and every file is a request the other debates wait for.
MAX_SEGMENTS = 30
# How long a stream without a subtitle track is left alone before looking
# again.
LOOK_AGAIN = timedelta(minutes=5)
# How long after the end of a part its subtitles are still read. What was
# said before the end comes in within about forty seconds; after this
# nothing of the part can still arrive.
AFTER_END = timedelta(minutes=3)
# See `_read`: how long nothing may happen before a part counts as over.
SILENT_IS_OVER = timedelta(hours=1)
# Mattermost refuses a message over 16383 characters. Only reachable by
# late words piling into a message that may not continue below itself.
MESSAGE_MAX = 16000
# In `tekst_geplaatst_hash`, where the digest of the text goes: the first
# line of this turn changed, so every message of it is written again
# whatever its text. No digest is this word, so the turn counts as not
# written until it has been.
WRITE_AGAIN = "opnieuw"
# What is counted under a message changed, and the message is written again
# for it (`DebatTranscript.write_counts`). Messages per round of the
# timeline: a round is ten seconds and each message is two requests at
# most, so a round spends twenty requests on this at worst. People tick
# questions off one at a time; more than this waits a round.
COUNTS_PER_ROUND = 10
# And seconds per round, looked at before each message: the round has the
# debates of today to get back to. A request that hangs takes what the
# client allows, so a round can overrun this by one message.
COUNTS_BUDGET = 5.0
# The clock that budget is counted on.
_clock = time.monotonic
# A message that could not be written is tried again after this long, twice
# as long after every failure and a quarter of an hour at most: after 30
# seconds, 1, 2, 4, 8, 15 and 15 minutes, and 15 more. That is nine tries in
# an hour; then its count is left as it is until someone reacts again.
COUNT_RETRY_FIRST = timedelta(seconds=30)
COUNT_RETRY_MAX = timedelta(minutes=15)
COUNT_ATTEMPTS = 9


@dataclass
class Turn:
    """A message of the timeline and the rows whose text belongs in it."""

    row_id: uuid.UUID
    post_id: str
    kop: str
    key: tuple[str, str]
    geplaatst: int
    # The digest of the text that is in the channel, or None for a message
    # from before that was kept.
    placed_key: str | None
    vervolg: list[str]
    # When the turn began, and when it was read for questions.
    start: datetime
    beoordeeld_at: datetime | None = None
    # Of an answer of the bewindspersoon: how many characters of it were
    # read for toezeggingen so far (`antwoord_gelezen_tot`).
    gelezen_tot: int = 0
    texts: list[str] = field(default_factory=list)
    # The rows those texts are of, in the same order.
    rows: list[uuid.UUID] = field(default_factory=list)
    # A suspension or the end: the text is the chairman's, and only the
    # last of it is shown.
    closing: bool = False
    # The chairman has the floor: the start, a resumption, or the chair
    # taking the word. Shown like a turn, but nobody's to ask questions in.
    chair: bool = False

    @property
    def is_member(self) -> bool:
        """A turn of a member or a bewindspersoon, to be read for questions."""
        return not (self.closing or self.chair)

    @property
    def text(self) -> str:
        joined = ""
        for text in self.texts:
            joined = append_text(joined, text)
        return joined

    def has_grown(self, text: str) -> bool:
        """Whether what is in the channel is still how `text` begins.

        Then the messages that are full can stay. Not when a line moved to
        or from this turn: the text changed in the middle, and every
        message of the turn has to be written again.
        """
        if len(text) < self.geplaatst:
            return False
        if self.placed_key is None:
            return True
        return text_key(text[: self.geplaatst]) == self.placed_key

    def is_written(self, text: str) -> bool:
        return len(text) == self.geplaatst and self.has_grown(text)


class DebatTranscript:
    def __init__(
        self,
        session: AsyncSession,
        mattermost: MattermostService,
        stemmen=None,  # type: ignore[no-untyped-def]
    ) -> None:
        self.session = session
        self.mattermost = mattermost
        # A `DebatStemmen`, or None when voices are not told apart: then a
        # line stays in the turn the time put it in.
        self.stemmen = stemmen

    async def update(
        self,
        sessie: DebatSessie,
        debates: dict[str, dd.DdDebat],
        client: httpx.AsyncClient,
        now: datetime,
        result,  # type: ignore[no-untyped-def]
    ) -> None:
        """Read what is new in the subtitles of every part and show it."""
        sessie_id = sessie.id
        channel_id = sessie.channel_id
        if channel_id is None:
            return
        for debate_id in list(sessie.debat_direct_ids or []):
            try:
                changed = await self._read(sessie, debate_id, debates, client, now)
            except subs.SubtitleError:
                # The timeline does not depend on the text. Not counted as
                # an error either: a debate without subtitles is not stuck.
                logger.warning("Ondertitels van %s niet te lezen", debate_id)
                changed = False
            if changed:
                await self.session.commit()
            if self.stemmen is not None:
                await self._listen(sessie, debate_id, client, now)
            # Also when nothing is new: what could not be written before
            # is written now.
            await self.write(sessie_id, channel_id, debate_id, result)

    async def _listen(
        self,
        sessie: DebatSessie,
        debate_id: str,
        client: httpx.AsyncClient,
        now: datetime,
    ) -> None:
        """Let the voices decide about the lines around a change of speaker.

        Nothing depends on this. Whatever goes wrong, a line stays where
        the time put it and the round goes on.
        """
        entry = (sessie.ondertitels or {}).get(debate_id) or {}
        audio_url = entry.get("audio")
        if not audio_url:
            return
        try:
            # A savepoint: half a decision is not kept, and what was read
            # before it is not undone.
            async with self.session.begin_nested():
                await self.stemmen.update(sessie.id, debate_id, audio_url, client, now)
            await self.session.commit()
        except Exception as exc:
            # Only what kind of error: the error itself may carry a piece
            # of what was being worked on, and audio and voices are not
            # written anywhere.
            logger.warning(
                "Stemmen van %s niet te onderscheiden (%s)",
                debate_id,
                type(exc).__name__,
            )

    async def _read(
        self,
        sessie: DebatSessie,
        debate_id: str,
        debates: dict[str, dd.DdDebat],
        client: httpx.AsyncClient,
        now: datetime,
    ) -> bool:
        state = dict(sessie.ondertitels or {})
        entry = dict(state.get(debate_id) or {})

        debat = debates.get(debate_id)
        if not entry.get("url"):
            looked = _moment(entry.get("gekeken"))
            if looked is not None and now - looked < LOOK_AGAIN:
                return False
            if debat is None or not debat.stream_url:
                return False
            master = await subs.fetch_text(client, debat.stream_url)
            # A stream without a subtitle track is looked at again later,
            # not on every round: the track may not be there yet at the
            # start.
            entry = {
                "url": subs.find_subtitle_playlist(master, debat.stream_url) or "",
                "offset_ms": round(debat.stream_offset.total_seconds() * 1000),
                "gekeken": now.isoformat(),
                "audio": _audio_of(debat),
            }
            # A new dict every time: a JSON column only notices a value
            # that is replaced, not one that is changed in place.
            sessie.ondertitels = {**state, debate_id: dict(entry)}
            if not entry["url"]:
                logger.info("Debat %s heeft geen ondertitelspoor", debate_id)
                return True

        if debat is not None and _audio_of(debat) != entry.get("audio", ""):
            # Also for a part that was first seen before the audio was
            # kept, and for a room whose address changed.
            entry["audio"] = _audio_of(debat)
            sessie.ondertitels = {**state, debate_id: dict(entry)}

        rows = (
            await self.session.execute(
                select(
                    DebatSpreekbeurt.id,
                    DebatSpreekbeurt.event_type,
                    DebatSpreekbeurt.event_start,
                )
                .where(
                    DebatSpreekbeurt.sessie_id == sessie.id,
                    DebatSpreekbeurt.debat_direct_id == debate_id,
                )
                .order_by(*ORDER)
            )
        ).all()
        if not rows:
            return False

        position = _moment(entry.get("positie"))
        # Past the end of the part there is nothing left to read: a line is
        # in the file it starts in, and that file has been read by then.
        ends = [r[2] for r in rows if r[1] == dd.EVENT_DEBATE_END]
        if debat is not None and debat.ended_at is not None:
            ends.append(debat.ended_at)
        if ends and position is not None and position > max(ends):
            return False
        # And by the clock. The stream stops when the debate does, so the
        # last file ends at or just before the end, the position never
        # gets past it, and the check above alone would have the playlist
        # fetched on every round until the debate drops out of sight.
        if ends and now > max(ends) + AFTER_END:
            return False
        # The address belongs to the room, not to the debate: the next
        # debate in that room is on the same one. Without an end, a part
        # in which nothing has happened for this long is taken to be over,
        # so that someone else's debate does not end up in this channel.
        if position is not None and position - rows[-1][2] > SILENT_IS_OVER:
            return False

        cues, position = await subs.fetch_since(
            client,
            entry["url"],
            position,
            max_segments=MAX_SEGMENTS,
            since=max(rows[0][2], now - READ_BACK),
        )
        if position is None or position.isoformat() == entry.get("positie"):
            return False

        offset = timedelta(milliseconds=entry.get("offset_ms") or 0)
        placed = place_cues(cues, [(r[0], r[2]) for r in rows], offset)
        if placed:
            await self.session.execute(
                insert(DebatOndertitel)
                .values(
                    [
                        {
                            "sessie_id": sessie.id,
                            "debat_direct_id": debate_id,
                            "start": cue.start,
                            "einde": cue.end,
                            "tekst": cue.text,
                            "spreekbeurt_id": row_id,
                        }
                        for row_id, cue in placed
                    ]
                )
                # A line that is there already was read by another worker
                # in the same round, as happens during a deploy.
                .on_conflict_do_nothing(constraint="uq_debat_ondertitel_start")
            )
            await derive_text(self.session, {row_id for row_id, _ in placed})
        entry["positie"] = position.isoformat()
        sessie.ondertitels = {**state, debate_id: dict(entry)}
        return True

    async def write(
        self,
        sessie_id: uuid.UUID,
        channel_id: str,
        debate_id: str,
        result,  # type: ignore[no-untyped-def]
    ) -> None:
        """Make the messages of one part say what the rows say.

        The one place the text of a turn is put into its messages: first
        line, text, and what was marked counted under it. Whoever changes
        a first line changes the row and leaves the message to this. What
        is counted under a message that does not change otherwise is
        written by `write_counts`, one message at a time.
        """
        turns = await load_turns(self.session, sessie_id, debate_id)
        if all(turn.is_written(turn.text) for turn in turns):
            return
        # The last thing the timeline put in the channel, of any part and
        # any kind. Only the turn that is that can continue below itself.
        newest = (
            await self.session.execute(
                select(DebatSpreekbeurt.id)
                .where(
                    DebatSpreekbeurt.sessie_id == sessie_id,
                    DebatSpreekbeurt.post_id.is_not(None),
                )
                .order_by(*(column.desc() for column in ORDER))
                .limit(1)
            )
        ).scalar_one_or_none()
        for turn in turns:
            text = turn.text
            if turn.is_written(text):
                continue
            placed = {
                "tekst_geplaatst": len(text),
                "tekst_geplaatst_hash": text_key(text),
            }
            if turn.closing:
                # `tekst_geplaatst` of this row counts the chairman's words
                # shown under it, which are kept on other rows.
                closing = render_closing(turn.kop, text)
                # The message of the end is where the toezeggingen from the
                # chairman's list hang. Written again from the words alone,
                # it would lose their count.
                blok = await statusblok_voor_post(self.session, turn.post_id)
                if blok:
                    room = MESSAGE_MAX - len(blok) - len(SCHEIDING) - 3
                    closing = voeg_samen(closing[:room], blok)
                if await self._rewrite(turn.post_id, closing):
                    await self._keep(turn.row_id, **placed)
                else:
                    logger.warning(
                        "Woorden van de voorzitter bij %s niet geplaatst", turn.row_id
                    )
                    result.fouten += 1
                continue
            pieces = split_text(text)
            if turn.row_id != newest:
                # A next message would land below whatever came after.
                pieces = fit_messages(pieces, 1 + len(turn.vervolg))
            # Full messages never change while the text only grows: only
            # the last one that exists is written again, and whatever comes
            # after it is new. A text that changed in the middle is cut
            # anew from the start, and every message is written again.
            grown = turn.has_grown(text)
            first = len(turn.vervolg) if grown else 0
            vervolg = list(turn.vervolg)
            done = True
            for number in range(first, len(pieces)):
                message = render(turn.kop, pieces[number], vervolg=number > 0)
                if number <= len(vervolg):
                    target = turn.post_id if number == 0 else vervolg[number - 1]
                    # A message is also where what was marked in it is
                    # counted: the questions of the turn under the first,
                    # a toezegging under the message that holds its quote.
                    # Writing it again from the text alone would wipe that,
                    # so it goes back in, below the text and outside what
                    # is cut into messages.
                    blok = await statusblok_voor_post(self.session, target)
                    if blok:
                        # Room for the rule and the block: what Mattermost
                        # refuses for its length is cut from the text.
                        room = MESSAGE_MAX - len(blok) - len(SCHEIDING) - 3
                        message = message[:room]
                    message = voeg_samen(message, blok)
                    ok = await self._rewrite(target, message)
                else:
                    post_id = await self.mattermost.send_channel_message(
                        channel_id, message
                    )
                    ok = bool(post_id)
                    if post_id:
                        vervolg.append(post_id)
                        result.berichten += 1
                        # At once: a message that exists has to be known,
                        # or a restart makes it a second time.
                        await self._keep(turn.row_id, vervolg_post_ids=list(vervolg))
                if not ok:
                    logger.warning(
                        "Tekst van spreekbeurt %s niet geplaatst", turn.row_id
                    )
                    result.fouten += 1
                    done = False
                    break
            # A turn that lost lines can need fewer messages than it has. A
            # next message with nothing left under it is taken away: it
            # would say "vervolg" and then nothing.
            while done and not grown and len(vervolg) >= len(pieces):
                if not await self._remove(vervolg[-1]):
                    logger.warning(
                        "Vervolgbericht van spreekbeurt %s niet verwijderd", turn.row_id
                    )
                    result.fouten += 1
                    done = False
                    break
                vervolg.pop()
                await self._keep(turn.row_id, vervolg_post_ids=list(vervolg))
            if done:
                await self._keep(turn.row_id, **placed)
            # A turn that could not be written does not hold up the ones
            # after it: it is tried again on a later round.

    async def write_counts(
        self,
        result,  # type: ignore[no-untyped-def]
        now: datetime | None = None,
    ) -> None:
        """Put what is counted under a message under it, where that changed.

        The marking used to do this itself, from its own loop: read the
        message, replace the block, write it back. Since an answer is read
        while it goes on, the transcription can write the next lines of
        that message in between, and what was written back was those
        lines short until the turn grew again, or for good. So the
        marking leaves a message of a turn alone and its row without
        `statusregel_at`, and every round of the timeline comes here,
        after its own work.

        That makes this process the one writer of a message: it writes
        the text of a turn (`write`) and then, here, the counts, one
        after the other. So reading a message and writing it back with
        another block is safe here where it was not there: nothing writes
        it in between.

        And that is all that is done. One message per row that is out of
        date; its text is taken as it stands in the channel and is never
        made anew from the rows, no other message of the turn or the part
        is touched, none is posted and none is taken away. A debate of
        last week was written by the code of last week, and a reaction of
        today changes the count under one message of it and nothing else.

        Which rows were out of date, and where each stood, is read before
        the message is written, and only a row that still stands there is
        marked as done: a count that changes while its message is being
        written is written again on a later round.

        Bounded three ways. At most `COUNTS_PER_ROUND` messages a round
        and `COUNTS_BUDGET` seconds. A message that cannot be written is
        tried again later and later, `COUNT_ATTEMPTS` times in about an
        hour, and then left as it is with one line in the log.
        """
        now = now or datetime.now(UTC)
        started = _clock()
        rows = (
            await self.session.execute(
                select(
                    DebatMarkering.id,
                    DebatMarkering.beurt_post_id,
                    DebatMarkering.status,
                    DebatMarkering.statusregel_pogingen,
                )
                .where(
                    DebatMarkering.thread_post_id.is_not(None),
                    DebatMarkering.statusregel_at.is_(None),
                    DebatMarkering.beurt_post_id.is_not(None),
                    or_(
                        DebatMarkering.statusregel_niet_voor.is_(None),
                        DebatMarkering.statusregel_niet_voor <= now,
                    ),
                )
                # What was never tried first, then what waited longest.
                .order_by(
                    DebatMarkering.statusregel_niet_voor.asc().nulls_first(),
                    DebatMarkering.created_at,
                )
                # More rows than messages: a turn can hold a dozen.
                .limit(COUNTS_PER_ROUND * 20)
            )
        ).all()
        stale: dict[str, list[tuple[uuid.UUID, str, int]]] = {}
        for markering_id, post_id, status, attempts in rows:
            if post_id not in stale and len(stale) >= COUNTS_PER_ROUND:
                continue
            stale.setdefault(post_id, []).append((markering_id, status, attempts or 0))
        for post_id, found in stale.items():
            if _clock() - started > COUNTS_BUDGET:
                break
            try:
                written = await vervang_statusblok(
                    self.session, self.mattermost, post_id
                )
            except Exception as exc:
                await self.session.rollback()
                # What kind of error, not its trace: this is tried again.
                logger.warning(
                    "Telling onder bericht %s niet geschreven (%s)",
                    post_id,
                    type(exc).__name__,
                )
                written = False
            attempts = max(row[2] for row in found) + 1
            given_up = not written and attempts >= COUNT_ATTEMPTS
            if given_up:
                result.fouten += 1
                logger.warning(
                    "Telling onder bericht %s na %d pogingen opgegeven",
                    post_id,
                    attempts,
                )
            for markering_id, status, _ in found:
                if written or given_up:
                    values = {
                        "statusregel_at": now,
                        "statusregel_pogingen": None,
                        "statusregel_niet_voor": None,
                    }
                else:
                    values = {
                        "statusregel_pogingen": attempts,
                        "statusregel_niet_voor": now
                        + min(COUNT_RETRY_FIRST * 2 ** (attempts - 1), COUNT_RETRY_MAX),
                    }
                await self.session.execute(
                    update(DebatMarkering)
                    # Not a row that changed since: its count is out of
                    # date again, and it starts anew.
                    .where(
                        DebatMarkering.id == markering_id,
                        DebatMarkering.status == status,
                        DebatMarkering.statusregel_at.is_(None),
                    )
                    .values(**values)
                )
            await self.session.commit()

    async def _rewrite(self, post_id: str, message: str) -> bool:
        """Write a message again. ``True`` also when it never can be.

        Someone can delete a message of the timeline. Trying that one
        again on every round, for the rest of the debate, helps nobody.
        """
        if await self.mattermost.update_post(post_id, message[:MESSAGE_MAX]):
            return True
        try:
            await self.mattermost.get_post(post_id)
        except PostNotFoundError:
            logger.info("Bericht %s is weg; de tekst komt er niet meer in", post_id)
            return True
        return False

    async def _remove(self, post_id: str) -> bool:
        """Take a message away. ``True`` also when it was gone already."""
        if await self.mattermost.delete_post(post_id):
            return True
        try:
            await self.mattermost.get_post(post_id)
        except PostNotFoundError:
            return True
        return False

    async def _keep(self, row_id: uuid.UUID, **values) -> None:  # type: ignore[no-untyped-def]
        await self.session.execute(
            update(DebatSpreekbeurt)
            .where(DebatSpreekbeurt.id == row_id)
            .values(**values)
        )
        await self.session.commit()


async def turn_of_message(
    session: AsyncSession, post_id: str, sessie_id: uuid.UUID | None = None
) -> Turn | None:
    """The turn a message is a message of, or ``None`` for a message the
    transcription does not write.

    The transcription writes the messages of the turns `load_turns`
    names: the first message of a turn, the ones it continues in, and a
    suspension or the end with the chairman's words. Every other message
    of the timeline is posted once and never written again. With
    `sessie_id` only the rows of that debate are looked through.
    """
    stmt = select(DebatSpreekbeurt.sessie_id, DebatSpreekbeurt.debat_direct_id).where(
        or_(
            DebatSpreekbeurt.post_id == post_id,
            DebatSpreekbeurt.vervolg_post_ids.contains([post_id]),
        )
    )
    if sessie_id is not None:
        stmt = stmt.where(DebatSpreekbeurt.sessie_id == sessie_id)
    row = (await session.execute(stmt.limit(1))).first()
    if row is None:
        return None
    for turn in await load_turns(session, row[0], row[1]):
        if post_id == turn.post_id or post_id in turn.vervolg:
            return turn
    return None


async def derive_text(session: AsyncSession, row_ids: set[uuid.UUID]) -> None:
    """Make the text of these turns what their lines say, in order.

    One statement, computed by the database from the lines as they are:
    two workers that both moved or added a line end up with the same text,
    whoever was last.
    """
    if not row_ids:
        return
    lines = (
        select(
            func.string_agg(
                DebatOndertitel.tekst,
                aggregate_order_by(literal(" "), DebatOndertitel.start),
            )
        )
        .where(DebatOndertitel.spreekbeurt_id == DebatSpreekbeurt.id)
        .scalar_subquery()
    )
    await session.execute(
        update(DebatSpreekbeurt)
        .where(DebatSpreekbeurt.id.in_(row_ids))
        .values(tekst=func.coalesce(lines, ""))
    )


# The order of the timeline: by moment, and within one second whatever is
# not someone speaking first.
ORDER = (
    DebatSpreekbeurt.event_start,
    case((DebatSpreekbeurt.event_type.in_(_SPEAKING), 1), else_=0),
    # And a fixed order for two people speaking in the same second, so
    # that reading and writing agree on who came last.
    DebatSpreekbeurt.event_type,
    DebatSpreekbeurt.object_id,
)


def _audio_of(debat: dd.DdDebat) -> str:
    """Where the audio of a part is, or nothing when it is not to be fetched."""
    url = debat.audio_url or ""
    return url if audio.is_trusted(url) else ""


def _moment(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else None


async def load_turns(
    session: AsyncSession, sessie_id: uuid.UUID, debate_id: str
) -> list[Turn]:
    """The messages of one part of a debate, each with the text that is its.

    The one place that says what a turn is. Writing the text and reading it
    for questions both go by this, so they cannot disagree about which
    words belong under which message.
    """
    rows = (
        await session.execute(
            select(
                DebatSpreekbeurt.id,
                DebatSpreekbeurt.event_type,
                DebatSpreekbeurt.object_id,
                DebatSpreekbeurt.event_start,
                DebatSpreekbeurt.post_id,
                DebatSpreekbeurt.kop,
                DebatSpreekbeurt.tekst,
                DebatSpreekbeurt.tekst_geplaatst,
                DebatSpreekbeurt.tekst_geplaatst_hash,
                DebatSpreekbeurt.vervolg_post_ids,
                DebatSpreekbeurt.beoordeeld_at,
                DebatSpreekbeurt.beurt_soort,
                DebatSpreekbeurt.antwoord_gelezen_tot,
            )
            .where(
                DebatSpreekbeurt.sessie_id == sessie_id,
                DebatSpreekbeurt.debat_direct_id == debate_id,
            )
            .order_by(*ORDER)
        )
    ).all()
    turns: list[Turn] = []
    current: Turn | None = None
    # What was said from the chair since a member last spoke, or since
    # the last suspension. Not only on rows of the chairman: what is
    # said after a resumption or a change of chairman is kept on the row
    # of that event.
    chairman = ""
    for (
        row_id,
        kind,
        who,
        start,
        post_id,
        kop,
        tekst,
        geplaatst,
        placed_key,
        vervolg,
        read,
        turn_kind,
        read_until,
    ) in rows:
        if kind in _SPEAKING and turn_kind:
            # Two events of one person in two roles, seconds apart, are
            # one turn; the timeline decided which kind. From here on the
            # row is that kind: its text goes under the one message, and
            # whoever reads the turn for questions reads it as that kind.
            kind = turn_kind
        if kind in _SPEAKING:
            chairman = ""
        if post_id:
            current = None
            if kind in _CLOSING and kop and chairman:
                # "Ik schors de vergadering tot kwart over twee" is said
                # by the chairman just before the event. Without it the
                # suspension comes out of nowhere. Only what is not under
                # a message of the chair already.
                turns.append(
                    Turn(
                        row_id,
                        post_id,
                        kop,
                        (kind, who),
                        geplaatst,
                        placed_key,
                        [],
                        start,
                        texts=[chairman],
                        closing=True,
                    )
                )
            if kind in _CLOSING:
                # Said once. A second suspension, or the end after a
                # suspension, does not repeat it.
                chairman = ""
            if (kind in _SPEAKING or kind in _CHAIR_OPENS) and kop:
                current = Turn(
                    row_id,
                    post_id,
                    kop,
                    (kind, who),
                    geplaatst,
                    placed_key,
                    list(vervolg or []),
                    start,
                    read,
                    read_until or 0,
                    chair=kind not in _SPEAKING,
                )
                turns.append(current)
        elif kind in _SPEAKING and (current is None or current.key != (kind, who)):
            # Someone spoke who has no message: a stretch the timeline
            # missed. What follows is not the turn from before it.
            current = None
        elif (
            kind == dd.EVENT_CHAIRMAN
            and current is not None
            and current.chair
            and current.key != (kind, who)
        ):
            # The chair taking the word without a message, after a stretch
            # the timeline missed: not the message of the chair before it.
            current = None
        shown = False
        if current is not None and tekst:
            if current.chair:
                # Whatever is said from the chair until a member speaks.
                shown = kind not in _SPEAKING and kind not in _CLOSING
            else:
                # The row of the message itself, and the rows of the same
                # speaker carrying on after the chairman said a word. What
                # the chairman said in between without a message of its
                # own (before the chair had messages) is kept but not
                # shown.
                shown = kind in _SPEAKING
        if shown:
            current.texts.append(tekst)
            current.rows.append(row_id)
        elif kind not in _SPEAKING and kind not in _CLOSING:
            chairman = append_text(chairman, tekst or "")
    return turns
