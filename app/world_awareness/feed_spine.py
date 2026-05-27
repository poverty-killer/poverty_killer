from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable, Mapping

from .config import ExternalFeedProviderConfig, WorldAwarenessConfig
from .enums import DirectionalityHint, ExternalFeedStatus, ExternalFeedType, ExternalVerificationStatus
from .models import ExternalIntelligenceEvent


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def payload_hash(payload: Mapping[str, Any]) -> str:
    material = json.dumps(dict(payload), sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def parse_event_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def listify_symbols(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = [value]
    return [str(item).strip().upper() for item in values if str(item).strip()]


def bounded_float(value: Any, *, default: float = 0.0, low: float = 0.0, high: float = 1.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, parsed))


def direction_from_payload(payload: Mapping[str, Any]) -> DirectionalityHint:
    raw = str(
        payload.get("direction_hint")
        or payload.get("direction")
        or payload.get("sentiment_label")
        or ""
    ).strip().lower()
    if raw in {"bullish", "buy", "positive"}:
        return DirectionalityHint.BULLISH
    if raw in {"bearish", "sell", "negative"}:
        return DirectionalityHint.BEARISH
    if raw in {"neutral", "none"}:
        return DirectionalityHint.NEUTRAL
    if raw in {"mixed"}:
        return DirectionalityHint.MIXED
    sentiment = payload.get("sentiment")
    try:
        sentiment_float = float(sentiment)
    except (TypeError, ValueError):
        return DirectionalityHint.UNKNOWN
    if sentiment_float > 0.2:
        return DirectionalityHint.BULLISH
    if sentiment_float < -0.2:
        return DirectionalityHint.BEARISH
    return DirectionalityHint.NEUTRAL


def verification_from_payload(payload: Mapping[str, Any], *, stale: bool) -> ExternalVerificationStatus:
    if stale:
        return ExternalVerificationStatus.STALE
    raw = str(payload.get("verification_status") or payload.get("verified") or "").strip().lower()
    if raw in {"confirmed", "true", "verified"}:
        return ExternalVerificationStatus.CONFIRMED
    if raw in {"conflicting", "conflict"}:
        return ExternalVerificationStatus.CONFLICTING
    return ExternalVerificationStatus.UNVERIFIED


def normalize_external_event(
    *,
    provider: str,
    feed_type: ExternalFeedType,
    payload: Mapping[str, Any],
    received_time: datetime | None = None,
    stale_after_seconds: int = 3600,
    default_asset_class: str | None = None,
) -> ExternalIntelligenceEvent:
    received = received_time or utc_now()
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)
    event_time = parse_event_time(
        payload.get("event_time")
        or payload.get("created_at")
        or payload.get("updated_at")
        or payload.get("published_at")
        or payload.get("transaction_date")
        or payload.get("filing_date")
        or payload.get("date")
    )
    age_seconds = int(max((received - (event_time or received)).total_seconds(), 0.0))
    stale = bool(age_seconds > int(stale_after_seconds))
    verification_status = verification_from_payload(payload, stale=stale)
    reasons = ["ADVISORY_ONLY", "NO_TRADE_AUTHORITY"]
    if stale:
        reasons.append("FEED_STALE")
    if verification_status == ExternalVerificationStatus.UNVERIFIED:
        reasons.append("UNVERIFIED_EXTERNAL_EVENT")
    if verification_status == ExternalVerificationStatus.CONFLICTING:
        reasons.append("CONFLICTING_EXTERNAL_EVENT")
    raw_hash = payload_hash(payload)
    event_id = str(payload.get("event_id") or payload.get("id") or payload.get("source_id") or "").strip()
    if not event_id:
        event_id = hashlib.sha256(f"{provider}|{feed_type.value}|{raw_hash}".encode("utf-8")).hexdigest()[:24]
    symbols = listify_symbols(payload.get("symbols") or payload.get("symbol") or payload.get("ticker"))
    return ExternalIntelligenceEvent(
        event_id=event_id,
        provider=provider,
        feed_type=feed_type,
        source_url=payload.get("source_url") or payload.get("url"),
        source_id=str(payload.get("source_id") or payload.get("id") or "").strip() or None,
        symbols=symbols,
        asset_class=str(payload.get("asset_class") or default_asset_class or "").strip() or None,
        topic=str(payload.get("topic") or feed_type.value).strip(),
        title=str(payload.get("title") or payload.get("headline") or "").strip(),
        summary=str(payload.get("summary") or payload.get("description") or "").strip(),
        event_time=event_time,
        received_time=received,
        freshness_seconds=age_seconds,
        stale=stale,
        confidence=bounded_float(payload.get("confidence"), default=0.40),
        relevance=bounded_float(payload.get("relevance"), default=0.0),
        sentiment=bounded_float(payload.get("sentiment"), default=0.0, low=-1.0, high=1.0)
        if payload.get("sentiment") is not None
        else None,
        severity=str(payload.get("severity") or "UNKNOWN").strip().upper(),
        direction_hint=direction_from_payload(payload),
        verification_status=verification_status,
        advisory_only=True,
        decisionframe_eligible=False,
        reason_codes=reasons,
        raw_payload_hash=raw_hash,
    )


