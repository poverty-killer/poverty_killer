from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.operator_activation.paper_baseline import (
    BASELINE_POLICY_PROTECTED,
    PAPER_BASELINE_DRIFT_REQUIRES_REFRESH,
    PREFLIGHT_BLOCKED_BASELINE_ADOPTION_REQUIRED,
    PREFLIGHT_BLOCKED_OPEN_ORDERS,
    PREFLIGHT_READY_WITH_ACCEPTED_EXISTING_POSITIONS,
    accept_existing_position_baseline,
    build_baseline_adoption_state,
    evaluate_protected_baseline_trade,
)
from app.operator_credentials.store import LocalCredentialStore
from app.main_loop import _build_pre_trade_guardrail_verdict


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def _preflight(*, positions: list[dict[str, object]] | None = None, open_orders: list[dict[str, object]] | None = None) -> dict[str, object]:
    rows = positions if positions is not None else [
        {
            "symbol": "AAPL",
            "asset_class": "us_equity",
            "qty": "10",
            "side": "long",
            "avg_entry_price": "100",
            "cost_basis": "1000",
            "market_value": "1100",
            "current_price": "110",
            "unrealized_pl": "100",
            "unrealized_plpc": "0.10",
        }
    ]
    orders = open_orders if open_orders is not None else []
    return {
        "endpoint_family": "paper",
        "account": {
            "id": "full-account-id-123456",
            "status": "ACTIVE",
            "equity": "50000",
            "buying_power": "75000",
            "currency": "USD",
            "trading_blocked": False,
            "account_blocked": False,
            "transfers_blocked": False,
            "pattern_day_trader": False,
        },
        "open_order_count": len(orders),
        "open_orders": orders,
        "position_count": len(rows),
        "positions": rows,
    }


def test_existing_positions_without_baseline_require_adoption_not_reset() -> None:
    state = build_baseline_adoption_state(current_snapshot=_preflight())

    assert state["status"] == PREFLIGHT_BLOCKED_BASELINE_ADOPTION_REQUIRED
    assert state["decision"] == "PAPER_BASELINE_ADOPTION_REQUIRED"
    assert state["start_ready"] is False
    assert "baseline adoption" in state["reason"].lower()
    assert "Accept current positions" in state["next_safe_action"]
    assert state["broker_mutation_occurred"] is False
    assert state["alpaca_network_call_occurred"] is False


def test_accepted_protected_baseline_allows_position_aware_preflight_state() -> None:
    accepted = accept_existing_position_baseline(_preflight(), accepted_by="Shan/local operator")
    state = build_baseline_adoption_state(current_snapshot=_preflight(), accepted_baseline=accepted)

    assert accepted["accepted"] is True
    assert accepted["policy"] == BASELINE_POLICY_PROTECTED
    assert accepted["baseline_snapshot"]["account"]["account_id"].startswith("redacted_suffix:")
    assert "full-account-id-123456" not in str(accepted)
    assert state["status"] == PREFLIGHT_READY_WITH_ACCEPTED_EXISTING_POSITIONS
    assert state["decision"] == "PREFLIGHT_READY_FOR_SHORT_PAPER_SMOKE"
    assert state["start_ready"] is True
    assert state["pnl_attribution"]["baseline_account_equity"] == "50000"
    assert state["pnl_attribution"]["baseline_positions_value"] == "1100"
    assert state["pnl_attribution"]["clean_baseline_claimed"] is False
    assert "baseline carry" in state["pnl_attribution"]["baseline_carry_pnl_label"]


def test_open_orders_still_block_without_cancel_suggestion() -> None:
    state = build_baseline_adoption_state(
        current_snapshot=_preflight(open_orders=[{"id": "order-1", "symbol": "AAPL", "side": "buy", "qty": "1", "status": "new"}])
    )

    assert state["status"] == PREFLIGHT_BLOCKED_OPEN_ORDERS
    assert state["start_ready"] is False
    assert "No cancellation is authorized" in state["reason"]
    assert state["broker_mutation_occurred"] is False


