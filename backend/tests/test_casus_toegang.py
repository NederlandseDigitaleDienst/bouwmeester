"""Toegang tot casuswerk: alleen voor wie het initiatief kan zien.

Issues en taken van een casus zijn zo vertrouwelijk als de casus.
Dit bestand bewaakt de regels die daarbij horen:

- Een taak op een casus is buiten het initiatief onvindbaar: 404 op detail,
  wijzigen en verwijderen, en afwezig in elke lijst, ook "mijn taken" en de
  inbox. Wie uit het initiatief gaat, ziet zijn eigen casustaken niet meer.
- Een taak op een casus aanmaken of ernaartoe verplaatsen kan alleen binnen
  een zichtbare casus, ook via een issue.
- Wie een casustaak doet, moet lid zijn van het initiatief (direct of via
  een eenheid). Anders 400, net als bij trekker en teamlid.
- Een subtaak hangt alleen onder een taak die je kunt zien (anders 404, en
  er ontstaat niets), en altijd in dezelfde casus als haar hoofdtaak (anders
  400): geen werk uit casus B onder een taak in casus A.
- Taken aan een node volgen deze regels niet; daar geldt de org-scope.
- De kandidatenlijst van een initiatief laat zien waarom iemand erbij hoort.
"""

import uuid

import pytest
from sqlalchemy import delete as sa_delete

from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.repositories.lead_column import LeadColumnRepository
from tests.factories import (
    START_INTERN,
    client_as,
    grant_role,
    make_org,
    make_person,
    place,
)

START = START_INTERN


@pytest.fixture
async def initiatief(db_session):
    init = Initiatief(id=uuid.uuid4(), naam="Regelrecht toegang", slug="rr-toegang")
    db_session.add(init)
    await db_session.flush()
    await LeadColumnRepository(db_session).seed_defaults(init.id)
    return init


async def _lid_van(db_session, initiatief_id, person_id, rol="contributor"):
    db_session.add(
        ResourcePermission(
            person_id=person_id,
            resource_type="initiatief",
            resource_id=initiatief_id,
            rol=rol,
        )
    )
    await db_session.flush()


@pytest.fixture
async def werkeenheid(db_session):
    """De eenheid waar iedereen zijn taakrechten van krijgt (rollen zijn
    altijd aan een eenheid gebonden)."""
    return await make_org(db_session, "Werkeenheid")


@pytest.fixture
async def lid(db_session, initiatief, werkeenheid):
    """Teamlid: ziet het initiatief en mag met taken werken."""
    p = await make_person(db_session, "Teamlid")
    await grant_role(db_session, p, "editor", werkeenheid)
    await _lid_van(db_session, initiatief.id, p.id)
    return p


@pytest.fixture
async def buitenstaander(db_session, werkeenheid):
    """Mag met taken werken, maar hoort niet bij het initiatief."""
    p = await make_person(db_session, "Buitenstaander")
    await grant_role(db_session, p, "editor", werkeenheid)
    return p


