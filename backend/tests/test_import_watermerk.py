"""The watermark of a feed import survives a restart of the worker.

It lived in the memory of the worker only. A restart put it back to "now",
and what appeared between the last round and the restart was never
imported. The restart is played here by emptying the module's watermark,
which is all a new process differs in.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bouwmeester.models.import_watermerk import ImportWatermerk
from bouwmeester.services import parlementair_import_service as mod
from bouwmeester.services.import_strategies import nieuws as nieuws_strategie
from bouwmeester.services.import_strategies import tkconv as tkconv_strategie
from bouwmeester.services.import_strategies.nieuws import NieuwsStrategy
from bouwmeester.services.import_strategies.registry import get_strategy
from bouwmeester.services.import_strategies.tkconv import TkconvSearchStrategy
from bouwmeester.services.parlementair_import_service import (
    MAX_ACHTERSTAND,
    ParlementairImportService,
)

BRON = "tkconv_document"


@pytest.fixture(autouse=True)
def _nieuw_proces():
    tkconv_strategie.reset_watermerk()
    nieuws_strategie.reset_watermerk()
    yield
    tkconv_strategie.reset_watermerk()
    nieuws_strategie.reset_watermerk()


async def _bewaard(session: AsyncSession, bron: str = BRON) -> datetime | None:
    return await session.scalar(
        select(ImportWatermerk.tijdstip)
        .where(ImportWatermerk.bron == bron)
        .execution_options(populate_existing=True)
    )


async def _zet(session: AsyncSession, tijdstip: datetime, bron: str = BRON) -> None:
    rij = await session.get(ImportWatermerk, bron)
    if rij is None:
        session.add(ImportWatermerk(bron=bron, tijdstip=tijdstip))
    else:
        rij.tijdstip = tijdstip
    await session.flush()


class TestNaEenHerstart:
    async def test_the_strategy_goes_on_where_the_process_before_it_was(
        self, db_session
    ):
        """The case that cost alerts: a document of 17:58, a restart at
        17:59. The new process must look from the last round on, not from
        its own start."""
        laatste_ronde = datetime.now(UTC) - timedelta(minutes=10)
        await _zet(db_session, laatste_ronde)
        strategy = TkconvSearchStrategy()

        await ParlementairImportService(db_session)._herstel_watermerk(strategy)

        assert tkconv_strategie.huidig_watermerk() == laatste_ronde
        # And that is the threshold the next round uses.
        assert strategy._drempel(None) == laatste_ronde

    async def test_without_anything_kept_it_starts_at_now_as_before(self, db_session):
        rij = await db_session.get(ImportWatermerk, BRON)
        if rij is not None:
            await db_session.delete(rij)
            await db_session.flush()
        strategy = TkconvSearchStrategy()

        await ParlementairImportService(db_session)._herstel_watermerk(strategy)

        assert tkconv_strategie.huidig_watermerk() is None
        assert datetime.now(UTC) - strategy._drempel(None) < timedelta(seconds=5)

    async def test_not_further_back_than_the_feed_carries(self, db_session):
        """A worker that was off for a month does not open with a month of
        alerts."""
        await _zet(db_session, datetime.now(UTC) - timedelta(days=30))

        await ParlementairImportService(db_session)._herstel_watermerk(
            TkconvSearchStrategy()
        )

        achter = datetime.now(UTC) - tkconv_strategie.huidig_watermerk()
        # The clock moves on between the two readings of it.
        assert abs(achter - MAX_ACHTERSTAND) < timedelta(seconds=5)
        assert timedelta(days=7) == MAX_ACHTERSTAND

    async def test_a_process_that_is_running_keeps_its_own(self, db_session):
        eigen = datetime.now(UTC) - timedelta(minutes=1)
        tkconv_strategie.herstel_watermerk(eigen)
        await _zet(db_session, datetime.now(UTC) - timedelta(hours=5))

        await ParlementairImportService(db_session)._herstel_watermerk(
            TkconvSearchStrategy()
        )

        assert tkconv_strategie.huidig_watermerk() == eigen

    async def test_news_has_a_watermark_of_its_own(self, db_session):
        tkconv = datetime.now(UTC) - timedelta(hours=3)
        nieuws = datetime.now(UTC) - timedelta(hours=1)
        await _zet(db_session, tkconv)
        await _zet(db_session, nieuws, "nieuwsartikel")
        service = ParlementairImportService(db_session)

        await service._herstel_watermerk(NieuwsStrategy())

        assert nieuws_strategie.huidig_watermerk() == nieuws
        assert tkconv_strategie.huidig_watermerk() is None

    async def test_the_row_is_keyed_on_the_item_type_of_the_strategy(self):
        assert TkconvSearchStrategy().item_type == BRON
        assert NieuwsStrategy().item_type == "nieuwsartikel"

    async def test_a_strategy_without_a_feed_is_left_alone(self, db_session):
        strategy = get_strategy("motie")
        service = ParlementairImportService(db_session)

        await service._herstel_watermerk(strategy)
        await service._bewaar_watermerk(strategy)

        assert mod._watermerk_module(strategy) is None

    async def test_a_database_that_fails_leaves_the_round_alone(
        self, db_session, monkeypatch
    ):
        service = ParlementairImportService(db_session)

        async def kapot(*args, **kwargs):
            raise RuntimeError("database weg")

        monkeypatch.setattr(service.session, "scalar", kapot)
        monkeypatch.setattr(service.session, "execute", kapot)

        await service._herstel_watermerk(TkconvSearchStrategy())
        tkconv_strategie.herstel_watermerk(datetime.now(UTC))
        await service._bewaar_watermerk(TkconvSearchStrategy())

        # No exception reached the round.


class TestNaEenRonde:
    async def test_where_the_round_got_to_is_kept(self, db_session):
        tot = datetime.now(UTC) - timedelta(minutes=2)
        tkconv_strategie.herstel_watermerk(tot)

        await ParlementairImportService(db_session)._bewaar_watermerk(
            TkconvSearchStrategy()
        )

        assert await _bewaard(db_session) == tot

    async def test_it_moves_on_with_every_round(self, db_session):
        service = ParlementairImportService(db_session)
        eerst = datetime.now(UTC) - timedelta(hours=1)
        await _zet(db_session, eerst)
        later = eerst + timedelta(minutes=30)
        tkconv_strategie.herstel_watermerk(later)

        await service._bewaar_watermerk(TkconvSearchStrategy())

        assert await _bewaard(db_session) == later

    async def test_it_never_goes_back(self, db_session):
        """Two workers during a deploy: the old one, further behind, writes
        last."""
        verder = datetime.now(UTC) - timedelta(minutes=1)
        await _zet(db_session, verder)
        tkconv_strategie.herstel_watermerk(verder - timedelta(hours=2))

        await ParlementairImportService(db_session)._bewaar_watermerk(
            TkconvSearchStrategy()
        )

        assert await _bewaard(db_session) == verder

    async def test_a_round_before_the_first_watermark_keeps_nothing(self, db_session):
        voor = await _bewaard(db_session)

        await ParlementairImportService(db_session)._bewaar_watermerk(
            TkconvSearchStrategy()
        )

        assert await _bewaard(db_session) == voor

    async def test_a_restart_between_two_rounds_loses_nothing(self, db_session):
        """Round, restart, round: the second starts where the first ended."""
        service = ParlementairImportService(db_session)
        eerste_ronde = datetime.now(UTC) - timedelta(minutes=4)
        tkconv_strategie.herstel_watermerk(eerste_ronde)
        await service._bewaar_watermerk(TkconvSearchStrategy())

        tkconv_strategie.reset_watermerk()  # the deploy
        strategy = TkconvSearchStrategy()
        await ParlementairImportService(db_session)._herstel_watermerk(strategy)

        assert strategy._drempel(None) == eerste_ronde
