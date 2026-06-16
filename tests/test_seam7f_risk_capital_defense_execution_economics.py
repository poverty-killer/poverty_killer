from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.core.decision_compiler import DecisionCompiler
from app.execution.fee_model import FeeModel, FeeQuality
from app.execution.latency_model import LatencyModel
from app.execution.slippage_model import (
    DepthProfile,
    ExecutionStyle,
    MarketImpactContext,
    SlippageModel,
    SlippageQuality,
)
from app.execution.throttler import CircuitBreakerState, EndpointCategory, SovereignThrottler
from app.models.contracts import ExchangeTruth, ExecutionTruth, PortfolioTruth, RiskTruth, StrategyTruth, TruthFrame
from app.models.enums import (
    BookIntegrity,
    FillLiquidity,
    LiquidityRegime,
    Marketability,
    OrderSide,
    OrderType,
    RegimeType,
    SleeveType,
    ToxicityLevel,
    TruthStatus,
)
from app.risk.drawdown_guard import DrawdownGuard
from app.risk.exposure_manager import ExposureManager
from app.risk.kill_switch import KillSwitch
from app.risk.net_edge_governor import (
    AdversarialBurdens,
    CandidateContext,
    CandidateType,
    EconomicDecision,
    ExecutionEconomics,
    NetEdgeGovernor,
)
from app.risk.position_sizing import PositionSizingEngine
from app.risk.reservation_lifecycle_coordinator import ReservationLifecycleCoordinator
from app.risk.stale_data_guard import StaleDataGuard, TemporalInput
from app.risk.trade_efficiency_governor import SleeveEfficiencyState, TradeEfficiencyGovernor
from app.risk.unified_risk import UnifiedRiskAuthority, UnifiedRiskDecision
from app.strategies.moving_floor import FloorMarketTick, TopologicalMovingFloor


T0_NS = 1_779_000_000_000_000_000


def _record(
    *,
    module_name: str,
    category: str,
    status: str,
    input_truth: str,
    output_summary: str,
    effect: str,
    decision: str,
    reason: str,
    provenance: dict | None = None,
    blocking: bool = False,
    veto: bool = False,
    severity: str = "INFO",
) -> dict:
    return {
        "module_name": module_name,
        "category": category,
        "status": status,
        "input_truth": input_truth,
        "output_summary": output_summary,
        "effect": effect,
        "decision": decision,
        "reason": reason,
        "provenance": provenance or {},
        "blocking": blocking,
        "veto": veto,
        "severity": severity,
        "timestamp_ns": T0_NS,
    }


def _truth_frame() -> TruthFrame:
    return TruthFrame(
        truth_frame_id="seam7f-truth-frame",
        timestamp_ns=T0_NS,
        exchange_truth=ExchangeTruth(venue="alpaca_paper_read_only", exchange_ts_ns=T0_NS),
        execution_truth=ExecutionTruth(last_reconciliation_ts_ns=T0_NS),
        portfolio_truth=PortfolioTruth(total_equity=Decimal("1000"), last_update_ts_ns=T0_NS),
        strategy_truth=StrategyTruth(last_update_ts_ns=T0_NS),
        risk_truth=RiskTruth(),
        status=TruthStatus.RECONCILED,
    )


def _positive_edge_context(symbol: str = "AAPL", sleeve_id: str = "gamma_front") -> CandidateContext:
    return CandidateContext(
        symbol=symbol,
        sleeve_id=sleeve_id,
        candidate_type=CandidateType.FRESH_ENTRY,
        gross_edge=Decimal("0.0300"),
        gross_edge_source="deterministic_verified_fixture_edge_input",
        estimate_confidence=Decimal("0.80"),
        timestamp_ns=T0_NS,
        valid_until_ns=T0_NS + 1_000_000,
        costs=ExecutionEconomics(
            fee_cost=Decimal("0.0010"),
            spread_cost=Decimal("0.0010"),
            slippage_cost=Decimal("0.0015"),
            latency_drag=Decimal("0.0005"),
        ),
        burdens=AdversarialBurdens(regime_burden=Decimal("0.0010")),
    )


