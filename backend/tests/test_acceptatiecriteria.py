"""Acceptatiecriteria voor een nieuwe satellietcasus.

- Het initiatief heeft een eigen lijst, in te stellen door de eigenaar (de
  instellingen); lege regels vallen weg, een criterium is hooguit 300 tekens.
- Bij het starten van een satellietcasus loopt het team de lijst na: per
  criterium afgevinkt of niet, met een uitleg. Dat staat daarna bij de
  startvoorwaarden van de casus, als momentopname. Bij een interne casus
  horen geen criteria (422).
- De vraag "op welke as" is vervallen: een start zonder as kan.
"""

import uuid

import pytest

from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.resource_permission import ResourcePermission
from tests.factories import START_INTERN, client_as, grant_role, make_org, make_person

START = START_INTERN
SATELLIET = {**START, "casustype": "satelliet"}


@pytest.fixture
async def initiatief(db_session):
    init = Initiatief(id=uuid.uuid4(), naam="Criteria", slug="rr-criteria")
    db_session.add(init)
    await db_session.flush()
    return init


async def _lead(db_session, initiatief, titel="Kandidaat"):
    lead = Lead(
        id=uuid.uuid4(),
        title=titel,
        stage="in_the_pocket",
        initiatief_id=initiatief.id,
    )
    db_session.add(lead)
    await db_session.flush()
    return lead


async def test_eigenaar_stelt_de_criteria_in(client, initiatief):
    resp = await client.put(
        f"/api/initiatieven/{initiatief.id}/settings",
        json={"acceptatiecriteria": ["  Data beschikbaar ", "", "Partner gevonden"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["acceptatiecriteria"] == ["Data beschikbaar", "Partner gevonden"]
    detail = (await client.get(f"/api/initiatieven/{initiatief.id}")).json()
    assert detail["acceptatiecriteria"] == ["Data beschikbaar", "Partner gevonden"]


async def test_criterium_te_lang_is_422(client, initiatief):
    resp = await client.put(
        f"/api/initiatieven/{initiatief.id}/settings",
        json={"acceptatiecriteria": ["x" * 301]},
    )
    assert resp.status_code == 422


async def test_alleen_de_eigenaar_stelt_ze_in(db_session, initiatief):
    eenheid = await make_org(db_session, "Eenheid criteria")
    lid = await make_person(db_session, "Lid criteria")
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
    async with client_as(db_session, lid) as c:
        resp = await c.put(
            f"/api/initiatieven/{initiatief.id}/settings",
            json={"acceptatiecriteria": ["Stiekem"]},
        )
    assert resp.status_code in (403, 404), resp.text
    await db_session.refresh(initiatief)
    assert initiatief.acceptatiecriteria == []


async def test_casus_start_legt_de_afgevinkte_criteria_vast(
    client, db_session, initiatief
):
    lead = await _lead(db_session, initiatief)
    criteria = [
        {"criterium": "Data beschikbaar", "akkoord": True, "opmerking": "Via CBS"},
        {"criterium": "Partner gevonden", "akkoord": False, "opmerking": None},
    ]
    resp = await client.post(
        "/api/casussen",
        json={
            "lead_id": str(lead.id),
            "startvoorwaarden": {**SATELLIET, "acceptatiecriteria": criteria},
        },
    )
    assert resp.status_code == 201, resp.text
    casus = resp.json()
    # Een lege opmerking wordt niet opgeslagen.
    verwacht = [
        {"criterium": "Data beschikbaar", "akkoord": True, "opmerking": "Via CBS"},
        {"criterium": "Partner gevonden", "akkoord": False},
    ]
    assert casus["startvoorwaarden"]["acceptatiecriteria"] == verwacht
    opnieuw = (await client.get(f"/api/casussen/{casus['id']}")).json()
    assert opnieuw["startvoorwaarden"]["acceptatiecriteria"] == verwacht


async def test_starten_zonder_criteria_kan_nog_steeds(client, db_session, initiatief):
    lead = await _lead(db_session, initiatief, "Zonder criteria")
    resp = await client.post(
        "/api/casussen", json={"lead_id": str(lead.id), "startvoorwaarden": START}
    )
    assert resp.status_code == 201, resp.text
    assert "acceptatiecriteria" not in resp.json()["startvoorwaarden"]


async def test_leeg_criterium_is_422(client, db_session, initiatief):
    lead = await _lead(db_session, initiatief, "Leeg criterium")
    resp = await client.post(
        "/api/casussen",
        json={
            "lead_id": str(lead.id),
            "startvoorwaarden": {
                **SATELLIET,
                "acceptatiecriteria": [{"criterium": "", "akkoord": True}],
            },
        },
    )
    assert resp.status_code == 422


async def test_criteria_bij_een_interne_casus_is_422(client, db_session, initiatief):
    lead = await _lead(db_session, initiatief, "Intern met criteria")
    resp = await client.post(
        "/api/casussen",
        json={
            "lead_id": str(lead.id),
            "startvoorwaarden": {
                **START,
                "acceptatiecriteria": [{"criterium": "Partner", "akkoord": True}],
            },
        },
    )
    assert resp.status_code == 422


async def test_casustype_wordt_vastgelegd_en_as_is_niet_meer_nodig(
    client, db_session, initiatief
):
    lead = await _lead(db_session, initiatief, "Satelliet zonder as")
    resp = await client.post(
        "/api/casussen",
        json={"lead_id": str(lead.id), "startvoorwaarden": SATELLIET},
    )
    assert resp.status_code == 201, resp.text
    sv = resp.json()["startvoorwaarden"]
    assert sv["casustype"] == "satelliet"
    assert "as" not in sv
