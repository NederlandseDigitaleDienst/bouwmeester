"""Shared builders for people, eenheden, placements and roles in tests.

Tests use these instead of their own ``_make_person`` / ``_make_org``
copies.  ``make_org`` writes both parent sources (``parent_id`` and the
temporal ``OrganisatieEenheidParent``) so tests exercise the same tree the
application reads.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.core.auth import get_optional_user
from bouwmeester.core.database import get_db
from bouwmeester.models.org_naam import OrganisatieEenheidNaam
from bouwmeester.models.org_parent import OrganisatieEenheidParent
from bouwmeester.models.organisatie_eenheid import OrganisatieEenheid
from bouwmeester.models.person import Person
from bouwmeester.models.person_email import PersonEmail
from bouwmeester.models.person_organisatie import PersonOrganisatieEenheid
from bouwmeester.models.role import PersonRole

YESTERDAY = date.today() - timedelta(days=1)

# Antwoorden op de standaard-startvragen (schema/startvragen.py), voor tests
# die een casus starten.
START_INTERN = {
    "casustype": "intern",
    "antwoorden": [
        {"vraag_id": "schakels", "waarde": ["Regelbeheer"]},
    ],
}


async def make_person(db: AsyncSession, naam: str, *, account: bool = True) -> Person:
    """A person with one email; ``account`` gives them a login (oidc_subject)."""
    uid = uuid.uuid4()
    email = f"{naam.lower().replace(' ', '-')}-{uid.hex[:8]}@example.com"
    person = Person(
        id=uid,
        naam=naam,
        email=email,
        functie="tester",
        is_active=True,
        oidc_subject=f"sub-{uid.hex}" if account else None,
        oidc_email=email if account else None,
    )
    db.add(person)
    await db.flush()
    db.add(PersonEmail(person_id=person.id, email=email, is_default=True))
    await db.flush()
    return person


async def make_org(
    db: AsyncSession,
    naam: str,
    type_: str = "directie",
    parent: OrganisatieEenheid | None = None,
) -> OrganisatieEenheid:
    org = OrganisatieEenheid(
        id=uuid.uuid4(),
        naam=naam,
        type=type_,
        parent_id=parent.id if parent else None,
    )
    db.add(org)
    await db.flush()
    db.add(OrganisatieEenheidNaam(eenheid_id=org.id, naam=naam, geldig_van=YESTERDAY))
    if parent is not None:
        db.add(
            OrganisatieEenheidParent(
                eenheid_id=org.id, parent_id=parent.id, geldig_van=YESTERDAY
            )
        )
    await db.flush()
    return org


async def place(db: AsyncSession, person: Person, org: OrganisatieEenheid) -> None:
    db.add(
        PersonOrganisatieEenheid(
            person_id=person.id,
            organisatie_eenheid_id=org.id,
            start_datum=YESTERDAY,
        )
    )
    await db.flush()


async def grant_role(
    db: AsyncSession,
    person: Person,
    role_id: str,
    org: OrganisatieEenheid | None = None,
) -> PersonRole:
    role = PersonRole(
        person_id=person.id,
        role_id=role_id,
        organisatie_eenheid_id=org.id if org else None,
        start_datum=YESTERDAY,
    )
    db.add(role)
    await db.flush()
    return role


@asynccontextmanager
async def client_as(db: AsyncSession, person: Person | None):
    """An API client acting as *person*, with real permission resolution.

    Only the current user is overridden; permission, org and initiatief
    contexts are built from the database like in production.
    """
    from bouwmeester.core.app import create_app

    app = create_app()

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_optional_user] = lambda: person
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer test"},
    ) as client:
        yield client
