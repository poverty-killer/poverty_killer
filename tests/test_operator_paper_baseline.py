from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

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
from app.operator_credentials.store import ALPACA_PAPER_ENV_PATH_ENV_KEY, LocalCredentialStore
from app.main_loop import _build_pre_trade_guardrail_verdict


@pytest.fixture(autouse=True)
def _isolated_canonical_paper_env(monkeypatch, tmp_path):
    path = tmp_path / "canonical_alpaca_paper.env"
    monkeypatch.setenv(ALPACA_PAPER_ENV_PATH_ENV_KEY, str(path))
    return path


def _account_pin_ok_assertion(_env=None) -> dict[str, object]:
    return {
        "source": "TEST_ACCOUNT_PIN",
        "status": "PASS",
        "reason_code": "ALPACA_PAPER_ACCOUNT_PIN_OK",
        "detail": "offline unit test account pin is pre-proven",
        "expected_suffix": "045ded",
        "actual_suffix": "045ded",
        "paper_account_pinned": True,
        "broker_read_attempted": True,
        "broker_read_occurred": True,
        "account_request_occurred": True,
        "broker_mutation_occurred": False,
        "order_submission_occurred": False,
        "cancel_occurred": False,
        "liquidation_occurred": False,
        "live_enabled": False,
        "real_money_enabled": False,
        "secrets_values_exposed": False,
    }


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


class _PaperReadClient:
    def __init__(self, snapshot: dict[str, object]) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path, headers):
        assert headers["APCA-API-KEY-ID"] == "test-paper-key"
        self.calls.append(("GET", path))
        if path == "/v2/account":
            return dict(self.snapshot["account"])
        if path == "/v2/positions":
            return list(self.snapshot.get("positions") or [])
        if path.startswith("/v2/orders?"):
            return list(self.snapshot.get("open_orders") or [])
        raise AssertionError(f"unexpected broker path: {path}")


def _paper_read_confirmations() -> dict[str, object]:
    return {
        "mode": "PAPER",
        "live": False,
        "real_money": False,
        "confirm_paper_read_only": True,
        "confirm_account_positions_orders_get_only": True,
        "confirm_no_broker_mutation": True,
        "confirm_process_scoped_authorization": True,
    }


def _preflight(
    *,
    positions: list[dict[str, object]] | None = None,
    open_orders: list[dict[str, object]] | None = None,
    account_id: str = "paper-account-045ded",
) -> dict[str, object]:
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
            "id": account_id,
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


def _crypto_preflight(*, account_id: str = "paper-account-045ded") -> dict[str, object]:
    return _preflight(
        account_id=account_id,
        positions=[
            {"symbol": "BTCUSD", "asset_class": "crypto", "qty": "0.5", "side": "long"},
            {"symbol": "ETHUSD", "asset_class": "crypto", "qty": "2", "side": "long"},
            {"symbol": "SOLUSD", "asset_class": "crypto", "qty": "10", "side": "long"},
        ]
    )


