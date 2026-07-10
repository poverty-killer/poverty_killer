from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from app.ai_chief_operator.config import AIChiefConfig
from app.ai_chief_operator.provider_gateway import AIProviderGateway
from app.api.operator_paper_supervisor import OperatorPaperSupervisor, PaperSupervisorConfig
from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.api.operator_session_store import OperatorSessionStore
from app.operator_activation.paper_baseline import BASELINE_POLICY_CLEAN_ONLY, BASELINE_POLICY_PROTECTED
from app.operator_credentials.store import ALPACA_PAPER_ENV_PATH_ENV_KEY, LocalCredentialStore
from tests.test_operator_paper_supervisor import FakeRunner


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


PAPER_ENV = {
    "APCA_API_KEY_ID": "test-paper-key",
    "APCA_API_SECRET_KEY": "test-paper-secret",
    "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
}


def _account_pin_ok_assertion() -> dict:
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


@pytest.fixture(autouse=True)
def _offline_account_pin_for_legacy_ai_tests(monkeypatch):
    monkeypatch.setattr(
        OperatorPaperSupervisor,
        "_paper_account_identity_assertion",
        lambda self, *, force=False: _account_pin_ok_assertion(),
    )


@pytest.fixture(autouse=True)
def _isolated_canonical_paper_env(monkeypatch, tmp_path) -> Path:
    path = tmp_path / "canonical_alpaca_paper.env"
    monkeypatch.setenv(ALPACA_PAPER_ENV_PATH_ENV_KEY, str(path))
    return path


def _write_canonical_paper_env() -> None:
    path = Path(os.environ[ALPACA_PAPER_ENV_PATH_ENV_KEY])
    path.write_text(
        "\n".join(
            [
                "APCA_API_KEY_ID=test-paper-key",
                "APCA_API_SECRET_KEY=test-paper-secret",
            ]
        ),
        encoding="utf-8",
    )


def _paper_preflight_snapshot(*, existing_positions: bool = False) -> dict[str, object]:
    positions = (
        [{"symbol": "AAPL", "asset_class": "us_equity", "qty": "1", "side": "long"}]
        if existing_positions
        else []
    )
    return {
        "endpoint_family": "paper",
        "account": {
            "id": "test-account-123456",
            "status": "ACTIVE",
            "equity": "50000",
            "buying_power": "75000",
            "currency": "USD",
            "trading_blocked": False,
            "account_blocked": False,
            "transfers_blocked": False,
            "pattern_day_trader": False,
        },
        "open_order_count": 0,
        "open_orders": [],
        "position_count": len(positions),
        "positions": positions,
    }


def _accept_ready_baseline(provider: OperatorSnapshotProvider, *, existing_positions: bool = False) -> None:
    accepted = provider.paper_baseline_accept(
        {
            "preflight_snapshot": _paper_preflight_snapshot(existing_positions=existing_positions),
            "policy": BASELINE_POLICY_PROTECTED if existing_positions else BASELINE_POLICY_CLEAN_ONLY,
            "accepted_by_operator": "Shan/local operator",
        }
    )
    assert accepted["accepted"] is True
    assert accepted["broker_mutation_occurred"] is False


def _ready_app(tmp_path):
    _write_canonical_paper_env()
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider("alpaca_paper", {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"})
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    _accept_ready_baseline(provider)
    return create_operator_app(provider=provider)


def _ready_app_with_historical_duplicate(tmp_path):
    runner = FakeRunner()
    repo_root = runner.repo_root
    store_path = repo_root / "state" / "session_journal.jsonl"
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(
            repo_root=repo_root,
            process_env=dict(PAPER_ENV),
            session_store_path=str(store_path),
        ),
        runner=runner,
        session_store=OperatorSessionStore(path=store_path),
    )
    supervisor.start_paper(
        {
            "profile": "PAPER_EXPLORATION_ALPHA",
            "duration_seconds": 300,
            "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
            "approve_autonomous_paper": True,
        }
    )
    supervisor.start_paper(
        {
            "profile": "PAPER_EXPLORATION_ALPHA",
            "duration_seconds": 300,
            "watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
            "approve_autonomous_paper": True,
        }
    )
    runner.process.exit_code = 0
    supervisor.status_snapshot()
    reloaded = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(
            repo_root=repo_root,
            process_env=dict(PAPER_ENV),
            session_store_path=str(store_path),
        ),
        runner=runner,
        session_store=OperatorSessionStore(path=store_path),
    )
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=repo_root),
        supervisor=reloaded,
        provider_env=dict(PAPER_ENV),
    )
    return create_operator_app(provider=provider)


def test_ai_ask_returns_advisory_fallback_and_cannot_execute(tmp_path):
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        ai_config=AIChiefConfig(provider="mock", enabled=True, mock_mode=True),
    )
    app = create_operator_app(provider=provider)

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "Where is the edge in latest run TCA evidence?",
            "page_context": {"page_id": "pnl", "page_title": "P&L / Net Profit"},
        }
    )

    assert payload["status"] == "ANSWERED_LOCAL_GUIDE"
    assert payload["answer_mode"] == "DETERMINISTIC"
    assert payload["answer_mode_status"] == "DEFAULTED_DETERMINISTIC"
    assert payload["response_source"] == "LOCAL_DETERMINISTIC"
    assert payload["answer_source"] == "LOCAL_DETERMINISTIC"
    assert payload["cost_mode"] == "FREE_LOCAL"
    assert payload["provider_mode"] == "DETERMINISTIC_FALLBACK"
    assert payload["provider_id"] == "deterministic_local"
    assert payload["model_name"] == "deterministic-local-guide"
    assert payload["model_quality"] == "FALLBACK_ONLY"
    assert payload["reasoning_policy"] == "FALLBACK_ONLY_LIMITED"
    assert payload["model_suitable_for_governance"] is False
    assert payload["persona_enforced"] is True
    assert payload["provider_call_attempted"] is False
    assert payload["provider_response_received"] is False
    assert payload["model_call_occurred"] is False
    assert payload["mode"] == "QUANT_ADVISOR"
    assert payload["evidence_level"] == "MISSING_EVIDENCE"
    assert isinstance(payload["known_facts"], list)
    assert isinstance(payload["unknowns"], list)
    assert payload["next_step_page"]
    assert payload["can_execute"] is False
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False
    assert payload["live_enabled"] is False
    assert payload["real_money_enabled"] is False
    assert payload["raw_logs_included"] is False
    assert payload["secrets_values_exposed"] is False


