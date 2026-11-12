"""Tests for archiving the channel of a debate that is long over and quiet.

Against a real database for the sessies, with Mattermost as a fake that
holds per channel when something was last said and whether it is archived.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from bouwmeester.models.debat_sessie import DebatSessie
from bouwmeester.services import debat_kanaal_opruimen as mod
from bouwmeester.services.debat_kanaal_opruimen import DebatKanaalOpruimen

NOW = datetime(2026, 12, 20, 9, 0, tzinfo=UTC)


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


class Mattermost:
    def __init__(self) -> None:
        # Per channel: last_post_at in ms, and delete_at.
        self.channels: dict[str, dict] = {}
        self.posts: dict[str, list[dict]] = {}
        self.archived: list[str] = []
        self.fail_archive = 0
        self.unreadable: set[str] = set()

    def channel(self, channel_id: str, last_post: datetime) -> None:
        self.channels[channel_id] = {
            "id": channel_id,
            "last_post_at": _ms(last_post),
            "delete_at": 0,
        }
        self.posts[channel_id] = [{"create_at": _ms(last_post), "props": {}}]

    async def is_enabled(self) -> bool:
        return True

    async def get_channel(self, channel_id):
        if channel_id in self.unreadable:
            return None
        return dict(self.channels[channel_id])

    async def send_channel_message(self, channel_id, text, props=None, root_id=None):
        at = _ms(NOW)
        self.posts[channel_id].append(
            {"create_at": at, "props": props or {}, "message": text}
        )
        self.channels[channel_id]["last_post_at"] = at
        return f"post{uuid.uuid4().hex}"[:26]

    async def get_channel_posts_since(self, channel_id, since, *, per_page=60):
        return [p for p in self.posts[channel_id] if p["create_at"] > since]

    async def archive_channel(self, channel_id) -> bool:
        if self.fail_archive:
            self.fail_archive -= 1
            return False
        self.channels[channel_id]["delete_at"] = _ms(NOW)
        self.archived.append(channel_id)
        return True

    async def close(self) -> None:
        return None


async def _sessie(db_session, mm: Mattermost, *, began: timedelta, quiet: timedelta):
    channel_id = f"chan{uuid.uuid4().hex}"[:26]
    sessie = DebatSessie(
        activiteit_id=str(uuid.uuid4()),
        activiteit_nummer="2026A00001",
        onderwerp="Een voorbeelddebat",
        aanvang=NOW - began,
        team_id="team00000000000000000000aa",
        channel_id=channel_id,
        channel_name=f"debat-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(sessie)
    await db_session.flush()
    mm.channel(channel_id, NOW - quiet)
    return channel_id


async def _tick(db_session, mm):
    return await DebatKanaalOpruimen(db_session, mm).tick(NOW)


@pytest.mark.asyncio
class TestOpruimen:
    async def test_a_quiet_channel_of_an_old_debate_is_archived(self, db_session):
        mm = Mattermost()
        channel = await _sessie(
            db_session, mm, began=timedelta(days=40), quiet=timedelta(days=20)
        )
        result = await _tick(db_session, mm)
        assert mm.archived == [channel]
        assert result.archived == 1
        [notice] = [p for p in mm.posts[channel] if p["props"].get(mod.PROP)]
        assert "wordt gearchiveerd" in notice["message"]

    async def test_a_channel_where_people_still_talk_stays(self, db_session):
        mm = Mattermost()
        await _sessie(db_session, mm, began=timedelta(days=40), quiet=timedelta(days=3))
        await _tick(db_session, mm)
        assert mm.archived == []

    async def test_a_recent_debate_stays_however_quiet(self, db_session):
        mm = Mattermost()
        await _sessie(
            db_session, mm, began=timedelta(days=20), quiet=timedelta(days=19)
        )
        await _tick(db_session, mm)
        assert mm.archived == []

    async def test_an_archived_channel_is_left_alone(self, db_session):
        mm = Mattermost()
        channel = await _sessie(
            db_session, mm, began=timedelta(days=40), quiet=timedelta(days=20)
        )
        mm.channels[channel]["delete_at"] = _ms(NOW - timedelta(days=1))
        await _tick(db_session, mm)
        assert mm.archived == []
        assert len(mm.posts[channel]) == 1

    async def test_a_failed_archiving_is_tried_again_without_a_second_notice(
        self, db_session
    ):
        mm = Mattermost()
        channel = await _sessie(
            db_session, mm, began=timedelta(days=40), quiet=timedelta(days=20)
        )
        mm.fail_archive = 1
        await _tick(db_session, mm)
        assert mm.archived == []

        await _tick(db_session, mm)
        assert mm.archived == [channel]
        notices = [p for p in mm.posts[channel] if p["props"].get(mod.PROP)]
        assert len(notices) == 1

    async def test_an_unreadable_channel_is_left_for_the_next_round(self, db_session):
        mm = Mattermost()
        channel = await _sessie(
            db_session, mm, began=timedelta(days=40), quiet=timedelta(days=20)
        )
        mm.unreadable.add(channel)
        await _tick(db_session, mm)
        assert mm.archived == []
        assert len(mm.posts[channel]) == 1

    async def test_debates_long_ago_are_not_looked_at(self, db_session):
        mm = Mattermost()
        await _sessie(
            db_session, mm, began=timedelta(days=200), quiet=timedelta(days=150)
        )
        result = await _tick(db_session, mm)
        assert mm.archived == []
        assert result.checked == 0
