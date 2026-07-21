from __future__ import annotations

import ast
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.core.authority_graph import authority_graph_summary
from app.core.decision_frame import resolve_active_threshold_profile
from app.execution.alpaca_paper_adapter import AlpacaPaperBrokerAdapter
from app.execution.broker_gateway import BrokerGatewayError, BrokerOrderSubmitRequest
from app.market.capability_registry import _alpaca_crypto_capability
from app.operator_credentials.store import ALPACA_PAPER_EXPECTED_ACCOUNT_SUFFIX


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "paper_true_capability_stage0.json"

ACTIVATION_STATES = {
    "IMPLEMENTED_OFFLINE",
    "OBSERVE_ONLY",
    "MOCKED_EXECUTION_PROVEN",
    "BROKER_READ_PROVEN",
    "BOUNDED_PAPER_PROVEN",
}

INVARIANT_IDS = {
    "PAPER_ENDPOINT_ONLY",
    "ACCOUNT_PIN_BEFORE_ORDER_ONE",
    "LIVE_MODE_DISABLED",
    "REAL_MONEY_DISABLED",
    "NO_NAKED_OR_SHORT_SELL",
    "NO_MANUAL_TRADE_CONTROLS",
    "MARKET_TRUTH_FRESHNESS_HARD",
    "RISK_ADMISSION_HARD",
    "NET_EDGE_HARD",
    "POSITION_SIZING_HARD",
    "ORDER_TTL_HARD",
    "OMS_AUTHORITY_HARD",
    "RECONCILIATION_HARD_NO_FAKE_FILL",
    "GOVERNED_STOP_ZERO_BROKER_MUTATION",
    "SOVEREIGN_EXECUTION_GUARD_DORMANT",
    "DEFAULT_THRESHOLDS_UNCHANGED",
    "NO_READINESS_FROM_LOWER_PROOF_RUNG",
}

FORBIDDEN_SECRET_KEYS = {
    "account_id",
    "api_key",
    "api_key_id",
    "api_secret",
    "api_secret_key",
    "authorization",
    "broker_order_id",
    "client_order_id",
    "credential_value",
    "position_quantity",
    "secret",
    "secret_key",
    "token",
}


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _record(fixture: dict[str, Any], kind: str) -> dict[str, Any]:
    matches = [item for item in fixture["records"] if item["record_kind"] == kind]
    assert len(matches) == 1, f"expected exactly one {kind!r} record"
    return matches[0]


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).lower()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _assert_test_node_exists(node_id: str) -> None:
    parts = node_id.split("::")
    assert len(parts) >= 2, f"node id does not name a test: {node_id}"
    relative_path = Path(*parts[0].split("/"))
    test_path = ROOT / relative_path
    assert test_path.is_file(), f"missing test file for invariant: {node_id}"

    scope = ast.parse(test_path.read_text(encoding="utf-8"), filename=str(test_path)).body
    for index, name in enumerate(parts[1:]):
        candidates = [
            item
            for item in scope
            if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == name
        ]
        assert len(candidates) == 1, f"missing or ambiguous test node: {node_id}"
        found = candidates[0]
        if index < len(parts[1:]) - 1:
            assert isinstance(found, ast.ClassDef), f"invalid nested test node: {node_id}"
            scope = found.body


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_fixture_is_sanitized_deterministic_and_not_current_authority():
    fixture = _load_fixture()
    provenance = fixture["provenance"]

    assert fixture["schema_version"] == "paper-true-capability-stage0-v1"
    assert provenance["historical"] is True
    assert provenance["sanitized"] is True
    assert provenance["deterministic"] is True
    assert provenance["executable_input"] is False
    assert provenance["current_runtime_truth"] is False
    assert provenance["current_broker_truth"] is False
    assert provenance["current_readiness_truth"] is False
    assert provenance["source_artifact_relative"] == (
        "logs/paper_runs/bounded_paper_20260717_182808.out.log"
    )
    assert not Path(provenance["source_artifact_relative"]).is_absolute()
    assert "tmp" not in Path(provenance["source_artifact_relative"]).parts
    assert provenance["source_sha256"] == (
        "335a67411bac595b2d5928a5d9e4fee06d2bd4d64e88c14969e8caafcd098240"
    )
    assert provenance["source_size_bytes"] == 106_512_681

    serialized = json.dumps(fixture, sort_keys=True).lower()
    assert "apca_api_key_id" not in serialized
    assert "apca_api_secret_key" not in serialized
    assert "paper-account-" not in serialized
    assert "c:\\tmp" not in serialized
    assert FORBIDDEN_SECRET_KEYS.isdisjoint(set(_walk_keys(fixture)))

    historical_suite = fixture["historical_suite_baseline"]
    assert historical_suite == {
        "result": "1820 passed, 14 skipped, 0 failed",
        "passed": 1820,
        "skipped": 14,
        "failed": 0,
        "rerun_at_stage_entry": False,
        "proof_source": "reports/codex_handoff_latest.md",
        "current_suite_truth": False,
    }


