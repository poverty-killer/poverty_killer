from __future__ import annotations

import inspect

from app.ai_chief_operator.config import AIChiefConfig
from app.ai_chief_operator.context_builder import build_ai_context, redact_secrets
from app.ai_chief_operator.governance_queue import GovernanceQueue
from app.ai_chief_operator.model_policy import classify_model_quality
from app.ai_chief_operator.models import normalize_recommendation
from app.ai_chief_operator.provider_gateway import AIProviderGateway
from app.ai_chief_operator.quant_persona import classify_quant_prompt, quant_persona_summary
from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def test_ai_provider_disabled_by_default():
    config = AIChiefConfig.from_env({})
    gateway = AIProviderGateway(config)

    assert config.provider_state() == "AI_DISABLED"
    assert gateway.status()["provider"]["provider_state"] == "AI_DISABLED"
    assert gateway.status()["can_execute"] is False


def test_ai_provider_auto_selects_openai_when_key_is_configured():
    config = AIChiefConfig.from_env({"OPENAI_API_KEY": "sk-hidden1234567890"})

    assert config.provider == "openai"
    assert config.provider_state() == "PROVIDER_READY"
    assert config.openai_configured is True
    assert config.openai_model == "gpt-5.5-pro"
    assert config.safe_summary()["model_quality"] == "HIGH_REASONING"
    assert config.safe_summary()["model_suitable_for_governance"] is True


def test_model_quality_registry_classifies_high_and_low_reasoning_models():
    assert classify_model_quality("openai", "gpt-5.5-pro") == "HIGH_REASONING"
    assert classify_model_quality("openai", "gpt-5.5-thinking") == "HIGH_REASONING"
    assert classify_model_quality("openai", "gpt-5-mini") == "LOW_REASONING"
    assert classify_model_quality("anthropic", "claude-opus-4.7") == "HIGH_REASONING"
    assert classify_model_quality("anthropic", "claude-haiku-4") == "LOW_REASONING"
    assert classify_model_quality("anthropic", "claude-sonnet-4") == "STANDARD"


def test_serious_quant_prompt_does_not_call_low_reasoning_model():
    calls = []

    def fake_post(url, headers, body, timeout):
        calls.append({"url": url, "headers": headers, "body": body, "timeout": timeout})
        return {"output_text": "This should not be called."}

    env = {"OPENAI_API_KEY": "sk-hidden1234567890", "PK_AI_CHIEF_OPENAI_MODEL": "gpt-5-mini"}
    gateway = AIProviderGateway(AIChiefConfig.from_env(env), credential_env=env, http_post=fake_post)

    answer = gateway.ask("Is this strategy statistically believable?", {}, {"page_id": "research"})

    assert calls == []
    assert answer["provider_mode"] == "DETERMINISTIC_FALLBACK"
    assert answer["model_name"] == "gpt-5-mini"
    assert answer["model_quality"] == "LOW_REASONING"
    assert answer["reasoning_policy"] == "LOWER_MODEL_WARNING"
    assert answer["model_suitable_for_governance"] is False
    assert "LOWER-REASONING MODEL ACTIVE" in answer["response"]


def test_openai_ai_ask_uses_real_provider_path_without_exposing_secrets():
    calls = []

    def fake_post(url, headers, body, timeout):
        calls.append({"url": url, "headers": headers, "body": body, "timeout": timeout})
        return {"output_text": "Model advisory: Alpaca credentials are the first blocker."}

    env = {"OPENAI_API_KEY": "sk-hidden1234567890", "PK_AI_CHIEF_TIMEOUT_SECONDS": "2"}
    gateway = AIProviderGateway(AIChiefConfig.from_env(env), credential_env=env, http_post=fake_post)

    answer = gateway.ask(
        "Can I run PAPER?",
        {
            "provider_readiness": {"OPENAI_API_KEY": "sk-hidden1234567890", "fingerprint": "sha256:abc123"},
            "latest_run_archive_summary": [{"report_path": r"C:\Users\shahn\OneDrive\Desktop\poverty_killer\state\operator\reports\paper.md"}],
        },
        {"page_id": "positions"},
    )

    assert answer["status"] == "ANSWERED_MODEL"
    assert answer["response_source"] == "OPENAI_RESPONSES_API"
    assert answer["provider_mode"] == "LIVE_OPENAI"
    assert answer["model_name"] == "gpt-5.5-pro"
    assert answer["model_quality"] == "HIGH_REASONING"
    assert answer["reasoning_policy"] == "HIGHEST_AVAILABLE_REQUIRED"
    assert answer["model_suitable_for_governance"] is True
    assert answer["can_execute"] is False
    assert answer["broker_call_occurred"] is False
    assert calls[0]["url"].endswith("/responses")
    assert calls[0]["headers"]["Authorization"].startswith("Bearer ")
    assert "sk-hidden" not in str(calls[0]["body"])
    assert "sha256:abc123" not in str(calls[0]["body"])
    assert "C:\\Users" not in str(calls[0]["body"])
    assert "state\\operator" not in str(calls[0]["body"])
    assert "sk-hidden" not in str(answer)


