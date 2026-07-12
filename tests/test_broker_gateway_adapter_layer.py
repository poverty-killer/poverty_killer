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
from app.execution.broker_gateway import BrokerAdapterIdentity, BrokerGatewayResponse, NormalizedBrokerStatus
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


class RecordingGatewayAdapter:
    def __init__(
        self,
        *,
        account_payload: dict | None = None,
        open_orders_payload: list | dict | None = None,
        account_error: BrokerGatewayError | None = None,
        open_orders_error: BrokerGatewayError | None = None,
    ) -> None:
        self._identity = BrokerAdapterIdentity(
            adapter_id="alpaca_paper_rest",
            venue_id="alpaca",
            portal_id="alpaca_paper",
            environment="paper",
            base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
            credential_status="configured",
            supported_methods=frozenset({"GET", "POST"}),
            supported_asset_classes=frozenset({"equity", "crypto"}),
            live_blocked=True,
        )
        self.account_payload = account_payload if account_payload is not None else {
            "id": "acct-test",
            "status": "ACTIVE",
            "cash": "100000",
            "buying_power": "100000",
        }
        self.open_orders_payload = [] if open_orders_payload is None else open_orders_payload
        self.account_error = account_error
        self.open_orders_error = open_orders_error
        self.submitted_orders: list[BrokerOrderSubmitRequest] = []
        self._counts = {"GET": 0, "POST": 0, "DELETE": 0}

    @property
    def identity(self) -> BrokerAdapterIdentity:
        return self._identity

    @property
    def request_counts(self) -> dict[str, int]:
        return dict(self._counts)

    def _response(
        self,
        *,
        method: str,
        endpoint_path: str,
        ok: bool = True,
        payload: object = None,
        broker_order_id: str | None = None,
        normalized_status: str = NormalizedBrokerStatus.UNKNOWN.value,
        reason_code: str | None = None,
    ) -> BrokerGatewayResponse:
        if method in self._counts:
            self._counts[method] += 1
        return BrokerGatewayResponse(
            adapter_id=self.identity.adapter_id,
            venue_id=self.identity.venue_id,
            portal_id=self.identity.portal_id,
            environment=self.identity.environment,
            request_method=method,
            endpoint_path=endpoint_path,
            ok=ok,
            mutation_occurred=method == "POST" and ok,
            live_blocked=self.identity.live_blocked,
            broker_order_id=broker_order_id,
            normalized_status=normalized_status,
            reason_code=reason_code,
            payload=payload,
        )

    def get_account(self) -> BrokerGatewayResponse:
        if self.account_error is not None:
            raise self.account_error
        return self._response(method="GET", endpoint_path="/v2/account", payload=self.account_payload)

    def get_positions(self) -> BrokerGatewayResponse:
        return self._response(method="GET", endpoint_path="/v2/positions", payload=[])

    def get_open_orders(self) -> BrokerGatewayResponse:
        if self.open_orders_error is not None:
            raise self.open_orders_error
        return self._response(method="GET", endpoint_path="/v2/orders", payload=self.open_orders_payload)

    def get_order_status(self, order_id: str) -> BrokerGatewayResponse:
        return self._response(
            method="GET",
            endpoint_path=f"/v2/orders/{order_id}",
            payload={"id": order_id, "status": "open", "symbol": "AAPL"},
            broker_order_id=order_id,
            normalized_status=NormalizedBrokerStatus.OPEN.value,
        )

    def submit_order(self, order: BrokerOrderSubmitRequest) -> BrokerGatewayResponse:
        self.submitted_orders.append(order)
        return self._response(
            method="POST",
            endpoint_path="/v2/orders",
            payload={
                "id": "broker-recorded-1",
                "client_order_id": order.client_order_id,
                "status": "open",
                "symbol": order.symbol,
            },
            broker_order_id="broker-recorded-1",
            normalized_status=NormalizedBrokerStatus.OPEN.value,
        )


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


def test_broker_connect_account_pin_uses_get_and_rejects_mismatch_without_post():
    matching_transport = StubTransport(
        {("GET", "/v2/account"): (200, {"id": "paper-account-045ded", "status": "ACTIVE"})}
    )
    matching = AlpacaPaperBrokerAdapter(_creds(), transport=matching_transport)

    assertion = matching.assert_expected_account_pin()

    assert assertion["status"] == "PASS"
    assert assertion["actual_suffix"] == "045ded"
    assert matching.request_counts == {"GET": 1, "POST": 0}

    mismatch_transport = StubTransport(
        {("GET", "/v2/account"): (200, {"id": "paper-account-104e2a", "status": "ACTIVE"})}
    )
    mismatch = AlpacaPaperBrokerAdapter(_creds(), transport=mismatch_transport)

    with pytest.raises(BrokerGatewayError, match="expected_suffix=045ded,actual_suffix=104e2a"):
        mismatch.assert_expected_account_pin()

    assert mismatch.account_pin_assertion["reason_code"] == "ALPACA_PAPER_ACCOUNT_PIN_MISMATCH"
    assert mismatch.request_counts == {"GET": 1, "POST": 0}
    assert all(call["method"] == "GET" for call in mismatch_transport.calls)


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


