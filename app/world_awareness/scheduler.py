from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .config import WorldAwarenessConfig
from .enums import ExternalFeedStatus, SourceFamily
from .feed_spine import ProviderRuntimeSnapshot, WorldAwarenessEventCache, build_provider_registry
from .adapters.alpaca_news import AlpacaNewsAdapter


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


@dataclass(frozen=True)
class ProviderPollState:
    provider_name: str
    enabled: bool
    status: ExternalFeedStatus
    next_poll_utc: datetime | None
    min_poll_interval_seconds: int
    backoff_seconds: int
    last_poll_utc: datetime | None = None
    last_success_utc: datetime | None = None
    latest_event_utc: datetime | None = None
    poll_count: int = 0
    error_count: int = 0
    consecutive_error_count: int = 0
    last_error_type: str | None = None
    last_added_count: int = 0
    last_duplicate_count: int = 0
    stale_count: int = 0
    reason_codes: tuple[str, ...] = ()

    def to_dict(self, *, as_of_utc: datetime | None = None) -> dict[str, Any]:
        current = as_of_utc or _utc_now()
        due = bool(self.enabled and self.next_poll_utc is not None and self.next_poll_utc <= current)
        return {
            "provider": self.provider_name,
            "enabled": self.enabled,
            "status": self.status.value,
            "next_poll_time": self.next_poll_utc.isoformat() if self.next_poll_utc else None,
            "next_poll_due": due,
            "min_poll_interval_seconds": self.min_poll_interval_seconds,
            "backoff_seconds": self.backoff_seconds,
            "last_poll_time": self.last_poll_utc.isoformat() if self.last_poll_utc else None,
            "last_success_time": self.last_success_utc.isoformat() if self.last_success_utc else None,
            "latest_event_time": self.latest_event_utc.isoformat() if self.latest_event_utc else None,
            "poll_count": self.poll_count,
            "error_count": self.error_count,
            "consecutive_error_count": self.consecutive_error_count,
            "last_error_type": self.last_error_type,
            "last_added_count": self.last_added_count,
            "last_duplicate_count": self.last_duplicate_count,
            "stale_count": self.stale_count,
            "reason_codes": self.reason_codes,
        }


@dataclass(frozen=True)
class ProviderDueDecision:
    provider_name: str
    due: bool
    allowed: bool
    reason_code: str
    next_poll_utc: datetime | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "due": self.due,
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "next_poll_time": self.next_poll_utc.isoformat() if self.next_poll_utc else None,
        }


