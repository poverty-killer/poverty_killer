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
)
from app.execution.order_router import OrderRouter
from app.models import OrderRequest
from app.models.enums import OrderSide, OrderType, SleeveType


@dataclass(frozen=True)
class _Adapter:
    identity: BrokerAdapterIdentity


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

    broker, primary_exchange, adapter, adapter_id = main.resolve_execution_broker_gateway(_config())

    assert broker == "alpaca_paper"
    assert primary_exchange == "alpaca"
    assert adapter is not None
    assert adapter_id == "alpaca_paper_rest"


def test_kraken_feed_can_remain_separate_from_alpaca_execution(monkeypatch):
    monkeypatch.setenv(main.EXECUTION_BROKER_ENV_VAR, "alpaca_paper")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("APCA_API_KEY_ID", "paper-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "paper-secret")
    config = SimpleNamespace(broker_mode="paper", primary_feed_venue="kraken")

    broker, primary_exchange, adapter, _adapter_id = main.resolve_execution_broker_gateway(config)

    assert config.primary_feed_venue == "kraken"
    assert broker == "alpaca_paper"
    assert primary_exchange == "alpaca"
    assert adapter.identity.venue_id == "alpaca"


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
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    with pytest.raises(main.ExecutionBrokerSelectionError, match="credentials_missing"):
        main.resolve_execution_broker_gateway(_config())

    monkeypatch.setenv("APCA_API_BASE_URL", "https://api.alpaca.markets")
    monkeypatch.setenv("APCA_API_KEY_ID", "paper-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "paper-secret")
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
