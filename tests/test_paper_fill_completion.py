"""
PAPER_FILL_COMPLETION_PROOF_BUNDLE — targeted tests.

Proves:
1. Valid paper SELL accepted when short selling configured.
2. Valid paper MARKET order fills when depth absent but mid/best price exists.
3. LIMIT orders do not fake-fill when depth absent and price conditions not met.
4. Latency-gated paper order becomes eligible when matching timestamp advanced.
5. OrderRouter returns OrderFill when PaperBroker reports filled.
6. Pending/un-fillable orders return None from OrderRouter.
7. No Decimal/float regression in fill fields.
"""

from decimal import Decimal
import json
import time

import pytest

from app.execution.paper_broker import (
    PaperBroker,
    PaperBrokerConfig,
    PaperMarketContext,
)
from app.execution.fee_model import FeeModel
from app.execution.slippage_model import SlippageModel
from app.execution.latency_model import LatencyModel
from app.execution.order_router import OrderRouter
from app.telemetry.event_store import TelemetryEventStore
from app.utils.enums import (
    OrderSide as PbOrderSide,
    OrderType as PbOrderType,
    OrderStatus as PbOrderStatus,
    TimeInForce,
)
from app.models import OrderFill, OrderRequest
from app.models.enums import OrderSide, OrderType, SleeveType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_broker(short_selling: bool = False) -> PaperBroker:
    return PaperBroker(
        fee_model=FeeModel(),
        slippage_model=SlippageModel(),
        latency_model=LatencyModel(),
        config=PaperBrokerConfig(enable_short_selling=short_selling),
    )


def _make_market_ctx(
    symbol: str = "ETH/USD",
    mid: str = "3000",
    best_bid: str = "2999",
    best_ask: str = "3001",
    ts_ns: int = 1,
) -> PaperMarketContext:
    return PaperMarketContext(
        symbol=symbol,
        timestamp_ns=ts_ns,
        mid_price=Decimal(mid),
        best_bid=Decimal(best_bid),
        best_ask=Decimal(best_ask),
        # ask_levels and bid_levels default to () — no depth
    )


def _now_ns() -> int:
    return time.time_ns()


# ---------------------------------------------------------------------------
# Test 1 — Valid paper SELL accepted when short selling configured
# ---------------------------------------------------------------------------

def test_sell_accepted_with_short_selling_enabled():
    broker = _make_broker(short_selling=True)
    ts = _now_ns()

    paper_order = broker.submit_order_detailed(
        symbol="ETH/USD",
        side=PbOrderSide.SELL,
        order_type=PbOrderType.MARKET,
        time_in_force=TimeInForce.GTC,
        quantity=Decimal("0.5"),
        price=None,
        ts_ns=ts,
        client_id="sell-short-001",
    )

    assert paper_order is not None
    assert "sell-short-001" in broker.open_orders


def test_sell_rejected_without_short_selling():
    broker = _make_broker(short_selling=False)
    ts = _now_ns()

    with pytest.raises((ValueError, Exception)):
        broker.submit_order_detailed(
            symbol="ETH/USD",
            side=PbOrderSide.SELL,
            order_type=PbOrderType.MARKET,
            time_in_force=TimeInForce.GTC,
            quantity=Decimal("0.5"),
            price=None,
            ts_ns=ts,
            client_id="sell-no-short-001",
        )


# ---------------------------------------------------------------------------
# Test 2 — MARKET order fills when depth absent but mid/best price exists
# ---------------------------------------------------------------------------

