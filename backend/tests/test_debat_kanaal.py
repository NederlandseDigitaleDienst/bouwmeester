"""Tests for the start button: from a reaction to a channel with its agenda.

Three layers. The builders are pure and tested as such. The service runs
against a real database with a fake Mattermost, because what matters there
is what ends up in `debat_sessie`. And two presses at the same moment are
tested with two real sessions: a shared session cannot show a lost race.
"""

from __future__ import annotations

import re
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.models.debat_sessie import (
    TIJDLIJN_AFGELAST,
    TIJDLIJN_GEKOPPELD,
    TIJDLIJN_LOOPT,
    DebatSessie,
)
from bouwmeester.models.parlementair_alert_post import ParlementairAlertPost
from bouwmeester.models.parlementair_item import ParlementairItem
from bouwmeester.services import debat_kanaal_service as mod
from bouwmeester.services.debat_kanaal_service import (
    REACTIE_UITLUISTEREN,
    DebatKanaalService,
    StartOutcome,
    change_message,
    channel_display_name,
    channel_header,
    channel_name,
    channel_purpose,
    format_moment,
    is_startable,
    stukken_message,
)
from bouwmeester.services.mattermost_service import (
    ChannelNameTakenError,
    MattermostPermissionError,
    MattermostUnavailableError,
)
from bouwmeester.services.tk_activiteit import (
    Activiteit,
    AgendaDocument,
    Agendapunt,
    Bewindspersoon,
    TkApiError,
)

AMS = ZoneInfo("Europe/Amsterdam")
# What Mattermost accepts as a channel url name.
NAME_RE = re.compile(r"^[a-z0-9]+([a-z\-\_0-9]+|(__)?)[a-z0-9]*$")

TEAM = "team00000000000000000000aa"
SOURCE_CHANNEL = "kanaal0000000000000000aaaa"
SOURCE_POST = "post000000000000000000aaaa"
USER = "user000000000000000000aaaa"
BOT = "bot0000000000000000000aaaa"


def _activiteit(**overrides) -> Activiteit:
    # Far in the future, so "is it over" never depends on the day the
    # suite runs.
    start = datetime(2099, 10, 6, 16, 30, tzinfo=AMS)
    values = {
        "id": str(uuid.uuid4()),
        "nummer": "2099A05428",
        "soort": "Commissiedebat",
        "onderwerp": "Digitaliserende overheid",
        "aanvang": start,
        "einde": start + timedelta(hours=3),
        "status": "Gepland",
        "commissie": "vaste commissie voor Digitale Zaken",
        "bewindspersonen": (
            Bewindspersoon("E. Voorbeeld", "staatssecretaris van BZK"),
        ),
        "agendapunten": (
            Agendapunt(
                1,
                "Voortgang digitale overheid",
                "2099Z00001",
                (
                    AgendaDocument(
                        "2099D00001", "Brief regering", "Voortgang", "2099Z00001"
                    ),
                    AgendaDocument("2099D00002", "Bijlage", "Rapport", "2099Z00001"),
                ),
            ),
            Agendapunt(2, "Indicatieve spreektijd 4 minuten", None, ()),
        ),
    }
    values.update(overrides)
    return Activiteit(**values)


class TestIsStartable:
    EXTRA = {
        "activiteit_id": "cc83dcc6-44ac-46ee-b56d-87371a47f94f",
        "soort": "Convocatie commissieactiviteit",
        "activiteit_datum": "2026-10-06",
        "activiteit_status": "Gepland",
    }
    TODAY = date(2026, 10, 4)

    def test_upcoming_convocatie_gets_the_button(self):
        assert is_startable(self.EXTRA, self.TODAY) is True

    def test_today_still_counts(self):
        assert is_startable(self.EXTRA, date(2026, 10, 6)) is True

    def test_yesterday_does_not(self):
        assert is_startable(self.EXTRA, date(2026, 10, 7)) is False

    def test_without_activiteit_there_is_nothing_to_start(self):
        """Alerts imported before the id was kept."""
        assert is_startable({**self.EXTRA, "activiteit_id": None}, self.TODAY) is False

    def test_convocatie_inbreng_is_a_deadline_not_a_meeting(self):
        assert (
            is_startable({**self.EXTRA, "soort": "Convocatie inbreng"}, self.TODAY)
            is False
        )

    def test_a_brief_does_not_get_the_button(self):
        assert (
            is_startable({**self.EXTRA, "soort": "Brief regering"}, self.TODAY) is False
        )

    @pytest.mark.parametrize("status", ["Geannuleerd", "Verplaatst"])
    def test_meeting_that_is_off_gets_no_button(self, status):
        assert (
            is_startable({**self.EXTRA, "activiteit_status": status}, self.TODAY)
            is False
        )

    def test_unreadable_date_does_not_hide_the_button(self):
        assert (
            is_startable({**self.EXTRA, "activiteit_datum": "onbekend"}, self.TODAY)
            is True
        )

    def test_none_is_not_startable(self):
        assert is_startable(None) is False


class TestFormatMoment:
    def test_dutch_weekday_and_month(self):
        assert format_moment(_activiteit()) == "dinsdag 6 oktober, 16:30 tot 19:30"

    def test_utc_time_is_shown_in_dutch_time(self):
        """The container runs in UTC; a debate at 14:30 UTC starts at
        16:30 for everyone who reads the header."""
        start = datetime(2099, 10, 6, 14, 30, tzinfo=UTC)
        tekst = format_moment(_activiteit(aanvang=start, einde=None))
        assert tekst == "dinsdag 6 oktober, 16:30"

    def test_end_on_another_day_is_left_out(self):
        a = _activiteit()
        a = _activiteit(aanvang=a.aanvang, einde=a.aanvang + timedelta(days=1))
        assert format_moment(a) == "dinsdag 6 oktober, 16:30"

    def test_no_start_no_text(self):
        assert format_moment(_activiteit(aanvang=None)) == ""


class TestChannelName:
    def test_subject_and_date(self):
        assert channel_name(_activiteit()) == "debat-digitaliserende-overheid-6-okt"

    def test_with_nummer_for_a_taken_name(self):
        assert (
            channel_name(_activiteit(), with_nummer=True)
            == "debat-digitaliserende-overheid-6-okt-2099a05428"
        )

    def test_accents_and_punctuation(self):
        a = _activiteit(onderwerp="Eurogroep/Ecofinraad d.d. 8 & 9 oktober (Curaçao)")
        assert (
            channel_name(a)
            == "debat-eurogroep-ecofinraad-d-d-8-9-oktober-curacao-6-okt"
        )

    @pytest.mark.parametrize("with_nummer", [False, True])
    @pytest.mark.parametrize(
        "onderwerp",
        [
            "Digitaliserende overheid",
            "x" * 200,
            "woord " * 40,
            "Een heel lang onderwerp over de voortgang van de digitalisering "
            "van de overheid en het toezicht daarop in de komende jaren",
            "!!!",
            "",
            "-- streepjes --",
        ],
    )
    def test_always_a_name_mattermost_accepts(self, onderwerp, with_nummer):
        naam = channel_name(_activiteit(onderwerp=onderwerp), with_nummer=with_nummer)
        assert len(naam) <= 64
        assert NAME_RE.match(naam), naam
        assert "--" not in naam

    def test_long_subject_keeps_the_date(self):
        """The date is what tells this year's debate from last year's."""
        naam = channel_name(_activiteit(onderwerp="woord " * 40))
        assert naam.endswith("-6-okt")
        assert naam.startswith("debat-woord-woord")

    def test_long_subject_is_cut_at_a_word(self):
        a = _activiteit(
            onderwerp=(
                "Voortgang van de digitaliseringsstrategie en informatiehuishouding"
            )
        )
        naam = channel_name(a)
        assert len(naam) <= 64
        assert naam == "debat-voortgang-van-de-digitaliseringsstrategie-en-6-okt"

    def test_long_subject_with_nummer_keeps_both(self):
        naam = channel_name(_activiteit(onderwerp="woord " * 40), with_nummer=True)
        assert naam.endswith("-6-okt-2099a05428")

    def test_empty_subject_falls_back_to_the_nummer(self):
        assert channel_name(_activiteit(onderwerp="")) == "debat-2099a05428-6-okt"

    def test_no_start_no_date(self):
        assert (
            channel_name(_activiteit(aanvang=None)) == "debat-digitaliserende-overheid"
        )


class TestChannelTexts:
    def test_display_name(self):
        assert channel_display_name(_activiteit()) == "Digitaliserende overheid (6 okt)"

    def test_display_name_fits_and_keeps_the_date(self):
        naam = channel_display_name(_activiteit(onderwerp="woord " * 40))
        assert len(naam) <= 64
        assert naam.endswith("… (6 okt)")

    def test_header_has_kind_time_and_links(self):
        header = channel_header(_activiteit())
        assert header.startswith("**Commissiedebat** · dinsdag 6 oktober, 16:30")
        assert "details?id=2099A05428" in header
        assert "debatdirect.tweedekamer.nl" in header
        assert len(header) <= 1024

    def test_header_without_nummer_has_no_broken_link(self):
        header = channel_header(_activiteit(nummer=None))
        assert "details?id=" not in header
        assert "None" not in header

    def test_purpose(self):
        assert (
            channel_purpose(_activiteit())
            == "Commissiedebat vaste commissie voor Digitale Zaken: "
            "Digitaliserende overheid"
        )

    @pytest.mark.parametrize(
        "onderwerp",
        [
            "Gewasbeschermingsmiddelenbeleid en bestrijdingsmiddelenregistratie"
            "systematiek van Nederland",
            "x" * 300,
        ],
    )
    def test_a_long_word_at_the_cut_still_fits(self, onderwerp):
        """Cutting adds an ellipsis. With no space near the cut that used
        to give one character too many, and Mattermost answers 400."""
        a = _activiteit(onderwerp=onderwerp)
        assert len(channel_display_name(a)) <= 64
        assert len(channel_purpose(a)) <= 250

    def test_a_bracket_in_a_nummer_cannot_end_the_link(self):
        header = channel_header(_activiteit(nummer="2099A)x"))
        assert "id=2099A%29x)" in header

    def test_purpose_fits(self):
        assert len(channel_purpose(_activiteit(onderwerp="woord " * 100))) <= 250


