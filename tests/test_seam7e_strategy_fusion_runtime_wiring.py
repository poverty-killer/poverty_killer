from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import numpy as np

from app.brain.signal_fusion import SignalFusion
from app.brain.shans_curve import ShansCurve
from app.brain.sentiment_engine import SentimentEngine
from app.brain.sentiment_velocity import SentimentVelocityEngine
from app.brain.topological_engine import TopologicalSignal
from app.brain.whale_zone_engine import WhaleZoneEngine
from app.constants import ControlMode, SleeveType
from app.core.decision_compiler import DecisionCompiler
from app.data.feature_builder import FeatureBuilder
from app.data.ghost_tick_detector import FastGhostTickDetector
from app.data.regime_detector import RegimeDetector
from app.data.validators import DataValidator
from app.models.contracts import (
    ExchangeTruth,
    ExecutionTruth,
    FeaturePayload,
    FeatureVector,
    PortfolioTruth,
    RiskTruth,
    StrategyTruth,
    StrategyVote,
    TruthFrame,
)
from app.models.enums import BookIntegrity, LiquidityRegime, RegimeType, SignalDirection, SignalType, StrategyID, ToxicityLevel, TruthStatus
from app.models.fusion import FusionDecision
from app.models.market_data import Candle, OrderBookSnapshot
from app.portfolio.opportunity_ranking import (
    OpportunityRanker,
    OpportunityRankingReport,
    summarize_opportunity_ranking,
)
from app.strategies.adaptive_dc import AdaptiveDC, DCMarketTick
from app.strategies.hedging_flow import HedgingFlow, HedgeMarketContext, PortfolioExposureSnapshot
from app.strategies.gamma_front import GammaFrontStrategy
from app.strategies.liquidity_void import LiquidityVoidStrategy
from app.strategies.moving_floor import FloorMarketTick, TopologicalMovingFloor
from app.strategies.sector_rotation import SectorRotationStrategy
from app.strategies.strategy_router import StrategyRouter
from app.strategies.strategy_vote_adapters import (
    adapt_adaptive_dc_to_vote,
    adapt_gamma_front_to_vote,
    adapt_moving_floor_to_vote,
    adapt_vote_to_runtime_evidence,
)
from app.strategies.council_metadata import (
    build_runtime_evidence_record,
    summarize_runtime_evidence,
)
from app.models.signals import DarkPoolPrint, StrategySignal
from app.world_awareness.adapters.capitol_trades import CapitolTradesAdapter
from app.world_awareness.adapters.official_calendars import OfficialCalendarsAdapter
from app.world_awareness.adapters.official_releases import OfficialReleasesAdapter
from app.world_awareness.adapters.openinsider import OpenInsiderAdapter
from app.world_awareness.adapters.quiver_free import QuiverFreeAdapter
from app.world_awareness.adapters.sec_edgar import SecEdgarAdapter
from app.world_awareness.enums import SourceFamily
from app.world_awareness.source_catalog import source_status_signature


T0_NS = 1_777_948_800_000_000_000


def _fusion_decision() -> FusionDecision:
    return FusionDecision(
        exchange_ts_ns=T0_NS,
        attack_mode=False,
        confidence=0.64,
        shadow_front_eligible=True,
        liquidity_void_eligible=True,
        entropy_decoder_eligible=False,
        gamma_front_eligible=True,
        sector_rotation_eligible=True,
        preferred_sleeve=SleeveType.GAMMA_FRONT.value,
        deprioritized_sleeves=[SleeveType.SECTOR_ROTATION.value],
        reason="deterministic seam 7e fusion",
        regime="crisis",
    )


def _router() -> StrategyRouter:
    safety_gate = SimpleNamespace(get_macro_status=lambda: {"macro_kill_active": False})
    return StrategyRouter(SimpleNamespace(control_mode=ControlMode.NORMAL.value), safety_gate)


def _truth_frame() -> TruthFrame:
    return TruthFrame(
        truth_frame_id="seam7e-truth-frame",
        timestamp_ns=T0_NS,
        exchange_truth=ExchangeTruth(venue="paper", exchange_ts_ns=T0_NS),
        execution_truth=ExecutionTruth(last_reconciliation_ts_ns=T0_NS),
        portfolio_truth=PortfolioTruth(last_update_ts_ns=T0_NS),
        strategy_truth=StrategyTruth(last_update_ts_ns=T0_NS),
        risk_truth=RiskTruth(),
        status=TruthStatus.RECONCILED,
    )


def _gamma_signal() -> StrategySignal:
    return StrategySignal(
        strategy="gamma_front",
        symbol="AAPL",
        side="buy",
        confidence=0.71,
        quantity=0.10,
        price=150.00,
        exchange_ts_ns=T0_NS,
        reason="deterministic_gamma_front_signal",
        metadata={"print_ratio": 3.2, "options_confirmed": True},
    )


