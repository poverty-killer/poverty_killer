"""Provider gateway for advisory-only AI Chief recommendations."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.ai_chief_operator.config import AIChiefConfig
from app.ai_chief_operator.context_builder import redact_secrets
from app.ai_chief_operator.models import AIRecommendation, normalize_recommendation
from app.ai_chief_operator.model_policy import (
    FALLBACK_ONLY_LIMITED,
    HIGHEST_AVAILABLE_REQUIRED,
    HIGH_REASONING,
    LOWER_MODEL_WARNING,
    model_quality_report,
    prompt_allows_model_call,
)
from app.ai_chief_operator.quant_persona import AI_SYSTEM_POLICY, classify_quant_prompt


HttpPost = Callable[[str, dict[str, str], dict[str, Any], int], dict[str, Any]]
LOCAL_PATH_RE = re.compile(
    r"([A-Za-z]:\\[^\s\"']+|/mnt/[A-Za-z]/[^\s\"']+|/home/[^\s\"']+|state[/\\][^\s\"']+|logs[/\\][^\s\"']+)",
    re.IGNORECASE,
)
PATH_KEY_PARTS = ("path", "stdout", "stderr", "log_file", "log_path", "report_path")


def _fallback_model_fields(provider: str = "disabled", *, state: str = "AI_DISABLED") -> dict[str, Any]:
    del state
    report = model_quality_report(provider=provider, model_name=None, configured=False, fallback=True)
    return {
        "provider_mode": report.provider_mode,
        "model_name": report.model_name,
        "model_quality": report.model_quality,
        "reasoning_policy": report.reasoning_policy,
        "model_suitable_for_governance": report.model_suitable_for_governance,
        "model_quality_warning": report.warning,
    }


class AdvisoryProvider(Protocol):
    name: str

    def status(self) -> dict[str, Any]:
        ...

    def analyze(self, context: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        ...

    def ask(
        self,
        question: str,
        context: dict[str, Any],
        page_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...


class DisabledProvider:
    name = "disabled"

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "provider_state": "AI_DISABLED",
            "can_call_model": False,
            "secrets_values_exposed": False,
            **_fallback_model_fields(self.name),
        }

    def analyze(self, context: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        del context, payload
        return {
            "recommendation_type": "OBSERVATION",
            "summary": "AI Chief is disabled. No model analysis was run.",
            "evidence": ["AI_DISABLED"],
            "risks": ["No AI review available until explicitly configured."],
            "uncertainty": ["Provider disabled by governance-safe default."],
            "proposed_action": "NO_ACTION",
            "can_execute": False,
            "status": "DRAFT",
            "refusal_reason": "AI_DISABLED",
        }

    def ask(
        self,
        question: str,
        context: dict[str, Any],
        page_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del question, context, page_context
        return {
            "status": "ANSWERED_FALLBACK",
            "provider": self.name,
            "provider_state": "AI_DISABLED",
            "response_source": "DETERMINISTIC_FALLBACK_NO_MODEL_CALL",
            "response": "AI Chief is disabled. No external model call was made.",
            "model_call_occurred": False,
            **_fallback_model_fields(self.name),
        }


class MockProvider:
    name = "mock"

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "provider_state": "MOCK_MODE",
            "can_call_model": False,
            "secrets_values_exposed": False,
            **_fallback_model_fields(self.name, state="MOCK_MODE"),
        }

    def analyze(self, context: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        del payload
        alert_count = len(context.get("alerts") or [])
        action_count = len((context.get("action_center") or {}).get("items") or [])
        return {
            "recommendation_type": "SYSTEM_HEALTH_WARNING" if alert_count else "OBSERVATION",
            "summary": f"Mock AI review found {alert_count} alerts and {action_count} operator action-center items.",
            "evidence": [
                f"live_status={context.get('live_status')}",
                f"real_money_blocked={context.get('real_money_blocked')}",
                f"alert_count={alert_count}",
            ],
            "risks": ["Mock provider is not a real model and has no trade authority."],
            "uncertainty": ["Runtime telemetry may be incomplete."],
            "proposed_action": "REVIEW_OPERATOR_ACTION_CENTER",
            "can_execute": False,
            "status": "PENDING_REVIEW",
        }

    def ask(
        self,
        question: str,
        context: dict[str, Any],
        page_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del page_context
        alert_count = len(context.get("alerts") or [])
        action_count = len((context.get("action_center") or {}).get("items") or [])
        return {
            "status": "ANSWERED_FALLBACK",
            "provider": self.name,
            "provider_state": "MOCK_MODE",
            "response_source": "MOCK_MODE_DETERMINISTIC",
            "response": (
                "DETERMINISTIC FALLBACK - not a full AI quant reasoning response.\n"
                "Mock AI advisor response.\n"
                f"Question: {question or 'No question supplied.'}\n"
                f"Loaded alerts: {alert_count}; operator action-center items: {action_count}.\n"
                "No model call, broker call, live enablement, real-money enablement, or threshold mutation occurred."
            ),
            "model_call_occurred": False,
            **_fallback_model_fields(self.name, state="MOCK_MODE"),
        }


class PlaceholderProvider:
    def __init__(self, *, name: str, state: str) -> None:
        self.name = name
        self.state = state

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "provider_state": self.state,
            "can_call_model": False,
            "secrets_values_exposed": False,
            **_fallback_model_fields(self.name, state=self.state),
        }

    def analyze(self, context: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        del context, payload
        return {
            "recommendation_type": "OBSERVATION",
            "summary": f"{self.name} provider is not ready; no external model call was made.",
            "evidence": [self.state],
            "risks": ["Real provider calls require a separate governed configuration path."],
            "uncertainty": ["No external model response exists."],
            "proposed_action": "NO_ACTION",
            "can_execute": False,
            "status": "DRAFT",
            "refusal_reason": self.state,
        }

    def ask(
        self,
        question: str,
        context: dict[str, Any],
        page_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del context, page_context
        return {
            "status": "ANSWERED_FALLBACK",
            "provider": self.name,
            "provider_state": self.state,
            "response_source": "DETERMINISTIC_FALLBACK_NO_MODEL_CALL",
            "response": (
                "DETERMINISTIC FALLBACK - not a full AI quant reasoning response.\n"
                f"{self.name} provider is not ready for external model calls.\n"
                f"Provider state: {self.state}.\n"
                f"Question: {question or 'No question supplied.'}"
            ),
            "model_call_occurred": False,
            **_fallback_model_fields(self.name, state=self.state),
        }


class ExternalAdvisoryProvider:
    provider_state = "PROVIDER_READY"

    def __init__(self, *, config: AIChiefConfig, api_key: str, http_post: HttpPost) -> None:
        self.config = config
        self.api_key = api_key
        self.http_post = http_post

    def status(self) -> dict[str, Any]:
        report = self.quality_report()
        return {
            "provider": self.name,
            "provider_state": self.provider_state,
            "can_call_model": bool(self.api_key),
            "model": self.model,
            **report.to_dict(),
            "secrets_values_exposed": False,
        }

    def quality_report(self, *, error: bool = False, fallback: bool = False) -> Any:
        return model_quality_report(
            provider=self.name,
            model_name=self.model,
            configured=bool(self.api_key),
            override=self.config.model_quality_override,
            fallback=fallback,
            error=error,
        )

    def analyze(self, context: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        question = str((payload or {}).get("prompt") or (payload or {}).get("question") or "Review current operator state.")
        result = self.ask(question, context, payload)
        return {
            "recommendation_type": "OBSERVATION",
            "summary": result.get("response") or "Provider returned no advisory text.",
            "evidence": [result.get("response_source") or self.name, f"model={self.model}"],
            "risks": ["AI advisory has no execution authority and must be verified against broker and market truth."],
            "uncertainty": ["Model response may be incomplete or wrong; operator proof still controls."],
            "proposed_action": "REVIEW_OPERATOR_EVIDENCE",
            "can_execute": False,
            "status": "PENDING_REVIEW",
        }

    def ask(
        self,
        question: str,
        context: dict[str, Any],
        page_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            report = self.quality_report(fallback=True)
            return {
                "status": "ANSWERED_FALLBACK",
                "provider": self.name,
                "provider_state": "CREDENTIAL_MISSING",
                "response_source": "DETERMINISTIC_FALLBACK_NO_MODEL_CALL",
                "response": (
                    "DETERMINISTIC FALLBACK - not a full AI quant reasoning response.\n"
                    f"{self.name} API key is missing. No external model call was made."
                ),
                "model_call_occurred": False,
                **report.to_dict(),
            }
        page_id = str((page_context or {}).get("page_id") or "")
        classification = classify_quant_prompt(question, page_id=page_id)
        mode = str(classification.get("mode") or "QUANT_ADVISOR")
        report = self.quality_report()
        allowed_call = prompt_allows_model_call(
            mode=mode,
            report=report,
            require_high_reasoning_for_quant=self.config.require_high_reasoning_for_quant,
            allow_low_reasoning_for_ui_help=self.config.allow_low_reasoning_for_ui_help,
        )
        if not allowed_call:
            warning = report.warning or "High-reasoning model not configured. Quant/governance answers are limited."
            return {
                "status": "ANSWERED_FALLBACK",
                "provider": self.name,
                "provider_state": self.provider_state,
                "response_source": "DETERMINISTIC_FALLBACK_MODEL_POLICY",
                "response": (
                    f"{warning}\n"
                    "I can give a limited operational answer, but final quant/risk/governance judgment requires the high-reasoning model.\n"
                    f"Configured model: {self.model or 'none'}.\n"
                    f"Prompt mode: {mode}. No lower-reasoning model call was made."
                ),
                "model_call_occurred": False,
                **report.to_dict(),
                "provider_mode": "DETERMINISTIC_FALLBACK",
            }
        prompt = self._build_prompt(question, context, page_context)
        response_json = self._call_model(prompt)
        text = self._extract_text(response_json).strip()
        if not text:
            error_report = self.quality_report(error=True)
            return {
                "status": "PROVIDER_ERROR",
                "provider": self.name,
                "provider_state": "PROVIDER_ERROR",
                "response_source": "PROVIDER_ERROR_EMPTY_MODEL_RESPONSE",
                "model": self.model,
                "response": (
                    "Configured high-reasoning AI provider returned no usable advisory text, "
                    "so no expert model answer is being faked."
                ),
                "model_call_occurred": True,
                **error_report.to_dict(),
            }
        return {
            "status": "ANSWERED_MODEL",
            "provider": self.name,
            "provider_state": self.provider_state,
            "response_source": self.response_source,
            "model": self.model,
            "response": text,
            "model_call_occurred": True,
            **report.to_dict(),
        }

    def _build_prompt(
        self,
        question: str,
        context: dict[str, Any],
        page_context: dict[str, Any] | None,
    ) -> str:
        safe_context = self._redact_paths(redact_secrets(context))
        safe_page = self._redact_paths(redact_secrets(page_context or {}))
        compact = {
            "question": question or "No question supplied.",
            "page_context": safe_page,
            "operator_context": safe_context,
            "hard_boundaries": {
                "advisory_only": True,
                "can_execute": False,
                "broker_call_allowed": False,
                "live_enablement_allowed": False,
                "real_money_allowed": False,
                "manual_trading_allowed": False,
                "threshold_mutation_allowed": False,
                "secret_handling": "Do not request, reveal, infer, or restate secrets.",
            },
        }
        serialized = json.dumps(compact, sort_keys=True, default=str)
        max_chars = max(int(self.config.max_context_items), 1) * 1200
        if len(serialized) > max_chars:
            serialized = serialized[:max_chars] + "\n...TRUNCATED_SAFE_CONTEXT..."
        return (
            f"{AI_SYSTEM_POLICY}\n"
            "Answer in plain English for a regular operator. "
            "Use only the provided redacted operator context. Do not claim broker truth when unavailable. "
            "Do not include local filesystem paths or log paths in the answer. "
            "Do not give instructions to place manual trades. Do not enable live or real-money trading. "
            "You cannot call brokers, execute orders, cancel orders, flatten, liquidate, or change thresholds. "
            "Focus on current holdings, blockers, PAPER readiness, P&L/exposure truth, execution quality, and proof needed. "
            "For quant questions include hypothesis, evidence, counterargument, risk, missing data, proof/disproof, and safe next test. "
            "For portfolio questions separate exposure, concentration, P&L, fees, TCA, slippage, stale/conflicted data, and broker-confirmed versus inferred truth. "
            "For operator questions name the page/control, why blocked, exact next step, what not to do, and whether a Codex packet is needed.\n\n"
            f"{serialized}"
        )

    def _redact_paths(self, value: Any, *, key: str = "") -> Any:
        key_lower = key.lower()
        if isinstance(value, dict):
            return {str(k): self._redact_paths(v, key=str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [self._redact_paths(item, key=key) for item in value[:100]]
        if isinstance(value, tuple):
            return tuple(self._redact_paths(item, key=key) for item in value[:100])
        if isinstance(value, str):
            if any(part in key_lower for part in PATH_KEY_PARTS):
                return "REDACTED_LOCAL_PATH"
            return LOCAL_PATH_RE.sub("REDACTED_LOCAL_PATH", value)
        return value

    def _call_model(self, prompt: str) -> dict[str, Any]:
        raise NotImplementedError

    def _extract_text_fields(self, value: Any) -> str:
        parts: list[str] = []

        def visit(node: Any) -> None:
            if isinstance(node, dict):
                for key in ("output_text", "text", "refusal"):
                    candidate = node.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        parts.append(candidate)
                    elif isinstance(candidate, dict) and isinstance(candidate.get("value"), str):
                        parts.append(candidate["value"])
                for key in ("output", "content", "message", "messages"):
                    if key in node:
                        visit(node[key])
            elif isinstance(node, list):
                for item in node:
                    visit(item)

        visit(value)
        return "\n".join(dict.fromkeys(part.strip() for part in parts if part.strip()))

    def _extract_text(self, response_json: dict[str, Any]) -> str:
        raise NotImplementedError


class OpenAIProvider(ExternalAdvisoryProvider):
    name = "openai"
    response_source = "OPENAI_RESPONSES_API"

    @property
    def model(self) -> str:
        return self.config.openai_model

    def _call_model(self, prompt: str) -> dict[str, Any]:
        return self.http_post(
            f"{self.config.openai_base_url}/responses",
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            {
                "model": self.model,
                "input": prompt,
                "max_output_tokens": 1800,
            },
            self.config.timeout_seconds,
        )

    def _extract_text(self, response_json: dict[str, Any]) -> str:
        return self._extract_text_fields(response_json)


class AnthropicProvider(ExternalAdvisoryProvider):
    name = "anthropic"
    response_source = "ANTHROPIC_MESSAGES_API"

    @property
    def model(self) -> str:
        return self.config.anthropic_model

    def _call_model(self, prompt: str) -> dict[str, Any]:
        return self.http_post(
            f"{self.config.anthropic_base_url}/v1/messages",
            {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            {
                "model": self.model,
                "max_tokens": 700,
                "messages": [{"role": "user", "content": prompt}],
            },
            self.config.timeout_seconds,
        )

    def _extract_text(self, response_json: dict[str, Any]) -> str:
        return self._extract_text_fields({"content": response_json.get("content") or []})


class AIProviderGateway:
    def __init__(
        self,
        config: AIChiefConfig | None = None,
        *,
        credential_env: Mapping[str, str] | None = None,
        http_post: HttpPost | None = None,
    ) -> None:
        self.config = config or AIChiefConfig()
        self.credential_env = credential_env or {}
        self.http_post = http_post or self._http_post
        self.provider = self._provider_for_config(self.config)

    def _provider_for_config(self, config: AIChiefConfig) -> AdvisoryProvider:
        state = config.provider_state()
        if state == "AI_DISABLED":
            return DisabledProvider()
        if state == "MOCK_MODE":
            return MockProvider()
        if config.provider == "openai" and state == "PROVIDER_READY":
            return OpenAIProvider(
                config=config,
                api_key=str(self.credential_env.get("OPENAI_API_KEY") or ""),
                http_post=self.http_post,
            )
        if config.provider == "anthropic" and state == "PROVIDER_READY":
            return AnthropicProvider(
                config=config,
                api_key=str(self.credential_env.get("ANTHROPIC_API_KEY") or ""),
                http_post=self.http_post,
            )
        if config.provider in {"openai", "anthropic"}:
            return PlaceholderProvider(name=config.provider, state=state)
        return PlaceholderProvider(name=config.provider, state=state)

    def _http_post(self, url: str, headers: dict[str, str], body: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        request = Request(url, data=data, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            raise RuntimeError(f"provider_http_{exc.code}: {detail[:240]}") from exc
        except URLError as exc:
            raise RuntimeError(f"provider_connection_error: {exc.reason}") from exc
        return json.loads(payload or "{}")

    def status(self) -> dict[str, Any]:
        provider_status = self.provider.status()
        config_summary = self.config.safe_summary()
        return {
            "gateway_version": "ai-chief-provider-gateway-v1",
            "config": config_summary,
            "provider": provider_status,
            "model_policy": {
                "provider_mode": provider_status.get("provider_mode") or config_summary.get("provider_mode"),
                "model_name": provider_status.get("model_name") or config_summary.get("model_name"),
                "model_quality": provider_status.get("model_quality") or config_summary.get("model_quality"),
                "reasoning_policy": provider_status.get("reasoning_policy") or config_summary.get("reasoning_policy"),
                "model_suitable_for_governance": provider_status.get("model_suitable_for_governance") is True,
                "warning": provider_status.get("model_quality_warning") or config_summary.get("model_quality_warning"),
                "require_high_reasoning_for_quant": self.config.require_high_reasoning_for_quant,
                "allow_low_reasoning_for_ui_help": self.config.allow_low_reasoning_for_ui_help,
                "refuse_governance_on_low_reasoning": self.config.refuse_governance_on_low_reasoning,
            },
            "advisory_only": True,
            "can_execute": False,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
        }

    def analyze(self, context: dict[str, Any], payload: dict[str, Any] | None = None) -> AIRecommendation:
        raw = self.provider.analyze(context, payload)
        return normalize_recommendation(raw, provider=self.provider.name)

    def ask(
        self,
        question: str,
        context: dict[str, Any],
        page_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            result = self.provider.ask(question, context, page_context)
        except Exception as exc:
            raw_detail = str(exc) or type(exc).__name__
            safe_detail = str(redact_secrets({"error": raw_detail}).get("error") or raw_detail)
            safe_detail = LOCAL_PATH_RE.sub("REDACTED_LOCAL_PATH", safe_detail)[:320]
            report = model_quality_report(
                provider=self.provider.name,
                model_name=getattr(self.provider, "model", None),
                configured=True,
                error=True,
            )
            result = {
                "status": "PROVIDER_ERROR",
                "provider": self.provider.name,
                "provider_state": "PROVIDER_ERROR",
                "response_source": "PROVIDER_ERROR_NO_MODEL_ANSWER",
                "response": (
                    "Configured high-reasoning AI provider could not return a response, so no model answer is being faked.\n"
                    f"Provider error: {type(exc).__name__}: {safe_detail}.\n"
                    "Use Provider Setup to verify the key/model and try again. If the configured high-reasoning model is unavailable in the account, set OPENAI_HIGH_REASONING_MODEL or ANTHROPIC_HIGH_REASONING_MODEL to an available high-reasoning model."
                ),
                "model_call_occurred": False,
                **report.to_dict(),
            }
        result.update(
            {
                "advisory_only": True,
                "can_execute": False,
                "broker_call_occurred": False,
                "trading_mutation_occurred": False,
                "live_enabled": False,
                "real_money_enabled": False,
                "raw_logs_included": False,
                "secrets_values_exposed": False,
            }
        )
        return result
