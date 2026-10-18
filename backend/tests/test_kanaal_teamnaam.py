"""Tests voor de teamnaam bij een Mattermost-kanaal.

Twee kanalen in verschillende teams mogen dezelfde naam dragen. De picker
toonde dan twee identieke regels met een koppel-knop, en kiezen was
gokken.

De naam wordt bij het tonen opgehaald en niet opgeslagen: een opgeslagen
naam veroudert zodra iemand het team in Mattermost hernoemt. Dat maakt de
foutpaden belangrijk, want ze draaien bij elke weergave.

Het beheeroverzicht toont dezelfde kanalen onder elkaar en loopt daarom
dezelfde weg, via `vul_teamnaam_aan`.
"""

from types import SimpleNamespace

import httpx
import pytest

from bouwmeester.schema.worker_health import MattermostChannelOverview
from bouwmeester.services import mattermost_service
from bouwmeester.services.mattermost_service import (
    MattermostService,
    vul_teamnaam_aan,
)


def _svc() -> MattermostService:
    return MattermostService.__new__(MattermostService)


class _Client:
    """Minimale httpx-vervanger die vaste antwoorden teruggeeft."""

    def __init__(self, antwoorden: dict):
        self._antwoorden = antwoorden

    async def get(self, url: str, **_kw):
        for pad, waarde in self._antwoorden.items():
            if pad in url:
                if isinstance(waarde, Exception):
                    raise waarde
                return SimpleNamespace(
                    json=lambda w=waarde: w,
                    raise_for_status=lambda: None,
                )
        raise AssertionError(f"onverwachte url: {url}")


class TestTeamNamen:
    async def test_leest_display_name(self):
        svc = _svc()
        svc._get_client = lambda: _klaar(
            _Client({"users/me/teams": [{"id": "t1", "display_name": "MOZa"}]})
        )
        assert await svc.team_namen() == {"t1": "MOZa"}

    async def test_valt_terug_op_de_slug(self):
        """Zonder display_name is de url-naam beter dan niets."""
        svc = _svc()
        svc._get_client = lambda: _klaar(
            _Client({"users/me/teams": [{"id": "t1", "name": "moza"}]})
        )
        assert await svc.team_namen() == {"t1": "moza"}

    async def test_mattermost_plat_geeft_lege_map(self):
        """Zonder namen is de lijst hetzelfde als voorheen, geen fout."""
        svc = _svc()
        svc._get_client = lambda: _klaar(
            _Client({"users/me/teams": httpx.ConnectError("plat")})
        )
        assert await svc.team_namen() == {}

    async def test_team_zonder_id_wordt_overgeslagen(self):
        svc = _svc()
        svc._get_client = lambda: _klaar(
            _Client({"users/me/teams": [{"display_name": "Zonder id"}]})
        )
        assert await svc.team_namen() == {}


class TestTeamIdPerKanaal:
    """Koppelingen van vóór deze wijziging dragen geen team_id.

    Zonder deze lookup valt er voor die koppelingen niets op te zoeken, en
    zou een migratie nodig zijn die alleen repareert wat er op dat moment
    staat.
    """

    async def test_koppelt_kanaal_aan_team(self):
        svc = _svc()
        svc.get_bot_user_id = _maak_async("bot1")
        svc._get_client = lambda: _klaar(
            _Client({"channels": [{"id": "c1", "team_id": "t1"}]})
        )
        assert await svc.team_id_per_kanaal() == {"c1": "t1"}

    async def test_zonder_bot_geen_lookup(self):
        svc = _svc()
        svc.get_bot_user_id = _maak_async(None)
        assert await svc.team_id_per_kanaal() == {}

    async def test_kanaal_zonder_team_id_valt_af(self):
        svc = _svc()
        svc.get_bot_user_id = _maak_async("bot1")
        svc._get_client = lambda: _klaar(_Client({"channels": [{"id": "c1"}]}))
        assert await svc.team_id_per_kanaal() == {}

    async def test_fout_geeft_lege_map(self):
        svc = _svc()
        svc.get_bot_user_id = _maak_async("bot1")
        svc._get_client = lambda: _klaar(
            _Client({"channels": httpx.ConnectError("plat")})
        )
        assert await svc.team_id_per_kanaal() == {}


class _Antwoord:
    """Staat voor elk antwoordmodel dat een kanaal toont.

    De kanaalkaart en het beheeroverzicht dragen verschillende modellen;
    `vul_teamnaam_aan` kent alleen deze drie velden, en dat is precies wat
    hier wordt vastgelegd.
    """

    def __init__(self, channel_id: str, team_id: str | None = None):
        self.channel_id = channel_id
        self.team_id = team_id
        self.team_name: str | None = None


