"""Tests for what is on right now on the debates page, and for stopping
and resuming the following of a debate.

Debat Direct, the TK API and Mattermost are stubbed at their service
boundary; the sessies are in a real database.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from bouwmeester.models.debat_sessie import (
    TIJDLIJN_AFGELAST,
    TIJDLIJN_AFGELOPEN,
    TIJDLIJN_GEKOPPELD,
    TIJDLIJN_LOOPT,
    DebatSessie,
    DebatSpreekbeurt,
)
from bouwmeester.services import debat_direct as dd
from bouwmeester.services import debat_stand
from bouwmeester.services import debat_stem as stem
from bouwmeester.services import debat_tijdlijn_service as tijdlijn_mod
from bouwmeester.services.debat_stand import (
    STAND_AFGELOPEN,
    STAND_BEZIG,
    STAND_GESCHORST,
    STAND_NIET_BEGONNEN,
    AgendaCache,
    Stand,
    parts_of,
    stand_of,
)
from bouwmeester.services.debat_tijdlijn_service import DebatTijdlijnService
from bouwmeester.services.debat_vraag_worker import DebatVraagWorker
from bouwmeester.services.mattermost_service import MattermostService
from bouwmeester.services.tk_activiteit import TkApiError, list_upcoming
from tests.test_debat_kanaal import TEAM, FakeMattermost, _activiteit
from tests.test_debatten_api import (
    NOW,
    OTHER_TEAM,
    TWO_TEAMS,
    _client,
    _row,
    _stub_agenda,
    _stub_mattermost,
    _stub_upcoming,
)

T0 = datetime(2026, 10, 6, 14, 0, tzinfo=UTC)


@pytest.fixture
async def people(db_session):
    """A reviewer with a linked Mattermost account, and people without."""
    from bouwmeester.models.mattermost_user import MattermostUser
    from tests.factories import grant_role, make_org, make_person

    org = await make_org(db_session, f"Directie {uuid.uuid4().hex[:6]}")
    reviewer = await make_person(db_session, "Reviewer")
    await grant_role(db_session, reviewer, "editor", org)
    unlinked = await make_person(db_session, "Zonder koppeling")
    await grant_role(db_session, unlinked, "editor", org)
    outsider = await make_person(db_session, "Zonder rol")
    # `viewer` carries parlementair:read and not :review.
    viewer = await make_person(db_session, "Meelezer")
    await grant_role(db_session, viewer, "viewer", org)
    db_session.add(
        MattermostUser(
            person_id=reviewer.id,
            mattermost_user_id="mmreviewer0000000000000000",
            mattermost_username="reviewer",
        )
    )
    db_session.add(
        MattermostUser(
            person_id=viewer.id,
            mattermost_user_id="mmreviewer0000000000000000"[:-1] + "1",
            mattermost_username="meelezer",
        )
    )
    await db_session.flush()
    return SimpleNamespace(
        reviewer=reviewer, unlinked=unlinked, outsider=outsider, viewer=viewer
    )


@pytest.fixture(autouse=True)
def _no_debat_direct(monkeypatch):
    _stub_agenda(monkeypatch, dd.DebatDirectError("niet in een test"))
    yield
    debat_stand.AGENDA.clear()


def _part(
    *,
    name: str = "Digitaliserende overheid",
    starts_at: datetime | None = T0,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    debate_type: str | None = "Commissiedebat",
    debate_id: str | None = None,
) -> dd.DdDebat:
    return dd.DdDebat(
        id=debate_id or str(uuid.uuid4()),
        name=name,
        slug="x",
        debate_type=debate_type,
        debate_date=None,
        starts_at=starts_at,
        started_at=started_at,
        ended_at=ended_at,
        location_id=None,
        location_name=None,
        category_ids=(),
    )


class TestStandOf:
    def test_unknown_to_debat_direct_says_nothing(self):
        assert stand_of([]) is None

    def test_planned_but_not_started(self):
        assert stand_of([_part()]) == Stand(STAND_NIET_BEGONNEN, None)

    def test_started_and_not_ended_is_running_since_its_real_start(self):
        started = T0 + timedelta(minutes=4)
        assert stand_of([_part(started_at=started)]) == Stand(STAND_BEZIG, started)

    def test_started_and_ended_is_over(self):
        part = _part(started_at=T0, ended_at=T0 + timedelta(hours=2))
        assert stand_of([part]) == Stand(STAND_AFGELOPEN, T0)

    def test_second_part_running_counts_from_the_first(self):
        first = _part(started_at=T0, ended_at=T0 + timedelta(hours=1))
        second = _part(started_at=T0 + timedelta(hours=2))
        assert stand_of([second, first]) == Stand(STAND_BEZIG, T0)

    def test_between_two_parts_is_a_break(self):
        first = _part(started_at=T0, ended_at=T0 + timedelta(hours=1))
        second = _part(starts_at=T0 + timedelta(hours=2))
        assert stand_of([first, second]) == Stand(STAND_GESCHORST, T0)

    def test_all_parts_ended_is_over(self):
        first = _part(started_at=T0, ended_at=T0 + timedelta(hours=1))
        second = _part(
            started_at=T0 + timedelta(hours=2), ended_at=T0 + timedelta(hours=3)
        )
        assert stand_of([first, second]) == Stand(STAND_AFGELOPEN, T0)


class TestPartsOf:
    def test_matches_on_subject_kind_and_start(self):
        activiteit = _activiteit(aanvang=T0)
        mine = _part()
        other = _part(name="Iets heel anders")
        assert parts_of(activiteit, [other, mine]) == [mine]

    def test_the_parts_the_timeline_found_win_from_matching(self):
        """A debate that began two hours late no longer matches its own
        planned start; the timeline knew which one it was before that."""
        activiteit = _activiteit(aanvang=T0)
        late = _part(started_at=T0 + timedelta(hours=2), debate_id="late")
        assert parts_of(activiteit, [late]) == []
        assert parts_of(activiteit, [late], {"late"}) == [late]

    def test_known_ids_that_are_not_in_the_agenda_fall_back_to_matching(self):
        activiteit = _activiteit(aanvang=T0)
        mine = _part()
        assert parts_of(activiteit, [mine], {"van-gisteren"}) == [mine]

    def test_without_a_start_nothing_is_matched_on_subject_alone(self):
        activiteit = _activiteit(aanvang=None, einde=None)
        assert parts_of(activiteit, [_part()]) == []


@pytest.mark.asyncio
class TestAgendaCache:
    def _cache(self, monkeypatch, result):
        clock = {"t": 1000.0}
        asked = _stub_agenda(monkeypatch, result)
        return AgendaCache(clock=lambda: clock["t"]), clock, asked

    async def test_reads_once_within_half_a_minute(self, monkeypatch):
        part = _part()
        cache, clock, asked = self._cache(monkeypatch, [part])

        assert await cache.today(T0) == [part]
        clock["t"] += 29.9
        assert await cache.today(T0) == [part]

        assert asked == [date(2026, 10, 6)]

    async def test_reads_again_after_half_a_minute(self, monkeypatch):
        cache, clock, asked = self._cache(monkeypatch, [])

        await cache.today(T0)
        clock["t"] += 30.0
        await cache.today(T0)

        assert len(asked) == 2

    async def test_a_new_day_is_read_at_once(self, monkeypatch):
        cache, _, asked = self._cache(monkeypatch, [])

        await cache.today(T0)
        await cache.today(T0 + timedelta(days=1))

        assert asked == [date(2026, 10, 6), date(2026, 10, 7)]

    async def test_the_day_is_the_dutch_one(self, monkeypatch):
        """23:30 UTC on the sixth is half past one on the seventh."""
        cache, _, asked = self._cache(monkeypatch, [])

        await cache.today(datetime(2026, 10, 6, 23, 30, tzinfo=UTC))

        assert asked == [date(2026, 10, 7)]

    async def test_unreachable_is_none_and_is_not_asked_again_at_once(
        self, monkeypatch
    ):
        cache, clock, asked = self._cache(monkeypatch, dd.DebatDirectError("down"))

        assert await cache.today(T0) is None
        clock["t"] += 10
        assert await cache.today(T0) is None

        assert len(asked) == 1

    async def test_requests_at_the_same_moment_share_one_reading(self, monkeypatch):
        calls = 0

        async def slow(client, day, base_url=None):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return []

        monkeypatch.setattr(dd, "fetch_agenda", slow)
        cache = AgendaCache()

        await asyncio.gather(*(cache.today(T0) for _ in range(5)))

        assert calls == 1


@pytest.mark.asyncio
class TestListUpcomingIncludeEnded:
    async def test_keeps_what_is_over_by_its_planned_end_when_asked(self):
        rows = [
            _row(
                Onderwerp="loopt uit",
                Aanvangstijd="2026-10-04T09:00:00+02:00",
                Eindtijd="2026-10-04T12:00:00+02:00",
            ),
            _row(Onderwerp="komt nog"),
        ]
        client, _ = _client(lambda r: httpx.Response(200, json={"value": rows}))

        kept = await list_upcoming(client, days=21, now=NOW, include_ended=True)
        client, _ = _client(lambda r: httpx.Response(200, json={"value": rows}))
        dropped = await list_upcoming(client, days=21, now=NOW)

        assert [a.onderwerp for a in kept] == ["loopt uit", "komt nog"]
        assert [a.onderwerp for a in dropped] == ["komt nog"]


def _today(**overrides):
    """An activiteit that started an hour ago and is planned for two more."""
    now = datetime.now(UTC).replace(microsecond=0)
    values = {"aanvang": now - timedelta(hours=1), "einde": now + timedelta(hours=2)}
    values.update(overrides)
    return _activiteit(**values)


def _sessie(activiteit, **overrides) -> DebatSessie:
    values = {
        "id": uuid.uuid4(),
        "activiteit_id": activiteit.id,
        "onderwerp": activiteit.onderwerp,
        "aanvang": activiteit.aanvang,
        "team_id": TEAM,
        "channel_id": f"chan{uuid.uuid4().hex}"[:26],
        "channel_name": "debat-digitaliserende-overheid-6-okt",
    }
    values.update(overrides)
    return DebatSessie(**values)


@pytest.mark.asyncio
class TestStandInDeLijst:
    async def test_a_running_debate_says_so_and_since_when(self, client, monkeypatch):
        activiteit = _today()
        started = activiteit.aanvang + timedelta(minutes=3)
        _stub_upcoming(monkeypatch, [activiteit])
        _stub_mattermost(monkeypatch)
        _stub_agenda(
            monkeypatch, [_part(starts_at=activiteit.aanvang, started_at=started)]
        )

        resp = await client.get("/api/debatten/aankomend")

        (debat,) = resp.json()["debatten"]
        assert debat["stand"] == "bezig"
        assert datetime.fromisoformat(debat["begonnen_om"]) == started

    async def test_a_debate_that_has_not_started(self, client, monkeypatch):
        activiteit = _today()
        _stub_upcoming(monkeypatch, [activiteit])
        _stub_mattermost(monkeypatch)
        _stub_agenda(monkeypatch, [_part(starts_at=activiteit.aanvang)])

        (debat,) = (await client.get("/api/debatten/aankomend")).json()["debatten"]

        assert debat["stand"] == "niet_begonnen"
        assert debat["begonnen_om"] is None

    async def test_what_debat_direct_does_not_know_has_no_stand(
        self, client, monkeypatch
    ):
        _stub_upcoming(monkeypatch, [_today()])
        _stub_mattermost(monkeypatch)
        _stub_agenda(monkeypatch, [_part(name="Iets heel anders")])

        (debat,) = (await client.get("/api/debatten/aankomend")).json()["debatten"]

        assert debat["stand"] is None

    async def test_without_debat_direct_the_list_still_comes(self, client, monkeypatch):
        _stub_upcoming(monkeypatch, [_today()])
        _stub_mattermost(monkeypatch)
        _stub_agenda(monkeypatch, dd.DebatDirectError("down"))

        resp = await client.get("/api/debatten/aankomend")

        assert resp.status_code == 200
        (debat,) = resp.json()["debatten"]
        assert debat["stand"] is None
        assert debat["begonnen_om"] is None

    async def test_two_requests_read_debat_direct_once(self, client, monkeypatch):
        _stub_upcoming(monkeypatch, [_today(), _today()])
        _stub_mattermost(monkeypatch)
        asked = _stub_agenda(monkeypatch, [])

        await client.get("/api/debatten/aankomend")
        await client.get("/api/debatten/aankomend")

        assert len(asked) == 1

    async def test_the_channel_says_where_the_timeline_stands(
        self, client, db_session, monkeypatch
    ):
        activiteit = _today()
        sessie = _sessie(activiteit, tijdlijn_status=TIJDLIJN_LOOPT)
        db_session.add(sessie)
        await db_session.flush()
        _stub_upcoming(monkeypatch, [activiteit])
        _stub_mattermost(monkeypatch)

        (debat,) = (await client.get("/api/debatten/aankomend")).json()["debatten"]

        (kanaal,) = debat["kanalen"]
        assert kanaal["sessie_id"] == str(sessie.id)
        assert kanaal["tijdlijn_status"] == "loopt"
        assert kanaal["wordt_gevolgd"] is True

    @pytest.mark.parametrize("tijdlijn", [TIJDLIJN_AFGELOPEN, TIJDLIJN_AFGELAST])
    async def test_a_stopped_or_cancelled_sessie_is_not_followed(
        self, client, db_session, monkeypatch, tijdlijn
    ):
        activiteit = _today()
        db_session.add(_sessie(activiteit, tijdlijn_status=tijdlijn))
        await db_session.flush()
        _stub_upcoming(monkeypatch, [activiteit])
        _stub_mattermost(monkeypatch)

        (debat,) = (await client.get("/api/debatten/aankomend")).json()["debatten"]

        assert debat["kanalen"][0]["tijdlijn_status"] == tijdlijn
        assert debat["kanalen"][0]["wordt_gevolgd"] is False

    async def test_a_debate_that_began_late_is_found_by_what_the_timeline_knows(
        self, client, db_session, monkeypatch
    ):
        activiteit = _today(aanvang=datetime.now(UTC) - timedelta(hours=3))
        late = _part(
            starts_at=activiteit.aanvang + timedelta(hours=2),
            started_at=activiteit.aanvang + timedelta(hours=2),
            debate_id="late",
        )
        db_session.add(
            _sessie(
                activiteit, tijdlijn_status=TIJDLIJN_LOOPT, debat_direct_ids=["late"]
            )
        )
        await db_session.flush()
        _stub_upcoming(monkeypatch, [activiteit])
        _stub_mattermost(monkeypatch)
        _stub_agenda(monkeypatch, [late])

        (debat,) = (await client.get("/api/debatten/aankomend")).json()["debatten"]

        assert debat["stand"] == "bezig"

    async def _with_events(self, db_session, monkeypatch, events, tijdlijn):
        activiteit = _today()
        part = _part(starts_at=activiteit.aanvang, started_at=activiteit.aanvang)
        sessie = _sessie(
            activiteit, tijdlijn_status=tijdlijn, debat_direct_ids=[part.id]
        )
        db_session.add(sessie)
        await db_session.flush()
        for kind, minutes in events:
            db_session.add(
                DebatSpreekbeurt(
                    sessie_id=sessie.id,
                    debat_direct_id=part.id,
                    event_type=kind,
                    event_start=activiteit.aanvang + timedelta(minutes=minutes),
                    object_id=kind,
                )
            )
        await db_session.flush()
        _stub_upcoming(monkeypatch, [activiteit])
        _stub_mattermost(monkeypatch)
        _stub_agenda(monkeypatch, [part])

    async def test_a_break_shows_as_suspended(self, client, db_session, monkeypatch):
        await self._with_events(
            db_session,
            monkeypatch,
            [("debate_start", 0), ("speaker", 1), ("suspended", 30)],
            TIJDLIJN_LOOPT,
        )

        (debat,) = (await client.get("/api/debatten/aankomend")).json()["debatten"]

        assert debat["stand"] == "geschorst"
        assert debat["begonnen_om"] is not None

    async def test_after_the_break_it_runs_again(self, client, db_session, monkeypatch):
        await self._with_events(
            db_session,
            monkeypatch,
            [("suspended", 30), ("continued", 45)],
            TIJDLIJN_LOOPT,
        )

        (debat,) = (await client.get("/api/debatten/aankomend")).json()["debatten"]

        assert debat["stand"] == "bezig"

    async def test_someone_speaking_after_the_break_ends_it_too(
        self, client, db_session, monkeypatch
    ):
        await self._with_events(
            db_session,
            monkeypatch,
            [("suspended", 30), ("speaker", 45)],
            TIJDLIJN_LOOPT,
        )

        (debat,) = (await client.get("/api/debatten/aankomend")).json()["debatten"]

        assert debat["stand"] == "bezig"

    async def test_the_chairman_giving_the_floor_does_not_end_a_break(
        self, client, db_session, monkeypatch
    ):
        """Only what the break itself is made of counts."""
        await self._with_events(
            db_session,
            monkeypatch,
            [("suspended", 30), ("chairman", 31)],
            TIJDLIJN_LOOPT,
        )

        (debat,) = (await client.get("/api/debatten/aankomend")).json()["debatten"]

        assert debat["stand"] == "geschorst"

    async def test_within_one_second_a_break_loses(
        self, client, db_session, monkeypatch
    ):
        await self._with_events(
            db_session,
            monkeypatch,
            [("suspended", 30), ("continued", 30)],
            TIJDLIJN_LOOPT,
        )

        (debat,) = (await client.get("/api/debatten/aankomend")).json()["debatten"]

        assert debat["stand"] == "bezig"

    async def test_a_sessie_that_was_stopped_knows_nothing_of_a_break(
        self, client, db_session, monkeypatch
    ):
        """Its last event is where it stopped listening, not where the
        debate is."""
        await self._with_events(
            db_session, monkeypatch, [("suspended", 30)], TIJDLIJN_AFGELOPEN
        )

        (debat,) = (await client.get("/api/debatten/aankomend")).json()["debatten"]

        assert debat["stand"] == "bezig"

    async def test_asks_the_agenda_for_what_is_over_by_its_plan_too(
        self, client, monkeypatch
    ):
        """Only then can a debate that runs late be on the list at all."""
        from bouwmeester.api.routes import debatten as routes

        asked: list[bool] = []

        async def fake(client, *, days, now=None, base_url=None, include_ended=False):
            asked.append(include_ended)
            return []

        monkeypatch.setattr(routes, "list_upcoming", fake)
        _stub_mattermost(monkeypatch)

        await client.get("/api/debatten/aankomend")

        assert asked == [True]

    async def test_past_its_planned_end_but_running_stays_on_the_list(
        self, client, monkeypatch
    ):
        now = datetime.now(UTC)
        activiteit = _today(
            aanvang=now - timedelta(hours=3), einde=now - timedelta(minutes=30)
        )
        _stub_upcoming(monkeypatch, [activiteit])
        _stub_mattermost(monkeypatch)
        _stub_agenda(
            monkeypatch,
            [_part(starts_at=activiteit.aanvang, started_at=activiteit.aanvang)],
        )

        debatten = (await client.get("/api/debatten/aankomend")).json()["debatten"]

        assert [d["stand"] for d in debatten] == ["bezig"]

    async def test_past_its_planned_end_and_over_is_dropped(self, client, monkeypatch):
        now = datetime.now(UTC)
        activiteit = _today(
            aanvang=now - timedelta(hours=3), einde=now - timedelta(minutes=30)
        )
        _stub_upcoming(monkeypatch, [activiteit])
        _stub_mattermost(monkeypatch)
        _stub_agenda(
            monkeypatch,
            [
                _part(
                    starts_at=activiteit.aanvang,
                    started_at=activiteit.aanvang,
                    ended_at=now - timedelta(minutes=40),
                )
            ],
        )

        assert (await client.get("/api/debatten/aankomend")).json()["debatten"] == []

    async def test_past_its_planned_end_without_debat_direct_is_dropped(
        self, client, monkeypatch
    ):
        """As it was before the page knew what is on: the plan decides."""
        now = datetime.now(UTC)
        activiteit = _today(
            aanvang=now - timedelta(hours=3), einde=now - timedelta(minutes=30)
        )
        _stub_upcoming(monkeypatch, [activiteit])
        _stub_mattermost(monkeypatch)

        assert (await client.get("/api/debatten/aankomend")).json()["debatten"] == []

    async def test_over_before_its_planned_end_stays_with_its_stand(
        self, client, monkeypatch
    ):
        activiteit = _today()
        _stub_upcoming(monkeypatch, [activiteit])
        _stub_mattermost(monkeypatch)
        _stub_agenda(
            monkeypatch,
            [
                _part(
                    starts_at=activiteit.aanvang,
                    started_at=activiteit.aanvang,
                    ended_at=activiteit.aanvang + timedelta(minutes=20),
                )
            ],
        )

        (debat,) = (await client.get("/api/debatten/aankomend")).json()["debatten"]

        assert debat["stand"] == "afgelopen"


def _record_posts(monkeypatch, ok: bool = True) -> list[tuple[str, str]]:
    posts: list[tuple[str, str]] = []

    async def send(self, channel_id, text, props=None, root_id=None):
        posts.append((channel_id, text))
        return "post0000000000000000000000" if ok else None

    monkeypatch.setattr(MattermostService, "send_channel_message", send)
    return posts


def _forbid_channel_changes(monkeypatch) -> list[str]:
    """Record anything that would change or remove the channel itself."""
    touched: list[str] = []
    for name in dir(MattermostService):
        if any(word in name for word in ("archive", "delete", "update_channel")):

            async def fail(self, *args, _name=name, **kwargs):
                touched.append(_name)

            monkeypatch.setattr(MattermostService, name, fail)
    return touched


@pytest.mark.asyncio
class TestStop:
    @pytest.mark.parametrize("tijdlijn", [None, TIJDLIJN_GEKOPPELD, TIJDLIJN_LOOPT])
    async def test_stops_a_debate_that_is_followed(
        self, client, db_session, monkeypatch, tijdlijn
    ):
        sessie = _sessie(_today(), tijdlijn_status=tijdlijn)
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch)
        posts = _record_posts(monkeypatch)
        touched = _forbid_channel_changes(monkeypatch)

        resp = await client.post(f"/api/debatten/{sessie.id}/stop")

        assert resp.status_code == 200
        assert resp.json() == {
            "sessie_id": str(sessie.id),
            "tijdlijn_status": "afgelopen",
            "wordt_gevolgd": False,
        }
        await db_session.refresh(sessie)
        assert sessie.tijdlijn_status == TIJDLIJN_AFGELOPEN
        # Without a login there is nobody to name.
        assert posts == [(sessie.channel_id, "⏹️ Het meeluisteren is gestopt.")]
        # The channel stays: with its name, and not archived.
        assert touched == []
        assert sessie.channel_id is not None
        assert sessie.channel_name == "debat-digitaliserende-overheid-6-okt"

    async def test_stopping_twice_answers_the_same_and_posts_once(
        self, client, db_session, monkeypatch
    ):
        sessie = _sessie(_today(), tijdlijn_status=TIJDLIJN_LOOPT)
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch)
        posts = _record_posts(monkeypatch)

        first = await client.post(f"/api/debatten/{sessie.id}/stop")
        second = await client.post(f"/api/debatten/{sessie.id}/stop")

        assert second.status_code == 200
        assert second.json() == first.json()
        assert len(posts) == 1

    async def test_a_cancelled_debate_stays_cancelled_and_nothing_is_said(
        self, client, db_session, monkeypatch
    ):
        sessie = _sessie(_today(), tijdlijn_status=TIJDLIJN_AFGELAST)
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch)
        posts = _record_posts(monkeypatch)

        resp = await client.post(f"/api/debatten/{sessie.id}/stop")

        assert resp.json()["tijdlijn_status"] == "afgelast"
        assert resp.json()["wordt_gevolgd"] is False
        assert posts == []

    async def test_a_message_that_fails_does_not_undo_the_stop(
        self, client, db_session, monkeypatch
    ):
        sessie = _sessie(_today(), tijdlijn_status=TIJDLIJN_LOOPT)
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch)
        _record_posts(monkeypatch, ok=False)

        resp = await client.post(f"/api/debatten/{sessie.id}/stop")

        assert resp.status_code == 200
        assert resp.json()["tijdlijn_status"] == "afgelopen"

    async def test_unknown_sessie_is_404(self, client, monkeypatch):
        _stub_mattermost(monkeypatch)
        posts = _record_posts(monkeypatch)

        resp = await client.post(f"/api/debatten/{uuid.uuid4()}/stop")

        assert resp.status_code == 404
        assert posts == []

    async def test_a_claim_without_a_channel_is_404(
        self, client, db_session, monkeypatch
    ):
        sessie = _sessie(_today(), channel_id=None, channel_name=None)
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch)
        _record_posts(monkeypatch)

        resp = await client.post(f"/api/debatten/{sessie.id}/stop")

        assert resp.status_code == 404
        await db_session.refresh(sessie)
        assert sessie.tijdlijn_status is None

    async def test_sessie_id_must_be_a_uuid(self, client, monkeypatch):
        _stub_mattermost(monkeypatch)
        assert (await client.post("/api/debatten/geen-uuid/stop")).status_code == 422

    async def test_mattermost_off_is_503(self, client, db_session, monkeypatch):
        sessie = _sessie(_today(), tijdlijn_status=TIJDLIJN_LOOPT)
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch, enabled=False)

        resp = await client.post(f"/api/debatten/{sessie.id}/stop")

        assert resp.status_code == 503
        await db_session.refresh(sessie)
        assert sessie.tijdlijn_status == TIJDLIJN_LOOPT

    async def test_the_voices_of_the_sessie_are_dropped_at_once(
        self, client, db_session, monkeypatch
    ):
        sessie = _sessie(_today(), tijdlijn_status=TIJDLIJN_LOOPT)
        other = uuid.uuid4()
        db_session.add(sessie)
        await db_session.flush()
        stem.VOICES.of(sessie.id, datetime.now(UTC))
        stem.VOICES.of(other, datetime.now(UTC))
        _stub_mattermost(monkeypatch)
        _record_posts(monkeypatch)
        try:
            await client.post(f"/api/debatten/{sessie.id}/stop")

            assert sessie.id not in stem.VOICES
            assert other in stem.VOICES
        finally:
            stem.VOICES.clear()

    async def test_the_timeline_and_the_questions_leave_it_alone(
        self, client, db_session, monkeypatch
    ):
        """What stops them is the selection of their tick: the transcript
        only runs from the timeline's."""
        now = datetime.now(UTC)
        sessie = _sessie(_today(), tijdlijn_status=TIJDLIJN_LOOPT)
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch)
        _record_posts(monkeypatch)
        advanced: list[uuid.UUID] = []

        async def advance(self, sessie_id, client, now, result):
            advanced.append(sessie_id)

        monkeypatch.setattr(tijdlijn_mod.DebatTijdlijnService, "_advance", advance)

        class Enabled(FakeMattermost):
            async def is_enabled(self) -> bool:
                return True

        try:
            await DebatTijdlijnService(db_session, Enabled()).tick(now)
            assert sessie.id in advanced
            advanced.clear()

            await client.post(f"/api/debatten/{sessie.id}/stop")

            await DebatTijdlijnService(db_session, Enabled()).tick(now)
            assert sessie.id not in advanced
            vragen = await DebatVraagWorker(db_session, Enabled()).tick(now)
            assert vragen.sessies == 0
        finally:
            stem.VOICES.clear()