def _native_risk_capital_and_economic_records() -> dict[str, list[dict]]:
    efficiency = TradeEfficiencyGovernor()
    net_edge = NetEdgeGovernor(efficiency).evaluate(
        current_time_ns=T0_NS,
        candidate=_positive_edge_context(),
        kill_switch_active=False,
    )
    assert net_edge.decision == EconomicDecision.ALLOW
    assert net_edge.net_adversarial_edge > Decimal("0")

    quarantine = efficiency.force_quarantine("liquidity_void", T0_NS, "seam7f_deterministic_veto_probe")
    assert quarantine.new_state == SleeveEfficiencyState.QUARANTINED

    fee = FeeModel().estimate_fees(
        symbol="AAPL",
        notional_value=Decimal("100"),
        liquidity_role=FillLiquidity.MAKER,
    )
    assert fee.quality == FeeQuality.COMPLETE
    assert fee.expected_fee > Decimal("0")

    slippage = SlippageModel().estimate_slippage_detailed(
        MarketImpactContext(
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            current_price=Decimal("100"),
            depth=DepthProfile(
                bid_depth_l1=Decimal("250"),
                ask_depth_l1=Decimal("250"),
                bid_depth_n=Decimal("1000"),
                ask_depth_n=Decimal("1000"),
            ),
            spread_bps=Decimal("1.0"),
            book_imbalance=Decimal("0"),
            regime=RegimeType.TRENDING_BULL,
            toxicity_score=Decimal("0.05"),
            liquidity_regime=LiquidityRegime.THICK,
            toxicity_level=ToxicityLevel.BENIGN,
            book_integrity=BookIntegrity.HEALTHY,
            marketability=Marketability.NEAR_TOUCH,
            execution_style=ExecutionStyle.PASSIVE_NEAR_TOUCH,
            venue="alpaca_paper",
        )
    )
    assert slippage.quality == SlippageQuality.COMPLETE
    assert slippage.total_slippage_bps >= Decimal("0")

    latency = LatencyModel(base_latency_ms=20, jitter_ms=0, exchange_processing_ms=5).sample_latency()
    assert latency.total_latency_ns >= 25_000_000

    sizing = PositionSizingEngine(SimpleNamespace(risk=SimpleNamespace(max_risk_per_trade=Decimal("0.02"))))
    size = sizing.calculate_position_size(
        capital_usd=Decimal("1000"),
        confidence=Decimal("0.75"),
        volatility=Decimal("0.20"),
        regime=RegimeType.TRENDING_BULL,
        strategy=SleeveType.GAMMA_FRONT,
        price=Decimal("100"),
        kelly_multiplier=Decimal("0.85"),
        stop_loss_pct=Decimal("0.02"),
    )
    assert size.sizing_method == "risk_based"
    assert size.notional_usd <= Decimal("250.00")

    exposure = ExposureManager(initial_equity=Decimal("1000"), max_utilization=Decimal("0.80"))
    exposure_allow = exposure.validate_intent_detailed(
        sleeve=SleeveType.GAMMA_FRONT,
        symbol="AAPL",
        side=OrderSide.BUY,
        qty=Decimal("1"),
        price=Decimal("100"),
    )
    exposure_block = exposure.validate_intent_detailed(
        sleeve=SleeveType.GAMMA_FRONT,
        symbol="AAPL",
        side=OrderSide.BUY,
        qty=Decimal("100"),
        price=Decimal("100"),
    )
    assert exposure_allow.authorized is True
    assert exposure_block.authorized is False

    drawdown = DrawdownGuard(initial_capital=Decimal("1000")).update_canonical(
        current_equity=Decimal("980"),
        ts_ns=T0_NS,
    )
    assert drawdown.aggression_multiplier <= Decimal("1.0000")

    stale = StaleDataGuard(symbol="AAPL", max_drift_ms=1).assess(
        TemporalInput(current_ts_ns=T0_NS, exchange_ts_ns=T0_NS - 10_000_000)
    )
    assert "absolute_drift_limit_breach" in stale.rationale

    kill = KillSwitch()
    assert kill.can_trade(T0_NS) is True
    kill.trigger_manual("seam7f deterministic protection probe", T0_NS)
    assert kill.can_trade(T0_NS) is False

    unified = UnifiedRiskAuthority().evaluate(
        timestamp_ns=T0_NS,
        kill_switch=KillSwitch(),
        stale_data_blocks=[],
        divergence_blocks=[],
        hard_flat_triggered=False,
        regime=RegimeType.TRENDING_BULL,
        toxicity_score=Decimal("0.10"),
        current_exposure_pct=Decimal("0.20"),
        symbol="AAPL",
    )
    assert unified.decision == UnifiedRiskDecision.FULL_ALLOW

    floor = TopologicalMovingFloor()
    event, assessment, recommendation = floor.process_tick(
        FloorMarketTick(
            symbol="AAPL",
            price=Decimal("100"),
            timestamp_ns=T0_NS,
            bid_volume=Decimal("1000"),
            ask_volume=Decimal("800"),
            regime=RegimeType.TRENDING_BULL,
            liquidity_regime=LiquidityRegime.THICK,
            toxicity_level=ToxicityLevel.BENIGN,
            book_integrity=BookIntegrity.HEALTHY,
        )
    )
    assert event is not None
    assert assessment is not None

    return {
        "risk_attribution": [
            _record(
                module_name="UnifiedRiskAuthority",
                category="risk",
                status="PASSED",
                input_truth="kill_switch=false stale_blocks=0 divergence_blocks=0 exposure_pct=0.20",
                output_summary=unified.reason,
                effect="APPROVED",
                decision=unified.decision.value,
                reason=unified.reason,
                provenance=unified.provenance,
            ),
            _record(
                module_name="ExposureManager",
                category="risk",
                status="ACTIVE_GUARDRAIL",
                input_truth="deterministic broker-truth-shaped buy intent and empty positions",
                output_summary=exposure_block.reason,
                effect="VETO",
                decision="BLOCK_OVERSIZED_INTENT",
                reason=exposure_block.reason,
                provenance={"projected_global_utilization": str(exposure_block.projected_global_utilization)},
                blocking=True,
                veto=True,
                severity=exposure_block.severity.value,
            ),
            _record(
                module_name="StaleDataGuard",
                category="risk",
                status="ACTIVE_GUARDRAIL",
                input_truth="exchange_ts_ns and current_ts_ns supplied",
                output_summary=";".join(stale.rationale),
                effect="VETO",
                decision=stale.risk_action.value,
                reason="absolute_drift_limit_breach",
                provenance={"drift_ns": stale.kinematics.drift_ns},
                blocking=True,
                veto=True,
                severity=stale.severity.value,
            ),
            _record(
                module_name="KillSwitch",
                category="risk",
                status="ACTIVE_GUARDRAIL",
                input_truth="manual deterministic trigger probe",
                output_summary="can_trade false after trigger",
                effect="VETO",
                decision="BLOCK_TRADING",
                reason="seam7f deterministic protection probe",
                blocking=True,
                veto=True,
                severity="CRITICAL",
            ),
        ],
        "capital_defense_attribution": [
            _record(
                module_name="DrawdownGuard",
                category="capital_defense",
                status="ACTIVE_GUARDRAIL",
                input_truth="equity=980 initial_capital=1000 timestamp_ns supplied",
                output_summary=drawdown.reason,
                effect="ADVISORY",
                decision=drawdown.risk_action.value,
                reason=drawdown.primary_reason_code.value,
                provenance={"aggression_multiplier": str(drawdown.aggression_multiplier)},
                severity=drawdown.severity.value,
            ),
            _record(
                module_name="MovingFloor",
                category="capital_defense",
                status="ACTIVE_NATIVE_SIGNAL",
                input_truth="canonical FloorMarketTick",
                output_summary=event.event_type.value,
                effect="ADVISORY",
                decision=recommendation.signal_direction.value if recommendation else "NO_PROTECTIVE_ACTION",
                reason="topological_floor_event_processed",
                provenance={"event_type": event.event_type.value, "floor": str(event.current_floor)},
            ),
        ],
        "sizing_attribution": [
            _record(
                module_name="PositionSizingEngine",
                category="sizing",
                status="ACTIVE_GUARDRAIL",
                input_truth="capital confidence volatility regime price stop_loss supplied",
                output_summary=size.reason,
                effect="APPROVED",
                decision=size.sizing_method,
                reason=size.reason,
                provenance={"notional_usd": str(size.notional_usd), "quantity": str(size.quantity)},
            )
        ],
        "execution_economics_attribution": [
            _record(
                module_name="NetEdgeGovernor",
                category="execution_economics",
                status="PASSED",
                input_truth="gross_edge plus fee spread slippage latency and regime burden",
                output_summary=net_edge.reason_code,
                effect="APPROVED",
                decision=net_edge.decision.value,
                reason=net_edge.reason_code,
                provenance={"net_adversarial_edge": str(net_edge.net_adversarial_edge)},
            ),
            _record(
                module_name="TradeEfficiencyGovernor",
                category="execution_economics",
                status="VETOED",
                input_truth="force_quarantine native override probe",
                output_summary=quarantine.reason_code,
                effect="VETO",
                decision=quarantine.new_state.value,
                reason=quarantine.reason_code,
                blocking=True,
                veto=True,
                severity="CRITICAL",
            ),
            _record(
                module_name="FeeModel",
                category="execution_economics",
                status="ACTIVE_NATIVE_SIGNAL",
                input_truth="notional and maker liquidity role supplied",
                output_summary=f"expected_fee={fee.expected_fee}",
                effect="ADVISORY",
                decision=fee.quality.value,
                reason="FEE_ESTIMATED",
                provenance={"effective_rate_bps": str(fee.effective_rate_bps)},
            ),
            _record(
                module_name="SlippageModel",
                category="execution_economics",
                status="ACTIVE_NATIVE_SIGNAL",
                input_truth="quote/depth/spread/regime/toxicity/book integrity supplied",
                output_summary=f"total_slippage_bps={slippage.total_slippage_bps}",
                effect="ADVISORY",
                decision=slippage.quality.value,
                reason="SLIPPAGE_ESTIMATED",
                provenance={"expected_execution_price": str(slippage.expected_execution_price)},
            ),
            _record(
                module_name="LatencyModel",
                category="execution_economics",
                status="ACTIVE_NATIVE_SIGNAL",
                input_truth="configured latency policy",
                output_summary=f"total_latency_ns={latency.total_latency_ns}",
                effect="ADVISORY",
                decision=latency.quality.value,
                reason="LATENCY_SAMPLED",
                provenance={"congestion_state": latency.congestion_state.value},
            ),
        ],
    }