def _funded_account_crypto_preflight() -> dict[str, object]:
    return _preflight(
        positions=[
            {"symbol": "AVAXUSD", "asset_class": "crypto", "qty": "10", "side": "long"},
            {"symbol": "ETHUSD", "asset_class": "crypto", "qty": "2", "side": "long"},
            {"symbol": "LINKUSD", "asset_class": "crypto", "qty": "25", "side": "long"},
            {"symbol": "SOLUSD", "asset_class": "crypto", "qty": "8", "side": "long"},
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
    assert "paper-account-045ded" not in str(accepted)
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


def test_operator_baseline_accept_is_local_only_and_does_not_bypass_broker_preflight(tmp_path) -> None:
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
    assert readiness["paper_credential_setup"]["preflight_gate"]["account_check_status"] == "blocked"
    assert "paper_read_only_preflight_gate" in readiness["reason_codes"]
    assert "paper_baseline_position_aware_policy" not in readiness["reason_codes"]
    checks = {row["check_id"]: row for row in readiness["checks"]}
    assert checks["paper_read_only_preflight_gate"]["status"] == "DEGRADED"
    assert readiness["paper_start_allowed"] is False
    assert readiness["protected_same_symbol_guard_active"] is True
    assert readiness["broker_mutation_occurred"] is False


def test_paper_control_state_allows_protected_position_baseline_when_runtime_guard_is_loaded(tmp_path, monkeypatch) -> None:
    paper_env = tmp_path / "canonical_alpaca_paper.env"
    paper_env.write_text(
        "APCA_API_BASE_URL=https://paper-api.alpaca.markets\nAPCA_API_KEY_ID=test-paper-key\nAPCA_API_SECRET_KEY=test-paper-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(ALPACA_PAPER_ENV_PATH_ENV_KEY, str(paper_env))
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    snapshot = _preflight()
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
        portfolio_client=_PaperReadClient(snapshot),
        account_identity_checker=_account_pin_ok_assertion,
    )
    app = create_operator_app(provider=provider)
    accepted = _endpoint(app, "/operator/paper-baseline/accept", "POST")(
        {"preflight_snapshot": snapshot, "policy": BASELINE_POLICY_PROTECTED, "accepted_by_operator": "Shan/local operator"}
    )
    verified = _endpoint(app, "/operator/intent/paper/verify-readonly", "POST")(_paper_read_confirmations())

    control = asyncio.run(_endpoint(app, "/operator/paper-control-state")())
    launch = _endpoint(app, "/operator/launch-readiness")()

    assert accepted["accepted"] is True
    assert verified["allowed"] is True
    assert verified["broker_read_occurred"] is True
    assert verified["broker_mutation_occurred"] is False
    assert control["paper_start_allowed"] is True
    assert control["dominant_blocker"] == "READY_FOR_BOUNDED_PAPER"
    assert "paper_baseline_position_aware_policy" not in control["reason_codes"]
    assert control["baseline_position_aware_policy_blocked"] is False
    assert control["baseline_position_aware_policy_guarded"] is True
    assert launch["paper_start_allowed"] is True
    assert launch["final_launch_readiness"] == "READY_FOR_BOUNDED_PAPER"
    assert "paper_baseline_position_aware_policy" not in launch["reason_codes"]
    assert launch["protected_same_symbol_guard_active"] is True
    assert control["broker_call_occurred"] is False
    assert control["broker_mutation_occurred"] is False


def test_supervisor_baseline_context_uses_configured_operator_state_dir(tmp_path, monkeypatch) -> None:
    paper_env = tmp_path / "canonical_alpaca_paper.env"
    paper_env.write_text(
        "APCA_API_BASE_URL=https://paper-api.alpaca.markets\nAPCA_API_KEY_ID=test-paper-key\nAPCA_API_SECRET_KEY=test-paper-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(ALPACA_PAPER_ENV_PATH_ENV_KEY, str(paper_env))
    repo_state = tmp_path / "state" / "operator"
    configured_state = tmp_path / "configured_operator_state"
    repo_state.mkdir(parents=True)
    configured_state.mkdir(parents=True)
    stale = accept_existing_position_baseline(_crypto_preflight(), accepted_by="stale wrong-path baseline")
    current = accept_existing_position_baseline(_preflight(), accepted_by="configured operator state baseline")
    (repo_state / "paper_baseline.json").write_text(json.dumps(stale), encoding="utf-8")
    (configured_state / "paper_baseline.json").write_text(json.dumps(current), encoding="utf-8")
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({"PK_OPERATOR_STATE_DIR": str(configured_state)}, repo_root=tmp_path),
        provider_env={},
        credential_store=LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json"),
        account_identity_checker=_account_pin_ok_assertion,
    )
    app = create_operator_app(provider=provider)

    launch = _endpoint(app, "/operator/launch-readiness")()
    control = asyncio.run(_endpoint(app, "/operator/paper-control-state")())

    assert launch["protected_symbols_count"] == 1
    assert launch["paper_baseline_runtime_context"]["protected_symbols_normalized"] == ["AAPL"]
    assert control["baseline_runtime_context"]["protected_symbols_normalized"] == ["AAPL"]
    assert "BTCUSD" not in str(launch["paper_baseline_runtime_context"])


def test_stale_baseline_from_wrong_account_blocks_paper_readiness(tmp_path, monkeypatch) -> None:
    paper_env = tmp_path / "canonical_alpaca_paper.env"
    paper_env.write_text(
        "APCA_API_BASE_URL=https://paper-api.alpaca.markets\nAPCA_API_KEY_ID=test-paper-key\nAPCA_API_SECRET_KEY=test-paper-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(ALPACA_PAPER_ENV_PATH_ENV_KEY, str(paper_env))
    repo_state = tmp_path / "state" / "operator"
    repo_state.mkdir(parents=True)
    stale = accept_existing_position_baseline(
        _crypto_preflight(account_id="paper-account-104e2a"),
        accepted_by="stale wrong-account baseline",
    )
    (repo_state / "paper_baseline.json").write_text(json.dumps(stale), encoding="utf-8")
    current = _crypto_preflight()
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json"),
        portfolio_client=_PaperReadClient(current),
        account_identity_checker=_account_pin_ok_assertion,
    )
    app = create_operator_app(provider=provider)
    verified = _endpoint(app, "/operator/intent/paper/verify-readonly", "POST")(_paper_read_confirmations())

    launch = _endpoint(app, "/operator/launch-readiness")()
    control = asyncio.run(_endpoint(app, "/operator/paper-control-state")())

    assert verified["allowed"] is False
    assert verified["reason_code"] == "PAPER_BASELINE_ACCOUNT_PIN_MISMATCH"
    assert launch["paper_account_pinned"] is True
    assert launch["final_launch_readiness"] == "BLOCKED"
    assert "paper_baseline_account_pin_mismatch" in launch["reason_codes"]
    setup = launch["paper_credential_setup"]["preflight_gate"]
    assert setup["read_only_preflight_authorized"] is True
    assert setup["broker_verification_passed"] is False
    assert setup["status_label"] == "PAPER verification blocked"
    assert setup["last_preflight_result"] == "PAPER_BASELINE_ACCOUNT_PIN_MISMATCH"
    assert launch["run_paper_operator_state"]["broker_truth"]["status"] == "BROKER_CONFIRMED_START_BLOCKED"
    assert launch["run_paper_operator_state"]["broker_truth"]["broker_confirmed"] is True
    assert control["paper_start_allowed"] is False
    assert "PAPER_BASELINE_ACCOUNT_PIN_MISMATCH" in control["reason_codes"]


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


def test_funded_account_protected_symbols_refuse_new_entries_before_route() -> None:
    accepted = accept_existing_position_baseline(
        _funded_account_crypto_preflight(),
        accepted_by="Shan/local operator",
    )
    context = build_paper_baseline_runtime_context(
        accepted,
        source_path="durable/operator/paper_baseline.json",
    ).to_dict()
    config = SimpleNamespace(
        broker_mode="paper",
        preferred_trading_portal="alpaca_paper",
        allow_portal_fallback=False,
        paper_baseline_runtime_context=context,
    )

    for symbol in ("AVAX/USD", "ETH/USD", "LINK/USD", "SOL/USD"):
        verdict = _build_pre_trade_guardrail_verdict(
            config=config,
            symbol=symbol,
            signal=SimpleNamespace(side="buy", quantity=Decimal("1"), metadata={}),
            runtime=SimpleNamespace(last_price=Decimal("100")),
            is_attack=False,
        )

        assert verdict["verdict"] == "BLOCK", symbol
        assert verdict["route_permitted"] is False, symbol
        assert verdict["mutation_permitted"] is False, symbol
        assert PAPER_BASELINE_SYMBOL_PROTECTED in verdict["reason_codes"], symbol


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
        symbol="LTC/USD",
        signal=SimpleNamespace(
            side="buy",
            quantity=Decimal("1"),
            metadata={
                "quote_fresh": True,
                "stale_data_observation": {
                    "current_ts_ns": 1_777_948_800_000_000_000,
                    "exchange_ts_ns": 1_777_948_800_000_000_000,
                    "local_received_ts_ns": 1_777_948_800_000_000_000,
                },
            },
        ),
        runtime=SimpleNamespace(last_price=Decimal("100")),
        is_attack=False,
    )

    assert PAPER_BASELINE_SYMBOL_PROTECTED not in verdict["reason_codes"]
    assert verdict["verdict"] == "ALLOW"
    assert verdict["route_permitted"] is True
    assert verdict["mutation_permitted"] is True
    assert verdict["capability_identity"]["portal_name"] == "alpaca_paper"


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