def test_baseline_drift_requires_fresh_read_only_preflight() -> None:
    accepted = accept_existing_position_baseline(_preflight(), accepted_by="Shan/local operator")
    drifted = _preflight(positions=[{"symbol": "AAPL", "asset_class": "us_equity", "qty": "9", "side": "long"}])

    state = build_baseline_adoption_state(current_snapshot=drifted, accepted_baseline=accepted)

    assert state["status"] == PAPER_BASELINE_DRIFT_REQUIRES_REFRESH
    assert state["start_ready"] is False
    assert "refresh read-only preflight" in state["reason"]


def test_operator_baseline_accept_endpoint_is_local_only_and_readiness_uses_it(tmp_path) -> None:
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider("alpaca_paper", {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"})
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    app = create_operator_app(provider=provider)

    accepted = _endpoint(app, "/operator/paper-baseline/accept", "POST")(
        {"preflight_snapshot": _preflight(), "policy": BASELINE_POLICY_PROTECTED, "accepted_by_operator": "Shan/local operator"}
    )
    baseline = _endpoint(app, "/operator/paper-baseline")()
    readiness = _endpoint(app, "/operator/launch-readiness")()

    assert accepted["accepted"] is True
    assert accepted["alpaca_network_call_occurred"] is False
    assert accepted["broker_mutation_occurred"] is False
    assert accepted["order_submission_occurred"] is False
    assert accepted["cancel_occurred"] is False
    assert accepted["liquidation_occurred"] is False
    assert baseline["status"] == PREFLIGHT_READY_WITH_ACCEPTED_EXISTING_POSITIONS
    assert readiness["paper_credential_setup"]["preflight_gate"]["account_check_status"] == "accepted_existing_positions"
    assert "paper_read_only_preflight_gate" not in readiness["reason_codes"]
    assert "paper_baseline_position_aware_policy" in readiness["reason_codes"]
    assert readiness["broker_mutation_occurred"] is False


def test_protected_baseline_blocks_same_symbol_trading_without_lot_tracking() -> None:
    accepted = accept_existing_position_baseline(_preflight(), accepted_by="Shan/local operator")

    sell = evaluate_protected_baseline_trade(
        symbol="AAPL",
        side="sell",
        requested_qty="10",
        accepted_baseline=accepted,
    )
    buy = evaluate_protected_baseline_trade(
        symbol="AAPL",
        side="buy",
        requested_qty="1",
        accepted_baseline=accepted,
    )
    unrelated = evaluate_protected_baseline_trade(
        symbol="MSFT",
        side="buy",
        requested_qty="1",
        accepted_baseline=accepted,
    )

    assert sell["allowed"] is False
    assert sell["reason_code"] == "BASELINE_PROTECTED_SAME_SYMBOL_BLOCKED"
    assert buy["allowed"] is False
    assert buy["reason_code"] == "BASELINE_PROTECTED_SAME_SYMBOL_BLOCKED"
    assert unrelated["allowed"] is True
    assert sell["broker_mutation_occurred"] is False


def test_main_loop_pre_trade_guard_blocks_protected_baseline_sell_before_route() -> None:
    accepted = accept_existing_position_baseline(_preflight(), accepted_by="Shan/local operator")
    signal = SimpleNamespace(
        side="sell",
        quantity=Decimal("10"),
        metadata={
            "existing_positions": [{"symbol": "AAPL", "quantity": "10"}],
            "accepted_paper_baseline": accepted,
        },
    )
    runtime = SimpleNamespace(last_price=Decimal("110"))
    config = SimpleNamespace(broker_mode="paper", preferred_trading_portal="alpaca_paper", allow_portal_fallback=False)

    verdict = _build_pre_trade_guardrail_verdict(
        config=config,
        symbol="AAPL",
        signal=signal,
        runtime=runtime,
        is_attack=False,
    )

    assert verdict["verdict"] == "BLOCK"
    assert verdict["mutation_permitted"] is False
    assert "BASELINE_PROTECTED_SAME_SYMBOL_BLOCKED" in verdict["reason_codes"]
    assert verdict["module_evidence"][0]["module"] == "paper_baseline_protection"
