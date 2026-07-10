"""Provider adapters behind the common advisory AI interface.

Adapters are intentionally narrow: text in, text out, no tools, no broker calls,
no execution authority. Every adapter receives the forced expert persona policy
from the router/gateway and must include it in the provider payload or packet.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.ai_chief_operator.context_builder import redact_secrets
from app.ai_chief_operator.model_registry import (
    API_HIGH_REASONING_APPROVED,
    API_LIGHT_MODEL,
    CHATGPT_PRO_MANUAL,
    FREE_LOCAL,
    LOCAL_DETERMINISTIC,
    LOCAL_INFRA_COST,
    LOCAL_MODEL,
    LOW_COST_API,
    NOT_CONFIGURED_SOURCE,
    PAID_API_APPROVED,
    PROVIDER_ERROR_COST,
    PROVIDER_ERROR_SOURCE,
    SUPREME_BOARD_PACKET,
)
from app.ai_chief_operator.quant_persona import AI_QUANT_ROLES


HttpPost = Callable[[str, dict[str, str], dict[str, Any], int], dict[str, Any]]
LOCAL_PATH_RE = re.compile(
    r"([A-Za-z]:\\[^\s\"']+|/mnt/[A-Za-z]/[^\s\"']+|/home/[^\s\"']+|state[/\\][^\s\"']+|logs[/\\][^\s\"']+)",
    re.IGNORECASE,
)
PATH_KEY_PARTS = ("path", "stdout", "stderr", "log_file", "log_path", "report_path")


@dataclass(frozen=True)
class AIProviderRequest:
    provider_id: str
    model_name: str | None
    mode: str
    question: str
    forced_persona_policy: str
    safe_context: dict[str, Any]
    max_output_tokens: int = 1800
    temperature: float | None = None
    reasoning_effort: str | None = None
    approved_paid_call: bool = False
    request_classification: dict[str, Any] = field(default_factory=dict)
    allow_tools: bool = False
    allow_broker_tools: bool = False


@dataclass(frozen=True)
class AIProviderResponse:
    answer: str
    provider_id: str
    provider_mode: str
    model_name: str | None
    model_quality: str
    cost_mode: str
    answer_source: str
    reasoning_policy: str
    model_suitable_for_governance: bool
    persona_enforced: bool
    expert_roles_applied: tuple[str, ...]
    provider_error_category: str | None = None
    provider_error_message_safe: str | None = None
    model_call_occurred: bool = False
    model_call_attempted: bool = False
    provider_response_received: bool = False
    fallback_reason: str | None = None
    actual_model_name: str | None = None
    provider_request_id: str | None = None
    endpoint_family: str | None = None
    latency_ms: int | None = None
    http_status_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "response": self.answer,
            "provider": self.provider_id,
            "provider_id": self.provider_id,
            "provider_mode": self.provider_mode,
            "model_name": self.model_name,
            "model": self.model_name,
            "model_quality": self.model_quality,
            "cost_mode": self.cost_mode,
            "answer_source": self.answer_source,
            "response_source": self.answer_source,
            "reasoning_policy": self.reasoning_policy,
            "model_suitable_for_governance": self.model_suitable_for_governance,
            "governance_suitable": self.model_suitable_for_governance,
            "persona_enforced": self.persona_enforced,
            "expert_roles_applied": list(self.expert_roles_applied),
            "provider_error_category": self.provider_error_category,
            "provider_error_message_safe": self.provider_error_message_safe,
            "model_call_occurred": self.model_call_occurred,
            "model_call_attempted": self.model_call_attempted,
            "provider_response_received": self.provider_response_received,
            "fallback_reason": self.fallback_reason,
            "actual_model_name": self.actual_model_name,
            "provider_request_id": self.provider_request_id,
            "endpoint_family": self.endpoint_family,
            "latency_ms": self.latency_ms,
            "http_status_code": self.http_status_code,
            "can_execute": False,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
            "secrets_exposed": False,
            "secrets_values_exposed": False,
        }


def compact_safe_payload(request: AIProviderRequest) -> str:
    safe_context = _redact_local_paths(redact_secrets(request.safe_context))
    payload = {
        "question": request.question,
        "mode": request.mode,
        "request_classification": request.request_classification,
        "safe_context": safe_context,
        "hard_boundaries": {
            "advisory_only": True,
            "can_execute": False,
            "allow_tools": request.allow_tools,
            "allow_broker_tools": False,
            "broker_call_allowed": False,
            "live_enablement_allowed": False,
            "real_money_allowed": False,
            "manual_trading_allowed": False,
            "threshold_mutation_allowed": False,
            "secret_handling": "Do not request, reveal, infer, or restate secrets.",
        },
    }
    return json.dumps(payload, sort_keys=True, default=str)


def _redact_local_paths(value: Any, *, key: str = "") -> Any:
    key_lower = key.lower()
    if isinstance(value, dict):
        return {str(k): _redact_local_paths(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_local_paths(item, key=key) for item in value[:100]]
    if isinstance(value, tuple):
        return tuple(_redact_local_paths(item, key=key) for item in value[:100])
    if isinstance(value, str):
        if any(part in key_lower for part in PATH_KEY_PARTS):
            return "REDACTED_LOCAL_PATH"
        return LOCAL_PATH_RE.sub("REDACTED_LOCAL_PATH", value)
    return value


def forced_prompt(request: AIProviderRequest) -> str:
    return (
        f"{request.forced_persona_policy}\n"
        "You must answer as a trading-system expert, not as a generic assistant. "
        "Default to a clean commercial chat answer: direct answer first, at most 2-5 useful bullets, and one next step only when useful. "
        "Do not dump route labels, raw diagnostics, provider counts, account dumps, archived runs, or JSON in the main answer unless explicitly asked for diagnostics. "
        "Separate broker-confirmed truth, market truth, local engine state, model inference, missing evidence, and speculation. "
        "Use only the structured safe_context evidence_contract and evidence packets as factual authority. "
        "If an evidence packet is absent or marked missing, say exactly: Unknown because this evidence is missing. "
        "Do not fill missing broker truth, market truth, risk results, portfolio values, blockers, fills, fees, TCA, or P&L from general knowledge. "
        "For model/provider identity questions, truthfully identify the selected provider/model and the actual answer source from the route context; never imply a local fallback was provider-authored. "
        "For quant/risk/governance questions include evidence, counterargument, risk, missing data, proof/disproof, and safe next test. "
        "For operator questions give exact page/control next steps. Never suggest manual trades, live enablement, broker calls, or guardrail bypass.\n\n"
        f"{compact_safe_payload(request)}"
    )


def extract_text_fields(value: Any) -> str:
    parts: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("output_text", "text", "refusal"):
                candidate = node.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    parts.append(candidate)
                elif isinstance(candidate, dict) and isinstance(candidate.get("value"), str):
                    parts.append(candidate["value"])
            for key in ("output", "content", "message", "messages", "choices", "candidates", "parts"):
                if key in node:
                    visit(node[key])
        elif isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, str) and node.strip():
            parts.append(node)

    visit(value)
    return "\n".join(dict.fromkeys(part.strip() for part in parts if part.strip()))


class ProviderAdapter:
    def ask_ai(self, request: AIProviderRequest) -> AIProviderResponse:
        raise NotImplementedError


class DeterministicLocalAdapter(ProviderAdapter):
    def ask_ai(self, request: AIProviderRequest) -> AIProviderResponse:
        answer = "\n".join(
            [
                "DETERMINISTIC LOCAL GUIDE - not a full AI quant reasoning response.",
                "I can explain current system facts locally, but final quant/risk/governance judgment requires either an approved high-reasoning API call or a Supreme Board packet.",
                f"Question: {request.question or 'No question supplied.'}",
                f"Mode: {request.mode}.",
                "Known boundaries: advisory-only, can_execute=false, no broker calls, no live or real-money enablement, no strategy/threshold mutation.",
            ]
        )
        return AIProviderResponse(
            answer=answer,
            provider_id="deterministic_local",
            provider_mode="DETERMINISTIC_FALLBACK",
            model_name=request.model_name or "deterministic-local-guide",
            model_quality="FALLBACK_ONLY",
            cost_mode=FREE_LOCAL,
            answer_source=LOCAL_DETERMINISTIC,
            reasoning_policy="FALLBACK_ONLY_LIMITED",
            model_suitable_for_governance=False,
            persona_enforced=True,
            expert_roles_applied=AI_QUANT_ROLES,
            model_call_occurred=False,
        )


class SupremeBoardPacketAdapter(ProviderAdapter):
    def ask_ai(self, request: AIProviderRequest) -> AIProviderResponse:
        context = redact_secrets(request.safe_context)
        page = context.get("page_context") or {}
        packet = "\n".join(
            [
                "POVERTY_KILLER - SUPREME BOARD CHIEF QUANT PACKET",
                "",
                "Forced role:",
                request.forced_persona_policy,
                "",
                "Question for Supreme Board:",
                request.question or "Review the current operator state.",
                "",
                "Active page:",
                f"- page_id: {page.get('page_id') or context.get('page_id') or 'unknown'}",
                f"- page_title: {page.get('page_title') or context.get('page_title') or 'unknown'}",
                "",
                "Router status:",
                f"- provider_id: {request.provider_id}",
                f"- model_name: {request.model_name or 'chatgpt-pro-manual'}",
                f"- mode: {request.mode}",
                "- cost_mode: CHATGPT_PRO_MANUAL",
                "",
                "Safe context summary:",
                json.dumps(context, indent=2, sort_keys=True, default=str)[:6000],
                "",
                "Hard laws:",
                "- Advisory only.",
                "- No live trading enablement.",
                "- No real-money enablement.",
                "- No manual buy/sell, force trade, cancel, flatten, or liquidate.",
                "- No broker calls or broker mutation.",
                "- No secret values or raw logs.",
                "- Separate broker-confirmed truth, market truth, local engine state, model inference, missing evidence, and speculation.",
                "",
                "Exact ask:",
                "Give expert quant/operator/risk/execution guidance using only the safe context above. Identify known facts, unknowns, blockers, missing proof, next safe PAPER validation step, and whether a Codex packet is needed.",
            ]
        )
        return AIProviderResponse(
            answer=packet,
            provider_id="supreme_board_packet",
            provider_mode="SUPREME_BOARD_PACKET",
            model_name=request.model_name or "chatgpt-pro-manual",
            model_quality="HIGH_REASONING",
            cost_mode=CHATGPT_PRO_MANUAL,
            answer_source=SUPREME_BOARD_PACKET,
            reasoning_policy="HIGHEST_AVAILABLE_REQUIRED",
            model_suitable_for_governance=True,
            persona_enforced=True,
            expert_roles_applied=AI_QUANT_ROLES,
            model_call_occurred=False,
        )


class NotImplementedAdapter(ProviderAdapter):
    def __init__(self, provider_id: str, model_quality: str = "UNKNOWN") -> None:
        self.provider_id = provider_id
        self.model_quality = model_quality

    def ask_ai(self, request: AIProviderRequest) -> AIProviderResponse:
        return AIProviderResponse(
            answer=(
                f"{self.provider_id} adapter is scaffolded but not implemented for live calls in this seam. "
                "No provider success is being faked. Use Local Guide or Supreme Board Packet, or configure an implemented provider."
            ),
            provider_id=self.provider_id,
            provider_mode="PROVIDER_ERROR",
            model_name=request.model_name,
            model_quality=self.model_quality,
            cost_mode=PROVIDER_ERROR_COST,
            answer_source=PROVIDER_ERROR_SOURCE,
            reasoning_policy="FALLBACK_ONLY_LIMITED",
            model_suitable_for_governance=False,
            persona_enforced=True,
            expert_roles_applied=AI_QUANT_ROLES,
            provider_error_category="NOT_IMPLEMENTED",
            provider_error_message_safe="Adapter scaffolded but not callable.",
            model_call_occurred=False,
            model_call_attempted=False,
            provider_response_received=False,
            fallback_reason="NOT_IMPLEMENTED",
        )


class OpenAIResponsesAdapter(ProviderAdapter):
    def __init__(self, *, api_key: str, base_url: str, http_post: HttpPost, timeout_seconds: int, model_quality: str, provider_id: str = "openai") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.http_post = http_post
        self.timeout_seconds = timeout_seconds
        self.model_quality = model_quality
        self.provider_id = provider_id

    def ask_ai(self, request: AIProviderRequest) -> AIProviderResponse:
        started = time.monotonic()
        body = {
            "model": request.model_name,
            "input": forced_prompt(request),
            "max_output_tokens": request.max_output_tokens,
        }
        if request.reasoning_effort:
            body["reasoning"] = {"effort": request.reasoning_effort}
        response = self.http_post(
            f"{self.base_url}/responses",
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            body,
            self.timeout_seconds,
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        text = extract_text_fields(response).strip()
        if not text:
            return AIProviderResponse(
                answer="Provider returned an empty advisory response. No provider success is being faked.",
                provider_id=self.provider_id,
                provider_mode="PROVIDER_ERROR",
                model_name=request.model_name,
                model_quality="UNKNOWN",
                cost_mode=PROVIDER_ERROR_COST,
                answer_source=PROVIDER_ERROR_SOURCE,
                reasoning_policy="FALLBACK_ONLY_LIMITED",
                model_suitable_for_governance=False,
                persona_enforced=True,
                expert_roles_applied=AI_QUANT_ROLES,
                provider_error_category="EMPTY_MODEL_RESPONSE",
                provider_error_message_safe="Provider returned empty response.",
                model_call_occurred=False,
                model_call_attempted=True,
                provider_response_received=True,
                fallback_reason="EMPTY_MODEL_RESPONSE",
                actual_model_name=str(response.get("model") or request.model_name or ""),
                provider_request_id=str(response.get("id") or "") or None,
                endpoint_family="openai_responses",
                latency_ms=latency_ms,
                http_status_code=response.get("status_code") if isinstance(response.get("status_code"), int) else None,
            )
        return AIProviderResponse(
            answer=text,
            provider_id=self.provider_id,
            provider_mode="LIVE_OPENAI",
            model_name=request.model_name,
            model_quality=self.model_quality,
            cost_mode=PAID_API_APPROVED if request.mode == "HIGH_REASONING_API" else LOW_COST_API,
            answer_source=API_HIGH_REASONING_APPROVED if request.mode == "HIGH_REASONING_API" else API_LIGHT_MODEL,
            reasoning_policy="HIGHEST_AVAILABLE_REQUIRED" if self.model_quality == "HIGH_REASONING" else "LOWER_MODEL_WARNING",
            model_suitable_for_governance=self.model_quality == "HIGH_REASONING",
            persona_enforced=True,
            expert_roles_applied=AI_QUANT_ROLES,
            model_call_occurred=True,
            model_call_attempted=True,
            provider_response_received=True,
            actual_model_name=str(response.get("model") or request.model_name or ""),
            provider_request_id=str(response.get("id") or "") or None,
            endpoint_family="openai_responses",
            latency_ms=latency_ms,
            http_status_code=response.get("status_code") if isinstance(response.get("status_code"), int) else None,
        )


class OpenAIChatCompatibleAdapter(ProviderAdapter):
    def __init__(
        self,
        *,
        provider_id: str,
        api_key: str,
        base_url: str,
        http_post: HttpPost,
        timeout_seconds: int,
        model_quality: str,
        provider_mode: str,
    ) -> None:
        self.provider_id = provider_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.http_post = http_post
        self.timeout_seconds = timeout_seconds
        self.model_quality = model_quality
        self.provider_mode = provider_mode

    def ask_ai(self, request: AIProviderRequest) -> AIProviderResponse:
        started = time.monotonic()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {
            "model": request.model_name,
            "messages": [
                {"role": "system", "content": request.forced_persona_policy},
                {"role": "user", "content": forced_prompt(request)},
            ],
            "max_tokens": request.max_output_tokens,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        response = self.http_post(f"{self.base_url}/chat/completions", headers, body, self.timeout_seconds)
        latency_ms = int((time.monotonic() - started) * 1000)
        text = extract_text_fields(response).strip()
        actual_model = str(response.get("model") or request.model_name or "") if isinstance(response, dict) else str(request.model_name or "")
        request_id = str(response.get("id") or response.get("request_id") or "") if isinstance(response, dict) else ""
        endpoint_family = "deepseek_chat_completions" if self.provider_id == "deepseek" else "openai_chat_completions"
        if not text:
            return AIProviderResponse(
                answer="Provider returned an empty advisory response. No provider success is being faked.",
                provider_id=self.provider_id,
                provider_mode="PROVIDER_ERROR",
                model_name=request.model_name,
                model_quality="UNKNOWN",
                cost_mode=PROVIDER_ERROR_COST,
                answer_source=PROVIDER_ERROR_SOURCE,
                reasoning_policy="FALLBACK_ONLY_LIMITED",
                model_suitable_for_governance=False,
                persona_enforced=True,
                expert_roles_applied=AI_QUANT_ROLES,
                provider_error_category="EMPTY_MODEL_RESPONSE",
                provider_error_message_safe="Provider returned empty response.",
                model_call_occurred=False,
                model_call_attempted=True,
                provider_response_received=True,
                fallback_reason="EMPTY_MODEL_RESPONSE",
                actual_model_name=actual_model,
                provider_request_id=request_id or None,
                endpoint_family=endpoint_family,
                latency_ms=latency_ms,
                http_status_code=response.get("status_code") if isinstance(response.get("status_code"), int) else None,
            )
        source = LOCAL_MODEL if self.provider_mode == "LOCAL_MODEL" else (
            API_HIGH_REASONING_APPROVED if request.mode == "HIGH_REASONING_API" else API_LIGHT_MODEL
        )
        return AIProviderResponse(
            answer=text,
            provider_id=self.provider_id,
            provider_mode=self.provider_mode,
            model_name=request.model_name,
            model_quality=self.model_quality,
            cost_mode=LOCAL_INFRA_COST if self.provider_mode == "LOCAL_MODEL" else (PAID_API_APPROVED if request.mode == "HIGH_REASONING_API" else LOW_COST_API),
            answer_source=source,
            reasoning_policy="HIGHEST_AVAILABLE_REQUIRED" if self.model_quality == "HIGH_REASONING" else "LOWER_MODEL_WARNING",
            model_suitable_for_governance=self.model_quality == "HIGH_REASONING" and self.provider_mode != "LOCAL_MODEL",
            persona_enforced=True,
            expert_roles_applied=AI_QUANT_ROLES,
            model_call_occurred=True,
            model_call_attempted=True,
            provider_response_received=True,
            actual_model_name=actual_model,
            provider_request_id=request_id or None,
            endpoint_family=endpoint_family,
            latency_ms=latency_ms,
            http_status_code=response.get("status_code") if isinstance(response.get("status_code"), int) else None,
        )


class AnthropicMessagesAdapter(ProviderAdapter):
    def __init__(self, *, api_key: str, base_url: str, http_post: HttpPost, timeout_seconds: int, model_quality: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.http_post = http_post
        self.timeout_seconds = timeout_seconds
        self.model_quality = model_quality

    def ask_ai(self, request: AIProviderRequest) -> AIProviderResponse:
        started = time.monotonic()
        response = self.http_post(
            f"{self.base_url}/v1/messages",
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            {
                "model": request.model_name,
                "system": request.forced_persona_policy,
                "max_tokens": request.max_output_tokens,
                "messages": [{"role": "user", "content": forced_prompt(request)}],
            },
            self.timeout_seconds,
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        text = extract_text_fields({"content": response.get("content") or response}).strip()
        if not text:
            return AIProviderResponse(
                answer="Provider returned an empty advisory response. No provider success is being faked.",
                provider_id="anthropic",
                provider_mode="PROVIDER_ERROR",
                model_name=request.model_name,
                model_quality="UNKNOWN",
                cost_mode=PROVIDER_ERROR_COST,
                answer_source=PROVIDER_ERROR_SOURCE,
                reasoning_policy="FALLBACK_ONLY_LIMITED",
                model_suitable_for_governance=False,
                persona_enforced=True,
                expert_roles_applied=AI_QUANT_ROLES,
                provider_error_category="EMPTY_MODEL_RESPONSE",
                provider_error_message_safe="Provider returned empty response.",
                model_call_occurred=False,
                model_call_attempted=True,
                provider_response_received=True,
                fallback_reason="EMPTY_MODEL_RESPONSE",
                actual_model_name=str(response.get("model") or request.model_name or ""),
                provider_request_id=str(response.get("id") or "") or None,
                endpoint_family="anthropic_messages",
                latency_ms=latency_ms,
                http_status_code=response.get("status_code") if isinstance(response.get("status_code"), int) else None,
            )
        return AIProviderResponse(
            answer=text,
            provider_id="anthropic",
            provider_mode="LIVE_ANTHROPIC",
            model_name=request.model_name,
            model_quality=self.model_quality,
            cost_mode=PAID_API_APPROVED if request.mode == "HIGH_REASONING_API" else LOW_COST_API,
            answer_source=API_HIGH_REASONING_APPROVED if request.mode == "HIGH_REASONING_API" else API_LIGHT_MODEL,
            reasoning_policy="HIGHEST_AVAILABLE_REQUIRED" if self.model_quality == "HIGH_REASONING" else "LOWER_MODEL_WARNING",
            model_suitable_for_governance=self.model_quality == "HIGH_REASONING",
            persona_enforced=True,
            expert_roles_applied=AI_QUANT_ROLES,
            model_call_occurred=True,
            model_call_attempted=True,
            provider_response_received=True,
            actual_model_name=str(response.get("model") or request.model_name or ""),
            provider_request_id=str(response.get("id") or "") or None,
            endpoint_family="anthropic_messages",
            latency_ms=latency_ms,
            http_status_code=response.get("status_code") if isinstance(response.get("status_code"), int) else None,
        )