def _moving_floor_recommendation() -> SimpleNamespace:
    return SimpleNamespace(
        symbol="AAPL",
        signal_direction=SignalDirection.SHORT,
        confidence=Decimal("0.82"),
        quality=SimpleNamespace(value="high"),
        event_type=SimpleNamespace(value="floor_break"),
        priority=SimpleNamespace(value="high"),
        authority_tier=SimpleNamespace(value="protective"),
        worst_case_fill_price=Decimal("149.50"),
        rationale=("protect_total_profit",),
    )


def _world_awareness_record() -> dict:
    signature = source_status_signature(SourceFamily.SEC_EDGAR)
    return build_runtime_evidence_record(
        module_name=signature["source_name"],
        category="world_awareness",
        status=signature["status"],
        input_truth=signature["input_truth"],
        output_summary=signature["output_summary"],
        effect="WORLD_AWARENESS_CONTEXT",
        reason=signature["reason"],
        timestamp_ns=T0_NS,
        provenance={"source_catalog": signature},
    )


def _intelligence_record(module_name: str = "SentimentVelocity") -> dict:
    return build_runtime_evidence_record(
        module_name=module_name,
        category="intelligence",
        status="MISSING_FEED_TRUTH",
        input_truth="native_sentiment_feed_absent",
        output_summary="No native sentiment payload supplied; no sentiment invented.",
        effect="NO_EFFECT_WITH_REASON",
        reason="MISSING_FEED_TRUTH",
        timestamp_ns=T0_NS,
        provenance={"seam": "7C"},
    )


def test_strategy_router_surfaces_multiple_strategy_evidence_without_flattening_provenance():
    packet = _router().collect_strategy_runtime_evidence(_fusion_decision())
    records = packet["strategy_attribution"]
    by_name = {record["module_name"]: record for record in records}

    assert packet["authority"] == "ranking_only_no_execution"
    assert by_name["gamma_front"]["status"] == "ACTIVE_STRATEGY_VOTE"
    assert by_name["sector_rotation"]["status"] == "ACTIVE_STRATEGY_VOTE"
    assert by_name["entropy_decoder"]["status"] == "ABSTAIN"
    assert by_name["moving_floor"]["status"] == "MISSING_FEED_TRUTH"
    assert by_name["gamma_front"]["provenance"]["eligible_sleeves"]
    assert by_name["gamma_front"]["provenance"] != by_name["sector_rotation"]["provenance"] or by_name["gamma_front"]["module_name"] != by_name["sector_rotation"]["module_name"]


def test_moving_floor_vote_is_total_profit_protection_evidence_not_fresh_entry():
    vote = adapt_moving_floor_to_vote(_moving_floor_recommendation(), T0_NS, "seam7e-mf")
    evidence = adapt_vote_to_runtime_evidence(vote)

    assert evidence["module_name"] == "moving_floor"
    assert evidence["status"] == "ACTIVE_PROTECTION"
    assert evidence["effect"] == "PROTECT_TOTAL_PROFIT"
    assert evidence["provenance"]["metadata"]["fresh_entry_authorized"] is False
    assert evidence["provenance"]["metadata"]["protective_only"] is True


def test_strategy_vote_adapters_preserve_active_missing_and_abstain_states():
    active_vote = adapt_gamma_front_to_vote(_gamma_signal(), T0_NS, "seam7e-gamma")
    active = adapt_vote_to_runtime_evidence(active_vote)
    missing_vote = StrategyVote(
        vote_id="seam7e-missing-vote",
        decision_uuid="seam7e-missing",
        strategy_id=StrategyID.SECTOR_ROTATION,
        timestamp_ns=T0_NS,
        signal=SignalType.FLAT,
        confidence=Decimal("0.01"),
        expected_move_bps=Decimal("0"),
        expected_duration_ns=1,
        risk_appetite=Decimal("0"),
        metadata={"source_module": "sector_rotation", "feed_status": "missing", "reason": "NO_SECTOR_FEED"},
    )
    missing = adapt_vote_to_runtime_evidence(missing_vote)
    abstain = _router().collect_strategy_runtime_evidence(_fusion_decision())["strategy_attribution"]

    assert active["status"] == "ACTIVE_STRATEGY_VOTE"
    assert Decimal(active["confidence"]) == Decimal("0.7100")
    assert missing["status"] == "MISSING_FEED_TRUTH"
    assert any(record["status"] == "ABSTAIN" for record in abstain)


