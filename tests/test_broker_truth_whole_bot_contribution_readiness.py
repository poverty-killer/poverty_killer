from __future__ import annotations

import importlib.util
import inspect
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.brain.recalibrator import Recalibrator
from app.execution.live_read_only_adapter import (
    LiveReadOnlyBrokerAdapter,
    ReadOnlyAdapterConfig,
    ReadOnlyBrokerSnapshot,
)
from app.execution.paper_broker import PaperBroker
from app.portfolio.opportunity_ranking import OpportunityRanker
from app.risk.net_edge_governor import NetEdgeGovernor
from app.risk.reservation_lifecycle_coordinator import ReservationLifecycleCoordinator
from app.risk.trade_efficiency_governor import TradeEfficiencyGovernor
from app.state.hydration_manager import HydrationManager
from app.state.invariant_checker import InvariantChecker
from app.strategies.adaptive_dc import AdaptiveDC
from app.strategies.gamma_front import GammaFrontStrategy
from app.strategies.hedging_flow import HedgingFlow
from app.strategies.liquidity_void import LiquidityVoidStrategy
from app.strategies.moving_floor import TopologicalMovingFloor
from app.strategies.sector_rotation import SectorRotationStrategy
from app.strategies.strategy_vote_adapters import (
    adapt_adaptive_dc_to_vote,
    adapt_gamma_front_to_vote,
    adapt_liquidity_void_to_vote,
    adapt_moving_floor_to_vote,
    adapt_sector_rotation_to_vote,
)
from app.utils.time_utils import now_ns


EXPECTED_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
BROKER_READ_AUTH_ENV = "PK_BOARD_AUTHORIZED_PAPER_BROKER_READ"
BROKER_READ_AUTH_VALUE = "YES_D4_BOARD_AUTHORIZED"
MAX_SNAPSHOT_AGE_NS = 5_000_000_000
ALLOWED_GET_PATHS = frozenset(
    {
        "/v2/account",
        "/v2/positions",
        "/v2/orders",
        "/v2/account/activities",
        "/v2/clock",
    }
)


@dataclass(frozen=True)
class AlpacaEnv:
    base_url: str
    key_id: str
    secret_key: str


@dataclass(frozen=True)
class ReadOnlyNoGoDecision:
    ready: bool
    reason_codes: tuple[str, ...]
    blocks_submit: bool = True
    trading_approval: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalFlatState:
    expected_currency: str = "USD"
    exposures: dict[str, Decimal] = field(default_factory=dict)
    local_open_order_ids: tuple[str, ...] = ()
    active_reservation_client_order_ids: tuple[str, ...] = ()


class AlpacaReadOnlyHttpClient:
    def __init__(self, env: AlpacaEnv) -> None:
        self._env = env
        self.calls: list[tuple[str, str]] = []

    @property
    def base_url(self) -> str:
        return self._env.base_url

    def get_json(self, path: str, query: dict[str, str] | None = None) -> Any:
        self._validate_get(path, query)
        url = f"{self._env.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "APCA-API-KEY-ID": self._env.key_id,
                "APCA-API-SECRET-KEY": self._env.secret_key,
                "Accept": "application/json",
            },
        )
        self.calls.append(("GET", path))
        try:
            with urllib.request.urlopen(request, timeout=10.0) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AssertionError(f"alpaca_read_only_http_error:{exc.code}:{path}:{body[:180]}") from exc

    def get_json_optional(self, path: str, query: dict[str, str] | None = None) -> tuple[Any, str | None]:
        try:
            return self.get_json(path, query), None
        except AssertionError as exc:
            if path == "/v2/account/activities":
                return (), str(exc)
            raise

    def _validate_get(self, path: str, query: dict[str, str] | None) -> None:
        assert self._env.base_url == EXPECTED_PAPER_BASE_URL
        assert self._env.base_url.startswith("https://paper-api.alpaca.markets")
        assert "api.alpaca.markets" not in self._env.base_url.replace("paper-api.alpaca.markets", "")
        assert path in ALLOWED_GET_PATHS
        assert path.startswith("/v2/")
        assert path != "/v2/orders" or (query or {}).get("status") == "open"
        blocked_fragments = ("submit", "cancel", "replace", "close", "liquidate")
        assert not any(fragment in path.lower() for fragment in blocked_fragments)


