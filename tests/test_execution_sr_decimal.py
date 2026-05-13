"""
EXECUTION_SR_DECIMAL Phase 2 Tests

Covers:
- B1: submit_signal float current_price -> Decimal enqueue_price (no crash, correct type)
- B2: _execute_signal float masked_size -> Decimal OrderRequest.quantity (no crash)
- B3: market orders pass limit_price=None; limit orders use current_price-based Decimal limit_price
- SIGNAL_SUBMITTED log emitted on successful signal queue
- PAPERBROKER_REACH_COUNT log emitted on successful submit_order
- PAPER_FILL_COUNT log emitted when paper fill is returned
"""

import logging
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from app.execution.engine import ExecutionEngine, QueuedSignal
from app.models.contracts import FillEvent
from app.models.enums import OrderSide
from app.telemetry.event_store import TelemetryEventStore
from app.telemetry.fill_recorder import FillRecorder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine():
    """Build a minimal ExecutionEngine with all dependencies mocked."""
    commander = MagicMock()
    risk_guard = MagicMock()
    risk_guard.can_trade.return_value = True
    risk_guard.is_vol_fuse_triggered.return_value = False
    risk_guard.register_recalibrate_callback = MagicMock()
    risk_guard.register_emergency_callback = MagicMock()
    risk_guard.register_zombie_callback = MagicMock()
    risk_guard.register_lag_callback = MagicMock()
    risk_guard.register_vol_fuse_callback = MagicMock()

    order_router = MagicMock()
    order_router.get_mid_price.return_value = Decimal("3000.00")
    order_router.submit_order.return_value = None

    masking_layer = MagicMock()
    masked = MagicMock()
    masked.masked_size = float(0.05)  # intentional float — the B2 blocker
    masking_layer.mask_order.return_value = masked

    engine = ExecutionEngine(
        commander=commander,
        risk_guard=risk_guard,
        order_router=order_router,
        masking_layer=masking_layer,
    )
    engine._state.is_running = True
    engine._state.last_regime = "neutral"
    return engine


def _make_signal(side="buy", price=None, strategy="sector_rotation"):
    """Build a minimal StrategySignal mock."""
    from app.models.signals import StrategySignal
    from app.utils.time_utils import now_ns
    return StrategySignal(
        strategy=strategy,
        symbol="ETH/USD",
        side=side,
        confidence=0.75,
        quantity=0.05,
        price=price,
        exchange_ts_ns=now_ns(),
        reason="test",
    )


def _canonical_aggression_replay_metadata():
    """Commander-owned aggression replay context with hostile advisory hints."""
    return {
        "canonical_aggression_contract": {
            "authority_owner": "Commander",
            "authority_version": "commander.aggression.v1",
            "mode": "SAFE",
            "execution_is_attack": False,
            "risk_guard_final_veto_preserved": True,
            "economic_admissibility_final_veto_preserved": True,
            "stale_gate_final_veto_preserved": True,
            "moving_floor_active": False,
            "dormant_governors_active": False,
        },
        "aggression_replay_proof": {
            "authority_owner": "Commander",
            "execution_is_attack": False,
            "execution_is_attack_source": (
                "Commander.canonical_aggression_contract.execution_is_attack"
            ),
            "fusion_attack_mode": True,
            "fusion_attack_mode_authoritative": False,
            "advisory_aggression_metadata_present": True,
            "advisory_aggression_metadata_authoritative": False,
            "risk_guard_final_veto_preserved": True,
            "economic_admissibility_final_veto_preserved": True,
            "stale_gate_final_veto_preserved": True,
        },
        "aggression_context": {
            "attack_mode_hint": True,
            "execution_is_attack": True,
            "authority_owner": "Fusion",
            "metadata_only": True,
        },
        "aggression_snapshot_id": "bundle12b-hostile-advisory-fusion",
    }


def _order_replay_metadata_from_signal_metadata(signal_metadata):
    return {
        "original_size": Decimal("0.250"),
        "masked_size": Decimal("0.250"),
        "is_attack": False,
        "canonical_aggression_contract": dict(signal_metadata["canonical_aggression_contract"]),
        "aggression_replay_proof": dict(signal_metadata["aggression_replay_proof"]),
        "execution_is_attack_source": (
            "Commander.canonical_aggression_contract.execution_is_attack"
        ),
        "execution_is_attack_matches_contract": True,
        "advisory_aggression_metadata_present": True,
        "advisory_aggression_snapshot_id": signal_metadata["aggression_snapshot_id"],
    }


def _passive_portfolio_replay_context():
    """Passive portfolio replay context; never an exposure veto authority."""
    return {
        "portfolio_context_authoritative": False,
        "portfolio_context_source": "test/passive_replay_fixture",
        "account_truth_source": "paper_broker_snapshot",
        "pre_trade_equity": "100000.00",
        "pre_trade_cash": "100000.00",
        "pre_trade_position_qty": "0",
        "projected_order_notional": "1250.00",
        "projected_exposure_after_order": "1250.00",
        "exposure_veto_authority": None,
        "exposure_veto_applied": False,
        "exposure_manager_active": False,
        "reserved_buying_power": None,
    }