class TestStukkenMessage:
    NOW = datetime(2099, 9, 20, 12, 5, tzinfo=UTC)

    def test_lists_the_agenda_with_links(self):
        bericht = stukken_message(_activiteit(), now=self.NOW)
        assert bericht.startswith(
            "#### Geagendeerde stukken: Digitaliserende overheid\n"
        )
        assert (
            "1. [Voortgang digitale overheid]"
            "(https://www.tweedekamer.nl/kamerstukken/detail"
            "?id=2099Z00001&did=2099D00001) · Brief regering (+1 stuk)"
        ) in bericht
        assert "2. Indicatieve spreektijd 4 minuten" in bericht

    def test_meta_and_bewindspersonen(self):
        bericht = stukken_message(_activiteit(), now=self.NOW)
        assert (
            "Commissiedebat · dinsdag 6 oktober, 16:30 tot 19:30 · "
            "vaste commissie voor Digitale Zaken"
        ) in bericht
        assert "Bewindspersonen: staatssecretaris van BZK (E. Voorbeeld)" in bericht

    def test_footer_says_when_it_was_read_in_dutch_time(self):
        """The agenda changes; the reader has to see how old this is."""
        bericht = stukken_message(_activiteit(), now=self.NOW)
        assert bericht.endswith("opgehaald op 20 september om 14:05._")

    def test_summary_is_added_where_we_have_one(self):
        bericht = stukken_message(
            _activiteit(),
            {"2099D00002": "De voortgang ligt\nop schema."},
            now=self.NOW,
        )
        assert "\n    > De voortgang ligt op schema." in bericht

    def test_no_summary_no_quote_line(self):
        assert ">" not in stukken_message(_activiteit(), now=self.NOW)

    def test_empty_agenda_says_so(self):
        bericht = stukken_message(_activiteit(agendapunten=()), now=self.NOW)
        assert "Er staan nog geen stukken op de agenda." in bericht

    def test_markdown_in_a_title_cannot_forge_a_link(self):
        """Titles come from documents by third parties."""
        punt = Agendapunt(
            1,
            "Kijk [hier](http://evil.test) @channel",
            "2099Z00001",
            (AgendaDocument("2099D00001", None, None),),
        )
        bericht = stukken_message(_activiteit(agendapunten=(punt,)), now=self.NOW)
        assert "[hier](http://evil.test)" not in bericht
        assert (
            "1. [Kijk \\[hier\\]\\(http://evil.test\\) @⁠channel]"
            "(https://www.tweedekamer.nl/"
        ) in bericht

    def test_markdown_in_the_subject_is_escaped_too(self):
        bericht = stukken_message(
            _activiteit(onderwerp="Debat @channel", agendapunten=()), now=self.NOW
        )
        assert "@channel" not in bericht.replace("\\@channel", "")

    def test_huge_agenda_stays_under_the_post_limit(self):
        """A message Mattermost refuses leaves the channel without agenda."""
        punten = tuple(
            Agendapunt(
                i,
                f"Agendapunt {i} " + "lang " * 38,
                f"2099Z{i:05d}",
                (AgendaDocument(f"2099D{i:05d}", "Brief regering", None),),
            )
            for i in range(1, 121)
        )
        samenvattingen = {f"2099D{i:05d}": "samenvatting " * 30 for i in range(1, 121)}
        bericht = stukken_message(
            _activiteit(agendapunten=punten), samenvattingen, now=self.NOW
        )
        assert len(bericht) <= 15000
        assert "1. [Agendapunt 1 " in bericht
        assert re.search(r"En nog \d+ agendapunten", bericht)
        # The footer survives the cut.
        assert bericht.endswith("._")

    def test_each_document_links_through_its_own_zaak(self):
        """One agendapunt can carry several zaken. The zaak of one with
        the document of another is a link to nothing."""
        punt = Agendapunt(
            1,
            "Twee zaken",
            "2099Z00001",
            (
                AgendaDocument("2099D00007", "Motie", None, "2099Z00002"),
                AgendaDocument("2099D00008", "Motie", None, "2099Z00001"),
            ),
        )
        bericht = stukken_message(_activiteit(agendapunten=(punt,)), now=self.NOW)
        assert "detail?id=2099Z00002&did=2099D00007)" in bericht

    def test_a_monstrous_header_is_still_cut(self):
        bericht = stukken_message(
            _activiteit(onderwerp="x" * 30000, agendapunten=()), now=self.NOW
        )
        assert len(bericht) <= 15000

    def test_summaries_go_before_agenda_items_do(self):
        punten = tuple(
            Agendapunt(
                i,
                f"Agendapunt {i}",
                f"2099Z{i:05d}",
                (AgendaDocument(f"2099D{i:05d}", "Brief regering", None),),
            )
            for i in range(1, 61)
        )
        samenvattingen = {f"2099D{i:05d}": "samenvatting " * 30 for i in range(1, 61)}
        bericht = stukken_message(
            _activiteit(agendapunten=punten), samenvattingen, now=self.NOW
        )
        assert "60. [Agendapunt 60]" in bericht
        assert ">" not in bericht


class FakeMattermost:
    """Records what the service asks of Mattermost."""

    def __init__(self) -> None:
        self.created: list[dict] = []
        self.create_errors: list[Exception] = []
        self.by_name: dict[str, dict] = {}
        self.messages: list[tuple[str, str, str | None]] = []
        self.pinned: list[str] = []
        self.members: list[tuple[str, str]] = []
        self.post_ok = True
        self.pin_ok = True
        self.team_id: str | None = TEAM
        self.username = "marieke"
        self.closed = False
        self.gone: set[str] = set()
        # What a channel says now, as far as a test cares: header, purpose
        # and display name by channel id.
        self.channels: dict[str, dict] = {}
        self.updated: list[tuple[str, dict]] = []
        self.edited: list[tuple[str, str]] = []
        self.edit_error: Exception | None = None

    def _id(self, prefix: str) -> str:
        # Random, not counted: `channel_id` is unique in the database, and
        # tests that really commit run next to each other.
        return f"{prefix}{uuid.uuid4().hex}"[:26]

    async def create_channel(self, **kwargs) -> dict:
        self.created.append(kwargs)
        if self.create_errors:
            error = self.create_errors.pop(0)
            if error is not None:
                raise error
        return {"id": self._id("chan"), "name": kwargs["name"], "creator_id": BOT}

    async def get_channel_by_name(self, team_id: str, name: str):
        return self.by_name.get(name)

    async def get_bot_user_id(self):
        return BOT

    async def channel_is_gone(self, channel_id: str) -> bool:
        return channel_id in self.gone

    async def get_channel(self, channel_id: str):
        if not self.team_id:
            return None
        return {
            "id": channel_id,
            "team_id": self.team_id,
            **self.channels.get(channel_id, {}),
        }

    async def update_channel(self, channel_id: str, **fields) -> bool:
        self.updated.append((channel_id, fields))
        return True

    async def update_post(self, post_id: str, message: str, props=None) -> bool:
        if self.edit_error is not None:
            raise self.edit_error
        self.edited.append((post_id, message))
        return True

    async def send_channel_message(self, channel_id, text, props=None, root_id=None):
        if not self.post_ok and root_id is None:
            return None
        self.messages.append((channel_id, text, root_id))
        return self._id("post")

    async def pin_post(self, post_id: str) -> bool:
        if self.pin_ok:
            self.pinned.append(post_id)
        return self.pin_ok

    async def add_channel_member(self, channel_id: str, user_id: str) -> bool:
        self.members.append((channel_id, user_id))
        return True

    async def get_username(self, user_id: str) -> str:
        return self.username

    async def close(self) -> None:
        self.closed = True

    @property
    def replies(self) -> list[str]:
        return [text for _, text, root in self.messages if root == SOURCE_POST]

    @property
    def channel_posts(self) -> list[tuple[str, str]]:
        return [(ch, text) for ch, text, root in self.messages if root is None]


async def _item(session: AsyncSession, activiteit_id: str | None) -> ParlementairItem:
    nummer = f"2099D{uuid.uuid4().int % 10**8:08d}"
    item = ParlementairItem(
        type="convocatie",
        zaak_id=nummer,
        zaak_nummer=nummer,
        titel="Convocatie commissiedebat Digitaliserende overheid",
        onderwerp="Convocatie",
        bron="tweede_kamer",
        extra_data={"activiteit_id": activiteit_id} if activiteit_id else {},
    )
    session.add(item)
    await session.flush()
    return item


def _patch_fetch(monkeypatch, result):
    """Make the TK API answer with `result` (an Activiteit, None or an error)."""
    asked: list[str] = []

    async def fake_fetch(activiteit_id, client, base_url=None):
        asked.append(activiteit_id)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(mod, "fetch_activiteit", fake_fetch)
    return asked


def _patch_fetch_many(monkeypatch, *activiteiten: Activiteit):
    """Make the TK API know several activiteiten, each by its id."""
    known = {a.id: a for a in activiteiten}
    asked: list[str] = []

    async def fake_fetch(activiteit_id, client, base_url=None):
        asked.append(activiteit_id)
        return known.get(activiteit_id)

    monkeypatch.setattr(mod, "fetch_activiteit", fake_fetch)
    return asked


async def _start(session, mattermost, item):
    return await DebatKanaalService(session, mattermost).start(
        item=item,
        source_channel_id=SOURCE_CHANNEL,
        source_post_id=SOURCE_POST,
        mattermost_user_id=USER,
    )


async def _sessies(session: AsyncSession, activiteit_id: str) -> list[DebatSessie]:
    stmt = select(DebatSessie).where(DebatSessie.activiteit_id == activiteit_id)
    return list((await session.execute(stmt)).scalars().all())


