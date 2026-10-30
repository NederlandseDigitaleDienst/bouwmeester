"""Issues binnen een casus en de Definition of Done.

Een issue is een onderzoeksvraag of niet; eronder hangen taken (zonder
subtaken, zie test_subtaken.py). Dekt: issues alleen binnen een
zichtbare casus, taken alleen onder een issue van dezelfde casus, taken
blijven staan als het issue weggaat, de status volgt de taken maar
afronden gaat met de hand, DoD per initiatief (eigenaar) met
dummy-default, en afgevinkte DoD-eisen op een afgerond issue.
"""

import uuid

import pytest

from bouwmeester.models.casus import Casus
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.schema.casus import DEFAULT_DOD
from tests.factories import make_person


@pytest.fixture
async def initiatief(db_session):
    init = Initiatief(id=uuid.uuid4(), naam="Regelrecht test", slug="rr-ov")
    db_session.add(init)
    await db_session.flush()
    return init


@pytest.fixture
async def casus(db_session, initiatief):
    lead = Lead(
        id=uuid.uuid4(),
        title="Casus",
        stage="in_the_pocket",
        initiatief_id=initiatief.id,
    )
    db_session.add(lead)
    await db_session.flush()
    c = Casus(
        id=uuid.uuid4(), lead_id=lead.id, title="Casus", initiatief_id=initiatief.id
    )
    db_session.add(c)
    await db_session.flush()
    return c


async def _vraag(client, casus, vraag="Hoe modelleren we de hardheidsclausule?"):
    resp = await client.post(f"/api/casussen/{casus.id}/issues", json={"title": vraag})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_and_list_issues(client, casus):
    await _vraag(client, casus, "Eerste vraag")
    await _vraag(client, casus, "Tweede vraag")
    resp = await client.get(f"/api/casussen/{casus.id}/issues")
    assert resp.status_code == 200
    assert [v["title"] for v in resp.json()] == ["Eerste vraag", "Tweede vraag"]
    assert resp.json()[0]["status"] == "open"
    assert resp.json()[0]["task_count"] == 0


async def test_issue_on_unknown_casus_is_404(client):
    resp = await client.post(
        f"/api/casussen/{uuid.uuid4()}/issues", json={"title": "x"}
    )
    assert resp.status_code == 404


async def test_counts_tasks_and_done(client, casus):
    vraag = await _vraag(client, casus)
    await _taak(client, vraag, "t1", status="done")
    await _taak(client, vraag, "t2")
    (v,) = (await client.get(f"/api/casussen/{casus.id}/issues")).json()
    assert (v["task_count"], v["task_done_count"]) == (2, 1)


async def test_user_story_route_is_gone(client, casus):
    resp = await client.get(f"/api/casussen/{casus.id}/user-stories")
    assert resp.status_code == 404


async def test_delete_vraag_keeps_tasks(client, casus):
    vraag = await _vraag(client, casus)
    taak = await _taak(client, vraag, "blijft")
    resp = await client.delete(f"/api/casussen/{casus.id}/issues/{vraag['id']}")
    assert resp.status_code == 204
    resp = await client.get(f"/api/tasks/{taak['id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["casus_id"] == str(casus.id)
    assert resp.json()["issue_id"] is None


async def _taak(client, issue, title, **velden):
    resp = await client.post(
        "/api/tasks", json={"title": title, "issue_id": issue["id"], **velden}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_update_and_reorder_vragen(client, casus):
    a = await _vraag(client, casus, "a")
    b = await _vraag(client, casus, "b")
    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/{a['id']}",
        json={"status": "done"},
    )
    assert resp.status_code == 200 and resp.json()["status"] == "done"
    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/reorder",
        json={"issue_ids": [b["id"], a["id"]]},
    )
    assert resp.status_code == 200, resp.text
    assert [v["title"] for v in resp.json()] == ["b", "a"]