def _passive_exposure_snapshot_replay_context():
    """Passive exposure snapshot context; never a veto or dormant activation."""
    return {
        "exposure_authority_version": "exposure.passive_replay.v1",
        "exposure_manager_active": False,
        "exposure_veto_authority": None,
        "exposure_veto_applied": False,
        "exposure_veto_reason": None,
        "exposure_snapshot_id": "exposure-snapshot-passive-001",
        "exposure_snapshot_version": 1,
        "snapshot_quality": "PASSIVE_REPLAY_CONTEXT",
        "pre_trade_equity": "100000.00",
        "pre_trade_cash": "100000.00",
        "pre_trade_positions_hash": "sha256:positions-passive-empty",
        "pre_trade_reservations_hash": "sha256:reservations-passive-empty",
        "projected_order_notional": "1250.00",
        "projected_global_utilization": "9.9900",
        "projected_sleeve_utilization": "9.9900",
        "projected_asset_concentration": "9.9900",
        "reservation_id": "reservation-passive-001",
        "reservation_status": "PASSIVE_NOT_RESERVED",
        "reserved_buying_power_before": "0",
        "reserved_buying_power_after": "0",
        "effective_gross_before": "0",
        "effective_gross_after": "1250.00",
        "residual_net_exposure_before": "0",
        "residual_net_exposure_after": "1250.00",
        "source_truth_frame_id": "truth-frame-passive-001",
    }


def _assert_aggression_replay_payload(payload, *, telemetry_event):
    """Assert persisted telemetry uses Commander authority, not advisory hints."""
    assert payload["canonical_aggression_contract"]["authority_owner"] == "Commander"
    assert payload["canonical_aggression_contract"]["execution_is_attack"] is False
    assert payload["canonical_aggression_contract"]["mode"] == "SAFE"
    assert payload["canonical_aggression_contract"]["moving_floor_active"] is False
    assert payload["canonical_aggression_contract"]["dormant_governors_active"] is False

    assert payload["aggression_replay_proof"]["authority_owner"] == "Commander"
    assert payload["aggression_replay_proof"]["execution_is_attack"] is False
    assert payload["aggression_replay_proof"]["execution_is_attack_source"] == (
        "Commander.canonical_aggression_contract.execution_is_attack"
    )
    assert payload["aggression_replay_proof"]["fusion_attack_mode"] is True
    assert payload["aggression_replay_proof"]["fusion_attack_mode_authoritative"] is False
    assert payload["aggression_replay_proof"]["advisory_aggression_metadata_present"] is True
    assert payload["aggression_replay_proof"]["advisory_aggression_metadata_authoritative"] is False

    assert payload["execution_is_attack_source"] == (
        "Commander.canonical_aggression_contract.execution_is_attack"
    )
    assert payload["execution_is_attack_matches_contract"] is True
    assert payload["advisory_aggression_metadata_present"] is True
    assert payload["advisory_aggression_snapshot_id"] == "bundle12b-hostile-advisory-fusion"

    order_metadata = payload["order_metadata"]
    assert order_metadata["is_attack"] is False
    assert order_metadata["canonical_aggression_contract"] == payload["canonical_aggression_contract"]
    assert order_metadata["aggression_replay_proof"] == payload["aggression_replay_proof"]
    assert "aggression_context" not in order_metadata
    assert telemetry_event in {"order_submitted", "fill", "order_rejected"}


def _assert_passive_portfolio_replay_payload(
    payload,
    *,
    expected_original_size,
    expected_masked_size,
):
    context = payload["portfolio_replay_context"]
    assert context["portfolio_context_authoritative"] is False
    assert context["portfolio_context_source"] == "test/passive_replay_fixture"
    assert context["account_truth_source"] == "paper_broker_snapshot"
    assert context["pre_trade_equity"] == "100000.00"
    assert context["pre_trade_cash"] == "100000.00"
    assert context["pre_trade_position_qty"] == "0"
    assert context["projected_order_notional"] == "1250.00"
    assert context["projected_exposure_after_order"] == "1250.00"
    assert context["exposure_veto_authority"] is None
    assert context["exposure_veto_applied"] is False
    assert context["exposure_manager_active"] is False
    assert context["reserved_buying_power"] is None

    order_metadata = payload["order_metadata"]
    assert order_metadata["portfolio_replay_context"] == context
    assert str(order_metadata["original_size"]) == str(expected_original_size)
    assert str(order_metadata["masked_size"]) == str(expected_masked_size)
    assert order_metadata["is_attack"] is False


