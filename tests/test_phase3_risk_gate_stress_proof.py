from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import app.execution.engine as engine_module
from app.brain.data_validator import DataContinuityValidator
from app.commander import Commander
from app.config import Config
from app.constants import AssetClass, SleeveType as AllocatorSleeveType
from app.core.market_snapshot import CANDIDATE_SNAPSHOT_STALE, build_market_truth_snapshot
from app.execution.broker_gateway import BrokerAdapterIdentity, BrokerGatewayResponse
from app.execution.engine import ExecutionEngine
from app.execution.order_router import OrderRouter
from app.main_loop import MainLoop, _build_pre_trade_guardrail_verdict
from app.meta.strategy_allocator import SovereignGovernor
from app.models.signals import StrategySignal
from app.operator_activation.paper_baseline import (
    BASELINE_POLICY_PROTECTED,
    evaluate_protected_baseline_trade,
)
from app.risk.drawdown_guard import DrawdownGuard, DrawdownReasonCode
from app.risk.exposure_manager import EXPOSURE_AUTHORITY_STATUS, ExposureManager
from app.risk.trade_efficiency_governor import KellyOverlayStatus, TradeEfficiencyGovernor
from app.state.state_store import StateStore
from app.strategies.moving_floor import TopologicalMovingFloor
from app.utils.enums import OrderSide as ExposureOrderSide
from app.utils.enums import RiskAction, SleeveType as ExposureSleeveType


T0_NS = 1_779_600_000_000_000_000
NS_PER_SECOND = 1_000_000_000

LIVE_RUNTIME = "LIVE_RUNTIME"
LOGIC_PROVEN_DORMANT = "LOGIC_PROVEN_DORMANT"


@dataclass(frozen=True)
class GateExpectation:
    gate: str
    label: str
    reason_code: str
    effect: str
    go_live_blocker: bool = False


GATE_EXPECTATIONS = {
    "G1": GateExpectation(
        "G1",
        LIVE_RUNTIME,
        "NON_POSITIVE_NET_EDGE",
        "ExecutionEngine admission blocks non-positive NetEdge before broker routing.",
    ),
    "G2": GateExpectation(
        "G2",
        LIVE_RUNTIME,
        "PAPER_BASELINE_SELL_EXCEEDS_RUN_ACQUIRED_QTY",
        "Protected baseline SELL is capped to run-acquired quantity.",
    ),
    "G3": GateExpectation(
        "G3",
        LOGIC_PROVEN_DORMANT,
        "GLOBAL_UTILIZATION_BREACH",
        "ExposureManager refuses total exposure above configured utilization cap.",
        go_live_blocker=True,
    ),
    "G4": GateExpectation(
        "G4",
        LOGIC_PROVEN_DORMANT,
        "corr_slash=50%",
        "SovereignGovernor applies a half-size correlation slash.",
        go_live_blocker=True,
    ),
    "G5": GateExpectation(
        "G5",
        LOGIC_PROVEN_DORMANT,
        "ASSET_CONCENTRATION_VETO",
        "ExposureManager refuses single-symbol concentration above asset cap.",
        go_live_blocker=True,
    ),
    "G6": GateExpectation(
        "G6",
        LIVE_RUNTIME,
        "SOFT_STOP_DRAWDOWN",
        "DrawdownGuard reduces aggression multiplier under soft-stop stress.",
    ),
    "G7": GateExpectation(
        "G7",
        LIVE_RUNTIME,
        "KELLY_FAIL_CLOSED_RISK_OF_RUIN_GE_1PCT",
        "TradeEfficiencyGovernor caps Kelly when estimated ruin is >= 1%.",
    ),
    "G8": GateExpectation(
        "G8",
        LIVE_RUNTIME,
        CANDIDATE_SNAPSHOT_STALE,
        "ExecutionEngine blocks stale MarketTruthSnapshot before broker routing.",
    ),
    "G9": GateExpectation(
        "G9",
        LIVE_RUNTIME,
        "ZOMBIE_TTL_CANCEL_ATTEMPTED",
        "ExecutionEngine TTL sweeper cancels aged pending orders through PCV.",
    ),
    "G10": GateExpectation(
        "G10",
        LIVE_RUNTIME,
        "MOVING_FLOOR_PROTECTIVE_EXIT_CANDIDATE",
        "MovingFloor emits only broker-position-backed sell_to_close exit intent.",
    ),
    "G11": GateExpectation(
        "G11",
        LIVE_RUNTIME,
        "SHUTDOWN_RECONCILIATION",
        "OrderRouter final reconciliation reads broker truth and reports no mutation.",
    ),
}


