"""Startvragen per initiatief en de antwoorden bij het starten van een casus.

Dekt: de standaardlijst zolang een initiatief geen eigen lijst heeft; een
eigen lijst instellen en terugzetten (eigenaar alleen); de vaste vraag naar
intern of satelliet blijft staan en houdt zijn tekst; elk antwoordtype wordt
getoetst bij de start, met verplichte vragen en een momentopname van de vraag.
"""

import uuid

import pytest

from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.resource_permission import ResourcePermission
from tests.factories import client_as, grant_role, make_org, make_person

STANDAARD_IDS = ["casustype", "schakels"]

EIGEN = [
    {
        "id": "casustype",
        "vraag": "Probeer de vaste vraag te hernoemen",
        "antwoordtype": "vrij",
        "op_kaartje": False,
    },
    {
        "id": "partner",
        "vraag": "Is er een partner?",
        "antwoordtype": "ja_nee",
        "op_kaartje": True,
    },
    {
        "id": "kanaal",
        "vraag": "Via welk kanaal kwam hij binnen?",
        "antwoordtype": "een_keuze",
        "opties": ["Netwerk", "Website", "Netwerk"],
    },
    {
        "id": "regelingen",
        "vraag": "Welke regelingen?",
        "antwoordtype": "meer_keuzes",
        "opties": ["Zorgtoeslag", "Huurtoeslag", "Kinderopvang"],
    },
    {
        "id": "notitie",
        "vraag": "Nog iets?",
        "antwoordtype": "vrij",
        "verplicht": False,
    },
]


@pytest.fixture
async def initiatief(db_session):
    init = Initiatief(id=uuid.uuid4(), naam="Startvragen", slug="rr-startvragen")
    db_session.add(init)
    await db_session.flush()
    return init


async def _lead(db_session, initiatief, titel="Kandidaat"):
    lead = Lead(
        id=uuid.uuid4(), title=titel, stage="in_the_pocket", initiatief_id=initiatief.id
    )
    db_session.add(lead)
    await db_session.flush()
    return lead


async def _zet(client, initiatief, vragen):
    return await client.put(
        f"/api/initiatieven/{initiatief.id}/settings", json={"startvragen": vragen}
    )


async def _start(client, lead, startvoorwaarden):
    return await client.post(
        "/api/casussen",
        json={"lead_id": str(lead.id), "startvoorwaarden": startvoorwaarden},
    )


# ---------------------------------------------------------------------------
# Beheren
# ---------------------------------------------------------------------------


async def test_standaardlijst_zolang_er_geen_eigen_lijst_is(client, initiatief):
    vragen = (await client.get(f"/api/initiatieven/{initiatief.id}")).json()[
        "startvragen"
    ]
    assert [v["id"] for v in vragen] == STANDAARD_IDS
    # De schakels: meer keuzes, acht schakels.
    assert vragen[1]["antwoordtype"] == "meer_keuzes"
    assert len(vragen[1]["opties"]) == 8


async def test_eigen_lijst_instellen_en_terugzetten(client, initiatief):
    resp = await _zet(client, initiatief, EIGEN)
    assert resp.status_code == 200, resp.text
    vragen = resp.json()["startvragen"]
    assert [v["id"] for v in vragen] == [
        "casustype",
        "partner",
        "kanaal",
        "regelingen",
        "notitie",
    ]
    # De vaste vraag houdt tekst en antwoorden, neemt alleen op_kaartje over.
    vast = vragen[0]
    assert vast["vraag"] == "Is het een interne casus of een satellietcasus?"
    assert vast["antwoordtype"] == "een_keuze"
    assert vast["opties"] == ["Interne casus", "Satellietcasus"]
    assert vast["op_kaartje"] is False
    # Dubbele keuzes vallen weg.
    assert vragen[2]["opties"] == ["Netwerk", "Website"]

    detail = (await client.get(f"/api/initiatieven/{initiatief.id}")).json()
    assert [v["id"] for v in detail["startvragen"]] == [v["id"] for v in vragen]

    resp = await _zet(client, initiatief, [])
    assert [v["id"] for v in resp.json()["startvragen"]] == STANDAARD_IDS


@pytest.mark.parametrize(
    "vragen",
    [
        # De vaste vraag ontbreekt.
        [{"id": "partner", "vraag": "Partner?", "antwoordtype": "ja_nee"}],
        # Twee keer dezelfde id.
        [
            {"id": "casustype", "vraag": "x", "antwoordtype": "ja_nee"},
            {"id": "a", "vraag": "A?", "antwoordtype": "ja_nee"},
            {"id": "a", "vraag": "Weer A?", "antwoordtype": "ja_nee"},
        ],
        # Eén keuze met maar één optie.
        [
            {"id": "casustype", "vraag": "x", "antwoordtype": "ja_nee"},
            {"id": "a", "vraag": "A?", "antwoordtype": "een_keuze", "opties": ["X"]},
        ],
        # Ja/nee met keuzes.
        [
            {"id": "casustype", "vraag": "x", "antwoordtype": "ja_nee"},
            {"id": "a", "vraag": "A?", "antwoordtype": "ja_nee", "opties": ["X", "Y"]},
        ],
        # Een vrij antwoord op het kaartje.
        [
            {"id": "casustype", "vraag": "x", "antwoordtype": "ja_nee"},
            {"id": "a", "vraag": "A?", "antwoordtype": "vrij", "op_kaartje": True},
        ],
        # Een id met hoofdletters en spaties.
        [
            {"id": "casustype", "vraag": "x", "antwoordtype": "ja_nee"},
            {"id": "Een Vraag", "vraag": "A?", "antwoordtype": "ja_nee"},
        ],
        # Een lege vraag.
        [
            {"id": "casustype", "vraag": "x", "antwoordtype": "ja_nee"},
            {"id": "a", "vraag": "   ", "antwoordtype": "ja_nee"},
        ],
    ],
)
async def test_ongeldige_lijst_is_422(client, initiatief, vragen):
    resp = await _zet(client, initiatief, vragen)
    assert resp.status_code == 422, resp.text


