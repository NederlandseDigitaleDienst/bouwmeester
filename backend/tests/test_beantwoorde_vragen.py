"""Beantwoorde onderzoeksvragen naar buiten, via Updates.

Casussen zijn nooit publiek. Een afgeronde onderzoeksvraag kan wel naar
buiten, maar alleen met een publieke vraag en een kort antwoord die iemand
bewust vrijgaf. Dekt: vrijgeven alleen voor een afgeronde onderzoeksvraag en
alleen door een bijdrager of eigenaar; heropenen trekt in; de publieke pagina
toont alleen de publieke tekst en nooit de casus; een update neemt alleen
vrijgegeven vragen van het eigen initiatief mee; de mailbrief; titel en
tekst van een update zonder @- of #-verwijzing, ook in de mailbrief en op de
publieke pagina; de stand "In een update" volgt of de vraag nog buiten is.
"""

import email
import uuid
from datetime import UTC, datetime
from email import policy

import pytest

from bouwmeester.core.config import get_settings
from bouwmeester.models.casus import Casus
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.initiatief_update import InitiatiefUpdatePost
from bouwmeester.models.lead import Lead
from bouwmeester.models.resource_permission import ResourcePermission
from tests.factories import client_as, make_person

GEHEIM = "Interne vraag over de hardheidsclausule bij gemeente X"
TOELICHTING = "Vertrouwelijk: contactpersoon Jansen belt donderdag"
CASUSTITEL = "Casus Gemeente X"
PUBLIEKE_VRAAG = "Kun je een hardheidsclausule uitvoerbaar maken?"
ANTWOORD = "Ja, met een expliciete beslisregel en een menselijke toets."


@pytest.fixture
async def initiatief(db_session):
    init = Initiatief(
        id=uuid.uuid4(),
        naam="Regelrecht buiten",
        slug="rr-buiten",
        casussen_enabled=True,
        public_page_enabled=True,
    )
    db_session.add(init)
    await db_session.flush()
    return init


async def _casus(db_session, initiatief, title=CASUSTITEL):
    lead = Lead(
        id=uuid.uuid4(), title=title, stage="in_the_pocket", initiatief_id=initiatief.id
    )
    db_session.add(lead)
    await db_session.flush()
    c = Casus(
        id=uuid.uuid4(), lead_id=lead.id, title=title, initiatief_id=initiatief.id
    )
    db_session.add(c)
    await db_session.flush()
    return c


@pytest.fixture
async def casus(db_session, initiatief):
    return await _casus(db_session, initiatief)


async def _vraag(client, casus, *, af=True, onderzoeksvraag=True):
    resp = await client.post(
        f"/api/casussen/{casus.id}/issues",
        json={
            "title": GEHEIM,
            "toelichting": TOELICHTING,
            "is_onderzoeksvraag": onderzoeksvraag,
        },
    )
    assert resp.status_code == 201, resp.text
    vraag = resp.json()
    if af:
        resp = await client.put(
            f"/api/casussen/{casus.id}/issues/{vraag['id']}", json={"status": "done"}
        )
        assert resp.status_code == 200, resp.text
        vraag = resp.json()
    return vraag


async def _vrijgeven(client, casus, vraag, vraagtekst=PUBLIEKE_VRAAG):
    return await client.put(
        f"/api/casussen/{casus.id}/issues/{vraag['id']}/publiek",
        json={"public_title": vraagtekst, "public_answer": ANTWOORD},
    )


async def _publiek(client, slug="rr-buiten"):
    resp = await client.get(f"/api/public/initiatieven/by-slug/{slug}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _lekt_niets(tekst: str) -> None:
    for intern in (GEHEIM, TOELICHTING, CASUSTITEL):
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


# --- Vrijgeven -------------------------------------------------------------


async def test_open_vraag_kan_niet_naar_buiten(client, casus):
    vraag = await _vraag(client, casus, af=False)
    resp = await _vrijgeven(client, casus, vraag)
    assert resp.status_code == 400
    assert "Rond de onderzoeksvraag eerst af" in resp.json()["detail"]


async def test_ander_issue_kan_niet_naar_buiten(client, casus):
    vraag = await _vraag(client, casus, onderzoeksvraag=False)
    resp = await _vrijgeven(client, casus, vraag)
    assert resp.status_code == 400


async def test_lege_publieke_tekst_is_422(client, casus):
    vraag = await _vraag(client, casus)
    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/{vraag['id']}/publiek",
        json={"public_title": "", "public_answer": ANTWOORD},
    )
    assert resp.status_code == 422