def _assert_passive_exposure_snapshot_replay_payload(payload):
    context = payload["exposure_snapshot_replay_context"]
    expected_keys = {
        "exposure_authority_version",
        "exposure_manager_active",
        "exposure_veto_authority",
        "exposure_veto_applied",
        "exposure_veto_reason",
        "exposure_snapshot_id",
        "exposure_snapshot_version",
        "snapshot_quality",
        "pre_trade_equity",
        "pre_trade_cash",
        "pre_trade_positions_hash",
        "pre_trade_reservations_hash",
        "projected_order_notional",
        "projected_global_utilization",
        "projected_sleeve_utilization",
        "projected_asset_concentration",
        "reservation_id",
        "reservation_status",
        "reserved_buying_power_before",
        "reserved_buying_power_after",
        "effective_gross_before",
        "effective_gross_after",
        "residual_net_exposure_before",
        "residual_net_exposure_after",
        "source_truth_frame_id",
    }
    assert set(context) == expected_keys
    assert context["exposure_authority_version"] == "exposure.passive_replay.v1"
    assert context["exposure_manager_active"] is False
    assert context["exposure_veto_authority"] is None
    assert context["exposure_veto_applied"] is False
    assert context["exposure_veto_reason"] is None
    assert context["snapshot_quality"] == "PASSIVE_REPLAY_CONTEXT"
    assert context["reservation_status"] == "PASSIVE_NOT_RESERVED"
    assert context["projected_global_utilization"] == "9.9900"
    assert context["projected_sleeve_utilization"] == "9.9900"
    assert context["projected_asset_concentration"] == "9.9900"

    order_metadata = payload["order_metadata"]
    assert order_metadata["exposure_snapshot_replay_context"] == context
    assert "ExposureManager" not in json.dumps(payload)
    assert "validate_intent" not in json.dumps(payload)


def _assert_passive_order_lifecycle_replay_payload(
    payload,
    *,
    expected_client_order_id,
    expected_decision_uuid,
    expected_lifecycle_phase,
    expected_venue_order_id,
    expected_terminal_state=None,
    expected_is_terminal=None,
):
    context = payload["order_lifecycle_replay_context"]
    assert context["lifecycle_context_version"] == 1
    assert context["event_family"] == "order_lifecycle"
    assert context["client_order_id"] == expected_client_order_id
    assert context["venue_order_id"] == expected_venue_order_id
    assert context["decision_uuid"] == expected_decision_uuid
    assert context["lifecycle_phase"] == expected_lifecycle_phase
    assert context["order_id_namespace"] == "client_order_id"
    assert context["is_terminal"] is expected_is_terminal
    assert context["terminal_state"] == expected_terminal_state
    assert context["idempotency_key"] == (
        f"{expected_decision_uuid}:{expected_client_order_id}:{expected_lifecycle_phase}"
    )

    assert context["mapping_authoritative"] is False
    assert context["active_cancel_status_mapping_ready"] is False
    assert context["router_cache_authoritative"] is False
    assert context["exposure_reservation_authority"] is False
    assert context["exposure_reservation_mutated"] is False
    assert context["reservation_mapping_ready"] is False
    assert context["reservation_delta_authoritative"] is False
    candidate = context["reservation_candidate_delta"]
    assert context["reservation_candidate_authoritative"] is False
    if candidate is not None:
        assert candidate["reservation_authority"] is False
        assert candidate["exposure_reservation_mutated"] is False
        assert candidate["reservation_mutation_performed"] is False
        assert candidate["exposure_release_performed"] is False
        assert candidate["reservation_release_performed"] is False
        assert candidate["active_reservation_ledger_created"] is False
        assert candidate["client_order_id"] == expected_client_order_id
    assert context["passive_mapping_namespace"] in {"client_order_id", "mixed/passive"}
    assert context["passive_mapping_id_namespaces"][0] == "client_order_id"

    order_metadata = payload["order_metadata"]
    assert order_metadata["order_lifecycle_replay_context"] == context


# ---------------------------------------------------------------------------
# B1: float current_price -> Decimal enqueue_price
# ---------------------------------------------------------------------------

def test_submit_signal_float_price_normalised_to_decimal():
    engine = _make_engine()
    signal = _make_signal()
    # Pass a float current_price — this is the B1 blocker
    result = engine.submit_signal(signal, current_price=float(3000.0), is_attack=False)
    assert result is True
    queued = engine._execution_queue.get_nowait()
    assert isinstance(queued.enqueue_price, Decimal), (
        f"enqueue_price must be Decimal after float normalization, got {type(queued.enqueue_price)}"
    )
    assert queued.enqueue_price == Decimal("3000.0")


def test_submit_signal_decimal_price_passthrough():
    engine = _make_engine()
    signal = _make_signal()
    result = engine.submit_signal(signal, current_price=Decimal("3000.00"), is_attack=False)
    assert result is True
    queued = engine._execution_queue.get_nowait()
    assert isinstance(queued.enqueue_price, Decimal)
    assert queued.enqueue_price == Decimal("3000.00")


