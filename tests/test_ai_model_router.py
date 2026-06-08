from __future__ import annotations

from app.ai_chief_operator.model_router import (
    HIGH_REASONING_API,
    LIGHT_API,
    LOCAL_GUIDE,
    LOCAL_MODEL_MODE,
    SUPREME_BOARD_PACKET_MODE,
    route_ai_request,
)
from app.ai_chief_operator.quant_persona import classify_quant_prompt


def test_router_defaults_to_free_local_guide_not_paid_api():
    decision = route_ai_request(
        requested_mode=LOCAL_GUIDE,
        provider_id="openai",
        model_name="gpt-5.5-pro",
        classification=classify_quant_prompt("Explain this page.", page_id="ai"),
        approved_paid_call=False,
        provider_configured=True,
        provider_implemented=True,
    )

    assert decision.provider_id == "deterministic_local"
    assert decision.cost_mode == "FREE_LOCAL"
    assert decision.answer_source == "LOCAL_DETERMINISTIC"
    assert decision.allowed_provider_call is False


def test_high_reasoning_api_requires_explicit_one_call_approval():
    decision = route_ai_request(
        requested_mode=HIGH_REASONING_API,
        provider_id="openai",
        model_name="gpt-5.5-pro",
        classification=classify_quant_prompt("What evidence blocks live readiness?", page_id="research"),
        approved_paid_call=False,
        provider_configured=True,
        provider_implemented=True,
    )

    assert decision.allowed_provider_call is False
    assert decision.approval_required is True
    assert decision.reason_code == "HIGH_REASONING_API_APPROVAL_REQUIRED"
    assert decision.answer_source == "LOCAL_DETERMINISTIC"


def test_high_reasoning_api_refuses_lower_model_without_silent_downgrade():
    decision = route_ai_request(
        requested_mode=HIGH_REASONING_API,
        provider_id="openai",
        model_name="gpt-5-mini",
        classification=classify_quant_prompt("Is this strategy statistically believable?", page_id="research"),
        approved_paid_call=True,
        provider_configured=True,
        provider_implemented=True,
    )

    assert decision.allowed_provider_call is False
    assert decision.reason_code == "NO_SILENT_DOWNGRADE_TO_LOWER_REASONING_MODEL"
    assert decision.cost_mode == "PROVIDER_ERROR"
    assert decision.model_suitable_for_governance is False


def test_serious_prompt_can_route_to_light_api_as_limited_advisory_not_governance():
    decision = route_ai_request(
        requested_mode=LIGHT_API,
        provider_id="openai",
        model_name="gpt-5-mini",
        classification=classify_quant_prompt("Audit readiness before live.", page_id="ai"),
        approved_paid_call=False,
        provider_configured=True,
        provider_implemented=True,
    )

    assert decision.allowed_provider_call is True
    assert decision.approval_required is False
    assert decision.answer_source == "API_LIGHT_MODEL"
    assert decision.reason_code == "LIGHT_API_SELECTED_SERIOUS_ADVISORY_LIMITED"
    assert decision.model_suitable_for_governance is False
    assert "not final quant/risk/governance authority" in str(decision.warning)


def test_supreme_board_packet_and_local_model_routes_are_labeled():
    packet = route_ai_request(
        requested_mode=SUPREME_BOARD_PACKET_MODE,
        provider_id="supreme_board_packet",
        model_name="chatgpt-pro-manual",
        classification=classify_quant_prompt("Draft a Codex packet.", page_id="ai"),
        approved_paid_call=False,
        provider_configured=True,
        provider_implemented=True,
    )
    local = route_ai_request(
        requested_mode=LOCAL_MODEL_MODE,
        provider_id="local_openai_compatible",
        model_name="local-model",
        classification=classify_quant_prompt("Explain this page.", page_id="ai"),
        approved_paid_call=False,
        provider_configured=True,
        provider_implemented=True,
    )

    assert packet.answer_source == "SUPREME_BOARD_PACKET"
    assert packet.cost_mode == "CHATGPT_PRO_MANUAL"
    assert packet.model_suitable_for_governance is True
    assert local.answer_source == "LOCAL_MODEL"
    assert local.cost_mode == "LOCAL_INFRA_COST"
    assert local.model_quality == "LOCAL_UNEVALUATED"
    assert local.model_suitable_for_governance is False