async def test_vraag_van_andere_casus_is_404(client, db_session, casus, initiatief):
    vraag = await _vraag(client, casus)
    andere = await _casus(db_session, initiatief, "Andere casus")
    resp = await _vrijgeven(client, andere, vraag)
    assert resp.status_code == 404


async def test_vrijgeven_zet_tekst_en_moment(client, casus):
    vraag = await _vraag(client, casus)
    resp = await _vrijgeven(client, casus, vraag)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["public_title"] == PUBLIEKE_VRAAG
    assert data["public_answer"] == ANTWOORD
    assert data["published_at"] is not None

    # Tekst aanpassen houdt het moment van vrijgeven.
    resp = await _vrijgeven(client, casus, vraag, "Een betere vraag?")
    assert resp.json()["published_at"] == data["published_at"]
    assert resp.json()["public_title"] == "Een betere vraag?"


async def test_backlog_toont_de_publieke_tekst(client, casus, initiatief):
    vraag = await _vraag(client, casus)
    await _vrijgeven(client, casus, vraag)
    resp = await client.get(f"/api/casussen/backlog?initiatief_id={initiatief.id}")
    assert resp.status_code == 200, resp.text
    (issue,) = [i for i in resp.json()["issues"] if i["id"] == vraag["id"]]
    assert issue["public_title"] == PUBLIEKE_VRAAG
    assert issue["published_at"] is not None


# --- De publieke pagina -----------------------------------------------------


async def test_publieke_pagina_toont_alleen_vrijgegeven_tekst(client, casus):
    binnen = await _vraag(client, casus)
    vraag = await _vraag(client, casus)
    await _vrijgeven(client, casus, vraag)

    data = await _publiek(client)
    assert data["beantwoorde_vragen"] == [
        {
            "vraag": PUBLIEKE_VRAAG,
            "antwoord": ANTWOORD,
            "published_at": data["beantwoorde_vragen"][0]["published_at"],
            "verslag": None,
        }
    ]
    # Geen id's, geen interne titel, toelichting of casus.
    _lekt_niets(str(data))
    assert binnen["id"] not in str(data) and vraag["id"] not in str(data)


async def test_heropenen_trekt_in(client, casus):
    vraag = await _vraag(client, casus)
    await _vrijgeven(client, casus, vraag)
    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/{vraag['id']}", json={"status": "open"}
    )
    assert resp.status_code == 200
    assert resp.json()["published_at"] is None
    # De tekst blijft bewaard, binnen.
    assert resp.json()["public_title"] == PUBLIEKE_VRAAG
    assert (await _publiek(client))["beantwoorde_vragen"] == []

    # Opnieuw afronden geeft hem niet vanzelf weer vrij.
    await client.put(
        f"/api/casussen/{casus.id}/issues/{vraag['id']}", json={"status": "done"}
    )
    assert (await _publiek(client))["beantwoorde_vragen"] == []


async def test_geen_onderzoeksvraag_meer_trekt_in(client, casus):
    vraag = await _vraag(client, casus)
    await _vrijgeven(client, casus, vraag)
    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/{vraag['id']}",
        json={"is_onderzoeksvraag": False},
    )
    assert resp.json()["published_at"] is None
    assert (await _publiek(client))["beantwoorde_vragen"] == []


async def test_taak_weer_open_trekt_in(client, casus):
    """De status volgt de taken: een taak die weer in uitvoering gaat, zet
    een afgeronde vraag terug naar in behandeling. Dan is hij niet meer
    beantwoord, dus ook niet meer buiten."""
    vraag = await _vraag(client, casus, af=False)
    resp = await client.post(
        "/api/tasks",
        json={"title": "Uitzoeken", "issue_id": vraag["id"], "status": "done"},
    )
    assert resp.status_code == 201, resp.text
    taak = resp.json()
    await client.put(
        f"/api/casussen/{casus.id}/issues/{vraag['id']}", json={"status": "done"}
    )
    assert (await _vrijgeven(client, casus, vraag)).status_code == 200
    resp = await client.put(f"/api/tasks/{taak['id']}", json={"status": "in_progress"})
    assert resp.status_code == 200, resp.text
    assert (await _publiek(client))["beantwoorde_vragen"] == []


