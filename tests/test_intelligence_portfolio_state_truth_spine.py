from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.core.intelligence_portfolio_state_truth_spine import (
    INTELLIGENCE_MISSING_FEED_TRUTH,
    INTEGRATED_STATE_BLOCKED,
    INTEGRATED_STATE_CORRUPTED,
    INTEGRATED_STATE_DEGRADED_MISSING_TRUTH,
    BrokerTruthSnapshot,
    IntelligencePortfolioStateTruthSpine,
    Seam5CycleRequest,
    STRATEGY_MISSING_FEED_TRUTH,
)
from app.execution.engine import ExecutionSpineResult
from app.market.capability_registry import (
    VenueCapabilityRegistry,
    build_alpaca_crypto_capability_registry,
    build_alpaca_crypto_universe,
    build_default_capability_registry,
    normalize_alpaca_crypto_catalog,
)
from app.models.signals import StrategySignal
from app.risk.exposure_manager import ExposureManager
from app.risk.reservation_lifecycle_coordinator import ReservationLifecycleCoordinator
from app.state.state_store import StateStore


T0_NS = 1_777_948_800_000_000_000


def _store(tmp_path) -> StateStore:
    return StateStore(str(tmp_path / "seam5.db"))


def _spine() -> IntelligencePortfolioStateTruthSpine:
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
                "min_trade_increment": "0.000000001",
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
    registry = VenueCapabilityRegistry((*preserved, *dynamic.capabilities))
    return IntelligencePortfolioStateTruthSpine(capability_registry=registry)


def _signal(symbol: str = "AAPL", qty: Decimal = Decimal("0.02")) -> StrategySignal:
    return StrategySignal(
        strategy="shadow_front",
        symbol=symbol,
        side="buy",
        confidence=0.70,
        quantity=float(qty),
        price=150.0,
        exchange_ts_ns=T0_NS,
        reason="seam5_fixture_strategy_signal",
        metadata={"expected_move": "0.02"},
    )


def _coordinator(store: StateStore) -> tuple[ExposureManager, ReservationLifecycleCoordinator]:
    exposure = ExposureManager(initial_equity=Decimal("20000"))
    return exposure, ReservationLifecycleCoordinator(exposure_manager=exposure, state_store=store)


def _execution(status: str, *, client_order_id: str = "seam5-client", broker_order_id: str | None = "broker-1") -> ExecutionSpineResult:
    return ExecutionSpineResult(
        decision_uuid="seam5-decision",
        client_order_id=client_order_id,
        broker_order_id=broker_order_id,
        normalized_status=status,
        route="fixture_execution_result",
        reason_code=None if status in {"accepted", "open", "filled"} else "fixture_rejected",
    )


def test_missing_strategy_and_intelligence_feeds_flow_into_fusion_candidate_and_result(tmp_path):
    store = _store(tmp_path)
    result = _spine().run_cycle(
        Seam5CycleRequest(
            symbol="AAPL",
            timestamp_ns=T0_NS,
            current_price=Decimal("150"),
            asset_class="equity",
            state_store=store,
        )
    )

    strategy_reasons = {
        reason
        for evidence in result.candidate.fusion.strategy_evidence
        for reason in evidence.reason_codes
    }
    intelligence_reasons = {
        reason
        for evidence in result.candidate.fusion.intelligence_evidence
        for reason in evidence.reason_codes
    }
    assert STRATEGY_MISSING_FEED_TRUTH in strategy_reasons
    assert INTELLIGENCE_MISSING_FEED_TRUTH in intelligence_reasons
    assert result.candidate.status == "CANDIDATE_BLOCKED"
    assert result.final_machine_status == INTEGRATED_STATE_BLOCKED
    assert store.list_events(event_type="seam5.decision_created")


def test_candidate_selection_comes_from_strategy_signal_not_bare_capability(tmp_path):
    store = _store(tmp_path)
    result = _spine().run_cycle(
        Seam5CycleRequest(
            symbol="AAPL",
            timestamp_ns=T0_NS,
            current_price=Decimal("150"),
            asset_class="equity",
            strategy_modules={"shadow_front": object()},
            strategy_signals=[_signal("AAPL", Decimal("0.02"))],
            state_store=store,
            max_notional=Decimal("5.00"),
        )
    )

    assert result.candidate.symbol == "AAPL"
    assert result.candidate.source_modules == ("shadow_front",)
    assert result.candidate.fusion.selected_symbol == "AAPL"
    assert result.candidate.capability_identity["execution_adapter"] == "alpaca_paper_rest"
    assert result.guardrail_verdict["route_permitted"] is True
    assert "FUSION_SELECTED_FROM_STRATEGY_EVIDENCE" in result.candidate.fusion.reason_codes


