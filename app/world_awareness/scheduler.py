from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import WorldAwarenessConfig
from .enums import SourceFamily


@dataclass(frozen=True)
class ScheduledSourceTask:
    source_family: SourceFamily
    next_run_utc: datetime
    interval_seconds: int
    enabled: bool


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _source_interval(config: WorldAwarenessConfig, source_family: SourceFamily) -> tuple[bool, int]:
    mapping = {
        SourceFamily.SEC_EDGAR: config.sec_edgar,
        SourceFamily.OPENINSIDER: config.openinsider,
        SourceFamily.CAPITOL_TRADES: config.capitol_trades,
        SourceFamily.QUIVER_FREE: config.quiver_free,
        SourceFamily.OFFICIAL_ISSUER_RELEASES: config.official_releases,
        SourceFamily.OFFICIAL_CALENDARS: config.official_calendars,
        SourceFamily.OFFICIAL_MACRO_RELEASES: config.official_calendars,
    }

    source_cfg = mapping[source_family]
    return source_cfg.enabled, source_cfg.min_poll_interval_seconds


def build_schedule(config: WorldAwarenessConfig) -> list[ScheduledSourceTask]:
    now = _utc_now()
    tasks: list[ScheduledSourceTask] = []

    for source_family in SourceFamily:
        enabled, interval_seconds = _source_interval(config, source_family)
        tasks.append(
            ScheduledSourceTask(
                source_family=source_family,
                next_run_utc=now + timedelta(seconds=interval_seconds),
                interval_seconds=interval_seconds,
                enabled=enabled,
            )
        )

    return tasks


def due_tasks(tasks: list[ScheduledSourceTask], as_of_utc: datetime | None = None) -> list[ScheduledSourceTask]:
    current = as_of_utc or _utc_now()
    return [task for task in tasks if task.enabled and task.next_run_utc <= current]