async def test_issue_with_direct_tasks(client, casus):
    issue = await _vraag(client, casus, "Synthetische dataset")
    resp = await client.post(
        "/api/tasks", json={"title": "direct", "issue_id": issue["id"]}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["casus_id"] == str(casus.id)
    assert resp.json()["issue_id"] == issue["id"]
    (i,) = (await client.get(f"/api/casussen/{casus.id}/issues")).json()
    assert (i["task_count"], i["task_done_count"]) == (1, 0)


async def test_task_on_issue_of_other_casus_is_400(client, db_session, casus):
    lead2 = Lead(id=uuid.uuid4(), title="Ander", stage="in_the_pocket")
    db_session.add(lead2)
    await db_session.flush()
    other = Casus(id=uuid.uuid4(), lead_id=lead2.id, title="Ander")
    db_session.add(other)
    await db_session.flush()
    issue = await _vraag(client, other)
    resp = await client.post(
        "/api/tasks",
        json={"title": "t", "casus_id": str(casus.id), "issue_id": issue["id"]},
    )
    assert resp.status_code == 400


async def _status(client, casus, issue_id):
    issues = (await client.get(f"/api/casussen/{casus.id}/issues")).json()
    return next(i["status"] for i in issues if i["id"] == issue_id)


async def test_issue_status_follows_tasks(client, casus):
    """In behandeling zodra er werk loopt. Ook als alles af is: afronden
    gaat met de hand, na de DoD. Een nieuwe open taak heropent het issue."""
    issue = await _vraag(client, casus, "Status volgt taken")
    a = (
        await client.post("/api/tasks", json={"title": "a", "issue_id": issue["id"]})
    ).json()
    b = (
        await client.post("/api/tasks", json={"title": "b", "issue_id": issue["id"]})
    ).json()
    assert await _status(client, casus, issue["id"]) == "open"

    await client.put(f"/api/tasks/{a['id']}", json={"status": "in_progress"})
    assert await _status(client, casus, issue["id"]) == "in_progress"

    await client.put(f"/api/tasks/{a['id']}", json={"status": "done"})
    assert await _status(client, casus, issue["id"]) == "in_progress"

    await client.put(f"/api/tasks/{b['id']}", json={"status": "done"})
    assert await _status(client, casus, issue["id"]) == "in_progress"

    await client.put(
        f"/api/casussen/{casus.id}/issues/{issue['id']}", json={"status": "done"}
    )
    assert await _status(client, casus, issue["id"]) == "done"
    # Een taak bewerken die al af was, laat het afgeronde issue staan.
    await client.put(f"/api/tasks/{b['id']}", json={"title": "b2"})
    assert await _status(client, casus, issue["id"]) == "done"

    # Een nieuwe open taak heropent het werk.
    await client.post("/api/tasks", json={"title": "c", "issue_id": issue["id"]})
    assert await _status(client, casus, issue["id"]) == "in_progress"


async def test_issue_status_after_delete(client, casus):
    issue = await _vraag(client, casus, "Verwijderen")
    await _taak(client, issue, "af", status="done")
    open_taak = await _taak(client, issue, "open")
    assert await _status(client, casus, issue["id"]) == "in_progress"
    await client.delete(f"/api/tasks/{open_taak['id']}")
    assert await _status(client, casus, issue["id"]) == "in_progress"


async def test_issue_status_manual_in_progress_stays_with_open_tasks(client, casus):
    """Met de hand op in behandeling blijft staan zolang alle taken open zijn."""
    issue = await _vraag(client, casus, "Handmatig")
    await client.put(
        f"/api/casussen/{casus.id}/issues/{issue['id']}",
        json={"status": "in_progress"},
    )
    await client.post("/api/tasks", json={"title": "x", "issue_id": issue["id"]})
    assert await _status(client, casus, issue["id"]) == "in_progress"


async def test_issue_onderzoeksvraag_flag(client, casus):
    vraag = await _vraag(client, casus, "Een vraag")
    assert vraag["is_onderzoeksvraag"] is True
    resp = await client.post(
        f"/api/casussen/{casus.id}/issues",
        json={"title": "Geen vraag", "is_onderzoeksvraag": False},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["is_onderzoeksvraag"] is False
    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/{vraag['id']}",
        json={"is_onderzoeksvraag": False},
    )
    assert resp.json()["is_onderzoeksvraag"] is False


async def test_issue_assignee_must_be_member(client, db_session, casus, initiatief):
    lid = await make_person(db_session, "Lid")
    buiten = await make_person(db_session, "Buiten")
    db_session.add(
        ResourcePermission(
            person_id=lid.id,
            resource_type="initiatief",
            resource_id=initiatief.id,
            rol="contributor",
        )
    )
    await db_session.flush()
    issue = await _vraag(client, casus, "Eigenaar")
    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/{issue['id']}",
        json={"assignee_id": str(buiten.id)},
    )
    assert resp.status_code == 400
    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/{issue['id']}",
        json={"assignee_id": str(lid.id)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["assignee"]["naam"] == "Lid"
    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/{issue['id']}",
        json={"assignee_id": None},
    )
    assert resp.json()["assignee_id"] is None


# ---------------------------------------------------------------------------
# Definition of Done
# ---------------------------------------------------------------------------


async def test_dod_default_when_initiatief_has_none(client, casus):
    resp = await client.get(f"/api/casussen/{casus.id}")
    assert resp.status_code == 200
    assert resp.json()["dod_items"] == list(DEFAULT_DOD)