def _expect_gate(gate: str, expected_label: str) -> GateExpectation:
    expectation = GATE_EXPECTATIONS[gate]
    assert expectation.label == expected_label
    return expectation


def test_phase3_gate_labels_are_complete_and_truthful():
    assert set(GATE_EXPECTATIONS) == {f"G{idx}" for idx in range(1, 12)}
    assert {
        gate for gate, expectation in GATE_EXPECTATIONS.items() if expectation.go_live_blocker
    } == {"G3", "G4", "G5"}
    assert GATE_EXPECTATIONS["G3"].label == LOGIC_PROVEN_DORMANT
    assert GATE_EXPECTATIONS["G4"].label == LOGIC_PROVEN_DORMANT
    assert GATE_EXPECTATIONS["G5"].label == LOGIC_PROVEN_DORMANT


def _risk_guard() -> MagicMock:
    risk_guard = MagicMock()
    risk_guard.can_trade.return_value = True
    risk_guard.is_vol_fuse_triggered.return_value = False
    risk_guard.register_recalibrate_callback = MagicMock()
    risk_guard.register_emergency_callback = MagicMock()
    risk_guard.register_zombie_callback = MagicMock()
    risk_guard.register_lag_callback = MagicMock()
    risk_guard.register_vol_fuse_callback = MagicMock()
    risk_guard.record_fees = MagicMock()
    risk_guard.update_pending_orders = MagicMock()
    return risk_guard


def _masking_layer() -> MagicMock:
    masking_layer = MagicMock()
    masking_layer.mask_order.return_value = SimpleNamespace(masked_size=Decimal("0.10"))
    return masking_layer


def _engine(
    router: MagicMock | None = None,
    *,
    data_validator: DataContinuityValidator | None = None,
    max_pending_age_sec: float = 5.0,
) -> ExecutionEngine:
    engine = ExecutionEngine(
        commander=Commander(),
        risk_guard=_risk_guard(),
        order_router=router or MagicMock(),
        masking_layer=_masking_layer(),
        data_validator=data_validator,
        signal_ttl_ms=300_000.0,
        max_pending_age_sec=max_pending_age_sec,
    )
    engine._state.is_running = True
    engine._state.last_regime = "neutral"
    return engine


def _guardrail(symbol: str) -> dict:
    return {
        "verdict": "ALLOW",
        "route_permitted": True,
        "mutation_permitted": True,
        "reason_codes": ("PRE_TRADE_GUARDRAILS_ALLOW",),
        "symbol": symbol,
        "side": "buy",
        "order_type": "limit",
        "time_in_force": "GTC",
    }