def test_market_buy_fills_without_depth_levels():
    broker = _make_broker(short_selling=True)
    ts = _now_ns()

    paper_order = broker.submit_order_detailed(
        symbol="ETH/USD",
        side=PbOrderSide.BUY,
        order_type=PbOrderType.MARKET,
        time_in_force=TimeInForce.GTC,
        quantity=Decimal("0.5"),
        price=None,
        ts_ns=ts,
        client_id="mkt-buy-no-depth-001",
    )

    eligible_ns = paper_order.eligible_at_ns
    ctx = _make_market_ctx(ts_ns=eligible_ns + 1)

    broker.process_matching_detailed(
        current_ts_ns=eligible_ns + 1,
        market_by_symbol={"ETH/USD": ctx},
    )

    filled = [
        r for r in broker.execution_reports
        if r.status == PbOrderStatus.FULLY_FILLED
    ]
    assert len(filled) >= 1, "Expected FULLY_FILLED report after MARKET order with no depth"
    assert filled[0].filled_quantity == Decimal("0.5")
    assert filled[0].fill_price > Decimal("0")


def test_market_sell_fills_without_depth_levels():
    broker = _make_broker(short_selling=True)
    ts = _now_ns()

    paper_order = broker.submit_order_detailed(
        symbol="ETH/USD",
        side=PbOrderSide.SELL,
        order_type=PbOrderType.MARKET,
        time_in_force=TimeInForce.GTC,
        quantity=Decimal("0.5"),
        price=None,
        ts_ns=ts,
        client_id="mkt-sell-no-depth-001",
    )

    eligible_ns = paper_order.eligible_at_ns
    ctx = _make_market_ctx(ts_ns=eligible_ns + 1)

    broker.process_matching_detailed(
        current_ts_ns=eligible_ns + 1,
        market_by_symbol={"ETH/USD": ctx},
    )

    filled = [
        r for r in broker.execution_reports
        if r.status == PbOrderStatus.FULLY_FILLED
    ]
    assert len(filled) >= 1, "Expected FULLY_FILLED report after MARKET SELL with no depth"
    assert filled[0].filled_quantity == Decimal("0.5")


# ---------------------------------------------------------------------------
# Test 3 — LIMIT orders do not fake-fill when depth absent and price wrong
# ---------------------------------------------------------------------------

def test_limit_buy_does_not_fill_when_price_below_market():
    broker = _make_broker()
    ts = _now_ns()

    paper_order = broker.submit_order_detailed(
        symbol="ETH/USD",
        side=PbOrderSide.BUY,
        order_type=PbOrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        quantity=Decimal("0.5"),
        price=Decimal("1.00"),   # far below market at 3001
        ts_ns=ts,
        client_id="limit-below-market-001",
    )

    eligible_ns = paper_order.eligible_at_ns
    ctx = _make_market_ctx(ts_ns=eligible_ns + 1)

    broker.process_matching_detailed(
        current_ts_ns=eligible_ns + 1,
        market_by_symbol={"ETH/USD": ctx},
    )

    filled = [
        r for r in broker.execution_reports
        if r.status == PbOrderStatus.FULLY_FILLED
    ]
    assert len(filled) == 0, "LIMIT BUY below market must NOT fill when no depth"


def test_limit_sell_does_not_fill_when_price_above_market():
    broker = _make_broker(short_selling=True)
    ts = _now_ns()

    paper_order = broker.submit_order_detailed(
        symbol="ETH/USD",
        side=PbOrderSide.SELL,
        order_type=PbOrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        quantity=Decimal("0.5"),
        price=Decimal("99999.00"),  # far above market bid at 2999
        ts_ns=ts,
        client_id="limit-above-market-001",
    )

    eligible_ns = paper_order.eligible_at_ns
    ctx = _make_market_ctx(ts_ns=eligible_ns + 1)

    broker.process_matching_detailed(
        current_ts_ns=eligible_ns + 1,
        market_by_symbol={"ETH/USD": ctx},
    )

    filled = [
        r for r in broker.execution_reports
        if r.status == PbOrderStatus.FULLY_FILLED
    ]
    assert len(filled) == 0, "LIMIT SELL above market must NOT fill when no depth"


# ---------------------------------------------------------------------------
# Test 4 — Latency gate: order only fills after eligible_at_ns
# ---------------------------------------------------------------------------

