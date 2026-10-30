"""Toegang tot een casus: alleen voor wie het initiatief kan zien.

- Trekker en teamlid komen alleen uit wie het initiatief kan zien: direct
  lid of via een gekoppelde eenheid (anders 400).
- De kandidatenlijst van een initiatief laat zien waarom iemand erbij hoort,
  en is buiten het initiatief niet te vinden (404).
- Dat een casus zelf buiten het initiatief onvindbaar is, staat in
  test_casus.py. De regels voor taken in een casus volgen met het werk op
  de casus.
"""

import uuid

import pytest

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
    init = Initiatief(id=uuid.uuid4(), naam="Regelrecht toegang", slug="rr-toegang")
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
        f"/api/casussen/{casus['id']}/team",
        json={"person_id": str(collega.id), "rol": "teamlid"},
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