def _snapshot_payload(
    *,
    symbol: str = "SOL/USD",
    current_ns: int,
    source_type: str = "runtime",
    candle_age_sec: int = 10,
    candle_policy_ms: float = 60_000.0,
    book_age_sec: int | None = 1,
    receive_age_sec: int | None = 0,
    executable: bool = True,
) -> tuple[dict, dict, dict]:
    candle_close_ts_ns = current_ns - candle_age_sec * NS_PER_SECOND
    candle_id = candle_close_ts_ns - 60 * NS_PER_SECOND
    latest_book_ts_ns = (
        current_ns - book_age_sec * NS_PER_SECOND
        if book_age_sec is not None
        else None
    )
    receive_ts_ns = (
        current_ns - receive_age_sec * NS_PER_SECOND
        if receive_age_sec is not None
        else None
    )
    executable_source = source_type == "runtime" and executable
    market_truth = {
        "symbol": symbol,
        "consumer_exchange_ts_ns": candle_id,
        "latest_book_ts_ns": latest_book_ts_ns,
        "latest_candle_ts_ns": candle_id,
        "data_source_type": source_type,
    }
    candle_truth = {
        "consumer_timestamp_ns": candle_id,
        "candle_id": candle_id,
        "candle_start_ts_ns": candle_id,
        "candle_close_ts_ns": candle_close_ts_ns,
        "candle_freshness_policy_ms": candle_policy_ms,
        "data_source_type": source_type,
        "provider_id": "coinbase_public",
        "receive_ts_ns": receive_ts_ns,
        "data_health_reason_code": "DATA_HEALTHY"
        if executable_source
        else "DATA_BACKFILL_OBSERVE_ONLY",
        "candle_freshness_reason_code": "CANDLE_RUNTIME_FRESH"
        if executable_source
        else "CANDLE_BATCH_BACKFILL_OBSERVE_ONLY",
        "executable_market_truth": executable_source,
    }
    snapshot = build_market_truth_snapshot(
        symbol=symbol,
        market_truth=market_truth,
        candle_truth=candle_truth,
        current_ns=current_ns,
    )
    market_truth["market_truth_snapshot"] = snapshot
    return market_truth, candle_truth, snapshot


def _canonical_metadata(symbol: str, market_truth: dict, snapshot: dict) -> dict:
    return {
        "execution_market_truth": market_truth,
        "market_truth_snapshot": snapshot,
        "candidate_market_snapshot": snapshot,
        "requires_canonical_market_snapshot": True,
        "snapshot_id": snapshot["snapshot_id"],
        "candle_id": snapshot["candle_id"],
        "pre_trade_guardrail_verdict": _guardrail(symbol),
    }


def _strategy_signal(
    *,
    symbol: str = "SOL/USD",
    candle_id: int,
    expected_move_bps: str,
    confidence: float = 0.90,
    metadata: dict,
) -> StrategySignal:
    return StrategySignal(
        strategy="sector_rotation",
        symbol=symbol,
        side="buy",
        confidence=confidence,
        quantity=0.10,
        price=150.0,
        exchange_ts_ns=candle_id,
        reason="phase3_risk_gate_stress_proof",
        metadata={
            "expected_move_bps": expected_move_bps,
            **metadata,
        },
    )


def test_g1_live_runtime_net_edge_blocks_non_positive_candidate(monkeypatch):
    gate = _expect_gate("G1", LIVE_RUNTIME)
    router = MagicMock()
    current_ns = T0_NS + 10 * NS_PER_SECOND
    monkeypatch.setattr(engine_module, "now_ns", lambda: current_ns)
    market_truth, _, snapshot = _snapshot_payload(current_ns=current_ns)
    signal = _strategy_signal(
        candle_id=snapshot["candle_id"],
        expected_move_bps="10",
        confidence=0.50,
        metadata=_canonical_metadata("SOL/USD", market_truth, snapshot),
    )
    engine = _engine(router)

    admitted = engine.submit_signal(signal, Decimal("150.00"), is_attack=False)
    block = engine.get_last_admission_block_result()

    assert admitted is False
    assert block.reason_code == "ECONOMIC_ADMISSIBILITY_BLOCKED"
    assert block.block_evidence["reason_code"] == gate.reason_code
    assert block.block_evidence["decision"] == "DENY"
    assert block.block_evidence["admissible"] is False
    assert block.block_evidence["broker_post"] is False
    router.submit_order.assert_not_called()