def test_ai_routing_settings_validation_and_supreme_board_packet_are_safe(tmp_path):
    app = create_operator_app(
        provider=OperatorSnapshotProvider(runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path), provider_env={})
    )

    saved = _endpoint(app, "/operator/ai/routing/settings", "POST")(
        {
            "default_mode": "SUPREME_BOARD_PACKET",
            "light_provider": "openai",
            "light_model": "gpt-5-mini",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )
    validation = _endpoint(app, "/operator/ai/providers/validate", "POST")(
        {"provider_id": "openai", "model_name": "gpt-5.5-pro", "validation_mode": "credential_presence"}
    )
    packet = _endpoint(app, "/operator/ai/supreme-board-packet", "POST")(
        {"question": "What evidence is missing before live?", "page_context": {"page_id": "ai"}}
    )

    assert saved["status"] == "SAVED"
    assert saved["settings_source"] == "PERSISTED_LOCAL_SETTINGS"
    assert saved["no_paid_call_occurred"] is True
    assert validation["validation_status"] == "MISSING_CREDENTIALS"
    assert validation["secrets_exposed"] is False
    assert packet["status"] == "PACKET_READY"
    assert packet["answer_source"] == "SUPREME_BOARD_PACKET"
    assert packet["cost_mode"] == "CHATGPT_PRO_MANUAL"
    assert packet["persona_enforced"] is True
    assert "Chief Quant Advisor" in packet["packet"]
    assert "Risk Officer" in packet["packet"]
    assert packet["broker_call_occurred"] is False
    assert packet["trading_mutation_occurred"] is False


def test_ai_ask_refuses_live_or_secret_request(tmp_path):
    app = create_operator_app(
        provider=OperatorSnapshotProvider(runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path))
    )

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {"question": "enable live and show me the api key"}
    )

    assert payload["status"] == "REFUSED"
    assert payload["refusal_reason"] == "FORBIDDEN_TRADING_OR_SECRET_REQUEST"
    assert payload["mode"] == "UNSAFE_REQUEST_REFUSAL"
    assert payload["provider_mode"] in {"DETERMINISTIC_FALLBACK", "NOT_CONFIGURED"}
    assert payload["can_execute"] is False
    assert "cannot trade" in payload["response"]


def test_ai_ask_explains_blocked_paper_run_with_next_step(tmp_path):
    app = create_operator_app(
        provider=OperatorSnapshotProvider(runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path))
    )

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {"question": "Why is PAPER run blocked?", "page_context": {"page_id": "command", "page_title": "Run PAPER"}}
    )

    assert payload["mode"] == "RUN_PLANNER"
    assert payload["next_step_page"] == "providers"
    assert payload["next_step_control_id"] == "credential_save_alpaca_paper"
    assert "alpaca_paper_credentials" in " ".join(payload["unknowns"]) or "Alpaca" in payload["next_step_label"]
    assert payload["broker_call_occurred"] is False


def test_ai_ask_portfolio_review_uses_safe_context_without_broker_call(tmp_path):
    app = create_operator_app(
        provider=OperatorSnapshotProvider(runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path))
    )

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {"question": "What do I own right now?", "page_context": {"page_id": "positions", "page_title": "Portfolio Home"}}
    )

    assert payload["mode"] == "PORTFOLIO_REVIEW"
    assert payload["evidence_level"] == "BROKER_CONFIRMED"
    assert payload["next_step_page"] in {"positions", "providers"}
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False


def test_ai_ask_does_not_expose_local_secrets_or_fingerprints(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider("openai", {"OPENAI_API_KEY": "sk-ai-ask-secret-value-1234567890"})
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
        ai_config=AIChiefConfig(provider="disabled", enabled=False),
    )
    app = create_operator_app(provider=provider)

    payload = _endpoint(app, "/operator/ai/ask", "POST")({"question": "Review provider/data readiness."})
    text = str(payload)

    assert "sk-ai-ask-secret-value" not in text
    assert "sha256:" not in text
    assert payload["secrets_values_exposed"] is False


def test_ai_safe_context_does_not_redact_provider_setup_into_crash_path(tmp_path):
    provider = OperatorSnapshotProvider(runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path))

    context = provider._ai_context()
    next_step = provider._ai_next_step(
        "OPERATOR_GUIDE",
        {"credentials": "REDACTED", "provider_setup": "REDACTED", "launch_readiness": {}},
        "portfolio-home",
    )

    assert "credentials" not in context
    assert isinstance(context["provider_setup"], dict)
    assert next_step["control_id"] == "ai_ask"


def test_ai_ask_treats_alive_launch_status_as_operator_prompt(tmp_path):
    provider = OperatorSnapshotProvider(runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path))
    app = create_operator_app(provider=provider)

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "Are you alive? Explain current operator launch status in one sentence.",
            "route_mode": "LOCAL_GUIDE",
            "page_context": {"page_id": "portfolio-home", "page_title": "Portfolio Home"},
        }
    )

    assert payload["status"] != "REFUSED"
    assert payload["mode"] == "OPERATOR_GUIDE"
    assert "REDACTED missing credentials" not in str(payload["known_facts"])
    assert payload["can_execute"] is False


def test_ai_ask_treats_blocking_bot_question_as_operator_prompt(tmp_path):
    provider = OperatorSnapshotProvider(runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path))
    app = create_operator_app(provider=provider)

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "What is blocking the bot right now?",
            "route_mode": "LOCAL_GUIDE",
            "page_context": {"page_id": "positions", "page_title": "Portfolio Home"},
        }
    )

    assert payload["status"] != "REFUSED"
    assert payload["refusal_reason"] is None
    assert payload["mode"] in {"TRADING_SYSTEMS_AUDITOR", "OPERATOR_GUIDE", "PORTFOLIO_REVIEW"}
    assert "cannot trade" not in payload["answer"]
    assert "Current backend truth:" not in payload["answer"]
    assert "Short answer:" in payload["answer"]
    assert "Launch readiness:" in payload["answer"]
    assert payload["can_execute"] is False
    assert payload["broker_call_occurred"] is False


def test_ai_status_exposes_gateway_route_truth_owner(tmp_path):
    provider = OperatorSnapshotProvider(runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path))
    app = create_operator_app(provider=provider)

    payload = _endpoint(app, "/operator/ai/status")()

    assert payload["route_truth_owner"] == "app.ai_chief_operator.provider_gateway.AIProviderGateway"
    assert payload["active_provider"]
    assert "active_model" in payload
    assert payload["response_mode"]
    assert payload["advisory_only"] is True
    assert payload["can_execute"] is False
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False