class AlpacaReadOnlySource:
    def __init__(self, client: AlpacaReadOnlyHttpClient, account: dict[str, Any]) -> None:
        self._client = client
        self._account = account
        self.activities_gap: str | None = None

    def fetch_balances(self):
        return (
            {
                "currency": self._account.get("currency") or "USD",
                "cash": _decimal_or_none(self._account.get("cash")),
                "buying_power": _decimal_or_none(self._account.get("buying_power")),
                "equity": _decimal_or_none(self._account.get("equity")),
                "portfolio_value": _decimal_or_none(self._account.get("portfolio_value")),
                "long_market_value": _decimal_or_none(self._account.get("long_market_value")),
                "short_market_value": _decimal_or_none(self._account.get("short_market_value")),
                "source": "alpaca_paper_account",
            },
        )

    def fetch_positions(self):
        positions = self._client.get_json("/v2/positions")
        _validate_positions_payload(positions)
        return tuple(
            {
                "symbol": item.get("symbol"),
                "instrument_id": item.get("asset_id"),
                "quantity": _decimal_or_none(item.get("qty")),
                "source": "alpaca_paper_positions",
            }
            for item in positions
        )

    def fetch_normalized_open_orders(self):
        orders = self._client.get_json("/v2/orders", {"status": "open", "limit": "50", "nested": "false"})
        assert isinstance(orders, list), "alpaca_open_orders_invalid_shape"
        return tuple(
            {
                "client_order_id": item.get("client_order_id"),
                "broker_order_id": item.get("id"),
                "symbol": item.get("symbol"),
                "remaining_qty": _decimal_or_none(item.get("qty")),
                "status": item.get("status"),
                "source": "alpaca_paper_open_orders",
            }
            for item in orders
        )

    def fetch_fills(self, limit: int = 100):
        activities, gap = self._client.get_json_optional(
            "/v2/account/activities",
            {"activity_types": "FILL", "page_size": str(min(limit, 100))},
        )
        self.activities_gap = gap
        items = activities.get("activities", ()) if isinstance(activities, dict) else activities or ()
        assert isinstance(items, (list, tuple)), "alpaca_activities_invalid_shape"
        return tuple(
            {
                "venue_fill_id": item.get("id"),
                "client_order_id": item.get("client_order_id"),
                "broker_order_id": item.get("order_id"),
                "symbol": item.get("symbol"),
                "quantity": _decimal_or_none(item.get("qty")),
                "fee": _decimal_or_none(item.get("commission") or "0"),
                "source": "alpaca_paper_account_activities",
            }
            for item in items
        )


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _validate_positions_payload(positions: Any) -> None:
    assert isinstance(positions, list), "alpaca_positions_invalid_shape"
    for item in positions:
        assert isinstance(item, dict), "alpaca_position_item_invalid_shape"
        symbol = item.get("symbol")
        qty = item.get("qty")
        assert isinstance(symbol, str) and symbol.strip(), "alpaca_position_missing_symbol"
        assert qty not in (None, ""), "alpaca_position_missing_qty"
        Decimal(str(qty))


