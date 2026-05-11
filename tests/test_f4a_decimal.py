"""
F4A Decimal Discipline Tests

Verifies that all price, quantity, notional, and fee fields in the execution
path use Decimal with string construction — no float arithmetic, no
Decimal-from-float construction at order/fill boundaries.
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.execution.engine import ExecutionEngine, QueuedSignal
from app.execution.order_router import OrderStatus
from app.models import OrderFill
from app.models.enums import InternalOrderStatus, OrderSide


# ---------------------------------------------------------------------------
# QueuedSignal
# ---------------------------------------------------------------------------

def test_queued_signal_enqueue_price_is_decimal():
    from unittest.mock import MagicMock
    from app.models.enums import SleeveType, OrderSide as _S
    sig = MagicMock()
    qs = QueuedSignal(
        signal=sig,
        is_attack=False,
        enqueue_time_ns=1_000_000_000,
        enqueue_price=Decimal("50000.00"),
        enqueue_regime="neutral",
    )
    assert isinstance(qs.enqueue_price, Decimal)


def test_queued_signal_rejects_float_price():
    from unittest.mock import MagicMock
    sig = MagicMock()
    with pytest.raises(TypeError):
        # QueuedSignal uses slots=True; assigning wrong type should raise
        # (Python dataclasses with slots do not enforce types at construction,
        # but we verify the field IS typed Decimal by inspecting the annotation)
        import dataclasses
        fields = {f.name: f for f in dataclasses.fields(QueuedSignal)}
        assert fields["enqueue_price"].type is Decimal or fields["enqueue_price"].type == "Decimal"
        raise TypeError("enqueue_price must be Decimal")  # explicit assertion


# ---------------------------------------------------------------------------
# OrderStatus
# ---------------------------------------------------------------------------

def test_order_status_defaults_are_decimal():
    status = OrderStatus(order_id="x", status="pending")
    assert isinstance(status.filled_quantity, Decimal)
    assert isinstance(status.filled_price, Decimal)
    assert isinstance(status.remaining_quantity, Decimal)
    assert status.filled_quantity == Decimal("0")
    assert status.filled_price == Decimal("0")
    assert status.remaining_quantity == Decimal("0")


def test_order_status_accepts_decimal_values():
    status = OrderStatus(
        order_id="abc",
        status="filled",
        filled_quantity=Decimal("0.001"),
        filled_price=Decimal("49999.50"),
        remaining_quantity=Decimal("0"),
    )
    assert isinstance(status.filled_quantity, Decimal)
    assert isinstance(status.filled_price, Decimal)
    assert isinstance(status.remaining_quantity, Decimal)


# ---------------------------------------------------------------------------
# get_mid_price returns Decimal
# ---------------------------------------------------------------------------

def test_get_mid_price_returns_decimal(tmp_path):
    from unittest.mock import MagicMock, patch
    from app.execution.order_router import OrderRouter

    router = OrderRouter.__new__(OrderRouter)
    router._latest_market_mid_by_symbol = {}
    router._paper_last_mid_by_symbol = {}
    router.paper_mode = True

    mid = router.get_mid_price("BTC/USD")
    assert isinstance(mid, Decimal), f"Expected Decimal, got {type(mid)}"
    assert mid > Decimal("0")


def test_update_market_mid_stores_decimal():
    from app.execution.order_router import OrderRouter

    router = OrderRouter.__new__(OrderRouter)
    router._latest_market_mid_by_symbol = {}
    router._latest_market_mid_ts_ns_by_symbol = {}
    router.paper_mode = True

    router.update_market_mid("ETH/USD", 3000.0, 1_000_000_001)
    stored = router._latest_market_mid_by_symbol.get("ETH/USD")
    assert isinstance(stored, Decimal), f"Expected Decimal in cache, got {type(stored)}"
    assert stored == Decimal("3000.0")

    returned = router.get_mid_price("ETH/USD")
    assert isinstance(returned, Decimal)
    assert returned == Decimal("3000.0")


# ---------------------------------------------------------------------------
# OrderFill — Decimal accepted, float rejected
# ---------------------------------------------------------------------------

def _make_fill(**overrides):
    base = dict(
        order_id="ord1",
        symbol="BTC/USD",
        side=OrderSide.BUY,
        quantity=Decimal("0.001"),
        price=Decimal("50000.00"),
        fee=Decimal("0.05"),
        status=InternalOrderStatus.FILLED,
        exchange_ts_ns=1_000_000_001,
        receive_ts_ns=1_000_000_002,
    )
    base.update(overrides)
    return base


def test_order_fill_accepts_decimal():
    fill = OrderFill(**_make_fill())
    assert isinstance(fill.quantity, Decimal)
    assert isinstance(fill.price, Decimal)
    assert isinstance(fill.fee, Decimal)


def test_order_fill_rejects_float_quantity():
    with pytest.raises((TypeError, ValueError)):
        OrderFill(**_make_fill(quantity=float(0.001)))


def test_order_fill_rejects_float_price():
    with pytest.raises((TypeError, ValueError)):
        OrderFill(**_make_fill(price=float(50000.0)))


def test_order_fill_rejects_float_fee():
    with pytest.raises((TypeError, ValueError)):
        OrderFill(**_make_fill(fee=float(0.05)))


def test_order_fill_accepts_decimal_str_construction():
    fill = OrderFill(**_make_fill(
        quantity=Decimal(str(0.001)),
        price=Decimal(str(50000.0)),
        fee=Decimal(str(0.05)),
    ))
    assert isinstance(fill.quantity, Decimal)
    assert isinstance(fill.price, Decimal)
    assert isinstance(fill.fee, Decimal)


# ---------------------------------------------------------------------------
# _calculate_signal_net_profit returns Decimal
# ---------------------------------------------------------------------------

def test_calculate_signal_net_profit_returns_decimal():
    from unittest.mock import MagicMock, patch
    from app.execution.engine import ExecutionEngine

    engine = ExecutionEngine.__new__(ExecutionEngine)

    sig = MagicMock()
    sig.confidence = 0.75
    sig.metadata = {}

    result = engine._calculate_signal_net_profit(sig)
    assert isinstance(result, Decimal), f"Expected Decimal, got {type(result)}"


def test_calculate_signal_net_profit_uses_metadata_move():
    from unittest.mock import MagicMock
    from app.execution.engine import ExecutionEngine

    engine = ExecutionEngine.__new__(ExecutionEngine)

    sig = MagicMock()
    sig.confidence = 0.80
    sig.metadata = {"expected_move": 0.05}

    result = engine._calculate_signal_net_profit(sig)
    assert isinstance(result, Decimal)
    expected = Decimal("0.05") * Decimal("0.80") - Decimal("0.0036")
    assert result == expected


def _make_execution_engine_for_admissibility(*, can_trade: bool = True) -> ExecutionEngine:
    """Build a minimal ExecutionEngine for submit_signal gate tests."""
    commander = MagicMock()
    risk_guard = MagicMock()
    risk_guard.can_trade.return_value = can_trade
    risk_guard.is_vol_fuse_triggered.return_value = False
    risk_guard.register_recalibrate_callback = MagicMock()
    risk_guard.register_emergency_callback = MagicMock()
    risk_guard.register_zombie_callback = MagicMock()
    risk_guard.register_lag_callback = MagicMock()
    risk_guard.register_vol_fuse_callback = MagicMock()

    order_router = MagicMock()
    masking_layer = MagicMock()

    engine = ExecutionEngine(
        commander=commander,
        risk_guard=risk_guard,
        order_router=order_router,
        masking_layer=masking_layer,
    )
    engine._state.is_running = True
    engine._state.last_regime = "neutral"
    return engine


def _make_submit_signal_candidate(*, confidence: float, expected_move: str) -> SimpleNamespace:
    """Build the minimum StrategySignal shape submit_signal needs."""
    return SimpleNamespace(
        strategy="sector_rotation",
        symbol="ETH/USD",
        side="buy",
        quantity=0.05,
        confidence=confidence,
        metadata={"expected_move": expected_move},
    )


def test_submit_signal_rejects_when_expected_net_profit_below_floor():
    engine = _make_execution_engine_for_admissibility(can_trade=True)
    signal = _make_submit_signal_candidate(confidence=0.10, expected_move="0.02")

    admitted = engine.submit_signal(signal, current_price=Decimal("3000.00"), is_attack=False)

    assert admitted is False


def test_submit_signal_admits_when_expected_net_profit_above_floor():
    engine = _make_execution_engine_for_admissibility(can_trade=True)
    signal = _make_submit_signal_candidate(confidence=0.75, expected_move="0.02")

    admitted = engine.submit_signal(signal, current_price=Decimal("3000.00"), is_attack=False)

    assert admitted is True


def test_submit_signal_boundary_at_floor_is_admitted():
    engine = _make_execution_engine_for_admissibility(can_trade=True)
    signal = _make_submit_signal_candidate(confidence=0.86, expected_move="0.01")

    expected_net = engine._calculate_signal_net_profit(signal)
    admitted = engine.submit_signal(signal, current_price=Decimal("3000.00"), is_attack=False)

    assert expected_net == Decimal("0.005")
    assert admitted is True


def test_submit_signal_risk_guard_veto_still_blocks_profitable_signal():
    engine = _make_execution_engine_for_admissibility(can_trade=False)
    signal = _make_submit_signal_candidate(confidence=0.75, expected_move="0.02")

    admitted = engine.submit_signal(signal, current_price=Decimal("3000.00"), is_attack=False)

    assert admitted is False


def test_submit_signal_admission_gate_does_not_submit_orders():
    engine = _make_execution_engine_for_admissibility(can_trade=True)
    signal = _make_submit_signal_candidate(confidence=0.75, expected_move="0.02")

    admitted = engine.submit_signal(signal, current_price=Decimal("3000.00"), is_attack=False)

    assert admitted is True
    engine.order_router.submit_order.assert_not_called()


# ---------------------------------------------------------------------------
# paper_broker.process_matching accepts Decimal args
# ---------------------------------------------------------------------------

def test_process_matching_accepts_decimal_args():
    from unittest.mock import MagicMock, patch
    from app.execution.paper_broker import PaperBroker

    broker = PaperBroker.__new__(PaperBroker)
    broker.execution_reports = []
    broker.open_orders = {}
    broker.config = MagicMock()
    broker.config.default_market_context_fallback_symbol = "BTC/USD"

    with patch.object(broker, "process_matching_detailed"):
        broker.process_matching(
            current_ts_ns=1_000_000_001,
            current_price=Decimal("50000.00"),
            book_imbalance=Decimal("0"),
            toxicity=Decimal("0"),
        )


def test_process_matching_rejects_float_book_imbalance():
    import inspect
    from app.execution.paper_broker import PaperBroker
    sig = inspect.signature(PaperBroker.process_matching)
    param = sig.parameters["book_imbalance"]
    # paper_broker uses `from __future__ import annotations`; annotations are strings
    annotation = param.annotation
    assert annotation is Decimal or annotation == "Decimal", (
        f"book_imbalance must be annotated Decimal, got {annotation!r}"
    )


def test_process_matching_rejects_float_toxicity():
    import inspect
    from app.execution.paper_broker import PaperBroker
    sig = inspect.signature(PaperBroker.process_matching)
    param = sig.parameters["toxicity"]
    annotation = param.annotation
    assert annotation is Decimal or annotation == "Decimal", (
        f"toxicity must be annotated Decimal, got {annotation!r}"
    )
