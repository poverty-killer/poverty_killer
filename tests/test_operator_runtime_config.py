from __future__ import annotations

from pathlib import Path

from app.api.operator_runtime_config import OperatorRuntimeConfig


def test_operator_runtime_config_defaults_are_safe(tmp_path):
    cfg = OperatorRuntimeConfig.from_env({}, repo_root=tmp_path)

    assert cfg.runtime_profile == "LOCAL_PAPER"
    assert cfg.hosted_mode is False
    assert cfg.live_enabled is False
    assert cfg.real_money_enabled is False
    assert cfg.allowed_profile == "PAPER_EXPLORATION_ALPHA"
    assert cfg.allowed_watchlist == ("BTC/USD", "ETH/USD", "SOL/USD")
    assert cfg.min_paper_duration_seconds == 60
    assert cfg.max_paper_duration_seconds == 604800
    assert cfg.operator_session_store_path == tmp_path / "state" / "operator" / "sessions.jsonl"
    assert cfg.world_awareness_cache_path == tmp_path / "state" / "world_awareness" / "operator_events.jsonl"


def test_operator_runtime_config_env_overrides_without_secret_values(tmp_path):
    env = {
        "PK_RUNTIME_PROFILE": "CLOUD_PAPER",
        "PK_HOSTED_MODE": "true",
        "PK_DATA_DIR": "/var/lib/pk/data",
        "PK_LOG_DIR": "runtime_logs",
        "PK_OPERATOR_STATE_DIR": "operator_state",
        "PK_ALLOWED_WATCHLIST": "BTC/USD,SOL/USD",
        "PK_ALLOWED_DURATIONS": "300,1200",
        "PK_MAX_PAPER_DURATION_SECONDS": "86400",
        "PK_LIVE_ENABLED": "true",
        "PK_REAL_MONEY_ENABLED": "true",
        "APCA_API_KEY_ID": "secret-key-id",
        "APCA_API_SECRET_KEY": "secret-key",
    }
    cfg = OperatorRuntimeConfig.from_env(env, repo_root=tmp_path)
    summary = cfg.safe_summary()
    status = cfg.status()

    assert cfg.runtime_profile == "CLOUD_PAPER"
    assert cfg.hosted_mode is True
    assert str(cfg.data_dir).replace("\\", "/").endswith("/var/lib/pk/data")
    assert cfg.log_dir == tmp_path / "runtime_logs"
    assert cfg.operator_state_dir == tmp_path / "operator_state"
    assert cfg.allowed_watchlist == ("BTC/USD", "SOL/USD")
    assert cfg.allowed_durations == (300, 1200)
    assert cfg.max_paper_duration_seconds == 86400
    assert cfg.alpaca_credentials_present is True
    assert summary["alpaca_credentials_present"] is True
    assert "secret-key" not in str(summary)
    assert status["live_status"] == "LIVE_LOCKED"
    assert status["real_money_status"] == "BLOCKED"
    assert "PK_LIVE_ENABLED_IGNORED_BY_OPERATOR_API" in status["warnings"]
    assert "PK_REAL_MONEY_ENABLED_IGNORED_BY_OPERATOR_API" in status["warnings"]
