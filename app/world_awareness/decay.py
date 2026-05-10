from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .enums import DecayProfileName


def freshness_horizon(profile: DecayProfileName) -> timedelta:
    mapping = {
        DecayProfileName.REGULATORY_FILING_FRESH: timedelta(hours=18),
        DecayProfileName.INSIDER_DISCLOSURE_DELAYED: timedelta(days=3),
        DecayProfileName.POLITICAL_DISCLOSURE_DELAYED: timedelta(days=5),
        DecayProfileName.ISSUER_RELEASE_WINDOWED: timedelta(hours=12),
        DecayProfileName.CALENDAR_EVENT_WINDOWED: timedelta(hours=8),
        DecayProfileName.MACRO_RELEASE_WINDOWED: timedelta(hours=6),
        DecayProfileName.GENERIC_CONTEXT: timedelta(hours=24),
    }
    return mapping[profile]


def compute_fresh_until(
    discovery_timestamp_utc: datetime,
    profile: DecayProfileName,
) -> datetime:
    return discovery_timestamp_utc + freshness_horizon(profile)


def decay_weight(
    now_utc: datetime,
    fresh_until_utc: datetime | None,
    discovery_timestamp_utc: datetime,
) -> float:
    """
    Returns a simple bounded freshness weight.

    Rules:
    - if fresh_until is missing, use a soft fallback based on age
    - before fresh_until: 1.0
    - after fresh_until: linearly decays toward 0.0 over same horizon length
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    if discovery_timestamp_utc.tzinfo is None:
        discovery_timestamp_utc = discovery_timestamp_utc.replace(tzinfo=timezone.utc)

    if fresh_until_utc is None:
        age_seconds = max((now_utc - discovery_timestamp_utc).total_seconds(), 0.0)
        if age_seconds <= 3600:
            return 1.0
        if age_seconds >= 86400:
            return 0.0
        return max(0.0, 1.0 - ((age_seconds - 3600) / (86400 - 3600)))

    if fresh_until_utc.tzinfo is None:
        fresh_until_utc = fresh_until_utc.replace(tzinfo=timezone.utc)

    if now_utc <= fresh_until_utc:
        return 1.0

    horizon = max((fresh_until_utc - discovery_timestamp_utc).total_seconds(), 1.0)
    stale_age = (now_utc - fresh_until_utc).total_seconds()
    weight = 1.0 - (stale_age / horizon)
    return max(0.0, min(1.0, weight))
