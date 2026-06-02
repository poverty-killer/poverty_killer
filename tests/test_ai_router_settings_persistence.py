from __future__ import annotations

import json
from pathlib import Path

from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def _provider(tmp_path, env: dict[str, str] | None = None) -> OperatorSnapshotProvider:
    return OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env=env or {},
    )


def test_ai_router_settings_save_persists_and_reloads_after_new_backend_instance(tmp_path):
    app = create_operator_app(provider=_provider(tmp_path))
    saved = _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "SUPREME_BOARD_PACKET",
            "active_provider": "supreme_board_packet",
            "active_model": "chatgpt-pro-manual",
            "light_provider": "deepseek",
            "light_model": "deepseek-chat",
            "high_reasoning_provider": "anthropic",
            "high_reasoning_model": "claude-opus-4.7",
            "local_base_url": "http://127.0.0.1:11434/v1",
            "local_model": "qwen2.5-coder",
            "supreme_board_packet_default": True,
        }
    )

    assert saved["status"] == "SAVED"
    assert saved["settings_source"] == "PERSISTED_LOCAL_SETTINGS"
    assert saved["no_paid_call_occurred"] is True
    assert (tmp_path / ".operator_config" / "ai_router_settings.json").exists()

    reloaded_app = create_operator_app(provider=_provider(tmp_path))
    loaded = _endpoint(reloaded_app, "/operator/ai/router/settings")()

    assert loaded["settings_source"] == "PERSISTED_LOCAL_SETTINGS"
    assert loaded["settings"]["default_mode"] == "SUPREME_BOARD_PACKET"
    assert loaded["settings"]["light_provider"] == "deepseek"
    assert loaded["settings"]["high_reasoning_provider"] == "anthropic"
    assert loaded["settings"]["local_model"] == "qwen2.5-coder"
    assert loaded["settings"]["supreme_board_packet_default"] is True
    assert loaded["validation_errors"] == []
    assert loaded["broker_call_occurred"] is False
    assert loaded["trading_mutation_occurred"] is False

    persisted = json.loads((tmp_path / ".operator_config" / "ai_router_settings.json").read_text(encoding="utf-8"))
    assert "OPENAI_API_KEY" not in persisted
    assert "secrets_values_exposed" not in persisted["settings"]


def test_ai_router_settings_default_load_has_no_validation_errors(tmp_path):
    app = create_operator_app(provider=_provider(tmp_path))
    loaded = _endpoint(app, "/operator/ai/router/settings")()

    assert loaded["status"] == "DEFAULT_SETTINGS"
    assert loaded["settings_source"] == "DEFAULT_SETTINGS"
    assert loaded["validation_errors"] == []
    assert loaded["settings_file_exists"] is False


def test_ai_router_settings_do_not_write_secrets(tmp_path):
    app = create_operator_app(provider=_provider(tmp_path))
    refused = _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LIGHT_API",
            "active_provider": "openai",
            "active_model": "gpt-5-mini",
            "light_provider": "openai",
            "light_model": "gpt-5-mini",
            "OPENAI_API_KEY": "openai-router-test-token-1234567890",
        }
    )
    settings_path = tmp_path / ".operator_config" / "ai_router_settings.json"

    assert refused["status"] == "FAILED"
    assert refused["error_category"] == "VALIDATION_FAILED"
    assert any(error["reason_code"] == "SECRET_FIELD_REFUSED" for error in refused["validation_errors"])
    assert not settings_path.exists()


def test_missing_credentials_do_not_erase_saved_provider_selection(tmp_path):
    app = create_operator_app(provider=_provider(tmp_path))
    saved = _endpoint(app, "/operator/ai/router/settings", "POST")(
        {
            "default_mode": "LIGHT_API",
            "active_provider": "deepseek",
            "active_model": "deepseek-chat",
            "light_provider": "deepseek",
            "light_model": "deepseek-chat",
            "high_reasoning_provider": "openai",
            "high_reasoning_model": "gpt-5.5-pro",
            "local_model": "local-model",
        }
    )
    loaded = _endpoint(app, "/operator/ai/router/settings")()

    assert saved["status"] == "SAVED"
    assert loaded["settings"]["light_provider"] == "deepseek"
    assert loaded["settings"]["active_provider"] == "deepseek"
    assert loaded["provider_availability"]["deepseek"]["status"] == "MISSING_CREDENTIALS"
    assert loaded["provider_availability"]["deepseek"]["configured"] is False


def test_invalid_ai_router_provider_or_model_is_rejected_with_reason(tmp_path):
    app = create_operator_app(provider=_provider(tmp_path))
    invalid_provider = _endpoint(app, "/operator/ai/router/settings", "POST")(
        {"default_mode": "LIGHT_API", "light_provider": "single_vendor_only", "light_model": "gpt-5-mini"}
    )
    invalid_model = _endpoint(app, "/operator/ai/router/settings", "POST")(
        {"default_mode": "LIGHT_API", "light_provider": "openai", "light_model": "bad model name"}
    )

    assert invalid_provider["status"] == "FAILED"
    assert any(error["reason_code"] == "UNKNOWN_PROVIDER" for error in invalid_provider["validation_errors"])
    assert invalid_model["status"] == "FAILED"
    assert any(error["reason_code"] == "INVALID_MODEL_NAME" for error in invalid_model["validation_errors"])


def test_ai_router_settings_path_is_gitignored():
    gitignore = (Path.cwd() / ".gitignore").read_text(encoding="utf-8-sig")

    assert ".operator_config/" in gitignore
