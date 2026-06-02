"""Persistent non-secret AI router settings for the operator console."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.ai_chief_operator.model_registry import ai_provider_ids, get_ai_provider_profile
from app.ai_chief_operator.model_router import HIGH_REASONING_API, LIGHT_API, LOCAL_GUIDE, LOCAL_MODEL_MODE, SUPREME_BOARD_PACKET_MODE


AI_ROUTER_SETTINGS_VERSION = "ai-router-settings-v1"
DEFAULT_AI_ROUTER_SETTINGS_RELATIVE_PATH = ".operator_config/ai_router_settings.json"

SOURCE_DEFAULT = "DEFAULT_SETTINGS"
SOURCE_PERSISTED = "PERSISTED_LOCAL_SETTINGS"
SOURCE_IN_MEMORY = "IN_MEMORY_UNSAVED"

HIGH_REASONING_WITH_APPROVAL = "HIGH_REASONING_API_WITH_APPROVAL"

SECRET_KEY_RE = re.compile(r"(api[_-]?key|secret|token|password|credential|authorization|bearer)", re.IGNORECASE)
SECRET_VALUE_RE = re.compile(r"(sk-[A-Za-z0-9_-]{10,}|AKIA[0-9A-Z]{12,}|xox[baprs]-[A-Za-z0-9-]+|-----BEGIN [A-Z ]*PRIVATE KEY-----)", re.IGNORECASE)
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/@+\-]+$")
URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_ai_router_settings_path(repo_root: Path) -> Path:
    return repo_root / DEFAULT_AI_ROUTER_SETTINGS_RELATIVE_PATH


def default_ai_router_settings() -> dict[str, Any]:
    return {
        "default_mode": LOCAL_GUIDE,
        "active_provider": "deterministic_local",
        "active_model": "deterministic-local-guide",
        "light_provider": "openai",
        "light_model": "gpt-5-mini",
        "high_reasoning_provider": "openai",
        "high_reasoning_model": "gpt-5.5-pro",
        "local_provider": "local_openai_compatible",
        "local_base_url": "http://127.0.0.1:11434/v1",
        "local_model": "local-model",
        "supreme_board_packet_default": False,
        "high_reasoning_api_requires_approval": True,
        "background_model_calls_disabled": True,
        "no_paid_call_on_load": True,
        "require_approval_for_paid_calls": True,
        "allow_paid_background_calls": False,
        "cost_control_flags": {
            "free_local_default": True,
            "paid_api_requires_explicit_approval": True,
            "settings_load_never_calls_provider": True,
        },
        "model_quality_overrides": {},
    }


def normalize_settings_mode(value: Any) -> str:
    raw = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "": LOCAL_GUIDE,
        "LOCAL": LOCAL_GUIDE,
        "LOCAL_GUIDE": LOCAL_GUIDE,
        "LIGHT": LIGHT_API,
        "LIGHT_API": LIGHT_API,
        "HIGH": HIGH_REASONING_WITH_APPROVAL,
        "HIGH_REASONING": HIGH_REASONING_WITH_APPROVAL,
        "HIGH_REASONING_API": HIGH_REASONING_WITH_APPROVAL,
        "HIGH_REASONING_API_WITH_APPROVAL": HIGH_REASONING_WITH_APPROVAL,
        "SUPREME_BOARD": SUPREME_BOARD_PACKET_MODE,
        "SUPREME_BOARD_PACKET": SUPREME_BOARD_PACKET_MODE,
        "PACKET": SUPREME_BOARD_PACKET_MODE,
        "LOCAL_MODEL": LOCAL_MODEL_MODE,
    }
    return aliases.get(raw, LOCAL_GUIDE)


def router_mode_for_gateway(value: Any) -> str:
    mode = normalize_settings_mode(value)
    return HIGH_REASONING_API if mode == HIGH_REASONING_WITH_APPROVAL else mode


def _clean_provider(value: Any) -> str:
    profile = get_ai_provider_profile(str(value or ""))
    return profile.provider_id if profile else ""


def _clean_model(value: Any) -> str:
    return str(value or "").strip()[:120]


def _contains_secret_key_or_value(value: Any, *, key: str = "") -> bool:
    if SECRET_KEY_RE.search(str(key or "")):
        return True
    if isinstance(value, Mapping):
        return any(_contains_secret_key_or_value(v, key=str(k)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_secret_key_or_value(item) for item in value)
    if isinstance(value, str):
        return bool(SECRET_VALUE_RE.search(value))
    return False


def _validate_provider(provider_id: str, field: str, errors: list[dict[str, str]]) -> str:
    cleaned = _clean_provider(provider_id)
    if not cleaned:
        errors.append({"field": field, "reason_code": "UNKNOWN_PROVIDER", "detail": f"{field} has unknown provider id."})
    return cleaned


def _validate_model(model_name: str, field: str, errors: list[dict[str, str]]) -> str:
    cleaned = _clean_model(model_name)
    if not cleaned:
        errors.append({"field": field, "reason_code": "MISSING_MODEL_NAME", "detail": f"{field} requires a model name."})
    elif not MODEL_RE.match(cleaned):
        errors.append({"field": field, "reason_code": "INVALID_MODEL_NAME", "detail": f"{field} contains unsupported characters."})
    return cleaned


def _selected_active(default_mode: str, settings: Mapping[str, Any]) -> tuple[str, str]:
    if default_mode == LIGHT_API:
        return str(settings.get("light_provider") or "openai"), str(settings.get("light_model") or "gpt-5-mini")
    if default_mode == HIGH_REASONING_WITH_APPROVAL:
        return str(settings.get("high_reasoning_provider") or "openai"), str(settings.get("high_reasoning_model") or "gpt-5.5-pro")
    if default_mode == SUPREME_BOARD_PACKET_MODE:
        return "supreme_board_packet", "chatgpt-pro-manual"
    if default_mode == LOCAL_MODEL_MODE:
        return "local_openai_compatible", str(settings.get("local_model") or "local-model")
    return "deterministic_local", "deterministic-local-guide"


def normalize_ai_router_settings(payload: Mapping[str, Any] | None, *, defaults: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, str]]]:
    source = dict(default_ai_router_settings())
    if defaults:
        source.update({key: value for key, value in defaults.items() if value is not None})
    body = dict(payload or {})
    errors: list[dict[str, str]] = []
    if _contains_secret_key_or_value(body):
        errors.append({"field": "payload", "reason_code": "SECRET_FIELD_REFUSED", "detail": "Router settings cannot contain API keys, secrets, tokens, or credentials."})

    default_mode = normalize_settings_mode(body.get("default_mode") or body.get("route_mode") or source.get("default_mode"))
    settings = {
        "default_mode": default_mode,
        "light_provider": _validate_provider(body.get("light_provider") or source.get("light_provider"), "light_provider", errors),
        "light_model": _validate_model(body.get("light_model") or source.get("light_model"), "light_model", errors),
        "high_reasoning_provider": _validate_provider(body.get("high_reasoning_provider") or source.get("high_reasoning_provider"), "high_reasoning_provider", errors),
        "high_reasoning_model": _validate_model(body.get("high_reasoning_model") or source.get("high_reasoning_model"), "high_reasoning_model", errors),
        "local_provider": "local_openai_compatible",
        "local_base_url": str(body.get("local_base_url") or source.get("local_base_url") or "http://127.0.0.1:11434/v1").strip().rstrip("/"),
        "local_model": _validate_model(body.get("local_model") or source.get("local_model"), "local_model", errors),
        "supreme_board_packet_default": body.get("supreme_board_packet_default") is True or source.get("supreme_board_packet_default") is True,
        "high_reasoning_api_requires_approval": True,
        "background_model_calls_disabled": True,
        "no_paid_call_on_load": True,
        "require_approval_for_paid_calls": True,
        "allow_paid_background_calls": False,
        "cost_control_flags": {
            "free_local_default": True,
            "paid_api_requires_explicit_approval": True,
            "settings_load_never_calls_provider": True,
        },
        "model_quality_overrides": body.get("model_quality_overrides") if isinstance(body.get("model_quality_overrides"), dict) else dict(source.get("model_quality_overrides") or {}),
    }
    if settings["local_base_url"] and not URL_RE.match(settings["local_base_url"]):
        errors.append({"field": "local_base_url", "reason_code": "INVALID_LOCAL_BASE_URL", "detail": "local_base_url must be an http(s) URL."})

    active_provider = _clean_provider(body.get("active_provider") or "")
    active_model = _clean_model(body.get("active_model") or "")
    if not active_provider or not active_model:
        active_provider, active_model = _selected_active(default_mode, settings)
    settings["active_provider"] = _validate_provider(active_provider, "active_provider", errors)
    settings["active_model"] = _validate_model(active_model, "active_model", errors)

    return settings, errors


@dataclass
class AIRouterSettingsStore:
    path: Path

    def load(self, *, defaults: Mapping[str, Any] | None = None) -> dict[str, Any]:
        base = dict(default_ai_router_settings())
        if defaults:
            base.update({key: value for key, value in defaults.items() if value is not None})
        if not self.path.exists():
            settings, errors = normalize_ai_router_settings(base, defaults=base)
            return self._response(
                status="DEFAULT_SETTINGS",
                settings=settings,
                settings_source=SOURCE_DEFAULT,
                validation_errors=errors,
                persisted=False,
            )
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            settings, errors = normalize_ai_router_settings(base, defaults=base)
            return self._response(
                status="DEFAULT_SETTINGS",
                settings=settings,
                settings_source=SOURCE_DEFAULT,
                validation_errors=[{"field": "settings_file", "reason_code": "SETTINGS_FILE_UNREADABLE", "detail": type(exc).__name__}],
                persisted=False,
            )
        raw_settings = payload.get("settings") if isinstance(payload, dict) else {}
        settings, errors = normalize_ai_router_settings(raw_settings if isinstance(raw_settings, dict) else {}, defaults=base)
        return self._response(
            status="LOADED",
            settings=settings,
            settings_source=SOURCE_PERSISTED,
            validation_errors=errors,
            persisted=True,
            updated_at=str(payload.get("updated_at") or "") if isinstance(payload, dict) else None,
        )

    def save(self, payload: Mapping[str, Any], *, defaults: Mapping[str, Any] | None = None) -> dict[str, Any]:
        settings, errors = normalize_ai_router_settings(payload, defaults=defaults)
        if errors:
            return self._response(
                status="FAILED",
                settings=settings,
                settings_source=SOURCE_IN_MEMORY,
                validation_errors=errors,
                persisted=False,
                error_category="VALIDATION_FAILED",
                safe_error_message="AI router settings were not saved because validation failed.",
            )
        data = {
            "version": AI_ROUTER_SETTINGS_VERSION,
            "updated_at": utc_now_iso(),
            "settings": settings,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(tmp_path, self.path)
        except OSError as exc:
            return self._response(
                status="FAILED",
                settings=settings,
                settings_source=SOURCE_IN_MEMORY,
                validation_errors=[{"field": "settings_file", "reason_code": "SETTINGS_WRITE_FAILED", "detail": type(exc).__name__}],
                persisted=False,
                error_category="SETTINGS_WRITE_FAILED",
                safe_error_message="AI router settings could not be written to the local config store.",
            )
        return self._response(status="SAVED", settings=settings, settings_source=SOURCE_PERSISTED, validation_errors=[], persisted=True, updated_at=data["updated_at"])

    def _response(
        self,
        *,
        status: str,
        settings: dict[str, Any],
        settings_source: str,
        validation_errors: list[dict[str, str]],
        persisted: bool,
        updated_at: str | None = None,
        error_category: str | None = None,
        safe_error_message: str | None = None,
    ) -> dict[str, Any]:
        return {
            "source": "AI_ROUTER_SETTINGS_STORE",
            "version": AI_ROUTER_SETTINGS_VERSION,
            "status": status,
            "settings": settings,
            "settings_source": settings_source,
            "settings_path_relative": DEFAULT_AI_ROUTER_SETTINGS_RELATIVE_PATH,
            "settings_file_exists": self.path.exists(),
            "persisted": persisted,
            "updated_at": updated_at,
            "validation_errors": validation_errors,
            "error_category": error_category,
            "safe_error_message": safe_error_message,
            "accepted_provider_ids": list(ai_provider_ids()),
            "secret_storage": "LOCAL_CREDENTIAL_VAULT_ONLY",
            "no_paid_call_occurred": True,
            "background_model_calls_disabled": True,
            "high_reasoning_api_requires_approval": True,
            "broker_call_occurred": False,
            "trading_mutation_occurred": False,
            "live_enabled": False,
            "real_money_enabled": False,
            "secrets_values_exposed": False,
        }
