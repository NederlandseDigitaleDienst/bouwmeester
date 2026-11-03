"""Het ritme per initiatief: de vaste overleggen van het team.

Dekt: leeg zolang er niets is vastgelegd; instellen, teruglezen en weghalen
(eigenaar alleen); invoer begrensd en getoetst; een lid leest de overleggen
wel maar wijzigt ze niet; de publieke pagina toont ze niet.
"""

import uuid

import pytest

from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.resource_permission import ResourcePermission
from tests.factories import client_as, grant_role, make_org, make_person

RITME = [
    {
        "id": "retro",
        "naam": "  Retro en review  ",
        "wanneer": "Om de week, di 9.00 tot 11.00",
        "wie": "Hele team",
        "waarvoor": "Terugkijken op het werk en op hoe we werken.",
    },
    {
        "id": "demo",
        "naam": "Demo",
        "wanneer": "Om de twee weken",
        "wie": "",
        "vastgesteld": False,
    },
]


@pytest.fixture
async def initiatief(db_session):
    init = Initiatief(
        id=uuid.uuid4(),
        naam="Ritme",
        slug="rr-ritme",
        public_page_enabled=True,
    )
    db_session.add(init)
    await db_session.flush()
    return init


async def _zet(client, initiatief, overleggen):
    return await client.put(
        f"/api/initiatieven/{initiatief.id}/settings",
        json={"overleggen": overleggen},
    )


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


# ---------------------------------------------------------------------------
# Beheren
# ---------------------------------------------------------------------------


async def test_leeg_zolang_er_niets_is_vastgelegd(client, initiatief):
    resp = await client.get(f"/api/initiatieven/{initiatief.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["overleggen"] == []


async def test_instellen_teruglezen_en_weghalen(client, initiatief):
    resp = await _zet(client, initiatief, RITME)
    assert resp.status_code == 200, resp.text
    overleggen = resp.json()["overleggen"]
    assert [o["id"] for o in overleggen] == ["retro", "demo"]
    # Spaties eraf, lege tekst wordt null, vastgesteld staat standaard aan.
    assert overleggen[0]["naam"] == "Retro en review"
    assert overleggen[0]["vastgesteld"] is True
    assert overleggen[1]["wie"] is None
    assert overleggen[1]["waarvoor"] is None
    assert overleggen[1]["vastgesteld"] is False

    detail = (await client.get(f"/api/initiatieven/{initiatief.id}")).json()
    assert detail["overleggen"] == overleggen

    resp = await _zet(client, initiatief, [])
    assert resp.status_code == 200, resp.text
    assert resp.json()["overleggen"] == []


async def test_null_haalt_ze_ook_weg(client, initiatief):
    await _zet(client, initiatief, RITME)
    resp = await _zet(client, initiatief, None)
    assert resp.status_code == 200, resp.text
    assert resp.json()["overleggen"] == []


async def test_andere_instellingen_laten_het_ritme_staan(client, initiatief):
    await _zet(client, initiatief, RITME)
    resp = await client.put(
        f"/api/initiatieven/{initiatief.id}/settings",
        json={"score_politiek_label": "Politiek"},
    )
    assert resp.status_code == 200, resp.text
    assert [o["id"] for o in resp.json()["overleggen"]] == ["retro", "demo"]


@pytest.mark.parametrize(
    "overleggen",
    [
        # Twee keer dezelfde id.
        [
            {"id": "a", "naam": "Een"},
            {"id": "a", "naam": "Twee"},
        ],
        # Een naam van alleen spaties.
        [{"id": "a", "naam": "   "}],
        # Een id met hoofdletters en een spatie.
        [{"id": "Mijn overleg", "naam": "Overleg"}],
        # Te lang.
        [{"id": "a", "naam": "x" * 81}],
        [{"id": "a", "naam": "Overleg", "wanneer": "x" * 121}],
        [{"id": "a", "naam": "Overleg", "waarvoor": "x" * 501}],
        # Te veel.
        [{"id": f"o{i}", "naam": f"Overleg {i}"} for i in range(21)],
    ],
)
async def test_ongeldige_lijst_is_422(client, initiatief, overleggen):
    resp = await _zet(client, initiatief, overleggen)
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Toegang
# ---------------------------------------------------------------------------


async def test_een_lid_leest_het_ritme_maar_wijzigt_het_niet(
    client, db_session, initiatief
):
    await _zet(client, initiatief, RITME)
    lid = await _lid(db_session, initiatief)
    async with client_as(db_session, lid) as c:
        lezen = await c.get(f"/api/initiatieven/{initiatief.id}")
        wijzigen = await _zet(c, initiatief, [{"id": "x", "naam": "Eigen overleg"}])
    assert lezen.status_code == 200, lezen.text
    assert [o["id"] for o in lezen.json()["overleggen"]] == ["retro", "demo"]
    assert wijzigen.status_code in (403, 404), wijzigen.text
    await db_session.refresh(initiatief)
    assert [o["id"] for o in initiatief.overleggen] == ["retro", "demo"]


async def test_buiten_het_initiatief_geen_ritme(db_session, initiatief):
    vreemde = await make_person(db_session, "Buitenstaander ritme")
    async with client_as(db_session, vreemde) as c:
        resp = await c.get(f"/api/initiatieven/{initiatief.id}")
    assert resp.status_code in (403, 404), resp.text
    assert "overleggen" not in resp.text


async def test_de_publieke_pagina_toont_geen_overleggen(client, initiatief):
    await _zet(client, initiatief, RITME)
    resp = await client.get("/api/public/initiatieven/by-slug/rr-ritme")
    assert resp.status_code == 200, resp.text
    assert "overleggen" not in resp.json()
    assert "Retro en review" not in resp.text
