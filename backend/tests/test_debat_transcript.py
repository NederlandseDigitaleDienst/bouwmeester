"""Tests for the text of a debate under the messages of the timeline.

First the parts that only compute: which line belongs to which turn, and
where a long turn is cut. Then the whole thing against a real database, with
the made-up debates and the fake Mattermost of the timeline tests, and
subtitles that come in half a minute behind like the real ones.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select, update

from bouwmeester.core.config import get_settings
from bouwmeester.models.debat_markering import DebatMarkering
from bouwmeester.models.debat_sessie import DebatOndertitel, DebatSpreekbeurt
from bouwmeester.services import debat_subtitles as subs
from bouwmeester.services import debat_tijdlijn_service as tijdlijn
from bouwmeester.services.debat_subtitles import Cue
from bouwmeester.services.debat_tijdlijn_service import (
    DebatTijdlijnService,
    TickResult,
    heading_as,
)
from bouwmeester.services.debat_transcript import (
    MESSAGE_LIMIT,
    append_text,
    fit_messages,
    last_sentences,
    place_cues,
    render,
    render_closing,
    split_text,
    text_key,
)
from bouwmeester.services.debat_transcript_service import (
    MESSAGE_MAX,
    DebatTranscript,
    derive_text,
    load_turns,
)
from bouwmeester.services.mattermost_service import PostNotFoundError
from tests.test_debat_tijdlijn import (
    START,
    FakeMattermost,
    Feed,
    _debat,
    _run,
    _sessie,
)

STREAM = "https://stream.example/live/zaal/index.m3u8"
PLAYLIST = "https://stream.example/live/zaal/subtitles/nl_Live.m3u8"
MASTER = f'#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,LANGUAGE="nl",URI="{PLAYLIST}"\n'
OFFSET = timedelta(seconds=2)
# The subtitle track lists a file about this long after its moment.
BEHIND = timedelta(seconds=35)


def _cue(seconds: float, text: str, length: float = 2.0) -> Cue:
    start = START + timedelta(seconds=seconds)
    return Cue(start, start + timedelta(seconds=length), text)


def assign_cues(cues, turns, *offset) -> dict:
    """The text per turn, as `place_cues` puts the lines."""
    texts: dict = {}
    for key, cue in place_cues(cues, turns, *offset):
        texts.setdefault(key, []).append(cue.text)
    return {key: " ".join(parts) for key, parts in texts.items()}


class TestPlaceCues:
    def test_a_line_belongs_to_the_turn_it_was_spoken_in(self):
        turns = [("a", START), ("b", START + timedelta(seconds=60))]
        cues = [_cue(5, "Een."), _cue(30, "Twee."), _cue(61, "Drie.")]

        assert assign_cues(cues, turns) == {"a": "Een. Twee.", "b": "Drie."}

    def test_the_sound_is_later_than_the_event(self):
        turns = [("a", START), ("b", START + timedelta(seconds=60))]
        cues = [_cue(61, "Nog van a."), _cue(62, "Van b.")]

        assert assign_cues(cues, turns, OFFSET) == {"a": "Nog van a.", "b": "Van b."}

    def test_a_line_before_the_first_turn_is_nobodys(self):
        assert assign_cues([_cue(-5, "Vooraf.")], [("a", START)]) == {}

    def test_a_turn_without_lines_is_not_in_the_answer(self):
        turns = [("a", START), ("b", START + timedelta(seconds=10))]

        assert assign_cues([_cue(20, "Alleen b.")], turns) == {"b": "Alleen b."}

    def test_lines_are_put_in_order_of_time(self):
        cues = [_cue(9, "Later."), _cue(3, "Eerder.")]

        assert assign_cues(cues, [("a", START)]) == {"a": "Eerder. Later."}

    def test_no_turns_no_text(self):
        assert assign_cues([_cue(3, "Iets.")], []) == {}


class TestAppendText:
    def test_more_text_goes_behind_with_a_space(self):
        assert append_text("Een.", "Twee.") == "Een. Twee."

    def test_the_first_text(self):
        assert append_text(None, " Een. ") == "Een."

    def test_nothing_new_changes_nothing(self):
        assert append_text("Een.", "  ") == "Een."

    def test_what_is_kept_is_never_changed(self):
        """Where a turn is cut and whether a message is up to date both
        lean on the text only getting longer."""
        assert append_text("dat we toewerken naar...", "een steunpunt.") == (
            "dat we toewerken naar... een steunpunt."
        )


class TestSplitText:
    def test_a_short_text_is_one_piece(self):
        assert split_text("Een korte zin.") == ["Een korte zin."]

    def test_no_text_is_one_empty_piece(self):
        assert split_text("") == [""]

    def test_a_cut_falls_after_the_last_sentence_that_fits(self):
        text = "Eerste zin hier. Tweede zin hier. Derde zin hier."

        assert split_text(text, limit=40, minimum=5) == [
            "Eerste zin hier. Tweede zin hier.",
            "Derde zin hier.",
        ]

    def test_a_question_mark_ends_a_sentence_too(self):
        text = "Is dat zo? Dat lijkt mij niet het geval te zijn, voorzitter."

        assert split_text(text, limit=30, minimum=5)[0] == "Is dat zo?"

    def test_not_before_the_minimum(self):
        text = "Kort. " + "woord " * 20

        pieces = split_text(text, limit=60, minimum=30)

        assert len(pieces[0]) > 30
        assert not pieces[0].endswith("Kort.")

    def test_without_a_sentence_end_the_cut_is_at_a_space(self):
        pieces = split_text("woord " * 30, limit=50, minimum=10)

        assert all(len(p) <= 50 for p in pieces)
        assert " ".join(pieces) == ("woord " * 30).strip()

    def test_one_endless_word_is_cut_anyway(self):
        pieces = split_text("x" * 100, limit=40, minimum=10)

        assert [len(p) for p in pieces] == [40, 40, 20]

    def test_nothing_is_lost_and_every_piece_fits(self):
        text = " ".join(f"Dit is zin nummer {i} van de spreker." for i in range(300))

        pieces = split_text(text)

        assert " ".join(pieces) == text
        assert all(len(p) <= MESSAGE_LIMIT for p in pieces)
        assert len(pieces) > 3

    def test_a_text_that_grows_keeps_its_cuts(self):
        """Otherwise a message that was full is rewritten, and what was
        read there a minute ago is suddenly somewhere else."""
        sentences = [f"Dit is zin nummer {i} van de spreker." for i in range(400)]
        earlier: list[str] = []
        for count in range(40, 400, 7):
            pieces = split_text(" ".join(sentences[:count]))
            assert pieces[: len(earlier) - 1] == earlier[:-1]
            earlier = pieces

    def test_a_sentence_ending_exactly_at_the_limit_fits(self):
        text = "a" * 39 + ". " + "b" * 20

        assert split_text(text, limit=40, minimum=5) == ["a" * 39 + ".", "b" * 20]

    def test_the_sentence_that_ends_at_the_limit_wins_from_an_earlier_one(self):
        text = "Eerste. " + "a" * 31 + ". " + "b" * 20

        assert split_text(text, limit=40, minimum=5) == [
            "Eerste. " + "a" * 31 + ".",
            "b" * 20,
        ]


class TestFitMessages:
    def test_enough_room_changes_nothing(self):
        assert fit_messages(["a", "b"], 2) == ["a", "b"]

    def test_the_last_message_takes_what_does_not_fit(self):
        assert fit_messages(["a", "b", "c", "d"], 2) == ["a", "b c d"]

    def test_one_message_takes_everything(self):
        assert fit_messages(["a", "b"], 1) == ["a b"]


class TestRender:
    def test_the_text_comes_under_the_first_line(self):
        assert render("**Kamerlid A (X)** · 10:42", "Voorzitter.") == (
            "**Kamerlid A (X)** · 10:42\nVoorzitter."
        )

    def test_without_text_it_is_the_first_line_alone(self):
        assert render("**Kamerlid A (X)** · 10:42", "") == "**Kamerlid A (X)** · 10:42"

    def test_a_next_message_says_it_continues(self):
        assert render("**Kamerlid A (X)** · 10:42", "En verder.", vervolg=True) == (
            "**Kamerlid A (X)** · 10:42 · vervolg\nEn verder."
        )

    def test_dots_of_a_line_that_runs_on_are_not_shown(self):
        message = render("kop", "dat we toewerken naar... een steunpunt.")

        assert message == "kop\ndat we toewerken naar een steunpunt."

    def test_dots_before_a_new_sentence_are_shown(self):
        assert render("kop", "En toen... Voorzitter.") == "kop\nEn toen... Voorzitter."

    def test_what_was_said_cannot_mention_or_format(self):
        message = render("kop", "@all kijk naar *dit* en _dat_")

        assert "@all" not in message.replace("\\@all", "")
        assert "*dit*" not in message


class TestClosing:
    def test_a_short_text_is_shown_whole(self):
        assert last_sentences("Ik schors tot twee uur.") == "Ik schors tot twee uur."

    def test_only_the_last_sentences_that_fit(self):
        text = (
            "Dank aan de leden. " * 30 + "Ik schors de vergadering tot kwart over twee."
        )

        assert last_sentences(text, limit=80) == (
            "Dank aan de leden. Ik schors de vergadering tot kwart over twee."
        )

    def test_a_scrap_after_a_long_sentence_is_not_all_that_is_shown(self):
        text = "woord " * 100 + "tot kwart over twee. Ja."

        shown = last_sentences(text, limit=80)

        assert shown.endswith("tot kwart over twee. Ja.")
        assert shown.startswith("… woord")

    def test_one_sentence_that_is_too_long_is_cut_at_a_word(self):
        text = "woord " * 100 + "einde"

        shown = last_sentences(text, limit=30)

        assert shown.startswith("… woord")
        assert shown.endswith("woord einde")
        assert len(shown) <= 31

    def test_under_the_first_line_and_said_by_whom(self):
        assert render_closing("⏸️ **Geschorst** · 13:46", "Ik schors tot @all uur.") == (
            "⏸️ **Geschorst** · 13:46\nVoorzitter: Ik schors tot @⁠all uur."
        )

    def test_only_the_end_of_a_long_text_goes_under_it(self):
        text = "Dank aan de leden. " * 30 + "Ik schors tot twee uur."

        message = render_closing("kop", text)

        assert message.endswith("Ik schors tot twee uur.")
        assert len(message) < 320

    def test_without_words_it_is_the_first_line(self):
        assert (
            render_closing("⏸️ **Geschorst** · 13:46", " ") == "⏸️ **Geschorst** · 13:46"
        )


class Subtitles:
    """The subtitle track at a moment in time."""

    def __init__(self, monkeypatch, feed: Feed, cues: list[Cue]) -> None:
        self.feed = feed
        self.cues = cues
        self.master = MASTER
        self.error = False
        # The moment the stream stopped: nothing is listed after it.
        self.stops_at = None
        self.reads: list[tuple] = []
        self.masters = 0

        async def fetch_text(client, url):
            self.masters += 1
            if self.error:
                raise subs.SubtitleError("down")
            return self.master

        async def fetch_since(client, url, after, *, max_segments, since=None):
            self.reads.append((url, after, since))
            if self.error:
                raise subs.SubtitleError("down")
            upto = self.feed.now - BEHIND
            if self.stops_at is not None:
                upto = min(upto, self.stops_at)
            begin = after or since or upto
            if upto <= begin:
                return [], after
            return [c for c in self.cues if begin <= c.start < upto], upto

        monkeypatch.setattr(subs, "fetch_text", fetch_text)
        monkeypatch.setattr(subs, "fetch_since", fetch_since)


class Mattermost(FakeMattermost):
    """Also remembers what every message says now, and every rewrite."""

    def __init__(self) -> None:
        super().__init__()
        self.messages: dict[str, str] = {}
        self.order: list[str] = []
        self.updates: list[tuple[str, str]] = []
        self.fail_updates = 0
        self.broken: set[str] = set()
        self.deleted: set[str] = set()
        self.removed: list[str] = []
        self.fail_deletes = 0

    async def send_channel_message(self, channel_id, text, props=None, root_id=None):
        post_id = await super().send_channel_message(channel_id, text, props, root_id)
        if post_id:
            self.messages[post_id] = text
            self.order.append(post_id)
        return post_id

    async def update_post(self, post_id, message, props=None) -> bool:
        if post_id in self.broken or post_id in self.deleted:
            return False
        if self.fail_updates > 0:
            self.fail_updates -= 1
            return False
        self.updates.append((post_id, message))
        self.messages[post_id] = message
        return True

    async def delete_post(self, post_id) -> bool:
        if post_id in self.deleted:
            return False
        if self.fail_deletes > 0:
            self.fail_deletes -= 1
            return False
        self.removed.append(post_id)
        self.order.remove(post_id)
        del self.messages[post_id]
        return True

    async def get_post(self, post_id) -> dict | None:
        if post_id in self.deleted:
            raise PostNotFoundError(post_id)
        return {"id": post_id, "message": self.messages[post_id]}

    @property
    def channel(self) -> list[str]:
        return [self.messages[post_id] for post_id in self.order]


def _stream(debat):
    return dataclasses.replace(debat, stream_url=STREAM, stream_offset=OFFSET)


def _minutes(minutes: float) -> timedelta:
    return timedelta(minutes=minutes)


async def _play(db_session, mm, feed, until: float, start: float = -10, step: int = 10):
    await _run(
        db_session, mm, feed, START + _minutes(start), START + _minutes(until), step
    )


@pytest.mark.asyncio
class TestTranscript:
    async def test_what_is_said_comes_under_who_says_it(self, db_session, monkeypatch):
        feed = Feed(monkeypatch, parts=[_stream(_debat(("speaker", 1, "a")))])
        Subtitles(
            monkeypatch,
            feed,
            [_cue(65, "Voorzitter, dank."), _cue(70, "Ik heb een vraag.")],
        )
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 3)

        assert mm.channel[-1].startswith("**Onbekende spreker** · [")
        assert mm.channel[-1].endswith("\nVoorzitter, dank. Ik heb een vraag.")
        assert len(mm.channel) == 2

    async def test_the_message_grows_while_someone_speaks(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch, parts=[_stream(_debat(("speaker", 1, "a")))])
        Subtitles(
            monkeypatch, feed, [_cue(65, "Een."), _cue(95, "Twee."), _cue(125, "Drie.")]
        )
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 4)

        bodies = [text.split("\n", 1)[1] for _, text in mm.updates]
        assert bodies == ["Een.", "Een. Twee.", "Een. Twee. Drie."]
        assert len({post_id for post_id, _ in mm.updates}) == 1

    async def test_an_interruption_gets_its_own_words(self, db_session, monkeypatch):
        debat = _debat(
            ("speaker", 1, "a"), ("interrupter", 2, "b"), ("speaker", 3, "a")
        )
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        cues = [
            _cue(70, "Mijn betoog."),
            _cue(125, "Mag ik iets vragen?"),
            _cue(185, "Zeker."),
        ]
        Subtitles(monkeypatch, feed, cues)
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 5)

        assert [m.split("\n", 1)[1] for m in mm.channel[1:]] == [
            "Mijn betoog.",
            "Mag ik iets vragen?",
            "Zeker.",
        ]
        assert mm.channel[2].startswith("↳ ")

    async def test_the_offset_of_the_stream_decides_at_the_edge(
        self, db_session, monkeypatch
    ):
        """A line one second after the event is still the speaker before:
        the sound runs two seconds behind the events."""
        debat = _debat(("speaker", 1, "a"), ("speaker", 2, "b"))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Subtitles(
            monkeypatch, feed, [_cue(121, "Slotzin van a."), _cue(123, "Begin van b.")]
        )
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 4)

        assert mm.channel[1].endswith("\nSlotzin van a.")
        assert mm.channel[2].endswith("\nBegin van b.")

    async def test_the_chairman_saying_a_word_has_a_message_of_its_own(
        self, db_session, monkeypatch
    ):
        """What the chair says is part of the debate. The speaker who
        carries on after it gets a next message, below the chairman's."""
        debat = _debat(("speaker", 1, "a"), ("chairman", 2, "v"), ("speaker", 3, "a"))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        cues = [
            _cue(70, "Eerste deel."),
            _cue(125, "Gaat u verder."),
            _cue(185, "Tweede deel."),
        ]
        Subtitles(monkeypatch, feed, cues)
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 5)

        assert len(mm.channel) == 4
        assert mm.channel[1].endswith("\nEerste deel.")
        assert mm.channel[2].startswith("🔨 **Voorzitter** · [")
        assert mm.channel[2].endswith("\nGaat u verder.")
        assert mm.channel[3].endswith("\nTweede deel.")

    async def test_a_long_turn_continues_in_a_next_message(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch, parts=[_stream(_debat(("speaker", 1, "a")))])
        cues = [
            _cue(65 + 4 * i, f"Dit is zin nummer {i} van het betoog.")
            for i in range(120)
        ]
        Subtitles(monkeypatch, feed, cues)
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 11)

        turn = mm.channel[1:]
        assert len(turn) == 3
        assert all(len(m.split("\n", 1)[1]) <= MESSAGE_LIMIT for m in turn)
        assert " · vervolg\n" not in turn[0]
        assert all(" · vervolg\n" in m for m in turn[1:])
        said = " ".join(m.split("\n", 1)[1] for m in turn)
        assert said == " ".join(c.text for c in cues)

    async def test_a_full_message_is_not_written_again(self, db_session, monkeypatch):
        feed = Feed(monkeypatch, parts=[_stream(_debat(("speaker", 1, "a")))])
        cues = [
            _cue(65 + 4 * i, f"Dit is zin nummer {i} van het betoog.")
            for i in range(120)
        ]
        Subtitles(monkeypatch, feed, cues)
        mm = Mattermost()
        await _sessie(db_session)
        await _play(db_session, mm, feed, 6)
        assert len(mm.channel) == 3
        first = mm.order[1]
        mm.updates.clear()

        await _play(db_session, mm, feed, 11, start=6.2)

        assert mm.updates
        assert first not in {post_id for post_id, _ in mm.updates}

    async def test_late_words_do_not_start_a_message_below_the_next_speaker(
        self, db_session, monkeypatch
    ):
        """The text runs half a minute behind. When it overflows after
        someone else already has a message, it stays where it is."""
        debat = _debat(("speaker", 1, "a"), ("speaker", 3, "b"))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        cues = [
            _cue(63 + 2 * i, f"Dit is zin nummer {i} van het betoog.")
            for i in range(58)
        ]
        Subtitles(monkeypatch, feed, cues)
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 5)

        assert len(mm.channel) == 3
        assert mm.channel[2].startswith("**Onbekende spreker**")
        assert " · vervolg" not in mm.channel[2]
        assert mm.channel[1].endswith("nummer 57 van het betoog.")
        assert len(mm.channel[1]) > MESSAGE_LIMIT

    async def test_a_rewrite_that_fails_is_done_the_next_round(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch, parts=[_stream(_debat(("speaker", 1, "a")))])
        Subtitles(monkeypatch, feed, [_cue(65, "Een."), _cue(70, "Twee.")])
        mm = Mattermost()
        await _sessie(db_session)
        await _play(db_session, mm, feed, 1.5)

        mm.fail_updates = 3
        feed.now = START + _minutes(2)
        result = await DebatTijdlijnService(db_session, mm).tick(feed.now)
        assert result.fouten == 1
        assert "\n" not in mm.channel[1]

        mm.fail_updates = 0
        await _play(db_session, mm, feed, 2.5, start=2.2)

        assert mm.channel[1].endswith("\nEen. Twee.")

    async def test_a_restart_reads_nothing_twice(self, db_session, monkeypatch):
        feed = Feed(monkeypatch, parts=[_stream(_debat(("speaker", 1, "a")))])
        track = Subtitles(monkeypatch, feed, [_cue(65, "Een."), _cue(95, "Twee.")])
        mm = Mattermost()
        await _sessie(db_session)
        await _play(db_session, mm, feed, 3)
        before = len(mm.updates)

        await _play(db_session, mm, feed, 4, start=3.2)

        assert mm.channel[1].endswith("\nEen. Twee.")
        assert len(mm.updates) == before
        assert track.masters == 1

    async def test_the_first_reading_goes_back_to_the_start_of_the_debate(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch, parts=[_stream(_debat(("speaker", 1, "a")))])
        track = Subtitles(monkeypatch, feed, [])
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 1)

        url, after, since = track.reads[0]
        assert (url, after, since) == (PLAYLIST, None, START)

    async def test_joining_late_reads_back_ten_minutes_at_most(
        self, db_session, monkeypatch
    ):
        feed = Feed(
            monkeypatch,
            parts=[_stream(_debat(("speaker", 1, "a"), ("speaker", 40, "b")))],
        )
        track = Subtitles(monkeypatch, feed, [])
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 41, start=40.5)

        assert track.reads[0][2] == track.feed.now - timedelta(minutes=10) or (
            START + _minutes(30) < track.reads[0][2] < START + _minutes(31.5)
        )

    async def test_a_stream_without_subtitles_is_asked_once(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch, parts=[_stream(_debat(("speaker", 1, "a")))])
        track = Subtitles(monkeypatch, feed, [_cue(65, "Een.")])
        track.master = "#EXTM3U\n"
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 3)

        assert track.masters == 1
        assert track.reads == []
        assert mm.updates == []
        assert len(mm.channel) == 2

    async def test_a_track_that_was_not_there_yet_is_found_later(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch, parts=[_stream(_debat(("speaker", 1, "a")))])
        track = Subtitles(monkeypatch, feed, [_cue(65, "Een."), _cue(400, "Twee.")])
        track.master = "#EXTM3U\n"
        mm = Mattermost()
        await _sessie(db_session)
        await _play(db_session, mm, feed, 3)

        track.master = MASTER
        await _play(db_session, mm, feed, 8, start=3.2, step=20)

        assert track.masters == 2
        assert mm.channel[1].endswith("\nEen. Twee.")

    async def test_subtitles_that_cannot_be_read_do_not_stop_the_timeline(
        self, db_session, monkeypatch
    ):
        debat = _debat(("speaker", 1, "a"), ("speaker", 2, "b"))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        track = Subtitles(monkeypatch, feed, [_cue(65, "Een.")])
        track.error = True
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 3)
        feed.now = START + _minutes(3.2)
        result = await DebatTijdlijnService(db_session, mm).tick(feed.now)

        assert len(mm.channel) == 3
        assert result.fouten == 0

        track.error = False
        await _play(db_session, mm, feed, 4, start=3.4)
        assert mm.channel[1].endswith("\nEen.")

    async def test_a_debate_without_a_stream_has_just_its_timeline(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch, parts=[_debat(("speaker", 1, "a"))])
        track = Subtitles(monkeypatch, feed, [_cue(65, "Een.")])
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 3)

        assert track.masters == 0
        assert mm.updates == []

    async def test_switched_off_leaves_the_timeline_as_it_was(
        self, db_session, monkeypatch
    ):
        monkeypatch.setattr(get_settings(), "DEBAT_TRANSCRIPT_ENABLED", False)
        feed = Feed(monkeypatch, parts=[_stream(_debat(("speaker", 1, "a")))])
        track = Subtitles(monkeypatch, feed, [_cue(65, "Een.")])
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 3)

        assert track.masters == 0
        assert mm.updates == []

    async def test_reading_stops_a_while_after_the_end(self, db_session, monkeypatch):
        debat = _debat(("speaker", 1, "a"), ("debate_end", 3, ""))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        track = Subtitles(
            monkeypatch, feed, [_cue(65, "Een."), _cue(175, "Laatste woorden.")]
        )
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 6)
        reads = len(track.reads)
        await _play(db_session, mm, feed, 9, start=6.2)

        assert mm.channel[1].endswith("\nEen. Laatste woorden.")
        assert len(track.reads) == reads

    async def test_reading_stops_when_the_stream_stopped_with_the_debate(
        self, db_session, monkeypatch
    ):
        """The last file ends just before the end, so where the reading
        stands never gets past it. The clock ends it."""
        debat = _debat(("speaker", 1, "a"), ("debate_end", 3, ""))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        track = Subtitles(
            monkeypatch, feed, [_cue(65, "Een."), _cue(170, "Laatste woorden.")]
        )
        track.stops_at = START + timedelta(seconds=178)
        mm = Mattermost()
        await _sessie(db_session)

        # Up to and including the last moment it is still read.
        await _play(db_session, mm, feed, 6)
        reads = len(track.reads)
        await _play(db_session, mm, feed, 6, start=6)
        assert len(track.reads) == reads + 1
        await _play(db_session, mm, feed, 9, start=6.1)

        assert mm.channel[1].endswith("\nEen. Laatste woorden.")
        assert len(track.reads) == reads + 1

    async def test_a_part_that_debat_direct_says_has_ended_is_not_read_for_long(
        self, db_session, monkeypatch
    ):
        """Also without the event of the end: the feed itself says so."""
        debat = _stream(_debat(("speaker", 1, "a")))
        ended = dataclasses.replace(debat, ended_at=START + _minutes(3))
        feed = Feed(monkeypatch, parts=[ended])
        track = Subtitles(monkeypatch, feed, [_cue(70, "Van dit debat.")])
        track.stops_at = START + timedelta(seconds=178)
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 6.5)
        reads = len(track.reads)
        await _play(db_session, mm, feed, 9, start=6.6)

        assert reads > 10
        assert len(track.reads) == reads

    async def test_a_turn_the_timeline_missed_does_not_end_up_with_someone_else(
        self, db_session, monkeypatch
    ):
        """Rows without a message, from a stretch that was missed, can have
        text too. It belongs to nobody's message: not to the speaker before
        the stretch, and what that speaker says after it is a new turn."""
        mm = Mattermost()
        sessie = await _sessie(db_session)
        post_id = await mm.send_channel_message(sessie.channel_id, "kop a")
        rows = [
            ("speaker", 1, "a", post_id, "kop a", "Van a."),
            ("speaker", 5, "b", None, None, "Van b."),
            ("speaker", 9, "a", None, None, "Weer a."),
        ]
        for kind, minute, who, post, kop, tekst in rows:
            db_session.add(
                DebatSpreekbeurt(
                    sessie_id=sessie.id,
                    debat_direct_id="d1",
                    event_type=kind,
                    event_start=START + _minutes(minute),
                    object_id=who,
                    post_id=post,
                    kop=kop,
                    tekst=tekst,
                )
            )
        await db_session.flush()

        await DebatTranscript(db_session, mm).write(
            sessie.id, sessie.channel_id, "d1", TickResult()
        )

        assert mm.channel == ["kop a\nVan a."]

    async def test_a_deleted_message_does_not_hold_up_the_others(
        self, db_session, monkeypatch
    ):
        debat = _debat(("speaker", 1, "a"), ("speaker", 2, "b"), ("speaker", 3, "c"))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Subtitles(
            monkeypatch,
            feed,
            [_cue(70, "Van a."), _cue(130, "Van b."), _cue(190, "Van c.")],
        )
        mm = Mattermost()
        await _sessie(db_session)
        await _play(db_session, mm, feed, 1.5)
        mm.deleted.add(mm.order[1])

        await _play(db_session, mm, feed, 5, start=1.6)
        feed.now = START + _minutes(5.1)
        result = await DebatTijdlijnService(db_session, mm).tick(feed.now)

        assert mm.channel[2].endswith("\nVan b.")
        assert mm.channel[3].endswith("\nVan c.")
        assert result.fouten == 0

    async def test_a_message_that_keeps_failing_does_not_hold_up_the_others(
        self, db_session, monkeypatch
    ):
        debat = _debat(("speaker", 1, "a"), ("speaker", 2, "b"))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Subtitles(monkeypatch, feed, [_cue(70, "Van a."), _cue(130, "Van b.")])
        mm = Mattermost()
        await _sessie(db_session)
        await _play(db_session, mm, feed, 1.5)
        mm.broken.add(mm.order[1])

        await _play(db_session, mm, feed, 4, start=1.6)

        assert mm.channel[2].endswith("\nVan b.")
        mm.broken.clear()
        await _play(db_session, mm, feed, 5.1, start=4.1)
        assert mm.channel[1].endswith("\nVan a.")

    async def test_late_words_do_not_start_a_message_below_a_suspension(
        self, db_session, monkeypatch
    ):
        debat = _debat(("speaker", 1, "a"), ("suspended", 3, ""))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        cues = [
            _cue(63 + 2 * i, f"Dit is zin nummer {i} van het betoog.")
            for i in range(58)
        ]
        Subtitles(monkeypatch, feed, cues)
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 5)

        assert len(mm.channel) == 3
        assert mm.channel[2].startswith("⏸️")
        assert mm.channel[1].endswith("nummer 57 van het betoog.")

    async def test_while_the_timeline_cannot_post_the_text_waits(
        self, db_session, monkeypatch
    ):
        """Otherwise what the next speaker says is filed under the one
        before: the turn it belongs to is not known yet."""
        debat = _debat(("speaker", 1, "a"), ("speaker", 2, "b"))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Subtitles(monkeypatch, feed, [_cue(70, "Van a."), _cue(125, "Van b.")])
        mm = Mattermost()
        await _sessie(db_session)
        await _play(db_session, mm, feed, 1.9)

        mm.fail_posts = 10_000
        await _play(db_session, mm, feed, 3.5, start=2)
        mm.fail_posts = 0
        await _play(db_session, mm, feed, 5.1, start=3.6)

        assert mm.channel[1].endswith("\nVan a.")
        assert mm.channel[2].endswith("\nVan b.")

    async def test_a_part_that_has_ended_on_debat_direct_is_not_read_on(
        self, db_session, monkeypatch
    ):
        """The address is the room's. Without this the next debate in that
        room would be written under the last speaker of this one."""
        debat = _stream(_debat(("speaker", 1, "a")))
        ended = dataclasses.replace(debat, ended_at=START + _minutes(3))
        feed = Feed(monkeypatch, parts=[ended])
        Subtitles(
            monkeypatch,
            feed,
            [_cue(70, "Van dit debat."), _cue(300, "Van het volgende.")],
        )
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 8)

        assert mm.channel[1].endswith("\nVan dit debat.")

    async def test_a_part_in_which_nothing_happens_for_an_hour_is_not_read_on(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch, parts=[_stream(_debat(("speaker", 1, "a")))])
        track = Subtitles(
            monkeypatch,
            feed,
            [_cue(70, "Van dit debat."), _cue(3720, "Een uur later.")],
        )
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 66, step=30)
        reads = len(track.reads)
        await _play(db_session, mm, feed, 68, start=66.5, step=30)

        assert mm.channel[1].endswith("\nVan dit debat.")
        assert len(track.reads) == reads

    async def test_a_next_message_that_fails_is_not_made_twice(
        self, db_session, monkeypatch
    ):
        feed = Feed(monkeypatch, parts=[_stream(_debat(("speaker", 1, "a")))])
        cues = [
            _cue(65 + 4 * i, f"Dit is zin nummer {i} van het betoog.")
            for i in range(120)
        ]
        Subtitles(monkeypatch, feed, cues)
        mm = Mattermost()
        await _sessie(db_session)
        await _play(db_session, mm, feed, 3)
        assert len(mm.channel) == 2

        # The first follow-up fails once, then the rewrites fail for a while.
        mm.fail_posts = 1
        await _play(db_session, mm, feed, 5, start=3.1)
        mm.fail_updates = 4
        await _play(db_session, mm, feed, 11, start=5.1)

        turn = mm.channel[1:]
        assert len(turn) == 3
        said = " ".join(m.split("\n", 1)[1] for m in turn)
        assert said == " ".join(c.text for c in cues)

    async def test_a_message_is_never_longer_than_mattermost_takes(self, db_session):
        mm = Mattermost()
        post_id = await mm.send_channel_message("c", "kop")

        assert await DebatTranscript(db_session, mm)._rewrite(post_id, "x" * 20_000)

        assert len(mm.messages[post_id]) == MESSAGE_MAX

    async def test_a_suspension_says_what_the_chairman_said(
        self, db_session, monkeypatch
    ):
        """Otherwise it comes out of nowhere, and nobody knows until when."""
        debat = _debat(("speaker", 1, "a"), ("chairman", 2, "v"), ("suspended", 3, ""))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        _chair_unposted(monkeypatch)
        cues = [
            _cue(70, "Mijn betoog."),
            _cue(125, "Dank u wel."),
            _cue(170, "Ik schors de vergadering tot kwart over twee."),
            _cue(200, "Geroezemoes in de zaal."),
        ]
        Subtitles(monkeypatch, feed, cues)
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 5)

        assert mm.channel[1].endswith("\nMijn betoog.")
        assert mm.channel[2].startswith("⏸️ **Geschorst** · ")
        assert mm.channel[2].endswith(
            "\nVoorzitter: Dank u wel. Ik schors de vergadering tot kwart over twee."
        )
        assert len(mm.channel) == 3

    async def test_the_end_says_what_the_chairman_said(self, db_session, monkeypatch):
        debat = _debat(("speaker", 1, "a"), ("chairman", 2, "v"), ("debate_end", 3, ""))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        _chair_unposted(monkeypatch)
        Subtitles(monkeypatch, feed, [_cue(125, "Ik sluit de vergadering.")])
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 5)

        assert mm.channel[2].startswith("⏹️ **Het debat is afgelopen** · ")
        assert mm.channel[2].endswith("\nVoorzitter: Ik sluit de vergadering.")

    async def test_the_end_keeps_the_count_of_what_hangs_under_it(
        self, db_session, monkeypatch
    ):
        """A toezegging from the chairman's list hangs under the message of
        the end. Written again from the chairman's words alone, the message
        would lose its count."""
        debat = _debat(("speaker", 1, "a"), ("chairman", 2, "v"), ("debate_end", 3, ""))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        _chair_unposted(monkeypatch)
        Subtitles(monkeypatch, feed, [_cue(125, "Ik sluit de vergadering.")])
        mm = Mattermost()
        sessie = await _sessie(db_session)
        await _play(db_session, mm, feed, 5)
        end = (
            await db_session.execute(
                select(DebatSpreekbeurt).where(
                    DebatSpreekbeurt.event_type == "debate_end"
                )
            )
        ).scalar_one()
        db_session.add(
            DebatMarkering(
                sessie_id=sessie.id,
                beurt_sleutel=f"slotlijst:beurt:{end.id}",
                volgnummer=1,
                soort="toezegging",
                channel_id="chan",
                beurt_post_id=end.post_id,
                thread_post_id="reply000000000000000000001",
                spreker="de voorzitter",
                gericht_aan="",
                citaat="De minister zegt toe de Kamer een brief te sturen.",
                samenvatting="Stuurt een brief.",
                moment=end.event_start,
            )
        )
        # As if a line came in late: the message is written again.
        end.tekst_geplaatst = 0
        await db_session.flush()

        await _play(db_session, mm, feed, 6, start=5.2)

        assert mm.messages[end.post_id].endswith(
            "\nVoorzitter: Ik sluit de vergadering.\n\n---\n"
            "🤝 1 toezegging · 🔴 **open**"
        )

    async def test_what_a_member_said_last_is_not_the_chairmans(
        self, db_session, monkeypatch
    ):
        """The chairman spoke, then a member, then the suspension. The
        chairman's words from before the member do not announce it."""
        debat = _debat(("chairman", 1, "v"), ("speaker", 2, "a"), ("suspended", 3, ""))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        _chair_unposted(monkeypatch)
        Subtitles(
            monkeypatch, feed, [_cue(65, "Het woord is aan u."), _cue(125, "Dank.")]
        )
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 5)

        assert "Voorzitter:" not in mm.channel[2]
        assert "\n" not in mm.channel[2]

    async def test_only_what_the_chairman_said_last_announces_it(
        self, db_session, monkeypatch
    ):
        debat = _debat(("chairman", 1, "v"), ("chairman", 2, "v"), ("suspended", 3, ""))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        _chair_unposted(monkeypatch)
        Subtitles(
            monkeypatch, feed, [_cue(65, "Een mededeling."), _cue(125, "Ik schors.")]
        )
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 5)

        assert mm.channel[1].endswith("\nVoorzitter: Een mededeling. Ik schors.")

    async def test_the_end_after_a_suspension_does_not_repeat_the_announcement(
        self, db_session, monkeypatch
    ):
        debat = _debat(
            ("chairman", 1, "v"), ("suspended", 2, ""), ("debate_end", 4, "")
        )
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        _chair_unposted(monkeypatch)
        Subtitles(monkeypatch, feed, [_cue(65, "Ik schors tot twee uur.")])
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 6)

        assert mm.channel[1].endswith("\nVoorzitter: Ik schors tot twee uur.")
        assert "Voorzitter:" not in mm.channel[2]

    async def test_what_is_said_after_a_resumption_comes_under_it(
        self, db_session, monkeypatch
    ):
        debat = _debat(
            ("chairman", 1, "v"),
            ("suspended", 2, ""),
            ("continued", 3, ""),
            ("suspended", 4, ""),
        )
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        _chair_unposted(monkeypatch)
        cues = [_cue(65, "Ik schors tot twee uur."), _cue(190, "Ik schors opnieuw.")]
        Subtitles(monkeypatch, feed, cues)
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 6)

        assert mm.channel[1].endswith("\nVoorzitter: Ik schors tot twee uur.")
        assert mm.channel[2].startswith("▶️ **Hervat**")
        assert mm.channel[2].endswith("\nIk schors opnieuw.")
        assert "Voorzitter:" not in mm.channel[3]

    async def test_the_words_under_a_suspension_are_written_once(
        self, db_session, monkeypatch
    ):
        debat = _debat(("chairman", 1, "v"), ("suspended", 2, ""))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        _chair_unposted(monkeypatch)
        Subtitles(monkeypatch, feed, [_cue(65, "Ik schors.")])
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 6)

        assert len(mm.updates) == 1

    async def test_words_that_cannot_be_put_under_a_suspension_count_as_an_error(
        self, db_session, monkeypatch
    ):
        debat = _debat(("chairman", 1, "v"), ("suspended", 2, ""))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        _chair_unposted(monkeypatch)
        Subtitles(monkeypatch, feed, [_cue(115, "Ik schors.")])
        mm = Mattermost()
        await _sessie(db_session)
        await _play(db_session, mm, feed, 2.3)
        assert "\n" not in mm.channel[1]
        mm.broken.add(mm.order[1])

        feed.now = START + _minutes(2.7)
        result = await DebatTijdlijnService(db_session, mm).tick(feed.now)
        assert result.fouten == 1

        mm.broken.clear()
        await _play(db_session, mm, feed, 3.2, start=2.8)
        assert mm.channel[1].endswith("\nVoorzitter: Ik schors.")

    async def test_a_resumption_gets_no_words(self, db_session, monkeypatch):
        debat = _debat(("chairman", 1, "v"), ("continued", 2, ""))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Subtitles(monkeypatch, feed, [_cue(65, "Ik heropen de vergadering.")])
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 4)

        assert all("Voorzitter:" not in m for m in mm.channel)

    async def test_a_meeting_with_only_a_start_and_an_end_is_not_empty(
        self, db_session, monkeypatch
    ):
        """A procedurevergadering: Debat Direct has its start and its end and
        nothing in between, while the chairman goes through the letters for
        forty minutes. That goes under the start."""
        debat = _debat(("debate_end", 4, ""))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        cues = [
            _cue(20, "Ik open de procedurevergadering."),
            _cue(90, "Punt drie, de brief over de cloud."),
            _cue(200, "Dan zijn we aan het einde van het openbare deel."),
        ]
        Subtitles(monkeypatch, feed, cues)
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 6)

        assert mm.channel[0].startswith("▶️ **Het debat is begonnen**")
        assert mm.channel[0].endswith(
            "\nIk open de procedurevergadering. Punt drie, de brief over de "
            "cloud. Dan zijn we aan het einde van het openbare deel."
        )
        assert mm.channel[1].startswith("⏹️ **Het debat is afgelopen**")
        assert "Voorzitter:" not in mm.channel[1]

    async def test_a_suspension_does_not_repeat_what_is_under_the_chair(
        self, db_session, monkeypatch
    ):
        debat = _debat(("chairman", 1, "v"), ("suspended", 2, ""))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Subtitles(monkeypatch, feed, [_cue(65, "Ik schors tot twee uur.")])
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 4)

        assert mm.channel[1].startswith("🔨 **Voorzitter** · [")
        assert mm.channel[1].endswith("\nIk schors tot twee uur.")
        assert mm.channel[2].startswith("⏸️ **Geschorst** · ")
        assert "\n" not in mm.channel[2]

    async def test_the_chair_opening_comes_under_the_start(
        self, db_session, monkeypatch
    ):
        debat = _debat(("speaker", 1, "a"))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Subtitles(
            monkeypatch,
            feed,
            [_cue(20, "Welkom bij dit debat."), _cue(70, "Mijn betoog.")],
        )
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 3)

        assert mm.channel[0].endswith("\nWelkom bij dit debat.")
        assert mm.channel[1].endswith("\nMijn betoog.")

    async def test_what_was_said_cannot_mention_anyone(self, db_session, monkeypatch):
        feed = Feed(monkeypatch, parts=[_stream(_debat(("speaker", 1, "a")))])
        Subtitles(monkeypatch, feed, [_cue(65, "Schrijf naar @channel en @all.")])
        mm = Mattermost()
        await _sessie(db_session)

        await _play(db_session, mm, feed, 3)

        assert "@⁠channel" in mm.channel[1]
        assert "@⁠all" in mm.channel[1]


