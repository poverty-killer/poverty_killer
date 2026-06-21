from __future__ import annotations

import inspect
import json
from decimal import Decimal
from urllib.parse import urlparse
from unittest.mock import MagicMock

from app.commander import Commander
from app.core.decision_compiler import DecisionCompiler
from app.execution.alpaca_paper_adapter import AlpacaPaperBrokerAdapter, AlpacaPaperCredentials
from app.execution.engine import ExecutionEngine, ExecutionSpineResult
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
from app.models.enums import SignalType, StrategyID, TruthStatus
from app.models.signals import StrategySignal


T0_NS = 1_777_948_800_000_000_000


class StubTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, *, method, url, headers, body=None, timeout=10.0):
        path = urlparse(url).path
        self.calls.append(
            {
                "method": method,
                "path": path,
                "headers": dict(headers),
                "body": json.loads(body.decode("utf-8")) if body else None,
                "timeout": timeout,
            }
        )
        if method == "GET" and path == "/v2/account":
            return 200, {"id": "acct-1", "status": "ACTIVE", "cash": "100000", "buying_power": "100000"}
        if method == "GET" and path == "/v2/orders":
            return 200, []
        return self.response


def _creds(base_url: str = "https://paper-api.alpaca.markets") -> AlpacaPaperCredentials:
    return AlpacaPaperCredentials(base_url=base_url, key_id="paper-key", secret_key="paper-secret")


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


def _truth_frame() -> TruthFrame:
    return TruthFrame(
        truth_frame_id="seam3-truth-frame",
        timestamp_ns=T0_NS,
        exchange_truth=ExchangeTruth(venue="alpaca", exchange_ts_ns=T0_NS),
        execution_truth=ExecutionTruth(last_reconciliation_ts_ns=T0_NS),
        portfolio_truth=PortfolioTruth(last_update_ts_ns=T0_NS),
        strategy_truth=StrategyTruth(last_update_ts_ns=T0_NS),
        risk_truth=RiskTruth(),
        status=TruthStatus.RECONCILED,
    )


def _vote(decision_uuid: str = "seam3-decision-uuid") -> StrategyVote:
    return StrategyVote(
        vote_id="seam3-vote",
        decision_uuid=decision_uuid,
        strategy_id=StrategyID.SECTOR_ROTATION,
        timestamp_ns=T0_NS,
        signal=SignalType.BUY,
        confidence=Decimal("0.90"),
        expected_move_bps=Decimal("50"),
        expected_duration_ns=60_000_000_000,
        risk_appetite=Decimal("0.40"),
        metadata={"source_signal_id": "seam3-signal"},
    )


def _pre_trade_guardrail(
    *,
    symbol: str = "AAPL",
    asset_class: str = "equity",
    verdict: str = "ALLOW",
    route_permitted: bool = True,
    reason_codes: tuple[str, ...] = ("PRE_TRADE_GUARDRAILS_ALLOW",),
):
    return {
        "verdict": verdict,
        "route_permitted": route_permitted,
        "mutation_permitted": route_permitted,
        "reason_codes": reason_codes,
        "symbol": symbol,
        "side": "buy",
        "order_type": "limit",
        "time_in_force": "DAY" if asset_class == "equity" else "GTC",
        "requested_notional": "15.00",
        "internal_max_notional": "20.00",
        "broker_min_notional": "1.00" if asset_class == "equity" else "10.00",
        "capability_identity": {
            "venue_id": "alpaca",
            "portal_name": "alpaca_paper",
            "environment": "paper",
            "asset_class": asset_class,
            "symbol": symbol,
            "execution_adapter": "alpaca_paper_rest",
        },
        "module_evidence": [],
    }


def _compiled_decision(*, symbol: str = "AAPL", decision_uuid: str = "seam3-decision-uuid"):
    asset_class = "crypto" if "/" in symbol else "equity"
    compiler = DecisionCompiler()
    return compiler.compile(
        truth_frame=_truth_frame(),
        strategy_votes=[_vote(decision_uuid)],
        additional_inputs={
            "order_intent": {
                "symbol": symbol,
                "normalized_symbol": symbol,
                "venue": "alpaca",
                "portal": "alpaca_paper",
                "environment": "paper",
                "asset_class": "equity",
                "side": "buy",
                "order_type": "limit",
                "time_in_force": "day",
                "requested_quantity": "0.10",
                "strategy": "sector_rotation",
                "paper_mode": True,
            },
            "capability_identity": {
                "venue_id": "alpaca",
                "portal_name": "alpaca_paper",
                "environment": "paper",
                "asset_class": "equity",
                "execution_adapter": "alpaca_paper_rest",
            },
            "order_constraint_verdict": "allowed",
            "pre_trade_guardrail_verdict": _pre_trade_guardrail(symbol=symbol, asset_class=asset_class),
        },
    )


