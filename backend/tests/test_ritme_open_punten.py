"""RegelRitme per initiatief: de open punten en de wensen voor Bouwmeester.

Dekt: leeg zolang er niets is ingevuld; instellen, teruglezen en weghalen
(eigenaar alleen); witruimte eraf, lege regels weg; invoer begrensd; andere
instellingen laten beide staan; een lid leest ze wel maar wijzigt ze niet;
buiten het initiatief, in het overzicht en op de publieke pagina is niets te
zien.
"""

import uuid

import pytest

from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.resource_permission import ResourcePermission
from tests.factories import client_as, grant_role, make_org, make_person

PUNTEN = ["  De Definition of Done samen vaststellen  ", "", "Koppeling met GitHub"]
WENS = {"soort": "bug", "titel": "Bord vergeet de volgorde"}


@pytest.fixture
async def initiatief(db_session):
    init = Initiatief(
        id=uuid.uuid4(),
        naam="Ritme",
        slug="rr-open-punten",
        public_page_enabled=True,
    )
    db_session.add(init)
    await db_session.flush()
    return init


async def _zet(client, initiatief, **velden):
    return await client.put(f"/api/initiatieven/{initiatief.id}/settings", json=velden)


async def _lid(db_session, initiatief, naam="Lid ritme"):
    eenheid = await make_org(db_session, f"Eenheid {naam}")
    lid = await make_person(db_session, naam)
    await grant_role(db_session, lid, "editor", eenheid)
    db_session.add(
        ResourcePermission(
            person_id=lid.id,
            resource_type="initiatief",
            resource_id=initiatief.id,
            rol="contributor",
        )
    )
    await db_session.flush()
    return lid


async def test_leeg_zolang_er_niets_is_ingevuld(client, initiatief):
    resp = await client.get(f"/api/initiatieven/{initiatief.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["open_punten"] == []
    assert resp.json()["wensen"] == []


async def test_open_punten_instellen_teruglezen_en_weghalen(client, initiatief):
    resp = await _zet(client, initiatief, open_punten=PUNTEN)
    assert resp.status_code == 200, resp.text
    # Witruimte eraf, lege regels weg, volgorde blijft.
    assert resp.json()["open_punten"] == [
        "De Definition of Done samen vaststellen",
        "Koppeling met GitHub",
    ]
    detail = (await client.get(f"/api/initiatieven/{initiatief.id}")).json()
    assert len(detail["open_punten"]) == 2

    # Een lege lijst of null haalt de punten weg.
    resp = await _zet(client, initiatief, open_punten=[])
    assert resp.json()["open_punten"] == []
    await _zet(client, initiatief, open_punten=PUNTEN)
    resp = await _zet(client, initiatief, open_punten=None)
    assert resp.json()["open_punten"] == []


async def test_wensen_instellen_teruglezen_en_weghalen(client, initiatief):
    resp = await _zet(
        client,
        initiatief,
        wensen=[
            {
                "soort": "bug",
                "titel": "  Bord vergeet de volgorde  ",
                "toelichting": "",
                "gemeld_door": "Een teamlid",
                "gemeld_op": "2026-11-05",
            },
            {"titel": "Vaste werktypes"},
        ],
    )
    assert resp.status_code == 200, resp.text
    bug, suggestie = resp.json()["wensen"]
    assert bug["soort"] == "bug" and bug["titel"] == "Bord vergeet de volgorde"
    assert bug["toelichting"] is None and bug["gemeld_op"] == "2026-11-05"
    # Zonder soort een suggestie, zonder id krijgt hij er een.
    assert suggestie["soort"] == "suggestie" and suggestie["id"]

    detail = (await client.get(f"/api/initiatieven/{initiatief.id}")).json()
    assert [w["id"] for w in detail["wensen"]] == [bug["id"], suggestie["id"]]

    resp = await _zet(client, initiatief, wensen=None)
    assert resp.json()["wensen"] == []


async def test_andere_instellingen_laten_ze_staan(client, initiatief):
    await _zet(client, initiatief, open_punten=PUNTEN, wensen=[WENS])
    resp = await _zet(client, initiatief, funnel_enabled=True)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["open_punten"]) == 2
    assert len(resp.json()["wensen"]) == 1


