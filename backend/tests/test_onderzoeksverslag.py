"""Het onderzoeksverslag bij een onderzoeksvraag, en of het naar buiten mag.

Dekt: uploaden en vervangen (alleen PDF, Word, ODT, en de inhoud begint met
de signatuur van dat type; vervangen zet het akkoord terug en ruimt het oude
bestand op), wie wat mag, en de publieke kant: een verslag staat pas buiten
als iemand akkoord gaf en de vraag zelf vrijgegeven is, intrekken of
heropenen van de vraag laat het akkoord vervallen, buiten heet het bestand
naar de publieke vraag, en de publieke download geeft in alle andere
gevallen dezelfde 404.
"""

import uuid

import pytest

from bouwmeester.core.config import get_settings
from bouwmeester.models.casus import Casus
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.resource_permission import ResourcePermission
from tests.factories import client_as, make_person

PDF = b"%PDF-1.4\n% Onderzoeksverslag\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
VRAAG = "Kun je een hardheidsclausule uitvoerbaar maken?"
# De naam buiten: afgeleid van VRAAG, niet van de naam bij het uploaden.
NAAM_BUITEN = "onderzoeksverslag-kun-je-een-hardheidsclausule-uitvoerbaar-maken.pdf"
ANTWOORD = "Ja, met een expliciete beslisregel en een menselijke toets."
SLUG = "rr-verslag"


@pytest.fixture
async def initiatief(db_session):
    init = Initiatief(
        id=uuid.uuid4(),
        naam="Regelrecht verslag",
        slug=SLUG,
        casussen_enabled=True,
        public_page_enabled=True,
    )
    db_session.add(init)
    await db_session.flush()
    return init


async def _casus(db_session, initiatief, title="Casus Gemeente X"):
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
        json={"title": "Interne vraag", "is_onderzoeksvraag": onderzoeksvraag},
    )
    assert resp.status_code == 201, resp.text
    vraag = resp.json()
    if af:
        await client.put(
            f"/api/casussen/{casus.id}/issues/{vraag['id']}", json={"status": "done"}
        )
    return vraag


def _url(casus, vraag, rest=""):
    return f"/api/casussen/{casus.id}/issues/{vraag['id']}/verslag{rest}"


async def _upload(client, casus, vraag, *, naam="verslag.pdf", inhoud=PDF, soort=None):
    return await client.post(
        _url(casus, vraag),
        files={"file": (naam, inhoud, soort or "application/pdf")},
    )


async def _vrijgeven(client, casus, vraag):
    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/{vraag['id']}/publiek",
        json={"public_title": VRAAG, "public_answer": ANTWOORD},
    )
    assert resp.status_code == 200, resp.text


async def _openbaar(client, casus, vraag):
    return await client.put(_url(casus, vraag, "/openbaar"), json={"akkoord": True})


async def _publiek(client):
    resp = await client.get(f"/api/public/initiatieven/by-slug/{SLUG}")
    assert resp.status_code == 200, resp.text
    return resp.json()


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


def _bestanden(blob_root):
    return [p for p in blob_root.rglob("*") if p.is_file()]


# --- Binnen ---------------------------------------------------------------


async def test_zonder_verslag_is_het_leeg(client, casus):
    vraag = await _vraag(client, casus)
    resp = await client.get(_url(casus, vraag))
    assert resp.status_code == 200
    assert resp.json() is None


async def test_uploaden_en_downloaden(client, casus):
    vraag = await _vraag(client, casus, af=False)
    resp = await _upload(client, casus, vraag)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["bestandsnaam"] == "verslag.pdf"
    assert data["bestandsgrootte"] == len(PDF)
    assert data["openbaar_op"] is None
    assert "pad" not in data

    resp = await client.get(_url(casus, vraag, "/download"))
    assert resp.status_code == 200
    assert resp.content == PDF
    assert resp.headers["content-disposition"].startswith("attachment")