# ---------------------------------------------------------------------------
# SIGNAL_SUBMITTED log
# ---------------------------------------------------------------------------

def test_submit_signal_emits_signal_submitted_log(caplog):
    engine = _make_engine()
    signal = _make_signal()
    with caplog.at_level(logging.INFO, logger="app.execution.engine"):
        engine.submit_signal(signal, current_price=float(3000.0), is_attack=False)
    assert any("SIGNAL_SUBMITTED" in r.message for r in caplog.records), (
        "SIGNAL_SUBMITTED must appear in logs after successful queue"
    )


# ---------------------------------------------------------------------------
# B2: float masked_size -> Decimal OrderRequest.quantity
# ---------------------------------------------------------------------------

def test_execute_signal_float_masked_size_normalised(caplog):
    """_execute_signal must construct OrderRequest without TypeError from float masked_size."""
    engine = _make_engine()
    signal = _make_signal(side="buy")
    from app.utils.time_utils import now_ns
    queued = QueuedSignal(
        signal=signal,
        is_attack=False,
        enqueue_time_ns=now_ns(),
        enqueue_price=Decimal("3000.00"),
        enqueue_regime="neutral",
    )
    # Should not raise — float masked_size must be Decimal-normalized before OrderRequest
    with caplog.at_level(logging.INFO, logger="app.execution.engine"):
        engine._execute_signal(queued)

    assert any("PAPERBROKER_REACH_COUNT" in r.message for r in caplog.records), (
        "PAPERBROKER_REACH_COUNT must appear after submit_order is called"
    )


# ---------------------------------------------------------------------------
# B3: market order passes limit_price=None
# ---------------------------------------------------------------------------

def test_execute_signal_market_order_limit_price_none():
    engine = _make_engine()
    signal = _make_signal(side="buy", price=float(3100.0))  # signal.price is float
    from app.utils.time_utils import now_ns
    queued = QueuedSignal(
        signal=signal,
        is_attack=False,  # market order
        enqueue_time_ns=now_ns(),
        enqueue_price=Decimal("3000.00"),
        enqueue_regime="neutral",
    )
    submitted_order = None

    def capture_order(order):
        nonlocal submitted_order
        submitted_order = order
        return None

    engine.order_router.submit_order.side_effect = capture_order
    engine._execute_signal(queued)

    assert submitted_order is not None
    assert submitted_order.limit_price is None, (
        f"Market order must have limit_price=None, got {submitted_order.limit_price!r}"
    )
    assert submitted_order.order_type in ("market", "MARKET"), (
        f"order_type must be market, got {submitted_order.order_type!r}"
    )


# ---------------------------------------------------------------------------
# B3: limit order uses current_price-based Decimal limit_price
# ---------------------------------------------------------------------------

def test_execute_signal_limit_order_decimal_limit_price():
    engine = _make_engine()
    # Provide a float signal.price — should be ignored in favour of current_price offset
    signal = _make_signal(side="buy", price=float(2999.0))
    from app.utils.time_utils import now_ns
    queued = QueuedSignal(
        signal=signal,
        is_attack=True,  # limit order
        enqueue_time_ns=now_ns(),
        enqueue_price=Decimal("3000.00"),
        enqueue_regime="neutral",
    )
    submitted_order = None

    def capture_order(order):
        nonlocal submitted_order
        submitted_order = order
        return None

    engine.order_router.submit_order.side_effect = capture_order
    engine._execute_signal(queued)

    assert submitted_order is not None
    assert isinstance(submitted_order.limit_price, Decimal), (
        f"Limit order limit_price must be Decimal, got {type(submitted_order.limit_price)}"
    )
    assert submitted_order.limit_price > Decimal("0"), (
        "Limit order limit_price must be positive"
    )
    assert isinstance(submitted_order.quantity, Decimal), (
        f"quantity must be Decimal, got {type(submitted_order.quantity)}"
    )


# ---------------------------------------------------------------------------
# PAPERBROKER_REACH_COUNT and PAPER_FILL_COUNT
# ---------------------------------------------------------------------------