def test_latency_gate_order_not_filled_before_eligible():
    broker = _make_broker()
    ts = _now_ns()

    paper_order = broker.submit_order_detailed(
        symbol="ETH/USD",
        side=PbOrderSide.BUY,
        order_type=PbOrderType.MARKET,
        time_in_force=TimeInForce.GTC,
        quantity=Decimal("0.5"),
        price=None,
        ts_ns=ts,
        client_id="latency-gate-001",
    )

    eligible_ns = paper_order.eligible_at_ns
    assert eligible_ns > ts, "eligible_at_ns must be strictly after submit ts due to latency"

    ctx_before = _make_market_ctx(ts_ns=ts)
    broker.process_matching_detailed(
        current_ts_ns=ts,
        market_by_symbol={"ETH/USD": ctx_before},
    )

    filled_before = [
        r for r in broker.execution_reports
        if r.status == PbOrderStatus.FULLY_FILLED
    ]
    assert len(filled_before) == 0, "Order must not fill before eligible_at_ns"


def test_latency_gate_order_fills_after_eligible():
    broker = _make_broker()
    ts = _now_ns()

    paper_order = broker.submit_order_detailed(
        symbol="ETH/USD",
        side=PbOrderSide.BUY,
        order_type=PbOrderType.MARKET,
        time_in_force=TimeInForce.GTC,
        quantity=Decimal("0.5"),
        price=None,
        ts_ns=ts,
        client_id="latency-gate-002",
    )

    eligible_ns = paper_order.eligible_at_ns

    ctx_after = _make_market_ctx(ts_ns=eligible_ns + 1)
    broker.process_matching_detailed(
        current_ts_ns=eligible_ns + 1,
        market_by_symbol={"ETH/USD": ctx_after},
    )

    filled = [
        r for r in broker.execution_reports
        if r.status == PbOrderStatus.FULLY_FILLED
    ]
    assert len(filled) >= 1, "Order must fill once current_ts_ns >= eligible_at_ns"


# ---------------------------------------------------------------------------
# Test 5 — OrderRouter returns OrderFill on successful paper fill
# ---------------------------------------------------------------------------

def test_order_router_returns_fill_for_market_buy():
    router = OrderRouter(paper_mode=True)
    ts = _now_ns()

    order = OrderRequest(
        symbol="ETH/USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.5"),
        strategy=SleeveType.SECTOR_ROTATION,
        confidence=0.9,
        exchange_ts_ns=ts,
        receive_ts_ns=ts,
    )

    fill = router.submit_order(order)

    assert fill is not None, "OrderRouter must return OrderFill for valid paper MARKET BUY"
    assert isinstance(fill, OrderFill)
    assert fill.quantity > Decimal("0")
    assert fill.price > Decimal("0")
    assert fill.symbol == "ETH/USD"


def test_order_router_paper_fill_preserves_passive_broker_id_mapping(tmp_path):
    telemetry_path = tmp_path / "paper_broker_id_mapping.db"
    store = TelemetryEventStore(str(telemetry_path))
    router = OrderRouter(paper_mode=True, telemetry_store=store)
    ts = _now_ns()

    order = OrderRequest(
        id="paper-client-order-001",
        symbol="ETH/USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.5"),
        strategy=SleeveType.SECTOR_ROTATION,
        confidence=0.9,
        decision_uuid="paper-broker-id-mapping-decision",
        exchange_ts_ns=ts,
        receive_ts_ns=ts,
    )

    fill = router.submit_order(order)

    assert fill is not None
    fill_events = store.get_events_by_type("fill", limit=10)
    assert fill_events

    payload = json.loads(fill_events[0]["payload_json"])
    context = payload["order_lifecycle_replay_context"]

    assert context["client_order_id"] == order.id
    assert context["order_id_namespace"] == "client_order_id"
    assert context["broker_order_id"] is not None
    assert context["broker_order_id"] != order.id
    assert context["venue_order_id"] == context["broker_order_id"]
    assert context["venue_fill_id"] == order.id
    assert context["is_terminal"] is True
    assert context["terminal_state"] == "filled"
    assert context["mapping_authoritative"] is False
    assert context["router_cache_authoritative"] is False
    assert context["exposure_reservation_authority"] is False
    assert context["exposure_reservation_mutated"] is False
    assert context["reservation_delta_authoritative"] is False
    assert context["reservation_candidate_authoritative"] is False


