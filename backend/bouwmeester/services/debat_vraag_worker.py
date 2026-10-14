"""Hand every finished turn at speaking to the marking of questions.

The timeline posts a message per turn and the transcription puts the text
under it. This looks, a few times a minute, for turns that are over and
whose text is complete, and has each one read once
(`DebatVraagService.beoordeel_beurt`): a turn of a member for questions to
the bewindspersoon and for moties, a turn of the bewindspersoon for
toezeggingen. Every rule in here holds for both.

The chairman is not read, with one exception: when a part of the debate has
ended, the list of toezeggingen the chairman read out at its end, if there
is one (`debat_slotlijst`). Once, after every turn of that part was read.

A round of its own, not part of the timeline: reading one turn takes the
model three to fourteen seconds, and the timeline has to say who speaks
within ten.

What a turn is, is not decided here. `load_turns` of the transcription says
which words belong under which message, and this reads exactly those.

A turn is read once, so it is read when its text is final. Around a change
of speaker the voices decide whose a line is, seconds to minutes later, and
a line can go to the turn before or after. A question read under one
speaker and then moved to the other would leave a thread under the wrong
message. So a turn waits for as long as a line can still move into or out
of it; see `rows_in_play`.

One kind of turn is not left until it is over: an answer of the
bewindspersoon. A toezegging in the second minute of an answer of ten is
of use when it is said, so the part of such a turn that is final is read
while the turn goes on (`final_lines`, `DebatVraagWorker._final`), a
window at a time, and the turn counts as read only when it is over and
the rest was read as well.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.core.config import get_settings
from bouwmeester.models.debat_sessie import (
    TIJDLIJN_LOOPT,
    DebatOndertitel,
    DebatSessie,
    DebatSpreekbeurt,
)
from bouwmeester.services import debat_direct as dd
from bouwmeester.services import debat_stem as stem
from bouwmeester.services import debat_stemmen_service as stemmen
from bouwmeester.services import tk_activiteit
from bouwmeester.services.debat_kanaal_service import AMSTERDAM
from bouwmeester.services.debat_slotlijst import (
    BEWINDSPERSOON,
    CHAIRMAN,
    MEMBER,
    Spoken,
    find_closing_list,
)
from bouwmeester.services.debat_stemmen_service import (
    AFTER,
    BEFORE,
    RETRY_FOR,
    WAIT,
)
from bouwmeester.services.debat_tijdlijn_service import (
    END_GRACE,
    GIVE_UP_AFTER,
    LOOKAHEAD,
)
from bouwmeester.services.debat_toezegging import may_hold_commitment
from bouwmeester.services.debat_transcript import append_text
from bouwmeester.services.debat_transcript_service import (
    _CLOSING,
    _SPEAKING,
    AFTER_END,
    ORDER,
    Turn,
    _moment,
    load_turns,
)
from bouwmeester.services.debat_vraag_moment import Line
from bouwmeester.services.debat_vraag_service import (
    SOORT_CHAIRMAN,
    UITKOMST_GEMARKEERD,
    UITKOMST_LLM_ONBRUIKBAAR,
    VOORZITTER,
    Beurt,
    DebatContext,
    DebatVraagService,
    final_end,
    is_bewindspersoon,
    next_window,
    running_window,
    skip_window,
    turn_sleutel,
)
from bouwmeester.services.debat_vraag_status_service import DebatVraagStatusService
from bouwmeester.services.llm.base import BaseLLMService
from bouwmeester.services.mattermost_service import MattermostService

logger = logging.getLogger(__name__)

# How far around a change of speaker a line can be the other person's, as
# the voices have it.
REACH = max(BEFORE, AFTER)
# How far past the end of a turn the subtitles have to be read before its
# text counts as complete: far enough that every line the voices can still
# give to this turn has been read. From there on it is the lines that say
# whether the turn has to wait (`rows_in_play`), not the clock. This was
# 75 seconds for a while, to give the voices time whether they needed it or
# not; they mostly need less, and now and then minutes.
MARGIN = REACH
# How long a turn waits for a line the voices have not decided about. The
# voices keep trying for ten minutes (`RETRY_FOR`), for a voice that is
# learned late or audio that was away; a thread that comes ten minutes
# after the question is of no use to who has to answer it. Past this the
# turn is read as it is. A line of a turn that was read is not moved any
# more (see `_assign` of the voices), so a late decision cannot leave a
# thread under the wrong speaker: the line stays where the time put it.
NEVER_MOVES_AFTER = timedelta(minutes=3)
# Turns of members per debate per round. Normally one or two are waiting;
# this is for after the model was away, so that catching up does not hold
# up the other debates or keep the heartbeat silent for minutes. The answers
# of the bewindspersoon have a bound of their own
# (`MAX_ANSWER_WINDOWS_PER_ROUND`).
MAX_TURNS = 10

# How long a debate on an initiatief is kept without the names of its
# initiatiefnemers before the TK API is asked again. Meetings that are
# still planned carry no names, so they are added on the day at the
# earliest; when exactly is not known.
REREAD_INITIATIEFNEMERS = timedelta(minutes=10)

_HTTP_TIMEOUT = 15.0
# The link to the moment, as the timeline wrote it in the first line.
_MOMENT_LINK = re.compile(r"· \[\d\d:\d\d\]\((https://[^\s()]+)\)")


@dataclass
class VraagTickResult:
    sessies: int = 0
    beoordeeld: int = 0
    vragen: int = 0
    moties: int = 0
    toezeggingen: int = 0
    fouten: int = 0
    # False when there was something to read and no model to read it.
    model: bool = True

    def summary(self) -> str:
        if not self.model:
            return "geen taalmodel ingesteld"
        return (
            f"{self.sessies} debatten, {self.beoordeeld} spreekbeurten gelezen, "
            f"{self.vragen} vragen, {self.moties} moties, "
            f"{self.toezeggingen} toezeggingen, {self.fouten} fouten"
        )


@dataclass(frozen=True)
class _Waiting:
    """A finished turn that has not been read, and who had the floor."""

    turn: Turn
    floor: Turn | None
    # The first turn of its part: which day's list of speakers applies.
    first: datetime
    # How much later than the events the sound of its part is.
    offset: timedelta = timedelta(0)
    # The turn right before it: an answer of the bewindspersoon is to
    # whoever interrupted there. The chairman giving the floor in between
    # is skipped: a message of the chair is no turn of a member.
    before: Turn | None = None
    # The part of the debate it is in.
    part: str = ""
    # Not over, or not final as a whole: only an answer of the
    # bewindspersoon is read then, as far as it is final.
    running: bool = False


@dataclass(frozen=True)
class SubLine:
    """A subtitle line of a turn, as far as reading the turn needs it."""

    id: uuid.UUID
    row_id: uuid.UUID
    start: datetime
    tekst: str
    # Whether the voices are done with it (`stem_klaar`).
    klaar: bool


@dataclass(frozen=True)
class _Final:
    """The part of a turn that goes on that will not change any more."""

    turn: Turn
    lines: tuple[SubLine, ...]
    # Lines that are not marked as decided about yet and have to be before
    # this part is read: the ones in it, and the ones that have waited for
    # the voices too long and could still be moved into it.
    settle: tuple[uuid.UUID, ...]

    @property
    def tekst(self) -> str:
        return text_of(self.lines)


@dataclass(frozen=True)
class _Ended:
    """A part of a debate that has ended and whose closing words were not
    looked at for the chairman's list yet."""

    # The row of the end, and the message under which a toezegging that is
    # only in the list hangs.
    row_id: uuid.UUID
    post_id: str | None
    kop: str
    end: datetime
    # The first turn of the part: which day's list of speakers applies.
    first: datetime
    offset: timedelta
    # Who spoke in the part, in order, as (kind, who, start, text, rows).
    spoken: tuple[tuple[str, str, datetime, str, tuple[uuid.UUID, ...]], ...]


def moment_url_from_kop(kop: str) -> str | None:
    """The link to the moment of a turn, read back from its first line.

    Building it anew takes the debate from Debat Direct, a download per
    round. The timeline had it when it wrote the message, and this way the
    thread links to exactly what the message links to.
    """
    found = _MOMENT_LINK.search(kop or "")
    return found.group(1) if found else None


