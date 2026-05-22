from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlparse
from unittest.mock import MagicMock

from app.commander import Commander
from app.core.decision_compiler import DecisionCompiler
from app.brain.data_validator import DataContinuityValidator
from app.execution.alpaca_paper_adapter import AlpacaPaperBrokerAdapter, AlpacaPaperCredentials
from app.execution.engine import ExecutionEngine
from app.execution.order_router import OrderRouter
from app.market.capability_registry import build_default_capability_registry
from app.market.venue_capabilities import (
    CapabilityAwareCandidate,
    PortalEnvironment,
    PortalPolicyMode,
    PortalSelectionRequest,
    classify_quote_session,
)
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
from app.risk.pre_trade_guardrails import (
    BLOCK,
    PreTradeGuardrailRequest,
    evaluate_pre_trade_guardrails,
)
from app.utils.time_utils import now_ns


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
            }
        )
        return self.response


def _cap(symbol: str, *, asset_class: str, order_type: str = "limit", tif: str | None = None):
    registry = build_default_capability_registry()
    result = registry.resolve(
        PortalSelectionRequest(
            symbol=symbol,
            asset_class=asset_class,
            environment=PortalEnvironment.PAPER.value,
            order_type=order_type,
            time_in_force=tif,
            policy_mode=PortalPolicyMode.EXPLICIT_PREFERRED_VENUE.value,
            preferred_venue="alpaca_paper",
        )
    )
    return result.selected, result


def _quote(capability, *, quote_present=True, quote_fresh=True, spread_bps=Decimal("10"), market_open=True):
    candidate = CapabilityAwareCandidate.from_capability(capability, tradable=True)
    return classify_quote_session(
        candidate,
        market_session_open=market_open,
        quote_present=quote_present,
        quote_fresh=quote_fresh,
        spread_bps=spread_bps,
    )


