"""Tests for handing finished turns to the marking of questions.

Two kinds. A whole debate played against the timeline, the subtitles and a
model that answers from a list, to see that a question ends up as a thread
under the right message at the right moment. And rows written by hand, for
everything about which turn is handed in when.

After that the message itself: the transcription and the marking both write
it, and neither may lose what the other wrote.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest
from sqlalchemy import select, update

from bouwmeester.models.debat_markering import (
    SOORT_VRAAG,
    STATUS_OPEN,
    DebatMarkering,
)
from bouwmeester.models.debat_sessie import (
    TIJDLIJN_AFGELOPEN,
    TIJDLIJN_GEKOPPELD,
    TIJDLIJN_LOOPT,
    DebatOndertitel,
    DebatSessie,
    DebatSpreekbeurt,
)
from bouwmeester.services import debat_direct as dd
from bouwmeester.services import debat_vraag_worker as mod
from bouwmeester.services import tk_activiteit
from bouwmeester.services.debat_kanaal_service import AMSTERDAM
from bouwmeester.services.debat_statusregel import voeg_samen
from bouwmeester.services.debat_tijdlijn_service import (
    END_GRACE,
    GIVE_UP_AFTER,
    LOOKAHEAD,
    DebatTijdlijnService,
    Floor,
    TickResult,
    heading_as,
)
from bouwmeester.services.debat_transcript import MESSAGE_LIMIT, render, split_text
from bouwmeester.services.debat_transcript_service import (
    MESSAGE_MAX,
    DebatTranscript,
    load_turns,
)
from bouwmeester.services.debat_vraag_moment import LEAD_IN, Line
from bouwmeester.services.debat_vraag_service import DebatVraagService
from bouwmeester.services.debat_vraag_worker import (
    MARGIN,
    DebatVraagWorker,
    moment_url_from_kop,
    text_is_complete,
)
from bouwmeester.services.tk_activiteit import (
    Activiteit,
    Bewindspersoon,
    TkApiError,
)
from tests.test_debat_tijdlijn import FULL, START, Feed, _debat, _sessie
from tests.test_debat_transcript import (
    BEHIND,
    OFFSET,
    Mattermost,
    Subtitles,
    _cue,
    _stream,
)
from tests.test_debat_vragen import FakeLLM, antwoord, vraag

SPREKERS = {
    "a": dd.Spreker("Kamerlid A", "X", "Tweede Kamerlid"),
    "b": dd.Spreker("Kamerlid B", "Y", "Tweede Kamerlid"),
    "c": dd.Spreker("Kamerlid C", "Z", "Tweede Kamerlid"),
    "m": dd.Spreker("Bewindspersoon A", None, "Minister van Voorbeelden"),
}
MINISTER = "Bewindspersoon A (Minister van Voorbeelden)"
STATUS_EEN = "❓ 1 vraag · 🔴 **open**"

Q_WANNEER = "Kan de minister zeggen wanneer het wetsvoorstel naar de Kamer komt?"
Q_BUDGET = "Is de minister bereid het budget voor dit jaar te verhogen?"
OPENING = "Voorzitter, dank u wel voor het woord."


class Chat(Mattermost):
    """Also remembers under which message a reply was posted."""

    def __init__(self) -> None:
        super().__init__()
        self.threads: list[tuple[str, str]] = []

    async def send_channel_message(self, channel_id, text, props=None, root_id=None):
        post_id = await super().send_channel_message(channel_id, text, props, root_id)
        if post_id and root_id:
            self.threads.append((root_id, text))
        return post_id


class Outside:
    """Who can speak today, and what the TK API knows about the debate."""

    def __init__(self, monkeypatch) -> None:
        self.sprekers_calls = 0
        self.sprekers_error = False
        self.activiteit_calls = 0
        self.activiteit_error = False
        self.activiteit_gone = False

        async def sprekers(client, day, base_url=None):
            self.sprekers_calls += 1
            if self.sprekers_error:
                raise dd.DebatDirectError("down")
            return SPREKERS

        async def activiteit(activiteit_id, client, base_url=None):
            self.activiteit_calls += 1
            if self.activiteit_error:
                raise TkApiError("down")
            if self.activiteit_gone:
                return None
            return Activiteit(
                id=activiteit_id,
                nummer="2026A00001",
                soort="Commissiedebat",
                onderwerp="Onderwerp volgens de Kamer",
                aanvang=START,
                einde=None,
                status="Gepland",
                commissie=None,
                bewindspersonen=(
                    Bewindspersoon("B. Bewindspersoon", "minister van Voorbeelden"),
                ),
                agendapunten=(),
            )

        monkeypatch.setattr(dd, "fetch_sprekers", sprekers)
        monkeypatch.setattr(tk_activiteit, "fetch_activiteit", activiteit)


@pytest.fixture(autouse=True)
def _no_pause_left_over():
    """The pause after a failure lives in the process; a test starts clean."""
    mod._pause.reset()
    yield
    mod._pause.reset()


@pytest.fixture
def handed(monkeypatch):
    """Every turn that was handed to the marking, with its context."""
    seen: list = []
    original = DebatVraagService.beoordeel_beurt

    async def record(self, beurt, context):
        seen.append((beurt, context))
        return await original(self, beurt, context)

    monkeypatch.setattr(DebatVraagService, "beoordeel_beurt", record)
    return seen


async def _follow(
    db_session,
    mm,
    feed,
    llm,
    until: float,
    start: float = -10,
    step: int = 10,
    contexts: dict | None = None,
) -> list:
    """The timeline and the marking side by side, as the worker runs them."""
    results = []
    now = START + timedelta(minutes=start)
    while now <= START + timedelta(minutes=until):
        feed.now = now
        await DebatTijdlijnService(db_session, mm).tick(now.astimezone(UTC))
        results.append(
            await DebatVraagWorker(db_session, mm, llm, contexts).tick(
                now.astimezone(UTC)
            )
        )
        now += timedelta(seconds=step)
    return results


async def _judged(db_session) -> dict[str, bool]:
    rows = (
        await db_session.execute(
            select(
                DebatSpreekbeurt.event_type,
                DebatSpreekbeurt.event_start,
                DebatSpreekbeurt.object_id,
                DebatSpreekbeurt.beoordeeld_at,
            )
            .where(DebatSpreekbeurt.post_id.is_not(None))
            .order_by(DebatSpreekbeurt.event_start)
        )
    ).all()
    return {
        f"{who}@{round((start - START).total_seconds())}": at is not None
        for kind, start, who, at in rows
        if kind in ("speaker", "interrupter")
    }


class TestTextIsComplete:
    NEXT = START + timedelta(minutes=2)

    def _entry(self, position: datetime | None, offset_ms: int | None = 2000) -> dict:
        return {
            "positie": position.isoformat() if position else None,
            "offset_ms": offset_ms,
        }

    def test_nothing_read_yet_is_not_complete(self):
        assert text_is_complete(self._entry(None), self.NEXT, self.NEXT) is False

    def test_a_turn_with_nothing_after_it_is_still_going_on(self):
        far = self._entry(self.NEXT + timedelta(hours=1))

        assert text_is_complete(far, None, None) is False

    def test_complete_once_read_past_the_next_message_the_offset_and_the_margin(self):
        edge = self.NEXT + OFFSET + MARGIN

        assert text_is_complete(self._entry(edge), self.NEXT, None) is True
        assert (
            text_is_complete(self._entry(edge - timedelta(seconds=1)), self.NEXT, None)
            is False
        )

    def test_the_margin_is_more_than_nothing(self):
        assert MARGIN >= timedelta(seconds=5)

    def test_no_offset_known_counts_as_none(self):
        edge = self.NEXT + MARGIN

        assert text_is_complete(self._entry(edge, None), self.NEXT, None) is True

    def test_past_the_end_of_the_part_is_complete_without_a_margin(self):
        end = self.NEXT
        just = self._entry(end + timedelta(seconds=1))

        assert text_is_complete(just, None, end) is True
        # The closing message is the next message; it does not make the
        # turn wait for a margin the reading never gets.
        assert text_is_complete(just, end, end) is True
        assert text_is_complete(self._entry(end), None, end) is False

    def test_an_end_that_is_not_reached_does_not_stand_in_the_way(self):
        end = self.NEXT + timedelta(hours=1)
        edge = self._entry(self.NEXT + OFFSET + MARGIN)

        assert text_is_complete(edge, self.NEXT, end) is True


class TestMomentUrl:
    def test_the_link_of_the_first_line(self):
        kop = "**Kamerlid A (X)** · [10:02](https://debat.example/a/b?event=speaker1)"

        assert moment_url_from_kop(kop) == "https://debat.example/a/b?event=speaker1"

    def test_of_an_interruption(self):
        kop = "↳ **Kamerlid A (X)** · [10:02](https://debat.example/x) · interruptie"

        assert moment_url_from_kop(kop) == "https://debat.example/x"

    def test_a_first_line_without_a_link(self):
        assert moment_url_from_kop("**Kamerlid A (X)** · 10:02") is None

    def test_only_a_link_that_is_safe_to_post(self):
        assert (
            moment_url_from_kop("**Kamerlid A (X)** · [10:02](http://x.example)")
            is None
        )

    def test_a_link_in_a_name_is_not_the_moment(self):
        kop = "**[10:02](https://elders.example/x)** · 10:02"

        assert moment_url_from_kop(kop) is None


@pytest.mark.asyncio
class TestAWholeDebate:
    async def test_a_question_becomes_a_thread_and_a_status_line(
        self, db_session, monkeypatch, handed
    ):
        debat = _debat(("speaker", 1, "a"), ("speaker", 3, "b"))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Outside(monkeypatch)
        Subtitles(monkeypatch, feed, [_cue(65, OPENING), _cue(70, Q_WANNEER)])
        mm, llm = Chat(), FakeLLM(antwoord(vraag(Q_WANNEER)))
        sessie = await _sessie(db_session)

        results = await _follow(db_session, mm, feed, llm, 6)

        row = (
            await db_session.execute(
                select(DebatSpreekbeurt).where(DebatSpreekbeurt.object_id == "a")
            )
        ).scalar_one()
        assert row.beoordeeld_at is not None
        # The thread hangs under the message of the turn.
        assert [root for root, _ in mm.threads] == [row.post_id]
        assert Q_WANNEER in mm.threads[0][1]
        # The message keeps who, when and what was said, and gets the line.
        message = mm.messages[row.post_id]
        assert message.startswith("**Kamerlid A (X)** · [")
        assert f"\n{OPENING} {Q_WANNEER}\n\n---\n{STATUS_EEN}" in message
        assert message.endswith(STATUS_EEN)
        # Read once, however many rounds follow.
        assert len(llm.prompts) == 1
        assert sum(r.beoordeeld for r in results) == 1
        assert sum(r.vragen for r in results) == 1
        assert sum(r.fouten for r in results) == 0

        beurt, context = handed[0]
        assert beurt.sessie_id == sessie.id
        assert beurt.spreekbeurt_id == row.id
        assert beurt.post_id == row.post_id
        assert beurt.channel_id == sessie.channel_id
        assert (beurt.soort, beurt.spreker, beurt.fractie) == (
            "speaker",
            "Kamerlid A (X)",
            "X",
        )
        assert beurt.start == row.event_start
        assert beurt.tekst == f"{OPENING} {Q_WANNEER}"
        assert beurt.is_bewindspersoon is False
        assert beurt.onderbroken is None
        # The link of the thread is the link of the message.
        assert beurt.moment_url is not None
        assert f"]({beurt.moment_url})" in message
        assert context.onderwerp == "Onderwerp volgens de Kamer"
        assert context.soort == "Commissiedebat"
        assert context.bewindspersonen[0].naam == "B. Bewindspersoon"

    async def test_a_turn_is_not_read_while_it_goes_on(
        self, db_session, monkeypatch, handed
    ):
        feed = Feed(monkeypatch, parts=[_stream(_debat(("speaker", 1, "a")))])
        Outside(monkeypatch)
        Subtitles(monkeypatch, feed, [_cue(65, OPENING), _cue(70, Q_WANNEER)])
        mm, llm = Chat(), FakeLLM()
        await _sessie(db_session)

        await _follow(db_session, mm, feed, llm, 8)

        assert Q_WANNEER in mm.channel[-1]
        assert handed == []
        assert await _judged(db_session) == {"a@60": False}

    async def test_a_turn_waits_for_the_words_that_come_in_late(
        self, db_session, monkeypatch, handed
    ):
        """The next speaker has a message after seven seconds; the last
        words of the one before arrive half a minute later."""
        debat = _debat(("speaker", 1, "a"), ("speaker", 2, "b"))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Outside(monkeypatch)
        Subtitles(monkeypatch, feed, [_cue(65, OPENING), _cue(117, Q_WANNEER)])
        mm, llm = Chat(), FakeLLM(antwoord(vraag(Q_WANNEER)))
        await _sessie(db_session)

        # 2:40. The message of b is there, the subtitles stand at 2:05.
        await _follow(db_session, mm, feed, llm, 2 + 40 / 60)
        assert len(mm.turns) == 2
        assert handed == []

        # Complete from 2:00 + offset + margin, which the subtitles reach
        # that long plus their own delay later.
        ready = 120 + (OFFSET + MARGIN + BEHIND).total_seconds()
        await _follow(db_session, mm, feed, llm, 4, start=2 + 50 / 60)

        assert [b.tekst for b, _ in handed] == [f"{OPENING} {Q_WANNEER}"]
        assert ready > 160
        assert len(mm.threads) == 1

    async def test_the_last_turn_is_read_when_the_debate_has_ended(
        self, db_session, monkeypatch, handed
    ):
        debat = _debat(("speaker", 1, "a"), ("debate_end", 2, ""))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Outside(monkeypatch)
        Subtitles(monkeypatch, feed, [_cue(65, OPENING), _cue(70, Q_WANNEER)])
        mm, llm = Chat(), FakeLLM(antwoord(vraag(Q_WANNEER)))
        await _sessie(db_session)

        await _follow(db_session, mm, feed, llm, 5)

        assert await _judged(db_session) == {"a@60": True}
        assert len(mm.threads) == 1

    async def test_who_is_interrupted_decides_whether_an_interruption_counts(
        self, db_session, monkeypatch, handed
    ):
        debat = _debat(
            ("speaker", 1, "m"),
            ("interrupter", 2, "a"),
            ("speaker", 3, "b"),
            ("interrupter", 4, "a"),
            ("interrupter", 5, "c"),
            ("debate_end", 6, ""),
        )
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Outside(monkeypatch)
        Subtitles(
            monkeypatch,
            feed,
            [
                _cue(65, "Dank voor de vragen, ik begin met het eerste blok."),
                _cue(125, "Kunt u toezeggen dat dit voor de zomer komt?"),
                _cue(185, "Voorzitter, ik heb drie punten voor vandaag."),
                _cue(245, "Bent u het daar dan mee eens, vraag ik u?"),
                _cue(305, "En wat vindt u daar dan zelf eigenlijk van?"),
            ],
        )
        mm, llm = Chat(), FakeLLM()
        await _sessie(db_session)

        await _follow(db_session, mm, feed, llm, 9)

        by_start = {round((b.start - START).total_seconds() / 60): b for b, _ in handed}
        assert sorted(by_start) == [1, 2, 3, 4, 5]
        assert by_start[1].is_bewindspersoon is True
        assert by_start[1].spreker == MINISTER
        assert by_start[1].fractie is None
        assert by_start[1].onderbroken is None
        assert by_start[2].soort == "interrupter"
        assert by_start[2].onderbroken == MINISTER
        assert by_start[2].onderbroken_is_bewindspersoon is True
        # A speaker is not interrupting anyone.
        assert by_start[3].onderbroken is None
        assert by_start[4].onderbroken == "Kamerlid B (Y)"
        assert by_start[4].onderbroken_is_bewindspersoon is False
        # Who has the floor, not who interrupted just before.
        assert by_start[5].onderbroken == "Kamerlid B (Y)"
        # The model read the interruption of the minister and the turn of
        # the member; not the minister, not members among themselves.
        assert len(llm.prompts) == 2
        assert all(await _judged_values(db_session))

    async def test_the_thread_hangs_under_the_first_message_of_a_long_turn(
        self, db_session, monkeypatch, handed
    ):
        debat = _debat(("speaker", 1, "a"), ("speaker", 6, "b"))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Outside(monkeypatch)
        zin = "Dit is een zin van precies zoveel woorden als nodig is. "
        cues = [_cue(62 + 3 * n, zin.strip()) for n in range(60)]
        cues.append(_cue(300, Q_WANNEER))
        Subtitles(monkeypatch, feed, cues)
        mm, llm = Chat(), FakeLLM(antwoord(vraag(Q_WANNEER)))
        await _sessie(db_session)

        await _follow(db_session, mm, feed, llm, 9)

        row = (
            await db_session.execute(
                select(DebatSpreekbeurt).where(DebatSpreekbeurt.object_id == "a")
            )
        ).scalar_one()
        assert len(row.vervolg_post_ids) >= 1
        assert [root for root, _ in mm.threads] == [row.post_id]
        # The line is at the end of the first message, and only there.
        assert mm.messages[row.post_id].endswith(f"\n\n---\n{STATUS_EEN}")
        for post_id in row.vervolg_post_ids:
            assert "---" not in mm.messages[post_id]
        # The question was said last, so it is in the last message.
        assert Q_WANNEER in mm.messages[row.vervolg_post_ids[-1]]
        assert handed[0][0].tekst.endswith(Q_WANNEER)


def _timed(debat: dd.DdDebat) -> dd.DdDebat:
    """The same debate, each event with its moment as the feed writes it."""
    return dataclasses.replace(
        debat,
        events=tuple(
            dataclasses.replace(event, raw_start=_feed_time(event.start))
            for event in debat.events
        ),
    )


def _feed_time(moment: datetime) -> str:
    return moment.astimezone(AMSTERDAM).strftime("%Y-%m-%dT%H:%M:%S%z")


@pytest.mark.asyncio
class TestTheMomentOfAQuestion:
    async def test_the_thread_links_to_the_question_not_to_the_start_of_the_turn(
        self, db_session, monkeypatch, handed
    ):
        debat = _timed(_debat(("speaker", 1, "a"), ("speaker", 4, "b")))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Outside(monkeypatch)
        # The opening at the start of the turn, the question minutes later.
        Subtitles(monkeypatch, feed, [_cue(65, OPENING), _cue(200, Q_WANNEER)])
        mm, llm = Chat(), FakeLLM(antwoord(vraag(Q_WANNEER)))
        await _sessie(db_session)

        await _follow(db_session, mm, feed, llm, 7)

        # The subtitles are on the clock of the sound, which the feed says
        # is two seconds later than the events. The link is on the clock
        # of the events, so the two seconds come off.
        asked = START + timedelta(seconds=200) - OFFSET
        beurt = handed[0][0]
        assert beurt.lines == (
            Line(START + timedelta(seconds=65) - OFFSET, OPENING),
            Line(asked, Q_WANNEER),
        )
        markering = (await db_session.execute(select(DebatMarkering))).scalar_one()
        assert markering.moment == START + timedelta(minutes=1)
        assert markering.vraag_moment == asked
        # Where the turn began, in the link of its message...
        begin = quote(f"speaker{_feed_time(markering.moment)}", safe="")
        assert beurt.moment_url == f"{dd.debate_url(debat)}?event={begin}"
        # ...and just before the question, in the link of the thread.
        hhmm = asked.astimezone(AMSTERDAM).strftime("%H:%M")
        at = quote(f"speaker{_feed_time(asked - LEAD_IN)}", safe="")
        assert mm.threads[0][1].split("\n")[1] == (
            f"Vraag 1 · aan de minister · [{hhmm}]({dd.debate_url(debat)}?event={at})"
        )

    async def test_the_lines_of_every_row_of_a_turn_in_the_order_of_its_text(
        self, db_session, monkeypatch, handed
    ):
        """The same speaker carrying on after a word of the chairman: two
        rows, one message, one text. What the chairman said is not in it."""
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM(antwoord(vraag(Q_WANNEER)))
        s = await _running(db_session)
        a = await _row(db_session, s, "speaker", 60, "a", tekst=OPENING)
        v = await _row(
            db_session, s, "chairman", 80, "v", tekst="Gaat u verder.", post=False
        )
        more = await _row(
            db_session, s, "speaker", 85, "a", tekst=Q_WANNEER, post=False
        )
        await _row(db_session, s, "debate_end", 180)
        _in_channel(mm, a)
        # Not kept in the order they were said.
        await _ondertitel(
            db_session, s, more, 91, "het wetsvoorstel naar de Kamer komt?"
        )
        await _ondertitel(db_session, s, a, 64, "voor het woord.")
        await _ondertitel(db_session, s, v, 82, "Gaat u verder.")
        await _ondertitel(db_session, s, more, 88, "Kan de minister zeggen wanneer")
        await _ondertitel(db_session, s, a, 62, "Voorzitter, dank u wel")

        await _tick(db_session, mm, llm)

        beurt = handed[0][0]
        assert beurt.tekst == f"{OPENING} {Q_WANNEER}"
        # Two seconds off each: `offset_ms` of this part.
        assert beurt.lines == (
            Line(START + timedelta(seconds=60), "Voorzitter, dank u wel"),
            Line(START + timedelta(seconds=62), "voor het woord."),
            Line(START + timedelta(seconds=86), "Kan de minister zeggen wanneer"),
            Line(START + timedelta(seconds=89), "het wetsvoorstel naar de Kamer komt?"),
        )
        markering = (await db_session.execute(select(DebatMarkering))).scalar_one()
        assert markering.vraag_moment == START + timedelta(seconds=86)

    async def test_a_turn_whose_text_has_no_lines_keeps_the_start_of_the_turn(
        self, db_session, monkeypatch, handed
    ):
        """A row from before lines were kept has text and nothing under it."""
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM(antwoord(vraag(Q_WANNEER)))
        s = await _running(db_session)
        a = await _row(
            db_session, s, "speaker", 60, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        await _row(db_session, s, "debate_end", 180)
        _in_channel(mm, a)

        await _tick(db_session, mm, llm)

        assert handed[0][0].lines == ()
        markering = (await db_session.execute(select(DebatMarkering))).scalar_one()
        assert markering.vraag_moment is None
        assert (
            mm.threads[0][1]
            .split("\n")[1]
            .endswith(
                "(https://debat.example/d?event=speaker1) (begin van de spreekbeurt)"
            )
        )

    async def test_the_lines_of_another_turn_are_not_this_ones(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        s = await _running(db_session)
        a = await _row(db_session, s, "speaker", 60, "a", tekst=OPENING)
        b = await _row(db_session, s, "speaker", 120, "b", tekst=Q_WANNEER)
        await _row(db_session, s, "debate_end", 180)
        _in_channel(mm, a, b)
        await _ondertitel(db_session, s, a, 62, OPENING)
        await _ondertitel(db_session, s, b, 122, Q_WANNEER)

        await _tick(db_session, mm, llm)

        assert [beurt.lines for beurt, _ in handed] == [
            (Line(START + timedelta(seconds=60), OPENING),),
            (Line(START + timedelta(seconds=120), Q_WANNEER),),
        ]


async def _judged_values(db_session) -> list[bool]:
    return list((await _judged(db_session)).values())


# --- rows written by hand ------------------------------------------------

PART = "deel-1"
KOP = "**Kamerlid A (X)** · [10:01](https://debat.example/d?event=speaker1)"


async def _running(db_session, *, read_until: float | None = 600, **overrides):
    """A debate the timeline is following, subtitles read up to a second."""
    entry: dict = {"url": "https://stream.example/sub.m3u8", "offset_ms": 2000}
    if read_until is not None:
        entry["positie"] = (START + timedelta(seconds=read_until)).isoformat()
    values = {
        "tijdlijn_status": TIJDLIJN_LOOPT,
        "debat_direct_ids": [PART],
        "ondertitels": {PART: entry},
    }
    values.update(overrides)
    return await _sessie(db_session, **values)


async def _row(
    db_session,
    sessie,
    kind: str,
    seconds: float,
    who: str = "",
    *,
    tekst: str | None = None,
    post: bool = True,
    part: str = PART,
    kop: str | None = None,
) -> DebatSpreekbeurt:
    speaking = kind in ("speaker", "interrupter")
    row = DebatSpreekbeurt(
        sessie_id=sessie.id,
        debat_direct_id=part,
        event_type=kind,
        event_start=START + timedelta(seconds=seconds),
        object_id=who,
        post_id=f"post{uuid.uuid4().hex}"[:26] if post else None,
        kop=kop or (KOP if post and speaking else None),
        tekst=tekst,
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _ondertitel(db_session, sessie, row, seconds: float, tekst: str) -> None:
    db_session.add(
        DebatOndertitel(
            sessie_id=sessie.id,
            debat_direct_id=row.debat_direct_id,
            start=START + timedelta(seconds=seconds),
            einde=START + timedelta(seconds=seconds + 2),
            tekst=tekst,
            spreekbeurt_id=row.id,
        )
    )
    await db_session.flush()


async def _nothing() -> None:
    """In place of a rollback: the test session rolls back the whole test."""


async def _tick(db_session, mm, llm, now_seconds: float = 700, contexts=None):
    return await DebatVraagWorker(db_session, mm, llm, contexts).tick(
        (START + timedelta(seconds=now_seconds)).astimezone(UTC)
    )


async def _at(db_session, row) -> datetime | None:
    return await db_session.scalar(
        select(DebatSpreekbeurt.beoordeeld_at).where(DebatSpreekbeurt.id == row.id)
    )


def _in_channel(mm: Chat, *rows: DebatSpreekbeurt) -> None:
    for row in rows:
        mm.messages[row.post_id] = render(row.kop, row.tekst or "")


@pytest.mark.asyncio
class TestWhichTurns:
    async def _two(self, db_session, mm, **sessie):
        s = await _running(db_session, **sessie)
        a = await _row(
            db_session, s, "speaker", 60, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        b = await _row(
            db_session, s, "speaker", 120, "b", tekst=f"{OPENING} {Q_BUDGET}"
        )
        end = await _row(db_session, s, "debate_end", 180)
        _in_channel(mm, a, b)
        return s, a, b, end

    async def test_finished_turns_are_read_in_the_order_they_were_spoken(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm = Chat()
        llm = FakeLLM(antwoord(vraag(Q_WANNEER)), antwoord(vraag(Q_BUDGET)))
        _, a, b, _ = await self._two(db_session, mm)

        result = await _tick(db_session, mm, llm)

        assert [beurt.spreekbeurt_id for beurt, _ in handed] == [a.id, b.id]
        assert [root for root, _ in mm.threads] == [a.post_id, b.post_id]
        assert (result.sessies, result.beoordeeld, result.vragen, result.fouten) == (
            1,
            2,
            2,
            0,
        )
        when = (START + timedelta(seconds=700)).astimezone(UTC)
        assert await _at(db_session, a) == when
        assert await _at(db_session, b) == when
        assert (
            "2 spreekbeurten gelezen, 2 vragen, 0 moties, 0 toezeggingen, 0 fouten"
            in result.summary()
        )

    async def test_a_turn_that_was_read_is_not_read_again(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        await self._two(db_session, mm)

        await _tick(db_session, mm, llm)
        again = await _tick(db_session, mm, llm, 715)

        assert len(handed) == 2
        assert again.beoordeeld == 0

    async def test_a_turn_without_text_is_done_without_asking_the_model(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        s = await _running(db_session)
        a = await _row(db_session, s, "speaker", 60, "a")
        b = await _row(
            db_session, s, "speaker", 120, "b", tekst=f"{OPENING} {Q_BUDGET}"
        )
        await _row(db_session, s, "debate_end", 180)
        _in_channel(mm, a, b)

        result = await _tick(db_session, mm, llm)

        assert await _at(db_session, a) is not None
        assert [beurt.spreekbeurt_id for beurt, _ in handed] == [b.id]
        # Only what was read counts as read.
        assert result.beoordeeld == 1

    async def test_a_model_that_is_away_stops_the_round_and_is_asked_again(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm = Chat()
        llm = FakeLLM(
            ConnectionError("geen verbinding"),
            antwoord(vraag(Q_WANNEER)),
            antwoord(vraag(Q_BUDGET)),
        )
        _, a, b, _ = await self._two(db_session, mm)

        result = await _tick(db_session, mm, llm)

        # Not the second turn as well: it would wait for the same model.
        assert len(llm.prompts) == 1
        assert (result.beoordeeld, result.fouten) == (0, 1)
        assert await _at(db_session, a) is None
        assert await _at(db_session, b) is None

        # Not at once: the debate is left alone for half a minute.
        result = await _tick(db_session, mm, llm, 715)
        assert (len(llm.prompts), result.beoordeeld) == (1, 0)

        result = await _tick(db_session, mm, llm, 731)

        assert (result.beoordeeld, result.vragen, result.fouten) == (2, 2, 0)
        assert [root for root, _ in mm.threads] == [a.post_id, b.post_id]

    async def test_the_wait_doubles_while_the_model_stays_away(
        self, db_session, monkeypatch
    ):
        Outside(monkeypatch)
        mm = Chat()
        llm = FakeLLM(*[ConnectionError("geen verbinding")] * 10)
        await self._two(db_session, mm)

        asked = []
        for seconds in range(700, 1000, 10):
            await _tick(db_session, mm, llm, seconds)
            asked.append(len(llm.prompts))

        # At 700, then after 30 s, then after 60 more, then after 120 more.
        assert [asked.index(n) * 10 for n in (1, 2, 3, 4)] == [0, 30, 90, 210]

    async def test_after_a_turn_that_went_well_the_wait_starts_short_again(self):
        now = START.astimezone(UTC)
        pause = mod._Pause()
        sessie_id = uuid.uuid4()
        pause.failed(sessie_id, now)
        pause.failed(sessie_id, now)
        assert pause.waiting(sessie_id, now + timedelta(seconds=45))

        pause.succeeded(sessie_id)
        assert not pause.waiting(sessie_id, now)
        pause.failed(sessie_id, now)

        assert pause.waiting(sessie_id, now + timedelta(seconds=29))
        assert not pause.waiting(sessie_id, now + timedelta(seconds=31))

    async def test_a_turn_that_keeps_failing_is_given_up_on(
        self, db_session, monkeypatch
    ):
        """Something the model cannot take, a filter or a text too long,
        fails every time. The turns after it must not wait for ever."""
        Outside(monkeypatch)
        mm = Chat()
        llm = FakeLLM(
            *[ConnectionError("geweigerd")] * mod.MAX_ATTEMPTS,
            antwoord(vraag(Q_BUDGET)),
        )
        _, a, b, _ = await self._two(db_session, mm)

        seconds = 700
        for _ in range(mod.MAX_ATTEMPTS):
            mod._pause.reset()
            await _tick(db_session, mm, llm, seconds)
            seconds += 10
        assert await _at(db_session, a) is not None
        assert await _at(db_session, b) is None

        mod._pause.reset()
        result = await _tick(db_session, mm, llm, seconds)

        assert result.beoordeeld == 1
        assert [root for root, _ in mm.threads] == [b.post_id]

    async def test_something_breaking_after_the_answer_counts_as_an_attempt(
        self, db_session, monkeypatch
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        _, a, _, _ = await self._two(db_session, mm)

        async def broken(self, beurt, context):
            raise RuntimeError("stuk")

        monkeypatch.setattr(DebatVraagService, "beoordeel_beurt", broken)
        monkeypatch.setattr(db_session, "rollback", _nothing)
        result = await _tick(db_session, mm, llm)

        assert result.fouten == 1
        attempts = await db_session.scalar(
            select(DebatSpreekbeurt.beoordeel_pogingen).where(
                DebatSpreekbeurt.id == a.id
            )
        )
        assert attempts == 1

    async def test_a_model_that_hangs_is_not_waited_for(self, db_session, monkeypatch):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        _, a, _, _ = await self._two(db_session, mm)
        monkeypatch.setattr(mod, "JUDGE_TIMEOUT", 0.05)
        monkeypatch.setattr(db_session, "rollback", _nothing)

        async def hangs(self, beurt, context):
            await asyncio.sleep(5)

        monkeypatch.setattr(DebatVraagService, "beoordeel_beurt", hangs)
        began = time.monotonic()
        result = await _tick(db_session, mm, llm)

        assert time.monotonic() - began < 2
        assert result.fouten == 1
        assert await _at(db_session, a) is None

    async def test_an_answer_that_cannot_be_read_is_not_asked_for_again(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm = Chat()
        llm = FakeLLM("geen json", "nog steeds niet", antwoord(vraag(Q_BUDGET)))
        _, a, b, _ = await self._two(db_session, mm)

        result = await _tick(db_session, mm, llm)

        assert await _at(db_session, a) is not None
        assert (result.beoordeeld, result.vragen, result.fouten) == (2, 1, 0)
        assert [root for root, _ in mm.threads] == [b.post_id]

    async def test_a_backlog_is_caught_up_a_few_turns_per_round(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        monkeypatch.setattr(mod, "MAX_TURNS", 1)
        mm, llm = Chat(), FakeLLM()
        _, a, b, _ = await self._two(db_session, mm)

        await _tick(db_session, mm, llm)
        assert [beurt.spreekbeurt_id for beurt, _ in handed] == [a.id]

        await _tick(db_session, mm, llm, 715)
        assert [beurt.spreekbeurt_id for beurt, _ in handed] == [a.id, b.id]

    async def test_the_turns_of_one_message_are_read_as_one(
        self, db_session, monkeypatch, handed
    ):
        """The same speaker carrying on after a word of the chairman has no
        message of their own; their text is in the message before."""
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        s = await _running(db_session)
        a = await _row(db_session, s, "speaker", 60, "a", tekst=OPENING)
        await _row(
            db_session, s, "chairman", 80, "v", tekst="Gaat u verder.", post=False
        )
        more = await _row(
            db_session, s, "speaker", 85, "a", tekst=Q_WANNEER, post=False
        )
        await _row(db_session, s, "debate_end", 180)
        _in_channel(mm, a)

        await _tick(db_session, mm, llm)

        assert [(b.spreekbeurt_id, b.tekst) for b, _ in handed] == [
            (a.id, f"{OPENING} {Q_WANNEER}")
        ]
        assert await _at(db_session, more) is None

    async def test_only_a_message_ends_a_turn(self, db_session, monkeypatch, handed):
        """An event without a message after it says nothing: the chairman
        said a word and the speaker carries on."""
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        s = await _running(db_session)
        a = await _row(db_session, s, "speaker", 60, "a", tekst=OPENING)
        await _row(db_session, s, "chairman", 80, "v", post=False)
        _in_channel(mm, a)

        await _tick(db_session, mm, llm)

        assert handed == []

    async def test_a_message_that_is_not_a_turn_ends_one_too(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        s = await _running(db_session)
        a = await _row(
            db_session, s, "speaker", 60, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        await _row(db_session, s, "suspended", 120)
        _in_channel(mm, a)

        await _tick(db_session, mm, llm)

        assert [beurt.spreekbeurt_id for beurt, _ in handed] == [a.id]

    async def test_a_suspension_with_the_words_of_the_chairman_is_nobodys_turn(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        s = await _running(db_session)
        a = await _row(
            db_session, s, "speaker", 60, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        await _row(
            db_session,
            s,
            "chairman",
            100,
            "v",
            tekst="Ik schors de vergadering, kan de minister om twee uur terug zijn?",
            post=False,
        )
        pause = await _row(
            db_session, s, "suspended", 110, kop="⏸️ **Geschorst** · 10:01"
        )
        b = await _row(
            db_session, s, "speaker", 200, "b", tekst=f"{OPENING} {Q_BUDGET}"
        )
        await _row(db_session, s, "debate_end", 300)
        _in_channel(mm, a, b)
        closing = [t for t in await load_turns(db_session, s.id, PART) if t.closing]
        assert [t.row_id for t in closing] == [pause.id]

        await _tick(db_session, mm, llm)

        assert [beurt.spreekbeurt_id for beurt, _ in handed] == [a.id, b.id]
        assert await _at(db_session, pause) is None

    async def test_a_message_of_the_chair_is_nobodys_turn(
        self, db_session, monkeypatch, handed
    ):
        """The chair has messages of its own, with his words under them.
        Questions are asked by members, so they are not read for any, and
        the turn before the chair stays the one an answer is to."""
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        s = await _running(db_session)
        a = await _row(
            db_session, s, "speaker", 60, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        chair = await _row(
            db_session,
            s,
            "chairman",
            100,
            "v",
            tekst=f"Dank u wel. {Q_BUDGET}",
            kop="🔨 **Voorzitter** · 10:01",
        )
        b = await _row(
            db_session, s, "speaker", 200, "b", tekst=f"{OPENING} {Q_BUDGET}"
        )
        await _row(db_session, s, "debate_end", 300)
        _in_channel(mm, a, chair, b)
        chairs = [t for t in await load_turns(db_session, s.id, PART) if t.chair]
        assert [t.row_id for t in chairs] == [chair.id]

        await _tick(db_session, mm, llm)

        assert [beurt.spreekbeurt_id for beurt, _ in handed] == [a.id, b.id]
        assert await _at(db_session, chair) is None

    async def test_the_subtitles_have_to_be_past_the_next_message(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        # 120 for the next message, 2 of offset, and one short of the margin.
        short = 120 + 2 + MARGIN.total_seconds() - 1
        s = await _running(db_session, read_until=short)
        a = await _row(
            db_session, s, "speaker", 60, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        b = await _row(db_session, s, "speaker", 120, "b", tekst=OPENING)
        _in_channel(mm, a, b)

        await _tick(db_session, mm, llm)
        assert handed == []

        entry = {**s.ondertitels[PART]}
        entry["positie"] = (START + timedelta(seconds=short + 1)).isoformat()
        await db_session.execute(
            update(DebatSessie)
            .where(DebatSessie.id == s.id)
            .values(ondertitels={PART: entry})
        )
        await _tick(db_session, mm, llm)

        # And b itself is still speaking.
        assert [beurt.spreekbeurt_id for beurt, _ in handed] == [a.id]

    async def test_a_debate_without_subtitles_is_left_alone(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        _, a, _, _ = await self._two(db_session, mm, read_until=None)

        await _tick(db_session, mm, llm)

        assert handed == []
        assert await _at(db_session, a) is None

    async def test_the_first_message_of_a_next_part_ends_the_last_turn_of_a_part(
        self, db_session, monkeypatch, handed
    ):
        """A part without an end of its own: the feed did not say so."""
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        s = await _running(db_session, debat_direct_ids=[PART, "deel-2"])
        a = await _row(
            db_session, s, "speaker", 60, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        b = await _row(db_session, s, "speaker", 300, "b", tekst=OPENING, part="deel-2")
        _in_channel(mm, a, b)

        await _tick(db_session, mm, llm)

        # By the subtitles of its own part, which were read to 600.
        assert [beurt.spreekbeurt_id for beurt, _ in handed] == [a.id]

    async def test_each_part_goes_by_its_own_subtitles(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        at = (START + timedelta(seconds=600)).isoformat()
        s = await _running(
            db_session,
            debat_direct_ids=[PART, "deel-2"],
            ondertitels={
                PART: {"url": "u", "offset_ms": 0, "positie": at},
                "deel-2": {"url": "u", "offset_ms": 0},
            },
        )
        a = await _row(
            db_session, s, "speaker", 60, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        await _row(db_session, s, "debate_end", 120)
        b = await _row(db_session, s, "speaker", 300, "b", tekst=OPENING, part="deel-2")
        await _row(db_session, s, "debate_end", 400, part="deel-2")
        _in_channel(mm, a, b)

        await _tick(db_session, mm, llm)

        assert [beurt.spreekbeurt_id for beurt, _ in handed] == [a.id]

    async def test_the_end_of_another_part_is_not_the_end_of_this_one(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        s = await _running(db_session, debat_direct_ids=[PART, "deel-2"])
        await _row(db_session, s, "debate_end", 30, part="deel-2")
        a = await _row(
            db_session, s, "speaker", 60, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        _in_channel(mm, a)

        await _tick(db_session, mm, llm)

        assert handed == []

    async def test_a_message_in_another_debate_ends_nothing_here(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        s = await _running(db_session)
        a = await _row(
            db_session, s, "speaker", 60, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        other = await _running(db_session)
        b = await _row(db_session, other, "speaker", 120, "b", tekst=OPENING)
        _in_channel(mm, a, b)

        result = await _tick(db_session, mm, llm)

        assert (result.sessies, handed) == (2, [])

    async def test_an_end_the_channel_was_not_told_of_ends_the_part_as_well(
        self, db_session, monkeypatch, handed
    ):
        """The end fell in a stretch the timeline missed: it is remembered
        without a message."""
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        s = await _running(db_session)
        a = await _row(
            db_session, s, "speaker", 60, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        await _row(db_session, s, "debate_end", 180, post=False)
        _in_channel(mm, a)

        await _tick(db_session, mm, llm)

        assert [beurt.spreekbeurt_id for beurt, _ in handed] == [a.id]

    async def test_an_end_without_a_message_is_not_the_next_message(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        s = await _running(
            db_session, debat_direct_ids=[PART, "deel-2"], read_until=150
        )
        a = await _row(
            db_session, s, "speaker", 60, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        await _row(db_session, s, "debate_end", 100, part="deel-2", post=False)
        b = await _row(db_session, s, "speaker", 200, "b", tekst=OPENING)
        _in_channel(mm, a, b)

        await _tick(db_session, mm, llm)

        # Read to 150, and the message after a is at 200.
        assert handed == []

    async def test_across_parts_the_order_is_still_that_of_the_debate(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        s = await _running(db_session, debat_direct_ids=["deel-2", PART])
        entry = s.ondertitels[PART]
        await db_session.execute(
            update(DebatSessie)
            .where(DebatSessie.id == s.id)
            .values(ondertitels={PART: entry, "deel-2": entry})
        )
        a = await _row(
            db_session, s, "speaker", 60, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        await _row(db_session, s, "debate_end", 120)
        b = await _row(db_session, s, "speaker", 300, "b", tekst=OPENING, part="deel-2")
        await _row(db_session, s, "debate_end", 400, part="deel-2")
        _in_channel(mm, a, b)

        await _tick(db_session, mm, llm)

        assert [beurt.spreekbeurt_id for beurt, _ in handed] == [a.id, b.id]

    async def test_an_interruption_in_another_part_has_nobody_from_the_part_before(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        s = await _running(db_session, debat_direct_ids=[PART, "deel-2"])
        m = await _row(db_session, s, "speaker", 60, "m", tekst=OPENING)
        await _row(db_session, s, "debate_end", 120)
        i = await _row(
            db_session, s, "interrupter", 300, "a", tekst=Q_WANNEER, part="deel-2"
        )
        await _row(db_session, s, "debate_end", 400, part="deel-2")
        entry = s.ondertitels[PART]
        await db_session.execute(
            update(DebatSessie)
            .where(DebatSessie.id == s.id)
            .values(ondertitels={PART: entry, "deel-2": entry})
        )
        _in_channel(mm, m, i)

        await _tick(db_session, mm, llm)

        assert [b.onderbroken for b, _ in handed] == [None, None]


@pytest.mark.asyncio
class TestWhichDebates:
    async def _one(self, db_session, mm, **sessie):
        s = await _running(db_session, **sessie)
        a = await _row(
            db_session, s, "speaker", 60, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        await _row(db_session, s, "debate_end", 180)
        _in_channel(mm, a)
        return s, a

    @pytest.mark.parametrize("status", [None, TIJDLIJN_GEKOPPELD, TIJDLIJN_AFGELOPEN])
    async def test_only_a_debate_the_timeline_is_following(
        self, db_session, monkeypatch, handed, status
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        await self._one(db_session, mm, tijdlijn_status=status)

        result = await _tick(db_session, mm, llm)

        assert handed == []
        assert result.sessies == 0

    async def test_within_the_same_days_as_the_timeline(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        aanvang = START.replace(second=0)
        await self._one(db_session, mm)
        old = (aanvang + GIVE_UP_AFTER + END_GRACE - START).total_seconds()
        ahead = (aanvang - LOOKAHEAD - START).total_seconds()

        assert (await _tick(db_session, mm, llm, old + 1)).sessies == 0
        assert (await _tick(db_session, mm, llm, ahead - 1)).sessies == 0
        assert handed == []
        assert (await _tick(db_session, mm, llm, old)).sessies == 1
        assert len(handed) == 1
        assert (await _tick(db_session, mm, llm, ahead)).sessies == 1

    async def test_a_debate_without_a_channel_or_a_start_is_skipped(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        await self._one(db_session, mm, channel_id=None)
        await self._one(db_session, mm, aanvang=None)

        assert (await _tick(db_session, mm, llm)).sessies == 0

    async def test_no_mattermost_no_work(self, db_session, monkeypatch, handed):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        mm.enabled = False
        await self._one(db_session, mm)

        result = await _tick(db_session, mm, llm)

        assert (result.sessies, handed) == (0, [])

    async def test_no_model_is_said_and_nothing_is_marked_as_read(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm = Chat()
        _, a = await self._one(db_session, mm)

        async def none(cls, session, mattermost=None):
            return None

        monkeypatch.setattr(DebatVraagService, "create", classmethod(none))
        result = await _tick(db_session, mm, None)

        assert result.model is False
        assert result.summary() == "geen taalmodel ingesteld"
        assert await _at(db_session, a) is None

    async def test_the_configured_model_is_used_when_none_is_handed_in(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM(antwoord(vraag(Q_WANNEER)))
        _, a = await self._one(db_session, mm)

        async def configured(cls, session, mattermost=None):
            return cls(session, mattermost, llm)

        monkeypatch.setattr(DebatVraagService, "create", classmethod(configured))
        result = await _tick(db_session, mm, None)

        assert (result.model, result.vragen) == (True, 1)
        assert [root for root, _ in mm.threads] == [a.post_id]

    async def test_no_model_is_looked_for_when_nothing_waits(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm = Chat()
        s = await _running(db_session)
        a = await _row(db_session, s, "speaker", 60, "a", tekst=OPENING)
        _in_channel(mm, a)

        async def boom(cls, session, mattermost=None):
            raise AssertionError("not needed")

        monkeypatch.setattr(DebatVraagService, "create", classmethod(boom))
        result = await _tick(db_session, mm, None)

        assert (result.sessies, result.fouten, result.model) == (1, 0, True)

    async def test_one_debate_that_breaks_does_not_stop_the_other(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        _, a = await self._one(db_session, mm)
        _, b = await self._one(db_session, mm)
        # The session of a test is one transaction: a real rollback would
        # take these rows with it.
        rolled_back = []

        async def rollback():
            rolled_back.append(True)

        monkeypatch.setattr(db_session, "rollback", rollback)
        original = DebatVraagWorker._read
        calls = []

        async def flaky(self, sessie_id, *args):
            calls.append(sessie_id)
            if len(calls) == 1:
                raise RuntimeError("stuk")
            return await original(self, sessie_id, *args)

        monkeypatch.setattr(DebatVraagWorker, "_read", flaky)
        result = await _tick(db_session, mm, llm)

        assert (result.sessies, result.fouten, result.beoordeeld) == (2, 1, 1)
        assert len(handed) == 1
        assert rolled_back == [True]


@pytest.mark.asyncio
class TestWhatIsKnownOfTheDebate:
    async def _one(self, db_session, mm, who="a", kind="speaker"):
        s = await _running(db_session)
        a = await _row(db_session, s, kind, 60, who, tekst=f"{OPENING} {Q_WANNEER}")
        await _row(db_session, s, "debate_end", 180)
        _in_channel(mm, a)
        return s, a

    async def test_the_tk_api_is_asked_once_per_debate(
        self, db_session, monkeypatch, handed
    ):
        outside = Outside(monkeypatch)
        mm, llm, contexts = Chat(), FakeLLM(), {}
        s = await _running(db_session)
        a = await _row(
            db_session, s, "speaker", 60, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        b = await _row(
            db_session, s, "speaker", 120, "b", tekst=f"{OPENING} {Q_BUDGET}"
        )
        _in_channel(mm, a, b)

        await _tick(db_session, mm, llm, contexts=contexts)
        await _row(db_session, s, "debate_end", 180)
        await _tick(db_session, mm, llm, 715, contexts=contexts)

        assert len(handed) == 2
        assert outside.activiteit_calls == 1
        assert list(contexts) == [s.id]
        assert handed[1][1] is handed[0][1]

    async def test_without_the_tk_api_the_subject_is_enough_and_it_is_asked_again(
        self, db_session, monkeypatch, handed
    ):
        outside = Outside(monkeypatch)
        outside.activiteit_error = True
        mm, llm, contexts = Chat(), FakeLLM(antwoord(vraag(Q_WANNEER))), {}
        s = await _running(db_session)
        a = await _row(
            db_session, s, "speaker", 60, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        b = await _row(
            db_session, s, "speaker", 120, "b", tekst=f"{OPENING} {Q_BUDGET}"
        )
        await _row(db_session, s, "debate_end", 180)
        _in_channel(mm, a, b)

        result = await _tick(db_session, mm, llm, contexts=contexts)

        assert (result.beoordeeld, result.fouten) == (2, 0)
        assert handed[0][1].onderwerp == FULL.name
        assert handed[0][1].bewindspersonen == ()
        assert contexts == {}
        assert outside.activiteit_calls == 2
        assert len(mm.threads) == 1

    async def test_an_activiteit_that_is_gone_is_the_same(
        self, db_session, monkeypatch, handed
    ):
        outside = Outside(monkeypatch)
        outside.activiteit_gone = True
        mm, llm, contexts = Chat(), FakeLLM(), {}
        await self._one(db_session, mm)

        await _tick(db_session, mm, llm, contexts=contexts)

        assert handed[0][1].onderwerp == FULL.name
        assert contexts == {}

    async def test_the_speakers_are_asked_once_per_round(
        self, db_session, monkeypatch, handed
    ):
        outside = Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        s = await _running(db_session)
        a = await _row(
            db_session, s, "speaker", 60, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        b = await _row(
            db_session, s, "speaker", 120, "b", tekst=f"{OPENING} {Q_BUDGET}"
        )
        await _row(db_session, s, "debate_end", 180)
        _in_channel(mm, a, b)

        await _tick(db_session, mm, llm)

        assert len(handed) == 2
        assert outside.sprekers_calls == 1

    async def test_without_the_speakers_nothing_is_read_until_they_are_back(
        self, db_session, monkeypatch, handed
    ):
        """Who is a minister comes from that list, and the answers of a
        minister are not questions."""
        outside = Outside(monkeypatch)
        outside.sprekers_error = True
        mm, llm = Chat(), FakeLLM()
        _, a = await self._one(db_session, mm, who="m")

        result = await _tick(db_session, mm, llm)

        assert (handed, result.fouten, result.beoordeeld) == ([], 1, 0)
        assert await _at(db_session, a) is None

        outside.sprekers_error = False
        result = await _tick(db_session, mm, llm, 715)

        assert handed[0][0].is_bewindspersoon is True
        assert llm.prompts == []
        assert (result.fouten, result.beoordeeld) == (0, 1)

    async def test_someone_who_is_not_on_the_list_is_not_read(
        self, db_session, monkeypatch, handed
    ):
        """Whether an unknown speaker asks or answers cannot be told, and
        the answers of a minister are not questions."""
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM(antwoord(vraag(Q_WANNEER)))
        _, a = await self._one(db_session, mm, who="zz")

        await _tick(db_session, mm, llm)

        assert handed == []
        assert llm.prompts == []
        assert await _at(db_session, a) is not None

    async def test_an_interruption_with_nobody_before_it(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        mm, llm = Chat(), FakeLLM()
        await self._one(db_session, mm, kind="interrupter")

        await _tick(db_session, mm, llm)

        beurt = handed[0][0]
        assert (beurt.onderbroken, beurt.onderbroken_is_bewindspersoon) == (None, False)

    async def test_the_list_of_the_day_the_part_began(
        self, db_session, monkeypatch, handed
    ):
        Outside(monkeypatch)
        days = []

        async def sprekers(client, day, base_url=None):
            days.append(day)
            return SPREKERS

        monkeypatch.setattr(dd, "fetch_sprekers", sprekers)
        mm, llm = Chat(), FakeLLM()
        # Past midnight in Amsterdam: still the people of the day before.
        late = (
            START.astimezone(mod.AMSTERDAM).replace(hour=23, minute=59, second=0)
            - START
        ).total_seconds()
        s = await _running(db_session, read_until=late + 600)
        a = await _row(
            db_session, s, "speaker", late, "a", tekst=f"{OPENING} {Q_WANNEER}"
        )
        b = await _row(
            db_session, s, "speaker", late + 120, "b", tekst=f"{OPENING} {Q_BUDGET}"
        )
        await _row(db_session, s, "debate_end", late + 300)
        _in_channel(mm, a, b)

        await _tick(db_session, mm, llm, late + 700)

        assert len(handed) == 2
        assert days == [START.astimezone(mod.AMSTERDAM).date()]


# --- one message, two writers ---------------------------------------------


async def _marked(db_session, sessie, row, volgnummer: int = 1) -> None:
    """A question of this turn that has its thread."""
    db_session.add(
        DebatMarkering(
            sessie_id=sessie.id,
            spreekbeurt_id=row.id,
            beurt_sleutel=f"beurt:{row.id}:{volgnummer}",
            volgnummer=volgnummer,
            soort=SOORT_VRAAG,
            status=STATUS_OPEN,
            channel_id=sessie.channel_id,
            beurt_post_id=row.post_id,
            thread_post_id=f"reply{uuid.uuid4().hex}"[:26],
            spreker="Kamerlid A (X)",
            gericht_aan="de minister",
            citaat=Q_WANNEER,
            samenvatting="",
            moment=row.event_start,
        )
    )
    await db_session.flush()


async def _say(db_session, row, more: str) -> None:
    tekst = await db_session.scalar(
        select(DebatSpreekbeurt.tekst).where(DebatSpreekbeurt.id == row.id)
    )
    await db_session.execute(
        update(DebatSpreekbeurt)
        .where(DebatSpreekbeurt.id == row.id)
        .values(tekst=f"{tekst or ''} {more}".strip())
    )


async def _transcribe(db_session, mm, sessie) -> None:
    await DebatTranscript(db_session, mm).write(
        sessie.id, sessie.channel_id, PART, TickResult()
    )


async def _status(db_session, mm, sessie) -> None:
    """What is counted under a message changed. The marking leaves the
    message alone and the transcription writes it, in the next round of
    the timeline."""
    await DebatVraagService(db_session, mm, FakeLLM())._werk_statusregels_bij(sessie.id)
    await DebatTranscript(db_session, mm).write_counts(TickResult())


@pytest.mark.asyncio
class TestOneMessageTwoWriters:
    async def _turn(self, db_session, mm, tekst=OPENING):
        s = await _running(db_session)
        a = await _row(db_session, s, "speaker", 60, "a")
        mm.messages[a.post_id] = KOP
        mm.order.append(a.post_id)
        await _say(db_session, a, tekst)
        return s, a

    async def test_text_written_after_the_status_line_keeps_the_line(self, db_session):
        mm = Chat()
        s, a = await self._turn(db_session, mm)
        await _transcribe(db_session, mm, s)
        await _marked(db_session, s, a)
        await _status(db_session, mm, s)
        assert mm.messages[a.post_id] == f"{KOP}\n{OPENING}\n\n---\n{STATUS_EEN}"

        await _say(db_session, a, Q_WANNEER)
        await _transcribe(db_session, mm, s)

        assert mm.messages[a.post_id] == (
            f"{KOP}\n{OPENING} {Q_WANNEER}\n\n---\n{STATUS_EEN}"
        )

    async def test_a_status_line_written_after_the_text_keeps_the_text(
        self, db_session
    ):
        mm = Chat()
        s, a = await self._turn(db_session, mm)
        await _transcribe(db_session, mm, s)
        await _say(db_session, a, Q_WANNEER)
        await _transcribe(db_session, mm, s)
        await _marked(db_session, s, a)

        await _status(db_session, mm, s)

        assert mm.messages[a.post_id] == (
            f"{KOP}\n{OPENING} {Q_WANNEER}\n\n---\n{STATUS_EEN}"
        )

    async def test_back_and_forth(self, db_session):
        mm = Chat()
        s, a = await self._turn(db_session, mm)
        await _marked(db_session, s, a)
        await _status(db_session, mm, s)
        await _transcribe(db_session, mm, s)
        await _say(db_session, a, Q_WANNEER)
        await _marked(db_session, s, a, 2)
        await _status(db_session, mm, s)
        await _transcribe(db_session, mm, s)
        await _say(db_session, a, Q_BUDGET)
        await _transcribe(db_session, mm, s)
        await _status(db_session, mm, s)

        assert mm.messages[a.post_id] == (
            f"{KOP}\n{OPENING} {Q_WANNEER} {Q_BUDGET}\n\n---\n❓ 2 vragen · 🔴 **open**"
        )

    async def test_the_transcription_restores_a_line_that_is_in_the_table(
        self, db_session
    ):
        """The line comes from the table, not from the message: a question
        marked between two writes of the text is not lost."""
        mm = Chat()
        s, a = await self._turn(db_session, mm)
        await _marked(db_session, s, a)

        await _transcribe(db_session, mm, s)

        assert mm.messages[a.post_id].endswith(f"\n\n---\n{STATUS_EEN}")

    async def test_a_question_without_a_thread_is_not_in_the_line(self, db_session):
        mm = Chat()
        s, a = await self._turn(db_session, mm)
        await _marked(db_session, s, a)
        await db_session.execute(update(DebatMarkering).values(thread_post_id=None))

        await _transcribe(db_session, mm, s)

        assert mm.messages[a.post_id] == f"{KOP}\n{OPENING}"

    async def test_the_line_of_another_turn_is_not_this_ones(self, db_session):
        mm = Chat()
        s, a = await self._turn(db_session, mm)
        b = await _row(db_session, s, "speaker", 120, "b")
        mm.messages[b.post_id] = KOP
        await _say(db_session, b, OPENING)
        await _marked(db_session, s, a)

        await _transcribe(db_session, mm, s)

        assert mm.messages[b.post_id] == f"{KOP}\n{OPENING}"
        assert mm.messages[a.post_id].endswith(STATUS_EEN)

    async def test_the_cut_is_in_the_text_and_the_line_stays_on_the_first_message(
        self, db_session
    ):
        mm = Chat()
        zin = "Dit is een zin van precies zoveel woorden als nodig is."
        tekst = " ".join([zin] * 60)
        s, a = await self._turn(db_session, mm, tekst)
        await _marked(db_session, s, a)

        await _transcribe(db_session, mm, s)

        pieces = split_text(tekst)
        assert len(pieces) > 1 and len(pieces[0]) <= MESSAGE_LIMIT
        turn = (await load_turns(db_session, s.id, PART))[0]
        # Cut exactly where it is cut without a line.
        assert mm.messages[a.post_id] == voeg_samen(render(KOP, pieces[0]), STATUS_EEN)
        assert [mm.messages[p] for p in turn.vervolg] == [
            render(KOP, piece, vervolg=True) for piece in pieces[1:]
        ]

        # Words that come in late go into the last message. The first one
        # is not written again, and still ends with the line.
        updates = len(mm.updates)
        await _row(db_session, s, "speaker", 300, "b")
        await _say(db_session, a, Q_WANNEER)
        await _transcribe(db_session, mm, s)

        assert [post_id for post_id, _ in mm.updates[updates:]] == [turn.vervolg[-1]]
        assert mm.messages[turn.vervolg[-1]].endswith(Q_WANNEER)
        assert "---" not in mm.messages[turn.vervolg[-1]]
        assert mm.messages[a.post_id].endswith(f"\n\n---\n{STATUS_EEN}")

    async def test_a_status_line_on_a_long_turn_touches_only_the_first_message(
        self, db_session
    ):
        mm = Chat()
        zin = "Dit is een zin van precies zoveel woorden als nodig is."
        tekst = " ".join([zin] * 60)
        s, a = await self._turn(db_session, mm, tekst)
        await _transcribe(db_session, mm, s)
        turn = (await load_turns(db_session, s.id, PART))[0]
        before = {p: mm.messages[p] for p in turn.vervolg}
        first = mm.messages[a.post_id]
        await _marked(db_session, s, a)

        await _status(db_session, mm, s)

        assert mm.messages[a.post_id] == f"{first}\n\n---\n{STATUS_EEN}"
        assert {p: mm.messages[p] for p in turn.vervolg} == before

    async def test_a_message_too_long_for_mattermost_loses_text_not_the_line(
        self, db_session
    ):
        mm = Chat()
        s, a = await self._turn(db_session, mm)
        await _transcribe(db_session, mm, s)
        # Someone else has a message below, so everything piles into one.
        await _row(db_session, s, "speaker", 300, "b")
        await _marked(db_session, s, a)
        await _say(db_session, a, "woord " * 4000)

        await _transcribe(db_session, mm, s)

        message = mm.messages[a.post_id]
        # One less when the cut falls on a space.
        assert MESSAGE_MAX - 1 <= len(message) <= MESSAGE_MAX
        assert message.endswith(f"\n\n---\n{STATUS_EEN}")
        assert message.count("woord") > 2000

    async def test_without_a_line_the_whole_room_is_for_the_text(self, db_session):
        mm = Chat()
        s, a = await self._turn(db_session, mm)
        await _transcribe(db_session, mm, s)
        await _row(db_session, s, "speaker", 300, "b")
        await _say(db_session, a, "woord " * 4000)

        await _transcribe(db_session, mm, s)

        assert len(mm.messages[a.post_id]) == MESSAGE_MAX

    async def test_a_rule_in_the_text_is_not_taken_for_the_line(self, db_session):
        mm = Chat()
        s, a = await self._turn(db_session, mm, "---")
        await _transcribe(db_session, mm, s)
        await _marked(db_session, s, a)

        await _status(db_session, mm, s)

        assert mm.messages[a.post_id] == f"{KOP}\n\\---\n\n---\n{STATUS_EEN}"


@pytest.mark.asyncio
class TestTheLoop:
    async def test_it_is_registered(self):
        import inspect

        from bouwmeester import worker

        assert "_debat_vragen_loop(settings)" in inspect.getsource(worker.main)

    async def test_on_by_default_and_switched_off_is_said_once(self, monkeypatch):
        from bouwmeester import worker
        from bouwmeester.core.config import Settings, get_settings

        assert Settings.model_fields["DEBAT_VRAGEN_ENABLED"].default is True
        ticks = []

        async def health(name, *, status="ok", detail=None):
            ticks.append((name, status))

        monkeypatch.setattr(worker, "health_tick", health)
        settings = get_settings().model_copy(update={"DEBAT_VRAGEN_ENABLED": False})

        await worker._debat_vragen_loop(settings)

        assert ticks == [("debat_vragen", "disabled")]

    async def test_a_round_per_interval_with_one_memory_of_the_debates(
        self, monkeypatch
    ):
        from bouwmeester import worker
        from bouwmeester.core.config import get_settings

        ticks, sleeps, memories, closed = [], [], [], []

        class StopError(Exception):
            pass

        async def health(name, *, status="ok", detail=None):
            ticks.append((name, status, detail))

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        class Worker:
            def __init__(self, session, contexts=None):
                memories.append(contexts)

            async def tick(self):
                if len(memories) == 2:
                    raise RuntimeError("stuk")
                return mod.VraagTickResult(sessies=1, beoordeeld=1)

            async def close(self):
                closed.append(len(memories))

        async def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 2:
                raise StopError

        monkeypatch.setattr(worker, "health_tick", health)
        monkeypatch.setattr(worker, "async_session", Session)
        monkeypatch.setattr(mod, "DebatVraagWorker", Worker)
        monkeypatch.setattr(worker.asyncio, "sleep", sleep)
        settings = get_settings().model_copy(
            update={"DEBAT_VRAGEN_ENABLED": True, "DEBAT_VRAGEN_INTERVAL_SECONDS": 7}
        )

        with pytest.raises(StopError):
            await worker._debat_vragen_loop(settings)

        assert sleeps == [7, 7]
        # One memory for all rounds, and every round closes what it opened.
        assert memories[0] is memories[1] and memories[0] == {}
        assert closed == [1, 2]
        assert [(name, status) for name, status, _ in ticks] == [
            ("debat_vragen", "starting"),
            ("debat_vragen", "ok"),
            ("debat_vragen", "error"),
        ]
        assert "1 spreekbeurten gelezen" in ticks[1][2]
        assert "stuk" in ticks[2][2]

    async def test_the_health_page_knows_the_loop(self):
        from bouwmeester.api.routes.admin import _worker_expected_cadence_sec

        cadence = _worker_expected_cadence_sec()["debat_vragen"]
        # Longer than a round that catches up, and than the heartbeat.
        assert cadence >= 120


@pytest.mark.asyncio
class TestTwoEventsOneTurn:
    """Someone entered as interrupter and seconds later as speaker has one
    turn, and it is read as a speaker's turn: an interruption only counts
    when it is put to the bewindspersoon who is interrupted."""

    async def test_the_turn_is_handed_in_once_as_a_speakers_turn(
        self, db_session, monkeypatch, handed
    ):
        debat = _debat(
            ("speaker", 0.5, "m"),
            ("interrupter", 1, "a"),
            ("speaker", 1.25, "a"),
            ("speaker", 3, "b"),
        )
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Outside(monkeypatch)
        Subtitles(monkeypatch, feed, [_cue(65, OPENING), _cue(80, Q_WANNEER)])
        mm, llm = Chat(), FakeLLM(antwoord(vraag(Q_WANNEER)))
        await _sessie(db_session)

        await _follow(db_session, mm, feed, llm, 6)

        rows = (
            (
                await db_session.execute(
                    select(DebatSpreekbeurt)
                    .where(DebatSpreekbeurt.object_id == "a")
                    .order_by(DebatSpreekbeurt.event_start)
                )
            )
            .scalars()
            .all()
        )
        first, second = rows
        assert (first.event_type, second.event_type) == ("interrupter", "speaker")
        assert second.post_id is None
        (beurt,) = [b for b, _ in handed if b.spreker == "Kamerlid A (X)"]
        assert beurt.spreekbeurt_id == first.id
        assert beurt.post_id == first.post_id
        assert beurt.soort == "speaker"
        # Nobody was interrupted, although the minister had the floor.
        assert beurt.onderbroken is None
        # The words under both events, as one text.
        assert beurt.tekst == f"{OPENING} {Q_WANNEER}"
        assert [root for root, _ in mm.threads] == [first.post_id]
        message = mm.messages[first.post_id]
        assert message.startswith("**Kamerlid A (X)** · [")
        assert message.endswith(STATUS_EEN)

    async def test_the_questions_counted_under_the_message_stay_when_it_changes(
        self, db_session
    ):
        """The first line is changed on the row; the message is put
        together by the one place that always does, status line and all."""
        mm = Chat()
        s = await _running(db_session)
        kop = heading_as(KOP, "interrupter")
        a = await _row(db_session, s, "interrupter", 60, "a", kop=kop)
        mm.messages[a.post_id] = kop
        mm.order.append(a.post_id)
        await _say(db_session, a, OPENING)
        await _transcribe(db_session, mm, s)
        await _marked(db_session, s, a)
        await _status(db_session, mm, s)
        assert mm.messages[a.post_id] == f"{kop}\n{OPENING}\n\n---\n{STATUS_EEN}"

        service = DebatTijdlijnService(db_session, mm)
        floor = Floor("interrupter", "a", a.event_start, kop)
        await service._change_turn(s.id, PART, floor, "speaker")
        await service._write_changed(s, TickResult())

        assert mm.messages[a.post_id] == f"{KOP}\n{OPENING}\n\n---\n{STATUS_EEN}"
