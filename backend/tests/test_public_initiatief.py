"""Tests for the unauthenticated public initiatief endpoint.

This is the only unauth route in the system; the 404-on-private logic is a
deliberate security decision (do not leak existence). Regressions here are
silent, so test thoroughly.
"""

import uuid
from datetime import UTC, datetime


async def _create_initiatief(
    db_session,
    *,
    naam: str,
    slug: str | None,
    public: bool = False,
):
    from bouwmeester.models.initiatief import Initiatief
    from bouwmeester.repositories.lead_column import LeadColumnRepository

    init = Initiatief(
        id=uuid.uuid4(),
        naam=naam,
        slug=slug,
        beschrijving=f"Beschrijving van {naam}",
        kleur="#3B82F6",
        public_page_enabled=public,
    )
    db_session.add(init)
    await db_session.flush()
    # Seed de 7 default-kolommen zodat de publieke pagina casuses kan tonen
    # (LeadColumn.is_public_visible filtert nu wat zichtbaar is, ipv een
    # hardcoded slug-lijst).
    await LeadColumnRepository(db_session).seed_defaults(init.id)
    return init


async def _create_update(
    db_session,
    *,
    initiatief_id: uuid.UUID,
    titel: str,
    body: str | None = "Body",
    published: bool = False,
):
    from bouwmeester.models.initiatief_update import InitiatiefUpdatePost

    post = InitiatiefUpdatePost(
        id=uuid.uuid4(),
        initiatief_id=initiatief_id,
        titel=titel,
        body=body,
        published_at=datetime.now(UTC) if published else None,
    )
    db_session.add(post)
    await db_session.flush()
    return post


async def test_public_initiatief_404_for_unknown_slug(client):
    resp = await client.get("/api/public/initiatieven/by-slug/onbestaand")
    assert resp.status_code == 404


async def test_public_initiatief_404_when_disabled(client, db_session):
    await _create_initiatief(db_session, naam="Privé", slug="prive-test", public=False)
    resp = await client.get("/api/public/initiatieven/by-slug/prive-test")
    assert resp.status_code == 404, (
        "moet 404 geven, niet 403, om bestaan niet te lekken"
    )


async def test_public_initiatief_returns_only_safe_fields(client, db_session):
    init = await _create_initiatief(
        db_session, naam="Publiek RR", slug="publiek-rr", public=True
    )
    resp = await client.get("/api/public/initiatieven/by-slug/publiek-rr")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "naam": "Publiek RR",
        "slug": "publiek-rr",
        "beschrijving": "Beschrijving van Publiek RR",
        "kleur": "#3B82F6",
        "updates": [],
        "casussen": [],
        "beantwoorde_vragen": [],
        "afgeronde_casussen": [],
    }
    # Geen interne velden in de response
    for forbidden in (
        "id",
        "funnel_enabled",
        "public_page_enabled",
        "score_strategisch_label",
        "score_politiek_label",
        "score_positie_label",
        "created_by_id",
        "created_at",
        "updated_at",
    ):
        assert forbidden not in data, f"{forbidden} mag niet in publieke response"
    # Geen lead-data
    assert "leads" not in data
    assert init.id  # silence lint


async def test_public_initiatief_only_published_updates(client, db_session):
    init = await _create_initiatief(db_session, naam="Mix", slug="mix", public=True)
    await _create_update(
        db_session,
        initiatief_id=init.id,
        titel="Concept (geheim)",
        body="<script>alert(1)</script>",
        published=False,
    )
    await _create_update(
        db_session,
        initiatief_id=init.id,
        titel="Gepubliceerd",
        body="Hallo wereld",
        published=True,
    )
    resp = await client.get("/api/public/initiatieven/by-slug/mix")
    assert resp.status_code == 200
    updates = resp.json()["updates"]
    assert len(updates) == 1
    assert updates[0]["titel"] == "Gepubliceerd"
    titles = {u["titel"] for u in updates}
    assert "Concept (geheim)" not in titles, "drafts mogen niet lekken"
    # Update-shape check: alleen veilige velden
    update = updates[0]
    for forbidden in ("id", "initiatief_id", "created_at", "updated_at"):
        assert forbidden not in update


async def test_public_initiatief_disable_flips_to_404(client, db_session):
    init = await _create_initiatief(
        db_session, naam="Toggle", slug="toggle", public=True
    )
    resp = await client.get("/api/public/initiatieven/by-slug/toggle")
    assert resp.status_code == 200
    init.public_page_enabled = False
    await db_session.flush()
    resp = await client.get("/api/public/initiatieven/by-slug/toggle")
    assert resp.status_code == 404


async def _create_lead(
    db_session,
    *,
    initiatief_id: uuid.UUID,
    title: str,
    stage: str = "eerste_gesprek",
    public_visible: bool = False,
    public_title: str | None = None,
    public_summary: str | None = None,
):
    from bouwmeester.models.lead import Lead

    lead = Lead(
        id=uuid.uuid4(),
        title=title,
        stage=stage,
        initiatief_id=initiatief_id,
        public_visible=public_visible,
        public_title=public_title,
        public_summary=public_summary,
    )
    db_session.add(lead)
    await db_session.flush()
    return lead