def test_council_metadata_records_participants_missing_degraded_and_reasons():
    records = (
        build_runtime_evidence_record(
            module_name="gamma_front",
            category="strategy_alpha",
            status="ACTIVE_STRATEGY_VOTE",
            input_truth="deterministic_vote",
            output_summary="active",
            effect="VOTE",
            reason="ACTIVE",
            timestamp_ns=T0_NS,
        ),
        build_runtime_evidence_record(
            module_name="liquidity_void",
            category="strategy_alpha",
            status="DEGRADED_FALLBACK",
            input_truth="lawful_book_truth",
            output_summary="degraded",
            effect="ADVISORY",
            reason="NATIVE_FEED_MISSING",
            timestamp_ns=T0_NS,
        ),
        build_runtime_evidence_record(
            module_name="sector_rotation",
            category="strategy_alpha",
            status="MISSING_FEED_TRUTH",
            input_truth="native_sector_feed_absent",
            output_summary="missing",
            effect="NO_EFFECT_WITH_REASON",
            reason="MISSING_FEED_TRUTH",
            timestamp_ns=T0_NS,
        ),
    )
    summary = summarize_runtime_evidence(records)

    assert summary["participants"] == ("gamma_front",)
    assert summary["degraded"] == ("liquidity_void",)
    assert summary["missing"] == ("sector_rotation",)
    assert records[2]["reason"] == "MISSING_FEED_TRUTH"


def test_alpha_modules_emit_native_or_explicit_missing_truth():
    records = _router().collect_strategy_runtime_evidence(_fusion_decision())["strategy_attribution"]
    by_name = {record["module_name"]: record for record in records}

    assert by_name["gamma_front"]["status"] == "ACTIVE_STRATEGY_VOTE"
    assert by_name["sector_rotation"]["status"] == "ACTIVE_STRATEGY_VOTE"
    assert by_name["liquidity_void"]["status"] == "ACTIVE_STRATEGY_VOTE"
    assert by_name["adaptive_dc"]["status"] == "MISSING_FEED_TRUTH"
    assert by_name["moving_floor"]["reason"] == "NO_PROTECTIVE_OR_ALPHA_VOTE_SUPPLIED"


def test_intelligence_and_world_awareness_enter_fusion_as_advisory_context():
    fusion = SignalFusion(SimpleNamespace(strategies=SimpleNamespace(sector_rotation_ranging_eligible=False)))
    strategy_records = _router().collect_strategy_runtime_evidence(_fusion_decision())["strategy_attribution"]
    fusion.update_strategy_evidence(strategy_records, T0_NS)
    fusion.update_intelligence_evidence([_intelligence_record("WhaleZoneEngine")], T0_NS)
    fusion.update_world_awareness_evidence([_world_awareness_record()], T0_NS)

    assert fusion.get_runtime_evidence()["strategy_attribution"]
    assert fusion.get_runtime_evidence()["intelligence_attribution"][0]["reason"] == "MISSING_FEED_TRUTH"
    assert fusion.get_runtime_evidence()["world_awareness_attribution"][0]["status"] == "INTENTIONALLY_BLOCKED_LIVE_ONLY"


def test_signal_fusion_preserves_missing_and_degraded_contributors_in_telemetry():
    fusion = SignalFusion(SimpleNamespace(strategies=SimpleNamespace(sector_rotation_ranging_eligible=False)))
    fusion.update_physical({"health_score": 0.90}, T0_NS)
    fusion.update_toxicity(SimpleNamespace(toxicity_score=0.10, regime=SimpleNamespace(value=0)), T0_NS)
    fusion.update_strategy_evidence(
        [
            build_runtime_evidence_record(
                module_name="LiquidityVoid",
                category="strategy_alpha",
                status="DEGRADED_FALLBACK",
                input_truth="lawful_top_of_book",
                output_summary="fallback only",
                effect="ADVISORY",
                reason="NATIVE_FEED_MISSING",
                timestamp_ns=T0_NS,
            )
        ],
        T0_NS,
    )

    fusion.fuse(T0_NS)
    telemetry = fusion.get_fusion_telemetry()

    assert telemetry["edge_attribution"]["LiquidityVoid"]["status"] == "DEGRADED_FALLBACK"
    assert telemetry["edge_attribution"]["WhaleFlow"]["status"] == "MISSING_FEED_TRUTH"
    assert "LiquidityVoid" in telemetry["degraded_fallback_summary"]
    assert "whale_flow" in telemetry["missing_inputs"]