def _alpaca_env_or_skip() -> AlpacaEnv:
    base_url = (os.environ.get("APCA_API_BASE_URL") or "").rstrip("/")
    key_id = os.environ.get("APCA_API_KEY_ID") or ""
    secret_key = os.environ.get("APCA_API_SECRET_KEY") or ""
    missing = []
    if not base_url:
        missing.append("APCA_API_BASE_URL")
    if not key_id:
        missing.append("APCA_API_KEY_ID")
    if not secret_key:
        missing.append("APCA_API_SECRET_KEY")
    if missing:
        pytest.skip(f"Alpaca paper read-only env missing: {', '.join(missing)}")
    if base_url != EXPECTED_PAPER_BASE_URL:
        pytest.fail(f"APCA_API_BASE_URL is not exact paper endpoint: {base_url!r}")
    return AlpacaEnv(base_url=base_url, key_id=key_id, secret_key=secret_key)


def _unique_decision(reasons: list[str], details: dict[str, Any] | None = None) -> ReadOnlyNoGoDecision:
    unique = tuple(dict.fromkeys(reasons))
    return ReadOnlyNoGoDecision(
        ready=not unique,
        reason_codes=unique,
        blocks_submit=True,
        trading_approval=False,
        details=details or {},
    )


def classify_read_only_reconciliation(
    snapshot: ReadOnlyBrokerSnapshot,
    local: LocalFlatState,
    *,
    current_ts_ns: int,
) -> ReadOnlyNoGoDecision:
    reasons: list[str] = []
    if not snapshot.account_id or snapshot.account_identity_status != "known":
        reasons.append("account_identity_ambiguous")
    if not snapshot.source or snapshot.environment != "paper":
        reasons.append("broker_source_environment_missing")
    if snapshot.receive_ts_ns is None or snapshot.receive_ts_ns <= 0:
        reasons.append("broker_snapshot_timestamp_missing")
    elif current_ts_ns - snapshot.receive_ts_ns > MAX_SNAPSHOT_AGE_NS:
        reasons.append("broker_snapshot_stale")
    if not snapshot.read_only or snapshot.mutation_allowed:
        reasons.append("broker_snapshot_not_read_only")

    balance = next((item for item in snapshot.balances if item.get("currency") == local.expected_currency), None)
    if balance is None:
        reasons.append("balance_currency_mismatch")
    elif balance.get("cash") is None or balance.get("buying_power") is None or balance.get("equity") is None:
        reasons.append("broker_balance_incomplete")

    broker_position_symbols: set[str] = set()
    for position in snapshot.positions:
        symbol = position.get("symbol")
        qty = position.get("quantity")
        if not symbol or qty is None:
            reasons.append("broker_position_invalid")
            continue
        broker_position_symbols.add(symbol)
        if qty != Decimal("0") and local.exposures.get(symbol, Decimal("0")) != qty:
            reasons.append("broker_position_while_local_flat")
    for symbol, local_qty in local.exposures.items():
        if symbol not in broker_position_symbols and local_qty != Decimal("0"):
            reasons.append("local_position_without_broker_support")

    broker_order_ids: set[str] = set()
    for order in snapshot.open_orders:
        client_order_id = order.get("client_order_id")
        broker_order_id = order.get("broker_order_id")
        if not client_order_id or not broker_order_id:
            reasons.append("broker_open_order_without_local_mapping")
            continue
        broker_order_ids.add(client_order_id)
        if client_order_id not in local.local_open_order_ids:
            reasons.append("broker_open_order_without_local_mapping")
    for local_order_id in local.local_open_order_ids:
        if local_order_id not in broker_order_ids:
            reasons.append("local_open_order_without_broker_support")
    for reservation_id in local.active_reservation_client_order_ids:
        if reservation_id not in broker_order_ids:
            reasons.append("local_reservation_without_broker_open_order")

    return _unique_decision(
        reasons,
        {
            "read_only_reconciliation_evaluated": True,
            "trading_approval_implied": False,
            "positions_count": len(snapshot.positions),
            "open_orders_count": len(snapshot.open_orders),
        },
    )


