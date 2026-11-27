"""Rollen in een initiatief en het werk per persoon.

Dekt:
- rollen staan per initiatief aan of uit; uit is 404, ook voor de lijst;
- de ankercirkel: één per initiatief, met doel en focus, en elke rol erin;
- beheren kan een bijdrager of eigenaar, een kijker krijgt 403 en wie het
  initiatief niet ziet 404;
- naam is uniek per initiatief (hoofdletters tellen niet), lege en dubbele
  regels vallen weg, null wist doel en vervuller;
- status: concept, open, belegd; toewijzen maakt belegd, opnieuw toewijzen
  maakt open met een nieuwe ronde interesse;
- interesse alleen bij een open rol, ook voor een ander, met wie het
  vastlegde; vervuller en wie interesse heeft moeten lid zijn (anders 400);
- raakvlakken tussen twee rollen, één keer per paar, zichtbaar bij allebei;
- persoonlijke focus en het werk per persoon, alleen binnen dit initiatief;
- export en import, ook naar een ander initiatief.
"""

import uuid

import pytest
from sqlalchemy import delete as sa_delete

from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.repositories.lead_column import LeadColumnRepository
from tests.factories import START_INTERN, client_as, make_person


async def _initiatief(db_session, naam, **extra):
    init = Initiatief(
        id=uuid.uuid4(),
        naam=naam,
        slug=f"rol-{uuid.uuid4().hex[:8]}",
        **{"rollen_enabled": True, "casussen_enabled": True, **extra},
    )
    db_session.add(init)
    await db_session.flush()
    await LeadColumnRepository(db_session).seed_defaults(init.id)
    return init


@pytest.fixture
async def initiatief(db_session):
    return await _initiatief(db_session, "Regelrecht rollen")


async def _lid(db_session, initiatief_id, person_id, rol="contributor"):
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
async def teamlid(db_session, initiatief):
    p = await make_person(db_session, "Teamlid Ünal")
    await _lid(db_session, initiatief.id, p.id)
    return p


def _url(initiatief, *rest):
    return "/".join([f"/api/initiatieven/{initiatief.id}/rollen", *rest])


