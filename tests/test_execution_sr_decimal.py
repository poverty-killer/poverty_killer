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
from decimal import Decimal
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from app.execution.engine import ExecutionEngine, QueuedSignal


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