def _static_snapshot(**overrides: Any) -> ReadOnlyBrokerSnapshot:
    fields = {
        "source": "alpaca",
        "environment": "paper",
        "account_id": "paper-account",
        "account_identity_status": "known",
        "balances": (
            {
                "currency": "USD",
                "cash": Decimal("1000"),
                "buying_power": Decimal("1000"),
                "equity": Decimal("1000"),
            },
        ),
        "positions": (),
        "open_orders": (),
        "recent_fills": (),
        "receive_ts_ns": 1_777_948_800_000_000_000,
        "asof_ts_ns": 1_777_948_800_000_000_000,
        "read_only": True,
        "mutation_allowed": False,
    }
    fields.update(overrides)
    return ReadOnlyBrokerSnapshot(**fields)


@pytest.mark.broker_read
def test_alpaca_paper_read_only_truth_feeds_reconciliation_no_go_classifier():
    if os.environ.get(BROKER_READ_AUTH_ENV) != BROKER_READ_AUTH_VALUE:
        pytest.skip(f"broker read deferred; requires {BROKER_READ_AUTH_ENV}={BROKER_READ_AUTH_VALUE}")
    env = _alpaca_env_or_skip()
    client = AlpacaReadOnlyHttpClient(env)

    account = client.get_json("/v2/account")
    assert isinstance(account, dict), "alpaca_account_invalid_shape"
    assert account.get("id"), "alpaca_account_identity_missing"
    client.get_json("/v2/clock")

    source = AlpacaReadOnlySource(client, account)
    receive_ts_ns = now_ns()
    adapter = LiveReadOnlyBrokerAdapter(
        source,
        ReadOnlyAdapterConfig(
            read_only_enabled=True,
            environment="paper",
            source="alpaca",
            allow_mutation=False,
            board_authorized_production_read=False,
            account_id=account.get("id"),
            credentials_present=True,
            credentials_required_for_call=True,
        ),
    )

    snapshot = adapter.get_exchange_truth_snapshot(
        receive_ts_ns=receive_ts_ns,
        asof_ts_ns=receive_ts_ns,
        require_credentials=True,
        require_account_identity=True,
    )
    decision = classify_read_only_reconciliation(snapshot, LocalFlatState(), current_ts_ns=receive_ts_ns + 1)

    assert client.base_url == EXPECTED_PAPER_BASE_URL
    assert all(method == "GET" for method, _path in client.calls)
    assert {path for _method, path in client.calls}.issubset(ALLOWED_GET_PATHS)
    assert ("GET", "/v2/positions") in client.calls
    assert ("GET", "/v2/orders") in client.calls
    assert snapshot.source == "alpaca"
    assert snapshot.environment == "paper"
    assert snapshot.read_only is True
    assert snapshot.mutation_allowed is False
    assert snapshot.account_identity_status == "known"
    assert snapshot.receive_ts_ns == receive_ts_ns
    assert snapshot.balances
    assert isinstance(snapshot.positions, tuple)
    assert isinstance(snapshot.open_orders, tuple)
    assert isinstance(snapshot.recent_fills, tuple)
    assert decision.details["read_only_reconciliation_evaluated"] is True
    assert decision.trading_approval is False


