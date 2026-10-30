"""Subtaken: alleen buiten een casus, en dan zoals op main.

- Een taak in een casus heeft geen subtaken: een subtaak eronder, een
  casustaak onder een andere taak hangen, of een subtaak of een taak met
  subtaken naar een casus verhuizen, geeft 400. Het werk staat dan als
  gewone taken onder de onderzoeksvraag.
- Een taak aan een node (buiten een casus) heeft ze wel, als gewone taken
  met eigen kenmerken: een subtaak neemt niets over van de hoofdtaak, en
  een wijziging van de hoofdtaak laat de subtaken staan. Zo verliest het
  bestaande werk in Bouwmeester niets.
- Zichtbaarheid van de hoofdtaak staat in test_casus_toegang.py, bij de
  andere toegangsregels.
"""

import uuid

import pytest

from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.repositories.lead_column import LeadColumnRepository
from tests.factories import START_INTERN, make_person


@pytest.fixture
async def uitvoerder(db_session):
    return await make_person(db_session, "Uitvoerder subtaken")


@pytest.fixture
async def tweede_uitvoerder(db_session):
    return await make_person(db_session, "Tweede uitvoerder subtaken")


@pytest.fixture
async def hoofdtaak(client, sample_node, uitvoerder):
    resp = await client.post(
        "/api/tasks",
        json={
            "title": "Hoofdtaak",
            "node_id": str(sample_node.id),
            "assignee_id": str(uitvoerder.id),
            "priority": "hoog",
            "due_date": "2026-12-01",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _subtaak(client, hoofdtaak, **extra):
    resp = await client.post(
        "/api/tasks",
        json={
            "title": "Stap",
            "parent_id": hoofdtaak["id"],
            "node_id": hoofdtaak["node_id"],
        }
        | extra,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Een taak in een casus: geen subtaken
# ---------------------------------------------------------------------------


@pytest.fixture
async def casustaak(client, db_session):
    init = Initiatief(id=uuid.uuid4(), naam="Subtaken casus", slug="rr-subtaken")
    db_session.add(init)
    await db_session.flush()
    await LeadColumnRepository(db_session).seed_defaults(init.id)
    lead = Lead(
        id=uuid.uuid4(), title="Casus", stage="in_the_pocket", initiatief_id=init.id
    )
    db_session.add(lead)
    await db_session.flush()
    casus = await client.post(
        "/api/casussen",
        json={"lead_id": str(lead.id), "startvoorwaarden": START_INTERN},
    )
    assert casus.status_code == 201, casus.text
    vraag = await client.post(
        f"/api/casussen/{casus.json()['id']}/issues", json={"title": "Werkt het?"}
    )
    assert vraag.status_code == 201, vraag.text
    taak = await client.post(
        "/api/tasks", json={"title": "Taak", "issue_id": vraag.json()["id"]}
    )
    assert taak.status_code == 201, taak.text
    return taak.json()


async def test_casustaak_krijgt_geen_subtaak(client, casustaak):
    resp = await client.post(
        "/api/tasks",
        json={
            "title": "Stap",
            "parent_id": casustaak["id"],
            "issue_id": casustaak["issue_id"],
        },
    )
    assert resp.status_code == 400, resp.text
    assert "geen subtaken" in resp.json()["detail"]


async def test_casustaak_hangt_niet_onder_een_andere_taak(client, casustaak, hoofdtaak):
    # Niet onder een taak aan een node...
    resp = await client.put(
        f"/api/tasks/{casustaak['id']}", json={"parent_id": hoofdtaak["id"]}
    )
    assert resp.status_code == 400, resp.text
    # ...en een nieuwe taak met een casus ook niet.
    resp = await client.post(
        "/api/tasks",
        json={
            "title": "Stap",
            "parent_id": hoofdtaak["id"],
            "casus_id": casustaak["casus_id"],
        },
    )
    assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# Een taak aan een node: subtaken zoals op main
# ---------------------------------------------------------------------------


async def test_subtaak_neemt_niets_over_van_de_hoofdtaak(client, hoofdtaak):
    sub = await _subtaak(client, hoofdtaak)
    assert sub["parent_id"] == hoofdtaak["id"]
    assert sub["assignee_id"] is None
    assert sub["due_date"] is None
    assert sub["priority"] != hoofdtaak["priority"]
    assert sub["casus_id"] is None


async def test_subtaak_met_eigen_kenmerken(client, hoofdtaak, tweede_uitvoerder):
    sub = await _subtaak(
        client,
        hoofdtaak,
        assignee_id=str(tweede_uitvoerder.id),
        priority="laag",
        due_date="2027-01-15",
        work_type="Review",
    )
    assert sub["assignee_id"] == str(tweede_uitvoerder.id)
    assert (sub["priority"], sub["due_date"], sub["work_type"]) == (
        "laag",
        "2027-01-15",
        "Review",
    )


async def test_wijziging_van_de_hoofdtaak_laat_subtaken_staan(
    client, hoofdtaak, uitvoerder, tweede_uitvoerder
):
    """Op main houdt een subtaak haar eigen waarden; dat blijft zo."""
    sub = await _subtaak(
        client,
        hoofdtaak,
        assignee_id=str(uitvoerder.id),
        priority="laag",
        due_date="2027-01-15",
        work_type="Review",
    )
    resp = await client.put(
        f"/api/tasks/{hoofdtaak['id']}",
        json={
            "assignee_id": str(tweede_uitvoerder.id),
            "priority": "kritiek",
            "due_date": "2026-11-11",
            "work_type": "Analyse",
            "title": "Nieuw",
            "status": "done",
        },
    )
    assert resp.status_code == 200, resp.text
    na = (await client.get(f"/api/tasks/{sub['id']}")).json()
    assert na["assignee_id"] == str(uitvoerder.id)
    assert (na["priority"], na["due_date"], na["work_type"]) == (
        "laag",
        "2027-01-15",
        "Review",
    )
    assert (na["title"], na["status"]) == ("Stap", "open")


async def test_subtaak_zonder_node_is_422(client, hoofdtaak):
    resp = await client.post(
        "/api/tasks", json={"title": "Los", "parent_id": hoofdtaak["id"]}
    )
    assert resp.status_code == 422


async def test_onbekende_hoofdtaak_geeft_404(client, hoofdtaak):
    resp = await client.post(
        "/api/tasks",
        json={
            "title": "Wees",
            "parent_id": str(uuid.uuid4()),
            "node_id": hoofdtaak["node_id"],
        },
    )
    assert resp.status_code == 404


async def test_subtaak_of_taak_met_subtaken_gaat_niet_naar_een_casus(
    client, hoofdtaak, casustaak
):
    sub = await _subtaak(client, hoofdtaak)
    for taak in (sub, hoofdtaak):
        resp = await client.put(
            f"/api/tasks/{taak['id']}", json={"issue_id": casustaak["issue_id"]}
        )
        assert resp.status_code == 400, resp.text
        na = (await client.get(f"/api/tasks/{taak['id']}")).json()
        assert na["casus_id"] is None


async def test_subtaken_staan_in_de_volgorde_waarin_ze_zijn_gemaakt(client, hoofdtaak):
    titels = ["Eerste", "Tweede", "Derde"]
    for titel in titels:
        await _subtaak(client, hoofdtaak, title=titel)
    detail = (await client.get(f"/api/tasks/{hoofdtaak['id']}")).json()
    assert [s["title"] for s in detail["subtasks"]] == titels
