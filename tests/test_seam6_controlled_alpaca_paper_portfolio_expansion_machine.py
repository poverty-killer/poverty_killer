from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.commander import Commander
from app.core.intelligence_portfolio_state_truth_spine import (
    BrokerTruthSnapshot,
    IntelligencePortfolioStateTruthSpine,
    Seam5CycleRequest,
)
from app.execution.alpaca_paper_adapter import (
    EXPECTED_ALPACA_PAPER_BASE_URL,
    AlpacaPaperBrokerAdapter,
    AlpacaPaperCredentials,
    BrokerGatewayError,
    load_alpaca_paper_credentials,
)
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
from app.models.signals import StrategySignal
from app.risk.pre_trade_guardrails import PreTradeGuardrailRequest, evaluate_pre_trade_guardrails
from app.state.state_store import StateStore
from app.utils.time_utils import now_ns


APPROVAL_ENV = "POVERTY_KILLER_APPROVE_SEAM6_ALPACA_PAPER_PORTFOLIO_EXPANSION"
APPROVAL_VALUE = "YES_I_APPROVE_UP_TO_15_BUY_LIMIT_10_NOTIONAL_SEAM6"
REPORT_PATH = Path("reports/seam6_controlled_alpaca_paper_portfolio_expansion_machine.md")
ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"
TARGET_NOTIONAL = Decimal("10.00")
MAX_SUBMITTED_SYMBOLS = 15
MAX_TOTAL_INTENDED_NOTIONAL = Decimal("150.00")
MAX_SPREAD_BPS = Decimal("50")
MAX_QUOTE_AGE_NS = 120_000_000_000
ACTIVE_ORDER_STATUSES = frozenset({"accepted", "new", "pending_new", "open", "accepted_for_bidding"})
CURRENT_KNOWN_EXPOSURE = ("AAPL", "NVDA", "AMZN", "GOOGL", "TSLA", "SPY", "QQQ")


@dataclass(frozen=True)
class QuoteTruth:
    symbol: str
    bid: Decimal | None
    ask: Decimal | None
    quote_ts_ns: int | None
    receive_ts_ns: int
    source: str

    @property
    def mid(self) -> Decimal | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread_bps(self) -> Decimal | None:
        if self.bid is None or self.ask is None or self.mid is None or self.mid <= 0:
            return None
        return ((self.ask - self.bid) / self.mid) * Decimal("10000")

    def fresh_at(self, ts_ns: int) -> bool:
        if self.quote_ts_ns is None:
            return False
        return 0 <= ts_ns - self.quote_ts_ns <= MAX_QUOTE_AGE_NS


@dataclass(frozen=True)
class CandidateDecision:
    symbol: str
    asset_class: str
    final_action: str
    reason_codes: tuple[str, ...]
    rank_score: str | None = None
    qty: Decimal | None = None
    limit_price: Decimal | None = None
    intended_notional: Decimal | None = None
    broker_order_id: str | None = None
    client_order_id: str | None = None
    broker_status: str | None = None
    broker_message: str | None = None


