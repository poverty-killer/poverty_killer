from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import aiohttp

from app.core.decision_compiler import DecisionCompiler
from app.core.intelligence_portfolio_state_truth_spine import BrokerTruthSnapshot
from app.core.truth_reconciler import TruthReconciler
from app.data.aggregator import MultiMarketAggregator
from app.data.depth_book import DepthBook
from app.data.market_feeds import MarketFeeds
from app.data.polling_client import PollingClient
from app.data.websocket_client import KrakenWebSocketClient
from app.execution.alpaca_paper_adapter import (
    EXPECTED_ALPACA_PAPER_BASE_URL,
    AlpacaPaperBrokerAdapter,
    AlpacaPaperCredentials,
)
from app.execution.live_read_only_adapter import LiveReadOnlyBrokerAdapter, ReadOnlyAdapterConfig
from app.instrument_registry import InstrumentRegistry
from app.market.capability_registry import (
    VenueCapabilityRegistry,
    build_alpaca_crypto_capability_registry,
    build_alpaca_crypto_universe,
    build_default_capability_registry,
    normalize_alpaca_crypto_catalog,
)
from app.market.venue_capabilities import PortalPolicyMode, PortalSelectionRequest, classify_quote_session
from app.models import Candle, OrderBookSnapshot
from app.models.contracts import (
    ExchangePosition,
    ExchangeTruth,
    ExecutionTruth,
    PortfolioPosition,
    PortfolioTruth,
    RiskTruth,
    StrategyTruthEntry,
    StrategyTruth,
    TruthFrame,
)
from app.models.enums import EventType, SourceType, StrategyID, TruthStatus
from app.models.unified_market import AssetClass as UnifiedAssetClass
from app.models.unified_market import Exchange, InstrumentSpec, UnifiedMarketData
from app.replay.source import ReplaySource
from app.session_manager import SessionManager
from app.snapshot_exporter import SnapshotExporter
from app.state.state_store import StateStore
from app.utils.time_utils import now_ns


T0_NS = 1_779_100_000_000_000_000


def _broker_catalog_registry() -> VenueCapabilityRegistry:
    catalog = normalize_alpaca_crypto_catalog(
        [
            {
                "id": "asset-btcusd",
                "class": "crypto",
                "exchange": "CRYPTO",
                "symbol": "BTC/USD",
                "status": "active",
                "tradable": True,
                "fractionable": True,
                "marginable": False,
                "shortable": False,
                "min_order_size": "0.0001",
                "min_trade_increment": "0.0001",
                "price_increment": "0.01",
            }
        ],
        observed_at_ns=T0_NS - 1,
        valid_until_ns=T0_NS + 1_000_000_000,
        expected_account_suffix="045ded",
        actual_account_suffix="045ded",
    )
    universe = build_alpaca_crypto_universe(
        catalog,
        as_of_ns=T0_NS,
        expected_account_suffix="045ded",
        actual_account_suffix="045ded",
        account_status="ACTIVE",
        crypto_status="ACTIVE",
        trading_blocked=False,
        account_blocked=False,
        trade_suspended_by_user=False,
        execution_adapter="alpaca_paper_rest",
        execution_adapter_available=True,
        funded_quote_currencies=("USD",),
        market_data_symbols=("BTC/USD",),
    )
    dynamic = build_alpaca_crypto_capability_registry(catalog, universe)
    base = build_default_capability_registry()
    preserved = tuple(
        capability
        for capability in base.capabilities
        if not (capability.venue_id == "alpaca" and capability.asset_class == "crypto")
    )
    return VenueCapabilityRegistry((*preserved, *dynamic.capabilities))


def _record(
    *,
    module_name: str,
    category: str,
    status: str,
    input_truth: str,
    output_summary: str,
    effect: str,
    reason: str,
    provenance: dict | None = None,
    staleness_ms: int | None = None,
    symbol_or_asset: str | None = None,
    venue: str | None = None,
    blocking: bool = False,
) -> dict:
    return {
        "module_name": module_name,
        "category": category,
        "status": status,
        "input_truth": input_truth,
        "output_summary": output_summary,
        "effect": effect,
        "reason": reason,
        "provenance": provenance or {},
        "timestamp": T0_NS,
        "staleness_ms": staleness_ms,
        "symbol_or_asset": symbol_or_asset,
        "venue": venue,
        "blocking": blocking,
    }


