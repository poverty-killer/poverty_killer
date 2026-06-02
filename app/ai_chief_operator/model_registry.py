"""Provider-agnostic AI model registry for operator advisory routing.

The registry is metadata only. It does not call provider APIs and never stores
secret values. Provider availability is derived by the gateway from environment
or the local credential vault.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping


AI_PROVIDER_REGISTRY_VERSION = "ai-provider-model-registry-v1"

API_OPENAI_RESPONSES = "openai_responses"
API_OPENAI_CHAT_COMPATIBLE = "openai_chat_compatible"
API_ANTHROPIC_MESSAGES = "anthropic_messages"
API_GEMINI_GENERATE_CONTENT = "gemini_generate_content"
API_CUSTOM_ADAPTER = "custom_adapter"
API_DETERMINISTIC = "deterministic"
API_PACKET_BRIDGE = "packet_bridge"

STATUS_READY = "READY"
STATUS_CONFIGURED = "CONFIGURED"
STATUS_MISSING_CREDENTIALS = "MISSING_CREDENTIALS"
STATUS_DISABLED = "DISABLED"
STATUS_VALIDATION_FAILED = "VALIDATION_FAILED"
STATUS_PROVIDER_ERROR = "PROVIDER_ERROR"
STATUS_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

FREE_LOCAL = "FREE_LOCAL"
CHATGPT_PRO_MANUAL = "CHATGPT_PRO_MANUAL"
LOW_COST_API = "LOW_COST_API"
PAID_API_APPROVED = "PAID_API_APPROVED"
LOCAL_INFRA_COST = "LOCAL_INFRA_COST"
PROVIDER_ERROR_COST = "PROVIDER_ERROR"

LOCAL_DETERMINISTIC = "LOCAL_DETERMINISTIC"
API_LIGHT_MODEL = "API_LIGHT_MODEL"
API_HIGH_REASONING_APPROVED = "API_HIGH_REASONING_APPROVED"
LOCAL_MODEL = "LOCAL_MODEL"
SUPREME_BOARD_PACKET = "SUPREME_BOARD_PACKET"
PROVIDER_ERROR_SOURCE = "PROVIDER_ERROR"
NOT_CONFIGURED_SOURCE = "NOT_CONFIGURED"


@dataclass(frozen=True)
class AIProviderProfile:
    provider_id: str
    display_name: str
    provider_family: str
    credential_env_vars: tuple[str, ...] = ()
    credential_vault_fields: tuple[str, ...] = ()
    base_url_config_key: str | None = None
    api_format: str = API_CUSTOM_ADAPTER
    supports_streaming: bool | str = "unknown"
    supports_tools: bool | str = "unknown"
    supports_vision: bool | str = "unknown"
    supports_long_context: bool | str = "unknown"
    supports_json_schema: bool | str = "unknown"
    default_model: str | None = None
    allowed_models: tuple[str, ...] = ()
    model_quality_map: dict[str, str] = field(default_factory=dict)
    cost_tier_map: dict[str, str] = field(default_factory=dict)
    reasoning_capability_map: dict[str, str] = field(default_factory=dict)
    safety_notes: tuple[str, ...] = ()
    implemented: bool = False
    enabled_by_default: bool = False
    status: str = STATUS_NOT_IMPLEMENTED
    last_validation_status: str = "NOT_RUN"
    last_error_category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "provider_family": self.provider_family,
            "credential_env_vars": list(self.credential_env_vars),
            "credential_vault_fields": list(self.credential_vault_fields),
            "base_url_config_key": self.base_url_config_key,
            "api_format": self.api_format,
            "supports_streaming": self.supports_streaming,
            "supports_tools": self.supports_tools,
            "supports_vision": self.supports_vision,
            "supports_long_context": self.supports_long_context,
            "supports_json_schema": self.supports_json_schema,
            "default_model": self.default_model,
            "allowed_models": list(self.allowed_models),
            "model_quality_map": dict(self.model_quality_map),
            "cost_tier_map": dict(self.cost_tier_map),
            "reasoning_capability_map": dict(self.reasoning_capability_map),
            "safety_notes": list(self.safety_notes),
            "implemented": self.implemented,
            "enabled_by_default": self.enabled_by_default,
            "status": self.status,
            "last_validation_status": self.last_validation_status,
            "last_error_category": self.last_error_category,
        }


AI_PROVIDER_PROFILES: tuple[AIProviderProfile, ...] = (
    AIProviderProfile(
        provider_id="openai",
        display_name="OpenAI / GPT",
        provider_family="openai",
        credential_env_vars=("OPENAI_API_KEY",),
        credential_vault_fields=("OPENAI_API_KEY",),
        base_url_config_key="OPENAI_BASE_URL",
        api_format=API_OPENAI_RESPONSES,
        supports_streaming=True,
        supports_tools=True,
        supports_vision=True,
        supports_long_context=True,
        supports_json_schema=True,
        default_model="gpt-5.5-pro",
        allowed_models=("gpt-5.5-pro", "gpt-5.5-thinking", "gpt-5-mini", "gpt-4.1"),
        model_quality_map={"gpt-5.5-pro": "HIGH_REASONING", "gpt-5.5-thinking": "HIGH_REASONING", "gpt-5-mini": "LOW_REASONING"},
        cost_tier_map={"gpt-5-mini": LOW_COST_API, "gpt-5.5-pro": PAID_API_APPROVED, "gpt-5.5-thinking": PAID_API_APPROVED},
        reasoning_capability_map={"gpt-5.5-pro": "highest", "gpt-5.5-thinking": "highest", "gpt-5-mini": "low"},
        safety_notes=("API billing is separate from ChatGPT Pro.", "No automatic high-reasoning calls."),
        implemented=True,
        status=STATUS_CONFIGURED,
    ),
    AIProviderProfile(
        provider_id="anthropic",
        display_name="Claude / Anthropic",
        provider_family="anthropic",
        credential_env_vars=("ANTHROPIC_API_KEY",),
        credential_vault_fields=("ANTHROPIC_API_KEY",),
        base_url_config_key="ANTHROPIC_BASE_URL",
        api_format=API_ANTHROPIC_MESSAGES,
        supports_streaming=True,
        supports_tools=True,
        supports_vision=True,
        supports_long_context=True,
        supports_json_schema="unknown",
        default_model="claude-opus-4.7",
        allowed_models=("claude-opus-4.7", "claude-opus-4.5", "claude-sonnet-4.5", "claude-haiku-4"),
        model_quality_map={"claude-opus-4.7": "HIGH_REASONING", "claude-opus-4.5": "HIGH_REASONING", "claude-haiku-4": "LOW_REASONING"},
        cost_tier_map={"claude-haiku-4": LOW_COST_API, "claude-opus-4.7": PAID_API_APPROVED},
        reasoning_capability_map={"claude-opus-4.7": "highest", "claude-sonnet-4.5": "standard", "claude-haiku-4": "low"},
        safety_notes=("High-reasoning calls require explicit approval.",),
        implemented=True,
        status=STATUS_CONFIGURED,
    ),
    AIProviderProfile(
        provider_id="gemini",
        display_name="Gemini / Google",
        provider_family="google",
        credential_env_vars=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        credential_vault_fields=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        base_url_config_key="GEMINI_BASE_URL",
        api_format=API_GEMINI_GENERATE_CONTENT,
        supports_streaming=True,
        supports_tools=True,
        supports_vision=True,
        supports_long_context=True,
        supports_json_schema=True,
        default_model="gemini-2.5-pro",
        allowed_models=("gemini-2.5-pro", "gemini-2.5-flash"),
        model_quality_map={"gemini-2.5-pro": "HIGH_REASONING", "gemini-2.5-flash": "STANDARD"},
        cost_tier_map={"gemini-2.5-pro": PAID_API_APPROVED, "gemini-2.5-flash": LOW_COST_API},
        reasoning_capability_map={"gemini-2.5-pro": "high", "gemini-2.5-flash": "standard"},
        safety_notes=("Adapter scaffolded; no fake provider success.",),
        implemented=False,
        status=STATUS_NOT_IMPLEMENTED,
    ),
    AIProviderProfile(
        provider_id="xai_grok",
        display_name="Grok / xAI",
        provider_family="xai",
        credential_env_vars=("XAI_API_KEY",),
        credential_vault_fields=("XAI_API_KEY",),
        base_url_config_key="XAI_BASE_URL",
        api_format=API_OPENAI_CHAT_COMPATIBLE,
        supports_streaming=True,
        supports_tools="unknown",
        supports_vision="unknown",
        supports_long_context=True,
        supports_json_schema="unknown",
        default_model="grok-4",
        allowed_models=("grok-4", "grok-3-mini"),
        model_quality_map={"grok-4": "HIGH_REASONING", "grok-3-mini": "LOW_REASONING"},
        cost_tier_map={"grok-4": PAID_API_APPROVED, "grok-3-mini": LOW_COST_API},
        reasoning_capability_map={"grok-4": "high", "grok-3-mini": "low"},
        safety_notes=("OpenAI-compatible scaffold; no silent downgrade.",),
        implemented=True,
        status=STATUS_CONFIGURED,
    ),
    AIProviderProfile(
        provider_id="deepseek",
        display_name="DeepSeek",
        provider_family="deepseek",
        credential_env_vars=("DEEPSEEK_API_KEY",),
        credential_vault_fields=("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL"),
        base_url_config_key="DEEPSEEK_BASE_URL",
        api_format=API_OPENAI_CHAT_COMPATIBLE,
        supports_streaming=True,
        supports_tools="unknown",
        supports_vision=False,
        supports_long_context=True,
        supports_json_schema="unknown",
        default_model="deepseek-reasoner",
        allowed_models=("deepseek-reasoner", "deepseek-chat"),
        model_quality_map={"deepseek-reasoner": "HIGH_REASONING", "deepseek-chat": "STANDARD"},
        cost_tier_map={"deepseek-reasoner": PAID_API_APPROVED, "deepseek-chat": LOW_COST_API},
        reasoning_capability_map={"deepseek-reasoner": "high", "deepseek-chat": "standard"},
        safety_notes=("Uses OpenAI-compatible chat endpoint when configured.",),
        implemented=True,
        status=STATUS_CONFIGURED,
    ),
    AIProviderProfile(
        provider_id="kimi_moonshot",
        display_name="Kimi / Moonshot",
        provider_family="moonshot",
        credential_env_vars=("KIMI_API_KEY", "MOONSHOT_API_KEY"),
        credential_vault_fields=("KIMI_API_KEY", "MOONSHOT_API_KEY", "KIMI_BASE_URL", "MOONSHOT_BASE_URL"),
        base_url_config_key="KIMI_BASE_URL",
        api_format=API_OPENAI_CHAT_COMPATIBLE,
        supports_streaming=True,
        supports_tools="unknown",
        supports_vision="unknown",
        supports_long_context=True,
        supports_json_schema="unknown",
        default_model="kimi-k2-thinking",
        allowed_models=("kimi-k2-thinking", "moonshot-v1-128k"),
        model_quality_map={"kimi-k2-thinking": "HIGH_REASONING", "moonshot-v1-128k": "STANDARD"},
        cost_tier_map={"kimi-k2-thinking": PAID_API_APPROVED, "moonshot-v1-128k": LOW_COST_API},
        reasoning_capability_map={"kimi-k2-thinking": "high", "moonshot-v1-128k": "standard"},
        safety_notes=("Uses OpenAI-compatible chat endpoint when configured.",),
        implemented=True,
        status=STATUS_CONFIGURED,
    ),
    AIProviderProfile(
        provider_id="local_openai_compatible",
        display_name="Local OpenAI-compatible",
        provider_family="local",
        credential_env_vars=("LOCAL_AI_BASE_URL", "LOCAL_AI_MODEL"),
        credential_vault_fields=("LOCAL_AI_BASE_URL", "LOCAL_AI_MODEL", "LOCAL_AI_API_KEY"),
        base_url_config_key="LOCAL_AI_BASE_URL",
        api_format=API_OPENAI_CHAT_COMPATIBLE,
        supports_streaming="unknown",
        supports_tools=False,
        supports_vision="unknown",
        supports_long_context="unknown",
        supports_json_schema="unknown",
        default_model="local-model",
        allowed_models=("local-model",),
        model_quality_map={"local-model": "LOCAL_UNEVALUATED"},
        cost_tier_map={"local-model": LOCAL_INFRA_COST},
        reasoning_capability_map={"local-model": "local_unevaluated"},
        safety_notes=("Requires Shan-owned local server/GPU.", "Not governance suitable unless explicitly evaluated."),
        implemented=True,
        status=STATUS_CONFIGURED,
    ),
    AIProviderProfile(
        provider_id="deterministic_local",
        display_name="Deterministic Local",
        provider_family="local",
        api_format=API_DETERMINISTIC,
        supports_streaming=False,
        supports_tools=False,
        supports_vision=False,
        supports_long_context=False,
        supports_json_schema=False,
        default_model="deterministic-local-guide",
        allowed_models=("deterministic-local-guide",),
        model_quality_map={"deterministic-local-guide": "FALLBACK_ONLY"},
        cost_tier_map={"deterministic-local-guide": FREE_LOCAL},
        reasoning_capability_map={"deterministic-local-guide": "limited_operator_guidance"},
        safety_notes=("Free/local.", "Not a full AI quant reasoning response."),
        implemented=True,
        enabled_by_default=True,
        status=STATUS_READY,
    ),
    AIProviderProfile(
        provider_id="supreme_board_packet",
        display_name="Supreme Board Packet",
        provider_family="manual_packet",
        api_format=API_PACKET_BRIDGE,
        supports_streaming=False,
        supports_tools=False,
        supports_vision=False,
        supports_long_context=True,
        supports_json_schema=False,
        default_model="chatgpt-pro-manual",
        allowed_models=("chatgpt-pro-manual",),
        model_quality_map={"chatgpt-pro-manual": "HIGH_REASONING"},
        cost_tier_map={"chatgpt-pro-manual": CHATGPT_PRO_MANUAL},
        reasoning_capability_map={"chatgpt-pro-manual": "manual_highest_reasoning_workflow"},
        safety_notes=("No API call.", "Copy-ready packet for ChatGPT Pro/Supreme Board workflow."),
        implemented=True,
        enabled_by_default=True,
        status=STATUS_READY,
    ),
)


def list_ai_provider_profiles() -> tuple[AIProviderProfile, ...]:
    return AI_PROVIDER_PROFILES


def ai_provider_ids() -> tuple[str, ...]:
    return tuple(profile.provider_id for profile in AI_PROVIDER_PROFILES)


def get_ai_provider_profile(provider_id: str | None) -> AIProviderProfile | None:
    requested = str(provider_id or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "claude": "anthropic",
        "google": "gemini",
        "grok": "xai_grok",
        "xai": "xai_grok",
        "kimi": "kimi_moonshot",
        "moonshot": "kimi_moonshot",
        "local": "local_openai_compatible",
        "fallback": "deterministic_local",
        "packet": "supreme_board_packet",
    }
    requested = aliases.get(requested, requested)
    for profile in AI_PROVIDER_PROFILES:
        if profile.provider_id == requested:
            return profile
    return None


def configured_credential_source(profile: AIProviderProfile, env: Mapping[str, str]) -> str:
    if not profile.credential_env_vars:
        return "NOT_REQUIRED"
    for name in profile.credential_env_vars:
        if str(env.get(name) or "").strip():
            return "ENV_PRESENT"
    return "NOT_CONFIGURED"


def first_configured_secret(profile: AIProviderProfile, env: Mapping[str, str]) -> str:
    for name in profile.credential_env_vars:
        value = str(env.get(name) or "").strip()
        if value:
            return value
    return ""


def env_model_key(provider_id: str) -> str:
    return f"PK_AI_{provider_id.upper()}_MODEL"


def selected_model_for_provider(provider_id: str, env: Mapping[str, str] | None = None) -> str | None:
    env_map = os.environ if env is None else env
    profile = get_ai_provider_profile(provider_id)
    if profile is None:
        return None
    provider_upper = profile.provider_id.upper()
    aliases = {
        "openai": ("PK_AI_CHIEF_OPENAI_MODEL", "OPENAI_HIGH_REASONING_MODEL", "OPENAI_MODEL"),
        "anthropic": ("PK_AI_CHIEF_ANTHROPIC_MODEL", "ANTHROPIC_HIGH_REASONING_MODEL", "ANTHROPIC_MODEL"),
        "gemini": ("GEMINI_MODEL", "GOOGLE_AI_MODEL"),
        "xai_grok": ("XAI_MODEL", "GROK_MODEL"),
        "deepseek": ("DEEPSEEK_MODEL",),
        "kimi_moonshot": ("KIMI_MODEL", "MOONSHOT_MODEL"),
        "local_openai_compatible": ("LOCAL_AI_MODEL",),
    }
    for key in (env_model_key(profile.provider_id), *aliases.get(profile.provider_id, ())):
        value = str(env_map.get(key) or "").strip()
        if value:
            return value
    return profile.default_model


def base_url_for_provider(provider_id: str, env: Mapping[str, str] | None = None) -> str | None:
    env_map = os.environ if env is None else env
    profile = get_ai_provider_profile(provider_id)
    if profile is None:
        return None
    defaults = {
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com",
        "gemini": "https://generativelanguage.googleapis.com/v1beta",
        "xai_grok": "https://api.x.ai/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "kimi_moonshot": "https://api.moonshot.ai/v1",
        "local_openai_compatible": "http://127.0.0.1:11434/v1",
    }
    keys = [f"PK_AI_{profile.provider_id.upper()}_BASE_URL"]
    if profile.base_url_config_key:
        keys.append(profile.base_url_config_key)
    if profile.provider_id == "kimi_moonshot":
        keys.append("MOONSHOT_BASE_URL")
    for key in keys:
        value = str(env_map.get(key) or "").strip().rstrip("/")
        if value:
            return value
    return defaults.get(profile.provider_id)


def registry_summary(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    env_map = os.environ if env is None else env
    providers: list[dict[str, Any]] = []
    for profile in AI_PROVIDER_PROFILES:
        credential_source = configured_credential_source(profile, env_map)
        configured = credential_source in {"ENV_PRESENT", "NOT_REQUIRED"}
        status = profile.status
        if not profile.implemented:
            status = STATUS_NOT_IMPLEMENTED
        elif profile.credential_env_vars and not configured:
            status = STATUS_MISSING_CREDENTIALS
        providers.append(
            {
                **profile.to_dict(),
                "status": status,
                "configured": configured,
                "credential_source": credential_source,
                "model_name": selected_model_for_provider(profile.provider_id, env_map),
                "base_url_configured": bool(base_url_for_provider(profile.provider_id, env_map)),
                "secrets_values_exposed": False,
            }
        )
    counts: dict[str, int] = {}
    for provider in providers:
        status = str(provider["status"])
        counts[status] = counts.get(status, 0) + 1
    return {
        "source": "AI_PROVIDER_MODEL_REGISTRY",
        "registry_version": AI_PROVIDER_REGISTRY_VERSION,
        "providers": providers,
        "provider_count": len(providers),
        "provider_ids": [provider["provider_id"] for provider in providers],
        "counts": counts,
        "paid_call_on_status_load": False,
        "forced_persona_policy_required": True,
        "secrets_values_exposed": False,
    }