def test_unavailable_high_reasoning_model_returns_clear_provider_error():
    def failing_post(url, headers, body, timeout):
        del url, headers, body, timeout
        raise RuntimeError("provider_http_404: model_not_found")

    env = {"OPENAI_API_KEY": "sk-hidden1234567890", "OPENAI_HIGH_REASONING_MODEL": "gpt-5.5-pro"}
    gateway = AIProviderGateway(AIChiefConfig.from_env(env), credential_env=env, http_post=failing_post)

    answer = gateway.ask("What evidence blocks live readiness?", {}, {"page_id": "research"})

    assert answer["status"] == "PROVIDER_ERROR"
    assert answer["provider_mode"] == "PROVIDER_ERROR"
    assert answer["model_quality"] == "UNKNOWN"
    assert answer["reasoning_policy"] == "FALLBACK_ONLY_LIMITED"
    assert answer["model_suitable_for_governance"] is False
    assert "no model answer is being faked" in answer["response"]
    assert "provider_http_404" in answer["response"]
    assert "OPENAI_HIGH_REASONING_MODEL" in answer["response"]


def test_empty_high_reasoning_response_is_provider_error_not_fake_answer():
    def empty_post(url, headers, body, timeout):
        del url, headers, body, timeout
        return {"id": "resp_empty", "output": []}

    env = {"OPENAI_API_KEY": "sk-hidden1234567890", "OPENAI_HIGH_REASONING_MODEL": "gpt-5.5-pro"}
    gateway = AIProviderGateway(AIChiefConfig.from_env(env), credential_env=env, http_post=empty_post)

    answer = gateway.ask("Why is PAPER run blocked?", {}, {"page_id": "command"})

    assert answer["status"] == "PROVIDER_ERROR"
    assert answer["provider_state"] == "PROVIDER_ERROR"
    assert answer["response_source"] == "PROVIDER_ERROR_EMPTY_MODEL_RESPONSE"
    assert answer["provider_mode"] == "PROVIDER_ERROR"
    assert answer["model_name"] == "gpt-5.5-pro"
    assert answer["model_quality"] == "UNKNOWN"
    assert answer["reasoning_policy"] == "FALLBACK_ONLY_LIMITED"
    assert answer["model_suitable_for_governance"] is False
    assert "no expert model answer is being faked" in answer["response"]


def test_mock_ai_provider_returns_structured_recommendation():
    gateway = AIProviderGateway(AIChiefConfig(provider="mock", enabled=True, mock_mode=True))

    recommendation = gateway.analyze({"alerts": [], "action_center": {"items": []}, "live_status": "LIVE_LOCKED", "real_money_blocked": True})

    payload = recommendation.to_dict()
    assert payload["recommendation_type"] == "OBSERVATION"
    assert payload["status"] == "PENDING_REVIEW"
    assert payload["can_execute"] is False
    assert payload["requires_shan_approval"] is True


def test_ai_context_builder_redacts_secrets_and_raw_logs():
    context = build_ai_context(
        run_archive={"runs": [{"wrapper_log_paths": {"stdout": "logs/run.log"}}]},
        action_center={"items": [{"detail": "token sk-testsecret1234567890"}]},
        decision_explainer={},
        pnl={"api_key": "abc123"},
        tca={},
        world_awareness={"nested": {"password": "secret-value"}},
        readiness={"OPENAI_API_KEY": "sk-real1234567890"},
        alerts=[],
    )

    text = str(context)
    assert "sk-testsecret" not in text
    assert "secret-value" not in text
    assert "abc123" not in text
    assert context["raw_logs_included"] is False
    assert context["secrets_values_exposed"] is False
    assert context["scope"] == "trading_quant_operator_research_only"
    assert context["persona"]["can_execute"] is False


def test_redact_secrets_handles_plain_nested_values():
    redacted = redact_secrets({"safe": "ok", "secret_token": "abc", "message": "sk-hidden1234567890"})

    assert redacted["safe"] == "ok"
    assert redacted["secret_token"] == "REDACTED"
    assert redacted["message"] == "REDACTED"


def test_malformed_and_unsafe_ai_output_is_rejected_or_downgraded():
    malformed = normalize_recommendation(
        {"recommendation_type": "TRADE_NOW", "summary": "bad", "can_execute": True},
        provider="mock",
    ).to_dict()
    live = normalize_recommendation(
        {"recommendation_type": "LIVE_READINESS_REVIEW", "summary": "live", "proposed_action": "ENABLE_LIVE_AND_CANCEL", "can_execute": True},
        provider="mock",
    ).to_dict()

    assert malformed["status"] == "REJECTED"
    assert malformed["can_execute"] is False
    assert live["status"] == "LIVE_REQUIRES_SEPARATE_APPROVAL"
    assert live["can_execute"] is False