def _signal(symbol: str = "AAPL", *, metadata: dict | None = None) -> StrategySignal:
    return StrategySignal(
        strategy="sector_rotation",
        symbol=symbol,
        side="buy",
        confidence=0.90,
        quantity=0.10,
        price=150.00,
        exchange_ts_ns=T0_NS,
        reason="seam3_execution_spine",
        metadata={
            "expected_move": "0.02",
            "asset_class": "equity",
            "venue_id": "alpaca",
            "portal_name": "alpaca_paper",
            "environment": "paper",
            "execution_adapter": "alpaca_paper_rest",
            "reconciliation_adapter": "alpaca_paper_rest_reconciliation",
            "capability_key": "alpaca_paper:equity:AAPL",
            "time_in_force": "day",
            "order_constraint_verdict": "allowed",
            "source_signal_id": "seam3-signal",
            **(metadata or {}),
        },
    )


def _engine(router: OrderRouter, *, size: Decimal = Decimal("0.10")) -> ExecutionEngine:
    engine = ExecutionEngine(
        commander=Commander(),
        risk_guard=_risk_guard(),
        order_router=router,
        masking_layer=_masking_layer(size),
        signal_ttl_ms=1000.0,
    )
    engine._state.is_running = True
    engine._state.last_regime = "neutral"
    return engine


def test_decision_compiler_creates_artifact_before_execution_routing():
    decision = _compiled_decision()

    assert decision.decision_uuid == "seam3-decision-uuid"
    assert decision.inputs["strategy_votes"] == ["seam3-vote"]
    assert decision.outputs["additional"]["order_intent"]["symbol"] == "AAPL"
    assert decision.outputs["additional"]["capability_identity"]["execution_adapter"] == "alpaca_paper_rest"


def test_full_spine_routes_open_alpaca_paper_gateway_response_without_fake_fill():
    transport = StubTransport(
        (
            200,
            {
                "id": "broker-open-seam3",
                "client_order_id": "sector_rotation_AAPL_1777948800000000000",
                "status": "open",
                "symbol": "AAPL",
            },
        )
    )
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport)
    router = OrderRouter(primary_exchange="alpaca", paper_mode=True, broker_gateway_adapter=adapter)
    router.update_market_mid("AAPL", 150.00, T0_NS)
    engine = _engine(router)
    decision = _compiled_decision()

    result = engine.execute_compiled_decision(
        decision,
        _signal(),
        current_price=Decimal("150.00"),
        is_attack=True,
    )

    assert isinstance(result, ExecutionSpineResult)
    assert result.decision_uuid == decision.decision_uuid
    assert result.normalized_status == "open"
    assert result.fill is None
    assert result.gateway_response is router.get_gateway_response(result.client_order_id)
    assert result.broker_order_id == "broker-open-seam3"
    assert result.route == "alpaca_paper_rest"
    assert result.client_order_id == "sector_rotation_AAPL_1777948800000000000"
    assert result.client_order_id in engine._state.pending_orders
    assert result.client_order_id not in router._paper_broker.open_orders
    post_call = next(call for call in transport.calls if call["method"] == "POST")
    assert post_call["path"] == "/v2/orders"
    assert post_call["body"]["type"] == "limit"
    assert post_call["body"]["time_in_force"] == "day"
    assert post_call["body"]["client_order_id"] == result.client_order_id

    order = engine._state.pending_orders[result.client_order_id]
    assert order.decision_uuid == decision.decision_uuid
    assert order.metadata["venue_id"] == "alpaca"
    assert order.metadata["portal_name"] == "alpaca_paper"
    assert order.metadata["environment"] == "paper"
    assert order.metadata["asset_class"] == "equity"
    assert order.metadata["execution_adapter"] == "alpaca_paper_rest"
    assert order.metadata["compiled_decision_artifact"]["decision_uuid"] == decision.decision_uuid


