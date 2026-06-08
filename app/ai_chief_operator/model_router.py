"""Advisory AI mode router.

The router decides whether an ask is free local guidance, an approved paid API
call, a local model call, or a Supreme Board packet. It does not call providers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ai_chief_operator.model_policy import HIGH_REASONING, LOCAL_UNEVALUATED, SERIOUS_AI_MODES, classify_model_quality
from app.ai_chief_operator.model_registry import (
    API_HIGH_REASONING_APPROVED,
    API_LIGHT_MODEL,
    CHATGPT_PRO_MANUAL,
    FREE_LOCAL,
    LOCAL_DETERMINISTIC,
    LOCAL_INFRA_COST,
    LOCAL_MODEL,
    LOW_COST_API,
    PAID_API_APPROVED,
    PROVIDER_ERROR_COST,
    PROVIDER_ERROR_SOURCE,
    SUPREME_BOARD_PACKET,
    get_ai_provider_profile,
)


LOCAL_GUIDE = "LOCAL_GUIDE"
LIGHT_API = "LIGHT_API"
HIGH_REASONING_API = "HIGH_REASONING_API"
SUPREME_BOARD_PACKET_MODE = "SUPREME_BOARD_PACKET"
LOCAL_MODEL_MODE = "LOCAL_MODEL"
PROVIDER_DISABLED = "PROVIDER_DISABLED"

ROUTING_MODES = (
    LOCAL_GUIDE,
    LIGHT_API,
    HIGH_REASONING_API,
    SUPREME_BOARD_PACKET_MODE,
    LOCAL_MODEL_MODE,
    PROVIDER_DISABLED,
)


@dataclass(frozen=True)
class AIRouteDecision:
    route_mode: str
    provider_id: str
    model_name: str | None
    model_quality: str
    cost_mode: str
    answer_source: str
    allowed_provider_call: bool
    approval_required: bool
    reason_code: str
    warning: str | None
    model_suitable_for_governance: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_mode": self.route_mode,
            "provider_id": self.provider_id,
            "model_name": self.model_name,
            "model_quality": self.model_quality,
            "cost_mode": self.cost_mode,
            "answer_source": self.answer_source,
            "allowed_provider_call": self.allowed_provider_call,
            "approval_required": self.approval_required,
            "reason_code": self.reason_code,
            "warning": self.warning,
            "model_suitable_for_governance": self.model_suitable_for_governance,
        }


def normalize_route_mode(value: str | None) -> str:
    raw = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "": LOCAL_GUIDE,
        "LOCAL": LOCAL_GUIDE,
        "FREE": LOCAL_GUIDE,
        "FREE_LOCAL": LOCAL_GUIDE,
        "PACKET": SUPREME_BOARD_PACKET_MODE,
        "SUPREME_BOARD": SUPREME_BOARD_PACKET_MODE,
        "HIGH": HIGH_REASONING_API,
        "HIGH_REASONING": HIGH_REASONING_API,
        "API_HIGH": HIGH_REASONING_API,
        "LIGHT": LIGHT_API,
        "API_LIGHT": LIGHT_API,
    }
    return aliases.get(raw, raw if raw in ROUTING_MODES else LOCAL_GUIDE)


def route_ai_request(
    *,
    requested_mode: str | None,
    provider_id: str | None,
    model_name: str | None,
    classification: dict[str, Any],
    approved_paid_call: bool,
    provider_configured: bool,
    provider_implemented: bool,
) -> AIRouteDecision:
    mode = normalize_route_mode(requested_mode)
    prompt_mode = str(classification.get("mode") or "OPERATOR_GUIDE")
    serious = prompt_mode in SERIOUS_AI_MODES
    profile = get_ai_provider_profile(provider_id) or get_ai_provider_profile("deterministic_local")
    chosen_provider = profile.provider_id if profile else "deterministic_local"
    chosen_model = model_name or (profile.default_model if profile else None)
    model_quality = classify_model_quality(chosen_provider, chosen_model)

    if mode == LOCAL_GUIDE:
        return AIRouteDecision(
            route_mode=LOCAL_GUIDE,
            provider_id="deterministic_local",
            model_name="deterministic-local-guide",
            model_quality="FALLBACK_ONLY",
            cost_mode=FREE_LOCAL,
            answer_source=LOCAL_DETERMINISTIC,
            allowed_provider_call=False,
            approval_required=False,
            reason_code="ROUTED_LOCAL_GUIDE_NO_API_CALL",
            warning="Local Guide is deterministic and limited.",
            model_suitable_for_governance=False,
        )

    if mode == SUPREME_BOARD_PACKET_MODE:
        return AIRouteDecision(
            route_mode=SUPREME_BOARD_PACKET_MODE,
            provider_id="supreme_board_packet",
            model_name="chatgpt-pro-manual",
            model_quality=HIGH_REASONING,
            cost_mode=CHATGPT_PRO_MANUAL,
            answer_source=SUPREME_BOARD_PACKET,
            allowed_provider_call=False,
            approval_required=False,
            reason_code="ROUTED_SUPREME_BOARD_PACKET_NO_API_CALL",
            warning=None,
            model_suitable_for_governance=True,
        )

    if mode == HIGH_REASONING_API:
        if not approved_paid_call:
            return AIRouteDecision(
                route_mode=PROVIDER_DISABLED,
                provider_id=chosen_provider,
                model_name=chosen_model,
                model_quality=model_quality,
                cost_mode=FREE_LOCAL,
                answer_source=LOCAL_DETERMINISTIC,
                allowed_provider_call=False,
                approval_required=True,
                reason_code="HIGH_REASONING_API_APPROVAL_REQUIRED",
                warning=(
                    "I can explain current system facts locally, but final quant/risk/governance judgment requires "
                    "either an approved high-reasoning API call or a Supreme Board packet."
                ),
                model_suitable_for_governance=False,
            )
        if not provider_configured:
            return AIRouteDecision(
                route_mode=PROVIDER_DISABLED,
                provider_id=chosen_provider,
                model_name=chosen_model,
                model_quality=model_quality,
                cost_mode=FREE_LOCAL,
                answer_source=LOCAL_DETERMINISTIC,
                allowed_provider_call=False,
                approval_required=False,
                reason_code="PROVIDER_CREDENTIALS_MISSING",
                warning="Selected provider is missing credentials.",
                model_suitable_for_governance=False,
            )
        if not provider_implemented:
            return AIRouteDecision(
                route_mode=PROVIDER_DISABLED,
                provider_id=chosen_provider,
                model_name=chosen_model,
                model_quality=model_quality,
                cost_mode=PROVIDER_ERROR_COST,
                answer_source=PROVIDER_ERROR_SOURCE,
                allowed_provider_call=False,
                approval_required=False,
                reason_code="PROVIDER_ADAPTER_NOT_IMPLEMENTED",
                warning="Selected provider is scaffolded but not callable.",
                model_suitable_for_governance=False,
            )
        if model_quality != HIGH_REASONING:
            return AIRouteDecision(
                route_mode=PROVIDER_DISABLED,
                provider_id=chosen_provider,
                model_name=chosen_model,
                model_quality=model_quality,
                cost_mode=PROVIDER_ERROR_COST,
                answer_source=PROVIDER_ERROR_SOURCE,
                allowed_provider_call=False,
                approval_required=False,
                reason_code="NO_SILENT_DOWNGRADE_TO_LOWER_REASONING_MODEL",
                warning="No silent downgrade: serious quant/governance work requires a HIGH_REASONING model.",
                model_suitable_for_governance=False,
            )
        return AIRouteDecision(
            route_mode=HIGH_REASONING_API,
            provider_id=chosen_provider,
            model_name=chosen_model,
            model_quality=model_quality,
            cost_mode=PAID_API_APPROVED,
            answer_source=API_HIGH_REASONING_APPROVED,
            allowed_provider_call=True,
            approval_required=False,
            reason_code="HIGH_REASONING_API_APPROVED",
            warning="High-reasoning API call approved for this request.",
            model_suitable_for_governance=True,
        )

    if mode == LOCAL_MODEL_MODE:
        if not provider_configured:
            return AIRouteDecision(
                route_mode=PROVIDER_DISABLED,
                provider_id="local_openai_compatible",
                model_name=chosen_model,
                model_quality=LOCAL_UNEVALUATED,
                cost_mode=PROVIDER_ERROR_COST,
                answer_source=PROVIDER_ERROR_SOURCE,
                allowed_provider_call=False,
                approval_required=False,
                reason_code="LOCAL_MODEL_ENDPOINT_MISSING",
                warning="Local Model requires LOCAL_AI_BASE_URL and LOCAL_AI_MODEL.",
                model_suitable_for_governance=False,
            )
        return AIRouteDecision(
            route_mode=LOCAL_MODEL_MODE,
            provider_id="local_openai_compatible",
            model_name=chosen_model,
            model_quality=LOCAL_UNEVALUATED,
            cost_mode=LOCAL_INFRA_COST,
            answer_source=LOCAL_MODEL,
            allowed_provider_call=True,
            approval_required=False,
            reason_code="LOCAL_MODEL_SELECTED_UNEVALUATED",
            warning="Local model is unevaluated and not suitable for final governance decisions.",
            model_suitable_for_governance=False,
        )

    if mode == LIGHT_API:
        if not provider_configured or not provider_implemented:
            return AIRouteDecision(
                route_mode=PROVIDER_DISABLED,
                provider_id=chosen_provider,
                model_name=chosen_model,
                model_quality=model_quality,
                cost_mode=PROVIDER_ERROR_COST,
                answer_source=PROVIDER_ERROR_SOURCE,
                allowed_provider_call=False,
                approval_required=False,
                reason_code="LIGHT_PROVIDER_UNAVAILABLE",
                warning="Selected light provider is unavailable or not implemented.",
                model_suitable_for_governance=False,
            )
        return AIRouteDecision(
            route_mode=LIGHT_API,
            provider_id=chosen_provider,
            model_name=chosen_model,
            model_quality=model_quality,
            cost_mode=LOW_COST_API,
            answer_source=API_LIGHT_MODEL,
            allowed_provider_call=True,
            approval_required=False,
            reason_code="LIGHT_API_SELECTED_SERIOUS_ADVISORY_LIMITED" if serious else "LIGHT_API_SELECTED",
            warning=(
                "Light API may answer this serious advisory prompt, but it is not final quant/risk/governance authority."
                if serious
                else "Light API is not suitable for final quant/risk/governance decisions."
            ),
            model_suitable_for_governance=False,
        )

    return AIRouteDecision(
        route_mode=PROVIDER_DISABLED,
        provider_id=chosen_provider,
        model_name=chosen_model,
        model_quality=model_quality,
        cost_mode=PROVIDER_ERROR_COST,
        answer_source=PROVIDER_ERROR_SOURCE,
        allowed_provider_call=False,
        approval_required=False,
        reason_code="PROVIDER_DISABLED",
        warning="Provider disabled or unavailable.",
        model_suitable_for_governance=False,
    )