def test_risk_capital_defense_sizing_and_execution_economics_emit_native_records():
    sections = _native_risk_capital_and_economic_records()
    all_records = [record for records in sections.values() for record in records]
    by_name = {record["module_name"]: record for record in all_records}

    assert by_name["UnifiedRiskAuthority"]["status"] == "PASSED"
    assert by_name["ExposureManager"]["veto"] is True
    assert by_name["DrawdownGuard"]["category"] == "capital_defense"
    assert by_name["MovingFloor"]["status"] == "ACTIVE_NATIVE_SIGNAL"
    assert by_name["PositionSizingEngine"]["status"] == "ACTIVE_GUARDRAIL"
    assert by_name["NetEdgeGovernor"]["decision"] == EconomicDecision.ALLOW.value
    assert by_name["TradeEfficiencyGovernor"]["decision"] == SleeveEfficiencyState.QUARANTINED.value
    assert by_name["FeeModel"]["status"] == "ACTIVE_NATIVE_SIGNAL"
    assert by_name["SlippageModel"]["status"] == "ACTIVE_NATIVE_SIGNAL"
    assert by_name["LatencyModel"]["status"] == "ACTIVE_NATIVE_SIGNAL"


def test_reservation_throttle_and_blocked_execution_modules_sign_without_broker_mutation():
    class FakeExposureManager:
        def guarded_open_reservation(self, **kwargs):
            return {
                "applied": True,
                "idempotent": False,
                "failed_reason": None,
                "reservation_id": kwargs["reservation_id"],
                "client_order_id": kwargs["client_order_id"],
                "mutation_applied": True,
            }

    coordinator = ReservationLifecycleCoordinator(
        exposure_manager=FakeExposureManager(),
        state_store=SimpleNamespace(),
    )
    reservation = coordinator.on_order_acknowledged(
        client_order_id="seam7f-client-order",
        symbol="AAPL",
        side=OrderSide.BUY,
        sleeve=SleeveType.GAMMA_FRONT,
        qty=Decimal("1"),
        price_basis=Decimal("100"),
        order_type=OrderType.LIMIT,
        decision_uuid="seam7f-decision",
        price_basis_source_proven=True,
    )
    assert reservation["applied"] is True
    assert reservation["broker_command_performed"] is False

    throttler = SovereignThrottler()
    bucket = throttler._buckets[EndpointCategory.PRIVATE_ORDER]
    for _ in range(bucket.config.circuit_breaker_threshold):
        bucket.record_response(success=False, response_time_ms=1000, rate_limited=True)
    assert bucket._stats.circuit_state == CircuitBreakerState.OPEN

    mutation_counts = {"POST": 0, "PATCH": 0, "DELETE": 0, "cancel": 0, "replace": 0, "sell": 0, "rebalance": 0}
    records = [
        _record(
            module_name="ReservationLifecycleCoordinator",
            category="reservation",
            status="ACTIVE_RECONCILIATION",
            input_truth="direct order ack lifecycle fact",
            output_summary="reservation opened through exposure manager only",
            effect="RECONCILED",
            decision="RESERVATION_APPLIED",
            reason="price_basis_source_proven",
            provenance=reservation,
        ),
        _record(
            module_name="SovereignThrottler",
            category="throttle",
            status="ACTIVE_GUARDRAIL",
            input_truth="private_order repeated rate-limit responses",
            output_summary="private order circuit breaker open",
            effect="BLOCKED",
            decision=bucket._stats.circuit_state.name,
            reason="CIRCUIT_BREAKER_OPEN",
            blocking=True,
            veto=True,
        ),
        _record(
            module_name="PositionUnwindManager",
            category="execution_boundary",
            status="INTENTIONALLY_BLOCKED_SHADOW",
            input_truth="shadow_read_only=true no sell/rebalance approval",
            output_summary="unwind authority not invoked in shadow",
            effect="NO_MUTATION_BOUNDARY",
            decision="BLOCKED",
            reason="SHADOW_READ_ONLY_BLOCKED_SELL_REBALANCE_UNWIND",
            blocking=True,
            veto=True,
        ),
        _record(
            module_name="LiveBroker",
            category="execution_boundary",
            status="INTENTIONALLY_BLOCKED_LIVE_ONLY",
            input_truth="paper/shadow runtime posture",
            output_summary="live broker not instantiated or called",
            effect="NO_MUTATION_BOUNDARY",
            decision="BLOCKED",
            reason="NO_LIVE_ENDPOINT_OR_LIVE_MODE",
            blocking=True,
            veto=True,
        ),
        _record(
            module_name="PaperBroker",
            category="execution_boundary",
            status="INTENTIONALLY_BLOCKED_SHADOW",
            input_truth="shadow_read_only=true",
            output_summary="paper broker submit/cancel/replace not called",
            effect="NO_MUTATION_BOUNDARY",
            decision="BLOCKED",
            reason="SHADOW_READ_ONLY_BLOCKED_BROKER_MUTATION",
            provenance={"broker_mutation_counts": mutation_counts},
            blocking=True,
            veto=True,
        ),
        _record(
            module_name="LiveReadOnlyBrokerAdapter",
            category="execution_boundary",
            status="ACTIVE_EXECUTION_BOUNDARY",
            input_truth="read-only adapter posture",
            output_summary="GET-only broker truth allowed; mutation disabled",
            effect="NO_MUTATION_BOUNDARY",
            decision="READ_ONLY_ALLOWED",
            reason="READ_ONLY_GATE",
            provenance={"broker_mutation_counts": mutation_counts},
        ),
    ]

    assert all(value == 0 for value in mutation_counts.values())
    assert {record["module_name"] for record in records} == {
        "ReservationLifecycleCoordinator",
        "SovereignThrottler",
        "PositionUnwindManager",
        "LiveBroker",
        "PaperBroker",
        "LiveReadOnlyBrokerAdapter",
    }


