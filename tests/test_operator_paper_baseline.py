from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.operator_activation.paper_baseline import (
    BASELINE_POLICY_PROTECTED,
    PAPER_BASELINE_DRIFT_REQUIRES_REFRESH,
    PAPER_BASELINE_ENV_PATH,
    PAPER_BASELINE_ENV_POLICY,
    PAPER_BASELINE_ENV_PROTECTED_SYMBOLS,
    PAPER_BASELINE_ENV_REQUIRED,
    PAPER_BASELINE_ENV_SNAPSHOT_HASH,
    PAPER_BASELINE_ENV_SNAPSHOT_ID,
    PAPER_BASELINE_SYMBOL_PROTECTED,
    PREFLIGHT_BLOCKED_BASELINE_ADOPTION_REQUIRED,
    PREFLIGHT_BLOCKED_OPEN_ORDERS,
    PREFLIGHT_READY_WITH_ACCEPTED_EXISTING_POSITIONS,
    accept_existing_position_baseline,
    build_baseline_adoption_state,
    build_paper_baseline_runtime_context,
    evaluate_protected_baseline_trade,
    load_paper_baseline_runtime_context_from_env,
    normalize_baseline_symbol,
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


def _crypto_preflight() -> dict[str, object]:
    return _preflight(
        positions=[
            {"symbol": "BTCUSD", "asset_class": "crypto", "qty": "0.5", "side": "long"},
            {"symbol": "ETHUSD", "asset_class": "crypto", "qty": "2", "side": "long"},
            {"symbol": "SOLUSD", "asset_class": "crypto", "qty": "10", "side": "long"},
        ]
    )


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
    assert sell["reason_code"] == PAPER_BASELINE_SYMBOL_PROTECTED
    assert buy["allowed"] is False
    assert buy["reason_code"] == PAPER_BASELINE_SYMBOL_PROTECTED
    assert unrelated["allowed"] is True
    assert sell["broker_mutation_occurred"] is False


def test_runtime_baseline_context_loads_from_env_and_normalizes_symbols(tmp_path) -> None:
    accepted = accept_existing_position_baseline(_crypto_preflight(), accepted_by="Shan/local operator")
    path = tmp_path / "state" / "operator" / "paper_baseline.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(accepted), encoding="utf-8")
    context = build_paper_baseline_runtime_context(accepted, source_path=path)
    env = context.to_env()

    loaded = load_paper_baseline_runtime_context_from_env(env)

    assert loaded.baseline_loaded is True
    assert loaded.policy == BASELINE_POLICY_PROTECTED
    assert loaded.same_symbol_baseline_guard_active is True
    assert loaded.protected_symbols_normalized == ("BTCUSD", "ETHUSD", "SOLUSD")
    assert env[PAPER_BASELINE_ENV_REQUIRED] == "1"
    assert env[PAPER_BASELINE_ENV_PATH] == str(path)
    assert env[PAPER_BASELINE_ENV_SNAPSHOT_ID] == accepted["baseline_snapshot_id"]
    assert env[PAPER_BASELINE_ENV_SNAPSHOT_HASH] == accepted["snapshot_hash"]
    assert env[PAPER_BASELINE_ENV_POLICY] == BASELINE_POLICY_PROTECTED
    assert env[PAPER_BASELINE_ENV_PROTECTED_SYMBOLS] == "BTCUSD,ETHUSD,SOLUSD"


def test_symbol_normalization_matches_slash_and_case_variants() -> None:
    assert normalize_baseline_symbol("BTC/USD") == "BTCUSD"
    assert normalize_baseline_symbol("btcusd") == "BTCUSD"
    assert normalize_baseline_symbol("ETH-USD") == "ETHUSD"
    assert normalize_baseline_symbol("sol_usd") == "SOLUSD"


def test_runtime_context_blocks_buy_and_sell_for_protected_symbol_without_signal_metadata() -> None:
    accepted = accept_existing_position_baseline(_crypto_preflight(), accepted_by="Shan/local operator")
    context = build_paper_baseline_runtime_context(accepted, source_path="state/operator/paper_baseline.json").to_dict()
    config = SimpleNamespace(
        broker_mode="paper",
        preferred_trading_portal="alpaca_paper",
        allow_portal_fallback=False,
        paper_baseline_runtime_context=context,
    )
    runtime = SimpleNamespace(last_price=Decimal("100"))

    buy = _build_pre_trade_guardrail_verdict(
        config=config,
        symbol="BTC/USD",
        signal=SimpleNamespace(side="buy", quantity=Decimal("1"), metadata={}),
        runtime=runtime,
        is_attack=False,
    )
    sell = _build_pre_trade_guardrail_verdict(
        config=config,
        symbol="ethusd",
        signal=SimpleNamespace(side="sell", quantity=Decimal("1"), metadata={}),
        runtime=runtime,
        is_attack=False,
    )

    assert buy["verdict"] == "BLOCK"
    assert sell["verdict"] == "BLOCK"
    assert PAPER_BASELINE_SYMBOL_PROTECTED in buy["reason_codes"]
    assert PAPER_BASELINE_SYMBOL_PROTECTED in sell["reason_codes"]
    assert buy["mutation_permitted"] is False
    assert sell["mutation_permitted"] is False
    assert buy["module_evidence"][0]["details"]["normalized_symbol"] == "BTCUSD"


def test_runtime_context_does_not_baseline_block_unprotected_symbol() -> None:
    accepted = accept_existing_position_baseline(_crypto_preflight(), accepted_by="Shan/local operator")
    context = build_paper_baseline_runtime_context(accepted, source_path="state/operator/paper_baseline.json").to_dict()
    verdict = _build_pre_trade_guardrail_verdict(
        config=SimpleNamespace(
            broker_mode="paper",
            preferred_trading_portal="alpaca_paper",
            allow_portal_fallback=False,
            paper_baseline_runtime_context=context,
        ),
        symbol="MSFT",
        signal=SimpleNamespace(side="buy", quantity=Decimal("1"), metadata={"quote_fresh": True}),
        runtime=SimpleNamespace(last_price=Decimal("100")),
        is_attack=False,
    )

    assert PAPER_BASELINE_SYMBOL_PROTECTED not in verdict["reason_codes"]


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
    assert PAPER_BASELINE_SYMBOL_PROTECTED in verdict["reason_codes"]
    assert verdict["module_evidence"][0]["module"] == "paper_baseline_protection"