@pytest.mark.parametrize(
    "naam,inhoud,soort",
    [
        ("plaatje.png", PNG, "image/png"),
        ("notities.txt", b"tekst", "text/plain"),
        ("vermomd.pdf", PNG, "application/pdf"),
        # Geen bekende signatuur: voor een verslag niet genoeg.
        ("zonder-signatuur.pdf", b"\x00\x01\x02\x03 geen pdf", "application/pdf"),
        ("leeg.pdf", b"", "application/pdf"),
        ("zonder-signatuur.doc", b"geen word", "application/msword"),
        (
            "zonder-signatuur.docx",
            b"geen zip",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "zonder-signatuur.odt",
            b"geen zip",
            "application/vnd.oasis.opendocument.text",
        ),
        ("pdf-als-word.doc", PDF, "application/msword"),
    ],
)
async def test_alleen_documenten(client, casus, naam, inhoud, soort):
    vraag = await _vraag(client, casus)
    resp = await _upload(client, casus, vraag, naam=naam, inhoud=inhoud, soort=soort)
    assert resp.status_code == 400


async def test_alleen_bij_een_onderzoeksvraag(client, casus):
    vraag = await _vraag(client, casus, onderzoeksvraag=False)
    assert (await _upload(client, casus, vraag)).status_code == 400


async def test_vervangen_zet_akkoord_terug_en_ruimt_op(client, casus, blob_root):
    vraag = await _vraag(client, casus)
    await _upload(client, casus, vraag, naam="eerste.pdf")
    assert (await _openbaar(client, casus, vraag)).json()["openbaar_op"] is not None

    resp = await _upload(client, casus, vraag, naam="tweede.pdf")
    assert resp.status_code == 200
    assert resp.json()["bestandsnaam"] == "tweede.pdf"
    assert resp.json()["openbaar_op"] is None, "het akkoord gold voor het oude bestand"
    bestanden = _bestanden(blob_root)
    assert len(bestanden) == 1 and bestanden[0].name.endswith("_tweede.pdf")


async def test_weghalen(client, casus, blob_root):
    vraag = await _vraag(client, casus)
    await _upload(client, casus, vraag)
    resp = await client.delete(_url(casus, vraag))
    assert resp.status_code == 204
    assert (await client.get(_url(casus, vraag))).json() is None
    assert _bestanden(blob_root) == []


async def test_vraag_weg_dan_verslag_weg(client, db_session, casus, blob_root):
    from bouwmeester.models.onderzoeksverslag import Onderzoeksverslag

    vraag = await _vraag(client, casus)
    voor = set(_bestanden(blob_root))
    await _upload(client, casus, vraag)
    assert set(_bestanden(blob_root)) - voor
    await client.delete(f"/api/casussen/{casus.id}/issues/{vraag['id']}")
    # Ook het bestand in de opslag, niet alleen de rij.
    assert set(_bestanden(blob_root)) - voor == set()
    db_session.expire_all()
    assert await db_session.get(Onderzoeksverslag, uuid.UUID(vraag["id"])) is None
    from sqlalchemy import func, select

    aantal = await db_session.scalar(
        select(func.count()).select_from(Onderzoeksverslag)
    )
    assert aantal == 0


async def test_casus_weg_dan_verslagbestand_weg(client, casus, blob_root):
    vraag = await _vraag(client, casus)
    voor = set(_bestanden(blob_root))
    await _upload(client, casus, vraag)
    assert set(_bestanden(blob_root)) - voor
    resp = await client.delete(f"/api/casussen/{casus.id}")
    assert resp.status_code == 204, resp.text
    assert set(_bestanden(blob_root)) - voor == set()


async def test_initiatief_weg_dan_verslagbestand_weg(
    client, casus, initiatief, blob_root
):
    vraag = await _vraag(client, casus)
    voor = set(_bestanden(blob_root))
    await _upload(client, casus, vraag)
    assert set(_bestanden(blob_root)) - voor
    resp = await client.delete(f"/api/initiatieven/{initiatief.id}")
    assert resp.status_code == 204, resp.text
    assert set(_bestanden(blob_root)) - voor == set()


async def test_akkoord_moet_expliciet(client, casus):
    vraag = await _vraag(client, casus)
    await _upload(client, casus, vraag)
    resp = await client.put(_url(casus, vraag, "/openbaar"), json={"akkoord": False})
    assert resp.status_code == 422
    resp = await client.put(_url(casus, vraag, "/openbaar"), json={})
    assert resp.status_code == 422


# --- Wie mag wat -------------------------------------------------------------