def test_fixture_preserves_candidate_causal_guard_shutdown_and_reconciliation_truth():
    fixture = _load_fixture()
    assert {item["record_kind"] for item in fixture["records"]} == {
        "candidate_summary",
        "causal_age_examples",
        "protected_baseline_summary",
        "stale_guard_summary",
        "no_trade_mutation_summary",
        "shutdown_summary",
        "final_reconciliation_summary",
    }

    candidates = _record(fixture, "candidate_summary")
    assert candidates["decision_path_candidate_count"] == 80
    assert candidates["economically_admissible_count"] == 80
    assert sum(candidates["terminal_outcomes"].values()) == 80
    assert candidates["terminal_outcomes"] == {
        "PAPER_BASELINE_SYMBOL_PROTECTED": 50,
        "BEARISH_NO_LONG": 15,
        "STALE_DATA_GUARD_ABSOLUTE_DRIFT_LIMIT_BREACH": 13,
        "STALE_DATA_GUARD_SAFE_MODE": 2,
    }
    assert candidates["submitted_count"] == 0

    causal = _record(fixture, "causal_age_examples")
    assert causal["normalization_applied"] is False
    assert [(item["module"], item["age_ns"]) for item in causal["examples"]] == [
        ("Shans Curve", -84_711_522_000),
        ("Regime Detector", -95_000_000_000),
    ]
    assert all(item["age_ns"] < 0 for item in causal["examples"])
    assert all(
        item["stage0_classification"] == "FUTURE_DATED_CAUSAL_CONTAMINATION"
        for item in causal["examples"]
    )

    protected = _record(fixture, "protected_baseline_summary")
    assert protected["refusal_count"] == 50
    assert protected["protected_symbols"] == ["AVAX/USD", "ETH/USD", "LINK/USD", "SOL/USD"]
    assert protected["guard_bypassed"] is False

    stale = _record(fixture, "stale_guard_summary")
    assert stale["absolute_drift_limit_breach_count"] == 13
    assert stale["safe_mode_count"] == 2
    assert stale["route_permitted_count"] == 0
    assert stale["guard_bypassed"] is False

    mutation = _record(fixture, "no_trade_mutation_summary")
    assert mutation["iterations"] == 492
    assert mutation["watched_symbol_count"] == 6
    for key in (
        "submitted_count",
        "order_post_attempted",
        "order_post_authorized",
        "order_post_acknowledged",
        "order_delete_count",
        "cancel_count",
        "replace_count",
        "sell_count",
        "rebalance_count",
        "broker_mutation_count",
        "current_open_order_count_at_reconciliation",
    ):
        assert mutation[key] == 0, key

    shutdown = _record(fixture, "shutdown_summary")
    assert shutdown["reason_code"] == "BOUNDED_DURATION_EXPIRED_NO_FLATTEN"
    assert shutdown["bounded_duration_seconds"] == 14_400
    assert shutdown["bounded_duration_elapsed"] is True
    assert shutdown["shutdown_complete"] is True
    assert shutdown["positions_preserved"] is True
    assert shutdown["flatten_requested"] is False
    assert shutdown["manual_trade_control_used"] is False
    assert shutdown["final_reconciliation_required"] is True

    reconciliation = _record(fixture, "final_reconciliation_summary")
    assert reconciliation["performed"] is True
    assert reconciliation["account_status"] == "ACTIVE"
    assert reconciliation["expected_account_suffix"] == "045ded"
    assert reconciliation["actual_account_suffix"] == "045ded"
    assert reconciliation["position_count"] == 4
    assert reconciliation["position_symbols"] == ["AVAX/USD", "ETH/USD", "LINK/USD", "SOL/USD"]
    assert reconciliation["broker_open_order_count"] == 0
    assert reconciliation["local_open_order_count"] == 0
    assert reconciliation["unknown_order_count"] == 0
    assert reconciliation["conflict_count"] == 0
    assert reconciliation["run_broker_mutation_count"] == 0
    assert reconciliation["historical_broker_filled_order_count_observed"] == 55
    assert reconciliation["fill_hydration_attempted_count"] == 92
    assert reconciliation["fill_hydration_hydrated_count"] == 0
    assert reconciliation["fill_hydration_missing_count"] == 92


