"""Tests for the outcome of the votes in the channel of a debate on a bill.

First what only computes: how a title of Debat Direct is read, how the votes
of both sources are counted and merged, and how the message looks. Then the
requests to both sources, against a fake transport: what is asked of the TK
API, and what happens to an answer of a shape nobody expected. Then the
whole thing against a real database: the message is posted once, written
again in place when something changed, left alone when nothing did, and
not posted again when someone took it away.

All text is made up. No names of people or of real parties: the fracties
are "Partij A" to "Partij C", a member is "het lid Voorbeeld".
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from bouwmeester.models.debat_sessie import DebatSessie
from bouwmeester.services import debat_stemmingsuitslag as mod
from bouwmeester.services.debat_stemmingsuitslag import (
    SOORT_AMENDEMENT,
    SOORT_MOTIE,
    SOORT_WETGEVING,
    SOURCE_DD,
    SOURCE_TK,
    DdActors,
    DebatDirectSource,
    DebatStemmingsuitslag,
    Fractiestem,
    SourceError,
    StemmingenTickResult,
    Uitslag,
    fetch_dossiers,
    fetch_tk_uitslagen,
    merge,
    parse_dd_actors,
    parse_dd_title,
    parse_dd_votings,
    parse_tk_uitslagen,
    render_day,
)
from bouwmeester.services.mattermost_service import PostNotFoundError

DAG = date(2026, 11, 12)
VOTE_AT = datetime(2026, 11, 12, 15, 40, tzinfo=UTC)

ACTORS = DdActors(
    parties={"pa": "Partij A", "pb": "Partij B", "pc": "Partij C"},
    members={
        **{f"a{i}": "pa" for i in range(5)},
        **{f"b{i}": "pb" for i in range(3)},
        **{f"c{i}": "pc" for i in range(2)},
    },
)


def _round(title: str, result: str, votes: list, *, soort="Fractie", at=VOTE_AT):
    return {
        "type": soort,
        "title": title,
        "result": result,
        "startedAt": at.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "votes": votes,
    }


def _voting(*rounds: dict, subject: str = "Een voorbeeldwet (37999)") -> dict:
    return {"votings": [{"subject": subject, "votingRounds": list(rounds)}]}


def _uitslag(**overrides) -> Uitslag:
    values = {
        "source": SOURCE_TK,
        "zaak_soort": SOORT_AMENDEMENT,
        "onderwerp": "Amendement van het lid Voorbeeld over een voorbeeld",
        "dossier": "37999",
        "volgnummer": 12,
        "outcome": mod.OUTCOME_AANGENOMEN,
        "besluit_tekst": "Aangenomen.",
        "hoofdelijk": False,
        "moment": VOTE_AT,
        "zaak_nummer": "2026Z00001",
        "document_nummer": "2026D00001",
    }
    values.update(overrides)
    return Uitslag(**values)


class TestDdTitle:
    def test_an_amendement_with_its_number(self):
        title = parse_dd_title(
            "het amendement-Voorbeeld over een voorbeeld (37999, nr. 12)"
        )
        assert (title.zaak_soort, title.dossier, title.volgnummer) == (
            SOORT_AMENDEMENT,
            "37999",
            12,
        )
        assert title.replaces is None
        assert title.onderwerp == "Amendement-Voorbeeld over een voorbeeld"

    def test_a_dossier_with_a_toevoeging(self):
        title = parse_dd_title("de motie-Voorbeeld over iets (37020-XVI, nr. 91)")
        assert (title.dossier, title.volgnummer) == ("37020-XVI", 91)

    def test_a_changed_motie_without_a_number_yet(self):
        title = parse_dd_title(
            "de gewijzigde motie-Voorbeeld c.s. over iets (37999, nr. ??, was nr. 36)"
        )
        assert (title.zaak_soort, title.volgnummer, title.replaces) == (
            SOORT_MOTIE,
            None,
            36,
        )

    def test_a_bill_and_an_initiatiefwetsvoorstel(self):
        bill = parse_dd_title("het wetsvoorstel Een wet (37999)")
        initiatief = parse_dd_title("het initiatiefwetsvoorstel Een wet (37999)")
        assert bill.zaak_soort == SOORT_WETGEVING
        assert initiatief.zaak_soort == SOORT_WETGEVING

    def test_the_last_kenmerk_counts(self):
        title = parse_dd_title(
            "de motie-Voorbeeld over de uitvoering van (36000, nr. 5) (37999, nr. 40)"
        )
        assert (title.dossier, title.volgnummer) == ("37999", 40)


class TestDdVotings:
    def test_a_vote_per_fractie_counts_its_seats(self):
        raw = _voting(
            _round(
                "het amendement-Voorbeeld over een voorbeeld (37999, nr. 12)",
                "Aangenomen",
                [["PA", "Voor"], ["pb", "Tegen"], ["pc", "Voor"]],
            )
        )
        [u] = parse_dd_votings(raw, ACTORS, {"37999"})
        assert u.outcome == mod.OUTCOME_AANGENOMEN
        assert (u.total("Voor"), u.total("Tegen")) == (7, 3)
        assert u.fracties("Voor") == ["Partij A", "Partij C"]

    def test_members_of_government_carry_no_seat(self):
        actors = parse_dd_actors(
            {
                "parties": [{"id": "PA", "shorthand": "Partij A"}],
                "politicians": [
                    {"id": "a0", "partyId": "PA"},
                    {"id": "a1", "partyId": "PA"},
                    {"id": "m0", "title": "Minister van Voorbeelden"},
                ],
            }
        )
        assert actors.seats("pa") == 2

    def test_a_hoofdelijke_stemming_counts_members_and_splits(self):
        votes = [[f"a{i}", "Voor"] for i in range(3)] + [
            ["a3", "Tegen"],
            ["a4", "Onbekend"],
            ["b0", "Tegen"],
            ["b1", "Tegen"],
        ]
        raw = _voting(
            _round(
                "de motie-Voorbeeld over iets (37999, nr. 20)",
                "Verworpen",
                votes,
                soort="Hoofd",
            )
        )
        [u] = parse_dd_votings(raw, ACTORS, {"37999"})
        assert u.hoofdelijk
        assert (u.total("Voor"), u.total("Tegen")) == (3, 3)
        assert u.fracties("Voor") == ["Partij A 3 van 4"]

    def test_a_tie_then_a_hoofdelijke_stemming_keeps_the_last(self):
        title = "de motie-Voorbeeld over iets (37999, nr. 20)"
        raw = _voting(
            _round(title, "Staken", [["pa", "Voor"], ["pb", "Tegen"]]),
            _round(
                title,
                "Aangenomen",
                [["a0", "Voor"]],
                soort="Hoofd",
                at=VOTE_AT + timedelta(minutes=5),
            ),
        )
        [u] = parse_dd_votings(raw, ACTORS, {"37999"})
        assert u.outcome == mod.OUTCOME_AANGENOMEN
        assert u.hoofdelijk

    def test_other_dossiers_are_left_out(self):
        raw = _voting(
            _round("de motie-Voorbeeld over iets (36000, nr. 3)", "Verworpen", [])
        )
        assert parse_dd_votings(raw, ACTORS, {"37999"}) == []

    def test_a_cut_off_title_takes_the_dossier_from_the_subject(self):
        raw = _voting(
            _round("het wetsvoorstel Een voorbeeldwet die...", "Aangenomen", [])
        )
        [u] = parse_dd_votings(raw, ACTORS, {"37999"})
        assert (u.zaak_soort, u.dossier) == (SOORT_WETGEVING, "37999")

    @pytest.mark.parametrize(
        "raw",
        [None, [], {"votings": None}, {"votings": [{"votingRounds": "x"}]}],
    )
    def test_an_unexpected_shape_reads_as_nothing(self, raw):
        assert parse_dd_votings(raw, ACTORS, {"37999"}) == []

    @pytest.mark.parametrize("raw", [None, [], {"parties": "x", "politicians": 3}])
    def test_actors_of_an_unexpected_shape_read_as_nobody(self, raw):
        assert parse_dd_actors(raw) == DdActors({}, {})


def _besluit(**overrides) -> dict:
    row = {
        "Id": str(uuid.uuid4()),
        "BesluitSoort": "Stemmen - verworpen",
        "BesluitTekst": "Verworpen.",
        "StemmingsSoort": "Met handopsteken",
        "GewijzigdOp": "2026-11-12T16:50:00+01:00",
        "Stemming": [
            {"Soort": "Voor", "FractieGrootte": 5, "ActorFractie": "Partij A"},
            {"Soort": "Tegen", "FractieGrootte": 3, "ActorFractie": "Partij B"},
            {"Soort": "Tegen", "FractieGrootte": 2, "ActorFractie": "Partij C"},
        ],
        "Zaak": [
            {
                "Nummer": "2026Z00001",
                "Soort": "Motie",
                "Onderwerp": "Motie van het lid Voorbeeld over iets",
                "Volgnummer": 20,
                "Kamerstukdossier": [{"Nummer": 37999, "Toevoeging": None}],
                "Document": [{"DocumentNummer": "2026D00001", "Volgnummer": 20}],
            }
        ],
        "Agendapunt": {
            "Activiteit": {
                "Id": "act-1",
                "Datum": "2026-11-12T00:00:00+01:00",
                "Aanvangstijd": None,
            }
        },
    }
    row.update(overrides)
    return row


class TestTk:
    def test_a_besluit_with_its_votes(self):
        [u] = parse_tk_uitslagen([_besluit()], {"37999"})
        assert (u.zaak_soort, u.dossier, u.volgnummer) == (SOORT_MOTIE, "37999", 20)
        assert u.outcome == mod.OUTCOME_VERWORPEN
        assert u.day == DAG
        assert (u.total("Voor"), u.total("Tegen")) == (5, 5)

    def test_the_latest_besluit_on_a_zaak_wins(self):
        later = _besluit(
            BesluitSoort="Stemmen - aangenomen",
            GewijzigdOp="2026-11-12T17:30:00+01:00",
        )
        [u] = parse_tk_uitslagen([later, _besluit()], {"37999"})
        assert u.outcome == mod.OUTCOME_AANGENOMEN

    def test_what_a_changed_motie_replaces(self):
        row = _besluit()
        row["Zaak"][0]["Onderwerp"] = "Gewijzigde motie over iets (t.v.v. 37999-18)"
        [u] = parse_tk_uitslagen([row], {"37999"})
        assert u.replaces == 18

    def test_an_initiatiefwetsvoorstel_is_a_bill(self):
        row = _besluit()
        row["Zaak"][0].update(Soort="Initiatiefwetgeving", Volgnummer=None)
        [u] = parse_tk_uitslagen([row], {"37999"})
        assert u.zaak_soort == SOORT_WETGEVING
        assert u.key == ("37999", "wet")


class TestMerge:
    def test_the_tk_besluit_takes_the_votes_of_debat_direct(self):
        tk = _uitslag(votes=())
        live = _uitslag(
            source=SOURCE_DD,
            document_nummer=None,
            votes=(Fractiestem("Partij A", "Voor", 5),),
        )
        [u] = merge([tk], [live])
        assert u.source == SOURCE_TK
        assert u.document_nummer == "2026D00001"
        assert u.total("Voor") == 5

    def test_votes_of_the_tk_api_stay(self):
        tk = _uitslag(votes=(Fractiestem("Partij A", "Voor", 5),))
        live = _uitslag(source=SOURCE_DD, votes=(Fractiestem("Partij B", "Voor", 3),))
        [u] = merge([tk], [live])
        assert u.fracties("Voor") == ["Partij A"]

    def test_debat_direct_alone_before_the_tk_api_has_it(self):
        [u] = merge([], [_uitslag(source=SOURCE_DD)])
        assert u.source == SOURCE_DD

    def test_a_changed_motie_without_a_number_matches_by_what_it_replaces(self):
        tk = _uitslag(zaak_soort=SOORT_MOTIE, volgnummer=45, replaces=42)
        live = _uitslag(
            source=SOURCE_DD,
            zaak_soort=SOORT_MOTIE,
            volgnummer=None,
            replaces=42,
            onderwerp="Gewijzigde motie-Voorbeeld c.s. over iets anders geschreven",
        )
        assert len(merge([tk], [live])) == 1

    def test_or_by_what_it_is_about(self):
        tk = _uitslag(
            zaak_soort=SOORT_MOTIE,
            volgnummer=45,
            onderwerp="Gewijzigde motie van de leden A en B over iets (t.v.v. x)",
        )
        live = _uitslag(
            source=SOURCE_DD,
            zaak_soort=SOORT_MOTIE,
            volgnummer=None,
            onderwerp="Gewijzigde motie-Voorbeeld c.s. over iets",
        )
        assert len(merge([tk], [live])) == 1

    def test_one_that_does_not_match_goes_once_the_tk_api_has_its_dossier(self):
        live = _uitslag(
            source=SOURCE_DD,
            zaak_soort=SOORT_MOTIE,
            volgnummer=None,
            onderwerp="Gewijzigde motie-Voorbeeld over A en B",
        )
        # Before the TK API has anything that day: shown.
        assert len(merge([], [live])) == 1
        # After: the TK API has it under its own words, so not twice.
        tk = _uitslag(
            zaak_soort=SOORT_MOTIE,
            volgnummer=45,
            onderwerp="Gewijzigde motie van het lid Voorbeeld over A, B",
        )
        assert merge([tk], [live]) == [tk]


class TestRender:
    def test_the_message(self):
        [message] = render_day(
            DAG,
            [
                _uitslag(votes=(Fractiestem("Partij A", "Voor", 5),)),
                _uitslag(
                    zaak_soort=SOORT_MOTIE,
                    volgnummer=20,
                    outcome=mod.OUTCOME_VERWORPEN,
                ),
                _uitslag(zaak_soort=SOORT_WETGEVING, volgnummer=None),
            ],
        )
        assert message.startswith("🗳️ **Stemmingen van donderdag 12 november**")
        assert "2 aangenomen, 1 verworpen" in message
        # Bills first, then amendementen, then moties.
        assert (
            message.index("**Wetsvoorstellen**")
            < message.index("**Amendementen**")
            < message.index("**Moties**")
        )
        assert (
            "[37999, nr. 12](https://www.tweedekamer.nl/kamerstukken/detail" in message
        )
        assert "voor 5, tegen 0 · voor: Partij A" in message
        assert "stemmen per fractie ontbreken, volgen die later" in message

    def test_a_long_day_is_cut_into_messages_under_the_limit(self, monkeypatch):
        monkeypatch.setattr(mod, "MESSAGE_MAX", 1200)
        items = [_uitslag(volgnummer=n) for n in range(1, 40)]
        messages = render_day(DAG, items)
        assert len(messages) > 1
        assert all(len(m) <= 1200 for m in messages)
        assert messages[1].startswith(
            "🗳️ **Stemmingen van donderdag 12 november** (vervolg)"
        )
        assert sum(m.count("\n- ") for m in messages) == 39


# --- The requests -----------------------------------------------------------


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
class TestRequests:
    async def test_what_is_asked_of_the_tk_api(self):
        asked: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            asked.append(request)
            return httpx.Response(200, json={"value": [_besluit()]})

        async with _client(handler) as client:
            [u] = await fetch_tk_uitslagen(
                ["37999", "37020-XVI"], date(2026, 11, 10), client, "https://tk"
            )

        assert u.volgnummer == 20
        [request] = asked
        assert request.url.path == "/Besluit"
        condition = request.url.params["$filter"]
        assert "startswith(BesluitSoort,'Stemmen - ')" in condition
        assert "Agendapunt/Activiteit/Datum ge 2026-11-10" in condition
        assert (
            "Zaak/any(z: z/Kamerstukdossier/any(k: "
            "(k/Nummer eq 37999 and k/Toevoeging eq null) or "
            "(k/Nummer eq 37020 and k/Toevoeging eq 'XVI')))"
        ) in condition
        assert "Stemming(" in request.url.params["$expand"]

    async def test_the_tk_api_follows_the_next_page(self):
        second = _besluit()
        second["Zaak"][0]["Volgnummer"] = 21
        pages = iter(
            [
                {"value": [_besluit()], "@odata.nextLink": "https://tk/Besluit?p=2"},
                {"value": [second]},
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=next(pages))

        async with _client(handler) as client:
            found = await fetch_tk_uitslagen(["37999"], DAG, client, "https://tk")
        assert sorted(u.volgnummer for u in found) == [20, 21]

    async def test_the_dossiers_of_the_bills_on_the_agenda(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/Agendapunt"
            zaken = [
                {"Soort": "Wetgeving", "Kamerstukdossier": [{"Nummer": 37999}]},
                {
                    "Soort": "Initiatiefwetgeving",
                    "Kamerstukdossier": [{"Nummer": 37020, "Toevoeging": "XVI"}],
                },
                {"Soort": "Brief regering", "Kamerstukdossier": [{"Nummer": 29999}]},
            ]
            return httpx.Response(200, json={"value": [{"Zaak": zaken}]})

        async with _client(handler) as client:
            found = await fetch_dossiers(str(uuid.uuid4()), client, "https://tk")
        assert found == ["37020-XVI", "37999"]

    async def test_a_tk_api_that_fails_is_a_source_error(self):
        async with _client(lambda r: httpx.Response(500)) as client:
            with pytest.raises(SourceError):
                await fetch_tk_uitslagen(["37999"], DAG, client, "https://tk")

    async def test_debat_direct_of_an_unexpected_shape_is_a_source_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.startswith("/agenda/"):
                debate = {
                    "id": "dd-1",
                    "name": "Stemmingen",
                    "debateType": "Stemmingen",
                    "startedAt": "2026-11-12T16:30:00+0100",
                }
                return httpx.Response(200, json={"debates": [debate]})
            # The debate itself comes back as a list.
            return httpx.Response(200, content=json.dumps([1, 2]))

        async with _client(handler) as client:
            source = DebatDirectSource(client, "https://dd")
            with pytest.raises(SourceError):
                await source.uitslagen(["37999"], [DAG])
            # Not asked again in the same round.
            with pytest.raises(SourceError):
                await source.blocks(DAG)


# --- In the channel ---------------------------------------------------------


class Mattermost:
    def __init__(self) -> None:
        self.messages: dict[str, str] = {}
        self.order: list[str] = []
        self.pinned: set[str] = set()
        self.updates = 0
        self.fail_pins = 0
        self.fail_deletes = 0

    async def is_enabled(self) -> bool:
        return True

    async def send_channel_message(self, channel_id, text, props=None, root_id=None):
        post_id = f"post{uuid.uuid4().hex}"[:26]
        self.messages[post_id] = text
        self.order.append(post_id)
        return post_id

    async def update_post(self, post_id, message, props=None) -> bool:
        if post_id not in self.messages:
            return False
        self.messages[post_id] = message
        self.updates += 1
        return True

    async def get_post(self, post_id):
        if post_id not in self.messages:
            raise PostNotFoundError(post_id)
        return {"id": post_id}

    async def delete_post(self, post_id) -> bool:
        if self.fail_deletes:
            self.fail_deletes -= 1
            return False
        self.messages.pop(post_id, None)
        return True

    async def pin_post(self, post_id) -> bool:
        if self.fail_pins:
            self.fail_pins -= 1
            return False
        self.pinned.add(post_id)
        return True

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
class TestInTheChannel:
    @pytest.fixture
    def sources(self, monkeypatch):
        state = {
            "dossiers": ["37999"],
            "tk": [],
            "dd": [],
            "dd_fails": False,
            "dossier_calls": 0,
        }

        async def dossiers(activiteit_id, client, base_url=None):
            state["dossier_calls"] += 1
            return list(state["dossiers"])

        async def tk(dossiers, since, client, base_url=None):
            return list(state["tk"])

        async def live(self, dossiers, days):
            if state["dd_fails"]:
                raise SourceError("onbereikbaar")
            return list(state["dd"])

        monkeypatch.setattr(mod, "fetch_dossiers", dossiers)
        monkeypatch.setattr(mod, "fetch_tk_uitslagen", tk)
        monkeypatch.setattr(mod.DebatDirectSource, "uitslagen", live)
        return state

    async def _sessie(self, db_session) -> DebatSessie:
        sessie = DebatSessie(
            activiteit_id=str(uuid.uuid4()),
            activiteit_nummer="2026A00001",
            onderwerp="Een voorbeeldwet",
            aanvang=VOTE_AT - timedelta(hours=5),
            team_id="team00000000000000000000aa",
            channel_id=f"chan{uuid.uuid4().hex}"[:26],
            channel_name="debat-test",
        )
        db_session.add(sessie)
        await db_session.flush()
        return sessie

    async def _update(self, db_session, mm, sessie, minutes: float):
        result = StemmingenTickResult()
        await DebatStemmingsuitslag(db_session, mm).update(
            sessie.id,
            VOTE_AT + timedelta(minutes=minutes),
            None,
            DebatDirectSource(None),
            result,
        )
        return result

    async def test_nothing_voted_nothing_posted(self, db_session, sources):
        mm = Mattermost()
        sessie = await self._sessie(db_session)
        await self._update(db_session, mm, sessie, 0)
        assert mm.order == []

    async def test_posted_once_pinned_and_written_again_in_place(
        self, db_session, sources
    ):
        mm = Mattermost()
        sessie = await self._sessie(db_session)
        sources["dd"] = [_uitslag(source=SOURCE_DD)]
        await self._update(db_session, mm, sessie, 0)
        assert len(mm.order) == 1
        assert mm.pinned == {mm.order[0]}

        # Nothing new: not written again, although the time moved on.
        await self._update(db_session, mm, sessie, 3)
        assert mm.updates == 0

        # The second vote of the day: the same message.
        sources["dd"].append(_uitslag(source=SOURCE_DD, volgnummer=13))
        await self._update(db_session, mm, sessie, 6)
        assert len(mm.order) == 1
        assert mm.updates == 1
        assert "nr. 13" in mm.messages[mm.order[0]]

    async def test_waits_between_rounds(self, db_session, sources):
        mm = Mattermost()
        sessie = await self._sessie(db_session)
        await self._update(db_session, mm, sessie, 0)
        sources["dd"] = [_uitslag(source=SOURCE_DD)]
        await self._update(db_session, mm, sessie, 1)
        assert mm.order == []
        await self._update(db_session, mm, sessie, 2)
        assert len(mm.order) == 1

    async def test_a_message_someone_deleted_is_not_posted_again(
        self, db_session, sources
    ):
        mm = Mattermost()
        sessie = await self._sessie(db_session)
        sources["dd"] = [_uitslag(source=SOURCE_DD)]
        await self._update(db_session, mm, sessie, 0)
        mm.messages.clear()

        sources["dd"].append(_uitslag(source=SOURCE_DD, volgnummer=13))
        await self._update(db_session, mm, sessie, 3)
        await self._update(db_session, mm, sessie, 6)
        assert mm.messages == {}
        assert len(mm.order) == 1

    async def test_without_debat_direct_the_tk_api_is_posted(self, db_session, sources):
        mm = Mattermost()
        sessie = await self._sessie(db_session)
        sources["dd_fails"] = True
        sources["tk"] = [_uitslag()]
        result = await self._update(db_session, mm, sessie, 0)
        assert len(mm.order) == 1
        assert result.errors == 1

    async def test_without_debat_direct_no_line_is_dropped(self, db_session, sources):
        mm = Mattermost()
        sessie = await self._sessie(db_session)
        sources["tk"] = [_uitslag()]
        sources["dd"] = [_uitslag(source=SOURCE_DD, volgnummer=13)]
        await self._update(db_session, mm, sessie, 0)
        assert "nr. 13" in mm.messages[mm.order[0]]

        # Debat Direct away: the TK API alone has fewer lines. Left as it is.
        sources["dd_fails"] = True
        await self._update(db_session, mm, sessie, 3)
        assert "nr. 13" in mm.messages[mm.order[0]]
        assert mm.updates == 0

        # The TK API catches up: written with what it has.
        sources["tk"].append(_uitslag(volgnummer=13, outcome=mod.OUTCOME_VERWORPEN))
        await self._update(db_session, mm, sessie, 6)
        assert mm.updates == 1
        assert "Verworpen" in mm.messages[mm.order[0]]

    async def test_a_pin_that_failed_is_tried_again(self, db_session, sources):
        mm = Mattermost()
        mm.fail_pins = 1
        sessie = await self._sessie(db_session)
        sources["dd"] = [_uitslag(source=SOURCE_DD)]
        await self._update(db_session, mm, sessie, 0)
        assert mm.pinned == set()
        await self._update(db_session, mm, sessie, 3)
        assert mm.pinned == {mm.order[0]}

    async def test_a_leftover_message_that_did_not_go_is_tried_again(
        self, db_session, sources, monkeypatch
    ):
        monkeypatch.setattr(mod, "MESSAGE_MAX", 800)
        mm = Mattermost()
        sessie = await self._sessie(db_session)
        sources["dd"] = [_uitslag(source=SOURCE_DD, volgnummer=n) for n in range(1, 12)]
        await self._update(db_session, mm, sessie, 0)
        assert len(mm.order) > 1

        # The day gets shorter: the second message goes, but not at once.
        sources["dd"] = sources["dd"][:1]
        mm.fail_deletes = 1
        await self._update(db_session, mm, sessie, 3)
        assert mm.order[1] in mm.messages
        await self._update(db_session, mm, sessie, 6)
        assert list(mm.messages) == [mm.order[0]]

    async def test_an_agenda_without_a_bill_is_asked_a_few_times(
        self, db_session, sources
    ):
        mm = Mattermost()
        sources["dossiers"] = []
        sessie = await self._sessie(db_session)
        minutes = 0.0
        for _ in range(10):
            await self._update(db_session, mm, sessie, minutes)
            minutes += 61
        assert sources["dossier_calls"] == mod.DOSSIERS_TRIES
        assert mm.order == []

    async def test_a_bill_linked_late_is_found(self, db_session, sources):
        mm = Mattermost()
        sources["dossiers"] = []
        sessie = await self._sessie(db_session)
        await self._update(db_session, mm, sessie, 0)

        sources["dossiers"] = ["37999"]
        sources["tk"] = [_uitslag()]
        await self._update(db_session, mm, sessie, 61)
        assert len(mm.order) == 1
