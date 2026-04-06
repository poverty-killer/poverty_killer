"""
test_models
Contract tests for governed model fields.

Covers: StrategySignal.exchange_ts_ns required-field enforcement.
"""

import pytest
from pydantic import ValidationError

from app.models.signals import StrategySignal


_VALID_KWARGS = dict(
    strategy="GAMMA_FRONT",
    symbol="SPY",
    side="buy",
    confidence=0.85,
    quantity=10.0,
    exchange_ts_ns=1_000_000_000,
)


class TestStrategySignalTimestampContract:

    def test_valid_construction_with_ts(self):
        """StrategySignal constructs correctly when exchange_ts_ns is supplied."""
        sig = StrategySignal(**_VALID_KWARGS)
        assert sig.exchange_ts_ns == 1_000_000_000

    def test_missing_exchange_ts_ns_raises(self):
        """exchange_ts_ns is required — omitting it must raise ValidationError."""
        kwargs = {k: v for k, v in _VALID_KWARGS.items() if k != "exchange_ts_ns"}
        with pytest.raises(ValidationError):
            StrategySignal(**kwargs)

    def test_exchange_ts_sec_property(self):
        """exchange_ts_sec must convert nanoseconds to seconds correctly."""
        sig = StrategySignal(**_VALID_KWARGS)
        assert sig.exchange_ts_sec == pytest.approx(1.0)

    def test_zero_ts_ns_accepted(self):
        """Zero is a valid integer timestamp (replay-safe: epoch start)."""
        sig = StrategySignal(**{**_VALID_KWARGS, "exchange_ts_ns": 0})
        assert sig.exchange_ts_ns == 0

    def test_negative_ts_ns_accepted(self):
        """Negative int is accepted — field type is int, no ge constraint."""
        sig = StrategySignal(**{**_VALID_KWARGS, "exchange_ts_ns": -1})
        assert sig.exchange_ts_ns == -1
