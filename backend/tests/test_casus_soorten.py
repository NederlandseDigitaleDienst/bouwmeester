"""Casussoorten: soorten casus per initiatief, als tags op een casus.

Dekt:
- beheren (aanmaken, hernoemen, kleur, volgorde, verwijderen) alleen door de
  eigenaar; een lid zonder eigenaarsrol krijgt 403, wie het initiatief niet
  ziet 404 (ook op de lijst), zodat het bestaan niet lekt;
- dezelfde naam twee keer (ook met andere hoofdletters) is 409;
- soorten op een casus zetten kan wie de casus ziet, alleen met soorten van
  het eigen initiatief (anders 400), en ook al bij het starten;
- hernoemen werkt meteen op de casus, verwijderen haalt de soort eraf;
- per soort starteisen en eindeisen (alleen de eigenaar); bij de start en
  in de laatste fase legt de casus ze vast als momentopname, met alle
  eisen van zijn soorten erin, en een eis van een andere soort is 422.
  Afvinken is geen poort: de fase gaat ook door zonder.
"""

import uuid

import pytest

from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.repositories.lead_column import LeadColumnRepository
from tests.factories import START_INTERN, client_as, make_person

START = START_INTERN


async def _initiatief(db_session, naam):
    init = Initiatief(id=uuid.uuid4(), naam=naam, slug=f"cs-{uuid.uuid4().hex[:8]}")
    db_session.add(init)
    await db_session.flush()
    await LeadColumnRepository(db_session).seed_defaults(init.id)
    return init


@pytest.fixture
async def initiatief(db_session):
    return await _initiatief(db_session, "Regelrecht soorten")


async def _rol(db_session, initiatief_id, person_id, rol):
    db_session.add(
        ResourcePermission(
            person_id=person_id,
            resource_type="initiatief",
            resource_id=initiatief_id,
            rol=rol,
        )
    )
    await db_session.flush()


async def _lead(db_session, initiatief, title="Casus"):
    lead = Lead(
        id=uuid.uuid4(), title=title, stage="in_the_pocket", initiatief_id=initiatief.id
    )
    db_session.add(lead)
    await db_session.flush()
    return lead