def test_execute_signal_paper_fill_count_on_fill(caplog):
    from app.models import OrderFill
    from app.models.enums import InternalOrderStatus, OrderSide
    from app.utils.time_utils import now_ns as _ns

    ts = _ns()
    mock_fill = OrderFill(
        order_id="test_order",
        symbol="ETH/USD",
        side=OrderSide.BUY,
        quantity=Decimal("0.05"),
        price=Decimal("3000.00"),
        fee=Decimal("0.01"),
        status=InternalOrderStatus.FILLED,
        exchange_ts_ns=ts,
        receive_ts_ns=ts,
    )

    engine = _make_engine()
    engine.order_router.submit_order.return_value = mock_fill

    signal = _make_signal(side="buy")
    queued = QueuedSignal(
        signal=signal,
        is_attack=False,
        enqueue_time_ns=ts,
        enqueue_price=Decimal("3000.00"),
        enqueue_regime="neutral",
    )

    with caplog.at_level(logging.INFO, logger="app.execution.engine"):
        engine._execute_signal(queued)

    messages = [r.message for r in caplog.records]
    assert any("PAPERBROKER_REACH_COUNT" in m for m in messages), (
        "PAPERBROKER_REACH_COUNT must appear when submit_order is reached"
    )
    assert any("PAPER_FILL_COUNT" in m for m in messages), (
        "PAPER_FILL_COUNT must appear when fill is returned"
    )


def test_execute_signal_no_paper_fill_count_when_pending(caplog):
    """When submit_order returns None (pending), PAPER_FILL_COUNT must NOT appear."""
    engine = _make_engine()
    engine.order_router.submit_order.return_value = None

    signal = _make_signal(side="buy")
    from app.utils.time_utils import now_ns
    queued = QueuedSignal(
        signal=signal,
        is_attack=False,
        enqueue_time_ns=now_ns(),
        enqueue_price=Decimal("3000.00"),
        enqueue_regime="neutral",
    )

    with caplog.at_level(logging.INFO, logger="app.execution.engine"):
        engine._execute_signal(queued)

    messages = [r.message for r in caplog.records]
    assert any("PAPERBROKER_REACH_COUNT" in m for m in messages)
    assert not any("PAPER_FILL_COUNT" in m for m in messages), (
        "PAPER_FILL_COUNT must NOT appear when order is pending (fill=None)"
    )


def test_execution_sr_fill_telemetry_decimal_stringification_regression(tmp_path):
    """
    Regression lock:
    - deterministic FillEvent seam keeps Decimal quantity/price/fee types
    - persisted telemetry payload stores those fields as plain strings
      (no float coercion and no scientific notation)
    """
    telemetry_path = tmp_path / "sr_decimal_telemetry.db"
    store = TelemetryEventStore(str(telemetry_path))
    recorder = FillRecorder(store)

    fill_event = FillEvent(
        fill_event_id="fill_decimal_regression",
        execution_event_id="exec_decimal_regression",
        order_intent_id="order_decimal_regression",
        decision_uuid="sr-decimal-regression-uuid",
        symbol="ETH/USD",
        side=OrderSide.BUY,
        quantity=Decimal("0.001"),
        price=Decimal("3000.125"),
        fee=Decimal("0.0105"),
        fee_currency="USD",
        venue_fill_id="venue_decimal_regression",
        exchange_ts_ns=1_700_000_000_000_000_000,
        receive_ts_ns=1_700_000_000_000_000_001,
    )
    # FillEvent currently stores enum values as strings; FillRecorder expects
    # a side object with .value. Normalize to enum for this telemetry seam.
    fill_event.side = OrderSide.BUY
    recorder.record_fill(fill_event)

    assert isinstance(fill_event.quantity, Decimal)
    assert isinstance(fill_event.price, Decimal)
    assert isinstance(fill_event.fee, Decimal)

    events = store.get_events_by_type("fill", limit=10)
    assert events, "Expected persisted fill telemetry event"
    payload_json = events[0]["payload_json"]
    payload = json.loads(payload_json)

    assert isinstance(payload["quantity"], str)
    assert isinstance(payload["price"], str)
    assert isinstance(payload["fee"], str)

    assert payload["quantity"] == str(fill_event.quantity)
    assert payload["price"] == str(fill_event.price)
    assert payload["fee"] == str(fill_event.fee)
    context = payload["order_lifecycle_replay_context"]
    assert context["client_order_id"] == fill_event.order_intent_id
    assert context["venue_order_id"] is None
    assert context["venue_fill_id"] == fill_event.venue_fill_id
    assert context["original_qty"] == str(fill_event.quantity)
    assert context["cumulative_filled_qty"] == str(fill_event.quantity)
    assert context["avg_fill_price"] == str(fill_event.price)
    assert context["cumulative_fee"] == str(fill_event.fee)
    assert context["mapping_authoritative"] is False
    assert context["active_cancel_status_mapping_ready"] is False
    assert context["router_cache_authoritative"] is False
    assert context["exposure_reservation_authority"] is False
    assert context["exposure_reservation_mutated"] is False
    assert context["reservation_mapping_ready"] is False
    assert context["reservation_delta_authoritative"] is False
    candidate = context["reservation_candidate_delta"]
    assert candidate is not None
    assert candidate["release_candidate_only"] is True
    assert candidate["open_candidate_only"] is False
    assert candidate["adjust_candidate_only"] is False
    assert candidate["reservation_authority"] is False
    assert candidate["exposure_reservation_mutated"] is False
    assert candidate["reservation_release_performed"] is False
    assert candidate["active_reservation_ledger_created"] is False
    assert context["reservation_candidate_authoritative"] is False

    assert "e" not in payload["quantity"].lower()
    assert "e" not in payload["price"].lower()
    assert "e" not in payload["fee"].lower()