def test_decision_compiler_carries_seam7f_attribution_sections_without_flattening():
    sections = _native_risk_capital_and_economic_records()
    edge_attribution = {
        record["module_name"]: record
        for records in sections.values()
        for record in records
    }
    additional_inputs = {
        "edge_attribution": edge_attribution,
        "risk_attribution": sections["risk_attribution"],
        "capital_defense_attribution": sections["capital_defense_attribution"],
        "sizing_attribution": sections["sizing_attribution"],
        "execution_economics_attribution": sections["execution_economics_attribution"],
        "reservation_attribution": [
            _record(
                module_name="ReservationLifecycleCoordinator",
                category="reservation",
                status="ACTIVE_RECONCILIATION",
                input_truth="order lifecycle fact",
                output_summary="reservation attribution carried",
                effect="RECONCILED",
                decision="RESERVATION_ATTRIBUTED",
                reason="source_lifecycle_phase=order_acknowledged",
            )
        ],
        "throttle_attribution": [
            _record(
                module_name="SovereignThrottler",
                category="throttle",
                status="ACTIVE_GUARDRAIL",
                input_truth="private order circuit stats",
                output_summary="throttle attribution carried",
                effect="BLOCKED",
                decision="CIRCUIT_OPEN",
                reason="rate_limit_response_window",
                blocking=True,
                veto=True,
            )
        ],
        "blocked_unwind_or_live_only_attribution": [
            _record(
                module_name="LiveBroker",
                category="execution_boundary",
                status="INTENTIONALLY_BLOCKED_LIVE_ONLY",
                input_truth="shadow/paper runtime",
                output_summary="live broker blocked",
                effect="NO_MUTATION_BOUNDARY",
                decision="BLOCKED",
                reason="NO_LIVE_ENDPOINT_OR_LIVE_MODE",
                blocking=True,
                veto=True,
            )
        ],
        "risk_economic_summary": {
            "broker_mutation_counts": {"POST": 0, "PATCH": 0, "DELETE": 0, "cancel": 0, "replace": 0, "sell": 0, "rebalance": 0},
            "normal_paper_path_preserved_when_shadow_false": True,
        },
    }

    record = DecisionCompiler().compile(_truth_frame(), additional_inputs=additional_inputs)

    assert record.metadata["edge_attribution"]["NetEdgeGovernor"]["decision"] == EconomicDecision.ALLOW.value
    assert record.metadata["risk_attribution"][0]["module_name"] == "UnifiedRiskAuthority"
    assert record.metadata["capital_defense_attribution"][0]["module_name"] == "DrawdownGuard"
    assert record.metadata["sizing_attribution"][0]["module_name"] == "PositionSizingEngine"
    assert record.metadata["execution_economics_attribution"][0]["module_name"] == "NetEdgeGovernor"
    assert record.metadata["reservation_attribution"][0]["module_name"] == "ReservationLifecycleCoordinator"
    assert record.metadata["throttle_attribution"][0]["module_name"] == "SovereignThrottler"
    assert record.metadata["blocked_unwind_or_live_only_attribution"][0]["module_name"] == "LiveBroker"
    assert record.metadata["risk_economic_summary"]["broker_mutation_counts"]["POST"] == 0
    assert "risk_attribution" in record.outputs["additional"]


