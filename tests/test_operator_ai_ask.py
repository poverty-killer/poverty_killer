from __future__ import annotations

from app.ai_chief_operator.config import AIChiefConfig
from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.operator_credentials.store import LocalCredentialStore


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


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

    assert payload["status"] == "ANSWERED_FALLBACK"
    assert payload["response_source"] == "MOCK_MODE_DETERMINISTIC"
    assert payload["provider_mode"] == "DETERMINISTIC_FALLBACK"
    assert payload["model_name"] is None
    assert payload["model_quality"] == "FALLBACK_ONLY"
    assert payload["reasoning_policy"] == "FALLBACK_ONLY_LIMITED"
    assert payload["model_suitable_for_governance"] is False
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
