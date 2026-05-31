"""AI Chief Operator configuration.

The default state is disabled. This module exposes only booleans and provider
names, never raw credentials or secret values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from app.ai_chief_operator.model_policy import (
    config_flags_from_env,
    explicit_quality_override,
    model_quality_report,
)


PROVIDER_STATES = {
    "AI_DISABLED",
    "MOCK_MODE",
    "CREDENTIAL_MISSING",
    "PROVIDER_READY",
    "PROVIDER_ERROR",
    "RATE_LIMITED",
    "TIMEOUT",
}


@dataclass(frozen=True)
class AIChiefConfig:
    provider: str = "disabled"
    enabled: bool = False
    mock_mode: bool = False
    timeout_seconds: int = 45
    max_context_items: int = 50
    openai_configured: bool = False
    anthropic_configured: bool = False
    openai_model: str = "gpt-5.5-pro"
    anthropic_model: str = "claude-opus-4.7"
    openai_high_reasoning_model: str = "gpt-5.5-pro"
    anthropic_high_reasoning_model: str = "claude-opus-4.7"
    require_high_reasoning_for_quant: bool = True
    allow_low_reasoning_for_ui_help: bool = False
    show_model_quality: bool = True
    refuse_governance_on_low_reasoning: bool = True
    model_quality_override: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_base_url: str = "https://api.anthropic.com"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AIChiefConfig":
        env_map = os.environ if env is None else env
        openai_configured = bool(str(env_map.get("OPENAI_API_KEY") or "").strip())
        anthropic_configured = bool(str(env_map.get("ANTHROPIC_API_KEY") or "").strip())
        raw_provider = env_map.get("PK_AI_CHIEF_PROVIDER")
        provider = str(raw_provider or "").strip().lower()
        if not provider:
            if openai_configured:
                provider = "openai"
            elif anthropic_configured:
                provider = "anthropic"
            else:
                provider = "disabled"
        mock_mode = provider == "mock" or str(env_map.get("PK_AI_CHIEF_MOCK_MODE") or "").strip().lower() in {"1", "true", "yes", "on"}
        enabled = provider not in {"", "disabled", "off", "none"} or mock_mode
        try:
            timeout = max(int(env_map.get("PK_AI_CHIEF_TIMEOUT_SECONDS") or 45), 1)
        except ValueError:
            timeout = 45
        flags = config_flags_from_env(env_map)
        openai_high = str(
            env_map.get("OPENAI_HIGH_REASONING_MODEL")
            or env_map.get("PK_AI_CHIEF_OPENAI_HIGH_REASONING_MODEL")
            or "gpt-5.5-pro"
        ).strip() or "gpt-5.5-pro"
        anthropic_high = str(
            env_map.get("ANTHROPIC_HIGH_REASONING_MODEL")
            or env_map.get("PK_AI_CHIEF_ANTHROPIC_HIGH_REASONING_MODEL")
            or "claude-opus-4.7"
        ).strip() or "claude-opus-4.7"
        openai_model = str(
            env_map.get("PK_AI_CHIEF_OPENAI_MODEL")
            or env_map.get("OPENAI_HIGH_REASONING_MODEL")
            or openai_high
        ).strip() or openai_high
        anthropic_model = str(
            env_map.get("PK_AI_CHIEF_ANTHROPIC_MODEL")
            or env_map.get("ANTHROPIC_HIGH_REASONING_MODEL")
            or anthropic_high
        ).strip() or anthropic_high
        quality_override = explicit_quality_override(env_map, provider)
        return cls(
            provider="mock" if mock_mode else provider,
            enabled=enabled,
            mock_mode=mock_mode,
            timeout_seconds=timeout,
            openai_configured=openai_configured,
            anthropic_configured=anthropic_configured,
            openai_model=openai_model,
            anthropic_model=anthropic_model,
            openai_high_reasoning_model=openai_high,
            anthropic_high_reasoning_model=anthropic_high,
            require_high_reasoning_for_quant=flags["require_high_reasoning_for_quant"],
            allow_low_reasoning_for_ui_help=flags["allow_low_reasoning_for_ui_help"],
            show_model_quality=flags["show_model_quality"],
            refuse_governance_on_low_reasoning=flags["refuse_governance_on_low_reasoning"],
            model_quality_override=quality_override,
            openai_base_url=str(env_map.get("PK_AI_CHIEF_OPENAI_BASE_URL") or "https://api.openai.com/v1").strip().rstrip("/") or "https://api.openai.com/v1",
            anthropic_base_url=str(env_map.get("PK_AI_CHIEF_ANTHROPIC_BASE_URL") or "https://api.anthropic.com").strip().rstrip("/") or "https://api.anthropic.com",
        )

    def provider_state(self) -> str:
        if not self.enabled or self.provider in {"disabled", "off", "none", ""}:
            return "AI_DISABLED"
        if self.mock_mode or self.provider == "mock":
            return "MOCK_MODE"
        if self.provider == "openai":
            return "PROVIDER_READY" if self.openai_configured else "CREDENTIAL_MISSING"
        if self.provider == "anthropic":
            return "PROVIDER_READY" if self.anthropic_configured else "CREDENTIAL_MISSING"
        return "PROVIDER_ERROR"

    def safe_summary(self) -> dict[str, object]:
        provider = self.provider
        configured = (provider == "openai" and self.openai_configured) or (provider == "anthropic" and self.anthropic_configured)
        model = self.openai_model if provider == "openai" else (self.anthropic_model if provider == "anthropic" else None)
        report = model_quality_report(
            provider=provider,
            model_name=model,
            configured=configured,
            override=self.model_quality_override,
            fallback=self.mock_mode or provider == "mock",
        )
        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "mock_mode": self.mock_mode,
            "provider_state": self.provider_state(),
            "timeout_seconds": self.timeout_seconds,
            "max_context_items": self.max_context_items,
            "openai_configured": self.openai_configured,
            "anthropic_configured": self.anthropic_configured,
            "openai_model": self.openai_model,
            "anthropic_model": self.anthropic_model,
            "openai_high_reasoning_model": self.openai_high_reasoning_model,
            "anthropic_high_reasoning_model": self.anthropic_high_reasoning_model,
            "active_model": model,
            "provider_mode": report.provider_mode,
            "model_name": report.model_name,
            "model_quality": report.model_quality,
            "reasoning_policy": report.reasoning_policy,
            "model_suitable_for_governance": report.model_suitable_for_governance,
            "model_quality_warning": report.warning,
            "require_high_reasoning_for_quant": self.require_high_reasoning_for_quant,
            "allow_low_reasoning_for_ui_help": self.allow_low_reasoning_for_ui_help,
            "show_model_quality": self.show_model_quality,
            "refuse_governance_on_low_reasoning": self.refuse_governance_on_low_reasoning,
            "openai_base_url_configured": bool(self.openai_base_url),
            "anthropic_base_url_configured": bool(self.anthropic_base_url),
            "secrets_values_exposed": False,
        }