@pytest.mark.asyncio
class TestStart:
    async def test_creates_the_channel_with_header_purpose_and_agenda(
        self, db_session, monkeypatch
    ):
        activiteit = _activiteit()
        asked = _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        item = await _item(db_session, activiteit.id)

        result = await _start(db_session, mm, item)

        assert result.outcome is StartOutcome.CREATED
        assert asked == [activiteit.id]
        assert mm.created == [
            {
                "team_id": TEAM,
                "name": "debat-digitaliserende-overheid-6-okt",
                "display_name": "Digitaliserende overheid (6 okt)",
                "header": channel_header(activiteit),
                "purpose": channel_purpose(activiteit),
            }
        ]
        # The agenda is posted in the new channel and pinned there.
        ((channel_id, agenda),) = mm.channel_posts
        assert channel_id == result.channel_id
        assert agenda.startswith("#### Geagendeerde stukken")
        assert len(mm.pinned) == 1
        # Whoever pressed is in the channel.
        assert mm.members == [(result.channel_id, USER)]

    async def test_the_sessie_is_stored(self, db_session, monkeypatch):
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        item = await _item(db_session, activiteit.id)

        result = await _start(db_session, mm, item)

        (sessie,) = await _sessies(db_session, activiteit.id)
        assert sessie.channel_id == result.channel_id
        assert sessie.channel_name == "debat-digitaliserende-overheid-6-okt"
        assert sessie.team_id == TEAM
        assert sessie.activiteit_nummer == "2099A05428"
        assert sessie.onderwerp == "Digitaliserende overheid"
        assert sessie.aanvang == activiteit.aanvang
        assert sessie.stukken_post_id == mm.pinned[0]
        assert sessie.parlementair_item_id == item.id
        assert sessie.started_by_mattermost_user_id == USER

    async def test_answers_in_the_thread_with_the_channel(
        self, db_session, monkeypatch
    ):
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()

        await _start(db_session, mm, await _item(db_session, activiteit.id))

        assert mm.replies == [
            "Kanaal ~debat-digitaliserende-overheid-6-okt staat klaar voor "
            "**Digitaliserende overheid** (dinsdag 6 oktober, 16:30 tot 19:30). "
            "De geagendeerde stukken staan er vastgepind. Gestart door @marieke."
        ]

    async def test_unknown_username_is_not_mentioned(self, db_session, monkeypatch):
        """`get_username` returns the id when the lookup fails."""
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        mm.username = USER

        await _start(db_session, mm, await _item(db_session, activiteit.id))

        assert "Gestart door" not in mm.replies[0]
        assert USER not in mm.replies[0]

    async def test_summaries_we_have_end_up_in_the_agenda(
        self, db_session, monkeypatch
    ):
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        db_session.add(
            ParlementairItem(
                type="brief",
                zaak_id="2099D00001",
                zaak_nummer="2099Z00001",
                titel="Voortgang",
                onderwerp="Voortgang",
                bron="tweede_kamer",
                llm_samenvatting="De aansluiting ligt op schema.",
            )
        )
        await db_session.flush()
        mm = FakeMattermost()

        await _start(db_session, mm, await _item(db_session, activiteit.id))

        assert "> De aansluiting ligt op schema." in mm.channel_posts[0][1]

    async def test_a_failed_summary_is_not_shown_as_one(self, db_session, monkeypatch):
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        db_session.add(
            ParlementairItem(
                type="brief",
                zaak_id="2099D00001",
                zaak_nummer="2099Z00001",
                titel="Voortgang",
                onderwerp="Voortgang",
                bron="tweede_kamer",
                llm_samenvatting="Samenvatting mislukt.",
            )
        )
        await db_session.flush()
        mm = FakeMattermost()

        await _start(db_session, mm, await _item(db_session, activiteit.id))

        assert "mislukt" not in mm.channel_posts[0][1]

    async def test_second_press_points_to_the_existing_channel(
        self, db_session, monkeypatch
    ):
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        item = await _item(db_session, activiteit.id)
        first = await _start(db_session, mm, item)

        second = await DebatKanaalService(db_session, mm).start(
            item=item,
            source_channel_id=SOURCE_CHANNEL,
            source_post_id=SOURCE_POST,
            mattermost_user_id="user000000000000000000bbbb",
        )

        assert second.outcome is StartOutcome.EXISTS
        assert second.channel_id == first.channel_id
        assert len(mm.created) == 1
        assert len(await _sessies(db_session, activiteit.id)) == 1
        assert mm.replies[-1] == (
            "Er is al een kanaal voor dit debat: ~debat-digitaliserende-overheid-6-okt"
        )
        # The second person is let in as well.
        assert mm.members[-1] == (first.channel_id, "user000000000000000000bbbb")

    async def test_same_debate_in_another_team_gets_its_own_channel(
        self, db_session, monkeypatch
    ):
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        item = await _item(db_session, activiteit.id)
        await _start(db_session, mm, item)

        mm.team_id = "team00000000000000000000bb"
        result = await _start(db_session, mm, item)

        assert result.outcome is StartOutcome.CREATED
        assert [c["team_id"] for c in mm.created] == [TEAM, mm.team_id]

    async def test_team_comes_from_our_own_link_when_it_knows(
        self, db_session, monkeypatch
    ):
        from bouwmeester.models.mattermost_channel_link import MattermostChannelLink

        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        source = f"kan{uuid.uuid4().hex[:23]}"
        db_session.add(
            MattermostChannelLink(
                channel_id=source,
                channel_name="in-de-kamer",
                channel_display_name="In de Kamer",
                team_id="team00000000000000000000cc",
                scope_type="initiatief",
                scope_id=uuid.uuid4(),
            )
        )
        await db_session.flush()
        mm = FakeMattermost()
        mm.team_id = None  # Mattermost would not know.

        result = await DebatKanaalService(db_session, mm).start(
            item=await _item(db_session, activiteit.id),
            source_channel_id=source,
            source_post_id=SOURCE_POST,
            mattermost_user_id=USER,
        )

        assert result.outcome is StartOutcome.CREATED
        assert mm.created[0]["team_id"] == "team00000000000000000000cc"


@pytest.mark.asyncio
class TestRefusals:
    """Nothing is created, and the thread says why."""

    async def _refused(self, db_session, monkeypatch, fetch_result, item=None):
        mm = FakeMattermost()
        if item is None:
            activiteit_id = (
                fetch_result.id
                if isinstance(fetch_result, Activiteit)
                else str(uuid.uuid4())
            )
            item = await _item(db_session, activiteit_id)
        _patch_fetch(monkeypatch, fetch_result)
        result = await _start(db_session, mm, item)
        assert mm.created == []
        assert mm.channel_posts == []
        assert (
            await db_session.execute(
                select(DebatSessie.id).where(
                    DebatSessie.parlementair_item_id == item.id
                )
            )
        ).first() is None
        return result, mm

    async def test_item_without_activiteit(self, db_session, monkeypatch):
        item = await _item(db_session, None)
        result, mm = await self._refused(
            db_session, monkeypatch, _activiteit(), item=item
        )
        assert result.outcome is StartOutcome.REFUSED
        assert "geen vergadering bekend" in mm.replies[0]

    async def test_cancelled(self, db_session, monkeypatch):
        result, mm = await self._refused(
            db_session, monkeypatch, _activiteit(status="Geannuleerd")
        )
        assert result.outcome is StartOutcome.REFUSED
        assert mm.replies == ["Deze vergadering is geannuleerd."]

    async def test_moved(self, db_session, monkeypatch):
        result, mm = await self._refused(
            db_session, monkeypatch, _activiteit(status="Verplaatst")
        )
        assert result.outcome is StartOutcome.REFUSED
        assert "verplaatst" in mm.replies[0]

    async def test_closed_meeting(self, db_session, monkeypatch):
        """A closed meeting is not broadcast; a channel with a link to the
        livestream would promise something that never comes."""
        result, mm = await self._refused(
            db_session, monkeypatch, _activiteit(besloten=True)
        )
        assert result.outcome is StartOutcome.REFUSED
        assert "besloten" in mm.replies[0]

    async def test_already_over(self, db_session, monkeypatch):
        start = datetime.now(UTC) - timedelta(hours=5)
        result, mm = await self._refused(
            db_session,
            monkeypatch,
            _activiteit(aanvang=start, einde=start + timedelta(hours=3)),
        )
        assert result.outcome is StartOutcome.REFUSED
        assert mm.replies == ["Deze vergadering is al geweest."]

    async def test_no_longer_in_the_agenda(self, db_session, monkeypatch):
        result, mm = await self._refused(db_session, monkeypatch, None)
        assert result.outcome is StartOutcome.REFUSED
        assert "staat niet meer in de agenda" in mm.replies[0]

    async def test_tk_api_down_is_a_failure_with_a_way_to_retry(
        self, db_session, monkeypatch
    ):
        result, mm = await self._refused(db_session, monkeypatch, TkApiError("down"))
        assert result.outcome is StartOutcome.FAILED
        assert "nu niet op te halen" in mm.replies[0]
        assert "Haal je reactie weg" in mm.replies[0]

    async def test_unknown_team(self, db_session, monkeypatch):
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        mm.team_id = None
        result = await _start(db_session, mm, await _item(db_session, activiteit.id))
        assert result.outcome is StartOutcome.FAILED
        assert mm.created == []
        assert "welk team" in mm.replies[0]


class TestIsOver:
    NOW = datetime(2026, 10, 6, 20, 0, tzinfo=UTC)

    def test_running_debate_is_not_over(self):
        a = _activiteit(
            aanvang=self.NOW - timedelta(hours=2), einde=self.NOW + timedelta(hours=1)
        )
        assert mod._is_over(a, self.NOW) is False

    def test_past_its_end_is_over(self):
        a = _activiteit(
            aanvang=self.NOW - timedelta(hours=4), einde=self.NOW - timedelta(minutes=1)
        )
        assert mod._is_over(a, self.NOW) is True

    def test_without_end_a_debate_from_this_afternoon_may_still_run(self):
        a = _activiteit(aanvang=self.NOW - timedelta(hours=6), einde=None)
        assert mod._is_over(a, self.NOW) is False

    def test_without_end_yesterday_is_over(self):
        a = _activiteit(aanvang=self.NOW - timedelta(hours=30), einde=None)
        assert mod._is_over(a, self.NOW) is True

    def test_without_any_time_it_is_not_over(self):
        assert mod._is_over(_activiteit(aanvang=None, einde=None), self.NOW) is False