def test_activation_matrix_uses_only_frozen_states_and_grants_no_authority():
    fixture = _load_fixture()
    definitions = fixture["activation_state_definitions"]
    matrix = fixture["activation_matrix"]

    assert set(definitions) == ACTIVATION_STATES
    assert {item["state"] for item in matrix} == ACTIVATION_STATES
    assert len(matrix) == len(ACTIVATION_STATES)
    for item in matrix:
        assert item["state"] in ACTIVATION_STATES
        assert item["proof_source"]
        assert item["proof_summary"]
        assert item["limitation"]
        assert item["current_activation_authority"] is False
        assert item["paper_start_authority"] is False
        assert item["broker_mutation_authority"] is False
        assert item["live_authority"] is False

    by_state = {item["state"]: item for item in matrix}
    assert "not an external Alpaca fill" in by_state["MOCKED_EXECUTION_PROVEN"]["limitation"]
    assert "Historical point-in-time truth" in by_state["BROKER_READ_PROVEN"]["limitation"]
    assert "not external order" in by_state["BOUNDED_PAPER_PROVEN"]["limitation"]


def test_invariant_manifest_references_existing_negative_tests():
    fixture = _load_fixture()
    manifest = fixture["invariant_manifest"]

    assert {item["invariant_id"] for item in manifest} == INVARIANT_IDS
    assert len(manifest) == len(INVARIANT_IDS)
    for invariant in manifest:
        assert invariant["failure_contract"]
        assert invariant["negative_test_nodes"], invariant["invariant_id"]
        for node_id in invariant["negative_test_nodes"]:
            _assert_test_node_exists(node_id)


def test_threshold_and_runtime_defaults_match_frozen_baseline(tmp_path):
    fixture = _load_fixture()
    baseline = fixture["baseline_fingerprints"]
    expected_runtime = baseline["runtime_config"]

    config = OperatorRuntimeConfig.from_env({}, repo_root=tmp_path)
    assert list(config.allowed_watchlist) == expected_runtime["allowed_watchlist"]
    assert config.allowed_profile == expected_runtime["allowed_profile"]
    assert list(config.allowed_durations) == expected_runtime["allowed_durations_seconds"]
    assert config.min_paper_duration_seconds == expected_runtime["minimum_duration_seconds"]
    assert config.max_paper_duration_seconds == expected_runtime["maximum_duration_seconds"]
    assert config.live_enabled is expected_runtime["live_enabled"] is False
    assert config.real_money_enabled is expected_runtime["real_money_enabled"] is False
    assert ALPACA_PAPER_EXPECTED_ACCOUNT_SUFFIX == expected_runtime["expected_account_suffix"]

    strategies = SimpleNamespace(
        min_confidence=0.60,
        sector_inflow_threshold=1.50,
        whale_threshold=0.20,
        sentiment_velocity_threshold=1.50,
    )
    profile = resolve_active_threshold_profile(
        SimpleNamespace(
            paper_exploration_alpha_enabled=True,
            broker_mode="paper",
            alpaca_paper=True,
            strategies=strategies,
        )
    )
    assert profile["profile_name"] == "PAPER_EXPLORATION_ALPHA"
    assert profile["activation_status"] == "PASS"
    assert profile["paper_only_active"] is True
    actual_thresholds = {
        name: {
            "default": item["default_value"],
            "exploration": item["exploration_value"],
        }
        for name, item in profile["thresholds_by_name"].items()
    }
    assert actual_thresholds == baseline["threshold_profile"]

    non_paper = resolve_active_threshold_profile(
        SimpleNamespace(
            paper_exploration_alpha_enabled=True,
            broker_mode="live",
            alpaca_paper=False,
            strategies=strategies,
        )
    )
    assert non_paper["enabled"] is False
    assert non_paper["activation_status"] == "BLOCK"
    assert non_paper["reason_codes"] == ("PAPER_EXPLORATION_PROFILE_NON_PAPER_BLOCKED",)