def test_full_spine_preserves_min_notional_rejection_without_fake_fill_or_pending_order():
    transport = StubTransport(
        (
            403,
            {"code": 40310000, "message": "cost basis must be >= minimal amount of order 10"},
        )
    )
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport)
    router = OrderRouter(primary_exchange="alpaca", paper_mode=True, broker_gateway_adapter=adapter)
    router.update_market_mid("BTC/USD", 77064.20, T0_NS)
    engine = _engine(router, size=Decimal("0.00006488"))
    decision = DecisionCompiler().compile(
        truth_frame=_truth_frame(),
        strategy_votes=[_vote("seam3-decision-uuid")],
        additional_inputs={
            "pre_trade_guardrail_verdict": _pre_trade_guardrail(
                symbol="BTC/USD",
                asset_class="crypto",
                verdict="BLOCK",
                route_permitted=False,
                reason_codes=("RISK_MAX_BELOW_BROKER_MIN",),
            )
        },
    )

    result = engine.execute_compiled_decision(
        decision,
        _signal(
            "BTC/USD",
            metadata={
                "asset_class": "crypto",
                "time_in_force": "gtc",
                "capability_key": "alpaca_paper:crypto:BTC/USD",
            },
        ),
        current_price=Decimal("77064.20"),
        is_attack=True,
    )

    assert result.normalized_status == "blocked"
    assert result.reason_code == "PRE_TRADE_GUARDRAIL_BLOCKED"
    assert "RISK_MAX_BELOW_BROKER_MIN" in result.pre_trade_guardrail_verdict["reason_codes"]
    assert result.fill is None
    assert result.broker_order_id is None
    assert result.client_order_id is None
    assert transport.calls == []


def test_full_spine_blocks_unsupported_sell_before_gateway_post():
    transport = StubTransport((200, {"id": "should-not-post", "status": "open"}))
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport)
    router = OrderRouter(primary_exchange="alpaca", paper_mode=True, broker_gateway_adapter=adapter)
    router.update_market_mid("AAPL", 150.00, T0_NS)
    engine = _engine(router)
    decision = _compiled_decision()
    signal = _signal().model_copy(update={"side": "sell"})

    result = engine.execute_compiled_decision(
        decision,
        signal,
        current_price=Decimal("150.00"),
        is_attack=True,
    )

    assert result.normalized_status == "blocked"
    assert result.reason_code == "PRE_TRADE_GUARDRAIL_SIGNAL_MISMATCH"
    assert result.fill is None
    assert result.gateway_response is None
    assert result.block_evidence["blocked_before_order_router"] is True
    assert "PRE_TRADE_GUARDRAIL_SIDE_MISMATCH" in result.block_evidence["reason_codes"]
    assert transport.calls == []
    assert result.client_order_id is None
    assert not hasattr(router, "replace_order")
    assert not hasattr(router, "rebalance")


def test_full_spine_simulated_paper_broker_route_stays_separate_from_gateway():
    router = OrderRouter(paper_mode=True)
    router.update_market_mid("ETH/USD", 2500.00, T0_NS)
    engine = _engine(router, size=Decimal("0.50"))
    decision = _compiled_decision(symbol="ETH/USD")

    result = engine.execute_compiled_decision(
        decision,
        _signal(
            "ETH/USD",
            metadata={
                "asset_class": "crypto",
                "execution_adapter": "paper_broker",
                "capability_key": "paper:crypto:ETH/USD",
            },
        ),
        current_price=Decimal("2500.00"),
        is_attack=False,
    )

    assert result.route == "paper_broker"
    assert result.normalized_status in {"filled", "pending"}
    assert router.get_gateway_response(result.client_order_id) is None
    assert result.client_order_id in router._order_status_cache


def test_live_endpoint_blocked_and_execution_engine_has_no_direct_raw_post():
    try:
        AlpacaPaperBrokerAdapter(_creds("https://api.alpaca.markets"), transport=StubTransport((200, {})))
    except Exception as exc:
        assert getattr(exc, "reason_code", None) == "live_or_nonpaper_endpoint_blocked"
    else:
        raise AssertionError("live Alpaca endpoint must be blocked")

    spine_source = inspect.getsource(ExecutionEngine.execute_compiled_decision)
    execute_source = inspect.getsource(ExecutionEngine._execute_signal)
    assert "urlopen" not in spine_source + execute_source
    assert "/v2/orders" not in spine_source + execute_source
    assert ".submit_order(" in execute_source