async def _rol(client, initiatief, naam="Spelverdeler", **extra):
    resp = await client.post(_url(initiatief), json={"naam": naam, **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Aan en uit, en de cirkel
# ---------------------------------------------------------------------------


async def test_rollen_uit_is_404(client, db_session):
    init = await _initiatief(db_session, "Zonder rollen", rollen_enabled=False)
    assert (await client.get(_url(init))).status_code == 404
    assert (await client.post(_url(init), json={"naam": "X"})).status_code == 404
    assert (await client.get(f"/api/initiatieven/{init.id}/cirkel")).status_code == 404


async def test_rollen_aanzetten_via_instellingen(client, db_session):
    init = await _initiatief(db_session, "Later aan", rollen_enabled=False)
    resp = await client.put(
        f"/api/initiatieven/{init.id}/settings", json={"rollen_enabled": True}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rollen_enabled"] is True
    resp = await client.get(_url(init))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_ankercirkel_met_doel_en_focus(client, initiatief):
    url = f"/api/initiatieven/{initiatief.id}/cirkel"
    cirkel = (await client.get(url)).json()
    assert cirkel["naam"] == "Regelrecht rollen"
    assert cirkel["parent_id"] is None
    # Nog eens ophalen geeft dezelfde cirkel, geen tweede.
    assert (await client.get(url)).json()["id"] == cirkel["id"]

    resp = await client.put(
        url, json={"doel": "Wetgeving uitvoerbaar", "focus": ["Napp", " ", "Napp"]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["focus"] == ["Napp"]
    rol = await _rol(client, initiatief)
    assert rol["cirkel_id"] == cirkel["id"]


# ---------------------------------------------------------------------------
# Beheren
# ---------------------------------------------------------------------------


async def test_rol_aanmaken_met_lijsten(client, initiatief, teamlid):
    rol = await _rol(
        client,
        initiatief,
        naam="  Aanjager ritme & werkafspraken ",
        doel="Een helder ritme, door het team zelf vormgegeven",
        aanspreekbaar_op=["Rituelen ingepland", " ", "Rituelen ingepland", "Demo's"],
        domein=["De teamagenda"],
    )
    assert rol["naam"] == "Aanjager ritme & werkafspraken"
    assert rol["aanspreekbaar_op"] == ["Rituelen ingepland", "Demo's"]
    assert rol["domein"] == ["De teamagenda"]
    assert rol["status"] == "concept"
    assert rol["ronde"] == 1


async def test_naam_is_uniek_zonder_hoofdletters(client, initiatief):
    await _rol(client, initiatief, naam="Spelverdeler")
    resp = await client.post(_url(initiatief), json={"naam": "spelverdeler"})
    assert resp.status_code == 409
    assert (await client.post(_url(initiatief), json={"naam": "  "})).status_code == 422


async def test_zelfde_naam_in_ander_initiatief_mag(client, db_session, initiatief):
    ander = await _initiatief(db_session, "Ander")
    await _rol(client, initiatief, naam="Spelverdeler")
    await _rol(client, ander, naam="Spelverdeler")


async def test_wijzigen_wist_alleen_wat_null_is(client, initiatief):
    rol = await _rol(client, initiatief, doel="Oud doel", domein=["Teamsamenstelling"])
    resp = await client.put(
        _url(initiatief, rol["id"]), json={"doel": None, "feedback": "Opsplitsen?"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["doel"] is None
    assert body["domein"] == ["Teamsamenstelling"]
    assert body["feedback"] == "Opsplitsen?"
    assert body["naam"] == "Spelverdeler"


async def test_hernoemen_naar_bestaande_naam_is_409(client, initiatief):
    await _rol(client, initiatief, naam="A")
    b = await _rol(client, initiatief, naam="B")
    resp = await client.put(_url(initiatief, b["id"]), json={"naam": "a"})
    assert resp.status_code == 409


async def test_verwijderen(client, initiatief):
    rol = await _rol(client, initiatief)
    assert (await client.delete(_url(initiatief, rol["id"]))).status_code == 204
    assert (await client.get(_url(initiatief))).json() == []
    assert (await client.delete(_url(initiatief, rol["id"]))).status_code == 404


async def test_rol_van_ander_initiatief_is_404(client, db_session, initiatief):
    ander = await _initiatief(db_session, "Ander initiatief")
    rol = await _rol(client, ander)
    resp = await client.put(_url(initiatief, rol["id"]), json={"naam": "Weg"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Status en toewijzen
# ---------------------------------------------------------------------------


async def test_van_concept_naar_belegd_en_weer_open(client, initiatief, teamlid):
    rol = await _rol(client, initiatief)
    url = _url(initiatief, rol["id"])

    rol = (await client.put(url, json={"status": "open"})).json()
    assert rol["status"] == "open"

    await client.put(
        _url(initiatief, rol["id"], "interesse", str(teamlid.id)),
        json={"invulling": "Vanaf januari"},
    )
    rol = (await client.put(url, json={"vervuller_id": str(teamlid.id)})).json()
    assert rol["status"] == "belegd"
    assert rol["vervuller"]["id"] == str(teamlid.id)
    # Na toewijzen is de interesse van die ronde iets van eerder.
    assert rol["interesse"] == []
    assert [i["person"]["id"] for i in rol["eerdere_interesse"]] == [str(teamlid.id)]

    # Opnieuw toewijzen: eerst terug naar open, vervuller eraf, nieuwe ronde.
    rol = (await client.put(url, json={"status": "open"})).json()
    assert rol["status"] == "open"
    assert rol["vervuller"] is None
    assert rol["ronde"] == 2
    assert rol["interesse"] == []
    assert len(rol["eerdere_interesse"]) == 1


async def test_vervuller_weghalen_is_opnieuw_toewijzen(client, initiatief, teamlid):
    rol = await _rol(client, initiatief, vervuller_id=str(teamlid.id))
    assert rol["status"] == "belegd"
    rol = (
        await client.put(_url(initiatief, rol["id"]), json={"vervuller_id": None})
    ).json()
    assert rol["status"] == "open"
    assert rol["ronde"] == 2


async def test_belegde_rol_kan_niet_terug_naar_concept(client, initiatief, teamlid):
    rol = await _rol(client, initiatief, vervuller_id=str(teamlid.id))
    resp = await client.put(_url(initiatief, rol["id"]), json={"status": "concept"})
    assert resp.status_code == 400


async def test_vervuller_moet_lid_zijn(client, db_session, initiatief):
    vreemde = await make_person(db_session, "Vreemde")
    resp = await client.post(
        _url(initiatief), json={"naam": "X", "vervuller_id": str(vreemde.id)}
    )
    assert resp.status_code == 400
    rol = await _rol(client, initiatief)
    resp = await client.put(
        _url(initiatief, rol["id"]), json={"vervuller_id": str(vreemde.id)}
    )
    assert resp.status_code == 400


async def test_vervuller_zonder_toegang_meldt_de_rol(
    client, db_session, initiatief, teamlid
):
    await _rol(client, initiatief, vervuller_id=str(teamlid.id))
    await db_session.execute(
        sa_delete(ResourcePermission).where(
            ResourcePermission.resource_type == "initiatief",
            ResourcePermission.person_id == teamlid.id,
        )
    )
    await db_session.flush()
    rol = (await client.get(_url(initiatief))).json()[0]
    assert rol["vervuller"]["id"] == str(teamlid.id)
    assert rol["vervuller_is_lid"] is False


# ---------------------------------------------------------------------------
# Wie mag wat
# ---------------------------------------------------------------------------


async def test_bijdrager_beheert(db_session, initiatief, teamlid):
    async with client_as(db_session, teamlid) as c:
        resp = await c.post(_url(initiatief), json={"naam": "Hoeder"})
        assert resp.status_code == 201, resp.text
        rol_id = resp.json()["id"]
        assert (
            await c.put(_url(initiatief, rol_id), json={"doel": "Doel"})
        ).status_code == 200


async def test_kijker_ziet_maar_beheert_niet(client, db_session, initiatief):
    rol = await _rol(client, initiatief, status="open")
    kijker = await make_person(db_session, "Kijker")
    await _lid(db_session, initiatief.id, kijker.id, rol="viewer")
    async with client_as(db_session, kijker) as c:
        assert (await c.get(_url(initiatief))).status_code == 200
        assert (
            await c.get(f"/api/initiatieven/{initiatief.id}/cirkel")
        ).status_code == 200
        assert (await c.post(_url(initiatief), json={"naam": "X"})).status_code == 403
        assert (
            await c.put(_url(initiatief, rol["id"]), json={"doel": "X"})
        ).status_code == 403
        assert (await c.delete(_url(initiatief, rol["id"]))).status_code == 403
        assert (
            await c.put(
                _url(initiatief, rol["id"], "interesse", str(kijker.id)), json={}
            )
        ).status_code == 403
        assert (
            await c.put(f"/api/initiatieven/{initiatief.id}/cirkel", json={"doel": "X"})
        ).status_code == 403


async def test_buitenstaander_krijgt_404(client, db_session, initiatief):
    rol = await _rol(client, initiatief)
    vreemde = await make_person(db_session, "Vreemde")
    async with client_as(db_session, vreemde) as c:
        assert (await c.get(_url(initiatief))).status_code == 404
        assert (await c.post(_url(initiatief), json={"naam": "X"})).status_code == 404
        assert (await c.delete(_url(initiatief, rol["id"]))).status_code == 404
        assert (await c.get(_url(initiatief, "export"))).status_code == 404


# ---------------------------------------------------------------------------
# Interesse
# ---------------------------------------------------------------------------


async def test_interesse_voor_een_ander(db_session, initiatief, teamlid):
    trekker = await make_person(db_session, "Trekker")
    await _lid(db_session, initiatief.id, trekker.id)
    async with client_as(db_session, trekker) as c:
        rol = (
            await c.post(
                _url(initiatief), json={"naam": "Spelverdeler", "status": "open"}
            )
        ).json()
        url = _url(initiatief, rol["id"], "interesse", str(teamlid.id))
        resp = await c.put(url, json={"invulling": "Zei het in de retro"})
        assert resp.status_code == 200, resp.text
        [i] = resp.json()["interesse"]
        assert i["person"]["id"] == str(teamlid.id)
        assert i["invulling"] == "Zei het in de retro"
        assert i["vastgelegd_door"]["id"] == str(trekker.id)

        # Nog eens zetten werkt bij, er komt geen tweede rij.
        resp = await c.put(url, json={"invulling": "Vanaf januari"})
        [i] = resp.json()["interesse"]
        assert i["invulling"] == "Vanaf januari"

        resp = await c.delete(url)
        assert resp.status_code == 200
        assert resp.json()["interesse"] == []
        assert (await c.delete(url)).status_code == 404


async def test_interesse_alleen_bij_open_rol(client, initiatief, teamlid):
    rol = await _rol(client, initiatief)
    url = _url(initiatief, rol["id"], "interesse", str(teamlid.id))
    assert (await client.put(url, json={})).status_code == 400
    await client.put(
        _url(initiatief, rol["id"]), json={"vervuller_id": str(teamlid.id)}
    )
    assert (await client.put(url, json={})).status_code == 400


async def test_interesse_moet_lid_zijn(client, db_session, initiatief):
    rol = await _rol(client, initiatief, status="open")
    vreemde = await make_person(db_session, "Vreemde")
    resp = await client.put(
        _url(initiatief, rol["id"], "interesse", str(vreemde.id)), json={}
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Raakvlakken
# ---------------------------------------------------------------------------


async def test_raakvlak_staat_bij_allebei(client, initiatief):
    spel = await _rol(client, initiatief, naam="Spelverdeler")
    punt = await _rol(client, initiatief, naam="Aanspreekpunt casus")
    resp = await client.post(
        _url(initiatief, spel["id"], "raakvlakken"),
        json={"rol_id": punt["id"], "omschrijving": "Belang per casus, inzet"},
    )
    assert resp.status_code == 201, resp.text
    rollen = {r["naam"]: r for r in (await client.get(_url(initiatief))).json()}
    [a] = rollen["Spelverdeler"]["raakvlakken"]
    [b] = rollen["Aanspreekpunt casus"]["raakvlakken"]
    assert a["id"] == b["id"]
    assert a["rol"]["naam"] == "Aanspreekpunt casus"
    assert b["rol"]["naam"] == "Spelverdeler"
    assert b["omschrijving"] == "Belang per casus, inzet"

    # Andersom is hetzelfde paar.
    resp = await client.post(
        _url(initiatief, punt["id"], "raakvlakken"), json={"rol_id": spel["id"]}
    )
    assert resp.status_code == 409

    url = f"/api/initiatieven/{initiatief.id}/raakvlakken/{a['id']}"
    resp = await client.put(url, json={"omschrijving": "Anders"})
    assert resp.status_code == 200
    assert (await client.delete(url)).status_code == 204
    rollen = (await client.get(_url(initiatief))).json()
    assert all(r["raakvlakken"] == [] for r in rollen)


async def test_raakvlak_met_zichzelf_of_elders_mag_niet(client, db_session, initiatief):
    spel = await _rol(client, initiatief)
    resp = await client.post(
        _url(initiatief, spel["id"], "raakvlakken"), json={"rol_id": spel["id"]}
    )
    assert resp.status_code == 400
    ander = await _initiatief(db_session, "Elders")
    vreemd = await _rol(client, ander, naam="Vreemd")
    resp = await client.post(
        _url(initiatief, spel["id"], "raakvlakken"), json={"rol_id": vreemd["id"]}
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Werk en focus per persoon
# ---------------------------------------------------------------------------


async def _casus(client, db_session, initiatief, title):
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


async def test_werk_van_persoon(client, db_session, initiatief, teamlid):
    rol = await _rol(client, initiatief, vervuller_id=str(teamlid.id))
    open_rol = await _rol(client, initiatief, naam="Hoeder", status="open")
    await client.put(
        _url(initiatief, open_rol["id"], "interesse", str(teamlid.id)),
        json={"invulling": "Denkt mee"},
    )
    db_session.add(
        Lead(
            id=uuid.uuid4(),
            title="Napp",
            stage="verkennen",
            initiatief_id=initiatief.id,
            assignee_id=teamlid.id,
            brought_by_id=teamlid.id,
        )
    )
    casus = await _casus(client, db_session, initiatief, "Referentiecasus")
    resp = await client.post(
        f"/api/casussen/{casus['id']}/team",
        json={"person_id": str(teamlid.id), "rol": "teamlid"},
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        f"/api/casussen/{casus['id']}/issues",
        json={"title": "Welke bronnen?", "assignee_id": str(teamlid.id)},
    )
    assert resp.status_code == 201, resp.text
    for title, status in (("Open taak", None), ("Afgerond", "done")):
        resp = await client.post(
            "/api/tasks",
            json={
                "title": title,
                "casus_id": casus["id"],
                "assignee_id": str(teamlid.id),
            },
        )
        assert resp.status_code == 201, resp.text
        if status:
            await client.put(f"/api/tasks/{resp.json()['id']}", json={"status": status})

    # Werk in een ander initiatief telt niet mee.
    ander_init = await _initiatief(db_session, "Elders")
    await _lid(db_session, ander_init.id, teamlid.id)
    andere_casus = await _casus(client, db_session, ander_init, "Elders")
    await client.post(
        "/api/tasks",
        json={
            "title": "Taak elders",
            "casus_id": andere_casus["id"],
            "assignee_id": str(teamlid.id),
        },
    )

    focus_url = f"/api/initiatieven/{initiatief.id}/personen/{teamlid.id}/focus"
    resp = await client.put(focus_url, json={"focus": ["Napp afronden", "Werving"]})
    assert resp.status_code == 200, resp.text

    resp = await client.get(
        f"/api/initiatieven/{initiatief.id}/personen/{teamlid.id}/werk"
    )
    assert resp.status_code == 200, resp.text
    werk = resp.json()
    assert werk["is_lid"] is True
    assert werk["focus"] == ["Napp afronden", "Werving"]
    assert [r["id"] for r in werk["rollen"]] == [rol["id"]]
    assert [(i["rol_naam"], i["invulling"]) for i in werk["interesse"]] == [
        ("Hoeder", "Denkt mee")
    ]
    assert [(lead["title"], lead["als"]) for lead in werk["leads"]] == [
        ("Napp", ["eigenaar", "aanbrenger"])
    ]
    assert [(c["title"], c["rol"]) for c in werk["casussen"]] == [
        ("Referentiecasus", "teamlid")
    ]
    assert [i["title"] for i in werk["issues"]] == ["Welke bronnen?"]
    assert [t["title"] for t in werk["open_taken"]] == ["Open taak"]


async def test_focus_alleen_voor_leden_en_bijdragers(client, db_session, initiatief):
    vreemde = await make_person(db_session, "Vreemde")
    resp = await client.put(
        f"/api/initiatieven/{initiatief.id}/personen/{vreemde.id}/focus",
        json={"focus": ["X"]},
    )
    assert resp.status_code == 400
    kijker = await make_person(db_session, "Kijker")
    await _lid(db_session, initiatief.id, kijker.id, rol="viewer")
    async with client_as(db_session, kijker) as c:
        resp = await c.put(
            f"/api/initiatieven/{initiatief.id}/personen/{kijker.id}/focus",
            json={"focus": ["X"]},
        )
        assert resp.status_code == 403


async def test_werk_zonder_rollen_aan(client, db_session, teamlid):
    init = await _initiatief(db_session, "Zonder rollen", rollen_enabled=False)
    await _lid(db_session, init.id, teamlid.id)
    resp = await client.get(f"/api/initiatieven/{init.id}/personen/{teamlid.id}/werk")
    assert resp.status_code == 200
    assert resp.json()["rollen"] == []


async def test_werk_van_onbekende_persoon_is_404(client, initiatief):
    resp = await client.get(
        f"/api/initiatieven/{initiatief.id}/personen/{uuid.uuid4()}/werk"
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Export en import
# ---------------------------------------------------------------------------


async def test_export_en_import_in_ander_initiatief(
    client, db_session, initiatief, teamlid
):
    await client.put(
        f"/api/initiatieven/{initiatief.id}/cirkel",
        json={"doel": "Uitvoerbare wetgeving", "focus": ["Napp"]},
    )
    spel = await _rol(
        client, initiatief, naam="Spelverdeler", vervuller_id=str(teamlid.id)
    )
    punt = await _rol(client, initiatief, naam="Aanspreekpunt casus", status="open")
    await client.post(
        _url(initiatief, spel["id"], "raakvlakken"),
        json={"rol_id": punt["id"], "omschrijving": "Belang en inzet"},
    )

    export = (await client.get(_url(initiatief, "export"))).json()
    assert export["versie"] == 1
    assert export["cirkel"]["focus"] == ["Napp"]
    namen = {r["naam"]: r for r in export["rollen"]}
    assert namen["Spelverdeler"]["vervuller_email"] == teamlid.email
    assert namen["Spelverdeler"]["status"] == "belegd"
    assert export["raakvlakken"] == [
        {
            "rol_a": "Aanspreekpunt casus",
            "rol_b": "Spelverdeler",
            "omschrijving": "Belang en inzet",
        }
    ] or export["raakvlakken"] == [
        {
            "rol_a": "Spelverdeler",
            "rol_b": "Aanspreekpunt casus",
            "omschrijving": "Belang en inzet",
        }
    ]

    # In een ander initiatief is de vervuller geen lid: de rol komt open.
    ander = await _initiatief(db_session, "Kopie")
    resp = await client.post(_url(ander, "import"), json=export)
    assert resp.status_code == 200, resp.text
    uit = resp.json()
    assert (uit["aangemaakt"], uit["bijgewerkt"], uit["raakvlakken"]) == (2, 0, 1)
    assert any("Spelverdeler" in m for m in uit["meldingen"])
    rollen = {r["naam"]: r for r in (await client.get(_url(ander))).json()}
    assert rollen["Spelverdeler"]["status"] == "open"
    assert rollen["Spelverdeler"]["vervuller"] is None
    assert (await client.get(f"/api/initiatieven/{ander.id}/cirkel")).json()[
        "focus"
    ] == ["Napp"]

    # Nog eens importeren werkt bij en maakt niets dubbel.
    uit = (await client.post(_url(ander, "import"), json=export)).json()
    assert (uit["aangemaakt"], uit["bijgewerkt"], uit["raakvlakken"]) == (0, 2, 0)
    assert len((await client.get(_url(ander))).json()) == 2


async def test_import_met_onbekende_rol_in_raakvlak(client, initiatief):
    resp = await client.post(
        _url(initiatief, "import"),
        json={
            "versie": 1,
            "rollen": [{"naam": "Één rol", "doel": 'Met "aanhalingstekens"'}],
            "raakvlakken": [{"rol_a": "Één rol", "rol_b": "Bestaat niet"}],
        },
    )
    assert resp.status_code == 200, resp.text
    uit = resp.json()
    assert uit["aangemaakt"] == 1
    assert uit["raakvlakken"] == 0
    assert any("Bestaat niet" in m for m in uit["meldingen"])
    [rol] = (await client.get(_url(initiatief))).json()
    assert rol["doel"] == 'Met "aanhalingstekens"'


async def test_import_vraagt_bijdrager(client, db_session, initiatief):
    kijker = await make_person(db_session, "Kijker")
    await _lid(db_session, initiatief.id, kijker.id, rol="viewer")
    async with client_as(db_session, kijker) as c:
        assert (await c.get(_url(initiatief, "export"))).status_code == 200
        resp = await c.post(_url(initiatief, "import"), json={"versie": 1})
        assert resp.status_code == 403


async def test_interesse_opnieuw_vastleggen_houdt_invulling(
    db_session, initiatief, teamlid
):
    trekker = await make_person(db_session, "Trekker")
    await _lid(db_session, initiatief.id, trekker.id)
    async with client_as(db_session, teamlid) as c:
        rol = (
            await c.post(_url(initiatief), json={"naam": "Hoeder", "status": "open"})
        ).json()
        url = _url(initiatief, rol["id"], "interesse", str(teamlid.id))
        await c.put(url, json={"invulling": "Vanaf januari"})
    async with client_as(db_session, trekker) as c:
        [i] = (await c.put(url, json={})).json()["interesse"]
    assert i["invulling"] == "Vanaf januari"
    assert i["vastgelegd_door"]["id"] == str(trekker.id)


async def test_naam_uniek_ook_in_de_database(db_session, initiatief):
    from bouwmeester.models.initiatief_rol import InitiatiefRol
    from bouwmeester.repositories.initiatief_rol import InitiatiefRolRepository

    cirkel = await InitiatiefRolRepository(db_session).ankercirkel(initiatief)
    db_session.add(
        InitiatiefRol(initiatief_id=initiatief.id, cirkel_id=cirkel.id, naam="Case")
    )
    await db_session.flush()
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                InitiatiefRol(
                    initiatief_id=initiatief.id, cirkel_id=cirkel.id, naam="CASE"
                )
            )
            await db_session.flush()


# ---------------------------------------------------------------------------
# Uit de review
# ---------------------------------------------------------------------------


async def test_import_zoekt_vervuller_op_persoonsmail(
    client, db_session, initiatief, teamlid
):
    # Het oude vrije veld telt niet; het adres in PersonEmail wel, zonder hoofdletters.
    teamlid.email = None
    await db_session.flush()
    from sqlalchemy import select

    from bouwmeester.models.person_email import PersonEmail

    adres = (
        await db_session.execute(
            select(PersonEmail.email).where(PersonEmail.person_id == teamlid.id)
        )
    ).scalar_one()
    resp = await client.post(
        _url(initiatief, "import"),
        json={"rollen": [{"naam": "Spelverdeler", "vervuller_email": adres.upper()}]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["meldingen"] == []
    [rol] = (await client.get(_url(initiatief))).json()
    assert rol["vervuller"]["id"] == str(teamlid.id)
    export = (await client.get(_url(initiatief, "export"))).json()
    assert export["rollen"][0]["vervuller_email"] == adres


async def test_import_volgt_de_regels_van_toewijzen(client, initiatief, teamlid):
    rol = await _rol(client, initiatief, status="open")
    await client.put(_url(initiatief, rol["id"], "interesse", str(teamlid.id)), json={})
    await client.put(
        _url(initiatief, rol["id"]), json={"vervuller_id": str(teamlid.id)}
    )

    # Zonder vervuller in het bestand: opnieuw toewijzen, nieuwe ronde.
    uit = (
        await client.post(
            _url(initiatief, "import"),
            json={"rollen": [{"naam": "Spelverdeler", "status": "concept"}]},
        )
    ).json()
    assert uit["bijgewerkt"] == 1
    [rol] = (await client.get(_url(initiatief))).json()
    assert rol["status"] == "open"
    assert rol["ronde"] == 2
    assert rol["interesse"] == []
    # Opnieuw interesse in de nieuwe ronde kan gewoon.
    resp = await client.put(
        _url(initiatief, rol["id"], "interesse", str(teamlid.id)), json={}
    )
    assert resp.status_code == 200, resp.text


async def test_import_zonder_cirkel_laat_cirkel_staan(client, initiatief):
    url = f"/api/initiatieven/{initiatief.id}/cirkel"
    await client.put(url, json={"doel": "Blijft", "focus": ["Napp"]})
    await client.post(_url(initiatief, "import"), json={"rollen": [{"naam": "X"}]})
    cirkel = (await client.get(url)).json()
    assert (cirkel["doel"], cirkel["focus"]) == ("Blijft", ["Napp"])


async def test_cirkel_volgt_de_naam_van_het_initiatief(client, initiatief):
    url = f"/api/initiatieven/{initiatief.id}/cirkel"
    await client.get(url)
    resp = await client.put(
        f"/api/initiatieven/{initiatief.id}", json={"naam": "RegelRecht 2.0"}
    )
    assert resp.status_code == 200, resp.text
    assert (await client.get(url)).json()["naam"] == "RegelRecht 2.0"


async def test_werk_toont_vraag_zonder_casus_en_geen_subtaken(
    client, db_session, initiatief, teamlid
):
    vraag = await client.post(
        f"/api/initiatieven/{initiatief.id}/vragen",
        json={"title": "Losse vraag", "assignee_id": str(teamlid.id)},
    )
    assert vraag.status_code == 201, vraag.text
    taak = await client.post(
        "/api/tasks",
        json={
            "title": "Taak onder losse vraag",
            "issue_id": vraag.json()["id"],
            "assignee_id": str(teamlid.id),
        },
    )
    assert taak.status_code == 201, taak.text
    # Subtaken onder casuswerk kan de API niet meer maken; oude data heeft ze.
    from bouwmeester.models.task import Task

    db_session.add(
        Task(
            title="Subtaak",
            parent_id=uuid.UUID(taak.json()["id"]),
            issue_id=uuid.UUID(vraag.json()["id"]),
            assignee_id=teamlid.id,
            status="open",
            priority="normaal",
        )
    )
    await db_session.flush()

    werk = (
        await client.get(
            f"/api/initiatieven/{initiatief.id}/personen/{teamlid.id}/werk"
        )
    ).json()
    assert [(i["title"], i["casus_id"]) for i in werk["issues"]] == [
        ("Losse vraag", None)
    ]
    assert [t["title"] for t in werk["open_taken"]] == ["Taak onder losse vraag"]