async def test_kijker_die_trekker_is(client, db_session, casus, initiatief):
    """Trekker: mag het verslag uploaden en terughalen naar binnen, niet
    naar buiten brengen."""
    vraag = await _vraag(client, casus)
    kijker = await make_person(db_session, "Kijker Trekker")
    await _rol(db_session, kijker, "initiatief", initiatief.id, "viewer")
    await _rol(db_session, kijker, "casus", casus.id, "trekker")
    async with client_as(db_session, kijker) as c:
        assert (await _upload(c, casus, vraag)).status_code == 200
        assert (await _openbaar(c, casus, vraag)).status_code == 403
    assert (await _openbaar(client, casus, vraag)).status_code == 200
    async with client_as(db_session, kijker) as c:
        resp = await c.delete(_url(casus, vraag, "/openbaar"))
        assert resp.status_code == 200
        assert resp.json()["openbaar_op"] is None


async def test_kijker_kan_niet_uploaden(client, db_session, casus, initiatief):
    vraag = await _vraag(client, casus)
    kijker = await make_person(db_session, "Kijker")
    await _rol(db_session, kijker, "initiatief", initiatief.id, "viewer")
    async with client_as(db_session, kijker) as c:
        assert (await _upload(c, casus, vraag)).status_code == 403


async def test_buitenstaander_ziet_niets(client, db_session, casus):
    vraag = await _vraag(client, casus)
    await _upload(client, casus, vraag)
    buiten = await make_person(db_session, "Buitenstaander")
    async with client_as(db_session, buiten) as c:
        assert (await c.get(_url(casus, vraag))).status_code == 404
        assert (await c.get(_url(casus, vraag, "/download"))).status_code == 404


async def test_verslag_van_andere_casus_is_404(client, db_session, casus, initiatief):
    vraag = await _vraag(client, casus)
    await _upload(client, casus, vraag)
    andere = await _casus(db_session, initiatief, "Andere casus")
    assert (await client.get(_url(andere, vraag))).status_code == 404


# --- Buiten -----------------------------------------------------------------


async def _publieke_download(client, verslag_id, slug=SLUG):
    return await client.get(
        f"/api/public/initiatieven/by-slug/{slug}/verslagen/{verslag_id}"
    )


async def test_buiten_alleen_met_akkoord_en_vrijgegeven_vraag(client, casus):
    vraag = await _vraag(client, casus)
    verslag = (await _upload(client, casus, vraag)).json()

    # Akkoord, maar de vraag is nog binnen: niets buiten.
    await _openbaar(client, casus, vraag)
    assert (await _publiek(client))["beantwoorde_vragen"] == []
    assert (await _publieke_download(client, verslag["id"])).status_code == 404

    # Vraag vrijgegeven: nu staat het verslag erbij.
    await _vrijgeven(client, casus, vraag)
    (buiten,) = (await _publiek(client))["beantwoorde_vragen"]
    assert buiten["verslag"] == {
        "id": verslag["id"],
        "bestandsnaam": NAAM_BUITEN,
        "content_type": "application/pdf",
        "bestandsgrootte": len(PDF),
    }
    resp = await _publieke_download(client, verslag["id"])
    assert resp.status_code == 200
    assert resp.content == PDF
    assert resp.headers["content-disposition"].startswith("attachment")
    assert resp.headers.get("x-content-type-options") == "nosniff"


async def test_buiten_zonder_akkoord_geen_verslag(client, casus):
    vraag = await _vraag(client, casus)
    verslag = (await _upload(client, casus, vraag)).json()
    await _vrijgeven(client, casus, vraag)
    (buiten,) = (await _publiek(client))["beantwoorde_vragen"]
    assert buiten["verslag"] is None
    assert (await _publieke_download(client, verslag["id"])).status_code == 404


async def test_vraag_heropend_dan_verslag_binnen(client, casus):
    vraag = await _vraag(client, casus)
    verslag = (await _upload(client, casus, vraag)).json()
    await _openbaar(client, casus, vraag)
    await _vrijgeven(client, casus, vraag)
    await client.put(
        f"/api/casussen/{casus.id}/issues/{vraag['id']}", json={"status": "open"}
    )
    assert (await _publieke_download(client, verslag["id"])).status_code == 404


async def test_publieke_pagina_uit_dan_404(client, db_session, casus, initiatief):
    vraag = await _vraag(client, casus)
    verslag = (await _upload(client, casus, vraag)).json()
    await _openbaar(client, casus, vraag)
    await _vrijgeven(client, casus, vraag)
    initiatief.public_page_enabled = False
    await db_session.flush()
    assert (await _publieke_download(client, verslag["id"])).status_code == 404