def test_read_only_reconciliation_adversarial_no_go_cases_without_network():
    current_ts_ns = 1_777_948_800_000_000_001
    clean_flat = classify_read_only_reconciliation(_static_snapshot(), LocalFlatState(), current_ts_ns=current_ts_ns)
    stale = classify_read_only_reconciliation(
        _static_snapshot(receive_ts_ns=current_ts_ns - MAX_SNAPSHOT_AGE_NS - 1),
        LocalFlatState(),
        current_ts_ns=current_ts_ns,
    )
    missing_identity = classify_read_only_reconciliation(
        _static_snapshot(account_id=None, account_identity_status="missing"),
        LocalFlatState(),
        current_ts_ns=current_ts_ns,
    )
    currency_mismatch = classify_read_only_reconciliation(
        _static_snapshot(balances=({"currency": "EUR", "cash": Decimal("100"), "buying_power": Decimal("100"), "equity": Decimal("100")},)),
        LocalFlatState(),
        current_ts_ns=current_ts_ns,
    )
    broker_orphan_order = classify_read_only_reconciliation(
        _static_snapshot(open_orders=({"client_order_id": "c1", "broker_order_id": "b1", "symbol": "ETH/USD"},)),
        LocalFlatState(),
        current_ts_ns=current_ts_ns,
    )
    local_orphan_reservation = classify_read_only_reconciliation(
        _static_snapshot(),
        LocalFlatState(active_reservation_client_order_ids=("c1",)),
        current_ts_ns=current_ts_ns,
    )
    broker_position_local_flat = classify_read_only_reconciliation(
        _static_snapshot(positions=({"symbol": "ETH/USD", "instrument_id": "eth-usd", "quantity": Decimal("0.25")},)),
        LocalFlatState(),
        current_ts_ns=current_ts_ns,
    )

    client = AlpacaReadOnlyHttpClient(AlpacaEnv(EXPECTED_PAPER_BASE_URL, "key", "secret"))

    assert clean_flat.ready is True
    assert clean_flat.trading_approval is False
    assert clean_flat.details["positions_count"] == 0
    assert clean_flat.details["open_orders_count"] == 0
    assert "broker_snapshot_stale" in stale.reason_codes
    assert "account_identity_ambiguous" in missing_identity.reason_codes
    assert "balance_currency_mismatch" in currency_mismatch.reason_codes
    assert "broker_open_order_without_local_mapping" in broker_orphan_order.reason_codes
    assert "local_reservation_without_broker_open_order" in local_orphan_reservation.reason_codes
    assert "broker_position_while_local_flat" in broker_position_local_flat.reason_codes
    with pytest.raises(AssertionError):
        client._validate_get("/v2/orders", {"status": "all"})
    with pytest.raises(AssertionError):
        client._validate_get("/v2/orders/abc/cancel", None)
    with pytest.raises(AssertionError):
        client._validate_get("/v2/account/configurations", None)