@pytest.mark.asyncio
class TestWhenMattermostFails:
    async def test_missing_permission_tells_what_an_admin_must_do(
        self, db_session, monkeypatch
    ):
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        mm.create_errors = [MattermostPermissionError("create_public_channel")]

        result = await _start(db_session, mm, await _item(db_session, activiteit.id))

        assert result.outcome is StartOutcome.FAILED
        assert "`create_public_channel`" in mm.replies[0]
        assert "beheerder" in mm.replies[0]

    @pytest.mark.parametrize(
        "error",
        [
            MattermostPermissionError("create_public_channel"),
            MattermostUnavailableError("down"),
        ],
    )
    async def test_a_failed_create_leaves_no_claim_behind(
        self, db_session, monkeypatch, error
    ):
        """Otherwise the button is dead for this debate until the claim
        goes stale, also after the administrator fixed the permission."""
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        mm.create_errors = [error]
        item = await _item(db_session, activiteit.id)

        first = await _start(db_session, mm, item)
        assert first.outcome is StartOutcome.FAILED
        assert await _sessies(db_session, activiteit.id) == []

        second = await _start(db_session, mm, item)
        assert second.outcome is StartOutcome.CREATED

    async def test_taken_name_gets_the_nummer(self, db_session, monkeypatch):
        """Someone made a channel with this name by hand, or last year's
        debate was archived under it."""
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        mm.create_errors = [ChannelNameTakenError("x")]

        result = await _start(db_session, mm, await _item(db_session, activiteit.id))

        assert result.outcome is StartOutcome.CREATED
        assert [c["name"] for c in mm.created] == [
            "debat-digitaliserende-overheid-6-okt",
            "debat-digitaliserende-overheid-6-okt-2099a05428",
        ]
        (sessie,) = await _sessies(db_session, activiteit.id)
        assert sessie.channel_name == "debat-digitaliserende-overheid-6-okt-2099a05428"
        assert "~debat-digitaliserende-overheid-6-okt-2099a05428" in mm.replies[0]

    async def test_taken_name_that_is_our_own_orphan_is_adopted(
        self, db_session, monkeypatch
    ):
        """Mattermost saved the channel but the answer never arrived. A
        new name would give this debate two channels."""
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        orphan = {
            "id": "chanorphan0000000000000000",
            "name": "debat-digitaliserende-overheid-6-okt",
            "creator_id": BOT,
            "header": channel_header(activiteit),
        }
        mm.by_name[orphan["name"]] = orphan
        mm.create_errors = [ChannelNameTakenError("x")]

        result = await _start(db_session, mm, await _item(db_session, activiteit.id))

        assert result.outcome is StartOutcome.CREATED
        assert result.channel_id == orphan["id"]
        assert len(mm.created) == 1
        # The adopted channel still gets its agenda.
        assert mm.channel_posts[0][0] == orphan["id"]

    async def test_channel_made_by_a_human_is_not_adopted(
        self, db_session, monkeypatch
    ):
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        mm.by_name["debat-digitaliserende-overheid-6-okt"] = {
            "id": "chanhuman00000000000000000",
            "name": "debat-digitaliserende-overheid-6-okt",
            "creator_id": USER,
            "header": channel_header(activiteit),
        }
        mm.create_errors = [ChannelNameTakenError("x")]

        result = await _start(db_session, mm, await _item(db_session, activiteit.id))

        assert result.channel_id != "chanhuman00000000000000000"
        assert len(mm.created) == 2

    async def test_channel_of_another_debate_is_not_adopted(
        self, db_session, monkeypatch
    ):
        """Two activiteiten with the same subject on the same day exist
        (Eilandraad Saba, 7 October 2026). The second must not move into
        the channel of the first."""
        first = _activiteit()
        _patch_fetch(monkeypatch, first)
        mm = FakeMattermost()
        result_first = await _start(db_session, mm, await _item(db_session, first.id))
        mm.by_name["debat-digitaliserende-overheid-6-okt"] = {
            "id": result_first.channel_id,
            "name": "debat-digitaliserende-overheid-6-okt",
            "creator_id": BOT,
            "header": channel_header(first),
        }

        second = _activiteit(nummer="2099A09999")
        _patch_fetch(monkeypatch, second)
        mm.create_errors = [ChannelNameTakenError("x")]
        result_second = await _start(db_session, mm, await _item(db_session, second.id))

        assert result_second.outcome is StartOutcome.CREATED
        assert result_second.channel_id != result_first.channel_id
        assert mm.created[-1]["name"].endswith("-2099a09999")

    async def test_orphan_of_a_twin_debate_is_not_adopted(
        self, db_session, monkeypatch
    ):
        """The twin's create was saved but never recorded, so no sessie
        points to its channel. Bot-made and unclaimed is then not enough:
        the header has to be the one of this activiteit."""
        twin = _activiteit(nummer="2099A00001")
        activiteit = _activiteit(nummer="2099A00002")
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        mm.by_name["debat-digitaliserende-overheid-6-okt"] = {
            "id": "chantwin000000000000000000",
            "name": "debat-digitaliserende-overheid-6-okt",
            "creator_id": BOT,
            "header": channel_header(twin),
        }
        mm.create_errors = [ChannelNameTakenError("x")]

        result = await _start(db_session, mm, await _item(db_session, activiteit.id))

        assert result.outcome is StartOutcome.CREATED
        assert result.channel_id != "chantwin000000000000000000"
        assert mm.created[-1]["name"].endswith("-2099a00002")

    async def test_twin_without_nummer_does_not_take_a_claimed_channel(
        self, db_session, monkeypatch
    ):
        """Without a nummer the header has no agenda link, so twins get
        the same header. Then the sessie is what says the channel is
        somebody's."""
        first = _activiteit(nummer=None)
        _patch_fetch(monkeypatch, first)
        mm = FakeMattermost()
        result_first = await _start(db_session, mm, await _item(db_session, first.id))
        mm.by_name["debat-digitaliserende-overheid-6-okt"] = {
            "id": result_first.channel_id,
            "name": "debat-digitaliserende-overheid-6-okt",
            "creator_id": BOT,
            "header": channel_header(first),
        }

        second = _activiteit(nummer=None)
        assert channel_header(second) == channel_header(first)
        _patch_fetch(monkeypatch, second)
        mm.create_errors = [ChannelNameTakenError("x")]
        result_second = await _start(db_session, mm, await _item(db_session, second.id))

        # Not only "another channel": the unique key on `channel_id` would
        # also stop the adoption, but as a failed start.
        assert result_second.outcome is StartOutcome.CREATED
        assert result_second.channel_id != result_first.channel_id

    async def test_archived_channel_is_set_up_again(self, db_session, monkeypatch):
        """Someone archives the channel weeks before the debate. The
        button must not keep pointing at a channel nobody can open."""
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        item = await _item(db_session, activiteit.id)
        first = await _start(db_session, mm, item)
        mm.gone.add(first.channel_id)

        second = await _start(db_session, mm, item)

        assert second.outcome is StartOutcome.CREATED
        assert second.channel_id != first.channel_id
        (sessie,) = await _sessies(db_session, activiteit.id)
        assert sessie.channel_id == second.channel_id

    async def test_channel_that_cannot_be_checked_is_kept(
        self, db_session, monkeypatch
    ):
        """`channel_is_gone` answers False when it does not know."""
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        item = await _item(db_session, activiteit.id)
        first = await _start(db_session, mm, item)

        second = await _start(db_session, mm, item)

        assert second.outcome is StartOutcome.EXISTS
        assert second.channel_id == first.channel_id

    async def test_refused_insert_without_a_row_is_not_silence(
        self, db_session, monkeypatch
    ):
        """Not every refused insert is a lost race. With no row to point
        at, saying nothing leaves the button looking dead."""
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        svc = DebatKanaalService(db_session, mm)

        async def refused(*args):
            return None, None

        monkeypatch.setattr(svc, "_claim", refused)
        result = await svc.start(
            item=await _item(db_session, activiteit.id),
            source_channel_id=SOURCE_CHANNEL,
            source_post_id=SOURCE_POST,
            mattermost_user_id=USER,
        )

        assert result.outcome is StartOutcome.FAILED
        assert "Er ging iets mis" in mm.replies[0]

    async def test_both_names_taken_is_a_failure(self, db_session, monkeypatch):
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        mm.create_errors = [ChannelNameTakenError("x"), ChannelNameTakenError("y")]

        result = await _start(db_session, mm, await _item(db_session, activiteit.id))

        assert result.outcome is StartOutcome.FAILED
        assert await _sessies(db_session, activiteit.id) == []
        assert "niet gelukt" in mm.replies[0]

    async def test_channel_is_known_even_if_the_agenda_post_fails(
        self, db_session, monkeypatch
    ):
        """The channel exists by then. Forgetting it would make the next
        press create a second one."""
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        mm.post_ok = False

        result = await _start(db_session, mm, await _item(db_session, activiteit.id))

        assert result.outcome is StartOutcome.CREATED
        (sessie,) = await _sessies(db_session, activiteit.id)
        assert sessie.channel_id == result.channel_id
        assert sessie.stukken_post_id is None
        assert mm.pinned == []
        # And the thread does not claim an agenda that is not there.
        assert "vastgepind" not in mm.replies[0]
        assert "staat klaar" in mm.replies[0]

    async def test_failed_pin_keeps_the_post(self, db_session, monkeypatch):
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        mm.pin_ok = False

        await _start(db_session, mm, await _item(db_session, activiteit.id))

        (sessie,) = await _sessies(db_session, activiteit.id)
        assert sessie.stukken_post_id is not None


@pytest.mark.asyncio
class TestClaim:
    async def test_fresh_claim_without_channel_blocks_quietly(
        self, db_session, monkeypatch
    ):
        """Another run is busy with it; that run answers in the thread."""
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        db_session.add(
            DebatSessie(activiteit_id=activiteit.id, onderwerp="x", team_id=TEAM)
        )
        await db_session.flush()
        mm = FakeMattermost()

        result = await _start(db_session, mm, await _item(db_session, activiteit.id))

        assert result.outcome is StartOutcome.IN_PROGRESS
        assert mm.created == []
        assert mm.replies == []

    async def test_stale_claim_is_taken_over(self, db_session, monkeypatch):
        """A restart between the claim and the Mattermost call would
        otherwise kill the button for this debate for good."""
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        db_session.add(
            DebatSessie(activiteit_id=activiteit.id, onderwerp="x", team_id=TEAM)
        )
        await db_session.flush()
        await db_session.execute(
            update(DebatSessie)
            .where(DebatSessie.activiteit_id == activiteit.id)
            .values(created_at=datetime.now(UTC) - timedelta(minutes=6))
        )
        db_session.expire_all()
        mm = FakeMattermost()

        result = await _start(db_session, mm, await _item(db_session, activiteit.id))

        assert result.outcome is StartOutcome.CREATED
        (sessie,) = await _sessies(db_session, activiteit.id)
        assert sessie.channel_id == result.channel_id

    async def test_old_sessie_with_a_channel_is_never_taken_over(
        self, db_session, monkeypatch
    ):
        """Staleness is about a claim without a channel. A debate that was
        started three weeks ago is not stale."""
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        db_session.add(
            DebatSessie(
                activiteit_id=activiteit.id,
                onderwerp="x",
                team_id=TEAM,
                channel_id="chanbestaand00000000000000",
                channel_name="debat-bestaand",
            )
        )
        await db_session.flush()
        await db_session.execute(
            update(DebatSessie)
            .where(DebatSessie.activiteit_id == activiteit.id)
            .values(created_at=datetime.now(UTC) - timedelta(days=21))
        )
        db_session.expire_all()
        mm = FakeMattermost()

        result = await _start(db_session, mm, await _item(db_session, activiteit.id))

        assert result.outcome is StartOutcome.EXISTS
        assert result.channel_id == "chanbestaand00000000000000"
        assert mm.created == []

    async def test_two_real_sessions_only_one_wins(self, _test_engine, monkeypatch):
        """Two presses at the same moment, each in its own transaction.

        Both look, both see nothing, both insert. `db_session` cannot show
        this: it is one connection, so the second look already sees the
        first insert. Here the unique constraint has to do the work.
        """
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        one = AsyncSession(bind=_test_engine, expire_on_commit=False)
        two = AsyncSession(bind=_test_engine, expire_on_commit=False)
        try:
            svc_one = DebatKanaalService(one, FakeMattermost())
            svc_two = DebatKanaalService(two, FakeMattermost())

            # Session two looks first and sees nothing...
            assert await svc_two._find(activiteit, TEAM) is None
            # ...then session one claims and commits...
            claimed, _ = await svc_one._claim(activiteit, TEAM, None, USER)
            assert isinstance(claimed, uuid.UUID)

            # ...and session two, still believing the way is free, inserts.
            real_find = svc_two._find
            calls = 0

            async def stale_find(activiteit, team_id):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return None
                return await real_find(activiteit, team_id)

            monkeypatch.setattr(svc_two, "_find", stale_find)
            lost, existing = await svc_two._claim(activiteit, TEAM, None, USER)

            assert lost is None
            assert existing is not None
            assert existing.id == claimed
            # And the session is usable again after the collision.
            assert len(await _sessies(two, activiteit.id)) == 1
        finally:
            await two.rollback()
            await one.rollback()
            await one.execute(
                delete(DebatSessie).where(DebatSessie.activiteit_id == activiteit.id)
            )
            await one.commit()
            await one.close()
            await two.close()


@pytest.fixture
async def real_session(_test_engine):
    """A session that really commits and really rolls back.

    `db_session` joins an outer transaction, so a rollback inside the
    service undoes the whole test and behaves unlike production. The
    failure paths below are about exactly that rollback.
    """
    session = AsyncSession(bind=_test_engine, expire_on_commit=False)
    made: list[str] = []
    try:
        yield session, made
    finally:
        await session.rollback()
        for activiteit_id in made:
            await session.execute(
                delete(DebatSessie).where(DebatSessie.activiteit_id == activiteit_id)
            )
        await session.commit()
        await session.close()


async def _press(session, mm, activiteit_id, item_id=None):
    item = SimpleNamespace(id=item_id, extra_data={"activiteit_id": activiteit_id})
    return await DebatKanaalService(session, mm).start(
        item=item,
        source_channel_id=SOURCE_CHANNEL,
        source_post_id=SOURCE_POST,
        mattermost_user_id=USER,
    )


