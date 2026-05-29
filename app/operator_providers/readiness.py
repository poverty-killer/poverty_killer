"""Secret-safe provider readiness summaries for the operator UI."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Mapping

from app.operator_providers.models import EnvVarStatus, ProviderProfile, ProviderReadiness
from app.operator_providers.registry import list_provider_profiles


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _configured(env: Mapping[str, str], name: str) -> bool:
    return bool(str(env.get(name, "")).strip())


def _fingerprint(value: str) -> str | None:
    text = str(value or "")
    if not text:
        return None
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"sha256:{digest}:len={len(text)}"


def _env_status(profile: ProviderProfile, env: Mapping[str, str]) -> tuple[EnvVarStatus, ...]:
    rows: list[EnvVarStatus] = []
    for name in (*profile.required_env_vars, *profile.optional_env_vars):
        value = str(env.get(name, "") or "")
        rows.append(EnvVarStatus(name=name, configured=bool(value.strip()), fingerprint=_fingerprint(value)))
    return tuple(rows)


def build_provider_readiness(profile: ProviderProfile, env: Mapping[str, str]) -> ProviderReadiness:
    env_rows = _env_status(profile, env)
    missing_required = [name for name in profile.required_env_vars if not _configured(env, name)]
    configured = not missing_required
    reason_codes: list[str] = []

    if not profile.implemented:
        status = "NOT_IMPLEMENTED"
        reason_codes.append("PROVIDER_NOT_IMPLEMENTED")
    elif not profile.enabled_by_default and not configured:
        status = "DISABLED" if not profile.required_env_vars else "MISSING_CREDENTIALS"
        reason_codes.append("PROVIDER_DISABLED_OR_NOT_CONFIGURED")
    elif missing_required:
        status = "MISSING_CREDENTIALS"
        reason_codes.extend(f"MISSING_ENV:{name}" for name in missing_required)
    elif profile.read_only_validation_supported:
        status = "CONFIGURED"
        reason_codes.append("READ_ONLY_VALIDATION_AVAILABLE_NOT_RUN")
    else:
        status = "READY"
        reason_codes.append("NO_CREDENTIALS_REQUIRED")

    return ProviderReadiness(
        provider_id=profile.provider_id,
        display_name=profile.display_name,
        category=profile.category,
        purpose=profile.purpose,
        status=status,
        required_env_vars=profile.required_env_vars,
        optional_env_vars=profile.optional_env_vars,
        env_status=env_rows,
        configured=configured,
        read_only_validation_supported=profile.read_only_validation_supported,
        can_trade=False,
        can_mutate_external_system=False,
        last_validation_status="NOT_RUN",
        last_validation_at=None,
        setup_instructions=profile.setup_instructions,
        reason_codes=tuple(reason_codes),
    )


def provider_readiness_summary(env: Mapping[str, str]) -> dict[str, object]:
    providers = [build_provider_readiness(profile, env).to_dict() for profile in list_provider_profiles()]
    counts: dict[str, int] = {}
    for provider in providers:
        status = str(provider["status"])
        counts[status] = counts.get(status, 0) + 1
    return {
        "source": "OPERATOR_PROVIDER_READINESS",
        "provider_registry_version": "operator-provider-registry-v1",
        "providers": providers,
        "provider_count": len(providers),
        "counts": counts,
        "secrets_values_exposed": False,
        "raw_secret_values_included": False,
        "broker_call_occurred": False,
        "external_mutation_occurred": False,
        "can_execute": False,
    }


def validate_provider_readonly(
    provider_id: str,
    env: Mapping[str, str],
    *,
    profiles: tuple[ProviderProfile, ...] | None = None,
) -> dict[str, object]:
    profile_map = {profile.provider_id: profile for profile in (profiles or list_provider_profiles())}
    profile = profile_map.get(str(provider_id))
    if profile is None:
        return {
            "source": "OPERATOR_PROVIDER_READINESS",
            "provider_id": provider_id,
            "status": "VALIDATION_FAILED",
            "reason_code": "UNKNOWN_PROVIDER",
            "read_only_validation": True,
            "broker_call_occurred": False,
            "external_mutation_occurred": False,
            "secrets_values_exposed": False,
        }

    readiness = build_provider_readiness(profile, env).to_dict()
    if not profile.read_only_validation_supported:
        validation_status = "NOT_IMPLEMENTED"
        reason_code = "READ_ONLY_VALIDATION_NOT_IMPLEMENTED"
    elif not readiness["configured"]:
        validation_status = "MISSING_CREDENTIALS"
        reason_code = "MISSING_REQUIRED_ENV_VARS"
    elif not profile.implemented:
        validation_status = "NOT_IMPLEMENTED"
        reason_code = "PROVIDER_NOT_IMPLEMENTED"
    else:
        validation_status = "READY"
        reason_code = "ENV_PRESENT_READ_ONLY_VALIDATION_ONLY"

    readiness.update(
        {
            "status": validation_status,
            "last_validation_status": validation_status,
            "last_validation_at": _utc_now(),
            "reason_code": reason_code,
            "read_only_validation": True,
            "broker_call_occurred": False,
            "external_mutation_occurred": False,
            "trading_mutation_occurred": False,
            "secrets_values_exposed": False,
            "can_execute": False,
        }
    )
    return readiness