@pytest.mark.asyncio
class TestStopOnBehalfOfAPerson:
    async def test_names_who_stopped_it(self, db_session, people, monkeypatch):
        from tests.factories import client_as

        sessie = _sessie(_today(), tijdlijn_status=TIJDLIJN_LOOPT)
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch, **TWO_TEAMS)
        posts = _record_posts(monkeypatch)

        async with client_as(db_session, people.reviewer) as c:
            resp = await c.post(f"/api/debatten/{sessie.id}/stop")

        assert resp.status_code == 200
        assert posts == [
            (sessie.channel_id, "⏹️ Het meeluisteren is gestopt door Reviewer.")
        ]

    async def test_a_name_cannot_inject_a_mention(
        self, db_session, people, monkeypatch
    ):
        from tests.factories import client_as

        people.reviewer.naam = "@channel [x](http://evil.test)"
        sessie = _sessie(_today(), tijdlijn_status=TIJDLIJN_LOOPT)
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch, **TWO_TEAMS)
        posts = _record_posts(monkeypatch)

        async with client_as(db_session, people.reviewer) as c:
            await c.post(f"/api/debatten/{sessie.id}/stop")

        (_, tekst) = posts[0]
        assert "@⁠channel" in tekst
        assert "@channel" not in tekst
        assert "[x]" not in tekst

    async def test_a_sessie_in_a_team_the_person_is_not_in_is_403(
        self,
        db_session,
        people,
        monkeypatch,
    ):
        from tests.factories import client_as

        sessie = _sessie(_today(), team_id=OTHER_TEAM, tijdlijn_status=TIJDLIJN_LOOPT)
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch, **TWO_TEAMS)
        posts = _record_posts(monkeypatch)

        async with client_as(db_session, people.reviewer) as c:
            stop = await c.post(f"/api/debatten/{sessie.id}/stop")
            sessie.tijdlijn_status = TIJDLIJN_AFGELOPEN
            await db_session.flush()
            hervat = await c.post(f"/api/debatten/{sessie.id}/hervat")

        assert stop.status_code == 403
        assert hervat.status_code == 403
        assert posts == []
        await db_session.refresh(sessie)
        assert sessie.tijdlijn_status == TIJDLIJN_AFGELOPEN

    async def test_without_a_linked_account_it_is_403(
        self,
        db_session,
        people,
        monkeypatch,
    ):
        from tests.factories import client_as

        sessie = _sessie(_today(), tijdlijn_status=TIJDLIJN_LOOPT)
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch, **TWO_TEAMS)
        posts = _record_posts(monkeypatch)

        async with client_as(db_session, people.unlinked) as c:
            resp = await c.post(f"/api/debatten/{sessie.id}/stop")

        assert resp.status_code == 403
        assert "Koppel je Mattermost-account" in resp.json()["detail"]
        assert posts == []

    async def test_reading_is_not_enough_to_stop_or_resume(
        self, db_session, people, monkeypatch
    ):
        """The same permission as starting: someone who may only read the
        list sees the debates and changes nothing."""
        from tests.factories import client_as

        sessie = _sessie(_today(), tijdlijn_status=TIJDLIJN_LOOPT)
        db_session.add(sessie)
        await db_session.flush()
        _stub_upcoming(monkeypatch, [])
        _stub_mattermost(monkeypatch)
        posts = _record_posts(monkeypatch)

        async with client_as(db_session, people.viewer) as c:
            lijst = await c.get("/api/debatten/aankomend")
            stop = await c.post(f"/api/debatten/{sessie.id}/stop")
            hervat = await c.post(f"/api/debatten/{sessie.id}/hervat")

        assert lijst.status_code == 200
        assert stop.status_code == 403
        assert hervat.status_code == 403
        assert posts == []
        await db_session.refresh(sessie)
        assert sessie.tijdlijn_status == TIJDLIJN_LOOPT

    async def test_without_the_permission_both_are_403(
        self,
        db_session,
        people,
        monkeypatch,
    ):
        from tests.factories import client_as

        sessie = _sessie(_today(), tijdlijn_status=TIJDLIJN_LOOPT)
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch)
        posts = _record_posts(monkeypatch)

        async with client_as(db_session, people.outsider) as c:
            stop = await c.post(f"/api/debatten/{sessie.id}/stop")
            hervat = await c.post(f"/api/debatten/{sessie.id}/hervat")

        assert stop.status_code == 403
        assert hervat.status_code == 403
        assert posts == []
        await db_session.refresh(sessie)
        assert sessie.tijdlijn_status == TIJDLIJN_LOOPT


