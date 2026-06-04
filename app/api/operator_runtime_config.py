"""Cloud-safe operator runtime configuration.

This module is intentionally limited to operator/runtime metadata. It does not
import broker, execution, OMS, alpha, or strategy code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


RUNTIME_PROFILES = {
    "LOCAL_DEV",
    "LOCAL_PAPER",
    "CLOUD_PAPER",
    "CLOUD_SHADOW",
    "CLOUD_LIVE_LOCKED",
    "CLOUD_LIVE_APPROVED",
}

DEFAULT_ALLOWED_WATCHLIST = ("BTC/USD", "ETH/USD", "SOL/USD")
DEFAULT_ALLOWED_DURATIONS = (180, 300, 900, 1200, 1800, 3600, 7200, 10800, 14400)
DEFAULT_MIN_PAPER_DURATION_SECONDS = 60
RUNNER_MAX_PAPER_DURATION_SECONDS = 86400
DEFAULT_MAX_PAPER_DURATION_SECONDS = RUNNER_MAX_PAPER_DURATION_SECONDS


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def _truthy(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(value: str | None, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if not value:
        return fallback
    rows = tuple(dict.fromkeys(part.strip().upper() for part in value.split(",") if part.strip()))
    return rows or fallback


def _split_ints(value: str | None, fallback: tuple[int, ...], *, maximum: int | None = None) -> tuple[int, ...]:
    if not value:
        return fallback
    parsed: list[int] = []
    for part in value.split(","):
        text = part.strip()
        if not text:
            continue
        try:
            parsed.append(int(text))
        except ValueError:
            continue
    if maximum is not None:
        parsed = [item for item in parsed if 0 < item <= maximum]
    else:
        parsed = [item for item in parsed if item > 0]
    return tuple(dict.fromkeys(parsed)) or fallback


def _positive_int(value: str | None, fallback: int) -> int:
    try:
        return max(int(value), 1) if value is not None else fallback
    except ValueError:
        return fallback


def _path_from_env(repo_root: Path, value: str | None, fallback: str) -> Path:
    raw = value or fallback
    path = Path(raw)
    if not path.is_absolute():
        path = repo_root / path
    return path


@dataclass(frozen=True)
class OperatorRuntimeConfig:
    repo_root: Path = field(default_factory=repo_root_from_here)
    runtime_profile: str = "LOCAL_PAPER"
    data_dir: Path = field(default_factory=lambda: repo_root_from_here() / "data")
    log_dir: Path = field(default_factory=lambda: repo_root_from_here() / "logs")
    operator_state_dir: Path = field(default_factory=lambda: repo_root_from_here() / "state" / "operator")
    operator_session_store_path: Path = field(
        default_factory=lambda: repo_root_from_here() / "state" / "operator" / "sessions.jsonl"
    )
    world_awareness_cache_path: Path = field(
        default_factory=lambda: repo_root_from_here() / "state" / "world_awareness" / "operator_events.jsonl"
    )
    max_session_history: int = 250
    max_event_cache: int = 250
    hosted_mode: bool = False
    paper_runner_mode: str = "LOCAL_POWERSHELL"
    allowed_watchlist: tuple[str, ...] = DEFAULT_ALLOWED_WATCHLIST
    allowed_profile: str = "PAPER_EXPLORATION_ALPHA"
    allowed_durations: tuple[int, ...] = DEFAULT_ALLOWED_DURATIONS
    min_paper_duration_seconds: int = DEFAULT_MIN_PAPER_DURATION_SECONDS
    max_paper_duration_seconds: int = DEFAULT_MAX_PAPER_DURATION_SECONDS
    live_enabled: bool = False
    real_money_enabled: bool = False
    alpaca_credentials_present: bool = False
    world_awareness_credentials_present: bool = False

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        repo_root: Path | None = None,
    ) -> "OperatorRuntimeConfig":
        env_map = os.environ if env is None else env
        root = repo_root or repo_root_from_here()
        profile = str(env_map.get("PK_RUNTIME_PROFILE") or "LOCAL_PAPER").strip().upper()
        if profile not in RUNTIME_PROFILES:
            profile = "LOCAL_PAPER"
        data_dir = _path_from_env(root, env_map.get("PK_DATA_DIR"), "data")
        log_dir = _path_from_env(root, env_map.get("PK_LOG_DIR"), "logs")
        operator_state_dir = _path_from_env(root, env_map.get("PK_OPERATOR_STATE_DIR"), "state/operator")
        session_store = _path_from_env(
            root,
            env_map.get("PK_OPERATOR_SESSION_STORE_PATH") or env_map.get("PK_OPERATOR_DB_PATH"),
            "state/operator/sessions.jsonl",
        )
        world_cache = _path_from_env(
            root,
            env_map.get("PK_WORLD_AWARENESS_CACHE_PATH"),
            "state/world_awareness/operator_events.jsonl",
        )
        max_duration = max(
            min(
                _positive_int(
                    env_map.get("PK_MAX_PAPER_DURATION_SECONDS"),
                    DEFAULT_MAX_PAPER_DURATION_SECONDS,
                ),
                RUNNER_MAX_PAPER_DURATION_SECONDS,
            ),
            DEFAULT_MIN_PAPER_DURATION_SECONDS,
        )
        allowed_durations = _split_ints(
            env_map.get("PK_ALLOWED_DURATIONS"),
            tuple(item for item in DEFAULT_ALLOWED_DURATIONS if item <= max_duration),
            maximum=max_duration,
        )
        return cls(
            repo_root=root,
            runtime_profile=profile,
            data_dir=data_dir,
            log_dir=log_dir,
            operator_state_dir=operator_state_dir,
            operator_session_store_path=session_store,
            world_awareness_cache_path=world_cache,
            max_session_history=_positive_int(env_map.get("PK_MAX_SESSION_HISTORY"), 250),
            max_event_cache=_positive_int(env_map.get("PK_MAX_EVENT_CACHE"), 250),
            hosted_mode=_truthy(env_map.get("PK_HOSTED_MODE")),
            paper_runner_mode=str(env_map.get("PK_PAPER_RUNNER_MODE") or "LOCAL_POWERSHELL").strip().upper(),
            allowed_watchlist=_split_csv(env_map.get("PK_ALLOWED_WATCHLIST"), DEFAULT_ALLOWED_WATCHLIST),
            allowed_profile=str(env_map.get("PK_ALLOWED_PROFILE") or "PAPER_EXPLORATION_ALPHA").strip().upper(),
            allowed_durations=allowed_durations,
            min_paper_duration_seconds=_positive_int(
                env_map.get("PK_MIN_PAPER_DURATION_SECONDS"),
                DEFAULT_MIN_PAPER_DURATION_SECONDS,
            ),
            max_paper_duration_seconds=max_duration,
            live_enabled=_truthy(env_map.get("PK_LIVE_ENABLED")),
            real_money_enabled=_truthy(env_map.get("PK_REAL_MONEY_ENABLED")),
            alpaca_credentials_present=bool(
                str(env_map.get("APCA_API_KEY_ID", "")).strip()
                and str(env_map.get("APCA_API_SECRET_KEY", "")).strip()
            ),
            world_awareness_credentials_present=bool(
                str(env_map.get("APCA_API_KEY_ID", "")).strip()
                and str(env_map.get("APCA_API_SECRET_KEY", "")).strip()
            ),
        )

    def safe_summary(self) -> dict[str, object]:
        return {
            "runtime_profile": self.runtime_profile,
            "hosted_mode": self.hosted_mode,
            "paper_runner_mode": self.paper_runner_mode,
            "repo_root": str(self.repo_root),
            "data_dir": str(self.data_dir),
            "log_dir": str(self.log_dir),
            "operator_state_dir": str(self.operator_state_dir),
            "operator_session_store_path": str(self.operator_session_store_path),
            "world_awareness_cache_path": str(self.world_awareness_cache_path),
            "max_session_history": self.max_session_history,
            "max_event_cache": self.max_event_cache,
            "allowed_watchlist": list(self.allowed_watchlist),
            "allowed_profile": self.allowed_profile,
            "allowed_durations": list(self.allowed_durations),
            "min_paper_duration_seconds": self.min_paper_duration_seconds,
            "max_paper_duration_seconds": self.max_paper_duration_seconds,
            "runner_max_paper_duration_seconds": RUNNER_MAX_PAPER_DURATION_SECONDS,
            "live_enabled": self.live_enabled,
            "real_money_enabled": self.real_money_enabled,
            "alpaca_credentials_present": self.alpaca_credentials_present,
            "world_awareness_credentials_present": self.world_awareness_credentials_present,
        }

    def status(self) -> dict[str, object]:
        warnings: list[str] = []
        if self.live_enabled:
            warnings.append("PK_LIVE_ENABLED_IGNORED_BY_OPERATOR_API")
        if self.real_money_enabled:
            warnings.append("PK_REAL_MONEY_ENABLED_IGNORED_BY_OPERATOR_API")
        if self.runtime_profile == "CLOUD_LIVE_APPROVED":
            warnings.append("CLOUD_LIVE_APPROVED_RESERVED_NOT_OPERATIONAL")
        return {
            "status": "READY_WITH_WARNINGS" if warnings else "READY",
            "runtime_profile": self.runtime_profile,
            "hosted_mode": self.hosted_mode,
            "live_status": "LIVE_LOCKED",
            "real_money_status": "BLOCKED",
            "warnings": warnings,
            "paths_configured": True,
            "secrets_values_exposed": False,
        }
