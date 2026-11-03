"""Opmerkingen en bijlagen op een taak (het taakdetail).

Dekt: opmerkingen alleen op een taak die je mag zien (task:read, zoals de
taak zelf), verwijderen alleen door auteur of beheerder, melding aan de
toegewezene, en bijlagen uploaden, downloaden en verwijderen. Een bijlage
verwijdert alleen wie hem plaatste of een beheerder; een taak heeft een
maximum aan bijlagen. Een opmerking noemt een maximum aan mensen, alleen
wie de taak mag zien krijgt een melding, en de vermeldingen gaan mee weg
met de opmerking.
"""

import uuid

import pytest
from sqlalchemy import select

from bouwmeester.models.mention import Mention
from bouwmeester.models.notification import Notification
from bouwmeester.models.task import Task
from tests.factories import client_as, grant_role, make_org, make_person, place


@pytest.fixture
async def taak(db_session, sample_node, sample_person):
    task = Task(
        id=uuid.uuid4(),
        title="Taak",
        node_id=sample_node.id,
        assignee_id=sample_person.id,
    )
    db_session.add(task)
    await db_session.flush()
    return task


async def test_add_and_list_comments(client, db_session, taak, sample_person):
    resp = await client.post(
        f"/api/tasks/{taak.id}/comments", json={"content": "Eerste opmerking"}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["content"] == "Eerste opmerking"
    await client.post(f"/api/tasks/{taak.id}/comments", json={"content": "Tweede"})
    resp = await client.get(f"/api/tasks/{taak.id}/comments")
    assert resp.status_code == 200
    assert [c["content"] for c in resp.json()] == ["Eerste opmerking", "Tweede"]
    # De toegewezene krijgt een melding (de dev-client is niet de toegewezene).
    stmt = select(Notification).where(
        Notification.person_id == sample_person.id,
        Notification.type == "task_comment_added",
    )
    assert len((await db_session.execute(stmt)).scalars().all()) == 2


async def test_empty_comment_is_422(client, taak):
    resp = await client.post(f"/api/tasks/{taak.id}/comments", json={"content": ""})
    assert resp.status_code == 422


async def test_comments_on_unknown_task_is_404(client):
    resp = await client.get(f"/api/tasks/{uuid.uuid4()}/comments")
    assert resp.status_code == 404


async def test_comments_without_task_read_is_403(db_session, taak):
    buitenstaander = await make_person(db_session, "Buitenstaander")
    async with client_as(db_session, buitenstaander) as c:
        resp = await c.get(f"/api/tasks/{taak.id}/comments")
        assert resp.status_code == 403
        resp = await c.post(f"/api/tasks/{taak.id}/comments", json={"content": "x"})
        assert resp.status_code == 403


async def test_delete_comment_only_author_or_admin(client, db_session, taak):
    auteur = await make_person(db_session, "Auteur")
    ander = await make_person(db_session, "Ander")
    eenheid = await make_org(db_session, "Eenheid opmerkingen")
    for p in (auteur, ander):
        await place(db_session, p, eenheid)
        await grant_role(db_session, p, "editor", eenheid)
    async with client_as(db_session, auteur) as c:
        resp = await c.post(f"/api/tasks/{taak.id}/comments", json={"content": "mijn"})
        assert resp.status_code == 201, resp.text
        comment_id = resp.json()["id"]
    async with client_as(db_session, ander) as c:
        resp = await c.delete(f"/api/tasks/{taak.id}/comments/{comment_id}")
        assert resp.status_code == 403
    async with client_as(db_session, auteur) as c:
        resp = await c.delete(f"/api/tasks/{taak.id}/comments/{comment_id}")
        assert resp.status_code == 204
    resp = await client.get(f"/api/tasks/{taak.id}/comments")
    assert resp.json() == []


async def test_attachment_upload_download_delete(client, taak):
    resp = await client.post(
        f"/api/tasks/{taak.id}/attachments",
        files={"file": ("notitie.txt", b"hallo taak", "text/plain")},
    )
    assert resp.status_code == 201, resp.text
    att = resp.json()
    assert att["bestandsnaam"] == "notitie.txt"
    assert att["bestandsgrootte"] == 10
    resp = await client.get(f"/api/tasks/{taak.id}/attachments")
    assert [a["id"] for a in resp.json()] == [att["id"]]
    resp = await client.get(f"/api/tasks/{taak.id}/attachments/{att['id']}/download")
    assert resp.status_code == 200
    assert resp.content == b"hallo taak"
    resp = await client.delete(f"/api/tasks/{taak.id}/attachments/{att['id']}")
    assert resp.status_code == 204
    resp = await client.get(f"/api/tasks/{taak.id}/attachments/{att['id']}/download")
    assert resp.status_code == 404


async def test_attachment_without_task_read_is_403(db_session, taak):
    buitenstaander = await make_person(db_session, "Buitenstaander")
    async with client_as(db_session, buitenstaander) as c:
        resp = await c.post(
            f"/api/tasks/{taak.id}/attachments",
            files={"file": ("x.txt", b"x", "text/plain")},
        )
    assert resp.status_code == 403


async def test_task_delete_removes_attachment_files(
    client, db_session, taak, blob_root
):
    """Een taak verwijderen haalt ook de bijlagebestanden weg, ook van subtaken.

    De rijen gaan via CASCADE mee; de bestanden op schijf moet de route zelf
    opruimen, anders blijven ze voor altijd staan.
    """
    from bouwmeester.models.task import Task

    sub = Task(title="Subtaak", parent_id=taak.id, node_id=taak.node_id)
    db_session.add(sub)
    await db_session.flush()
    for t in (taak, sub):
        resp = await client.post(
            f"/api/tasks/{t.id}/attachments",
            files={"file": ("notitie.txt", b"weg ermee", "text/plain")},
        )
        assert resp.status_code == 201, resp.text
    assert len([p for p in blob_root.rglob("*") if p.is_file()]) == 2

    resp = await client.delete(f"/api/tasks/{taak.id}")
    assert resp.status_code == 204
    assert [p for p in blob_root.rglob("*") if p.is_file()] == []


# ---------------------------------------------------------------------------
# Na de review: verwijderen, maxima en meldingen
# ---------------------------------------------------------------------------


async def _met_rol(db_session, naam, rol, eenheid):
    p = await make_person(db_session, naam)
    await place(db_session, p, eenheid)
    await grant_role(db_session, p, rol, eenheid)
    return p


async def _upload(c, taak, naam="notitie.txt"):
    return await c.post(
        f"/api/tasks/{taak.id}/attachments",
        files={"file": (naam, b"inhoud", "text/plain")},
    )


async def test_bijlage_verwijdert_alleen_wie_hem_plaatste_of_een_beheerder(
    client, db_session, taak
):
    eenheid = await make_org(db_session, "Eenheid bijlagen")
    plaatser = await _met_rol(db_session, "Plaatser", "editor", eenheid)
    kijker = await _met_rol(db_session, "Kijker", "viewer", eenheid)

    async with client_as(db_session, plaatser) as c:
        resp = await _upload(c, taak)
        assert resp.status_code == 201, resp.text
        att = resp.json()
        assert att["uploaded_by_id"] == str(plaatser.id)
        tweede = (await _upload(c, taak, "tweede.txt")).json()

    # Wie alleen mag kijken, ziet de bijlage wel maar haalt hem niet weg.
    async with client_as(db_session, kijker) as c:
        lijst = await c.get(f"/api/tasks/{taak.id}/attachments")
        assert att["id"] in {a["id"] for a in lijst.json()}
        resp = await c.delete(f"/api/tasks/{taak.id}/attachments/{att['id']}")
        assert resp.status_code == 403

    async with client_as(db_session, plaatser) as c:
        resp = await c.delete(f"/api/tasks/{taak.id}/attachments/{att['id']}")
        assert resp.status_code == 204
    # Een beheerder mag het ook.
    resp = await client.delete(f"/api/tasks/{taak.id}/attachments/{tweede['id']}")
    assert resp.status_code == 204


async def test_taak_heeft_een_maximum_aan_bijlagen(client, taak, monkeypatch):
    from bouwmeester.api.routes import task_comments

    monkeypatch.setattr(task_comments, "MAX_BIJLAGEN_PER_TAAK", 2)
    for naam in ("een.txt", "twee.txt"):
        assert (await _upload(client, taak, naam)).status_code == 201
    resp = await _upload(client, taak, "drie.txt")
    assert resp.status_code == 400
    assert "hooguit 2 bijlagen" in resp.json()["detail"]


async def test_opmerking_noemt_een_maximum_aan_mensen(
    client, db_session, taak, monkeypatch
):
    from bouwmeester.api.routes import task_comments

    monkeypatch.setattr(task_comments, "MAX_GENOEMDEN", 2)
    mensen = [await make_person(db_session, f"Genoemd {i}") for i in range(3)]

    def noem(personen):
        return " ".join(f"[@{p.naam}](user:{p.id})" for p in personen)

    url = f"/api/tasks/{taak.id}/comments"
    resp = await client.post(url, json={"content": noem(mensen)})
    assert resp.status_code == 400
    resp = await client.post(url, json={"content": noem(mensen[:2])})
    assert resp.status_code == 201, resp.text


async def test_melding_alleen_voor_wie_de_taak_mag_zien(client, db_session, taak):
    eigen = await make_org(db_session, "Eigen eenheid")
    andere = await make_org(db_session, "Andere eenheid")
    taak.organisatie_eenheid_id = eigen.id
    await db_session.flush()
    collega = await _met_rol(db_session, "Collega", "editor", eigen)
    elders = await _met_rol(db_session, "Elders", "editor", andere)
    zonder_rol = await make_person(db_session, "Zonder rol")

    tekst = " ".join(f"[@{p.naam}](user:{p.id})" for p in (collega, elders, zonder_rol))
    resp = await client.post(f"/api/tasks/{taak.id}/comments", json={"content": tekst})
    assert resp.status_code == 201, resp.text

    async def meldingen(p):
        stmt = select(Notification).where(
            Notification.person_id == p.id, Notification.type == "mention"
        )
        return (await db_session.execute(stmt)).scalars().all()

    assert len(await meldingen(collega)) == 1
    assert await meldingen(elders) == []
    assert await meldingen(zonder_rol) == []


async def test_vermeldingen_gaan_mee_weg_met_de_opmerking(client, db_session, taak):
    genoemd = await make_person(db_session, "Genoemd")
    resp = await client.post(
        f"/api/tasks/{taak.id}/comments",
        json={"content": f"Zie [@Genoemd](user:{genoemd.id})"},
    )
    assert resp.status_code == 201, resp.text
    cid = uuid.UUID(resp.json()["id"])

    async def vermeldingen():
        stmt = select(Mention).where(
            Mention.source_type == "task_comment", Mention.source_id == cid
        )
        return (await db_session.execute(stmt)).scalars().all()

    assert len(await vermeldingen()) == 1
    resp = await client.delete(f"/api/tasks/{taak.id}/comments/{cid}")
    assert resp.status_code == 204
    assert await vermeldingen() == []
