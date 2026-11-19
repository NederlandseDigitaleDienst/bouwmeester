"""Een onderzoeksvraag zonder casus, van het initiatief zelf.

Wat dit bestand bewaakt:

- Een bijdrager maakt een vraag zonder casus via
  /initiatieven/{id}/vragen; een kijker niet (403), een buitenstaander vindt
  hem niet (404). De vraag staat in de backlog, zonder casus.
- Een taak onder zo'n vraag hangt alleen aan de vraag (casus_id leeg) en is
  zo vertrouwelijk als het initiatief: buiten het initiatief 404 en in geen
  lijst. Wie hem doet, moet lid zijn van het initiatief.
- Een vraag verhuist uit een casus naar het initiatief en terug, met zijn
  taken; niet naar een casus van een ander initiatief.
- Een vraag zonder casus met taken verwijder je niet (400); zonder taken wel.
- Het interne antwoord staat bij de vraag; een kijker wijzigt het niet.
- Afgerond en vrijgegeven gaat hij naar buiten, net als een casusvraag.
- Verwijderen van het initiatief ruimt de taken onder zo'n vraag op.
"""

import uuid

import pytest

from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.models.task import Task
from bouwmeester.repositories.lead_column import LeadColumnRepository
from tests.factories import (
    START_INTERN,
    client_as,
    grant_role,
    make_org,
    make_person,
)


async def _initiatief(db_session, slug):
    init = Initiatief(
        id=uuid.uuid4(), naam=f"Init {slug}", slug=slug, casussen_enabled=True
    )
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