def test_authority_capability_module_and_source_fingerprints_match_frozen_baseline():
    fixture = _load_fixture()
    baseline = fixture["baseline_fingerprints"]
    approved_deltas = fixture["approved_source_deltas"]
    assert set(approved_deltas) == {"stage1", "stage2", "stage3", "stage4"}
    approved_delta = approved_deltas["stage1"]
    delta_hashes = approved_delta["source_sha256"]

    assert approved_delta["stage_entry_head"] == (
        "e363f4b919d3ae52416278c810a87169ca7f1186"
    )
    assert approved_delta["stage_entry_covenant"] == "PASS"
    assert set(delta_hashes) == {
        "app/main_loop.py",
        "main.py",
        "app/risk/pre_trade_guardrails.py",
    }
    stage_report = ROOT / Path(*approved_delta["report"].split("/"))
    assert stage_report.is_file()
    assert "STAGE_ENTRY_COVENANT: PASS" in stage_report.read_text(encoding="utf-8")

    stage2_delta = approved_deltas["stage2"]
    stage2_hashes = stage2_delta["source_sha256"]
    assert stage2_delta["stage_entry_head"] == (
        "f462356d140eaf0acccfd5be05faeb01536ae989"
    )
    assert stage2_delta["stage_entry_covenant"] == "PASS"
    assert set(stage2_hashes) == {
        "app/api/operator_paper_supervisor.py",
        "app/execution/order_router.py",
        "app/main_loop.py",
        "app/operator_activation/paper_baseline.py",
        "app/risk/exposure_manager.py",
        "app/risk/reservation_lifecycle_coordinator.py",
        "app/state/state_store.py",
        "main.py",
    }
    stage2_report = ROOT / Path(*stage2_delta["report"].split("/"))
    assert stage2_report.is_file()
    assert "STAGE_ENTRY_COVENANT: PASS" in stage2_report.read_text(encoding="utf-8")
    for relative_path, hashes in stage2_hashes.items():
        assert set(hashes) == {"before", "after"}
        assert len(hashes["before"]) == len(hashes["after"]) == 64
    for relative_path in set(delta_hashes) & set(stage2_hashes):
        assert stage2_hashes[relative_path]["before"] == delta_hashes[relative_path]["after"]

    stage3_delta = approved_deltas["stage3"]
    stage3_hashes = stage3_delta["source_sha256"]
    assert stage3_delta["stage_entry_head"] == (
        "4b9b8ed13583d56bfc2120fbee291e3695b1a288"
    )
    assert stage3_delta["stage_entry_covenant"] == "PASS"
    assert set(stage3_hashes) == {
        "app/api/operator_paper_supervisor.py",
        "app/api/operator_runtime_config.py",
        "app/config.py",
        "app/core/intelligence_portfolio_state_truth_spine.py",
        "app/execution/alpaca_paper_adapter.py",
        "app/execution/broker_gateway.py",
        "app/execution/broker_read_policy.py",
        "app/instrument_registry.py",
        "app/main_loop.py",
        "app/market/capability_registry.py",
        "app/market/venue_capabilities.py",
        "app/state/state_store.py",
        "main.py",
    }
    stage3_report = ROOT / Path(*stage3_delta["report"].split("/"))
    assert stage3_report.is_file()
    assert "STAGE_ENTRY_COVENANT: PASS" in stage3_report.read_text(encoding="utf-8")
    for relative_path, hashes in stage3_hashes.items():
        assert set(hashes) == {"before", "after"}
        assert len(hashes["before"]) == len(hashes["after"]) == 64
    for relative_path in set(stage2_hashes) & set(stage3_hashes):
        assert stage3_hashes[relative_path]["before"] == stage2_hashes[relative_path]["after"]

    stage4_delta = approved_deltas["stage4"]
    stage4_hashes = stage4_delta["source_sha256"]
    assert stage4_delta["stage_entry_head"] == (
        "6340bae4aff24d272f3ba4270c641d896de10278"
    )
    assert stage4_delta["stage_entry_covenant"] == "PASS"
    assert set(stage4_hashes) == {
        "app/config.py",
        "app/data/feed_provider_router.py",
        "app/data/market_feeds.py",
        "app/data/polling_client.py",
        "app/data/validators.py",
        "app/data/websocket_client.py",
        "app/market/capability_registry.py",
        "app/operator_providers/registry.py",
        "app/state/state_store.py",
        "main.py",
        "scripts/run_bounded_paper.ps1",
    }
    stage4_report = ROOT / Path(*stage4_delta["report"].split("/"))
    assert stage4_report.is_file()
    assert "STAGE_ENTRY_COVENANT: PASS" in stage4_report.read_text(encoding="utf-8")
    for relative_path, hashes in stage4_hashes.items():
        assert set(hashes) == {"before", "after"}
        assert len(hashes["before"]) == len(hashes["after"]) == 64
        assert _sha256(ROOT / Path(*relative_path.split("/"))) == hashes["after"]
    for relative_path in set(stage3_hashes) & set(stage4_hashes):
        assert stage4_hashes[relative_path]["before"] == stage3_hashes[relative_path]["after"]
    for relative_path in set(stage3_hashes) - set(stage4_hashes):
        assert _sha256(ROOT / Path(*relative_path.split("/"))) == stage3_hashes[relative_path]["after"]
    assert stage4_delta["market_data_authority_delta"] == {
        "execution_location": "alpaca",
        "dynamic_activation_mode": "OBSERVE_ONLY",
        "dynamic_execution_authorized": False,
        "cross_venue_role": "ADVISORY_ONLY",
    }

    graph = authority_graph_summary()
    actual_owners = {
        item["authority"]: item["owner"]["module"] for item in graph["authorities"]
    }
    assert graph["version"] == baseline["authority_graph"]["version"]
    assert graph["integrity"] == {"ok": True, "messages": ()}
    assert actual_owners == baseline["authority_graph"]["owners"]
    assert graph["broker_mutation_occurred"] is False
    assert graph["trading_mutation_occurred"] is False
    assert graph["live_enabled"] is False
    assert graph["real_money_enabled"] is False

    capability_expected = baseline["alpaca_crypto_capability"]
    static_contract_delta = stage3_delta["capability_contract_delta"]["static_alpaca_crypto"]
    capability = _alpaca_crypto_capability("BTC/USD")
    assert sorted(capability.supported_actions) == capability_expected["declared_actions"]
    assert static_contract_delta["classification"] == "COMMISSIONING_OR_TEST_SCAFFOLD"
    assert static_contract_delta["before"] == {
        "enabled": True,
        "paper_mutation": capability_expected["paper_mutation"],
        "execution_authority_source": None,
    }
    assert capability.enabled is static_contract_delta["after"]["enabled"] is False
    assert capability.paper_mutation is static_contract_delta["after"]["paper_mutation"] is False
    assert capability.execution_authority_source == static_contract_delta["after"]["execution_authority_source"]
    assert capability.fail_closed_reason_code == static_contract_delta["after"]["fail_closed_reason_code"]
    assert capability.live_mutation is capability_expected["live_mutation"] is False
    assert capability.live_blocked is capability_expected["live_blocked"] is True

    sell_request = BrokerOrderSubmitRequest(
        symbol="BTC/USD",
        side="sell",
        order_type="limit",
        time_in_force="GTC",
        quantity=Decimal("0.001"),
        client_order_id="stage0-offline-sell-contract",
        limit_price=Decimal("100000"),
        asset_class="crypto",
    )
    with pytest.raises(BrokerGatewayError) as exc_info:
        AlpacaPaperBrokerAdapter._payload_for_order(None, sell_request)
    assert exc_info.value.reason_code == "invalid_order_request"
    assert capability_expected["external_adapter_sell_supported"] is False
    assert capability_expected["external_adapter_sell_block_reason"] in exc_info.value.message
    assert capability_expected["blocker_owner_stage"] == 8

    classification = baseline["module_classification"]
    assert sum(
        classification[key]
        for key in ("WIRED", "BLOCKED", "PRESERVED-DEAD", "REJECTED-PRESERVED")
    ) == classification["countable_total"] == 397
    phase_b_text = (ROOT / "reports" / "completion" / "PHASE_B_MODULE_TRUTH_MAP.md").read_text(
        encoding="utf-8"
    )
    counts_line = next(
        line
        for line in phase_b_text.splitlines()
        if line.startswith("- Classification counts excluding generated __pycache__ artifacts:")
    )
    recorded_counts = ast.literal_eval(counts_line.split(":", 1)[1].strip())
    assert recorded_counts == {
        key: classification[key]
        for key in ("WIRED", "BLOCKED", "PRESERVED-DEAD", "REJECTED-PRESERVED")
    }
    assert "2 __pycache__ artifacts excluded" in phase_b_text

    mutation_surface = baseline["broker_mutation_surface"]
    assert mutation_surface["final_owner"] == actual_owners["broker_order_lifecycle"]
    assert mutation_surface["submit_method"] == "POST"
    assert mutation_surface["submit_path"] == "/v2/orders"
    assert mutation_surface["cancel_method"] == "DELETE"
    assert mutation_surface["stage0_transport_calls_authorized"] is False

    for relative_path, expected_hash in baseline["source_sha256"].items():
        path = ROOT / Path(*relative_path.split("/"))
        expected_current = expected_hash
        for stage_hashes in (delta_hashes, stage2_hashes, stage3_hashes, stage4_hashes):
            delta = stage_hashes.get(relative_path)
            if delta is None:
                continue
            assert delta["before"] == expected_current, relative_path
            expected_current = delta["after"]
        assert _sha256(path) == expected_current, relative_path