class TestTextKey:
    def test_the_same_text_has_the_same_name(self):
        assert text_key("Een. Twee.") == text_key("Een. Twee.")

    def test_another_text_of_the_same_length_has_another(self):
        assert text_key("Een. Twee.") != text_key("Een. Drie.")

    def test_it_fits_the_column(self):
        assert len(text_key("Een. Twee." * 1000)) == 16


async def _member_turns(db_session, sessie) -> list:
    turns = await load_turns(db_session, sessie.id, sessie.debat_direct_ids[0])
    return [turn for turn in turns if turn.is_member]


def _chair_unposted(monkeypatch) -> None:
    """The chairman's events get no message of their own.

    As after a stretch the timeline missed: what was said from the chair
    then has no message to go under, and only its last words are shown,
    under a suspension or the end.
    """
    real = tijdlijn.format_event

    def without_chair(event, debat, sprekers):  # type: ignore[no-untyped-def]
        return None if event.type == "chairman" else real(event, debat, sprekers)

    monkeypatch.setattr(tijdlijn, "format_event", without_chair)


async def _row(db_session, sessie, who: str) -> DebatSpreekbeurt:
    return (
        await db_session.execute(
            select(DebatSpreekbeurt)
            .where(
                DebatSpreekbeurt.sessie_id == sessie.id,
                DebatSpreekbeurt.object_id == who,
            )
            # As it is in the database now, not as it was read before.
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _move(db_session, sessie, texts: list[str], to: DebatSpreekbeurt) -> None:
    """What the voices do: these lines belong to another turn after all."""
    moved = (
        await db_session.execute(
            update(DebatOndertitel)
            .where(
                DebatOndertitel.sessie_id == sessie.id,
                DebatOndertitel.tekst.in_(texts),
            )
            .values(spreekbeurt_id=to.id)
            .returning(DebatOndertitel.id)
        )
    ).all()
    assert len(moved) == len(texts)
    rows = (
        await db_session.execute(
            select(DebatSpreekbeurt.id).where(DebatSpreekbeurt.sessie_id == sessie.id)
        )
    ).scalars()
    await derive_text(db_session, set(rows))


def _sentence(i: int) -> str:
    return f"Dit is zin nummer {i} van het betoog."


@pytest.mark.asyncio
class TestLines:
    """Every line is a row, and the text of a turn is its lines in order."""

    async def test_every_line_is_kept_with_its_turn(self, db_session, monkeypatch):
        debat = _debat(("speaker", 1, "a"), ("speaker", 2, "b"))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Subtitles(
            monkeypatch,
            feed,
            [_cue(65, "Een.", 2.5), _cue(70, "Twee."), _cue(125, "Drie.")],
        )
        sessie = await _sessie(db_session)

        await _play(db_session, Mattermost(), feed, 4)

        a, b = await _row(db_session, sessie, "a"), await _row(db_session, sessie, "b")
        lines = (
            await db_session.execute(
                select(DebatOndertitel)
                .where(DebatOndertitel.sessie_id == sessie.id)
                .order_by(DebatOndertitel.start)
            )
        ).scalars()
        assert [
            (
                line.tekst,
                line.spreekbeurt_id,
                (line.start - START).total_seconds(),
                (line.einde - START).total_seconds(),
                line.debat_direct_id,
                line.toewijzing,
                line.stem_klaar,
            )
            for line in lines
        ] == [
            ("Een.", a.id, 65.0, 67.5, debat.id, "tijd", False),
            ("Twee.", a.id, 70.0, 72.0, debat.id, "tijd", False),
            ("Drie.", b.id, 125.0, 127.0, debat.id, "tijd", False),
        ]
        assert (a.tekst, b.tekst) == ("Een. Twee.", "Drie.")

    async def test_a_line_read_twice_is_kept_once(self, db_session, monkeypatch):
        """Two workers read the same file during a deploy."""
        feed = Feed(monkeypatch, parts=[_stream(_debat(("speaker", 1, "a")))])
        Subtitles(monkeypatch, feed, [_cue(65, "Een."), _cue(70, "Twee.")])
        mm = Mattermost()
        sessie = await _sessie(db_session)
        await _play(db_session, mm, feed, 3)
        entry = dict(sessie.ondertitels[feed.parts[0].id])
        del entry["positie"]
        sessie.ondertitels = {feed.parts[0].id: entry}
        await db_session.flush()
        mm.updates.clear()

        await _play(db_session, mm, feed, 4, start=3.2)

        count = await db_session.scalar(
            select(func.count()).where(DebatOndertitel.sessie_id == sessie.id)
        )
        assert count == 2
        assert (await _row(db_session, sessie, "a")).tekst == "Een. Twee."
        assert mm.updates == []

    async def test_the_text_of_a_turn_follows_from_its_lines_in_order_of_time(
        self, db_session, monkeypatch
    ):
        debat = _debat(("speaker", 1, "a"), ("speaker", 2, "b"))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Subtitles(monkeypatch, feed, [_cue(65, "Een."), _cue(125, "Drie.")])
        sessie = await _sessie(db_session)
        await _play(db_session, Mattermost(), feed, 4)
        a = await _row(db_session, sessie, "a")
        # A line that comes in late and out of order.
        db_session.add(
            DebatOndertitel(
                sessie_id=sessie.id,
                debat_direct_id=debat.id,
                start=START + timedelta(seconds=62),
                einde=START + timedelta(seconds=64),
                tekst="Nul.",
                spreekbeurt_id=a.id,
            )
        )
        await db_session.flush()

        await derive_text(db_session, {a.id})

        assert (await _row(db_session, sessie, "a")).tekst == "Nul. Een."
        assert (await _row(db_session, sessie, "b")).tekst == "Drie."

    async def test_a_turn_that_lost_its_last_line_has_no_text(
        self, db_session, monkeypatch
    ):
        debat = _debat(("speaker", 1, "a"), ("speaker", 2, "b"))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Subtitles(monkeypatch, feed, [_cue(65, "Een."), _cue(125, "Drie.")])
        mm = Mattermost()
        sessie = await _sessie(db_session)
        await _play(db_session, mm, feed, 4)

        await _move(db_session, sessie, ["Drie."], await _row(db_session, sessie, "a"))
        await _play(db_session, mm, feed, 4.5, start=4.2)

        assert (await _row(db_session, sessie, "b")).tekst == ""
        assert mm.channel[1].endswith("\nEen. Drie.")
        assert "\n" not in mm.channel[2]

    async def test_nothing_to_derive_is_no_statement(self, db_session):
        await derive_text(db_session, set())

    async def test_a_turn_from_before_lines_were_kept_keeps_its_text(
        self, db_session, monkeypatch
    ):
        """A turn can have text and no lines. Its text is only made anew
        when a line is added to it or taken from it, never because another
        turn changed."""
        debat = _debat(("speaker", 1, "a"), ("speaker", 2, "b"))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Subtitles(monkeypatch, feed, [_cue(65, "Een."), _cue(125, "Drie.")])
        mm = Mattermost()
        sessie = await _sessie(db_session)
        await _play(db_session, mm, feed, 2)
        a = await _row(db_session, sessie, "a")
        assert a.tekst == "Een."
        await db_session.execute(
            delete(DebatOndertitel).where(DebatOndertitel.spreekbeurt_id == a.id)
        )
        await db_session.flush()

        await _play(db_session, mm, feed, 4, start=2.2)

        assert (await _row(db_session, sessie, "b")).tekst == "Drie."
        assert (await _row(db_session, sessie, "a")).tekst == "Een."
        assert mm.channel[1].endswith("\nEen.")


@pytest.mark.asyncio
class TestTextThatChanges:
    """A line can move to another turn. Then the text of a turn changes
    otherwise than by growing, and what is in the channel is not how it
    begins any more."""

    async def _long_turn(self, db_session, monkeypatch, count: int = 120):
        debat = _debat(("speaker", 1, "a"), ("speaker", 10, "b"))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        cues = [_cue(65 + 4 * i, _sentence(i)) for i in range(count)]
        cues.append(_cue(605, "Van b."))
        Subtitles(monkeypatch, feed, cues)
        mm = Mattermost()
        sessie = await _sessie(db_session)
        await _play(db_session, mm, feed, 11.5)
        assert len(mm.channel) == 5
        mm.updates.clear()
        return feed, mm, sessie

    async def test_every_message_of_the_turn_is_written_again(
        self, db_session, monkeypatch
    ):
        feed, mm, sessie = await self._long_turn(db_session, monkeypatch)
        first, second, third, other = mm.order[1:]

        await _move(
            db_session, sessie, [_sentence(0)], await _row(db_session, sessie, "b")
        )
        await _play(db_session, mm, feed, 12, start=11.6)

        assert [post_id for post_id, _ in mm.updates] == [first, second, third, other]
        said = " ".join(m.split("\n", 1)[1] for m in mm.channel[1:4])
        assert said == " ".join(_sentence(i) for i in range(1, 120))
        assert mm.channel[4].endswith(f"\n{_sentence(0)} Van b.")
        assert all(len(m.split("\n", 1)[1]) <= MESSAGE_LIMIT for m in mm.channel[1:4])

    async def test_lines_that_come_to_a_turn_with_someone_below_it_stay_in_its_messages(
        self, db_session, monkeypatch
    ):
        """A turn of three messages that gets more text after the next
        speaker began: a fourth message would land below that speaker."""
        feed, mm, sessie = await self._long_turn(db_session, monkeypatch)
        first, second, third, other = mm.order[1:]
        a = await _row(db_session, sessie, "a")
        for i in range(120, 180):
            db_session.add(
                DebatOndertitel(
                    sessie_id=sessie.id,
                    debat_direct_id=feed.parts[0].id,
                    start=START + timedelta(seconds=65 + 4 * 119, milliseconds=i),
                    einde=START + timedelta(seconds=65 + 4 * 119 + 1),
                    tekst=_sentence(i),
                    spreekbeurt_id=a.id,
                )
            )
        await db_session.flush()
        await derive_text(db_session, {a.id})

        await _play(db_session, mm, feed, 12, start=11.6)

        assert mm.order[1:] == [first, second, third, other]
        assert mm.messages[third].endswith(_sentence(179))
        assert len(mm.messages[third]) > MESSAGE_LIMIT
        assert first not in {post_id for post_id, _ in mm.updates}

    async def test_and_then_only_once(self, db_session, monkeypatch):
        feed, mm, sessie = await self._long_turn(db_session, monkeypatch)
        await _move(
            db_session, sessie, [_sentence(0)], await _row(db_session, sessie, "b")
        )
        await _play(db_session, mm, feed, 12, start=11.6)
        mm.updates.clear()

        await _play(db_session, mm, feed, 13, start=12.2)

        assert mm.updates == []

    async def test_a_text_of_the_same_length_that_says_something_else(
        self, db_session, monkeypatch
    ):
        """The length alone does not show it."""
        feed, mm, sessie = await self._long_turn(db_session, monkeypatch)
        first = mm.order[1]
        await db_session.execute(
            update(DebatOndertitel)
            .where(DebatOndertitel.tekst == _sentence(3))
            .values(tekst=_sentence(4))
        )
        a = await _row(db_session, sessie, "a")
        before = len(a.tekst)
        await derive_text(db_session, {a.id})
        assert len((await _row(db_session, sessie, "a")).tekst) == before

        await _play(db_session, mm, feed, 12, start=11.6)

        assert first in {post_id for post_id, _ in mm.updates}
        assert _sentence(3) not in mm.messages[first]

    async def test_a_next_message_that_is_not_needed_any_more_is_taken_away(
        self, db_session, monkeypatch
    ):
        feed, mm, sessie = await self._long_turn(db_session, monkeypatch)
        first, second, third, other = mm.order[1:]

        gone = [_sentence(i) for i in range(60, 120)]
        await _move(db_session, sessie, gone, await _row(db_session, sessie, "b"))
        await _play(db_session, mm, feed, 12, start=11.6)

        assert mm.removed == [third]
        assert mm.order[1:3] == [first, second]
        a = await _row(db_session, sessie, "a")
        assert a.vervolg_post_ids == [second]
        said = " ".join(mm.messages[p].split("\n", 1)[1] for p in (first, second))
        assert said == " ".join(_sentence(i) for i in range(60))
        assert a.tekst_geplaatst == len(a.tekst)

    async def test_a_turn_that_lost_everything_keeps_only_its_first_line(
        self, db_session, monkeypatch
    ):
        feed, mm, sessie = await self._long_turn(db_session, monkeypatch)
        first, second, third, other = mm.order[1:]

        everything = [_sentence(i) for i in range(120)]
        await _move(db_session, sessie, everything, await _row(db_session, sessie, "b"))
        await _play(db_session, mm, feed, 12, start=11.6)

        assert mm.removed == [third, second]
        assert "\n" not in mm.messages[first]
        assert (await _row(db_session, sessie, "a")).vervolg_post_ids == []
        # The turn that got them is the last thing in the channel, so it
        # can continue below itself.
        assert len(mm.order) > 3

    async def test_a_message_that_cannot_be_taken_away_is_tried_again(
        self, db_session, monkeypatch
    ):
        feed, mm, sessie = await self._long_turn(db_session, monkeypatch)
        third = mm.order[3]
        gone = [_sentence(i) for i in range(60, 120)]
        await _move(db_session, sessie, gone, await _row(db_session, sessie, "b"))

        mm.fail_deletes = 1
        feed.now = START + _minutes(11.6)
        result = await DebatTijdlijnService(db_session, mm).tick(feed.now)

        assert result.fouten == 1
        assert third in mm.order
        a = await _row(db_session, sessie, "a")
        assert third in a.vervolg_post_ids
        assert a.tekst_geplaatst != len(a.tekst)

        await _play(db_session, mm, feed, 12, start=11.8)

        assert mm.removed == [third]
        a = await _row(db_session, sessie, "a")
        assert third not in a.vervolg_post_ids
        assert a.tekst_geplaatst == len(a.tekst)

    async def test_a_message_someone_deleted_already_counts_as_taken_away(
        self, db_session, monkeypatch
    ):
        feed, mm, sessie = await self._long_turn(db_session, monkeypatch)
        third = mm.order[3]
        mm.deleted.add(third)
        gone = [_sentence(i) for i in range(60, 120)]
        await _move(db_session, sessie, gone, await _row(db_session, sessie, "b"))

        feed.now = START + _minutes(11.6)
        result = await DebatTijdlijnService(db_session, mm).tick(feed.now)

        assert result.fouten == 0
        assert third not in (await _row(db_session, sessie, "a")).vervolg_post_ids

    async def test_a_turn_that_only_grew_keeps_its_full_messages(
        self, db_session, monkeypatch
    ):
        """Also for a message written before the digest was kept: it is
        taken at its length, and not written again from the start."""
        debat = _debat(("speaker", 1, "a"))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        Subtitles(
            monkeypatch, feed, [_cue(65 + 4 * i, _sentence(i)) for i in range(120)]
        )
        mm = Mattermost()
        sessie = await _sessie(db_session)
        await _play(db_session, mm, feed, 6)
        first = mm.order[1]
        a = await _row(db_session, sessie, "a")
        assert a.tekst_geplaatst_hash == text_key(a.tekst)
        a.tekst_geplaatst_hash = None
        await db_session.flush()
        mm.updates.clear()

        await _play(db_session, mm, feed, 11, start=6.2)

        assert mm.updates
        assert first not in {post_id for post_id, _ in mm.updates}
        a = await _row(db_session, sessie, "a")
        assert a.tekst_geplaatst_hash == text_key(a.tekst)

    async def test_a_text_that_became_shorter_is_written_again_also_without_a_digest(
        self, db_session, monkeypatch
    ):
        feed, mm, sessie = await self._long_turn(db_session, monkeypatch)
        first = mm.order[1]
        a = await _row(db_session, sessie, "a")
        a.tekst_geplaatst_hash = None
        await db_session.flush()

        await _move(
            db_session, sessie, [_sentence(119)], await _row(db_session, sessie, "b")
        )
        await _play(db_session, mm, feed, 12, start=11.6)

        assert first in {post_id for post_id, _ in mm.updates}

    async def test_the_words_under_a_suspension_follow_a_line_that_moved(
        self, db_session, monkeypatch
    ):
        debat = _debat(("speaker", 1, "a"), ("chairman", 2, "v"), ("suspended", 3, ""))
        feed = Feed(monkeypatch, parts=[_stream(debat)])
        _chair_unposted(monkeypatch)
        Subtitles(
            monkeypatch,
            feed,
            [_cue(65, "Ik rond af."), _cue(118, "Dank u."), _cue(125, "Ik schors.")],
        )
        mm = Mattermost()
        sessie = await _sessie(db_session)
        await _play(db_session, mm, feed, 5)
        assert mm.channel[2].endswith("\nVoorzitter: Ik schors.")

        # "Dank u." was the chairman's, not the speaker's.
        await _move(
            db_session, sessie, ["Dank u."], await _row(db_session, sessie, "v")
        )
        await _play(db_session, mm, feed, 5.5, start=5.2)

        assert mm.channel[1].endswith("\nIk rond af.")
        assert mm.channel[2].endswith("\nVoorzitter: Dank u. Ik schors.")


def _seconds(seconds: float) -> float:
    """For `_debat`, which counts in minutes."""
    return seconds / 60


async def _speaking_rows(db_session) -> list[DebatSpreekbeurt]:
    rows = await db_session.execute(
        select(DebatSpreekbeurt)
        .where(DebatSpreekbeurt.event_type.in_(("speaker", "interrupter")))
        .order_by(
            DebatSpreekbeurt.event_start,
            DebatSpreekbeurt.event_type,
            DebatSpreekbeurt.object_id,
        )
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


def _turns_in(mm: Mattermost) -> list[str]:
    return [text for text in mm.channel if text.startswith(("**", "↳"))]


@pytest.mark.asyncio
class TestTwoEventsOneTurn:
    """Debat Direct enters someone who gets the floor as interrupter and
    seconds later as speaker. That is one turn, in the channel and for
    whoever reads the turns."""

    async def _follow(self, db_session, monkeypatch, events, cues=(), until=4.0):
        feed = Feed(monkeypatch, parts=[_stream(_debat(*events))])
        Subtitles(monkeypatch, feed, list(cues))
        mm = Mattermost()
        sessie = await _sessie(db_session)
        await _play(db_session, mm, feed, until)
        return mm, sessie, feed

    async def test_a_heading_that_cannot_be_rewritten_does_not_stop_the_text(
        self, db_session, monkeypatch
    ):
        """The message exists but Mattermost refuses the rewrite, round
        after round. That is an error, and it must not keep the text of
        everyone else in the debate from being read."""
        events = [
            ("interrupter", _seconds(60), "a"),
            ("speaker", _seconds(75), "a"),
            ("speaker", _seconds(120), "b"),
        ]
        cues = [_cue(64, "Van a."), _cue(125, "Van b.")]
        feed = Feed(monkeypatch, parts=[_stream(_debat(*events))])
        Subtitles(monkeypatch, feed, cues)
        mm = Mattermost()
        await _sessie(db_session)
        # The interruption is in the channel; its speaker event is not
        # there yet.
        await _play(db_session, mm, feed, 1.2)
        mm.broken.add(mm.order[1])

        await _play(db_session, mm, feed, 4.0, start=1.25)

        assert mm.channel[2].endswith("\nVan b.")

    # 3 seconds apart both events are in one reading of the feed; 15 seconds
    # apart the first is in the channel before the second exists.
    @pytest.mark.parametrize("apart", [3, 15])
    async def test_interrupter_and_then_speaker_is_one_message_of_a_speaker(
        self, db_session, monkeypatch, apart
    ):
        events = [
            ("interrupter", _seconds(60), "a"),
            ("speaker", _seconds(60 + apart), "a"),
        ]
        cues = [_cue(64, "Eerste zin."), _cue(80, "Tweede zin.")]

        mm, sessie, _ = await self._follow(db_session, monkeypatch, events, cues)

        assert len(mm.channel) == 2
        message = mm.channel[1]
        assert message.startswith("**Onbekende spreker** · [")
        assert "interruptie" not in message
        # What was said under either event is under the one message.
        assert message.endswith("\nEerste zin. Tweede zin.")
        # It was posted as what the feed said at that moment.
        assert mm.posts[1][1].startswith("↳ **Onbekende spreker**")
        assert mm.posts[1][1].endswith(" · interruptie")

        first, second = await _speaking_rows(db_session)
        # The rows are still the events that were seen.
        assert (first.event_type, second.event_type) == ("interrupter", "speaker")
        assert first.event_start == START + timedelta(seconds=60)
        assert second.event_start == START + timedelta(seconds=60 + apart)
        assert (first.object_id, second.object_id) == ("a", "a")
        assert first.post_id and second.post_id is None
        assert first.beurt_soort == "speaker"
        assert first.kop == message.split("\n")[0]
        assert (first.tekst, second.tekst) == ("Eerste zin.", "Tweede zin.")

        (turn,) = await _member_turns(db_session, sessie)
        assert turn.key == ("speaker", "a")
        assert turn.row_id == first.id
        assert turn.text == "Eerste zin. Tweede zin."

    async def test_the_link_stays_the_one_to_where_the_turn_began(
        self, db_session, monkeypatch
    ):
        events = [("interrupter", _seconds(60), "a"), ("speaker", _seconds(75), "a")]
        mm, _, _ = await self._follow(db_session, monkeypatch, events)

        assert mm.channel[1] == heading_as(mm.posts[1][1], "speaker")
        assert "?event=interrupter" in mm.channel[1]

    async def test_after_a_restart_the_turn_is_still_a_speakers(
        self, db_session, monkeypatch
    ):
        """A fresh service every ten seconds, as after a restart, against
        one service that sees everything in one reading: the same channel
        and the same rows. Carrying on as speaker two minutes later is the
        same turn, which only holds when the kind of the turn is read back;
        an interruption after that is a new one."""
        events = [
            ("interrupter", _seconds(60), "a"),
            ("speaker", _seconds(63), "a"),
            ("speaker", _seconds(120), "a"),
            ("interrupter", _seconds(200), "a"),
        ]

        mm, sessie, feed = await self._follow(db_session, monkeypatch, events)
        stepwise = [
            (r.event_type, r.event_start, bool(r.post_id), r.beurt_soort, r.kop)
            for r in await _speaking_rows(db_session)
        ]
        turns = _turns_in(mm)
        assert len(turns) == 2
        assert turns[0].startswith("**Onbekende spreker**")
        assert turns[1].startswith("↳ **Onbekende spreker**")

        # And once more from nothing, everything in one tick.
        await db_session.execute(
            delete(DebatSpreekbeurt).where(DebatSpreekbeurt.sessie_id == sessie.id)
        )
        at_once = Mattermost()
        feed.now = START + timedelta(seconds=215)
        service = DebatTijdlijnService(db_session, at_once)
        await service.tick(feed.now)
        assert _turns_in(at_once) == turns
        assert [
            (r.event_type, r.event_start, bool(r.post_id), r.beurt_soort, r.kop)
            for r in await _speaking_rows(db_session)
        ] == stepwise

    async def test_the_chairman_giving_the_floor_in_between_is_a_message(
        self, db_session, monkeypatch
    ):
        """The chair's message stands between the two, so they are not one
        turn: the channel follows the order of the debate."""
        events = [
            ("interrupter", _seconds(60), "a"),
            ("chairman", _seconds(62), "v"),
            ("speaker", _seconds(64), "a"),
        ]
        mm, _, _ = await self._follow(db_session, monkeypatch, events)

        assert len(_turns_in(mm)) == 2
        assert mm.channel[2].startswith("🔨 **Voorzitter**")
        assert mm.channel[3].startswith("**Onbekende spreker**")

    async def test_when_someone_else_spoke_in_between_it_is_a_new_turn(
        self, db_session, monkeypatch
    ):
        """A speaker who answers an interruption shows up again."""
        events = [
            ("interrupter", _seconds(60), "a"),
            ("speaker", _seconds(62), "b"),
            ("speaker", _seconds(64), "a"),
        ]
        mm, _, _ = await self._follow(db_session, monkeypatch, events)

        turns = _turns_in(mm)
        assert len(turns) == 3
        assert turns[0].startswith("↳ ")
        assert [r.beurt_soort for r in await _speaking_rows(db_session)] == [None] * 3

    async def test_a_suspension_in_between_makes_it_a_new_turn(
        self, db_session, monkeypatch
    ):
        events = [
            ("interrupter", _seconds(60), "a"),
            ("suspended", _seconds(62), ""),
            ("continued", _seconds(64), ""),
            ("speaker", _seconds(66), "a"),
        ]
        mm, _, _ = await self._follow(db_session, monkeypatch, events)

        turns = _turns_in(mm)
        assert len(turns) == 2
        assert turns[0].startswith("↳ ")
        assert turns[1].startswith("**")

    @pytest.mark.parametrize(("after", "messages"), [(50, 1), (51, 2)])
    async def test_only_within_fifty_seconds_of_the_start_of_the_turn(
        self, db_session, monkeypatch, after, messages
    ):
        """Later than that it is someone who interrupted and was given the
        floor afterwards: measured from 61 seconds on."""
        events = [
            ("interrupter", _seconds(60), "a"),
            ("speaker", _seconds(60 + after), "a"),
        ]
        mm, _, _ = await self._follow(db_session, monkeypatch, events)

        turns = _turns_in(mm)
        assert len(turns) == messages
        assert turns[0].startswith("**" if messages == 1 else "↳ ")

    async def test_speaker_and_then_interrupter_is_one_interruption(
        self, db_session, monkeypatch
    ):
        """The event that came last is the correction of the first."""
        events = [("speaker", _seconds(60), "a"), ("interrupter", _seconds(75), "a")]
        cues = [_cue(64, "Mag ik"), _cue(80, "iets vragen?")]
        mm, sessie, _ = await self._follow(db_session, monkeypatch, events, cues)

        assert len(mm.channel) == 2
        assert mm.channel[1].startswith("↳ **Onbekende spreker** · [")
        assert mm.channel[1].endswith(" · interruptie\nMag ik iets vragen?")
        (turn,) = await _member_turns(db_session, sessie)
        assert turn.key == ("interrupter", "a")

    @pytest.mark.parametrize(
        "order", [("interrupter", "speaker"), ("speaker", "interrupter")]
    )
    async def test_in_the_same_second_it_is_a_speaker_whichever_came_first(
        self, db_session, monkeypatch, order
    ):
        events = [(kind, _seconds(60), "a") for kind in order]
        cues = [_cue(64, "Voorzitter, dank.")]
        mm, sessie, _ = await self._follow(db_session, monkeypatch, events, cues)

        assert len(mm.channel) == 2
        assert mm.channel[1].startswith("**Onbekende spreker** · [")
        assert mm.channel[1].endswith("\nVoorzitter, dank.")
        (turn,) = await _member_turns(db_session, sessie)
        assert turn.key == ("speaker", "a")
        assert turn.text == "Voorzitter, dank."
        # Every row of the turn says which turn it went into, also the one
        # that has no message.
        entered_as_interrupter, _ = await _speaking_rows(db_session)
        assert entered_as_interrupter.event_type == "interrupter"
        assert entered_as_interrupter.beurt_soort == "speaker"

    async def test_a_turn_that_changes_twice_ends_as_what_came_last(
        self, db_session, monkeypatch
    ):
        """Seen once in 170 debates: interrupter, speaker 2 seconds later,
        interrupter again 27 seconds after that. It was an interruption."""
        events = [
            ("interrupter", _seconds(60), "a"),
            ("speaker", _seconds(62), "a"),
            ("interrupter", _seconds(89), "a"),
        ]
        cues = [_cue(62.5, "Een."), _cue(70, "Twee."), _cue(95, "Drie.")]
        mm, sessie, _ = await self._follow(db_session, monkeypatch, events, cues)

        assert len(mm.channel) == 2
        assert mm.channel[1].startswith("↳ **Onbekende spreker** · [")
        assert mm.channel[1].endswith(" · interruptie\nEen. Twee. Drie.")
        rows = await _speaking_rows(db_session)
        assert [r.event_type for r in rows] == ["interrupter", "speaker", "interrupter"]
        # The row in the middle says by itself which turn it went into.
        assert rows[1].beurt_soort == "interrupter"
        # Only the row with the message has a first line to write again.
        assert [r.kop is not None for r in rows] == [True, False, False]
        assert [r.tekst_geplaatst_hash for r in rows[1:]] == [None, None]
        (turn,) = await _member_turns(db_session, sessie)
        assert turn.key == ("interrupter", "a")
        assert turn.text == "Een. Twee. Drie."

    async def test_a_message_that_could_not_be_rewritten_is_rewritten_later(
        self, db_session, monkeypatch
    ):
        events = [("interrupter", _seconds(60), "a"), ("speaker", _seconds(75), "a")]
        feed = Feed(monkeypatch, parts=[_stream(_debat(*events))])
        Subtitles(monkeypatch, feed, [])
        mm = Mattermost()
        await _sessie(db_session)
        await _play(db_session, mm, feed, _seconds(80))
        assert mm.channel[1].startswith("↳ ")

        # Both who write the message in a round fail: the timeline for the
        # heading, and the transcript that would write it with the text.
        mm.fail_updates = 2
        feed.now = START + timedelta(seconds=90)
        result = await DebatTijdlijnService(db_session, mm).tick(feed.now)

        assert result.fouten >= 1
        assert mm.channel[1].startswith("↳ ")
        (first, _) = await _speaking_rows(db_session)
        assert not first.kop.startswith("↳ ")

        feed.now = START + timedelta(seconds=100)
        result = await DebatTijdlijnService(db_session, mm).tick(feed.now)

        assert result.fouten == 0
        assert mm.channel[1] == first.kop
        # And then it is done: not written again on every tick.
        written = len(mm.updates)
        feed.now = START + timedelta(seconds=110)
        await DebatTijdlijnService(db_session, mm).tick(feed.now)
        assert len(mm.updates) == written

    async def test_also_without_the_transcription(self, db_session, monkeypatch):
        monkeypatch.setattr(get_settings(), "DEBAT_TRANSCRIPT_ENABLED", False)
        events = [("interrupter", _seconds(60), "a"), ("speaker", _seconds(75), "a")]

        mm, _, _ = await self._follow(db_session, monkeypatch, events)

        assert len(mm.channel) == 2
        assert mm.channel[1] == heading_as(mm.posts[1][1], "speaker")
        assert len(mm.updates) == 1

    async def test_only_the_rows_of_this_turn_change(self, db_session, monkeypatch):
        """Not an earlier turn of the same person, and not someone else who
        was given the floor in the same second."""
        events = [
            ("speaker", _seconds(10), "b"),
            ("speaker", _seconds(60), "a"),
            ("speaker", _seconds(60), "b"),
            ("interrupter", _seconds(75), "b"),
        ]
        mm, sessie, _ = await self._follow(db_session, monkeypatch, events)

        turns = _turns_in(mm)
        assert [t.startswith("↳ ") for t in turns] == [False, False, True]
        rows = await _speaking_rows(db_session)
        assert [(r.object_id, r.event_type, r.beurt_soort) for r in rows] == [
            ("b", "speaker", None),
            ("a", "speaker", None),
            ("b", "speaker", "interrupter"),
            ("b", "interrupter", None),
        ]
        keys = [turn.key for turn in await _member_turns(db_session, sessie)]
        assert keys == [("speaker", "b"), ("speaker", "a"), ("interrupter", "b")]
        # The two other messages were not touched.
        assert len(mm.updates) == 1
