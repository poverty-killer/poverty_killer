from __future__ import annotations

from decimal import Decimal

import pytest

from app.execution.alpaca_paper_adapter import (
    EXPECTED_ALPACA_PAPER_BASE_URL,
    FORBIDDEN_ALPACA_LIVE_BASE_URL,
    AlpacaPaperBrokerAdapter,
    AlpacaPaperCredentials,
)
from app.execution.broker_gateway import BrokerGatewayAdapter, BrokerGatewayError, BrokerOrderSubmitRequest
from app.execution.order_router import OrderRouter
from app.execution.paper_broker import PaperBroker
from app.models import OrderRequest
from app.models.enums import OrderSide, OrderType, SleeveType
from app.market.capability_registry import build_default_capability_registry
from app.market.venue_capabilities import PortalSelectionRequest
from app.utils.time_utils import now_ns


class StubTransport:
    def __init__(self, responses: dict[tuple[str, str], tuple[int, object]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[dict[str, object]] = []

    def request(self, *, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body, "timeout": timeout})
        path = url.removeprefix(EXPECTED_ALPACA_PAPER_BASE_URL).split("?", 1)[0]
        if (method, path) not in self.responses and method == "GET" and path == "/v2/account":
            return 200, {"id": "acct-1", "status": "ACTIVE", "cash": "100000", "buying_power": "100000"}
        if (method, path) not in self.responses and method == "GET" and path == "/v2/orders":
            return 200, []
        return self.responses.get((method, path), (200, {}))


def _creds(**overrides: str) -> AlpacaPaperCredentials:
    values = {
        "base_url": EXPECTED_ALPACA_PAPER_BASE_URL,
        "key_id": "key-secret-not-returned",
        "secret_key": "secret-not-returned",
    }
    values.update(overrides)
    return AlpacaPaperCredentials(**values)


def _order(
    *,
    order_id: str = "client-1",
    symbol: str = "AAPL",
    side: OrderSide = OrderSide.BUY,
    order_type: OrderType = OrderType.LIMIT,
    quantity: Decimal = Decimal("0.01"),
    limit_price: Decimal = Decimal("100"),
    metadata: dict | None = None,
) -> OrderRequest:
    ts_ns = now_ns()
    return OrderRequest(
        id=order_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        limit_price=limit_price,
        strategy=SleeveType.SECTOR_ROTATION,
        confidence=0.9,
        decision_uuid=f"decision-{order_id}",
        exchange_ts_ns=ts_ns,
        receive_ts_ns=ts_ns,
        metadata=metadata or {
            "venue_id": "alpaca",
            "portal_name": "alpaca_paper",
            "environment": "paper",
            "asset_class": "equity",
            "execution_adapter": "alpaca_paper_rest",
            "time_in_force": "day",
        },
    )


def test_broker_gateway_contract_is_platform_agnostic():
    annotations = getattr(BrokerGatewayAdapter, "__annotations__", {})

    assert "Alpaca" not in repr(BrokerGatewayAdapter)
    assert "alpaca" not in repr(annotations).lower()
    assert callable(getattr(BrokerGatewayAdapter, "get_account"))
    assert callable(getattr(BrokerGatewayAdapter, "get_positions"))
    assert callable(getattr(BrokerGatewayAdapter, "get_open_orders"))
    assert callable(getattr(BrokerGatewayAdapter, "get_order_status"))
    assert callable(getattr(BrokerGatewayAdapter, "submit_order"))


def test_alpaca_paper_adapter_validates_exact_paper_endpoint_and_blocks_live():
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=StubTransport())

    assert adapter.identity.base_url == EXPECTED_ALPACA_PAPER_BASE_URL
    assert adapter.identity.environment == "paper"
    assert adapter.identity.live_blocked is True

    with pytest.raises(BrokerGatewayError) as exc:
        AlpacaPaperBrokerAdapter(_creds(base_url=FORBIDDEN_ALPACA_LIVE_BASE_URL), transport=StubTransport())

    assert exc.value.reason_code == "live_or_nonpaper_endpoint_blocked"