def test_ai_ask_returns_evidence_contract_and_canonical_blockers(tmp_path):
    provider = OperatorSnapshotProvider(runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path))
    app = create_operator_app(provider=provider)

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "What is blocking the bot right now?",
            "route_mode": "LOCAL_GUIDE",
            "page_context": {"page_id": "command", "page_title": "Run PAPER"},
        }
    )

    contract = payload["evidence_contract"]
    canonical = payload["canonical_readiness"]
    blocker_text = " ".join(payload["canonical_readiness_blockers"])

    assert payload["evidence_bound"] is True
    assert contract["schema_version"] == "ai-chief-evidence-contract-v1"
    assert contract["evidence_bound"] is True
    assert contract["canonical_readiness"]["current_blockers"] == payload["canonical_readiness_blockers"]
    assert canonical["source"] == "OPERATOR_LAUNCH_READINESS_D6_CONTRACT"
    assert canonical["final_launch_readiness"] == "BLOCKED"
    assert "alpaca_paper_credentials" in blocker_text
    assert "IDLE_NO_ACTIVE_PAPER_RUN" not in blocker_text
    assert any("Unknown because this evidence is missing" in item for item in payload["unknowns"])
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False


def test_ai_ask_portfolio_review_marks_missing_broker_packet_unknown(tmp_path):
    provider = OperatorSnapshotProvider(runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path))
    app = create_operator_app(provider=provider)

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "What do I own right now?",
            "route_mode": "LOCAL_GUIDE",
            "page_context": {"page_id": "positions", "page_title": "Portfolio Home"},
        }
    )

    packets = {row["name"]: row for row in payload["evidence_contract"]["packets"]}
    assert payload["mode"] == "PORTFOLIO_REVIEW"
    assert packets["portfolio_truth"]["required"] is True
    assert packets["portfolio_truth"]["present"] is False
    assert "Unknown because this evidence is missing" in packets["portfolio_truth"]["reason"]
    assert any("broker portfolio truth unavailable" in item for item in payload["unknowns"])
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False


def test_ai_provider_prompt_receives_evidence_contract_not_secret_or_tools(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "deepseek-test-token-value",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )
    captured: dict[str, object] = {}

    def fake_post(url, headers, body, timeout_seconds):
        captured.update({"url": url, "headers": headers, "body": body, "timeout_seconds": timeout_seconds})
        return {"id": "ds-evidence-1", "model": "deepseek-chat", "choices": [{"message": {"content": "I can only use the supplied evidence contract."}}]}

    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    provider.ai_gateway = AIProviderGateway(
        AIChiefConfig.from_env(provider.provider_env),
        credential_env=provider.provider_env,
        http_post=fake_post,
    )
    app = create_operator_app(provider=provider)
    _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LIGHT_API",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "deepseek",
            "light_model": "deepseek-chat",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "Explain the current bot state in plain English.",
            "answer_mode": "AI_CHAT_MODEL",
            "page_context": {"page_id": "ai", "page_title": "AI Advisor"},
        }
    )

    body_text = str(captured["body"])
    assert payload["model_call_occurred"] is True
    assert "evidence_contract" in body_text
    assert "Unknown because this evidence is missing" in body_text
    assert "allow_broker_tools" in body_text
    assert "deepseek-test-token-value" not in body_text
    assert "test-paper-secret" not in body_text
    assert "sk-" not in body_text
    assert payload["evidence_bound"] is True
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False


def test_ai_ask_can_i_start_paper_uses_run_planner_truth(tmp_path):
    provider = OperatorSnapshotProvider(runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path))
    app = create_operator_app(provider=provider)

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "Can I start PAPER?",
            "route_mode": "LOCAL_GUIDE",
            "page_context": {"page_id": "command", "page_title": "Run PAPER"},
        }
    )

    assert payload["status"] != "REFUSED"
    assert payload["mode"] == "RUN_PLANNER"
    assert "No - current blocker is alpaca_paper_credentials." in payload["answer"]
    assert "Launch readiness:" in payload["answer"]
    assert payload["can_execute"] is False
    assert payload["broker_call_occurred"] is False


def test_ai_ask_ready_paper_run_answers_yes_without_fake_blocker(tmp_path):
    app = _ready_app(tmp_path)

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "can i do paper run?",
            "route_mode": "LOCAL_GUIDE",
            "page_context": {"page_id": "command", "page_title": "Run PAPER"},
        }
    )
    answer = payload["answer"]

    assert payload["mode"] == "RUN_PLANNER"
    assert answer.startswith("Yes - governed PAPER is ready and start is allowed.")
    assert "Launch readiness: READY_FOR_BOUNDED_PAPER" in answer
    assert "Supervisor: IDLE" in answer
    assert "Paper start allowed: true" in answer
    assert "Live locked; real money blocked" in answer
    assert "Max duration: 432000 seconds / 5 days" in answer
    assert "Use a short proof first; long PAPER leases are available only through the same governed controls." in answer
    assert "Shan must click Start PAPER" in answer
    assert "Current backend truth:" not in answer
    assert "Provider readiness loaded" not in answer
    assert "readiness blockers are cleared" not in answer
    assert "Current blocker: READY_IDLE_NO_ACTIVE_RUNTIME" not in answer
    assert payload["can_execute"] is False
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False
    assert payload["live_enabled"] is False
    assert payload["real_money_enabled"] is False


def test_ai_ask_ready_paper_run_bypasses_stale_external_run_planner_text(tmp_path):
    _write_canonical_paper_env()
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider("alpaca_paper", {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"})
    store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "deepseek-test-token-value",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    _accept_ready_baseline(provider)

    def fail_if_external_called(url, headers, body, timeout_seconds):
        raise AssertionError("RUN_PLANNER readiness truth must not call an external provider")

    provider.ai_gateway = AIProviderGateway(
        AIChiefConfig.from_env(provider.provider_env),
        credential_env=provider.provider_env,
        http_post=fail_if_external_called,
    )
    app = create_operator_app(provider=provider)
    saved = _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LIGHT_API",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "openai",
            "light_model": "gpt-5-mini",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "can i do paper run?",
            "page_context": {"page_id": "command", "page_title": "Run PAPER"},
        }
    )
    answer = payload["answer"]

    assert saved["settings"]["active_provider"] == "deepseek"
    assert payload["mode"] == "RUN_PLANNER"
    assert payload["status"] == "ANSWERED_LOCAL_GUIDE"
    assert payload["provider_id"] == "deterministic_local"
    assert payload["answer_source"] == "LOCAL_DETERMINISTIC"
    assert payload["route_decision"]["reason_code"] == "RUN_PLANNER_LOCAL_RUNTIME_TRUTH"
    assert payload["model_call_attempted"] is False
    assert payload["model_call_occurred"] is False
    assert answer.startswith("Yes - governed PAPER is ready and start is allowed.")
    assert "Launch readiness: READY_FOR_BOUNDED_PAPER" in answer
    assert "Current state: READY_IDLE_NO_ACTIVE_RUNTIME" not in answer
    assert "READY_IDLE_NO_ACTIVE_RUNTIME" in " ".join(payload["known_facts"])
    assert "Use Run PAPER only after readiness blockers are cleared" not in answer
    assert "readiness blockers are cleared" not in payload["next_step_label"]
    assert "Current blocker: READY_IDLE_NO_ACTIVE_RUNTIME" not in answer
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False
    assert payload["live_enabled"] is False
    assert payload["real_money_enabled"] is False