async def test_intrekken(client, casus):
    vraag = await _vraag(client, casus)
    await _vrijgeven(client, casus, vraag)
    resp = await client.delete(f"/api/casussen/{casus.id}/issues/{vraag['id']}/publiek")
    assert resp.status_code == 200
    assert resp.json()["published_at"] is None
    assert resp.json()["public_answer"] == ANTWOORD
    assert (await _publiek(client))["beantwoorde_vragen"] == []


async def test_publieke_pagina_uit_lekt_geen_vragen(client, db_session, casus):
    vraag = await _vraag(client, casus)
    await _vrijgeven(client, casus, vraag)
    init = await db_session.get(Initiatief, casus.initiatief_id)
    init.public_page_enabled = False
    await db_session.flush()
    resp = await client.get("/api/public/initiatieven/by-slug/rr-buiten")
    assert resp.status_code == 404


# --- Wie mag vrijgeven -------------------------------------------------------


async def test_kijker_die_trekker_is_mag_niet_vrijgeven_wel_intrekken(
    client, db_session, casus, initiatief
):
    """Trekker zijn is genoeg om de casus te wijzigen, niet om iets naar
    buiten te brengen: dat vraagt dezelfde rol als een update publiceren."""
    vraag = await _vraag(client, casus)
    kijker = await make_person(db_session, "Kijker Trekker")
    await _rol(db_session, kijker, "initiatief", initiatief.id, "viewer")
    await _rol(db_session, kijker, "casus", casus.id, "trekker")
    async with client_as(db_session, kijker) as c:
        resp = await _vrijgeven(c, casus, vraag)
        assert resp.status_code == 403
    assert (await _vrijgeven(client, casus, vraag)).status_code == 200
    async with client_as(db_session, kijker) as c:
        resp = await c.delete(f"/api/casussen/{casus.id}/issues/{vraag['id']}/publiek")
        assert resp.status_code == 200, resp.text


async def test_bijdrager_mag_vrijgeven(client, db_session, casus, initiatief):
    vraag = await _vraag(client, casus)
    bijdrager = await make_person(db_session, "Bijdrager")
    await _rol(db_session, bijdrager, "initiatief", initiatief.id, "contributor")
    async with client_as(db_session, bijdrager) as c:
        resp = await _vrijgeven(c, casus, vraag)
    assert resp.status_code == 200, resp.text


async def test_buitenstaander_ziet_de_vraag_niet(client, db_session, casus):
    vraag = await _vraag(client, casus)
    buiten = await make_person(db_session, "Buitenstaander")
    async with client_as(db_session, buiten) as c:
        resp = await _vrijgeven(c, casus, vraag)
    assert resp.status_code in (403, 404)


# --- Updates ----------------------------------------------------------------


async def _update(client, initiatief, vraag_ids=(), publish=True):
    return await client.post(
        f"/api/initiatieven/{initiatief.id}/updates",
        json={
            "titel": "Stand van zaken",
            "body": "Deze maand **twee** vragen af.",
            "publish": publish,
            "vraag_ids": [str(v) for v in vraag_ids],
        },
    )


async def test_update_neemt_vrijgegeven_vraag_mee(client, casus, initiatief):
    vraag = await _vraag(client, casus)
    await _vrijgeven(client, casus, vraag)
    resp = await _update(client, initiatief, [vraag["id"]])
    assert resp.status_code == 201, resp.text
    (meegenomen,) = resp.json()["vragen"]
    assert meegenomen["vraag"] == PUBLIEKE_VRAAG
    assert meegenomen["antwoord"] == ANTWOORD

    (update,) = (await _publiek(client))["updates"]
    assert update["vragen"][0]["vraag"] == PUBLIEKE_VRAAG
    _lekt_niets(str(update))


async def test_update_weigert_niet_vrijgegeven_vraag(client, casus, initiatief):
    vraag = await _vraag(client, casus)
    resp = await _update(client, initiatief, [vraag["id"]])
    assert resp.status_code == 400


