"""Safe operator provider readiness contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


PROVIDER_CATEGORIES = {
    "broker",
    "market_data",
    "news",
    "economic_calendar",
    "ai_provider",
    "alternative_data",
    "execution_analytics",
    "asset_class_data",
}

PROVIDER_STATUSES = {
    "CONFIGURED",
    "MISSING_CREDENTIALS",
    "DISABLED",
    "VALIDATION_FAILED",
    "READY",
    "NOT_IMPLEMENTED",
}


@dataclass(frozen=True)
class ProviderProfile:
    provider_id: str
    display_name: str
    category: str
    purpose: str
    required_env_vars: tuple[str, ...] = ()
    optional_env_vars: tuple[str, ...] = ()
    implemented: bool = False
    enabled_by_default: bool = False
    read_only_validation_supported: bool = False
    can_trade: bool = False
    can_mutate_external_system: bool = False
    setup_instructions: str = ""

    def __post_init__(self) -> None:
        if self.category not in PROVIDER_CATEGORIES:
            raise ValueError(f"unsupported provider category: {self.category}")


@dataclass(frozen=True)
class EnvVarStatus:
    name: str
    configured: bool
    fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderReadiness:
    provider_id: str
    display_name: str
    category: str
    purpose: str
    status: str
    required_env_vars: tuple[str, ...]
    optional_env_vars: tuple[str, ...]
    env_status: tuple[EnvVarStatus, ...] = ()
    configured: bool = False
    read_only_validation_supported: bool = False
    can_trade: bool = False
    can_mutate_external_system: bool = False
    last_validation_status: str = "NOT_RUN"
    last_validation_at: str | None = None
    setup_instructions: str = ""
    secrets_values_exposed: bool = False
    broker_call_occurred: bool = False
    external_mutation_occurred: bool = False
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.status not in PROVIDER_STATUSES:
            raise ValueError(f"unsupported provider status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["env_status"] = [item.to_dict() for item in self.env_status]
        payload["required_env_vars"] = list(self.required_env_vars)
        payload["optional_env_vars"] = list(self.optional_env_vars)
        payload["reason_codes"] = list(self.reason_codes)
        payload["secrets_values_exposed"] = False
        payload["broker_call_occurred"] = False
        payload["external_mutation_occurred"] = False
        payload["can_trade"] = False
        return payload
