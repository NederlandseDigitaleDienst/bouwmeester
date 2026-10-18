"""A kamerstuk the model could not judge is tried again, and then alerted.

When the call to the model failed while a document came in, the document
was stored as `pending`: no summary, no node, no alert, "to be done
later". Nothing did it later, and the row made every next round skip the
document as already imported. So it waited for good and nobody was told.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from bouwmeester.models.parlementair_item import ParlementairItem
from bouwmeester.services.import_strategies.registry import get_strategy
from bouwmeester.services.import_strategies.tkconv import TkconvSearchStrategy
from bouwmeester.services.llm.base import TagExtractionResult
from bouwmeester.services.parlementair_import_service import (
    WACHTENDEN_OPNIEUW_TOT,
    WACHTENDEN_PER_RONDE,
    ParlementairImportService,
)

LLM = "bouwmeester.services.parlementair_import_service.get_llm_service"


def _abonnement(term: str = "voorbeeldterm"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        term=term,
        ingehaald_op=datetime.now(UTC),
        zoekopdracht=lambda: f'"{term}"',
    )


def _strategy(*abonnementen) -> TkconvSearchStrategy:
    strategy = TkconvSearchStrategy()
    strategy.abonnementen = list(abonnementen)
    strategy.treffers = {}
    strategy.verse_abonnementen = set()
    return strategy


async def _wachtend(
    session,
    *,
    term: str = "voorbeeldterm",
    status: str = "pending",
    soort: str = "tkconv_document",
    oud: timedelta = timedelta(hours=3),
) -> ParlementairItem:
    nummer = f"2030D{uuid.uuid4().hex[:6]}"
    rij = ParlementairItem(
        type=soort,
        zaak_id=nummer,
        zaak_nummer=nummer,
        titel="Verslag houdende een lijst van vragen",
        onderwerp="Lijst van vragen over een voorbeeldbegroting",
        bron="tweede_kamer",
        datum=date(2030, 1, 15),
        status=status,
        document_tekst="Een vraag over de voorbeeldterm en de middelen daarvoor.",
        document_url="https://voorbeeld.example/document",
        extra_data={"herkomst": "tkconv", "matched_terms": [f'"{term}"']},
        created_at=datetime.now(UTC) - oud,
    )
    session.add(rij)
    await session.flush()
    return rij


def _service(session) -> ParlementairImportService:
    service = ParlementairImportService(session)
    # The rows of the search terms are not in this database; which term
    # brought a document in is all these tests need.
    service.abonnement_repo = SimpleNamespace(
        registreer_treffers=AsyncMock(return_value=1)
    )
    service._te_alerteren = []
    service._inhaalslag = {}
    return service


def _werkend_model():
    model = AsyncMock()
    model.extract_tags.return_value = TagExtractionResult(
        matched_tags=[], suggested_new_tags=[], samenvatting="Waar het over gaat."
    )
    return model


def _kapot_model():
    model = AsyncMock()
    model.extract_tags.side_effect = Exception("model onbereikbaar")
    return model


async def _lees(session, zaak_id: str) -> ParlementairItem | None:
    return (
        await session.execute(
            select(ParlementairItem)
            .where(ParlementairItem.zaak_id == zaak_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


class TestWatErOpnieuwGaat:
    async def test_a_waiting_document_of_a_followed_term_is_taken_along(
        self, db_session
    ):
        rij = await _wachtend(db_session)
        abonnement = _abonnement()
        strategy = _strategy(abonnement)
        service = _service(db_session)

        items = await service._wachtenden(strategy, set())

        eigen = [i for i in items if i.zaak_id == rij.zaak_id]
        assert len(eigen) == 1
        assert eigen[0].document_tekst == rij.document_tekst
        assert eigen[0].titel == rij.titel
        assert eigen[0].extra_data["matched_terms"] == ['"voorbeeldterm"']
        # Which term brought it in, for the summary and for the alert.
        assert strategy.treffers[rij.zaak_id] == [abonnement.id]
        assert rij.zaak_id in service._opnieuw

    async def test_a_term_that_is_no_longer_followed_is_left(self, db_session):
        rij = await _wachtend(db_session, term="niet meer gevolgd")
        service = _service(db_session)

        items = await service._wachtenden(_strategy(_abonnement()), set())

        assert rij.zaak_id not in {i.zaak_id for i in items}
        assert rij.zaak_id not in service._opnieuw

    async def test_what_waited_longer_than_the_feed_carries_is_left(self, db_session):
        rij = await _wachtend(
            db_session, oud=WACHTENDEN_OPNIEUW_TOT + timedelta(hours=1)
        )
        service = _service(db_session)

        items = await service._wachtenden(_strategy(_abonnement()), set())

        assert rij.zaak_id not in {i.zaak_id for i in items}
        assert timedelta(days=7) == WACHTENDEN_OPNIEUW_TOT

    async def test_only_what_waits(self, db_session):
        rij = await _wachtend(db_session, status="imported")
        service = _service(db_session)

        items = await service._wachtenden(_strategy(_abonnement()), set())

        assert rij.zaak_id not in {i.zaak_id for i in items}

    async def test_only_documents_of_a_search_term(self, db_session):
        rij = await _wachtend(db_session, soort="toezegging")
        service = _service(db_session)

        assert await service._wachtenden(get_strategy("toezegging"), set()) == []
        items = await service._wachtenden(_strategy(_abonnement()), set())
        assert rij.zaak_id not in {i.zaak_id for i in items}

    async def test_a_few_a_round_the_oldest_first(self, db_session):
        term = f"term-{uuid.uuid4().hex[:6]}"
        rijen = [
            await _wachtend(db_session, term=term, oud=timedelta(minutes=10 * n))
            for n in range(1, WACHTENDEN_PER_RONDE + 4)
        ]
        service = _service(db_session)

        items = await service._wachtenden(_strategy(_abonnement(term)), set())

        assert len(items) <= WACHTENDEN_PER_RONDE
        eigen = [i.zaak_id for i in items if i.zaak_id in {r.zaak_id for r in rijen}]
        # Whatever else waits in this database: of these, older goes first.
        volgorde = [r.zaak_id for r in reversed(rijen)]
        assert eigen == [z for z in volgorde if z in eigen]

    async def test_one_the_feed_brought_along_again_is_not_taken_twice(
        self, db_session
    ):
        rij = await _wachtend(db_session)
        service = _service(db_session)

        items = await service._wachtenden(_strategy(_abonnement()), {rij.zaak_id})

        assert rij.zaak_id not in {i.zaak_id for i in items}
        # But the copy from the feed may replace the row that waits.
        assert rij.zaak_id in service._opnieuw


class TestOpnieuwBeoordelen:
    async def test_once_the_model_answers_it_is_imported_and_alerted(self, db_session):
        rij = await _wachtend(db_session)
        strategy = _strategy(_abonnement())
        service = _service(db_session)
        (item,) = [
            i
            for i in await service._wachtenden(strategy, set())
            if i.zaak_id == rij.zaak_id
        ]

        with patch(LLM, new=AsyncMock(return_value=_werkend_model())):
            resultaat = await service._process_item(item, strategy)

        assert resultaat is True
        nu = await _lees(db_session, rij.zaak_id)
        assert nu.status == "imported"
        assert nu.llm_samenvatting == "Waar het over gaat."
        assert nu.corpus_node_id is not None
        # This is what was missing: the alert goes out after the commit.
        assert service._te_alerteren == [nu.id]

    async def test_a_model_that_fails_again_leaves_it_waiting_since_when_it_came(
        self, db_session
    ):
        rij = await _wachtend(db_session, oud=timedelta(days=2))
        kwam_binnen = rij.created_at
        strategy = _strategy(_abonnement())
        service = _service(db_session)
        (item,) = [
            i
            for i in await service._wachtenden(strategy, set())
            if i.zaak_id == rij.zaak_id
        ]

        with patch(LLM, new=AsyncMock(return_value=_kapot_model())):
            resultaat = await service._process_item(item, strategy)

        assert resultaat is False
        nu = await _lees(db_session, rij.zaak_id)
        assert nu.status == "pending"
        # Not from today: otherwise it would be tried for ever.
        assert nu.created_at == kwam_binnen
        assert service._te_alerteren == []

    async def test_a_waiting_document_that_is_not_up_for_it_is_skipped_as_before(
        self, db_session
    ):
        rij = await _wachtend(db_session)
        strategy = _strategy(_abonnement())
        service = _service(db_session)
        item = SimpleNamespace(zaak_id=rij.zaak_id, zaak_nummer=rij.zaak_nummer)
        model = _werkend_model()

        with patch(LLM, new=AsyncMock(return_value=model)):
            resultaat = await service._process_item(item, strategy)

        assert resultaat is False
        model.extract_tags.assert_not_awaited()
        assert (await _lees(db_session, rij.zaak_id)).status == "pending"

    async def test_a_document_that_was_imported_is_never_done_again(self, db_session):
        rij = await _wachtend(db_session, status="imported")
        strategy = _strategy(_abonnement())
        service = _service(db_session)
        service._opnieuw = {rij.zaak_id}
        item = SimpleNamespace(zaak_id=rij.zaak_id, zaak_nummer=rij.zaak_nummer)
        model = _werkend_model()

        with patch(LLM, new=AsyncMock(return_value=model)):
            resultaat = await service._process_item(item, strategy)

        assert resultaat is False
        model.extract_tags.assert_not_awaited()
        nu = await _lees(db_session, rij.zaak_id)
        assert (nu.id, nu.status) == (rij.id, "imported")
