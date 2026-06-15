from __future__ import annotations

import inspect
import types
from decimal import Decimal
from pathlib import Path

from app.brain.convexity_switch import ConvexitySwitch
from app.brain.entropy_decoder import EntropyDecoder
from app.brain.insider_signal_engine import (
    InsiderObservation,
    InsiderSignalEngine,
    ObservationDirection,
    ObservationSourceType,
)
from app.brain.physical_validator import PhysicalValidator
from app.brain.regime_detector import RegimeDetector
from app.brain.sentiment_engine import SentimentEngine
from app.brain.shans_curve import ShansCurveSignal
from app.brain.signal_fusion import SignalFusion
from app.brain.toxicity_engine import ToxicityAlert, ToxicityEngine, ToxicityRegime
from app.brain.whale_flow_engine import WhaleFlowEngine
from app.brain.whale_zone_engine import WhalePresenceZone, WhaleZoneEngine
from app.config import Config
from app.models import Candle, OrderBookSnapshot, StrategySignal
from app.models.enums import RegimeType, SleeveType
from app.models.instrument_profile import AssetClass, InstrumentProfile, InstrumentType
from app.portfolio.opportunity_ranking import OpportunityRanker
from app.risk.cross_asset_risk_model import CrossAssetRiskCalculator
from app.strategies.adaptive_dc import (
    AdaptiveDC,
    DCEventType,
    DCMarketTick,
    DCSignalAssessment,
)
from app.strategies.strategy_vote_adapters import (
    adapt_liquidity_void_to_vote,
    adapt_sector_rotation_to_vote,
)
from app.strategies.council_metadata import (
    FEED_MISSING,
    FEED_REAL,
    KEY_CONTRIBUTION_ROLE,
    KEY_EXECUTION_CANDIDATE,
    KEY_FEED_STATUS,
    KEY_FRESH_ENTRY_AUTHORIZED,
    KEY_PROTECTIVE_ONLY,
    ROLE_ENTRY,
    ROLE_EXIT,
)
from app.symbol_runtime import SymbolRuntime


T0_NS = 1_777_948_800_000_000_000


def _order_book(symbol: str, ts_ns: int, mid: float) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        symbol=symbol,
        exchange_ts_ns=ts_ns,
        bids=[(mid - 1.0, 4.0), (mid - 2.0, 3.0)],
        asks=[(mid + 1.0, 3.0), (mid + 2.0, 2.0)],
    )


def _candle(symbol: str, ts_ns: int, close: float) -> Candle:
    return Candle(
        symbol=symbol,
        exchange_ts_ns=ts_ns,
        open=close,
        high=close * 1.002,
        low=close * 0.998,
        close=close,
        volume=2500.0,
        timeframe="1m",
    )


def _toxicity(ts_ns: int, score: float = 0.20) -> ToxicityAlert:
    return ToxicityAlert(
        toxicity_score=score,
        regime=ToxicityRegime.NORMAL,
        direction_bias="neutral",
        vpin_proxy=0.10,
        burst_pressure=0.10,
        instability_score=0.10,
        volume_anomaly=0.0,
        persistence=0.0,
        confidence=0.80,
        timestamp_ns=ts_ns,
        reason="intelligence_contribution_spine",
    )


def _strategy_signal(
    *,
    symbol: str = "BTC/USD",
    strategy: str = "sector_rotation",
    side: str = "buy",
    ts_ns: int = T0_NS,
    metadata: dict | None = None,
) -> StrategySignal:
    return StrategySignal(
        strategy=strategy,
        symbol=symbol,
        side=side,
        confidence=0.75,
        quantity=0.25,
        price=None,
        exchange_ts_ns=ts_ns,
        reason="intelligence_contribution_spine",
        metadata=metadata or {},
    )