@pytest.fixture
async def casus(client, db_session, initiatief):
    lead = Lead(
        id=uuid.uuid4(),
        title="Toegangscasus",
        stage="in_the_pocket",
        initiatief_id=initiatief.id,
    )
    db_session.add(lead)
    await db_session.flush()
    resp = await client.post(
        "/api/casussen", json={"lead_id": str(lead.id), "startvoorwaarden": START}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def taak(client, casus, lid):
    resp = await client.post(
        "/api/tasks",
        json={
            "title": "Casustaak",
            "casus_id": casus["id"],
            "assignee_id": str(lid.id),
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Zien
# ---------------------------------------------------------------------------


async def test_buitenstaander_vindt_casustaak_niet(db_session, buitenstaander, taak):
    tid = taak["id"]
    async with client_as(db_session, buitenstaander) as c:
        assert (await c.get(f"/api/tasks/{tid}")).status_code == 404
        assert (await c.get(f"/api/tasks/{tid}/subtasks")).status_code == 404
        assert (
            await c.put(f"/api/tasks/{tid}", json={"title": "x"})
        ).status_code == 404
        assert (
            await c.put(f"/api/tasks/{tid}/subtasks/reorder", json={"task_ids": []})
        ).status_code == 404
        assert (await c.delete(f"/api/tasks/{tid}")).status_code == 404
    # En hij bestaat nog gewoon.
    async with client_as(db_session, None) as admin:
        assert (await admin.get(f"/api/tasks/{tid}")).status_code == 200


async def test_lid_ziet_casustaak(db_session, lid, taak):
    async with client_as(db_session, lid) as c:
        resp = await c.get(f"/api/tasks/{taak['id']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Casustaak"


async def test_casustaak_staat_in_geen_lijst_buiten_het_initiatief(
    client, db_session, buitenstaander, lid, casus, taak
):
    los = await client.post(
        "/api/tasks", json={"title": "Zonder uitvoerder", "casus_id": casus["id"]}
    )
    assert los.status_code == 201
    verborgen = {taak["id"], los.json()["id"]}
    async with client_as(db_session, buitenstaander) as c:
        for url, params in [
            ("/api/tasks", {}),
            ("/api/tasks", {"assignee_id": str(lid.id)}),
            ("/api/tasks/unassigned", {}),
        ]:
            resp = await c.get(url, params=params)
            assert resp.status_code == 200, (url, resp.text)
            assert verborgen.isdisjoint({t["id"] for t in resp.json()}), url
        assert (
            await c.get("/api/tasks", params={"casus_id": casus["id"]})
        ).status_code == 404


async def test_wie_uit_het_initiatief_gaat_ziet_eigen_casustaak_niet_meer(
    db_session, initiatief, lid, taak
):
    async with client_as(db_session, lid) as c:
        assert taak["id"] in {t["id"] for t in (await c.get("/api/tasks/my")).json()}
        inbox = (await c.get("/api/tasks/inbox")).json()
        assert taak["id"] in {i["related_task_id"] for i in inbox["items"]}

    await db_session.execute(
        sa_delete(ResourcePermission).where(
            ResourcePermission.resource_type == "initiatief",
            ResourcePermission.resource_id == initiatief.id,
            ResourcePermission.person_id == lid.id,
        )
    )
    await db_session.flush()

    async with client_as(db_session, lid) as c:
        assert taak["id"] not in {
            t["id"] for t in (await c.get("/api/tasks/my")).json()
        }
        inbox = (await c.get("/api/tasks/inbox")).json()
        assert taak["id"] not in {i["related_task_id"] for i in inbox["items"]}
        assert (await c.get(f"/api/tasks/{taak['id']}")).status_code == 404


# ---------------------------------------------------------------------------
# Aanmaken en verplaatsen
# ---------------------------------------------------------------------------


async def test_buitenstaander_maakt_geen_taak_op_casus(
    client, db_session, buitenstaander, casus
):
    cid = casus["id"]
    issue = await client.post(f"/api/casussen/{cid}/issues", json={"title": "Vraag"})
    assert issue.status_code == 201
    async with client_as(db_session, buitenstaander) as c:
        for anker in [{"casus_id": cid}, {"issue_id": issue.json()["id"]}]:
            resp = await c.post("/api/tasks", json={"title": "Stiekem", **anker})
            assert resp.status_code == 404, (anker, resp.text)


async def test_buitenstaander_verplaatst_nodetaak_niet_naar_casus(
    db_session, buitenstaander, casus, sample_node
):
    async with client_as(db_session, buitenstaander) as c:
        resp = await c.post(
            "/api/tasks", json={"title": "Nodetaak", "node_id": str(sample_node.id)}
        )
        assert resp.status_code == 201, resp.text
        resp = await c.put(
            f"/api/tasks/{resp.json()['id']}", json={"casus_id": casus["id"]}
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Wie doet de taak
# ---------------------------------------------------------------------------


async def test_uitvoerder_moet_lid_zijn(db_session, lid, buitenstaander, casus, taak):
    async with client_as(db_session, lid) as c:
        resp = await c.post(
            "/api/tasks",
            json={
                "title": "Voor een vreemde",
                "casus_id": casus["id"],
                "assignee_id": str(buitenstaander.id),
            },
        )
        assert resp.status_code == 400
        assert "geen lid van Regelrecht toegang" in resp.json()["detail"]

        resp = await c.put(
            f"/api/tasks/{taak['id']}", json={"assignee_id": str(buitenstaander.id)}
        )
        assert resp.status_code == 400

        resp = await c.put(f"/api/tasks/{taak['id']}", json={"assignee_id": None})
        assert resp.status_code == 200
        resp = await c.put(
            f"/api/tasks/{taak['id']}", json={"assignee_id": str(lid.id)}
        )
        assert resp.status_code == 200
        assert resp.json()["assignee_id"] == str(lid.id)


async def test_ook_een_beheerder_wijst_geen_buitenstaander_toe(
    client, buitenstaander, casus
):
    resp = await client.post(
        "/api/tasks",
        json={
            "title": "Door admin",
            "casus_id": casus["id"],
            "assignee_id": str(buitenstaander.id),
        },
    )
    assert resp.status_code == 400


async def test_verhuizen_naar_casus_controleert_de_uitvoerder(
    client, buitenstaander, casus, sample_node
):
    """Een nodetaak met een buitenstaander erop mag niet zo een casus in."""
    resp = await client.post(
        "/api/tasks",
        json={
            "title": "Nodetaak",
            "node_id": str(sample_node.id),
            "assignee_id": str(buitenstaander.id),
        },
    )
    assert resp.status_code == 201, resp.text
    resp = await client.put(
        f"/api/tasks/{resp.json()['id']}", json={"casus_id": casus["id"]}
    )
    assert resp.status_code == 400


async def test_nodetaak_blijft_vrij(client, buitenstaander, sample_node):
    resp = await client.post(
        "/api/tasks",
        json={
            "title": "Nodetaak",
            "node_id": str(sample_node.id),
            "assignee_id": str(buitenstaander.id),
        },
    )
    assert resp.status_code == 201, resp.text


async def test_lid_via_eenheid_telt_mee(client, db_session, initiatief, casus):
    """Toegang via een gekoppelde eenheid is net zo goed als een directe rol."""
    org = await make_org(db_session, "Directie Toegang")
    collega = await make_person(db_session, "Collega via eenheid")
    await place(db_session, collega, org)
    db_session.add(
        ResourcePermission(
            organisatie_eenheid_id=org.id,
            resource_type="initiatief",
            resource_id=initiatief.id,
            rol="viewer",
        )
    )
    await db_session.flush()
    resp = await client.post(
        "/api/tasks",
        json={
            "title": "Voor collega",
            "casus_id": casus["id"],
            "assignee_id": str(collega.id),
        },
    )
    assert resp.status_code == 201, resp.text

    resp = await client.get(f"/api/initiatieven/{initiatief.id}/personen")
    assert resp.status_code == 200
    rij = next(p for p in resp.json() if p["id"] == str(collega.id))
    assert rij["rol"] is None
    assert rij["via_eenheden"] == ["Directie Toegang"]


# ---------------------------------------------------------------------------
# Het team zichtbaar
# ---------------------------------------------------------------------------


async def test_personen_toont_wie_erbij_hoort_en_waarom(
    db_session, initiatief, lid, buitenstaander
):
    async with client_as(db_session, lid) as c:
        resp = await c.get(f"/api/initiatieven/{initiatief.id}/personen")
    assert resp.status_code == 200
    rijen = {p["id"]: p for p in resp.json()}
    assert str(lid.id) in rijen
    assert rijen[str(lid.id)]["rol"] == "contributor"
    assert rijen[str(lid.id)]["via_eenheden"] == []
    assert str(buitenstaander.id) not in rijen

    # Zonder enige rol of lidmaatschap: niet gevonden. (Een rol met
    # initiatief:update op een eenheid opent het initiatief wel; dat is
    # bestaand gedrag van GET /initiatieven/{id} en staat hier buiten.)
    vreemde = await make_person(db_session, "Vreemde")
    async with client_as(db_session, vreemde) as c:
        resp = await c.get(f"/api/initiatieven/{initiatief.id}/personen")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Subtaken
# ---------------------------------------------------------------------------


async def test_buitenstaander_hangt_geen_subtaak_onder_casustaak(
    db_session, buitenstaander, taak, sample_node
):
    async with client_as(db_session, buitenstaander) as c:
        # Met een eigen node, zodat de route de hoofdtaak echt opzoekt.
        resp = await c.post(
            "/api/tasks",
            json={
                "title": "Stiekem",
                "parent_id": taak["id"],
                "node_id": str(sample_node.id),
            },
        )
        assert resp.status_code == 404, resp.text
        # Ook niet door een eigen taak eronder te hangen.
        eigen = await c.post(
            "/api/tasks", json={"title": "Eigen", "node_id": str(sample_node.id)}
        )
        assert eigen.status_code == 201, eigen.text
        resp = await c.put(
            f"/api/tasks/{eigen.json()['id']}", json={"parent_id": taak["id"]}
        )
        assert resp.status_code == 404, resp.text
    async with client_as(db_session, None) as admin:
        subs = await admin.get(f"/api/tasks/{taak['id']}/subtasks")
    assert subs.json() == []


async def test_casustaak_hangt_onder_geen_andere_taak(
    client, db_session, initiatief, lid, taak
):
    # Een tweede casus in hetzelfde initiatief: het lid ziet ze allebei.
    lead = Lead(
        id=uuid.uuid4(),
        title="Andere casus",
        stage="in_the_pocket",
        initiatief_id=initiatief.id,
    )
    db_session.add(lead)
    await db_session.flush()
    ander = await client.post(
        "/api/casussen", json={"lead_id": str(lead.id), "startvoorwaarden": START}
    )
    assert ander.status_code == 201, ander.text
    andere_casus = ander.json()["id"]

    async with client_as(db_session, lid) as c:
        resp = await c.post(
            "/api/tasks",
            json={"title": "Uit B", "parent_id": taak["id"], "casus_id": andere_casus},
        )
        assert resp.status_code == 400, resp.text
        # Een taak uit casus B kan niet onder een taak in casus A gaan hangen.
        b = await c.post("/api/tasks", json={"title": "In B", "casus_id": andere_casus})
        assert b.status_code == 201, b.text
        resp = await c.put(
            f"/api/tasks/{b.json()['id']}", json={"parent_id": taak["id"]}
        )
        assert resp.status_code == 400, resp.text
        # En een subtaak in de eigen casus ook niet: casustaken hebben er geen.
        sub = await c.post(
            "/api/tasks",
            json={
                "title": "Stap",
                "parent_id": taak["id"],
                "casus_id": taak["casus_id"],
            },
        )
        assert sub.status_code == 400, sub.text