def test_seam4_guardrail_blocks_unsafe_crypto_candidate_before_route(tmp_path):
    store = _store(tmp_path)
    result = _spine().run_cycle(
        Seam5CycleRequest(
            symbol="BTC/USD",
            timestamp_ns=T0_NS,
            current_price=Decimal("77064.20"),
            asset_class="crypto",
            strategy_modules={"shadow_front": object()},
            strategy_signals=[_signal("BTC/USD", Decimal("0.00006488"))],
            state_store=store,
            max_notional=Decimal("5.00"),
        )
    )

    assert result.candidate.status == "CANDIDATE_GUARDRAIL_BLOCKED"
    assert "MIN_QUANTITY_NOT_MET" in result.guardrail_verdict["reason_codes"]
    assert result.execution_status == "blocked"
    assert store.list_events(event_type="seam5.candidate_blocked")


def test_rejected_order_fixture_records_no_locked_reservation(tmp_path):
    store = _store(tmp_path)
    exposure, coordinator = _coordinator(store)
    result = _spine().run_cycle(
        Seam5CycleRequest(
            symbol="AAPL",
            timestamp_ns=T0_NS,
            current_price=Decimal("150"),
            asset_class="equity",
            strategy_modules={"shadow_front": object()},
            strategy_signals=[_signal("AAPL", Decimal("0.02"))],
            state_store=store,
            exposure_manager=exposure,
            reservation_lifecycle_coordinator=coordinator,
            execution_result_fixture=_execution("rejected"),
            max_notional=Decimal("5.00"),
        )
    )

    assert result.execution_status == "rejected"
    assert result.reservation_lifecycle.status == "REJECTED_NO_LOCK"
    assert store.list_reservation_ledger(active_only=True, include_terminal=False) == []


def test_open_order_fixture_opens_reservation_and_records_state(tmp_path):
    store = _store(tmp_path)
    exposure, coordinator = _coordinator(store)
    result = _spine().run_cycle(
        Seam5CycleRequest(
            symbol="AAPL",
            timestamp_ns=T0_NS,
            current_price=Decimal("150"),
            asset_class="equity",
            strategy_modules={"shadow_front": object()},
            strategy_signals=[_signal("AAPL", Decimal("0.02"))],
            state_store=store,
            exposure_manager=exposure,
            reservation_lifecycle_coordinator=coordinator,
            execution_result_fixture=_execution("open"),
            broker_truth=BrokerTruthSnapshot(
                open_orders=({"id": "broker-1", "client_order_id": "seam5-client", "symbol": "AAPL"},),
                receive_ts_ns=T0_NS,
            ),
            max_notional=Decimal("5.00"),
        )
    )

    active = store.list_reservation_ledger(active_only=True, include_terminal=False)
    assert result.reservation_lifecycle.status == "OPENED"
    assert result.reservation_lifecycle.opened is True
    assert len(active) == 1
    assert active[0]["client_order_id"] == "seam5-client"
    assert store.list_events(event_type="seam5.reservation_lifecycle")


def test_filled_order_fixture_releases_reservation_and_binds_position(tmp_path):
    store = _store(tmp_path)
    exposure, coordinator = _coordinator(store)
    result = _spine().run_cycle(
        Seam5CycleRequest(
            symbol="AAPL",
            timestamp_ns=T0_NS,
            current_price=Decimal("150"),
            asset_class="equity",
            strategy_modules={"shadow_front": object()},
            strategy_signals=[_signal("AAPL", Decimal("0.02"))],
            state_store=store,
            exposure_manager=exposure,
            reservation_lifecycle_coordinator=coordinator,
            execution_result_fixture=_execution("filled"),
            broker_truth=BrokerTruthSnapshot(
                positions=({"symbol": "AAPL", "qty": "0.02", "avg_entry_price": "150"},),
                receive_ts_ns=T0_NS,
            ),
            max_notional=Decimal("5.00"),
        )
    )

    assert result.reservation_lifecycle.status == "BOUND_POSITION"
    assert result.reservation_lifecycle.released is True
    assert result.reservation_lifecycle.bound_position is True
    assert store.list_reservation_ledger(active_only=True, include_terminal=False) == []
    assert store.get_positions()[0]["symbol"] == "AAPL"