def test_credentials_missing_fail_closed_without_secret_leakage():
    with pytest.raises(BrokerGatewayError) as exc:
        AlpacaPaperBrokerAdapter(
            AlpacaPaperCredentials(base_url=EXPECTED_ALPACA_PAPER_BASE_URL, key_id="", secret_key="top-secret"),
            transport=StubTransport(),
        )

    rendered = str(exc.value)
    assert exc.value.reason_code == "credentials_missing"
    assert "APCA_API_KEY_ID" in rendered
    assert "top-secret" not in rendered


def test_read_only_methods_exist_and_normalize_stubbed_responses():
    transport = StubTransport(
        {
            ("GET", "/v2/account"): (200, {"id": "acct-1", "status": "ACTIVE", "cash": "100"}),
            ("GET", "/v2/positions"): (200, [{"symbol": "AAPL", "qty": "1"}]),
            ("GET", "/v2/orders"): (200, [{"id": "order-1", "status": "open"}]),
            ("GET", "/v2/orders/order-1"): (200, {"id": "order-1", "client_order_id": "client-1", "status": "filled"}),
        }
    )
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport)

    account = adapter.get_account()
    positions = adapter.get_positions()
    open_orders = adapter.get_open_orders()
    status = adapter.get_order_status("order-1")

    assert account.ok is True
    assert account.payload["status"] == "ACTIVE"
    assert positions.payload[0]["symbol"] == "AAPL"
    assert open_orders.endpoint_path == "/v2/orders"
    assert status.broker_order_id == "order-1"
    assert status.normalized_status == "filled"
    assert adapter.request_counts == {"GET": 4, "POST": 0}
    assert all(call["method"] == "GET" for call in transport.calls)


def test_submit_method_shape_normalizes_stubbed_buy_limit_ack_without_auto_execution():
    transport = StubTransport(
        {
            ("POST", "/v2/orders"): (
                200,
                {
                    "id": "broker-1",
                    "client_order_id": "client-1",
                    "status": "accepted",
                    "symbol": "AAPL",
                },
            )
        }
    )
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport)

    assert adapter.request_counts == {"GET": 0, "POST": 0}
    response = adapter.submit_order(
        BrokerOrderSubmitRequest(
            symbol="AAPL",
            side="buy",
            order_type="limit",
            time_in_force="day",
            quantity=Decimal("0.01"),
            limit_price=Decimal("100"),
            client_order_id="client-1",
            asset_class="equity",
        )
    )

    assert response.ok is True
    assert response.mutation_occurred is True
    assert response.broker_order_id == "broker-1"
    assert response.client_order_id == "client-1"
    assert response.normalized_status == "accepted"
    assert adapter.request_counts == {"GET": 0, "POST": 1}


def test_invalid_order_shape_and_unsupported_methods_fail_closed():
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=StubTransport())

    with pytest.raises(BrokerGatewayError) as market_exc:
        adapter.submit_order(
            BrokerOrderSubmitRequest(
                symbol="AAPL",
                side="buy",
                order_type="market",
                time_in_force="day",
                quantity=Decimal("1"),
                client_order_id="client-1",
            )
        )
    with pytest.raises(BrokerGatewayError) as patch_exc:
        adapter.request_unsupported("PATCH", "/v2/orders/order-1")
    with pytest.raises(BrokerGatewayError) as delete_exc:
        adapter.request_unsupported("DELETE", "/v2/account")

    assert market_exc.value.reason_code == "invalid_order_request"
    assert patch_exc.value.reason_code == "unsupported_method"
    assert delete_exc.value.reason_code == "unsupported_delete_path"


def test_broker_rejection_normalizes_without_fake_fill():
    transport = StubTransport(
        {
            ("POST", "/v2/orders"): (
                403,
                {"code": 40310000, "message": "cost basis must be >= minimal amount of order 10"},
            )
        }
    )
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport)
    response = adapter.submit_order(
        BrokerOrderSubmitRequest(
            symbol="BTC/USD",
            side="buy",
            order_type="limit",
            time_in_force="gtc",
            quantity=Decimal("0.00006488"),
            limit_price=Decimal("77064.2"),
            client_order_id="client-btc-1",
            asset_class="crypto",
        )
    )

    assert response.ok is False
    assert response.mutation_occurred is False
    assert response.normalized_status == "rejected"
    assert response.reason_code == "MIN_NOTIONAL_NOT_MET"
    assert response.broker_order_id is None
    assert "fake" not in repr(response).lower()


