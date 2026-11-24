"""Een Mattermost-kanaal aan een casus, met de voortgang erin.

Dekt:
- Koppelen aan een casus: voortgang staat aan, meelezen niet. Alleen een
  privékanaal waar de bot in zit; de naam komt uit Mattermost. Vlak voor
  het versturen wordt nog eens gekeken of het kanaal privé is.
- Koppelen, wijzigen en ontkoppelen (ook met `/bouwmeester ontkoppel`)
  volgt het wijzigen van de casus: bijdrager, eigenaar of de trekker. Een
  kijker ziet alleen.
- Toegang: buiten het initiatief 404 op lijst, koppelen, wijzigen en
  ontkoppelen; het bestaan van de casus lekt niet. Per rol nagelopen
  (eigenaar, lid, kijker, via een eenheid, buitenstaander, oud-lid, zonder
  rol, niet ingelogd), plus scheiding tussen initiatieven en het
  beheeroverzicht.
- Casus starten: het kanaal van de lead verhuist mee, met de voortgang
  uit en zonder bericht. Aanzetten kan alleen als het privé is. Een lead
  met casus krijgt geen nieuw kanaal (409). Gaat de casus weg, dan gaat het
  kanaal terug naar de lead.
- Berichten bij een fasewissel en een nieuw of afgerond issue (een
  onderzoeksvraag of een gewoon issue). Geen bericht naar Mattermost zonder
  kanaal, als de voortgang uit staat, of bij een andere statuswissel.
- Elk bericht staat ook bij de casus, met of zonder kanaal, nieuwste
  eerst. Na het versturen staat erbij hoe het afliep: verstuurd, mislukt,
  of Mattermost uit. Een savepoint verstuurt nog niets; wat mislukte of
  bleef hangen gaat opnieuw, met de hand (alleen wie de casus wijzigt) of
  door de worker.
- Opmaak: korte inhoud, escaping (ook met een backslash ervoor of een
  regeleinde in de titel; een vermelding krijgt een zero-width space, want
  een backslash houdt de melding niet tegen), een link naar de casus, en
  de voetregel los van het citaat. Rare tiptap-JSON breekt het afronden
  van een issue niet.
- Schakelaars per soort kanaal, en het slash-commando volgt de regel dat
  een lead met casus geen kanaal meer krijgt.

Tests committen niet, dus er gaat niets echt naar Mattermost: ze lezen wat
na de commit zou gaan (`wachtende_berichten`) en wat bij de casus staat.
Mattermost zelf is nagebootst: de routes zien alleen de kanalen uit
`_kanaal`, het versturen gaat naar `_NepMattermost`.
"""

import asyncio
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from bouwmeester.models.activity import Activity
from bouwmeester.models.casus_kanaalbericht import CasusKanaalbericht
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.mattermost_channel_link import SCOPE_CASUS
from bouwmeester.models.person_organisatie import PersonOrganisatieEenheid
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.repositories.lead_column import LeadColumnRepository
from bouwmeester.repositories.mattermost_channel_link import (
    MattermostChannelLinkRepository,
)
from bouwmeester.repositories.mattermost_user import MattermostUserRepository
from bouwmeester.schema.casus_fases import DEFAULT_CASUS_FASES
from bouwmeester.services import casus_kanaal_service as kanaal
from bouwmeester.services.mattermost_slash_service import MattermostSlashService
from tests.factories import (
    START_INTERN,
    client_as,
    grant_role,
    make_org,
    make_person,
    place,
)


def _channel_id() -> str:
    return uuid.uuid4().hex[:26]


# Wat de nagebootste Mattermost kent: kanaal-id naar kanaal, zoals de API.
_MM_KANALEN: dict[str, dict] = {}


def _kanaal(
    naam: str = "casus-kanaal",
    *,
    soort: str = "P",
    bot: bool = True,
    delete_at: int = 0,
) -> dict:
    """Een kanaal in Mattermost, en het verzoek om het te koppelen."""
    channel_id = _channel_id()
    weergave = naam.replace("-", " ").capitalize()
    _MM_KANALEN[channel_id] = {
        "id": channel_id,
        "name": naam,
        "display_name": weergave,
        "type": soort,
        "team_id": "",
        "delete_at": delete_at,
        "bot": bot,
    }
    return {
        "channel_id": channel_id,
        "channel_name": naam,
        "channel_display_name": weergave,
    }


class _NepMattermostService:
    """Mattermost voor de routes: kent alleen de kanalen uit `_kanaal`."""

    def __init__(self, session):
        pass

    async def is_enabled(self) -> bool:
        return True

    async def get_channel(self, channel_id: str) -> dict | None:
        return _MM_KANALEN.get(channel_id)

    async def is_bot_member_of_channel(self, channel_id: str) -> bool:
        return _MM_KANALEN[channel_id]["bot"]

    async def send_channel_message(self, channel_id: str, tekst: str) -> bool:
        # Alleen voor opnieuw versturen uit de route; de eerste keer gaat
        # na de commit, en tests committen niet.
        _MM_GEPLAATST.append((channel_id, tekst))
        return True

    async def team_namen(self) -> dict[str, str]:
        return {}

    async def close(self) -> None:
        pass


# Wat de nagebootste Mattermost uit de routes geplaatst kreeg: (kanaal, tekst).
_MM_GEPLAATST: list[tuple[str, str]] = []


@pytest.fixture(autouse=True)
def nep_mattermost(monkeypatch):
    monkeypatch.setattr(
        "bouwmeester.services.mattermost_service.MattermostService",
        _NepMattermostService,
    )


@pytest.fixture
async def initiatief(db_session):
    init = Initiatief(
        id=uuid.uuid4(),
        naam="Regelrecht kanaal",
        slug="rr-kanaal",
        casussen_enabled=True,
    )
    db_session.add(init)
    await db_session.flush()
    await LeadColumnRepository(db_session).seed_defaults(init.id)
    return init


@pytest.fixture
async def werkeenheid(db_session):
    return await make_org(db_session, "Werkeenheid")


@pytest.fixture
async def lid(db_session, initiatief, werkeenheid):
    p = await make_person(db_session, "Teamlid")
    await grant_role(db_session, p, "editor", werkeenheid)
    db_session.add(
        ResourcePermission(
            person_id=p.id,
            resource_type="initiatief",
            resource_id=initiatief.id,
            rol="contributor",
        )
    )
    await db_session.flush()
    return p


@pytest.fixture
async def buitenstaander(db_session, werkeenheid):
    p = await make_person(db_session, "Buitenstaander")
    await grant_role(db_session, p, "editor", werkeenheid)
    return p


@pytest.fixture
async def lead(db_session, initiatief):
    lead = Lead(
        id=uuid.uuid4(),
        title="Kanaalcasus",
        stage="in_the_pocket",
        initiatief_id=initiatief.id,
    )
    db_session.add(lead)
    await db_session.flush()
    return lead