@pytest.mark.asyncio
class TestHervat:
    async def test_a_stopped_debate_with_its_parts_is_followed_again(
        self, client, db_session, monkeypatch
    ):
        sessie = _sessie(
            _today(),
            tijdlijn_status=TIJDLIJN_AFGELOPEN,
            debat_direct_ids=["deel-1"],
            tijdlijn_gecontroleerd_at=datetime.now(UTC),
        )
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch)
        posts = _record_posts(monkeypatch)

        resp = await client.post(f"/api/debatten/{sessie.id}/hervat")

        assert resp.status_code == 200
        assert resp.json() == {
            "sessie_id": str(sessie.id),
            "tijdlijn_status": "gekoppeld",
            "wordt_gevolgd": True,
        }
        await db_session.refresh(sessie)
        # The parts are kept, and the timeline looks at once.
        assert sessie.debat_direct_ids == ["deel-1"]
        assert sessie.tijdlijn_gecontroleerd_at is None
        assert posts == [(sessie.channel_id, "▶️ Het meeluisteren is hervat.")]

    async def test_one_that_was_running_runs_again_at_once(
        self, client, db_session, monkeypatch
    ):
        """The text and the questions only look at a debate that runs. The
        timeline says so again at the next event, which in a long speech is
        a quarter of an hour away."""
        sessie = _sessie(
            _today(), tijdlijn_status=TIJDLIJN_AFGELOPEN, debat_direct_ids=["deel-1"]
        )
        db_session.add(sessie)
        await db_session.flush()
        db_session.add(
            DebatSpreekbeurt(
                sessie_id=sessie.id,
                debat_direct_id="deel-1",
                event_type="speaker",
                event_start=datetime.now(UTC),
                object_id="a",
                post_id="post0000000000000000000001",
            )
        )
        await db_session.flush()
        _stub_mattermost(monkeypatch)
        _record_posts(monkeypatch)

        resp = await client.post(f"/api/debatten/{sessie.id}/hervat")

        assert resp.json()["tijdlijn_status"] == "loopt"

    async def test_one_that_was_never_found_is_looked_for_again(
        self, client, db_session, monkeypatch
    ):
        sessie = _sessie(_today(), tijdlijn_status=TIJDLIJN_AFGELOPEN)
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch)
        _record_posts(monkeypatch)

        resp = await client.post(f"/api/debatten/{sessie.id}/hervat")

        assert resp.json()["tijdlijn_status"] is None
        assert resp.json()["wordt_gevolgd"] is True

    @pytest.mark.parametrize("tijdlijn", [None, TIJDLIJN_GEKOPPELD, TIJDLIJN_LOOPT])
    async def test_resuming_what_is_followed_changes_and_says_nothing(
        self, client, db_session, monkeypatch, tijdlijn
    ):
        checked = datetime.now(UTC).replace(microsecond=0)
        sessie = _sessie(
            _today(),
            tijdlijn_status=tijdlijn,
            debat_direct_ids=["deel-1"],
            tijdlijn_gecontroleerd_at=checked,
        )
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch)
        posts = _record_posts(monkeypatch)

        resp = await client.post(f"/api/debatten/{sessie.id}/hervat")

        assert resp.status_code == 200
        assert resp.json()["tijdlijn_status"] == tijdlijn
        assert resp.json()["wordt_gevolgd"] is True
        assert posts == []
        await db_session.refresh(sessie)
        assert sessie.tijdlijn_gecontroleerd_at == checked

    async def test_a_debate_that_ended_on_debat_direct_is_not_resumed(
        self, client, db_session, monkeypatch
    ):
        activiteit = _today()
        ended = _part(
            started_at=activiteit.aanvang,
            ended_at=activiteit.aanvang + timedelta(minutes=30),
            debate_id="deel-1",
        )
        sessie = _sessie(
            activiteit, tijdlijn_status=TIJDLIJN_AFGELOPEN, debat_direct_ids=["deel-1"]
        )
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch)
        _stub_agenda(monkeypatch, [ended])
        posts = _record_posts(monkeypatch)

        resp = await client.post(f"/api/debatten/{sessie.id}/hervat")

        assert resp.status_code == 409
        assert "afgelopen" in resp.json()["detail"]
        assert posts == []
        await db_session.refresh(sessie)
        assert sessie.tijdlijn_status == TIJDLIJN_AFGELOPEN

    async def test_a_debate_that_still_runs_on_debat_direct_is_resumed(
        self, client, db_session, monkeypatch
    ):
        activiteit = _today()
        running = _part(started_at=activiteit.aanvang, debate_id="deel-1")
        sessie = _sessie(
            activiteit, tijdlijn_status=TIJDLIJN_AFGELOPEN, debat_direct_ids=["deel-1"]
        )
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch)
        _stub_agenda(monkeypatch, [running])
        _record_posts(monkeypatch)

        resp = await client.post(f"/api/debatten/{sessie.id}/hervat")

        assert resp.status_code == 200
        assert resp.json()["wordt_gevolgd"] is True

    async def test_a_cancelled_debate_is_not_resumed(
        self, client, db_session, monkeypatch
    ):
        sessie = _sessie(_today(), tijdlijn_status=TIJDLIJN_AFGELAST)
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch)
        posts = _record_posts(monkeypatch)

        resp = await client.post(f"/api/debatten/{sessie.id}/hervat")

        assert resp.status_code == 409
        assert posts == []
        await db_session.refresh(sessie)
        assert sessie.tijdlijn_status == TIJDLIJN_AFGELAST

    async def test_unknown_sessie_is_404(self, client, monkeypatch):
        _stub_mattermost(monkeypatch)
        resp = await client.post(f"/api/debatten/{uuid.uuid4()}/hervat")
        assert resp.status_code == 404

    async def test_names_who_resumed_it(self, db_session, people, monkeypatch):
        from tests.factories import client_as

        sessie = _sessie(_today(), tijdlijn_status=TIJDLIJN_AFGELOPEN)
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch, **TWO_TEAMS)
        posts = _record_posts(monkeypatch)

        async with client_as(db_session, people.reviewer) as c:
            resp = await c.post(f"/api/debatten/{sessie.id}/hervat")

        assert resp.status_code == 200
        assert posts == [
            (sessie.channel_id, "▶️ Het meeluisteren is hervat door Reviewer.")
        ]

    async def test_stop_and_resume_and_the_timeline_takes_it_up_again(
        self, client, db_session, monkeypatch
    ):
        now = datetime.now(UTC)
        sessie = _sessie(
            _today(), tijdlijn_status=TIJDLIJN_LOOPT, debat_direct_ids=["deel-1"]
        )
        db_session.add(sessie)
        await db_session.flush()
        _stub_mattermost(monkeypatch)
        posts = _record_posts(monkeypatch)
        advanced: list[uuid.UUID] = []

        async def advance(self, sessie_id, client, now, result):
            advanced.append(sessie_id)

        monkeypatch.setattr(tijdlijn_mod.DebatTijdlijnService, "_advance", advance)

        class Enabled(FakeMattermost):
            async def is_enabled(self) -> bool:
                return True

        try:
            await client.post(f"/api/debatten/{sessie.id}/stop")
            await client.post(f"/api/debatten/{sessie.id}/hervat")
            await DebatTijdlijnService(db_session, Enabled()).tick(now)
        finally:
            stem.VOICES.clear()

        assert sessie.id in advanced
        assert [tekst for _, tekst in posts] == [
            "⏹️ Het meeluisteren is gestopt.",
            "▶️ Het meeluisteren is hervat.",
        ]