def test_execution_engine_paper_fill_telemetry_e2e_with_decision_uuid(tmp_path):
    """
    End-to-end regression lock:
    StrategySignal metadata decision_uuid flows through execution into
    persisted fill telemetry with Decimal monetary fields stringified.
    """
    from app.execution.order_router import OrderRouter
    from app.models.signals import StrategySignal
    from app.utils.time_utils import now_ns

    telemetry_path = tmp_path / "e2e_fill_telemetry.db"
    store = TelemetryEventStore(str(telemetry_path))

    commander = MagicMock()
    risk_guard = MagicMock()
    risk_guard.can_trade.return_value = True
    risk_guard.is_vol_fuse_triggered.return_value = False
    risk_guard.register_recalibrate_callback = MagicMock()
    risk_guard.register_emergency_callback = MagicMock()
    risk_guard.register_zombie_callback = MagicMock()
    risk_guard.register_lag_callback = MagicMock()
    risk_guard.register_vol_fuse_callback = MagicMock()

    masking_layer = MagicMock()
    masked = MagicMock()
    masked.masked_size = Decimal("0.05")
    masking_layer.mask_order.return_value = masked

    router = OrderRouter(paper_mode=True, telemetry_store=store)
    engine = ExecutionEngine(
        commander=commander,
        risk_guard=risk_guard,
        order_router=router,
        masking_layer=masking_layer,
    )
    engine._state.is_running = True
    engine._state.last_regime = "neutral"

    decision_uuid = "bundle3a-e2e-decision-uuid"
    signal_ts_ns = now_ns() - 1_000_000
    replay_metadata = _canonical_aggression_replay_metadata()
    portfolio_replay_context = _passive_portfolio_replay_context()
    exposure_snapshot_replay_context = _passive_exposure_snapshot_replay_context()
    signal = StrategySignal(
        strategy="sector_rotation",
        symbol="ETH/USD",
        side="buy",
        confidence=0.9,
        quantity=0.05,
        price=None,
        exchange_ts_ns=signal_ts_ns,
        reason="bundle3a e2e telemetry guardrail",
        metadata={
            "decision_uuid": decision_uuid,
            "portfolio_replay_context": portfolio_replay_context,
            "exposure_snapshot_replay_context": exposure_snapshot_replay_context,
            **replay_metadata,
        },
    )

    admitted = engine.submit_signal(
        signal=signal,
        current_price=Decimal("3000.00"),
        is_attack=False,
    )
    assert admitted is True
    risk_guard.can_trade.assert_called_once_with()
    risk_guard.is_vol_fuse_triggered.assert_called_once_with()

    queued = engine._execution_queue.get_nowait()
    assert queued.decision_uuid == decision_uuid

    engine._execute_signal(queued)
    masking_layer.mask_order.assert_called_once_with(0.05)

    events = store.get_events_by_type("fill", limit=20)
    assert events, "Expected persisted fill telemetry event from end-to-end execution path"

    match = next((event for event in events if event.get("decision_uuid") == decision_uuid), None)
    assert match is not None, "Expected fill event with submitted decision_uuid"

    payload = json.loads(match["payload_json"])
    assert payload["decision_uuid"] == decision_uuid
    _assert_aggression_replay_payload(payload, telemetry_event="fill")
    _assert_passive_portfolio_replay_payload(
        payload,
        expected_original_size="0.05",
        expected_masked_size="0.05",
    )
    _assert_passive_exposure_snapshot_replay_payload(payload)
    expected_client_order_id = (
        queued.signal.strategy + "_" + queued.signal.symbol + "_" + str(queued.signal.exchange_ts_ns)
    )
    _assert_passive_order_lifecycle_replay_payload(
        payload,
        expected_client_order_id=expected_client_order_id,
        expected_decision_uuid=decision_uuid,
        expected_lifecycle_phase="full_fill",
        expected_venue_order_id=payload["order_lifecycle_replay_context"]["venue_order_id"],
        expected_terminal_state="filled",
        expected_is_terminal=True,
    )
    assert payload["order_lifecycle_replay_context"]["venue_order_id"] is not None
    assert payload["order_lifecycle_replay_context"]["broker_order_id"] is not None
    assert payload["order_lifecycle_replay_context"]["venue_fill_id"] == expected_client_order_id
    assert isinstance(payload["order_lifecycle_replay_context"]["original_qty"], str)
    assert Decimal(payload["order_lifecycle_replay_context"]["original_qty"]) == Decimal("0.05")
    assert payload["order_lifecycle_replay_context"]["terminal_reason"] == "full_fill_observed"
    assert payload["order_lifecycle_replay_context"]["status_source"] == "order_router.fill_observation"
    assert payload["order_lifecycle_replay_context"]["id_mapping_source"] == "paper_broker.execution_report"
    assert payload["order_lifecycle_replay_context"]["submit_seen"] is True
    assert payload["order_lifecycle_replay_context"]["partial_fill_seen"] is None
    assert payload["order_lifecycle_replay_context"]["full_fill_seen"] is True
    assert payload["order_lifecycle_replay_context"]["cumulative_filled_qty"] == payload["quantity"]
    assert Decimal(payload["order_lifecycle_replay_context"]["cumulative_filled_qty"]) == Decimal("0.05")
    assert payload["order_lifecycle_replay_context"]["remaining_qty"] == "0"
    assert payload["order_lifecycle_replay_context"]["avg_fill_price"] == payload["price"]
    assert payload["order_lifecycle_replay_context"]["cumulative_fee"] == payload["fee"]
    release_candidate = payload["reservation_candidate_delta"]
    assert release_candidate == payload["order_lifecycle_replay_context"]["reservation_candidate_delta"]
    assert release_candidate["release_candidate_only"] is True
    assert release_candidate["reservation_dedupe_key"] == f"{decision_uuid}:{expected_client_order_id}"

    assert isinstance(payload["quantity"], str)
    assert isinstance(payload["price"], str)
    assert isinstance(payload["fee"], str)

    assert payload["quantity"] == str(Decimal(payload["quantity"]))
    assert payload["price"] == str(Decimal(payload["price"]))
    assert payload["fee"] == str(Decimal(payload["fee"]))

    assert "e" not in payload["quantity"].lower()
    assert "e" not in payload["price"].lower()
    assert "e" not in payload["fee"].lower()

    assert int(match["receive_ts_ns"]) >= int(match["exchange_ts_ns"])

    order_events = store.get_events_by_type("order", limit=20)
    assert order_events, "Expected persisted order submission telemetry event"

    order_submit = next(
        (
            event
            for event in order_events
            if event.get("decision_uuid") == decision_uuid
            and json.loads(event["payload_json"]).get("telemetry_event") == "order_submitted"
        ),
        None,
    )
    assert order_submit is not None, "Expected decision-linked order_submitted event"

    order_payload = json.loads(order_submit["payload_json"])
    assert order_payload["client_order_id"] == expected_client_order_id
    assert order_payload["decision_uuid"] == decision_uuid
    _assert_aggression_replay_payload(order_payload, telemetry_event="order_submitted")
    _assert_passive_portfolio_replay_payload(
        order_payload,
        expected_original_size="0.05",
        expected_masked_size="0.05",
    )
    _assert_passive_exposure_snapshot_replay_payload(order_payload)
    _assert_passive_order_lifecycle_replay_payload(
        order_payload,
        expected_client_order_id=expected_client_order_id,
        expected_decision_uuid=decision_uuid,
        expected_lifecycle_phase="order_submitted",
        expected_venue_order_id=None,
        expected_is_terminal=False,
    )
    assert order_payload["order_lifecycle_replay_context"]["broker_order_id"] is None
    assert order_payload["order_lifecycle_replay_context"]["exchange_txid"] is None
    assert order_payload["order_lifecycle_replay_context"]["venue_fill_id"] is None
    assert isinstance(order_payload["order_lifecycle_replay_context"]["original_qty"], str)
    assert Decimal(order_payload["order_lifecycle_replay_context"]["original_qty"]) == Decimal("0.05")
    assert order_payload["order_lifecycle_replay_context"]["terminal_state"] is None
    assert order_payload["order_lifecycle_replay_context"]["terminal_reason"] is None
    assert order_payload["order_lifecycle_replay_context"]["status_source"] == "order_router.submit_attempt"
    assert order_payload["order_lifecycle_replay_context"]["id_mapping_source"] == "order_router.client_order_id"
    assert order_payload["order_lifecycle_replay_context"]["submit_seen"] is True
    assert order_payload["order_lifecycle_replay_context"]["reject_seen"] is None
    assert order_payload["order_lifecycle_replay_context"]["partial_fill_seen"] is None
    assert order_payload["order_lifecycle_replay_context"]["full_fill_seen"] is None
    assert order_payload["order_lifecycle_replay_context"]["cancel_seen"] is None
    assert order_payload["order_lifecycle_replay_context"]["cumulative_filled_qty"] == "0"
    assert Decimal(order_payload["order_lifecycle_replay_context"]["remaining_qty"]) == Decimal("0.05")
    assert order_payload["order_lifecycle_replay_context"]["cumulative_fee"] == "0"
    open_candidate = order_payload["reservation_candidate_delta"]
    assert open_candidate == order_payload["order_lifecycle_replay_context"]["reservation_candidate_delta"]
    assert open_candidate["open_candidate_only"] is True
    assert open_candidate["adjust_candidate_only"] is False
    assert open_candidate["release_candidate_only"] is False
    assert open_candidate["reservation_authority"] is False
    assert open_candidate["exposure_reservation_mutated"] is False
    assert open_candidate["reservation_dedupe_key"] == f"{decision_uuid}:{expected_client_order_id}"
    assert order_payload["symbol"] == "ETH/USD"
    assert order_payload["side"] == "buy"
    assert isinstance(order_payload["quantity"], str)
    assert Decimal(order_payload["quantity"]) == Decimal("0.05")
    assert order_payload["order_type"] == "market"
    assert order_payload["limit_price"] is None
    assert int(order_submit["receive_ts_ns"]) >= int(order_submit["exchange_ts_ns"])
    assert "e" not in order_payload["quantity"].lower()

    chain = store.get_decision_chain(decision_uuid)
    chain_event_ids = [event["event_id"] for event in chain]
    assert order_submit["event_id"] in chain_event_ids
    assert match["event_id"] in chain_event_ids


