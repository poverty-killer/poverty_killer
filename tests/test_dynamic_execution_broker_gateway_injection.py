from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

import pytest

import main
from app.execution.broker_gateway import (
    BrokerAdapterIdentity,
    BrokerCredentialStatus,
    BrokerEnvironment,
    BrokerGatewayError,
)
from app.execution.order_router import OrderRouter
from app.models import OrderRequest
from app.models.enums import OrderSide, OrderType, SleeveType


@dataclass
class _Adapter:
    identity: BrokerAdapterIdentity
    actual_suffix: str = "045ded"
    pin_checks: int = 0
    post_calls: int = 0

    def assert_expected_account_pin(self) -> dict[str, object]:
        self.pin_checks += 1
        if self.actual_suffix != "045ded":
            raise BrokerGatewayError(
                "alpaca_paper_account_pin_mismatch",
                message=f"expected_suffix=045ded,actual_suffix={self.actual_suffix}",
            )
        return {
            "status": "PASS",
            "reason_code": "ALPACA_PAPER_ACCOUNT_PIN_OK",
            "expected_suffix": "045ded",
            "actual_suffix": self.actual_suffix,
            "broker_mutation_occurred": False,
        }


def _patch_pinned_adapter(monkeypatch, *, actual_suffix: str = "045ded") -> _Adapter:
    adapter = _Adapter(_identity(), actual_suffix=actual_suffix)
    monkeypatch.setattr(main.AlpacaPaperBrokerAdapter, "from_env", lambda: adapter)
    return adapter


def _identity(
    *,
    venue_id: str = "alpaca",
    environment: str = BrokerEnvironment.PAPER.value,
    credential_status: str = BrokerCredentialStatus.CONFIGURED.value,
    live_blocked: bool = True,
) -> BrokerAdapterIdentity:
    return BrokerAdapterIdentity(
        adapter_id="alpaca_paper_rest",
        venue_id=venue_id,
        portal_id="alpaca_paper",
        environment=environment,
        base_url="https://paper-api.alpaca.markets",
        credential_status=credential_status,
        supported_methods=frozenset({"GET", "POST"}),
        supported_asset_classes=frozenset({"equity", "etf", "crypto"}),
        live_blocked=live_blocked,
    )


def _config(broker_mode: str = "paper"):
    return SimpleNamespace(broker_mode=broker_mode)


def _order() -> OrderRequest:
    return OrderRequest(
        id="test-order-1",
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=OrderType.LIMIT,
        limit_price=Decimal("100"),
        strategy=SleeveType.SHADOW_FRONT,
        confidence=Decimal("0.7"),
        decision_uuid="decision-1",
        exchange_ts_ns=1,
        receive_ts_ns=1,
    )


def test_execution_broker_defaults_to_explicit_internal_paper(monkeypatch):
    monkeypatch.delenv(main.EXECUTION_BROKER_ENV_VAR, raising=False)

    broker = main.get_configured_execution_broker(_config())

    assert broker == "internal_paper"