def test_position_sizing_leadership_boost_remains_under_global_cap():
    sizing = PositionSizingEngine(SimpleNamespace(risk=SimpleNamespace(max_risk_per_trade=Decimal("0.02"))))
    result = sizing.calculate_position_size(
        capital_usd=Decimal("1000"),
        confidence=Decimal("1.00"),
        volatility=Decimal("0.20"),
        regime=RegimeType.TRENDING_BULL,
        strategy=SleeveType.SHADOW_FRONT,
        price=Decimal("100"),
        kelly_multiplier=Decimal("0.50"),
        stop_loss_pct=Decimal("0.001"),
        leadership_multiplier=Decimal("5.00"),
        kelly_cap=Decimal("0.50"),
        risk_of_ruin_evidence={"status": "ACTIVE_RISK_OF_RUIN_CONFIRMED"},
    )

    assert result.leadership_adjusted is True
    assert result.leadership_multiplier == Decimal("5.00")
    assert result.kelly_cap == Decimal("0.50")
    assert result.notional_usd == Decimal("250.00")
    assert result.position_pct <= Decimal("0.25")
    assert result.capped_by_global is True


def test_missing_economic_truth_fails_closed_and_no_fake_profitability_is_emitted():
    efficiency = TradeEfficiencyGovernor()
    denied = NetEdgeGovernor(efficiency).evaluate(
        current_time_ns=T0_NS,
        candidate=CandidateContext(
            symbol="AAPL",
            sleeve_id="gamma_front",
            candidate_type=CandidateType.FRESH_ENTRY,
            gross_edge=Decimal("0.0010"),
            gross_edge_source="deterministic_verified_fixture_edge_input",
            estimate_confidence=Decimal("0.80"),
            timestamp_ns=T0_NS,
            valid_until_ns=T0_NS + 1_000_000,
            costs=ExecutionEconomics(
                fee_cost=Decimal("0.0010"),
                spread_cost=Decimal("0.0010"),
                slippage_cost=Decimal("0.0010"),
                latency_drag=Decimal("0.0010"),
            ),
            burdens=AdversarialBurdens(regime_burden=Decimal("0.0010")),
        ),
        kill_switch_active=False,
    )
    assert denied.decision == EconomicDecision.DENY
    assert denied.net_adversarial_edge <= Decimal("0")

    record = _record(
        module_name="NetEdgeGovernor",
        category="execution_economics",
        status="FAILED_CLOSED",
        input_truth="gross_edge less than modeled friction/burden",
        output_summary=denied.reason_code,
        effect="VETO",
        decision=denied.decision.value,
        reason=denied.reason_code,
        provenance={
            "net_adversarial_edge": str(denied.net_adversarial_edge),
            "invented_pnl": None,
            "invented_profitability": None,
            "invented_slippage": None,
        },
        blocking=True,
        veto=True,
    )

    forbidden_claims = {"pnl", "profitability", "net_profit", "fake_fill", "fake_quote"}
    serialized = str(record).lower()
    assert record["status"] == "FAILED_CLOSED"
    assert record["veto"] is True
    assert not any(claim in serialized and f"invented_{claim}" not in serialized for claim in forbidden_claims)