@pytest.mark.asyncio
class TestAfterARollback:
    """A rollback expires every loaded object, and async code cannot
    reload one by touching it. These paths used to stop halfway."""

    async def test_failing_summaries_still_give_an_agenda(
        self, real_session, monkeypatch
    ):
        session, made = real_session
        activiteit = _activiteit()
        made.append(activiteit.id)
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()

        real_execute = session.execute

        async def execute(stmt, *args, **kwargs):
            if "llm_samenvatting" in str(stmt):
                # A statement that really fails in the database, so the
                # transaction is really aborted.
                await real_execute(text("SELECT 1/0"))
            return await real_execute(stmt, *args, **kwargs)

        monkeypatch.setattr(session, "execute", execute)

        result = await _press(session, mm, activiteit.id)

        assert result.outcome is StartOutcome.CREATED
        assert mm.channel_posts[0][1].startswith("#### Geagendeerde stukken")
        assert mm.members == [(result.channel_id, USER)]
        assert "staat klaar" in mm.replies[0]
        monkeypatch.undo()
        (sessie,) = await _sessies(session, activiteit.id)
        assert sessie.channel_id == result.channel_id
        assert sessie.stukken_post_id == mm.pinned[0]

    async def test_unexpected_error_releases_the_claim_and_answers(
        self, real_session, monkeypatch
    ):
        """Otherwise every press in the next five minutes gets silence."""
        session, made = real_session
        activiteit = _activiteit()
        made.append(activiteit.id)
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()
        mm.create_errors = [RuntimeError("iets onvoorziens")]

        result = await _press(session, mm, activiteit.id)

        assert result.outcome is StartOutcome.FAILED
        assert "Er ging iets mis" in mm.replies[0]
        assert await _sessies(session, activiteit.id) == []

        again = await _press(session, mm, activiteit.id)
        assert again.outcome is StartOutcome.CREATED

    async def test_error_after_the_channel_is_recorded_keeps_the_row(
        self, real_session, monkeypatch
    ):
        """The channel exists by then. Dropping the row would make the
        next press create a second one."""
        session, made = real_session
        activiteit = _activiteit()
        made.append(activiteit.id)
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()

        async def exploding(post_id):
            raise RuntimeError("pin kapot")

        monkeypatch.setattr(mm, "pin_post", exploding)

        result = await _press(session, mm, activiteit.id)

        assert result.outcome is StartOutcome.FAILED
        (sessie,) = await _sessies(session, activiteit.id)
        assert sessie.channel_id is not None
        again = await _press(session, mm, activiteit.id)
        assert again.outcome is StartOutcome.EXISTS

    async def test_item_that_no_longer_exists_is_a_failure_not_silence(
        self, real_session, monkeypatch
    ):
        """The foreign key refuses the insert. That is an IntegrityError
        too, but nobody else is busy with this debate."""
        session, made = real_session
        activiteit = _activiteit()
        made.append(activiteit.id)
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()

        result = await _press(session, mm, activiteit.id, item_id=uuid.uuid4())

        assert result.outcome is StartOutcome.FAILED
        assert mm.created == []
        assert "Er ging iets mis" in mm.replies[0]

    async def test_a_failing_team_lookup_still_answers(self, real_session, monkeypatch):
        session, made = real_session
        activiteit = _activiteit()
        _patch_fetch(monkeypatch, activiteit)
        mm = FakeMattermost()

        async def exploding(channel_id):
            raise RuntimeError("database weg")

        svc = DebatKanaalService(session, mm)
        monkeypatch.setattr(svc, "_team_of", exploding)
        result = await svc.start(
            item=SimpleNamespace(id=None, extra_data={"activiteit_id": activiteit.id}),
            source_channel_id=SOURCE_CHANNEL,
            source_post_id=SOURCE_POST,
            mattermost_user_id=USER,
        )

        assert result.outcome is StartOutcome.FAILED
        assert "Er ging iets mis" in mm.replies[0]


@pytest.mark.asyncio
class TestButtonUnderTheAlert:
    """The alert service places the reaction that is the button."""

    async def _reactions(self, start_button: bool) -> list[str]:
        from tests.test_wegklikken import _Mattermost, _svc

        mm = _Mattermost()
        await _svc(mattermost=mm)._onthoud_post(
            uuid.uuid4(), "kanaal1", "post123", start_button=start_button
        )
        return [emoji for _, emoji in mm.reacties]

    async def test_startable_alert_gets_the_headphones(self):
        assert REACTIE_UITLUISTEREN in await self._reactions(True)

    async def test_other_alerts_do_not(self):
        reactions = await self._reactions(False)
        assert REACTIE_UITLUISTEREN not in reactions
        assert reactions == ["x"]

    async def _post_alert(self, **extra) -> list[str]:
        """Run `post_alert` itself: the wiring, not only the building block."""
        from tests.test_wegklikken import (
            TestPostAlertLegtVast,
            _abonnement,
            _Mattermost,
            _Sessie,
        )
        from tests.test_wegklikken import _item as alert_item

        mm = _Mattermost(post_id="post-abc")
        svc = TestPostAlertLegtVast()._svc_met_kanaal(mm, _Sessie(), _abonnement())
        gepost = await svc.post_alert(alert_item(relevantie_score=85, **extra))
        assert gepost == 1
        return [emoji for _, emoji in mm.reacties]

    async def test_post_alert_puts_the_button_under_a_convocatie(self):
        reactions = await self._post_alert(
            categorie="vergadering_vooruit",
            soort="Convocatie commissieactiviteit",
            activiteit_id=str(uuid.uuid4()),
            activiteit_datum="2099-10-06",
            activiteit_status="Gepland",
        )
        # The megaphone is the other button, see `test_debat_aankondiging`.
        assert reactions == ["x", REACTIE_UITLUISTEREN, "mega"]

    async def test_post_alert_puts_no_button_under_a_brief(self):
        reactions = await self._post_alert(categorie="brief", soort="Brief regering")
        assert reactions == ["x"]


@pytest.mark.asyncio
class TestReactionReachesTheService:
    """From a `reaction_added` on the websocket to `DebatKanaalService`."""

    async def _dispatch(self, db_session, monkeypatch, *, emoji, post_id, user=USER):
        from bouwmeester.services import mattermost_websocket_service as ws_mod

        calls: list[dict] = []
        closed: list[bool] = []

        class FakeService:
            def __init__(self, session):
                pass

            async def start(self, **kwargs):
                calls.append(kwargs)
                return mod.StartResult(StartOutcome.CREATED)

            async def close(self):
                closed.append(True)

        monkeypatch.setattr(mod, "DebatKanaalService", FakeService)

        @asynccontextmanager
        async def _session():
            yield db_session

        monkeypatch.setattr(ws_mod, "async_session", _session)

        svc = ws_mod.MattermostWebsocketService.__new__(
            ws_mod.MattermostWebsocketService
        )
        svc._bot_user_id = BOT
        await svc._dispatch_reaction_added(
            {
                "event": "reaction_added",
                "data": {
                    "reaction": {
                        "user_id": user,
                        "post_id": post_id,
                        "emoji_name": emoji,
                    }
                },
            }
        )
        return calls, closed

    async def _alert(self, db_session) -> tuple[ParlementairItem, str]:
        item = await _item(db_session, str(uuid.uuid4()))
        post_id = f"post{uuid.uuid4().hex[:22]}"
        db_session.add(
            ParlementairAlertPost(
                parlementair_item_id=item.id,
                channel_id=SOURCE_CHANNEL,
                post_id=post_id,
            )
        )
        await db_session.flush()
        return item, post_id

    async def test_headphones_on_an_alert_starts(self, db_session, monkeypatch):
        item, post_id = await self._alert(db_session)

        calls, closed = await self._dispatch(
            db_session, monkeypatch, emoji=REACTIE_UITLUISTEREN, post_id=post_id
        )

        assert len(calls) == 1
        assert calls[0]["item"].id == item.id
        assert calls[0]["source_channel_id"] == SOURCE_CHANNEL
        assert calls[0]["source_post_id"] == post_id
        assert calls[0]["mattermost_user_id"] == USER
        assert closed == [True]

    async def test_the_bots_own_reaction_does_not_start(self, db_session, monkeypatch):
        """The bot places the button itself. If that counted, every
        convocatie would get a channel the moment it is posted."""
        _, post_id = await self._alert(db_session)

        calls, _ = await self._dispatch(
            db_session,
            monkeypatch,
            emoji=REACTIE_UITLUISTEREN,
            post_id=post_id,
            user=BOT,
        )

        assert calls == []

    async def test_headphones_on_another_post_does_nothing(
        self, db_session, monkeypatch
    ):
        calls, _ = await self._dispatch(
            db_session,
            monkeypatch,
            emoji=REACTIE_UITLUISTEREN,
            post_id="post-zonder-alert",
        )
        assert calls == []

    async def test_another_emoji_on_an_alert_does_not_start(
        self, db_session, monkeypatch
    ):
        _, post_id = await self._alert(db_session)
        calls, _ = await self._dispatch(
            db_session, monkeypatch, emoji="eyes", post_id=post_id
        )
        assert calls == []

    async def test_a_crashing_start_does_not_kill_the_read_loop(
        self, db_session, monkeypatch
    ):
        from bouwmeester.services import mattermost_websocket_service as ws_mod

        _, post_id = await self._alert(db_session)
        closed: list[bool] = []

        class Exploding:
            def __init__(self, session):
                pass

            async def start(self, **kwargs):
                raise RuntimeError("boom")

            async def close(self):
                closed.append(True)

        monkeypatch.setattr(mod, "DebatKanaalService", Exploding)

        @asynccontextmanager
        async def _session():
            yield db_session

        monkeypatch.setattr(ws_mod, "async_session", _session)
        svc = ws_mod.MattermostWebsocketService.__new__(
            ws_mod.MattermostWebsocketService
        )
        svc._bot_user_id = BOT

        handled = await svc._handle_debat_start(post_id, REACTIE_UITLUISTEREN, USER)

        assert handled is True
        assert closed == [True]


class TestChangeMessage:
    def test_new_time_names_the_old_one(self):
        nieuw = _activiteit(
            aanvang=datetime(2099, 10, 8, 10, 0, tzinfo=AMS),
            einde=datetime(2099, 10, 8, 14, 0, tzinfo=AMS),
        )
        tekst = change_message(
            nieuw,
            old_aanvang=datetime(2099, 10, 6, 16, 30, tzinfo=AMS),
            new_time=True,
            new_subject=False,
        )
        assert tekst == (
            "📅 De vergadering is gewijzigd: nu op donderdag 8 oktober, "
            "10:00 tot 14:00 (was dinsdag 6 oktober, 16:30)."
        )

    def test_new_subject_is_escaped(self):
        tekst = change_message(
            _activiteit(onderwerp="Wadden [en](http://x) meer"),
            old_aanvang=None,
            new_time=False,
            new_subject=True,
        )
        assert tekst.startswith(
            "📅 De vergadering is gewijzigd: het onderwerp is nu **"
        )
        assert "[en](http://x)" not in tekst

    def test_both(self):
        tekst = change_message(
            _activiteit(), old_aanvang=None, new_time=True, new_subject=True
        )
        assert "nu op dinsdag 6 oktober, 16:30 tot 19:30; het onderwerp is nu" in tekst
        assert "(was" not in tekst

    def test_moved_without_a_visible_difference_still_says_something(self):
        tekst = change_message(
            _activiteit(), old_aanvang=None, new_time=False, new_subject=False
        )
        assert tekst == (
            "📅 De vergadering is gewijzigd: de Kamer heeft haar opnieuw in de "
            "agenda gezet."
        )


