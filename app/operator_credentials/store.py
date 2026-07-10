"""Gitignored local credential store for operator activation.

This module intentionally has no broker, execution, OMS, strategy, or AI
provider dependency. It persists local secrets so the operator backend can
prepare PAPER runtime credentials, while every public summary is redacted.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


STORE_VERSION = "operator-local-credential-store-v1"
DEFAULT_RELATIVE_STORE_PATH = ".operator_secrets/provider_credentials.json"
ALPACA_PAPER_ENV_PATH_ENV_KEY = "POVERTY_KILLER_ALPACA_PAPER_ENV_PATH"
ALPACA_PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
ALPACA_LIVE_ENDPOINT = "https://api.alpaca.markets"
ALPACA_MARKET_DATA_ENDPOINT = "https://data.alpaca.markets"
ALPACA_ENDPOINT_SOURCE_ENV_KEY = "APCA_API_BASE_URL_SOURCE"
ALPACA_PAPER_CREDENTIAL_KEYS = ("APCA_API_BASE_URL", "APCA_API_KEY_ID", "APCA_API_SECRET_KEY")
ALPACA_PAPER_REQUIRED_SECRET_KEYS = ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")
ALPACA_PAPER_ACCOUNT_PIN_ENV_KEY = "PK_ALPACA_PAPER_EXPECTED_ACCOUNT_SUFFIX"
ALPACA_PAPER_EXPECTED_ACCOUNT_SUFFIX = "045ded"
ALPACA_PAPER_ACCOUNT_PIN_SOURCE = "BOARD_D4_ACCOUNT_PIN_FUNDED_045DED"
ALPACA_BROKER_ENDPOINT_HOSTS = frozenset(
    {
        "broker-api.alpaca.markets",
        "broker-api.sandbox.alpaca.markets",
    }
)
ALPACA_ENDPOINT_CONFIGURATION_ACTION = (
    "Set APCA_API_BASE_URL to https://paper-api.alpaca.markets in Keys & Providers -> "
    "Alpaca PAPER Broker/Data -> PAPER base URL, or in the Windows process environment."
)


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


def canonical_alpaca_paper_env_path() -> Path:
    configured = os.environ.get(ALPACA_PAPER_ENV_PATH_ENV_KEY)
    return Path(configured) if configured else Path.home() / ".poverty_killer_alpaca_paper_env"


def normalize_alpaca_account_suffix(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.lower().startswith("redacted_suffix:"):
        text = text.split(":", 1)[1]
    return text[-6:].lower() if len(text) > 6 else text.lower()


def expected_alpaca_paper_account_suffix(_env: Mapping[str, str] | None = None) -> str:
    """Single canonical PAPER account pin.

    The active Board packet pins PAPER trading to Shan's funded 045ded account.
    Runtime env may carry this value to child processes, but cannot override it.
    """
    return ALPACA_PAPER_EXPECTED_ACCOUNT_SUFFIX


def alpaca_paper_account_pin_env() -> dict[str, str]:
    return {ALPACA_PAPER_ACCOUNT_PIN_ENV_KEY: expected_alpaca_paper_account_suffix()}


def alpaca_paper_account_pin_config() -> dict[str, Any]:
    return {
        "source": ALPACA_PAPER_ACCOUNT_PIN_SOURCE,
        "expected_suffix": expected_alpaca_paper_account_suffix(),
        "env_key": ALPACA_PAPER_ACCOUNT_PIN_ENV_KEY,
        "env_override_allowed": False,
        "raw_account_id_exposed": False,
        "secrets_values_exposed": False,
    }


def read_alpaca_paper_env_file(path: Path | None = None) -> dict[str, str]:
    env_path = path or canonical_alpaca_paper_env_path()
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        if key in ALPACA_PAPER_CREDENTIAL_KEYS:
            values[key] = value.strip().strip("'").strip('"')
    return values


def fingerprint_secret(value: str | None) -> str | None:
    text = str(value or "")
    if not text:
        return None
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"sha256:{digest}:len={len(text)}"


def _parse_endpoint_host_path(endpoint: str) -> tuple[str, str]:
    candidate = endpoint if "://" in endpoint else f"https://{endpoint}"
    parsed = urllib.parse.urlsplit(candidate)
    host = str(parsed.hostname or "").strip().lower()
    path = "/" + str(parsed.path or "").strip("/")
    if path == "/":
        path = ""
    return host, path


def normalize_alpaca_trading_endpoint(raw_endpoint: str | None) -> dict[str, Any]:
    """Classify a configured Alpaca endpoint without touching the network."""
    raw = str(raw_endpoint or "").strip()
    configured = bool(raw)
    if not configured:
        return {
            "raw_endpoint_configured": False,
            "raw_endpoint_display": None,
            "normalized_endpoint": ALPACA_PAPER_ENDPOINT,
            "endpoint_host": "paper-api.alpaca.markets",
            "endpoint_family": "paper",
            "paper_endpoint_valid": True,
            "live_endpoint_blocked": True,
            "blocker_code": None,
            "status": "PAPER_ENDPOINT_CONFIRMED",
            "source": "SAFE_DEFAULT_PAPER_ENDPOINT",
            "safe_detail": (
                "Alpaca PAPER trading endpoint was not configured; using the safe official "
                "PAPER trading default https://paper-api.alpaca.markets. Live endpoint "
                "api.alpaca.markets remains blocked."
            ),
            "operator_action": "No endpoint action required; safe official PAPER trading default is in force.",
        }

    host, path = _parse_endpoint_host_path(raw)
    paper_path_ok = path in {"", "/v2"}
    if host == "paper-api.alpaca.markets" and paper_path_ok:
        detail = "Alpaca PAPER trading endpoint is confirmed."
        if raw.rstrip("/") != ALPACA_PAPER_ENDPOINT:
            detail = "Alpaca PAPER trading endpoint is confirmed and normalized to https://paper-api.alpaca.markets."
        return {
            "raw_endpoint_configured": True,
            "raw_endpoint_display": raw,
            "normalized_endpoint": ALPACA_PAPER_ENDPOINT,
            "endpoint_host": host,
            "endpoint_family": "paper",
            "paper_endpoint_valid": True,
            "live_endpoint_blocked": True,
            "blocker_code": None,
            "status": "PAPER_ENDPOINT_CONFIRMED",
            "source": "CONFIGURED",
            "safe_detail": detail,
            "operator_action": "No endpoint action required.",
        }

    if host == "api.alpaca.markets":
        return {
            "raw_endpoint_configured": True,
            "raw_endpoint_display": raw,
            "normalized_endpoint": ALPACA_LIVE_ENDPOINT,
            "endpoint_host": host,
            "endpoint_family": "live",
            "paper_endpoint_valid": False,
            "live_endpoint_blocked": True,
            "blocker_code": "LIVE_ENDPOINT_BLOCKED",
            "status": "LIVE_ENDPOINT_BLOCKED",
            "source": "CONFIGURED",
            "safe_detail": (
                "Live Alpaca endpoint is blocked for this project. Use the PAPER trading "
                "endpoint only: https://paper-api.alpaca.markets."
            ),
            "operator_action": ALPACA_ENDPOINT_CONFIGURATION_ACTION,
        }

    if host == "data.alpaca.markets":
        return {
            "raw_endpoint_configured": True,
            "raw_endpoint_display": raw,
            "normalized_endpoint": ALPACA_MARKET_DATA_ENDPOINT,
            "endpoint_host": host,
            "endpoint_family": "data",
            "paper_endpoint_valid": False,
            "live_endpoint_blocked": True,
            "blocker_code": "ALPACA_DATA_ENDPOINT_NOT_TRADING",
            "status": "ALPACA_DATA_ENDPOINT_NOT_TRADING",
            "source": "CONFIGURED",
            "safe_detail": "data.alpaca.markets is a market data endpoint, not the PAPER trading endpoint.",
            "operator_action": ALPACA_ENDPOINT_CONFIGURATION_ACTION,
        }

    if host in ALPACA_BROKER_ENDPOINT_HOSTS:
        return {
            "raw_endpoint_configured": True,
            "raw_endpoint_display": raw,
            "normalized_endpoint": f"https://{host}",
            "endpoint_host": host,
            "endpoint_family": "broker",
            "paper_endpoint_valid": False,
            "live_endpoint_blocked": True,
            "blocker_code": "ALPACA_BROKER_ENDPOINT_UNSUPPORTED",
            "status": "ALPACA_BROKER_ENDPOINT_UNSUPPORTED",
            "source": "CONFIGURED",
            "safe_detail": (
                "Alpaca Broker API endpoints are not approved for this PAPER trading endpoint seam."
            ),
            "operator_action": ALPACA_ENDPOINT_CONFIGURATION_ACTION,
        }

    blocker = "ALPACA_UNSUPPORTED_ENDPOINT_PATH" if host == "paper-api.alpaca.markets" else "ALPACA_PAPER_ENDPOINT_REQUIRED"
    return {
        "raw_endpoint_configured": True,
        "raw_endpoint_display": raw,
        "normalized_endpoint": f"https://{host}" if host else "UNKNOWN_NON_PAPER_ENDPOINT",
        "endpoint_host": host or None,
        "endpoint_family": "unknown",
        "paper_endpoint_valid": False,
        "live_endpoint_blocked": True,
        "blocker_code": blocker,
        "status": blocker,
        "source": "CONFIGURED",
        "safe_detail": (
            "Configured Alpaca endpoint is not the required PAPER trading endpoint. "
            "Configure https://paper-api.alpaca.markets. Live endpoint api.alpaca.markets remains blocked."
        ),
        "operator_action": ALPACA_ENDPOINT_CONFIGURATION_ACTION,
    }


def alpaca_endpoint_authority(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return safe Alpaca endpoint authority without exposing credentials."""
    env = env or {}
    raw_endpoint = str(env.get("APCA_API_BASE_URL") or "").strip()
    endpoint_truth = normalize_alpaca_trading_endpoint(raw_endpoint)
    if (
        raw_endpoint
        and str(env.get(ALPACA_ENDPOINT_SOURCE_ENV_KEY) or "").strip().upper() == "SAFE_DEFAULT_PAPER_ENDPOINT"
        and endpoint_truth["paper_endpoint_valid"] is True
    ):
        endpoint_truth = {
            **endpoint_truth,
            "raw_endpoint_configured": False,
            "source": "SAFE_DEFAULT_PAPER_ENDPOINT",
            "safe_detail": (
                "Alpaca PAPER trading endpoint was not configured; using the safe official "
                "PAPER trading default https://paper-api.alpaca.markets. Live endpoint "
                "api.alpaca.markets remains blocked."
            ),
            "operator_action": "No endpoint action required; safe official PAPER trading default is in force.",
        }
    reason_code = endpoint_truth["blocker_code"]
    return {
        "status": endpoint_truth["status"],
        "reason_code": reason_code,
        "paper_endpoint_only": endpoint_truth["paper_endpoint_valid"] is True,
        "endpoint_source": endpoint_truth["source"],
        "actual_endpoint": endpoint_truth["normalized_endpoint"],
        "normalized_endpoint": endpoint_truth["normalized_endpoint"],
        "expected_paper_endpoint": ALPACA_PAPER_ENDPOINT,
        "safe_detail": endpoint_truth["safe_detail"],
        "operator_action": endpoint_truth["operator_action"],
        "alpaca_endpoint_configured": endpoint_truth["raw_endpoint_configured"],
        "alpaca_endpoint_source": endpoint_truth["source"],
        "alpaca_trading_endpoint_host": endpoint_truth["endpoint_host"],
        "alpaca_trading_endpoint_family": endpoint_truth["endpoint_family"],
        "alpaca_paper_endpoint_valid": endpoint_truth["paper_endpoint_valid"],
        "alpaca_live_endpoint_blocked": endpoint_truth["live_endpoint_blocked"],
        "alpaca_endpoint_blocker_code": reason_code,
        "alpaca_endpoint_display": endpoint_truth["normalized_endpoint"],
        "raw_endpoint_display": endpoint_truth["raw_endpoint_display"],
        "secrets_values_exposed": False,
        "raw_secret_values_included": False,
    }


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
    clean: dict[str, str] = {}
    for name in allowed:
        raw = credentials.get(name, "")
        value = str(raw or "").strip()
        if value:
            clean[name] = value
    if provider == "gemini" and not clean.get("GEMINI_API_KEY") and clean.get("GOOGLE_API_KEY"):
        clean["GEMINI_API_KEY"] = clean["GOOGLE_API_KEY"]
    if provider == "kimi_moonshot" and not clean.get("KIMI_API_KEY") and clean.get("MOONSHOT_API_KEY"):
        clean["KIMI_API_KEY"] = clean["MOONSHOT_API_KEY"]
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
            write_strategy = self._write_store_payload(payload)
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
            "write_strategy": write_strategy,
            "summary": self.provider_summary(provider),
        }

    def _write_store_payload(self, payload: Mapping[str, Any]) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, indent=2, sort_keys=True)
        tmp_path = self.path.with_name(f"{self.path.name}.tmp.{os.getpid()}.{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}")
        try:
            tmp_path.write_text(text, encoding="utf-8")
            os.replace(tmp_path, self.path)
            return "ATOMIC_REPLACE"
        except OSError:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            with self.path.open("w", encoding="utf-8") as handle:
                handle.write(text)
                handle.write("\n")
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            return "DIRECT_TRUNCATE_AFTER_ATOMIC_REPLACE_FAILED"

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
        if provider == "alpaca_paper" and field_name in ALPACA_PAPER_CREDENTIAL_KEYS:
            file_values = read_alpaca_paper_env_file()
            for candidate in candidate_names:
                file_value = str(file_values.get(candidate, "") or "").strip()
                if file_value:
                    return {
                        "name": field_name,
                        "value": file_value,
                        "source": "CANONICAL_PAPER_ENV_FILE",
                        "source_provider_id": "alpaca_paper_env_file",
                    }
            return {
                "name": field_name,
                "value": "",
                "source": "NOT_CONFIGURED",
                "source_provider_id": "alpaca_paper_env_file",
            }
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
        defaulted_alpaca_endpoint = False
        for name in (*fields["required"], *fields["optional"]):  # type: ignore[index]
            field_name = str(name)
            resolved = self.resolve_provider_field(provider, field_name, process_env)
            value = str(resolved.get("value") or "").strip()
            if not value and field_name in defaults:
                value = str(defaults[field_name] or "").strip()
                if provider in {"alpaca_paper", "alpaca_news"} and field_name == "APCA_API_BASE_URL" and value:
                    defaulted_alpaca_endpoint = True
            if value:
                effective[field_name] = value
        if provider == "gemini" and not effective.get("GEMINI_API_KEY") and effective.get("GOOGLE_API_KEY"):
            effective["GEMINI_API_KEY"] = effective["GOOGLE_API_KEY"]
        if provider == "kimi_moonshot" and not effective.get("KIMI_API_KEY") and effective.get("MOONSHOT_API_KEY"):
            effective["KIMI_API_KEY"] = effective["MOONSHOT_API_KEY"]
        if provider in {"alpaca_paper", "alpaca_news"} and "APCA_API_BASE_URL" not in effective:
            effective["APCA_API_BASE_URL"] = ALPACA_PAPER_ENDPOINT
            defaulted_alpaca_endpoint = True
        if defaulted_alpaca_endpoint:
            effective[ALPACA_ENDPOINT_SOURCE_ENV_KEY] = "SAFE_DEFAULT_PAPER_ENDPOINT"
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
        for key in ALPACA_PAPER_CREDENTIAL_KEYS:
            effective.pop(key, None)
        effective.update(self.effective_provider_values("alpaca_paper", {}))
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
            endpoint_authority = alpaca_endpoint_authority(effective)
            if endpoint_authority["paper_endpoint_only"] is not True:
                status = "VALIDATION_FAILED"
                reason_codes.append(str(endpoint_authority["reason_code"] or "ALPACA_PAPER_ENDPOINT_REQUIRED"))
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
            "paper_endpoint_authority": alpaca_endpoint_authority(self.effective_env(process_env or {})),
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