@dataclass
class WorldAwarenessProviderRuntime:
    """Manual read-only provider polling runtime.

    This runtime does not start background polling. It only polls when an
    operator intent calls `poll_provider`, and provider adapters remain
    advisory-only.
    """

    config: WorldAwarenessConfig = field(default_factory=WorldAwarenessConfig)
    cache: WorldAwarenessEventCache = field(default_factory=WorldAwarenessEventCache)
    env: Mapping[str, str] = field(default_factory=dict)
    adapters: dict[str, Any] = field(default_factory=dict)
    _states: dict[str, ProviderPollState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.adapters:
            self.adapters = {
                self.config.alpaca_news.provider_name: AlpacaNewsAdapter(config=self.config.alpaca_news),
            }
        now = _utc_now()
        for entry in build_provider_registry(self.config, env=self.env):
            provider_cfg = self._provider_config(entry.provider_name)
            next_poll = now if entry.status == ExternalFeedStatus.FEED_READY else None
            self._states[entry.provider_name] = ProviderPollState(
                provider_name=entry.provider_name,
                enabled=entry.enabled,
                status=entry.status,
                next_poll_utc=next_poll,
                min_poll_interval_seconds=provider_cfg.min_poll_interval_seconds,
                backoff_seconds=getattr(provider_cfg, "backoff_seconds", provider_cfg.min_poll_interval_seconds),
                reason_codes=entry.reason_codes,
            )
            self.cache.mark_provider(
                ProviderRuntimeSnapshot(
                    provider_name=entry.provider_name,
                    feed_type=entry.feed_type,
                    enabled=entry.enabled,
                    status=entry.status,
                    advisory_only=entry.advisory_only,
                    reason_codes=entry.reason_codes,
                )
            )

    def _provider_config(self, provider_name: str):
        for candidate in (
            self.config.alpaca_news,
            self.config.sec_insider_filings,
            self.config.finnhub_insider,
            self.config.economic_calendar,
            self.config.crypto_onchain,
            self.config.social_sentiment,
        ):
            if candidate.provider_name == provider_name:
                return candidate
        raise KeyError(provider_name)

    def status_snapshot(self, *, as_of_utc: datetime | None = None) -> dict[str, Any]:
        current = as_of_utc or _utc_now()
        return {
            "runtime": "world-awareness-provider-runtime-v1",
            "auto_start": False,
            "manual_poll_only": True,
            "provider_count": len(self._states),
            "provider_polling_active": False,
            "providers": [state.to_dict(as_of_utc=current) for state in self._states.values()],
            "due_providers": [
                state.provider_name
                for state in self._states.values()
                if state.enabled and state.next_poll_utc is not None and state.next_poll_utc <= current
            ],
            "cache": {
                "event_count": len(self.cache.events(limit=self.cache.max_events)),
                "duplicate_event_ignored_count": self.cache.duplicate_event_ignored_count,
            },
            "feed_can_trade": False,
            "decisionframe_score_impact": 0.0,
            "reason_codes": ("MANUAL_READ_ONLY_POLLING_ONLY", "ADVISORY_ONLY_NO_TRADE_AUTHORITY"),
        }

    def due_decision(
        self,
        provider_name: str,
        *,
        as_of_utc: datetime | None = None,
        force: bool = False,
    ) -> ProviderDueDecision:
        current = as_of_utc or _utc_now()
        state = self._states.get(provider_name)
        if state is None:
            return ProviderDueDecision(provider_name, False, False, "UNKNOWN_PROVIDER", None)
        if not state.enabled:
            return ProviderDueDecision(provider_name, False, False, "FEED_DISABLED", state.next_poll_utc)
        if state.status == ExternalFeedStatus.CREDENTIAL_MISSING:
            return ProviderDueDecision(provider_name, False, False, "CREDENTIAL_MISSING", state.next_poll_utc)
        if force:
            return ProviderDueDecision(provider_name, True, True, "FORCED_MANUAL_READ_ONLY_POLL", state.next_poll_utc)
        if state.next_poll_utc is None:
            return ProviderDueDecision(provider_name, False, False, "NEXT_POLL_NOT_SCHEDULED", None)
        if state.next_poll_utc > current:
            return ProviderDueDecision(provider_name, False, False, "PROVIDER_NOT_DUE", state.next_poll_utc)
        return ProviderDueDecision(provider_name, True, True, "PROVIDER_DUE", state.next_poll_utc)

    def poll_provider(
        self,
        provider_name: str,
        *,
        as_of_utc: datetime | None = None,
        force: bool = False,
        symbols: list[str] | tuple[str, ...] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        current = as_of_utc or _utc_now()
        decision = self.due_decision(provider_name, as_of_utc=current, force=force)
        if not decision.allowed:
            return {
                "intent": "world_awareness_manual_poll",
                "allowed": False,
                "status": "REFUSED",
                "reason_code": decision.reason_code,
                "provider": provider_name,
                "broker_call_occurred": False,
                "trade_authority": False,
                "decisionframe_score_impact": 0.0,
                "due": decision.to_dict(),
            }
        adapter = self.adapters.get(provider_name)
        if adapter is None:
            return {
                "intent": "world_awareness_manual_poll",
                "allowed": False,
                "status": "REFUSED",
                "reason_code": "PROVIDER_ADAPTER_MISSING",
                "provider": provider_name,
                "broker_call_occurred": False,
                "trade_authority": False,
                "decisionframe_score_impact": 0.0,
                "due": decision.to_dict(),
            }
        previous = self._states[provider_name]
        result = adapter.poll(
            env=self.env,
            symbols=symbols,
            limit=limit,
            received_time=current,
        )
        added, duplicates = self.cache.upsert(result.events)
        self.cache.mark_provider(result.provider_snapshot)
        success = result.status in {ExternalFeedStatus.FEED_READY, ExternalFeedStatus.FEED_STALE}
        interval_seconds = previous.min_poll_interval_seconds if success else previous.backoff_seconds
        next_poll = current + timedelta(seconds=interval_seconds)
        consecutive_errors = 0 if success else previous.consecutive_error_count + 1
        error_count = previous.error_count + (0 if success else 1)
        latest_event_time = result.provider_snapshot.latest_event_time or previous.latest_event_utc
        self._states[provider_name] = ProviderPollState(
            provider_name=provider_name,
            enabled=previous.enabled,
            status=result.status,
            next_poll_utc=next_poll,
            min_poll_interval_seconds=previous.min_poll_interval_seconds,
            backoff_seconds=previous.backoff_seconds,
            last_poll_utc=current,
            last_success_utc=current if success else previous.last_success_utc,
            latest_event_utc=latest_event_time,
            poll_count=previous.poll_count + 1,
            error_count=error_count,
            consecutive_error_count=consecutive_errors,
            last_error_type=result.error_type,
            last_added_count=added,
            last_duplicate_count=duplicates,
            stale_count=result.provider_snapshot.stale_count,
            reason_codes=result.reason_codes,
        )
        return {
            "intent": "world_awareness_manual_poll",
            "allowed": True,
            "status": "POLL_COMPLETE" if success else "POLL_FAILED_SOFT",
            "reason_code": "READ_ONLY_POLL_COMPLETE" if success else "READ_ONLY_POLL_FAILED_SOFT",
            "provider": provider_name,
            "provider_status": result.status.value,
            "events_seen": len(result.events),
            "events_added": added,
            "duplicates_ignored": duplicates,
            "next_poll_time": next_poll.isoformat(),
            "broker_call_occurred": False,
            "trade_authority": False,
            "decisionframe_score_impact": 0.0,
            "cache_event_count": len(self.cache.events(limit=self.cache.max_events)),
            "reason_codes": result.reason_codes,
        }