async def test_verslag_via_ander_initiatief_is_404(client, db_session, casus):
    """Het id van een openbaar verslag geeft niets via de slug van een ander
    initiatief, ook als die pagina aan staat."""
    vraag = await _vraag(client, casus)
    verslag = (await _upload(client, casus, vraag)).json()
    await _openbaar(client, casus, vraag)
    await _vrijgeven(client, casus, vraag)
    db_session.add(
        Initiatief(
            id=uuid.uuid4(),
            naam="Ander",
            slug="ander-publiek",
            public_page_enabled=True,
        )
    )
    await db_session.flush()
    resp = await _publieke_download(client, verslag["id"], slug="ander-publiek")
    assert resp.status_code == 404
    resp = await _publieke_download(client, uuid.uuid4())
    assert resp.status_code == 404


async def test_update_en_mailbrief_noemen_het_verslag(
    client, casus, initiatief, monkeypatch
):
    monkeypatch.setattr(get_settings(), "FRONTEND_URL", "https://bouwmeester.test")
    vraag = await _vraag(client, casus)
    verslag = (await _upload(client, casus, vraag)).json()
    await _openbaar(client, casus, vraag)
    await _vrijgeven(client, casus, vraag)
    post = (
        await client.post(
            f"/api/initiatieven/{initiatief.id}/updates",
            json={"titel": "Stand", "publish": True, "vraag_ids": [vraag["id"]]},
        )
    ).json()
    assert post["vragen"][0]["verslag"]["id"] == verslag["id"]
    (update,) = (await _publiek(client))["updates"]
    assert update["vragen"][0]["verslag"]["bestandsnaam"] == NAAM_BUITEN

    resp = await client.get(
        f"/api/initiatieven/{initiatief.id}/updates/{post['id']}/eml"
    )
    assert "Het onderzoeksverslag staat op de publieke pagina" in resp.text


# --- Na de review van #461 ----------------------------------------------------