class AlpacaDataReadOnlyClient:
    def __init__(self, key_id: str, secret_key: str) -> None:
        self.key_id = key_id
        self.secret_key = secret_key
        self.calls: list[tuple[str, str]] = []

    def latest_stock_quote(self, symbol: str) -> dict[str, Any]:
        path = f"/v2/stocks/{urllib.parse.quote(symbol, safe='')}/quotes/latest"
        return self._get(path)

    def _get(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(
            ALPACA_DATA_BASE_URL + path,
            method="GET",
            headers={
                "APCA-API-KEY-ID": self.key_id,
                "APCA-API-SECRET-KEY": self.secret_key,
                "Accept": "application/json",
            },
        )
        self.calls.append(("GET", path))
        try:
            with urllib.request.urlopen(request, timeout=10.0) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return {"_quote_error": f"HTTP_{exc.code}", "_quote_error_body": body[:300]}
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise RuntimeError(f"alpaca_data_network_unavailable:{type(exc).__name__}") from None


class Seam6RiskGuard:
    def can_trade(self) -> bool:
        return True

    def is_vol_fuse_triggered(self) -> bool:
        return False

    def record_fees(self, _fee: Any) -> None:
        return

    def register_recalibrate_callback(self, _callback: Any) -> None:
        return

    def register_emergency_callback(self, _callback: Any) -> None:
        return

    def register_zombie_callback(self, _callback: Any) -> None:
        return

    def register_lag_callback(self, _callback: Any) -> None:
        return

    def register_vol_fuse_callback(self, _callback: Any) -> None:
        return


class Seam6MaskingLayer:
    def __init__(self) -> None:
        self.next_size = Decimal("0")

    def mask_order(self, _quantity: Any) -> SimpleNamespace:
        return SimpleNamespace(masked_size=self.next_size)


def _approval_present() -> bool:
    return os.environ.get(APPROVAL_ENV) == APPROVAL_VALUE


def _active_open_orders(open_orders: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    return tuple(order for order in open_orders if str(order.get("status") or "").lower() in ACTIVE_ORDER_STATUSES)


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _ns_from_iso(value: Any) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return int(parsed.astimezone(timezone.utc).timestamp() * 1_000_000_000)
    except ValueError:
        return None


def _quote_from_payload(symbol: str, payload: dict[str, Any], receive_ts_ns: int) -> QuoteTruth:
    quote = payload.get("quote") if isinstance(payload, dict) else {}
    quote = quote if isinstance(quote, dict) else {}
    return QuoteTruth(
        symbol=symbol,
        bid=_decimal(quote.get("bp") or quote.get("bid_price")),
        ask=_decimal(quote.get("ap") or quote.get("ask_price")),
        quote_ts_ns=_ns_from_iso(quote.get("t") or quote.get("timestamp")),
        receive_ts_ns=receive_ts_ns,
        source="alpaca_data_latest_stock_quote",
    )


def _registry_universe() -> tuple[tuple[str, str], ...]:
    registry = build_default_capability_registry()
    pairs: list[tuple[str, str]] = []
    for asset_class in ("equity", "etf", "crypto"):
        caps = [
            cap
            for cap in registry.capabilities_for_asset_class(asset_class, environment=PortalEnvironment.PAPER.value)
            if cap.venue_id == "alpaca" and cap.portal_name == "alpaca_paper"
        ]
        for cap in caps:
            pairs.append((cap.symbol, cap.asset_class))
    return tuple(dict.fromkeys(pairs))


def _asset_truth_ok(asset_payload: Any) -> tuple[bool, tuple[str, ...]]:
    if not isinstance(asset_payload, dict):
        return False, ("ASSET_TRUTH_INVALID_SHAPE",)
    if asset_payload.get("status") != "active":
        return False, ("BROKER_ASSET_NOT_ACTIVE",)
    if asset_payload.get("tradable") is not True:
        return False, ("BROKER_ASSET_NOT_TRADABLE",)
    if asset_payload.get("fractionable") is not True:
        return False, ("BROKER_ASSET_NOT_FRACTIONABLE",)
    return True, ()


def _sizing(limit_price: Decimal, capability_min_notional: Decimal | None) -> tuple[Decimal | None, Decimal | None, tuple[str, ...]]:
    limit = limit_price.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if limit <= 0:
        return None, None, ("LIMIT_PRICE_NONPOSITIVE",)
    qty = (TARGET_NOTIONAL / limit).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    intended = (qty * limit).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    reasons: list[str] = []
    if qty <= 0:
        reasons.append("QUANTITY_NONPOSITIVE")
    if intended <= 0 or intended > TARGET_NOTIONAL:
        reasons.append("NOTIONAL_CAP_BREACH")
    if capability_min_notional is not None and intended < capability_min_notional:
        reasons.append("MIN_NOTIONAL_CANNOT_BE_MET_WITH_CAP_AND_PRECISION")
    return qty, intended, tuple(reasons)


def _build_engine(adapter: AlpacaPaperBrokerAdapter) -> tuple[ExecutionEngine, Seam6MaskingLayer, OrderRouter]:
    masking = Seam6MaskingLayer()
    router = OrderRouter(primary_exchange="alpaca", paper_mode=True, broker_gateway_adapter=adapter)
    engine = ExecutionEngine(
        commander=Commander(),
        risk_guard=Seam6RiskGuard(),
        order_router=router,
        masking_layer=masking,
        signal_ttl_ms=5000.0,
        maker_offset_pct=0.0,
    )
    engine._state.is_running = True
    engine._state.last_regime = "neutral"
    return engine, masking, router


def _signal(symbol: str, qty: Decimal, limit_price: Decimal, ts_ns: int) -> StrategySignal:
    return StrategySignal(
        strategy="shadow_front",
        symbol=symbol,
        side="buy",
        confidence=0.90,
        quantity=float(qty),
        price=float(limit_price),
        exchange_ts_ns=ts_ns,
        reason="seam6_controlled_alpaca_paper_portfolio_expansion",
        metadata={"expected_move": "0.02", "requested_notional": str(TARGET_NOTIONAL)},
    )


def _summarize_response(response: Any) -> Any:
    payload = getattr(response, "payload", response)
    return _json_ready(payload)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    return value


def _selected_account_fields(account: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "status",
        "cash",
        "buying_power",
        "equity",
        "portfolio_value",
        "long_market_value",
        "short_market_value",
        "pattern_day_trader",
        "trading_blocked",
        "transfers_blocked",
        "account_blocked",
        "trade_suspended_by_user",
        "multiplier",
    )
    return {field: account.get(field) for field in fields if field in account}


def _position_summary(position: dict[str, Any]) -> dict[str, Any]:
    fields = ("symbol", "asset_class", "qty", "side", "market_value", "cost_basis", "avg_entry_price", "current_price", "unrealized_pl")
    return {field: position.get(field) for field in fields if field in position}


def _order_summary(order: dict[str, Any]) -> dict[str, Any]:
    fields = ("id", "client_order_id", "symbol", "asset_class", "side", "type", "time_in_force", "qty", "limit_price", "status", "filled_qty", "filled_avg_price", "submitted_at")
    return {field: order.get(field) for field in fields if field in order}


def _write_report(summary: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Seam 6 Controlled Alpaca PAPER Portfolio Expansion Machine",
        "",
        f"- report_ts_ns: {summary['report_ts_ns']}",
        f"- endpoint: {summary['endpoint']}",
        f"- approval_env_present: {summary['approval_env_present']}",
        f"- selected_candidate_universe: `{json.dumps(summary['candidate_universe'])}`",
        f"- system_chosen_symbols: `{json.dumps(summary['system_chosen_symbols'])}`",
        f"- submitted_orders_count: {len(summary['submitted_orders'])}",
        f"- no_live_endpoint_or_mode: {summary['safety']['no_live_endpoint_or_mode']}",
        f"- no_sell_rebalance_cancel_replace_retry_storm: {summary['safety']['no_sell_rebalance_cancel_replace_retry_storm']}",
        f"- no_fake_broker_facts: {summary['safety']['no_fake_broker_facts']}",
        "",
        "## Skips",
        "```json",
        json.dumps(summary["skipped_symbols"], indent=2, sort_keys=True),
        "```",
        "",
        "## Submitted Orders",
        "```json",
        json.dumps(summary["submitted_orders"], indent=2, sort_keys=True),
        "```",
        "",
        "## Reconciled Orders",
        "```json",
        json.dumps(summary["reconciled_orders"], indent=2, sort_keys=True),
        "```",
        "",
        "## Positions After Reconciliation",
        "```json",
        json.dumps(summary["positions_after"], indent=2, sort_keys=True),
        "```",
        "",
        "## Open Orders After Reconciliation",
        "```json",
        json.dumps(summary["open_orders_after"], indent=2, sort_keys=True),
        "```",
        "",
        "## Account After Reconciliation",
        "```json",
        json.dumps(summary["account_after"], indent=2, sort_keys=True),
        "```",
        "",
        "## Machine Evidence",
        "```json",
        json.dumps(summary["machine_evidence"], indent=2, sort_keys=True),
        "```",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_seam6_approval_gate_is_exact_and_not_live_authority(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(APPROVAL_ENV, raising=False)

    assert _approval_present() is False
    assert EXPECTED_ALPACA_PAPER_BASE_URL == "https://paper-api.alpaca.markets"
    with pytest.raises(BrokerGatewayError) as exc:
        AlpacaPaperBrokerAdapter(
            AlpacaPaperCredentials(
                base_url="https://api.alpaca.markets",
                key_id="paper-key",
                secret_key="paper-secret",
            )
        )
    assert exc.value.reason_code == "live_or_nonpaper_endpoint_blocked"


def test_seam6_candidate_universe_is_registry_driven_and_broad_enough_for_fifteen_new_symbols():
    universe = _registry_universe()
    existing = set(CURRENT_KNOWN_EXPOSURE)
    new_equity_etf = [symbol for symbol, asset_class in universe if asset_class in {"equity", "etf"} and symbol not in existing]

    assert len(universe) > MAX_SUBMITTED_SYMBOLS
    assert len(new_equity_etf) >= MAX_SUBMITTED_SYMBOLS
    assert ("BTC/USD", "crypto") in universe


def test_real_seam6_controlled_alpaca_paper_portfolio_expansion_machine(tmp_path: Path):
    if not _approval_present():
        pytest.skip("Seam 6 Alpaca PAPER mutation approval env missing; no broker mutation attempted")

    credentials = load_alpaca_paper_credentials()
    assert credentials.base_url == EXPECTED_ALPACA_PAPER_BASE_URL
    adapter = AlpacaPaperBrokerAdapter(credentials)
    identity = adapter.identity
    assert identity.base_url == EXPECTED_ALPACA_PAPER_BASE_URL
    assert identity.environment == "paper"
    assert identity.live_blocked is True

    account_pre_response = adapter.get_account()
    positions_pre_response = adapter.get_positions()
    open_orders_pre_response = adapter.get_open_orders()
    clock_response = adapter.get_clock()
    account_pre = account_pre_response.payload
    positions_pre = positions_pre_response.payload
    open_orders_pre = open_orders_pre_response.payload
    clock = clock_response.payload
    assert isinstance(account_pre, dict)
    assert str(account_pre.get("status") or "").upper() == "ACTIVE"
    assert isinstance(positions_pre, list)
    assert isinstance(open_orders_pre, list)
    assert isinstance(clock, dict)

    data = AlpacaDataReadOnlyClient(credentials.key_id, credentials.secret_key)
    registry = build_default_capability_registry()
    now = now_ns()
    existing_symbols = {str(row.get("symbol") or "").upper() for row in positions_pre if _decimal(row.get("qty")) != Decimal("0")}
    active_open_order_symbols = {str(row.get("symbol") or "").upper() for row in _active_open_orders(open_orders_pre)}
    decisions: list[CandidateDecision] = []
    passed: list[tuple[Decimal, str, str, Decimal, Decimal, Decimal, dict[str, Any]]] = []

    for symbol, asset_class in _registry_universe():
        reasons: list[str] = []
        if symbol in existing_symbols:
            reasons.append("DUPLICATE_EXISTING_EXPOSURE")
        if symbol in active_open_order_symbols:
            reasons.append("OPEN_ORDER_CONFLICT")
        if asset_class == "crypto":
            reasons.append("CRYPTO_NOT_SELECTED_EQUITIES_ETFS_FIRST_FOR_SEAM6")

        capability_result = registry.resolve(
            PortalSelectionRequest(
                symbol=symbol,
                asset_class=asset_class,
                environment=PortalEnvironment.PAPER.value,
                action="buy",
                order_type="limit",
                time_in_force="GTC" if asset_class == "crypto" else "DAY",
                policy_mode=PortalPolicyMode.EXPLICIT_PREFERRED_VENUE.value,
                preferred_venue="alpaca_paper",
                allow_fallback=False,
            )
        )
        capability = capability_result.selected
        if capability is None:
            reasons.extend(capability_result.reason_codes or ("NO_USABLE_PORTAL",))
            decisions.append(CandidateDecision(symbol, asset_class, "SKIP_CAPABILITY", tuple(dict.fromkeys(reasons))))
            continue

        asset_response = adapter.get_asset(symbol)
        asset_ok, asset_reasons = _asset_truth_ok(asset_response.payload)
        reasons.extend(asset_reasons)

        quote_payload: dict[str, Any] = {}
        quote: QuoteTruth | None = None
        if asset_class in {"equity", "etf"}:
            quote_payload = data.latest_stock_quote(symbol)
            if quote_payload.get("_quote_error"):
                reasons.append(str(quote_payload.get("_quote_error")))
            else:
                quote = _quote_from_payload(symbol, quote_payload, now_ns())
        if quote is None:
            reasons.append("QUOTE_MISSING")
        else:
            if not quote.fresh_at(now_ns()):
                reasons.append("QUOTE_STALE")
            if quote.spread_bps is None or quote.spread_bps > MAX_SPREAD_BPS:
                reasons.append("QUOTE_WIDE_SPREAD")
        market_open = bool(clock.get("is_open")) if asset_class in {"equity", "etf"} else None
        if asset_class in {"equity", "etf"} and market_open is not True:
            reasons.append("MARKET_CLOSED")

        limit_price = quote.ask if quote and quote.ask is not None else Decimal("0")
        qty, intended_notional, sizing_reasons = _sizing(limit_price, capability.min_notional)
        reasons.extend(sizing_reasons)
        if intended_notional is not None and intended_notional > TARGET_NOTIONAL:
            reasons.append("NOTIONAL_CAP_BREACH")

        quote_classification = classify_quote_session(
            CapabilityAwareCandidate.from_capability(capability, tradable=asset_ok),
            market_session_open=market_open,
            quote_present=quote is not None and quote.bid is not None and quote.ask is not None,
            quote_fresh=quote.fresh_at(now_ns()) if quote is not None else False,
            spread_bps=quote.spread_bps if quote is not None else None,
            max_spread_bps=MAX_SPREAD_BPS,
        )
        guardrail = evaluate_pre_trade_guardrails(
            PreTradeGuardrailRequest(
                symbol=symbol,
                side="buy",
                order_type="limit",
                time_in_force=capability.default_time_in_force,
                quantity=qty or Decimal("0"),
                limit_price=limit_price,
                current_price=limit_price,
                internal_max_notional=TARGET_NOTIONAL,
                capability=capability,
                portal_selection_result=capability_result,
                quote_classification=quote_classification,
                existing_positions=tuple(positions_pre),
                open_orders=tuple(open_orders_pre),
            )
        )
        if not guardrail.route_permitted:
            reasons.extend(guardrail.reason_codes)

        unique_reasons = tuple(dict.fromkeys(reasons))
        if unique_reasons:
            decisions.append(
                CandidateDecision(
                    symbol,
                    asset_class,
                    "SKIP_GUARDRAIL_OR_TRUTH",
                    unique_reasons,
                    qty=qty,
                    limit_price=limit_price if limit_price > 0 else None,
                    intended_notional=intended_notional,
                )
            )
            continue

        rank_score = quote.spread_bps if quote and quote.spread_bps is not None else Decimal("999999")
        passed.append((rank_score, symbol, asset_class, qty or Decimal("0"), limit_price, intended_notional or Decimal("0"), guardrail.to_dict()))

    passed.sort(key=lambda item: (0 if item[2] in {"equity", "etf"} else 1, item[0], item[1]))
    selected = passed[:MAX_SUBMITTED_SYMBOLS]
    total_intended = sum((item[5] for item in selected), Decimal("0"))
    assert total_intended <= MAX_TOTAL_INTENDED_NOTIONAL

    engine, masking, router = _build_engine(adapter)
    spine = IntelligencePortfolioStateTruthSpine()
    store = StateStore(str(tmp_path / "seam6_state.db"))
    submitted: list[CandidateDecision] = []
    machine_evidence: list[dict[str, Any]] = []

    for index, (rank_score, symbol, asset_class, qty, limit_price, intended_notional, _guardrail) in enumerate(selected):
        ts_ns = now + index + 1
        masking.next_size = qty
        router.update_market_mid(symbol, limit_price, ts_ns)
        cycle = spine.run_cycle(
            Seam5CycleRequest(
                symbol=symbol,
                timestamp_ns=ts_ns,
                current_price=limit_price,
                asset_class=asset_class,
                strategy_modules={"shadow_front": object()},
                strategy_signals=[_signal(symbol, qty, limit_price, ts_ns)],
                broker_truth=BrokerTruthSnapshot(
                    positions=tuple(positions_pre),
                    open_orders=tuple(open_orders_pre),
                    account=account_pre,
                    receive_ts_ns=now,
                    fixture_truth=True,
                ),
                state_store=store,
                execution_engine=engine,
                allow_execution=True,
                max_notional=TARGET_NOTIONAL,
            )
        )
        result = cycle.execution_result
        gateway_response = result.gateway_response if result is not None else None
        submitted.append(
            CandidateDecision(
                symbol=symbol,
                asset_class=asset_class,
                final_action="SUBMITTED_BUY_LIMIT" if gateway_response is not None and gateway_response.ok else "BROKER_REJECTED_OR_BLOCKED",
                reason_codes=tuple(cycle.reason_codes),
                rank_score=str(rank_score),
                qty=qty,
                limit_price=limit_price,
                intended_notional=intended_notional,
                broker_order_id=getattr(gateway_response, "broker_order_id", None),
                client_order_id=getattr(gateway_response, "client_order_id", None) or (result.client_order_id if result else None),
                broker_status=getattr(gateway_response, "normalized_status", None) or cycle.execution_status,
                broker_message=getattr(gateway_response, "message", None),
            )
        )
        machine_evidence.append(
            {
                "symbol": symbol,
                "candidate_status": cycle.candidate.status,
                "guardrail": _json_ready(cycle.guardrail_verdict),
                "execution_status": cycle.execution_status,
                "execution_route": result.route if result else None,
                "client_order_id": result.client_order_id if result else None,
                "broker_order_id": result.broker_order_id if result else None,
                "state_events": list(cycle.state_mutation.recorded_events),
                "truth_kernel": cycle.truth_kernel.status,
                "invariants": cycle.invariant_checker.status,
            }
        )

    if not selected:
        aggregate_reasons = tuple(
            dict.fromkeys(reason for decision in decisions for reason in decision.reason_codes)
        )
        machine_evidence.append(
            {
                "selection_status": "NO_SAFE_CANDIDATES_AFTER_REAL_TRUTH_GATES",
                "decision_compiler_reached": False,
                "execution_engine_reached": False,
                "order_router_reached": False,
                "broker_gateway_post_count": adapter.request_counts.get("POST", 0),
                "reason_codes": aggregate_reasons,
            }
        )

    account_after = adapter.get_account().payload
    positions_after = adapter.get_positions().payload
    open_orders_after = adapter.get_open_orders().payload
    reconciled_orders = []
    for row in submitted:
        if row.broker_order_id:
            status_response = adapter.get_order_status(row.broker_order_id)
            reconciled_orders.append(_order_summary(status_response.payload if isinstance(status_response.payload, dict) else {}))
        else:
            reconciled_orders.append(
                {
                    "symbol": row.symbol,
                    "client_order_id": row.client_order_id,
                    "status": row.broker_status,
                    "message": row.broker_message,
                }
            )

    skipped = [
        {
            "symbol": row.symbol,
            "asset_class": row.asset_class,
            "final_action": row.final_action,
            "reason_codes": row.reason_codes,
            "qty": str(row.qty) if row.qty is not None else None,
            "limit_price": str(row.limit_price) if row.limit_price is not None else None,
            "intended_notional": str(row.intended_notional) if row.intended_notional is not None else None,
        }
        for row in decisions
    ]
    submitted_summary = [
        {
            "symbol": row.symbol,
            "asset_class": row.asset_class,
            "final_action": row.final_action,
            "reason_codes": row.reason_codes,
            "rank_score": row.rank_score,
            "qty": str(row.qty),
            "limit_price": str(row.limit_price),
            "intended_notional": str(row.intended_notional),
            "broker_order_id": row.broker_order_id,
            "client_order_id": row.client_order_id,
            "broker_status": row.broker_status,
            "broker_message": row.broker_message,
        }
        for row in submitted
    ]
    summary = {
        "report_ts_ns": now_ns(),
        "endpoint": identity.base_url,
        "approval_env_present": True,
        "candidate_universe": [{"symbol": symbol, "asset_class": asset_class} for symbol, asset_class in _registry_universe()],
        "system_chosen_symbols": [row.symbol for row in submitted],
        "skipped_symbols": skipped,
        "submitted_orders": submitted_summary,
        "reconciled_orders": reconciled_orders,
        "positions_after": [_position_summary(row) for row in positions_after],
        "open_orders_after": [_order_summary(row) for row in open_orders_after],
        "account_after": _selected_account_fields(account_after),
        "machine_evidence": machine_evidence,
        "safety": {
            "no_live_endpoint_or_mode": identity.base_url == EXPECTED_ALPACA_PAPER_BASE_URL and identity.environment == "paper",
            "no_market_orders": True,
            "no_sell_orders": True,
            "no_sell_rebalance_cancel_replace_retry_storm": True,
            "no_fake_broker_facts": True,
            "broker_truth_canonical": True,
            "local_state_supporting_evidence_only": True,
            "adapter_request_counts": adapter.request_counts,
            "data_calls": data.calls,
        },
    }
    _write_report(summary)

    assert identity.base_url == EXPECTED_ALPACA_PAPER_BASE_URL
    assert len(submitted) <= MAX_SUBMITTED_SYMBOLS
    assert all(row.final_action in {"SUBMITTED_BUY_LIMIT", "BROKER_REJECTED_OR_BLOCKED"} for row in submitted)
    assert all((row.qty or Decimal("0")) * (row.limit_price or Decimal("0")) <= TARGET_NOTIONAL for row in submitted)
    assert all(item.get("type") in {None, "limit"} for item in reconciled_orders)
    assert adapter.request_counts.get("POST", 0) == len(submitted)
    assert REPORT_PATH.exists()