def test_rejection_telemetry_payload_replay_context_parity(tmp_path):
    """
    Rejection telemetry should persist decision-linked replay context using
    available order-level fields when provided.
    """
    from app.models.enums import OrderType

    telemetry_path = tmp_path / "rejection_replay_context.db"
    store = TelemetryEventStore(str(telemetry_path))
    recorder = FillRecorder(store)

    decision_uuid = "rejection-replay-decision-uuid"
    replay_metadata = _order_replay_metadata_from_signal_metadata(
        _canonical_aggression_replay_metadata()
    )
    replay_metadata["portfolio_replay_context"] = _passive_portfolio_replay_context()
    replay_metadata["exposure_snapshot_replay_context"] = (
        _passive_exposure_snapshot_replay_context()
    )
    event_id = recorder.record_rejection(
        client_order_id="reject_client_order_001",
        decision_uuid=decision_uuid,
        reason="simulated rejection for replay parity",
        reject_ts_ns=1_700_000_000_000_000_000,
        symbol="ETH/USD",
        side=OrderSide.SELL,
        quantity=Decimal("0.250"),
        order_type=OrderType.LIMIT,
        limit_price=Decimal("2999.50"),
        venue_order_id="venue_reject_001",
        metadata=replay_metadata,
    )

    events = store.get_events_by_type("order_rejected", limit=20)
    assert events, "Expected persisted order_rejected telemetry event"

    match = next((event for event in events if event.get("event_id") == event_id), None)
    assert match is not None, "Expected rejection event to be queryable by event_id"
    assert match["decision_uuid"] == decision_uuid
    assert match["event_type"] == "order_rejected"
    assert int(match["receive_ts_ns"]) >= int(match["exchange_ts_ns"])

    payload = json.loads(match["payload_json"])
    assert payload["client_order_id"] == "reject_client_order_001"
    assert payload["decision_uuid"] == decision_uuid
    assert payload["symbol"] == "ETH/USD"
    assert payload["side"] == "sell"
    assert payload["quantity"] == "0.250"
    assert payload["order_type"] == "limit"
    assert payload["limit_price"] == "2999.50"
    assert payload["venue_order_id"] == "venue_reject_001"
    _assert_aggression_replay_payload(payload, telemetry_event="order_rejected")
    _assert_passive_portfolio_replay_payload(
        payload,
        expected_original_size="0.250",
        expected_masked_size="0.250",
    )
    _assert_passive_exposure_snapshot_replay_payload(payload)
    _assert_passive_order_lifecycle_replay_payload(
        payload,
        expected_client_order_id="reject_client_order_001",
        expected_decision_uuid=decision_uuid,
        expected_lifecycle_phase="rejected",
        expected_venue_order_id="venue_reject_001",
        expected_terminal_state="rejected",
        expected_is_terminal=True,
    )
    assert payload["order_lifecycle_replay_context"]["terminal_reason"] == (
        "simulated rejection for replay parity"
    )
    assert payload["order_lifecycle_replay_context"]["original_qty"] == "0.250"
    assert payload["order_lifecycle_replay_context"]["status_source"] == "fill_recorder.rejection"
    assert payload["order_lifecycle_replay_context"]["id_mapping_source"] == "fill_recorder.client_order_id"
    assert payload["order_lifecycle_replay_context"]["submit_seen"] is True
    assert payload["order_lifecycle_replay_context"]["reject_seen"] is True
    assert payload["order_lifecycle_replay_context"]["full_fill_seen"] is None
    assert payload["order_lifecycle_replay_context"]["cumulative_filled_qty"] == "0"
    assert payload["order_lifecycle_replay_context"]["remaining_qty"] == "0.250"
    assert payload["order_lifecycle_replay_context"]["cumulative_fee"] == "0"

    assert "e" not in payload["quantity"].lower()
    assert "e" not in payload["limit_price"].lower()