def test_g2_live_runtime_baseline_sell_capped_to_run_acquired_quantity():
    gate = _expect_gate("G2", LIVE_RUNTIME)
    result = evaluate_protected_baseline_trade(
        symbol="BTC/USD",
        side="sell",
        requested_qty="0.02",
        accepted_baseline={
            "baseline_loaded": True,
            "policy": BASELINE_POLICY_PROTECTED,
            "protected_symbols_normalized": ("BTCUSD",),
        },
        run_acquired_qty="0.01",
        lot_tracking_available=True,
    )

    assert result["allowed"] is False
    assert result["reason_code"] == gate.reason_code
    assert result["broker_mutation_occurred"] is False


def test_g3_dormant_heat_cap_refuses_global_utilization_breach():
    gate = _expect_gate("G3", LOGIC_PROVEN_DORMANT)
    assert EXPOSURE_AUTHORITY_STATUS == "DORMANT_SEAM"
    manager = ExposureManager(initial_equity=Decimal("1000"), max_utilization=Decimal("0.80"))

    result = manager.validate_intent_detailed(
        sleeve=ExposureSleeveType.SECTOR_ROTATION,
        symbol="BTC/USD",
        side=ExposureOrderSide.BUY,
        qty=Decimal("1"),
        price=Decimal("2100"),
    )

    assert result.authorized is False
    assert result.reason == gate.reason_code
    assert result.risk_action == RiskAction.BLOCK_ALL_NEW


def test_g4_dormant_correlation_slashing_halves_correlated_position_size():
    gate = _expect_gate("G4", LOGIC_PROVEN_DORMANT)
    governor = SovereignGovernor(
        total_capital=20_000.0,
        correlation_kill_threshold=0.85,
        correlation_slash_factor=0.5,
    )
    governor.update_asset_exposure("BTC/USD", AssetClass.CRYPTO, 1_000.0)
    governor.update_correlation("ETH/USD", "BTC/USD", 0.90)

    slash_factor = governor.get_correlation_slash_factor("ETH/USD", ["BTC/USD"])
    adjusted, reason = governor.calculate_adjusted_allocation(
        AllocatorSleeveType.SECTOR_ROTATION,
        requested_capital=1_000.0,
        symbol="ETH/USD",
        asset_class=AssetClass.CRYPTO,
    )

    assert slash_factor == 0.5
    assert gate.reason_code in reason
    assert adjusted <= 300.0


def test_g5_dormant_per_symbol_cap_refuses_asset_concentration_breach():
    gate = _expect_gate("G5", LOGIC_PROVEN_DORMANT)
    assert EXPOSURE_AUTHORITY_STATUS == "DORMANT_SEAM"
    manager = ExposureManager(
        initial_equity=Decimal("1000"),
        max_utilization=Decimal("0.95"),
        sleeve_limits={ExposureSleeveType.SECTOR_ROTATION: Decimal("0.95")},
    )

    result = manager.validate_intent_detailed(
        sleeve=ExposureSleeveType.SECTOR_ROTATION,
        symbol="ETH/USD",
        side=ExposureOrderSide.BUY,
        qty=Decimal("1"),
        price=Decimal("700"),
    )

    assert result.authorized is False
    assert result.reason == gate.reason_code
    assert result.risk_action == RiskAction.BLOCK_ALL_NEW


def test_g6_live_runtime_drawdown_soft_stop_delevers_aggression():
    gate = _expect_gate("G6", LIVE_RUNTIME)
    guard = DrawdownGuard(initial_capital=Decimal("1000"))

    advisory = guard.update_canonical(
        current_equity=Decimal("920"),
        ts_ns=T0_NS,
    )

    assert advisory.primary_reason_code == DrawdownReasonCode(gate.reason_code)
    assert advisory.risk_action == RiskAction.SAFE_MODE
    assert advisory.aggression_multiplier < Decimal("1.0")


