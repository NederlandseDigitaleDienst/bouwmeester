"""Tests for the outcome of the votes in the channel of a debate on a bill.

First what only computes: how a title of Debat Direct is read, how the votes
of both sources are counted and merged, and how the message looks. Then
the whole thing against a real database: the message is posted once,
written again in place when something changed, left alone when nothing
did, and not posted again when someone took it away.

All text is made up. No names of people or of real parties: the fracties
are "Partij A" to "Partij C", a member is "het lid Voorbeeld".
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from bouwmeester.models.debat_sessie import DebatSessie
from bouwmeester.services import debat_stemmingsuitslag as mod
from bouwmeester.services.debat_stemmingsuitslag import (
    BRON_DD,
    BRON_TK,
    SOORT_AMENDEMENT,
    SOORT_MOTIE,
    SOORT_WETGEVING,
    DdActors,
    DebatStemmingsuitslag,
    Fractiestem,
    StemmingenTickResult,
    Uitslag,
    merge,
    parse_dd_titel,
    parse_dd_votings,
    parse_tk_uitslagen,
    render_dag,
)
from bouwmeester.services.mattermost_service import PostNotFoundError

DAG = date(2026, 11, 12)
VOTE_AT = datetime(2026, 11, 12, 15, 40, tzinfo=UTC)

ACTORS = DdActors(
    partijen={"pa": "Partij A", "pb": "Partij B", "pc": "Partij C"},
    leden={
        **{f"a{i}": "pa" for i in range(5)},
        **{f"b{i}": "pb" for i in range(3)},
        **{f"c{i}": "pc" for i in range(2)},
    },
)


def _ronde(titel: str, result: str, votes: list, *, soort="Fractie", at=VOTE_AT):
    return {
        "type": soort,
        "title": titel,
        "result": result,
        "startedAt": at.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "votes": votes,
    }


def _voting(*rondes: dict, subject: str = "Een voorbeeldwet (37999)") -> dict:
    return {"votings": [{"subject": subject, "votingRounds": list(rondes)}]}


def _uitslag(**overrides) -> Uitslag:
    values = {
        "bron": BRON_TK,
        "zaak_soort": SOORT_AMENDEMENT,
        "onderwerp": "Amendement van het lid Voorbeeld over een voorbeeld",
        "dossier": "37999",
        "volgnummer": 12,
        "uitkomst": mod.UITKOMST_AANGENOMEN,
        "besluit_tekst": "Aangenomen.",
        "hoofdelijk": False,
        "moment": VOTE_AT,
        "zaak_nummer": "2026Z00001",
        "document_nummer": "2026D00001",
    }
    values.update(overrides)
    return Uitslag(**values)


class TestDdTitel:
    def test_an_amendement_with_its_number(self):
        soort, dossier, nr, onderwerp, vervangt = parse_dd_titel(
            "het amendement-Voorbeeld over een voorbeeld (37999, nr. 12)"
        )
        assert (soort, dossier, nr, vervangt) == (SOORT_AMENDEMENT, "37999", 12, None)
        assert onderwerp == "Amendement-Voorbeeld over een voorbeeld"

    def test_a_dossier_with_a_toevoeging(self):
        _, dossier, nr, _, _ = parse_dd_titel(
            "de motie-Voorbeeld over iets (37020-XVI, nr. 91)"
        )
        assert (dossier, nr) == ("37020-XVI", 91)

    def test_a_changed_motie_without_a_number_yet(self):
        soort, dossier, nr, _, vervangt = parse_dd_titel(
            "de gewijzigde motie-Voorbeeld c.s. over iets (37999, nr. ??, was nr. 36)"
        )
        assert (soort, dossier, nr, vervangt) == (SOORT_MOTIE, "37999", None, 36)

    def test_a_bill(self):
        soort, dossier, nr, _, _ = parse_dd_titel(
            "het wetsvoorstel Een voorbeeldwet (37999)"
        )
        assert (soort, dossier, nr) == (SOORT_WETGEVING, "37999", None)

    def test_the_last_kenmerk_counts(self):
        _, dossier, nr, _, _ = parse_dd_titel(
            "de motie-Voorbeeld over de uitvoering van (36000, nr. 5) (37999, nr. 40)"
        )
        assert (dossier, nr) == ("37999", 40)


class TestDdVotings:
    def test_a_vote_per_fractie_counts_its_seats(self):
        raw = _voting(
            _ronde(
                "het amendement-Voorbeeld over een voorbeeld (37999, nr. 12)",
                "Aangenomen",
                [["PA", "Voor"], ["pb", "Tegen"], ["pc", "Voor"]],
            )
        )
        [u] = parse_dd_votings(raw, ACTORS, {"37999"})
        assert u.uitkomst == mod.UITKOMST_AANGENOMEN
        assert (u.totaal("Voor"), u.totaal("Tegen")) == (7, 3)
        assert u.fracties("Voor") == ["Partij A", "Partij C"]

    def test_a_hoofdelijke_stemming_counts_members_and_splits(self):
        votes = [[f"a{i}", "Voor"] for i in range(3)] + [
            ["a3", "Tegen"],
            ["a4", "Onbekend"],
            ["b0", "Tegen"],
            ["b1", "Tegen"],
        ]
        raw = _voting(
            _ronde(
                "de motie-Voorbeeld over iets (37999, nr. 20)",
                "Verworpen",
                votes,
                soort="Hoofd",
            )
        )
        [u] = parse_dd_votings(raw, ACTORS, {"37999"})
        assert u.hoofdelijk
        assert (u.totaal("Voor"), u.totaal("Tegen")) == (3, 3)
        assert u.fracties("Voor") == ["Partij A 3 van 4"]

    def test_a_tie_then_a_hoofdelijke_stemming_keeps_the_last(self):
        titel = "de motie-Voorbeeld over iets (37999, nr. 20)"
        raw = _voting(
            _ronde(titel, "Staken", [["pa", "Voor"], ["pb", "Tegen"]]),
            _ronde(
                titel,
                "Aangenomen",
                [["a0", "Voor"]],
                soort="Hoofd",
                at=VOTE_AT + timedelta(minutes=5),
            ),
        )
        [u] = parse_dd_votings(raw, ACTORS, {"37999"})
        assert u.uitkomst == mod.UITKOMST_AANGENOMEN
        assert u.hoofdelijk

    def test_other_dossiers_are_left_out(self):
        raw = _voting(
            _ronde("de motie-Voorbeeld over iets (36000, nr. 3)", "Verworpen", [])
        )
        assert parse_dd_votings(raw, ACTORS, {"37999"}) == []

    def test_a_cut_off_title_takes_the_dossier_from_the_subject(self):
        raw = _voting(
            _ronde("het wetsvoorstel Een voorbeeldwet die...", "Aangenomen", [])
        )
        [u] = parse_dd_votings(raw, ACTORS, {"37999"})
        assert (u.zaak_soort, u.dossier) == (SOORT_WETGEVING, "37999")


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
        assert u.uitkomst == mod.UITKOMST_VERWORPEN
        assert u.dag == DAG
        assert (u.totaal("Voor"), u.totaal("Tegen")) == (5, 5)

    def test_the_latest_besluit_on_a_zaak_wins(self):
        later = _besluit(
            BesluitSoort="Stemmen - aangenomen",
            GewijzigdOp="2026-11-12T17:30:00+01:00",
        )
        [u] = parse_tk_uitslagen([later, _besluit()], {"37999"})
        assert u.uitkomst == mod.UITKOMST_AANGENOMEN

    def test_what_a_changed_motie_replaces(self):
        row = _besluit()
        row["Zaak"][0]["Onderwerp"] = "Gewijzigde motie over iets (t.v.v. 37999-18)"
        [u] = parse_tk_uitslagen([row], {"37999"})
        assert u.vervangt == 18


class TestMerge:
    def test_the_tk_besluit_takes_the_votes_of_debat_direct(self):
        tk = _uitslag(stemmen=())
        dd_u = _uitslag(
            bron=BRON_DD,
            document_nummer=None,
            stemmen=(Fractiestem("Partij A", "Voor", 5),),
        )
        [u] = merge([tk], [dd_u])
        assert u.bron == BRON_TK
        assert u.document_nummer == "2026D00001"
        assert u.totaal("Voor") == 5

    def test_votes_of_the_tk_api_stay(self):
        tk = _uitslag(stemmen=(Fractiestem("Partij A", "Voor", 5),))
        dd_u = _uitslag(bron=BRON_DD, stemmen=(Fractiestem("Partij B", "Voor", 3),))
        [u] = merge([tk], [dd_u])
        assert u.fracties("Voor") == ["Partij A"]

    def test_debat_direct_alone_before_the_tk_api_has_it(self):
        [u] = merge([], [_uitslag(bron=BRON_DD)])
        assert u.bron == BRON_DD

    def test_a_changed_motie_without_a_number_matches_by_what_it_replaces(self):
        tk = _uitslag(zaak_soort=SOORT_MOTIE, volgnummer=45, vervangt=42)
        dd_u = _uitslag(
            bron=BRON_DD,
            zaak_soort=SOORT_MOTIE,
            volgnummer=None,
            vervangt=42,
            onderwerp="Gewijzigde motie-Voorbeeld c.s. over iets anders geschreven",
        )
        assert len(merge([tk], [dd_u])) == 1

    def test_or_by_what_it_is_about(self):
        tk = _uitslag(
            zaak_soort=SOORT_MOTIE,
            volgnummer=45,
            onderwerp="Gewijzigde motie van de leden A en B over iets (t.v.v. x)",
        )
        dd_u = _uitslag(
            bron=BRON_DD,
            zaak_soort=SOORT_MOTIE,
            volgnummer=None,
            onderwerp="Gewijzigde motie-Voorbeeld c.s. over iets",
        )
        assert len(merge([tk], [dd_u])) == 1


class TestRender:
    def test_the_message(self):
        [message] = render_dag(
            DAG,
            [
                _uitslag(stemmen=(Fractiestem("Partij A", "Voor", 5),)),
                _uitslag(
                    zaak_soort=SOORT_MOTIE,
                    volgnummer=20,
                    uitkomst=mod.UITKOMST_VERWORPEN,
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
        messages = render_dag(DAG, items)
        assert len(messages) > 1
        assert all(len(m) <= 1200 for m in messages)
        assert messages[1].startswith(
            "🗳️ **Stemmingen van donderdag 12 november** (vervolg)"
        )
        assert sum(m.count("\n- ") for m in messages) == 39


# --- In the channel ---------------------------------------------------------


class Mattermost:
    def __init__(self) -> None:
        self.messages: dict[str, str] = {}
        self.order: list[str] = []
        self.pinned: set[str] = set()
        self.updates = 0

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
        self.messages.pop(post_id, None)
        return True

    async def pin_post(self, post_id) -> bool:
        self.pinned.add(post_id)
        return True

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
class TestInTheChannel:
    @pytest.fixture
    def sources(self, monkeypatch):
        state = {"dossiers": ["37999"], "tk": [], "dd": [], "dossier_calls": 0}

        async def dossiers(activiteit_id, client, base_url=None):
            state["dossier_calls"] += 1
            return state["dossiers"]

        async def tk(dossiers, since, client, base_url=None):
            return list(state["tk"])

        async def dd_uitslagen(self, dossiers, days):
            return list(state["dd"])

        monkeypatch.setattr(mod, "fetch_dossiers", dossiers)
        monkeypatch.setattr(mod, "fetch_tk_uitslagen", tk)
        monkeypatch.setattr(mod.DdBron, "uitslagen", dd_uitslagen)
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
            mod.DdBron(None),
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
        sources["dd"] = [_uitslag(bron=BRON_DD)]
        await self._update(db_session, mm, sessie, 0)
        assert len(mm.order) == 1
        assert mm.pinned == {mm.order[0]}

        # Nothing new: not written again, although the time moved on.
        await self._update(db_session, mm, sessie, 3)
        assert mm.updates == 0

        # The second vote of the day: the same message.
        sources["dd"].append(_uitslag(bron=BRON_DD, volgnummer=13))
        await self._update(db_session, mm, sessie, 6)
        assert len(mm.order) == 1
        assert mm.updates == 1
        assert "nr. 13" in mm.messages[mm.order[0]]

    async def test_waits_between_rounds(self, db_session, sources):
        mm = Mattermost()
        sessie = await self._sessie(db_session)
        await self._update(db_session, mm, sessie, 0)
        sources["dd"] = [_uitslag(bron=BRON_DD)]
        await self._update(db_session, mm, sessie, 1)
        assert mm.order == []
        await self._update(db_session, mm, sessie, 2)
        assert len(mm.order) == 1

    async def test_a_message_someone_deleted_is_not_posted_again(
        self, db_session, sources
    ):
        mm = Mattermost()
        sessie = await self._sessie(db_session)
        sources["dd"] = [_uitslag(bron=BRON_DD)]
        await self._update(db_session, mm, sessie, 0)
        mm.messages.clear()

        sources["dd"].append(_uitslag(bron=BRON_DD, volgnummer=13))
        await self._update(db_session, mm, sessie, 3)
        await self._update(db_session, mm, sessie, 6)
        assert mm.messages == {}
        assert len(mm.order) == 1

    async def test_a_debate_without_a_bill_is_asked_once(self, db_session, sources):
        mm = Mattermost()
        sources["dossiers"] = []
        sessie = await self._sessie(db_session)
        await self._update(db_session, mm, sessie, 0)
        await self._update(db_session, mm, sessie, 10)
        assert sources["dossier_calls"] == 1
        assert mm.order == []
