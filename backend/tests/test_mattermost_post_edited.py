"""Bewerkte Mattermost-posts (``post_edited``).

Aanleiding: iemand postte eerst kort en plakte daarna een hele mailwisseling
in hetzelfde bericht. De bot had alleen de eerste versie gezien en die als
"geen lead" afgedaan; de bewerking kwam nooit binnen.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.lead import Lead
from bouwmeester.models.lead_activity import LeadActivity
from bouwmeester.models.mattermost_channel_link import (
    SCOPE_INITIATIEF,
    SCOPE_LEAD,
    MattermostChannelLink,
)
from bouwmeester.models.mattermost_post_link import MattermostPostLink
from bouwmeester.models.suggested_lead import SuggestedLead
from bouwmeester.services.llm.base import LeadCandidateClassification
from bouwmeester.services.mattermost_ingest_service import MattermostIngestService
from bouwmeester.services.mattermost_websocket_service import (
    MattermostWebsocketService,
)


def _id() -> str:
    return uuid.uuid4().hex[:26]


class FakeMattermostService:
    replies: list[str] = []

    def __init__(self, session):
        self.session = session

    async def is_enabled(self) -> bool:
        return True

    async def reply_to_post(self, channel_id, root_id, message, *, props=None):
        FakeMattermostService.replies.append(message)
        return {"id": _id()}

    async def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _fake_mattermost(monkeypatch):
    FakeMattermostService.replies = []
    monkeypatch.setattr(
        "bouwmeester.services.mattermost_service.MattermostService",
        FakeMattermostService,
    )


@pytest.fixture
async def initiatief_channel(db_session):
    init = Initiatief(id=uuid.uuid4(), naam="Regelrecht")
    db_session.add(init)
    await db_session.flush()
    link = MattermostChannelLink(
        channel_id=_id(),
        channel_name="leads",
        channel_display_name="Leads",
        scope_type=SCOPE_INITIATIEF,
        scope_id=init.id,
        auto_note_enabled=False,
        suggest_leads_enabled=True,
    )
    db_session.add(link)
    await db_session.flush()
    return link


@pytest.fixture
async def lead_channel(db_session):
    init = Initiatief(id=uuid.uuid4(), naam="Regelrecht")
    db_session.add(init)
    await db_session.flush()
    lead = Lead(id=uuid.uuid4(), title="Gemeente X", stage="inbox")
    lead.initiatief_id = init.id
    db_session.add(lead)
    await db_session.flush()
    link = MattermostChannelLink(
        channel_id=_id(),
        channel_name="gemeente-x",
        channel_display_name="Gemeente X",
        scope_type=SCOPE_LEAD,
        scope_id=lead.id,
        auto_note_enabled=True,
        suggest_leads_enabled=False,
    )
    db_session.add(link)
    await db_session.flush()
    return link


def _classify(*answers: bool) -> AsyncMock:
    return AsyncMock(
        side_effect=[
            LeadCandidateClassification(
                is_lead=answer,
                confidence=0.8 if answer else 0.1,
                proposed_title="Vakgroep Architectuur" if answer else "",
                proposed_description="",
                match_existing_lead_id=None,
                reasoning="",
            )
            for answer in answers
        ]
    )


def _llm_patches(classify: AsyncMock):
    fake_llm = AsyncMock()
    fake_llm.classify_mattermost_lead_candidate = classify
    fake_llm.is_mattermost_noise = AsyncMock(return_value=False)
    return (
        patch(
            "bouwmeester.services.llm.factory.get_llm_service_for",
            new=AsyncMock(return_value=fake_llm),
        ),
        patch.object(
            MattermostIngestService,
            "_post_suggestion_reply",
            new=AsyncMock(return_value=None),
        ),
    )


def _post(channel, message: str, *, post_id: str, edit_at: int = 0) -> dict:
    return {
        "id": post_id,
        "channel_id": channel.channel_id,
        "user_id": "collega0000000000000000000",
        "create_at": 1_700_000_000_000,
        "edit_at": edit_at,
        "message": message,
    }


async def _link(db_session, post_id: str) -> MattermostPostLink:
    return (
        await db_session.execute(
            select(MattermostPostLink).where(MattermostPostLink.post_id == post_id)
        )
    ).scalar_one()


async def test_afgewezen_post_wordt_na_bewerking_opnieuw_beoordeeld(
    db_session, initiatief_channel
):
    post_id = _id()
    classify = _classify(False, True)
    p1, p2 = _llm_patches(classify)
    with p1, p2:
        ingest = MattermostIngestService(db_session, bot_user_id="bot")
        await ingest.ingest_post(_post(initiatief_channel, "Hoi!", post_id=post_id))
        assert (await _link(db_session, post_id)).skipped_reason == "no_lead"

        bewerkt = _post(
            initiatief_channel,
            "Hoi! Uitnodiging om te spreken bij de vakgroep Architectuur.",
            post_id=post_id,
            edit_at=1_700_000_100_000,
        )
        await ingest.ingest_edit(bewerkt)

    assert classify.await_count == 2
    assert "vakgroep Architectuur" in classify.await_args.kwargs["message"]
    link = await _link(db_session, post_id)
    assert link.suggested_lead_id is not None
    assert link.skipped_reason is None


async def test_pinnen_zonder_tekstwijziging_doet_niets(db_session, initiatief_channel):
    post_id = _id()
    classify = _classify(False)
    p1, p2 = _llm_patches(classify)
    with p1, p2:
        ingest = MattermostIngestService(db_session, bot_user_id="bot")
        await ingest.ingest_post(_post(initiatief_channel, "Hoi!", post_id=post_id))
        # Pinnen stuurt post_edited zonder edit_at.
        await ingest.ingest_edit(_post(initiatief_channel, "Hoi!", post_id=post_id))

    assert classify.await_count == 1


async def test_dezelfde_bewerking_maar_een_keer(db_session, initiatief_channel):
    post_id = _id()
    classify = _classify(False, False)
    p1, p2 = _llm_patches(classify)
    with p1, p2:
        ingest = MattermostIngestService(db_session, bot_user_id="bot")
        await ingest.ingest_post(_post(initiatief_channel, "Hoi!", post_id=post_id))
        bewerkt = _post(initiatief_channel, "Hoi, nog steeds niks", post_id=post_id)
        bewerkt["edit_at"] = 1_700_000_100_000
        await ingest.ingest_edit(bewerkt)
        # Daarna gepind: zelfde edit_at, opnieuw een post_edited.
        await ingest.ingest_edit(bewerkt)

    assert classify.await_count == 2
    assert FakeMattermostService.replies == []


async def test_open_suggestie_krijgt_de_nieuwe_tekst(db_session, initiatief_channel):
    post_id = _id()
    classify = _classify(True)
    p1, p2 = _llm_patches(classify)
    with p1, p2:
        ingest = MattermostIngestService(db_session, bot_user_id="bot")
        await ingest.ingest_post(
            _post(initiatief_channel, "Gemeente X wil praten", post_id=post_id)
        )
        await ingest.ingest_edit(
            _post(
                initiatief_channel,
                "Gemeente X wil praten over de regelhulp, volgende week",
                post_id=post_id,
                edit_at=1_700_000_100_000,
            )
        )

    assert classify.await_count == 1
    suggested = (await db_session.execute(select(SuggestedLead))).scalar_one()
    assert suggested.raw_text.endswith("volgende week")


async def test_notitie_bij_lead_wordt_bijgewerkt(db_session, lead_channel):
    post_id = _id()
    p1, p2 = _llm_patches(_classify())
    with p1, p2:
        ingest = MattermostIngestService(db_session, bot_user_id="bot")
        await ingest.ingest_post(_post(lead_channel, "Gesprek gehad", post_id=post_id))
        await ingest.ingest_edit(
            _post(
                lead_channel,
                "Gesprek gehad, ze willen een pilot",
                post_id=post_id,
                edit_at=1_700_000_100_000,
            )
        )

    link = await _link(db_session, post_id)
    activity = await db_session.get(LeadActivity, link.lead_activity_id)
    assert "pilot" in activity.content
    assert activity.metadata_["mm_edit_at"] == 1_700_000_100_000


async def test_onbekende_post_wordt_niet_alsnog_opgepikt(
    db_session, initiatief_channel
):
    classify = _classify(True)
    p1, p2 = _llm_patches(classify)
    with p1, p2:
        ingest = MattermostIngestService(db_session, bot_user_id="bot")
        await ingest.ingest_edit(
            _post(initiatief_channel, "Oud bericht", post_id=_id(), edit_at=5)
        )

    assert classify.await_count == 0


async def test_websocket_stuurt_post_edited_door():
    svc = MattermostWebsocketService()
    msg = {
        "event": "post_edited",
        "data": {"post": json.dumps({"id": "p1", "channel_id": "c1", "edit_at": 5})},
    }
    with patch.object(
        MattermostIngestService, "ingest_edit", new=AsyncMock(return_value=None)
    ) as ingest_edit:
        await svc._dispatch(msg)

    assert ingest_edit.await_args.args[0]["id"] == "p1"
