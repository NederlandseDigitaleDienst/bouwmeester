"""Een mention in een thread laat de bot de hele thread beoordelen.

Aanleiding: iemand plakte een uitnodiging om te komen spreken in een thread
en vroeg daaronder "@bouwmeester zie je deze niet?". De bot beoordeelde
alleen die vraag, vond daar geen lead in en zei dat ook. Wie de bot in een
thread aanspreekt, wijst naar de thread.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from bouwmeester.models.initiatief import Initiatief
from bouwmeester.models.mattermost_channel_link import (
    SCOPE_INITIATIEF,
    MattermostChannelLink,
)
from bouwmeester.services.llm.base import LeadCandidateClassification
from bouwmeester.services.llm.prompts import build_classify_mattermost_lead_prompt
from bouwmeester.services.mattermost_ingest_service import MattermostIngestService

BOT_ID = "botuserid0000000000000000a"
BOT = "bouwmeester"


def _id() -> str:
    return uuid.uuid4().hex[:26]


class FakeMattermostService:
    thread: list[dict] = []
    replies: list[str] = []

    def __init__(self, session):
        self.session = session

    async def is_enabled(self) -> bool:
        return True

    async def get_post_thread(self, post_id):
        return list(FakeMattermostService.thread)

    async def get_username(self, user_id):
        return f"user-{user_id[:4]}"

    async def reply_to_post(self, channel_id, root_id, message, *, props=None):
        FakeMattermostService.replies.append(message)
        return {"id": _id()}

    async def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _fake_mattermost(monkeypatch):
    FakeMattermostService.thread = []
    FakeMattermostService.replies = []
    monkeypatch.setattr(
        "bouwmeester.services.mattermost_service.MattermostService",
        FakeMattermostService,
    )


@pytest.fixture
async def channel(db_session):
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


def _classification(is_lead: bool, reasoning: str = "") -> LeadCandidateClassification:
    return LeadCandidateClassification(
        is_lead=is_lead,
        confidence=0.8 if is_lead else 0.1,
        proposed_title="Vakgroep Architectuur" if is_lead else "",
        proposed_description="",
        match_existing_lead_id=None,
        reasoning=reasoning,
    )


async def _ingest_mention(db_session, channel, classify: AsyncMock) -> None:
    fake_llm = AsyncMock()
    fake_llm.classify_mattermost_lead_candidate = classify
    root_id = _id()
    collega = _id()
    FakeMattermostService.thread = [
        {
            "id": root_id,
            "user_id": collega,
            "create_at": 1000,
            "message": "Uitnodiging om te spreken bij de vakgroep Architectuur.",
        },
        {"id": _id(), "user_id": BOT_ID, "create_at": 1500, "message": "Gezien."},
        {"id": _id(), "user_id": collega, "create_at": 1800, "message": ""},
        {
            "id": "mentionpost0000000000000aa",
            "user_id": collega,
            "create_at": 2000,
            "message": "@bouwmeester zie je deze niet?",
        },
        {"id": _id(), "user_id": collega, "create_at": 3000, "message": "later"},
    ]
    post = {
        "id": "mentionpost0000000000000aa",
        "channel_id": channel.channel_id,
        "root_id": root_id,
        "user_id": collega,
        "create_at": 2000,
        "message": "@bouwmeester zie je deze niet?",
    }
    ingest = MattermostIngestService(db_session, bot_user_id=BOT_ID, bot_username=BOT)
    with (
        patch(
            "bouwmeester.services.llm.factory.get_llm_service_for",
            new=AsyncMock(return_value=fake_llm),
        ),
        patch.object(
            MattermostIngestService,
            "_post_suggestion_reply",
            new=AsyncMock(return_value=None),
        ),
    ):
        await ingest.ingest_post(post)


async def test_mention_in_thread_beoordeelt_de_thread(db_session, channel):
    classify = AsyncMock(return_value=_classification(True))
    await _ingest_mention(db_session, channel, classify)

    kwargs = classify.await_args.kwargs
    assert kwargs["explicit_request"] is True
    text = kwargs["message"]
    assert "vakgroep Architectuur" in text
    assert "zie je deze niet?" in text
    # Bot-bevestigingen en posts ná de mention horen er niet in.
    assert "Gezien." not in text
    assert "later" not in text
    assert text.index("vakgroep") < text.index("zie je deze niet?")


async def test_geen_lead_noemt_de_reden(db_session, channel):
    classify = AsyncMock(
        return_value=_classification(False, "Alleen interne planning.")
    )
    await _ingest_mention(db_session, channel, classify)

    assert len(FakeMattermostService.replies) == 1
    reply = FakeMattermostService.replies[0]
    assert "geen nieuwe lead in (Alleen interne planning)" in reply


async def test_thread_onbereikbaar_valt_terug_op_bericht(
    db_session, channel, monkeypatch
):
    async def no_thread(self, post_id):
        return []

    monkeypatch.setattr(FakeMattermostService, "get_post_thread", no_thread)
    classify = AsyncMock(return_value=_classification(True))
    await _ingest_mention(db_session, channel, classify)

    assert classify.await_args.kwargs["message"] == "@bouwmeester zie je deze niet?"


def test_prompt_expliciete_vraag_verlaagt_drempel():
    gewoon = build_classify_mattermost_lead_prompt(
        message="x",
        initiatief_naam="Regelrecht",
        channel_display_name="Leads",
        recent_leads=[],
    )
    expliciet = build_classify_mattermost_lead_prompt(
        message="x",
        initiatief_naam="Regelrecht",
        channel_display_name="Leads",
        recent_leads=[],
        explicit_request=True,
    )
    assert "Bij twijfel" in gewoon
    assert "Bij twijfel" not in expliciet
    assert "ook bij twijfel" in expliciet
    # Een uitnodiging om te spreken telt in beide gevallen als lead.
    for prompt in (gewoon, expliciet):
        assert "spreken of presenteren" in prompt