def _moved_pair(**new_overrides) -> tuple[Activiteit, Activiteit]:
    """A meeting that was moved, as the TK API has it: the old activiteit
    stays with status Verplaatst and a note in its subject, the new date is
    a new activiteit with another id and nummer that names the old one."""
    old_id, new_id = str(uuid.uuid4()), str(uuid.uuid4())
    oud = _activiteit(
        id=old_id,
        nummer="2099A02489",
        onderwerp="Digitaliserende overheid (verplaatst naar 8 oktober 2099)",
        status="Verplaatst",
        vervangen_door=(new_id,),
    )
    values = {
        "id": new_id,
        "nummer": "2099A06595",
        "aanvang": datetime(2099, 10, 8, 10, 0, tzinfo=AMS),
        "einde": datetime(2099, 10, 8, 14, 0, tzinfo=AMS),
        "vervangen_vanuit": (old_id,),
    }
    values.update(new_overrides)
    return oud, _activiteit(**values)


async def _channel_for(session, monkeypatch, mm, activiteit) -> tuple:
    """Start the channel for `activiteit` as it stood before any change."""
    eerst = _activiteit(id=activiteit.id, nummer=activiteit.nummer)
    _patch_fetch(monkeypatch, eerst)
    item = await _item(session, activiteit.id)
    result = await _start(session, mm, item)
    assert result.outcome is StartOutcome.CREATED
    return item, result


async def _team_sessies(session: AsyncSession, *ids: str) -> list[DebatSessie]:
    # The service writes by statement, so what the session holds is old.
    # Read over it instead of expiring everything: an expired item cannot
    # be handed to `start` again.
    stmt = (
        select(DebatSessie)
        .where(DebatSessie.activiteit_id.in_(ids))
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(stmt)).scalars().all())


def _change_lines(mm: FakeMattermost) -> list[str]:
    return [t for _, t in mm.channel_posts if t.startswith("📅")]


@pytest.mark.asyncio
class TestMovedMeeting:
    """The convocatie of the new date is a convocatie for another
    activiteit. It is the same debate, so it is the same channel."""

    async def test_button_under_the_new_convocatie_finds_the_old_channel(
        self, db_session, monkeypatch
    ):
        oud, nieuw = _moved_pair()
        mm = FakeMattermost()
        _, first = await _channel_for(db_session, monkeypatch, mm, oud)
        _patch_fetch_many(monkeypatch, oud, nieuw)

        result = await _start(db_session, mm, await _item(db_session, nieuw.id))

        assert result.outcome is StartOutcome.EXISTS
        assert result.channel_id == first.channel_id
        assert len(mm.created) == 1
        assert mm.replies[-1] == (
            f"Er is al een kanaal voor dit debat: ~{first.channel_name}"
        )

    async def test_the_row_follows_the_meeting(self, db_session, monkeypatch):
        oud, nieuw = _moved_pair()
        mm = FakeMattermost()
        await _channel_for(db_session, monkeypatch, mm, oud)
        _patch_fetch_many(monkeypatch, oud, nieuw)

        await _start(db_session, mm, await _item(db_session, nieuw.id))

        (sessie,) = await _team_sessies(db_session, oud.id, nieuw.id)
        assert sessie.activiteit_id == nieuw.id
        assert sessie.activiteit_nummer == "2099A06595"
        assert sessie.aanvang == nieuw.aanvang
        assert sessie.onderwerp == "Digitaliserende overheid"

    async def test_the_channel_says_so_once(self, db_session, monkeypatch):
        oud, nieuw = _moved_pair()
        mm = FakeMattermost()
        _, first = await _channel_for(db_session, monkeypatch, mm, oud)
        _patch_fetch_many(monkeypatch, oud, nieuw)
        item = await _item(db_session, nieuw.id)

        await _start(db_session, mm, item)
        await _start(db_session, mm, item)

        assert _change_lines(mm) == [
            "📅 De vergadering is gewijzigd: nu op donderdag 8 oktober, "
            "10:00 tot 14:00 (was dinsdag 6 oktober, 16:30)."
        ]
        assert [ch for ch, t in mm.channel_posts if t.startswith("📅")] == [
            first.channel_id
        ]

    async def test_header_name_and_agenda_follow(self, db_session, monkeypatch):
        oud, nieuw = _moved_pair()
        mm = FakeMattermost()
        _, first = await _channel_for(db_session, monkeypatch, mm, oud)
        (sessie,) = await _team_sessies(db_session, oud.id)
        stukken_post_id = sessie.stukken_post_id
        _patch_fetch_many(monkeypatch, oud, nieuw)

        await _start(db_session, mm, await _item(db_session, nieuw.id))

        ((channel_id, fields),) = mm.updated
        assert channel_id == first.channel_id
        assert fields["header"] == channel_header(nieuw)
        assert "donderdag 8 oktober, 10:00 tot 14:00" in fields["header"]
        assert "2099A06595" in fields["header"]
        assert fields["display_name"] == "Digitaliserende overheid (8 okt)"
        ((post_id, bericht),) = mm.edited
        assert post_id == stukken_post_id
        assert "donderdag 8 oktober, 10:00 tot 14:00" in bericht

    async def test_only_what_differs_is_sent_to_mattermost(
        self, db_session, monkeypatch
    ):
        """Mattermost posts a system message for every header it is given."""
        oud, nieuw = _moved_pair()
        mm = FakeMattermost()
        _, first = await _channel_for(db_session, monkeypatch, mm, oud)
        mm.channels[first.channel_id] = {
            "header": "oud",
            "purpose": channel_purpose(nieuw),
            "display_name": channel_display_name(nieuw),
        }
        _patch_fetch_many(monkeypatch, oud, nieuw)

        await _start(db_session, mm, await _item(db_session, nieuw.id))

        assert mm.updated == [(first.channel_id, {"header": channel_header(nieuw)})]

    async def test_button_under_the_old_convocatie_leads_to_the_same_channel(
        self, db_session, monkeypatch
    ):
        oud, nieuw = _moved_pair()
        mm = FakeMattermost()
        old_item, first = await _channel_for(db_session, monkeypatch, mm, oud)
        asked = _patch_fetch_many(monkeypatch, oud, nieuw)

        result = await _start(db_session, mm, old_item)

        assert asked == [oud.id, nieuw.id]
        assert result.outcome is StartOutcome.EXISTS
        assert result.channel_id == first.channel_id
        (sessie,) = await _team_sessies(db_session, oud.id, nieuw.id)
        assert sessie.activiteit_id == nieuw.id
        assert len(_change_lines(mm)) == 1

    async def test_old_and_new_button_in_any_order_give_one_channel(
        self, db_session, monkeypatch
    ):
        oud, nieuw = _moved_pair()
        _patch_fetch_many(monkeypatch, oud, nieuw)
        mm = FakeMattermost()

        # Nobody started it before the move: the old button sets up the
        # channel for the new date.
        first = await _start(db_session, mm, await _item(db_session, oud.id))
        second = await _start(db_session, mm, await _item(db_session, nieuw.id))

        assert first.outcome is StartOutcome.CREATED
        assert "donderdag 8 oktober, 10:00 tot 14:00" in mm.replies[0]
        assert second.outcome is StartOutcome.EXISTS
        assert second.channel_id == first.channel_id
        (sessie,) = await _team_sessies(db_session, oud.id, nieuw.id)
        assert sessie.activiteit_id == nieuw.id
        # Started for the new date, so nothing changed since.
        assert _change_lines(mm) == []
        assert mm.updated == []

    async def test_moved_more_than_once(self, db_session, monkeypatch):
        """The meeting as it stands now names every predecessor (15 of
        107 successors have two, 4 three, 1 four)."""
        eerste, nieuw = _moved_pair()
        tweede_id = str(uuid.uuid4())
        nieuw = _activiteit(
            id=nieuw.id,
            nummer=nieuw.nummer,
            aanvang=nieuw.aanvang,
            einde=nieuw.einde,
            vervangen_vanuit=(tweede_id, eerste.id),
        )
        mm = FakeMattermost()
        _, first = await _channel_for(db_session, monkeypatch, mm, eerste)
        _patch_fetch_many(monkeypatch, eerste, nieuw)

        result = await _start(db_session, mm, await _item(db_session, nieuw.id))

        assert result.outcome is StartOutcome.EXISTS
        assert result.channel_id == first.channel_id

    async def test_the_timeline_starts_over_for_the_new_date(
        self, db_session, monkeypatch
    ):
        """On the old date the timeline said the debate was moved and
        stopped. The new date has to be followed again."""
        oud, nieuw = _moved_pair()
        mm = FakeMattermost()
        await _channel_for(db_session, monkeypatch, mm, oud)
        await db_session.execute(
            update(DebatSessie)
            .where(DebatSessie.activiteit_id == oud.id)
            .values(
                tijdlijn_status=TIJDLIJN_AFGELAST,
                tijdlijn_gecontroleerd_at=datetime.now(UTC),
                debat_direct_ids=["x"],
            )
        )
        _patch_fetch_many(monkeypatch, oud, nieuw)

        await _start(db_session, mm, await _item(db_session, nieuw.id))

        (sessie,) = await _team_sessies(db_session, nieuw.id)
        assert sessie.tijdlijn_status is None
        assert sessie.tijdlijn_gecontroleerd_at is None
        # SQL NULL, not the JSON value null: the timeline tests for NULL.
        is_null = await db_session.scalar(
            select(DebatSessie.debat_direct_ids.is_(None)).where(
                DebatSessie.id == sessie.id
            )
        )
        assert is_null is True
        assert len(_change_lines(mm)) == 1

    @pytest.mark.parametrize("status", [TIJDLIJN_GEKOPPELD, TIJDLIJN_LOOPT])
    async def test_a_debate_the_timeline_follows_is_left_alone(
        self, db_session, monkeypatch, status
    ):
        oud, nieuw = _moved_pair()
        mm = FakeMattermost()
        _, first = await _channel_for(db_session, monkeypatch, mm, oud)
        await db_session.execute(
            update(DebatSessie)
            .where(DebatSessie.activiteit_id == oud.id)
            .values(tijdlijn_status=status)
        )
        _patch_fetch_many(monkeypatch, oud, nieuw)

        result = await _start(db_session, mm, await _item(db_session, nieuw.id))

        # Still no second channel.
        assert result.outcome is StartOutcome.EXISTS
        assert result.channel_id == first.channel_id
        (sessie,) = await _team_sessies(db_session, oud.id, nieuw.id)
        assert sessie.activiteit_id == oud.id
        assert sessie.tijdlijn_status == status
        assert _change_lines(mm) == []
        assert mm.updated == []

    async def test_channel_of_the_old_date_in_another_team_is_not_this_one(
        self, db_session, monkeypatch
    ):
        oud, nieuw = _moved_pair()
        mm = FakeMattermost()
        await _channel_for(db_session, monkeypatch, mm, oud)
        _patch_fetch_many(monkeypatch, oud, nieuw)

        mm.team_id = "team00000000000000000000bb"
        result = await _start(db_session, mm, await _item(db_session, nieuw.id))

        assert result.outcome is StartOutcome.CREATED
        assert len(await _team_sessies(db_session, oud.id, nieuw.id)) == 2
        assert _change_lines(mm) == []

    async def test_archived_channel_of_the_old_date_is_set_up_again(
        self, db_session, monkeypatch
    ):
        oud, nieuw = _moved_pair()
        mm = FakeMattermost()
        _, first = await _channel_for(db_session, monkeypatch, mm, oud)
        mm.gone.add(first.channel_id)
        _patch_fetch_many(monkeypatch, oud, nieuw)

        result = await _start(db_session, mm, await _item(db_session, nieuw.id))

        assert result.outcome is StartOutcome.CREATED
        (sessie,) = await _team_sessies(db_session, oud.id, nieuw.id)
        assert sessie.activiteit_id == nieuw.id
        assert sessie.channel_id == result.channel_id != first.channel_id

    async def test_two_channels_from_before_this_rule_stay_two(
        self, db_session, monkeypatch
    ):
        """Old and new each got a channel already. The new one answers for
        itself, and the old row is not forced onto a key that is taken."""
        oud, nieuw = _moved_pair()
        mm = FakeMattermost()
        _, old_channel = await _channel_for(db_session, monkeypatch, mm, oud)
        new_item, new_channel = await _channel_for(db_session, monkeypatch, mm, nieuw)
        _patch_fetch_many(monkeypatch, oud, nieuw)

        result = await _start(db_session, mm, new_item)

        assert result.outcome is StartOutcome.EXISTS
        assert result.channel_id == new_channel.channel_id != old_channel.channel_id
        assert len(await _team_sessies(db_session, oud.id, nieuw.id)) == 2

    async def test_the_row_of_the_meeting_itself_goes_before_a_predecessor(
        self, db_session, monkeypatch
    ):
        """Also when the channel of the old date is the newer of the two:
        the unique key is on the id, so that row is the one to answer."""
        oud, nieuw = _moved_pair()
        mm = FakeMattermost()
        _, new_channel = await _channel_for(db_session, monkeypatch, mm, nieuw)
        await db_session.execute(
            update(DebatSessie)
            .where(DebatSessie.activiteit_id == nieuw.id)
            .values(created_at=datetime.now(UTC) - timedelta(days=3))
        )
        await _channel_for(db_session, monkeypatch, mm, oud)
        _patch_fetch_many(monkeypatch, oud, nieuw)

        result = await _start(db_session, mm, await _item(db_session, nieuw.id))

        assert result.outcome is StartOutcome.EXISTS
        assert result.channel_id == new_channel.channel_id

    def _moved_twice(self) -> tuple[Activiteit, Activiteit, Activiteit]:
        eerste, nieuw = _moved_pair()
        tweede = _activiteit(status="Verplaatst", vervangen_door=(nieuw.id,))
        nieuw = _activiteit(
            id=nieuw.id,
            nummer=nieuw.nummer,
            aanvang=nieuw.aanvang,
            einde=nieuw.einde,
            vervangen_vanuit=(eerste.id, tweede.id),
        )
        return eerste, tweede, nieuw

    @pytest.mark.parametrize("claim_first", [True, False])
    async def test_predecessor_with_a_channel_goes_before_a_broken_claim(
        self, db_session, monkeypatch, claim_first
    ):
        """A claim for one of the old dates that never got its channel
        must not answer with silence while another old date has one."""
        eerste, tweede, nieuw = self._moved_twice()
        mm = FakeMattermost()

        async def claim():
            db_session.add(
                DebatSessie(activiteit_id=tweede.id, onderwerp="x", team_id=TEAM)
            )
            await db_session.flush()

        if claim_first:
            await claim()
        _, first = await _channel_for(db_session, monkeypatch, mm, eerste)
        if not claim_first:
            await claim()
        _patch_fetch_many(monkeypatch, eerste, tweede, nieuw)

        result = await _start(db_session, mm, await _item(db_session, nieuw.id))

        assert result.outcome is StartOutcome.EXISTS
        assert result.channel_id == first.channel_id

    async def test_new_activiteit_at_the_same_time_still_follows(
        self, db_session, monkeypatch
    ):
        """Nothing a reader would see changed, but the agenda link in the
        header is keyed on the nummer and the timeline on the id."""
        start = datetime(2099, 10, 6, 16, 30, tzinfo=AMS)
        oud, nieuw = _moved_pair(aanvang=start, einde=start + timedelta(hours=3))
        mm = FakeMattermost()
        await _channel_for(db_session, monkeypatch, mm, oud)
        _patch_fetch_many(monkeypatch, oud, nieuw)

        await _start(db_session, mm, await _item(db_session, nieuw.id))

        (sessie,) = await _team_sessies(db_session, oud.id, nieuw.id)
        assert sessie.activiteit_id == nieuw.id
        assert _change_lines(mm) == [
            "📅 De vergadering is gewijzigd: de Kamer heeft haar opnieuw in de "
            "agenda gezet."
        ]
        ((_, fields),) = mm.updated
        assert "2099A06595" in fields["header"]

    async def test_of_two_old_channels_the_newest_answers(
        self, db_session, monkeypatch
    ):
        """Both old dates got a channel before this rule existed. The one
        people were sent to last is the one to keep sending them to."""
        eerste, tweede, nieuw = self._moved_twice()
        mm = FakeMattermost()
        await _channel_for(db_session, monkeypatch, mm, tweede)
        _, newest = await _channel_for(db_session, monkeypatch, mm, eerste)
        await db_session.execute(
            update(DebatSessie)
            .where(DebatSessie.activiteit_id == tweede.id)
            .values(created_at=datetime.now(UTC) - timedelta(days=30))
        )
        _patch_fetch_many(monkeypatch, eerste, tweede, nieuw)

        result = await _start(db_session, mm, await _item(db_session, nieuw.id))

        assert result.outcome is StartOutcome.EXISTS
        assert result.channel_id == newest.channel_id

    async def test_a_failing_update_still_gives_the_link(self, db_session, monkeypatch):
        oud, nieuw = _moved_pair()
        mm = FakeMattermost()
        _, first = await _channel_for(db_session, monkeypatch, mm, oud)
        mm.edit_error = RuntimeError("Mattermost zegt nee")
        _patch_fetch_many(monkeypatch, oud, nieuw)

        result = await _start(db_session, mm, await _item(db_session, nieuw.id))

        assert result.outcome is StartOutcome.EXISTS
        assert result.channel_id == first.channel_id
        assert mm.replies[-1].startswith("Er is al een kanaal voor dit debat")


