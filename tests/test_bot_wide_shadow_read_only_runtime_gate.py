from __future__ import annotations

import json
from decimal import Decimal
from urllib.parse import urlparse
from unittest.mock import MagicMock

import pytest

from app.commander import Commander
from app.config import Config
from app.core.decision_compiler import DecisionCompiler
from app.execution.alpaca_paper_adapter import AlpacaPaperBrokerAdapter, AlpacaPaperCredentials
from app.execution.engine import ExecutionEngine
from app.execution.order_router import OrderRouter
from app.models.contracts import (
    ExchangeTruth,
    ExecutionTruth,
    PortfolioTruth,
    RiskTruth,
    StrategyTruth,
    StrategyVote,
    TruthFrame,
)
from app.models.enums import EventType, SignalType, StrategyID, TruthStatus
from app.models.signals import StrategySignal
from app.telemetry.event_store import TelemetryEventStore


T0_NS = 1_777_948_800_000_000_000


class StubTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, *, method, url, headers, body=None, timeout=10.0):
        self.calls.append(
            {
                "method": method,
                "path": urlparse(url).path,
                "body": json.loads(body.decode("utf-8")) if body else None,
                "timeout": timeout,
            }
        )
        return self.response


def _creds() -> AlpacaPaperCredentials:
    return AlpacaPaperCredentials(
        base_url="https://paper-api.alpaca.markets",
        key_id="paper-key",
        secret_key="paper-secret",
    )


def _risk_guard():
    risk_guard = MagicMock()
    risk_guard.can_trade.return_value = True
    risk_guard.is_vol_fuse_triggered.return_value = False
    risk_guard.register_recalibrate_callback = MagicMock()
    risk_guard.register_emergency_callback = MagicMock()
    risk_guard.register_zombie_callback = MagicMock()
    risk_guard.register_lag_callback = MagicMock()
    risk_guard.register_vol_fuse_callback = MagicMock()
    risk_guard.record_fees = MagicMock()
    return risk_guard


def _masking_layer(size: Decimal = Decimal("0.10")):
    masked = MagicMock()
    masked.masked_size = size
    masking_layer = MagicMock()
    masking_layer.mask_order.return_value = masked
    return masking_layer


def _engine(
    router,
    *,
    shadow_read_only: bool,
    telemetry_store: TelemetryEventStore | None = None,
) -> ExecutionEngine:
    engine = ExecutionEngine(
        commander=Commander(),
        risk_guard=_risk_guard(),
        order_router=router,
        masking_layer=_masking_layer(),
        signal_ttl_ms=1000.0,
        telemetry_store=telemetry_store,
        shadow_read_only=shadow_read_only,
    )
    engine._state.is_running = True
    engine._state.last_regime = "neutral"
    return engine


def _truth_frame() -> TruthFrame:
    return TruthFrame(
        truth_frame_id="shadow-read-only-truth-frame",
        timestamp_ns=T0_NS,
        exchange_truth=ExchangeTruth(venue="alpaca", exchange_ts_ns=T0_NS),
        execution_truth=ExecutionTruth(last_reconciliation_ts_ns=T0_NS),
        portfolio_truth=PortfolioTruth(last_update_ts_ns=T0_NS),
        strategy_truth=StrategyTruth(last_update_ts_ns=T0_NS),
        risk_truth=RiskTruth(),
        status=TruthStatus.RECONCILED,
    )


def _vote(decision_uuid: str = "shadow-read-only-decision") -> StrategyVote:
    return StrategyVote(
        vote_id="shadow-read-only-vote",
        decision_uuid=decision_uuid,
        strategy_id=StrategyID.SECTOR_ROTATION,
        timestamp_ns=T0_NS,
        signal=SignalType.BUY,
        confidence=Decimal("0.90"),
        expected_move_bps=Decimal("50"),
        expected_duration_ns=60_000_000_000,
        risk_appetite=Decimal("0.40"),
        metadata={"source_signal_id": "shadow-read-only-signal"},
    )


def _guardrail(*, route_permitted: bool = True) -> dict:
    reason_codes = (
        ("PRE_TRADE_GUARDRAILS_ALLOW",)
        if route_permitted
        else ("QUOTE_SESSION_TRUTH_MISSING",)
    )
    return {
        "verdict": "ALLOW" if route_permitted else "BLOCK",
        "route_permitted": route_permitted,
        "mutation_permitted": route_permitted,
        "reason_codes": reason_codes,
        "symbol": "AAPL",
        "asset_class": "equity",
        "side": "buy",
        "order_type": "limit",
        "time_in_force": "DAY",
        "requested_notional": "15.00",
        "internal_max_notional": "20.00",
        "broker_min_notional": "1.00",
        "capability_identity": {
            "venue_id": "alpaca",
            "portal_name": "alpaca_paper",
            "environment": "paper",
            "asset_class": "equity",
            "symbol": "AAPL",
            "execution_adapter": "alpaca_paper_rest",
        },
        "module_evidence": [],
    }


def _decision(*, guardrail: dict | None = None):
    additional_inputs = {}
    if guardrail is not None:
        additional_inputs["pre_trade_guardrail_verdict"] = guardrail
    return DecisionCompiler().compile(
        truth_frame=_truth_frame(),
        strategy_votes=[_vote()],
        additional_inputs=additional_inputs,
    )


