"""Read-only PAPER portfolio snapshots for the operator UI.

The module performs only broker GET-style reads when credentials are available.
It does not import or call execution, OMS, strategy, order submission, cancel,
or liquidation code.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Protocol

from app.operator_credentials.store import (
    ALPACA_LIVE_ENDPOINT,
    ALPACA_PAPER_ENDPOINT,
    alpaca_endpoint_authority,
)


PORTFOLIO_SOURCE = "OPERATOR_PORTFOLIO_READ_ONLY"


class ReadOnlyBrokerClient(Protocol):
    def get_json(self, path: str, headers: Mapping[str, str]) -> Any:
        ...


class AlpacaPaperReadOnlyClient:
    """Small GET-only Alpaca PAPER client used by operator read endpoints."""

    def __init__(self, *, base_url: str = ALPACA_PAPER_ENDPOINT, timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path: str, headers: Mapping[str, str]) -> Any:
        self.calls.append(("GET", path))
        url = f"{self.base_url}{path}"
        request = urllib.request.Request(url, method="GET", headers=dict(headers))
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - governed PAPER URL.
            return json.loads(response.read().decode("utf-8"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _decimal_text(value: Any) -> str | None:
    parsed = _decimal(value)
    if parsed is None:
        return None
    return format(parsed.normalize(), "f")


def _pct(numerator: Decimal | None, denominator: Decimal | None) -> str | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return f"{(numerator / denominator * Decimal('100')).quantize(Decimal('0.01'))}%"


def _difference(left: Any, right: Any) -> str | None:
    left_d = _decimal(left)
    right_d = _decimal(right)
    if left_d is None or right_d is None:
        return None
    return format((left_d - right_d).normalize(), "f")


def _portfolio_unavailable_status(reason: str) -> str:
    if reason == "MISSING_ALPACA_PAPER_CREDENTIALS":
        return "MISSING_CREDENTIALS"
    if reason == "AUTH_FAILED":
        return "AUTH_FAILED"
    if reason == "BROKER_READ_FAILED":
        return "BROKER_READ_FAILED"
    if reason in {"LIVE_ENDPOINT_BLOCKED", "ALPACA_PAPER_ENDPOINT_REQUIRED"}:
        return "BACKEND_DEGRADED"
    return "BACKEND_DEGRADED"


def _broker_failure_reason(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    text = f"{type(exc).__name__}: {exc}".lower()
    if code in {401, 403} or any(marker in text for marker in ("401", "403", "unauthor", "forbidden")):
        return "AUTH_FAILED"
    return "BROKER_READ_FAILED"


def _empty_unavailable(
    reason: str,
    *,
    detail: str | None = None,
    broker_read_attempted: bool = False,
    endpoint_authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = _portfolio_unavailable_status(reason)
    endpoint_truth = endpoint_authority or alpaca_endpoint_authority({})
    return {
        "source": PORTFOLIO_SOURCE,
        "data_source": "UNAVAILABLE",
        "status": status,
        "unavailable_reason": reason,
        "detail": detail,
        "summary": {
            "total_equity": None,
            "cash": None,
            "buying_power": None,
            "total_market_value": None,
            "total_unrealized_pnl": None,
            "total_realized_pnl": None,
            "day_pnl": None,
            "gross_exposure": None,
            "net_exposure": None,
            "position_count": 0,
            "open_order_count": 0,
            "largest_position": None,
            "highest_risk_position": None,
            "stale_or_conflicted_position_count": 0,
            "broker_local_reconciliation_status": "UNAVAILABLE",
        },
        "positions": [],
        "open_orders": [],
        "position_intelligence": [],
        "empty": False,
        "message": "Broker PAPER portfolio data is unavailable; no positions are invented.",
        "data_freshness_ts": None,
        "broker_read_attempted": broker_read_attempted,
        "broker_read_occurred": False,
        "paper_endpoint_authority": endpoint_truth,
        "paper_endpoint_only": endpoint_truth["paper_endpoint_only"],
        "paper_endpoint_status": endpoint_truth["status"],
        "paper_endpoint_operator_action": endpoint_truth["operator_action"],
        "broker_mutation_occurred": False,
        "order_submission_occurred": False,
        "cancel_occurred": False,
        "liquidation_occurred": False,
        "live_enabled": False,
        "real_money_enabled": False,
        "secrets_values_exposed": False,
        "raw_secret_values_included": False,
    }


def _headers(env: Mapping[str, str]) -> dict[str, str] | None:
    key_id = str(env.get("APCA_API_KEY_ID") or "").strip()
    secret_key = str(env.get("APCA_API_SECRET_KEY") or "").strip()
    if not key_id or not secret_key:
        return None
    return {
        "APCA-API-KEY-ID": key_id,
        "APCA-API-SECRET-KEY": secret_key,
        "Accept": "application/json",
    }


def _base_url(env: Mapping[str, str]) -> str:
    return str(env.get("APCA_API_BASE_URL") or ALPACA_PAPER_ENDPOINT).strip().rstrip("/")


def _active_order(order: Mapping[str, Any]) -> bool:
    return str(order.get("status") or "").lower() in {
        "new",
        "accepted",
        "pending_new",
        "partially_filled",
        "accepted_for_bidding",
        "held",
        "pending_replace",
        "replaced",
    }


def _map_order(order: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "order_id": order.get("id"),
        "client_order_id": order.get("client_order_id"),
        "symbol": order.get("symbol"),
        "asset_class": order.get("asset_class"),
        "qty": order.get("qty"),
        "filled_qty": order.get("filled_qty"),
        "side": order.get("side"),
        "type": order.get("type"),
        "time_in_force": order.get("time_in_force"),
        "limit_price": order.get("limit_price"),
        "stop_price": order.get("stop_price"),
        "status": order.get("status"),
        "submitted_at": order.get("submitted_at"),
        "updated_at": order.get("updated_at"),
        "filled_at": order.get("filled_at"),
        "source": "BROKER_CONFIRMED",
        "read_only": True,
        "can_cancel": False,
        "can_replace": False,
        "can_liquidate": False,
    }


def _latest_fills_by_symbol(activities: Any) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    if not isinstance(activities, list):
        return latest
    for row in activities:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if not symbol or symbol in latest:
            continue
        latest[symbol] = {
            "latest_fill_time": row.get("transaction_time") or row.get("date"),
            "latest_fill_price": row.get("price"),
            "latest_fill_qty": row.get("qty"),
            "latest_fill_side": row.get("side"),
        }
    return latest


def _map_position(
    position: Mapping[str, Any],
    *,
    equity: Decimal | None,
    open_orders: list[dict[str, Any]],
    latest_fills: Mapping[str, dict[str, Any]],
    now: str,
) -> dict[str, Any]:
    symbol = str(position.get("symbol") or "").upper()
    market_value = _decimal(position.get("market_value"))
    exposure_pct = _pct(market_value.copy_abs() if market_value is not None else None, equity)
    symbol_orders = [order for order in open_orders if str(order.get("symbol") or "").upper() == symbol]
    qty = _decimal(position.get("qty") or position.get("quantity"))
    side = str(position.get("side") or ("long" if qty is None or qty >= 0 else "short")).lower()
    latest_fill = latest_fills.get(symbol, {})
    warnings: list[str] = []
    exposure_number = None
    if exposure_pct and exposure_pct.endswith("%"):
        exposure_number = _decimal(exposure_pct[:-1])
    if exposure_number is not None and exposure_number > Decimal("25"):
        warnings.append("CONCENTRATION_WARNING")
    if position.get("current_price") in {None, ""}:
        warnings.append("PRICE_UNAVAILABLE")
    if market_value is None:
        warnings.append("EXPOSURE_UNKNOWN")
    warnings.extend(["FEE_STATUS_UNKNOWN", "TCA_STATUS_UNKNOWN", "SLIPPAGE_UNKNOWN"])
    if symbol_orders:
        warnings.append("OPEN_ORDER_PRESENT_READ_ONLY")
    return {
        "symbol": symbol,
        "asset_class": position.get("asset_class") or "unknown",
        "quantity": _decimal_text(position.get("qty") or position.get("quantity")),
        "side": side,
        "average_entry_price": _decimal_text(position.get("avg_entry_price")),
        "current_market_price": _decimal_text(position.get("current_price")),
        "cost_basis": _decimal_text(position.get("cost_basis")),
        "market_value": _decimal_text(position.get("market_value")),
        "unrealized_pnl": _decimal_text(position.get("unrealized_pl")),
        "unrealized_pnl_percent": _decimal_text(position.get("unrealized_plpc")),
        "realized_pnl": None,
        "today_price_change": _difference(position.get("current_price"), position.get("lastday_price")),
        "today_percent_change": _decimal_text(position.get("change_today")),
        "position_age": "UNKNOWN",
        "opened_time": None,
        "latest_fill_time": latest_fill.get("latest_fill_time"),
        "latest_fill_price": _decimal_text(latest_fill.get("latest_fill_price")),
        "open_orders_for_symbol": symbol_orders,
        "open_order_count": len(symbol_orders),
        "fees_status": "UNKNOWN",
        "tca_status": "UNKNOWN",
        "slippage": None,
        "broker_confirmed": True,
        "source": "BROKER_CONFIRMED",
        "oms_reconciliation_status": "BROKER_CONFIRMED_OPEN_ORDER_PRESENT" if symbol_orders else "BROKER_CONFIRMED_NO_OPEN_ORDER",
        "data_freshness_ts": now,
        "tradability_status": "READ_ONLY_PAPER_POSITION",
        "risk_status": "WARN" if warnings else "OK",
        "intelligence": {
            "exposure_percent_of_portfolio": exposure_pct,
            "concentration_warning": "CONCENTRATION_WARNING" in warnings,
            "volatility_range_warning": "UNKNOWN",
            "fee_drag_warning": "UNKNOWN_FEE_DETAIL",
            "slippage_warning": "UNKNOWN_SLIPPAGE_DETAIL",
            "stale_data_warning": False,
            "spread_liquidity_warning": "UNKNOWN",
            "correlation_cluster_warning": "UNKNOWN",
            "moving_floor_status": "UNKNOWN_NOT_EXPOSED_TO_OPERATOR_PORTFOLIO",
            "protective_floor_status": "UNKNOWN_NOT_EXPOSED_TO_OPERATOR_PORTFOLIO",
            "exit_logic_status": "READ_ONLY_NO_MANUAL_EXIT_CONTROL",
            "why_holding": "No DecisionFrame hold evidence is attached to this read-only portfolio snapshot.",
            "blockers_conflicts": warnings,
        },
    }


def build_portfolio_snapshot(
    env: Mapping[str, str],
    *,
    client: ReadOnlyBrokerClient | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    headers = _headers(env)
    if headers is None:
        return _empty_unavailable("MISSING_ALPACA_PAPER_CREDENTIALS")

    base_url = _base_url(env)
    endpoint_truth = alpaca_endpoint_authority(env)
    if base_url == ALPACA_LIVE_ENDPOINT:
        return _empty_unavailable("LIVE_ENDPOINT_BLOCKED", endpoint_authority=endpoint_truth)
    if base_url != ALPACA_PAPER_ENDPOINT:
        return _empty_unavailable("ALPACA_PAPER_ENDPOINT_REQUIRED", endpoint_authority=endpoint_truth)

    broker_client = client or AlpacaPaperReadOnlyClient(base_url=base_url)
    freshness = now or _utc_now()
    try:
        account = broker_client.get_json("/v2/account", headers)
        positions = broker_client.get_json("/v2/positions", headers)
        orders_path = "/v2/orders?" + urllib.parse.urlencode({"status": "open", "limit": "100", "nested": "false"})
        orders = broker_client.get_json(orders_path, headers)
    except Exception as exc:
        return _empty_unavailable(
            _broker_failure_reason(exc),
            detail=exc.__class__.__name__,
            broker_read_attempted=True,
        )

    activities: Any = []
    activities_status = "UNAVAILABLE"
    try:
        activities_path = "/v2/account/activities/FILL?" + urllib.parse.urlencode({"direction": "desc", "page_size": "100"})
        activities = broker_client.get_json(activities_path, headers)
        activities_status = "AVAILABLE"
    except Exception:
        activities = []

    positions_list = positions if isinstance(positions, list) else []
    orders_list = orders if isinstance(orders, list) else []
    open_orders = [_map_order(order) for order in orders_list if isinstance(order, dict) and _active_order(order)]
    latest_fills = _latest_fills_by_symbol(activities)
    account_map = account if isinstance(account, dict) else {}
    equity = _decimal(account_map.get("equity") or account_map.get("portfolio_value"))
    position_rows = [
        _map_position(position, equity=equity, open_orders=open_orders, latest_fills=latest_fills, now=freshness)
        for position in positions_list
        if isinstance(position, dict)
    ]
    largest = max(position_rows, key=lambda item: _decimal(item.get("market_value")) or Decimal("0"), default=None)
    highest_risk = next((position for position in position_rows if position["risk_status"] == "WARN"), largest)
    stale_conflicted = sum(1 for position in position_rows if position["risk_status"] == "WARN")
    total_market_value = sum(
        (_decimal(position.get("market_value")) or Decimal("0")) for position in position_rows
    )
    total_unrealized = sum(
        (_decimal(position.get("unrealized_pnl")) or Decimal("0")) for position in position_rows
    )
    if not isinstance(total_market_value, Decimal):
        total_market_value = Decimal("0")
    if not isinstance(total_unrealized, Decimal):
        total_unrealized = Decimal("0")
    return {
        "source": PORTFOLIO_SOURCE,
        "data_source": "BROKER_CONFIRMED",
        "status": "BROKER_CONFIRMED_EMPTY" if not position_rows else "BROKER_CONFIRMED",
        "unavailable_reason": None,
        "summary": {
            "total_equity": _decimal_text(account_map.get("equity") or account_map.get("portfolio_value")),
            "cash": _decimal_text(account_map.get("cash")),
            "buying_power": _decimal_text(account_map.get("buying_power")),
            "total_market_value": format(total_market_value.normalize(), "f"),
            "total_unrealized_pnl": format(total_unrealized.normalize(), "f"),
            "total_realized_pnl": None,
            "day_pnl": None,
            "gross_exposure": _decimal_text(account_map.get("long_market_value")) or format(total_market_value.copy_abs().normalize(), "f"),
            "net_exposure": _decimal_text(account_map.get("long_market_value")) or format(total_market_value.normalize(), "f"),
            "position_count": len(position_rows),
            "open_order_count": len(open_orders),
            "largest_position": largest["symbol"] if largest else None,
            "highest_risk_position": highest_risk["symbol"] if highest_risk else None,
            "stale_or_conflicted_position_count": stale_conflicted,
            "broker_local_reconciliation_status": "BROKER_CONFIRMED_NO_LOCAL_TRUTH_PROMOTED",
            "activities_status": activities_status,
        },
        "positions": position_rows,
        "open_orders": open_orders,
        "position_intelligence": [
            {
                "symbol": position["symbol"],
                **position["intelligence"],
                "risk_status": position["risk_status"],
                "source": position["source"],
            }
            for position in position_rows
        ],
        "empty": not position_rows,
        "message": "No current PAPER positions." if not position_rows else "Broker-confirmed PAPER positions loaded.",
        "data_freshness_ts": freshness,
        "broker_read_attempted": True,
        "broker_read_occurred": True,
        "paper_endpoint_authority": endpoint_truth,
        "paper_endpoint_only": endpoint_truth["paper_endpoint_only"],
        "paper_endpoint_status": endpoint_truth["status"],
        "paper_endpoint_operator_action": endpoint_truth["operator_action"],
        "broker_mutation_occurred": False,
        "order_submission_occurred": False,
        "cancel_occurred": False,
        "liquidation_occurred": False,
        "live_enabled": False,
        "real_money_enabled": False,
        "secrets_values_exposed": False,
        "raw_secret_values_included": False,
    }