async def test_update_weigert_vraag_van_ander_initiatief(
    client, db_session, initiatief
):
    ander = Initiatief(
        id=uuid.uuid4(), naam="Ander", slug="ander-buiten", casussen_enabled=True
    )
    db_session.add(ander)
    await db_session.flush()
    andere_casus = await _casus(db_session, ander, "Andere casus")
    vraag = await _vraag(client, andere_casus)
    await _vrijgeven(client, andere_casus, vraag)
    resp = await _update(client, initiatief, [vraag["id"]])
    assert resp.status_code == 400


async def test_update_weigert_onbekende_vraag(client, initiatief):
    resp = await _update(client, initiatief, [uuid.uuid4()])
    assert resp.status_code == 400


async def test_ingetrokken_vraag_valt_uit_de_update(client, casus, initiatief):
    vraag = await _vraag(client, casus)
    await _vrijgeven(client, casus, vraag)
    post = (await _update(client, initiatief, [vraag["id"]])).json()
    await client.delete(f"/api/casussen/{casus.id}/issues/{vraag['id']}/publiek")

    (update,) = (await _publiek(client))["updates"]
    assert update["vragen"] == []
    (intern,) = (await client.get(f"/api/initiatieven/{initiatief.id}/updates")).json()
    assert intern["id"] == post["id"] and intern["vragen"] == []


async def test_vragen_van_update_wijzigen(client, casus, initiatief):
    een = await _vraag(client, casus)
    twee = await _vraag(client, casus)
    await _vrijgeven(client, casus, een, "Vraag een?")
    await _vrijgeven(client, casus, twee, "Vraag twee?")
    post = (await _update(client, initiatief, [een["id"]], publish=False)).json()

    resp = await client.put(
        f"/api/initiatieven/{initiatief.id}/updates/{post['id']}",
        json={"vraag_ids": [twee["id"]]},
    )
    assert [v["vraag"] for v in resp.json()["vragen"]] == ["Vraag twee?"]
    # Zonder vraag_ids blijft de lijst staan.
    resp = await client.put(
        f"/api/initiatieven/{initiatief.id}/updates/{post['id']}",
        json={"titel": "Nieuwe titel"},
    )
    assert [v["vraag"] for v in resp.json()["vragen"]] == ["Vraag twee?"]


async def test_vrijgegeven_vragen_met_stand(client, casus, initiatief):
    een = await _vraag(client, casus)
    twee = await _vraag(client, casus)
    await _vrijgeven(client, casus, een, "Vraag een?")
    await _vrijgeven(client, casus, twee, "Vraag twee?")
    await _update(client, initiatief, [een["id"]], publish=True)
    await _update(client, initiatief, [twee["id"]], publish=False)

    resp = await client.get(f"/api/initiatieven/{initiatief.id}/vrijgegeven-vragen")
    assert resp.status_code == 200
    stand = {v["vraag"]: v["in_gepubliceerde_update"] for v in resp.json()}
    # Alleen een gepubliceerde update telt; een concept niet.
    assert stand == {"Vraag een?": True, "Vraag twee?": False}
    _lekt_niets(str(resp.json()))


async def test_vrijgegeven_vragen_alleen_voor_leden(client, db_session, initiatief):
    buiten = await make_person(db_session, "Buitenstaander")
    async with client_as(db_session, buiten) as c:
        resp = await c.get(f"/api/initiatieven/{initiatief.id}/vrijgegeven-vragen")
    assert resp.status_code == 403


# --- De mailbrief -----------------------------------------------------------


def _mail(resp) -> email.message.EmailMessage:
    return email.message_from_bytes(resp.content, policy=policy.default)


async def test_mailbrief_van_concept_is_409(client, initiatief):
    post = (await _update(client, initiatief, publish=False)).json()
    resp = await client.get(
        f"/api/initiatieven/{initiatief.id}/updates/{post['id']}/eml"
    )
    assert resp.status_code == 409