async def test_casussen_only_visible_when_opted_in(client, db_session):
    init = await _create_initiatief(
        db_session, naam="Casus-test", slug="casus-test", public=True
    )
    # Lead met public_visible=true en public_title gezet — moet verschijnen
    await _create_lead(
        db_session,
        initiatief_id=init.id,
        title="INTERN: gemeente Utrecht — pilot stagneert",
        stage="follow_up",
        public_visible=True,
        public_title="Pilot Gemeente Utrecht",
        public_summary="We werken samen met Utrecht aan een pilot voor X.",
    )
    # Lead met public_visible=false — moet onzichtbaar blijven, ook als
    # public_title gezet is
    await _create_lead(
        db_session,
        initiatief_id=init.id,
        title="INTERN: amsterdam",
        public_visible=False,
        public_title="Amsterdam (mag niet lekken)",
    )
    # Lead met public_visible=true maar geen public_title — moet onzichtbaar
    await _create_lead(
        db_session,
        initiatief_id=init.id,
        title="INTERN: niets ingevuld",
        public_visible=True,
        public_title=None,
    )

    resp = await client.get("/api/public/initiatieven/by-slug/casus-test")
    assert resp.status_code == 200
    casussen = resp.json()["casussen"]
    assert len(casussen) == 1
    assert casussen[0] == {
        "titel": "Pilot Gemeente Utrecht",
        "samenvatting": "We werken samen met Utrecht aan een pilot voor X.",
        "updates": [],
    }
    # Internal title mag nooit lekken
    body_text = resp.text
    assert "INTERN" not in body_text
    assert "mag niet lekken" not in body_text


async def test_casussen_hidden_in_inactive_stages(client, db_session):
    init = await _create_initiatief(
        db_session, naam="Stages", slug="stages", public=True
    )
    for stage in ("inbox", "verkennen", "koelkast"):
        await _create_lead(
            db_session,
            initiatief_id=init.id,
            title=f"INTERN: {stage}",
            stage=stage,
            public_visible=True,
            public_title=f"Casus in {stage}",
        )
    resp = await client.get("/api/public/initiatieven/by-slug/stages")
    assert resp.status_code == 200
    assert resp.json()["casussen"] == []


async def test_casussen_response_shape_no_extra_lead_fields(client, db_session):
    init = await _create_initiatief(db_session, naam="Shape", slug="shape", public=True)
    await _create_lead(
        db_session,
        initiatief_id=init.id,
        title="INTERN",
        stage="interne_check",
        public_visible=True,
        public_title="Mijn casus",
        public_summary="Korte samenvatting",
    )
    resp = await client.get("/api/public/initiatieven/by-slug/shape")
    casus = resp.json()["casussen"][0]
    # Strikt: alleen titel + samenvatting + (lege) updates-feed.
    assert set(casus.keys()) == {"titel", "samenvatting", "updates"}
    for forbidden in (
        "id",
        "initiatief_id",
        "stage",
        "title",
        "description",
        "assignee_id",
        "score_strategisch",
        "engagement_type",
    ):
        assert forbidden not in casus


async def _create_lead_update(
    db_session,
    *,
    lead_id: uuid.UUID,
    titel: str,
    body_internal: str | None = "Interne tekst (mag NIET lekken)",
    body_public: str | None = "Korte publieke samenvatting",
    published: bool = False,
    mail_subject: str | None = "geheim onderwerp",
    mail_to: list[str] | None = None,
):
    from bouwmeester.models.lead_update import LeadUpdatePost

    post = LeadUpdatePost(
        id=uuid.uuid4(),
        lead_id=lead_id,
        titel=titel,
        body_internal=body_internal,
        body_public=body_public,
        mail_subject=mail_subject,
        mail_to=mail_to or ["intern@team.nl"],
        published_at=datetime.now(UTC) if published else None,
    )
    db_session.add(post)
    await db_session.flush()
    return post


async def test_casus_published_updates_visible(client, db_session):
    init = await _create_initiatief(
        db_session, naam="Met updates", slug="met-updates", public=True
    )
    lead = await _create_lead(
        db_session,
        initiatief_id=init.id,
        title="INTERN",
        stage="eerste_gesprek",
        public_visible=True,
        public_title="Mijn casus",
        public_summary="Korte samenvatting",
    )
    await _create_lead_update(
        db_session, lead_id=lead.id, titel="Update 1", published=True
    )
    await _create_lead_update(
        db_session, lead_id=lead.id, titel="Concept (mag niet lekken)", published=False
    )

    resp = await client.get("/api/public/initiatieven/by-slug/met-updates")
    assert resp.status_code == 200
    casus = resp.json()["casussen"][0]
    assert len(casus["updates"]) == 1, "alleen gepubliceerde updates mogen lekken"
    update = casus["updates"][0]
    assert update["titel"] == "Update 1"
    assert update["body_public"] == "Korte publieke samenvatting"
    # Internal/mail-velden mogen nooit in de publieke response zitten.
    assert "body_internal" not in update
    assert "mail_subject" not in update
    assert "mail_to" not in update


async def test_casus_updates_skip_those_without_body_public(client, db_session):
    init = await _create_initiatief(
        db_session, naam="No body", slug="no-body", public=True
    )
    lead = await _create_lead(
        db_session,
        initiatief_id=init.id,
        title="INTERN",
        stage="eerste_gesprek",
        public_visible=True,
        public_title="Casus",
    )
    await _create_lead_update(
        db_session,
        lead_id=lead.id,
        titel="Wel intern, geen publieke tekst",
        body_public=None,
        published=True,
    )
    resp = await client.get("/api/public/initiatieven/by-slug/no-body")
    casus = resp.json()["casussen"][0]
    assert casus["updates"] == []