def test_opportunity_ranking_abstains_with_explicit_reason_and_no_execution_authority():
    report = OpportunityRankingReport(
        timestamp_ns=T0_NS,
        total_equity_usd=Decimal("1000"),
        available_capital_usd=Decimal("1000"),
        opportunities=(),
        total_ranked=0,
        total_skipped=0,
        top_opportunity=None,
        top_opportunity_score=Decimal("0"),
        assumptions=("deterministic_empty_input",),
    )
    summary = summarize_opportunity_ranking(report)

    assert summary["status"] == "ABSTAIN"
    assert summary["reason"] == "NO_RANKABLE_OPPORTUNITY"
    assert summary["execution_authority"] == "none"


def test_decision_record_metadata_carries_runtime_flow_attribution_sections():
    fusion = SignalFusion(SimpleNamespace(strategies=SimpleNamespace(sector_rotation_ranging_eligible=False)))
    strategy_records = _router().collect_strategy_runtime_evidence(_fusion_decision())["strategy_attribution"]
    intelligence = [_intelligence_record()]
    world = [_world_awareness_record()]
    fusion.update_strategy_evidence(strategy_records, T0_NS)
    fusion.update_intelligence_evidence(intelligence, T0_NS)
    fusion.update_world_awareness_evidence(world, T0_NS)
    fusion.update_physical({"health_score": 0.90}, T0_NS)
    fusion.update_toxicity(SimpleNamespace(toxicity_score=0.10, regime=SimpleNamespace(value=0)), T0_NS)
    fusion.fuse(T0_NS)
    telemetry = fusion.get_fusion_telemetry()

    record = DecisionCompiler().compile(
        truth_frame=_truth_frame(),
        strategy_votes=[adapt_gamma_front_to_vote(_gamma_signal(), T0_NS, "seam7e-gamma")],
        additional_inputs={
            "edge_attribution": telemetry["edge_attribution"],
            "strategy_attribution": strategy_records,
            "intelligence_attribution": intelligence,
            "world_awareness_attribution": world,
            "fusion_summary": {"preferred_sleeve": fusion.get_last_fusion().preferred_sleeve},
            "opportunity_ranking_summary": {"status": "ABSTAIN", "reason": "NO_RANKABLE_OPPORTUNITY"},
            "missing_truth_summary": telemetry["missing_truth_summary"],
            "degraded_fallback_summary": telemetry["degraded_fallback_summary"],
            "blocked_or_abstained_summary": telemetry["blocked_or_abstained_summary"],
        },
    )

    assert record.metadata["strategy_attribution"] == strategy_records
    assert record.metadata["intelligence_attribution"] == intelligence
    assert record.metadata["world_awareness_attribution"] == world
    assert record.metadata["fusion_summary"]["preferred_sleeve"] == SleeveType.SHADOW_FRONT.value
    assert "edge_attribution" in record.metadata


def test_no_target_module_exposes_broker_mutation_or_live_endpoint_authority():
    modules = (
        _router(),
        SignalFusion(SimpleNamespace(strategies=SimpleNamespace(sector_rotation_ranging_eligible=False))),
    )
    forbidden_attrs = {
        "submit_order",
        "cancel_order",
        "replace_order",
        "rebalance",
        "liquidate",
        "broker_gateway",
        "order_router",
        "execution_engine",
    }

    for module in modules:
        assert forbidden_attrs.isdisjoint(set(dir(module)))


def _strategy_config() -> SimpleNamespace:
    return SimpleNamespace(
        strategies=SimpleNamespace(
            dark_pool_enabled=True,
            options_flow_enabled=False,
            dark_pool_volume_threshold=2.0,
            min_confidence=0.10,
            sector_rotation_enabled=True,
            sector_inflow_threshold=0.10,
            flv_max_hold_bars=3,
            flv_kelly_multiplier=0.50,
            flv_volume_anomaly_threshold=0.10,
            flv_spread_expansion_threshold=5.0,
            sector_rotation_ranging_eligible=False,
        )
    )


def _order_book(ts_ns: int, *, spread: float = 0.20) -> OrderBookSnapshot:
    mid = 100.0
    half = spread / 2.0
    return OrderBookSnapshot(
        symbol="AAPL",
        exchange_ts_ns=ts_ns,
        bids=[(mid - half, 1000.0), (mid - half - 0.01, 500.0)],
        asks=[(mid + half, 1000.0), (mid + half + 0.01, 500.0)],
    )


def _native_evidence_from_object(
    *,
    module_name: str,
    category: str,
    output: object,
    output_summary: str,
    effect: str,
    reason: str,
    timestamp_ns: int = T0_NS,
) -> dict:
    return build_runtime_evidence_record(
        module_name=module_name,
        category=category,
        status="ACTIVE_NATIVE_SIGNAL" if category == "strategy_alpha" else "ACTIVE_INTELLIGENCE_ADVISORY",
        input_truth="deterministic_native_shape_fixture_not_live_truth",
        output_summary=output_summary,
        effect=effect,
        reason=reason,
        timestamp_ns=timestamp_ns,
        confidence=getattr(output, "confidence", None),
        score_or_direction=getattr(output, "signal_direction", getattr(output, "level", None)),
        provenance={
            "native_type": type(output).__name__,
            "native_output": repr(output),
            "fixture_truth": "deterministic_native_shape_fixture_not_live_truth",
        },
    )