async def _casus(client, db_session, initiatief):
    lead = Lead(
        id=uuid.uuid4(),
        title="Een casus",
        stage="in_the_pocket",
        initiatief_id=initiatief.id,
    )
    db_session.add(lead)
    await db_session.flush()
    resp = await client.post(
        "/api/casussen",
        json={"lead_id": str(lead.id), "startvoorwaarden": START_INTERN},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def initiatief(db_session):
    return await _initiatief(db_session, "rr-los")


@pytest.fixture
async def werkeenheid(db_session):
    return await make_org(db_session, "Werkeenheid")


@pytest.fixture
async def lid(db_session, initiatief, werkeenheid):
    p = await make_person(db_session, "Bijdrager")
    await grant_role(db_session, p, "editor", werkeenheid)
    await _lid_van(db_session, initiatief.id, p.id)
    return p


@pytest.fixture
async def kijker(db_session, initiatief, werkeenheid):
    p = await make_person(db_session, "Kijker")
    await grant_role(db_session, p, "editor", werkeenheid)
    await _lid_van(db_session, initiatief.id, p.id, rol="viewer")
    return p


@pytest.fixture
async def buitenstaander(db_session, werkeenheid):
    p = await make_person(db_session, "Buitenstaander")
    await grant_role(db_session, p, "editor", werkeenheid)
    return p


@pytest.fixture
async def vraag(db_session, initiatief, lid):
    async with client_as(db_session, lid) as c:
        resp = await c.post(
            f"/api/initiatieven/{initiatief.id}/vragen",
            json={"title": "Wat is de rol van werkpakketten?"},
        )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def taak(db_session, vraag, lid):
    async with client_as(db_session, lid) as c:
        resp = await c.post(
            "/api/tasks",
            json={
                "title": "Werkpakketten op een rij",
                "issue_id": vraag["id"],
                "assignee_id": str(lid.id),
            },
        )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_bijdrager_maakt_vraag_zonder_casus(db_session, initiatief, lid, vraag):
    assert vraag["casus_id"] is None
    assert vraag["initiatief_id"] == str(initiatief.id)
    async with client_as(db_session, lid) as c:
        lijst = (await c.get(f"/api/initiatieven/{initiatief.id}/vragen")).json()
        backlog = (
            await c.get(
                "/api/casussen/backlog", params={"initiatief_id": str(initiatief.id)}
            )
        ).json()
    assert [v["id"] for v in lijst] == [vraag["id"]]
    item = next(i for i in backlog["issues"] if i["id"] == vraag["id"])
    assert item["casus"] is None and item["casus_id"] is None


async def test_kijker_en_buitenstaander(
    db_session, initiatief, kijker, buitenstaander, vraag
):
    pad = f"/api/initiatieven/{initiatief.id}/vragen"
    async with client_as(db_session, kijker) as c:
        assert (await c.get(pad)).status_code == 200
        assert (await c.post(pad, json={"title": "Nee"})).status_code == 403
        assert (
            await c.put(f"{pad}/{vraag['id']}", json={"title": "Anders"})
        ).status_code == 403
    async with client_as(db_session, buitenstaander) as c:
        assert (await c.get(pad)).status_code == 404
        assert (await c.post(pad, json={"title": "Nee"})).status_code == 404
        assert (await c.delete(f"{pad}/{vraag['id']}")).status_code == 404


async def test_taak_onder_vraag_zonder_casus(db_session, buitenstaander, taak):
    assert taak["casus_id"] is None and taak["node_id"] is None
    async with client_as(db_session, buitenstaander) as c:
        assert (await c.get(f"/api/tasks/{taak['id']}")).status_code == 404
        assert (
            await c.put(f"/api/tasks/{taak['id']}", json={"status": "done"})
        ).status_code == 404
        assert (await c.delete(f"/api/tasks/{taak['id']}")).status_code == 404
        for url in ["/api/tasks", "/api/tasks/unassigned"]:
            resp = await c.get(url)
            assert resp.status_code == 200, (url, resp.text)
            assert taak["id"] not in {t["id"] for t in resp.json()}, url


async def test_uitvoerder_moet_lid_zijn(db_session, lid, buitenstaander, vraag):
    async with client_as(db_session, lid) as c:
        resp = await c.post(
            "/api/tasks",
            json={
                "title": "Voor een buitenstaander",
                "issue_id": vraag["id"],
                "assignee_id": str(buitenstaander.id),
            },
        )
    assert resp.status_code == 400, resp.text


async def test_kijker_werkt_eigen_taak_bij_maar_maakt_er_geen(
    db_session, lid, kijker, vraag
):
    async with client_as(db_session, lid) as c:
        taak = (
            await c.post(
                "/api/tasks",
                json={
                    "title": "Voor de kijker",
                    "issue_id": vraag["id"],
                    "assignee_id": str(kijker.id),
                },
            )
        ).json()
    async with client_as(db_session, kijker) as c:
        assert (
            await c.put(f"/api/tasks/{taak['id']}", json={"status": "in_progress"})
        ).status_code == 200
        assert (
            await c.post("/api/tasks", json={"title": "Zelf", "issue_id": vraag["id"]})
        ).status_code == 403


async def test_vraag_verhuist_uit_casus_en_terug(client, db_session, initiatief, lid):
    casus = await _casus(client, db_session, initiatief)
    async with client_as(db_session, lid) as c:
        v = (
            await c.post(
                f"/api/casussen/{casus['id']}/issues", json={"title": "Verhuisvraag"}
            )
        ).json()
        assert v["initiatief_id"] == str(initiatief.id)
        t = (
            await c.post("/api/tasks", json={"title": "Mee", "issue_id": v["id"]})
        ).json()
        assert t["casus_id"] == casus["id"]

        uit = await c.put(
            f"/api/casussen/{casus['id']}/issues/{v['id']}", json={"casus_id": None}
        )
        assert uit.status_code == 200, uit.text
        assert uit.json()["casus_id"] is None
        assert (await c.get(f"/api/tasks/{t['id']}")).json()["casus_id"] is None

        terug = await c.put(
            f"/api/initiatieven/{initiatief.id}/vragen/{v['id']}",
            json={"casus_id": casus["id"]},
        )
        assert terug.status_code == 200, terug.text
        assert terug.json()["casus_id"] == casus["id"]
        assert (await c.get(f"/api/tasks/{t['id']}")).json()["casus_id"] == casus["id"]


async def test_niet_naar_casus_van_ander_initiatief(
    client, db_session, initiatief, lid, vraag
):
    ander = await _initiatief(db_session, "rr-ander")
    await _lid_van(db_session, ander.id, lid.id)
    casus = await _casus(client, db_session, ander)
    async with client_as(db_session, lid) as c:
        resp = await c.put(
            f"/api/initiatieven/{initiatief.id}/vragen/{vraag['id']}",
            json={"casus_id": casus["id"]},
        )
        assert resp.status_code == 400, resp.text
        # Via het pad van het andere initiatief bestaat de vraag niet.
        assert (
            await c.put(
                f"/api/initiatieven/{ander.id}/vragen/{vraag['id']}",
                json={"title": "Weg"},
            )
        ).status_code == 404


async def test_verwijderen_alleen_zonder_taken(db_session, initiatief, lid, taak):
    pad = f"/api/initiatieven/{initiatief.id}/vragen"
    async with client_as(db_session, lid) as c:
        vraag_id = (await c.get(pad)).json()[0]["id"]
        assert (await c.delete(f"{pad}/{vraag_id}")).status_code == 400
        assert (await c.delete(f"/api/tasks/{taak['id']}")).status_code == 204
        assert (await c.delete(f"{pad}/{vraag_id}")).status_code == 204


async def test_intern_antwoord(db_session, initiatief, lid, kijker, vraag):
    """Het interne antwoord staat bij de vraag, wissen kan met een lege
    waarde; een kijker past het niet aan."""
    pad = f"/api/initiatieven/{initiatief.id}/vragen/{vraag['id']}"
    async with client_as(db_session, lid) as c:
        resp = await c.put(pad, json={"antwoord": "<p>Zo zit het, binnen.</p>"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["antwoord"] == "<p>Zo zit het, binnen.</p>"
        backlog = (
            await c.get(f"/api/casussen/backlog?initiatief_id={initiatief.id}")
        ).json()
        assert backlog["issues"][0]["antwoord"] == "<p>Zo zit het, binnen.</p>"
        too_long = await c.put(pad, json={"antwoord": "x" * 20001})
        assert too_long.status_code == 422
    async with client_as(db_session, kijker) as c:
        assert (await c.put(pad, json={"antwoord": "Anders"})).status_code == 403
    async with client_as(db_session, lid) as c:
        resp = await c.put(pad, json={"antwoord": None})
        assert resp.json()["antwoord"] is None


async def test_vrijgegeven_vraag_zonder_casus_gaat_naar_buiten(
    db_session, initiatief, lid, vraag
):
    pad = f"/api/initiatieven/{initiatief.id}/vragen/{vraag['id']}"
    async with client_as(db_session, lid) as c:
        assert (await c.put(pad, json={"status": "done"})).status_code == 200
        resp = await c.put(
            f"{pad}/publiek",
            json={"public_title": "Werkpakketten", "public_answer": "Zo zit het."},
        )
        assert resp.status_code == 200, resp.text
        vrij = (
            await c.get(f"/api/initiatieven/{initiatief.id}/vrijgegeven-vragen")
        ).json()
    assert vraag["id"] in {v["id"] for v in vrij}


async def test_initiatief_verwijderen_ruimt_taken_op(
    client, db_session, initiatief, taak
):
    resp = await client.delete(f"/api/initiatieven/{initiatief.id}")
    assert resp.status_code == 204, resp.text
    assert await db_session.get(Task, uuid.UUID(taak["id"])) is None
