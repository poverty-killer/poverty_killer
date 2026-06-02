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
from app.ai_chief_operator.model_registry import (
    base_url_for_provider,
    get_ai_provider_profile,
    registry_summary,
    selected_model_for_provider,
)
from app.ai_chief_operator.model_router import LOCAL_GUIDE, normalize_route_mode


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
    gemini_configured: bool = False
    xai_grok_configured: bool = False
    deepseek_configured: bool = False
    kimi_moonshot_configured: bool = False
    local_openai_compatible_configured: bool = False
    openai_model: str = "gpt-5.5-pro"
    anthropic_model: str = "claude-opus-4.7"
    gemini_model: str = "gemini-2.5-pro"
    xai_grok_model: str = "grok-4"
    deepseek_model: str = "deepseek-reasoner"
    kimi_moonshot_model: str = "kimi-k2-thinking"
    local_openai_compatible_model: str = "local-model"
    openai_high_reasoning_model: str = "gpt-5.5-pro"
    anthropic_high_reasoning_model: str = "claude-opus-4.7"
    default_route_mode: str = LOCAL_GUIDE
    light_provider: str = "openai"
    light_model: str = "gpt-5-mini"
    high_reasoning_provider: str = "openai"
    high_reasoning_model: str = "gpt-5.5-pro"
    local_model_provider: str = "local_openai_compatible"
    supreme_board_packet_default: bool = False
    require_high_reasoning_for_quant: bool = True
    allow_low_reasoning_for_ui_help: bool = False
    show_model_quality: bool = True
    refuse_governance_on_low_reasoning: bool = True
    model_quality_override: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_base_url: str = "https://api.anthropic.com"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    xai_grok_base_url: str = "https://api.x.ai/v1"
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    kimi_moonshot_base_url: str = "https://api.moonshot.ai/v1"
    local_openai_compatible_base_url: str = "http://127.0.0.1:11434/v1"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AIChiefConfig":
        env_map = os.environ if env is None else env
        openai_configured = bool(str(env_map.get("OPENAI_API_KEY") or "").strip())
        anthropic_configured = bool(str(env_map.get("ANTHROPIC_API_KEY") or "").strip())
        gemini_configured = bool(str(env_map.get("GEMINI_API_KEY") or env_map.get("GOOGLE_API_KEY") or "").strip())
        xai_grok_configured = bool(str(env_map.get("XAI_API_KEY") or "").strip())
        deepseek_configured = bool(str(env_map.get("DEEPSEEK_API_KEY") or "").strip())
        kimi_moonshot_configured = bool(str(env_map.get("KIMI_API_KEY") or env_map.get("MOONSHOT_API_KEY") or "").strip())
        local_openai_compatible_configured = bool(
            str(env_map.get("LOCAL_AI_BASE_URL") or "").strip()
            and str(env_map.get("LOCAL_AI_MODEL") or "").strip()
        )
        raw_provider = env_map.get("PK_AI_CHIEF_PROVIDER")
        provider = str(raw_provider or "").strip().lower()
        if not provider:
            if openai_configured:
                provider = "openai"
            elif anthropic_configured:
                provider = "anthropic"
            elif gemini_configured:
                provider = "gemini"
            elif xai_grok_configured:
                provider = "xai_grok"
            elif deepseek_configured:
                provider = "deepseek"
            elif kimi_moonshot_configured:
                provider = "kimi_moonshot"
            elif local_openai_compatible_configured:
                provider = "local_openai_compatible"
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
        gemini_model = str(selected_model_for_provider("gemini", env_map) or "gemini-2.5-pro")
        xai_grok_model = str(selected_model_for_provider("xai_grok", env_map) or "grok-4")
        deepseek_model = str(selected_model_for_provider("deepseek", env_map) or "deepseek-reasoner")
        kimi_moonshot_model = str(selected_model_for_provider("kimi_moonshot", env_map) or "kimi-k2-thinking")
        local_model = str(selected_model_for_provider("local_openai_compatible", env_map) or "local-model")
        default_route_mode = normalize_route_mode(str(env_map.get("PK_AI_DEFAULT_MODE") or env_map.get("AI_DEFAULT_MODE") or LOCAL_GUIDE))
        high_provider_default = provider if provider not in {"disabled", "mock"} else "openai"
        high_provider = str(env_map.get("PK_AI_HIGH_REASONING_PROVIDER") or high_provider_default).strip().lower()
        if get_ai_provider_profile(high_provider) is None:
            high_provider = "openai"
        light_provider = str(env_map.get("PK_AI_LIGHT_PROVIDER") or "openai").strip().lower()
        if get_ai_provider_profile(light_provider) is None:
            light_provider = "openai"
        high_model = str(env_map.get("PK_AI_HIGH_REASONING_MODEL") or selected_model_for_provider(high_provider, env_map) or openai_high).strip()
        light_model = str(env_map.get("PK_AI_LIGHT_MODEL") or selected_model_for_provider(light_provider, env_map) or "gpt-5-mini").strip()
        quality_override = explicit_quality_override(env_map, provider)
        return cls(
            provider="mock" if mock_mode else provider,
            enabled=enabled,
            mock_mode=mock_mode,
            timeout_seconds=timeout,
            openai_configured=openai_configured,
            anthropic_configured=anthropic_configured,
            gemini_configured=gemini_configured,
            xai_grok_configured=xai_grok_configured,
            deepseek_configured=deepseek_configured,
            kimi_moonshot_configured=kimi_moonshot_configured,
            local_openai_compatible_configured=local_openai_compatible_configured,
            openai_model=openai_model,
            anthropic_model=anthropic_model,
            gemini_model=gemini_model,
            xai_grok_model=xai_grok_model,
            deepseek_model=deepseek_model,
            kimi_moonshot_model=kimi_moonshot_model,
            local_openai_compatible_model=local_model,
            openai_high_reasoning_model=openai_high,
            anthropic_high_reasoning_model=anthropic_high,
            default_route_mode=default_route_mode,
            light_provider=light_provider,
            light_model=light_model,
            high_reasoning_provider=high_provider,
            high_reasoning_model=high_model,
            local_model_provider="local_openai_compatible",
            supreme_board_packet_default=str(env_map.get("PK_AI_SUPREME_BOARD_PACKET_DEFAULT") or "").strip().lower() in {"1", "true", "yes", "on"},
            require_high_reasoning_for_quant=flags["require_high_reasoning_for_quant"],
            allow_low_reasoning_for_ui_help=flags["allow_low_reasoning_for_ui_help"],
            show_model_quality=flags["show_model_quality"],
            refuse_governance_on_low_reasoning=flags["refuse_governance_on_low_reasoning"],
            model_quality_override=quality_override,
            openai_base_url=str(env_map.get("PK_AI_CHIEF_OPENAI_BASE_URL") or "https://api.openai.com/v1").strip().rstrip("/") or "https://api.openai.com/v1",
            anthropic_base_url=str(env_map.get("PK_AI_CHIEF_ANTHROPIC_BASE_URL") or "https://api.anthropic.com").strip().rstrip("/") or "https://api.anthropic.com",
            gemini_base_url=str(base_url_for_provider("gemini", env_map) or "https://generativelanguage.googleapis.com/v1beta").strip().rstrip("/"),
            xai_grok_base_url=str(base_url_for_provider("xai_grok", env_map) or "https://api.x.ai/v1").strip().rstrip("/"),
            deepseek_base_url=str(base_url_for_provider("deepseek", env_map) or "https://api.deepseek.com/v1").strip().rstrip("/"),
            kimi_moonshot_base_url=str(base_url_for_provider("kimi_moonshot", env_map) or "https://api.moonshot.ai/v1").strip().rstrip("/"),
            local_openai_compatible_base_url=str(base_url_for_provider("local_openai_compatible", env_map) or "http://127.0.0.1:11434/v1").strip().rstrip("/"),
        )

    def provider_state(self) -> str:
        if not self.enabled or self.provider in {"disabled", "off", "none", ""}:
            return "AI_DISABLED"
        if self.mock_mode or self.provider == "mock":
            return "MOCK_MODE"
        if get_ai_provider_profile(self.provider) is None:
            return "PROVIDER_ERROR"
        if self.provider in {"deterministic_local", "supreme_board_packet"}:
            return "PROVIDER_READY"
        return "PROVIDER_READY" if self.configured_for_provider(self.provider) else "CREDENTIAL_MISSING"

    def configured_for_provider(self, provider_id: str) -> bool:
        mapping = {
            "openai": self.openai_configured,
            "anthropic": self.anthropic_configured,
            "gemini": self.gemini_configured,
            "xai_grok": self.xai_grok_configured,
            "deepseek": self.deepseek_configured,
            "kimi_moonshot": self.kimi_moonshot_configured,
            "local_openai_compatible": self.local_openai_compatible_configured,
            "deterministic_local": True,
            "supreme_board_packet": True,
        }
        return bool(mapping.get(str(provider_id or "").strip().lower(), False))

    def model_for_provider(self, provider_id: str) -> str | None:
        mapping = {
            "openai": self.openai_model,
            "anthropic": self.anthropic_model,
            "gemini": self.gemini_model,
            "xai_grok": self.xai_grok_model,
            "deepseek": self.deepseek_model,
            "kimi_moonshot": self.kimi_moonshot_model,
            "local_openai_compatible": self.local_openai_compatible_model,
            "deterministic_local": "deterministic-local-guide",
            "supreme_board_packet": "chatgpt-pro-manual",
        }
        return mapping.get(str(provider_id or "").strip().lower())

    def base_url_for_provider(self, provider_id: str) -> str | None:
        mapping = {
            "openai": self.openai_base_url,
            "anthropic": self.anthropic_base_url,
            "gemini": self.gemini_base_url,
            "xai_grok": self.xai_grok_base_url,
            "deepseek": self.deepseek_base_url,
            "kimi_moonshot": self.kimi_moonshot_base_url,
            "local_openai_compatible": self.local_openai_compatible_base_url,
        }
        return mapping.get(str(provider_id or "").strip().lower())

    def safe_summary(self) -> dict[str, object]:
        provider = self.provider
        configured = self.configured_for_provider(provider)
        model = self.model_for_provider(provider)
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
            "gemini_configured": self.gemini_configured,
            "xai_grok_configured": self.xai_grok_configured,
            "deepseek_configured": self.deepseek_configured,
            "kimi_moonshot_configured": self.kimi_moonshot_configured,
            "local_openai_compatible_configured": self.local_openai_compatible_configured,
            "openai_model": self.openai_model,
            "anthropic_model": self.anthropic_model,
            "gemini_model": self.gemini_model,
            "xai_grok_model": self.xai_grok_model,
            "deepseek_model": self.deepseek_model,
            "kimi_moonshot_model": self.kimi_moonshot_model,
            "local_openai_compatible_model": self.local_openai_compatible_model,
            "openai_high_reasoning_model": self.openai_high_reasoning_model,
            "anthropic_high_reasoning_model": self.anthropic_high_reasoning_model,
            "active_model": model,
            "default_route_mode": self.default_route_mode,
            "light_provider": self.light_provider,
            "light_model": self.light_model,
            "high_reasoning_provider": self.high_reasoning_provider,
            "high_reasoning_model": self.high_reasoning_model,
            "local_model_provider": self.local_model_provider,
            "supreme_board_packet_default": self.supreme_board_packet_default,
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
            "gemini_base_url_configured": bool(self.gemini_base_url),
            "xai_grok_base_url_configured": bool(self.xai_grok_base_url),
            "deepseek_base_url_configured": bool(self.deepseek_base_url),
            "kimi_moonshot_base_url_configured": bool(self.kimi_moonshot_base_url),
            "local_openai_compatible_base_url_configured": bool(self.local_openai_compatible_base_url),
            "registry": registry_summary({})["registry_version"],
            "secrets_values_exposed": False,
        }