def text_is_complete(
    entry: dict,
    next_message: datetime | None,
    part_end: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Whether no new line will be added to a turn.

    `entry` is where the reading of the subtitles of its part stands,
    `next_message` the start of the first message after it, `part_end` the
    end of its part. Without something after it the turn is still going on.
    """
    position = _moment(entry.get("positie"))
    if position is None:
        return False
    # The reading stops as soon as it is past the end of the part, so it
    # never gets a margin beyond it. Past the end is complete.
    if part_end is not None and position > part_end:
        return True
    # And it stops by the clock. The stream ends when the debate does, so
    # the reading may never get past the end at all, and the last turns
    # would wait for a margin that does not come.
    if part_end is not None and now is not None and now > part_end + AFTER_END:
        return True
    if next_message is None:
        return False
    offset = timedelta(milliseconds=entry.get("offset_ms") or 0)
    return position >= next_message + offset + MARGIN


def voices_listen() -> bool:
    """Whether lines are being decided about by voice in this process.

    The same two things the timeline goes by. Without the model no line is
    ever marked as decided, and a turn must not wait for that. As long as
    nobody has looked for the model, at the start of the process, it
    counts as there: the lines kept from before a restart can still move
    once the voices are learned again.
    """
    settings = get_settings()
    if not settings.DEBAT_STEMMEN_ENABLED:
        return False
    return stem.available(settings.DEBAT_STEM_MODEL_PATH) is not False


def rows_in_play(
    turns: list[stemmen.Turn],
    lines: list[tuple[datetime, uuid.UUID | None]],
    now: datetime,
) -> set[uuid.UUID]:
    """The events whose text can still change by a line moving.

    `turns` are the events of one part as the voices see them, `lines` the
    lines of it that are not decided about, each with its moment and the
    event it is under now. Asked of the code that moves them:

    * A line the voices have not looked at yet, because the events around
      it may not all be in, can end up under anything it is near.
    * After that, a line near a change of speaker can go to the nearest
      turn of whoever is around that change, and can leave where it is.
    * A line that is not near a change stays where it is, and so does one
      the voices have given up on.
    """
    return set(first_in_play(turns, lines, now))


def reach_of(
    turns: list[stemmen.Turn],
    start: datetime,
    row_id: uuid.UUID | None,
    now: datetime,
) -> set[uuid.UUID]:
    """The events a line can still be under: where it is and where the
    voices can put it. Empty for a line that stays where it is.

    However long the line has waited; `NEVER_MOVES_AFTER` is for whoever
    asks.
    """
    if now - start < WAIT:
        reached = [turn for turn in turns if turn.distance(start) <= REACH]
    else:
        around = stemmen.candidates(turns, start)
        persons = dict.fromkeys(turn.person for turn in around)
        reached = [
            stemmen.nearest(turns, person, start)
            for person in persons
            if person is not None
        ]
        if not reached:
            return set()
    found = {turn.row_id for turn in reached}
    if row_id is not None:
        found.add(row_id)
    return found


def first_in_play(
    turns: list[stemmen.Turn],
    lines: list[tuple[datetime, uuid.UUID | None]],
    now: datetime,
) -> dict[uuid.UUID, datetime]:
    """Per event whose text can still change by a line moving, the moment
    of the first such line. See `rows_in_play` for which lines those are.

    What was said in an event before that moment does not change any
    more: a line that moves takes its place by its moment, so it lands
    behind everything that was said earlier.
    """
    found: dict[uuid.UUID, datetime] = {}
    for start, row_id in lines:
        if now - start > NEVER_MOVES_AFTER:
            continue
        for reached in reach_of(turns, start, row_id, now):
            if reached not in found or start < found[reached]:
                found[reached] = start
    return found


def waits_for_interruption(item: _Waiting, now: datetime) -> bool:
    """Whether an answer that goes on has to wait for the turn before it
    to be read.

    Only for the interruption of a member right before it: a toezegging
    at the start of an answer is tied to the question that was marked in
    that interruption, and promised to who asked it (`link_to_question`).
    No other turn before it is needed for anything, so an answer does not
    wait behind an earlier answer in its pause, or behind a term whose
    lines are not decided about. And not for longer than
    `WAIT_FOR_INTERRUPTION`.
    """
    before = item.before
    return (
        before is not None
        and before.key[0] == dd.EVENT_INTERRUPTER
        and bool(before.text)
        and now - item.turn.start < WAIT_FOR_INTERRUPTION
    )


def text_of(lines: Sequence[SubLine]) -> str:
    """The text of a turn made of these lines, as `derive_text` and
    `load_turns` make it: the lines of a row with a space between them,
    and row after row.

    `lines` are in the order of the text. For the part of a turn that is
    final this is how the text of the whole turn begins, so a place in it
    counted in characters is the same place in the turn when it is over.
    """
    joined = ""
    row: list[str] = []
    current: uuid.UUID | None = None
    for line in lines:
        if line.row_id != current and row:
            joined = append_text(joined, " ".join(row))
            row = []
        current = line.row_id
        row.append(line.tekst)
    if row:
        joined = append_text(joined, " ".join(row))
    return joined


def final_lines(lines: Sequence[SubLine], bound: datetime | None) -> list[SubLine]:
    """The lines of a turn that goes on that are final, in order.

    `lines` are all its lines in the order of its text, `bound` the moment
    of the first line that can still move into or out of the turn
    (`first_in_play`), or ``None`` when there is none. Every line of
    before that moment is final:

    * It is all there. The subtitles are read file after file and a line
      is in the file it starts in, so nothing is added in front of a line
      that was read.
    * It does not leave the turn: the voices are done with it, or it is
      not near a change of speaker, or it has waited for the voices longer
      than `NEVER_MOVES_AFTER`. And whoever reads it marks it as decided
      first, so that this is also true ten minutes from now.
    * Nothing is put in front of it: a line that moves into the turn lands
      at its own moment, which is `bound` or later.

    A line the voices can still move, and everything said after it, is
    left for a later round.
    """
    final: list[SubLine] = []
    for line in lines:
        if bound is not None and line.start >= bound:
            break
        final.append(line)
    return final


def _names_may_follow(context: DebatContext, now: datetime) -> bool:
    """Whether to ask again for who the initiatiefnemers of a debate are."""
    if not context.initiatiefnemers or context.initiatiefnemer_namen:
        return False
    # A context that was handed in and not read here is left as it is.
    return (
        context.gelezen_at is not None
        and now - context.gelezen_at >= REREAD_INITIATIEFNEMERS
    )


class _Pause:
    """How long a debate, or one turn, is left alone after reading failed.

    In the memory of the process: after a restart the first try is free,
    which is what a restart is for. The wait doubles with every failure in
    a row, so a model that is down costs a few calls and not four a minute.
    """

    def __init__(
        self, first: timedelta | None = None, maximum: timedelta | None = None
    ) -> None:
        self._until: dict[uuid.UUID, datetime] = {}
        self._failures: dict[uuid.UUID, int] = {}
        # How long the first wait is and how long a wait gets at most;
        # `PAUSE_FIRST` and `PAUSE_MAX` when not said.
        self._first = first
        self._maximum = maximum

    def waiting(self, sessie_id: uuid.UUID, now: datetime) -> bool:
        until = self._until.get(sessie_id)
        return until is not None and now < until

    def failed(self, sessie_id: uuid.UUID, now: datetime) -> None:
        count = self._failures.get(sessie_id, 0) + 1
        self._failures[sessie_id] = count
        first = self._first or PAUSE_FIRST
        self._until[sessie_id] = now + min(
            first * 2 ** (count - 1), self._maximum or PAUSE_MAX
        )

    def succeeded(self, sessie_id: uuid.UUID) -> None:
        self._until.pop(sessie_id, None)
        self._failures.pop(sessie_id, None)

    def reset(self) -> None:
        self._until.clear()
        self._failures.clear()


class _Roles:
    """Who answers in a debate and who asks, as far as it was looked up.

    A turn that goes on is looked at every round, and whether it is an
    answer is on the list of speakers of Debat Direct. Asking for that
    list every quarter of a minute for as long as someone speaks is 240
    requests an hour for something that does not change during a debate.
    In the memory of the process, per debate: after a restart it is asked
    once more.
    """

    def __init__(self) -> None:
        self._known: dict[tuple[uuid.UUID, str], bool] = {}
        self._asked: dict[uuid.UUID, datetime] = {}

    def of(self, sessie_id: uuid.UUID, who: str) -> bool | None:
        """Whether this person answers; ``None`` when not known."""
        return self._known.get((sessie_id, who))

    def learn(self, sessie_id: uuid.UUID, sprekers: dict[str, dd.Spreker]) -> None:
        """Everyone on a list of speakers at once: who speaks next is on
        it too, and must not wait for the list to be asked for again."""
        for who, spreker in sprekers.items():
            self._known[(sessie_id, who)] = is_bewindspersoon(spreker)

    def may_ask(self, sessie_id: uuid.UUID, now: datetime) -> bool:
        asked = self._asked.get(sessie_id)
        return asked is None or abs(now - asked) >= ASK_ROLES_AGAIN

    def asked(self, sessie_id: uuid.UUID, now: datetime) -> None:
        self._asked[sessie_id] = now

    def keep_only(self, sessie_ids: list[uuid.UUID]) -> None:
        keep = set(sessie_ids)
        self._known = {k: v for k, v in self._known.items() if k[0] in keep}
        self._asked = {k: v for k, v in self._asked.items() if k in keep}

    def reset(self) -> None:
        self._known.clear()
        self._asked.clear()


# How long the list of speakers is not asked for again for a turn that goes
# on and whose speaker is not on it: a guest, or a bewindspersoon the list
# does not have yet. A turn that is over asks every round, as it did.
ASK_ROLES_AGAIN = timedelta(minutes=5)
_roles = _Roles()
# How long an answer that goes on is left alone after a window of it was
# asked about. A bewindspersoon who commits to three things in three
# sentences would otherwise cost a call a round. On the gold set it costs
# nothing: played on the clock with a floor of 0, 20, 30 and 45 seconds
# the same 37 windows are asked about and the toezeggingen wait the same
# median of 71 seconds, so no two calls on one turn came that close
# there. A window that is full does not wait: that is an answer running
# ahead of its reading.
RUNNING_EVERY = timedelta(seconds=30)
# When a window of each answer that goes on was last asked about, in the
# memory of the process.
_asked_at: dict[uuid.UUID, datetime] = {}
# How long an answer that goes on waits for the interruption before it to
# be read. The two are ready at about the same moment, a minute after the
# answer began: the lines around the change of speaker between them hold
# both. Past this the interruption is stuck on something else (the lines
# at its own start, a model that is away), and the answer is read without
# the question it may be tied to.
WAIT_FOR_INTERRUPTION = timedelta(seconds=90)
_pause = _Pause()
# The same for one answer of the bewindspersoon of which a window could not
# be read: that turn is left alone for a while, and the debate is not. When
# a window is slow or fails, the questions of the members after it must
# still be marked. Keyed by the row of the turn.
_answer_pause = _Pause()
# How many windows of answers one round reads per debate, each one model
# call (two when the reply is unreadable the first time). The turns of
# members of a round are read first; this bounds what the answers add to
# it. Two, because a round comes every quarter of a minute and two windows
# at their slowest are a minute: an answer of ten minutes is three windows
# and is read in two rounds, and the members who speak meanwhile wait a
# minute at most.
MAX_ANSWER_WINDOWS_PER_ROUND = 2
# How long the call for one window of an answer may take. A window is about
# 4,000 characters; on the debate the rules were made on, 14 such calls took
# 4.2 to 7.1 seconds. Four times the slowest, and half of what a turn of a
# member gets: a window that takes longer than this hangs.
WINDOW_TIMEOUT = 30.0
# How often one window is tried before the answer is read on behind it.
# With the pauses in between that is a minute and a half. Per window: the
# count starts anew when the answer is read further.
WINDOW_ATTEMPTS = 3
# How long one call for a turn may take, model and all. Measured: 3 to 14
# seconds for a turn of a member. An answer of the bewindspersoon is read
# a window per call and has a limit of its own (`WINDOW_TIMEOUT`).
JUDGE_TIMEOUT = 60.0
# How long one round may spend on working reactions in, in seconds, before
# it goes on to the turns. Enough for a few replies on a slow Mattermost.
REACTIES_BUDGET = 20.0
# The pauses add up to a quarter of an hour before a turn is given up on.
MAX_ATTEMPTS = 6
PAUSE_FIRST = timedelta(seconds=30)
PAUSE_MAX = timedelta(minutes=5)
# How long the chairman's list waits for a turn of its part that is not
# read yet: the list confirms the toezeggingen that were marked, so they
# have to be there. A turn that is still not read by then never will be,
# and the list is read without it.
LIST_WAITS_FOR_TURNS = timedelta(minutes=15)
# The list is one call for a whole debate, and the debate is over: nothing
# waits behind it. So a model that is away is not asked again a quarter of
# a minute later, three times in a row: five tries with 2, 4, 8 and 8
# minutes between them, 22 minutes in all. A reply that cannot be read gets
# one more try; a third would give the same. The list of speakers that
# cannot be fetched waits the same way, without a count: without it nobody
# can say whether a bewindspersoon answered before the list.
LIST_ATTEMPTS = 5
LIST_UNUSABLE_ATTEMPTS = 2
LIST_PAUSE_FIRST = timedelta(minutes=2)
LIST_PAUSE_MAX = timedelta(minutes=8)
# A list is not read later than this after the end of its debate: by then
# the waiting and the tries above are used up, and a reply that turns up
# under the end of a debate of hours ago is read by nobody. It also keeps a
# worker that was away for a while from reading the lists of everything
# that ended meanwhile. (The debates that had ended before this was built
# were marked as looked at by a migration.)
LIST_NOT_AFTER = timedelta(hours=1)
# Keyed by the row of the end of the part.
_list_pause = _Pause(LIST_PAUSE_FIRST, LIST_PAUSE_MAX)


class DebatVraagWorker:
    def __init__(
        self,
        session: AsyncSession,
        mattermost: MattermostService | None = None,
        llm: BaseLLMService | None = None,
        contexts: dict[uuid.UUID, DebatContext] | None = None,
    ) -> None:
        self.session = session
        self.mattermost = mattermost or MattermostService(session)
        self.llm = llm
        # What is known about each debate beforehand. Handed in by the
        # loop, so it is asked of the TK API once and not every round.
        self.contexts = contexts if contexts is not None else {}
        # Per day, for the length of one round.
        self._sprekers: dict[str, dict[str, dd.Spreker]] = {}
        # Per debate, the turns `_waiting` found that are not over or not
        # final as a whole: an answer among them is read as far as it is.
        self._going: dict[uuid.UUID, list[_Waiting]] = {}

    async def close(self) -> None:
        await self.mattermost.close()

    async def tick(self, now: datetime | None = None) -> VraagTickResult:
        """Read the turns that have finished since the last round."""
        now = now or datetime.now(UTC)
        result = VraagTickResult()
        await self._reacties()
        # The debates the timeline is following, and for a few hours after
        # their end: that long the timeline keeps them running as well.
        stmt = select(DebatSessie.id).where(
            DebatSessie.channel_id.is_not(None),
            DebatSessie.aanvang.is_not(None),
            DebatSessie.aanvang <= now + LOOKAHEAD,
            DebatSessie.aanvang >= now - GIVE_UP_AFTER - END_GRACE,
            DebatSessie.tijdlijn_status == TIJDLIJN_LOOPT,
        )
        sessie_ids = list((await self.session.execute(stmt)).scalars().all())
        _roles.keep_only(sessie_ids)
        for row_id in [r for r, at in _asked_at.items() if abs(now - at) > PAUSE_MAX]:
            del _asked_at[row_id]
        if not sessie_ids:
            return result
        if not await self.mattermost.is_enabled():
            return result

        vragen: DebatVraagService | None = None
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            for sessie_id in sessie_ids:
                result.sessies += 1
                if _pause.waiting(sessie_id, now):
                    continue
                try:
                    waiting = await self._waiting(sessie_id, now)
                    # The list of the chairman only when no turn waits: it
                    # is matched to what the turns held.
                    ended = [] if waiting else await self._ended(sessie_id, now)
                    ended = [
                        part
                        for part in ended
                        if not _list_pause.waiting(part.row_id, now)
                    ]
                    # The answers that go on and of which something final
                    # is worth a call now. Nothing is looked up and no
                    # model is looked for when there is none: nearly every
                    # round of a debate.
                    going = await self._ready(
                        sessie_id,
                        self._going.pop(sessie_id, []),
                        {item.turn.row_id for item in waiting},
                        client,
                        now,
                    )
                    if not waiting and not ended and not going:
                        continue
                    if vragen is None:
                        vragen = await self._service()
                    if vragen is None:
                        result.model = False
                        return result
                    if waiting or going:
                        await self._read(
                            sessie_id, waiting, going, vragen, client, now, result
                        )
                    for part in ended:
                        await self._read_list(
                            sessie_id, part, vragen, client, now, result
                        )
                except Exception:
                    # One debate that breaks must not stop the others.
                    await self.session.rollback()
                    result.fouten += 1
                    logger.exception("Vragen van sessie %s liepen vast", sessie_id)
        return result

    async def _reacties(self) -> None:
        """Work in what people said became of a question, with a reaction.

        First in the round, before any turn is read: someone who clicks
        waits for this, and reading turns can take a minute. Also for a
        debate that is over, which is when most answers are ticked off; so
        not per debate that is running, but for every markering the
        websocket marked. By the real clock, like those marks.

        A round in which this breaks still reads its turns.
        """
        try:
            # With a limit: a slow Mattermost must not keep the turns of a
            # running debate from being read. What is not done waits, with
            # its mark, for the next round.
            ronde = await asyncio.wait_for(
                DebatVraagStatusService(self.session, self.mattermost).werk_bij(),
                timeout=REACTIES_BUDGET,
            )
        except TimeoutError:
            await self.session.rollback()
            logger.warning("Reacties op vragen niet af binnen %ds", REACTIES_BUDGET)
            return
        except Exception:
            await self.session.rollback()
            logger.exception("Reacties op vragen niet verwerkt")
            return
        if ronde.gewijzigd or ronde.mislukt:
            logger.info(
                "Reacties op vragen: %d bijgewerkt, %d gewijzigd, %d wachten",
                ronde.bijgewerkt,
                ronde.gewijzigd,
                ronde.mislukt,
            )

    async def _service(self) -> DebatVraagService | None:
        if self.llm is not None:
            return DebatVraagService(self.session, self.mattermost, self.llm)
        return await DebatVraagService.create(self.session, self.mattermost)

    async def _waiting(self, sessie_id: uuid.UUID, now: datetime) -> list[_Waiting]:
        """The turns of a debate that are over, final and not read yet."""
        sessie = (
            await self.session.execute(
                select(DebatSessie.debat_direct_ids, DebatSessie.ondertitels).where(
                    DebatSessie.id == sessie_id
                )
            )
        ).first()
        if sessie is None:
            return []
        parts, ondertitels = list(sessie[0] or []), dict(sessie[1] or {})

        # Every event of the debate in the order of the channel, and where
        # each part ended. A turn is over when a message follows it.
        marks = (
            await self.session.execute(
                select(
                    DebatSpreekbeurt.id,
                    DebatSpreekbeurt.debat_direct_id,
                    DebatSpreekbeurt.event_type,
                    DebatSpreekbeurt.event_start,
                    DebatSpreekbeurt.post_id,
                    DebatSpreekbeurt.object_id,
                )
                .where(DebatSpreekbeurt.sessie_id == sessie_id)
                .order_by(*ORDER)
            )
        ).all()
        next_message: dict[uuid.UUID, datetime] = {}
        ends: dict[str, datetime] = {}
        events: dict[str, list[tuple]] = {}
        previous: uuid.UUID | None = None
        for row_id, debate_id, kind, start, post_id, who in marks:
            events.setdefault(debate_id, []).append((row_id, kind, start, who))
            if kind == dd.EVENT_DEBATE_END:
                ends[debate_id] = start
            if post_id:
                if previous is not None:
                    next_message[previous] = start
                previous = row_id

        # The parts whose lines the voices decide about: with a model, and
        # with audio to listen to. In any other part a line stays where
        # the time put it, and nothing is waited for.
        heard = [
            debate_id
            for debate_id in parts
            if (ondertitels.get(debate_id) or {}).get("audio")
        ]
        open_lines = await self._open_lines(sessie_id, heard, now)

        waiting: list[_Waiting] = []
        going: list[_Waiting] = []
        for debate_id in parts:
            entry = dict(ondertitels.get(debate_id) or {})
            turns = await load_turns(self.session, sessie_id, debate_id)
            unsettled: set[uuid.UUID] = set()
            if debate_id in open_lines:
                voiced = stemmen.as_turns(events.get(debate_id, []))
                under = stemmen.message_of(voiced, {turn.row_id for turn in turns})
                unsettled = {
                    under[row_id]
                    for row_id in rows_in_play(voiced, open_lines[debate_id], now)
                    if row_id in under
                }
            floor: Turn | None = None
            before: Turn | None = None
            # When the meeting was suspended or taken up again. What was
            # said before a break is not what an answer after it is to.
            # From the events, not from the turns: a suspension only has a
            # message of its own when the chairman said something first.
            breaks = [
                start
                for _, kind, start, _ in events.get(debate_id, [])
                if kind in (dd.EVENT_SUSPENDED, dd.EVENT_CONTINUED)
            ]
            for turn in turns:
                if not turn.is_member:
                    # The chair, or a suspension or the end with the words
                    # of the chairman under it. Nobody's turn at speaking.
                    continue
                if before is not None and any(
                    before.start < moment <= turn.start for moment in breaks
                ):
                    before = None
                if turn.beoordeeld_at is None:
                    offset = timedelta(milliseconds=entry.get("offset_ms") or 0)
                    item = _Waiting(
                        turn, floor, turns[0].start, offset, before, debate_id
                    )
                    if turn.row_id not in unsettled and text_is_complete(
                        entry, next_message.get(turn.row_id), ends.get(debate_id), now
                    ):
                        waiting.append(item)
                    elif turn.text:
                        going.append(replace(item, running=True))
                if turn.key[0] == dd.EVENT_SPEAKER:
                    floor = turn
                before = turn
        # In the order they were spoken: a question asked again has to
        # find the first time it was asked. A turn that waits for a line
        # does not hold up the ones after it, which can be minutes; a
        # question it repeats from a later turn is then filed under that
        # later one.
        waiting.sort(key=lambda w: w.turn.start)
        going.sort(key=lambda w: w.turn.start)
        self._going[sessie_id] = going
        return waiting

    async def _ready(
        self,
        sessie_id: uuid.UUID,
        going: list[_Waiting],
        waiting: set[uuid.UUID],
        client: httpx.AsyncClient,
        now: datetime,
    ) -> list[_Waiting]:
        """Of the turns that go on, the answers of a bewindspersoon of which
        a window is worth a call now. `waiting` are the turns that are
        over and are read this round, before any of these.

        Cheapest first, so that a round in which nothing is ready costs
        next to nothing: the words of a commitment have to stand in what
        was not read, then who speaks is looked up, and only then the
        lines of the turn are read to see what of it is final.
        """
        ready: list[_Waiting] = []
        for item in going:
            turn = item.turn
            if not may_hold_commitment(turn.text[turn.gelezen_tot :]):
                continue
            before = item.before
            if (
                before is not None
                and waits_for_interruption(item, now)
                and before.beoordeeld_at is None
                and before.row_id not in waiting
            ):
                # One that is read this very round is checked again when
                # it is this turn's turn (`_read_running`).
                continue
            if not await self._answers(sessie_id, item, client, now):
                continue
            final = await self._final(sessie_id, item, now)
            if final is None:
                continue
            venster = running_window(final.tekst, final.turn.gelezen_tot)
            if venster is None:
                continue
            last = _asked_at.get(turn.row_id)
            if (
                last is not None
                and abs(now - last) < RUNNING_EVERY
                and venster[2] == final_end(final.tekst)
            ):
                continue
            ready.append(item)
        return ready

    async def _answers(
        self,
        sessie_id: uuid.UUID,
        item: _Waiting,
        client: httpx.AsyncClient,
        now: datetime,
    ) -> bool:
        """Whether a turn that goes on is one of a bewindspersoon.

        From what was looked up before (`_roles`). Someone who is not
        known is looked up on the list of speakers, not more often than
        every `ASK_ROLES_AGAIN`; until then the turn is left for when it
        is over.
        """
        who = item.turn.key[1]
        known = _roles.of(sessie_id, who)
        if known is None and _roles.may_ask(sessie_id, now):
            _roles.asked(sessie_id, now)
            _roles.learn(sessie_id, await self._sprekers_for(client, item.first) or {})
            known = _roles.of(sessie_id, who)
        return bool(known)

    async def _turn_lines(self, turn: Turn) -> list[SubLine]:
        """The subtitle lines of a turn, in the order of its text: row
        after row as `load_turns` joined them, and within a row by moment,
        as `derive_text` does."""
        if not turn.rows:
            return []
        found = (
            await self.session.execute(
                select(
                    DebatOndertitel.id,
                    DebatOndertitel.spreekbeurt_id,
                    DebatOndertitel.start,
                    DebatOndertitel.tekst,
                    DebatOndertitel.stem_klaar,
                )
                .where(DebatOndertitel.spreekbeurt_id.in_(turn.rows))
                .order_by(DebatOndertitel.start)
            )
        ).all()
        per_row: dict[uuid.UUID, list[SubLine]] = {}
        for row in found:
            per_row.setdefault(row[1], []).append(SubLine(*row))
        return [line for row_id in turn.rows for line in per_row.get(row_id, [])]

    async def _final(
        self, sessie_id: uuid.UUID, item: _Waiting, now: datetime
    ) -> _Final | None:
        """The part of a turn that goes on that is final, as it is now.

        Read anew, not taken from the start of the round: the turns of
        the members are read first and that can take a minute, in which
        lines came in and were moved. ``None`` when nothing of the turn
        is final, or the turn is not what it was.

        What is final is said by `final_lines`. Where the voices are not
        listened to, or the part has no audio, no line ever moves and
        every line that was read is final.
        """
        turns = await load_turns(self.session, sessie_id, item.part)
        turn = next((t for t in turns if t.row_id == item.turn.row_id), None)
        if turn is None or not turn.is_member or turn.beoordeeld_at is not None:
            return None
        lines = await self._turn_lines(turn)
        bound: datetime | None = None
        late: list[tuple[datetime, uuid.UUID]] = []
        ondertitels = await self.session.scalar(
            select(DebatSessie.ondertitels).where(DebatSessie.id == sessie_id)
        )
        heard = ((ondertitels or {}).get(item.part) or {}).get("audio")
        if heard and voices_listen():
            events = (
                await self.session.execute(
                    select(
                        DebatSpreekbeurt.id,
                        DebatSpreekbeurt.event_type,
                        DebatSpreekbeurt.event_start,
                        DebatSpreekbeurt.object_id,
                    )
                    .where(
                        DebatSpreekbeurt.sessie_id == sessie_id,
                        DebatSpreekbeurt.debat_direct_id == item.part,
                    )
                    .order_by(*ORDER)
                )
            ).all()
            voiced = stemmen.as_turns([tuple(row) for row in events])
            under = stemmen.message_of(voiced, {t.row_id for t in turns})
            # Every line the voices have not decided about and still can:
            # they give up on a line after `RETRY_FOR`.
            undecided = (
                await self.session.execute(
                    select(
                        DebatOndertitel.id,
                        DebatOndertitel.start,
                        DebatOndertitel.spreekbeurt_id,
                    )
                    .where(
                        DebatOndertitel.sessie_id == sessie_id,
                        DebatOndertitel.debat_direct_id == item.part,
                        DebatOndertitel.stem_klaar.is_(False),
                        DebatOndertitel.start >= now - RETRY_FOR - NEVER_MOVES_AFTER,
                    )
                    .order_by(DebatOndertitel.start)
                )
            ).all()
            in_play = first_in_play(
                voiced, [(start, row_id) for _, start, row_id in undecided], now
            )
            bounds = [
                moment
                for row_id, moment in in_play.items()
                if under.get(row_id) == turn.row_id
            ]
            bound = min(bounds) if bounds else None
            # A line that has waited for the voices longer than
            # `NEVER_MOVES_AFTER` does not hold the turn up, and the voices
            # keep trying for it until `RETRY_FOR`. One that could be put
            # into this turn is marked as decided before the turn is read.
            late = [
                (start, line_id)
                for line_id, start, row_id in undecided
                if now - start > NEVER_MOVES_AFTER
                and turn.row_id
                in {under.get(row) for row in reach_of(voiced, start, row_id, now)}
            ]
        final = final_lines(lines, bound)
        if not final:
            return None
        last = max(line.start for line in final)
        settle = {line.id for line in final if not line.klaar}
        settle.update(line_id for start, line_id in late if start <= last)
        return _Final(turn, tuple(final), tuple(sorted(settle, key=str)))

    async def _settle(self, final: _Final) -> bool:
        """Mark the lines of what is about to be read as decided about, and
        say whether the turn still begins with exactly those lines.

        The voices move a line only while it is not marked as decided
        (`DebatStemmen._assign`), in one statement that looks at that mark.
        So once this is committed, no line of what is read can leave the
        turn, and none of the lines that waited too long can be put into
        it: what the model is shown is what stays under the message. A
        line the voices moved in the moment before, or hold at this
        moment, is seen by the second look, and the turn is then left for
        the next round.
        """
        if final.settle:
            # The voices decide line after line and hold each one until
            # their round is committed. Waiting for a line they hold while
            # they wait for one held here is a deadlock, so nothing is
            # waited for: a line they hold is passed over, stays without
            # its mark, and the turn is left for the next round.
            free = (
                (
                    await self.session.execute(
                        select(DebatOndertitel.id)
                        .where(
                            DebatOndertitel.id.in_(final.settle),
                            DebatOndertitel.stem_klaar.is_(False),
                        )
                        .order_by(DebatOndertitel.start)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )
            if free:
                await self.session.execute(
                    update(DebatOndertitel)
                    .where(DebatOndertitel.id.in_(free))
                    .values(stem_klaar=True)
                )
            await self.session.commit()
            # Every one of them, not only the lines of the turn itself: a
            # line of another turn that waited too long and that the voices
            # are putting into this one right now is held by them, was
            # passed over, and lands in the middle of what is about to be
            # read when they commit.
            left = await self.session.scalar(
                select(func.count())
                .select_from(DebatOndertitel)
                .where(
                    DebatOndertitel.id.in_(final.settle),
                    DebatOndertitel.stem_klaar.is_(False),
                )
            )
            if left:
                return False
        head = (await self._turn_lines(final.turn))[: len(final.lines)]
        return [line.id for line in head] == [line.id for line in final.lines]

    async def _open_lines(
        self, sessie_id: uuid.UUID, parts: list[str], now: datetime
    ) -> dict[str, list[tuple[datetime, uuid.UUID | None]]]:
        """Per part, the lines the voices have not decided about yet.

        One question for the whole debate, and none at all when the voices
        are not listened to. Normally a handful of lines: the last half
        minute, and what waits for a voice that is not known yet.
        """
        if not parts or not voices_listen():
            return {}
        rows = await self.session.execute(
            select(
                DebatOndertitel.debat_direct_id,
                DebatOndertitel.start,
                DebatOndertitel.spreekbeurt_id,
            )
            .where(
                DebatOndertitel.sessie_id == sessie_id,
                DebatOndertitel.debat_direct_id.in_(parts),
                DebatOndertitel.stem_klaar.is_(False),
                DebatOndertitel.start >= now - NEVER_MOVES_AFTER,
            )
            .order_by(DebatOndertitel.start)
        )
        found: dict[str, list[tuple[datetime, uuid.UUID | None]]] = {}
        for debate_id, start, row_id in rows.all():
            found.setdefault(debate_id, []).append((start, row_id))
        return found

    async def _read(
        self,
        sessie_id: uuid.UUID,
        waiting: list[_Waiting],
        going: list[_Waiting],
        vragen: DebatVraagService,
        client: httpx.AsyncClient,
        now: datetime,
        result: VraagTickResult,
    ) -> None:
        channel_id, activiteit_id, onderwerp = (
            await self.session.execute(
                select(
                    DebatSessie.channel_id,
                    DebatSessie.activiteit_id,
                    DebatSessie.onderwerp,
                ).where(DebatSessie.id == sessie_id)
            )
        ).one()

        # The turns of members first, the answers of the bewindspersoon
        # after them: who has to prepare an answer waits for the questions,
        # and an answer is the call that can be slow. An answer that fails
        # does not stop the round and does not pause the debate.
        answers: list[_Waiting] = []
        members = 0
        for item in waiting:
            if members >= MAX_TURNS:
                break
            set_aside = len(answers)
            if await self._read_turn(
                sessie_id,
                item,
                vragen,
                client,
                now,
                result,
                (channel_id, activiteit_id, onderwerp),
                answers,
            ):
                return
            # An answer that was set aside does not use up the round: the
            # turns of members behind a row of answers are still reached.
            members += len(answers) == set_aside
        # The answers that are over first, then the ones that go on: all
        # of them after the members, and together not more windows than a
        # round may take.
        parts = 0
        for item in [*answers, *going]:
            if parts >= MAX_ANSWER_WINDOWS_PER_ROUND:
                break
            if _answer_pause.waiting(item.turn.row_id, now):
                continue
            asked = vragen.aanroepen
            if item.running:
                stop = await self._read_running(
                    sessie_id,
                    item,
                    vragen,
                    client,
                    now,
                    result,
                    (channel_id, activiteit_id, onderwerp),
                )
            else:
                stop = await self._read_turn(
                    sessie_id,
                    item,
                    vragen,
                    client,
                    now,
                    result,
                    (channel_id, activiteit_id, onderwerp),
                    None,
                )
            # A slot is a call of the model. A turn that turned out to
            # hold nothing to ask about, or whose line moved a moment ago,
            # does not use one up for the turns behind it.
            parts += vragen.aanroepen > asked
            if stop:
                return

    async def _read_turn(
        self,
        sessie_id: uuid.UUID,
        item: _Waiting,
        vragen: DebatVraagService,
        client: httpx.AsyncClient,
        now: datetime,
        result: VraagTickResult,
        sessie: tuple[str, str, str],
        answers: list[_Waiting] | None,
    ) -> bool:
        """Read one turn. ``True`` when the round of this debate has to stop.

        With `answers` a turn of the bewindspersoon is not read but put on
        that list, for after the turns of the members.
        """
        channel_id, activiteit_id, onderwerp = sessie
        turn = item.turn
        tekst = turn.text
        if not tekst:
            # Nothing was said, or nothing was heard. Not a reason to
            # ask the model, and not a reason to look again either.
            await self._mark(turn.row_id, now)
            return False

        sprekers = await self._sprekers_for(client, item.first)
        if sprekers is None:
            # Without the list nobody can tell a member from a
            # minister, and the answers of a minister are not
            # questions. A later round has the list again.
            result.fouten += 1
            return True
        _roles.learn(sessie_id, sprekers)
        kind, who = turn.key
        spreker = sprekers.get(who)
        if spreker is None:
            # Not on the list of Debat Direct: a guest, or a minister
            # the list does not have yet. Whether this is someone who
            # asks or someone who answers cannot be told, so the model
            # is not asked to guess.
            await self._mark(turn.row_id, now)
            return False
        answer = is_bewindspersoon(spreker)
        if answer and answers is not None:
            answers.append(item)
            return False
        context = await self._context(sessie_id, activiteit_id, onderwerp, client)
        beurt = self._as_beurt(
            sessie_id,
            item,
            turn,
            sprekers,
            channel_id,
            tekst=tekst,
            lines=await self._lines(turn, item.offset),
            gelezen_tot=await self._position(turn.row_id) if answer else 0,
        )
        outcome = None
        try:
            outcome = await asyncio.wait_for(
                vragen.beoordeel_beurt(beurt, context),
                WINDOW_TIMEOUT if answer else JUDGE_TIMEOUT,
            )
            failed = outcome.opnieuw_proberen
        except Exception:
            # Also a model that hangs: the clients wait ten minutes by
            # themselves. And anything that breaks after the model
            # answered, which would otherwise ask it again every round.
            logger.exception("Spreekbeurt %s niet beoordeeld", turn.row_id)
            await self.session.rollback()
            failed = True
        if failed:
            result.fouten += 1
            attempts = await self._count_attempt(turn.row_id)
            if answer:
                # Only this turn waits. The debate goes on: its members'
                # turns were read before this one, and are next round too.
                _answer_pause.failed(turn.row_id, now)
                if attempts >= WINDOW_ATTEMPTS:
                    # This window is given up on, not the answer: what was
                    # read before it is stored, and what comes behind it
                    # is still read.
                    further = skip_window(tekst, beurt.gelezen_tot)
                    logger.warning(
                        "Spreekbeurt %s: venster vanaf teken %d na %d pogingen"
                        " overgeslagen, verder vanaf %d",
                        turn.row_id,
                        beurt.gelezen_tot,
                        attempts,
                        further,
                    )
                    await self._keep_position(turn.row_id, further)
                    _answer_pause.succeeded(turn.row_id)
                    if next_window(tekst, further) is None:
                        await self._mark(turn.row_id, now)
                return False
            if attempts >= MAX_ATTEMPTS:
                logger.warning(
                    "Spreekbeurt %s na %d pogingen overgeslagen",
                    turn.row_id,
                    attempts,
                )
                await self._mark(turn.row_id, now)
            # The turns after this one would find the same, each after
            # its own wait. The debate is left alone for a while, longer
            # each time; a turn that keeps failing is given up on, so
            # that it does not hold up every turn after it.
            _pause.failed(sessie_id, now)
            return True
        assert outcome is not None
        if answer:
            _answer_pause.succeeded(turn.row_id)
            await self._keep_position(turn.row_id, outcome.gelezen_tot)
        else:
            _pause.succeeded(sessie_id)
        if outcome.uitkomst == UITKOMST_GEMARKEERD:
            result.vragen += (
                len(outcome.markering_ids) - outcome.moties - outcome.toezeggingen
            )
            result.moties += outcome.moties
            result.toezeggingen += outcome.toezeggingen
        if outcome.meer:
            # A long answer of which a window was read. The rest is for
            # the next rounds, a window at a time.
            return False
        await self._mark(turn.row_id, now)
        result.beoordeeld += 1
        return False

    def _as_beurt(
        self,
        sessie_id: uuid.UUID,
        item: _Waiting,
        turn: Turn,
        sprekers: dict[str, dd.Spreker],
        channel_id: str,
        *,
        tekst: str,
        lines: tuple[Line, ...],
        gelezen_tot: int,
        loopt: bool = False,
    ) -> Beurt:
        """A turn as the marking reads it. `turn` is the turn as it is
        now, whose speaker is on the list."""
        kind, who = turn.key
        spreker = sprekers[who]
        answer = is_bewindspersoon(spreker)
        onderbroken = None
        if kind == dd.EVENT_INTERRUPTER and item.floor is not None:
            onderbroken = sprekers.get(item.floor.key[1])
        # For an answer of the bewindspersoon: the member who
        # interrupted right before it, and what they said. Someone
        # without a party is no member, and someone the list does not
        # have is nobody to name.
        asked: dd.Spreker | None = None
        if (
            answer
            and item.before is not None
            and item.before.key[0] == dd.EVENT_INTERRUPTER
        ):
            asked = sprekers.get(item.before.key[1])
            if asked is not None and not asked.fractie:
                asked = None
        return Beurt(
            sessie_id=sessie_id,
            spreekbeurt_id=turn.row_id,
            post_id=turn.post_id,
            channel_id=channel_id,
            soort=kind,
            spreker=spreker.label,
            fractie=spreker.fractie,
            start=turn.start,
            moment_url=moment_url_from_kop(turn.kop),
            tekst=tekst,
            lines=lines,
            is_bewindspersoon=answer,
            onderbroken=onderbroken.label if onderbroken else None,
            onderbroken_is_bewindspersoon=bool(
                onderbroken and is_bewindspersoon(onderbroken)
            ),
            voorafgaand=asked.label if asked else None,
            voorafgaand_tekst=item.before.text if asked and item.before else "",
            voorafgaand_sleutel=(
                turn_sleutel(item.before.row_id) if asked and item.before else None
            ),
            gelezen_tot=gelezen_tot,
            loopt=loopt,
            vervolg_post_ids=tuple(turn.vervolg),
        )

    async def _read_running(
        self,
        sessie_id: uuid.UUID,
        item: _Waiting,
        vragen: DebatVraagService,
        client: httpx.AsyncClient,
        now: datetime,
        result: VraagTickResult,
        sessie: tuple[str, str, str],
    ) -> bool:
        """Read one window of an answer that goes on. ``True`` when the
        round of this debate has to stop.

        The turn is never marked as read here: that is for when it is
        over, and what is left of it was read as any other turn is. What
        is kept is how far it was read (`antwoord_gelezen_tot`), counted
        in characters of its text. That is a safe place because the text
        in front of it cannot change: it is made of lines that were
        marked as decided before they were read (`_settle`), and such a
        line is never moved or taken away. A line that is put in front of
        it after all, by a rule that is not foreseen here, makes the next
        window start a line early: read twice and stored once, never
        skipped.
        """
        channel_id, activiteit_id, onderwerp = sessie
        sprekers = await self._sprekers_for(client, item.first)
        if sprekers is None:
            result.fouten += 1
            return True
        spreker = sprekers.get(item.turn.key[1])
        if spreker is None or not is_bewindspersoon(spreker):
            return False
        if (
            item.before is not None
            and waits_for_interruption(item, now)
            and await self._read_at(item.before.row_id) is None
        ):
            # The turn before was to be read earlier in this round and
            # was not: the model was away, or more turns waited than a
            # round reads. See `_ready`.
            return False
        final = await self._final(sessie_id, item, now)
        if final is None:
            return False
        turn, tekst = final.turn, final.tekst
        gelezen = turn.gelezen_tot
        venster = running_window(tekst, gelezen)
        if venster is None or not await self._settle(final):
            # Nothing to read after all, or a line moved a moment ago: the
            # next round looks again.
            return False
        context = await self._context(sessie_id, activiteit_id, onderwerp, client)
        beurt = self._as_beurt(
            sessie_id,
            item,
            turn,
            sprekers,
            channel_id,
            tekst=tekst,
            lines=tuple(
                Line(line.start - item.offset, line.tekst) for line in final.lines
            ),
            gelezen_tot=gelezen,
            loopt=True,
        )
        _asked_at[turn.row_id] = now
        try:
            outcome = await asyncio.wait_for(
                vragen.beoordeel_beurt(beurt, context), WINDOW_TIMEOUT
            )
            failed = outcome.opnieuw_proberen
        except Exception:
            logger.exception("Lopende spreekbeurt %s niet gelezen", turn.row_id)
            await self.session.rollback()
            outcome = None
            failed = True
        if failed or outcome is None:
            result.fouten += 1
            attempts = await self._count_attempt(turn.row_id)
            # Only this turn waits, as for an answer that is over.
            _answer_pause.failed(turn.row_id, now)
            if attempts >= WINDOW_ATTEMPTS:
                logger.warning(
                    "Lopende spreekbeurt %s: venster vanaf teken %d na %d pogingen"
                    " overgeslagen, verder vanaf %d",
                    turn.row_id,
                    gelezen,
                    attempts,
                    venster[2],
                )
                await self._keep_position(turn.row_id, venster[2])
                _answer_pause.succeeded(turn.row_id)
            return False
        _answer_pause.succeeded(turn.row_id)
        if outcome.gelezen_tot > gelezen:
            await self._keep_position(turn.row_id, outcome.gelezen_tot)
        if outcome.uitkomst == UITKOMST_GEMARKEERD:
            result.toezeggingen += outcome.toezeggingen
        return False

    async def _ended(self, sessie_id: uuid.UUID, now: datetime) -> list[_Ended]:
        """The parts of a debate that are over and whose closing words were
        not looked at yet for the list of toezeggingen.

        A part is ready when its end is there, its text is complete, no
        line of it can still move to another speaker, and every turn of it
        was read: the list is matched to the toezeggingen those turns
        held. Whether the row of the end was read (`beoordeeld_at`) is how
        "looked at" is kept, so that the list is read once.

        Only parts in which the chairman speaks of toezeggingen at all
        come back. Any other part is done here and now: it needs no list
        of speakers and no model, and most debates have no list. So is a
        part that ended longer ago than `LIST_NOT_AFTER`.
        """
        # Nearly every round of a debate that is running: nothing ended.
        if not await self.session.scalar(
            select(DebatSpreekbeurt.id)
            .where(
                DebatSpreekbeurt.sessie_id == sessie_id,
                DebatSpreekbeurt.event_type == dd.EVENT_DEBATE_END,
                DebatSpreekbeurt.beoordeeld_at.is_(None),
            )
            .limit(1)
        ):
            return []
        sessie = (
            await self.session.execute(
                select(DebatSessie.debat_direct_ids, DebatSessie.ondertitels).where(
                    DebatSessie.id == sessie_id
                )
            )
        ).first()
        if sessie is None:
            return []
        parts, ondertitels = list(sessie[0] or []), dict(sessie[1] or {})
        rows = (
            await self.session.execute(
                select(
                    DebatSpreekbeurt.id,
                    DebatSpreekbeurt.debat_direct_id,
                    DebatSpreekbeurt.event_type,
                    DebatSpreekbeurt.beurt_soort,
                    DebatSpreekbeurt.object_id,
                    DebatSpreekbeurt.event_start,
                    DebatSpreekbeurt.post_id,
                    DebatSpreekbeurt.kop,
                    DebatSpreekbeurt.tekst,
                    DebatSpreekbeurt.beoordeeld_at,
                )
                .where(DebatSpreekbeurt.sessie_id == sessie_id)
                .order_by(*ORDER)
            )
        ).all()
        found: list[_Ended] = []
        for debate_id in parts:
            of_part = [row for row in rows if row[1] == debate_id]
            ends = [row for row in of_part if row[2] == dd.EVENT_DEBATE_END]
            if not ends or ends[-1][9] is not None:
                continue
            end = ends[-1]
            if now - end[5] > LIST_NOT_AFTER:
                await self._mark(end[0], now)
                continue
            entry = dict(ondertitels.get(debate_id) or {})
            if not text_is_complete(entry, None, end[5], now):
                continue
            if (
                entry.get("audio")
                and voices_listen()
                and now - end[5] < NEVER_MOVES_AFTER
            ):
                # A line around the last change of speaker can still be
                # given to the chairman, or taken away.
                continue
            turns = await load_turns(self.session, sessie_id, debate_id)
            unread = any(
                turn.is_member and turn.beoordeeld_at is None and turn.text
                for turn in turns
            )
            if unread and now - end[5] < LIST_WAITS_FOR_TURNS:
                continue
            spoken: list[tuple[str, str, datetime, str, tuple[uuid.UUID, ...]]] = []
            for row_id, _, kind, turn_kind, who, start, _, _, tekst, _ in of_part:
                if kind in _SPEAKING:
                    spoken.append(
                        (turn_kind or kind, who or "", start, tekst or "", (row_id,))
                    )
                elif kind in _CLOSING:
                    # What is said after the end is no part of the debate.
                    continue
                else:
                    spoken.append((SOORT_CHAIRMAN, "", start, tekst or "", (row_id,)))
            if not any(
                kind == SOORT_CHAIRMAN and "zegging" in tekst.lower()
                for kind, _, _, tekst, _ in spoken
            ):
                await self._mark(end[0], now)
                continue
            first = next((row[5] for row in of_part), end[5])
            found.append(
                _Ended(
                    row_id=end[0],
                    post_id=end[6],
                    kop=end[7] or "",
                    end=end[5],
                    first=first,
                    offset=timedelta(milliseconds=entry.get("offset_ms") or 0),
                    spoken=tuple(spoken),
                )
            )
        return found

    async def _read_list(
        self,
        sessie_id: uuid.UUID,
        part: _Ended,
        vragen: DebatVraagService,
        client: httpx.AsyncClient,
        now: datetime,
        result: VraagTickResult,
    ) -> None:
        """Look for the chairman's list in the closing words of a part, and
        have it read if it is there.

        Which words are the list is decided by rule
        (`find_closing_list`); nothing else the chairman said goes to the
        model. A part without a list costs no call.
        """
        sprekers = await self._sprekers_for(client, part.first)
        if sprekers is None:
            # Without the list of speakers nobody can tell whether a
            # bewindspersoon answered before the chairman's words. Asked
            # again later, and later each time.
            result.fouten += 1
            _list_pause.failed(part.row_id, now)
            return
        said: list[Spoken] = []
        for kind, who, start, tekst, _ in part.spoken:
            if kind == SOORT_CHAIRMAN:
                wie = CHAIRMAN
            else:
                spreker = sprekers.get(who)
                wie = (
                    BEWINDSPERSOON
                    if spreker is not None and is_bewindspersoon(spreker)
                    else MEMBER
                )
            said.append(Spoken(wie, start, tekst))
        closing = find_closing_list(said, part.end)
        if closing is None:
            await self._mark(part.row_id, now)
            return
        channel_id, activiteit_id, onderwerp = (
            await self.session.execute(
                select(
                    DebatSessie.channel_id,
                    DebatSessie.activiteit_id,
                    DebatSessie.onderwerp,
                ).where(DebatSessie.id == sessie_id)
            )
        ).one()
        context = await self._context(sessie_id, activiteit_id, onderwerp, client)
        rows = [row for index, _ in closing.delen for row in part.spoken[index][4]]
        beurt = Beurt(
            sessie_id=sessie_id,
            spreekbeurt_id=part.row_id,
            post_id=part.post_id,
            channel_id=channel_id,
            soort=SOORT_CHAIRMAN,
            spreker=VOORZITTER,
            fractie=None,
            start=closing.start,
            moment_url=moment_url_from_kop(part.kop),
            tekst=closing.tekst,
            lines=await self._lines_of(rows, part.offset),
            slotlijst=True,
        )
        try:
            outcome = await asyncio.wait_for(
                vragen.beoordeel_beurt(beurt, context), JUDGE_TIMEOUT
            )
            unusable = outcome.uitkomst == UITKOMST_LLM_ONBRUIKBAAR
            failed = outcome.opnieuw_proberen or unusable
        except Exception:
            logger.exception("Slotlijst bij %s niet gelezen", part.row_id)
            await self.session.rollback()
            outcome = None
            unusable = False
            failed = True
        if failed:
            result.fouten += 1
            attempts = await self._count_attempt(part.row_id)
            if attempts >= (LIST_UNUSABLE_ATTEMPTS if unusable else LIST_ATTEMPTS):
                logger.warning(
                    "Slotlijst bij %s na %d pogingen opgegeven", part.row_id, attempts
                )
                _list_pause.succeeded(part.row_id)
                await self._mark(part.row_id, now)
            else:
                _list_pause.failed(part.row_id, now)
            return
        _list_pause.succeeded(part.row_id)
        assert outcome is not None
        if outcome.uitkomst == UITKOMST_GEMARKEERD:
            result.toezeggingen += outcome.toezeggingen
        await self._mark(part.row_id, now)
        result.beoordeeld += 1

    async def _lines_of(
        self, rows: list[uuid.UUID], offset: timedelta
    ) -> tuple[Line, ...]:
        """The subtitle lines of some rows, row after row and within a row
        by moment. See `_lines` for the clock they are on."""
        if not rows:
            return ()
        found = (
            await self.session.execute(
                select(
                    DebatOndertitel.spreekbeurt_id,
                    DebatOndertitel.start,
                    DebatOndertitel.tekst,
                )
                .where(DebatOndertitel.spreekbeurt_id.in_(rows))
                .order_by(DebatOndertitel.start)
            )
        ).all()
        per_row: dict[uuid.UUID, list[Line]] = {}
        for row_id, start, tekst in found:
            per_row.setdefault(row_id, []).append(Line(start - offset, tekst))
        return tuple(line for row_id in rows for line in per_row.get(row_id, []))

    async def _read_at(self, row_id: uuid.UUID) -> datetime | None:
        """When a turn was read, as the table has it now."""
        return await self.session.scalar(
            select(DebatSpreekbeurt.beoordeeld_at).where(DebatSpreekbeurt.id == row_id)
        )

    async def _position(self, row_id: uuid.UUID) -> int:
        """How many characters of an answer were read and stored."""
        return (
            await self.session.scalar(
                select(DebatSpreekbeurt.antwoord_gelezen_tot).where(
                    DebatSpreekbeurt.id == row_id
                )
            )
        ) or 0

    async def _keep_position(self, row_id: uuid.UUID, position: int) -> None:
        """Note how far an answer was read; the tries of the next window
        start at none."""
        await self.session.execute(
            update(DebatSpreekbeurt)
            .where(DebatSpreekbeurt.id == row_id)
            .values(antwoord_gelezen_tot=position, beoordeel_pogingen=0)
        )
        await self.session.commit()

    async def _lines(self, turn: Turn, offset: timedelta) -> tuple[Line, ...]:
        """The subtitle lines the text of a turn is made of, in its order.

        Row after row as `load_turns` joined them, and within a row by
        moment, as `derive_text` does. A line is on the clock of the sound.
        The events are `offset` earlier, and the site adds that itself when
        it seeks to a moment: the timeline links to the event time of a
        turn and the site plays where the speaker begins, which the
        subtitles have `offset` later. So it comes off here.
        """
        return await self._lines_of(list(turn.rows), offset)

    async def _count_attempt(self, row_id: uuid.UUID) -> int:
        attempts = (
            await self.session.execute(
                update(DebatSpreekbeurt)
                .where(DebatSpreekbeurt.id == row_id)
                .values(beoordeel_pogingen=DebatSpreekbeurt.beoordeel_pogingen + 1)
                .returning(DebatSpreekbeurt.beoordeel_pogingen)
            )
        ).scalar_one()
        await self.session.commit()
        return attempts

    async def _mark(self, row_id: uuid.UUID, now: datetime) -> None:
        await self.session.execute(
            update(DebatSpreekbeurt)
            .where(DebatSpreekbeurt.id == row_id)
            .values(beoordeeld_at=now)
        )
        # Per turn: one that has been read is not read again after a
        # restart halfway through a round.
        await self.session.commit()

    async def _sprekers_for(
        self, client: httpx.AsyncClient, moment: datetime
    ) -> dict[str, dd.Spreker] | None:
        day = moment.astimezone(AMSTERDAM).date()
        key = day.isoformat()
        if key not in self._sprekers:
            try:
                self._sprekers[key] = await dd.fetch_sprekers(client, day)
            except dd.DebatDirectError:
                logger.warning("Sprekers niet te lezen", exc_info=True)
                return None
        return self._sprekers[key]

    async def _context(
        self,
        sessie_id: uuid.UUID,
        activiteit_id: str,
        onderwerp: str,
        client: httpx.AsyncClient,
    ) -> DebatContext:
        known = self.contexts.get(sessie_id)
        now = datetime.now(UTC)
        if known is not None and not _names_may_follow(known, now):
            return known
        try:
            activiteit = await tk_activiteit.fetch_activiteit(activiteit_id, client)
        except tk_activiteit.TkApiError:
            logger.warning("Activiteit %s niet te lezen", activiteit_id, exc_info=True)
            activiteit = None
        if activiteit is None and known is not None:
            # Asked again for the names and got nothing. What was known
            # stays, and the next try is a while from now, not with the
            # next turn: an API that is down is not asked every turn.
            self.contexts[sessie_id] = replace(known, gelezen_at=now)
            return self.contexts[sessie_id]
        if activiteit is None:
            # The subject alone is enough to read a turn by. Not kept, so
            # the next turn asks again for who is at the table.
            return DebatContext(onderwerp=onderwerp)
        self.contexts[sessie_id] = replace(
            DebatContext.from_activiteit(activiteit), gelezen_at=now
        )
        return self.contexts[sessie_id]