def _world_event_record(module_name: str, event: object) -> dict:
    return build_runtime_evidence_record(
        module_name=module_name,
        category="world_awareness",
        status="ACTIVE_WORLD_AWARENESS_ADVISORY",
        input_truth="deterministic_local_cache_fixture_not_live_truth",
        output_summary=type(event).__name__,
        effect="WORLD_AWARENESS_CONTEXT",
        reason="NATIVE_ADAPTER_NORMALIZED_LOCAL_CACHE_FIXTURE",
        timestamp_ns=T0_NS,
        provenance={
            "native_type": type(event).__name__,
            "canonical_truth_claimed": getattr(event, "canonical_truth_claimed", None),
            "live_attached": getattr(event, "live_attached", None),
        },
    )


def _native_strategy_records() -> dict[str, dict]:
    config = _strategy_config()

    moving_floor = TopologicalMovingFloor()
    moving_floor.process_tick(
        FloorMarketTick("AAPL", Decimal("100"), T0_NS, Decimal("1000"), Decimal("1000"))
    )
    _, _, floor_rec = moving_floor.process_tick(
        FloorMarketTick("AAPL", Decimal("97"), T0_NS + 2_000_000_000, Decimal("100"), Decimal("1000"))
    )
    assert floor_rec is not None
    moving_floor_record = adapt_vote_to_runtime_evidence(
        adapt_moving_floor_to_vote(floor_rec, T0_NS + 2_000_000_000, "seam7e-native-mf")
    )
    moving_floor_record["provenance"]["native_type"] = type(floor_rec).__name__
    moving_floor_record["provenance"]["native_output"] = repr(floor_rec)

    shans = ShansCurve(
        risk_guard=SimpleNamespace(),
        safety_gate=SimpleNamespace(),
        data_validator=SimpleNamespace(validate=lambda **_: (True, "fixture_ok")),
        entropy_decoder=SimpleNamespace(get_current=lambda _symbol: SimpleNamespace(entropy=0.20)),
        curvature_window=5,
        enable_denoising=False,
    )
    shans_signal = None
    for i, price in enumerate((100.0, 100.4, 100.9, 101.7, 102.8), start=1):
        shans_signal = shans.update_order_book("AAPL", price, 2000 + i * 100, 1000 - i * 20, 0.0, T0_NS + i)
    assert shans_signal is not None
    shans_record = _native_evidence_from_object(
        module_name="ShansCurve",
        category="strategy_alpha",
        output=shans_signal,
        output_summary="ShansCurveSignal",
        effect="ALPHA_SIGNAL",
        reason="NATIVE_SHANS_CURVE_SIGNAL",
    )

    adaptive = AdaptiveDC(initial_theta=Decimal("0.005"))
    adaptive.process_tick(DCMarketTick("AAPL", Decimal("100"), T0_NS))
    _, _, dc_rec = adaptive.process_tick(DCMarketTick("AAPL", Decimal("101"), T0_NS + 1))
    assert dc_rec is not None
    adaptive_record = adapt_vote_to_runtime_evidence(
        adapt_adaptive_dc_to_vote(dc_rec, T0_NS + 1, "seam7e-native-dc")
    )
    adaptive_record["provenance"]["native_type"] = type(dc_rec).__name__
    adaptive_record["provenance"]["native_output"] = repr(dc_rec)

    gamma = GammaFrontStrategy(config, "AAPL")
    gamma_signal = None
    for i in range(5):
        gamma.update_dark_pool(
            DarkPoolPrint(symbol="AAPL", exchange_ts_ns=T0_NS + i, price=100.0, size=100.0, exchange="ATS", is_buy=True)
        )
    gamma_signal = gamma.update_dark_pool(
        DarkPoolPrint(symbol="AAPL", exchange_ts_ns=T0_NS + 10, price=100.0, size=1000.0, exchange="ATS", is_buy=True)
    )
    assert gamma_signal is not None
    gamma_record = adapt_vote_to_runtime_evidence(
        adapt_gamma_front_to_vote(gamma_signal, gamma_signal.exchange_ts_ns, "seam7e-native-gamma")
    )
    gamma_record["provenance"]["native_type"] = type(gamma_signal).__name__
    gamma_record["provenance"]["native_output"] = repr(gamma_signal)

    sector = SectorRotationStrategy(config, "AAPL")
    sector_signal = None
    for i in range(10):
        sector.update_candle(100.0 + (i * 0.01), 100.0, T0_NS + i)
    sector_signal = sector.update_candle(101.0, 1000.0, T0_NS + 20)
    assert sector_signal is not None
    sector_record = _native_evidence_from_object(
        module_name="sector_rotation",
        category="strategy_alpha",
        output=sector_signal,
        output_summary="StrategySignal",
        effect="ALPHA_SIGNAL",
        reason="NATIVE_SECTOR_ROTATION_SIGNAL",
        timestamp_ns=sector_signal.exchange_ts_ns,
    )

    flv = LiquidityVoidStrategy(config, "AAPL")
    flv.update_topology(
        TopologicalSignal(
            coherence_score=0.90,
            betti_0=1,
            betti_1=2,
            persistence_score=0.80,
            super_void_detected=True,
            structural_collapse=False,
            confidence=0.88,
            exchange_ts_ns=T0_NS,
            reason="deterministic_tpe_fixture",
        )
    )
    flv_signal = flv.update_order_book(_order_book(T0_NS + 30, spread=0.20))
    assert flv_signal is not None
    flv_record = _native_evidence_from_object(
        module_name="liquidity_void",
        category="strategy_alpha",
        output=flv_signal,
        output_summary="StrategySignal",
        effect="ALPHA_SIGNAL",
        reason="NATIVE_LIQUIDITY_VOID_SIGNAL",
        timestamp_ns=flv_signal.exchange_ts_ns,
    )

    hedge = HedgingFlow()
    hedge_assessment = hedge.assess(
        PortfolioExposureSnapshot(
            net_delta=Decimal("2000"),
            total_equity=Decimal("10000"),
            target_symbol="AAPL",
            sleeve="hedging_flow",
        ),
        HedgeMarketContext(symbol="AAPL", price=Decimal("100"), bid=Decimal("99.99"), ask=Decimal("100.01")),
    )
    hedge_rec = hedge.recommend(hedge_assessment, HedgeMarketContext(symbol="AAPL", price=Decimal("100")))
    assert hedge_assessment.hedge_required is True
    assert hedge_rec is not None
    hedge_record = _native_evidence_from_object(
        module_name="hedging_flow",
        category="strategy_alpha",
        output=hedge_rec,
        output_summary="HedgeRecommendation",
        effect="ADVISORY",
        reason="NATIVE_HEDGING_FLOW_RECOMMENDATION",
    )

    return {
        "MovingFloor": moving_floor_record,
        "ShansCurve": shans_record,
        "AdaptiveDC": adaptive_record,
        "gamma_front": gamma_record,
        "sector_rotation": sector_record,
        "liquidity_void": flv_record,
        "hedging_flow": hedge_record,
    }