def _truth_frame() -> TruthFrame:
    return TruthFrame(
        truth_frame_id="seam7g-truth-frame",
        timestamp_ns=T0_NS,
        exchange_truth=ExchangeTruth(venue="alpaca_paper_read_only", exchange_ts_ns=T0_NS),
        execution_truth=ExecutionTruth(last_reconciliation_ts_ns=T0_NS),
        portfolio_truth=PortfolioTruth(last_update_ts_ns=T0_NS),
        strategy_truth=StrategyTruth(last_update_ts_ns=T0_NS),
        risk_truth=RiskTruth(),
        status=TruthStatus.RECONCILED,
    )


def test_websocket_market_feeds_polling_and_depth_emit_truthful_market_records():
    emitted_books: list[OrderBookSnapshot] = []
    client = KrakenWebSocketClient(symbols=["BTC/USD"], on_order_book=emitted_books.append)

    asyncio.run(
        client._process_message(
            """
            {
              "channel": "book",
              "data": [{
                "symbol": "BTC/USD",
                "timestamp": "2026-05-20T14:00:00.000000Z",
                "bids": [{"price": "100.00", "qty": "1.50"}],
                "asks": [{"price": "101.00", "qty": "2.00"}]
              }]
            }
            """,
            T0_NS,
        )
    )
    assert len(emitted_books) == 1
    assert emitted_books[0].symbol == "BTC/USD"
    assert emitted_books[0].depth_at_levels(10) == (1.5, 2.0)
    ws_record = _record(
        module_name="KrakenWebSocketClient",
        category="market_data",
        status="ACTIVE_WEBSOCKET",
        input_truth="deterministic Kraken v2 book message with nested exchange timestamp",
        output_summary="one valid two-sided OrderBookSnapshot emitted",
        effect="PROVIDES_DEPTH",
        reason="FRESH_BOOK_INGRESS",
        provenance=client.get_stats(),
        symbol_or_asset="BTC/USD",
        venue="kraken",
    )

    config = SimpleNamespace(
        symbol_universe=["BTC/USD"],
        data=SimpleNamespace(max_candles_per_symbol=10, polling_interval_seconds=1),
        risk=SimpleNamespace(stale_data_threshold_seconds=60),
    )
    feeds = MarketFeeds(config)
    feeds._on_order_book(OrderBookSnapshot(
        symbol="BTC/USD",
        exchange_ts_ns=now_ns(),
        bids=[(100.0, 1.5), (99.5, 1.0)],
        asks=[(101.0, 2.0), (101.5, 2.5)],
    ))
    assert feeds.get_order_book("BTC/USD") is not None
    assert feeds.get_depth_history("BTC/USD", 1)[-1] == 7.0
    feed_record = _record(
        module_name="MarketFeeds",
        category="market_data",
        status="ACTIVE_FEED_INGRESS",
        input_truth="provided OrderBookSnapshot",
        output_summary="book stored and depth derived from canonical depth_at_levels",
        effect="PROVIDES_DEPTH",
        reason="NORMALIZED_BOOK_ACCEPTED",
        provenance=feeds.get_market_status(),
        symbol_or_asset="BTC/USD",
        venue="kraken",
    )

    class FailingSession:
        def get(self, *args, **kwargs):
            conn_key = SimpleNamespace(host="dns.invalid", port=443, ssl=True)
            raise aiohttp.ClientConnectorError(conn_key, OSError("dns failure"))

    polling = PollingClient(symbols=["BTC/USD"])
    polling._session = FailingSession()
    asyncio.run(polling._fetch_candles("BTC/USD"))
    failure = polling.get_stats()["last_failure_status"]
    assert failure["status"] == "DNS_FAILURE_RECORDED"
    polling_record = _record(
        module_name="PollingClient",
        category="market_data",
        status="DNS_FAILURE_RECORDED",
        input_truth="ClientConnectorError from REST polling session",
        output_summary="failure recorded without raising out of fetch path",
        effect="NO_EFFECT_WITH_REASON",
        reason="DNS_FAILURE_RECORDED",
        provenance=failure,
        symbol_or_asset="BTC/USD",
        venue="kraken",
        blocking=True,
    )

    depth = DepthBook("BTC/USD")
    depth.update(OrderBookSnapshot(
        symbol="BTC/USD",
        exchange_ts_ns=T0_NS,
        bids=[(100.0, 1.5), (99.5, 1.0)],
        asks=[(101.0, 2.0), (101.5, 2.5)],
    ))
    assert depth.market_depth == 7.0
    assert depth.get_depth_at_levels(1) == (1.5, 2.0)
    depth_record = _record(
        module_name="DepthBook",
        category="market_data",
        status="ACTIVE_DEPTH_BOOK",
        input_truth="provided canonical OrderBookSnapshot",
        output_summary="depth and spread derived from supplied levels",
        effect="PROVIDES_DEPTH",
        reason="DEPTH_BOOK_UPDATED",
        provenance=depth.get_snapshot(),
        symbol_or_asset="BTC/USD",
        venue="kraken",
    )

    assert {ws_record["status"], feed_record["status"], polling_record["status"], depth_record["status"]} == {
        "ACTIVE_WEBSOCKET",
        "ACTIVE_FEED_INGRESS",
        "DNS_FAILURE_RECORDED",
        "ACTIVE_DEPTH_BOOK",
    }