def test_active_intelligence_contributors_feed_fusion_with_visible_status():
    config = types.SimpleNamespace(
        strategies=types.SimpleNamespace(sector_rotation_ranging_eligible=False),
        symbol="BTC/USD",
    )
    fusion = SignalFusion(config=config)

    whale = WhaleFlowEngine().update(
        buy_volume=3.0,
        sell_volume=0.5,
        trade_sizes=[3.0, 2.0, 1.0],
        exchange_ts_ns=T0_NS,
        price=50_000.0,
    )
    shans = ShansCurveSignal(
        symbol="BTC/USD",
        timestamp_ns=T0_NS,
        shans_superfluid_score=0.10,
        shans_bias=1,
        shans_confidence=0.55,
        fit_r_squared=0.80,
        inflection_distance=0.20,
    )
    entropy = EntropyDecoder().update("BTC/USD", T0_NS, 0.25)
    regime = RegimeDetector(symbol="BTC/USD").update(
        price=50_000.0,
        volume=2500.0,
        bid_price=49_999.0,
        ask_price=50_001.0,
        bid_depth=12.0,
        ask_depth=10.0,
        exchange_ts_ns=T0_NS,
    )
    toxicity = ToxicityEngine("BTC/USD")
    toxicity.update_candle(
        volume=2500.0,
        high=50_100.0,
        low=49_900.0,
        close=50_000.0,
        timestamp_ns=T0_NS,
    )
    tox_alert = toxicity.update_toxicity(T0_NS)
    physical = PhysicalValidator()
    physical.record_latency(
        symbol="BTC/USD",
        exchange="kraken",
        latency_ms=10.0,
        order_size=0.0,
        price_impact_bps=0.0,
        timestamp_ns=T0_NS,
    )
    insider = InsiderSignalEngine().ingest_observation(
        InsiderObservation(
            observation_id="btc-flow-1",
            timestamp_ns=T0_NS,
            symbol="BTC/USD",
            entity_id="",
            direction=ObservationDirection.BUY,
            intensity=Decimal("0.40"),
            notional_weight=Decimal("0.30"),
            source_reliability=Decimal("0.35"),
            event_proximity_weight=Decimal("0"),
            novelty_weight=Decimal("0"),
            corroboration_weight=Decimal("0.20"),
            invalidation_weight=Decimal("0"),
            source_type=ObservationSourceType.FLOW,
        )
    )

    fusion.update_whale(whale, T0_NS)
    fusion.update_shans(shans, T0_NS)
    fusion.update_entropy(entropy, T0_NS)
    fusion.update_regime(regime, T0_NS)
    fusion.update_toxicity(tox_alert, T0_NS)
    fusion.update_physical(physical.to_fusion_dict("kraken"), T0_NS)
    fusion.update_insider(insider, T0_NS)

    decision = fusion.fuse(T0_NS)
    telemetry = fusion.get_fusion_telemetry()

    assert decision.has_valid_sleeve
    assert telemetry["missing_inputs"] == []
    assert "final_confidence" in telemetry
    assert decision.preferred_sleeve in {
        SleeveType.SHADOW_FRONT.value,
        SleeveType.SECTOR_ROTATION.value,
        SleeveType.GAMMA_FRONT.value,
        SleeveType.FLV.value,
    }
    assert isinstance(decision.attack_mode, bool)


def test_signal_fusion_neutralizes_missing_noncritical_inputs_but_vetoes_missing_or_stale_critical_inputs():
    config = types.SimpleNamespace(
        strategies=types.SimpleNamespace(sector_rotation_ranging_eligible=False),
        symbol="BTC/USD",
    )
    fusion = SignalFusion(config=config)
    fusion.update_physical({"health_score": 0.80}, T0_NS)
    fusion.update_toxicity(_toxicity(T0_NS), T0_NS)

    decision = fusion.fuse(T0_NS)
    telemetry = fusion.get_fusion_telemetry()

    assert decision.has_valid_sleeve
    assert set(telemetry["missing_inputs"]) == {
        "whale_flow",
        "shans_curve",
        "entropy",
        "insider",
        "regime",
    }
    assert 0.0 <= telemetry["final_confidence"] <= 1.0
    assert "veto_reason" not in telemetry

    missing_physical = SignalFusion(config=config)
    missing_physical.update_toxicity(_toxicity(T0_NS), T0_NS)
    veto = missing_physical.fuse(T0_NS)
    assert veto.preferred_sleeve is None
    assert "Missing critical signal [physical]" in veto.reason
    assert missing_physical.get_fusion_telemetry()["veto_reason"]

    stale_toxicity = SignalFusion(config=config)
    stale_toxicity.update_physical({"health_score": 0.80}, T0_NS)
    stale_toxicity.update_toxicity(_toxicity(T0_NS - 31_000_000_000), T0_NS - 31_000_000_000)
    veto = stale_toxicity.fuse(T0_NS)
    assert veto.preferred_sleeve is None
    assert "Stale critical signal [toxicity]" in veto.reason


