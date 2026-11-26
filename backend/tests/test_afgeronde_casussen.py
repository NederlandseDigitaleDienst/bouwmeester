"""Afgeronde casussen en hun lessen naar buiten, via Updates.

De casus zelf gaat nooit naar buiten. Van een afgeronde casus (in de laatste
fase van de funnel) gaat alleen een tekst naar buiten die iemand daarvoor
schreef en vrijgaf. Dekt: lessen vastleggen (binnen), vrijgeven alleen voor
een afgeronde casus en alleen door een bijdrager of eigenaar, uit de laatste
fase trekt in (ook als de funnel verandert), de publieke pagina en de
mailbrief tonen alleen de tekst voor buiten, een update neemt alleen
vrijgegeven casussen van het eigen initiatief mee, en het overzicht "klaar
om te delen" in de tab Updates.
"""

import email
import uuid
from email import policy

import pytest

from bouwmeester.core.config import get_settings
from bouwmeester.models.casus import Casus
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.schema.casus_fases import DEFAULT_CASUS_FASES
from tests.factories import client_as, make_person

LAATSTE = DEFAULT_CASUS_FASES[-1].id
INTERNE_TITEL = "Gemeente X: kwijtschelding met contactpersoon Jansen"
INTERNE_LESSEN = "Jansen reageert traag, volgende keer eerder bellen"
NAAM = "Kwijtschelding van gemeentelijke belastingen"
RESULTAAT = "Een werkend regelwerk voor de kwijtscheldingsnorm."
LESSEN = "Begin met de uitzonderingen, daar zit het meeste werk."
SLUG = "rr-casus-buiten"


@pytest.fixture
async def initiatief(db_session):
    init = Initiatief(
        id=uuid.uuid4(),
        naam="Regelrecht casussen",
        slug=SLUG,
        casussen_enabled=True,
        public_page_enabled=True,
    )
    db_session.add(init)
    await db_session.flush()
    return init


async def _casus(db_session, initiatief, title=INTERNE_TITEL, fase="start"):
    lead = Lead(
        id=uuid.uuid4(), title=title, stage="in_the_pocket", initiatief_id=initiatief.id
    )
    db_session.add(lead)
    await db_session.flush()
    c = Casus(
        id=uuid.uuid4(),
        lead_id=lead.id,
        title=title,
        description="Vertrouwelijke beschrijving",
        initiatief_id=initiatief.id,
        fase=fase,
    )
    db_session.add(c)
    await db_session.flush()
    return c


@pytest.fixture
async def casus(db_session, initiatief):
    return await _casus(db_session, initiatief, fase=LAATSTE)


async def _vrijgeven(client, casus, **velden):
    data = {
        "public_title": NAAM,
        "public_resultaat": RESULTAAT,
        "public_lessen": LESSEN,
    }
    data.update(velden)
    return await client.put(f"/api/casussen/{casus.id}/publiek", json=data)


