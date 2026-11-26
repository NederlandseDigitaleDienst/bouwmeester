"""De koelkast op de RegelReis.

Dekt:
- een casus in de koelkast zetten met reden en verwachte datum; de fase
  blijft staan;
- zonder reden of datum: 422; een datum in het verleden: 422;
- bijwerken in de koelkast houdt koelkast_sinds;
- uit de koelkast haalt alles weg, de fase blijft; nog eens is geen fout;
- in de koelkast staat de fase vast: een andere fase is 409, behalve met
  uit_koelkast, dan gaat hij in één wijziging eruit en naar die fase (ook met
  de eindeisen); faalt die wijziging, dan blijft hij in de koelkast;
- een fase weghalen waar een casus in de koelkast in staat: de 409 zegt dat
  hij in de koelkast staat;
- de database weigert een koelkast zonder reden of datum (ck_casus_koelkast);
- een kijker mag de casus niet wijzigen en dus ook niet in de koelkast: 403;
  een trekker die op het initiatief alleen kijker is, mag het wel;
- wie het initiatief niet ziet, krijgt 404 en ziet niet dat de casus bestaat
  (de toegangsregel uit test_casus_toegang.py, hier voor de koelkast).
"""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from bouwmeester.models.activity import Activity
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.resource_permission import ResourcePermission
from bouwmeester.repositories.lead_column import LeadColumnRepository
from tests.factories import START_INTERN, client_as, make_person


@pytest.fixture
async def initiatief(db_session):
    init = Initiatief(
        id=uuid.uuid4(), naam="Koelkast", slug="rr-koelkast", casussen_enabled=True
    )
    db_session.add(init)
    await db_session.flush()
    await LeadColumnRepository(db_session).seed_defaults(init.id)
    return init