def test_symbol_runtime_keeps_active_contributor_and_observed_vote_state_symbol_local():
    cfg = Config()
    btc = SymbolRuntime("BTC/USD")
    eth = SymbolRuntime("ETH/USD")
    btc.initialize_engines(config=cfg, safety_gate=None)
    eth.initialize_engines(config=cfg, safety_gate=None)

    btc.update_order_book(_order_book("BTC/USD", T0_NS, 50_000.0))
    eth.update_order_book(_order_book("ETH/USD", T0_NS + 1, 2_500.0))
    btc.update_candle(_candle("BTC/USD", T0_NS + 2, 50_010.0))
    eth.update_candle(_candle("ETH/USD", T0_NS + 3, 2_505.0))
    btc.update_whale_with_trade(2.0, 0.0, [2.0], T0_NS + 4, price=50_010.0)
    eth.update_whale_with_trade(0.0, 2.0, [2.0], T0_NS + 5, price=2_505.0)
    btc.update_sentiment_engine(T0_NS + 6)
    eth.update_sentiment_engine(T0_NS + 7)

    btc_sig = _strategy_signal(symbol="BTC/USD", strategy="sector_rotation", ts_ns=T0_NS + 8)
    eth_sig = _strategy_signal(symbol="ETH/USD", strategy="liquidity_void", ts_ns=T0_NS + 9)
    btc_vote = adapt_sector_rotation_to_vote(btc_sig, exchange_ts_ns=T0_NS + 8)
    eth_vote = adapt_liquidity_void_to_vote(eth_sig, exchange_ts_ns=T0_NS + 9)

    btc.record_observed_signal("sector_rotation", btc_sig)
    btc.record_observed_vote("sector_rotation", btc_vote)
    eth.record_observed_signal("liquidity_void", eth_sig)
    eth.record_observed_vote("liquidity_void", eth_vote)

    assert btc.last_price != eth.last_price
    assert btc.last_order_book.symbol == "BTC/USD"
    assert eth.last_order_book.symbol == "ETH/USD"
    assert btc.get_whale_score().symbol == "BTC/USD"
    assert eth.get_whale_score().symbol == "ETH/USD"
    assert btc.last_sector_rotation_observed_signal.symbol == "BTC/USD"
    assert btc.last_liquidity_void_observed_signal is None
    assert eth.last_liquidity_void_observed_signal.symbol == "ETH/USD"
    assert eth.last_sector_rotation_observed_signal is None
    assert btc.last_sector_rotation_observed_vote.timestamp_ns == T0_NS + 8
    assert eth.last_liquidity_void_observed_vote.timestamp_ns == T0_NS + 9


