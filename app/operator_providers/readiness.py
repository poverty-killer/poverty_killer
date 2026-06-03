"""Secret-safe provider readiness summaries for the operator UI."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from app.operator_credentials.store import LocalCredentialStore, fingerprint_secret
from app.operator_providers.models import EnvVarStatus, ProviderProfile, ProviderReadiness
from app.operator_providers.registry import list_provider_profiles

ALTERNATIVE_ENV_KEYS = {
    "GEMINI_API_KEY": ("GOOGLE_API_KEY",),
    "KIMI_API_KEY": ("MOONSHOT_API_KEY",),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _credential_value(
    *,
    provider_id: str,
    name: str,
    env: Mapping[str, str],
    local_env: Mapping[str, str],
    credential_store: LocalCredentialStore | None = None,
) -> tuple[str, str]:
    if credential_store is not None:
        resolved = credential_store.resolve_provider_field(provider_id, name, env)
        value = str(resolved.get("value") or "").strip()
        if value:
            return value, str(resolved.get("source") or "LOCAL_SECRET_PRESENT")
    env_value = str(env.get(name, "") or "").strip()
    if env_value:
        return env_value, "ENV_PRESENT"
    local_value = str(local_env.get(name, "") or "").strip()
    if local_value:
        return local_value, "LOCAL_SECRET_PRESENT"
    for alias in ALTERNATIVE_ENV_KEYS.get(name, ()):
        alias_env_value = str(env.get(alias, "") or "").strip()
        if alias_env_value:
            return alias_env_value, "ENV_PRESENT"
        alias_local_value = str(local_env.get(alias, "") or "").strip()
        if alias_local_value:
            return alias_local_value, "LOCAL_SECRET_PRESENT"
    return "", "NOT_CONFIGURED"


def _configured(profile: ProviderProfile, env: Mapping[str, str], local_env: Mapping[str, str], name: str, credential_store: LocalCredentialStore | None) -> bool:
    value, _source = _credential_value(
        provider_id=profile.provider_id,
        name=name,
        env=env,
        local_env=local_env,
        credential_store=credential_store,
    )
    return bool(value)


def _env_status(
    profile: ProviderProfile,
    env: Mapping[str, str],
    local_env: Mapping[str, str],
    credential_store: LocalCredentialStore | None,
) -> tuple[EnvVarStatus, ...]:
    rows: list[EnvVarStatus] = []
    for name in (*profile.required_env_vars, *profile.optional_env_vars):
        value, source = _credential_value(
            provider_id=profile.provider_id,
            name=name,
            env=env,
            local_env=local_env,
            credential_store=credential_store,
        )
        rows.append(
            EnvVarStatus(
                name=name,
                configured=bool(value),
                fingerprint=fingerprint_secret(value),
                source=source,
            )
        )
    return tuple(rows)


def build_provider_readiness(
    profile: ProviderProfile,
    env: Mapping[str, str],
    *,
    credential_store: LocalCredentialStore | None = None,
) -> ProviderReadiness:
    local_env = credential_store.local_env() if credential_store else {}
    env_rows = _env_status(profile, env, local_env, credential_store)
    missing_required = [
        name
        for name in profile.required_env_vars
        if not _configured(profile, env, local_env, name, credential_store)
    ]
    configured = not missing_required
    reason_codes: list[str] = []
    configured_sources = {row.source for row in env_rows if row.configured}
    required_sources = {
        row.source
        for row in env_rows
        if row.name in profile.required_env_vars and row.configured
    }
    if profile.required_env_vars:
        credential_source = "+".join(sorted(required_sources)) if configured else "NOT_CONFIGURED"
    else:
        credential_source = "NOT_REQUIRED"

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

    reason_codes.extend(f"CREDENTIAL_SOURCE:{source}" for source in sorted(configured_sources))
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
        credential_source=credential_source,
        last_validation_status="NOT_RUN",
        last_validation_at=None,
        setup_instructions=profile.setup_instructions,
        reason_codes=tuple(reason_codes),
    )


def provider_readiness_summary(
    env: Mapping[str, str],
    *,
    credential_store: LocalCredentialStore | None = None,
) -> dict[str, object]:
    providers = [
        build_provider_readiness(profile, env, credential_store=credential_store).to_dict()
        for profile in list_provider_profiles()
    ]
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
        "providers_source": "OPERATOR_PROVIDER_READINESS",
        "secrets_values_exposed": False,
        "raw_secret_values_included": False,
        "broker_call_occurred": False,
        "external_mutation_occurred": False,
        "can_execute": False,
        "credential_precedence": "ENV_PRESENT_OVERRIDES_LOCAL_SECRET",
    }


def validate_provider_readonly(
    provider_id: str,
    env: Mapping[str, str],
    *,
    profiles: tuple[ProviderProfile, ...] | None = None,
    credential_store: LocalCredentialStore | None = None,
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

    readiness = build_provider_readiness(profile, env, credential_store=credential_store).to_dict()
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