def test_order_router_gateway_buying_power_gate_exempts_sell_exit_when_cash_exhausted():
    adapter = RecordingGatewayAdapter(
        account_payload={
            "id": "acct-exhausted",
            "status": "ACTIVE",
            "cash": "-11",
            "buying_power": "0",
            "non_marginable_buying_power": "0",
        }
    )
    router = OrderRouter(primary_exchange="alpaca", paper_mode=True, broker_gateway_adapter=adapter)
    sell_order = _order(order_id="client-sell-exit", side=OrderSide.SELL, quantity=Decimal("1"), limit_price=Decimal("100"))

    fill = router.submit_order(sell_order)
    response = router.get_gateway_response(sell_order.id)
    accounting = router.get_oms_shutdown_accounting()

    assert fill is None
    assert response is not None
    assert response.ok is True
    assert response.broker_order_id == "broker-recorded-1"
    assert adapter.submitted_orders == [
        BrokerOrderSubmitRequest(
            symbol="AAPL",
            side="sell",
            order_type="limit",
            time_in_force="day",
            quantity=Decimal("1"),
            limit_price=Decimal("100"),
            client_order_id="client-sell-exit",
            asset_class="equity",
            metadata={
                "decision_uuid": "decision-client-sell-exit",
                "strategy": "sector_rotation",
                "execution_adapter": "alpaca_paper_rest",
                "portal_name": "alpaca_paper",
                "venue_id": "alpaca",
                "environment": "paper",
            },
        )
    ]
    assert accounting["buying_power_pre_post_gate_event_count"] == 0
    assert all(
        "BUYING_POWER" not in str(event.get("reason_code", ""))
        for event in accounting["broker_boundary_events"]
    )
    assert accounting["broker_boundary_events"][-1]["broker_post_attempted"] is True
    assert accounting["broker_boundary_events"][-1]["broker_post_authorized"] is True
    assert adapter.request_counts["POST"] == 1


def test_order_router_gateway_buying_power_gate_fails_closed_before_submit_for_unknown_buy_truth():
    scenarios = [
        (
            "account_read_error",
            RecordingGatewayAdapter(account_error=BrokerGatewayError("account_read_failed", message="read failed")),
            _order(order_id="client-account-read-error", quantity=Decimal("1"), limit_price=Decimal("100")),
            None,
            "BUYING_POWER_TRUTH_UNAVAILABLE_PRE_POST",
        ),
        (
            "missing_buying_power_basis",
            RecordingGatewayAdapter(account_payload={"id": "acct-missing", "status": "ACTIVE"}),
            _order(order_id="client-missing-basis", quantity=Decimal("1"), limit_price=Decimal("100")),
            None,
            "BUYING_POWER_TRUTH_UNAVAILABLE_PRE_POST",
        ),
        (
            "market_order_notional_unknown",
            RecordingGatewayAdapter(),
            _order(
                order_id="client-market-notional-unknown",
                order_type=OrderType.MARKET,
                limit_price=None,
            ),
            None,
            "BUYING_POWER_NOTIONAL_UNKNOWN_PRE_POST",
        ),
        (
            "zero_notional",
            RecordingGatewayAdapter(),
            _order(order_id="client-zero-notional", quantity=Decimal("1"), limit_price=Decimal("100")),
            BrokerOrderSubmitRequest(
                symbol="AAPL",
                side="buy",
                order_type="limit",
                time_in_force="day",
                quantity=Decimal("0"),
                limit_price=Decimal("100"),
                client_order_id="client-zero-notional",
                asset_class="equity",
            ),
            "BUYING_POWER_NOTIONAL_UNKNOWN_PRE_POST",
        ),
        (
            "account_not_active",
            RecordingGatewayAdapter(
                account_payload={
                    "id": "acct-inactive",
                    "status": "INACTIVE",
                    "cash": "100000",
                    "buying_power": "100000",
                }
            ),
            _order(order_id="client-inactive-account", quantity=Decimal("1"), limit_price=Decimal("100")),
            None,
            "ACCOUNT_NOT_ACTIVE_PRE_POST",
        ),
        (
            "open_order_read_error",
            RecordingGatewayAdapter(
                open_orders_error=BrokerGatewayError("open_orders_read_failed", message="open order read failed")
            ),
            _order(order_id="client-open-order-read-error", quantity=Decimal("1"), limit_price=Decimal("100")),
            None,
            "BUYING_POWER_TRUTH_UNAVAILABLE_PRE_POST",
        ),
    ]

    for name, adapter, order, request_override, expected_reason in scenarios:
        router = OrderRouter(primary_exchange="alpaca", paper_mode=True, broker_gateway_adapter=adapter)

        if request_override is None:
            router.submit_order(order)
            response = router.get_gateway_response(order.id)
        else:
            response = router._gateway_buying_power_pre_post_response(order, request_override)

        assert response is not None, name
        assert response.ok is False, name
        assert response.reason_code == expected_reason, name
        assert response.reconciliation_metadata["blocked_before_submit"] is True, name
        assert response.reconciliation_metadata["broker_post_attempted"] is False, name
        assert adapter.submitted_orders == [], name
        assert adapter.request_counts["POST"] == 0, name


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