def test_aggregator_uses_only_provided_ticks_and_instrument_metadata():
    unified = UnifiedMarketData(max_instruments=4)
    unified.register_instrument(
        InstrumentSpec(
            id=0,
            symbol="BTC/USD",
            asset_class=UnifiedAssetClass.CRYPTO,
            exchange=Exchange.KRAKEN,
            description="Bitcoin / USD",
            base_tick_size=0.01,
            base_lot_size=0.0001,
            step_size=0.0001,
            min_notional=10.0,
            timezone="UTC",
            is_24_7=True,
        )
    )

    class FakeSharedMemory:
        def __init__(self):
            self.prices = []
            self.features = []

        def write_price_history(self, instrument_id, price, timestamp_ns, index):
            self.prices.append((instrument_id, price, timestamp_ns, index))

        def write_feature_vector(self, features, timestamp_ns):
            self.features.append((features, timestamp_ns))
            return len(self.features)

    shared = FakeSharedMemory()
    aggregator = MultiMarketAggregator(unified, shared)
    accepted = aggregator.ingest_kraken_tick("BTC/USD", 100.0, 1.0, T0_NS, bid=99.5, ask=100.5)

    assert accepted is True
    assert unified.get_price("BTC/USD") == 100.0
    assert shared.prices == [(0, 100.0, T0_NS, 1)]
    stats = aggregator.get_stats()
    assert stats["total_ticks"] == 1
    assert stats["ghost_ticks_filtered"] == 0