def test_ai_ask_alive_is_concise_health_answer_when_ready_idle(tmp_path):
    app = _ready_app(tmp_path)

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "are you alive?",
            "route_mode": "LOCAL_GUIDE",
            "page_context": {"page_id": "positions", "page_title": "Portfolio Home"},
        }
    )
    answer = payload["answer"]

    assert payload["mode"] == "OPERATOR_GUIDE"
    assert payload["model_call_attempted"] is False
    assert payload["model_call_occurred"] is False
    assert answer.startswith("Yes - backend connected and our bot is idle-ready.")
    assert "Runtime: IDLE / no active PAPER run" in answer
    assert "Launch readiness: READY_FOR_BOUNDED_PAPER" in answer
    assert "Current backend truth:" not in answer
    assert "Provider readiness loaded" not in answer
    assert "Redacted JSON" not in answer
    assert len(answer.splitlines()) <= 6
    assert payload["can_execute"] is False
    assert payload["broker_call_occurred"] is False


def test_ai_ask_historical_duplicate_is_audit_context_not_cleanup_target(tmp_path):
    app = _ready_app_with_historical_duplicate(tmp_path)

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "can i do paper run?",
            "route_mode": "LOCAL_GUIDE",
            "page_context": {"page_id": "command", "page_title": "Run PAPER"},
        }
    )
    answer = payload["answer"]
    lowered = answer.lower()

    assert "Historical duplicate refusal exists as audit context, but it is not current start authority." in " ".join(payload["known_facts"])
    assert "Historical duplicate refusal" not in answer
    assert "clean" not in lowered
    assert "clear stale" not in lowered
    assert "delete" not in lowered
    assert "reset" not in lowered
    assert "prune" not in lowered
    assert "Run Manager" not in answer
    assert "Start Governed PAPER" not in answer
    assert "Operator Dashboard" not in answer
    assert payload["can_execute"] is False
    assert payload["broker_call_occurred"] is False


def test_ai_ask_local_guide_uses_light_context_without_heavy_evidence_graph(tmp_path):
    provider = OperatorSnapshotProvider(runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path))

    def fail_if_heavy_context_used():
        raise AssertionError("LOCAL_GUIDE should use lightweight AI context")

    provider._ai_context = fail_if_heavy_context_used  # type: ignore[method-assign]
    payload = provider.ai_ask(
        {
            "question": "Are you alive? Explain current operator launch status in one sentence.",
            "route_mode": "LOCAL_GUIDE",
            "page_context": {"page_id": "portfolio-home", "page_title": "Portfolio Home"},
        }
    )

    assert payload["status"] != "REFUSED"
    assert payload["context"]["context_version"] == "ai-chief-light-context-v1"
    assert payload["broker_call_occurred"] is False


def test_ai_ask_uses_saved_active_deepseek_provider_without_silent_openai_fallback(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "deepseek-test-token-value",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )
    captured: dict[str, object] = {}

    def fake_post(url, headers, body, timeout_seconds):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        captured["timeout_seconds"] = timeout_seconds
        return {"choices": [{"message": {"content": "DeepSeek operator answer."}}]}

    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    provider.ai_gateway = AIProviderGateway(
        AIChiefConfig.from_env(provider.provider_env),
        credential_env=provider.provider_env,
        http_post=fake_post,
    )
    app = create_operator_app(provider=provider)

    saved = _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LIGHT_API",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "openai",
            "light_model": "gpt-5-mini",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )
    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "Explain this page.",
            "answer_mode": "AI_CHAT_MODEL",
            "page_context": {"page_id": "ai", "page_title": "AI Advisor"},
        }
    )

    assert saved["status"] == "SAVED"
    assert saved["settings"]["active_provider"] == "deepseek"
    assert payload["answer_mode"] == "AI_CHAT_MODEL"
    assert payload["provider_id"] == "deepseek", payload
    assert payload["route_decision"]["reason_code"] == "LIGHT_API_SELECTED", payload
    assert payload["status"] == "ANSWERED_MODEL", payload
    assert payload["model_name"] == "deepseek-chat"
    assert payload["answer_source"] == "API_LIGHT_MODEL"
    assert payload["model_call_attempted"] is True
    assert payload["model_call_occurred"] is True
    assert payload["provider_response_received"] is True
    assert payload["route_decision"]["provider_id"] == "deepseek"
    assert "api.deepseek.com" in str(captured["url"])
    assert captured["body"]["model"] == "deepseek-chat"
    assert "DeepSeek operator answer" in payload["answer"]
    assert "openai" not in str(captured["url"]).lower()
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False


def test_ai_ask_model_identity_uses_active_deepseek_provider_when_available(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "deepseek-test-token-value",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )
    captured: dict[str, object] = {}

    def fake_post(url, headers, body, timeout_seconds):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        captured["timeout_seconds"] = timeout_seconds
        return {"choices": [{"message": {"content": "I am DeepSeek answering through deepseek-chat."}}]}

    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    provider.ai_gateway = AIProviderGateway(
        AIChiefConfig.from_env(provider.provider_env),
        credential_env=provider.provider_env,
        http_post=fake_post,
    )
    app = create_operator_app(provider=provider)

    saved = _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LOCAL_GUIDE",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "openai",
            "light_model": "gpt-5-mini",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )
    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "which model are you?",
            "answer_mode": "AI_CHAT_MODEL",
            "page_context": {"page_id": "ai", "page_title": "AI Advisor"},
        }
    )

    assert saved["settings"]["active_provider"] == "deepseek"
    assert payload["status"] == "ANSWERED_MODEL", payload
    assert payload["refusal_reason"] is None
    assert payload["mode"] == "OPERATOR_GUIDE"
    assert payload["provider_id"] == "deepseek"
    assert payload["model_name"] == "deepseek-chat"
    assert payload["answer_source"] == "API_LIGHT_MODEL"
    assert payload["route_decision"]["reason_code"] == "LIGHT_API_SELECTED"
    assert payload["answer"].startswith("I am DeepSeek answering through deepseek-chat.")
    assert payload["model_call_attempted"] is True
    assert payload["model_call_occurred"] is True
    assert payload["provider_response_received"] is True
    assert payload["actual_provider"] == "deepseek"
    assert payload["actual_model"] == "deepseek-chat"
    assert payload["display_source_label"].startswith("DeepSeek model answer")
    assert "I can give a limited operational answer" not in payload["answer"]
    assert "api.deepseek.com" in str(captured["url"])
    assert captured["body"]["model"] == "deepseek-chat"
    prompt_text = str(captured["body"])
    assert "advisory_only" in prompt_text
    assert payload["can_execute"] is False
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False
    assert payload["live_enabled"] is False
    assert payload["real_money_enabled"] is False