def test_g7_live_runtime_risk_of_ruin_ge_one_percent_fails_closed():
    gate = _expect_gate("G7", LIVE_RUNTIME)
    governor = TradeEfficiencyGovernor()
    for offset in range(50):
        governor.register_trade_result(
            sleeve_id="gamma_front",
            timestamp_ns=T0_NS + offset,
            gross_pnl=Decimal("10"),
            net_pnl=Decimal("-2"),
            fee_cost=Decimal("1"),
            spread_tax=Decimal("0.5"),
            slippage_drag=Decimal("0.5"),
            carry_drag=Decimal("0"),
            capital_committed=Decimal("100"),
            regime="ranging",
        )

    overlay = governor.get_kelly_overlay("gamma_front", "ranging")

    assert overlay.status == KellyOverlayStatus.ACTIVE_RISK_OF_RUIN_BLOCKED
    assert overlay.reason_code == gate.reason_code
    assert overlay.risk_of_ruin_estimate >= Decimal("0.01")
    assert overlay.effective_kelly_cap == Decimal("0.25")


def test_g8_live_runtime_stale_market_truth_halts_before_broker_route():
    gate = _expect_gate("G8", LIVE_RUNTIME)
    router = MagicMock()
    current_ns = T0_NS + 20 * NS_PER_SECOND
    validator = DataContinuityValidator(max_stale_age_sec=5.0)
    validator.record_data(
        "SOL/USD",
        datetime.fromtimestamp(current_ns / NS_PER_SECOND, tz=timezone.utc),
    )
    market_truth, _, snapshot = _snapshot_payload(
        current_ns=current_ns,
        candle_age_sec=90,
        book_age_sec=None,
    )
    signal = _strategy_signal(
        candle_id=snapshot["candle_id"],
        expected_move_bps="200",
        confidence=0.90,
        metadata=_canonical_metadata("SOL/USD", market_truth, snapshot),
    )
    engine = _engine(router, data_validator=validator)

    admitted = engine.submit_signal(signal, Decimal("150.00"), is_attack=False)
    block = engine.get_last_admission_block_result()

    assert admitted is False
    assert block.reason_code == "DATA_UNHEALTHY"
    assert block.block_evidence["data_health_reason_code"] == gate.reason_code
    assert gate.reason_code in block.block_evidence["snapshot_reason_codes"]
    router.submit_order.assert_not_called()


def test_g9_live_runtime_zombie_ttl_sweeper_cancels_aged_pending_order(monkeypatch):
    _expect_gate("G9", LIVE_RUNTIME)
    current_ns = T0_NS + 30 * NS_PER_SECOND
    stale_submit_ns = current_ns - 5 * NS_PER_SECOND
    router = MagicMock()
    router.is_order_terminal.return_value = False
    router.cancel_order.return_value = True
    router.get_order_status.return_value = "canceled"
    engine = _engine(router, max_pending_age_sec=1.0)
    engine._state.pending_orders["zombie-order"] = SimpleNamespace(
        exchange_ts_ns=stale_submit_ns,
        receive_ts_ns=stale_submit_ns,
        quantity=Decimal("1"),
        limit_price=Decimal("1"),
    )
    monkeypatch.setattr(engine_module, "now_ns", lambda: current_ns)

    engine._sweep_zombie_orders()

    router.cancel_order.assert_called_once_with("zombie-order")
    assert "zombie-order" not in engine._state.pending_orders
    assert "zombie-order" in engine._cancel_attempted_order_ids


class _Book:
    spread = 1.0

    def __init__(self, bid_depth: str = "40", ask_depth: str = "160") -> None:
        self._bid_depth = Decimal(bid_depth)
        self._ask_depth = Decimal(ask_depth)

    def depth_at_levels(self, levels: int):
        return self._bid_depth, self._ask_depth