@pytest.fixture
async def casus(client, db_session, initiatief):
    lead = Lead(
        id=uuid.uuid4(),
        title="Casus",
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
    c = resp.json()
    assert (
        await client.put(f"/api/casussen/{c['id']}", json={"fase": "uitvoeren"})
    ).status_code == 200
    return c


def _url(casus):
    return f"/api/casussen/{casus['id']}/koelkast"


MORGEN = (date.today() + timedelta(days=30)).isoformat()


async def test_in_en_uit_de_koelkast(client, casus):
    resp = await client.put(
        _url(casus),
        json={"reden": " Partner heeft geen tijd ", "verwacht_terug": MORGEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["koelkast_sinds"]
    assert body["koelkast_reden"] == "Partner heeft geen tijd"
    assert body["koelkast_verwacht_terug"] == MORGEN
    assert body["fase"] == "uitvoeren"
    sinds = body["koelkast_sinds"]

    # Bijwerken houdt het moment waarop hij erin ging.
    later = (date.today() + timedelta(days=60)).isoformat()
    resp = await client.put(
        _url(casus), json={"reden": "Na de zomer", "verwacht_terug": later}
    )
    assert resp.json()["koelkast_sinds"] == sinds
    assert resp.json()["koelkast_verwacht_terug"] == later

    # In de lijst ook.
    lijst = (
        await client.get(f"/api/casussen?initiatief_id={body['initiatief_id']}")
    ).json()
    assert [c["koelkast_reden"] for c in lijst if c["id"] == casus["id"]] == [
        "Na de zomer"
    ]

    resp = await client.delete(_url(casus))
    assert resp.status_code == 200
    body = resp.json()
    assert body["koelkast_sinds"] is None
    assert body["koelkast_reden"] is None
    assert body["koelkast_verwacht_terug"] is None
    assert body["fase"] == "uitvoeren"
    # Nog eens: niets te doen, geen fout.
    assert (await client.delete(_url(casus))).status_code == 200


@pytest.mark.parametrize(
    "data",
    [
        {"verwacht_terug": MORGEN},
        {"reden": "", "verwacht_terug": MORGEN},
        {"reden": "   ", "verwacht_terug": MORGEN},
        {"reden": "Waarom"},
        {
            "reden": "Waarom",
            "verwacht_terug": (date.today() - timedelta(days=1)).isoformat(),
        },
    ],
)
async def test_reden_en_toekomstige_datum_verplicht(client, casus, data):
    resp = await client.put(_url(casus), json=data)
    assert resp.status_code == 422
    assert (await client.get(f"/api/casussen/{casus['id']}")).json()[
        "koelkast_sinds"
    ] is None


async def test_kijker_zet_niets_in_de_koelkast(client, db_session, initiatief, casus):
    kijker = await make_person(db_session, "Kijker")
    db_session.add(
        ResourcePermission(
            person_id=kijker.id,
            resource_type="initiatief",
            resource_id=initiatief.id,
            rol="viewer",
        )
    )
    await db_session.flush()
    async with client_as(db_session, kijker) as c:
        resp = await c.put(
            _url(casus), json={"reden": "Waarom", "verwacht_terug": MORGEN}
        )
        assert resp.status_code == 403
        assert (await c.delete(_url(casus))).status_code == 403


async def test_buitenstaander_ziet_geen_koelkast(client, db_session, casus):
    buiten = await make_person(db_session, "Buitenstaander")
    async with client_as(db_session, buiten) as c:
        resp = await c.put(
            _url(casus), json={"reden": "Waarom", "verwacht_terug": MORGEN}
        )
        assert resp.status_code == 404
        assert (await c.delete(_url(casus))).status_code == 404
    assert (await client.get(f"/api/casussen/{casus['id']}")).json()[
        "koelkast_sinds"
    ] is None


async def _in_koelkast(client, casus):
    resp = await client.put(
        _url(casus), json={"reden": "Partner heeft geen tijd", "verwacht_terug": MORGEN}
    )
    assert resp.status_code == 200, resp.text


async def test_fase_staat_vast_in_de_koelkast(client, casus):
    await _in_koelkast(client, casus)
    url = f"/api/casussen/{casus['id']}"

    resp = await client.put(url, json={"fase": "afronden"})
    assert resp.status_code == 409
    assert "koelkast" in resp.json()["detail"]
    body = (await client.get(url)).json()
    assert body["fase"] == "uitvoeren"
    assert body["koelkast_sinds"] is not None

    # De fase die hij al heeft, en andere gegevens, kunnen wel.
    resp = await client.put(url, json={"fase": "uitvoeren", "title": "Andere titel"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["koelkast_sinds"] is not None


async def test_uit_de_koelkast_naar_een_fase_in_een_wijziging(
    client, db_session, casus
):
    await _in_koelkast(client, casus)
    url = f"/api/casussen/{casus['id']}"
    # Zoals het afrondvenster het doet: fase, eindeisen en uit de koelkast.
    resp = await client.put(
        url, json={"fase": "afronden", "eind_eisen": [], "uit_koelkast": True}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fase"] == "afronden"
    assert body["koelkast_sinds"] is None
    assert body["koelkast_reden"] is None
    assert body["koelkast_verwacht_terug"] is None

    soorten = (
        await db_session.scalars(
            select(Activity.event_type).where(
                Activity.event_type.in_(["casus.koelkast_uit", "casus.updated"])
            )
        )
    ).all()
    assert soorten.count("casus.koelkast_uit") == 1
    assert "casus.updated" in soorten

    # Niet in de koelkast: uit_koelkast doet dan niets extra.
    resp = await client.put(url, json={"fase": "delen", "uit_koelkast": True})
    assert resp.status_code == 200
    assert resp.json()["fase"] == "delen"


async def test_mislukte_wijziging_laat_de_casus_in_de_koelkast(client, casus):
    await _in_koelkast(client, casus)
    url = f"/api/casussen/{casus['id']}"
    resp = await client.put(url, json={"fase": "bestaat-niet", "uit_koelkast": True})
    assert resp.status_code == 400
    eis = {"soort_id": str(uuid.uuid4()), "eis": "Onbekend", "akkoord": True}
    resp = await client.put(
        url, json={"fase": "afronden", "eind_eisen": [eis], "uit_koelkast": True}
    )
    assert resp.status_code == 422
    body = (await client.get(url)).json()
    assert body["fase"] == "uitvoeren"
    assert body["koelkast_reden"] == "Partner heeft geen tijd"


async def test_fase_weghalen_noemt_de_koelkast(client, initiatief, casus):
    await _in_koelkast(client, casus)
    zonder_uitvoeren = [
        {"id": "start", "naam": "Start", "kleur": "lintblauw"},
        {"id": "klaar", "naam": "Klaar", "kleur": "mosgroen"},
    ]
    resp = await client.put(
        f"/api/initiatieven/{initiatief.id}/settings",
        json={"casus_fases": zonder_uitvoeren},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "uitvoeren (1 in de koelkast)" in detail
    assert "Sleep hem vanuit de koelkast" in detail


async def test_database_weigert_koelkast_zonder_reden_of_datum(db_session, casus):
    for zet in [
        "koelkast_sinds = now()",
        "koelkast_sinds = now(), koelkast_reden = 'Waarom'",
        "koelkast_sinds = now(), koelkast_verwacht_terug = current_date",
        "koelkast_sinds = now(), koelkast_reden = '  ',"
        " koelkast_verwacht_terug = current_date",
        "koelkast_reden = 'Waarom', koelkast_verwacht_terug = current_date",
    ]:
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await db_session.execute(
                    text(f"UPDATE casus SET {zet} WHERE id = :id"),  # noqa: S608
                    {"id": casus["id"]},
                )
    # Alle drie gevuld kan wel.
    async with db_session.begin_nested():
        await db_session.execute(
            text(
                "UPDATE casus SET koelkast_sinds = now(), koelkast_reden = 'Waarom',"
                " koelkast_verwacht_terug = current_date WHERE id = :id"
            ),
            {"id": casus["id"]},
        )


async def test_trekker_die_kijker_is_mag_de_koelkast(
    client, db_session, initiatief, casus
):
    trekker = await make_person(db_session, "Trekker")
    db_session.add_all(
        [
            ResourcePermission(
                person_id=trekker.id,
                resource_type="initiatief",
                resource_id=initiatief.id,
                rol="viewer",
            ),
            ResourcePermission(
                person_id=trekker.id,
                resource_type="casus",
                resource_id=uuid.UUID(casus["id"]),
                rol="trekker",
            ),
        ]
    )
    await db_session.flush()
    async with client_as(db_session, trekker) as c:
        resp = await c.put(
            _url(casus), json={"reden": "Waarom", "verwacht_terug": MORGEN}
        )
        assert resp.status_code == 200, resp.text
        resp = await c.put(
            f"/api/casussen/{casus['id']}",
            json={"fase": "afronden", "uit_koelkast": True},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["koelkast_sinds"] is None
