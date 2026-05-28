"""Provider gateway for advisory-only AI Chief recommendations."""

from __future__ import annotations

from typing import Any, Protocol

from app.ai_chief_operator.config import AIChiefConfig
from app.ai_chief_operator.models import AIRecommendation, normalize_recommendation


class AdvisoryProvider(Protocol):
    name: str

    def status(self) -> dict[str, Any]:
        ...

    def analyze(self, context: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        ...


class DisabledProvider:
    name = "disabled"

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "provider_state": "AI_DISABLED",
            "can_call_model": False,
            "secrets_values_exposed": False,
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


class MockProvider:
    name = "mock"

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "provider_state": "MOCK_MODE",
            "can_call_model": False,
            "secrets_values_exposed": False,
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
        }

    def analyze(self, context: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        del context, payload
        return {
            "recommendation_type": "OBSERVATION",
            "summary": f"{self.name} provider is config-only in this seam; no external model call was made.",
            "evidence": [self.state],
            "risks": ["Real provider calls require a separate governed configuration path."],
            "uncertainty": ["No external model response exists."],
            "proposed_action": "NO_ACTION",
            "can_execute": False,
            "status": "DRAFT",
            "refusal_reason": self.state,
        }


class AIProviderGateway:
    def __init__(self, config: AIChiefConfig | None = None) -> None:
        self.config = config or AIChiefConfig()
        self.provider = self._provider_for_config(self.config)

    def _provider_for_config(self, config: AIChiefConfig) -> AdvisoryProvider:
        state = config.provider_state()
        if state == "AI_DISABLED":
            return DisabledProvider()
        if state == "MOCK_MODE":
            return MockProvider()
        if config.provider in {"openai", "anthropic"}:
            return PlaceholderProvider(name=config.provider, state=state)
        return PlaceholderProvider(name=config.provider, state=state)

    def status(self) -> dict[str, Any]:
        provider_status = self.provider.status()
        return {
            "gateway_version": "ai-chief-provider-gateway-v1",
            "config": self.config.safe_summary(),
            "provider": provider_status,
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