@pytest.mark.asyncio
class TestMovedButNotCertain:
    """Where the API does not say which meeting it became, the answer is
    the one from before: start the channel for the new date yourself."""

    async def _press_old(
        self,
        db_session,
        monkeypatch,
        oud,
        *others,
        answer="Deze vergadering is verplaatst.",
    ):
        _patch_fetch_many(monkeypatch, oud, *others)
        mm = FakeMattermost()
        result = await _start(db_session, mm, await _item(db_session, oud.id))
        assert result.outcome is StartOutcome.REFUSED
        assert mm.replies[-1].startswith(answer)
        assert mm.created == []
        return result

    async def test_no_successor_named(self, db_session, monkeypatch):
        """6 of 72 moved meetings: merged, turned into a written round,
        or without a new date yet."""
        oud, _ = _moved_pair()
        oud = _activiteit(id=oud.id, status="Verplaatst")
        await self._press_old(db_session, monkeypatch, oud)

    async def test_two_successors_named(self, db_session, monkeypatch):
        oud, nieuw = _moved_pair()
        ander = _activiteit(vervangen_vanuit=(oud.id,))
        oud = _activiteit(
            id=oud.id, status="Verplaatst", vervangen_door=(nieuw.id, ander.id)
        )
        await self._press_old(db_session, monkeypatch, oud, nieuw, ander)

    async def test_successor_is_gone(self, db_session, monkeypatch):
        oud, _ = _moved_pair()
        await self._press_old(db_session, monkeypatch, oud)

    async def test_successor_is_another_kind_of_meeting(self, db_session, monkeypatch):
        """9 of 133 links: mostly a debate that became written input."""
        oud, nieuw = _moved_pair(soort="Inbreng schriftelijk overleg")
        await self._press_old(db_session, monkeypatch, oud, nieuw)

    async def test_successor_has_no_date_yet(self, db_session, monkeypatch):
        """11 of 50 moved meetings: "nieuwe datum volgt". Nothing can be
        followed on a day that is not known."""
        oud, nieuw = _moved_pair(aanvang=None, einde=None)
        await self._press_old(db_session, monkeypatch, oud, nieuw)

    async def test_a_channel_does_not_move_to_a_meeting_without_a_date(
        self, db_session, monkeypatch
    ):
        oud, nieuw = _moved_pair(aanvang=None, einde=None)
        gepland = _activiteit(id=oud.id, nummer=oud.nummer)
        _patch_fetch_many(monkeypatch, gepland)
        mm = FakeMattermost()
        first = await _start(db_session, mm, await _item(db_session, oud.id))
        assert first.outcome is StartOutcome.CREATED
        said = len(mm.messages)

        _patch_fetch_many(monkeypatch, oud, nieuw)
        await _start(db_session, mm, await _item(db_session, oud.id))

        sessie = (
            await db_session.execute(
                select(DebatSessie).where(DebatSessie.channel_id == first.channel_id)
            )
        ).scalar_one()
        assert sessie.activiteit_id == oud.id
        assert not any(
            "De vergadering is gewijzigd" in text for _, text, _ in mm.messages[said:]
        )

    async def test_successor_was_moved_again_without_saying_where(
        self, db_session, monkeypatch
    ):
        oud, nieuw = _moved_pair(status="Verplaatst")
        await self._press_old(db_session, monkeypatch, oud, nieuw)

    async def test_new_date_that_is_off_is_answered_as_itself(
        self, db_session, monkeypatch
    ):
        """What stands in the way is said about the meeting as it is now,
        the same words as under the convocatie of the new date."""
        oud, nieuw = _moved_pair(status="Geannuleerd")
        await self._press_old(
            db_session,
            monkeypatch,
            oud,
            nieuw,
            answer="Deze vergadering is geannuleerd.",
        )

    async def test_new_date_that_is_closed(self, db_session, monkeypatch):
        oud, nieuw = _moved_pair(besloten=True)
        await self._press_old(
            db_session,
            monkeypatch,
            oud,
            nieuw,
            answer="Deze vergadering is besloten",
        )

    async def test_new_date_that_is_over(self, db_session, monkeypatch):
        gisteren = datetime.now(UTC) - timedelta(days=1)
        oud, nieuw = _moved_pair(aanvang=gisteren, einde=gisteren + timedelta(hours=2))
        await self._press_old(
            db_session,
            monkeypatch,
            oud,
            nieuw,
            answer="Deze vergadering is al geweest.",
        )

    async def test_same_subject_and_committee_is_not_the_same_debate(
        self, db_session, monkeypatch
    ):
        """48 of 1000 activiteiten share subject and committee with
        another one without being linked: the debate that returns every
        half year. Each gets its own channel."""
        voorjaar = _activiteit(nummer="2099A00001")
        najaar = _activiteit(
            nummer="2099A00002", aanvang=datetime(2099, 11, 26, 10, 0, tzinfo=AMS)
        )
        mm = FakeMattermost()
        _, first = await _channel_for(db_session, monkeypatch, mm, voorjaar)
        _patch_fetch(monkeypatch, najaar)

        result = await _start(db_session, mm, await _item(db_session, najaar.id))

        assert result.outcome is StartOutcome.CREATED
        assert result.channel_id != first.channel_id
        assert _change_lines(mm) == []