def test_ai_ask_model_identity_fallback_is_clearly_labeled_when_provider_unavailable(tmp_path):
    provider = OperatorSnapshotProvider(runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path), provider_env={})
    app = create_operator_app(provider=provider)

    saved = _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LOCAL_GUIDE",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "openai",
            "light_model": "gpt-5-mini",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )
    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "which model are you?",
            "answer_mode": "AI_CHAT_MODEL",
            "page_context": {"page_id": "ai", "page_title": "AI Advisor"},
        }
    )
    answer = payload["answer"]

    assert saved["settings"]["active_provider"] == "deepseek"
    assert payload["status"] == "ANSWERED_FALLBACK"
    assert payload["refusal_reason"] is None
    assert payload["mode"] == "OPERATOR_GUIDE"
    assert payload["provider_id"] == "deepseek"
    assert payload["answer_source"] == "LOCAL_DETERMINISTIC"
    assert payload["model_call_attempted"] is False
    assert payload["model_call_occurred"] is False
    assert payload["fallback_reason"] == "LIGHT_PROVIDER_UNAVAILABLE"
    assert "DeepSeek is selected, but no provider model answered this question." in answer
    assert "Selected provider/model: DeepSeek / deepseek-chat" in answer
    assert "Actual answer source: LOCAL_DETERMINISTIC" in answer
    assert "Provider call did not answer:" in answer
    assert "api key" not in answer.lower()
    assert payload["can_execute"] is False
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False
    assert payload["live_enabled"] is False
    assert payload["real_money_enabled"] is False


def test_ai_ask_deterministic_identity_never_calls_provider(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "deepseek-test-token-value",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )
    calls: list[dict[str, object]] = []

    def fake_post(url, headers, body, timeout_seconds):
        calls.append({"url": url, "headers": headers, "body": body, "timeout_seconds": timeout_seconds})
        return {"choices": [{"message": {"content": "provider should not answer"}}]}

    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    provider.ai_gateway = AIProviderGateway(
        AIChiefConfig.from_env(provider.provider_env),
        credential_env=provider.provider_env,
        http_post=fake_post,
    )
    app = create_operator_app(provider=provider)
    _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LIGHT_API",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "deepseek",
            "light_model": "deepseek-chat",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {"question": "which model are you?", "answer_mode": "DETERMINISTIC", "page_context": {"page_id": "ai"}}
    )

    assert calls == []
    assert payload["answer_mode"] == "DETERMINISTIC"
    assert payload["answer_source"] == "LOCAL_DETERMINISTIC"
    assert payload["provider_call_attempted"] is False
    assert payload["provider_response_received"] is False
    assert payload["model_call_occurred"] is False
    assert "Deterministic mode is our bot/local backend" in payload["answer"]
    assert "DeepSeek answered" not in payload["answer"]
    assert payload["broker_call_occurred"] is False


def test_ai_ask_deterministic_self_test_request_does_not_call_provider(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "deepseek-test-token-value",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )
    calls: list[dict[str, object]] = []

    def fake_post(url, headers, body, timeout_seconds):
        calls.append({"url": url, "headers": headers, "body": body, "timeout_seconds": timeout_seconds})
        return {"choices": [{"message": {"content": "provider should not answer"}}]}

    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    provider.ai_gateway = AIProviderGateway(
        AIChiefConfig.from_env(provider.provider_env),
        credential_env=provider.provider_env,
        http_post=fake_post,
    )
    app = create_operator_app(provider=provider)

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "i want the bot to make a API call so i know it works",
            "answer_mode": "DETERMINISTIC",
            "page_context": {"page_id": "ai"},
        }
    )

    assert calls == []
    assert payload["answer_source"] == "LOCAL_DETERMINISTIC"
    assert payload["provider_call_attempted"] is False
    assert payload["provider_response_received"] is False
    assert payload["model_call_occurred"] is False
    assert "Deterministic mode does not call the AI provider" in payload["answer"]
    assert "AI Chat Model mode" in payload["answer"]
    assert "broker api call" not in payload["answer"].lower()
    assert payload["broker_call_occurred"] is False


def test_ai_ask_model_identity_provider_failure_reports_attempt_without_fake_answer(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "deepseek-test-token-value",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )
    calls: list[dict[str, object]] = []

    def failing_post(url, headers, body, timeout_seconds):
        calls.append({"url": url, "headers": headers, "body": body, "timeout_seconds": timeout_seconds})
        raise RuntimeError("provider_connection_error: simulated outage")

    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    provider.ai_gateway = AIProviderGateway(
        AIChiefConfig.from_env(provider.provider_env),
        credential_env=provider.provider_env,
        http_post=failing_post,
    )
    app = create_operator_app(provider=provider)
    _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LOCAL_GUIDE",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "openai",
            "light_model": "gpt-5-mini",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {"question": "which model are you?", "answer_mode": "AI_CHAT_MODEL", "page_context": {"page_id": "ai", "page_title": "AI Advisor"}}
    )

    assert calls, "provider transport should be attempted before fallback"
    assert payload["status"] == "ANSWERED_FALLBACK"
    assert payload["provider_id"] == "deepseek"
    assert payload["answer_source"] == "LOCAL_DETERMINISTIC"
    assert payload["model_call_attempted"] is True
    assert payload["model_call_occurred"] is False
    assert payload["provider_response_received"] is False
    assert "simulated outage" in payload["fallback_reason"]
    assert "DeepSeek is selected, but no provider model answered this question." in payload["answer"]
    assert "DeepSeek answered" not in payload["answer"]
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False