@pytest.mark.parametrize(
    "velden",
    [
        {"open_punten": ["a" * 301]},
        {"open_punten": [f"punt {i}" for i in range(31)]},
        {"wensen": [{"soort": "klacht", "titel": "x"}]},
        {"wensen": [{"titel": "x" * 301}]},
        {"wensen": [{"titel": "   "}]},
        {"wensen": [{"titel": "x", "toelichting": "a" * 5001}]},
        {"wensen": [{"id": "a", "titel": "x"}, {"id": "a", "titel": "y"}]},
        {"wensen": [{"titel": f"wens {i}"} for i in range(201)]},
    ],
)
async def test_te_lang_te_veel_of_ongeldig_is_422(client, initiatief, velden):
    resp = await _zet(client, initiatief, **velden)
    assert resp.status_code == 422, resp.text


async def test_een_lid_leest_ze_maar_wijzigt_ze_niet(client, db_session, initiatief):
    await _zet(client, initiatief, open_punten=PUNTEN, wensen=[WENS])
    lid = await _lid(db_session, initiatief)
    async with client_as(db_session, lid) as c:
        lezen = await c.get(f"/api/initiatieven/{initiatief.id}")
        wijzigen = await _zet(c, initiatief, open_punten=["Weg"], wensen=[])
    assert lezen.status_code == 200, lezen.text
    assert len(lezen.json()["open_punten"]) == 2
    assert lezen.json()["wensen"][0]["titel"] == WENS["titel"]
    assert wijzigen.status_code in (403, 404), wijzigen.text
    await db_session.refresh(initiatief)
    assert len(initiatief.open_punten) == 2
    assert len(initiatief.wensen) == 1


async def test_buiten_het_initiatief_niets_te_zien(client, db_session, initiatief):
    await _zet(client, initiatief, open_punten=PUNTEN, wensen=[WENS])
    vreemde = await make_person(db_session, "Buitenstaander ritme")
    async with client_as(db_session, vreemde) as c:
        resp = await c.get(f"/api/initiatieven/{initiatief.id}")
    assert resp.status_code in (403, 404), resp.text
    assert "GitHub" not in resp.text
    assert "volgorde" not in resp.text


async def test_het_overzicht_stuurt_ze_niet_mee(client, initiatief):
    """GET /api/initiatieven geeft per initiatief een kaartje: zonder ritme,
    open punten en wensen. Die leest alleen de tab RegelRitme, uit de
    detailrespons, en anders groeit het overzicht met elk team mee."""
    await _zet(client, initiatief, open_punten=PUNTEN, wensen=[WENS])
    resp = await client.get("/api/initiatieven")
    assert resp.status_code == 200, resp.text
    item = next(i for i in resp.json() if i["id"] == str(initiatief.id))
    assert "overleggen" not in item
    assert "open_punten" not in item
    assert "wensen" not in item
    assert "volgorde" not in resp.text
    # De detailrespons en het antwoord op opslaan houden ze wel.
    detail = (await client.get(f"/api/initiatieven/{initiatief.id}")).json()
    assert {"overleggen", "open_punten", "wensen"} <= detail.keys()


async def test_de_publieke_pagina_toont_ze_niet(client, initiatief):
    await _zet(client, initiatief, open_punten=PUNTEN, wensen=[WENS])
    resp = await client.get("/api/public/initiatieven/by-slug/rr-open-punten")
    assert resp.status_code == 200, resp.text
    assert "open_punten" not in resp.json()
    assert "wensen" not in resp.json()
    assert "GitHub" not in resp.text
    assert "volgorde" not in resp.text
