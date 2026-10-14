"""The timeline: who speaks when, in the channel of a debate.

On the day of a debate this finds it on Debat Direct, puts room and stream
in the channel header, and then posts one message per turn at speaking,
each with a link to that moment in the broadcast. No transcript yet; that is
added to these same messages later.

Runs as ticks from the worker. One tick looks at every debate channel whose
debate is today, and does whatever is next for it. Everything it has done
is in the database, so a restart continues where the last tick stopped.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from bouwmeester.core.config import get_settings
from bouwmeester.models.debat_sessie import (
    TIJDLIJN_AFGELAST,
    TIJDLIJN_AFGELOPEN,
    TIJDLIJN_GEKOPPELD,
    TIJDLIJN_LOOPT,
    DebatSessie,
    DebatSpreekbeurt,
)
from bouwmeester.services import debat_direct as dd
from bouwmeester.services import debat_stem as stem
from bouwmeester.services.debat_kanaal_service import (
    AMSTERDAM,
    channel_header,
    format_moment,
)
from bouwmeester.services.debat_stemmen_service import Budget, DebatStemmen
from bouwmeester.services.debat_transcript_service import (
    ORDER,
    WRITE_AGAIN,
    DebatTranscript,
)
from bouwmeester.services.mattermost_service import MattermostService
from bouwmeester.services.mattermost_utils import (
    escape_mattermost_prose as _escape,
)
from bouwmeester.services.tk_activiteit import (
    STATUS_CANCELLED,
    STATUS_MOVED,
    Activiteit,
    TkApiError,
    fetch_activiteit,
)

logger = logging.getLogger(__name__)

# How long before the start a debate is looked for on Debat Direct. The
# agenda of a day is there the evening before.
LOOKAHEAD = timedelta(hours=14)
# How long after the start a debate that was never found is still looked
# for. Past this it is given up on.
GIVE_UP_AFTER = timedelta(hours=16)
# How often the activiteit and the agenda are read again while waiting, and
# while a debate runs to find a second part after a break.
RECHECK_EVERY = timedelta(minutes=5)
# And how soon after a reading of the agenda that failed.
RECHECK_SOON = timedelta(minutes=1)
# A debate counts as over this long after its last part ended. Debat Direct
# cuts a plenary debate in two around a break, and the second part only
# appears when it starts.
END_GRACE = timedelta(hours=3)
# Events older than this when the timeline first sees a debate are history:
# the timeline joined a debate that was already running. Posting them would
# put a hundred messages in the channel at once.
BACKLOG_AGE = timedelta(minutes=3)
# The same for a debate the timeline was already following, with more
# patience: after the worker or Debat Direct was away for a while, what was
# missed is history too. Without this half an hour of absence comes back as
# fifty messages in one burst.
GAP_AGE = timedelta(minutes=10)
# A debate is not asked for its events until this long before its planned
# start. Every poll downloads the whole debate, and a debate found the
# evening before would be polled thousands of times for nothing.
POLL_BEFORE_START = timedelta(minutes=15)

_HTTP_TIMEOUT = 15.0
_SPEAKING = (dd.EVENT_SPEAKER, dd.EVENT_INTERRUPTER)
# Who can hold the floor: a member, or the chairman.
_FLOOR = (*_SPEAKING, dd.EVENT_CHAIRMAN)
# Messages the chairman's words go under, until a member gets the floor. A
# procedurevergadering has no events between its start and its end at all,
# so without the start among these its whole text would go unseen.
CHAIR_OPENS = (
    dd.EVENT_CHAIRMAN,
    dd.EVENT_DEBATE_START,
    dd.EVENT_CONTINUED,
    dd.EVENT_CHAIRMAN_CHANGE,
)
# Messages that get text under them later, so their first line is kept.
_WITH_TEXT = (*_SPEAKING, *CHAIR_OPENS, dd.EVENT_SUSPENDED, dd.EVENT_DEBATE_END)
# What the channel would have been told. A missed stretch with any of these
# in it is said to have been missed; one with only the chairman giving the
# floor is not.
_ANNOUNCED = (
    *_SPEAKING,
    dd.EVENT_DEBATE_START,
    dd.EVENT_SUSPENDED,
    dd.EVENT_CONTINUED,
    dd.EVENT_CHAIRMAN_CHANGE,
    dd.EVENT_DEBATE_END,
)

_ACTIVE = (None, TIJDLIJN_GEKOPPELD, TIJDLIJN_LOOPT)


def _hhmm(moment: datetime) -> str:
    return moment.astimezone(AMSTERDAM).strftime("%H:%M")


def _linked_time(debat: dd.DdDebat, event: dd.DdEvent) -> str:
    """The time of an event, as a link to that moment where that is possible."""
    url = dd.moment_url(debat, event)
    tijd = _hhmm(event.start)
    return f"[{tijd}]({url})" if url else tijd


# One person, two events in two roles, close together: one turn. Debat
# Direct enters someone who gets the floor as interrupter first and as
# speaker seconds later, and the channel then showed that person twice,
# first as "interruptie", with the text cut over the two messages.
#
# Measured on the 170 debates of 22 September to 6 October 2026 (10,187
# events of someone speaking, some 8,200 turns): 108 times in 39 debates the
# person who had the floor got an event in the other role with nobody else
# speaking in between. 99 times interrupter and then speaker, 9 times the
# other way. All 108 came within 40 seconds of the start of the turn (48
# of the 99 within 2 seconds, 81 within 10); the next ones came after 61,
# 78, 132, 160 and 265 seconds, and those are someone who interrupts and
# is given the floor afterwards. The bound sits in that gap. It counts
# from the start of the turn, not from its last event, so what is decided
# again is never more than this much of a turn.
SAME_TURN_WITHIN = timedelta(seconds=50)

_INTERRUPTION = ("↳ ", " · interruptie")


def turn_kind(kind: str, began: datetime, event: dd.DdEvent) -> str | None:
    """What kind a turn is once this event of the same person is part of it.

    `kind` is what the turn is so far and `began` when it began. ``None``
    for an event that is a turn of its own: the same person in another
    role is a new turn, as a speaker who is given the floor a while after
    interrupting.

    Someone who simply carries on after the chairman said a word stays in
    the turn, however long it has lasted. In the other role, the event that
    came last says what the turn is: it is the correction of the one before
    it. That is nearly always the speaker. The other way was seen 5 times
    with seconds between (three within 5 seconds, and after 29 and 35), and
    where what followed showed which was right, it was the interruption. In
    the same second the order of the two is not known (7 times), and then it
    is the speaker's.
    """
    if event.type == kind:
        return kind
    if dd.EVENT_CHAIRMAN in (kind, event.type):
        # The chair is no role a member speaks in.
        return None
    if event.start - began > SAME_TURN_WITHIN or event.start < began:
        return None
    if event.start == began:
        return dd.EVENT_SPEAKER
    return event.type


def heading_as(kop: str, kind: str) -> str:
    """The first line of a turn, for the kind the turn turned out to be.

    Made from the line that is there and not from the event again: the
    time in it, and the moment it links to, stay those of the start of the
    turn.
    """
    before, after = _INTERRUPTION
    bare = kop.removeprefix(before).removesuffix(after)
    return f"{before}{bare}{after}" if kind == dd.EVENT_INTERRUPTER else bare


def format_event(
    event: dd.DdEvent, debat: dd.DdDebat, sprekers: dict[str, dd.Spreker]
) -> str | None:
    """The message for one event, or ``None`` for an event that gets none.

    One message per turn at speaking, the chairman's included: what is
    said from the chair (the order of business, a ruling, the list of
    toezeggingen) is part of the debate. Whether an event of someone
    speaking is a turn of its own is not decided here; see `turn_kind`.
    """
    if event.type in _SPEAKING:
        spreker = sprekers.get(event.object_id)
        naam = _escape(spreker.label if spreker else "Onbekende spreker")
        regel = f"**{naam}** · {_linked_time(debat, event)}"
        return heading_as(regel, event.type)
    if event.type == dd.EVENT_CHAIRMAN:
        spreker = sprekers.get(event.object_id)
        naam = f" {_escape(spreker.naam)}" if spreker else ""
        return f"🔨 **Voorzitter{naam}** · {_linked_time(debat, event)}"
    if event.type == dd.EVENT_CHAIRMAN_CHANGE:
        spreker = sprekers.get(event.object_id)
        if spreker is None:
            return None
        naam = _escape(spreker.naam)
        return f"_Voorzitter is nu {naam}_ · {_hhmm(event.start)}"
    if event.type == dd.EVENT_DEBATE_START:
        zaal = f" in de {_escape(debat.location_name)}" if debat.location_name else ""
        return f"▶️ **Het debat is begonnen**{zaal} · {_linked_time(debat, event)}"
    if event.type == dd.EVENT_SUSPENDED:
        return f"⏸️ **Geschorst** · {_hhmm(event.start)}"
    if event.type == dd.EVENT_CONTINUED:
        return f"▶️ **Hervat** · {_linked_time(debat, event)}"
    if event.type == dd.EVENT_DEBATE_END:
        return f"⏹️ **Het debat is afgelopen** · {_hhmm(event.start)}"
    return None


@dataclass
class Floor:
    """The turn that has the floor in a part: the last one with a message."""

    # What the turn is. Not always what its first event said.
    kind: str
    who: str
    # When the event came that the message was posted for.
    began: datetime
    # The first line of the message as it is now.
    kop: str | None


def floors_from(rows) -> dict[str, Floor]:  # type: ignore[no-untyped-def]
    """Who has the floor in every part, going by the rows of a debate.

    `rows` are (part, kind, start, person, message, kind of the turn, first
    line), in the order of the timeline. This is what a tick starts from,
    so that after a restart it goes on exactly as it would have.
    """
    floors: dict[str, Floor] = {}
    for part, kind, start, who, post_id, beurt_soort, kop in rows:
        speaking = kind in _FLOOR
        turn = (beurt_soort or kind) if speaking else kind
        floor = floors.get(part)
        if not post_id:
            if speaking and (floor is None or (floor.kind, floor.who) != (turn, who)):
                # Someone else spoke without a message: that only
                # happens in a stretch the timeline missed. Who spoke
                # before it says nothing about who speaks after it.
                floors.pop(part, None)
            continue
        if speaking:
            floors[part] = Floor(turn, who, start, kop)
        else:
            # A break or a new chairman was posted in between: whoever
            # speaks next is a new turn, also if it is the same person.
            floors.pop(part, None)
    return floors


@dataclass
class TickResult:
    sessies: int = 0
    gekoppeld: int = 0
    berichten: int = 0
    fouten: int = 0

    def summary(self) -> str:
        return (
            f"{self.sessies} debatten, {self.gekoppeld} gekoppeld, "
            f"{self.berichten} berichten, {self.fouten} fouten"
        )


class DebatTijdlijnService:
    def __init__(
        self, session: AsyncSession, mattermost: MattermostService | None = None
    ) -> None:
        self.session = session
        self.mattermost = mattermost or MattermostService(session)
        # Per day, for the length of one tick.
        self._sprekers: dict[str, dict[str, dd.Spreker]] = {}
        self._agenda: dict[str, list[dd.DdDebat]] = {}
        # The debates read in this tick, for whoever needs them after.
        self._debates: dict[str, dd.DdDebat] = {}
        # How many debates this tick looks at: they share what a tick may
        # spend on telling voices apart.
        self._sessies = 1

    async def close(self) -> None:
        await self.mattermost.close()

    async def tick(self, now: datetime | None = None) -> TickResult:
        """Do what is next for every debate that is on today."""
        now = now or datetime.now(UTC)
        result = TickResult()
        stmt = select(DebatSessie.id).where(
            DebatSessie.channel_id.is_not(None),
            DebatSessie.aanvang.is_not(None),
            DebatSessie.aanvang <= now + LOOKAHEAD,
            DebatSessie.aanvang >= now - GIVE_UP_AFTER - END_GRACE,
            DebatSessie.tijdlijn_status.is_(None)
            | DebatSessie.tijdlijn_status.in_((TIJDLIJN_GEKOPPELD, TIJDLIJN_LOOPT)),
        )
        sessie_ids = list((await self.session.execute(stmt)).scalars().all())
        # A voice does not outlive its debate: what is not followed any
        # more is forgotten here, whatever the reason it dropped out, and
        # so is what has not been used for a while.
        stem.VOICES.keep_only(sessie_ids)
        stem.VOICES.expire(now)
        self._sessies = len(sessie_ids)
        if not await self.mattermost.is_enabled():
            return result

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            for sessie_id in sessie_ids:
                result.sessies += 1
                try:
                    await self._advance(sessie_id, client, now, result)
                    await self.session.commit()
                except Exception:
                    # One debate that breaks must not stop the others, and
                    # must not stop the next tick from trying again.
                    await self.session.rollback()
                    result.fouten += 1
                    logger.exception("Tijdlijn van sessie %s liep vast", sessie_id)
        try:
            # After the debates of today, which is what a round is for,
            # and also with none on today: people tick questions off in
            # the channel of a debate that is over.
            await DebatTranscript(self.session, self.mattermost).write_counts(
                result, now
            )
        except Exception as exc:
            await self.session.rollback()
            result.fouten += 1
            logger.warning(
                "Tellingen onder berichten niet bijgewerkt (%s)", type(exc).__name__
            )
        return result

    async def _advance(
        self,
        sessie_id: uuid.UUID,
        client: httpx.AsyncClient,
        now: datetime,
        result: TickResult,
    ) -> None:
        sessie = await self.session.get(DebatSessie, sessie_id)
        if sessie is None or sessie.channel_id is None:
            return
        await self._step(sessie, client, now, result)
        if sessie.tijdlijn_status not in _ACTIVE:
            # Over or cancelled: the voices go at once, not a tick later.
            stem.VOICES.forget(sessie_id)

    async def _step(
        self,
        sessie: DebatSessie,
        client: httpx.AsyncClient,
        now: datetime,
        result: TickResult,
    ) -> None:
        due = (
            sessie.tijdlijn_gecontroleerd_at is None
            or now - sessie.tijdlijn_gecontroleerd_at >= RECHECK_EVERY
        )

        if sessie.tijdlijn_status is None:
            if not due:
                return
            sessie.tijdlijn_gecontroleerd_at = now
            if await self.mattermost.channel_is_gone(sessie.channel_id):
                # Someone archived the channel. Posting into it fails, and
                # a post that fails is retried on every tick.
                logger.info(
                    "Kanaal %s bestaat niet meer; geen tijdlijn", sessie.channel_id
                )
                sessie.tijdlijn_status = TIJDLIJN_AFGELOPEN
                return
            if await self._find_on_debat_direct(sessie, client, now):
                result.gekoppeld += 1
            elif sessie.tijdlijn_status is None and (
                sessie.aanvang and now - sessie.aanvang > GIVE_UP_AFTER
            ):
                # Never found. Say so once, instead of a channel that stays
                # silent without a reason.
                await self.mattermost.send_channel_message(
                    sessie.channel_id,
                    "Ik heb dit debat niet op Debat Direct kunnen vinden, dus "
                    "er komt geen tijdlijn in dit kanaal.",
                )
                sessie.tijdlijn_status = TIJDLIJN_AFGELOPEN
            return

        if due:
            # Look for a later part of the same debate.
            sessie.tijdlijn_gecontroleerd_at = now
            await self._find_more_parts(sessie, client, now)

        fouten = result.fouten
        await self._post_new_events(sessie, client, now, result)
        # Taken here, before the headings: a heading that cannot be
        # rewritten is counted as an error too, and it must not keep the
        # text of the whole debate from being read.
        all_posted = result.fouten == fouten
        await self._write_changed(sessie, result)
        if (
            get_settings().DEBAT_TRANSCRIPT_ENABLED
            and sessie.tijdlijn_status == TIJDLIJN_LOOPT
            # While a message of the timeline waits to be posted, its turn
            # is not known yet, and what is said in it would be filed
            # under the speaker before. The subtitles keep for an hour.
            and all_posted
        ):
            await DebatTranscript(
                self.session, self.mattermost, await self._stemmen()
            ).update(sessie, self._debates, client, now, result)

    async def _stemmen(self) -> DebatStemmen | None:
        """What tells the voices apart, or ``None`` when that is not done.

        Without the model a line stays in the turn the time put it in,
        which is how it was before voices were listened to.
        """
        settings = get_settings()
        if not settings.DEBAT_STEMMEN_ENABLED:
            return None
        # Reading the model takes a moment the first time; after that this
        # is a lookup.
        embedder = await asyncio.to_thread(stem.load, settings.DEBAT_STEM_MODEL_PATH)
        if embedder is None:
            return None
        return DebatStemmen(self.session, embedder, Budget.share(self._sessies))

    async def _read_activiteit(
        self, sessie: DebatSessie, client: httpx.AsyncClient
    ) -> Activiteit | None:
        try:
            return await fetch_activiteit(sessie.activiteit_id, client)
        except TkApiError:
            logger.warning(
                "Activiteit %s niet opnieuw te lezen",
                sessie.activiteit_id,
                exc_info=True,
            )
            return None

    def _as_activiteit(self, sessie: DebatSessie) -> Activiteit:
        """What the sessie remembers, for when the TK API cannot be read."""
        return Activiteit(
            id=sessie.activiteit_id,
            nummer=sessie.activiteit_nummer,
            soort=None,
            onderwerp=sessie.onderwerp,
            aanvang=sessie.aanvang,
            einde=None,
            status=None,
            commissie=None,
            bewindspersonen=(),
            agendapunten=(),
        )

    async def _agenda_for(
        self, client: httpx.AsyncClient, moment: datetime
    ) -> list[dd.DdDebat]:
        day = moment.astimezone(AMSTERDAM).date()
        key = day.isoformat()
        if key not in self._agenda:
            self._agenda[key] = await dd.fetch_agenda(client, day)
        return self._agenda[key]

    async def _find_on_debat_direct(
        self, sessie: DebatSessie, client: httpx.AsyncClient, now: datetime
    ) -> bool:
        """Read the appointment again and look for it on Debat Direct.

        The appointment is read again because it changes: of 250 measured
        activiteiten 14 were cancelled and 11 moved after the convocatie.
        A cancelled debate is said so in the channel, instead of waiting
        for a stream that never comes.
        """
        activiteit = await self._read_activiteit(sessie, client)
        if activiteit is not None:
            if activiteit.status in (STATUS_CANCELLED, STATUS_MOVED):
                wat = (
                    "geannuleerd"
                    if activiteit.status == STATUS_CANCELLED
                    else "verplaatst; de nieuwe datum komt als een nieuwe vergadering"
                )
                await self.mattermost.send_channel_message(
                    sessie.channel_id, f"⚠️ Dit debat is {wat}."
                )
                sessie.tijdlijn_status = TIJDLIJN_AFGELAST
                return False
            if activiteit.aanvang and activiteit.aanvang != sessie.aanvang:
                sessie.aanvang = activiteit.aanvang
        else:
            activiteit = self._as_activiteit(sessie)

        if activiteit.aanvang is None:
            return False
        try:
            agenda = await self._agenda_for(client, activiteit.aanvang)
        except dd.DebatDirectError:
            logger.warning("Agenda van Debat Direct niet te lezen", exc_info=True)
            return False
        parts = dd.match_debates(activiteit, agenda)
        if not parts:
            return False

        sessie.debat_direct_ids = [part.id for part in parts]
        if not await self._move_status(sessie, None, TIJDLIJN_GEKOPPELD):
            return False
        first = parts[0]
        header = channel_header(
            activiteit, zaal=first.location_name, stream_url=dd.debate_url(first)
        )
        if not await self.mattermost.update_channel(sessie.channel_id, header=header):
            logger.warning("Header van kanaal %s niet bijgewerkt", sessie.channel_id)
        logger.info(
            "Debat %s gekoppeld aan Debat Direct: %s (%s)",
            sessie.onderwerp,
            ", ".join(sessie.debat_direct_ids),
            format_moment(activiteit),
        )
        return True

    async def _find_more_parts(
        self, sessie: DebatSessie, client: httpx.AsyncClient, now: datetime
    ) -> None:
        if sessie.aanvang is None:
            return
        try:
            agenda = await self._agenda_for(client, sessie.aanvang)
        except dd.DebatDirectError:
            # Not in five minutes but in one: this reading is also what
            # notices a debate that starts early.
            sessie.tijdlijn_gecontroleerd_at = now - RECHECK_EVERY + RECHECK_SOON
            return
        known = list(sessie.debat_direct_ids or [])
        # A debate can start well before its planned time: plenary items
        # were measured up to 38 minutes early. The agenda says so, and it
        # is read here anyway. Its start, the real one once
        # the debate runs, replaces an appointment that is later, so the
        # next ticks know it too.
        for part in agenda:
            start = dd.start_of(part)
            if part.id in known and start is not None and start < sessie.aanvang:
                sessie.aanvang = start
        new = [p.id for p in dd.later_parts(sessie.onderwerp, known, agenda)]
        if new:
            # A new list, not an append: a JSON column only notices a
            # change when the value itself is replaced.
            sessie.debat_direct_ids = [*known, *new]
            logger.info("Vervolg van debat %s gevonden: %s", sessie.onderwerp, new)

    async def _sprekers_for(
        self, client: httpx.AsyncClient, debat: dd.DdDebat
    ) -> dict[str, dd.Spreker]:
        moment = debat.started_at or debat.starts_at
        if moment is None:
            return {}
        day = moment.astimezone(AMSTERDAM).date()
        key = day.isoformat()
        if key not in self._sprekers:
            try:
                self._sprekers[key] = await dd.fetch_sprekers(client, day)
            except dd.DebatDirectError:
                # Without names the timeline still says that someone spoke,
                # and when. Not cached, so the next tick tries again.
                logger.warning("Sprekers niet te lezen", exc_info=True)
                return {}
        return self._sprekers[key]

    async def _post_new_events(
        self,
        sessie: DebatSessie,
        client: httpx.AsyncClient,
        now: datetime,
        result: TickResult,
    ) -> None:
        rows = (
            await self.session.execute(
                select(
                    DebatSpreekbeurt.debat_direct_id,
                    DebatSpreekbeurt.event_type,
                    DebatSpreekbeurt.event_start,
                    DebatSpreekbeurt.object_id,
                    DebatSpreekbeurt.post_id,
                    DebatSpreekbeurt.beurt_soort,
                    DebatSpreekbeurt.kop,
                )
                .where(DebatSpreekbeurt.sessie_id == sessie.id)
                # Within one second the same order as the feed is read in:
                # a resumption comes before whoever speaks after it.
                # The order the transcription reads them in as well.
                .order_by(*ORDER)
            )
        ).all()
        seen = {(r[0], r[1], r[2], r[3]) for r in rows}
        ended = {r[0] for r in rows if r[1] == dd.EVENT_DEBATE_END}
        started_parts = {r[0] for r in rows}
        # The last turn that became a message, per part: a speaker who
        # carries on does not get a second one.
        floors = floors_from(rows)

        last_end: datetime | None = None
        for debate_id in list(sessie.debat_direct_ids or []):
            if debate_id in ended:
                end_rows = [
                    r[2]
                    for r in rows
                    if r[0] == debate_id and r[1] == dd.EVENT_DEBATE_END
                ]
                last_end = max([last_end, *end_rows]) if last_end else max(end_rows)
                continue
            if (
                debate_id not in started_parts
                and sessie.aanvang is not None
                and now < sessie.aanvang - POLL_BEFORE_START
            ):
                continue
            try:
                debat = await dd.fetch_debate(client, debate_id)
            except dd.DebatDirectError:
                logger.warning("Debat %s niet te lezen", debate_id, exc_info=True)
                continue
            if debat is None or not debat.events:
                continue
            self._debates[debate_id] = debat

            new = [
                e
                for e in debat.events
                if (debate_id, e.type, e.start, e.object_id) not in seen
            ]
            if not new:
                continue
            sprekers = await self._sprekers_for(client, debat)

            joining = debate_id not in started_parts
            too_old = GAP_AGE
            if joining and not await self._was_there_before(sessie.id, debat):
                too_old = BACKLOG_AGE
            old = [e for e in new if now - e.start > too_old]
            new = [e for e in new if now - e.start <= too_old]
            # Old and from before the last message: the feed added or
            # corrected an event afterwards. Nothing was missed, so nothing
            # is said. Old and after the last message: the timeline was
            # away, or could not post. The last message, not the last row:
            # a row without a message is also written while posting fails.
            last_posted = max(
                (r[2] for r in rows if r[0] == debate_id and r[4]), default=None
            )
            missed = [e for e in old if last_posted is None or e.start > last_posted]
            beurten = sum(1 for e in missed if e.type in _SPEAKING)
            is_over = any(e.type == dd.EVENT_DEBATE_END for e in missed)
            if any(e.type in _ANNOUNCED for e in missed):
                url = dd.debate_url(debat)
                waar = f"[Debat Direct]({url})" if url else "Debat Direct"
                aantal = "1 spreekbeurt" if beurten == 1 else f"{beurten} spreekbeurten"
                staan = "staat" if beurten == 1 else "staan"
                if joining and is_over:
                    melding = (
                        f"🎧 Dit debat was al afgelopen toen ik om {_hhmm(now)} "
                        f"aanhaakte; de {aantal} {staan} op {waar}."
                    )
                elif joining:
                    melding = (
                        f"🎧 Ik luister mee vanaf {_hhmm(now)}. Het debat "
                        f"was toen al bezig; de {aantal} daarvoor {staan} op {waar}."
                    )
                else:
                    hoeveel = f" ({aantal})" if beurten else ""
                    melding = (
                        f"⏭️ Ik was er even niet. Wat er tussen "
                        f"{_hhmm(missed[0].start)} en {_hhmm(missed[-1].start)} "
                        f"gebeurde{hoeveel} staat op {waar}."
                    )
                    if is_over:
                        melding += " Het debat is inmiddels afgelopen."
                post_id = await self.mattermost.send_channel_message(
                    sessie.channel_id, melding
                )
                if not post_id:
                    # Nothing is remembered before the channel has been told.
                    # Mattermost being down looks the same as having been
                    # away: what waits grows old. Remembering it here would
                    # drop it without a word.
                    logger.warning(
                        "Melding over gemist deel voor %s niet geplaatst", debate_id
                    )
                    result.fouten += 1
                    if await self._stop_if_channel_gone(sessie):
                        return
                    continue
                result.berichten += 1
                # What came before the gap says nothing about who speaks
                # after it.
                floors.pop(debate_id, None)
            for event in old:
                await self._remember(sessie.id, debate_id, event, None)
                if event.type == dd.EVENT_DEBATE_END:
                    ended.add(debate_id)
                    last_end = max(last_end, event.start) if last_end else event.start
            if old:
                # Commit the history before going on: a crash after this
                # must not make the next tick announce it again.
                await self.session.commit()

            for event in new:
                floor = floors.get(debate_id)
                if (
                    floor is not None
                    and event.type in _FLOOR
                    and event.object_id == floor.who
                    and (kind := turn_kind(floor.kind, floor.began, event))
                ):
                    # Part of the turn that has the floor: no message of
                    # its own.
                    if kind != floor.kind:
                        await self._change_turn(sessie.id, debate_id, floor, kind)
                    await self._remember(
                        sessie.id,
                        debate_id,
                        event,
                        None,
                        beurt_soort=kind if kind != event.type else None,
                    )
                    # Together: the row of the event and what it made of
                    # the turn.
                    await self.session.commit()
                    continue
                tekst = format_event(event, debat, sprekers)
                post_id = None
                if tekst:
                    post_id = await self.mattermost.send_channel_message(
                        sessie.channel_id, tekst
                    )
                    if not post_id:
                        # Not remembered, so the next tick tries it again.
                        # Stop here to keep the order of the debate.
                        logger.warning(
                            "Tijdlijnbericht voor %s niet geplaatst", debate_id
                        )
                        # Counted, so the heartbeat shows a timeline that
                        # is stuck instead of "ok".
                        result.fouten += 1
                        if await self._stop_if_channel_gone(sessie):
                            return
                        break
                    result.berichten += 1
                    if event.type in _FLOOR:
                        floors[debate_id] = Floor(
                            event.type, event.object_id, event.start, tekst
                        )
                    else:
                        floors.pop(debate_id, None)
                kop = tekst if post_id and event.type in _WITH_TEXT else None
                await self._remember(sessie.id, debate_id, event, post_id, kop)
                # Per event: a message that is in the channel has to be in
                # the database, or a restart posts it a second time.
                await self.session.commit()
                if event.type == dd.EVENT_DEBATE_END:
                    ended.add(debate_id)
                    last_end = max(last_end, event.start) if last_end else event.start

            if sessie.tijdlijn_status == TIJDLIJN_GEKOPPELD:
                if not await self._move_status(
                    sessie, TIJDLIJN_GEKOPPELD, TIJDLIJN_LOOPT
                ):
                    return

        parts = list(sessie.debat_direct_ids or [])
        if parts and all(p in ended for p in parts) and last_end is not None:
            if now - last_end > END_GRACE:
                sessie.tijdlijn_status = TIJDLIJN_AFGELOPEN

    async def _stop_if_channel_gone(self, sessie: DebatSessie) -> bool:
        """After a message that failed: is there still a channel to post in?

        Someone can archive the channel while the debate runs. Without this
        the message is tried again on every tick until the debate drops out
        of sight the next day, with an error in the heartbeat each time.
        """
        if not await self.mattermost.channel_is_gone(sessie.channel_id):
            return False
        logger.info("Kanaal %s bestaat niet meer; tijdlijn gestopt", sessie.channel_id)
        sessie.tijdlijn_status = TIJDLIJN_AFGELOPEN
        return True

    async def _move_status(
        self, sessie: DebatSessie, expected: str | None, new: str
    ) -> bool:
        """Take the timeline a step further, unless someone stopped it.

        The sessie was read at the start of the round. In the seconds since,
        someone can have pressed "stoppen met volgen". Writing the status
        from what was read then would undo that without a word: the channel
        says it was stopped and the bot goes on. So the step is only taken
        from the status it was read with; otherwise the status of now is
        taken over and the round leaves the debate alone.
        """
        moved = (
            await self.session.execute(
                update(DebatSessie)
                .where(
                    DebatSessie.id == sessie.id,
                    DebatSessie.tijdlijn_status.is_not_distinct_from(expected),
                )
                .values(tijdlijn_status=new)
                .execution_options(synchronize_session=False)
            )
        ).rowcount
        if not moved:
            await self.session.refresh(sessie, ["tijdlijn_status"])
            logger.info(
                "Tijdlijn van %s is intussen %s; deze ronde laat het zo",
                sessie.id,
                sessie.tijdlijn_status,
            )
            return False
        set_committed_value(sessie, "tijdlijn_status", new)
        return True

    async def _was_there_before(self, sessie_id: uuid.UUID, debat: dd.DdDebat) -> bool:
        """Whether the channel existed before this part of the debate began.

        Then the timeline did not join late: it only saw the start late,
        at most one round of reading the agenda. That gets the patience of
        a gap, not the short one for a channel made halfway through.
        """
        start = dd.start_of(debat)
        if start is None:
            return False
        created = await self.session.scalar(
            select(DebatSessie.created_at).where(DebatSessie.id == sessie_id)
        )
        return created is not None and created <= start

    async def _remember(
        self,
        sessie_id: uuid.UUID,
        debate_id: str,
        event: dd.DdEvent,
        post_id: str | None,
        kop: str | None = None,
        beurt_soort: str | None = None,
    ) -> None:
        stmt = (
            insert(DebatSpreekbeurt)
            .values(
                sessie_id=sessie_id,
                debat_direct_id=debate_id,
                event_type=event.type,
                event_start=event.start,
                object_id=event.object_id,
                post_id=post_id,
                kop=kop,
                beurt_soort=beurt_soort,
            )
            .on_conflict_do_nothing(constraint="uq_debat_spreekbeurt_event")
        )
        await self.session.execute(stmt)

    async def _change_turn(
        self, sessie_id: uuid.UUID, debate_id: str, floor: Floor, kind: str
    ) -> None:
        """Make the turn that has the floor another kind of turn.

        The message is in the channel already when the second event comes:
        the feed shows an event about 7 seconds after it happened and it is
        posted at once, and half of the second events come more than 2
        seconds after the first. Holding every interruption back until its
        second event can no longer come would cost up to 50 seconds each,
        for the 1 turn in 80 this happens to. So the message is posted as
        what the feed says and made into what it turned out to be.

        Only the rows change here. The message is written from them by the
        transcription, which is what writes it every other time as well;
        see `_write_changed`.
        """
        turn = (
            DebatSpreekbeurt.sessie_id == sessie_id,
            DebatSpreekbeurt.debat_direct_id == debate_id,
            DebatSpreekbeurt.object_id == floor.who,
            DebatSpreekbeurt.event_type.in_(_SPEAKING),
            DebatSpreekbeurt.event_start >= floor.began,
        )
        # On every row of the turn, so that each says by itself which turn
        # it is part of.
        await self.session.execute(
            update(DebatSpreekbeurt).where(*turn).values(beurt_soort=kind)
        )
        floor.kind = kind
        if floor.kop is None:
            return
        floor.kop = heading_as(floor.kop, kind)
        await self.session.execute(
            update(DebatSpreekbeurt)
            # One row of a turn carries the message.
            .where(*turn, DebatSpreekbeurt.post_id.is_not(None))
            .values(kop=floor.kop, tekst_geplaatst_hash=WRITE_AGAIN)
        )

    async def _write_changed(self, sessie: DebatSessie, result: TickResult) -> None:
        """Write the messages whose first line changed.

        Asked of the rows and not remembered from this tick: a message that
        could not be written, or a worker that stopped between the row and
        the message, is then simply done on the next tick. Also without
        the transcription switched on, which is otherwise what does this.
        """
        sessie_id, channel_id = sessie.id, sessie.channel_id
        if channel_id is None or sessie.tijdlijn_status not in _ACTIVE:
            return
        parts = (
            await self.session.execute(
                select(DebatSpreekbeurt.debat_direct_id)
                .where(
                    DebatSpreekbeurt.sessie_id == sessie_id,
                    DebatSpreekbeurt.tekst_geplaatst_hash == WRITE_AGAIN,
                )
                .distinct()
            )
        ).scalars()
        for debate_id in list(parts):
            await DebatTranscript(self.session, self.mattermost).write(
                sessie_id, channel_id, debate_id, result
            )