def test_ai_ask_model_identity_strips_provider_text_that_contradicts_call_metadata(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "deepseek-test-token-value",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )

    def contradictory_post(url, headers, body, timeout_seconds):
        del url, headers, body, timeout_seconds
        return {
            "choices": [
                {
                    "message": {
                        "content": "\n".join(
                            [
                                "I am the Chief Quant Advisor using DeepSeek.",
                                "- Provider selected: DeepSeek / deepseek-chat",
                                "- Answer source: Local deterministic guide; no external model call was made.",
                                "- Broker actions blocked.",
                            ]
                        )
                    }
                }
            ]
        }

    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    provider.ai_gateway = AIProviderGateway(
        AIChiefConfig.from_env(provider.provider_env),
        credential_env=provider.provider_env,
        http_post=contradictory_post,
    )
    app = create_operator_app(provider=provider)
    _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LOCAL_GUIDE",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "openai",
            "light_model": "gpt-5-mini",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {"question": "which model are you?", "answer_mode": "AI_CHAT_MODEL", "page_context": {"page_id": "ai", "page_title": "AI Advisor"}}
    )
    answer = payload["answer"].lower()

    assert payload["provider_id"] == "deepseek"
    assert payload["answer_source"] == "API_LIGHT_MODEL"
    assert payload["model_call_attempted"] is True
    assert payload["model_call_occurred"] is True
    assert "i am the chief quant advisor using deepseek" in answer
    assert "no external model call" not in answer
    assert "local deterministic guide" not in answer
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False


def test_ai_ask_quant_smoke_run_assessment_calls_selected_provider_as_limited_advisory(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "deepseek-test-token-value",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )
    captured: dict[str, object] = {}

    def fake_post(url, headers, body, timeout_seconds):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        captured["timeout_seconds"] = timeout_seconds
        return {"choices": [{"message": {"content": "DeepSeek concise quant advisory: ready for a short bounded PAPER smoke run only."}}]}

    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    provider.ai_gateway = AIProviderGateway(
        AIChiefConfig.from_env(provider.provider_env),
        credential_env=provider.provider_env,
        http_post=fake_post,
    )
    app = create_operator_app(provider=provider)
    _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LIGHT_API",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "deepseek",
            "light_model": "deepseek-chat",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "Give me a concise quant assessment of whether the bot is ready for a 10 minute PAPER smoke run.",
            "answer_mode": "AI_CHAT_MODEL",
            "page_context": {"page_id": "command", "page_title": "Run PAPER"},
        }
    )

    assert payload["provider_id"] == "deepseek"
    assert payload["status"] == "ANSWERED_MODEL"
    assert payload["answer_source"] == "API_LIGHT_MODEL"
    assert payload["route_decision"]["reason_code"] == "LIGHT_API_SELECTED_SERIOUS_ADVISORY_LIMITED"
    assert payload["model_call_attempted"] is True
    assert payload["model_call_occurred"] is True
    assert "DeepSeek concise quant advisory" in payload["answer"]
    assert "I can give a limited operational answer" not in payload["answer"]
    assert "api.deepseek.com" in str(captured["url"])
    assert captured["body"]["model"] == "deepseek-chat"
    assert payload["can_execute"] is False
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False
    assert payload["live_enabled"] is False
    assert payload["real_money_enabled"] is False


def test_ai_ask_quant_smoke_run_live_contradiction_is_replaced_with_backend_truth(tmp_path):
    _write_canonical_paper_env()
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider("alpaca_paper", {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"})
    store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "deepseek-test-token-value",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )

    def contradictory_post(url, headers, body, timeout_seconds):
        del url, headers, body, timeout_seconds
        return {
            "id": "ds-grounding-1",
            "model": "deepseek-chat",
            "choices": [
                {
                    "message": {
                        "content": (
                            "Answer: NOT READY. It is missing the evidence to justify a 10-minute smoke run. "
                            "You would be running a blind robot."
                        )
                    }
                }
            ],
        }

    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    _accept_ready_baseline(provider)
    provider.ai_gateway = AIProviderGateway(
        AIChiefConfig.from_env(provider.provider_env),
        credential_env=provider.provider_env,
        http_post=contradictory_post,
    )
    app = create_operator_app(provider=provider)
    _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LIGHT_API",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "deepseek",
            "light_model": "deepseek-chat",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "Give me a concise quant assessment of whether the bot is ready for a 10 minute PAPER smoke run.",
            "answer_mode": "AI_CHAT_MODEL",
            "page_context": {"page_id": "command", "page_title": "Run PAPER"},
        }
    )
    answer = payload["answer"].lower()

    assert payload["model_call_attempted"] is True
    assert payload["model_call_occurred"] is True
    assert payload["provider_response_received"] is True
    assert payload["safety_filter_triggered"] is True
    assert "not ready" in payload["blocked_terms"]
    assert "missing the evidence to justify" in payload["blocked_terms"]
    assert "blind robot" in payload["blocked_terms"]
    assert "answer: not ready" not in answer
    assert "blind robot" not in answer
    assert "wording was replaced with grounded backend truth" in answer
    assert "launch readiness: ready_for_bounded_paper" in answer
    assert "paper start allowed: true" in answer
    assert "ai cannot start it" in answer
    assert payload["answer_source"] == "API_LIGHT_MODEL"
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False


def test_ai_ask_live_provider_answer_is_compacted_and_redacts_local_paths(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "deepseek-test-token-value",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )

    def noisy_post(url, headers, body, timeout_seconds):
        del url, headers, timeout_seconds
        assert "C:\\Users\\shahn" not in str(body)
        return {
            "choices": [
                {
                    "message": {
                        "content": "\n".join(
                            [
                                "**Bot state**",
                                "Broker-confirmed truth: noisy diagnostic heading",
                                "The bot is idle and PAPER-ready.",
                                r"Review C:\Users\shahn\OneDrive\Desktop\poverty_killer\state\operator\reports\paper.md",
                                "- Live locked.",
                                "- Real money blocked.",
                                "- No broker action occurred.",
                                "- Extra diagnostic line one.",
                                "- Extra diagnostic line two.",
                                "- Extra diagnostic line three.",
                            ]
                        )
                    }
                }
            ]
        }

    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    provider.ai_gateway = AIProviderGateway(
        AIChiefConfig.from_env(provider.provider_env),
        credential_env=provider.provider_env,
        http_post=noisy_post,
    )
    app = create_operator_app(provider=provider)
    _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LIGHT_API",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "deepseek",
            "light_model": "deepseek-chat",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "explain the current bot state in plain English",
            "answer_mode": "AI_CHAT_MODEL",
            "page_context": {"page_id": "ai", "page_title": "AI Advisor"},
        }
    )
    answer = payload["answer"]

    assert payload["model_call_attempted"] is True
    assert payload["model_call_occurred"] is True
    assert "Broker-confirmed truth:" not in answer
    assert "C:\\Users\\shahn" not in answer
    assert "REDACTED_LOCAL_PATH" in answer
    assert len([line for line in answer.splitlines() if line.strip()]) <= 6
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False