def _native_intelligence_records() -> dict[str, dict]:
    sentiment = SentimentEngine(min_sources=2)
    sentiment.update_source("AAPL", "technical", 0.40, T0_NS, confidence=0.90)
    sentiment.update_source("AAPL", "macro", 0.30, T0_NS + 1, confidence=0.80)
    aggregate = sentiment.aggregate("AAPL", T0_NS + 2)
    assert aggregate is not None

    velocity = SentimentVelocityEngine(min_history_points=3)
    vector = None
    for i, value in enumerate((0.10, 0.20, 0.35), start=1):
        vector = velocity.update_sentiment(value, T0_NS + i)
    macro = velocity.analyze(T0_NS + 10)
    assert vector is not None
    assert macro is not None

    whale = WhaleZoneEngine({"zone_stability_required": 2, "zone_confidence_threshold": 0.10})
    zone = None
    for i in range(4):
        zone = whale.update("AAPL", close=101.9, high=102.0, low=100.0, volume=5000.0, vwap=101.7, exchange_ts_ns=T0_NS + i)
    assert zone is not None

    regime_detector = RegimeDetector(min_samples=1, transition_cooldown_ns=0)
    feature_vector = FeatureVector(
        decision_uuid="seam7e-native-regime",
        timestamp_ns=T0_NS,
        symbol="AAPL",
        features=FeaturePayload(
            topological_coherence=Decimal("0.90"),
            entropy=Decimal("0.20"),
            void_depth=Decimal("0.10"),
            sentiment_velocity=Decimal("0.50"),
        ),
    )
    regime = regime_detector.update(feature_vector, T0_NS)
    assert regime in {RegimeType.TRENDING_BULL, RegimeType.UNKNOWN}

    candles = [
        Candle(symbol="AAPL", exchange_ts_ns=T0_NS + i, open=100 + i, high=101 + i, low=99 + i, close=100.5 + i, volume=1000 + i * 10)
        for i in range(8)
    ]
    feature_builder = FeatureBuilder(slow_window=3, fast_window=2)
    features = feature_builder.build_all_features(
        candles,
        len(candles),
        order_book=_order_book(T0_NS + 50, spread=0.10),
        historical_spreads=[1.0, 1.1, 1.2],
        whale_zone=(99.0, 103.0),
    )
    assert "volatility_zscore" in features
    assert "order_book_imbalance" in features

    ghost = FastGhostTickDetector(window=4, threshold=3.5)
    for price in (100.0, 100.1, 100.2, 100.3):
        ghost.update(1, price)
        ghost.update(2, price * 2)
    ghost_flags = ghost.detect_vector([1], np.array([100.4]))
    assert ghost_flags.shape == (1,)

    validator = DataValidator(stale_threshold_seconds=10)
    validation = validator.validate_order_book(_order_book(T0_NS + 80, spread=0.10), current_time_ns=T0_NS + 81)
    assert validation.is_valid is True

    return {
        "sentiment_engine": _native_evidence_from_object(
            module_name="sentiment_engine",
            category="intelligence",
            output=aggregate,
            output_summary="AggregateSentiment",
            effect="INTELLIGENCE_CONTEXT",
            reason="NATIVE_SENTIMENT_AGGREGATE",
        ),
        "sentiment_velocity": _native_evidence_from_object(
            module_name="sentiment_velocity",
            category="intelligence",
            output=vector,
            output_summary="SentimentVector",
            effect="INTELLIGENCE_CONTEXT",
            reason="NATIVE_SENTIMENT_VECTOR",
        ),
        "whale_zone_engine": _native_evidence_from_object(
            module_name="whale_zone_engine",
            category="intelligence",
            output=zone,
            output_summary="WhalePresenceZone",
            effect="INTELLIGENCE_CONTEXT",
            reason="NATIVE_WHALE_ZONE",
        ),
        "regime_detector": _native_evidence_from_object(
            module_name="regime_detector",
            category="intelligence",
            output=SimpleNamespace(confidence=regime_detector.get_current_confidence(), signal_direction=regime.value),
            output_summary="RegimeType",
            effect="INTELLIGENCE_CONTEXT",
            reason="NATIVE_REGIME_DETECTION",
        ),
        "feature_builder": _native_evidence_from_object(
            module_name="feature_builder",
            category="intelligence",
            output=SimpleNamespace(confidence=1.0, signal_direction="feature_dict"),
            output_summary="feature_dict",
            effect="INTELLIGENCE_CONTEXT",
            reason="NATIVE_FEATURE_BUILD",
        ),
        "ghost_tick_detector": _native_evidence_from_object(
            module_name="ghost_tick_detector",
            category="intelligence",
            output=SimpleNamespace(confidence=1.0, signal_direction=f"ghost_flags={ghost_flags.tolist()}"),
            output_summary="np.ndarray[bool]",
            effect="INTELLIGENCE_CONTEXT",
            reason="NATIVE_GHOST_TICK_VECTOR",
        ),
        "validators": _native_evidence_from_object(
            module_name="validators",
            category="intelligence",
            output=SimpleNamespace(confidence=1.0, signal_direction=f"is_valid={validation.is_valid}"),
            output_summary="ValidationResult",
            effect="INTELLIGENCE_CONTEXT",
            reason="NATIVE_DATA_VALIDATION",
        ),
    }