def _signal(*, metadata: dict | None = None) -> StrategySignal:
    return StrategySignal(
        strategy="sector_rotation",
        symbol="AAPL",
        side="buy",
        confidence=0.90,
        quantity=0.10,
        price=150.00,
        exchange_ts_ns=T0_NS,
        reason="shadow_read_only_runtime_gate",
        metadata={
            "expected_move": "0.02",
            "asset_class": "equity",
            "venue_id": "alpaca",
            "portal_name": "alpaca_paper",
            "environment": "paper",
            "execution_adapter": "alpaca_paper_rest",
            "time_in_force": "day",
            **(metadata or {}),
        },
    )


def test_shadow_read_only_allows_decision_and_guardrail_but_blocks_gateway_post(tmp_path):
    telemetry = TelemetryEventStore(str(tmp_path / "telemetry.db"))
    transport = StubTransport((200, {"id": "must-not-post", "status": "open"}))
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport)
    router = OrderRouter(primary_exchange="alpaca", paper_mode=True, broker_gateway_adapter=adapter)
    router.update_market_mid("AAPL", 150.00, T0_NS)
    engine = _engine(router, shadow_read_only=True, telemetry_store=telemetry)
    decision = _decision(guardrail=_guardrail(route_permitted=True))

    result = engine.execute_compiled_decision(
        decision,
        _signal(),
        current_price=Decimal("150.00"),
        is_attack=True,
    )

    assert result.normalized_status == "blocked"
    assert result.reason_code == "SHADOW_READ_ONLY_BLOCKED_BROKER_MUTATION"
    assert result.decision_artifact["decision_uuid"] == decision.decision_uuid
    assert result.pre_trade_guardrail_verdict["route_permitted"] is True
    assert result.fill is None
    assert result.client_order_id is None
    assert result.broker_order_id is None
    assert transport.calls == []
    assert engine.get_shadow_broker_mutation_counts() == {
        "POST": 0,
        "PATCH": 0,
        "DELETE": 0,
        "cancel": 0,
        "replace": 0,
        "sell": 0,
        "rebalance": 0,
    }

    shadow_events = engine.get_shadow_read_only_events()
    assert len(shadow_events) == 1
    assert shadow_events[0]["reason"] == "SHADOW_READ_ONLY_BLOCKED_BROKER_MUTATION"
    assert shadow_events[0]["broker_post_patch_delete_count"] == 0
    assert shadow_events[0]["confirmation"]["order_router_submit_order_reached"] is False

    stored = telemetry.get_events_by_type(EventType.AUDIT_EVENT.value)
    assert len(stored) == 1
    payload = json.loads(stored[0]["payload_json"])
    assert payload["reason"] == "SHADOW_READ_ONLY_BLOCKED_BROKER_MUTATION"
    assert payload["broker_mutation_counts"]["POST"] == 0


def test_shadow_read_only_blocks_direct_submit_signal_before_order_router():
    router = MagicMock()
    router.get_mid_price.return_value = Decimal("150.00")
    engine = _engine(router, shadow_read_only=True)

    admitted = engine.submit_signal(
        _signal(metadata={"pre_trade_guardrail_verdict": _guardrail(route_permitted=True)}),
        current_price=Decimal("150.00"),
        is_attack=True,
    )

    assert admitted is False
    assert engine.get_status()["execution_queue_size"] == 0
    router.submit_order.assert_not_called()
    assert engine.get_shadow_read_only_events()[0]["reason"] == "SHADOW_READ_ONLY_BLOCKED_BROKER_MUTATION"


def test_normal_paper_mode_still_posts_to_alpaca_paper_gateway_when_shadow_disabled():
    transport = StubTransport(
        (
            200,
            {
                "id": "broker-open-shadow-control",
                "client_order_id": "sector_rotation_AAPL_1777948800000000000",
                "status": "open",
                "symbol": "AAPL",
            },
        )
    )
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport)
    router = OrderRouter(primary_exchange="alpaca", paper_mode=True, broker_gateway_adapter=adapter)
    router.update_market_mid("AAPL", 150.00, T0_NS)
    engine = _engine(router, shadow_read_only=False)

    result = engine.execute_compiled_decision(
        _decision(guardrail=_guardrail(route_permitted=True)),
        _signal(),
        current_price=Decimal("150.00"),
        is_attack=True,
    )

    assert result.normalized_status == "open"
    assert result.broker_order_id == "broker-open-shadow-control"
    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["path"] == "/v2/orders"
    assert engine.get_shadow_read_only_events() == ()


def test_shadow_read_only_never_authorizes_live_mode():
    with pytest.raises(ValueError, match="shadow_read_only requires broker_mode='paper'"):
        Config(broker_mode="live", shadow_read_only=True)


def test_missing_guardrail_truth_fails_closed_before_shadow_would_submit():
    transport = StubTransport((200, {"id": "must-not-post", "status": "open"}))
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport)
    router = OrderRouter(primary_exchange="alpaca", paper_mode=True, broker_gateway_adapter=adapter)
    router.update_market_mid("AAPL", 150.00, T0_NS)
    engine = _engine(router, shadow_read_only=True)

    result = engine.execute_compiled_decision(
        _decision(guardrail=None),
        _signal(),
        current_price=Decimal("150.00"),
        is_attack=True,
    )

    assert result.normalized_status == "blocked"
    assert result.reason_code == "PRE_TRADE_GUARDRAIL_MISSING"
    assert transport.calls == []
    assert engine.get_shadow_read_only_events() == ()
