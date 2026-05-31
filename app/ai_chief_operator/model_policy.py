"""Model quality policy for the Chief Quant Advisor.

This module does not call model provider APIs. It classifies configured model
names so the operator UI/API can refuse silent downgrades for quant,
risk, portfolio, and governance work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


HIGH_REASONING = "HIGH_REASONING"
STANDARD = "STANDARD"
LOW_REASONING = "LOW_REASONING"
FALLBACK_ONLY = "FALLBACK_ONLY"
UNKNOWN = "UNKNOWN"

HIGHEST_AVAILABLE_REQUIRED = "HIGHEST_AVAILABLE_REQUIRED"
LOWER_MODEL_WARNING = "LOWER_MODEL_WARNING"
FALLBACK_ONLY_LIMITED = "FALLBACK_ONLY_LIMITED"

SERIOUS_AI_MODES = {
    "QUANT_ADVISOR",
    "QUANT_ENGINEER",
    "TRADING_SYSTEMS_AUDITOR",
    "RUN_PLANNER",
    "PORTFOLIO_REVIEW",
    "CODEX_PACKET_ADVISOR",
}


@dataclass(frozen=True)
class ModelQualityReport:
    provider: str
    provider_mode: str
    model_name: str | None
    model_quality: str
    reasoning_policy: str
    model_suitable_for_governance: bool
    warning: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "provider_mode": self.provider_mode,
            "model_name": self.model_name,
            "model_quality": self.model_quality,
            "reasoning_policy": self.reasoning_policy,
            "model_suitable_for_governance": self.model_suitable_for_governance,
            "warning": self.warning,
        }


def _env_flag(env: Mapping[str, str], *names: str, default: bool) -> bool:
    for name in names:
        raw = str(env.get(name) or "").strip().lower()
        if raw:
            return raw in {"1", "true", "yes", "on"}
    return default


def explicit_quality_override(env: Mapping[str, str], provider: str) -> str | None:
    provider_upper = str(provider or "").strip().upper()
    names = (
        f"{provider_upper}_MODEL_QUALITY_OVERRIDE",
        f"PK_AI_CHIEF_{provider_upper}_MODEL_QUALITY_OVERRIDE",
        "AI_MODEL_QUALITY_OVERRIDE",
        "PK_AI_CHIEF_MODEL_QUALITY_OVERRIDE",
    )
    allowed = {HIGH_REASONING, STANDARD, LOW_REASONING, FALLBACK_ONLY, UNKNOWN}
    for name in names:
        value = str(env.get(name) or "").strip().upper()
        if value in allowed:
            return value
    return None


def classify_model_quality(provider: str, model_name: str | None, *, override: str | None = None) -> str:
    if override in {HIGH_REASONING, STANDARD, LOW_REASONING, FALLBACK_ONLY, UNKNOWN}:
        return str(override)
    provider_key = str(provider or "").strip().lower()
    model = str(model_name or "").strip().lower()
    if not model:
        return FALLBACK_ONLY
    low_tokens = ("mini", "nano", "haiku", "instant", "fast", "cheap", "small", "lite")
    if any(token in model for token in low_tokens):
        return LOW_REASONING
    if provider_key == "openai":
        high_tokens = (
            "gpt-5.5-pro",
            "gpt-5.5 pro",
            "gpt-5.5-thinking",
            "gpt-5.5 thinking",
            "gpt-5-pro",
            "o1-pro",
            "o3-pro",
            "o3",
            "reasoning-high",
        )
        if any(token in model for token in high_tokens):
            return HIGH_REASONING
        if "gpt-5.5" in model and ("pro" in model or "thinking" in model or "reasoning" in model):
            return HIGH_REASONING
        if model.startswith("gpt-5") or model.startswith("gpt-4"):
            return STANDARD
    if provider_key == "anthropic":
        if "opus" in model:
            return HIGH_REASONING
        if "sonnet" in model:
            return STANDARD
    return UNKNOWN


def provider_mode_for(provider: str, *, configured: bool, error: bool = False, fallback: bool = False) -> str:
    provider_key = str(provider or "").strip().lower()
    if error:
        return "PROVIDER_ERROR"
    if fallback:
        return "DETERMINISTIC_FALLBACK"
    if not configured or provider_key in {"", "disabled", "off", "none"}:
        return "NOT_CONFIGURED"
    if provider_key == "openai":
        return "LIVE_OPENAI"
    if provider_key == "anthropic":
        return "LIVE_ANTHROPIC"
    return "PROVIDER_ERROR"


def model_quality_report(
    *,
    provider: str,
    model_name: str | None,
    configured: bool,
    override: str | None = None,
    fallback: bool = False,
    error: bool = False,
) -> ModelQualityReport:
    provider_mode = provider_mode_for(provider, configured=configured, error=error, fallback=fallback)
    if error:
        quality = UNKNOWN
        policy = FALLBACK_ONLY_LIMITED
        warning = "Configured provider/model returned an error; no expert model answer is being faked."
    elif fallback or provider_mode in {"DETERMINISTIC_FALLBACK", "NOT_CONFIGURED"}:
        quality = FALLBACK_ONLY
        policy = FALLBACK_ONLY_LIMITED
        warning = "DETERMINISTIC FALLBACK - not a full AI quant reasoning response."
    else:
        quality = classify_model_quality(provider, model_name, override=override)
        if quality == HIGH_REASONING:
            policy = HIGHEST_AVAILABLE_REQUIRED
            warning = None
        else:
            policy = LOWER_MODEL_WARNING
            warning = "LOWER-REASONING MODEL ACTIVE - not suitable for final quant/risk/governance decisions."
    return ModelQualityReport(
        provider=provider,
        provider_mode=provider_mode,
        model_name=model_name,
        model_quality=quality,
        reasoning_policy=policy,
        model_suitable_for_governance=quality == HIGH_REASONING and provider_mode in {"LIVE_OPENAI", "LIVE_ANTHROPIC"},
        warning=warning,
    )


def prompt_allows_model_call(
    *,
    mode: str,
    report: ModelQualityReport,
    require_high_reasoning_for_quant: bool,
    allow_low_reasoning_for_ui_help: bool,
) -> bool:
    if report.model_quality == HIGH_REASONING and report.provider_mode in {"LIVE_OPENAI", "LIVE_ANTHROPIC"}:
        return True
    if report.provider_mode not in {"LIVE_OPENAI", "LIVE_ANTHROPIC"}:
        return False
    if mode in SERIOUS_AI_MODES and require_high_reasoning_for_quant:
        return False
    if mode in {"OPERATOR_GUIDE", "SETUP_HELP"} and allow_low_reasoning_for_ui_help:
        return report.model_quality in {STANDARD, LOW_REASONING, UNKNOWN}
    return False


def config_flags_from_env(env: Mapping[str, str]) -> dict[str, bool]:
    return {
        "require_high_reasoning_for_quant": _env_flag(
            env,
            "AI_REQUIRE_HIGH_REASONING_FOR_QUANT",
            "PK_AI_REQUIRE_HIGH_REASONING_FOR_QUANT",
            default=True,
        ),
        "allow_low_reasoning_for_ui_help": _env_flag(
            env,
            "AI_ALLOW_LOW_REASONING_FOR_UI_HELP",
            "PK_AI_ALLOW_LOW_REASONING_FOR_UI_HELP",
            default=False,
        ),
        "show_model_quality": _env_flag(
            env,
            "AI_SHOW_MODEL_QUALITY",
            "PK_AI_SHOW_MODEL_QUALITY",
            default=True,
        ),
        "refuse_governance_on_low_reasoning": _env_flag(
            env,
            "AI_REFUSE_GOVERNANCE_ON_LOW_REASONING",
            "PK_AI_REFUSE_GOVERNANCE_ON_LOW_REASONING",
            default=True,
        ),
    }