async def test_mailbrief_met_vragen_en_link(client, casus, initiatief, monkeypatch):
    monkeypatch.setattr(get_settings(), "FRONTEND_URL", "https://bouwmeester.test")
    vraag = await _vraag(client, casus)
    await _vrijgeven(client, casus, vraag)
    post = (await _update(client, initiatief, [vraag["id"]])).json()

    resp = await client.get(
        f"/api/initiatieven/{initiatief.id}/updates/{post['id']}/eml"
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("message/rfc822")
    msg = _mail(resp)
    assert msg["Subject"] == "Regelrecht buiten: Stand van zaken"
    assert msg["To"] is None, "geen ontvangers: die zet de afzender er zelf in"
    assert msg["X-Unsent"] == "1"
    body_html = msg.get_body(preferencelist=("html",)).get_content()
    body_text = msg.get_body(preferencelist=("plain",)).get_content()
    for body in (body_html, body_text):
        assert PUBLIEKE_VRAAG in body and ANTWOORD in body
        assert "https://bouwmeester.test/c/rr-buiten" in body
        _lekt_niets(body)
    assert "<strong>twee</strong>" in body_html


async def test_mailbrief_escapet_ingevoerde_tekst(client, casus, initiatief):
    vraag = await _vraag(client, casus)
    await client.put(
        f"/api/casussen/{casus.id}/issues/{vraag['id']}/publiek",
        json={
            "public_title": '<a href="https://kwaad.test">klik</a>',
            "public_answer": "<script>alert(1)</script>",
        },
    )
    post = (await _update(client, initiatief, [vraag["id"]])).json()
    resp = await client.get(
        f"/api/initiatieven/{initiatief.id}/updates/{post['id']}/eml"
    )
    body_html = _mail(resp).get_body(preferencelist=("html",)).get_content()
    assert "<script>" not in body_html
    assert 'href="https://kwaad.test"' not in body_html
    assert "&lt;script&gt;" in body_html


async def test_mailbrief_zonder_publieke_pagina_heeft_geen_link(
    client, db_session, initiatief, monkeypatch
):
    monkeypatch.setattr(get_settings(), "FRONTEND_URL", "https://bouwmeester.test")
    initiatief.public_page_enabled = False
    await db_session.flush()
    post = (await _update(client, initiatief)).json()
    resp = await client.get(
        f"/api/initiatieven/{initiatief.id}/updates/{post['id']}/eml"
    )
    assert "/c/rr-buiten" not in resp.text


async def test_mailbrief_alleen_voor_bijdragers(client, db_session, initiatief):
    post = (await _update(client, initiatief)).json()
    kijker = await make_person(db_session, "Kijker")
    await _rol(db_session, kijker, "initiatief", initiatief.id, "viewer")
    async with client_as(db_session, kijker) as c:
        resp = await c.get(
            f"/api/initiatieven/{initiatief.id}/updates/{post['id']}/eml"
        )
    assert resp.status_code == 403


# --- Na de veiligheidsreview ------------------------------------------------


@pytest.mark.parametrize(
    "veld,tekst",
    [
        ("public_answer", "Uitgezocht door [@Jan Jansen](user:%s)."),
        ("public_answer", "Zie [#Belronde gemeente X](task:%s)."),
        ("public_title", "Wat vond [@Gemeente X](org:%s)?"),
        ("public_answer", "Volgens [#Wet X](node:%s)."),
    ],
)
async def test_publieke_tekst_zonder_verwijzingen(client, casus, veld, tekst):
    """Een @- of #-verwijzing zet een naam, een taaktitel en een id in de
    publieke tekst. Die gaat er niet door."""
    vraag = await _vraag(client, casus)
    data = {"public_title": PUBLIEKE_VRAAG, "public_answer": ANTWOORD}
    data[veld] = tekst % uuid.uuid4()
    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/{vraag['id']}/publiek", json=data
    )
    assert resp.status_code == 422
    assert "verwijzing" in resp.text


async def test_publieke_tekst_van_alleen_spaties_is_422(client, casus):
    vraag = await _vraag(client, casus)
    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/{vraag['id']}/publiek",
        json={"public_title": "   ", "public_answer": ANTWOORD},
    )
    assert resp.status_code == 422
    assert (await _publiek(client))["beantwoorde_vragen"] == []


async def test_mailbrief_met_regeleinde_in_de_titel(client, initiatief):
    resp = await client.post(
        f"/api/initiatieven/{initiatief.id}/updates",
        json={"titel": "Stand\nvan zaken", "publish": True},
    )
    post = resp.json()
    resp = await client.get(
        f"/api/initiatieven/{initiatief.id}/updates/{post['id']}/eml"
    )
    assert resp.status_code == 200, resp.text
    assert _mail(resp)["Subject"] == "Regelrecht buiten: Stand van zaken"


