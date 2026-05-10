from datetime import datetime, timedelta, timezone

from app.world_awareness.decay import compute_fresh_until, decay_weight, freshness_horizon
from app.world_awareness.enums import DecayProfileName


def test_freshness_horizon_for_regulatory_profile_is_positive():
    horizon = freshness_horizon(DecayProfileName.REGULATORY_FILING_FRESH)
    assert horizon.total_seconds() > 0


def test_compute_fresh_until_advances_time():
    discovered = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    fresh_until = compute_fresh_until(discovered, DecayProfileName.CALENDAR_EVENT_WINDOWED)
    assert fresh_until > discovered


def test_decay_weight_is_full_before_expiry():
    discovered = datetime.now(timezone.utc)
    fresh_until = discovered + timedelta(hours=2)

    weight = decay_weight(
        now_utc=discovered + timedelta(minutes=30),
        fresh_until_utc=fresh_until,
        discovery_timestamp_utc=discovered,
    )

    assert weight == 1.0


def test_decay_weight_falls_after_expiry():
    discovered = datetime.now(timezone.utc)
    fresh_until = discovered + timedelta(hours=1)

    weight = decay_weight(
        now_utc=discovered + timedelta(hours=2),
        fresh_until_utc=fresh_until,
        discovery_timestamp_utc=discovered,
    )

    assert 0.0 <= weight < 1.0