async def _publiek(client):
    resp = await client.get(f"/api/public/initiatieven/by-slug/{SLUG}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _lekt_niets(tekst: str) -> None:
    for intern in (INTERNE_TITEL, INTERNE_LESSEN, "Vertrouwelijke beschrijving"):
        assert intern not in tekst, f"interne tekst naar buiten: {intern}"


async def _rol(db_session, person, resource_type, resource_id, rol):
    db_session.add(
        ResourcePermission(
            person_id=person.id,
            resource_type=resource_type,
            resource_id=resource_id,
            rol=rol,
        )
    )
    await db_session.flush()


# --- Lessen en vrijgeven -------------------------------------------------------


async def test_lessen_vastleggen_blijft_binnen(client, casus):
    resp = await client.put(
        f"/api/casussen/{casus.id}", json={"lessen": INTERNE_LESSEN}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["lessen"] == INTERNE_LESSEN
    assert resp.json()["published_at"] is None
    _lekt_niets(str(await _publiek(client)))


async def test_niet_afgerond_kan_niet_naar_buiten(client, db_session, initiatief):
    lopend = await _casus(db_session, initiatief, fase="start")
    resp = await _vrijgeven(client, lopend)
    assert resp.status_code == 400
    assert "Rond de casus eerst af" in resp.json()["detail"]


async def test_vrijgeven_en_publieke_pagina(client, casus):
    await client.put(f"/api/casussen/{casus.id}", json={"lessen": INTERNE_LESSEN})
    resp = await _vrijgeven(client, casus)
    assert resp.status_code == 200, resp.text
    assert resp.json()["published_at"] is not None

    data = await _publiek(client)
    (buiten,) = data["afgeronde_casussen"]
    assert buiten["titel"] == NAAM
    assert buiten["resultaat"] == RESULTAAT
    assert buiten["lessen"] == LESSEN
    assert set(buiten) == {"titel", "resultaat", "lessen", "published_at"}
    _lekt_niets(str(data))


async def test_lessen_voor_buiten_zijn_optioneel(client, casus):
    resp = await _vrijgeven(client, casus, public_lessen=None)
    assert resp.status_code == 200, resp.text
    (buiten,) = (await _publiek(client))["afgeronde_casussen"]
    assert buiten["lessen"] is None


@pytest.mark.parametrize(
    "veld,tekst",
    [
        ("public_title", "   "),
        ("public_resultaat", ""),
        (
            "public_lessen",
            "Vraag het [@Jan Jansen](user:00000000-0000-0000-0000-000000000001)",
        ),
    ],
)
async def test_tekst_voor_buiten_wordt_gecontroleerd(client, casus, veld, tekst):
    resp = await _vrijgeven(client, casus, **{veld: tekst})
    assert resp.status_code == 422


async def test_uit_de_laatste_fase_trekt_in(client, casus):
    await _vrijgeven(client, casus)
    resp = await client.put(f"/api/casussen/{casus.id}", json={"fase": "start"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["published_at"] is None
    assert resp.json()["public_title"] == NAAM, "de tekst blijft bewaard"
    assert (await _publiek(client))["afgeronde_casussen"] == []

    # Opnieuw afronden geeft hem niet vanzelf weer vrij.
    await client.put(f"/api/casussen/{casus.id}", json={"fase": LAATSTE})
    assert (await _publiek(client))["afgeronde_casussen"] == []


async def test_intrekken(client, casus):
    await _vrijgeven(client, casus)
    resp = await client.delete(f"/api/casussen/{casus.id}/publiek")
    assert resp.status_code == 200
    assert resp.json()["published_at"] is None
    assert (await _publiek(client))["afgeronde_casussen"] == []


async def test_kijker_die_trekker_is(client, db_session, casus, initiatief):
    kijker = await make_person(db_session, "Kijker Trekker")
    await _rol(db_session, kijker, "initiatief", initiatief.id, "viewer")
    await _rol(db_session, kijker, "casus", casus.id, "trekker")
    async with client_as(db_session, kijker) as c:
        assert (await _vrijgeven(c, casus)).status_code == 403
    assert (await _vrijgeven(client, casus)).status_code == 200
    async with client_as(db_session, kijker) as c:
        resp = await c.delete(f"/api/casussen/{casus.id}/publiek")
        assert resp.status_code == 200, resp.text


async def test_publieke_pagina_uit(client, db_session, casus, initiatief):
    await _vrijgeven(client, casus)
    initiatief.public_page_enabled = False
    await db_session.flush()
    resp = await client.get(f"/api/public/initiatieven/by-slug/{SLUG}")
    assert resp.status_code == 404


# --- Updates ------------------------------------------------------------------


async def _update(client, initiatief, casus_ids=(), publish=True):
    return await client.post(
        f"/api/initiatieven/{initiatief.id}/updates",
        json={
            "titel": "Wat we afrondden",
            "publish": publish,
            "casus_ids": [str(c) for c in casus_ids],
        },
    )


async def test_update_neemt_vrijgegeven_casus_mee(client, casus, initiatief):
    await _vrijgeven(client, casus)
    resp = await _update(client, initiatief, [casus.id])
    assert resp.status_code == 201, resp.text
    (mee,) = resp.json()["casussen"]
    assert mee["titel"] == NAAM and mee["lessen"] == LESSEN

    (update,) = (await _publiek(client))["updates"]
    assert update["casussen"][0]["titel"] == NAAM
    _lekt_niets(str(update))


async def test_update_weigert_niet_vrijgegeven_casus(client, casus, initiatief):
    assert (await _update(client, initiatief, [casus.id])).status_code == 400


async def test_update_weigert_casus_van_ander_initiatief(
    client, db_session, initiatief
):
    ander = Initiatief(
        id=uuid.uuid4(), naam="Ander", slug="ander-casus", casussen_enabled=True
    )
    db_session.add(ander)
    await db_session.flush()
    andere = await _casus(db_session, ander, "Andere casus", fase=LAATSTE)
    await _vrijgeven(client, andere)
    assert (await _update(client, initiatief, [andere.id])).status_code == 400


async def test_ingetrokken_casus_valt_uit_de_update(client, casus, initiatief):
    await _vrijgeven(client, casus)
    await _update(client, initiatief, [casus.id])
    await client.put(f"/api/casussen/{casus.id}", json={"fase": "start"})
    (update,) = (await _publiek(client))["updates"]
    assert update["casussen"] == []


async def test_casussen_van_update_wijzigen(client, db_session, casus, initiatief):
    tweede = await _casus(db_session, initiatief, "Tweede casus", fase=LAATSTE)
    await _vrijgeven(client, casus)
    await _vrijgeven(client, tweede, public_title="Tweede voor buiten")
    post = (await _update(client, initiatief, [casus.id], publish=False)).json()
    resp = await client.put(
        f"/api/initiatieven/{initiatief.id}/updates/{post['id']}",
        json={"casus_ids": [str(tweede.id)]},
    )
    assert [c["titel"] for c in resp.json()["casussen"]] == ["Tweede voor buiten"]


async def test_mailbrief_noemt_de_casus(client, casus, initiatief, monkeypatch):
    monkeypatch.setattr(get_settings(), "FRONTEND_URL", "https://bouwmeester.test")
    await _vrijgeven(client, casus)
    post = (await _update(client, initiatief, [casus.id])).json()
    resp = await client.get(
        f"/api/initiatieven/{initiatief.id}/updates/{post['id']}/eml"
    )
    assert resp.status_code == 200
    msg = email.message_from_bytes(resp.content, policy=policy.default)
    for deel in ("html", "plain"):
        body = msg.get_body(preferencelist=(deel,)).get_content()
        assert "Afgeronde casussen" in body
        assert NAAM in body and RESULTAAT in body and LESSEN in body
        _lekt_niets(body)


# --- Klaar om te delen ----------------------------------------------------------


async def test_klaar_om_te_delen(client, db_session, casus, initiatief):
    await client.put(f"/api/casussen/{casus.id}", json={"lessen": INTERNE_LESSEN})
    lopend = await _casus(db_session, initiatief, "Lopende casus", fase="start")
    vraag = (
        await client.post(
            f"/api/casussen/{lopend.id}/issues", json={"title": "Afgeronde vraag"}
        )
    ).json()
    await client.put(
        f"/api/casussen/{lopend.id}/issues/{vraag['id']}", json={"status": "done"}
    )
    await client.post(f"/api/casussen/{lopend.id}/issues", json={"title": "Open vraag"})
    await _vrijgeven(client, casus)
    await _update(client, initiatief, [casus.id])

    resp = await client.get(f"/api/initiatieven/{initiatief.id}/klaar-om-te-delen")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert [v["titel"] for v in data["vragen"]] == ["Afgeronde vraag"]
    assert data["vragen"][0]["casus_titel"] == "Lopende casus"
    assert data["vragen"][0]["published_at"] is None
    (afgerond,) = data["casussen"]
    assert afgerond["titel"] == INTERNE_TITEL
    assert afgerond["lessen"] == INTERNE_LESSEN
    assert afgerond["in_gepubliceerde_update"] is True


async def test_klaar_om_te_delen_niet_voor_buitenstaanders(
    client, db_session, initiatief
):
    buiten = await make_person(db_session, "Buitenstaander")
    async with client_as(db_session, buiten) as c:
        resp = await c.get(f"/api/initiatieven/{initiatief.id}/klaar-om-te-delen")
    assert resp.status_code in (403, 404)


# --- Na de review van #461 ----------------------------------------------------


def _funnel(*extra):
    return [f.model_dump() for f in DEFAULT_CASUS_FASES] + list(extra)


NAZORG = {"id": "nazorg", "naam": "Nazorg", "kleur": "lintblauw"}


async def test_fase_achter_de_laatste_trekt_in(client, casus, initiatief):
    """Een fase achter de laatste: de casus staat niet meer in de laatste
    fase, dus is hij ingetrokken. Hij komt niet vanzelf terug als hij later
    in de nieuwe laatste fase staat."""
    await _vrijgeven(client, casus)
    resp = await client.put(
        f"/api/initiatieven/{initiatief.id}/settings",
        json={"casus_fases": _funnel(NAZORG)},
    )
    assert resp.status_code == 200, resp.text
    detail = (await client.get(f"/api/casussen/{casus.id}")).json()
    assert detail["published_at"] is None
    assert detail["public_title"] == NAAM, "de tekst blijft bewaard"
    assert (await _publiek(client))["afgeronde_casussen"] == []

    resp = await client.put(f"/api/casussen/{casus.id}", json={"fase": "nazorg"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["published_at"] is None
    assert (await _publiek(client))["afgeronde_casussen"] == []


async def test_funnel_wijzigen_laat_casus_in_laatste_fase_staan(
    client, casus, initiatief
):
    """Een andere omschrijving of kleur, dezelfde laatste fase: de casus blijft
    buiten."""
    await _vrijgeven(client, casus)
    funnel = _funnel()
    funnel[0]["naam"] = "Beginnen"
    resp = await client.put(
        f"/api/initiatieven/{initiatief.id}/settings", json={"casus_fases": funnel}
    )
    assert resp.status_code == 200, resp.text
    (buiten,) = (await _publiek(client))["afgeronde_casussen"]
    assert buiten["titel"] == NAAM


async def test_in_een_update_volgt_of_de_casus_buiten_is(client, casus, initiatief):
    await _vrijgeven(client, casus)
    await _update(client, initiatief, [casus.id])
    pad = f"/api/initiatieven/{initiatief.id}/klaar-om-te-delen"
    (klaar,) = (await client.get(pad)).json()["casussen"]
    assert klaar["in_gepubliceerde_update"] is True

    await client.delete(f"/api/casussen/{casus.id}/publiek")
    (klaar,) = (await client.get(pad)).json()["casussen"]
    assert klaar["published_at"] is None
    assert klaar["in_gepubliceerde_update"] is False