def test_order_router_routes_alpaca_paper_order_to_gateway_adapter_with_stub_transport():
    transport = StubTransport(
        {
            ("POST", "/v2/orders"): (
                200,
                {
                    "id": "broker-open-1",
                    "client_order_id": "client-open-1",
                    "status": "open",
                    "symbol": "AAPL",
                },
            )
        }
    )
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport)
    router = OrderRouter(primary_exchange="alpaca", paper_mode=True, broker_gateway_adapter=adapter)
    order = _order(order_id="client-open-1", quantity=Decimal("1"))

    fill = router.submit_order(order)
    response = router.get_gateway_response(order.id)

    assert fill is None
    assert response is not None
    assert response.ok is True
    assert response.normalized_status == "open"
    assert response.broker_order_id == "broker-open-1"
    assert response.mutation_occurred is True
    assert router._pending_orders[order.id] == order
    assert router._paper_broker is not None
    assert order.id not in router._paper_broker.open_orders
    assert [call["method"] for call in transport.calls[:3]] == ["GET", "GET", "POST"]
    assert [call["method"] for call in transport.calls].count("POST") == 1
    accounting = router.get_oms_shutdown_accounting()
    assert accounting["buying_power_pre_post_gate_event_count"] == 1
    assert accounting["buying_power_pre_post_gate_events"][0]["blocked_before_submit"] is False


def test_order_router_gateway_rejection_flows_back_without_fake_fill():
    transport = StubTransport(
        {
            ("POST", "/v2/orders"): (
                403,
                {"code": 40310000, "message": "cost basis must be >= minimal amount of order 10"},
            )
        }
    )
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport)
    router = OrderRouter(primary_exchange="alpaca", paper_mode=True, broker_gateway_adapter=adapter)
    order = _order(
        order_id="client-btc-low-notional",
        symbol="BTC/USD",
        quantity=Decimal("0.00006488"),
        limit_price=Decimal("77064.2"),
        metadata={
            "venue_id": "alpaca",
            "portal_name": "alpaca_paper",
            "environment": "paper",
            "asset_class": "crypto",
            "execution_adapter": "alpaca_paper_rest",
            "time_in_force": "gtc",
        },
    )

    fill = router.submit_order(order)
    response = router.get_gateway_response(order.id)

    assert fill is None
    assert response is not None
    assert response.ok is False
    assert response.normalized_status == "rejected"
    assert response.reason_code == "MIN_NOTIONAL_NOT_MET_PRE_POST"
    assert response.mutation_occurred is False
    assert response.broker_order_id is None
    assert response.reconciliation_metadata["blocked_before_submit"] is True
    assert transport.calls == []
    assert order.id not in router._pending_orders


def test_order_router_gateway_blocks_unfunded_buy_before_broker_post():
    transport = StubTransport(
        {
            ("GET", "/v2/account"): (
                200,
                {
                    "id": "acct-1",
                    "status": "ACTIVE",
                    "cash": "50",
                    "buying_power": "50",
                    "non_marginable_buying_power": "50",
                },
            ),
            ("GET", "/v2/orders"): (200, []),
            ("POST", "/v2/orders"): (200, {"id": "should-not-post", "status": "open"}),
        }
    )
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport)
    router = OrderRouter(primary_exchange="alpaca", paper_mode=True, broker_gateway_adapter=adapter)
    order = _order(order_id="client-unfunded", quantity=Decimal("1"), limit_price=Decimal("100"))

    fill = router.submit_order(order)
    response = router.get_gateway_response(order.id)

    assert fill is None
    assert response is not None
    assert response.ok is False
    assert response.reason_code == "BUYING_POWER_INSUFFICIENT_PRE_POST"
    assert response.reconciliation_metadata["blocked_before_submit"] is True
    assert response.reconciliation_metadata["available_after_open_buy_reservations"] == "50"
    assert [call["method"] for call in transport.calls] == ["GET", "GET"]
    accounting = router.get_oms_shutdown_accounting()
    boundary = accounting["broker_boundary_events"][-1]
    assert boundary["broker_post_attempted"] is False
    assert boundary["broker_post_authorized"] is False
    assert boundary["broker_boundary_result"] == "BROKER_POST_BLOCKED_BEFORE_SUBMIT"
    assert accounting["mutation_method_counts"]["POST"] == 0