def test_alpaca_paper_resolver_wires_gateway_adapter_from_configured_env(monkeypatch):
    monkeypatch.setenv(main.EXECUTION_BROKER_ENV_VAR, "alpaca_paper")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("APCA_API_KEY_ID", "paper-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "paper-secret")
    expected_adapter = _patch_pinned_adapter(monkeypatch)

    broker, primary_exchange, adapter, adapter_id = main.resolve_execution_broker_gateway(_config())

    assert broker == "alpaca_paper"
    assert primary_exchange == "alpaca"
    assert adapter is expected_adapter
    assert adapter_id == "alpaca_paper_rest"
    assert expected_adapter.pin_checks == 1


def test_kraken_feed_can_remain_separate_from_alpaca_execution(monkeypatch):
    monkeypatch.setenv(main.EXECUTION_BROKER_ENV_VAR, "alpaca_paper")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("APCA_API_KEY_ID", "paper-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "paper-secret")
    config = SimpleNamespace(broker_mode="paper", primary_feed_venue="kraken")
    _patch_pinned_adapter(monkeypatch)

    broker, primary_exchange, adapter, _adapter_id = main.resolve_execution_broker_gateway(config)

    assert config.primary_feed_venue == "kraken"
    assert broker == "alpaca_paper"
    assert primary_exchange == "alpaca"
    assert adapter.identity.venue_id == "alpaca"


def test_child_broker_connect_rejects_mismatched_account_pin_before_order_one(monkeypatch):
    monkeypatch.setenv(main.EXECUTION_BROKER_ENV_VAR, "alpaca_paper")
    adapter = _patch_pinned_adapter(monkeypatch, actual_suffix="104e2a")

    with pytest.raises(
        main.ExecutionBrokerSelectionError,
        match="alpaca_paper_account_pin_mismatch",
    ):
        main.resolve_execution_broker_gateway(_config())

    assert adapter.pin_checks == 1
    assert adapter.post_calls == 0


def test_external_paper_gateway_routes_without_internal_paper_fallback(monkeypatch):
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        execution_broker="alpaca_paper",
        broker_gateway_adapter=_Adapter(_identity()),
    )
    calls: list[str] = []
    monkeypatch.setattr(router, "_submit_order_gateway", lambda order: calls.append("gateway"))
    monkeypatch.setattr(router, "_submit_order_paper", lambda order: calls.append("internal_paper"))

    router.submit_order(_order())

    assert calls == ["gateway"]
    assert router.get_ghost_status()["broker_gateway_route_available"] is True


def test_external_paper_request_without_adapter_fails_closed():
    with pytest.raises(ValueError, match="external_paper_broker_requires_broker_gateway_adapter"):
        OrderRouter(
            primary_exchange="alpaca",
            paper_mode=True,
            execution_broker="alpaca_paper",
            broker_gateway_adapter=None,
        )


def test_unsupported_or_invalid_external_broker_fails_closed(monkeypatch):
    monkeypatch.setenv(main.EXECUTION_BROKER_ENV_VAR, "future_adapter")
    with pytest.raises(main.ExecutionBrokerSelectionError, match="unsupported_execution_broker"):
        main.get_configured_execution_broker(_config())

    with pytest.raises(ValueError, match="broker_gateway_adapter_primary_exchange_mismatch"):
        OrderRouter(
            primary_exchange="kraken",
            paper_mode=True,
            execution_broker="alpaca_paper",
            broker_gateway_adapter=_Adapter(_identity(venue_id="alpaca")),
        )


def test_missing_credentials_and_live_endpoint_fail_closed(monkeypatch):
    monkeypatch.setenv(main.EXECUTION_BROKER_ENV_VAR, "alpaca_paper")
    monkeypatch.setattr(
        main.AlpacaPaperBrokerAdapter,
        "from_env",
        lambda: (_ for _ in ()).throw(BrokerGatewayError("credentials_missing")),
    )
    with pytest.raises(main.ExecutionBrokerSelectionError, match="credentials_missing"):
        main.resolve_execution_broker_gateway(_config())

    monkeypatch.setattr(
        main.AlpacaPaperBrokerAdapter,
        "from_env",
        lambda: (_ for _ in ()).throw(
            BrokerGatewayError(
                "live_or_nonpaper_endpoint_blocked",
                message="live_endpoint_blocked",
            )
        ),
    )
    with pytest.raises(main.ExecutionBrokerSelectionError, match="live_or_nonpaper_endpoint_blocked"):
        main.resolve_execution_broker_gateway(_config())


def test_internal_paper_remains_explicit_simulation_backend():
    router = OrderRouter(
        primary_exchange="kraken",
        paper_mode=True,
        execution_broker="internal_paper",
        broker_gateway_adapter=None,
    )

    status = router.get_ghost_status()

    assert status["execution_broker"] == "internal_paper"
    assert status["external_paper_broker_requested"] is False
    assert status["broker_gateway_adapter"] is None