@pytest.mark.asyncio
class TestSameMeetingChanged:
    """A revised convocatie on the same activiteit: 253 of 1000. The key
    already finds the channel; the channel has to hear what changed."""

    async def _changed(self, db_session, monkeypatch, **overrides):
        activiteit = _activiteit()
        mm = FakeMattermost()
        item, first = await _channel_for(db_session, monkeypatch, mm, activiteit)
        nu = _activiteit(id=activiteit.id, **overrides)
        _patch_fetch(monkeypatch, nu)
        result = await _start(db_session, mm, item)
        assert result.outcome is StartOutcome.EXISTS
        assert result.channel_id == first.channel_id
        assert len(mm.created) == 1
        (sessie,) = await _team_sessies(db_session, activiteit.id)
        return mm, item, nu, sessie

    async def test_another_time(self, db_session, monkeypatch):
        later = datetime(2099, 10, 6, 18, 0, tzinfo=AMS)
        mm, item, nu, sessie = await self._changed(
            db_session, monkeypatch, aanvang=later, einde=later + timedelta(hours=2)
        )

        assert sessie.aanvang == later
        assert _change_lines(mm) == [
            "📅 De vergadering is gewijzigd: nu op dinsdag 6 oktober, "
            "18:00 tot 20:00 (was dinsdag 6 oktober, 16:30)."
        ]
        ((_, fields),) = mm.updated
        assert "18:00 tot 20:00" in fields["header"]

        # Pressed again: nothing new to say.
        await _start(db_session, mm, item)
        assert len(_change_lines(mm)) == 1
        assert len(mm.updated) == 1

    async def test_another_subject(self, db_session, monkeypatch):
        mm, _, _, sessie = await self._changed(
            db_session, monkeypatch, onderwerp="Digitale autonomie"
        )

        assert sessie.onderwerp == "Digitale autonomie"
        assert _change_lines(mm) == [
            "📅 De vergadering is gewijzigd: het onderwerp is nu "
            "**Digitale autonomie**."
        ]

    async def test_nothing_changed_nothing_said(self, db_session, monkeypatch):
        mm, _, _, _ = await self._changed(db_session, monkeypatch)

        assert _change_lines(mm) == []
        assert mm.updated == []
        assert mm.edited == []

    async def test_only_the_agenda_changed_is_not_announced(
        self, db_session, monkeypatch
    ):
        """Known gap: the row does not keep the agenda or who comes, so a
        revision of only those cannot be told from no revision."""
        mm, _, _, _ = await self._changed(
            db_session, monkeypatch, agendapunten=(), bewindspersonen=()
        )

        assert _change_lines(mm) == []

    async def test_a_time_the_api_does_not_give_is_not_a_change(
        self, db_session, monkeypatch
    ):
        mm, _, _, sessie = await self._changed(
            db_session, monkeypatch, aanvang=None, einde=None, onderwerp=""
        )

        assert sessie.aanvang == datetime(2099, 10, 6, 16, 30, tzinfo=AMS)
        assert sessie.onderwerp == "Digitaliserende overheid"
        assert _change_lines(mm) == []

    async def test_a_missing_time_does_not_erase_the_one_we_had(
        self, db_session, monkeypatch
    ):
        """The subject did change; the time is only missing. Without a
        time the timeline would never look for this debate."""
        mm, _, _, sessie = await self._changed(
            db_session, monkeypatch, aanvang=None, einde=None, onderwerp="Wadden"
        )

        assert sessie.onderwerp == "Wadden"
        assert sessie.aanvang == datetime(2099, 10, 6, 16, 30, tzinfo=AMS)
        assert len(_change_lines(mm)) == 1

    async def test_a_missing_subject_does_not_erase_the_one_we_had(
        self, db_session, monkeypatch
    ):
        later = datetime(2099, 10, 6, 18, 0, tzinfo=AMS)
        mm, _, _, sessie = await self._changed(
            db_session, monkeypatch, aanvang=later, einde=None, onderwerp=""
        )

        assert sessie.aanvang == later
        assert sessie.onderwerp == "Digitaliserende overheid"
        assert "onderwerp" not in _change_lines(mm)[0]
        ((_, fields),) = mm.updated
        assert fields["display_name"] == "Digitaliserende overheid (6 okt)"

    @pytest.mark.parametrize(
        "status", [TIJDLIJN_GEKOPPELD, TIJDLIJN_LOOPT, TIJDLIJN_AFGELAST]
    )
    async def test_once_the_timeline_has_the_row_it_is_not_touched(
        self, db_session, monkeypatch, status
    ):
        """The timeline puts the real start in `aanvang` (up to 38 minutes
        early) and room and stream in the header. That is not a changed
        meeting, and must not be written back to the appointment."""
        activiteit = _activiteit()
        mm = FakeMattermost()
        item, _ = await _channel_for(db_session, monkeypatch, mm, activiteit)
        echt_begin = activiteit.aanvang - timedelta(minutes=20)
        await db_session.execute(
            update(DebatSessie)
            .where(DebatSessie.activiteit_id == activiteit.id)
            .values(tijdlijn_status=status, aanvang=echt_begin)
        )
        _patch_fetch(monkeypatch, activiteit)

        result = await _start(db_session, mm, item)

        assert result.outcome is StartOutcome.EXISTS
        (sessie,) = await _team_sessies(db_session, activiteit.id)
        assert sessie.aanvang == echt_begin
        assert sessie.tijdlijn_status == status
        assert _change_lines(mm) == []
        assert mm.updated == []

    async def test_same_nummer_under_another_id_is_not_matched(
        self, db_session, monkeypatch
    ):
        """Nummer and id are one to one (1000 of 1000), so the nummer is
        not a second key: only the id and the links say "same debate"."""
        activiteit = _activiteit(nummer="2099A07777")
        mm = FakeMattermost()
        await _channel_for(db_session, monkeypatch, mm, activiteit)
        opnieuw = _activiteit(nummer="2099A07777")
        _patch_fetch(monkeypatch, opnieuw)

        result = await _start(db_session, mm, await _item(db_session, opnieuw.id))

        assert result.outcome is StartOutcome.CREATED


@pytest.mark.asyncio
class TestChangeAtTheSameMoment:
    async def test_two_presses_say_it_once(self, _test_engine, monkeypatch):
        """Two people press under the new convocatie at the same moment.

        Both read the row of the old date before either writes. With one
        shared session the second would already see the first write; two
        real sessions show that the update itself has to decide.
        """
        oud, nieuw = _moved_pair()
        _patch_fetch_many(monkeypatch, oud, nieuw)
        one = AsyncSession(bind=_test_engine, expire_on_commit=False)
        two = AsyncSession(bind=_test_engine, expire_on_commit=False)
        mm = FakeMattermost()
        try:
            one.add(
                DebatSessie(
                    activiteit_id=oud.id,
                    activiteit_nummer=oud.nummer,
                    onderwerp="Digitaliserende overheid",
                    aanvang=datetime(2099, 10, 6, 16, 30, tzinfo=AMS),
                    team_id=TEAM,
                    channel_id=mm._id("chan"),
                    channel_name="debat-digitaliserende-overheid-6-okt",
                )
            )
            await one.commit()
            svc_one = DebatKanaalService(one, mm)
            svc_two = DebatKanaalService(two, mm)

            seen_one = await svc_one._find(nieuw, TEAM)
            seen_two = await svc_two._find(nieuw, TEAM)
            await two.rollback()
            assert seen_one == seen_two
            assert seen_one.activiteit_id == oud.id

            await svc_one._follow_change(seen_one, nieuw)
            await svc_two._follow_change(seen_two, nieuw)

            assert len(_change_lines(mm)) == 1
            assert len(mm.updated) == 1
            rows = await _team_sessies(two, oud.id, nieuw.id)
            assert [r.activiteit_id for r in rows] == [nieuw.id]
        finally:
            await two.rollback()
            await one.rollback()
            await one.execute(
                delete(DebatSessie).where(
                    DebatSessie.activiteit_id.in_([oud.id, nieuw.id])
                )
            )
            await one.commit()
            await one.close()
            await two.close()

    async def test_a_row_for_the_new_date_that_appeared_meanwhile_wins(
        self, _test_engine, monkeypatch
    ):
        """The row of the old date was read, and before it could follow
        the move a row for the new date was there. The unique key refuses
        the update; nothing is said and the session still works."""
        oud, nieuw = _moved_pair()
        one = AsyncSession(bind=_test_engine, expire_on_commit=False)
        mm = FakeMattermost()
        try:
            one.add(
                DebatSessie(
                    activiteit_id=oud.id,
                    onderwerp="Digitaliserende overheid",
                    aanvang=datetime(2099, 10, 6, 16, 30, tzinfo=AMS),
                    team_id=TEAM,
                    channel_id=mm._id("chan"),
                    channel_name="debat-oud",
                )
            )
            await one.commit()
            svc = DebatKanaalService(one, mm)
            seen = await svc._find(nieuw, TEAM)
            assert seen.activiteit_id == oud.id
            one.add(
                DebatSessie(
                    activiteit_id=nieuw.id,
                    onderwerp="Digitaliserende overheid",
                    aanvang=nieuw.aanvang,
                    team_id=TEAM,
                    channel_id=mm._id("chan"),
                    channel_name="debat-nieuw",
                )
            )
            await one.commit()

            await svc._follow_change(seen, nieuw)

            assert _change_lines(mm) == []
            assert mm.updated == []
            rows = await _team_sessies(one, oud.id, nieuw.id)
            assert sorted(r.channel_name for r in rows) == ["debat-nieuw", "debat-oud"]
            assert (await svc._find(nieuw, TEAM)).channel_name == "debat-nieuw"
        finally:
            await one.rollback()
            await one.execute(
                delete(DebatSessie).where(
                    DebatSessie.activiteit_id.in_([oud.id, nieuw.id])
                )
            )
            await one.commit()
            await one.close()

    async def test_old_and_new_button_at_once_make_one_channel(
        self, _test_engine, monkeypatch
    ):
        """One presses under the old convocatie, one under the new, and
        no channel exists. Both end up on the new activiteit, so the
        unique key decides as it does for two presses on one button."""
        oud, nieuw = _moved_pair()
        _patch_fetch_many(monkeypatch, oud, nieuw)
        one = AsyncSession(bind=_test_engine, expire_on_commit=False)
        two = AsyncSession(bind=_test_engine, expire_on_commit=False)
        mm = FakeMattermost()
        try:
            via_old = await _press(one, mm, oud.id)
            via_new = await _press(two, mm, nieuw.id)

            assert via_old.outcome is StartOutcome.CREATED
            assert via_new.outcome is StartOutcome.EXISTS
            assert via_new.channel_id == via_old.channel_id
            assert len(mm.created) == 1
        finally:
            await two.rollback()
            await one.rollback()
            await one.execute(
                delete(DebatSessie).where(
                    DebatSessie.activiteit_id.in_([oud.id, nieuw.id])
                )
            )
            await one.commit()
            await one.close()
            await two.close()