def _moving_floor_snapshot() -> dict:
    return {
        "snapshot_id": "mts_phase3_moving_floor",
        "symbol": "ETH/USD",
        "candle_id": T0_NS,
        "snapshot_status": "PASS",
        "executable_market_truth": True,
        "source_type": "runtime",
    }


def _moving_floor_candle(price: str, ts_ns: int, *, high: str, low: str) -> SimpleNamespace:
    close = Decimal(price)
    return SimpleNamespace(
        symbol="ETH/USD",
        open=float(close),
        high=float(Decimal(high)),
        low=float(Decimal(low)),
        close=float(close),
        volume=100.0,
        exchange_ts_ns=ts_ns,
    )


def _moving_floor_loop(position: dict) -> SimpleNamespace:
    loop = SimpleNamespace()
    loop._last_risk_state = {}
    loop._current_regime = "neutral"
    loop.decision_compiler = SimpleNamespace(reserve_decision_uuid=lambda: "phase3-moving-floor")
    loop._get_dispatch_regime = MainLoop._get_dispatch_regime.__get__(loop, MainLoop)
    loop._broker_position_truth = MagicMock(
        return_value=(
            position,
            {
                "status": "PASS",
                "reason_code": "BROKER_POSITION_TRUTH_READ_ONLY",
                "source": "controlled_phase3_test_fixture",
                "read_only": True,
            },
        )
    )
    loop._moving_floor_toxicity_level = MainLoop._moving_floor_toxicity_level
    loop._moving_floor_book_integrity = MainLoop._moving_floor_book_integrity
    loop._moving_floor_risk_action = MainLoop._moving_floor_risk_action.__get__(loop, MainLoop)
    loop._build_moving_floor_signal = MainLoop._build_moving_floor_signal.__get__(loop, MainLoop)
    loop._observe_moving_floor = MainLoop._observe_moving_floor.__get__(loop, MainLoop)
    return loop


def _moving_floor_runtime() -> SimpleNamespace:
    runtime = SimpleNamespace(
        last_order_book=_Book(),
        moving_floor_strategy=TopologicalMovingFloor(),
        last_moving_floor_observed_signal=None,
        last_moving_floor_observed_vote=None,
        last_moving_floor_evidence=None,
        regime_detector=None,
        toxicity_engine=None,
    )
    runtime.record_observed_signal = (
        lambda sleeve, signal: setattr(runtime, "last_moving_floor_observed_signal", signal)
    )
    runtime.record_observed_vote = (
        lambda sleeve, vote: setattr(runtime, "last_moving_floor_observed_vote", vote)
    )

    def reset(reason: str = "MOVING_FLOOR_RESET") -> None:
        runtime.moving_floor_strategy = TopologicalMovingFloor()
        runtime.last_moving_floor_observed_signal = None
        runtime.last_moving_floor_observed_vote = None
        runtime.last_moving_floor_evidence = {
            "module": "MovingFloor",
            "status": "NOT_APPLICABLE",
            "reason_code": reason,
        }

    runtime.reset_moving_floor = reset
    return runtime