def _verdict(
    *,
    symbol: str = "BTC/USD",
    asset_class: str = "crypto",
    qty: Decimal = Decimal("0.00006488"),
    price: Decimal = Decimal("77064.20"),
    tif: str = "GTC",
    internal_max: Decimal | None = Decimal("5.00"),
    quote_kwargs: dict | None = None,
    existing_positions=(),
    open_orders=(),
    reservations=(),
):
    capability, portal_result = _cap(symbol, asset_class=asset_class, tif=tif)
    quote_options = {"market_open": None if asset_class == "crypto" else True}
    quote_options.update(quote_kwargs or {})
    quote = (
        _quote(capability, **quote_options)
        if capability is not None
        else None
    )
    return evaluate_pre_trade_guardrails(
        PreTradeGuardrailRequest(
            symbol=symbol,
            side="buy",
            order_type="limit",
            time_in_force=tif,
            quantity=qty,
            limit_price=price,
            current_price=price,
            internal_max_notional=internal_max,
            capability=capability,
            portal_selection_result=portal_result,
            quote_classification=quote,
            existing_positions=existing_positions,
            open_orders=open_orders,
            reservations=reservations,
        )
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


def _masking_layer(size: Decimal):
    masking_layer = MagicMock()
    masking_layer.mask_order.return_value = SimpleNamespace(masked_size=size)
    return masking_layer


def _truth_frame() -> TruthFrame:
    return TruthFrame(
        truth_frame_id="seam4-truth-frame",
        timestamp_ns=T0_NS,
        exchange_truth=ExchangeTruth(venue="alpaca", exchange_ts_ns=T0_NS),
        execution_truth=ExecutionTruth(last_reconciliation_ts_ns=T0_NS),
        portfolio_truth=PortfolioTruth(last_update_ts_ns=T0_NS),
        strategy_truth=StrategyTruth(last_update_ts_ns=T0_NS),
        risk_truth=RiskTruth(),
        status=TruthStatus.RECONCILED,
    )


def _decision(pre_trade_guardrail_verdict: dict):
    return DecisionCompiler().compile(
        truth_frame=_truth_frame(),
        strategy_votes=[
            StrategyVote(
                vote_id="seam4-vote",
                decision_uuid="seam4-decision",
                strategy_id=StrategyID.SECTOR_ROTATION,
                timestamp_ns=T0_NS,
                signal=SignalType.BUY,
                confidence=Decimal("0.90"),
                expected_move_bps=Decimal("50"),
                expected_duration_ns=60_000_000_000,
                risk_appetite=Decimal("0.40"),
            )
        ],
        additional_inputs={"pre_trade_guardrail_verdict": pre_trade_guardrail_verdict},
    )


def _signal(symbol: str, qty: Decimal, metadata: dict):
    return StrategySignal(
        strategy="sector_rotation",
        symbol=symbol,
        side="buy",
        confidence=0.90,
        quantity=float(qty),
        price=100.0,
        exchange_ts_ns=T0_NS,
        reason="seam4_guardrail_test",
        metadata={"expected_move": "0.02", **metadata},
    )


def _engine(router: OrderRouter, *, size: Decimal):
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


def _ns_datetime(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc)


def test_alpaca_paper_crypto_internal_five_dollar_cap_blocks_before_broker_minimum():
    verdict = _verdict()

    assert verdict.verdict == BLOCK
    assert verdict.route_permitted is False
    assert "RISK_MAX_BELOW_BROKER_MIN" in verdict.reason_codes
    assert verdict.broker_min_notional == Decimal("10.00")
    assert any(item.module == "sizing/risk cap" for item in verdict.module_evidence)


def test_internal_risk_cap_blocks_requested_notional_above_max():
    verdict = _verdict(
        symbol="AAPL",
        asset_class="equity",
        qty=Decimal("0.10"),
        price=Decimal("150"),
        tif="DAY",
        internal_max=Decimal("5.00"),
    )

    assert verdict.verdict == BLOCK
    assert "REQUESTED_NOTIONAL_ABOVE_INTERNAL_MAX" in verdict.reason_codes


def test_alpaca_paper_crypto_day_tif_is_not_allowed_but_gtc_and_ioc_are_allowed():
    day = _verdict(tif="DAY", qty=Decimal("0.0002"), internal_max=Decimal("20.00"))
    gtc = _verdict(tif="GTC", qty=Decimal("0.0002"), internal_max=Decimal("20.00"))
    ioc = _verdict(tif="IOC", qty=Decimal("0.0002"), internal_max=Decimal("20.00"))

    assert "TIME_IN_FORCE_UNSUPPORTED" in day.reason_codes
    assert gtc.route_permitted is True
    assert ioc.route_permitted is True


def test_alpaca_paper_equity_etf_limit_day_is_allowed_with_fresh_quote():
    equity = _verdict(
        symbol="AAPL",
        asset_class="equity",
        qty=Decimal("0.10"),
        price=Decimal("150"),
        tif="DAY",
        internal_max=Decimal("20.00"),
    )
    etf = _verdict(
        symbol="SPY",
        asset_class="etf",
        qty=Decimal("0.10"),
        price=Decimal("500"),
        tif="DAY",
        internal_max=Decimal("60.00"),
    )

    assert equity.route_permitted is True
    assert etf.route_permitted is True


def test_quote_session_and_market_data_blocking_reasons_are_preserved():
    missing = _verdict(quote_kwargs={"quote_present": False})
    stale = _verdict(quote_kwargs={"quote_fresh": False})
    wide = _verdict(quote_kwargs={"spread_bps": Decimal("100")})
    closed = _verdict(
        symbol="AAPL",
        asset_class="equity",
        qty=Decimal("0.10"),
        price=Decimal("150"),
        tif="DAY",
        internal_max=Decimal("20.00"),
        quote_kwargs={"market_open": False},
    )

    assert "QUOTE_MISSING" in missing.reason_codes
    assert "QUOTE_STALE" in stale.reason_codes
    assert "QUOTE_WIDE_SPREAD" in wide.reason_codes
    assert "MARKET_CLOSED" in closed.reason_codes


def test_exposure_open_order_and_reservation_conflicts_block_before_routing():
    duplicate = _verdict(existing_positions=({"symbol": "BTC/USD", "quantity": "0.01"},))
    open_order = _verdict(open_orders=({"symbol": "BTC/USD", "side": "buy", "status": "open"},))
    orphan = _verdict(open_orders=({"symbol": "BTC/USD", "side": "buy"},))
    reserved = _verdict(reservations=({"symbol": "BTC/USD", "status": "active"},))

    assert "DUPLICATE_EXISTING_EXPOSURE" in duplicate.reason_codes
    assert "OPEN_ORDER_CONFLICT" in open_order.reason_codes
    assert "ORPHAN_OPEN_ORDER" in orphan.reason_codes
    assert "RESERVATION_CONFLICT" in reserved.reason_codes


def test_unsupported_live_and_missing_adapter_capability_fail_closed():
    registry = build_default_capability_registry()
    live_result = registry.resolve(
        PortalSelectionRequest(
            symbol="AAPL",
            asset_class="equity",
            environment=PortalEnvironment.LIVE.value,
            order_type="limit",
            time_in_force="DAY",
            policy_mode=PortalPolicyMode.CAPABILITY_FIRST.value,
        )
    )
    missing_adapter_result = registry.resolve(
        PortalSelectionRequest(
            symbol="BTC/USD",
            asset_class="crypto",
            environment=PortalEnvironment.PAPER.value,
            order_type="limit",
            time_in_force="GTC",
            policy_mode=PortalPolicyMode.EXPLICIT_PREFERRED_VENUE.value,
            preferred_venue="coinbase",
        )
    )

    live = evaluate_pre_trade_guardrails(
        PreTradeGuardrailRequest(
            symbol="AAPL",
            side="buy",
            order_type="limit",
            time_in_force="DAY",
            quantity=Decimal("0.10"),
            limit_price=Decimal("150"),
            current_price=Decimal("150"),
            portal_selection_result=live_result,
        )
    )
    missing_adapter = evaluate_pre_trade_guardrails(
        PreTradeGuardrailRequest(
            symbol="BTC/USD",
            side="buy",
            order_type="limit",
            time_in_force="GTC",
            quantity=Decimal("0.0002"),
            limit_price=Decimal("77064.20"),
            current_price=Decimal("77064.20"),
            portal_selection_result=missing_adapter_result,
        )
    )

    assert live.route_permitted is False
    assert "NO_USABLE_PORTAL" in live.reason_codes
    assert missing_adapter.route_permitted is False
    assert "PREFERRED_PORTAL_UNSUPPORTED" in missing_adapter.reason_codes


def test_guardrail_verdict_contains_advisory_module_contribution_without_fake_economics():
    verdict = _verdict(qty=Decimal("0.0002"), internal_max=Decimal("20.00"))
    evidence = {item.module: item for item in verdict.module_evidence}

    assert verdict.route_permitted is True
    assert evidence["protective modules/council"].status == "CONTRIBUTED_ADVISORY"
    assert evidence["economics advisory"].reason_code == "ECONOMICS_ADVISORY_MISSING_TRUTH"
    assert evidence["NetEdgeGovernor"].reason_code == "NET_EDGE_MISSING_TRUTH"
    assert evidence["TradeEfficiencyGovernor"].reason_code == "TRADE_EFFICIENCY_MISSING_TRUTH"
    assert evidence["SovereignExecutionGuard"].status == "DORMANT_BY_POLICY"
    assert evidence["StrategyAllocator / SovereignGovernor"].status == "DORMANT_BY_POLICY"


def test_execution_engine_blocks_guardrail_denial_before_order_router_submit():
    router = MagicMock()
    router.get_mid_price.return_value = Decimal("77064.20")
    engine = _engine(router, size=Decimal("0.00006488"))
    verdict = _verdict().to_dict()

    admitted = engine.submit_signal(
        _signal("BTC/USD", Decimal("0.00006488"), {"pre_trade_guardrail_verdict": verdict}),
        current_price=Decimal("77064.20"),
        is_attack=True,
    )

    assert admitted is False
    router.submit_order.assert_not_called()


def test_data_unhealthy_block_emits_causal_evidence_before_router_submit():
    router = MagicMock()
    router.get_mid_price.return_value = Decimal("2500.00")
    validator = DataContinuityValidator(max_stale_age_sec=5.0)
    validator.record_data("ETH/USD", _ns_datetime(T0_NS))
    engine = ExecutionEngine(
        commander=Commander(),
        risk_guard=_risk_guard(),
        order_router=router,
        masking_layer=_masking_layer(Decimal("0.01")),
        data_validator=validator,
        signal_ttl_ms=1000.0,
    )
    engine._state.is_running = True
    signal = _signal(
        "ETH/USD",
        Decimal("0.01"),
        {
            "execution_market_truth": {
                "symbol": "ETH/USD",
                "latest_book_ts_ns": None,
                "latest_candle_ts_ns": T0_NS,
                "data_source_type": "runtime",
            }
        },
    )

    admitted = engine.submit_signal(
        signal,
        current_price=Decimal("2500.00"),
        is_attack=False,
    )

    block = engine.get_last_admission_block_result()
    evidence = block.block_evidence
    assert admitted is False
    assert block.reason_code == "DATA_UNHEALTHY"
    assert evidence["symbol"] == "ETH/USD"
    assert evidence["gap_detected"] is False
    assert evidence["last_valid_data_ns"] == T0_NS
    assert evidence["last_valid_data_age_ms"] > evidence["max_stale_age_ms"]
    assert evidence["max_stale_age_ms"] == 5000.0
    assert evidence["latest_book_ts_ns"] is None
    assert evidence["latest_candle_ts_ns"] == T0_NS
    assert evidence["data_health_reason_code"] == "DATA_STALE"
    assert evidence["data_source_type"] == "runtime"
    router.submit_order.assert_not_called()


def test_data_continuity_validator_packet_health_remains_strict_at_five_seconds():
    validator = DataContinuityValidator(max_stale_age_sec=5.0)
    validator.record_data("ETH/USD", _ns_datetime(T0_NS))

    snapshot = validator.health_snapshot(
        "ETH/USD",
        current_ns=T0_NS + 6_000_000_000,
        latest_candle_ts_ns=T0_NS,
        source_type="runtime",
    )

    assert validator.max_stale_age_ns == 5_000_000_000
    assert snapshot["data_healthy"] is False
    assert snapshot["data_health_reason_code"] == "DATA_STALE"
    assert snapshot["last_valid_data_age_ms"] == 6000.0
    assert snapshot["max_stale_age_ms"] == 5000.0


def test_backfill_observe_only_signal_is_blocked_as_data_unhealthy():
    router = MagicMock()
    validator = DataContinuityValidator(max_stale_age_sec=5.0)
    fresh_ns = now_ns()
    validator.record_data("ETH/USD", _ns_datetime(fresh_ns))
    engine = ExecutionEngine(
        commander=Commander(),
        risk_guard=_risk_guard(),
        order_router=router,
        masking_layer=_masking_layer(Decimal("0.01")),
        data_validator=validator,
        signal_ttl_ms=1000.0,
    )
    engine._state.is_running = True
    signal = _signal(
        "ETH/USD",
        Decimal("0.01"),
        {
            "execution_market_truth": {
                "symbol": "ETH/USD",
                "latest_candle_ts_ns": fresh_ns,
                "data_source_type": "backfill",
            }
        },
    )

    admitted = engine.submit_signal(
        signal,
        current_price=Decimal("2500.00"),
        is_attack=False,
    )

    block = engine.get_last_admission_block_result()
    assert admitted is False
    assert block.reason_code == "DATA_UNHEALTHY"
    assert block.block_evidence["data_health_reason_code"] == "DATA_BACKFILL_OBSERVE_ONLY"
    assert block.block_evidence["data_source_type"] == "backfill"
    router.submit_order.assert_not_called()


def test_fresh_same_symbol_market_truth_passes_to_non_mutating_queue_boundary():
    router = MagicMock()
    validator = DataContinuityValidator(max_stale_age_sec=5.0)
    fresh_ns = now_ns()
    validator.record_data("ETH/USD", _ns_datetime(fresh_ns))
    engine = ExecutionEngine(
        commander=Commander(),
        risk_guard=_risk_guard(),
        order_router=router,
        masking_layer=_masking_layer(Decimal("0.01")),
        data_validator=validator,
        signal_ttl_ms=1000.0,
    )
    engine._state.is_running = True
    signal = _signal(
        "ETH/USD",
        Decimal("0.01"),
        {
            "execution_market_truth": {
                "symbol": "ETH/USD",
                "latest_candle_ts_ns": fresh_ns,
                "data_source_type": "runtime",
            }
        },
    )

    admitted = engine.submit_signal(
        signal,
        current_price=Decimal("2500.00"),
        is_attack=False,
    )

    assert admitted is True
    assert engine.get_last_admission_block_result() is None
    assert engine.get_status()["execution_queue_size"] == 1
    router.submit_order.assert_not_called()


def test_safe_mode_active_block_emits_latency_recovery_evidence():
    router = MagicMock()
    engine = _engine(router, size=Decimal("0.01"))
    engine._state.is_in_safe_mode = True
    engine._state.safe_mode_entered_at_ns = T0_NS
    engine._state.last_latency_ok_at_ns = T0_NS - 10_000_000
    engine._state.safe_mode_recovery_state = "LAG_ABORT_ACTIVE"
    engine._state.last_latency_truth = {
        "status": "LAG_ABORT_ACTIVE",
        "reason_code": "LATENCY_THRESHOLD_EXCEEDED",
        "latency_ms": 250.0,
        "threshold_ms": 200.0,
        "source": "order_router.websocket_rtt",
    }

    admitted = engine.submit_signal(
        _signal("ETH/USD", Decimal("0.01"), {}),
        current_price=Decimal("2500.00"),
        is_attack=False,
    )

    block = engine.get_last_admission_block_result()
    evidence = block.block_evidence
    assert admitted is False
    assert block.reason_code == "SAFE_MODE_ACTIVE"
    assert evidence["latency_truth_status"] == "LAG_ABORT_ACTIVE"
    assert evidence["latency_truth_reason_code"] == "LATENCY_THRESHOLD_EXCEEDED"
    assert evidence["latency_ms"] == 250.0
    assert evidence["threshold_ms"] == 200.0
    assert evidence["latency_source"] == "order_router.websocket_rtt"
    assert evidence["safe_mode_entered_at_ns"] == T0_NS
    assert evidence["last_latency_ok_at_ns"] == T0_NS - 10_000_000
    assert evidence["safe_mode_recovery_state"] == "LAG_ABORT_ACTIVE"
    router.submit_order.assert_not_called()


def test_safe_mode_recovery_clears_only_with_latency_ok_truth():
    router = MagicMock()
    engine = _engine(router, size=Decimal("0.01"))
    engine._state.is_in_safe_mode = True
    engine._state.safe_mode_entered_at_ns = T0_NS
    stale_truth = engine._classify_latency_truth(
        {"latency_ms": 9.0, "pong_ns": T0_NS - 40_000_000_000},
        current_ns=T0_NS,
    )
    engine._apply_latency_truth(stale_truth)
    assert engine.get_status()["is_in_safe_mode"] is True

    ok_truth = engine._classify_latency_truth(
        {
            "latency_ms": 9.0,
            "ping_ns": T0_NS - 9_000_000,
            "pong_ns": T0_NS,
        },
        current_ns=T0_NS,
    )
    engine._apply_latency_truth(ok_truth)
    status = engine.get_status()
    assert ok_truth.status == "LATENCY_OK"
    assert status["is_in_safe_mode"] is False
    assert status["safe_mode_recovery_state"] == "LATENCY_OK_CONFIRMED"
    assert status["safe_mode_entered_at_ns"] == 0


def test_execution_engine_uses_guardrail_order_shape_for_alpaca_crypto_non_attack():
    router = MagicMock()
    router.get_mid_price.return_value = Decimal("77064.20")
    router.submit_order.return_value = None
    router.get_gateway_response.return_value = None
    engine = _engine(router, size=Decimal("0.0002"))
    verdict = _verdict(
        symbol="BTC/USD",
        asset_class="crypto",
        qty=Decimal("0.0002"),
        price=Decimal("77064.20"),
        tif="GTC",
        internal_max=Decimal("20.00"),
    ).to_dict()

    result = engine.execute_compiled_decision(
        _decision(verdict),
        _signal(
            "BTC/USD",
            Decimal("0.0002"),
            {
                "asset_class": "crypto",
                "venue_id": "alpaca",
                "portal_name": "alpaca_paper",
                "environment": "paper",
                "execution_adapter": "alpaca_paper_rest",
            },
        ),
        current_price=Decimal("77064.20"),
        is_attack=False,
    )

    assert result.normalized_status == "pending"
    order = router.submit_order.call_args.args[0]
    assert order.order_type == "limit"
    assert order.limit_price == Decimal("77064.20")
    assert order.metadata["time_in_force"] == "gtc"
    assert order.metadata["execution_adapter"] == "alpaca_paper_rest"


def test_execution_spine_passes_allowed_guardrail_to_gateway_without_fake_fill():
    transport = StubTransport((200, {"id": "broker-seam4-open", "status": "open", "symbol": "AAPL"}))
    adapter = AlpacaPaperBrokerAdapter(
        AlpacaPaperCredentials(
            base_url="https://paper-api.alpaca.markets",
            key_id="paper-key",
            secret_key="paper-secret",
        ),
        transport=transport,
    )
    router = OrderRouter(
        primary_exchange="alpaca",
        paper_mode=True,
        broker_gateway_adapter=adapter,
        execution_broker="alpaca_paper",
    )
    router.update_market_mid("AAPL", 150.00, T0_NS)
    engine = _engine(router, size=Decimal("0.10"))
    verdict = _verdict(
        symbol="AAPL",
        asset_class="equity",
        qty=Decimal("0.10"),
        price=Decimal("150"),
        tif="DAY",
        internal_max=Decimal("20.00"),
    ).to_dict()

    result = engine.execute_compiled_decision(
        _decision(verdict),
        _signal(
            "AAPL",
            Decimal("0.10"),
            {
                "asset_class": "equity",
                "venue_id": "alpaca",
                "portal_name": "alpaca_paper",
                "environment": "paper",
                "execution_adapter": "alpaca_paper_rest",
                "time_in_force": "day",
            },
        ),
        current_price=Decimal("150.00"),
        is_attack=True,
    )

    assert result.normalized_status == "open"
    assert result.fill is None
    assert result.pre_trade_guardrail_verdict["route_permitted"] is True
    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["path"] == "/v2/orders"
    assert transport.calls[0]["body"]["time_in_force"] == "day"
