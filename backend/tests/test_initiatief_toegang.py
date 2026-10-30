"""Wie in een initiatief zit, vindt het in het overzicht en kan het openen.

Een vaste regel, voor elke rol en voor wie er via een eenheid in zit: het
initiatief staat in GET /api/initiatieven (de pagina Initiatieven) en
GET /api/initiatieven/{id} geeft 200 met de juiste rol. Wie er niet in zit,
ziet het niet en krijgt 404. Ook de weg die lokaal getest wordt, de
personenkeuze rechtsboven (het cookie bm_dev_person), volgt die regel.
"""

import uuid

import pytest

from bouwmeester.core.auth import DEV_PERSON_COOKIE
from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.resource_permission import ResourcePermission
from tests.factories import client_as, make_org, make_person, place


@pytest.fixture
async def initiatief(db_session):
    init = Initiatief(id=uuid.uuid4(), naam="Regelrecht toegang", slug="rr-toegang")
    db_session.add(init)
    await db_session.flush()
    return init


async def _lid(db_session, initiatief, naam: str, rol: str):
    persoon = await make_person(db_session, naam)
    db_session.add(
        ResourcePermission(
            person_id=persoon.id,
            resource_type="initiatief",
            resource_id=initiatief.id,
            rol=rol,
        )
    )
    await db_session.flush()
    return persoon


async def _zichtbaar(client, initiatief) -> tuple[bool, int, str | None]:
    """(staat in het overzicht, status van het detail, rol in het detail)."""
    lijst = await client.get("/api/initiatieven")
    assert lijst.status_code == 200, lijst.text
    in_lijst = str(initiatief.id) in {i["id"] for i in lijst.json()}
    detail = await client.get(f"/api/initiatieven/{initiatief.id}")
    rol = detail.json().get("access_level") if detail.status_code == 200 else None
    return in_lijst, detail.status_code, rol


@pytest.mark.parametrize("rol", ["eigenaar", "contributor", "viewer"])
async def test_lid_vindt_en_opent_het_initiatief(db_session, initiatief, rol):
    lid = await _lid(db_session, initiatief, f"Lid {rol}", rol)
    async with client_as(db_session, lid) as c:
        assert await _zichtbaar(c, initiatief) == (True, 200, rol)


@pytest.mark.parametrize("rol", ["contributor", "viewer"])
async def test_via_een_eenheid_vindt_en_opent_het_initiatief(
    db_session, initiatief, rol
):
    eenheid = await make_org(db_session, f"Eenheid {rol}")
    persoon = await make_person(db_session, f"Medewerker {rol}")
    await place(db_session, persoon, eenheid)
    db_session.add(
        ResourcePermission(
            organisatie_eenheid_id=eenheid.id,
            resource_type="initiatief",
            resource_id=initiatief.id,
            rol=rol,
        )
    )
    await db_session.flush()
    async with client_as(db_session, persoon) as c:
        in_lijst, status, _ = await _zichtbaar(c, initiatief)
    assert (in_lijst, status) == (True, 200)


async def test_wie_er_niet_in_zit_ziet_het_niet(db_session, initiatief):
    await _lid(db_session, initiatief, "Wel lid", "eigenaar")
    buiten = await make_person(db_session, "Niet lid")
    async with client_as(db_session, buiten) as c:
        assert await _zichtbaar(c, initiatief) == (False, 404, None)


async def test_personenkeuze_rechtsboven_volgt_dezelfde_regel(
    client, db_session, initiatief
):
    """Lokaal kies je rechtsboven een persoon; dat zet het cookie
    bm_dev_person, en dan gelden de rechten van die persoon."""
    eigenaar = await _lid(db_session, initiatief, "Eigenaar keuze", "eigenaar")
    buiten = await make_person(db_session, "Buiten keuze")

    client.cookies.set(DEV_PERSON_COOKIE, str(eigenaar.id))
    assert await _zichtbaar(client, initiatief) == (True, 200, "eigenaar")

    client.cookies.set(DEV_PERSON_COOKIE, str(buiten.id))
    assert await _zichtbaar(client, initiatief) == (False, 404, None)

    # Zonder keuze is alles toegestaan.
    client.cookies.delete(DEV_PERSON_COOKIE)
    in_lijst, status, _ = await _zichtbaar(client, initiatief)
    assert (in_lijst, status) == (True, 200)