async def test_update_toont_geen_vraag_van_een_ander_initiatief(
    client, db_session, casus, initiatief
):
    """Verhuizen kan alleen binnen een initiatief. Komt een gekoppelde vraag
    toch bij een ander initiatief terecht, dan valt hij uit de update."""
    vraag = await _vraag(client, casus)
    await _vrijgeven(client, casus, vraag)
    await _update(client, initiatief, [vraag["id"]])
    ander = Initiatief(
        id=uuid.uuid4(), naam="Ander", slug="ander-verhuisd", casussen_enabled=True
    )
    db_session.add(ander)
    await db_session.flush()
    casus.initiatief_id = ander.id
    await db_session.flush()
    db_session.expire_all()

    (update,) = (await _publiek(client))["updates"]
    assert update["vragen"] == []
    (intern,) = (await client.get(f"/api/initiatieven/{initiatief.id}/updates")).json()
    assert intern["vragen"] == []


INTERN_ANTWOORD = "Intern: Jansen van gemeente X twijfelt nog over de beslisregel"


async def test_intern_antwoord_blijft_binnen(client, casus, initiatief):
    """Een vraag heeft een interne en een externe versie van het antwoord.
    De interne versie staat in de vraag en de backlog, nooit buiten."""
    vraag = await _vraag(client, casus)
    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/{vraag['id']}",
        json={"antwoord": INTERN_ANTWOORD},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["antwoord"] == INTERN_ANTWOORD
    await _vrijgeven(client, casus, vraag)
    await _update(client, initiatief, [vraag["id"]])

    backlog = (
        await client.get(
            "/api/casussen/backlog", params={"initiatief_id": str(initiatief.id)}
        )
    ).json()
    item = next(i for i in backlog["issues"] if i["id"] == vraag["id"])
    assert item["antwoord"] == INTERN_ANTWOORD

    publiek = await _publiek(client)
    assert INTERN_ANTWOORD not in str(publiek)
    assert ANTWOORD in str(publiek)
    _lekt_niets(str(publiek))


