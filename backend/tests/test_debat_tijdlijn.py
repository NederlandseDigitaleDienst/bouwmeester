"""Tests for the timeline: who speaks when, in the channel of a debate.

The service tests replay a real debate (see `test_debat_direct.py` for the
fixture) against a real database with a fake Mattermost. Debat Direct is
replaced by a clock: at each moment it shows the events that had happened
by then, the way the live feed does.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy import update as sa_update

from bouwmeester.models.debat_sessie import (
    TIJDLIJN_AFGELAST,
    TIJDLIJN_AFGELOPEN,
    TIJDLIJN_GEKOPPELD,
    TIJDLIJN_LOOPT,
    DebatSessie,
    DebatSpreekbeurt,
)
from bouwmeester.services import debat_direct as dd
from bouwmeester.services import debat_tijdlijn_service as mod
from bouwmeester.services.debat_kanaal_service import channel_header
from bouwmeester.services.debat_tijdlijn_service import (
    DebatTijdlijnService,
    Floor,
    TickResult,
    floors_from,
    format_event,
    heading_as,
    turn_kind,
)
from bouwmeester.services.mattermost_service import PostNotFoundError
from bouwmeester.services.tk_activiteit import Activiteit, TkApiError
from tests.test_debat_direct import CEST, FIXTURE

FULL = dd.parse_debate(FIXTURE["debate"])
START = FULL.started_at
# How long after a speaker change the feed shows it (measured: 5.8 to 8.7 s).
FEED_DELAY = timedelta(seconds=7)


def _sprekers() -> dict[str, dd.Spreker]:
    fracties = {p["id"].lower(): p["shorthand"] for p in FIXTURE["actors"]["parties"]}
    return {
        p["id"]: dd.Spreker(
            p["name"], fracties.get((p.get("partyId") or "").lower()), p.get("title")
        )
        for p in FIXTURE["actors"]["politicians"]
    }


SPREKERS = _sprekers()


def _event(kind: str, at: str, object_id: str = "p1") -> dd.DdEvent:
    raw = f"2026-10-01T{at}+0200"
    return dd.DdEvent(datetime.fromisoformat(raw), kind, object_id, raw)


class TestFormatEvent:
    S = {"p1": dd.Spreker("Kamerlid A", "CDA"), "p2": dd.Spreker("Kamerlid B", "SP")}

    def test_speaker_with_a_link_to_the_moment(self):
        tekst = format_event(_event("speaker", "10:42:10"), FULL, self.S)
        assert tekst == (
            "**Kamerlid A (CDA)** · [10:42]("
            + dd.debate_url(FULL)
            + "?event=speaker2026-10-01T10%3A42%3A10%2B0200)"
        )

    def test_interruption_is_marked(self):
        tekst = format_event(_event("interrupter", "10:45:00", "p2"), FULL, self.S)
        assert tekst.startswith("↳ **Kamerlid B (SP)** · [10:45](")
        assert tekst.endswith(" · interruptie")

    def test_the_chairman_is_a_turn_of_his_own(self):
        tekst = format_event(_event("chairman", "10:42:00"), FULL, self.S)
        assert tekst.startswith("🔨 **Voorzitter Kamerlid A** · [10:42](")

    def test_an_unknown_chairman_is_still_the_chairman(self):
        tekst = format_event(_event("chairman", "10:42:00", "wie"), FULL, self.S)
        assert tekst.startswith("🔨 **Voorzitter** · [10:42](")

    def test_unknown_speaker_is_still_a_turn(self):
        tekst = format_event(_event("speaker", "10:42:10", "wie"), FULL, self.S)
        assert tekst.startswith("**Onbekende spreker**")

    def test_time_is_dutch_time(self):
        """The worker runs in UTC; the debate is at 10:42 in The Hague."""
        raw = "2026-10-01T08:42:10+0000"
        event = dd.DdEvent(datetime.fromisoformat(raw), "speaker", "p1", raw)
        assert "[10:42](" in format_event(event, FULL, self.S)

    def test_a_name_cannot_inject_a_mention(self):
        evil = {"p1": dd.Spreker("@channel [x](http://evil.test)", None)}
        tekst = format_event(_event("speaker", "10:42:10"), FULL, evil)
        assert "@channel" not in tekst.replace("\\@channel", "")
        assert "[x](http://evil.test)" not in tekst

    def test_start_names_the_room(self):
        tekst = format_event(_event("debate_start", "10:00:36", FULL.id), FULL, {})
        assert tekst.startswith(
            "▶️ **Het debat is begonnen** in de Klompézaal · [10:00]("
        )

    def test_suspension_resumption_and_end(self):
        assert format_event(_event("suspended", "11:10:08"), FULL, {}) == (
            "⏸️ **Geschorst** · 11:10"
        )
        assert format_event(_event("continued", "11:34:00"), FULL, {}).startswith(
            "▶️ **Hervat** · [11:34]("
        )
        assert format_event(_event("debate_end", "13:00:54"), FULL, {}) == (
            "⏹️ **Het debat is afgelopen** · 13:00"
        )

    def test_change_of_chairman_names_the_new_one(self):
        tekst = format_event(_event("chairman_change", "12:42:23", "p2"), FULL, self.S)
        assert tekst == "_Voorzitter is nu Kamerlid B_ · 12:42"

    def test_an_event_of_an_unknown_kind_gets_no_message(self):
        assert format_event(_event("voting_round", "12:00:00"), FULL, self.S) is None


class TestTurnKind:
    """Whether an event of the person who has the floor is part of the turn."""

    BEGAN = _event("speaker", "10:42:00").start

    def _kind(self, kind: str, event_kind: str, at: str) -> str | None:
        return turn_kind(kind, self.BEGAN, _event(event_kind, at))

    def test_a_speaker_who_carries_on_stays_in_the_turn(self):
        assert self._kind("speaker", "speaker", "10:43:00") == "speaker"

    def test_however_long_the_turn_has_lasted(self):
        assert self._kind("speaker", "speaker", "11:30:00") == "speaker"
        assert self._kind("interrupter", "interrupter", "10:50:00") == "interrupter"

    def test_entered_as_interrupter_and_seconds_later_as_speaker_is_a_speaker(self):
        assert self._kind("interrupter", "speaker", "10:42:03") == "speaker"

    def test_the_event_that_came_last_says_which_it_is(self):
        """The other way round it was an interruption after all."""
        assert self._kind("speaker", "interrupter", "10:42:05") == "interrupter"

    def test_in_the_same_second_it_is_the_speaker(self):
        """The order of two events in one second is not known."""
        assert self._kind("interrupter", "speaker", "10:42:00") == "speaker"
        assert self._kind("speaker", "interrupter", "10:42:00") == "speaker"

    def test_the_bound_is_on_the_time_since_the_turn_began(self):
        """All 108 measured came within 40 seconds; the next after 61."""
        assert mod.SAME_TURN_WITHIN == timedelta(seconds=50)
        assert self._kind("interrupter", "speaker", "10:42:50") == "speaker"
        assert self._kind("interrupter", "speaker", "10:42:51") is None
        assert self._kind("speaker", "interrupter", "10:42:51") is None

    def test_an_event_from_before_the_turn_is_not_part_of_it(self):
        assert self._kind("interrupter", "speaker", "10:41:59") is None


class TestHeadingAs:
    S = {"p1": dd.Spreker("Kamerlid A", "CDA")}

    def test_an_interruption_becomes_a_speakers_line_and_back(self):
        speaker = format_event(_event("speaker", "10:42:10"), FULL, self.S)
        interruption = format_event(_event("interrupter", "10:42:10"), FULL, self.S)
        link = "?event=interrupter2026-10-01T10%3A42%3A10%2B0200)"
        assert heading_as(interruption, "speaker") == speaker.replace(
            "?event=speaker2026-10-01T10%3A42%3A10%2B0200)", link
        )
        # The link stays the one to the first event: that is where the
        # turn begins, and the site only knows moments by their own kind.
        assert link in heading_as(interruption, "speaker")
        assert heading_as(heading_as(interruption, "speaker"), "interrupter") == (
            interruption
        )

    def test_a_line_that_is_the_kind_already_stays_as_it_is(self):
        speaker = format_event(_event("speaker", "10:42:10"), FULL, self.S)
        interruption = format_event(_event("interrupter", "10:42:10"), FULL, self.S)
        assert heading_as(speaker, "speaker") == speaker
        assert heading_as(interruption, "interrupter") == interruption


class TestFloors:
    """Who has the floor, read back from the rows after a restart."""

    T = _event("speaker", "10:42:00").start

    def _row(self, kind, seconds, who="a", post="p", soort=None, part="d1"):
        post_id = f"{post}{seconds}" if post else None
        return (
            part,
            kind,
            self.T + timedelta(seconds=seconds),
            who,
            post_id,
            soort,
            f"kop {kind}" if post_id else None,
        )

    def test_the_last_turn_with_a_message(self):
        floors = floors_from(
            [self._row("speaker", 0, "a"), self._row("interrupter", 30, "b")]
        )
        assert floors["d1"] == Floor(
            "interrupter",
            "b",
            self.T + timedelta(seconds=30),
            "kop interrupter",
        )

    def test_a_turn_is_the_kind_it_was_made_not_the_kind_of_its_first_event(self):
        floors = floors_from(
            [
                self._row("interrupter", 0, soort="speaker"),
                self._row("speaker", 3, post=None),
            ]
        )
        floor = floors["d1"]
        assert (floor.kind, floor.began) == ("speaker", self.T)

    def test_a_row_that_went_into_the_turn_does_not_end_it(self):
        """Entered as speaker in between, in a turn that became an
        interruption after all."""
        floors = floors_from(
            [
                self._row("interrupter", 0, soort="interrupter"),
                self._row("speaker", 2, post=None, soort="interrupter"),
                self._row("interrupter", 27, post=None, soort="interrupter"),
            ]
        )
        assert floors["d1"].kind == "interrupter"

    def test_someone_without_a_message_takes_the_floor_from_whoever_had_it(self):
        """A stretch the timeline missed."""
        rows = [self._row("speaker", 0, "a"), self._row("speaker", 30, "b", post=None)]
        assert floors_from(rows) == {}
        # Also the same person in the other role, when that was not made
        # part of the turn.
        rows = [self._row("interrupter", 0), self._row("speaker", 90, post=None)]
        assert floors_from(rows) == {}

    def test_a_message_that_is_not_a_turn_ends_the_turn(self):
        rows = [self._row("speaker", 0), self._row("suspended", 30, "")]
        assert floors_from(rows) == {}

    def test_the_chairman_takes_the_floor(self):
        rows = [self._row("speaker", 0), self._row("chairman", 30, "v")]
        assert floors_from(rows)["d1"].who == "v"

    def test_a_chairman_without_a_message_is_a_stretch_that_was_missed(self):
        rows = [self._row("speaker", 0), self._row("chairman", 30, "v", post=None)]
        assert floors_from(rows) == {}

    def test_every_part_has_a_floor_of_its_own(self):
        rows = [self._row("speaker", 0, "a"), self._row("speaker", 5, "b", part="d2")]
        assert {part: f.who for part, f in floors_from(rows).items()} == {
            "d1": "a",
            "d2": "b",
        }


class TestHeader:
    def test_room_and_stream_replace_the_generic_link(self):
        activiteit = Activiteit(
            id="a",
            nummer="2026A00001",
            soort="Commissiedebat",
            onderwerp="x",
            aanvang=datetime(2026, 10, 1, 10, 0, tzinfo=CEST),
            einde=None,
            status=None,
            commissie=None,
            bewindspersonen=(),
            agendapunten=(),
        )
        header = channel_header(
            activiteit, zaal="Klompézaal", stream_url="https://dd.test/debat"
        )
        assert "· Klompézaal ·" in header
        assert "[Livestream](https://dd.test/debat)" in header
        assert "[Debat Direct]" not in header
        # And without them it is what it was, so an adopted channel still
        # compares equal.
        assert "[Debat Direct](" in channel_header(activiteit)
        assert "Klompézaal" not in channel_header(activiteit)


class FakeMattermost:
    def __init__(self) -> None:
        self.posts: list[tuple[str, str]] = []
        self.headers: list[tuple[str, dict]] = []
        self.fail_posts = 0
        self.enabled = True
        self.gone: set[str] = set()
        # Where in `posts` each message is.
        self.now: dict[str, int] = {}

    async def is_enabled(self) -> bool:
        return self.enabled

    async def send_channel_message(self, channel_id, text, props=None, root_id=None):
        if self.fail_posts > 0:
            self.fail_posts -= 1
            return None
        self.posts.append((channel_id, text))
        post_id = f"post{uuid.uuid4().hex}"[:26]
        self.now[post_id] = len(self.posts) - 1
        return post_id

    async def update_post(self, post_id, message, props=None) -> bool:
        """A message is written again: it says the new text from then on."""
        if post_id not in self.now:
            return False
        channel_id, _ = self.posts[self.now[post_id]]
        self.posts[self.now[post_id]] = (channel_id, message)
        return True

    async def get_post(self, post_id) -> dict | None:
        if post_id not in self.now:
            raise PostNotFoundError(post_id)
        return {"id": post_id}

    async def update_channel(self, channel_id, **fields) -> bool:
        self.headers.append((channel_id, fields))
        return True

    async def channel_is_gone(self, channel_id) -> bool:
        return channel_id in self.gone

    async def close(self) -> None:
        pass

    @property
    def texts(self) -> list[str]:
        return [text for _, text in self.posts]

    @property
    def turns(self) -> list[str]:
        return [t for t in self.texts if t.startswith(("**", "↳"))]


class Feed:
    """Debat Direct at a moment in time: what the live feed showed then."""

    def __init__(self, monkeypatch, *, parts: list[dd.DdDebat] | None = None) -> None:
        self.now = START
        self.parts = parts or [FULL]
        self.activiteit_status = "Gepland"
        self.aanvang = START.replace(second=0)
        self.activiteit_error = False
        self.agenda_error = False
        self.calls: list[str] = []

        async def agenda(client, day, base_url=None):
            self.calls.append("agenda")
            if self.agenda_error:
                raise dd.DebatDirectError("down")
            return [self._at(part) for part in self.parts if self._known(part)]

        async def debate(client, debate_id, base_url=None):
            self.calls.append("debate")
            part = next(p for p in self.parts if p.id == debate_id)
            return self._at(part)

        async def sprekers(client, day, base_url=None):
            self.calls.append("sprekers")
            return SPREKERS

        async def activiteit(activiteit_id, client, base_url=None):
            self.calls.append("activiteit")
            if self.activiteit_error:
                raise TkApiError("down")
            return _activiteit(
                activiteit_id, status=self.activiteit_status, aanvang=self.aanvang
            )

        monkeypatch.setattr(dd, "fetch_agenda", agenda)
        monkeypatch.setattr(dd, "fetch_debate", debate)
        monkeypatch.setattr(dd, "fetch_sprekers", sprekers)
        monkeypatch.setattr(mod, "fetch_activiteit", activiteit)

    def _known(self, part: dd.DdDebat) -> bool:
        """A later part only appears on the agenda when it starts."""
        return part is self.parts[0] or part.starts_at <= self.now

    def _at(self, part: dd.DdDebat) -> dd.DdDebat:
        events = tuple(e for e in part.events if e.start <= self.now - FEED_DELAY)
        return dd.DdDebat(
            **{
                **part.__dict__,
                "events": events,
                "started_at": part.started_at if part.started_at <= self.now else None,
                "ended_at": part.ended_at
                if part.ended_at and part.ended_at <= self.now
                else None,
            }
        )


def _activiteit(
    activiteit_id: str, *, status: str = "Gepland", aanvang: datetime | None = None
) -> Activiteit:
    return Activiteit(
        id=activiteit_id,
        nummer="2026A00001",
        soort="Commissiedebat",
        onderwerp=FULL.name,
        aanvang=aanvang or START.replace(second=0),
        einde=None,
        status=status,
        commissie=None,
        bewindspersonen=(),
        agendapunten=(),
    )


def _debat(*events: tuple[str, int, str]) -> dd.DdDebat:
    """A made-up debate: a start, then (kind, minutes after the start, who)."""
    made = [dd.DdEvent(START, dd.EVENT_DEBATE_START, "", "start")]
    for kind, minutes, who in events:
        at = START + timedelta(minutes=minutes)
        made.append(dd.DdEvent(at, kind, who, f"{kind}{minutes}"))
    return dd.DdDebat(**{**FULL.__dict__, "events": tuple(made), "ended_at": None})


async def _sessie(db_session, **overrides) -> DebatSessie:
    values = {
        "activiteit_id": str(uuid.uuid4()),
        "activiteit_nummer": "2026A00001",
        "onderwerp": FULL.name,
        "aanvang": START.replace(second=0),
        "team_id": "team00000000000000000000aa",
        "channel_id": f"chan{uuid.uuid4().hex}"[:26],
        "channel_name": "debat-test",
    }
    values.update(overrides)
    sessie = DebatSessie(**values)
    db_session.add(sessie)
    await db_session.flush()
    return sessie


async def _run(db_session, mm, feed, start: datetime, end: datetime, step: int = 30):
    """Tick from `start` to `end`, a fresh service each time like the worker."""
    now = start
    while now <= end:
        feed.now = now
        await DebatTijdlijnService(db_session, mm).tick(now.astimezone(UTC))
        now += timedelta(seconds=step)


async def _rows(db_session, sessie) -> int:
    stmt = select(func.count()).where(DebatSpreekbeurt.sessie_id == sessie.id)
    return (await db_session.execute(stmt)).scalar_one()


@pytest.mark.asyncio
class TestCoupling:
    async def test_found_on_debat_direct_and_header_updated(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        sessie = await _sessie(db_session)

        feed.now = START - timedelta(hours=1)
        result = await DebatTijdlijnService(db_session, mm).tick(feed.now)

        assert result.gekoppeld == 1
        assert sessie.tijdlijn_status == TIJDLIJN_GEKOPPELD
        assert sessie.debat_direct_ids == [FULL.id]
        ((channel_id, fields),) = mm.headers
        assert channel_id == sessie.channel_id
        assert "· Klompézaal ·" in fields["header"]
        assert f"[Livestream]({dd.debate_url(FULL)})" in fields["header"]
        # Nothing is posted for finding it; the header says it.
        assert mm.posts == []

    async def test_cancelled_debate_is_said_in_the_channel(
        self, db_session, monkeypatch
    ):
        """Instead of waiting for a stream that never comes."""
        feed = Feed(monkeypatch)
        feed.activiteit_status = "Geannuleerd"
        mm = FakeMattermost()
        sessie = await _sessie(db_session)

        await _run(db_session, mm, feed, START - timedelta(hours=1), START, step=600)

        assert sessie.tijdlijn_status == TIJDLIJN_AFGELAST
        assert mm.texts == ["⚠️ Dit debat is geannuleerd."]
        assert mm.headers == []

    async def test_moved_debate_is_said_too(self, db_session, monkeypatch):
        feed = Feed(monkeypatch)
        feed.activiteit_status = "Verplaatst"
        mm = FakeMattermost()
        sessie = await _sessie(db_session)

        feed.now = START - timedelta(hours=1)
        await DebatTijdlijnService(db_session, mm).tick(feed.now)

        assert sessie.tijdlijn_status == TIJDLIJN_AFGELAST
        assert "verplaatst" in mm.texts[0]

    async def test_unreadable_tk_api_does_not_stop_the_coupling(
        self, db_session, monkeypatch
    ):
        """What the sessie remembers is enough to find the debate."""
        feed = Feed(monkeypatch)
        feed.activiteit_error = True
        mm = FakeMattermost()
        sessie = await _sessie(db_session)

        feed.now = START - timedelta(hours=1)
        await DebatTijdlijnService(db_session, mm).tick(feed.now)

        assert sessie.tijdlijn_status == TIJDLIJN_GEKOPPELD

    async def test_not_yet_on_debat_direct_is_tried_again_later_not_every_tick(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch)
        feed.agenda_error = True
        mm = FakeMattermost()
        sessie = await _sessie(db_session)

        start = START - timedelta(hours=1)
        await _run(db_session, mm, feed, start, start + timedelta(minutes=4), step=10)
        assert sessie.tijdlijn_status is None
        assert feed.calls.count("agenda") == 1

        feed.agenda_error = False
        await _run(
            db_session,
            mm,
            feed,
            start + timedelta(minutes=5),
            start + timedelta(minutes=6),
        )
        assert sessie.tijdlijn_status == TIJDLIJN_GEKOPPELD

    async def test_an_archived_channel_gets_no_timeline(self, db_session, monkeypatch):
        """Posting into it fails, and a failed post is retried every tick."""
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        sessie = await _sessie(db_session)
        mm.gone.add(sessie.channel_id)

        await _run(
            db_session,
            mm,
            feed,
            START - timedelta(hours=1),
            START + timedelta(minutes=10),
        )

        assert sessie.tijdlijn_status == TIJDLIJN_AFGELOPEN
        assert mm.posts == []
        assert mm.headers == []
        assert "agenda" not in feed.calls

    async def test_a_debate_far_ahead_is_left_alone(self, db_session, monkeypatch):
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        sessie = await _sessie(db_session)

        feed.now = START - timedelta(days=3)
        result = await DebatTijdlijnService(db_session, mm).tick(feed.now)

        assert result.sessies == 0
        assert feed.calls == []
        assert sessie.tijdlijn_status is None

    async def test_never_found_is_said_once_and_then_given_up(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch)
        feed.parts = [dd.parse_debate({**FIXTURE["debate"], "name": "Iets anders"})]
        mm = FakeMattermost()
        sessie = await _sessie(db_session)

        late = START + timedelta(hours=16, minutes=10)
        await _run(db_session, mm, feed, late, late + timedelta(minutes=20), step=300)

        assert sessie.tijdlijn_status == TIJDLIJN_AFGELOPEN
        assert len(mm.texts) == 1
        assert "niet op Debat Direct kunnen vinden" in mm.texts[0]

    async def test_no_mattermost_no_work(self, db_session, monkeypatch):
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        mm.enabled = False
        await _sessie(db_session)

        feed.now = START - timedelta(hours=1)
        await DebatTijdlijnService(db_session, mm).tick(feed.now)

        assert feed.calls == []


@pytest.mark.asyncio
class TestTimeline:
    async def test_a_whole_real_debate(self, db_session, monkeypatch):
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        sessie = await _sessie(db_session)

        await _run(
            db_session,
            mm,
            feed,
            START - timedelta(minutes=10),
            FULL.ended_at + timedelta(minutes=2),
            step=20,
        )

        assert sessie.tijdlijn_status == TIJDLIJN_LOOPT
        assert mm.texts[0].startswith("▶️ **Het debat is begonnen** in de Klompézaal")
        assert mm.texts[1].startswith("🔨 **Voorzitter Kamerlid E** · [10:00](")
        assert mm.texts[2].startswith("**Kamerlid D (SP)** · [10:01](")
        assert mm.texts[-1] == "⏹️ **Het debat is afgelopen** · 13:00"
        assert "⏸️ **Geschorst** · 11:10" in mm.texts
        assert any(t.startswith("▶️ **Hervat** · [11:34](") for t in mm.texts)
        assert "_Voorzitter is nu Kamerlid B_ · 12:42" in mm.texts
        # One message per turn: 153 speaker and interrupter events, of
        # which 6 are someone carrying on with nobody in between, or the
        # second event of someone entered as interrupter and seconds later
        # as speaker. The 75 chairman events are a message each.
        assert len(mm.turns) == 147
        assert sum(1 for t in mm.texts if t.startswith("🔨")) == 75
        assert len(mm.texts) == 227
        # Every event is remembered, posted or not.
        assert await _rows(db_session, sessie) == 233
        assert {channel for channel, _ in mm.posts} == {sessie.channel_id}

    async def test_messages_follow_the_order_of_the_debate(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        await _sessie(db_session)

        # Coarse ticks, so several events arrive at once.
        await _run(
            db_session,
            mm,
            feed,
            START - timedelta(minutes=10),
            START + timedelta(minutes=30),
            step=240,
        )

        tijden = [t.split("[")[1][:5] for t in mm.turns]
        assert tijden == sorted(tijden)
        assert len(tijden) > 10

    async def test_after_a_break_the_same_speaker_is_a_new_turn(
        self, db_session, monkeypatch
    ):
        """The minister spoke before the suspension and again after it.
        Without a message after "Hervat" the channel does not say who."""
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        await _sessie(db_session)

        await _run(
            db_session,
            mm,
            feed,
            START - timedelta(minutes=10),
            START.replace(hour=11, minute=36, second=0),
            step=20,
        )

        hervat = next(i for i, t in enumerate(mm.texts) if t.startswith("▶️ **Hervat**"))
        assert mm.texts[hervat + 1].startswith("**Bewindspersoon A")

    async def test_a_gap_in_following_is_not_posted_in_one_burst(
        self, db_session, monkeypatch
    ):
        """The worker, or Debat Direct, was away for half an hour. What was
        missed is history, like before joining."""
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        await _sessie(db_session)
        gap_start = START.replace(hour=10, minute=20, second=0)
        await _run(db_session, mm, feed, START - timedelta(minutes=10), gap_start)
        before = len(mm.texts)

        back = gap_start + timedelta(minutes=30)
        await _run(db_session, mm, feed, back, back + timedelta(seconds=30), step=10)

        after = mm.texts[before:]
        assert after[0].startswith(
            "⏭️ Ik was er even niet. Wat er tussen 10:19 en 10:39"
        )
        assert "spreekbeurten) staat op [Debat Direct](" in after[0]
        # Only the last ten minutes follow, not the 48 events of all thirty.
        assert len(after) < 20
        assert sum(1 for t in mm.texts if t.startswith("⏭️")) == 1

    async def test_mattermost_being_down_does_not_drop_events_without_a_word(
        self, db_session, monkeypatch
    ):
        """Events that could not be posted grow old while they wait. They
        are only filed as history once the channel has been told so."""
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        sessie = await _sessie(db_session)
        down = START.replace(hour=10, minute=20, second=0)
        await _run(db_session, mm, feed, START - timedelta(minutes=10), down)
        before = len(mm.texts)
        rows = await _rows(db_session, sessie)

        mm.fail_posts = 10_000
        up = down + timedelta(minutes=25)
        await _run(db_session, mm, feed, down + timedelta(seconds=30), up)
        feed.now = up
        result = await DebatTijdlijnService(db_session, mm).tick(up)

        assert len(mm.texts) == before
        # Only what gets no message of its own was filed in the meantime.
        unposted = select(func.count()).where(
            DebatSpreekbeurt.sessie_id == sessie.id,
            DebatSpreekbeurt.event_type.in_(("speaker", "interrupter")),
            DebatSpreekbeurt.event_start > down,
        )
        assert (await db_session.execute(unposted)).scalar_one() == 0
        assert await _rows(db_session, sessie) - rows < 3
        assert result.fouten == 1

        mm.fail_posts = 0
        await _run(db_session, mm, feed, up, up + timedelta(seconds=30), step=10)

        after = mm.texts[before:]
        assert after[0].startswith("⏭️ Ik was er even niet. Wat er tussen 10:19 en 10:3")
        assert sum(1 for t in after if t.startswith("⏭️")) == 1
        assert 1 <= len(after) - 1 < 25

    async def test_an_event_added_afterwards_is_not_a_gap(
        self, db_session, monkeypatch
    ):
        """The feed sometimes adds or corrects an event minutes later. The
        timeline was there all along, so it does not say it was away."""
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        sessie = await _sessie(db_session)
        until = START + timedelta(minutes=30)
        await _run(db_session, mm, feed, START - timedelta(minutes=10), until)
        before = list(mm.texts)
        rows = await _rows(db_session, sessie)

        late = dd.DdEvent(
            START + timedelta(minutes=12), dd.EVENT_SPEAKER, "late", "late"
        )
        events = tuple(sorted([*FULL.events, late], key=lambda e: e.start))
        feed.parts = [dd.DdDebat(**{**FULL.__dict__, "events": events})]
        feed.now = until + timedelta(seconds=5)
        await DebatTijdlijnService(db_session, mm).tick(feed.now)

        assert mm.texts == before
        assert await _rows(db_session, sessie) == rows + 1

    async def test_a_debate_that_ended_during_a_gap_is_said_to_be_over(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        await _sessie(db_session)
        gone = FULL.ended_at - timedelta(minutes=20)
        await _run(db_session, mm, feed, START - timedelta(minutes=10), gone)
        before = len(mm.texts)

        back = FULL.ended_at + timedelta(minutes=15)
        await _run(db_session, mm, feed, back, back + timedelta(seconds=20), step=10)

        after = mm.texts[before:]
        assert len(after) == 1
        assert after[0].startswith("⏭️ Ik was er even niet.")
        assert after[0].endswith("Het debat is inmiddels afgelopen.")

    async def test_a_debate_that_starts_early_is_followed_from_its_start(
        self, db_session, monkeypatch
    ):
        """Planned forty minutes later than it began. The agenda says it has
        started; the planned time is not waited for."""
        feed = Feed(monkeypatch)
        feed.aanvang = START.replace(second=0) + timedelta(minutes=40)
        mm = FakeMattermost()
        await _sessie(
            db_session, aanvang=feed.aanvang, created_at=START - timedelta(days=1)
        )

        await _run(
            db_session,
            mm,
            feed,
            START - timedelta(minutes=20),
            START + timedelta(minutes=8),
            step=10,
        )

        assert not any(t.startswith("🎧") for t in mm.texts)
        assert any("Het debat is begonnen" in t for t in mm.texts)
        assert mm.turns

    async def test_a_channel_made_before_the_start_gets_the_first_minutes(
        self, db_session, monkeypatch
    ):
        """The worker was down at the start and came back six minutes in.
        The channel was there in time, so that is a gap to catch up, not a
        debate joined halfway."""
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        await _sessie(db_session, created_at=START - timedelta(days=1))
        await _run(
            db_session,
            mm,
            feed,
            START - timedelta(minutes=20),
            START - timedelta(minutes=16),
        )

        back = START + timedelta(minutes=6)
        await _run(db_session, mm, feed, back, back + timedelta(seconds=20), step=10)

        assert not any(t.startswith("🎧") for t in mm.texts)
        assert any("Het debat is begonnen" in t for t in mm.texts)

    async def test_the_speaker_from_before_a_gap_is_a_new_turn_after_it(
        self, db_session, monkeypatch
    ):
        """A spoke, the timeline was away while B spoke, and A speaks again.
        Without a message for A the channel reads as if B never happened."""
        feed = Feed(
            monkeypatch,
            parts=[
                _debat(("speaker", 1, "a"), ("speaker", 5, "b"), ("speaker", 20, "a"))
            ],
        )
        mm = FakeMattermost()
        await _sessie(db_session)
        await _run(
            db_session,
            mm,
            feed,
            START - timedelta(minutes=10),
            START + timedelta(minutes=2),
        )
        assert len(mm.turns) == 1

        back = START + timedelta(minutes=21)
        await _run(db_session, mm, feed, back, back + timedelta(seconds=10), step=10)

        assert sum(1 for t in mm.texts if t.startswith("⏭️")) == 1
        assert len(mm.turns) == 2

    async def test_the_same_when_that_speaker_only_shows_a_round_later(
        self, db_session, monkeypatch
    ):
        feed = Feed(
            monkeypatch,
            parts=[
                _debat(("speaker", 1, "a"), ("speaker", 5, "b"), ("speaker", 20, "a"))
            ],
        )
        mm = FakeMattermost()
        await _sessie(db_session)
        await _run(
            db_session,
            mm,
            feed,
            START - timedelta(minutes=10),
            START + timedelta(minutes=2),
        )

        back = START + timedelta(minutes=17)
        await _run(db_session, mm, feed, back, back + timedelta(minutes=4), step=30)

        assert sum(1 for t in mm.texts if t.startswith("⏭️")) == 1
        assert len(mm.turns) == 2

    async def test_a_gap_in_which_nobody_spoke_is_not_announced(
        self, db_session, monkeypatch
    ):
        """Only the chairman said a word. "0 spreekbeurten" is not news."""
        feed = Feed(
            monkeypatch, parts=[_debat(("speaker", 1, "a"), ("chairman", 5, "v"))]
        )
        mm = FakeMattermost()
        sessie = await _sessie(db_session)
        await _run(
            db_session,
            mm,
            feed,
            START - timedelta(minutes=10),
            START + timedelta(minutes=2),
        )
        before = list(mm.texts)

        back = START + timedelta(minutes=17)
        await _run(db_session, mm, feed, back, back + timedelta(seconds=10), step=10)

        assert mm.texts == before
        assert await _rows(db_session, sessie) == 3

    async def test_a_resumption_and_a_speaker_in_the_same_second_keep_their_order(
        self, db_session, monkeypatch
    ):
        """Read back from the database, "hervat" has to come before the
        speaker of that same second, or that speaker counts as forgotten
        and gets a second message when carrying on."""
        debat = _debat(
            ("speaker", 1, "a"),
            ("suspended", 2, ""),
            ("continued", 3, ""),
            ("speaker", 3, "a"),
            ("speaker", 5, "a"),
        )
        feed = Feed(monkeypatch, parts=[debat])
        mm = FakeMattermost()
        sessie = await _sessie(
            db_session, tijdlijn_status=TIJDLIJN_LOOPT, debat_direct_ids=[debat.id]
        )
        # Stored in the unlucky order: the speaker before the resumption.
        for index in (0, 1, 2, 4, 3):
            event = debat.events[index]
            db_session.add(
                DebatSpreekbeurt(
                    sessie_id=sessie.id,
                    debat_direct_id=debat.id,
                    event_type=event.type,
                    event_start=event.start,
                    object_id=event.object_id,
                    post_id=f"post{index}",
                )
            )
            await db_session.flush()

        feed.now = START + timedelta(minutes=5, seconds=20)
        await DebatTijdlijnService(db_session, mm).tick(feed.now)

        assert mm.texts == []

    async def test_a_debate_that_ended_long_ago_in_a_gap_is_closed_at_once(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        sessie = await _sessie(db_session)
        gone = FULL.ended_at - timedelta(minutes=20)
        await _run(db_session, mm, feed, START - timedelta(minutes=10), gone)

        feed.now = FULL.ended_at + timedelta(hours=3, minutes=5)
        await DebatTijdlijnService(db_session, mm).tick(feed.now)

        assert sessie.tijdlijn_status == TIJDLIJN_AFGELOPEN

    async def test_a_channel_archived_during_the_debate_stops_the_timeline(
        self, db_session, monkeypatch
    ):
        """Otherwise every tick fails for the rest of the day, and the
        heartbeat says "error" over a timeline nobody is waiting for."""
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        sessie = await _sessie(db_session)
        until = START + timedelta(minutes=20)
        await _run(db_session, mm, feed, START - timedelta(minutes=10), until)

        mm.gone.add(sessie.channel_id)
        mm.fail_posts = 10_000
        later = until + timedelta(minutes=3)
        await _run(db_session, mm, feed, until, later)

        assert sessie.tijdlijn_status == TIJDLIJN_AFGELOPEN
        feed.now = later + timedelta(seconds=30)
        result = await DebatTijdlijnService(db_session, mm).tick(feed.now)
        assert (result.sessies, result.fouten) == (0, 0)

    async def test_a_channel_archived_while_the_timeline_was_away_stops_it_too(
        self, db_session, monkeypatch
    ):
        """Then the first thing that fails is the line about what was
        missed, and nothing after it is ever tried."""
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        sessie = await _sessie(db_session)
        until = START + timedelta(minutes=20)
        await _run(db_session, mm, feed, START - timedelta(minutes=10), until)

        mm.gone.add(sessie.channel_id)
        mm.fail_posts = 10_000
        feed.now = until + timedelta(minutes=30)
        await DebatTijdlijnService(db_session, mm).tick(feed.now)

        assert sessie.tijdlijn_status == TIJDLIJN_AFGELOPEN

    async def test_a_message_that_fails_in_a_living_channel_does_not_stop_it(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        sessie = await _sessie(db_session)
        until = START + timedelta(minutes=20)
        await _run(db_session, mm, feed, START - timedelta(minutes=10), until)

        mm.fail_posts = 10_000
        await _run(db_session, mm, feed, until, until + timedelta(minutes=15))

        assert sessie.tijdlijn_status == TIJDLIJN_LOOPT

    async def test_a_suspension_missed_in_a_storing_is_not_dropped_silently(
        self, db_session, monkeypatch
    ):
        """Nobody spoke, but the channel would have been told "geschorst"."""
        feed = Feed(
            monkeypatch, parts=[_debat(("speaker", 1, "a"), ("suspended", 2, ""))]
        )
        mm = FakeMattermost()
        await _sessie(db_session)
        down = START + timedelta(minutes=1, seconds=30)
        await _run(db_session, mm, feed, START - timedelta(minutes=10), down)
        before = len(mm.texts)

        mm.fail_posts = 10_000
        up = START + timedelta(minutes=14)
        await _run(db_session, mm, feed, down + timedelta(seconds=30), up)
        mm.fail_posts = 0
        await _run(db_session, mm, feed, up, up + timedelta(seconds=30), step=10)

        after = mm.texts[before:]
        assert len(after) == 1
        assert after[0].startswith("⏭️ Ik was er even niet.")
        assert "gebeurde staat op" in after[0]
        assert "spreekbeurt" not in after[0]

    async def test_a_turn_in_the_same_second_as_a_silent_event_is_not_lost(
        self, db_session, monkeypatch
    ):
        """The chairman's event gets no message and is filed while posting
        fails. The speaker of that same second must still count as missed."""
        feed = Feed(
            monkeypatch,
            parts=[
                _debat(("speaker", 1, "a"), ("chairman", 5, "v"), ("speaker", 5, "b"))
            ],
        )
        mm = FakeMattermost()
        await _sessie(db_session)
        down = START + timedelta(minutes=2)
        await _run(db_session, mm, feed, START - timedelta(minutes=10), down)
        before = len(mm.texts)

        mm.fail_posts = 10_000
        up = START + timedelta(minutes=17)
        await _run(db_session, mm, feed, down + timedelta(seconds=30), up)
        mm.fail_posts = 0
        await _run(db_session, mm, feed, up, up + timedelta(seconds=30), step=10)

        after = mm.texts[before:]
        assert len(after) == 1
        assert "(1 spreekbeurt)" in after[0]

    async def test_the_early_start_is_remembered_between_ticks(
        self, db_session, monkeypatch
    ):
        """The agenda is read once in five minutes. What it said has to
        hold for the ticks in between, also when the first look at the
        debate found nothing yet."""
        feed = Feed(monkeypatch)
        feed.aanvang = START.replace(second=0) + timedelta(minutes=40)
        mm = FakeMattermost()
        sessie = await _sessie(
            db_session, aanvang=feed.aanvang, created_at=START - timedelta(days=1)
        )

        await _run(
            db_session,
            mm,
            feed,
            START - timedelta(minutes=20),
            START + timedelta(minutes=8),
            step=10,
        )

        assert sessie.aanvang <= START + timedelta(seconds=1)
        assert feed.calls.count("debate") > 10

    async def test_an_agenda_that_cannot_be_read_is_tried_again_soon(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch)
        feed.aanvang = START.replace(second=0) + timedelta(minutes=40)
        mm = FakeMattermost()
        await _sessie(db_session, aanvang=feed.aanvang)
        first = START - timedelta(minutes=30)
        await _run(db_session, mm, feed, first, first + timedelta(seconds=20), step=10)
        feed.calls.clear()

        feed.agenda_error = True
        again = first + timedelta(minutes=6)
        await _run(db_session, mm, feed, again, again + timedelta(minutes=3), step=10)

        assert 3 <= feed.calls.count("agenda") <= 5

    async def test_joining_after_the_end_says_it_is_over(self, db_session, monkeypatch):
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        await _sessie(db_session)

        late = FULL.ended_at + timedelta(minutes=10)
        await _run(db_session, mm, feed, late, late + timedelta(seconds=20), step=10)

        assert len(mm.texts) == 1
        assert mm.texts[0].startswith("🎧 Dit debat was al afgelopen toen ik om ")
        assert "bezig" not in mm.texts[0]

    async def test_a_short_hiccup_is_simply_caught_up(self, db_session, monkeypatch):
        """Two minutes away is not a gap worth a message."""
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        await _sessie(db_session)
        pause = START.replace(hour=10, minute=20, second=0)
        await _run(db_session, mm, feed, START - timedelta(minutes=10), pause)

        back = pause + timedelta(minutes=2)
        await _run(db_session, mm, feed, back, back + timedelta(seconds=30), step=10)

        assert not any(t.startswith("⏭️") for t in mm.texts)

    async def test_a_debate_is_not_polled_long_before_it_starts(
        self, db_session, monkeypatch
    ):
        """Found the evening before, it would be asked for its events
        thousands of times before anyone speaks."""
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        sessie = await _sessie(db_session)

        early = START - timedelta(hours=3)
        await _run(db_session, mm, feed, early, early + timedelta(minutes=12), step=60)
        assert sessie.tijdlijn_status == TIJDLIJN_GEKOPPELD
        assert "debate" not in feed.calls

        soon = START - timedelta(minutes=14)
        await _run(db_session, mm, feed, soon, soon + timedelta(seconds=20), step=10)
        assert "debate" in feed.calls

    async def test_a_message_that_does_not_arrive_shows_in_the_result(
        self, db_session, monkeypatch
    ):
        """Otherwise the heartbeat says "ok" over a timeline that is stuck."""
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        await _sessie(db_session)
        await _run(db_session, mm, feed, START - timedelta(minutes=10), START)

        mm.fail_posts = 1
        feed.now = START + timedelta(minutes=2)
        result = await DebatTijdlijnService(db_session, mm).tick(feed.now)

        assert result.fouten == 1

    async def test_a_restart_posts_nothing_twice(self, db_session, monkeypatch):
        """Everything done is in the database, not in the process."""
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        await _sessie(db_session)
        until = START + timedelta(minutes=20)
        await _run(db_session, mm, feed, START - timedelta(minutes=10), until)
        before = list(mm.texts)

        # The same moments again, as a process that knows nothing.
        await _run(db_session, mm, feed, until - timedelta(minutes=5), until)

        assert mm.texts == before

    async def test_a_message_that_fails_is_tried_again_in_order(
        self, db_session, monkeypatch
    ):
        """Skipping it would put the debate in the channel with a hole in
        it; posting the later ones first would shuffle it."""
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        await _sessie(db_session)
        await _run(db_session, mm, feed, START - timedelta(minutes=10), START)
        reference = FakeMattermost()

        mm.fail_posts = 3
        await _run(db_session, mm, feed, START, START + timedelta(minutes=20))

        # The same run without failures, on its own sessie.
        feed2 = Feed(monkeypatch)
        await _sessie(db_session)
        await _run(
            db_session,
            reference,
            feed2,
            START - timedelta(minutes=10),
            START + timedelta(minutes=20),
        )
        strip = [t.split(" · ")[0] for t in mm.turns]
        assert strip == [t.split(" · ")[0] for t in reference.turns][: len(strip)]
        assert len(strip) >= len(reference.turns) - 1

    async def test_joining_a_running_debate_does_not_flood_the_channel(
        self, db_session, monkeypatch
    ):
        """A hundred messages at once is not a timeline."""
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        sessie = await _sessie(db_session)

        join = START.replace(hour=11, minute=0, second=0)
        await _run(db_session, mm, feed, join, join + timedelta(seconds=40), step=10)

        assert mm.texts[0].startswith("🎧 Ik luister mee vanaf 11:00.")
        assert "de 65 spreekbeurten daarvoor" in mm.texts[0]
        assert f"[Debat Direct]({dd.debate_url(FULL)})" in mm.texts[0]
        # Only what happened in the last minutes follows.
        assert 1 <= len(mm.turns) <= 6
        assert all("[10:5" in t or "[11:0" in t for t in mm.turns)
        # The history is remembered, so it is never posted later.
        assert await _rows(db_session, sessie) > 90

    async def test_the_history_is_announced_once(self, db_session, monkeypatch):
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        await _sessie(db_session)

        join = START.replace(hour=11, minute=0, second=0)
        await _run(db_session, mm, feed, join, join + timedelta(minutes=5), step=10)

        assert sum(1 for t in mm.texts if t.startswith("🎧")) == 1

    async def test_no_names_does_not_stop_the_timeline(self, db_session, monkeypatch):
        feed = Feed(monkeypatch)

        async def no_sprekers(client, day, base_url=None):
            raise dd.DebatDirectError("down")

        monkeypatch.setattr(dd, "fetch_sprekers", no_sprekers)
        mm = FakeMattermost()
        await _sessie(db_session)

        await _run(
            db_session,
            mm,
            feed,
            START - timedelta(minutes=10),
            START + timedelta(minutes=5),
        )

        assert any(t.startswith("**Onbekende spreker** · [10:01](") for t in mm.texts)

    async def test_one_debate_breaking_does_not_stop_another(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        kapot = await _sessie(db_session, channel_id=f"kap{uuid.uuid4().hex}"[:26])
        goed = await _sessie(db_session)
        real = DebatTijdlijnService._advance

        async def advance(self, sessie_id, client, now, result):
            if sessie_id == kapot.id:
                raise RuntimeError("boom")
            await real(self, sessie_id, client, now, result)

        monkeypatch.setattr(DebatTijdlijnService, "_advance", advance)

        # The test session joins an outer transaction, so a real rollback
        # would undo the fixtures as well. In production it only undoes
        # the work on the debate that broke.
        async def no_rollback():
            return None

        monkeypatch.setattr(db_session, "rollback", no_rollback)
        feed.now = START - timedelta(hours=1)
        result = await DebatTijdlijnService(db_session, mm).tick(feed.now)

        assert result.fouten == 1
        assert result.gekoppeld == 1
        await db_session.refresh(goed)
        assert goed.tijdlijn_status == TIJDLIJN_GEKOPPELD


@pytest.mark.asyncio
class TestEnding:
    async def test_over_some_hours_after_the_last_part_ended(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        sessie = await _sessie(db_session)
        await _run(
            db_session,
            mm,
            feed,
            START - timedelta(minutes=10),
            FULL.ended_at + timedelta(minutes=2),
            step=60,
        )
        assert sessie.tijdlijn_status == TIJDLIJN_LOOPT
        posts = len(mm.posts)

        await _run(
            db_session,
            mm,
            feed,
            FULL.ended_at + timedelta(hours=3, minutes=1),
            FULL.ended_at + timedelta(hours=3, minutes=12),
            step=300,
        )

        assert sessie.tijdlijn_status == TIJDLIJN_AFGELOPEN
        assert len(mm.posts) == posts

    async def test_an_ended_part_is_not_fetched_any_more(self, db_session, monkeypatch):
        """Every poll downloads the whole debate; there is no ETag."""
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        await _sessie(db_session)
        await _run(
            db_session,
            mm,
            feed,
            START - timedelta(minutes=10),
            FULL.ended_at + timedelta(minutes=2),
            step=60,
        )
        feed.calls.clear()

        await _run(
            db_session,
            mm,
            feed,
            FULL.ended_at + timedelta(minutes=3),
            FULL.ended_at + timedelta(minutes=20),
            step=60,
        )

        assert "debate" not in feed.calls

    async def test_a_second_part_after_a_break_is_picked_up(
        self, db_session, monkeypatch
    ):
        """Debat Direct cuts a plenary debate in two around a break. The
        second part only exists once it starts."""
        shift = timedelta(hours=4)
        raw = dict(FIXTURE["debate"])
        second = dd.parse_debate({**raw, "id": "deel-2"})
        second = dd.DdDebat(
            **{
                **second.__dict__,
                "starts_at": second.starts_at + shift,
                "started_at": second.started_at + shift,
                "ended_at": second.ended_at + shift,
                "events": tuple(
                    dd.DdEvent(e.start + shift, e.type, e.object_id, e.raw_start)
                    for e in second.events[:12]
                ),
            }
        )
        feed = Feed(monkeypatch, parts=[FULL, second])
        mm = FakeMattermost()
        sessie = await _sessie(db_session)

        await _run(
            db_session,
            mm,
            feed,
            START - timedelta(minutes=10),
            second.started_at + timedelta(minutes=8),
            step=60,
        )

        assert sessie.debat_direct_ids == [FULL.id, "deel-2"]
        # Not closed after the first part ended, although that was hours ago.
        assert sessie.tijdlijn_status == TIJDLIJN_LOOPT
        assert sum(1 for t in mm.texts if "Het debat is begonnen" in t) == 2

    async def test_the_same_subject_hours_after_the_end_is_not_a_second_part(
        self, db_session, monkeypatch
    ):
        """An item of the agenda that comes back later that day under the
        same name is somebody else's: it starts longer after the end than
        any break lasts."""
        shift = FULL.ended_at - FULL.started_at + dd.MAX_BREAK + timedelta(minutes=5)
        later = dd.DdDebat(
            **{
                **FULL.__dict__,
                "id": "later",
                "starts_at": FULL.starts_at + shift,
                "started_at": FULL.started_at + shift,
                "ended_at": FULL.ended_at + shift,
                "events": tuple(
                    dd.DdEvent(e.start + shift, e.type, e.object_id, e.raw_start)
                    for e in FULL.events[:12]
                ),
            }
        )
        feed = Feed(monkeypatch, parts=[FULL, later])
        mm = FakeMattermost()
        sessie = await _sessie(db_session)

        await _run(
            db_session,
            mm,
            feed,
            START - timedelta(minutes=10),
            later.started_at + timedelta(minutes=8),
            step=60,
        )

        assert sessie.debat_direct_ids == [FULL.id]
        assert sum(1 for t in mm.texts if "Het debat is begonnen" in t) == 1

    async def test_a_second_part_is_found_when_the_debate_started_late(
        self, db_session, monkeypatch
    ):
        """Once started, Debat Direct replaces the planned start by the
        real one. A debate that began two hours late no longer matches the
        planned time of its activiteit, and its second part was never
        found."""
        late = timedelta(hours=2)
        first = dd.DdDebat(
            **{
                **FULL.__dict__,
                "starts_at": FULL.starts_at + late,
                "started_at": FULL.started_at + late,
                "ended_at": FULL.ended_at + late,
                "events": tuple(
                    dd.DdEvent(e.start + late, e.type, e.object_id, e.raw_start)
                    for e in FULL.events
                ),
            }
        )
        second_start = first.ended_at + timedelta(hours=1)
        second = dd.DdDebat(
            **{
                **FULL.__dict__,
                "id": "deel-2",
                "starts_at": second_start,
                "started_at": second_start,
                "ended_at": None,
                "events": (),
            }
        )
        # Linked before the start, on the planned time; the delay only
        # shows once the debate is running.
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        sessie = await _sessie(db_session)
        feed.now = START - timedelta(minutes=30)
        await DebatTijdlijnService(db_session, mm).tick(feed.now)
        assert sessie.debat_direct_ids == [FULL.id]

        feed.parts = [first, second]
        at = second_start + timedelta(minutes=1)
        await _run(db_session, mm, feed, at, at + timedelta(minutes=6), step=120)

        assert sessie.debat_direct_ids == [FULL.id, "deel-2"]


@pytest.mark.asyncio
async def test_the_worker_loop_is_registered():
    """A loop that is written but not started posts nothing."""
    import inspect

    from bouwmeester import worker

    assert "_debat_tijdlijn_loop(settings)" in inspect.getsource(worker.main)


@pytest.mark.asyncio
async def test_the_tick_reads_real_shapes_through_httpx(db_session, monkeypatch):
    """One run where Debat Direct is an HTTP server, not a replaced function."""

    async def activiteit(activiteit_id, client, base_url=None):
        return _activiteit(activiteit_id)

    monkeypatch.setattr(mod, "fetch_activiteit", activiteit)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/agenda/" in path:
            return httpx.Response(200, json={"debates": [FIXTURE["debate"]]})
        if "/debates/" in path:
            return httpx.Response(200, json=FIXTURE["debate"])
        if "/actors/" in path:
            return httpx.Response(200, json=FIXTURE["actors"])
        return httpx.Response(404)

    real_client = httpx.AsyncClient

    def client(**kwargs):
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(mod.httpx, "AsyncClient", client)
    mm = FakeMattermost()
    sessie = await _sessie(db_session)

    now = START + timedelta(minutes=2)
    await DebatTijdlijnService(db_session, mm).tick(now)
    await DebatTijdlijnService(db_session, mm).tick(now + timedelta(seconds=10))

    assert sessie.tijdlijn_status == TIJDLIJN_LOOPT
    # The whole recorded debate is "in the past" relative to this clock
    # except its first two minutes, which are recent enough to be posted.
    assert any(t.startswith("**Kamerlid D (SP)**") for t in mm.texts)


@pytest.mark.asyncio
class TestStoppedInTheMeantime:
    """Someone presses "stoppen met volgen" while a round is under way. The
    round read the sessie before that, and must not write its status back."""

    async def _stopped_behind_its_back(self, db_session, status):
        sessie = await _sessie(db_session, tijdlijn_status=status)
        # As another session would: the object in this one does not know.
        await db_session.execute(
            sa_update(DebatSessie)
            .where(DebatSessie.id == sessie.id)
            .values(tijdlijn_status=TIJDLIJN_AFGELOPEN)
            .execution_options(synchronize_session=False)
        )
        assert sessie.tijdlijn_status == status
        return sessie

    @pytest.mark.parametrize(
        "read_as,step",
        [(None, TIJDLIJN_GEKOPPELD), (TIJDLIJN_GEKOPPELD, TIJDLIJN_LOOPT)],
    )
    async def test_a_step_is_not_taken_over_a_stop(self, db_session, read_as, step):
        sessie = await self._stopped_behind_its_back(db_session, read_as)
        service = DebatTijdlijnService(db_session, FakeMattermost())

        assert await service._move_status(sessie, read_as, step) is False

        assert sessie.tijdlijn_status == TIJDLIJN_AFGELOPEN
        await db_session.flush()
        kept = await db_session.scalar(
            select(DebatSessie.tijdlijn_status).where(DebatSessie.id == sessie.id)
        )
        assert kept == TIJDLIJN_AFGELOPEN

    @pytest.mark.parametrize(
        "read_as,step",
        [(None, TIJDLIJN_GEKOPPELD), (TIJDLIJN_GEKOPPELD, TIJDLIJN_LOOPT)],
    )
    async def test_a_step_is_taken_when_nothing_changed(
        self, db_session, read_as, step
    ):
        sessie = await _sessie(db_session, tijdlijn_status=read_as)
        service = DebatTijdlijnService(db_session, FakeMattermost())

        assert await service._move_status(sessie, read_as, step) is True

        assert sessie.tijdlijn_status == step
        kept = await db_session.scalar(
            select(DebatSessie.tijdlijn_status).where(DebatSessie.id == sessie.id)
        )
        assert kept == step

    async def test_a_debate_stopped_while_it_is_being_found_is_not_followed(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch)
        mm = FakeMattermost()
        sessie = await _sessie(db_session)
        # The stop lands after the round read the sessie.
        await db_session.execute(
            sa_update(DebatSessie)
            .where(DebatSessie.id == sessie.id)
            .values(tijdlijn_status=TIJDLIJN_AFGELOPEN)
            .execution_options(synchronize_session=False)
        )
        service = DebatTijdlijnService(db_session, mm)
        result = TickResult()

        async with httpx.AsyncClient() as client:
            feed.now = START
            await service._advance(sessie.id, client, START.astimezone(UTC), result)
        await db_session.flush()

        kept = await db_session.scalar(
            select(DebatSessie.tijdlijn_status).where(DebatSessie.id == sessie.id)
        )
        assert kept == TIJDLIJN_AFGELOPEN
        assert result.gekoppeld == 0
