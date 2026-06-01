"""Gitignored local credential store for operator activation.

This module intentionally has no broker, execution, OMS, strategy, or AI
provider dependency. It persists local secrets so the operator backend can
prepare PAPER runtime credentials, while every public summary is redacted.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


STORE_VERSION = "operator-local-credential-store-v1"
DEFAULT_RELATIVE_STORE_PATH = ".operator_secrets/provider_credentials.json"
ALPACA_PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
ALPACA_LIVE_ENDPOINT = "https://api.alpaca.markets"


PROVIDER_CREDENTIAL_FIELDS: dict[str, dict[str, object]] = {
    "alpaca_paper": {
        "display_name": "Alpaca PAPER Broker/Data",
        "required": ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY"),
        "optional": ("APCA_API_BASE_URL",),
        "defaults": {"APCA_API_BASE_URL": ALPACA_PAPER_ENDPOINT},
    },
    "alpaca_news": {
        "display_name": "Alpaca News",
        "required": ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY"),
        "optional": ("APCA_API_BASE_URL",),
        "defaults": {"APCA_API_BASE_URL": ALPACA_PAPER_ENDPOINT},
    },
    "openai": {
        "display_name": "OpenAI",
        "required": ("OPENAI_API_KEY",),
        "optional": (),
        "defaults": {},
    },
    "anthropic": {
        "display_name": "Anthropic / Claude",
        "required": ("ANTHROPIC_API_KEY",),
        "optional": (),
        "defaults": {},
    },
    "gemini": {
        "display_name": "Gemini / Google",
        "required": ("GEMINI_API_KEY",),
        "optional": ("GOOGLE_API_KEY",),
        "defaults": {},
    },
    "xai_grok": {
        "display_name": "Grok / xAI",
        "required": ("XAI_API_KEY",),
        "optional": ("XAI_BASE_URL",),
        "defaults": {},
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "required": ("DEEPSEEK_API_KEY",),
        "optional": ("DEEPSEEK_BASE_URL",),
        "defaults": {},
    },
    "kimi_moonshot": {
        "display_name": "Kimi / Moonshot",
        "required": ("KIMI_API_KEY",),
        "optional": ("MOONSHOT_API_KEY", "KIMI_BASE_URL", "MOONSHOT_BASE_URL"),
        "defaults": {},
    },
    "local_openai_compatible": {
        "display_name": "Local OpenAI-compatible Model",
        "required": ("LOCAL_AI_BASE_URL", "LOCAL_AI_MODEL"),
        "optional": ("LOCAL_AI_API_KEY",),
        "defaults": {},
    },
}

PROVIDER_ID_ALIASES = {
    "alpaca": "alpaca_paper",
    "alpaca-paper": "alpaca_paper",
    "alpaca paper": "alpaca_paper",
    "alpaca_paper_broker": "alpaca_paper",
    "alpaca-paper-broker": "alpaca_paper",
    "alpaca broker": "alpaca_paper",
    "alpaca-news": "alpaca_news",
    "alpaca news": "alpaca_news",
    "claude": "anthropic",
    "google": "gemini",
    "grok": "xai_grok",
    "xai": "xai_grok",
    "xai-grok": "xai_grok",
    "deepseek-ai": "deepseek",
    "kimi": "kimi_moonshot",
    "moonshot": "kimi_moonshot",
    "kimi-moonshot": "kimi_moonshot",
    "local": "local_openai_compatible",
    "local-ai": "local_openai_compatible",
    "local openai compatible": "local_openai_compatible",
}

ALTERNATIVE_CREDENTIAL_KEYS = {
    "GEMINI_API_KEY": ("GOOGLE_API_KEY",),
    "KIMI_API_KEY": ("MOONSHOT_API_KEY",),
}

SHARED_CREDENTIAL_PROVIDER_GROUPS = {
    "alpaca_paper": ("alpaca_paper", "alpaca_news"),
    "alpaca_news": ("alpaca_paper", "alpaca_news"),
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_credential_store_path(repo_root: Path) -> Path:
    return repo_root / DEFAULT_RELATIVE_STORE_PATH


def fingerprint_secret(value: str | None) -> str | None:
    text = str(value or "")
    if not text:
        return None
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"sha256:{digest}:len={len(text)}"


def normalize_provider_id(provider_id: str) -> str:
    raw = str(provider_id or "").strip()
    normalized = raw.replace("-", "_").replace(" ", "_").lower()
    return PROVIDER_ID_ALIASES.get(raw.lower(), PROVIDER_ID_ALIASES.get(normalized, normalized))


def _provider_fields(provider_id: str) -> dict[str, object]:
    fields = PROVIDER_CREDENTIAL_FIELDS.get(normalize_provider_id(provider_id))
    if fields is None:
        raise ValueError("UNKNOWN_PROVIDER")
    return fields


def _clean_credentials(provider_id: str, credentials: Mapping[str, Any]) -> dict[str, str]:
    provider = normalize_provider_id(provider_id)
    fields = _provider_fields(provider)
    allowed = set(fields["required"]) | set(fields["optional"])  # type: ignore[arg-type]
    defaults = dict(fields.get("defaults") or {})
    clean: dict[str, str] = {}
    for name in allowed:
        raw = credentials.get(name, defaults.get(name, ""))
        value = str(raw or "").strip()
        if value:
            clean[name] = value
    if provider == "gemini" and not clean.get("GEMINI_API_KEY") and clean.get("GOOGLE_API_KEY"):
        clean["GEMINI_API_KEY"] = clean["GOOGLE_API_KEY"]
    if provider == "kimi_moonshot" and not clean.get("KIMI_API_KEY") and clean.get("MOONSHOT_API_KEY"):
        clean["KIMI_API_KEY"] = clean["MOONSHOT_API_KEY"]
    if provider in {"alpaca_paper", "alpaca_news"} and "APCA_API_BASE_URL" not in clean:
        clean["APCA_API_BASE_URL"] = ALPACA_PAPER_ENDPOINT
    return clean


def credential_field_presence(provider_id: str, credentials: Mapping[str, Any]) -> dict[str, bool]:
    provider = normalize_provider_id(provider_id)
    try:
        fields = _provider_fields(provider)
    except ValueError:
        return {}
    ordered = [str(name) for name in (*fields["required"], *fields["optional"])]  # type: ignore[index]
    return {
        name: bool(str(credentials.get(name, "") or "").strip())
        for name in ordered
    }


@dataclass(frozen=True)
class CredentialFieldSummary:
    name: str
    configured: bool
    source: str
    fingerprint: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "configured": self.configured,
            "source": self.source,
            "fingerprint": self.fingerprint,
        }


class LocalCredentialStore:
    """JSON local credential store with redacted public summaries."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.exists()

    def vault_status(self) -> dict[str, Any]:
        parent = self.path.parent
        nearest_existing = parent
        while not nearest_existing.exists() and nearest_existing.parent != nearest_existing:
            nearest_existing = nearest_existing.parent
        return {
            "vault_path": str(self.path),
            "vault_file_exists": self.path.exists(),
            "vault_parent_exists": parent.exists(),
            "vault_parent_writable": bool(
                (parent.exists() and os.access(parent, os.W_OK))
                or (nearest_existing.exists() and os.access(nearest_existing, os.W_OK))
            ),
        }

    def credential_schema(self, provider_id: str) -> dict[str, Any]:
        provider = normalize_provider_id(provider_id)
        fields = _provider_fields(provider)
        return {
            "provider_id": provider,
            "display_name": fields["display_name"],
            "required_fields": [str(name) for name in fields["required"]],  # type: ignore[index]
            "optional_fields": [str(name) for name in fields["optional"]],  # type: ignore[index]
            "defaulted_fields": sorted(str(name) for name in dict(fields.get("defaults") or {})),
        }

    def load_raw(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": STORE_VERSION, "providers": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": STORE_VERSION, "providers": {}, "store_error": "LOCAL_CREDENTIAL_STORE_UNREADABLE"}
        if not isinstance(data, dict):
            return {"version": STORE_VERSION, "providers": {}, "store_error": "LOCAL_CREDENTIAL_STORE_INVALID"}
        providers = data.get("providers")
        if not isinstance(providers, dict):
            providers = {}
        return {"version": STORE_VERSION, "providers": providers}

    def save_provider(self, provider_id: str, credentials: Mapping[str, Any]) -> dict[str, Any]:
        provider = normalize_provider_id(provider_id)
        received_field_names = sorted(str(key) for key in credentials)
        base_result: dict[str, Any] = {
            "source": "OPERATOR_LOCAL_CREDENTIAL_STORE",
            "provider_id": provider,
            "received_provider_id": str(provider_id or "").strip(),
            "accepted_provider_ids": sorted(PROVIDER_CREDENTIAL_FIELDS),
            "received_field_names": received_field_names,
            "secrets_values_exposed": False,
            "raw_secret_values_included": False,
            **self.vault_status(),
        }
        try:
            fields = _provider_fields(provider)
        except ValueError:
            return {
                **base_result,
                "status": "REFUSED",
                "reason_code": "UNKNOWN_PROVIDER",
                "required_fields": [],
                "optional_fields": [],
                "received_field_presence": {},
                "saved": False,
            }
        base_result.update(
            {
                "required_fields": [str(name) for name in fields["required"]],  # type: ignore[index]
                "optional_fields": [str(name) for name in fields["optional"]],  # type: ignore[index]
                "received_field_presence": credential_field_presence(provider, credentials),
            }
        )
        clean = _clean_credentials(provider, credentials)
        missing = [name for name in fields["required"] if not clean.get(str(name))]  # type: ignore[index]
        if missing:
            return {
                **base_result,
                "status": "REFUSED",
                "reason_code": "MISSING_REQUIRED_CREDENTIAL_FIELDS",
                "missing_fields": missing,
                "saved": False,
            }

        try:
            data = self.load_raw()
            providers = dict(data.get("providers") or {})
            providers[provider] = {
                "provider_id": provider,
                "updated_at": utc_now_iso(),
                "values": clean,
            }
            payload = {"version": STORE_VERSION, "providers": providers}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(tmp_path, self.path)
        except OSError as exc:
            return {
                **base_result,
                **self.vault_status(),
                "status": "REFUSED",
                "reason_code": "LOCAL_CREDENTIAL_STORE_WRITE_FAILED",
                "error_type": type(exc).__name__,
                "saved": False,
            }
        return {
            **base_result,
            **self.vault_status(),
            "status": "SAVED",
            "saved": True,
            "configured": True,
            "summary": self.provider_summary(provider),
        }

    def delete_provider(self, provider_id: str) -> dict[str, Any]:
        provider = normalize_provider_id(provider_id)
        data = self.load_raw()
        providers = dict(data.get("providers") or {})
        existed = provider in providers
        providers.pop(provider, None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps({"version": STORE_VERSION, "providers": providers}, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, self.path)
        return {
            "source": "OPERATOR_LOCAL_CREDENTIAL_STORE",
            "provider_id": provider,
            "status": "DELETED" if existed else "NOT_FOUND",
            "deleted": existed,
            "secrets_values_exposed": False,
            "raw_secret_values_included": False,
        }

    def provider_values(self, provider_id: str) -> dict[str, str]:
        provider = normalize_provider_id(provider_id)
        data = self.load_raw()
        row = (data.get("providers") or {}).get(provider)
        if not isinstance(row, dict):
            return {}
        values = row.get("values")
        if not isinstance(values, dict):
            return {}
        return {str(k): str(v) for k, v in values.items() if str(v).strip()}

    def _provider_search_order(self, provider_id: str) -> tuple[str, ...]:
        provider = normalize_provider_id(provider_id)
        group = SHARED_CREDENTIAL_PROVIDER_GROUPS.get(provider)
        if not group:
            return (provider,)
        return tuple(dict.fromkeys((provider, *group)))

    def resolve_provider_field(
        self,
        provider_id: str,
        field_name: str,
        process_env: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        provider = normalize_provider_id(provider_id)
        process_env = process_env or {}
        candidate_names = (field_name, *ALTERNATIVE_CREDENTIAL_KEYS.get(field_name, ()))
        for candidate in candidate_names:
            env_value = str(process_env.get(candidate, "") or "").strip()
            if env_value:
                return {
                    "name": field_name,
                    "value": env_value,
                    "source": "ENV_PRESENT",
                    "source_provider_id": "process_env",
                }
        for source_provider_id in self._provider_search_order(provider):
            local_values = self.provider_values(source_provider_id)
            for candidate in candidate_names:
                local_value = str(local_values.get(candidate, "") or "").strip()
                if local_value:
                    return {
                        "name": field_name,
                        "value": local_value,
                        "source": "LOCAL_SECRET_PRESENT",
                        "source_provider_id": source_provider_id,
                    }
        return {
            "name": field_name,
            "value": "",
            "source": "NOT_CONFIGURED",
            "source_provider_id": "",
        }

    def effective_provider_values(self, provider_id: str, process_env: Mapping[str, str] | None = None) -> dict[str, str]:
        provider = normalize_provider_id(provider_id)
        try:
            fields = _provider_fields(provider)
        except ValueError:
            return {}
        process_env = process_env or {}
        defaults = dict(fields.get("defaults") or {})
        effective: dict[str, str] = {}
        for name in (*fields["required"], *fields["optional"]):  # type: ignore[index]
            field_name = str(name)
            resolved = self.resolve_provider_field(provider, field_name, process_env)
            value = str(resolved.get("value") or "").strip()
            if not value and field_name in defaults:
                value = str(defaults[field_name] or "").strip()
            if value:
                effective[field_name] = value
        if provider == "gemini" and not effective.get("GEMINI_API_KEY") and effective.get("GOOGLE_API_KEY"):
            effective["GEMINI_API_KEY"] = effective["GOOGLE_API_KEY"]
        if provider == "kimi_moonshot" and not effective.get("KIMI_API_KEY") and effective.get("MOONSHOT_API_KEY"):
            effective["KIMI_API_KEY"] = effective["MOONSHOT_API_KEY"]
        if provider in {"alpaca_paper", "alpaca_news"} and "APCA_API_BASE_URL" not in effective:
            effective["APCA_API_BASE_URL"] = ALPACA_PAPER_ENDPOINT
        return effective

    def local_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        for provider_id in PROVIDER_CREDENTIAL_FIELDS:
            for key, value in self.provider_values(provider_id).items():
                env.setdefault(key, value)
        return env

    def effective_env(self, process_env: Mapping[str, str]) -> dict[str, str]:
        local = self.local_env()
        effective = dict(local)
        for key, value in process_env.items():
            if str(value or "").strip():
                effective[str(key)] = str(value)
        return effective

    def provider_summary(self, provider_id: str, process_env: Mapping[str, str] | None = None) -> dict[str, Any]:
        provider = normalize_provider_id(provider_id)
        try:
            fields = _provider_fields(provider)
        except ValueError:
            return {
                "provider_id": provider,
                "display_name": provider,
                "configured": False,
                "required_fields": [],
                "optional_fields": [],
                "fields": [],
                "source": "UNKNOWN_PROVIDER",
                "precedence": "ENV_PRESENT_OVERRIDES_LOCAL_SECRET",
                "store_path": str(self.path),
                "secrets_values_exposed": False,
                "raw_secret_values_included": False,
            }
        process_env = process_env or {}
        required = tuple(str(name) for name in fields["required"])  # type: ignore[index]
        optional = tuple(str(name) for name in fields["optional"])  # type: ignore[index]
        rows: list[CredentialFieldSummary] = []
        for name in (*required, *optional):
            resolved = self.resolve_provider_field(provider, name, process_env)
            value = str(resolved.get("value") or "").strip()
            source = str(resolved.get("source") or "NOT_CONFIGURED")
            if not value and name in dict(fields.get("defaults") or {}):
                value = str(dict(fields.get("defaults") or {}).get(name) or "").strip()
                source = "SAFE_DEFAULT" if value else "NOT_CONFIGURED"
            rows.append(
                CredentialFieldSummary(
                    name=name,
                    configured=bool(value),
                    source=source,
                    fingerprint=fingerprint_secret(value),
                )
            )
        configured = all(row.configured for row in rows if row.name in required)
        sources = sorted({row.source for row in rows if row.configured}) or ["NOT_CONFIGURED"]
        return {
            "provider_id": provider,
            "display_name": fields["display_name"],
            "configured": configured,
            "required_fields": list(required),
            "optional_fields": list(optional),
            "fields": [row.to_dict() for row in rows],
            "source": "+".join(sources),
            "precedence": "ENV_PRESENT_OVERRIDES_LOCAL_SECRET",
            "store_path": str(self.path),
            "secrets_values_exposed": False,
            "raw_secret_values_included": False,
        }

    def providers_summary(self, process_env: Mapping[str, str] | None = None) -> dict[str, Any]:
        process_env = process_env or {}
        providers = [self.provider_summary(provider_id, process_env) for provider_id in PROVIDER_CREDENTIAL_FIELDS]
        return {
            "source": "OPERATOR_LOCAL_CREDENTIAL_STORE",
            "store_version": STORE_VERSION,
            "store_path": str(self.path),
            "store_exists": self.path.exists(),
            "providers": providers,
            "provider_count": len(providers),
            "configured_count": sum(1 for provider in providers if provider["configured"] is True),
            "precedence": "ENV_PRESENT_OVERRIDES_LOCAL_SECRET",
            "secrets_values_exposed": False,
            "raw_secret_values_included": False,
        }

    def validate_readonly(self, provider_id: str, process_env: Mapping[str, str] | None = None) -> dict[str, Any]:
        provider = normalize_provider_id(provider_id)
        if provider not in PROVIDER_CREDENTIAL_FIELDS:
            return {
                "source": "OPERATOR_LOCAL_CREDENTIAL_STORE",
                "provider_id": provider,
                "status": "VALIDATION_FAILED",
                "reason_codes": ["UNKNOWN_PROVIDER"],
                "read_only_validation": True,
                "broker_call_occurred": False,
                "external_mutation_occurred": False,
                "trading_mutation_occurred": False,
                "live_enabled": False,
                "real_money_enabled": False,
                "secrets_values_exposed": False,
                "raw_secret_values_included": False,
                "can_execute": False,
            }
        summary = self.provider_summary(provider, process_env or {})
        reason_codes: list[str] = []
        status = "READY" if summary["configured"] else "MISSING_CREDENTIALS"
        if provider in {"alpaca_paper", "alpaca_news"} and summary["configured"]:
            effective = self.effective_env(process_env or {})
            endpoint = str(effective.get("APCA_API_BASE_URL") or ALPACA_PAPER_ENDPOINT).rstrip("/")
            if endpoint == ALPACA_LIVE_ENDPOINT:
                status = "VALIDATION_FAILED"
                reason_codes.append("LIVE_ENDPOINT_BLOCKED")
            elif endpoint != ALPACA_PAPER_ENDPOINT:
                status = "VALIDATION_FAILED"
                reason_codes.append("ALPACA_PAPER_ENDPOINT_REQUIRED")
            else:
                reason_codes.append("PAPER_ENDPOINT_CONFIRMED")
        elif not summary["configured"]:
            reason_codes.append("MISSING_REQUIRED_CREDENTIAL_FIELDS")
        else:
            reason_codes.append("LOCAL_READ_ONLY_PRESENCE_VALIDATION_PASSED")
        return {
            "source": "OPERATOR_LOCAL_CREDENTIAL_STORE",
            "provider_id": provider,
            "status": status,
            "summary": summary,
            "reason_codes": reason_codes,
            "read_only_validation": True,
            "broker_call_occurred": False,
            "external_mutation_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
            "secrets_values_exposed": False,
            "raw_secret_values_included": False,
            "can_execute": False,
        }