def test_ai_ask_live_provider_broker_and_archived_run_dump_is_safety_filtered(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "deepseek-test-token-value",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )

    def broker_dump_post(url, headers, body, timeout_seconds):
        del url, headers, body, timeout_seconds
        return {
            "id": "ds-dump-1",
            "model": "deepseek-chat",
            "choices": [
                {
                    "message": {
                        "content": "\n".join(
                            [
                                "**Broker-Confirmed Truth (from Alpaca PAPER):**",
                                "- You have 10 open positions with total market value and buying power.",
                                "- One previous run `paper_d8b6013e0a594775` completed with CONDITIONAL_PASS.",
                                "- A newer run was refused because of duplicate prevention.",
                            ]
                        )
                    }
                }
            ],
        }

    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    provider.ai_gateway = AIProviderGateway(
        AIChiefConfig.from_env(provider.provider_env),
        credential_env=provider.provider_env,
        http_post=broker_dump_post,
    )
    app = create_operator_app(provider=provider)
    _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LIGHT_API",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "deepseek",
            "light_model": "deepseek-chat",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "explain the current bot state in plain English",
            "answer_mode": "AI_CHAT_MODEL",
            "page_context": {"page_id": "ai", "page_title": "AI Advisor"},
        }
    )
    answer = payload["answer"].lower()

    assert payload["model_call_attempted"] is True
    assert payload["model_call_occurred"] is True
    assert payload["safety_filter_triggered"] is True
    assert "open positions" in payload["blocked_terms"]
    assert "archived paper run id" in payload["blocked_terms"]
    assert "duplicate prevention" in payload["blocked_terms"]
    assert "open positions" not in answer
    assert "paper_d8b6013e0a594775" not in answer
    assert "wording was replaced with grounded backend truth" in answer
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False


def test_ai_ask_compound_health_and_model_identity_calls_provider(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "deepseek-test-token-value",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )
    calls: list[dict[str, object]] = []

    def fake_post(url, headers, body, timeout_seconds):
        calls.append({"url": url, "headers": headers, "body": body, "timeout_seconds": timeout_seconds})
        return {"id": "ds-compound-1", "model": "deepseek-chat", "choices": [{"message": {"content": "I am DeepSeek through deepseek-chat."}}]}

    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    provider.ai_gateway = AIProviderGateway(
        AIChiefConfig.from_env(provider.provider_env),
        credential_env=provider.provider_env,
        http_post=fake_post,
    )
    app = create_operator_app(provider=provider)
    _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LOCAL_GUIDE",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "deepseek",
            "light_model": "deepseek-chat",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )

    deterministic = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "are you alive? which model are you?",
            "answer_mode": "DETERMINISTIC",
            "page_context": {"page_id": "ai", "page_title": "AI Advisor"},
        }
    )

    assert calls == []
    assert deterministic["intent"] == "COMPOUND_LOCAL_AND_PROVIDER"
    assert deterministic["answer_source"] == "LOCAL_DETERMINISTIC"
    assert deterministic["provider_call_attempted"] is False
    assert "Yes -" in deterministic["answer"]
    assert "Deterministic mode is our bot/local backend" in deterministic["answer"]

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "are you alive? which model are you?",
            "answer_mode": "AI_CHAT_MODEL",
            "page_context": {"page_id": "ai", "page_title": "AI Advisor"},
        }
    )

    assert calls, "AI Chat mode should call the selected provider for compound prompt"
    assert payload["intent"] == "COMPOUND_LOCAL_AND_PROVIDER"
    assert payload["model_call_attempted"] is True
    assert payload["model_call_occurred"] is True
    assert payload["provider_response_received"] is True
    assert payload["answer_source"] == "API_LIGHT_MODEL"
    assert "I am DeepSeek through deepseek-chat." in payload["answer"]
    assert payload["ai_call_trace"]["intent"] == "COMPOUND_LOCAL_AND_PROVIDER"
    assert payload["ai_call_trace"]["endpoint_family"] == "deepseek_chat_completions"
    assert payload["ai_call_trace"]["provider_call_attempted"] is True
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False


def test_ai_ask_provider_self_test_uses_nonce_and_does_not_suggest_broker_or_paper(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "deepseek-test-token-value",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )
    captured: dict[str, object] = {}

    def fake_post(url, headers, body, timeout_seconds):
        captured.update({"url": url, "headers": headers, "body": body, "timeout_seconds": timeout_seconds})
        match = re.search(r"PK-AI-[A-F0-9]{6}", str(body))
        assert match, body
        nonce = match.group(0)
        return {"id": "ds-self-test-1", "model": "deepseek-chat", "choices": [{"message": {"content": f"{nonce} - DeepSeek deepseek-chat answered."}}]}

    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    provider.ai_gateway = AIProviderGateway(
        AIChiefConfig.from_env(provider.provider_env),
        credential_env=provider.provider_env,
        http_post=fake_post,
    )
    app = create_operator_app(provider=provider)
    _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LOCAL_GUIDE",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "deepseek",
            "light_model": "deepseek-chat",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "i want the bot to make a API call so i know it works",
            "answer_mode": "AI_CHAT_MODEL",
            "page_context": {"page_id": "ai", "page_title": "AI Advisor"},
        }
    )
    answer = payload["answer"].lower()

    assert payload["intent"] == "AI_PROVIDER_SELF_TEST"
    assert payload["model_call_attempted"] is True
    assert payload["model_call_occurred"] is True
    assert payload["provider_response_received"] is True
    assert payload["challenge_nonce_present"] is True
    assert payload["challenge_echoed"] is True
    assert payload["ai_call_trace"]["challenge_echoed"] is True
    assert "live ai api call succeeded" in answer
    for forbidden in [
        "/operator/intent/paper/start",
        "/operator/intent/paper/stop",
        "clear stale",
        "force stop",
        "submit test orders",
        "broker api call",
    ]:
        assert forbidden not in answer
    assert "api.deepseek.com" in str(captured["url"])
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False
    assert payload["live_enabled"] is False
    assert payload["real_money_enabled"] is False