def test_g10_live_runtime_moving_floor_exit_is_broker_position_backed_sell_to_close():
    gate = _expect_gate("G10", LIVE_RUNTIME)
    position = {
        "symbol": "ETHUSD",
        "quantity": "0.25",
        "average_entry_price": "80",
        "broker_position_backed": True,
    }
    loop = _moving_floor_loop(position)
    runtime = _moving_floor_runtime()
    snapshot = _moving_floor_snapshot()

    loop._observe_moving_floor(
        "ETH/USD",
        runtime,
        _moving_floor_candle("100", T0_NS, high="100.20", low="100.00"),
        snapshot,
    )
    loop._observe_moving_floor(
        "ETH/USD",
        runtime,
        _moving_floor_candle("110", T0_NS + 60 * NS_PER_SECOND, high="112.00", low="111.80"),
        snapshot,
    )
    loop._observe_moving_floor(
        "ETH/USD",
        runtime,
        _moving_floor_candle("107", T0_NS + 120 * NS_PER_SECOND, high="107.00", low="106.80"),
        snapshot,
    )

    signal = runtime.last_moving_floor_observed_signal
    verdict = _build_pre_trade_guardrail_verdict(
        config=Config(
            broker_mode="paper",
            active_markets=["crypto"],
            symbol_universe=["ETH/USD"],
            portal_selection_policy="explicit_preferred_venue",
            preferred_trading_portal="alpaca_paper",
        ),
        symbol="ETH/USD",
        signal=signal,
        runtime=SimpleNamespace(last_price=107.0),
        is_attack=False,
    )

    assert runtime.last_moving_floor_evidence["reason_code"] == gate.reason_code
    assert signal.side == "sell"
    assert signal.metadata["protective_only"] is True
    assert signal.metadata["requires_existing_position"] is True
    assert signal.metadata["broker_position_backed"] is True
    assert signal.metadata["fresh_entry_authorized"] is False
    assert signal.metadata["action"] == "sell_to_close"
    assert signal.metadata["execution_action"] == "sell_to_close"
    assert signal.metadata["order_action"] == "sell_to_close"
    assert signal.metadata["position_lifecycle_transition"]["target_state"] == "FLAT"
    assert signal.metadata["position_lifecycle_transition"]["cooldown_state"] == "PENDING_FILL"
    assert verdict["action"] == "sell_to_close"
    assert "SELL_AUTHORITY_MISSING" not in verdict["reason_codes"]


class _ReadOnlyPaperGateway:
    def __init__(self) -> None:
        self.identity = BrokerAdapterIdentity(
            adapter_id="phase3_read_only_paper_gateway",
            venue_id="alpaca",
            portal_id="alpaca_paper",
            environment="paper",
            base_url="https://paper-api.alpaca.markets",
            credential_status="configured",
            supported_methods=frozenset({"GET"}),
            supported_asset_classes=frozenset({"crypto"}),
            live_blocked=True,
        )
        self.request_counts = {"GET": 0}

    def _response(self, endpoint_path: str, payload) -> BrokerGatewayResponse:
        self.request_counts["GET"] += 1
        return BrokerGatewayResponse(
            adapter_id=self.identity.adapter_id,
            venue_id=self.identity.venue_id,
            portal_id=self.identity.portal_id,
            environment=self.identity.environment,
            request_method="GET",
            endpoint_path=endpoint_path,
            ok=True,
            mutation_occurred=False,
            live_blocked=True,
            normalized_status="accepted",
            payload=payload,
        )

    def get_open_orders(self) -> BrokerGatewayResponse:
        return self._response("/v2/orders", [])

    def get_positions(self) -> BrokerGatewayResponse:
        return self._response("/v2/positions", [])

    def get_account(self) -> BrokerGatewayResponse:
        return self._response("/v2/account", {"status": "ACTIVE"})


def test_g11_live_runtime_shutdown_reconciliation_reads_broker_truth_without_mutation(tmp_path):
    _expect_gate("G11", LIVE_RUNTIME)
    gateway = _ReadOnlyPaperGateway()
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=gateway,
        state_store=StateStore(str(tmp_path / "state.db")),
    )

    reconciliation = router.finalize_oms_shutdown_reconciliation()

    assert reconciliation["performed"] is True
    assert reconciliation["mutation_performed"] is False
    assert reconciliation["broker_truth_wins_after_ack"] is True
    assert reconciliation["local_state_authority"] == "supporting_evidence_only"
    assert reconciliation["account_status"] == "ACTIVE"
    assert reconciliation["broker_confirmed_open_orders"] == 0
    assert reconciliation["positions_count"] == 0
    assert reconciliation["reconciliation_conflict_count"] == 0
    assert reconciliation["reason_codes"] == ()
    assert gateway.request_counts["GET"] == 3
