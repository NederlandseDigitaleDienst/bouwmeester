"""Tests for import strategy pattern, registry, and new strategies."""

import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock

import pytest

from bouwmeester.services.import_strategies.base import FetchedItem
from bouwmeester.services.import_strategies.kamervraag import KamervraagStrategy
from bouwmeester.services.import_strategies.motie import MotieStrategy
from bouwmeester.services.import_strategies.nieuws import NieuwsStrategy
from bouwmeester.services.import_strategies.registry import (
    STRATEGIES,
    get_all_strategies,
    get_strategy,
)
from bouwmeester.services.import_strategies.tkconv import TkconvSearchStrategy
from bouwmeester.services.import_strategies.toezegging import ToezeggingStrategy
from bouwmeester.services.tk_api_client import (
    MotieData,
    ToezeggingData,
    TweedeKamerClient,
    ZaakData,
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_all_strategies_registered(self):
        assert "motie" in STRATEGIES
        assert "kamervraag" in STRATEGIES
        assert "toezegging" in STRATEGIES
        assert "nieuwsartikel" in STRATEGIES

    def test_get_strategy_motie(self):
        s = get_strategy("motie")
        assert isinstance(s, MotieStrategy)

    def test_get_strategy_kamervraag(self):
        s = get_strategy("kamervraag")
        assert isinstance(s, KamervraagStrategy)

    def test_get_strategy_toezegging(self):
        s = get_strategy("toezegging")
        assert isinstance(s, ToezeggingStrategy)

    def test_get_strategy_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown item type"):
            get_strategy("onbekend")

    def test_get_all_strategies(self):
        """Elke geregistreerde sleutel levert zijn eigen strategie op.

        Geen telling: die moest bij elke nieuwe bron worden bijgewerkt en
        faalde dan met "assert 5 == 4", wat niets zegt over wat er mis is.
        Dat de registry en `STRATEGIES` dezelfde sleutels dragen, is wat
        deze test hoort te bewaken.
        """
        all_s = get_all_strategies()
        assert set(all_s) == set(STRATEGIES)
        assert isinstance(all_s["motie"], MotieStrategy)
        assert isinstance(all_s["kamervraag"], KamervraagStrategy)
        assert isinstance(all_s["toezegging"], ToezeggingStrategy)
        assert isinstance(all_s["tkconv_document"], TkconvSearchStrategy)
        assert isinstance(all_s["nieuwsartikel"], NieuwsStrategy)


# ---------------------------------------------------------------------------
# MotieStrategy
# ---------------------------------------------------------------------------


class TestMotieStrategy:
    def setup_method(self):
        self.strategy = MotieStrategy()

    def test_item_type(self):
        assert self.strategy.item_type == "motie"

    def test_politieke_input_type(self):
        assert self.strategy.politieke_input_type == "motie"

    def test_requires_llm(self):
        assert self.strategy.requires_llm is True

    def test_task_title(self):
        item = FetchedItem(
            zaak_id="z1",
            zaak_nummer="36200-VII-42",
            titel="Test",
            onderwerp="Digitale overheid",
        )
        assert "motie" in self.strategy.task_title(item).lower()
        assert "Digitale overheid" in self.strategy.task_title(item)

    def test_notification_title(self):
        title = self.strategy.notification_title("Test motie")
        assert "motie" in title.lower()

    @pytest.mark.anyio
    async def test_fetch_items_from_tk_client(self):
        mock_client = AsyncMock(spec=TweedeKamerClient)
        mock_client.fetch_moties.return_value = [
            MotieData(
                zaak_id="z1",
                zaak_nummer="36200-VII-42",
                titel="Motie titel",
                onderwerp="Digitale overheid",
                datum=datetime(2026, 1, 15),
                indieners=["Van der Berg"],
                document_tekst="Tekst",
                document_url="https://example.com/doc",
                bron="tweede_kamer",
            )
        ]

        items = await self.strategy.fetch_items(mock_client, None, 100)
        assert len(items) == 1
        assert items[0].zaak_id == "z1"
        assert items[0].datum == date(2026, 1, 15)
        assert items[0].indieners == ["Van der Berg"]


# ---------------------------------------------------------------------------
# KamervraagStrategy
# ---------------------------------------------------------------------------


class TestKamervraagStrategy:
    def setup_method(self):
        self.strategy = KamervraagStrategy()

    def test_item_type(self):
        assert self.strategy.item_type == "kamervraag"

    def test_politieke_input_type(self):
        assert self.strategy.politieke_input_type == "kamervraag"

    def test_requires_llm(self):
        assert self.strategy.requires_llm is True

    def test_task_title(self):
        item = FetchedItem(
            zaak_id="z2",
            zaak_nummer="2026Z01234",
            titel="Test",
            onderwerp="Huisvesting statushouders",
        )
        assert "kamervraag" in self.strategy.task_title(item).lower()
        assert "Huisvesting statushouders" in self.strategy.task_title(item)

    def test_task_priority(self):
        item = FetchedItem(
            zaak_id="z2",
            zaak_nummer="2026Z01234",
            titel="Test",
            onderwerp="Test",
        )
        assert self.strategy.task_priority(item) == "hoog"

    def test_notification_title(self):
        title = self.strategy.notification_title("Test kamervraag")
        assert "kamervraag" in title.lower()

    def test_context_hint(self):
        assert self.strategy.context_hint() == "kamervraag"

    @pytest.mark.anyio
    async def test_fetch_items_from_tk_client(self):
        mock_client = AsyncMock(spec=TweedeKamerClient)
        mock_client.fetch_zaak_by_soort.return_value = [
            ZaakData(
                zaak_id="z2",
                zaak_nummer="2026Z01234",
                titel="Kamervraag titel",
                onderwerp="Huisvesting statushouders",
                soort="Schriftelijke vragen",
                datum=datetime(2026, 2, 1),
                indieners=["Kamerling"],
                termijn=datetime(2026, 3, 1),
                bron="tweede_kamer",
            )
        ]

        items = await self.strategy.fetch_items(mock_client, None, 100)
        assert len(items) == 1
        assert items[0].zaak_id == "z2"
        assert items[0].datum == date(2026, 2, 1)
        assert items[0].deadline == date(2026, 3, 1)
        assert items[0].indieners == ["Kamerling"]

        from bouwmeester.services.import_strategies.kamervraag import (
            MAX_KAMERVRAAG_FETCH,
        )

        mock_client.fetch_zaak_by_soort.assert_called_once_with(
            soort="Schriftelijke vragen",
            since=None,
            limit=min(100, MAX_KAMERVRAAG_FETCH),
        )

    @pytest.mark.anyio
    async def test_fetch_items_non_tk_client_returns_empty(self):
        mock_client = AsyncMock()  # not a TweedeKamerClient
        items = await self.strategy.fetch_items(mock_client, None, 100)
        assert items == []


# ---------------------------------------------------------------------------
# ToezeggingStrategy
# ---------------------------------------------------------------------------


class TestToezeggingStrategy:
    def setup_method(self):
        self.strategy = ToezeggingStrategy()

    def test_item_type(self):
        assert self.strategy.item_type == "toezegging"

    def test_politieke_input_type(self):
        assert self.strategy.politieke_input_type == "toezegging"

    def test_requires_llm_is_true(self):
        assert self.strategy.requires_llm is True

    def test_task_title(self):
        item = FetchedItem(
            zaak_id="t1",
            zaak_nummer="123",
            titel="Test",
            onderwerp="Betere digitale dienstverlening",
        )
        assert "toezegging" in self.strategy.task_title(item).lower()

    def test_task_priority(self):
        item = FetchedItem(
            zaak_id="t1",
            zaak_nummer="123",
            titel="Test",
            onderwerp="Test",
        )
        assert self.strategy.task_priority(item) == "normaal"

    def test_notification_title(self):
        title = self.strategy.notification_title("Test toezegging")
        assert "toezegging" in title.lower()

    def test_context_hint(self):
        assert self.strategy.context_hint() == "toezegging"

    @pytest.mark.anyio
    async def test_fetch_items_from_tk_client(self):
        mock_client = AsyncMock(spec=TweedeKamerClient)
        mock_client.fetch_toezeggingen.return_value = [
            ToezeggingData(
                toezegging_id="t1",
                nummer="T2026-001",
                tekst="De minister zegt toe de digitale dienstverlening te verbeteren",
                naam_bewindspersoon="De Jonge",
                ministerie="Binnenlandse Zaken en Koninkrijksrelaties",
                status="Openstaand",
                datum_nakoming=datetime(2026, 6, 30),
                activiteit_nummer="ACT-2026-01",
                bron="tweede_kamer",
            )
        ]

        items = await self.strategy.fetch_items(mock_client, None, 100)
        assert len(items) == 1
        assert items[0].zaak_id == "t1"
        assert items[0].deadline == date(2026, 6, 30)
        assert items[0].ministerie == "Binnenlandse Zaken en Koninkrijksrelaties"
        assert items[0].indieners == ["De Jonge"]
        assert items[0].extra_data["status"] == "Openstaand"

        mock_client.fetch_toezeggingen.assert_called_once_with(
            ministerie="Binnenlandse Zaken",
            since=None,
            limit=100,
        )

    @pytest.mark.anyio
    async def test_fetch_items_non_tk_client_returns_empty(self):
        mock_client = AsyncMock()  # not a TweedeKamerClient
        items = await self.strategy.fetch_items(mock_client, None, 100)
        assert items == []

    @pytest.mark.anyio
    async def test_fetch_items_without_datum_nakoming(self):
        mock_client = AsyncMock(spec=TweedeKamerClient)
        mock_client.fetch_toezeggingen.return_value = [
            ToezeggingData(
                toezegging_id="t2",
                nummer="T2026-002",
                tekst="Toezegging zonder deadline",
                bron="tweede_kamer",
            )
        ]

        items = await self.strategy.fetch_items(mock_client, None, 100)
        assert len(items) == 1
        assert items[0].deadline is None
        assert items[0].ministerie is None
        assert items[0].indieners == []


# ---------------------------------------------------------------------------
# Base strategy defaults
# ---------------------------------------------------------------------------


class TestBaseStrategyDefaults:
    def test_default_edge_type(self):
        s = MotieStrategy()
        assert s.default_edge_type() == "adresseert"

    def test_calculate_deadline_returns_item_deadline(self):
        s = MotieStrategy()
        item = FetchedItem(
            zaak_id="z1",
            zaak_nummer="1",
            titel="T",
            onderwerp="O",
            deadline=date(2026, 12, 31),
        )
        assert s.calculate_deadline(item) == date(2026, 12, 31)

    def test_calculate_deadline_returns_none_when_no_deadline(self):
        s = MotieStrategy()
        item = FetchedItem(
            zaak_id="z1",
            zaak_nummer="1",
            titel="T",
            onderwerp="O",
        )
        assert s.calculate_deadline(item) is None

    def test_default_always_import_is_false(self):
        s = MotieStrategy()
        assert s.always_import is False

    def test_default_supports_ek_is_true(self):
        s = MotieStrategy()
        assert s.supports_ek is True

    def test_default_politieke_input_status(self):
        s = MotieStrategy()
        item = FetchedItem(zaak_id="z1", zaak_nummer="1", titel="T", onderwerp="O")
        assert s.politieke_input_status(item) == "aangenomen"


class TestToezeggingAlwaysImport:
    """Test the always_import and politieke_input_status behavior."""

    def test_always_import_is_true(self):
        s = ToezeggingStrategy()
        assert s.always_import is True

    def test_supports_ek_is_false(self):
        s = ToezeggingStrategy()
        assert s.supports_ek is False

    def test_politieke_input_status_openstaand(self):
        s = ToezeggingStrategy()
        item = FetchedItem(
            zaak_id="t1",
            zaak_nummer="1",
            titel="T",
            onderwerp="O",
            extra_data={"status": "Openstaand"},
        )
        assert s.politieke_input_status(item) == "openstaand"

    def test_politieke_input_status_deels_voldaan(self):
        s = ToezeggingStrategy()
        item = FetchedItem(
            zaak_id="t1",
            zaak_nummer="1",
            titel="T",
            onderwerp="O",
            extra_data={"status": "Deels voldaan"},
        )
        assert s.politieke_input_status(item) == "deels_voldaan"

    def test_politieke_input_status_voldaan(self):
        s = ToezeggingStrategy()
        item = FetchedItem(
            zaak_id="t1",
            zaak_nummer="1",
            titel="T",
            onderwerp="O",
            extra_data={"status": "Voldaan"},
        )
        assert s.politieke_input_status(item) == "voldaan"

    def test_politieke_input_status_unknown_defaults_to_openstaand(self):
        s = ToezeggingStrategy()
        item = FetchedItem(
            zaak_id="t1",
            zaak_nummer="1",
            titel="T",
            onderwerp="O",
            extra_data={"status": "Onbekend"},
        )
        assert s.politieke_input_status(item) == "openstaand"

    def test_politieke_input_status_no_extra_data(self):
        s = ToezeggingStrategy()
        item = FetchedItem(
            zaak_id="t1",
            zaak_nummer="1",
            titel="T",
            onderwerp="O",
        )
        assert s.politieke_input_status(item) == "openstaand"


class TestKamervraagSupportsEk:
    def test_supports_ek_is_false(self):
        s = KamervraagStrategy()
        assert s.supports_ek is False


class TestKamervraagFetchLimit:
    """Test that kamervragen are capped at MAX_KAMERVRAAG_FETCH."""

    @pytest.mark.anyio
    async def test_limit_capped_to_max(self):
        from bouwmeester.services.import_strategies.kamervraag import (
            MAX_KAMERVRAAG_FETCH,
        )

        mock_client = AsyncMock(spec=TweedeKamerClient)
        mock_client.fetch_zaak_by_soort.return_value = []

        strategy = KamervraagStrategy()
        await strategy.fetch_items(mock_client, None, 1000)

        mock_client.fetch_zaak_by_soort.assert_called_once_with(
            soort="Schriftelijke vragen",
            since=None,
            limit=MAX_KAMERVRAAG_FETCH,
        )

    @pytest.mark.anyio
    async def test_limit_below_max_unchanged(self):
        mock_client = AsyncMock(spec=TweedeKamerClient)
        mock_client.fetch_zaak_by_soort.return_value = []

        strategy = KamervraagStrategy()
        await strategy.fetch_items(mock_client, None, 10)

        mock_client.fetch_zaak_by_soort.assert_called_once_with(
            soort="Schriftelijke vragen",
            since=None,
            limit=10,
        )


class TestODataEscape:
    """Test the _odata_escape helper."""

    def test_no_quotes(self):
        from bouwmeester.services.tk_api_client import _odata_escape

        assert _odata_escape("Binnenlandse Zaken") == "Binnenlandse Zaken"

    def test_single_quote_escaped(self):
        from bouwmeester.services.tk_api_client import _odata_escape

        assert _odata_escape("It's a test") == "It''s a test"

    def test_multiple_quotes(self):
        from bouwmeester.services.tk_api_client import _odata_escape

        assert _odata_escape("a'b'c") == "a''b''c"


# ---------------------------------------------------------------------------
# API filter: type parameter
# ---------------------------------------------------------------------------


async def _create_parlementair_item(db_session, item_type="motie", status="imported"):
    """Helper to create a ParlementairItem of a given type."""
    from bouwmeester.models.parlementair_item import ParlementairItem

    item = ParlementairItem(
        id=uuid.uuid4(),
        type=item_type,
        zaak_id=f"zaak-{uuid.uuid4().hex[:8]}",
        zaak_nummer="36200-VII-42",
        titel=f"Test {item_type}",
        onderwerp=f"Test onderwerp {item_type}",
        bron="tweede_kamer",
        datum=date(2026, 1, 15),
        status=status,
    )
    db_session.add(item)
    await db_session.flush()
    return item


async def test_list_imports_filter_by_type(client, db_session):
    """GET /api/parlementair/imports?type=kamervraag filters by type."""
    await _create_parlementair_item(db_session, item_type="motie")
    await _create_parlementair_item(db_session, item_type="kamervraag")
    await _create_parlementair_item(db_session, item_type="toezegging")

    resp = await client.get("/api/parlementair/imports", params={"type": "kamervraag"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert all(m["type"] == "kamervraag" for m in data)


async def test_list_imports_returns_all_types(client, db_session):
    """GET /api/parlementair/imports without type filter returns all types."""
    await _create_parlementair_item(db_session, item_type="motie")
    await _create_parlementair_item(db_session, item_type="toezegging")

    resp = await client.get("/api/parlementair/imports")
    assert resp.status_code == 200
    data = resp.json()
    types = {m["type"] for m in data}
    assert "motie" in types
    assert "toezegging" in types


async def test_review_queue_filter_by_type(client, db_session):
    """GET /api/parlementair/review-queue?type=toezegging filters by type."""
    await _create_parlementair_item(db_session, item_type="motie", status="imported")
    await _create_parlementair_item(
        db_session, item_type="toezegging", status="imported"
    )

    resp = await client.get(
        "/api/parlementair/review-queue",
        params={"type": "toezegging"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert all(m["type"] == "toezegging" for m in data)