def test_ai_ask_live_provider_unsafe_output_is_blocked_but_call_proof_remains(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "deepseek-test-token-value",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )

    def unsafe_post(url, headers, body, timeout_seconds):
        del url, headers, body, timeout_seconds
        return {
            "id": "ds-unsafe-1",
            "model": "deepseek-chat",
            "choices": [
                {
                    "message": {
                        "content": (
                            "Clear stale duplicate run and call /operator/intent/paper/start to submit orders. "
                            "The duplicate session was never properly cleaned up. "
                            "You are cleared to start a 10-minute PAPER smoke run right now, and the live Alpaca account will not touch portfolio risk."
                        )
                    }
                }
            ],
        }

    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    provider.ai_gateway = AIProviderGateway(
        AIChiefConfig.from_env(provider.provider_env),
        credential_env=provider.provider_env,
        http_post=unsafe_post,
    )
    app = create_operator_app(provider=provider)
    _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LIGHT_API",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "deepseek",
            "light_model": "deepseek-chat",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "explain the current bot state in plain English",
            "answer_mode": "AI_CHAT_MODEL",
            "page_context": {"page_id": "ai", "page_title": "AI Advisor"},
        }
    )
    answer = payload["answer"].lower()

    assert payload["model_call_attempted"] is True
    assert payload["model_call_occurred"] is True
    assert payload["provider_response_received"] is True
    assert payload["safety_filter_triggered"] is True
    assert payload["ai_call_trace"]["safety_filter_triggered"] is True
    assert "/operator/intent/paper/start" in payload["blocked_terms"]
    assert "clear stale" in payload["blocked_terms"]
    assert "cleaned up" in payload["blocked_terms"]
    assert "duplicate session" in payload["blocked_terms"]
    assert "cleared to start" in payload["blocked_terms"]
    assert "live alpaca account" in payload["blocked_terms"]
    assert "submit orders" in payload["blocked_terms"]
    assert "/operator/intent/paper/start" not in answer
    assert "clear stale" not in answer
    assert "cleaned up" not in answer
    assert "duplicate session" not in answer
    assert "live alpaca account" not in answer
    assert "submit orders" not in answer
    assert "wording was replaced with grounded backend truth" in answer
    assert "launch readiness:" in answer
    assert "paper start allowed:" in answer
    assert payload["answer_source"] == "API_LIGHT_MODEL"
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False


def test_ai_ask_reasoning_strategy_uses_approved_high_reasoning_provider(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider("openai", {"OPENAI_API_KEY": "sk-test-openai-token"})
    captured: dict[str, object] = {}

    def fake_post(url, headers, body, timeout_seconds):
        captured.update({"url": url, "headers": headers, "body": body, "timeout_seconds": timeout_seconds})
        return {"id": "resp-reasoning-1", "model": "gpt-5.5-pro", "output_text": "High reasoning advisory: bounded PAPER may be reviewed, but AI cannot start it."}

    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    provider.ai_gateway = AIProviderGateway(
        AIChiefConfig.from_env(provider.provider_env),
        credential_env=provider.provider_env,
        http_post=fake_post,
    )
    app = create_operator_app(provider=provider)
    _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LOCAL_GUIDE",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "deepseek",
            "light_model": "deepseek-chat",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "give me a concise quant assessment of whether the bot is ready for a 10 minute PAPER smoke run",
            "answer_mode": "AI_REASONING_STRATEGY",
            "approved_paid_call": True,
            "page_context": {"page_id": "command", "page_title": "Run PAPER"},
        }
    )

    assert payload["answer_mode"] == "AI_REASONING_STRATEGY"
    assert payload["provider_id"] == "openai"
    assert payload["answer_source"] == "API_HIGH_REASONING_APPROVED"
    assert payload["provider_call_attempted"] is True
    assert payload["provider_response_received"] is True
    assert payload["model_call_occurred"] is True
    assert payload["route_decision"]["reason_code"] == "HIGH_REASONING_API_APPROVED"
    assert captured["body"]["model"] == "gpt-5.5-pro"
    assert "High reasoning advisory" in payload["answer"]
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False


def test_ai_ask_reasoning_strategy_requires_approval_and_does_not_light_fallback(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "deepseek-test-token-value",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )
    calls: list[dict[str, object]] = []

    def fake_post(url, headers, body, timeout_seconds):
        calls.append({"url": url, "headers": headers, "body": body, "timeout_seconds": timeout_seconds})
        return {"choices": [{"message": {"content": "light fallback should not happen"}}]}

    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    provider.ai_gateway = AIProviderGateway(
        AIChiefConfig.from_env(provider.provider_env),
        credential_env=provider.provider_env,
        http_post=fake_post,
    )
    app = create_operator_app(provider=provider)
    _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LIGHT_API",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "deepseek",
            "light_model": "deepseek-chat",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )

    payload = _endpoint(app, "/operator/ai/ask", "POST")(
        {
            "question": "give me a concise quant assessment of whether the bot is ready for a 10 minute PAPER smoke run",
            "answer_mode": "AI_REASONING_STRATEGY",
            "page_context": {"page_id": "command", "page_title": "Run PAPER"},
        }
    )

    assert calls == []
    assert payload["answer_mode"] == "AI_REASONING_STRATEGY"
    assert payload["answer_source"] == "LOCAL_DETERMINISTIC"
    assert payload["provider_call_attempted"] is False
    assert payload["model_call_occurred"] is False
    assert payload["route_decision"]["reason_code"] == "HIGH_REASONING_API_APPROVAL_REQUIRED"
    assert "did not run a deep provider call" in payload["answer"]
    assert "No light-model fallback was treated as deep reasoning" in payload["answer"]
    assert payload["broker_call_occurred"] is False
    assert payload["trading_mutation_occurred"] is False


def test_ai_provider_credential_validation_is_not_labeled_live_api_success(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider(
        "deepseek",
        {
            "DEEPSEEK_API_KEY": "deepseek-test-token-value",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        },
    )
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    app = create_operator_app(provider=provider)

    payload = _endpoint(app, "/operator/ai/providers/validate", "POST")(
        {"provider_id": "deepseek", "model_name": "deepseek-chat", "validation_mode": "credential_presence"}
    )

    assert payload["validation_status"] == "CREDENTIAL_PRESENCE_CONFIRMED"
    assert payload["credential_presence_status"] == "PRESENT"
    assert payload["local_validation_status"] == "KEYS_PRESENT_RAW_SECRETS_HIDDEN"
    assert payload["live_api_test_status"] == "NOT_TESTED"
    assert payload["paid_call_occurred"] is False
    assert "No live AI API call was made" in payload["safe_error_message"]