def _module_exists(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def whole_bot_contribution_matrix() -> dict[str, tuple[str, ...]]:
    matrix = {
        "active_and_contributing": (
            "ShansCurve/SignalFusion",
            "Entropy",
            "Regime",
            "WhaleFlow",
            "WhaleZone",
            "Insider",
            "Toxicity",
            "PhysicalVerification",
            "StrategyRouter",
            "PaperBroker",
            "TruthKernel",
            "InvariantChecker",
            "HydrationManager",
        ),
        "harness_advisory_proven_not_production_wired": (
            "MovingFloor",
            "HedgingFlow",
            "Recalibrator",
            "OpportunityRanking",
            "GammaFront",
            "AdaptiveDC",
            "SectorRotation",
            "LiquidityVoid",
            "CrossAssetRisk",
            "ReservationLifecycle",
            "LiveReadOnlyAdapter",
        ),
        "passive_evidence_only": (
            "PaperBrokerFeeFillEvidence",
            "FillRecorderEconomicTelemetry",
            "PassiveEconomicTruth25G",
        ),
        "dormant_protected_authority": (
            "NetEdgeGovernor",
            "TradeEfficiencyGovernor",
            "broker_adapter",
            "live_broker",
        ),
        "blocked_pending_evidence": (
            "protective_enforcement_runtime_path",
            "multi_contributor_entry_selection_path",
            "economics_advisory_before_veto_path",
            "live_reservation_lifecycle",
        ),
        "unsafe_to_activate_now": (
            "live_mode",
            "broker_mutation",
            "economics_veto",
            "direct_protective_execution",
        ),
    }
    return {key: tuple(value) for key, value in matrix.items()}


def test_protective_entry_economics_and_whole_bot_readiness_classification():
    protective_surfaces = (
        TopologicalMovingFloor,
        HedgingFlow,
        Recalibrator,
        adapt_moving_floor_to_vote,
    )
    entry_surfaces = (
        OpportunityRanker,
        GammaFrontStrategy,
        AdaptiveDC,
        SectorRotationStrategy,
        LiquidityVoidStrategy,
        adapt_gamma_front_to_vote,
        adapt_adaptive_dc_to_vote,
        adapt_sector_rotation_to_vote,
        adapt_liquidity_void_to_vote,
    )
    economics_surfaces = (NetEdgeGovernor, TradeEfficiencyGovernor)

    forbidden_direct_execution = (
        "broker_adapter",
        "live_broker",
        "submit_order",
        "_execute_signal",
    )
    for surface in protective_surfaces + entry_surfaces + economics_surfaces:
        source = inspect.getsource(surface)
        for token in forbidden_direct_execution:
            assert token not in source

    router_source = Path("app/execution/order_router.py").read_text(encoding="utf-8-sig")
    broker_source = inspect.getsource(PaperBroker)
    assert "NetEdgeGovernor" not in router_source
    assert "TradeEfficiencyGovernor" not in router_source
    assert "NetEdgeGovernor" not in broker_source
    assert "TradeEfficiencyGovernor" not in broker_source

    broker_adapter_source = Path("app/execution/broker_adapter.py").read_text(encoding="utf-8-sig")
    live_broker_source = Path("app/execution/live_broker.py").read_text(encoding="utf-8-sig")
    assert "PRE-INTEGRATION" in broker_adapter_source
    assert "NO IMPLEMENTATION" in broker_adapter_source
    assert "Under construction" in live_broker_source

    readiness = {
        "protective_enforcement_ready": "no",
        "entry_selection_ready": "conditional",
        "economics_advisory_ready": "conditional",
        "economics_veto_ready": "no",
    }
    blockers = {
        "protective": "BLOCKED_FOR_ENFORCEMENT until governed runtime path can block entries, reduce aggression, freeze trading, or raise operator escalation without direct execution.",
        "entry": "No proven production selector consumes all contributors without bypassing Fusion/Router/DecisionCompiler/ExecutionEngine.",
        "economics": "Missing real slippage_bps, arrival_price, expected_fill_price, net_pnl, net_edge, and profitability evidence.",
    }

    assert readiness["protective_enforcement_ready"] == "no"
    assert readiness["entry_selection_ready"] == "conditional"
    assert readiness["economics_advisory_ready"] == "conditional"
    assert readiness["economics_veto_ready"] == "no"
    assert "BLOCKED_FOR_ENFORCEMENT" in blockers["protective"]
    assert "without bypassing" in blockers["entry"]
    assert "slippage_bps" in blockers["economics"]

    required_modules = {
        "app.core.truth_kernel",
        "app.state.invariant_checker",
        "app.state.hydration_manager",
        "app.execution.paper_broker",
        "app.execution.live_read_only_adapter",
        "app.execution.broker_adapter",
        "app.execution.live_broker",
        "app.risk.reservation_lifecycle_coordinator",
    }
    assert all(_module_exists(module_name) for module_name in required_modules)
    assert InvariantChecker is not None
    assert HydrationManager is not None
    assert ReservationLifecycleCoordinator is not None

    matrix = whole_bot_contribution_matrix()
    flattened = {item for items in matrix.values() for item in items}
    for module_name in (
        "MovingFloor",
        "HedgingFlow",
        "Recalibrator",
        "OpportunityRanking",
        "GammaFront",
        "AdaptiveDC",
        "SectorRotation",
        "LiquidityVoid",
        "CrossAssetRisk",
        "NetEdgeGovernor",
        "TradeEfficiencyGovernor",
        "ReservationLifecycle",
        "TruthKernel",
        "InvariantChecker",
        "HydrationManager",
        "PaperBroker",
        "LiveReadOnlyAdapter",
        "broker_adapter",
        "live_broker",
    ):
        assert module_name in flattened or any(module_name in item for item in flattened)