async def test_dod_from_initiatief_settings(client, casus, initiatief):
    resp = await client.put(
        f"/api/initiatieven/{initiatief.id}/settings",
        json={"dod_items": ["  Demo gegeven ", "", "Verslag af"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["dod_items"] == ["Demo gegeven", "Verslag af"]
    resp = await client.get(f"/api/casussen/{casus.id}")
    assert resp.json()["dod_items"] == ["Demo gegeven", "Verslag af"]


async def test_dod_item_too_long_is_422(client, initiatief):
    resp = await client.put(
        f"/api/initiatieven/{initiatief.id}/settings", json={"dod_items": ["x" * 301]}
    )
    assert resp.status_code == 422


async def test_issue_done_stores_dod_checked(client, casus):
    issue = await _vraag(client, casus)
    assert issue["dod_checked"] == []
    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/{issue['id']}",
        json={"status": "done", "dod_checked": [DEFAULT_DOD[0], DEFAULT_DOD[1]]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "done"
    assert resp.json()["dod_checked"] == [DEFAULT_DOD[0], DEFAULT_DOD[1]]


async def test_issue_dod_checked_too_many_is_422(client, casus):
    issue = await _vraag(client, casus)
    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/{issue['id']}",
        json={"dod_checked": [f"eis {i}" for i in range(51)]},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Verhuizen naar een andere casus
# ---------------------------------------------------------------------------


async def _casus(db_session, initiatief, title):
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


async def test_issue_moves_to_other_casus_with_its_tasks(
    client, db_session, casus, initiatief
):
    doel = await _casus(db_session, initiatief, "Andere casus")
    blijft = await _vraag(client, casus, "Blijft staan")
    vraag = await _vraag(client, casus)
    direct = await _taak(client, vraag, "Direct")
    tweede = await _taak(client, vraag, "Tweede")
    los = (
        await client.post(
            "/api/tasks", json={"title": "Los", "casus_id": str(casus.id)}
        )
    ).json()

    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/{vraag['id']}",
        json={"casus_id": str(doel.id), "is_onderzoeksvraag": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["casus_id"] == str(doel.id)
    assert resp.json()["is_onderzoeksvraag"] is False
    assert resp.json()["task_count"] == 2

    oud = {
        i["id"] for i in (await client.get(f"/api/casussen/{casus.id}/issues")).json()
    }
    nieuw = {
        i["id"] for i in (await client.get(f"/api/casussen/{doel.id}/issues")).json()
    }
    assert oud == {blijft["id"]}
    assert nieuw == {vraag["id"]}
    taken_doel = (
        await client.get("/api/tasks", params={"casus_id": str(doel.id)})
    ).json()
    assert {t["id"] for t in taken_doel} == {direct["id"], tweede["id"]}
    taken_oud = (
        await client.get("/api/tasks", params={"casus_id": str(casus.id)})
    ).json()
    assert {t["id"] for t in taken_oud} == {los["id"]}


async def test_issue_does_not_move_to_other_initiatief(client, db_session, casus):
    ander = Initiatief(id=uuid.uuid4(), naam="Ander initiatief", slug="ander-ov")
    db_session.add(ander)
    await db_session.flush()
    elders = await _casus(db_session, ander, "Elders")
    vraag = await _vraag(client, casus)
    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/{vraag['id']}",
        json={"casus_id": str(elders.id)},
    )
    assert resp.status_code == 400
    assert "hetzelfde initiatief" in resp.json()["detail"]


async def test_issue_move_to_unknown_casus_is_404(client, casus):
    vraag = await _vraag(client, casus)
    resp = await client.put(
        f"/api/casussen/{casus.id}/issues/{vraag['id']}",
        json={"casus_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404


async def test_issue_move_to_invisible_casus_is_404(db_session, casus, initiatief):
    """Een lid van dit initiatief kan niet verhuizen naar een casus die hij
    niet kan zien: 404, het bestaan lekt niet."""
    from bouwmeester.models.resource_permission import ResourcePermission
    from tests.factories import client_as

    ander = Initiatief(id=uuid.uuid4(), naam="Geheim initiatief", slug="geheim-ov")
    db_session.add(ander)
    await db_session.flush()
    geheim = await _casus(db_session, ander, "Geheim")
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
        vraag = (
            await c.post(f"/api/casussen/{casus.id}/issues", json={"title": "Vraag"})
        ).json()
        resp = await c.put(
            f"/api/casussen/{casus.id}/issues/{vraag['id']}",
            json={"casus_id": str(geheim.id)},
        )
    assert resp.status_code == 404


async def test_initiatief_detail_toont_de_standaard_dod(client, initiatief):
    """De instellingen tonen de standaardlijst, ook zolang er geen eigen is."""
    resp = await client.get(f"/api/initiatieven/{initiatief.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["dod_items"] == []
    assert resp.json()["dod_standaard"] == list(DEFAULT_DOD)