async def test_intern_antwoord_wissen(client, casus):
    vraag = await _vraag(client, casus, af=False)
    pad = f"/api/casussen/{casus.id}/issues/{vraag['id']}"
    await client.put(pad, json={"antwoord": INTERN_ANTWOORD})
    resp = await client.put(pad, json={"antwoord": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["antwoord"] is None


# --- Na de review van #461 ----------------------------------------------------


@pytest.mark.parametrize(
    "veld,tekst",
    [
        ("body", "Met dank aan [@Jan Jansen](user:%s)."),
        ("body", "Zie [#Belronde](task:%s)."),
        ("titel", "Stand bij [@Gemeente X](org:%s)"),
        # Markdown laat een spatie en punthaken toe voor het doel.
        ("body", "Met dank aan [@Jan Jansen]( user:%s)."),
        ("body", "Met dank aan [@Jan Jansen](<user:%s>)."),
    ],
)
async def test_update_zonder_verwijzingen(client, initiatief, veld, tekst):
    """Titel en tekst van een update gaan naar buiten: geen verwijzing, bij
    schrijven en bij wijzigen."""
    data = {"titel": "Stand van zaken", "body": "Gewone tekst.", "publish": True}
    data[veld] = tekst % uuid.uuid4()
    resp = await client.post(f"/api/initiatieven/{initiatief.id}/updates", json=data)
    assert resp.status_code == 422
    assert "verwijzing" in resp.text

    post = (await _update(client, initiatief)).json()
    resp = await client.put(
        f"/api/initiatieven/{initiatief.id}/updates/{post['id']}",
        json={veld: tekst % uuid.uuid4()},
    )
    assert resp.status_code == 422
    assert "verwijzing" in resp.text


async def test_update_titel_van_alleen_spaties_is_422(client, initiatief):
    resp = await client.post(
        f"/api/initiatieven/{initiatief.id}/updates", json={"titel": "   "}
    )
    assert resp.status_code == 422


async def _oude_update(db_session, initiatief, *, gepubliceerd: bool, persoon_id):
    """Een update van vóór de controle, met een verwijzing in titel en tekst."""
    post = InitiatiefUpdatePost(
        initiatief_id=initiatief.id,
        titel=f"Stand bij [@Gemeente X](org:{persoon_id})",
        body=f"Met dank aan [@Jan Jansen](user:{persoon_id}) en **twee** vragen.",
        published_at=datetime.now(UTC) if gepubliceerd else None,
    )
    db_session.add(post)
    await db_session.flush()
    return post


async def test_oud_concept_met_verwijzing_publiceert_niet(
    client, db_session, initiatief
):
    post = await _oude_update(
        db_session, initiatief, gepubliceerd=False, persoon_id=uuid.uuid4()
    )
    resp = await client.post(
        f"/api/initiatieven/{initiatief.id}/updates/{post.id}/publish"
    )
    assert resp.status_code == 422
    assert "verwijzing" in resp.text
    assert (await _publiek(client))["updates"] == []


async def test_mailbrief_bevat_geen_verwijzing(
    client, db_session, initiatief, monkeypatch
):
    """Een gepubliceerde update van vóór de controle: in de mailbrief wordt
    de verwijzing gewone tekst, zonder id en zonder link."""
    monkeypatch.setattr(get_settings(), "FRONTEND_URL", "https://bouwmeester.test")
    persoon_id = uuid.uuid4()
    post = await _oude_update(
        db_session, initiatief, gepubliceerd=True, persoon_id=persoon_id
    )
    resp = await client.get(f"/api/initiatieven/{initiatief.id}/updates/{post.id}/eml")
    assert resp.status_code == 200, resp.text
    msg = _mail(resp)
    assert str(persoon_id) not in msg["Subject"]
    for deel in ("html", "plain"):
        body = msg.get_body(preferencelist=(deel,)).get_content()
        assert str(persoon_id) not in body
        assert "user:" not in body and "org:" not in body
        assert "@Jan Jansen" in body


async def test_publieke_pagina_bevat_geen_verwijzing(client, db_session, initiatief):
    """Ook op de publieke pagina: de oude update en de beschrijving van het
    initiatief (die voor binnen geschreven wordt) zonder id."""
    persoon_id = uuid.uuid4()
    await _oude_update(db_session, initiatief, gepubliceerd=True, persoon_id=persoon_id)
    initiatief.beschrijving = f"Getrokken door [@Anne](user:{persoon_id})."
    await db_session.flush()
    publiek = await _publiek(client)
    assert str(persoon_id) not in str(publiek)
    assert publiek["beschrijving"] == "Getrokken door @Anne."
    (update,) = publiek["updates"]
    assert update["titel"] == "Stand bij @Gemeente X"


def test_verwijzingen_als_tekst():
    from bouwmeester.schema.publieke_tekst import verwijzingen_als_tekst as t

    id_ = uuid.uuid4()
    assert t(None) is None
    assert t("") == ""
    assert t("Gewoon [een link](https://example.org).") == (
        "Gewoon [een link](https://example.org)."
    )
    assert t(f"[@Anne](user:{id_}) en [#Wet](node:{id_})") == "@Anne en #Wet"
    assert t(f"[@A \\] B](user:{id_})") == "@A ] B"
    assert t(f"[@Anne]( <USER:{id_}> )") == "@Anne"
    # Zonder sluitende haak: het id gaat er toch af.
    assert str(id_) not in (t(f"[@Anne](user:{id_}") or "")


async def test_in_een_update_volgt_of_de_vraag_buiten_is(client, casus, initiatief):
    """De stand "In een update" geldt zolang de vraag buiten is: na
    intrekken staat hij in geen update meer te lezen."""
    vraag = await _vraag(client, casus)
    await _vrijgeven(client, casus, vraag)
    await _update(client, initiatief, [vraag["id"]])
    pad = f"/api/initiatieven/{initiatief.id}/klaar-om-te-delen"

    (klaar,) = (await client.get(pad)).json()["vragen"]
    assert klaar["in_gepubliceerde_update"] is True

    await client.delete(f"/api/casussen/{casus.id}/issues/{vraag['id']}/publiek")
    (klaar,) = (await client.get(pad)).json()["vragen"]
    assert klaar["published_at"] is None
    assert klaar["in_gepubliceerde_update"] is False

    # Opnieuw vrijgeven: de update toont hem weer, dus weer "In een update".
    await _vrijgeven(client, casus, vraag)
    (klaar,) = (await client.get(pad)).json()["vragen"]
    assert klaar["in_gepubliceerde_update"] is True
