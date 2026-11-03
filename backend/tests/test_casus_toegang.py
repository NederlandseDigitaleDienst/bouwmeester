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
- Ook elders in Bouwmeester blijft een casustaak binnen het initiatief:
  zoeken, eenheidsoverzicht, persoonssamenvatting, mentions, de takenlijst
  van een node, de chat-tools en meldingen. Buiten het initiatief is het
  antwoord 404, ook als de taak een eenheid heeft die je niet ziet.
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
    init = Initiatief(
        id=uuid.uuid4(),
        naam="Regelrecht toegang",
        slug="rr-toegang",
        casussen_enabled=True,
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
        f"/api/tasks/{resp.json()['id']}",
        json={"casus_id": casus["id"], "node_id": None},
    )
    assert resp.status_code == 400
    assert "geen lid" in resp.json()["detail"]


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


# ---------------------------------------------------------------------------
# Elders in Bouwmeester: zoeken, overzichten, mentions, chat, meldingen
# ---------------------------------------------------------------------------
# Een casustaak heeft meestal geen eenheid. De org-scope laat zo'n taak voor
# iedereen door; deze plekken moeten dus zelf op de casus filteren.


@pytest.fixture
async def geheim(client, casus):
    """Een casustaak zonder eenheid en zonder uitvoerder."""
    resp = await client.post(
        "/api/tasks",
        json={"title": "Geheimtaak Zeldzaamwoord", "casus_id": casus["id"]},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["organisatie_eenheid_id"] is None
    return resp.json()


async def test_zoeken_vindt_casustaak_alleen_voor_leden(
    db_session, buitenstaander, lid, geheim
):
    params = {"q": "Zeldzaamwoord", "result_types": "task"}
    async with client_as(db_session, buitenstaander) as c:
        resp = await c.get("/api/search", params=params)
    assert resp.status_code == 200, resp.text
    assert geheim["id"] not in {r["id"] for r in resp.json()["results"]}

    async with client_as(db_session, lid) as c:
        resp = await c.get("/api/search", params=params)
    assert geheim["id"] in {r["id"] for r in resp.json()["results"]}


async def test_eenheidsoverzicht_toont_casustaak_alleen_aan_leden(
    db_session, buitenstaander, lid, werkeenheid, geheim
):
    # Het overzicht van een eenheid is er voor wie er geplaatst is.
    await place(db_session, buitenstaander, werkeenheid)
    await place(db_session, lid, werkeenheid)
    params = {"organisatie_eenheid_id": str(werkeenheid.id)}
    async with client_as(db_session, buitenstaander) as c:
        resp = await c.get("/api/tasks/eenheid-overview", params=params)
    assert resp.status_code == 200, resp.text
    zonder_eenheid = {t["id"] for t in resp.json()["unassigned_no_unit"]}
    assert geheim["id"] not in zonder_eenheid
    assert resp.json()["unassigned_no_unit_count"] == len(zonder_eenheid)

    async with client_as(db_session, lid) as c:
        resp = await c.get("/api/tasks/eenheid-overview", params=params)
    assert resp.status_code == 200, resp.text
    rij = next(t for t in resp.json()["unassigned_no_unit"] if t["id"] == geheim["id"])
    assert rij["casus"]["title"] == "Toegangscasus"


async def test_persoonssamenvatting_telt_casustaak_alleen_voor_leden(
    db_session, buitenstaander, lid, taak
):
    async with client_as(db_session, buitenstaander) as c:
        resp = await c.get(f"/api/people/{lid.id}/summary")
    assert resp.status_code == 200, resp.text
    assert resp.json()["open_task_count"] == 0
    assert taak["id"] not in {t["id"] for t in resp.json()["open_tasks"]}

    async with client_as(db_session, lid) as c:
        resp = await c.get(f"/api/people/{lid.id}/summary")
    assert resp.json()["open_task_count"] == 1
    assert taak["id"] in {t["id"] for t in resp.json()["open_tasks"]}


async def test_mentions_tonen_casustaak_alleen_aan_leden(
    client, db_session, buitenstaander, lid, casus, sample_node
):
    # Een casustaak die een node noemt: de node krijgt een terugverwijzing.
    resp = await client.post(
        "/api/tasks",
        json={
            "title": "Noemt de node Zeldzaamwoord",
            "casus_id": casus["id"],
            "description": f"Zie [#Test dossier](node:{sample_node.id})",
        },
    )
    assert resp.status_code == 201, resp.text
    tid = resp.json()["id"]

    zoek = {"q": "Zeldzaamwoord", "types": "task"}
    async with client_as(db_session, buitenstaander) as c:
        gevonden = await c.get("/api/mentions/search", params=zoek)
        refs = await c.get(f"/api/mentions/references/{sample_node.id}")
    assert gevonden.status_code == 200, gevonden.text
    assert tid not in {r["id"] for r in gevonden.json()}
    assert refs.status_code == 200, refs.text
    assert tid not in {r["source_id"] for r in refs.json()}

    async with client_as(db_session, lid) as c:
        gevonden = await c.get("/api/mentions/search", params=zoek)
        refs = await c.get(f"/api/mentions/references/{sample_node.id}")
    assert tid in {r["id"] for r in gevonden.json()}
    assert tid in {r["source_id"] for r in refs.json()}


async def test_taak_hangt_aan_node_of_casus_niet_aan_allebei(
    client, casus, taak, sample_node
):
    vraag = await client.post(
        f"/api/casussen/{casus['id']}/issues", json={"title": "V"}
    )
    for anker in [{"casus_id": casus["id"]}, {"issue_id": vraag.json()["id"]}]:
        resp = await client.post(
            "/api/tasks",
            json={"title": "Beide", "node_id": str(sample_node.id), **anker},
        )
        assert resp.status_code == 422, (anker, resp.text)
        assert "niet aan allebei" in resp.text

    # Een casustaak krijgt er geen node bij.
    resp = await client.put(
        f"/api/tasks/{taak['id']}", json={"node_id": str(sample_node.id)}
    )
    assert resp.status_code == 400
    assert "niet aan allebei" in resp.json()["detail"]

    # Een nodetaak gaat alleen een casus in als de node er tegelijk af gaat.
    node_taak = await client.post(
        "/api/tasks", json={"title": "Nodetaak", "node_id": str(sample_node.id)}
    )
    tid = node_taak.json()["id"]
    resp = await client.put(f"/api/tasks/{tid}", json={"casus_id": casus["id"]})
    assert resp.status_code == 400
    resp = await client.put(
        f"/api/tasks/{tid}", json={"casus_id": casus["id"], "node_id": None}
    )
    assert resp.status_code == 200, resp.text
    assert (resp.json()["casus_id"], resp.json()["node_id"]) == (casus["id"], None)

    # En zonder anker blijft niets over: ook dat geeft een nette 400.
    resp = await client.put(
        f"/api/tasks/{tid}", json={"casus_id": None, "issue_id": None}
    )
    assert resp.status_code == 400


async def test_takenlijst_van_node_toont_casustaak_alleen_aan_leden(
    db_session, buitenstaander, lid, casus, sample_node
):
    """Kan via de API niet meer ontstaan, maar mocht zo'n taak toch bestaan
    (een script, oude data), dan blijft ze binnen het initiatief."""
    from bouwmeester.models.task import Task

    taak = Task(
        title="Op node en casus",
        node_id=sample_node.id,
        casus_id=uuid.UUID(casus["id"]),
    )
    db_session.add(taak)
    await db_session.flush()
    tid = str(taak.id)
    async with client_as(db_session, buitenstaander) as c:
        resp = await c.get(f"/api/nodes/{sample_node.id}/tasks")
    assert resp.status_code == 200, resp.text
    assert tid not in {t["id"] for t in resp.json()}
    async with client_as(db_session, lid) as c:
        resp = await c.get(f"/api/nodes/{sample_node.id}/tasks")
    assert tid in {t["id"] for t in resp.json()}


async def test_casustaak_met_vreemde_eenheid_geeft_404_en_geen_403(
    client, db_session, buitenstaander, taak
):
    """Eerst de casus, dan de org-scope: een 403 zou verraden dat ze bestaat."""
    elders = await make_org(db_session, "Andere eenheid")
    resp = await client.put(
        f"/api/tasks/{taak['id']}",
        json={"organisatie_eenheid_id": str(elders.id)},
    )
    assert resp.status_code == 200, resp.text
    tid = taak["id"]
    async with client_as(db_session, buitenstaander) as c:
        assert (await c.get(f"/api/tasks/{tid}")).status_code == 404
        assert (await c.get(f"/api/tasks/{tid}/subtasks")).status_code == 404
        assert (
            await c.put(f"/api/tasks/{tid}", json={"title": "x"})
        ).status_code == 404
        assert (await c.delete(f"/api/tasks/{tid}")).status_code == 404


async def test_chat_wijzigt_geen_casustaak_buiten_het_initiatief(
    db_session, buitenstaander, taak, sample_node
):
    from sqlalchemy import func, select

    from bouwmeester.models.task import Task
    from bouwmeester.services.chat_service import _execute_write_tool

    result = await _execute_write_tool(
        "update_task",
        {"task_id": taak["id"], "title": "Overgenomen", "status": "done"},
        db_session,
        person_id=buitenstaander.id,
    )
    assert result["success"] is False
    # Een subtaak eronder hangen kan ook niet.
    result = await _execute_write_tool(
        "create_task",
        {
            "title": "Stiekem",
            "node_id": str(sample_node.id),
            "parent_task_id": taak["id"],
        },
        db_session,
        person_id=buitenstaander.id,
    )
    assert result["success"] is False

    db_session.expire_all()
    task = await db_session.get(Task, uuid.UUID(taak["id"]))
    assert (task.title, task.status) == ("Casustaak", "open")
    onder = await db_session.scalar(
        select(func.count()).select_from(Task).where(Task.parent_id == task.id)
    )
    assert onder == 0


async def test_chat_hangt_ook_voor_een_lid_niets_onder_een_casustaak(
    db_session, lid, taak, sample_node
):
    from bouwmeester.services.chat_service import _execute_write_tool

    result = await _execute_write_tool(
        "create_task",
        {
            "title": "Subtaak",
            "node_id": str(sample_node.id),
            "parent_task_id": taak["id"],
        },
        db_session,
        person_id=lid.id,
    )
    assert result["success"] is False


async def test_chat_status_van_taak_werkt_de_vraag_bij(client, db_session, lid, casus):
    """Zoals PUT /api/tasks/{id}: de onderzoeksvraag volgt haar taken."""
    from bouwmeester.services.chat_service import _execute_write_tool

    cid = casus["id"]
    vraag = (
        await client.post(f"/api/casussen/{cid}/issues", json={"title": "V"})
    ).json()
    taak = (
        await client.post("/api/tasks", json={"title": "T", "issue_id": vraag["id"]})
    ).json()

    result = await _execute_write_tool(
        "update_task",
        {"task_id": taak["id"], "status": "in_progress"},
        db_session,
        person_id=lid.id,
    )
    assert result["success"] is True, result
    vragen = (await client.get(f"/api/casussen/{cid}/issues")).json()
    assert next(v for v in vragen if v["id"] == vraag["id"])["status"] == "in_progress"


async def test_chat_activiteit_vraagt_audit_recht(db_session, buitenstaander, lid):
    """Zelfde recht als /api/activity/feed; het log noemt casus- en vraagtitels."""
    import json

    from bouwmeester.services.chat_service import _execute_read_tool

    for persoon in (buitenstaander, lid):
        result = json.loads(
            await _execute_read_tool(
                "get_recent_activity", {}, db_session, person_id=persoon.id
            )
        )
        assert "error" in result
        assert "activities" not in result


async def test_meldingen_over_casustaak_alleen_voor_leden(
    client, db_session, buitenstaander, lid, casus
):
    """Teammanager en @-vermelding: geen titel naar wie de casus niet ziet."""
    from sqlalchemy import select

    from bouwmeester.models.notification import Notification

    eenheid = await make_org(db_session, "Eenheid met manager")
    await grant_role(db_session, buitenstaander, "unit_manager", eenheid)
    noemt = (
        f"Vraag aan [@Buitenstaander](user:{buitenstaander.id}) "
        f"en [@Teamlid](user:{lid.id})"
    )
    resp = await client.post(
        "/api/tasks",
        json={
            "title": "Met eenheid",
            "casus_id": casus["id"],
            "organisatie_eenheid_id": str(eenheid.id),
            "description": noemt,
        },
    )
    assert resp.status_code == 201, resp.text
    tid = uuid.UUID(resp.json()["id"])
    # Een opmerking op de taak met dezelfde vermeldingen.
    resp = await client.post(f"/api/tasks/{tid}/comments", json={"content": noemt})
    assert resp.status_code == 201, resp.text

    async def meldingen(persoon):
        rows = await db_session.execute(
            select(Notification).where(Notification.person_id == persoon.id)
        )
        return [n for n in rows.scalars().all() if n.related_task_id == tid]

    assert await meldingen(buitenstaander) == []
    assert await meldingen(lid) != []