def test_order_router_returns_fill_for_market_sell():
    router = OrderRouter(paper_mode=True)
    ts = _now_ns()

    order = OrderRequest(
        symbol="ETH/USD",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.5"),
        strategy=SleeveType.SECTOR_ROTATION,
        confidence=0.9,
        exchange_ts_ns=ts,
        receive_ts_ns=ts,
    )

    fill = router.submit_order(order)

    assert fill is not None, "OrderRouter must return OrderFill for valid paper MARKET SELL"
    assert isinstance(fill, OrderFill)
    assert fill.quantity > Decimal("0")


# ---------------------------------------------------------------------------
# Test 6 — Pending/un-fillable orders return None from OrderRouter
# ---------------------------------------------------------------------------

def test_order_router_returns_none_for_unfillable_limit():
    router = OrderRouter(paper_mode=True)
    ts = _now_ns()

    order = OrderRequest(
        symbol="ETH/USD",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.5"),
        limit_price=Decimal("1.00"),   # far below simulated price of 3000
        strategy=SleeveType.SECTOR_ROTATION,
        confidence=0.9,
        exchange_ts_ns=ts,
        receive_ts_ns=ts,
    )

    fill = router.submit_order(order)

    assert fill is None, "OrderRouter must return None when LIMIT order cannot fill at current price"


# ---------------------------------------------------------------------------
# Test 7 — No Decimal/float regression in fill fields
# ---------------------------------------------------------------------------

def test_no_float_in_fill_fields_broker_level():
    broker = _make_broker()
    ts = _now_ns()

    paper_order = broker.submit_order_detailed(
        symbol="ETH/USD",
        side=PbOrderSide.BUY,
        order_type=PbOrderType.MARKET,
        time_in_force=TimeInForce.GTC,
        quantity=Decimal("0.5"),
        price=None,
        ts_ns=ts,
        client_id="decimal-check-001",
    )

    eligible_ns = paper_order.eligible_at_ns
    ctx = _make_market_ctx(ts_ns=eligible_ns + 1)

    broker.process_matching_detailed(
        current_ts_ns=eligible_ns + 1,
        market_by_symbol={"ETH/USD": ctx},
    )

    filled = [r for r in broker.execution_reports if r.status == PbOrderStatus.FULLY_FILLED]
    assert len(filled) >= 1

    report = filled[0]
    assert isinstance(report.filled_quantity, Decimal), (
        f"filled_quantity must be Decimal, got {type(report.filled_quantity)}"
    )
    assert isinstance(report.fill_price, Decimal), (
        f"fill_price must be Decimal, got {type(report.fill_price)}"
    )
    assert isinstance(report.fee, Decimal), (
        f"fee must be Decimal, got {type(report.fee)}"
    )


def test_no_float_in_fill_fields_router_level():
    router = OrderRouter(paper_mode=True)
    ts = _now_ns()

    order = OrderRequest(
        symbol="ETH/USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.5"),
        strategy=SleeveType.SECTOR_ROTATION,
        confidence=0.9,
        exchange_ts_ns=ts,
        receive_ts_ns=ts,
    )

    fill = router.submit_order(order)

    assert fill is not None
    assert isinstance(fill.quantity, Decimal), (
        f"fill.quantity must be Decimal, got {type(fill.quantity)}"
    )
    assert isinstance(fill.price, Decimal), (
        f"fill.price must be Decimal, got {type(fill.price)}"
    )
    assert isinstance(fill.fee, Decimal), (
        f"fill.fee must be Decimal, got {type(fill.fee)}"
    )
