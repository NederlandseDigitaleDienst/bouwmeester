"""Tests for archiving the channel of a debate that is long over and quiet.

Against a real database for the sessies, with Mattermost as a fake that
holds per channel when something was last said and whether it is archived,
and the TK API as a fake that says where each activiteit stands now.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from bouwmeester.models.debat_sessie import DebatSessie
from bouwmeester.services import debat_channel_cleanup as mod
from bouwmeester.services import tk_activiteit
from bouwmeester.services.debat_channel_cleanup import DebateChannelCleanup
from bouwmeester.services.tk_activiteit import Activiteit, TkApiError

NOW = datetime(2026, 12, 20, 9, 0, tzinfo=UTC)


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


class Mattermost:
    def __init__(self) -> None:
        self.channels: dict[str, dict] = {}
        self.posts: dict[str, list[str]] = {}
        self.archived: list[str] = []
        self.deleted: list[str] = []
        self.fail_archive = 0
        self.unreadable: set[str] = set()
        self.reads = 0

    def channel(self, channel_id: str, last_post: datetime) -> None:
        self.channels[channel_id] = {
            "id": channel_id,
            "last_post_at": _ms(last_post),
            "delete_at": 0,
        }
        self.posts[channel_id] = []

    async def is_enabled(self) -> bool:
        return True

    async def get_channel(self, channel_id):
        self.reads += 1
        if channel_id in self.unreadable:
            return None
        return dict(self.channels[channel_id])

    async def send_channel_message(self, channel_id, text, props=None, root_id=None):
        post_id = f"post{uuid.uuid4().hex}"[:26]
        self.posts[channel_id].append(post_id)
        return post_id

    async def delete_post(self, post_id) -> bool:
        for posts in self.posts.values():
            if post_id in posts:
                posts.remove(post_id)
        self.deleted.append(post_id)
        return True

    async def archive_channel(self, channel_id) -> bool:
        if self.fail_archive:
            self.fail_archive -= 1
            return False
        self.channels[channel_id]["delete_at"] = _ms(NOW)
        self.archived.append(channel_id)
        return True

    async def close(self) -> None:
        return None


def _activiteit(activiteit_id: str, **overrides) -> Activiteit:
    values = {
        "id": activiteit_id,
        "nummer": "2026A00001",
        "soort": "Plenair debat",
        "onderwerp": "Een voorbeelddebat",
        "aanvang": NOW - timedelta(days=40),
        "einde": None,
        "status": "Uitgevoerd",
        "commissie": None,
        "bewindspersonen": (),
        "agendapunten": (),
    }
    values.update(overrides)
    return Activiteit(**values)


@pytest.fixture(autouse=True)
def _fresh():
    mod.reset()
    yield
    mod.reset()


@pytest.fixture
def tk(monkeypatch):
    """Per activiteit id what the TK API says now; absent is as set up."""
    known: dict[str, Activiteit | None | Exception] = {}

    async def fetch(activiteit_id, client, base_url=None):
        found = known.get(activiteit_id, _activiteit(activiteit_id))
        if isinstance(found, Exception):
            raise found
        return found

    monkeypatch.setattr(tk_activiteit, "fetch_activiteit", fetch)
    return known


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
    return sessie


async def _tick(db_session, mm, at: datetime = NOW):
    return await DebateChannelCleanup(db_session, mm).tick(at, client=object())


async def _marked(db_session, sessie) -> datetime | None:
    return (
        await db_session.execute(
            select(DebatSessie.kanaal_gearchiveerd_at).where(
                DebatSessie.id == sessie.id
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
class TestCleanup:
    async def test_a_quiet_channel_of_an_old_debate_is_archived(self, db_session, tk):
        mm = Mattermost()
        sessie = await _sessie(
            db_session, mm, began=timedelta(days=40), quiet=timedelta(days=20)
        )
        result = await _tick(db_session, mm)
        assert mm.archived == [sessie.channel_id]
        assert len(mm.posts[sessie.channel_id]) == 1
        assert result.archived == 1
        assert await _marked(db_session, sessie) == NOW

    async def test_a_channel_where_people_still_talk_stays(self, db_session, tk):
        mm = Mattermost()
        await _sessie(db_session, mm, began=timedelta(days=40), quiet=timedelta(days=3))
        await _tick(db_session, mm)
        assert mm.archived == []

    async def test_a_recent_debate_stays_however_quiet(self, db_session, tk):
        mm = Mattermost()
        await _sessie(
            db_session, mm, began=timedelta(days=20), quiet=timedelta(days=19)
        )
        await _tick(db_session, mm)
        assert mm.archived == []

    async def test_a_debate_moved_to_later_keeps_its_channel(self, db_session, tk):
        mm = Mattermost()
        sessie = await _sessie(
            db_session, mm, began=timedelta(days=40), quiet=timedelta(days=20)
        )
        later = str(uuid.uuid4())
        tk[sessie.activiteit_id] = _activiteit(
            sessie.activiteit_id,
            status=tk_activiteit.STATUS_MOVED,
            vervangen_door=(later,),
        )
        tk[later] = _activiteit(later, aanvang=NOW + timedelta(days=5))
        await _tick(db_session, mm)
        assert mm.archived == []
        assert mm.posts[sessie.channel_id] == []

    async def test_a_debate_moved_long_ago_is_over(self, db_session, tk):
        mm = Mattermost()
        sessie = await _sessie(
            db_session, mm, began=timedelta(days=60), quiet=timedelta(days=20)
        )
        later = str(uuid.uuid4())
        tk[sessie.activiteit_id] = _activiteit(
            sessie.activiteit_id,
            status=tk_activiteit.STATUS_MOVED,
            vervangen_door=(later,),
        )
        tk[later] = _activiteit(later, aanvang=NOW - timedelta(days=35))
        await _tick(db_session, mm)
        assert mm.archived == [sessie.channel_id]

    async def test_a_debate_moved_without_saying_where_waits(self, db_session, tk):
        mm = Mattermost()
        sessie = await _sessie(
            db_session, mm, began=timedelta(days=40), quiet=timedelta(days=20)
        )
        tk[sessie.activiteit_id] = _activiteit(
            sessie.activiteit_id, status=tk_activiteit.STATUS_MOVED
        )
        await _tick(db_session, mm)
        assert mm.archived == []

    async def test_a_cancelled_debate_is_over(self, db_session, tk):
        mm = Mattermost()
        sessie = await _sessie(
            db_session, mm, began=timedelta(days=40), quiet=timedelta(days=20)
        )
        tk[sessie.activiteit_id] = _activiteit(
            sessie.activiteit_id,
            status=tk_activiteit.STATUS_CANCELLED,
            aanvang=NOW + timedelta(days=5),
        )
        await _tick(db_session, mm)
        assert mm.archived == [sessie.channel_id]

    async def test_without_the_tk_api_the_channel_waits(self, db_session, tk):
        mm = Mattermost()
        sessie = await _sessie(
            db_session, mm, began=timedelta(days=40), quiet=timedelta(days=20)
        )
        tk[sessie.activiteit_id] = TkApiError("weg")
        result = await _tick(db_session, mm)
        assert mm.archived == []
        assert result.errors == 0

    async def test_a_refused_archiving_takes_its_message_away_and_waits_a_day(
        self, db_session, tk
    ):
        mm = Mattermost()
        sessie = await _sessie(
            db_session, mm, began=timedelta(days=40), quiet=timedelta(days=20)
        )
        mm.fail_archive = 1
        result = await _tick(db_session, mm)
        assert mm.archived == []
        assert mm.posts[sessie.channel_id] == []
        assert len(mm.deleted) == 1
        assert result.errors == 1

        # An hour later: not tried again.
        await _tick(db_session, mm, NOW + timedelta(hours=1))
        assert mm.archived == []
        assert len(mm.deleted) == 1

        # A day later: archived, with one message.
        await _tick(db_session, mm, NOW + timedelta(days=1))
        assert mm.archived == [sessie.channel_id]
        assert len(mm.posts[sessie.channel_id]) == 1

    async def test_a_channel_once_archived_is_not_looked_at_again(self, db_session, tk):
        mm = Mattermost()
        sessie = await _sessie(
            db_session, mm, began=timedelta(days=40), quiet=timedelta(days=20)
        )
        await _tick(db_session, mm)
        reads = mm.reads

        # An admin brings it back; it stays quiet.
        mm.channels[sessie.channel_id]["delete_at"] = 0
        await _tick(db_session, mm, NOW + timedelta(days=30))
        assert mm.archived == [sessie.channel_id]
        assert mm.reads == reads

    async def test_a_channel_archived_by_someone_else_is_marked(self, db_session, tk):
        mm = Mattermost()
        sessie = await _sessie(
            db_session, mm, began=timedelta(days=40), quiet=timedelta(days=20)
        )
        mm.channels[sessie.channel_id]["delete_at"] = _ms(NOW - timedelta(days=1))
        await _tick(db_session, mm)
        assert mm.archived == []
        assert mm.posts[sessie.channel_id] == []
        assert await _marked(db_session, sessie) == NOW

    async def test_an_unreadable_channel_is_left_for_the_next_round(
        self, db_session, tk
    ):
        mm = Mattermost()
        sessie = await _sessie(
            db_session, mm, began=timedelta(days=40), quiet=timedelta(days=20)
        )
        mm.unreadable.add(sessie.channel_id)
        await _tick(db_session, mm)
        assert mm.archived == []
        assert await _marked(db_session, sessie) is None

    async def test_debates_long_ago_are_not_looked_at(self, db_session, tk):
        mm = Mattermost()
        await _sessie(
            db_session, mm, began=timedelta(days=200), quiet=timedelta(days=150)
        )
        result = await _tick(db_session, mm)
        assert mm.archived == []
        assert result.checked == 0
