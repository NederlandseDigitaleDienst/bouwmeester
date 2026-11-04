"""Tests for the decisions of a procedurevergadering in the debate channel.

First what only computes: which meeting is one, what the timeline calls
it, how the model's answer is read and how the message looks. Then the
whole thing against a real database: the message is posted once, written
again in place, replaced by the final overview at the end, and left alone
when the model fails.

All text is made up. No names of people: the chairman is "de voorzitter",
a member is "een lid".
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, timedelta

import pytest
from sqlalchemy import select

from bouwmeester.models.debat_sessie import (
    TIJDLIJN_LOOPT,
    DebatSessie,
    DebatSpreekbeurt,
)
from bouwmeester.services import debat_besluiten as mod
from bouwmeester.services import debat_direct as dd
from bouwmeester.services import tk_activiteit
from bouwmeester.services.debat_besluiten import (
    DebatBesluiten,
    meeting_text,
    render_besluiten,
)
from bouwmeester.services.debat_tijdlijn_service import format_event
from bouwmeester.services.debat_vraag_worker import DebatVraagWorker
from bouwmeester.services.llm.base import (
    DEBAT_VRAGEN_ONBEREIKBAAR,
    DEBAT_VRAGEN_ONBRUIKBAAR,
    BaseLLMService,
    DataSensitivity,
    DebatAgendapunt,
    ProviderCapabilities,
)
from bouwmeester.services.llm.prompts import build_procedurevergadering_prompt
from bouwmeester.services.mattermost_service import PostNotFoundError
from bouwmeester.services.tk_activiteit import Activiteit, Agendapunt
from tests.test_debat_tijdlijn import FULL, START, _sessie

PART = "deel-pv"
ONDERWERP = "Procedurevergadering Voorbeeldzaken"
CHAIR = (
    "Dan agendapunt 27, het overzicht van ongeplande activiteiten. Het"
    " commissiedebat over het voorbeeldbeleid op twee februari gaan we"
    " verplaatsen, de griffie zoekt een nieuwe datum. Voor de technische"
    " briefing over de voorbeeldwet hebben zich voldoende leden aangemeld,"
    " die plannen we op één december van half zes tot half zeven. Ja, dat"
    " kan. Dan agendapunt 28, de brief over de uitvoering. Een lid vraagt"
    " om een reactie van het kabinet op het rapport, daar stemt de"
    " commissie mee in. "
)


def _answer(*punten: dict, samenvatting: str = "") -> str:
    return json.dumps({"agendapunten": list(punten), "samenvatting": samenvatting})


PUNT_27 = {
    "nummer": "27",
    "onderwerp": "Overzicht ongeplande activiteiten",
    "besluiten": [
        "Commissiedebat voorbeeldbeleid (2 februari) wordt verplaatst.",
        "Technische briefing voorbeeldwet op 1 december, 17.30-18.30 uur.",
    ],
}
PUNT_28 = {
    "nummer": 28,
    "onderwerp": "Brief over de uitvoering",
    "besluiten": ["Kabinetsreactie op het rapport gevraagd."],
}


class FakeLLM(BaseLLMService):
    """A real provider, except that the text comes from a list."""

    capabilities = ProviderCapabilities(allowed_data={DataSensitivity.PUBLIC})

    def __init__(self, *answers: str | Exception) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def _complete(self, prompt: str, max_tokens: int = 1024) -> str:
        self.prompts.append(prompt)
        if not self.answers:
            return _answer()
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class Mattermost:
    """The channel: what is in it, by post id, and what is pinned."""

    def __init__(self) -> None:
        self.messages: dict[str, str] = {}
        self.order: list[str] = []
        self.pinned: set[str] = set()
        self.deleted: list[str] = []
        self.fail_sends = 0
        self.fail_updates = 0

    async def is_enabled(self) -> bool:
        return True

    async def send_channel_message(self, channel_id, text, props=None, root_id=None):
        if self.fail_sends:
            self.fail_sends -= 1
            return None
        post_id = f"post{uuid.uuid4().hex}"[:26]
        self.messages[post_id] = text
        self.order.append(post_id)
        return post_id

    async def update_post(self, post_id, message, props=None) -> bool:
        if self.fail_updates or post_id not in self.messages:
            self.fail_updates = max(0, self.fail_updates - 1)
            return False
        self.messages[post_id] = message
        return True

    async def get_post(self, post_id):
        if post_id not in self.messages:
            raise PostNotFoundError(post_id)
        return {"id": post_id}

    async def delete_post(self, post_id) -> bool:
        self.messages.pop(post_id, None)
        self.pinned.discard(post_id)
        self.deleted.append(post_id)
        return True

    async def pin_post(self, post_id) -> bool:
        self.pinned.add(post_id)
        return True

    async def close(self) -> None:
        pass


def _at(minutes: float):
    return (START + timedelta(minutes=minutes)).astimezone(UTC)


async def _meeting(db_session, **overrides) -> DebatSessie:
    values = {
        "onderwerp": ONDERWERP,
        "tijdlijn_status": TIJDLIJN_LOOPT,
        "debat_direct_ids": [PART],
    }
    values.update(overrides)
    return await _sessie(db_session, **values)


async def _start(db_session, sessie, tekst: str) -> DebatSpreekbeurt:
    """The start of the meeting, with everything the chairman said under it."""
    row = DebatSpreekbeurt(
        sessie_id=sessie.id,
        debat_direct_id=PART,
        event_type=dd.EVENT_DEBATE_START,
        event_start=START,
        object_id="",
        post_id=f"post{uuid.uuid4().hex}"[:26],
        kop="▶️ **De procedurevergadering is begonnen** · 11:00",
        tekst=tekst,
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _end(db_session, sessie, minutes: float) -> None:
    db_session.add(
        DebatSpreekbeurt(
            sessie_id=sessie.id,
            debat_direct_id=PART,
            event_type=dd.EVENT_DEBATE_END,
            event_start=START + timedelta(minutes=minutes),
            object_id="",
            post_id=f"post{uuid.uuid4().hex}"[:26],
            kop="⏹️ **De procedurevergadering is afgelopen** · 11:40",
        )
    )
    await db_session.flush()


async def _no_agenda() -> list[str]:
    return []


def _service(db_session, mm, llm) -> DebatBesluiten:
    async def provider():
        return llm

    return DebatBesluiten(db_session, mm, provider)


async def _update(db_session, mm, llm, sessie, minutes: float) -> bool:
    return await _service(db_session, mm, llm).update(
        sessie.id, ONDERWERP, _no_agenda, _at(minutes)
    )


async def _state(db_session, sessie) -> dict:
    return (
        await db_session.scalar(
            select(DebatSessie.besluiten).where(DebatSessie.id == sessie.id)
        )
    ) or {}


class TestWhichMeeting:
    @pytest.mark.parametrize(
        "kinds",
        [
            ("Procedurevergadering",),
            ("Procedurevergadering Voorbeeldzaken",),
            ("Commissiedebat", "procedurevergadering"),
            (None, "Procedurevergadering commissie voor Voorbeelden"),
        ],
    )
    def test_a_procedurevergadering(self, kinds):
        assert dd.is_procedurevergadering(*kinds)

    @pytest.mark.parametrize(
        "kinds",
        [
            ("Commissiedebat",),
            ("Plenair debat",),
            (None,),
            ("Agenda procedurevergadering",),
            ("Debat over de procedurevergadering",),
        ],
    )
    def test_not_a_procedurevergadering(self, kinds):
        assert not dd.is_procedurevergadering(*kinds)


class TestMeetingNoun:
    @pytest.mark.parametrize(
        ("debate_type", "noun"),
        [
            ("Procedurevergadering", "De procedurevergadering"),
            ("Technische briefing", "De technische briefing"),
            ("Rondetafelgesprek", "Het rondetafelgesprek"),
            ("Gesprek", "Het gesprek"),
            ("Wetgevingsoverleg", "Het wetgevingsoverleg"),
            ("Commissiedebat", "Het debat"),
            ("Plenair debat", "Het debat"),
            ("Mededelingen", "Het debat"),
            (None, "Het debat"),
        ],
    )
    def test_what_a_meeting_is_called(self, debate_type, noun):
        assert dd.meeting_noun(debate_type) == noun

    def _event(self, kind: str) -> dd.DdEvent:
        return dd.DdEvent(START, kind, "", kind)

    def test_a_procedurevergadering_is_not_a_debate_that_began(self):
        debat = dd.DdDebat(**{**FULL.__dict__, "debate_type": "Procedurevergadering"})

        begun = format_event(self._event(dd.EVENT_DEBATE_START), debat, {})
        over = format_event(self._event(dd.EVENT_DEBATE_END), debat, {})

        assert begun.startswith("▶️ **De procedurevergadering is begonnen**")
        assert over.startswith("⏹️ **De procedurevergadering is afgelopen**")

    def test_a_debate_stays_a_debate(self):
        debat = dd.DdDebat(**{**FULL.__dict__, "debate_type": "Commissiedebat"})

        begun = format_event(self._event(dd.EVENT_DEBATE_START), debat, {})

        assert begun.startswith("▶️ **Het debat is begonnen**")


@pytest.mark.asyncio
class TestReadingTheAnswer:
    async def _read(self, *answers, af: bool = False):
        llm = FakeLLM(*answers)
        result = await llm.vat_procedurevergadering_samen(
            onderwerp=ONDERWERP, agenda=[], tekst=CHAIR, eerder=[], af=af
        )
        return result, llm

    async def test_agendapunten_with_their_decisions(self):
        result, _ = await self._read(_answer(PUNT_27, PUNT_28))

        assert result.fout is None
        assert [p.nummer for p in result.agendapunten] == ["27", "28"]
        assert result.agendapunten[0].besluiten == PUNT_27["besluiten"]

    async def test_a_point_without_a_subject_is_left_out(self):
        result, _ = await self._read(
            _answer({"nummer": "1", "onderwerp": " ", "besluiten": ["x"]}, PUNT_28)
        )

        assert [p.onderwerp for p in result.agendapunten] == [PUNT_28["onderwerp"]]

    async def test_a_samenvatting_halfway_is_not_taken(self):
        result, _ = await self._read(_answer(PUNT_27, samenvatting="Klaar."))

        assert result.samenvatting == ""

    async def test_a_samenvatting_at_the_end_is(self):
        result, _ = await self._read(
            _answer(PUNT_27, samenvatting="Een debat verschuift."), af=True
        )

        assert result.samenvatting == "Een debat verschuift."

    async def test_an_unreadable_answer_is_tried_once_more(self):
        result, llm = await self._read("geen json", _answer(PUNT_27))

        assert len(llm.prompts) == 2
        assert len(result.agendapunten) == 1

    async def test_twice_unreadable_is_unusable(self):
        result, _ = await self._read("geen json", "{}")

        assert result.fout == DEBAT_VRAGEN_ONBRUIKBAAR

    async def test_a_model_that_is_away_is_unreachable(self):
        result, _ = await self._read(RuntimeError("weg"))

        assert result.fout == DEBAT_VRAGEN_ONBEREIKBAAR


class TestPrompt:
    def test_agenda_and_earlier_reading_are_in_it(self):
        prompt = build_procedurevergadering_prompt(
            onderwerp=ONDERWERP,
            agenda=["Brief over de uitvoering"],
            tekst=CHAIR,
            eerder=[("27", "Overzicht", ["Debat verplaatst."])],
            af=False,
        )

        assert "- Brief over de uitvoering" in prompt
        assert "- 27. Overzicht: Debat verplaatst." in prompt
        assert CHAIR.strip() in prompt
        assert "loopt nog" in prompt

    def test_a_long_meeting_keeps_its_end(self):
        tekst = "begin " + "x" * 50000 + " einde"

        prompt = build_procedurevergadering_prompt(
            onderwerp=ONDERWERP, agenda=[], tekst=tekst, eerder=[], af=True
        )

        assert "einde" in prompt
        assert "begin x" not in prompt
        assert "afgelopen" in prompt


class TestRender:
    def test_per_agendapunt_a_line_and_bullets(self):
        message = render_besluiten(
            [DebatAgendapunt(**PUNT_27)], af=False, bijgewerkt=_at(10)
        )

        lines = message.split("\n")
        assert lines[0].startswith("📋 **Besluiten tot nu toe** · bijgewerkt ")
        assert "**27. Overzicht ongeplande activiteiten**" in lines
        assert (
            "- Technische briefing voorbeeldwet op 1 december, 17.30-18.30 uur."
            in lines
        )
        assert message.endswith("de besluitenlijst van de commissie is leidend._")

    def test_the_final_overview_opens_with_the_samenvatting(self):
        message = render_besluiten(
            [DebatAgendapunt(**{**PUNT_28, "nummer": "28"})],
            af=True,
            samenvatting="Een kabinetsreactie gevraagd.",
        )

        lines = message.split("\n")
        assert lines[0] == "📋 **Besluiten van de procedurevergadering**"
        assert lines[1] == "Een kabinetsreactie gevraagd."

    def test_a_point_without_a_decision_says_so(self):
        message = render_besluiten([DebatAgendapunt(onderwerp="Rondvraag")], af=False)

        assert "**Rondvraag**\n- _geen besluit gehoord_" in message

    def test_what_the_model_writes_is_no_markup(self):
        message = render_besluiten(
            [DebatAgendapunt(onderwerp="Punt", besluiten=["@all **let op**"])],
            af=False,
        )

        assert "- \\@all \\*\\*let op\\*\\*" in message

    def test_never_longer_than_mattermost_takes(self):
        punten = [
            DebatAgendapunt(onderwerp=f"Punt {i}", besluiten=["x" * 400])
            for i in range(100)
        ]

        message = render_besluiten(punten, af=True)

        assert len(message) <= mod.MESSAGE_MAX
        assert message.endswith("leidend._")


@pytest.mark.asyncio
class TestOverview:
    async def test_the_text_of_the_meeting_is_what_the_chairman_said(self, db_session):
        sessie = await _meeting(db_session)
        await _start(db_session, sessie, CHAIR)

        tekst = await meeting_text(db_session, sessie.id, [PART])

        assert tekst == f"[Voorzitter] {CHAIR.strip()}"

    async def test_posted_once_and_pinned(self, db_session):
        mm, llm = Mattermost(), FakeLLM(_answer(PUNT_27))
        sessie = await _meeting(db_session)
        await _start(db_session, sessie, CHAIR)

        assert await _update(db_session, mm, llm, sessie, 5)

        state = await _state(db_session, sessie)
        assert mm.order == [state["post_id"]]
        assert mm.pinned == {state["post_id"]}
        assert (
            "**27. Overzicht ongeplande activiteiten**" in mm.messages[state["post_id"]]
        )

    async def test_not_read_again_before_there_is_more(self, db_session):
        mm, llm = Mattermost(), FakeLLM(_answer(PUNT_27))
        sessie = await _meeting(db_session)
        await _start(db_session, sessie, CHAIR)
        await _update(db_session, mm, llm, sessie, 5)

        # Later, but nothing more was said; then more, but too soon.
        assert not await _update(db_session, mm, llm, sessie, 20)
        start = await db_session.scalar(
            select(DebatSpreekbeurt).where(DebatSpreekbeurt.sessie_id == sessie.id)
        )
        start.tekst = CHAIR + "Dan agendapunt 29. " * 30
        await db_session.flush()
        assert not await _update(db_session, mm, llm, sessie, 6)

        assert len(llm.prompts) == 1

    async def test_written_again_in_place_as_more_comes_in(self, db_session):
        mm = Mattermost()
        llm = FakeLLM(_answer(PUNT_27), _answer(PUNT_27, PUNT_28))
        sessie = await _meeting(db_session)
        start = await _start(db_session, sessie, CHAIR)
        await _update(db_session, mm, llm, sessie, 5)

        start.tekst = CHAIR + "Dan agendapunt 28, de brief. " * 15
        await db_session.flush()
        assert await _update(db_session, mm, llm, sessie, 9)

        assert len(mm.order) == 1
        assert "**28. Brief over de uitvoering**" in mm.messages[mm.order[0]]
        # The model is told what it found before.
        assert "- 27. Overzicht ongeplande activiteiten:" in llm.prompts[1]

    async def test_at_the_end_the_final_overview_replaces_the_one_that_grew(
        self, db_session
    ):
        mm = Mattermost()
        llm = FakeLLM(
            _answer(PUNT_27),
            _answer(PUNT_27, PUNT_28, samenvatting="Een debat schuift op."),
        )
        sessie = await _meeting(db_session)
        await _start(db_session, sessie, CHAIR)
        await _update(db_session, mm, llm, sessie, 5)
        live = mm.order[0]
        await _end(db_session, sessie, 40)

        # Not while the last words can still come in.
        assert not await _update(db_session, mm, llm, sessie, 41)
        assert await _update(db_session, mm, llm, sessie, 44)

        state = await _state(db_session, sessie)
        assert state["af"] is True
        assert mm.deleted == [live]
        final = state["eind_post_id"]
        assert list(mm.messages) == [final]
        assert mm.pinned == {final}
        assert mm.messages[final].startswith(
            "📋 **Besluiten van de procedurevergadering**\nEen debat schuift op."
        )
        assert "afgelopen" in llm.prompts[1]

        # And that is the last of it.
        assert not await _update(db_session, mm, llm, sessie, 60)
        assert len(llm.prompts) == 2

    async def test_a_restart_does_not_post_the_final_overview_twice(self, db_session):
        """The final message is remembered before the old one goes: a worker
        that stops in between finds it on the next round."""
        mm = Mattermost()
        llm = FakeLLM(_answer(PUNT_27), _answer(PUNT_27), _answer(PUNT_27))
        sessie = await _meeting(db_session)
        await _start(db_session, sessie, CHAIR)
        await _update(db_session, mm, llm, sessie, 5)
        await _end(db_session, sessie, 40)

        async def stuck(post_id):
            return False

        mm.delete_post = stuck
        await _update(db_session, mm, llm, sessie, 44)
        del mm.delete_post
        await _update(db_session, mm, llm, sessie, 45)

        finals = [m for m in mm.messages.values() if "procedurevergadering**" in m]
        assert len(finals) == 1
        assert (await _state(db_session, sessie))["af"] is True

    async def test_a_model_that_fails_leaves_the_channel_as_it_is(self, db_session):
        mm, llm = Mattermost(), FakeLLM(RuntimeError("weg"))
        sessie = await _meeting(db_session)
        await _start(db_session, sessie, CHAIR)

        assert not await _update(db_session, mm, llm, sessie, 5)

        assert mm.order == []
        state = await _state(db_session, sessie)
        assert state["pogingen"] == 1
        # And it waits before it tries again.
        assert not await _update(db_session, mm, llm, sessie, 5.5)
        assert len(llm.prompts) == 1

    async def test_a_model_that_is_too_slow_is_a_failure(self, db_session, monkeypatch):
        class Slow(FakeLLM):
            async def _complete(self, prompt, max_tokens=1024):
                import asyncio

                await asyncio.sleep(1)
                return _answer(PUNT_27)

        monkeypatch.setattr(mod, "TIMEOUT", 0.01)
        mm = Mattermost()
        sessie = await _meeting(db_session)
        await _start(db_session, sessie, CHAIR)

        assert not await _update(db_session, mm, Slow(), sessie, 5)

        assert mm.order == []
        assert (await _state(db_session, sessie))["pogingen"] == 1

    async def test_at_the_end_it_gives_up_after_a_few_tries(self, db_session):
        mm = Mattermost()
        llm = FakeLLM(_answer(PUNT_27), *[RuntimeError("weg")] * 10)
        sessie = await _meeting(db_session)
        await _start(db_session, sessie, CHAIR)
        await _update(db_session, mm, llm, sessie, 5)
        await _end(db_session, sessie, 40)

        minute = 44.0
        for _ in range(20):
            await _update(db_session, mm, llm, sessie, minute)
            minute += 10

        state = await _state(db_session, sessie)
        assert state["af"] is True
        assert len(llm.prompts) == 1 + mod.FINAL_ATTEMPTS
        # The overview that grew stays; the transcript was never touched.
        assert list(mm.messages) == [state["post_id"]]

    async def test_a_message_someone_deleted_is_not_posted_again(self, db_session):
        mm = Mattermost()
        llm = FakeLLM(_answer(PUNT_27), _answer(PUNT_27, PUNT_28))
        sessie = await _meeting(db_session)
        start = await _start(db_session, sessie, CHAIR)
        await _update(db_session, mm, llm, sessie, 5)
        mm.messages.clear()

        start.tekst = CHAIR + "Dan agendapunt 28. " * 30
        await db_session.flush()
        await _update(db_session, mm, llm, sessie, 9)

        assert mm.messages == {}
        assert (await _state(db_session, sessie))["weg"] is True

    async def test_nothing_said_nothing_posted(self, db_session):
        mm, llm = Mattermost(), FakeLLM()
        sessie = await _meeting(db_session)
        await _start(db_session, sessie, "")
        await _end(db_session, sessie, 10)

        assert not await _update(db_session, mm, llm, sessie, 20)

        assert llm.prompts == []
        assert mm.order == []
        assert (await _state(db_session, sessie))["af"] is True


@pytest.mark.asyncio
class TestInTheWorker:
    @pytest.fixture
    def tk_api(self, monkeypatch):
        calls: list[str] = []

        async def activiteit(activiteit_id, client, base_url=None):
            calls.append(activiteit_id)
            return Activiteit(
                id=activiteit_id,
                nummer="2026A00002",
                soort="Procedurevergadering",
                onderwerp=ONDERWERP,
                aanvang=START,
                einde=None,
                status="Gepland",
                commissie=None,
                bewindspersonen=(),
                agendapunten=(
                    Agendapunt(27, "Overzicht ongeplande activiteiten", None, ()),
                ),
            )

        monkeypatch.setattr(tk_activiteit, "fetch_activiteit", activiteit)
        return calls

    async def _tick(self, db_session, mm, llm, minutes: float):
        return await DebatVraagWorker(db_session, mm, llm, {}).tick(_at(minutes))

    async def test_a_procedurevergadering_gets_its_overview(self, db_session, tk_api):
        mm, llm = Mattermost(), FakeLLM(_answer(PUNT_27))
        sessie = await _meeting(db_session)
        await _start(db_session, sessie, CHAIR)

        result = await self._tick(db_session, mm, llm, 5)

        assert result.fouten == 0
        assert len(mm.order) == 1
        assert "- Overzicht ongeplande activiteiten" in llm.prompts[0]
        assert tk_api == [sessie.activiteit_id]

    async def test_a_debate_gets_none(self, db_session, tk_api):
        mm, llm = Mattermost(), FakeLLM(_answer(PUNT_27))
        sessie = await _meeting(db_session, onderwerp="Commissiedebat Voorbeelden")
        await _start(db_session, sessie, CHAIR)

        await self._tick(db_session, mm, llm, 5)

        assert llm.prompts == []
        assert mm.order == []
        assert tk_api == []
