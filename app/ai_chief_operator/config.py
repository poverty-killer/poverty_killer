"""AI Chief Operator configuration.

The default state is disabled. This module exposes only booleans and provider
names, never raw credentials or secret values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


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
    timeout_seconds: int = 15
    max_context_items: int = 50
    openai_configured: bool = False
    anthropic_configured: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AIChiefConfig":
        env_map = env or os.environ
        provider = str(env_map.get("PK_AI_CHIEF_PROVIDER") or "disabled").strip().lower()
        mock_mode = provider == "mock" or str(env_map.get("PK_AI_CHIEF_MOCK_MODE") or "").strip().lower() in {"1", "true", "yes", "on"}
        enabled = provider not in {"", "disabled", "off", "none"} or mock_mode
        try:
            timeout = max(int(env_map.get("PK_AI_CHIEF_TIMEOUT_SECONDS") or 15), 1)
        except ValueError:
            timeout = 15
        return cls(
            provider="mock" if mock_mode else provider,
            enabled=enabled,
            mock_mode=mock_mode,
            timeout_seconds=timeout,
            openai_configured=bool(str(env_map.get("OPENAI_API_KEY") or "").strip()),
            anthropic_configured=bool(str(env_map.get("ANTHROPIC_API_KEY") or "").strip()),
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
        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "mock_mode": self.mock_mode,
            "provider_state": self.provider_state(),
            "timeout_seconds": self.timeout_seconds,
            "max_context_items": self.max_context_items,
            "openai_configured": self.openai_configured,
            "anthropic_configured": self.anthropic_configured,
            "secrets_values_exposed": False,
        }