def test_ai_quant_persona_is_domain_scoped_and_refuses_general_or_unsafe_prompts():
    persona = quant_persona_summary()
    general = classify_quant_prompt("write a dinner recipe")
    unsafe = classify_quant_prompt("enable live and submit order now")
    quant = classify_quant_prompt("Where is the edge in latest run TCA evidence?")
    setup = classify_quant_prompt("Where do I enter Alpaca keys?", page_id="providers")
    portfolio = classify_quant_prompt("What do I own right now?", page_id="positions")
    codex = classify_quant_prompt("What should I ask Codex to fix?", page_id="ai")

    assert persona["identity"].startswith("Chief Quant Advisor")
    assert "You are the Chief Quant Advisor" in persona["system_policy"]
    assert persona["can_execute"] is False
    assert general["allowed"] is False
    assert general["reason_code"] == "NON_TRADING_GENERALIST_PROMPT"
    assert unsafe["allowed"] is False
    assert unsafe["reason_code"] == "FORBIDDEN_TRADING_OR_SECRET_REQUEST"
    assert unsafe["mode"] == "UNSAFE_REQUEST_REFUSAL"
    assert quant["allowed"] is True
    assert quant["mode"] == "QUANT_ADVISOR"
    assert setup["mode"] == "SETUP_HELP"
    assert portfolio["mode"] == "PORTFOLIO_REVIEW"
    assert codex["mode"] == "CODEX_PACKET_ADVISOR"


def test_governance_queue_approve_paper_research_does_not_start_paper(tmp_path):
    queue = GovernanceQueue(path=tmp_path / "queue.jsonl")
    rec = normalize_recommendation({"summary": "try paper research"}, provider="mock")
    queued = queue.add(rec)

    result = queue.approve_paper_research(queued["recommendation_id"])

    assert result["status"] == "APPROVED_FOR_PAPER_RESEARCH"
    assert result["paper_started"] is False
    assert result["broker_call_occurred"] is False
    assert result["trading_mutation_occurred"] is False


def test_operator_ai_endpoints_return_safe_mutation_flags(tmp_path):
    runtime_config = OperatorRuntimeConfig.from_env({}, repo_root=tmp_path)
    provider = OperatorSnapshotProvider(
        runtime_config=runtime_config,
        ai_config=AIChiefConfig(provider="mock", enabled=True, mock_mode=True),
        ai_queue=GovernanceQueue(path=tmp_path / "state" / "operator" / "ai_queue.jsonl"),
    )
    app = create_operator_app(provider=provider)

    status = _endpoint(app, "/operator/ai/status")()
    analyzed = _endpoint(app, "/operator/ai/analyze", "POST")({"advisory_only": True})
    quant_review = _endpoint(app, "/operator/ai/quant-review", "POST")({"prompt": "What is the weakest assumption?"})
    codex = _endpoint(app, "/operator/ai/draft-codex-packet", "POST")({"prompt": "Draft a Codex packet for TCA review"})
    rec_id = analyzed["recommendation"]["recommendation_id"]
    approved = _endpoint(app, "/operator/ai/recommendations/{recommendation_id}/approve-paper-research", "POST")(rec_id)
    action_center = _endpoint(app, "/operator/action-center")()

    assert status["can_execute"] is False
    assert analyzed["broker_call_occurred"] is False
    assert analyzed["trading_mutation_occurred"] is False
    assert analyzed["recommendation"]["can_execute"] is False
    assert quant_review["recommendation"]["can_execute"] is False
    assert quant_review["broker_call_occurred"] is False
    assert codex["can_execute"] is False
    assert codex["broker_call_occurred"] is False
    assert "Forbidden" in codex["draft_packet"] or "Forbidden:" in codex["draft_packet"]
    assert approved["paper_started"] is False
    assert approved["trading_mutation_occurred"] is False
    assert action_center["safe_mutation_flags"]["can_execute"] is False


def test_operator_system_map_endpoint_exists(tmp_path):
    app = create_operator_app(
        provider=OperatorSnapshotProvider(runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path))
    )

    payload = _endpoint(app, "/operator/system-map")()

    assert payload["summary"]["advisory_ai_only"] is True
    assert "AI Chief Operator" in payload["markdown"]
    assert payload["secrets_values_exposed"] is False


def test_ai_and_operator_intelligence_do_not_import_execution_or_broker_calls():
    from app.ai_chief_operator import provider_gateway
    from app.operator_intelligence import archive

    source = inspect.getsource(provider_gateway) + inspect.getsource(archive)

    assert "from app.execution" not in source
    assert "import app.execution" not in source
    assert "from app.broker" not in source
    assert "import app.broker" not in source
