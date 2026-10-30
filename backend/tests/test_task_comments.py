"""Opmerkingen en bijlagen op een taak (het taakdetail).

Dekt: opmerkingen alleen op een taak die je mag zien (task:read, zoals de
taak zelf), verwijderen alleen door auteur of beheerder, melding aan de
toegewezene, en bijlagen uploaden, downloaden en verwijderen.
"""

import uuid

import pytest
from sqlalchemy import select

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
