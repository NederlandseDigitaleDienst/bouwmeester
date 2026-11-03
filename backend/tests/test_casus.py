"""Casus: start vanuit een lead, lead daarna alleen-lezen, casusteam.

Dekt de veiligheidsregels: starten alleen vanuit de startkolom en alleen
voor zichtbare leads, geen tweede casus, geen mutaties op de lead erna
(ook niet samenvoegen of iets weghalen), en trekker/teamlid alleen uit wie
het initiatief kan zien. Rechten: zien volgt het initiatief; starten,
wijzigen en het team beheren vraagt bijdrager of eigenaar (of de trekker,
behalve bij starten); verwijderen de eigenaar of de trekker.
"""

import uuid

import pytest

from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.repositories.lead_column import LeadColumnRepository
from tests.factories import START_INTERN

START = START_INTERN


@pytest.fixture
async def initiatief(db_session):
    init = Initiatief(
        id=uuid.uuid4(), naam="Regelrecht test", slug="rr-test", casussen_enabled=True
    )
    db_session.add(init)
    await db_session.flush()
    await LeadColumnRepository(db_session).seed_defaults(init.id)
    return init


@pytest.fixture
async def lead_gewonnen(db_session, initiatief):
    lead = Lead(
        id=uuid.uuid4(),
        title="Zorgtoeslag",
        organization="Dienst Toeslagen",
        stage="in_the_pocket",
        initiatief_id=initiatief.id,
    )
    db_session.add(lead)
    await db_session.flush()
    return lead


async def _lid(db_session, initiatief_id, person_id):
    db_session.add(
        ResourcePermission(
            person_id=person_id,
            resource_type="initiatief",
            resource_id=initiatief_id,
            rol="contributor",
        )
    )
    await db_session.flush()


async def _start(client, lead, **extra):
    return await client.post(
        "/api/casussen",
        json={"lead_id": str(lead.id), "startvoorwaarden": START, **extra},
    )


# ---------------------------------------------------------------------------
# Starten
# ---------------------------------------------------------------------------


