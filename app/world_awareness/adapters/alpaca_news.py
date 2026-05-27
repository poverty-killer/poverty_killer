from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from typing import Any, Mapping

from ..config import ExternalFeedProviderConfig, WorldAwarenessConfig
from ..enums import ExternalFeedStatus, ExternalFeedType
from ..feed_spine import (
    ProviderRegistryEntry,
    ProviderRuntimeSnapshot,
    normalize_external_event,
    provider_entry,
    utc_now,
)
from ..models import ExternalIntelligenceEvent


class AlpacaNewsRateLimitError(RuntimeError):
    pass


class AlpacaNewsUnavailableError(RuntimeError):
    pass


@dataclass
class AlpacaNewsHttpClient:
    """Minimal read-only Alpaca News HTTP client.

    This client is only constructed when explicitly configured credentials are
    supplied. Tests inject fake clients and never use this network path.
    """

    key_id: str
    secret_key: str
    endpoint: str = "https://data.alpaca.markets/v1beta1/news"
    timeout_seconds: int = 20

    def get_news(self, **params: Any) -> Mapping[str, Any]:
        clean_params = {key: value for key, value in params.items() if value not in (None, "", [], ())}
        url = self.endpoint
        if clean_params:
            url = f"{url}?{urlencode(clean_params, doseq=True)}"
        request = Request(
            url,
            method="GET",
            headers={
                "APCA-API-KEY-ID": self.key_id,
                "APCA-API-SECRET-KEY": self.secret_key,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429:
                raise AlpacaNewsRateLimitError("ALPACA_NEWS_RATE_LIMITED") from exc
            raise AlpacaNewsUnavailableError(f"ALPACA_NEWS_HTTP_{exc.code}") from exc
        except (OSError, URLError, TimeoutError) as exc:
            raise AlpacaNewsUnavailableError(type(exc).__name__) from exc


@dataclass(frozen=True)
class AlpacaNewsPollResult:
    provider: str
    status: ExternalFeedStatus
    events: tuple[ExternalIntelligenceEvent, ...]
    provider_snapshot: ProviderRuntimeSnapshot
    raw_payload_count: int = 0
    error_type: str | None = None
    reason_codes: tuple[str, ...] = ("ADVISORY_ONLY_NO_TRADE_AUTHORITY",)


@dataclass
class AlpacaNewsAdapter:
    """Read-only Alpaca News lane.

    The default adapter is disabled/config-gated. Polling requires explicit
    provider enablement plus credentials and remains advisory only.
    """

    config: ExternalFeedProviderConfig = field(default_factory=lambda: WorldAwarenessConfig().alpaca_news)
    client: Any | None = None

    def status(self, *, env: Mapping[str, str] | None = None) -> ProviderRegistryEntry:
        return provider_entry(self.config, feed_type=ExternalFeedType.NEWS, env=env)

    def _client_from_env(self, env: Mapping[str, str] | None) -> AlpacaNewsHttpClient | None:
        env_values = env or {}
        keys = self.config.credential_env_keys
        if len(keys) < 2:
            return None
        key_id = str(env_values.get(keys[0], "")).strip()
        secret_key = str(env_values.get(keys[1], "")).strip()
        if not key_id or not secret_key:
            return None
        return AlpacaNewsHttpClient(
            key_id=key_id,
            secret_key=secret_key,
            timeout_seconds=self.config.timeout_seconds,
        )

    @staticmethod
    def _extract_payloads(response: Any) -> list[Mapping[str, Any]]:
        if response is None:
            return []
        if isinstance(response, list):
            return [item for item in response if isinstance(item, Mapping)]
        if isinstance(response, Mapping):
            for key in ("news", "items", "data", "results"):
                value = response.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, Mapping)]
            if response.get("id") or response.get("headline") or response.get("title"):
                return [response]
        return []

    def fetch(
        self,
        *,
        env: Mapping[str, str] | None = None,
        symbols: list[str] | tuple[str, ...] | None = None,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
        limit: int | None = None,
    ) -> list[Mapping[str, Any]]:
        entry = self.status(env=env)
        if entry.status in {ExternalFeedStatus.FEED_DISABLED, ExternalFeedStatus.CREDENTIAL_MISSING}:
            return []
        client = self.client or self._client_from_env(env)
        if client is None:
            return []
        params: dict[str, Any] = {
            "symbols": ",".join(symbols) if symbols else None,
            "start": start.isoformat() if isinstance(start, datetime) else start,
            "end": end.isoformat() if isinstance(end, datetime) else end,
            "limit": min(int(limit or self.config.max_items_per_fetch), int(self.config.max_items_per_fetch)),
        }
        response = client.get_news(**params) if hasattr(client, "get_news") else client(**params)
        return self._extract_payloads(response)

    def normalize_payload(
        self,
        payload: Mapping[str, Any],
        *,
        received_time=None,
    ) -> ExternalIntelligenceEvent:
        return normalize_external_event(
            provider=self.config.provider_name,
            feed_type=ExternalFeedType.NEWS,
            payload=payload,
            received_time=received_time,
            stale_after_seconds=self.config.stale_after_seconds,
        )

    def fetch_and_normalize(
        self,
        *,
        env: Mapping[str, str] | None = None,
        symbols: list[str] | tuple[str, ...] | None = None,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
        limit: int | None = None,
        received_time: datetime | None = None,
    ) -> list[ExternalIntelligenceEvent]:
        return [
            self.normalize_payload(payload, received_time=received_time)
            for payload in self.fetch(env=env, symbols=symbols, start=start, end=end, limit=limit)
        ]

    def poll(
        self,
        *,
        env: Mapping[str, str] | None = None,
        symbols: list[str] | tuple[str, ...] | None = None,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
        limit: int | None = None,
        received_time: datetime | None = None,
    ) -> AlpacaNewsPollResult:
        entry = self.status(env=env)
        now = received_time or utc_now()
        if entry.status in {ExternalFeedStatus.FEED_DISABLED, ExternalFeedStatus.CREDENTIAL_MISSING}:
            snapshot = ProviderRuntimeSnapshot(
                provider_name=entry.provider_name,
                feed_type=entry.feed_type,
                enabled=entry.enabled,
                status=entry.status,
                advisory_only=entry.advisory_only,
                last_poll_time=None,
                reason_codes=entry.reason_codes,
            )
            return AlpacaNewsPollResult(entry.provider_name, entry.status, (), snapshot, reason_codes=entry.reason_codes)
        try:
            payloads = self.fetch(env=env, symbols=symbols, start=start, end=end, limit=limit)
            events = tuple(self.normalize_payload(payload, received_time=now) for payload in payloads)
            stale_count = sum(1 for event in events if event.stale)
            latest_event_time = max((event.event_time or event.received_time for event in events), default=None)
            status = ExternalFeedStatus.FEED_STALE if events and stale_count == len(events) else ExternalFeedStatus.FEED_READY
            reasons = ("READ_ONLY_ALPACA_NEWS_POLLED", "ADVISORY_ONLY_NO_TRADE_AUTHORITY")
            snapshot = ProviderRuntimeSnapshot(
                provider_name=entry.provider_name,
                feed_type=entry.feed_type,
                enabled=entry.enabled,
                status=status,
                advisory_only=entry.advisory_only,
                last_poll_time=now,
                latest_event_time=latest_event_time,
                event_count=len(events),
                stale_count=stale_count,
                reason_codes=reasons,
            )
            return AlpacaNewsPollResult(entry.provider_name, status, events, snapshot, len(payloads), reason_codes=reasons)
        except AlpacaNewsRateLimitError as exc:
            return self._error_result(entry, now, ExternalFeedStatus.FEED_RATE_LIMITED, type(exc).__name__, "ALPACA_NEWS_RATE_LIMITED")
        except AlpacaNewsUnavailableError as exc:
            return self._error_result(entry, now, ExternalFeedStatus.FEED_UNAVAILABLE, type(exc).__name__, "ALPACA_NEWS_UNAVAILABLE")
        except (OSError, TimeoutError) as exc:
            return self._error_result(entry, now, ExternalFeedStatus.FEED_UNAVAILABLE, type(exc).__name__, "ALPACA_NEWS_UNAVAILABLE")
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            response = getattr(exc, "response", None)
            response_status = getattr(response, "status_code", None)
            if status_code == 429 or response_status == 429:
                return self._error_result(entry, now, ExternalFeedStatus.FEED_RATE_LIMITED, type(exc).__name__, "ALPACA_NEWS_RATE_LIMITED")
            return self._error_result(entry, now, ExternalFeedStatus.FEED_ERROR, type(exc).__name__, "ALPACA_NEWS_ERROR")

    def _error_result(
        self,
        entry: ProviderRegistryEntry,
        now: datetime,
        status: ExternalFeedStatus,
        error_type: str,
        reason_code: str,
    ) -> AlpacaNewsPollResult:
        reasons = (reason_code, "ADVISORY_ONLY_NO_TRADE_AUTHORITY")
        snapshot = ProviderRuntimeSnapshot(
            provider_name=entry.provider_name,
            feed_type=entry.feed_type,
            enabled=entry.enabled,
            status=status,
            advisory_only=entry.advisory_only,
            last_poll_time=now,
            error_count=1,
            last_error_type=error_type,
            reason_codes=reasons,
        )
        return AlpacaNewsPollResult(entry.provider_name, status, (), snapshot, 0, error_type, reasons)
