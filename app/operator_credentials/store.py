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


def _provider_fields(provider_id: str) -> dict[str, object]:
    fields = PROVIDER_CREDENTIAL_FIELDS.get(str(provider_id))
    if fields is None:
        raise ValueError("UNKNOWN_PROVIDER")
    return fields


def _clean_credentials(provider_id: str, credentials: Mapping[str, Any]) -> dict[str, str]:
    fields = _provider_fields(provider_id)
    allowed = set(fields["required"]) | set(fields["optional"])  # type: ignore[arg-type]
    defaults = dict(fields.get("defaults") or {})
    clean: dict[str, str] = {}
    for name in allowed:
        raw = credentials.get(name, defaults.get(name, ""))
        value = str(raw or "").strip()
        if value:
            clean[name] = value
    if provider_id in {"alpaca_paper", "alpaca_news"} and "APCA_API_BASE_URL" not in clean:
        clean["APCA_API_BASE_URL"] = ALPACA_PAPER_ENDPOINT
    return clean


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
        provider = str(provider_id).strip().lower()
        try:
            fields = _provider_fields(provider)
        except ValueError:
            return {
                "source": "OPERATOR_LOCAL_CREDENTIAL_STORE",
                "provider_id": provider,
                "status": "REFUSED",
                "reason_code": "UNKNOWN_PROVIDER",
                "saved": False,
                "secrets_values_exposed": False,
                "raw_secret_values_included": False,
            }
        clean = _clean_credentials(provider, credentials)
        missing = [name for name in fields["required"] if not clean.get(str(name))]  # type: ignore[index]
        if missing:
            return {
                "source": "OPERATOR_LOCAL_CREDENTIAL_STORE",
                "provider_id": provider,
                "status": "REFUSED",
                "reason_code": "MISSING_REQUIRED_CREDENTIAL_FIELDS",
                "missing_fields": missing,
                "saved": False,
                "secrets_values_exposed": False,
                "raw_secret_values_included": False,
            }

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
        return {
            "source": "OPERATOR_LOCAL_CREDENTIAL_STORE",
            "provider_id": provider,
            "status": "SAVED",
            "saved": True,
            "configured": True,
            "summary": self.provider_summary(provider),
            "secrets_values_exposed": False,
            "raw_secret_values_included": False,
        }

    def delete_provider(self, provider_id: str) -> dict[str, Any]:
        provider = str(provider_id).strip().lower()
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
        provider = str(provider_id).strip().lower()
        data = self.load_raw()
        row = (data.get("providers") or {}).get(provider)
        if not isinstance(row, dict):
            return {}
        values = row.get("values")
        if not isinstance(values, dict):
            return {}
        return {str(k): str(v) for k, v in values.items() if str(v).strip()}

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
        provider = str(provider_id).strip().lower()
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
        local_values = self.provider_values(provider)
        required = tuple(str(name) for name in fields["required"])  # type: ignore[index]
        optional = tuple(str(name) for name in fields["optional"])  # type: ignore[index]
        rows: list[CredentialFieldSummary] = []
        for name in (*required, *optional):
            env_value = str(process_env.get(name, "") or "").strip()
            local_value = str(local_values.get(name, "") or "").strip()
            if env_value:
                source = "ENV_PRESENT"
                value = env_value
            elif local_value:
                source = "LOCAL_SECRET_PRESENT"
                value = local_value
            else:
                source = "NOT_CONFIGURED"
                value = ""
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
        provider = str(provider_id).strip().lower()
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
