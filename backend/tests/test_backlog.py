"""Backlog van een initiatief: alle issues van alle casussen, met hun taken.

Dekt ook de zichtbaarheid: de backlog en de takenlijst per casus geven 404
buiten de initiatieven die iemand kan zien, net als de casus zelf.
"""

import uuid

import pytest

from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.repositories.lead_column import LeadColumnRepository
from tests.factories import START_INTERN, client_as, make_person

START = START_INTERN
BACKLOG = "/api/casussen/backlog"


@pytest.fixture
async def initiatief(db_session):
    init = Initiatief(id=uuid.uuid4(), naam="Regelrecht backlog", slug="rr-backlog")
    db_session.add(init)
    await db_session.flush()
    await LeadColumnRepository(db_session).seed_defaults(init.id)
    return init


async def _casus(client, db_session, initiatief, title):
    lead = Lead(
        id=uuid.uuid4(),
        title=title,
        stage="in_the_pocket",
        initiatief_id=initiatief.id,
    )
    db_session.add(lead)
    await db_session.flush()
    resp = await client.post(
        "/api/casussen", json={"lead_id": str(lead.id), "startvoorwaarden": START}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _post(client, url, **json):
    resp = await client.post(url, json=json)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def gevuld(client, db_session, initiatief):
    """Alfa: twee issues met elk een taak, en een losse taak. Beta: alleen een
    losse taak."""
    a = await _casus(client, db_session, initiatief, "Alfa")
    b = await _casus(client, db_session, initiatief, "Beta")
    vraag = await _post(client, f"/api/casussen/{a}/issues", title="Werkt het?")
    tech = await _post(client, f"/api/casussen/{a}/issues", title="Dataset")
    await _post(client, "/api/tasks", title="Taak op vraag", issue_id=vraag["id"])
    await _post(
        client, "/api/tasks", title="Taak op issue", issue_id=tech["id"], status="done"
    )
    await _post(client, "/api/tasks", title="Losse taak alfa", casus_id=a)
    await _post(client, "/api/tasks", title="Losse taak beta", casus_id=b)
    return {"a": a, "b": b, "vraag_id": vraag["id"], "tech_id": tech["id"]}


async def test_backlog_lists_issues_with_tasks(client, initiatief, gevuld):
    resp = await client.get(BACKLOG, params={"initiatief_id": str(initiatief.id)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    issues = {i["title"]: i for i in body["issues"]}
    assert set(issues) == {"Werkt het?", "Dataset"}

    vraag = issues["Werkt het?"]
    assert vraag["casus"]["title"] == "Alfa"
    assert [t["title"] for t in vraag["tasks"]] == ["Taak op vraag"]

    tech = issues["Dataset"]
    assert [t["title"] for t in tech["tasks"]] == ["Taak op issue"]
    assert tech["tasks"][0]["status"] == "done"

    los = {t["title"]: t for t in body["losse_taken"]}
    assert set(los) == {"Losse taak alfa", "Losse taak beta"}
    assert los["Losse taak beta"]["casus"]["title"] == "Beta"


async def test_backlog_comment_count_per_card(client, initiatief, gevuld):
    """Een kaartje toont hoeveel opmerkingen de taak heeft."""
    params = {"initiatief_id": str(initiatief.id)}
    body = (await client.get(BACKLOG, params=params)).json()
    issues = {i["title"]: i for i in body["issues"]}
    taak = issues["Werkt het?"]["tasks"][0]
    los = next(t for t in body["losse_taken"] if t["title"] == "Losse taak alfa")
    assert taak["comment_count"] == 0
    for tekst in ("Eerste", "Tweede"):
        await _post(client, f"/api/tasks/{taak['id']}/comments", content=tekst)
    await _post(client, f"/api/tasks/{los['id']}/comments", content="Los")

    body = (await client.get(BACKLOG, params=params)).json()
    issues = {i["title"]: i for i in body["issues"]}
    assert issues["Werkt het?"]["tasks"][0]["comment_count"] == 2
    assert issues["Dataset"]["tasks"][0]["comment_count"] == 0
    losse = {t["title"]: t for t in body["losse_taken"]}
    assert losse["Losse taak alfa"]["comment_count"] == 1


async def test_backlog_only_this_initiatief(client, db_session, initiatief, gevuld):
    other = Initiatief(id=uuid.uuid4(), naam="Ander", slug="ander-backlog")
    db_session.add(other)
    await db_session.flush()
    await LeadColumnRepository(db_session).seed_defaults(other.id)
    gamma = await _casus(client, db_session, other, "Gamma")
    await _post(client, f"/api/casussen/{gamma}/issues", title="Issue gamma")
    await _post(client, "/api/tasks", title="Taak gamma", casus_id=gamma)
    resp = await client.get(BACKLOG, params={"initiatief_id": str(initiatief.id)})
    assert "Issue gamma" not in {i["title"] for i in resp.json()["issues"]}
    assert "Taak gamma" not in {t["title"] for t in resp.json()["losse_taken"]}


async def test_backlog_requires_initiatief_id(client):
    resp = await client.get(BACKLOG)
    assert resp.status_code == 422


async def test_backlog_invisible_initiatief_is_404(db_session, initiatief, gevuld):
    buitenstaander = await make_person(db_session, "Buitenstaander")
    async with client_as(db_session, buitenstaander) as c:
        resp = await c.get(BACKLOG, params={"initiatief_id": str(initiatief.id)})
    assert resp.status_code == 404


async def test_backlog_visible_for_member(db_session, initiatief, gevuld):
    lid = await make_person(db_session, "Teamlid")
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
        resp = await c.get(BACKLOG, params={"initiatief_id": str(initiatief.id)})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["issues"]) == 2
    assert len(resp.json()["losse_taken"]) == 2


async def test_tasks_by_casus_invisible_is_404(db_session, gevuld):
    """De takenlijst per casus lekt niets buiten het zichtbare initiatief."""
    buitenstaander = await make_person(db_session, "Buitenstaander")
    async with client_as(db_session, buitenstaander) as c:
        resp = await c.get("/api/tasks", params={"casus_id": gevuld["a"]})
    assert resp.status_code == 404


async def test_tasks_by_unknown_casus_is_empty(client):
    resp = await client.get("/api/tasks", params={"casus_id": str(uuid.uuid4())})
    assert resp.status_code == 200
    assert resp.json() == []
