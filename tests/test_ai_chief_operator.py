from __future__ import annotations

import inspect

from app.ai_chief_operator.config import AIChiefConfig
from app.ai_chief_operator.context_builder import build_ai_context, redact_secrets
from app.ai_chief_operator.governance_queue import GovernanceQueue
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

    assert persona["identity"].startswith("AI Quant Research Chief")
    assert persona["can_execute"] is False
    assert general["allowed"] is False
    assert general["reason_code"] == "NON_TRADING_GENERALIST_PROMPT"
    assert unsafe["allowed"] is False
    assert unsafe["reason_code"] == "FORBIDDEN_TRADING_OR_SECRET_REQUEST"
    assert quant["allowed"] is True


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