def test_broker_derived_venue_capability_and_static_instrument_reference_fail_closed():
    static_registry = build_default_capability_registry()
    static_alpaca = static_registry.resolve(
        PortalSelectionRequest(
            symbol="BTC/USD",
            asset_class="crypto",
            policy_mode=PortalPolicyMode.EXPLICIT_PREFERRED_VENUE.value,
            preferred_venue="alpaca_paper",
        )
    )
    assert static_alpaca.ready is False
    assert any("BROKER_CATALOG_REQUIRED" in reasons for reasons in static_alpaca.rejected.values())

    registry = _broker_catalog_registry()
    candidates = registry.build_candidate_identities(
        symbols=["AAPL", "BTC/USD"],
        active_markets=["equity", "crypto"],
    )
    by_symbol = {candidate.normalized_symbol: candidate for candidate in candidates}

    assert by_symbol["AAPL"].default_order_type == "limit"
    assert by_symbol["AAPL"].default_time_in_force == "DAY"
    assert by_symbol["BTC/USD"].min_notional is None or by_symbol["BTC/USD"].default_time_in_force == "GTC"

    aapl_session = classify_quote_session(
        by_symbol["AAPL"],
        market_session_open=False,
        quote_present=True,
        quote_fresh=False,
    )
    assert "MARKET_CLOSED" in aapl_session.reason_codes
    btc_session = classify_quote_session(
        by_symbol["BTC/USD"],
        market_session_open=None,
        quote_present=True,
        quote_fresh=True,
        spread_bps=Decimal("10"),
    )
    assert btc_session.tradable_now is True

    instrument = InstrumentRegistry.get_instrument("BTC/USD")
    assert instrument is not None
    assert instrument.execution_authorized is False
    valid, reason = InstrumentRegistry.validate_order("BTC/USD", quantity=0.001, price=10000.0, side="buy")
    assert valid is False
    assert "not execution-authorized" in reason
    valid_unknown, reason_unknown = InstrumentRegistry.validate_order("NOTREAL", quantity=1.0, price=1.0, side="buy")
    assert valid_unknown is False
    assert "Unknown symbol" in reason_unknown


def test_broker_read_only_truth_and_reconciliation_remain_non_mutating():
    class FakeTransport:
        def __init__(self):
            self.calls = []

        def request(self, *, method, url, headers, body, timeout):
            self.calls.append((method, url, body))
            if url.endswith("/v2/account"):
                return 200, {"id": "paper-account", "cash": "1000"}
            if "/v2/positions" in url:
                return 200, [{"symbol": "AAPL", "qty": "1"}]
            if "/v2/orders" in url:
                return 200, []
            return 200, {}

    adapter = AlpacaPaperBrokerAdapter(
        AlpacaPaperCredentials(
            base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
            key_id="test-key",
            secret_key="test-secret",
        ),
        transport=FakeTransport(),
    )
    account = adapter.get_account()
    positions = adapter.get_positions()
    open_orders = adapter.get_open_orders()
    assert account.ok is True
    assert positions.mutation_occurred is False
    assert open_orders.mutation_occurred is False
    assert adapter.request_counts == {"GET": 3, "POST": 0}
    assert adapter.identity.live_blocked is True

    class FakeReadSource:
        def fetch_balances(self):
            return [{"currency": "USD", "cash": "1000"}]

        def fetch_positions(self):
            return [{"symbol": "AAPL", "qty": "1"}]

        def fetch_normalized_open_orders(self):
            return []

        def fetch_fills(self, *args, **kwargs):
            return []

    read_only = LiveReadOnlyBrokerAdapter(
        FakeReadSource(),
        ReadOnlyAdapterConfig(
            read_only_enabled=True,
            environment="paper",
            source="alpaca_paper",
            allow_mutation=False,
            account_id="paper-account",
            credentials_present=True,
        ),
    )
    snapshot = read_only.get_exchange_truth_snapshot(receive_ts_ns=T0_NS, require_credentials=True)
    assert snapshot.read_only is True
    assert snapshot.mutation_allowed is False
    assert snapshot.contract_mapping()["read_only_no_submit_cancel_25m_25r"] is True

    reconciler = TruthReconciler()
    exchange_truth = ExchangeTruth(
        venue="alpaca_paper",
        balances={"USD": Decimal("1000")},
        positions=[ExchangePosition(symbol="AAPL", side="long", quantity=Decimal("1"), entry_price=Decimal("100"))],
        open_orders=[],
        exchange_ts_ns=T0_NS,
    )
    execution_truth = ExecutionTruth(last_reconciliation_ts_ns=T0_NS)
    portfolio_match = PortfolioTruth(
        cash={"USD": Decimal("1000")},
        positions=[PortfolioPosition(symbol="AAPL", quantity=Decimal("1"), avg_price=Decimal("100"), mark_price=Decimal("100"), unrealized_pnl=Decimal("0"))],
        last_update_ts_ns=T0_NS,
    )
    strategy_match = StrategyTruth(
        active_strategies=[
            StrategyTruthEntry(
                strategy_id=StrategyID.MOVING_FLOOR,
                state="active",
                entry_price=Decimal("100"),
                current_exposure=Decimal("1"),
            )
        ],
        last_update_ts_ns=T0_NS,
    )
    status, reasons = reconciler.reconcile(exchange_truth, execution_truth, portfolio_match, strategy_match, RiskTruth())
    assert status == TruthStatus.RECONCILED
    assert reasons == []

    portfolio_conflict = PortfolioTruth(
        cash={"USD": Decimal("1000")},
        positions=[PortfolioPosition(symbol="AAPL", quantity=Decimal("2"), avg_price=Decimal("100"), mark_price=Decimal("100"), unrealized_pnl=Decimal("0"))],
        last_update_ts_ns=T0_NS,
    )
    conflict_status, conflict_reasons = reconciler.reconcile(
        exchange_truth,
        execution_truth,
        portfolio_conflict,
        StrategyTruth(last_update_ts_ns=T0_NS),
        RiskTruth(),
    )
    assert conflict_status == TruthStatus.BROKEN
    assert any("position.AAPL.quantity" in reason for reason in conflict_reasons)