async def _casus(client, db_session, initiatief, **extra):
    lead = await _lead(db_session, initiatief)
    resp = await client.post(
        "/api/casussen",
        json={"lead_id": str(lead.id), "startvoorwaarden": START, **extra},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _url(initiatief, *rest):
    return "/".join([f"/api/initiatieven/{initiatief.id}/casussoorten", *rest])


async def _soort(client, initiatief, naam, kleur="neutral"):
    resp = await client.post(_url(initiatief), json={"naam": naam, "kleur": kleur})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Beheren
# ---------------------------------------------------------------------------


async def test_eigenaar_beheert_soorten(client, initiatief):
    a = await _soort(client, initiatief, "Wetgeving", "lintblauw")
    b = await _soort(client, initiatief, "Uitvoering")
    lijst = (await client.get(_url(initiatief))).json()
    assert [s["naam"] for s in lijst] == ["Wetgeving", "Uitvoering"]
    assert lijst[0]["kleur"] == "lintblauw"

    resp = await client.put(
        _url(initiatief, a["id"]), json={"naam": "Wetgevingsproces"}
    )
    assert resp.status_code == 200 and resp.json()["naam"] == "Wetgevingsproces"

    resp = await client.post(
        _url(initiatief, "reorder"), json={"soort_ids": [b["id"], a["id"]]}
    )
    assert [s["naam"] for s in resp.json()] == ["Uitvoering", "Wetgevingsproces"]

    assert (await client.delete(_url(initiatief, b["id"]))).status_code == 204
    assert [s["naam"] for s in (await client.get(_url(initiatief))).json()] == [
        "Wetgevingsproces"
    ]


async def test_dubbele_naam_is_409(client, initiatief):
    await _soort(client, initiatief, "Wetgeving")
    resp = await client.post(_url(initiatief), json={"naam": "wetgeving"})
    assert resp.status_code == 409
    ander = await _soort(client, initiatief, "Uitvoering")
    resp = await client.put(_url(initiatief, ander["id"]), json={"naam": "WETGEVING"})
    assert resp.status_code == 409


async def test_ongeldige_kleur_en_lege_naam_zijn_422(client, initiatief):
    assert (
        await client.post(_url(initiatief), json={"naam": "X", "kleur": "#ff0000"})
    ).status_code == 422
    assert (
        await client.post(_url(initiatief), json={"naam": "   "})
    ).status_code == 422


async def test_lid_ziet_maar_beheert_niet(db_session, client, initiatief):
    soort = await _soort(client, initiatief, "Wetgeving")
    lid = await make_person(db_session, "Lid")
    await _rol(db_session, initiatief.id, lid.id, "contributor")
    async with client_as(db_session, lid) as c:
        assert (await c.get(_url(initiatief))).status_code == 200
        assert (
            await c.post(_url(initiatief), json={"naam": "Nieuw"})
        ).status_code == 403
        assert (
            await c.put(_url(initiatief, soort["id"]), json={"naam": "Anders"})
        ).status_code == 403
        assert (await c.delete(_url(initiatief, soort["id"]))).status_code == 403
        assert (
            await c.post(_url(initiatief, "reorder"), json={"soort_ids": [soort["id"]]})
        ).status_code == 403


async def test_eigenaar_via_rol(db_session, initiatief):
    baas = await make_person(db_session, "Eigenaar")
    await _rol(db_session, initiatief.id, baas.id, "eigenaar")
    async with client_as(db_session, baas) as c:
        resp = await c.post(_url(initiatief), json={"naam": "Wetgeving"})
    assert resp.status_code == 201, resp.text


async def test_buitenstaander_krijgt_404(db_session, client, initiatief):
    soort = await _soort(client, initiatief, "Wetgeving")
    vreemde = await make_person(db_session, "Vreemde")
    async with client_as(db_session, vreemde) as c:
        assert (await c.get(_url(initiatief))).status_code == 404
        assert (
            await c.post(_url(initiatief), json={"naam": "Nieuw"})
        ).status_code == 404
        assert (await c.delete(_url(initiatief, soort["id"]))).status_code == 404


async def test_soort_van_ander_initiatief_is_404_bij_beheren(
    client, db_session, initiatief
):
    ander = await _initiatief(db_session, "Ander")
    vreemd = await _soort(client, ander, "Elders")
    resp = await client.put(_url(initiatief, vreemd["id"]), json={"naam": "Hier"})
    assert resp.status_code == 404
    assert (await client.delete(_url(initiatief, vreemd["id"]))).status_code == 404


# ---------------------------------------------------------------------------
# Op een casus
# ---------------------------------------------------------------------------


async def test_soorten_op_casus_zetten_hernoemen_verwijderen(
    client, db_session, initiatief
):
    a = await _soort(client, initiatief, "Wetgeving", "lintblauw")
    b = await _soort(client, initiatief, "Uitvoering")
    casus = await _casus(client, db_session, initiatief)
    assert casus["soorten"] == []

    resp = await client.put(
        f"/api/casussen/{casus['id']}/soorten", json={"soort_ids": [b["id"], a["id"]]}
    )
    assert resp.status_code == 200, resp.text
    # In de volgorde van de instellingen, niet die van het verzoek.
    assert [s["naam"] for s in resp.json()] == ["Wetgeving", "Uitvoering"]

    await client.put(_url(initiatief, a["id"]), json={"naam": "Wetgevingsproces"})
    detail = (await client.get(f"/api/casussen/{casus['id']}")).json()
    assert [s["naam"] for s in detail["soorten"]] == ["Wetgevingsproces", "Uitvoering"]
    lijst = (await client.get(_url(initiatief))).json()
    assert {s["naam"]: s["casus_count"] for s in lijst} == {
        "Wetgevingsproces": 1,
        "Uitvoering": 1,
    }

    await client.delete(_url(initiatief, b["id"]))
    detail = (await client.get(f"/api/casussen/{casus['id']}")).json()
    assert [s["naam"] for s in detail["soorten"]] == ["Wetgevingsproces"]
    rij = next(
        c
        for c in (
            await client.get(
                "/api/casussen", params={"initiatief_id": str(initiatief.id)}
            )
        ).json()
        if c["id"] == casus["id"]
    )
    assert [s["naam"] for s in rij["soorten"]] == ["Wetgevingsproces"]


async def test_soort_van_ander_initiatief_niet_op_casus(client, db_session, initiatief):
    ander = await _initiatief(db_session, "Ander")
    vreemd = await _soort(client, ander, "Elders")
    casus = await _casus(client, db_session, initiatief)
    resp = await client.put(
        f"/api/casussen/{casus['id']}/soorten", json={"soort_ids": [vreemd["id"]]}
    )
    assert resp.status_code == 400

    lead = await _lead(db_session, initiatief, "Tweede")
    resp = await client.post(
        "/api/casussen",
        json={
            "lead_id": str(lead.id),
            "startvoorwaarden": START,
            "soort_ids": [vreemd["id"]],
        },
    )
    assert resp.status_code == 400
    # En er is geen casus ontstaan.
    assert (await client.get(f"/api/leads/{lead.id}")).json().get("casus_id") is None


async def test_soorten_meteen_bij_starten(client, db_session, initiatief):
    a = await _soort(client, initiatief, "Wetgeving")
    casus = await _casus(client, db_session, initiatief, soort_ids=[a["id"]])
    assert [s["naam"] for s in casus["soorten"]] == ["Wetgeving"]


async def test_buitenstaander_zet_geen_soorten(db_session, client, initiatief):
    a = await _soort(client, initiatief, "Wetgeving")
    casus = await _casus(client, db_session, initiatief)
    vreemde = await make_person(db_session, "Vreemde")
    async with client_as(db_session, vreemde) as c:
        resp = await c.put(
            f"/api/casussen/{casus['id']}/soorten", json={"soort_ids": [a["id"]]}
        )
    assert resp.status_code == 404


async def test_twee_keer_hetzelfde_zetten_is_idempotent(client, db_session, initiatief):
    """Een dubbele klik stuurt hetzelfde twee keer: dat mag geen fout geven."""
    a = await _soort(client, initiatief, "Wetgeving")
    b = await _soort(client, initiatief, "Uitvoering")
    casus = await _casus(client, db_session, initiatief)
    url = f"/api/casussen/{casus['id']}/soorten"
    for _ in range(2):
        resp = await client.put(url, json={"soort_ids": [a["id"], b["id"]]})
        assert resp.status_code == 200, resp.text
    resp = await client.put(url, json={"soort_ids": [b["id"]]})
    assert [s["naam"] for s in resp.json()] == ["Uitvoering"]
    resp = await client.put(url, json={"soort_ids": []})
    assert resp.json() == []


async def test_uitleg_bij_een_soort(client, db_session, initiatief):
    """Een soort heeft een uitleg: zichtbaar bij kiezen en op het label."""
    resp = await client.post(
        _url(initiatief),
        json={
            "naam": "Experiment",
            "uitleg": "  We proberen iets nieuws uit om ervan te leren.  ",
        },
    )
    assert resp.status_code == 201, resp.text
    soort = resp.json()
    assert soort["uitleg"] == "We proberen iets nieuws uit om ervan te leren."

    casus = await _casus(client, db_session, initiatief, soort_ids=[soort["id"]])
    assert casus["soorten"][0]["uitleg"] == soort["uitleg"]

    # Alleen de naam wijzigen laat de uitleg staan; leeg maken wist hem.
    resp = await client.put(_url(initiatief, soort["id"]), json={"naam": "Proef"})
    assert resp.json()["uitleg"] == soort["uitleg"]
    resp = await client.put(_url(initiatief, soort["id"]), json={"uitleg": "  "})
    assert resp.json()["uitleg"] is None


async def test_uitleg_te_lang_is_422(client, initiatief):
    resp = await client.post(_url(initiatief), json={"naam": "X", "uitleg": "a" * 501})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# In detail: hoe ver, starteisen en eindeisen
# ---------------------------------------------------------------------------


async def test_hoe_ver_en_eisen_bij_een_soort(client, initiatief):
    """Per soort: hoe ver we zo'n casus brengen, en de eisen op volgorde."""
    soort = await _soort(client, initiatief, "Beproeven")
    assert soort["hoe_ver"] is None
    assert (soort["start_eisen"], soort["eind_eisen"]) == ([], [])
    resp = await client.put(
        _url(initiatief, soort["id"]),
        json={
            "hoe_ver": "  Tot een werkend prototype bij een partner.  ",
            "start_eisen": [" Partner gevonden ", "", "Partner gevonden"],
            "eind_eisen": ["  Prototype draait ", "", "Demo gegeven"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["hoe_ver"] == "Tot een werkend prototype bij een partner."
    # Lege en dubbele regels vallen weg.
    assert body["start_eisen"] == ["Partner gevonden"]
    assert body["eind_eisen"] == ["Prototype draait", "Demo gegeven"]

    # Alleen de naam wijzigen laat hoe ver en de eisen staan.
    resp = await client.put(_url(initiatief, soort["id"]), json={"naam": "Proef"})
    assert resp.json()["start_eisen"] == ["Partner gevonden"]
    assert resp.json()["eind_eisen"] == ["Prototype draait", "Demo gegeven"]
    assert resp.json()["hoe_ver"] == "Tot een werkend prototype bij een partner."

    # Leeg wist ze.
    resp = await client.put(
        _url(initiatief, soort["id"]),
        json={"hoe_ver": " ", "start_eisen": [], "eind_eisen": []},
    )
    assert resp.json()["hoe_ver"] is None
    assert (resp.json()["start_eisen"], resp.json()["eind_eisen"]) == ([], [])


@pytest.mark.parametrize("lijst", ["start_eisen", "eind_eisen"])
async def test_eis_te_lang_of_te_veel_is_422(client, initiatief, lijst):
    soort = await _soort(client, initiatief, f"Lang {lijst}")
    url = _url(initiatief, soort["id"])
    assert (await client.put(url, json={lijst: ["a" * 301]})).status_code == 422
    assert (
        await client.put(url, json={lijst: [f"p{i}" for i in range(31)]})
    ).status_code == 422


async def test_lid_zet_geen_eisen(db_session, client, initiatief):
    soort = await _soort(client, initiatief, "Alleen eigenaar")
    lid = await make_person(db_session, "Lid eisen")
    await _rol(db_session, initiatief.id, lid.id, "contributor")
    async with client_as(db_session, lid) as c:
        resp = await c.put(
            _url(initiatief, soort["id"]),
            json={"start_eisen": ["Stiekem"], "eind_eisen": ["Stiekem"]},
        )
    assert resp.status_code in (403, 404), resp.text
    lijst = (await client.get(_url(initiatief))).json()
    eigen = next(s for s in lijst if s["id"] == soort["id"])
    assert (eigen["start_eisen"], eigen["eind_eisen"]) == ([], [])


async def _soort_met_eisen(client, initiatief, naam, start=(), eind=()):
    soort = await _soort(client, initiatief, naam)
    resp = await client.put(
        _url(initiatief, soort["id"]),
        json={"start_eisen": list(start), "eind_eisen": list(eind)},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Starteisen: bij het starten van een casus
# ---------------------------------------------------------------------------


async def test_starteisen_van_de_gekozen_soorten_als_momentopname(
    client, db_session, initiatief
):
    a = await _soort_met_eisen(client, initiatief, "Model", start=["Wet gekozen"])
    b = await _soort_met_eisen(
        client, initiatief, "Proef", start=["Partner gevonden", "Data beschikbaar"]
    )
    await _soort_met_eisen(client, initiatief, "Niet gekozen", start=["Weg"])
    casus = await _casus(
        client,
        db_session,
        initiatief,
        soort_ids=[b["id"], a["id"]],
        startvoorwaarden={
            **START,
            "start_eisen": [
                {"soort_id": b["id"], "eis": "Partner gevonden", "akkoord": True},
                {
                    "soort_id": a["id"],
                    "eis": "Wet gekozen",
                    "opmerking": "  Zorgtoeslag ",
                },
            ],
        },
    )
    # Alle eisen van de gekozen soorten, op volgorde van de instellingen; een
    # eis die niemand aanvinkte, staat erin als niet akkoord.
    assert casus["startvoorwaarden"]["start_eisen"] == [
        {
            "soort_id": a["id"],
            "soort": "Model",
            "eis": "Wet gekozen",
            "akkoord": False,
            "opmerking": "Zorgtoeslag",
        },
        {
            "soort_id": b["id"],
            "soort": "Proef",
            "eis": "Partner gevonden",
            "akkoord": True,
        },
        {
            "soort_id": b["id"],
            "soort": "Proef",
            "eis": "Data beschikbaar",
            "akkoord": False,
        },
    ]

    # Een latere wijziging van de soort verandert de casus niet.
    await client.put(_url(initiatief, a["id"]), json={"start_eisen": ["Anders"]})
    na = (await client.get(f"/api/casussen/{casus['id']}")).json()
    assert na["startvoorwaarden"]["start_eisen"][0]["eis"] == "Wet gekozen"


async def test_starteis_van_een_andere_soort_is_422(client, db_session, initiatief):
    a = await _soort_met_eisen(client, initiatief, "Gekozen", start=["Eigen eis"])
    b = await _soort_met_eisen(client, initiatief, "Niet gekozen", start=["Vreemd"])
    lead = await _lead(db_session, initiatief)
    resp = await client.post(
        "/api/casussen",
        json={
            "lead_id": str(lead.id),
            "soort_ids": [a["id"]],
            "startvoorwaarden": {
                **START,
                "start_eisen": [{"soort_id": b["id"], "eis": "Vreemd"}],
            },
        },
    )
    assert resp.status_code == 422, resp.text


async def test_zonder_starteisen_geen_veld(client, db_session, initiatief):
    soort = await _soort(client, initiatief, "Zonder eisen")
    casus = await _casus(client, db_session, initiatief, soort_ids=[soort["id"]])
    assert "start_eisen" not in casus["startvoorwaarden"]


# ---------------------------------------------------------------------------
# Eindeisen: als de casus in de laatste fase komt
# ---------------------------------------------------------------------------


async def test_eindeisen_bij_de_laatste_fase_als_momentopname(
    client, db_session, initiatief
):
    soort = await _soort_met_eisen(
        client, initiatief, "Eind", eind=["Verslag gedeeld", "Demo gegeven"]
    )
    casus = await _casus(client, db_session, initiatief, soort_ids=[soort["id"]])
    assert casus["eind_eisen"] == []
    resp = await client.put(
        f"/api/casussen/{casus['id']}",
        json={
            "fase": "besluiten",
            "eind_eisen": [
                {"soort_id": soort["id"], "eis": "Verslag gedeeld", "akkoord": True}
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Niet alles af, en toch door: afvinken is geen poort.
    assert body["fase"] == "besluiten"
    assert body["eind_eisen"] == [
        {
            "soort_id": soort["id"],
            "soort": "Eind",
            "eis": "Verslag gedeeld",
            "akkoord": True,
        },
        {
            "soort_id": soort["id"],
            "soort": "Eind",
            "eis": "Demo gegeven",
            "akkoord": False,
        },
    ]

    # Nog eens nalopen vervangt de momentopname; alleen de fase laat hem staan.
    resp = await client.put(
        f"/api/casussen/{casus['id']}",
        json={
            "eind_eisen": [
                {
                    "soort_id": soort["id"],
                    "eis": "Demo gegeven",
                    "akkoord": True,
                    "opmerking": "Op 30 oktober",
                }
            ]
        },
    )
    assert [e["akkoord"] for e in resp.json()["eind_eisen"]] == [False, True]
    resp = await client.put(f"/api/casussen/{casus['id']}", json={"fase": "delen"})
    assert resp.json()["eind_eisen"][1]["opmerking"] == "Op 30 oktober"


async def test_fase_door_zonder_eindeisen(client, db_session, initiatief):
    soort = await _soort_met_eisen(client, initiatief, "Geen poort", eind=["Iets"])
    casus = await _casus(client, db_session, initiatief, soort_ids=[soort["id"]])
    resp = await client.put(f"/api/casussen/{casus['id']}", json={"fase": "besluiten"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["eind_eisen"] == []


async def test_eindeis_van_een_andere_soort_is_422(client, db_session, initiatief):
    eigen = await _soort_met_eisen(client, initiatief, "Op de casus", eind=["Eigen"])
    ander = await _soort_met_eisen(client, initiatief, "Niet erop", eind=["Vreemd"])
    casus = await _casus(client, db_session, initiatief, soort_ids=[eigen["id"]])
    resp = await client.put(
        f"/api/casussen/{casus['id']}",
        json={
            "fase": "besluiten",
            "eind_eisen": [{"soort_id": ander["id"], "eis": "Vreemd"}],
        },
    )
    assert resp.status_code == 422, resp.text
    # Niets veranderd, ook de fase niet.
    na = (await client.get(f"/api/casussen/{casus['id']}")).json()
    assert (na["fase"], na["eind_eisen"]) == (casus["fase"], [])


async def test_eisen_staan_bij_de_soort_op_de_casus(client, db_session, initiatief):
    """Het startvenster en het afronden lezen de eisen van de casus zelf."""
    soort = await _soort_met_eisen(
        client, initiatief, "Mee", start=["Bij de start"], eind=["Aan het eind"]
    )
    casus = await _casus(client, db_session, initiatief, soort_ids=[soort["id"]])
    (op_casus,) = casus["soorten"]
    assert op_casus["start_eisen"] == ["Bij de start"]
    assert op_casus["eind_eisen"] == ["Aan het eind"]