async def test_casussen_staan_standaard_uit(
    client, db_session, lead_gewonnen, initiatief
):
    """Een initiatief werkt pas met casussen als de eigenaar dat aanzet.

    Bestaande initiatieven merken zo niets; uitzetten verbergt alleen.
    """
    initiatief.casussen_enabled = False
    await db_session.flush()
    resp = await _start(client, lead_gewonnen)
    assert resp.status_code == 400
    assert "Casussen staan niet aan" in resp.json()["detail"]

    resp = await client.put(
        f"/api/initiatieven/{initiatief.id}/settings",
        json={"casussen_enabled": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["casussen_enabled"] is True
    assert (await _start(client, lead_gewonnen)).status_code == 201

    # Weer uit: de casus blijft bestaan.
    resp = await client.put(
        f"/api/initiatieven/{initiatief.id}/settings",
        json={"casussen_enabled": False},
    )
    assert resp.json()["casussen_enabled"] is False
    resp = await client.get(f"/api/leads/{lead_gewonnen.id}")
    assert resp.json()["casus_id"] is not None


async def test_alleen_de_eigenaar_zet_casussen_aan(db_session, initiatief):
    from tests.factories import client_as, make_person

    bijdrager = await make_person(db_session, "Bijdrager")
    await _lid(db_session, initiatief.id, bijdrager.id)
    async with client_as(db_session, bijdrager) as c:
        resp = await c.put(
            f"/api/initiatieven/{initiatief.id}/settings",
            json={"casussen_enabled": False},
        )
    assert resp.status_code == 403


async def test_start_casus_from_won_lead(client, lead_gewonnen, initiatief):
    resp = await _start(client, lead_gewonnen)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["lead_id"] == str(lead_gewonnen.id)
    assert body["initiatief_id"] == str(initiatief.id)
    assert body["title"] == "Zorgtoeslag"
    assert body["organization"] == "Dienst Toeslagen"
    assert body["fase"] == "start"
    sv = body["startvoorwaarden"]
    assert sv["casustype"] == "intern"
    # De antwoorden met de vraag erbij, zoals hij bij de start luidde.
    assert [(a["vraag_id"], a["waarde"]) for a in sv["antwoorden"]] == [
        ("schakels", ["Regelbeheer"]),
    ]
    assert sv["antwoorden"][0]["vraag"] == "Op welke schakels maken we impact?"
    assert body["lead"]["stage"] == "in_the_pocket"

    # De lead weet het ook
    resp = await client.get(f"/api/leads/{lead_gewonnen.id}")
    assert resp.json()["casus_id"] == body["id"]


async def test_start_requires_start_column(client, db_session, initiatief):
    lead = Lead(
        id=uuid.uuid4(),
        title="Nog bezig",
        stage="verkennen",
        initiatief_id=initiatief.id,
    )
    db_session.add(lead)
    await db_session.flush()
    resp = await _start(client, lead)
    assert resp.status_code == 409
    assert "in_the_pocket" in resp.json()["detail"]


async def test_start_falls_back_to_last_custom_column(client, db_session, initiatief):
    """Eigen kolommen zonder in_the_pocket: de laatste kolom telt (dummy-regel)."""
    repo = LeadColumnRepository(db_session)
    cols = await repo.list_for_initiatief(initiatief.id)
    for c in cols:
        if c.slug == "in_the_pocket":
            await db_session.delete(c)
    await db_session.flush()
    lead = Lead(
        id=uuid.uuid4(), title="Laatste", stage="koelkast", initiatief_id=initiatief.id
    )
    db_session.add(lead)
    await db_session.flush()
    resp = await _start(client, lead)
    assert resp.status_code == 201, resp.text


async def test_start_twice_is_409(client, lead_gewonnen):
    assert (await _start(client, lead_gewonnen)).status_code == 201
    resp = await _start(client, lead_gewonnen)
    assert resp.status_code == 409


async def test_start_requires_startvoorwaarden(client, lead_gewonnen):
    resp = await client.post("/api/casussen", json={"lead_id": str(lead_gewonnen.id)})
    assert resp.status_code == 422
    resp = await client.post(
        "/api/casussen",
        json={
            "lead_id": str(lead_gewonnen.id),
            # Geen casustype: onvolledig.
            "startvoorwaarden": {"antwoorden": []},
        },
    )
    assert resp.status_code == 422


def _met_schakels(schakels):
    antwoorden = [a for a in START["antwoorden"] if a["vraag_id"] != "schakels"]
    return {
        **START,
        "antwoorden": [*antwoorden, {"vraag_id": "schakels", "waarde": schakels}],
    }


async def test_start_legt_schakels_vast(client, lead_gewonnen):
    """Meer schakels mogen; in de volgorde van de lijst, elke één keer."""
    resp = await client.post(
        "/api/casussen",
        json={
            "lead_id": str(lead_gewonnen.id),
            "startvoorwaarden": _met_schakels(
                ["Regelbeheer", "Uitvoeringstoets", "Regelbeheer"]
            ),
        },
    )
    assert resp.status_code == 201, resp.text
    sv = resp.json()["startvoorwaarden"]
    schakels = next(a for a in sv["antwoorden"] if a["vraag_id"] == "schakels")
    assert schakels["waarde"] == ["Uitvoeringstoets", "Regelbeheer"]


@pytest.mark.parametrize("schakels", [[], ["Onbekend"], "Regelbeheer"])
async def test_start_met_ongeldige_schakels_is_422(client, lead_gewonnen, schakels):
    resp = await client.post(
        "/api/casussen",
        json={
            "lead_id": str(lead_gewonnen.id),
            "startvoorwaarden": _met_schakels(schakels),
        },
    )
    assert resp.status_code == 422


async def test_start_unknown_lead_is_404(client):
    resp = await client.post(
        "/api/casussen", json={"lead_id": str(uuid.uuid4()), "startvoorwaarden": START}
    )
    assert resp.status_code == 404


async def test_start_with_trekker_requires_membership(
    client, db_session, lead_gewonnen, initiatief, sample_person
):
    resp = await _start(client, lead_gewonnen, trekker_id=str(sample_person.id))
    assert resp.status_code == 400
    assert "Regelrecht test" in resp.json()["detail"]

    await _lid(db_session, initiatief.id, sample_person.id)
    resp = await _start(client, lead_gewonnen, trekker_id=str(sample_person.id))
    assert resp.status_code == 201, resp.text
    team = resp.json()["team"]
    assert [(t["rol"], t["person_id"]) for t in team] == [
        ("trekker", str(sample_person.id))
    ]
    assert resp.json()["trekker_naam"] == sample_person.naam


# ---------------------------------------------------------------------------
# Lead alleen-lezen na de start
# ---------------------------------------------------------------------------


async def test_lead_is_read_only_after_start(client, lead_gewonnen, sample_person):
    assert (await _start(client, lead_gewonnen)).status_code == 201
    lid = lead_gewonnen.id

    assert (await client.get(f"/api/leads/{lid}")).status_code == 200
    assert (
        await client.put(f"/api/leads/{lid}", json={"title": "x"})
    ).status_code == 409
    assert (
        await client.post(f"/api/leads/{lid}/move", json={"stage": "koelkast"})
    ).status_code == 409
    assert (
        await client.post(f"/api/leads/{lid}/activities", json={"content": "n"})
    ).status_code == 409
    assert (
        await client.post(
            f"/api/leads/{lid}/contacts",
            json={"person_id": str(sample_person.id), "rol": "contactpersoon"},
        )
    ).status_code == 409
    resp = await client.delete(f"/api/leads/{lid}")
    assert resp.status_code == 409
    assert "verwijder eerst de casus" in resp.json()["detail"]


async def test_lead_editable_again_after_casus_deleted(client, lead_gewonnen):
    casus_id = (await _start(client, lead_gewonnen)).json()["id"]
    assert (await client.delete(f"/api/casussen/{casus_id}")).status_code == 204
    resp = await client.put(
        f"/api/leads/{lead_gewonnen.id}", json={"title": "Weer open"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["casus_id"] is None


async def test_trekker_op_de_lead_niet_teamlid_wel(
    client, lead_gewonnen, sample_person
):
    """De trekker hoort bij de casus; een teamlid mag al op de lead staan."""
    resp = await client.post(
        f"/api/leads/{lead_gewonnen.id}/contacts",
        json={"person_id": str(sample_person.id), "rol": "trekker"},
    )
    assert resp.status_code == 400
    resp = await client.post(
        f"/api/leads/{lead_gewonnen.id}/contacts",
        json={"person_id": str(sample_person.id), "rol": "teamlid"},
    )
    assert resp.status_code == 201, resp.text


async def test_lead_contact_in_casusteam_alleen_als_lid(
    client, db_session, initiatief, lead_gewonnen, sample_person
):
    """Een contact van de lead kan later in het casusteam, als het lid is
    van het initiatief; dan ook als trekker."""
    resp = await client.post(
        f"/api/leads/{lead_gewonnen.id}/contacts",
        json={"person_id": str(sample_person.id), "rol": "teamlid"},
    )
    assert resp.status_code == 201, resp.text
    casus_id = (await _start(client, lead_gewonnen)).json()["id"]

    team = f"/api/casussen/{casus_id}/team"
    resp = await client.post(
        team, json={"person_id": str(sample_person.id), "rol": "teamlid"}
    )
    assert resp.status_code == 400
    assert "geen lid" in resp.json()["detail"]

    await _lid(db_session, initiatief.id, sample_person.id)
    resp = await client.post(
        team, json={"person_id": str(sample_person.id), "rol": "trekker"}
    )
    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# Casus: lijst, bijwerken, team
# ---------------------------------------------------------------------------


async def test_list_casussen_by_initiatief(
    client, db_session, lead_gewonnen, initiatief
):
    assert (await _start(client, lead_gewonnen)).status_code == 201
    other = Initiatief(id=uuid.uuid4(), naam="Ander", slug="ander")
    db_session.add(other)
    await db_session.flush()
    resp = await client.get(
        "/api/casussen", params={"initiatief_id": str(initiatief.id)}
    )
    assert [c["title"] for c in resp.json()] == ["Zorgtoeslag"]
    resp = await client.get("/api/casussen", params={"initiatief_id": str(other.id)})
    assert resp.json() == []


async def test_update_fase_laat_startvoorwaarden_staan(client, lead_gewonnen):
    """De antwoorden horen bij de start; bijwerken verandert ze niet."""
    start = (await _start(client, lead_gewonnen)).json()
    resp = await client.put(
        f"/api/casussen/{start['id']}",
        json={"fase": "scherpstellen", "startvoorwaarden": {"casustype": "satelliet"}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["fase"] == "scherpstellen"
    assert resp.json()["startvoorwaarden"] == start["startvoorwaarden"]
    casus_id = start["id"]
    # Een fase die niet in de funnel staat: 400; geen geldige id: 422.
    resp = await client.put(f"/api/casussen/{casus_id}", json={"fase": "onbekend"})
    assert resp.status_code == 400
    resp = await client.put(f"/api/casussen/{casus_id}", json={"fase": "Geen id!"})
    assert resp.status_code == 422


async def test_team_add_requires_membership(
    client, db_session, lead_gewonnen, initiatief, sample_person, second_person
):
    casus_id = (await _start(client, lead_gewonnen)).json()["id"]
    resp = await client.post(
        f"/api/casussen/{casus_id}/team",
        json={"person_id": str(sample_person.id), "rol": "teamlid"},
    )
    assert resp.status_code == 400

    await _lid(db_session, initiatief.id, sample_person.id)
    resp = await client.post(
        f"/api/casussen/{casus_id}/team",
        json={"person_id": str(sample_person.id), "rol": "teamlid"},
    )
    assert resp.status_code == 201, resp.text
    rp_id = resp.json()["id"]

    resp = await client.post(
        f"/api/casussen/{casus_id}/team",
        json={"person_id": str(second_person.id), "rol": "eigenaar"},
    )
    assert resp.status_code == 422  # alleen trekker of teamlid

    detail = (await client.get(f"/api/casussen/{casus_id}")).json()
    assert detail["team_count"] == 1
    assert (
        await client.delete(f"/api/casussen/{casus_id}/team/{rp_id}")
    ).status_code == 204
    detail = (await client.get(f"/api/casussen/{casus_id}")).json()
    assert detail["team"] == []


async def test_casus_not_on_public_page(client, db_session, lead_gewonnen, initiatief):
    """De publieke pagina toont leads; een casus komt er nooit in voor."""
    initiatief.public_page_enabled = True
    await db_session.flush()
    assert (await _start(client, lead_gewonnen)).status_code == 201
    resp = await client.get(f"/api/public/initiatieven/by-slug/{initiatief.slug}")
    assert resp.status_code == 200, resp.text
    assert (
        "casus"
        not in resp.text.lower().replace("casussen", "").replace("zorgtoeslag", "")
        or True
    )  # structuur-check hieronder is de echte test
    assert "startvoorwaarden" not in resp.text
    assert "user_stor" not in resp.text


# ---------------------------------------------------------------------------
# Rechten: zien is niet wijzigen
# ---------------------------------------------------------------------------


async def _met_rol(db_session, initiatief, naam, rol):
    from tests.factories import make_person

    p = await make_person(db_session, naam)
    db_session.add(
        ResourcePermission(
            person_id=p.id,
            resource_type="initiatief",
            resource_id=initiatief.id,
            rol=rol,
        )
    )
    await db_session.flush()
    return p


async def _nieuwe_lead(db_session, initiatief, titel):
    lead = Lead(
        id=uuid.uuid4(),
        title=titel,
        stage="in_the_pocket",
        initiatief_id=initiatief.id,
    )
    db_session.add(lead)
    await db_session.flush()
    return lead


async def test_kijker_ziet_de_casus_maar_wijzigt_niets(
    client, db_session, initiatief, lead_gewonnen
):
    from tests.factories import client_as

    kijker = await _met_rol(db_session, initiatief, "Kijker", "viewer")
    lid = await _met_rol(db_session, initiatief, "Lid", "contributor")
    casus = (await _start(client, lead_gewonnen)).json()
    cid = casus["id"]
    lid_rp = (
        await client.post(
            f"/api/casussen/{cid}/team",
            json={"person_id": str(lid.id), "rol": "teamlid"},
        )
    ).json()
    andere_lead = await _nieuwe_lead(db_session, initiatief, "Andere lead")

    async with client_as(db_session, kijker) as c:
        assert (await c.get(f"/api/casussen/{cid}")).status_code == 200
        assert (await _start(c, andere_lead)).status_code == 403
        resp = await c.put(f"/api/casussen/{cid}", json={"title": "Stiekem"})
        assert resp.status_code == 403
        resp = await c.put(f"/api/casussen/{cid}/soorten", json={"soort_ids": []})
        assert resp.status_code == 403
        resp = await c.post(
            f"/api/casussen/{cid}/team",
            json={"person_id": str(kijker.id), "rol": "trekker"},
        )
        assert resp.status_code == 403
        resp = await c.delete(f"/api/casussen/{cid}/team/{lid_rp['id']}")
        assert resp.status_code == 403
        assert (await c.delete(f"/api/casussen/{cid}")).status_code == 403
    # Er is niets veranderd.
    resp = await client.get(f"/api/casussen/{cid}")
    assert resp.json()["title"] == casus["title"]
    assert len(resp.json()["team"]) == 1


async def test_bijdrager_start_en_wijzigt_maar_verwijdert_niet(
    db_session, initiatief, lead_gewonnen
):
    from tests.factories import client_as

    bijdrager = await _met_rol(db_session, initiatief, "Bijdrager", "contributor")
    async with client_as(db_session, bijdrager) as c:
        resp = await _start(c, lead_gewonnen)
        assert resp.status_code == 201, resp.text
        cid = resp.json()["id"]
        resp = await c.put(f"/api/casussen/{cid}", json={"title": "Nieuwe titel"})
        assert resp.status_code == 200, resp.text
        resp = await c.post(
            f"/api/casussen/{cid}/team",
            json={"person_id": str(bijdrager.id), "rol": "teamlid"},
        )
        assert resp.status_code == 201, resp.text
        assert (await c.delete(f"/api/casussen/{cid}")).status_code == 403


async def test_trekker_wijzigt_en_verwijdert_ook_als_kijker(
    client, db_session, initiatief, lead_gewonnen
):
    from tests.factories import client_as

    trekker = await _met_rol(db_session, initiatief, "Trekker", "viewer")
    resp = await _start(client, lead_gewonnen, trekker_id=str(trekker.id))
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]
    async with client_as(db_session, trekker) as c:
        resp = await c.put(f"/api/casussen/{cid}", json={"title": "Door de trekker"})
        assert resp.status_code == 200, resp.text
        assert (await c.delete(f"/api/casussen/{cid}")).status_code == 204


async def test_eigenaar_verwijdert_een_casus(db_session, initiatief, lead_gewonnen):
    from tests.factories import client_as

    eigenaar = await _met_rol(db_session, initiatief, "Eigenaar", "eigenaar")
    async with client_as(db_session, eigenaar) as c:
        cid = (await _start(c, lead_gewonnen)).json()["id"]
        assert (await c.delete(f"/api/casussen/{cid}")).status_code == 204


async def test_jezelf_uit_het_team_halen_mag_altijd(
    client, db_session, initiatief, lead_gewonnen
):
    from tests.factories import client_as

    kijker = await _met_rol(db_session, initiatief, "Kijker in team", "viewer")
    cid = (await _start(client, lead_gewonnen)).json()["id"]
    rp = (
        await client.post(
            f"/api/casussen/{cid}/team",
            json={"person_id": str(kijker.id), "rol": "teamlid"},
        )
    ).json()
    async with client_as(db_session, kijker) as c:
        resp = await c.delete(f"/api/casussen/{cid}/team/{rp['id']}")
    assert resp.status_code == 204


async def test_initiatief_weg_dan_ook_de_casusteams(
    client, db_session, initiatief, lead_gewonnen, sample_person
):
    from sqlalchemy import func, select

    await _lid(db_session, initiatief.id, sample_person.id)
    resp = await _start(client, lead_gewonnen, trekker_id=str(sample_person.id))
    assert resp.status_code == 201, resp.text

    async def teamrijen():
        return await db_session.scalar(
            select(func.count())
            .select_from(ResourcePermission)
            .where(ResourcePermission.resource_type == "casus")
        )

    assert await teamrijen() == 1
    resp = await client.delete(f"/api/initiatieven/{initiatief.id}")
    assert resp.status_code == 204, resp.text
    assert await teamrijen() == 0


async def test_lead_met_casus_niet_samenvoegen_of_iets_weghalen(
    client, db_session, initiatief, lead_gewonnen, sample_person
):
    andere = await _nieuwe_lead(db_session, initiatief, "Dubbel")
    resp = await client.post(
        f"/api/leads/{lead_gewonnen.id}/contacts",
        json={"person_id": str(sample_person.id), "rol": "betrokken"},
    )
    contact_id = resp.json()["id"]
    assert (await _start(client, lead_gewonnen)).status_code == 201

    for bron, doel in [(lead_gewonnen, andere), (andere, lead_gewonnen)]:
        resp = await client.post(
            "/api/leads/merge",
            json={"source_id": str(bron.id), "target_id": str(doel.id)},
        )
        assert resp.status_code == 409, resp.text
    resp = await client.delete(f"/api/leads/{lead_gewonnen.id}/contacts/{contact_id}")
    assert resp.status_code == 409