class _NepService:
    """Vervangt MattermostService binnen `vul_teamnaam_aan`."""

    def __init__(self, enabled=True, namen=None, per_kanaal=None):
        self._enabled = enabled
        self._namen = namen if namen is not None else {}
        self._per_kanaal = per_kanaal if per_kanaal is not None else {}
        self.per_kanaal_opgevraagd = False

    def __call__(self, _session):
        return self

    async def is_enabled(self):
        return self._enabled

    async def team_namen(self):
        return self._namen

    async def team_id_per_kanaal(self):
        self.per_kanaal_opgevraagd = True
        return self._per_kanaal


class TestVulTeamnaamAan:
    """De gedeelde invulling, die de kanaalkaart en het beheeroverzicht
    allebei aanroepen zodat er niet twee implementaties naast elkaar staan.
    """

    async def test_lege_lijst_raakt_mattermost_niet(self, monkeypatch):
        nep = _NepService(enabled=True)
        monkeypatch.setattr(mattermost_service, "MattermostService", nep)
        assert await vul_teamnaam_aan(None, []) == []
        assert not nep.per_kanaal_opgevraagd

    async def test_vult_naam_bij_opgeslagen_team_id(self, monkeypatch):
        nep = _NepService(namen={"t1": "MOZa"})
        monkeypatch.setattr(mattermost_service, "MattermostService", nep)
        antwoord = _Antwoord("c1", team_id="t1")

        await vul_teamnaam_aan(None, [antwoord])

        assert antwoord.team_name == "MOZa"
        # Alles droeg al een team_id, dus de dure lookup blijft achterwege.
        assert not nep.per_kanaal_opgevraagd

    async def test_koppeling_zonder_team_id_herstelt_zichzelf(self, monkeypatch):
        """Koppelingen van vóór deze reeks dragen `team_id` NULL.

        Daarom wordt het bij het tonen opgezocht in plaats van eenmalig
        gemigreerd: een migratie repareert wat er op dat moment staat en
        niet wat er tussendoor bijkomt.
        """
        nep = _NepService(namen={"t1": "MOZa"}, per_kanaal={"c1": "t1"})
        monkeypatch.setattr(mattermost_service, "MattermostService", nep)
        antwoord = _Antwoord("c1", team_id=None)

        await vul_teamnaam_aan(None, [antwoord])

        assert antwoord.team_id == "t1"
        assert antwoord.team_name == "MOZa"

    async def test_zonder_mattermost_blijft_de_lijst_zoals_hij_was(self, monkeypatch):
        nep = _NepService(enabled=False)
        monkeypatch.setattr(mattermost_service, "MattermostService", nep)
        antwoord = _Antwoord("c1", team_id="t1")

        await vul_teamnaam_aan(None, [antwoord])

        assert antwoord.team_name is None

    async def test_zonder_namen_blijft_de_lijst_zoals_hij_was(self, monkeypatch):
        """Een fout op het teams-verzoek geeft een lege map, geen uitzondering."""
        nep = _NepService(namen={})
        monkeypatch.setattr(mattermost_service, "MattermostService", nep)
        antwoord = _Antwoord("c1", team_id="t1")

        await vul_teamnaam_aan(None, [antwoord])

        assert antwoord.team_name is None

    async def test_onbekend_team_id_geeft_geen_naam(self, monkeypatch):
        """Het id blijft staan; alleen de naam ontbreekt."""
        nep = _NepService(namen={"t2": "Elders"})
        monkeypatch.setattr(mattermost_service, "MattermostService", nep)
        antwoord = _Antwoord("c1", team_id="t1")

        await vul_teamnaam_aan(None, [antwoord])

        assert antwoord.team_id == "t1"
        assert antwoord.team_name is None


class TestBeheeroverzichtSchema:
    """Het beheeroverzicht draagt de velden die `vul_teamnaam_aan` invult,
    en alle vier de schakelaars. Zonder die twee laatste toonde het
    overzicht "Niets actief" bij een kanaal met alerts aan.
    """

    def test_draagt_team_en_alle_schakelaars(self):
        velden = MattermostChannelOverview.model_fields
        for veld in (
            "team_id",
            "team_name",
            "auto_note_enabled",
            "suggest_leads_enabled",
            "parlementaire_alerts_enabled",
            "nieuws_alerts_enabled",
        ):
            assert veld in velden, f"{veld} ontbreekt in het beheeroverzicht"


def _maak_async(waarde):
    async def f():
        return waarde

    return f


async def _klaar(waarde):
    return waarde


@pytest.fixture
def anyio_backend():
    return "asyncio"
