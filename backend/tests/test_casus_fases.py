"""De casusfunnel per initiatief.

Dekt:
- zonder eigen funnel geldt het voorstel (zes fases, Uitvoeren in plaats
  van Werken in ritme), en het initiatief toont of dat zo is;
- de eigenaar zet een eigen funnel (naam, kleur, omschrijving, door als);
  een lege lijst zet het voorstel terug;
- een fase weghalen waar nog casussen in staan: 409;
- een nieuwe casus begint in de eerste fase van de funnel;
- een casus kan alleen naar een fase uit de funnel (anders 400);
- dubbele ids of namen, of een onbekende kleur: 422;
- alleen de eigenaar beheert de funnel (een lid krijgt 403).
"""

import uuid

import pytest

from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.repositories.lead_column import LeadColumnRepository
from bouwmeester.schema.casus_fases import DEFAULT_CASUS_FASES
from tests.factories import START_INTERN, client_as, make_person


@pytest.fixture
async def initiatief(db_session):
    init = Initiatief(id=uuid.uuid4(), naam="Regelrecht funnel", slug="rr-funnel")
    db_session.add(init)
    await db_session.flush()
    await LeadColumnRepository(db_session).seed_defaults(init.id)
    return init


async def _casus(client, db_session, initiatief, title="Casus"):
    lead = Lead(
        id=uuid.uuid4(), title=title, stage="in_the_pocket", initiatief_id=initiatief.id
    )
    db_session.add(lead)
    await db_session.flush()
    resp = await client.post(
        "/api/casussen",
        json={"lead_id": str(lead.id), "startvoorwaarden": START_INTERN},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _settings(initiatief):
    return f"/api/initiatieven/{initiatief.id}/settings"


EIGEN = [
    {"id": "verkennen", "naam": "Verkennen", "kleur": "lintblauw", "door_als": "x"},
    {"id": "bouwen", "naam": "Bouwen", "kleur": "oranje", "omschrijving": "We bouwen"},
    {"id": "klaar", "naam": "Klaar", "kleur": "success"},
]


async def test_zonder_eigen_funnel_het_voorstel(client, initiatief):
    resp = await client.get(f"/api/initiatieven/{initiatief.id}")
    body = resp.json()
    assert [f["naam"] for f in body["casus_fases"]] == [
        "Start",
        "Scherpstellen",
        "Uitvoeren",
        "Afronden",
        "Delen",
        "Besluiten",
    ]
    assert body["casus_fases"][0]["door_als"].startswith("de analist aan boord is")
    assert body["casus_fases_is_voorstel"] is True
    assert len(body["casus_fases_voorstel"]) == len(DEFAULT_CASUS_FASES)


async def test_eigen_funnel_en_terug_naar_voorstel(client, initiatief):
    resp = await client.put(_settings(initiatief), json={"casus_fases": EIGEN})
    assert resp.status_code == 200, resp.text
    assert [f["id"] for f in resp.json()["casus_fases"]] == [
        "verkennen",
        "bouwen",
        "klaar",
    ]
    detail = (await client.get(f"/api/initiatieven/{initiatief.id}")).json()
    assert detail["casus_fases_is_voorstel"] is False
    assert detail["casus_fases"][1]["omschrijving"] == "We bouwen"

    resp = await client.put(_settings(initiatief), json={"casus_fases": []})
    assert resp.status_code == 200
    assert resp.json()["casus_fases"][0]["id"] == "start"


async def test_nieuwe_casus_begint_in_de_eerste_fase(client, db_session, initiatief):
    resp = await client.put(_settings(initiatief), json={"casus_fases": EIGEN})
    assert resp.status_code == 200, resp.text
    casus = await _casus(client, db_session, initiatief)
    assert casus["fase"] == "verkennen"


async def test_zonder_eigen_funnel_begint_een_casus_bij_start(
    client, db_session, initiatief
):
    assert (await _casus(client, db_session, initiatief))["fase"] == "start"


async def test_casus_alleen_naar_fase_uit_de_funnel(client, db_session, initiatief):
    casus = await _casus(client, db_session, initiatief)
    url = f"/api/casussen/{casus['id']}"
    assert (await client.put(url, json={"fase": "uitvoeren"})).status_code == 200
    assert (await client.put(url, json={"fase": "bouwen"})).status_code == 400


async def test_fase_met_casussen_weghalen_is_409(client, db_session, initiatief):
    casus = await _casus(client, db_session, initiatief)
    await client.put(f"/api/casussen/{casus['id']}", json={"fase": "uitvoeren"})
    resp = await client.put(_settings(initiatief), json={"casus_fases": EIGEN})
    assert resp.status_code == 409
    assert "uitvoeren (1)" in resp.json()["detail"]
    # Met de fase erin mag het wel, ook hernoemd.
    met = [*EIGEN, {"id": "uitvoeren", "naam": "Werken", "kleur": "geel"}]
    resp = await client.put(_settings(initiatief), json={"casus_fases": met})
    assert resp.status_code == 200, resp.text
    # En terug naar het voorstel kan ook: daar staat uitvoeren in.
    assert (
        await client.put(_settings(initiatief), json={"casus_fases": []})
    ).status_code == 200


@pytest.mark.parametrize(
    "fases",
    [
        [{"id": "a", "naam": "Een"}, {"id": "a", "naam": "Twee"}],
        [{"id": "a", "naam": "Een"}, {"id": "b", "naam": "een"}],
        [{"id": "a", "naam": "Een", "kleur": "#ff0000"}],
        [{"id": "Met Spatie", "naam": "Een"}],
        [{"id": f"f{i}", "naam": f"Fase {i}"} for i in range(13)],
    ],
)
async def test_ongeldige_funnel_is_422(client, initiatief, fases):
    resp = await client.put(_settings(initiatief), json={"casus_fases": fases})
    assert resp.status_code == 422


async def test_alleen_eigenaar_beheert_de_funnel(db_session, initiatief):
    lid = await make_person(db_session, "Lid")
    db_session.add(
        ResourcePermission(
            person_id=lid.id,
            resource_type="initiatief",
            resource_id=initiatief.id,
            rol="contributor",
        )
    )
    await db_session.flush()
    async with client_as(db_session, lid) as c:
        resp = await c.put(_settings(initiatief), json={"casus_fases": EIGEN})
    assert resp.status_code == 403
