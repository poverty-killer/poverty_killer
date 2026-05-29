"""Honest historical-test control foundation for the operator UI.

This module exposes a safe shell for historical Alpaca data tests. It can record
the requested window and, when a fake/read-only market data client is supplied
in tests, count retrieved bars. It does not simulate trades or produce
performance numbers until a governed replay/backtest harness is wired.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol


DEFAULT_WATCHLIST = ("BTC/USD", "ETH/USD", "SOL/USD")
TIMEFRAMES = ("1Min", "5Min", "15Min", "1Hour", "1Day")
FEE_SLIPPAGE_POLICIES = (
    "broker_fees_unavailable_unknown",
    "conservative_estimate_not_broker_truth",
)


class HistoricalMarketDataClient(Protocol):
    def fetch_bars(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: str,
        end_date: str,
        timeframe: str,
    ) -> dict[str, list[dict[str, Any]]]:
        ...


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def default_four_month_range(today: date | None = None) -> dict[str, str]:
    end = today or _today_utc()
    start = end - timedelta(days=122)
    return {"start_date": start.isoformat(), "end_date": end.isoformat()}


def _parse_date(value: Any, fallback: str) -> str:
    raw = str(value or fallback).strip()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return fallback


def _watchlist(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        items = DEFAULT_WATCHLIST
    symbols = tuple(dict.fromkeys(str(item).strip().upper() for item in items if str(item).strip()))
    return symbols or DEFAULT_WATCHLIST


def _money_text(value: Any, fallback: str = "10000") -> str:
    raw = str(value or fallback).strip()
    try:
        parsed = float(raw)
    except ValueError:
        return fallback
    return fallback if parsed <= 0 else raw


def _request_from_payload(payload: dict[str, Any] | None, *, today: date | None = None) -> dict[str, Any]:
    body = payload or {}
    preset = str(body.get("date_range_preset") or "last_4_months").strip() or "last_4_months"
    defaults = default_four_month_range(today)
    if preset == "last_4_months":
        start_date = defaults["start_date"]
        end_date = defaults["end_date"]
    else:
        start_date = _parse_date(body.get("start_date"), defaults["start_date"])
        end_date = _parse_date(body.get("end_date"), defaults["end_date"])
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    timeframe = str(body.get("timeframe") or "1Day").strip()
    if timeframe not in TIMEFRAMES:
        timeframe = "1Day"
    fee_policy = str(body.get("fee_slippage_policy") or FEE_SLIPPAGE_POLICIES[0]).strip()
    if fee_policy not in FEE_SLIPPAGE_POLICIES:
        fee_policy = FEE_SLIPPAGE_POLICIES[0]
    return {
        "date_range_preset": preset,
        "start_date": start_date,
        "end_date": end_date,
        "watchlist": list(_watchlist(body.get("watchlist"))),
        "timeframe": timeframe,
        "starting_capital": _money_text(body.get("starting_capital")),
        "fee_slippage_policy": fee_policy,
        "strategy_profile": str(body.get("strategy_profile") or "PAPER_EXPLORATION_ALPHA").strip()
        or "PAPER_EXPLORATION_ALPHA",
    }


def _test_id(request: dict[str, Any]) -> str:
    material = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "hist_" + hashlib.sha256(material).hexdigest()[:16]


def _empty_per_symbol(symbols: list[str], bars_by_symbol: dict[str, list[dict[str, Any]]] | None = None) -> list[dict[str, Any]]:
    bars_by_symbol = bars_by_symbol or {}
    return [
        {
            "symbol": symbol,
            "bar_count": len(bars_by_symbol.get(symbol, [])),
            "simulated_trades": 0,
            "total_return": None,
            "warning": "NO_STRATEGY_REPLAY_HARNESS_ATTACHED",
        }
        for symbol in symbols
    ]


def run_historical_test(
    payload: dict[str, Any] | None = None,
    *,
    market_data_client: HistoricalMarketDataClient | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    request = _request_from_payload(payload, today=today)
    symbols = tuple(request["watchlist"])
    bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
    market_data_attempted = False
    market_data_error: str | None = None
    if market_data_client is not None:
        market_data_attempted = True
        try:
            bars_by_symbol = market_data_client.fetch_bars(
                symbols=symbols,
                start_date=request["start_date"],
                end_date=request["end_date"],
                timeframe=request["timeframe"],
            )
        except Exception as exc:  # pragma: no cover - defensive for injected clients
            market_data_error = type(exc).__name__

    reason_codes = ["STRATEGY_REPLAY_HARNESS_NOT_ATTACHED", "NO_FAKE_PERFORMANCE_NUMBERS"]
    if not market_data_attempted:
        reason_codes.append("HISTORICAL_DATA_CLIENT_NOT_ATTACHED")
    if market_data_error:
        reason_codes.append("HISTORICAL_DATA_READ_FAILED")

    status = "DATA_READY_SIMULATION_NOT_AVAILABLE" if market_data_attempted and not market_data_error else "NOT_IMPLEMENTED_READY_FOR_HARNESS"
    completeness = {
        "market_data_read_attempted": market_data_attempted,
        "symbols_requested": list(symbols),
        "symbols_with_data": sorted([symbol for symbol, bars in bars_by_symbol.items() if bars]),
        "total_bars_loaded": sum(len(bars) for bars in bars_by_symbol.values()),
        "read_error": market_data_error,
    }
    test_id = _test_id(request)
    return {
        "source": "OPERATOR_HISTORICAL_TESTS",
        "test_id": test_id,
        "status": status,
        "request": request,
        "result": {
            "final_equity": None,
            "total_return": None,
            "max_drawdown": None,
            "win_loss_count": None,
            "simulated_trade_count": 0,
            "rejected_blocked_trade_count": 0,
            "reason_codes": reason_codes,
            "fees_slippage_assumption": request["fee_slippage_policy"],
            "unknown_fee_tca_warnings": [
                "broker fees unavailable / unknown",
                "historical TCA not broker-confirmed",
            ],
            "missing_data_warnings": [
                "No governed strategy replay/backtest harness is attached to this operator control yet.",
                "No performance numbers are produced without simulation evidence.",
            ],
            "symbols_tested": list(symbols),
            "time_range": {"start_date": request["start_date"], "end_date": request["end_date"]},
            "data_source": "ALPACA_HISTORICAL_DATA_READ_ONLY_IF_CLIENT_ATTACHED",
            "data_freshness_completeness": completeness,
            "equity_curve": [],
            "per_symbol_summary": _empty_per_symbol(list(symbols), bars_by_symbol),
            "risk_summary": {
                "historical_simulation_only": True,
                "not_broker_confirmed": True,
                "not_live_proof": True,
                "not_future_profit_proof": True,
            },
            "caveats": [
                "historical simulation only",
                "not broker-confirmed",
                "not live proof",
                "not future-profit proof",
                "no fake P&L/TCA/fees",
            ],
        },
        "read_only_market_data_only": True,
        "broker_trading_call_occurred": False,
        "broker_mutation_occurred": False,
        "trading_mutation_occurred": False,
        "paper_started": False,
        "live_enabled": False,
        "real_money_enabled": False,
        "can_execute": False,
        "raw_logs_included": False,
        "secrets_values_exposed": False,
    }


def render_historical_report(snapshot: dict[str, Any]) -> str:
    request = snapshot.get("request") or {}
    result = snapshot.get("result") or {}
    return "\n".join(
        [
            f"# Historical Alpaca Test - {snapshot.get('test_id', 'unknown')}",
            "",
            f"- Status: {snapshot.get('status', 'UNKNOWN')}",
            f"- Range: {request.get('start_date')} to {request.get('end_date')}",
            f"- Symbols: {', '.join(request.get('watchlist') or [])}",
            f"- Timeframe: {request.get('timeframe')}",
            f"- Starting capital: {request.get('starting_capital')}",
            f"- Fee/slippage policy: {request.get('fee_slippage_policy')}",
            "",
            "## Result",
            "- Final equity: unknown - no governed simulation harness attached",
            "- Total return: unknown - no governed simulation harness attached",
            "- Max drawdown: unknown - no governed simulation harness attached",
            f"- Simulated trades: {result.get('simulated_trade_count', 0)}",
            f"- Reason codes: {', '.join(result.get('reason_codes') or [])}",
            "",
            "## Caveats",
            "- Historical simulation only.",
            "- Not broker-confirmed.",
            "- Not live proof.",
            "- Not future-profit proof.",
            "- No fake P&L, fees, fills, TCA, or market truth is produced.",
        ]
    )


@dataclass
class HistoricalTestService:
    market_data_client: HistoricalMarketDataClient | None = None
    today: date | None = None
    _results: dict[str, dict[str, Any]] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        defaults = default_four_month_range(self.today)
        return {
            "source": "OPERATOR_HISTORICAL_TESTS",
            "status": "READY_FOR_REQUEST_HARNESS_NOT_ATTACHED",
            "presets": [
                {
                    "id": "last_4_months",
                    "label": "Last 4 months",
                    "start_date": defaults["start_date"],
                    "end_date": defaults["end_date"],
                }
            ],
            "timeframes": list(TIMEFRAMES),
            "fee_slippage_policies": list(FEE_SLIPPAGE_POLICIES),
            "default_watchlist": list(DEFAULT_WATCHLIST),
            "last_results": list(self._results.values())[-5:],
            "simulation_harness_attached": False,
            "read_only_market_data_only": True,
            "broker_trading_call_occurred": False,
            "broker_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
            "can_execute": False,
            "secrets_values_exposed": False,
        }

    def run(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        snapshot = run_historical_test(payload, market_data_client=self.market_data_client, today=self.today)
        self._results[snapshot["test_id"]] = snapshot
        return snapshot

    def detail(self, test_id: str) -> dict[str, Any]:
        return self._results.get(str(test_id), {
            "source": "OPERATOR_HISTORICAL_TESTS",
            "test_id": str(test_id),
            "status": "NOT_FOUND",
            "reason_codes": ["HISTORICAL_TEST_ID_NOT_FOUND"],
            "can_execute": False,
            "broker_mutation_occurred": False,
            "secrets_values_exposed": False,
        })

    def report(self, test_id: str) -> dict[str, Any]:
        snapshot = self.detail(test_id)
        if snapshot.get("status") == "NOT_FOUND":
            return snapshot
        return {
            "source": "OPERATOR_HISTORICAL_TESTS",
            "test_id": test_id,
            "status": snapshot.get("status"),
            "markdown": render_historical_report(snapshot),
            "report_path": None,
            "logs_mutated": False,
            "raw_logs_included": False,
            "secrets_values_exposed": False,
        }