@dataclass(frozen=True)
class ProviderRegistryEntry:
    provider_name: str
    feed_type: ExternalFeedType
    enabled: bool
    credential_env_keys: tuple[str, ...] = field(repr=False)
    credential_present: bool
    status: ExternalFeedStatus
    stale_after_seconds: int
    advisory_only: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ProviderRuntimeSnapshot:
    provider_name: str
    feed_type: ExternalFeedType
    enabled: bool
    status: ExternalFeedStatus
    advisory_only: bool
    last_poll_time: datetime | None = None
    latest_event_time: datetime | None = None
    event_count: int = 0
    stale_count: int = 0
    error_count: int = 0
    last_error_type: str | None = None
    duplicate_event_ignored_count: int = 0
    reason_codes: tuple[str, ...] = ("ADVISORY_ONLY_NO_TRADE_AUTHORITY",)


@dataclass
class WorldAwarenessEventCache:
    """In-memory advisory event cache.

    The cache is intentionally process-local and replaceable by a future
    persistent store. It never polls providers by itself and never grants trade
    authority.
    """

    max_events: int = 250
    _events: OrderedDict[str, ExternalIntelligenceEvent] = field(default_factory=OrderedDict)
    _provider_snapshots: dict[str, ProviderRuntimeSnapshot] = field(default_factory=dict)
    duplicate_event_ignored_count: int = 0

    @staticmethod
    def event_key(event: ExternalIntelligenceEvent) -> str:
        if event.source_id:
            return f"{event.provider}:source:{event.source_id}"
        return f"{event.provider}:event:{event.event_id}"

    def upsert(self, events: Iterable[ExternalIntelligenceEvent]) -> tuple[int, int]:
        added = 0
        duplicates = 0
        for event in events:
            key = self.event_key(event)
            if key in self._events:
                duplicates += 1
                self.duplicate_event_ignored_count += 1
                continue
            self._events[key] = event
            added += 1
        while len(self._events) > self.max_events:
            self._events.popitem(last=False)
        return added, duplicates

    def mark_provider(self, snapshot: ProviderRuntimeSnapshot) -> None:
        self._provider_snapshots[snapshot.provider_name] = snapshot

    def events(self, *, limit: int = 25, provider: str | None = None) -> list[ExternalIntelligenceEvent]:
        rows = list(self._events.values())
        if provider:
            rows = [event for event in rows if event.provider == provider]
        rows.sort(key=lambda event: event.event_time or event.received_time, reverse=True)
        return rows[: max(int(limit), 0)]

    def provider_snapshots(self) -> list[ProviderRuntimeSnapshot]:
        return list(self._provider_snapshots.values())

    def summary(
        self,
        config: WorldAwarenessConfig | None = None,
        *,
        env: Mapping[str, str] | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        return world_awareness_summary(
            config,
            env=env,
            events=self.events(limit=limit),
            provider_runtime=self.provider_snapshots(),
            duplicate_event_ignored_count=self.duplicate_event_ignored_count,
        )


def provider_entry(
    config: ExternalFeedProviderConfig,
    *,
    feed_type: ExternalFeedType,
    env: Mapping[str, str] | None = None,
) -> ProviderRegistryEntry:
    env_values = env or {}
    credential_keys = tuple(config.credential_env_keys)
    credential_present = all(bool(str(env_values.get(key, "")).strip()) for key in credential_keys) if credential_keys else True
    if not config.enabled:
        status = ExternalFeedStatus.FEED_DISABLED
        reasons = ("FEED_DISABLED_BY_CONFIG",)
    elif not credential_present:
        status = ExternalFeedStatus.CREDENTIAL_MISSING
        reasons = ("CREDENTIAL_MISSING",)
    else:
        status = ExternalFeedStatus.FEED_READY
        reasons = ("READ_ONLY_ADVISORY_FEED_READY",)
    return ProviderRegistryEntry(
        provider_name=config.provider_name,
        feed_type=feed_type,
        enabled=bool(config.enabled),
        credential_env_keys=credential_keys,
        credential_present=bool(credential_present),
        status=status,
        stale_after_seconds=int(config.stale_after_seconds),
        advisory_only=bool(config.advisory_only),
        reason_codes=reasons,
    )


def build_provider_registry(
    config: WorldAwarenessConfig | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> list[ProviderRegistryEntry]:
    cfg = config or WorldAwarenessConfig()
    return [
        provider_entry(cfg.alpaca_news, feed_type=ExternalFeedType.NEWS, env=env),
        provider_entry(cfg.sec_insider_filings, feed_type=ExternalFeedType.SEC_FILING, env=env),
        provider_entry(cfg.finnhub_insider, feed_type=ExternalFeedType.INSIDER_TRANSACTION, env=env),
        provider_entry(cfg.economic_calendar, feed_type=ExternalFeedType.ECONOMIC_CALENDAR, env=env),
        provider_entry(cfg.crypto_onchain, feed_type=ExternalFeedType.ONCHAIN_EVENT, env=env),
        provider_entry(cfg.social_sentiment, feed_type=ExternalFeedType.SOCIAL_SENTIMENT, env=env),
    ]


def world_awareness_summary(
    config: WorldAwarenessConfig | None = None,
    *,
    env: Mapping[str, str] | None = None,
    events: list[ExternalIntelligenceEvent] | None = None,
    provider_runtime: Iterable[ProviderRuntimeSnapshot] | None = None,
    duplicate_event_ignored_count: int = 0,
) -> dict[str, Any]:
    registry = build_provider_registry(config, env=env)
    event_rows = events or []
    runtime_by_provider = {snapshot.provider_name: snapshot for snapshot in provider_runtime or []}

    def provider_row(entry: ProviderRegistryEntry) -> dict[str, Any]:
        runtime = runtime_by_provider.get(entry.provider_name)
        status = runtime.status if runtime else entry.status
        reason_codes = runtime.reason_codes if runtime else entry.reason_codes
        return {
            "provider": entry.provider_name,
            "feed_type": entry.feed_type.value,
            "enabled": entry.enabled,
            "status": status.value,
            "credential_present": entry.credential_present,
            "advisory_only": entry.advisory_only,
            "last_poll_time": runtime.last_poll_time.isoformat() if runtime and runtime.last_poll_time else None,
            "latest_event_time": runtime.latest_event_time.isoformat() if runtime and runtime.latest_event_time else None,
            "event_count": runtime.event_count if runtime else 0,
            "stale_count": runtime.stale_count if runtime else 0,
            "error_count": runtime.error_count if runtime else 0,
            "last_error_type": runtime.last_error_type if runtime else None,
            "duplicate_event_ignored_count": runtime.duplicate_event_ignored_count if runtime else 0,
            "reason_codes": reason_codes,
        }

    return {
        "module_name": "WorldAwareness",
        "authority_class": "ADVISORY",
        "advisory_only": True,
        "direct_trade_authority": False,
        "providers": [
            provider_row(entry)
            for entry in registry
        ],
        "event_count": len(event_rows),
        "advisory_event_count": len(event_rows),
        "stale_event_count": sum(1 for event in event_rows if event.stale),
        "high_relevance_event_count": sum(1 for event in event_rows if event.relevance >= 0.75 and not event.stale),
        "decisionframe_eligible_count": sum(1 for event in event_rows if event.decisionframe_eligible),
        "duplicate_event_ignored_count": int(duplicate_event_ignored_count),
        "events": [event.model_dump(mode="json") for event in event_rows[:25]],
        "reason_codes": ("ADVISORY_ONLY_NO_TRADE_AUTHORITY",),
    }
