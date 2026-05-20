from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.brain.signal_fusion import SignalFusion
from app.constants import ControlMode, SleeveType
from app.core.decision_compiler import DecisionCompiler
from app.models.contracts import (
    ExchangeTruth,
    ExecutionTruth,
    PortfolioTruth,
    RiskTruth,
    StrategyTruth,
    StrategyVote,
    TruthFrame,
)
from app.models.enums import SignalDirection, SignalType, StrategyID, TruthStatus
from app.models.fusion import FusionDecision
from app.portfolio.opportunity_ranking import (
    OpportunityRankingReport,
    summarize_opportunity_ranking,
)
from app.strategies.strategy_router import StrategyRouter
from app.strategies.strategy_vote_adapters import (
    adapt_gamma_front_to_vote,
    adapt_moving_floor_to_vote,
    adapt_vote_to_runtime_evidence,
)
from app.strategies.council_metadata import (
    build_runtime_evidence_record,
    summarize_runtime_evidence,
)
from app.models.signals import StrategySignal
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