@pytest.mark.asyncio
class TestTheAgendaIsKept:
    """The page refreshes every minute. The agenda of the coming weeks does
    not change by the minute, and the Kamer is not asked for it that often."""

    def _count(self, monkeypatch, result):
        from bouwmeester.api.routes import debatten as routes

        calls: list[int] = []

        async def fake(client, *, days, include_ended=False, **kwargs):
            calls.append(days)
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(routes, "list_upcoming", fake)
        return routes, calls

    async def test_two_refreshes_are_one_request_to_the_kamer(self, monkeypatch):
        routes, calls = self._count(monkeypatch, [])

        async with httpx.AsyncClient() as client:
            first = await routes.UPCOMING.get(client, 21)
            second = await routes.UPCOMING.get(client, 21)

        assert first is second
        assert calls == [21]

    async def test_another_number_of_days_is_another_agenda(self, monkeypatch):
        routes, calls = self._count(monkeypatch, [])

        async with httpx.AsyncClient() as client:
            await routes.UPCOMING.get(client, 21)
            await routes.UPCOMING.get(client, 7)

        assert calls == [21, 7]

    async def test_after_five_minutes_it_is_read_again(self, monkeypatch):
        routes, calls = self._count(monkeypatch, [])
        clock = [1000.0]
        monkeypatch.setattr(routes.time, "monotonic", lambda: clock[0])

        async with httpx.AsyncClient() as client:
            await routes.UPCOMING.get(client, 21)
            clock[0] += routes.UPCOMING_SECONDS - 1
            await routes.UPCOMING.get(client, 21)
            assert calls == [21]
            clock[0] += 2
            await routes.UPCOMING.get(client, 21)

        assert calls == [21, 21]

    async def test_a_failure_is_not_kept(self, monkeypatch):
        routes, calls = self._count(monkeypatch, TkApiError("down"))

        async with httpx.AsyncClient() as client:
            for _ in range(2):
                with pytest.raises(TkApiError):
                    await routes.UPCOMING.get(client, 21)

        assert calls == [21, 21]

    async def test_requests_at_the_same_time_are_one_request(self, monkeypatch):
        from bouwmeester.api.routes import debatten as routes

        calls: list[int] = []

        async def slow(client, *, days, include_ended=False, **kwargs):
            calls.append(days)
            await asyncio.sleep(0.05)
            return []

        monkeypatch.setattr(routes, "list_upcoming", slow)

        async with httpx.AsyncClient() as client:
            await asyncio.gather(*(routes.UPCOMING.get(client, 21) for _ in range(5)))

        assert calls == [21]