async def _start(client, lead) -> dict:
    resp = await client.post(
        "/api/casussen",
        json={"lead_id": str(lead.id), "startvoorwaarden": START_INTERN},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def casus(client, lead):
    return await _start(client, lead)


async def _koppel(client, casus, naam: str = "casus-kanaal") -> dict:
    resp = await client.post(
        f"/api/casussen/{casus['id']}/mattermost-channels", json=_kanaal(naam)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _bewaard(client, casus) -> list[dict]:
    resp = await client.get(f"/api/casussen/{casus['id']}/kanaalberichten")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _teksten(db_session, vanaf: int = 0) -> list[str]:
    return [b.tekst for b in kanaal.wachtende_berichten(db_session)[vanaf:]]


def _aantal(db_session) -> int:
    return len(kanaal.wachtende_berichten(db_session))


# ---------------------------------------------------------------------------
# Koppelen
# ---------------------------------------------------------------------------


async def test_kanaal_aan_casus_post_voortgang_en_leest_niet_mee(client, casus):
    body = await _koppel(client, casus)
    assert body["scope_type"] == SCOPE_CASUS
    assert body["scope_id"] == casus["id"]
    assert body["casus_updates_enabled"] is True
    assert body["auto_note_enabled"] is False
    assert body["suggest_leads_enabled"] is False

    resp = await client.get(f"/api/casussen/{casus['id']}/mattermost-channels")
    assert resp.status_code == 200
    assert [x["id"] for x in resp.json()] == [body["id"]]


async def test_zelfde_kanaal_niet_twee_keer(client, casus, lead, initiatief):
    data = _kanaal()
    eerste = await client.post(
        f"/api/casussen/{casus['id']}/mattermost-channels", json=data
    )
    assert eerste.status_code == 201
    weer = await client.post(
        f"/api/initiatieven/{initiatief.id}/mattermost-channels", json=data
    )
    assert weer.status_code == 409


async def test_onbekende_casus_is_404(client):
    resp = await client.get(f"/api/casussen/{uuid.uuid4()}/mattermost-channels")
    assert resp.status_code == 404
    resp = await client.get(f"/api/casussen/{uuid.uuid4()}/kanaalberichten")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Toegang
# ---------------------------------------------------------------------------


async def test_buiten_het_initiatief_onvindbaar(
    db_session, client, casus, lid, buitenstaander
):
    link = await _koppel(client, casus)
    pad = f"/api/casussen/{casus['id']}/mattermost-channels"
    berichten = f"/api/casussen/{casus['id']}/kanaalberichten"
    await client.put(
        f"/api/casussen/{casus['id']}", json={"fase": DEFAULT_CASUS_FASES[1].id}
    )

    async with client_as(db_session, buitenstaander) as c:
        assert (await c.get(pad)).status_code == 404
        assert (await c.get(berichten)).status_code == 404
        assert (await c.post(pad, json=_kanaal("ander"))).status_code == 404
        assert (
            await c.patch(
                f"/api/mattermost-channels/{link['id']}",
                json={"casus_updates_enabled": False},
            )
        ).status_code == 404
        assert (
            await c.delete(f"/api/mattermost-channels/{link['id']}")
        ).status_code == 404

    async with client_as(db_session, lid) as c:
        resp = await c.get(pad)
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        resp = await c.get(berichten)
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        resp = await c.patch(
            f"/api/mattermost-channels/{link['id']}",
            json={"casus_updates_enabled": False},
        )
        assert resp.status_code == 200
        assert resp.json()["casus_updates_enabled"] is False


# ---------------------------------------------------------------------------
# Rollen: wie ziet de berichten en beheert de kanalen
# ---------------------------------------------------------------------------


async def _lid_met_rol(db_session, initiatief, naam: str, rol: str, orgrol: str):
    org = await make_org(db_session, f"Eenheid {naam}")
    p = await make_person(db_session, naam)
    await grant_role(db_session, p, orgrol, org)
    db_session.add(
        ResourcePermission(
            person_id=p.id,
            resource_type="initiatief",
            resource_id=initiatief.id,
            rol=rol,
        )
    )
    await db_session.flush()
    return p


@pytest.fixture
async def eigenaar(db_session, initiatief):
    return await _lid_met_rol(db_session, initiatief, "Eigenaar", "eigenaar", "editor")


@pytest.fixture
async def kijker(db_session, initiatief):
    # Alleen kijken, op het initiatief en in de organisatie.
    return await _lid_met_rol(db_session, initiatief, "Kijker", "viewer", "viewer")


@pytest.fixture
async def via_eenheid(db_session, initiatief):
    org = await make_org(db_session, "Directie Kanaal")
    p = await make_person(db_session, "Collega via eenheid")
    await place(db_session, p, org)
    db_session.add(
        ResourcePermission(
            organisatie_eenheid_id=org.id,
            resource_type="initiatief",
            resource_id=initiatief.id,
            rol="viewer",
        )
    )
    await db_session.flush()
    return p


@pytest.fixture
async def oud_lid(db_session, initiatief):
    # Zat in een eenheid die bij het initiatief hoort, maar is daar weg.
    org = await make_org(db_session, "Oude directie")
    p = await make_person(db_session, "Oud lid")
    vandaag = date.today()
    db_session.add(
        PersonOrganisatieEenheid(
            person_id=p.id,
            organisatie_eenheid_id=org.id,
            start_datum=vandaag - timedelta(days=30),
            eind_datum=vandaag - timedelta(days=1),
        )
    )
    db_session.add(
        ResourcePermission(
            organisatie_eenheid_id=org.id,
            resource_type="initiatief",
            resource_id=initiatief.id,
            rol="contributor",
        )
    )
    await db_session.flush()
    return p


@pytest.fixture
async def personen(
    db_session, eigenaar, lid, kijker, via_eenheid, buitenstaander, oud_lid
):
    # Eén fixture voor allemaal: een async fixture laat zich niet bij naam
    # ophalen vanuit een async test.
    return {
        "eigenaar": eigenaar,
        "lid": lid,
        "kijker": kijker,
        "via_eenheid": via_eenheid,
        "buitenstaander": buitenstaander,
        "oud_lid": oud_lid,
        "zonder_rol": await make_person(db_session, "Zonder rol"),
    }


async def _wat_mag(c, casus, link) -> dict[str, int]:
    """Wat iemand met de berichten en kanalen van een casus kan."""
    pad = f"/api/casussen/{casus['id']}"
    koppel = _kanaal("nog-een")
    linkpad = f"/api/mattermost-channels/{link['id']}"
    uit = {"casus_updates_enabled": False}
    return {
        "berichten": (await c.get(f"{pad}/kanaalberichten")).status_code,
        "kanalen": (await c.get(f"{pad}/mattermost-channels")).status_code,
        "koppelen": (
            await c.post(f"{pad}/mattermost-channels", json=koppel)
        ).status_code,
        "wijzigen": (await c.patch(linkpad, json=uit)).status_code,
        "ontkoppelen": (await c.delete(linkpad)).status_code,
    }


MAG = {
    "berichten": 200,
    "kanalen": 200,
    "koppelen": 201,
    "wijzigen": 200,
    "ontkoppelen": 204,
}
# Kijken mag, beheren niet: dat is aan een eigenaar of contributor.
MAG_KIJKEN = {
    "berichten": 200,
    "kanalen": 200,
    "koppelen": 403,
    "wijzigen": 403,
    "ontkoppelen": 403,
}
MAG_NIET = dict.fromkeys(MAG, 404)


@pytest.mark.parametrize(
    ("wie", "verwacht"),
    [
        ("eigenaar", MAG),
        ("lid", MAG),
        # Een kijker ziet de berichten en de kanalen, maar stuurt geen
        # casusinhoud naar Mattermost. Ook niet via een eenheid.
        ("kijker", MAG_KIJKEN),
        ("via_eenheid", MAG_KIJKEN),
        ("buitenstaander", MAG_NIET),
        ("oud_lid", MAG_NIET),
        ("zonder_rol", MAG_NIET),
    ],
)
async def test_wie_ziet_berichten_en_beheert_kanalen(
    db_session, client, casus, personen, wie, verwacht
):
    link = await _koppel(client, casus)
    await client.put(
        f"/api/casussen/{casus['id']}", json={"fase": DEFAULT_CASUS_FASES[1].id}
    )
    async with client_as(db_session, personen[wie]) as c:
        assert await _wat_mag(c, casus, link) == verwacht
    if verwacht is not MAG:
        # Niets veranderd: het kanaal hangt er nog, met de voortgang aan.
        kanalen = await client.get(f"/api/casussen/{casus['id']}/mattermost-channels")
        [nog] = kanalen.json()
        assert nog["id"] == link["id"]
        assert nog["casus_updates_enabled"] is True
        assert len(await _bewaard(client, casus)) == 1


async def test_trekker_die_alleen_kijkt_beheert_wel(db_session, client, casus, kijker):
    # Zelfde regel als het wijzigen van de casus: de trekker mag het ook.
    db_session.add(
        ResourcePermission(
            person_id=kijker.id,
            resource_type="casus",
            resource_id=uuid.UUID(casus["id"]),
            rol="trekker",
        )
    )
    await db_session.flush()
    link = await _koppel(client, casus)
    async with client_as(db_session, kijker) as c:
        assert await _wat_mag(c, casus, link) == MAG


async def test_niet_ingelogd_ziet_niets(db_session, client, casus, monkeypatch):
    # Buiten dev-modus: een verzoek zonder gebruiker is niemand.
    link = await _koppel(client, casus)
    monkeypatch.setattr("bouwmeester.core.config.is_dev_mode", lambda: False)
    async with client_as(db_session, None) as c:
        assert await _wat_mag(c, casus, link) == MAG_NIET


async def test_berichten_blijven_bij_hun_eigen_initiatief(
    db_session, client, casus, lid
):
    ander = Initiatief(
        id=uuid.uuid4(),
        naam="Ander initiatief",
        slug="rr-ander",
        casussen_enabled=True,
    )
    db_session.add(ander)
    await db_session.flush()
    await LeadColumnRepository(db_session).seed_defaults(ander.id)
    lead = Lead(
        id=uuid.uuid4(),
        title="Geheime casus",
        stage="in_the_pocket",
        initiatief_id=ander.id,
    )
    db_session.add(lead)
    await db_session.flush()
    geheim = await _start(client, lead)
    await client.post(
        f"/api/casussen/{geheim['id']}/issues", json={"title": "Geheime vraag"}
    )
    await client.post(f"/api/casussen/{casus['id']}/issues", json={"title": "Vraag"})

    async with client_as(db_session, lid) as c:
        resp = await c.get(f"/api/casussen/{geheim['id']}/kanaalberichten")
        assert resp.status_code == 404
        resp = await c.get(f"/api/casussen/{casus['id']}/kanaalberichten")
        assert resp.status_code == 200
        teksten = " ".join(b["tekst"] for b in resp.json())
    assert "Vraag" in teksten
    assert "Geheim" not in teksten


async def test_beheeroverzicht_alleen_voor_beheerders(db_session, client, casus, lid):
    await _koppel(client, casus)
    async with client_as(db_session, lid) as c:
        assert (await c.get("/api/admin/mattermost-channels")).status_code == 403
    resp = await client.get("/api/admin/mattermost-channels")
    assert resp.status_code == 200
    rij = next(r for r in resp.json() if r["scope_type"] == SCOPE_CASUS)
    assert rij["casus_updates_enabled"] is True


# ---------------------------------------------------------------------------
# Het kanaal van de lead
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("soort", "aanzetten"), [("P", 200), ("O", 400)])
async def test_kanaal_van_de_lead_verhuist_mee_met_voortgang_uit(
    db_session, client, lead, soort, aanzetten
):
    resp = await client.post(
        f"/api/leads/{lead.id}/mattermost-channels",
        json=_kanaal("lead-kanaal", soort=soort),
    )
    assert resp.status_code == 201, resp.text
    link_id = resp.json()["id"]
    assert resp.json()["auto_note_enabled"] is True

    voor = _aantal(db_session)
    casus = await _start(client, lead)

    leadkanalen = await client.get(f"/api/leads/{lead.id}/mattermost-channels")
    assert leadkanalen.json() == []
    casuskanalen = await client.get(f"/api/casussen/{casus['id']}/mattermost-channels")
    [link] = casuskanalen.json()
    assert link["id"] == link_id
    # Gekozen om berichten binnen te halen, niet om ze te sturen: de
    # voortgang staat uit, en er gaat ook geen bericht heen.
    assert link["casus_updates_enabled"] is False
    assert _teksten(db_session, voor) == []
    assert await _bewaard(client, casus) == []

    # Aanzetten kan, maar alleen in een privékanaal.
    resp = await client.patch(
        f"/api/mattermost-channels/{link_id}", json={"casus_updates_enabled": True}
    )
    assert resp.status_code == aanzetten, resp.text


async def test_lead_met_casus_krijgt_geen_nieuw_kanaal(client, casus, lead):
    resp = await client.post(
        f"/api/leads/{lead.id}/mattermost-channels", json=_kanaal()
    )
    assert resp.status_code == 409
    assert "casus" in resp.json()["detail"]


async def test_ook_niet_via_het_slash_commando(db_session, casus, lead, lid):
    await MattermostUserRepository(db_session).create_mapping(
        person_id=lid.id,
        mattermost_user_id="mm-teamlid",
        mattermost_username="teamlid",
    )
    antwoord = await MattermostSlashService(db_session).handle_command(
        "mm-teamlid",
        f"koppel lead {lead.id}",
        channel_id=_channel_id(),
        channel_name="kanaal",
    )
    assert "casus gestart" in antwoord["text"]
    leadkanalen = await MattermostChannelLinkRepository(db_session).list_for_scope(
        "lead", lead.id
    )
    assert leadkanalen == []


@pytest.mark.parametrize(
    ("kanaal_kwargs", "reden"),
    [
        ({"soort": "O"}, "privékanaal"),
        ({"bot": False}, "bot zit niet"),
        ({"delete_at": 1_700_000_000_000}, "niet te vinden"),
    ],
)
async def test_alleen_een_privekanaal_met_de_bot_erin(
    client, casus, kanaal_kwargs, reden
):
    resp = await client.post(
        f"/api/casussen/{casus['id']}/mattermost-channels",
        json=_kanaal("verkeerd", **kanaal_kwargs),
    )
    assert resp.status_code == 400
    assert reden in resp.json()["detail"]


async def test_delete_at_min_een_is_niet_gearchiveerd(db_session, client, casus):
    # De Mattermost van productie gaf bij teamlidmaatschap -1 waar 9.5 een 0
    # geeft. Alleen een tijdstip groter dan 0 betekent gearchiveerd; anders
    # mislukt elk koppelen en elk bericht zodra dat ook bij een kanaal gebeurt.
    link = _kanaal("min-een", delete_at=-1)
    resp = await client.post(
        f"/api/casussen/{casus['id']}/mattermost-channels", json=link
    )
    assert resp.status_code == 201, resp.text

    # En plaatsen gaat gewoon door, net als bij 0.
    bericht = await _bericht_met_status(db_session, client, casus, "mislukt")
    _MM_GEPLAATST.clear()
    resp = await client.post(
        f"/api/casussen/{casus['id']}/kanaalberichten/{bericht['id']}/opnieuw"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "verstuurd"
    assert _MM_GEPLAATST == [(link["channel_id"], bericht["tekst"])]


async def test_onbekend_kanaal_wordt_niet_gekoppeld(client, casus):
    resp = await client.post(
        f"/api/casussen/{casus['id']}/mattermost-channels",
        json={
            "channel_id": _channel_id(),
            "channel_name": "bestaat-niet",
            "channel_display_name": "Bestaat niet",
        },
    )
    assert resp.status_code == 400


async def test_naam_komt_uit_mattermost(client, casus):
    # Wat de browser meestuurt, telt niet: anders kan iemand een groot
    # kanaal een onschuldige naam geven.
    verzoek = _kanaal("echte-naam")
    verzoek["channel_name"] = "verzonnen"
    verzoek["channel_display_name"] = "Casusteam intern"
    resp = await client.post(
        f"/api/casussen/{casus['id']}/mattermost-channels", json=verzoek
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["channel_name"] == "echte-naam"
    assert resp.json()["channel_display_name"] == "Echte naam"


async def test_zonder_mattermost_geen_koppeling(client, casus, monkeypatch):
    async def uit(self):
        return False

    monkeypatch.setattr(_NepMattermostService, "is_enabled", uit)
    resp = await client.post(
        f"/api/casussen/{casus['id']}/mattermost-channels", json=_kanaal()
    )
    assert resp.status_code == 503


async def test_ontkoppelen_via_slash_alleen_met_rechten(
    db_session, casus, lid, kijker, client
):
    link = await _koppel(client, casus)
    users = MattermostUserRepository(db_session)
    await users.create_mapping(
        person_id=kijker.id, mattermost_user_id="mm-kijker", mattermost_username="k"
    )
    await users.create_mapping(
        person_id=lid.id, mattermost_user_id="mm-lid", mattermost_username="l"
    )
    slash = MattermostSlashService(db_session)
    kanaalpad = f"/api/casussen/{casus['id']}/mattermost-channels"

    antwoord = await slash.handle_command(
        "mm-kijker", "ontkoppel", channel_id=link["channel_id"], channel_name="k"
    )
    assert "trekker" in antwoord["text"]
    assert len((await client.get(kanaalpad)).json()) == 1

    antwoord = await slash.handle_command(
        "mm-lid", "ontkoppel", channel_id=link["channel_id"], channel_name="k"
    )
    assert "verwijderd" in antwoord["text"]
    assert (await client.get(kanaalpad)).json() == []


async def test_kanaalstatus_alleen_voor_wie_de_casus_ziet(
    db_session, client, casus, lid, buitenstaander
):
    link = await _koppel(client, casus)
    users = MattermostUserRepository(db_session)
    await users.create_mapping(
        person_id=lid.id, mattermost_user_id="mm-lid", mattermost_username="l"
    )
    await users.create_mapping(
        person_id=buitenstaander.id,
        mattermost_user_id="mm-buiten",
        mattermost_username="b",
    )
    slash = MattermostSlashService(db_session)
    for wie in ("mm-buiten", "mm-onbekend"):
        antwoord = await slash.handle_command(
            wie, "kanaal", channel_id=link["channel_id"], channel_name="k"
        )
        assert "Kanaalcasus" not in antwoord["text"]
        assert "geen toegang" in antwoord["text"]
    antwoord = await slash.handle_command(
        "mm-lid", "kanaal", channel_id=link["channel_id"], channel_name="k"
    )
    assert "Kanaalcasus" in antwoord["text"]


async def test_koppelen_en_ontkoppelen_staan_in_het_log(db_session, client, casus):
    link = await _koppel(client, casus)
    pad = f"/api/mattermost-channels/{link['id']}"
    await client.patch(pad, json={"casus_updates_enabled": False})
    await client.delete(pad)
    rijen = (
        await db_session.execute(
            select(Activity.event_type, Activity.details).where(
                Activity.event_type.like("casus.kanaal_%")
            )
        )
    ).all()
    soorten = [r.event_type for r in rijen]
    assert sorted(soorten) == [
        "casus.kanaal_gekoppeld",
        "casus.kanaal_ontkoppeld",
        "casus.kanaal_voortgang",
    ]
    assert all(r.details["casus_id"] == casus["id"] for r in rijen)


async def test_alleen_de_schakelaars_van_de_soort(client, casus, initiatief):
    link = await _koppel(client, casus)
    resp = await client.patch(
        f"/api/mattermost-channels/{link['id']}", json={"auto_note_enabled": True}
    )
    assert resp.status_code == 400
    resp = await client.post(
        f"/api/initiatieven/{initiatief.id}/mattermost-channels",
        json=_kanaal("initiatief-kanaal"),
    )
    assert resp.status_code == 201, resp.text
    resp = await client.patch(
        f"/api/mattermost-channels/{resp.json()['id']}",
        json={"casus_updates_enabled": True},
    )
    assert resp.status_code == 400


async def test_initiatief_weg_dan_ook_de_casuskanalen(
    db_session, client, casus, initiatief
):
    # Zonder FK blijft een koppeling anders naar een verdwenen casus wijzen:
    # dan is het kanaal nergens meer te koppelen, en alleen een
    # systeembeheerder haalt hem nog weg.
    link = await _koppel(client, casus)
    resp = await client.delete(f"/api/initiatieven/{initiatief.id}")
    assert resp.status_code == 204, resp.text
    repo = MattermostChannelLinkRepository(db_session)
    assert await repo.get_by_channel_id(link["channel_id"]) is None


async def test_casus_weg_dan_alleen_het_leadkanaal_terug(db_session, client, lead):
    resp = await client.post(
        f"/api/leads/{lead.id}/mattermost-channels", json=_kanaal("lead-kanaal")
    )
    assert resp.status_code == 201, resp.text
    leadkanaal = resp.json()
    casus = await _start(client, lead)
    # Een privékanaal dat het team zelf aan de casus hing: op de lead zou
    # het meelezen onder de ruimere regels van een lead.
    eigen = await _koppel(client, casus, "casusteam")
    # Met een bewaard bericht: dat gaat mee weg met de casus.
    await client.put(
        f"/api/casussen/{casus['id']}", json={"fase": DEFAULT_CASUS_FASES[1].id}
    )
    resp = await client.delete(f"/api/casussen/{casus['id']}")
    assert resp.status_code == 204, resp.text

    leadkanalen = await client.get(f"/api/leads/{lead.id}/mattermost-channels")
    [terug] = leadkanalen.json()
    assert terug["id"] == leadkanaal["id"]
    assert terug["auto_note_enabled"] is True
    repo = MattermostChannelLinkRepository(db_session)
    assert await repo.get_by_channel_id(eigen["channel_id"]) is None


# ---------------------------------------------------------------------------
# Berichten
# ---------------------------------------------------------------------------


async def test_fasewissel_geeft_bericht(db_session, client, casus):
    link = await _koppel(client, casus)
    eerste, tweede = DEFAULT_CASUS_FASES[0], DEFAULT_CASUS_FASES[1]
    voor = _aantal(db_session)
    resp = await client.put(f"/api/casussen/{casus['id']}", json={"fase": tweede.id})
    assert resp.status_code == 200, resp.text

    berichten = kanaal.wachtende_berichten(db_session)[voor:]
    assert len(berichten) == 1
    assert berichten[0].channel_ids == (link["channel_id"],)
    tekst = berichten[0].tekst
    assert f"naar fase **{tweede.naam}**" in tekst
    assert f"(was {eerste.naam})" in tekst
    assert f"casussen?casus={casus['id']}" in tekst

    [bewaard] = await _bewaard(client, casus)
    assert bewaard["tekst"] == tekst
    assert bewaard["kanalen"] == ["Casus kanaal"]
    assert bewaard["status"] == "wacht"


async def test_zelfde_fase_geen_bericht(db_session, client, casus):
    await _koppel(client, casus)
    voor = _aantal(db_session)
    await client.put(f"/api/casussen/{casus['id']}", json={"fase": casus["fase"]})
    assert _teksten(db_session, voor) == []


async def test_zonder_kanaal_alleen_bij_de_casus(db_session, client, casus):
    voor = _aantal(db_session)
    await client.put(
        f"/api/casussen/{casus['id']}", json={"fase": DEFAULT_CASUS_FASES[1].id}
    )
    await client.post(f"/api/casussen/{casus['id']}/issues", json={"title": "Vraag"})
    # Niets naar Mattermost, wel te zien bij de casus; nieuwste eerst.
    assert _teksten(db_session, voor) == []
    issue, fase = await _bewaard(client, casus)
    assert "Nieuw in casus **Kanaalcasus**" in issue["tekst"]
    assert "naar fase" in fase["tekst"]
    assert issue["status"] == fase["status"] == "geen_kanaal"
    assert issue["kanalen"] == fase["kanalen"] == []


async def test_voortgang_uit_geen_bericht(db_session, client, casus):
    link = await _koppel(client, casus)
    await client.patch(
        f"/api/mattermost-channels/{link['id']}",
        json={"casus_updates_enabled": False},
    )
    voor = _aantal(db_session)
    await client.put(
        f"/api/casussen/{casus['id']}", json={"fase": DEFAULT_CASUS_FASES[1].id}
    )
    assert _teksten(db_session, voor) == []
    [bewaard] = await _bewaard(client, casus)
    assert bewaard["status"] == "geen_kanaal"


async def test_issue_nieuw_en_afgerond(db_session, client, casus):
    await _koppel(client, casus)
    voor = _aantal(db_session)
    resp = await client.post(
        f"/api/casussen/{casus['id']}/issues",
        json={"title": "Werkt het?", "toelichting": "Kijk naar artikel 3."},
    )
    assert resp.status_code == 201, resp.text
    issue = resp.json()
    [nieuw] = _teksten(db_session, voor)
    assert "Nieuw in casus **Kanaalcasus**: onderzoeksvraag **Werkt het?**" in nieuw
    assert "> Kijk naar artikel 3." in nieuw

    # Onderweg geen bericht, pas als hij af is.
    voor = _aantal(db_session)
    pad = f"/api/casussen/{casus['id']}/issues/{issue['id']}"
    await client.put(pad, json={"status": "in_progress"})
    assert _teksten(db_session, voor) == []
    resp = await client.put(pad, json={"status": "done"})
    assert resp.status_code == 200, resp.text
    [af] = _teksten(db_session, voor)
    assert "Onderzoeksvraag **Werkt het?** is afgerond" in af

    # Nog een keer opslaan als afgerond is geen nieuw bericht.
    voor = _aantal(db_session)
    await client.put(pad, json={"title": "Werkt het echt?"})
    assert _teksten(db_session, voor) == []


async def test_bericht_noemt_wie_het_deed(db_session, client, casus, lid):
    await _koppel(client, casus)
    voor = _aantal(db_session)
    async with client_as(db_session, lid) as c:
        resp = await c.post(
            f"/api/casussen/{casus['id']}/issues", json={"title": "Vraag"}
        )
        assert resp.status_code == 201, resp.text
    [tekst] = _teksten(db_session, voor)
    assert "Door Teamlid" in tekst


class _NepMattermost:
    """Doet alsof: plaatst niets, onthoudt wat het zou plaatsen."""

    def __init__(
        self,
        aan: bool = True,
        mislukt: set[str] | None = None,
        open: set[str] | None = None,
    ):
        self.aan = aan
        self.mislukt = mislukt or set()
        self.open = open or set()
        self.geplaatst: list[tuple[str, str]] = []

    async def is_enabled(self) -> bool:
        return self.aan

    async def get_channel(self, channel_id: str) -> dict:
        return {"id": channel_id, "type": "O" if channel_id in self.open else "P"}

    async def send_channel_message(self, channel_id: str, tekst: str) -> bool:
        if channel_id in self.mislukt:
            return False
        self.geplaatst.append((channel_id, tekst))
        return True


async def test_na_het_versturen_staat_erbij_hoe_het_afliep(db_session, client, casus):
    eerste = await _koppel(client, casus, "eerste")
    tweede = await _koppel(client, casus, "tweede")
    voor = _aantal(db_session)
    for fase in DEFAULT_CASUS_FASES[1:5]:
        await client.put(f"/api/casussen/{casus['id']}", json={"fase": fase.id})
    gelukt, half, uit, openbaar = kanaal.wachtende_berichten(db_session)[voor:]
    assert gelukt.channel_ids == (eerste["channel_id"], tweede["channel_id"])

    mm = _NepMattermost()
    statussen = await kanaal.plaats(mm, [gelukt])
    assert [c for c, _ in mm.geplaatst] == list(gelukt.channel_ids)
    statussen |= await kanaal.plaats(
        _NepMattermost(mislukt={tweede["channel_id"]}), [half]
    )
    mm = _NepMattermost(aan=False)
    statussen |= await kanaal.plaats(mm, [uit])
    assert mm.geplaatst == []
    # Na het koppelen openbaar gemaakt: daar gaat niets meer heen.
    mm = _NepMattermost(open={tweede["channel_id"]})
    statussen |= await kanaal.plaats(mm, [openbaar])
    assert [c for c, _ in mm.geplaatst] == [eerste["channel_id"]]
    await kanaal.zet_status(db_session, statussen)

    bewaard = {b["id"]: b for b in await _bewaard(client, casus)}
    assert bewaard[str(gelukt.bericht_id)]["status"] == "verstuurd"
    assert bewaard[str(half.bericht_id)]["status"] == "mislukt"
    assert bewaard[str(uit.bericht_id)]["status"] == "uit"
    assert bewaard[str(uit.bericht_id)]["kanalen"] == ["Eerste", "Tweede"]
    assert bewaard[str(openbaar.bericht_id)]["status"] == "mislukt"


# ---------------------------------------------------------------------------
# Opmaak
# ---------------------------------------------------------------------------


def _casus(**velden):
    return SimpleNamespace(
        id=uuid.uuid4(),
        initiatief_id=uuid.uuid4(),
        title="Casus",
        initiatief=None,
        **velden,
    )


def test_titel_wordt_ge_escaped():
    casus = _casus()
    issue = SimpleNamespace(
        title="*vet* en @iedereen", toelichting=None, is_onderzoeksvraag=False
    )
    tekst = kanaal.bericht_issue_nieuw(casus, issue, None)
    assert "**\\*vet\\* en @\u200biedereen**" in tekst
    assert "issue **" in tekst


def test_vermelding_en_kanaal_krijgen_een_zero_width_space():
    # Een backslash houdt een vermelding niet tegen: Mattermost knipt de
    # tekst op de server op de backslash en ziet gewoon `@channel`, en in de
    # client blijft de backslash staan. Gemeten tegen 9.5.14 op 20 november
    # 2026: met backslash een melding, met een zero-width space niet.
    casus = _casus()
    issue = SimpleNamespace(
        title="Let op @channel en @here in ~casus-prive",
        toelichting="Voor @iedereen",
        is_onderzoeksvraag=False,
    )
    tekst = kanaal.bericht_issue_nieuw(casus, issue, None)
    zw = kanaal.ZERO_WIDTH_SPACE
    assert f"@{zw}channel en @{zw}here in ~{zw}casus-prive" in tekst
    assert f"> Voor @{zw}iedereen" in tekst
    assert "\\@" not in tekst
    assert "\\~" not in tekst


def test_inhoud_kort_en_op_een_regel():
    casus = _casus()
    lang = "woord " * 200
    issue = SimpleNamespace(title="Vraag", toelichting=lang, is_onderzoeksvraag=True)
    tekst = kanaal.bericht_issue_nieuw(casus, issue, None)
    citaat = next(r for r in tekst.splitlines() if r.startswith("> "))
    assert citaat.endswith("…")
    assert len(citaat) <= kanaal.MAX_INHOUD + 3


def test_inhoud_uit_tiptap_is_platte_tekst():
    casus = _casus()
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Eerste"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "tweede"}]},
        ],
    }
    issue = SimpleNamespace(
        title="Vraag", toelichting=json.dumps(doc), is_onderzoeksvraag=True
    )
    tekst = kanaal.bericht_issue_nieuw(casus, issue, None)
    assert "> Eerste tweede" in tekst
    assert '"type"' not in tekst


def test_backslash_maakt_escapen_niet_ongedaan():
    # `\[hier\]` mag geen `\\[hier\\]` worden: dan staat er een gewone
    # backslash met een werkende link erachter. Een backslash voor een
    # vermelding blijft een gewone backslash; de zero-width space erachter
    # houdt de vermelding tegen.
    casus = _casus()
    issue = SimpleNamespace(
        title="Kijk \\@channel \\[hier\\](https://nep.example)",
        toelichting=None,
        is_onderzoeksvraag=False,
    )
    kop = kanaal.bericht_issue_nieuw(casus, issue, None).split("\n\n")[0]
    assert f"\\\\@{kanaal.ZERO_WIDTH_SPACE}channel" in kop
    assert "\\\\\\[hier\\\\\\]" in kop


def test_geen_autolink_naar_een_vermelding():
    casus = _casus()
    issue = SimpleNamespace(
        title="Zie <node:123>", toelichting=None, is_onderzoeksvraag=False
    )
    tekst = kanaal.bericht_issue_nieuw(casus, issue, None)
    assert "\\<node:123>" in tekst


def test_regeleinde_in_titel_maakt_geen_eigen_regels():
    casus = _casus()
    issue = SimpleNamespace(
        title="Vraag\n\nDoor Iemand · https://nep.example\n> citaat",
        toelichting=None,
        is_onderzoeksvraag=False,
    )
    tekst = kanaal.bericht_issue_nieuw(casus, issue, None)
    kop, voet = tekst.split("\n\n")
    assert "\n" not in kop
    assert "Vraag Door Iemand" in kop
    assert voet.startswith("[Open in Bouwmeester](")


def test_rare_tiptap_geeft_geen_fout():
    casus = _casus()
    doc = {
        "type": "doc",
        "content": [
            "los",
            5,
            {"type": "mention", "attrs": ["geen", "dict"]},
            {"type": "paragraph", "content": "geen lijst"},
            {"type": "paragraph", "content": [{"type": "text", "text": "Goed"}]},
        ],
    }
    issue = SimpleNamespace(
        title="Vraag", toelichting=json.dumps(doc), is_onderzoeksvraag=True
    )
    tekst = kanaal.bericht_issue_nieuw(casus, issue, None)
    assert "> Goed" in tekst


async def test_issue_met_rare_toelichting_is_af_te_ronden(client, casus):
    rare = json.dumps({"type": "doc", "content": ["x", 5]})
    resp = await client.post(
        f"/api/casussen/{casus['id']}/issues",
        json={"title": "Vraag", "toelichting": rare},
    )
    assert resp.status_code == 201, resp.text
    pad = f"/api/casussen/{casus['id']}/issues/{resp.json()['id']}"
    resp = await client.put(pad, json={"status": "done"})
    assert resp.status_code == 200, resp.text


def test_voetregel_staat_los_van_het_citaat():
    # Zonder lege regel hoort "Door ..." in markdown nog bij het citaat.
    casus = _casus()
    issue = SimpleNamespace(
        title="Vraag", toelichting="Kijk hier.", is_onderzoeksvraag=True
    )
    tekst = kanaal.bericht_issue_nieuw(casus, issue, "Teamlid")
    _kop, citaat, voet = tekst.split("\n\n")
    assert citaat == "> Kijk hier."
    assert voet.startswith("Door Teamlid · [Open in Bouwmeester](")


def test_zonder_initiatief_geen_link():
    casus = _casus()
    casus.initiatief_id = None
    tekst = kanaal.bericht_fase(casus, None, DEFAULT_CASUS_FASES[0].id, None)
    assert "Open in Bouwmeester" not in tekst


# ---------------------------------------------------------------------------
# Na de commit, en wat daarna nog mis kan gaan
# ---------------------------------------------------------------------------


async def test_savepoint_verstuurt_nog_niets(db_session, client, casus, monkeypatch):
    # `after_commit` vuurt ook als een savepoint wordt vrijgegeven. Dan is
    # er nog niets gecommit: het bericht moet blijven wachten op de echte
    # commit, en dan precies één keer weggaan.
    verstuurd: list[list[kanaal.Bericht]] = []

    async def _nep_verstuur(berichten):
        verstuurd.append(berichten)

    monkeypatch.setattr(kanaal, "_verstuur", _nep_verstuur)
    await _koppel(client, casus)
    voor = _aantal(db_session)
    await kanaal.meld(db_session, uuid.UUID(casus["id"]), "Eerste bericht")
    async with db_session.begin_nested():
        await kanaal.meld(db_session, uuid.UUID(casus["id"]), "Tweede bericht")
    assert verstuurd == []
    assert _teksten(db_session, voor) == ["Eerste bericht", "Tweede bericht"]

    await db_session.commit()
    await asyncio.sleep(0)
    assert [b.tekst for b in verstuurd[0]] == ["Eerste bericht", "Tweede bericht"]
    assert len(verstuurd) == 1
    assert kanaal.wachtende_berichten(db_session) == []

    # Een tweede commit zonder nieuw bericht verstuurt niets nog een keer.
    await db_session.commit()
    await asyncio.sleep(0)
    assert len(verstuurd) == 1


async def _bericht_met_status(
    db_session, client, casus, status: str, fase: int = 1
) -> dict:
    """Een bewaard bericht van de casus (een fasewissel), met deze status."""
    voor = _aantal(db_session)
    resp = await client.put(
        f"/api/casussen/{casus['id']}", json={"fase": DEFAULT_CASUS_FASES[fase].id}
    )
    assert resp.status_code == 200, resp.text
    (bericht,) = kanaal.wachtende_berichten(db_session)[voor:]
    await kanaal.zet_status(db_session, {bericht.bericht_id: status})
    bewaard = {b["id"]: b for b in await _bewaard(client, casus)}
    return bewaard[str(bericht.bericht_id)]


async def test_mislukt_bericht_gaat_opnieuw(db_session, client, casus):
    link = await _koppel(client, casus)
    bericht = await _bericht_met_status(db_session, client, casus, "mislukt")
    _MM_GEPLAATST.clear()

    pad = f"/api/casussen/{casus['id']}/kanaalberichten/{bericht['id']}/opnieuw"
    resp = await client.post(pad)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "verstuurd"
    assert _MM_GEPLAATST == [(link["channel_id"], bericht["tekst"])]
    bewaard = {b["id"]: b for b in await _bewaard(client, casus)}
    assert bewaard[bericht["id"]]["status"] == "verstuurd"

    # Nog eens: al verstuurd, dus niet nog een keer.
    resp = await client.post(pad)
    assert resp.status_code == 400, resp.text
    assert len(_MM_GEPLAATST) == 1

    # Het staat in het log, met de kanalen en hoe het afliep.
    rows = await db_session.execute(
        select(Activity).where(Activity.event_type == "casus.kanaalbericht_opnieuw")
    )
    (activiteit,) = rows.scalars().all()
    assert activiteit.details["status"] == "verstuurd"
    assert activiteit.details["kanalen"] == [link["channel_display_name"]]


async def test_opnieuw_volgt_dezelfde_controles(db_session, client, casus):
    # Het kanaal is inmiddels openbaar: dan gaat er ook bij opnieuw niets heen.
    link = await _koppel(client, casus)
    bericht = await _bericht_met_status(db_session, client, casus, "mislukt")
    _MM_KANALEN[link["channel_id"]]["type"] = "O"
    _MM_GEPLAATST.clear()
    resp = await client.post(
        f"/api/casussen/{casus['id']}/kanaalberichten/{bericht['id']}/opnieuw"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "mislukt"
    assert _MM_GEPLAATST == []


async def test_opnieuw_alleen_voor_wie_de_casus_wijzigt(
    db_session, client, casus, kijker, buitenstaander
):
    await _koppel(client, casus)
    bericht = await _bericht_met_status(db_session, client, casus, "mislukt")
    pad = f"/api/casussen/{casus['id']}/kanaalberichten/{bericht['id']}/opnieuw"
    async with client_as(db_session, kijker) as c:
        assert (await c.post(pad)).status_code == 403
    async with client_as(db_session, buitenstaander) as c:
        assert (await c.post(pad)).status_code == 404
    # Een bericht van een andere casus hoort niet bij deze.
    resp = await client.post(
        f"/api/casussen/{uuid.uuid4()}/kanaalberichten/{bericht['id']}/opnieuw"
    )
    assert resp.status_code == 404


async def test_worker_pakt_op_wat_bleef_hangen(db_session, client, casus):
    # Herstart het proces tussen de commit en het versturen, dan blijft
    # "wacht" staan. Na tien minuten is dat blijven hangen, niet onderweg.
    link = await _koppel(client, casus)
    oud = await _bericht_met_status(db_session, client, casus, "wacht", fase=1)
    vers = await _bericht_met_status(db_session, client, casus, "wacht", fase=2)
    await db_session.execute(
        update(CasusKanaalbericht)
        .where(CasusKanaalbericht.id == uuid.UUID(oud["id"]))
        .values(created_at=datetime.now(UTC) - timedelta(minutes=11))
    )
    mm = _NepMattermost()
    assert await kanaal.verstuur_blijven_hangen(db_session, mm) == 1
    assert mm.geplaatst == [(link["channel_id"], oud["tekst"])]
    bewaard = {b["id"]: b for b in await _bewaard(client, casus)}
    assert bewaard[oud["id"]]["status"] == "verstuurd"
    assert bewaard[vers["id"]]["status"] == "wacht"
    assert await kanaal.verstuur_blijven_hangen(db_session, mm) == 0


async def test_opnieuw_alleen_naar_de_kanalen_van_nu(db_session, client, casus):
    # Het bericht onthoudt de kanalen van toen. Is er sindsdien een
    # ontkoppeld, dan mag het daar niet alsnog heen.
    eerste = await _koppel(client, casus, "eerste")
    tweede = await _koppel(client, casus, "tweede")
    bericht = await _bericht_met_status(db_session, client, casus, "mislukt")
    assert sorted(bericht["kanalen"]) == ["Eerste", "Tweede"]
    resp = await client.delete(f"/api/mattermost-channels/{tweede['id']}")
    assert resp.status_code == 204, resp.text
    _MM_GEPLAATST.clear()
    resp = await client.post(
        f"/api/casussen/{casus['id']}/kanaalberichten/{bericht['id']}/opnieuw"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "verstuurd"
    assert _MM_GEPLAATST == [(eerste["channel_id"], bericht["tekst"])]
    # Bij de casus en in het log staat waar het echt heen ging.
    assert resp.json()["kanalen"] == ["Eerste"]
    bewaard = {b["id"]: b for b in await _bewaard(client, casus)}
    assert bewaard[bericht["id"]]["kanalen"] == ["Eerste"]
    rows = await db_session.execute(
        select(Activity).where(Activity.event_type == "casus.kanaalbericht_opnieuw")
    )
    (activiteit,) = rows.scalars().all()
    assert activiteit.details["kanalen"] == ["Eerste"]


async def test_opnieuw_gaat_nergens_heen_zonder_kanaal_van_nu(
    db_session, client, casus, initiatief
):
    link = await _koppel(client, casus)
    pad = f"/api/casussen/{casus['id']}/kanaalberichten/{{}}/opnieuw"

    # Voortgang uit: het team wil dit kanaal (even) niet meer.
    uit = await _bericht_met_status(db_session, client, casus, "mislukt", fase=1)
    resp = await client.patch(
        f"/api/mattermost-channels/{link['id']}", json={"casus_updates_enabled": False}
    )
    assert resp.status_code == 200, resp.text
    _MM_GEPLAATST.clear()
    resp = await client.post(pad.format(uit["id"]))
    assert resp.status_code == 400, resp.text
    assert "voortgang" in resp.json()["detail"]
    assert _MM_GEPLAATST == []

    # Ontkoppeld, en het kanaal hangt inmiddels aan een andere lead.
    resp = await client.patch(
        f"/api/mattermost-channels/{link['id']}", json={"casus_updates_enabled": True}
    )
    assert resp.status_code == 200, resp.text
    weg = await _bericht_met_status(db_session, client, casus, "mislukt", fase=2)
    resp = await client.delete(f"/api/mattermost-channels/{link['id']}")
    assert resp.status_code == 204, resp.text
    andere = Lead(
        id=uuid.uuid4(),
        title="Andere lead",
        stage="in_the_pocket",
        initiatief_id=initiatief.id,
    )
    db_session.add(andere)
    await db_session.flush()
    resp = await client.post(
        f"/api/leads/{andere.id}/mattermost-channels",
        json={
            "channel_id": link["channel_id"],
            "channel_name": link["channel_name"],
            "channel_display_name": link["channel_display_name"],
        },
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(pad.format(weg["id"]))
    assert resp.status_code == 400, resp.text
    assert _MM_GEPLAATST == []
    bewaard = {b["id"]: b for b in await _bewaard(client, casus)}
    assert bewaard[weg["id"]]["status"] == "mislukt"


async def test_worker_laat_een_ontkoppeld_kanaal_met_rust(db_session, client, casus):
    link = await _koppel(client, casus)
    oud = await _bericht_met_status(db_session, client, casus, "wacht")
    await db_session.execute(
        update(CasusKanaalbericht)
        .where(CasusKanaalbericht.id == uuid.UUID(oud["id"]))
        .values(created_at=datetime.now(UTC) - timedelta(minutes=11))
    )
    resp = await client.delete(f"/api/mattermost-channels/{link['id']}")
    assert resp.status_code == 204, resp.text
    mm = _NepMattermost()
    assert await kanaal.verstuur_blijven_hangen(db_session, mm) == 1
    assert mm.geplaatst == []
    bewaard = {b["id"]: b for b in await _bewaard(client, casus)}
    assert bewaard[oud["id"]]["status"] == "mislukt"


async def test_vers_bericht_op_wacht_gaat_niet_opnieuw(db_session, client, casus):
    # Nog onderweg: nog een keer versturen zou het dubbel laten aankomen.
    await _koppel(client, casus)
    vers = await _bericht_met_status(db_session, client, casus, "wacht")
    resp = await client.post(
        f"/api/casussen/{casus['id']}/kanaalberichten/{vers['id']}/opnieuw"
    )
    assert resp.status_code == 400, resp.text
    assert "onderweg" in resp.json()["detail"]


async def test_kijker_krijgt_403_voor_de_inhoud_van_het_verzoek(
    db_session, client, casus, kijker
):
    # Eerst de rechten, dan pas de 400 over schakelaars die niet bij een
    # casus horen.
    link = await _koppel(client, casus)
    async with client_as(db_session, kijker) as c:
        resp = await c.patch(
            f"/api/mattermost-channels/{link['id']}", json={"auto_note_enabled": True}
        )
    assert resp.status_code == 403, resp.text


async def test_weer_aanzetten_staat_in_het_log(db_session, client, casus):
    link = await _koppel(client, casus)
    resp = await client.patch(
        f"/api/mattermost-channels/{link['id']}", json={"reenable": True}
    )
    assert resp.status_code == 200, resp.text
    rows = await db_session.execute(
        select(Activity).where(Activity.event_type == "casus.kanaal_weer_aan")
    )
    (activiteit,) = rows.scalars().all()
    assert activiteit.details["casus_id"] == casus["id"]