def test_state_session_snapshot_replay_and_decision_record_metadata(tmp_path):
    store = StateStore(str(tmp_path / "state.db"))
    store.save_strategy_state(
        strategy="seam7g",
        symbol="BTC/USD",
        state="hydrated",
        data={"source": "deterministic_test"},
        transition_complete=True,
    )
    restored = store.get_last_strategy_state("seam7g", "BTC/USD")
    assert restored["state"] == "hydrated"
    state_record = _record(
        module_name="StateStore",
        category="state_hydration",
        status="ACTIVE_STATE_HYDRATION",
        input_truth="local deterministic sqlite state write/read",
        output_summary="local supporting state restored",
        effect="HYDRATES_LOCAL_STATE",
        reason="LOCAL_STATE_SUPPORTING_ONLY",
        provenance={"state": restored["state"]},
    )

    broker_truth = BrokerTruthSnapshot(
        positions=({"symbol": "AAPL", "qty": "1"},),
        open_orders=(),
        balances={"USD": "1000"},
        receive_ts_ns=T0_NS,
        fixture_truth=False,
    )
    assert broker_truth.fixture_truth is False

    session = SessionManager()
    assert session.is_crypto_hours() is True
    session_record = _record(
        module_name="SessionManager",
        category="session_snapshot_replay",
        status="ACTIVE_SESSION_CONTINUITY",
        input_truth="session manager market calendar",
        output_summary="crypto session continuous",
        effect="PROVIDES_SESSION_TRUTH",
        reason="CRYPTO_24_7",
        provenance=session.get_session_status(),
    )

    exporter = SnapshotExporter(export_dir=str(tmp_path / "snapshots"), interval_seconds=999)
    snapshot = exporter._build_snapshot()
    assert snapshot["portfolio"]["error"] == "No portfolio data"
    snapshot_record = _record(
        module_name="SnapshotExporter",
        category="session_snapshot_replay",
        status="ACTIVE_SNAPSHOT",
        input_truth="provided in-memory exporter state only",
        output_summary="snapshot built without invented portfolio truth",
        effect="EXPORTS_SNAPSHOT",
        reason="NO_PORTFOLIO_DATA_RECORDED_EXPLICITLY",
        provenance={"portfolio": snapshot["portfolio"]},
    )

    replay = ReplaySource.create_test_source([
        (
            EventType.QUOTE,
            T0_NS,
            {
                "symbol": "BTC/USD",
                "bid_price": "100",
                "bid_size": "1",
                "ask_price": "101",
                "ask_size": "2",
            },
        )
    ])
    with replay as source:
        events = list(source)
    assert len(events) == 1
    assert events[0].receive_ts_ns == events[0].exchange_ts_ns == T0_NS
    assert replay.source_type == SourceType.JSONL
    replay_record = _record(
        module_name="ReplaySource",
        category="session_snapshot_replay",
        status="ACTIVE_REPLAY",
        input_truth="local JSONL replay source",
        output_summary="quote replayed with receive_ts_ns equal to exchange_ts_ns",
        effect="REPLAYS_HISTORICAL_TRUTH",
        reason="REPLAY_ONLY_NOT_LIVE_TRUTH",
        provenance=replay.get_source_info(),
    )

    additional_inputs = {
        "market_data_attribution": [
            _record(
                module_name="MarketFeeds",
                category="market_data",
                status="ACTIVE_FEED_INGRESS",
                input_truth="deterministic fixture",
                output_summary="market data attribution carried",
                effect="PROVIDES_QUOTES",
                reason="FIXTURE_MARKET_TRUTH",
            )
        ],
        "venue_capability_attribution": [
            _record(
                module_name="VenueCapabilityRegistry",
                category="venue_capability",
                status="ACTIVE_VENUE_CAPABILITY",
                input_truth="default capability registry",
                output_summary="venue capability attribution carried",
                effect="PROVIDES_CAPABILITY_TRUTH",
                reason="STATIC_CAPABILITY_TRUTH",
            )
        ],
        "instrument_registry_attribution": [
            _record(
                module_name="InstrumentRegistry",
                category="instrument_registry",
                status="ACTIVE_INSTRUMENT_REGISTRY",
                input_truth="known instrument lookup",
                output_summary="instrument metadata attribution carried",
                effect="PROVIDES_INSTRUMENT_METADATA",
                reason="KNOWN_INSTRUMENT",
            )
        ],
        "broker_truth_attribution": [
            _record(
                module_name="LiveReadOnlyBrokerAdapter",
                category="broker_truth",
                status="ACTIVE_BROKER_TRUTH_READ",
                input_truth="read-only broker snapshot",
                output_summary="broker truth attribution carried",
                effect="READS_BROKER_ACCOUNT",
                reason="READ_ONLY_NO_MUTATION",
            )
        ],
        "truth_reconciliation_attribution": [
            _record(
                module_name="TruthReconciler",
                category="truth_reconciliation",
                status="ACTIVE_TRUTH_RECONCILIATION",
                input_truth="exchange and local truth snapshots",
                output_summary="reconciliation attribution carried",
                effect="RECONCILES_BROKER_LOCAL_STATE",
                reason="BROKER_TRUTH_CANONICAL",
            )
        ],
        "state_hydration_attribution": [state_record],
        "session_snapshot_replay_attribution": [session_record, snapshot_record, replay_record],
        "market_truth_summary": {
            "broker_mutation_counts": {"POST": 0, "PATCH": 0, "DELETE": 0, "cancel": 0, "replace": 0, "sell": 0, "rebalance": 0},
            "live_endpoint_used": False,
            "replay_labeled_not_live": True,
        },
    }
    record = DecisionCompiler().compile(_truth_frame(), additional_inputs=additional_inputs)
    assert record.metadata["market_data_attribution"][0]["module_name"] == "MarketFeeds"
    assert record.metadata["venue_capability_attribution"][0]["module_name"] == "VenueCapabilityRegistry"
    assert record.metadata["instrument_registry_attribution"][0]["module_name"] == "InstrumentRegistry"
    assert record.metadata["broker_truth_attribution"][0]["module_name"] == "LiveReadOnlyBrokerAdapter"
    assert record.metadata["truth_reconciliation_attribution"][0]["module_name"] == "TruthReconciler"
    assert record.metadata["state_hydration_attribution"][0]["module_name"] == "StateStore"
    assert record.metadata["session_snapshot_replay_attribution"][2]["module_name"] == "ReplaySource"
    assert record.metadata["market_truth_summary"]["broker_mutation_counts"]["POST"] == 0