def test_under_contributing_intelligence_modules_have_pure_harness_or_classification():
    zone_engine = WhaleZoneEngine()
    zone = None
    for i in range(8):
        zone = zone_engine.update(
            symbol="BTC/USD",
            close=50_000.0 + i,
            high=50_200.0 + i,
            low=49_800.0 + i,
            volume=2_000.0 + (i * 100.0),
            vwap=50_000.0 + i,
            exchange_ts_ns=T0_NS + i,
        )
    assert zone is None or isinstance(zone, WhalePresenceZone)
    assert not hasattr(zone_engine, "submit_order")

    convexity = ConvexitySwitch()
    convexity_regime = convexity.update("BTC/USD", returns=0.01, benchmark_returns=0.005)
    assert isinstance(convexity_regime, str)
    assert isinstance(convexity.get_strategy_weight("BTC/USD"), dict)

    sentiment = SentimentEngine(min_sources=1)
    sentiment.update_source("BTC/USD", "internal_proxy", 0.25, T0_NS, confidence=0.9)
    aggregate = sentiment.aggregate("BTC/USD", T0_NS)
    assert aggregate is not None
    assert aggregate.symbol == "BTC/USD"

    adaptive_dc = AdaptiveDC()
    init_tick = DCMarketTick(symbol="BTC/USD", price=Decimal("100"), timestamp_ns=T0_NS)
    init_event = adaptive_dc.detect_event(init_tick)
    assert init_event.event_type == DCEventType.INITIALIZED
    assessment = adaptive_dc.assess_event(init_event, init_tick)
    assert isinstance(assessment, DCSignalAssessment)
    assert assessment.symbol == "BTC/USD"
    assert assessment.signal_emittable is False

    profile = InstrumentProfile(
        instrument_id="BTC/USD",
        symbol="BTC/USD",
        canonical_symbol="BTC/USD",
        venue_symbol="XBT/USD",
        display_symbol="BTC/USD",
        root_symbol="BTC",
        asset_class=AssetClass.CRYPTO,
        instrument_type=InstrumentType.SPOT,
        venue="KRAKEN",
        primary_exchange="KRAKEN",
        currency="USD",
        quote_currency="USD",
        base_currency="BTC",
        country="US",
        region="North America",
        timezone="UTC",
    )
    risk_report = CrossAssetRiskCalculator().calculate(
        positions={"BTC/USD": {"quantity": Decimal("0.1"), "avg_price": Decimal("49000")}},
        current_prices={"BTC/USD": Decimal("50000")},
        instruments={"BTC/USD": profile},
        equity=Decimal("20000"),
        timestamp_ns=T0_NS,
    )
    assert risk_report.timestamp_ns == T0_NS
    assert risk_report.total_gross_exposure_usd == Decimal("5000.0")

    ranking_report = OpportunityRanker().rank(
        candidates=[
            ("BTC/USD", "sector_rotation", Decimal("40.0"), Decimal("0.80"), Decimal("3000")),
        ],
        instruments={"BTC/USD": profile},
        existing_exposures={},
        total_equity=Decimal("20000"),
        available_capital=Decimal("10000"),
        timestamp_ns=T0_NS,
    )
    assert ranking_report.total_ranked == 1
    assert ranking_report.top_opportunity == "BTC/USD"
    assert ranking_report.opportunities[0].skip is False

    ranker_source = Path("app/portfolio/opportunity_ranking.py").read_text()
    assert "non-default argument 'net_edge_after_all' follows default argument" not in ranker_source
    assert "submit_order" not in ranker_source
    assert "ExecutionEngine" not in ranker_source
    assert "spread_bps = instrument.constraints.max_spread_bps" in ranker_source


def test_contributor_role_boundaries_remain_metadata_only_and_non_executing():
    entry_signal = _strategy_signal(symbol="BTC/USD", strategy="sector_rotation", metadata={})
    exit_signal = _strategy_signal(
        symbol="BTC/USD",
        strategy="liquidity_void",
        side="sell",
        metadata={"exit_price": "50000", "pnl_pct": "0.01"},
    )

    entry_vote = adapt_sector_rotation_to_vote(entry_signal, exchange_ts_ns=T0_NS)
    exit_vote = adapt_liquidity_void_to_vote(exit_signal, exchange_ts_ns=T0_NS)

    assert entry_vote.metadata[KEY_CONTRIBUTION_ROLE] == ROLE_ENTRY
    assert entry_vote.metadata[KEY_FRESH_ENTRY_AUTHORIZED] is True
    assert entry_vote.metadata[KEY_PROTECTIVE_ONLY] is False
    assert entry_vote.metadata[KEY_EXECUTION_CANDIDATE] is True
    assert entry_vote.metadata[KEY_FEED_STATUS] == FEED_REAL
    assert exit_vote.metadata[KEY_CONTRIBUTION_ROLE] == ROLE_EXIT
    assert exit_vote.metadata[KEY_FRESH_ENTRY_AUTHORIZED] is False
    assert exit_vote.metadata[KEY_FEED_STATUS] == FEED_MISSING

    for adapter in (adapt_sector_rotation_to_vote, adapt_liquidity_void_to_vote):
        source = inspect.getsource(adapter)
        assert "submit_order" not in source
        assert "ExecutionEngine" not in source
        assert "OrderRouter" not in source

    context_modules = [
        WhaleZoneEngine,
        ConvexitySwitch,
        SentimentEngine,
        CrossAssetRiskCalculator,
    ]
    for module_cls in context_modules:
        source = inspect.getsource(module_cls)
        assert "submit_order" not in source
        assert "OrderRouter" not in source
        assert "ExecutionEngine" not in source

    opportunity_source = Path("app/portfolio/opportunity_ranking.py").read_text()
    assert "submit_order" not in opportunity_source
    assert "OrderRouter" not in opportunity_source
    assert "ExecutionEngine" not in opportunity_source