@pytest.mark.parametrize(
    "naam,inhoud,soort",
    [
        ("verslag.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "application/msword"),
        (
            "verslag.docx",
            b"PK\x03\x04 rest",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        ("verslag.odt", b"PK\x03\x04 rest", "application/vnd.oasis.opendocument.text"),
    ],
)
async def test_documenten_met_signatuur(client, casus, naam, inhoud, soort):
    vraag = await _vraag(client, casus)
    resp = await _upload(client, casus, vraag, naam=naam, inhoud=inhoud, soort=soort)
    assert resp.status_code == 200, resp.text


def test_signatuur_verplicht():
    """Zonder de vlag laat de controle onbekende inhoud door (zo werken de
    andere bijlagen); met de vlag niet."""
    from bouwmeester.core.storage import verify_content_type

    onbekend = b"\x00\x01\x02\x03"
    assert verify_content_type(onbekend, "application/pdf") is True
    assert (
        verify_content_type(onbekend, "application/pdf", signatuur_verplicht=True)
        is False
    )
    assert verify_content_type(PDF, "application/pdf", signatuur_verplicht=True) is True
    assert (
        verify_content_type(PNG, "application/pdf", signatuur_verplicht=True) is False
    )
    # Een type zonder signatuur kan met de vlag nooit.
    assert (
        verify_content_type(b"tekst", "text/plain", signatuur_verplicht=True) is False
    )


async def test_intrekken_laat_akkoord_vervallen(client, casus):
    """Het akkoord gold voor de vraag buiten. Na intrekken en opnieuw
    vrijgeven staat het verslag pas weer buiten na een nieuw akkoord."""
    vraag = await _vraag(client, casus)
    verslag = (await _upload(client, casus, vraag)).json()
    await _openbaar(client, casus, vraag)
    await _vrijgeven(client, casus, vraag)
    assert (await _publieke_download(client, verslag["id"])).status_code == 200

    resp = await client.delete(f"/api/casussen/{casus.id}/issues/{vraag['id']}/publiek")
    assert resp.status_code == 200, resp.text
    binnen = (await client.get(_url(casus, vraag))).json()
    assert binnen["openbaar_op"] is None and binnen["openbaar_door_naam"] is None

    await _vrijgeven(client, casus, vraag)
    (buiten,) = (await _publiek(client))["beantwoorde_vragen"]
    assert buiten["verslag"] is None
    assert (await _publieke_download(client, verslag["id"])).status_code == 404

    await _openbaar(client, casus, vraag)
    assert (await _publieke_download(client, verslag["id"])).status_code == 200


async def test_heropenen_laat_akkoord_vervallen(client, casus):
    vraag = await _vraag(client, casus)
    verslag = (await _upload(client, casus, vraag)).json()
    await _openbaar(client, casus, vraag)
    await _vrijgeven(client, casus, vraag)
    pad = f"/api/casussen/{casus.id}/issues/{vraag['id']}"
    await client.put(pad, json={"status": "open"})
    assert (await client.get(_url(casus, vraag))).json()["openbaar_op"] is None

    await client.put(pad, json={"status": "done"})
    await _vrijgeven(client, casus, vraag)
    assert (await _publieke_download(client, verslag["id"])).status_code == 404


async def test_taak_weer_open_laat_akkoord_vervallen(client, casus):
    """Ook als de status via een taak terugvalt (sync_status)."""
    vraag = await _vraag(client, casus, af=False)
    taak = (
        await client.post(
            "/api/tasks",
            json={"title": "Uitzoeken", "issue_id": vraag["id"], "status": "done"},
        )
    ).json()
    await client.put(
        f"/api/casussen/{casus.id}/issues/{vraag['id']}", json={"status": "done"}
    )
    await _upload(client, casus, vraag)
    await _openbaar(client, casus, vraag)
    await _vrijgeven(client, casus, vraag)
    resp = await client.put(f"/api/tasks/{taak['id']}", json={"status": "in_progress"})
    assert resp.status_code == 200, resp.text
    assert (await client.get(_url(casus, vraag))).json()["openbaar_op"] is None


async def test_akkoord_voor_vrijgeven_blijft_staan(client, casus):
    """Akkoord geven voordat de vraag buiten staat kan: dat akkoord vervalt
    niet bij het vrijgeven zelf."""
    vraag = await _vraag(client, casus)
    await _upload(client, casus, vraag)
    await _openbaar(client, casus, vraag)
    await _vrijgeven(client, casus, vraag)
    assert (await client.get(_url(casus, vraag))).json()["openbaar_op"] is not None


async def test_bestandsnaam_blijft_binnen(client, casus):
    """Buiten heet het verslag naar de publieke vraag; de naam bij het
    uploaden (met een naam of een versie erin) blijft binnen."""
    vraag = await _vraag(client, casus)
    intern = "Concept v3 Jansen gemeente X.pdf"
    verslag = (await _upload(client, casus, vraag, naam=intern)).json()
    assert verslag["bestandsnaam"] == intern
    await _openbaar(client, casus, vraag)
    await _vrijgeven(client, casus, vraag)

    publiek = await _publiek(client)
    assert publiek["beantwoorde_vragen"][0]["verslag"]["bestandsnaam"] == NAAM_BUITEN
    assert "Jansen" not in str(publiek)
    resp = await _publieke_download(client, verslag["id"])
    assert resp.status_code == 200
    assert NAAM_BUITEN in resp.headers["content-disposition"]
    assert "Jansen" not in resp.headers["content-disposition"]


def test_publieke_verslagnaam():
    from types import SimpleNamespace

    from bouwmeester.services.publieke_vragen import publieke_verslagnaam

    def naam(titel, soort="application/pdf"):
        return publieke_verslagnaam(SimpleNamespace(public_title=titel), soort)

    assert (
        naam("Wat kost één beslisregel?")
        == "onderzoeksverslag-wat-kost-een-beslisregel.pdf"
    )
    assert naam(None) == "onderzoeksverslag.pdf"
    assert naam("???") == "onderzoeksverslag.pdf"
    assert (
        naam("x", "application/vnd.oasis.opendocument.text")
        == "onderzoeksverslag-x.odt"
    )
    lang = naam("a" * 200)
    assert lang == "onderzoeksverslag-" + "a" * 60 + ".pdf"
    # Een verwijzing van vroeger: geen id in de naam.
    zonder_id = naam(f"Vraag van [@Jan](user:{uuid.uuid4()})")
    assert zonder_id == "onderzoeksverslag-vraag-van-jan.pdf"