async def test_alleen_de_eigenaar_beheert_de_startvragen(db_session, initiatief):
    eenheid = await make_org(db_session, "Eenheid startvragen")
    lid = await make_person(db_session, "Lid startvragen")
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
            json={"startvragen": EIGEN},
        )
    assert resp.status_code in (403, 404), resp.text
    await db_session.refresh(initiatief)
    assert initiatief.startvragen == []


# ---------------------------------------------------------------------------
# Beantwoorden bij de start
# ---------------------------------------------------------------------------


GOED = {
    "casustype": "intern",
    "antwoorden": [
        {"vraag_id": "partner", "waarde": False},
        {"vraag_id": "kanaal", "waarde": "Website"},
        {"vraag_id": "regelingen", "waarde": ["Kinderopvang", "Zorgtoeslag"]},
    ],
}


async def test_start_met_eigen_vragen_legt_een_momentopname_vast(
    client, db_session, initiatief
):
    assert (await _zet(client, initiatief, EIGEN)).status_code == 200
    lead = await _lead(db_session, initiatief)
    resp = await _start(client, lead, GOED)
    assert resp.status_code == 201, resp.text
    sv = resp.json()["startvoorwaarden"]
    assert sv["casustype"] == "intern"
    # De niet-verplichte vrije vraag bleef leeg en staat er niet bij; de
    # keuzes staan in de volgorde van de lijst.
    assert sv["antwoorden"] == [
        {
            "vraag_id": "partner",
            "vraag": "Is er een partner?",
            "antwoordtype": "ja_nee",
            "waarde": False,
        },
        {
            "vraag_id": "kanaal",
            "vraag": "Via welk kanaal kwam hij binnen?",
            "antwoordtype": "een_keuze",
            "waarde": "Website",
        },
        {
            "vraag_id": "regelingen",
            "vraag": "Welke regelingen?",
            "antwoordtype": "meer_keuzes",
            "waarde": ["Zorgtoeslag", "Kinderopvang"],
        },
    ]

    # Een latere wijziging van de vraag laat de casus staan.
    anders = [dict(v) for v in EIGEN]
    anders[1] = {**anders[1], "vraag": "Doet er een partner mee?"}
    assert (await _zet(client, initiatief, anders)).status_code == 200
    casus = (await client.get(f"/api/casussen/{resp.json()['id']}")).json()
    assert casus["startvoorwaarden"]["antwoorden"][0]["vraag"] == "Is er een partner?"


async def test_vrij_antwoord_wordt_bewaard(client, db_session, initiatief):
    assert (await _zet(client, initiatief, EIGEN)).status_code == 200
    lead = await _lead(db_session, initiatief)
    sv = {
        **GOED,
        "antwoorden": [*GOED["antwoorden"], {"vraag_id": "notitie", "waarde": " Ja "}],
    }
    resp = await _start(client, lead, sv)
    assert resp.status_code == 201, resp.text
    notitie = resp.json()["startvoorwaarden"]["antwoorden"][-1]
    assert (notitie["vraag_id"], notitie["waarde"]) == ("notitie", "Ja")


def _zonder(vraag_id):
    return {
        **GOED,
        "antwoorden": [a for a in GOED["antwoorden"] if a["vraag_id"] != vraag_id],
    }


def _met(vraag_id, waarde):
    return {
        **GOED,
        "antwoorden": [
            *[a for a in GOED["antwoorden"] if a["vraag_id"] != vraag_id],
            {"vraag_id": vraag_id, "waarde": waarde},
        ],
    }


@pytest.mark.parametrize(
    "startvoorwaarden",
    [
        # Verplichte vragen niet beantwoord.
        _zonder("kanaal"),
        _met("regelingen", []),
        {**GOED, "casustype": None},
        # Verkeerd type of een keuze die er niet is.
        _met("partner", "ja"),
        _met("kanaal", "Telefoon"),
        _met("regelingen", ["Zorgtoeslag", "Bijstand"]),
        _met("regelingen", "Zorgtoeslag"),
        _met("notitie", True),
        # Een vraag die het initiatief niet stelt, of de vaste vraag als antwoord.
        _met("onbekend", "x"),
        _met("casustype", "Interne casus"),
        # Te lang of te veel.
        _met("notitie", "x" * 5001),
        _met("regelingen", ["Zorgtoeslag"] * 21),
    ],
)
async def test_ongeldige_antwoorden_zijn_422(
    client, db_session, initiatief, startvoorwaarden
):
    assert (await _zet(client, initiatief, EIGEN)).status_code == 200
    lead = await _lead(db_session, initiatief)
    resp = await _start(client, lead, startvoorwaarden)
    assert resp.status_code == 422, resp.text


async def test_zonder_initiatief_alleen_de_vaste_vraag(client, db_session):
    """Zonder initiatief zijn er geen instellingen: alleen intern of satelliet."""
    lead = Lead(id=uuid.uuid4(), title="Los", stage="in_the_pocket")
    db_session.add(lead)
    await db_session.flush()
    resp = await _start(client, lead, {"antwoorden": []})
    assert resp.status_code == 422
    resp = await _start(client, lead, {"casustype": "satelliet"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["startvoorwaarden"]["antwoorden"] == []