def test_order_router_gateway_subtracts_open_buy_reservations_before_post():
    transport = StubTransport(
        {
            ("GET", "/v2/account"): (200, {"id": "acct-1", "status": "ACTIVE", "cash": "125", "buying_power": "125"}),
            ("GET", "/v2/orders"): (
                200,
                [
                    {"id": "reserved-buy", "side": "buy", "status": "open", "qty": "0.50", "limit_price": "100"},
                    {"id": "sell-exit", "side": "sell", "status": "open", "qty": "0.10", "limit_price": "100"},
                ],
            ),
            ("POST", "/v2/orders"): (200, {"id": "should-not-post", "status": "open"}),
        }
    )
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport)
    router = OrderRouter(primary_exchange="alpaca", paper_mode=True, broker_gateway_adapter=adapter)
    order = _order(order_id="client-reserved", quantity=Decimal("1"), limit_price=Decimal("100"))

    router.submit_order(order)
    response = router.get_gateway_response(order.id)

    assert response is not None
    assert response.reason_code == "BUYING_POWER_INSUFFICIENT_PRE_POST"
    assert response.reconciliation_metadata["reserved_open_buy_notional"] == "50.00"
    assert response.reconciliation_metadata["available_after_open_buy_reservations"] == "75.00"
    assert [call["method"] for call in transport.calls] == ["GET", "GET"]


def test_order_router_gateway_blocks_sell_cancel_replace_without_gateway_mutation():
    transport = StubTransport()
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport)
    router = OrderRouter(primary_exchange="alpaca", paper_mode=True, broker_gateway_adapter=adapter)
    sell_order = _order(order_id="client-sell-blocked", side=OrderSide.SELL)

    fill = router.submit_order(sell_order)
    response = router.get_gateway_response(sell_order.id)

    assert fill is None
    assert response is not None
    assert response.ok is False
    assert response.reason_code == "invalid_order_request"
    assert response.reconciliation_metadata["blocked_before_submit"] is True
    assert transport.calls == []
    assert router.cancel_order(sell_order.id) is False
    assert not hasattr(router, "replace_order")
    assert not hasattr(router, "rebalance")


def test_paper_broker_boundary_remains_simulated_and_separate_from_external_adapter():
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=StubTransport())

    assert PaperBroker is not AlpacaPaperBrokerAdapter
    assert adapter.identity.adapter_id == "alpaca_paper_rest"
    assert PaperBroker.__module__ == "app.execution.paper_broker"


def test_simulated_paper_broker_path_still_works_without_gateway():
    router = OrderRouter(paper_mode=True)
    order = _order(order_id="paper-client-1", symbol="ETH/USD", quantity=Decimal("1"), limit_price=Decimal("3000"))

    router.submit_order(order)

    assert router.get_gateway_response(order.id) is None
    assert router._paper_broker is not None
    assert order.id in router._order_status_cache


def test_capability_registry_identifies_alpaca_paper_adapter_identity_without_strategy_hardcode():
    registry = build_default_capability_registry()
    result = registry.resolve(
        PortalSelectionRequest(
            symbol="AAPL",
            asset_class="equity",
            policy_mode="explicit_preferred_venue",
            preferred_venue="alpaca_paper",
        )
    )

    assert result.ready is True
    assert result.selected is not None
    assert result.selected.execution_adapter == "alpaca_paper_rest"
    assert result.selected.reconciliation_adapter == "alpaca_paper_rest_reconciliation"