def _native_world_records() -> dict[str, dict]:
    payload = {
        "symbol": "AAPL",
        "issuer": "Deterministic Fixture Issuer",
        "actor": "Deterministic Fixture Actor",
        "source_event_type": "deterministic_cache_fixture",
        "fixture_only": True,
    }
    adapters = {
        "openinsider_adapter": OpenInsiderAdapter(),
        "sec_edgar_adapter": SecEdgarAdapter(),
        "capitol_trades_adapter": CapitolTradesAdapter(),
        "quiver_free_adapter": QuiverFreeAdapter(),
        "official_calendars_adapter": OfficialCalendarsAdapter(),
        "official_releases_adapter": OfficialReleasesAdapter(),
    }
    records = {
        "world_awareness/source_catalog": build_runtime_evidence_record(
            module_name="world_awareness/source_catalog",
            category="world_awareness",
            status="ACTIVE_WORLD_AWARENESS_ADVISORY",
            input_truth="catalog_status_function",
            output_summary="source_status_signature",
            effect="WORLD_AWARENESS_CONTEXT",
            reason="NATIVE_SOURCE_STATUS_SIGNATURE",
            timestamp_ns=T0_NS,
            provenance={"native_output": source_status_signature(SourceFamily.SEC_EDGAR)},
        )
    }
    for name, adapter in adapters.items():
        event = adapter.normalize_payload(payload)
        assert event.canonical_truth_claimed is False
        assert event.live_attached is False
        records[name] = _world_event_record(name, event)
    return records


