"""De koelkast op de RegelReis.

Dekt:
- een casus in de koelkast zetten met reden en verwachte datum; de fase
  blijft staan;
- zonder reden of datum: 422; een datum in het verleden: 422;
- bijwerken in de koelkast houdt koelkast_sinds;
- uit de koelkast haalt alles weg, de fase blijft; nog eens is geen fout;
- een kijker mag de casus niet wijzigen en dus ook niet in de koelkast: 403.
"""

import uuid
from datetime import date, timedelta

import pytest

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