def test_truth_reconciler_exposure_truth_kernel_and_invariants_run(tmp_path):
    store = _store(tmp_path)
    result = _spine().run_cycle(
        Seam5CycleRequest(
            symbol="AAPL",
            timestamp_ns=T0_NS,
            current_price=Decimal("150"),
            asset_class="equity",
            strategy_modules={"shadow_front": object()},
            strategy_signals=[_signal("AAPL", Decimal("0.02"))],
            state_store=store,
            broker_truth=BrokerTruthSnapshot(
                positions=({"symbol": "AAPL", "qty": "0.02", "avg_entry_price": "150"},),
                receive_ts_ns=T0_NS,
                fixture_truth=False,
            ),
            max_notional=Decimal("5.00"),
        )
    )

    assert result.reconciliation.status == "RECONCILED"
    assert result.exposure.status == "EXPOSURE_UPDATED"
    assert result.truth_kernel.status == "PASS"
    assert result.invariant_checker.status == "PASS"
    assert result.final_machine_status in {INTEGRATED_STATE_DEGRADED_MISSING_TRUTH, "INTEGRATED_STATE_READY"}


def test_reconciliation_and_invariant_checker_flag_real_mismatch_and_corruption(tmp_path):
    store = _store(tmp_path)
    store.insert_position(
        {
            "id": "local-aapl",
            "symbol": "AAPL",
            "side": "long",
            "quantity": 1.0,
            "entry_price": 150.0,
            "current_price": 150.0,
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.0,
            "strategy": "shadow_front",
            "opened_at": str(T0_NS),
            "updated_at": str(T0_NS),
            "last_strategy_heartbeat": str(T0_NS),
            "exchange": "local",
            "entry_latency_ms": None,
        }
    )
    result = _spine().run_cycle(
        Seam5CycleRequest(
            symbol="AAPL",
            timestamp_ns=T0_NS,
            current_price=Decimal("150"),
            asset_class="equity",
            strategy_modules={"shadow_front": object()},
            strategy_signals=[_signal("AAPL", Decimal("0.02"))],
            state_store=store,
            broker_truth=BrokerTruthSnapshot(
                positions=(),
                open_orders=(
                    {"id": "dup", "client_order_id": "same", "symbol": "AAPL"},
                    {"id": "dup", "client_order_id": "same", "symbol": "AAPL"},
                ),
                receive_ts_ns=0,
                fixture_truth=False,
            ),
            max_notional=Decimal("5.00"),
        )
    )

    assert "LOCAL_BROKER_POSITION_MISMATCH" in result.reconciliation.reason_codes
    assert "DUPLICATE_ORDER_ID" in result.invariant_checker.violation_codes
    assert "STALE_TRUTH_MARKED_CURRENT" in result.invariant_checker.violation_codes
    assert result.final_machine_status == INTEGRATED_STATE_CORRUPTED


def test_no_fake_broker_or_market_truth_is_marked_real_for_fixtures(tmp_path):
    store = _store(tmp_path)
    result = _spine().run_cycle(
        Seam5CycleRequest(
            symbol="AAPL",
            timestamp_ns=T0_NS,
            current_price=Decimal("150"),
            asset_class="equity",
            strategy_modules={"shadow_front": object()},
            strategy_signals=[_signal("AAPL", Decimal("0.02"))],
            state_store=store,
            execution_result_fixture=_execution("open"),
            broker_truth=BrokerTruthSnapshot(
                open_orders=({"id": "broker-1", "client_order_id": "seam5-client", "symbol": "AAPL"},),
                receive_ts_ns=T0_NS,
                fixture_truth=True,
            ),
            max_notional=Decimal("5.00"),
        )
    )

    assert result.execution_result.route == "fixture_execution_result"
    assert result.reconciliation.reason_codes == ("RECONCILIATION_MATCH_OR_FIXTURE_SCOPED",)