def test_seam7e_completion_correction_calls_every_native_module_and_carries_output_to_decision_record():
    strategy_records_by_name = _native_strategy_records()
    intelligence_records_by_name = _native_intelligence_records()
    world_records_by_name = _native_world_records()

    ranker = OpportunityRanker(min_net_edge_bps=Decimal("1"), min_confidence=Decimal("0.10"))
    ranking_report = ranker.rank(
        candidates=[("AAPL", "gamma_front", Decimal("20"), Decimal("0.80"), Decimal("1000"))],
        instruments={
            "AAPL": SimpleNamespace(
                symbol="AAPL",
                constraints=SimpleNamespace(max_spread_bps=Decimal("2.0")),
            )
        },
        existing_exposures={},
        total_equity=Decimal("10000"),
        available_capital=Decimal("5000"),
        timestamp_ns=T0_NS,
    )
    ranking_summary = summarize_opportunity_ranking(ranking_report)
    assert ranking_report.total_ranked == 1
    assert ranking_summary["status"] == "RANKED"
    assert ranking_summary["execution_authority"] == "none"

    fusion = SignalFusion(SimpleNamespace(strategies=SimpleNamespace(sector_rotation_ranging_eligible=False)))
    fusion.update_strategy_evidence(strategy_records_by_name.values(), T0_NS)
    fusion.update_intelligence_evidence(intelligence_records_by_name.values(), T0_NS)
    fusion.update_world_awareness_evidence(world_records_by_name.values(), T0_NS)
    fusion.update_physical({"health_score": 0.90}, T0_NS)
    fusion.update_toxicity(SimpleNamespace(toxicity_score=0.10, regime=SimpleNamespace(value=0)), T0_NS)
    fusion.fuse(T0_NS)
    telemetry = fusion.get_fusion_telemetry()

    all_records_by_name = {
        record["module_name"]: record
        for record in (
            *strategy_records_by_name.values(),
            *intelligence_records_by_name.values(),
            *world_records_by_name.values(),
        )
    }
    assert set(all_records_by_name) >= {
        "moving_floor",
        "ShansCurve",
        "adaptive_dc",
        "gamma_front",
        "sector_rotation",
        "liquidity_void",
        "hedging_flow",
        "sentiment_engine",
        "sentiment_velocity",
        "whale_zone_engine",
        "regime_detector",
        "feature_builder",
        "ghost_tick_detector",
        "validators",
        "world_awareness/source_catalog",
        "openinsider_adapter",
        "sec_edgar_adapter",
        "capitol_trades_adapter",
        "quiver_free_adapter",
        "official_calendars_adapter",
        "official_releases_adapter",
    }
    edge_attribution = telemetry["edge_attribution"]
    for module_name, record in all_records_by_name.items():
        assert module_name in edge_attribution
        provenance = edge_attribution[module_name]["provenance"]
        assert provenance.get("native_type") or provenance.get("native_output")
        assert record["status"] in {
            "ACTIVE_NATIVE_SIGNAL",
            "ACTIVE_PROTECTION",
            "ACTIVE_STRATEGY_VOTE",
            "ACTIVE_INTELLIGENCE_ADVISORY",
            "ACTIVE_WORLD_AWARENESS_ADVISORY",
        }

    record = DecisionCompiler().compile(
        truth_frame=_truth_frame(),
        strategy_votes=[
            adapt_gamma_front_to_vote(_gamma_signal(), T0_NS, "seam7e-native-metadata")
        ],
        additional_inputs={
            "edge_attribution": edge_attribution,
            "strategy_attribution": tuple(strategy_records_by_name.values()),
            "intelligence_attribution": tuple(intelligence_records_by_name.values()),
            "world_awareness_attribution": tuple(world_records_by_name.values()),
            "fusion_summary": {"preferred_sleeve": fusion.get_last_fusion().preferred_sleeve},
            "opportunity_ranking_summary": ranking_summary,
            "missing_truth_summary": telemetry["missing_truth_summary"],
            "degraded_fallback_summary": telemetry["degraded_fallback_summary"],
            "blocked_or_abstained_summary": telemetry["blocked_or_abstained_summary"],
        },
    )

    for module_name in all_records_by_name:
        assert module_name in record.metadata["edge_attribution"]
    assert record.metadata["opportunity_ranking_summary"]["status"] == "RANKED"
    assert record.metadata["opportunity_ranking_summary"]["execution_authority"] == "none"
