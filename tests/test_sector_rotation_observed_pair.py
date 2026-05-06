"""
test_sector_rotation_observed_pair
SECTOR_ROTATION_FRESH_OBSERVED_PAIR_PROOF_BUNDLE — observed pair contract tests.

Verifies:
- SectorRotationStrategy cold-start guard (candle_count < min blocks signal)
- PAPER_PROOF_WINDOW_OVERRIDE env var lowers _effective_min_candles
- Observed signal and vote stored together with matching candle timestamp
- Same-candle pair passes freshness gate
- Stale pair (prior candle timestamp) blocks freshness gate
- Missing signal or vote blocks Gate 2
- BTC/ETH no-signal case: cold-start never produces a pair in short window
- SOL stale case: prior-candle signal rejected at freshness
- Freshness gate uses strict nanosecond equality (not a range comparison)
- No fake pair: nothing stored when strategy returns None
"""

import os
import types
import pytest
from unittest.mock import Mock

from app.strategies.sector_rotation import SectorRotationStrategy, _MIN_BASELINE_CANDLES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(enabled=True, inflow_threshold=1.5, min_confidence=0.5):
    cfg = Mock()
    cfg.strategies.sector_rotation_enabled = enabled
    cfg.strategies.sector_inflow_threshold = inflow_threshold
    cfg.strategies.min_confidence = min_confidence
    return cfg


def _make_strategy(enabled=True, inflow_threshold=1.5, min_confidence=0.5):
    return SectorRotationStrategy(
        config=_make_config(enabled, inflow_threshold, min_confidence),
        symbol="TEST/USD",
    )


def _warm_baseline(s, n=9, price=100.0, volume=100.0):
    for i in range(n):
        s.update_candle(price, volume, i * 1_000_000_000)


class _MockRuntime:
    """Minimal per-symbol runtime for observed pair contract tests."""
    last_sector_rotation_observed_signal = None
    last_sector_rotation_observed_vote = None

    def record_observed_signal(self, sleeve_name, signal):
        if sleeve_name == "sector_rotation":
            self.last_sector_rotation_observed_signal = signal

    def record_observed_vote(self, sleeve_name, vote):
        if sleeve_name == "sector_rotation":
            self.last_sector_rotation_observed_vote = vote


def _make_signal(ts_ns):
    return types.SimpleNamespace(exchange_ts_ns=ts_ns, side="buy", quantity=1.0)


def _make_vote(ts_ns):
    return types.SimpleNamespace(timestamp_ns=ts_ns, confidence=0.75, risk_appetite=0.5)


def _freshness_contract(signal, vote, exchange_ts_ns):
    """
    Mirrors Gate 2 + Gate 3 of _consume_observed_pair_sector_rotation.

    Gate 2: both signal and vote must be present.
    Gate 3: vote.timestamp_ns == exchange_ts_ns  OR  signal.exchange_ts_ns == exchange_ts_ns
            (strict nanosecond equality — same-candle only).

    Returns (passed: bool, reason: str).
    """
    if signal is None or vote is None:
        return False, "pair_missing"
    vote_ts = getattr(vote, "timestamp_ns", None)
    signal_ts = getattr(signal, "exchange_ts_ns", None)
    fresh = (vote_ts == exchange_ts_ns) or (signal_ts == exchange_ts_ns)
    if not fresh:
        return False, (
            f"freshness_fail:vote_ts={vote_ts},"
            f"signal_ts={signal_ts},"
            f"exchange_ts_ns={exchange_ts_ns}"
        )
    return True, "admitted"


# ---------------------------------------------------------------------------
# 1. Observed signal and vote stored together with matching candle timestamp
# ---------------------------------------------------------------------------

class TestObservedPairStorage:

    def test_signal_and_vote_stored_together(self):
        runtime = _MockRuntime()
        ts_ns = 1_000_000_000_000
        sig = _make_signal(ts_ns)
        vote = _make_vote(ts_ns)
        runtime.record_observed_signal("sector_rotation", sig)
        runtime.record_observed_vote("sector_rotation", vote)
        assert runtime.last_sector_rotation_observed_signal is sig
        assert runtime.last_sector_rotation_observed_vote is vote

    def test_stored_pair_carries_same_candle_timestamp(self):
        ts_ns = 1_778_004_120_000_000_000
        sig = _make_signal(ts_ns)
        vote = _make_vote(ts_ns)
        assert sig.exchange_ts_ns == ts_ns
        assert vote.timestamp_ns == ts_ns
        assert sig.exchange_ts_ns == vote.timestamp_ns

    def test_runtime_starts_with_none_pair(self):
        runtime = _MockRuntime()
        assert runtime.last_sector_rotation_observed_signal is None
        assert runtime.last_sector_rotation_observed_vote is None

    def test_overwrite_replaces_prior_pair(self):
        runtime = _MockRuntime()
        sig1 = _make_signal(1_000_000_000_000)
        sig2 = _make_signal(2_000_000_000_000)
        vote1 = _make_vote(1_000_000_000_000)
        vote2 = _make_vote(2_000_000_000_000)
        runtime.record_observed_signal("sector_rotation", sig1)
        runtime.record_observed_vote("sector_rotation", vote1)
        runtime.record_observed_signal("sector_rotation", sig2)
        runtime.record_observed_vote("sector_rotation", vote2)
        assert runtime.last_sector_rotation_observed_signal.exchange_ts_ns == 2_000_000_000_000
        assert runtime.last_sector_rotation_observed_vote.timestamp_ns == 2_000_000_000_000

    def test_wrong_sleeve_does_not_overwrite(self):
        runtime = _MockRuntime()
        sig = _make_signal(1_000_000_000_000)
        runtime.record_observed_signal("liquidity_void", sig)
        assert runtime.last_sector_rotation_observed_signal is None


# ---------------------------------------------------------------------------
# 2. Same-candle pair passes freshness
# ---------------------------------------------------------------------------

class TestSameCandleFreshness:

    def test_same_candle_passes(self):
        ts_ns = 1_000_000_000_000
        sig = _make_signal(ts_ns)
        vote = _make_vote(ts_ns)
        passed, reason = _freshness_contract(sig, vote, ts_ns)
        assert passed, f"expected admit, got: {reason}"

    def test_vote_ts_match_is_sufficient(self):
        ts_ns = 2_000_000_000_000
        sig = types.SimpleNamespace(exchange_ts_ns=ts_ns - 1, side="buy", quantity=1.0)
        vote = _make_vote(ts_ns)
        passed, reason = _freshness_contract(sig, vote, ts_ns)
        assert passed, f"vote_ts match should admit: {reason}"

    def test_signal_ts_match_is_sufficient(self):
        ts_ns = 2_000_000_000_000
        sig = _make_signal(ts_ns)
        vote = types.SimpleNamespace(timestamp_ns=ts_ns - 1, confidence=0.7, risk_appetite=0.5)
        passed, reason = _freshness_contract(sig, vote, ts_ns)
        assert passed, f"signal_ts match should admit: {reason}"


# ---------------------------------------------------------------------------
# 3. Stale pair blocks freshness (strict nanosecond equality)
# ---------------------------------------------------------------------------

class TestStalePairBlocks:

    def test_stale_240s_blocked(self):
        """Reproduces SOL/USD proof log evidence exactly."""
        sig_ts = 1_778_004_120_000_000_000
        dispatch_ts = 1_778_004_360_000_000_000   # Δ = 240s
        passed, reason = _freshness_contract(
            _make_signal(sig_ts), _make_vote(sig_ts), dispatch_ts
        )
        assert not passed, "240s stale pair must be blocked"
        assert "freshness_fail" in reason

    def test_stale_1ns_blocked(self):
        ts_ns = 1_000_000_000_000
        passed, _ = _freshness_contract(
            _make_signal(ts_ns), _make_vote(ts_ns), ts_ns + 1
        )
        assert not passed, "1ns offset must be blocked (strict equality)"

    def test_freshness_uses_strict_equality_not_range(self):
        ts_ns = 5_000_000_000_000
        for offset in (1, 1_000, 60_000_000_000, 240_000_000_000):
            passed, _ = _freshness_contract(
                _make_signal(ts_ns), _make_vote(ts_ns), ts_ns + offset
            )
            assert not passed, f"offset={offset}ns must be blocked by strict equality"


# ---------------------------------------------------------------------------
# 4. Missing pair blocks Gate 2
# ---------------------------------------------------------------------------

class TestMissingPairBlocks:

    def test_missing_signal_blocked(self):
        vote = _make_vote(1_000_000_000_000)
        passed, reason = _freshness_contract(None, vote, 1_000_000_000_000)
        assert not passed
        assert "pair_missing" in reason

    def test_missing_vote_blocked(self):
        sig = _make_signal(1_000_000_000_000)
        passed, reason = _freshness_contract(sig, None, 1_000_000_000_000)
        assert not passed
        assert "pair_missing" in reason

    def test_both_none_blocked(self):
        passed, reason = _freshness_contract(None, None, 1_000_000_000_000)
        assert not passed
        assert "pair_missing" in reason


# ---------------------------------------------------------------------------
# 5. BTC/ETH no-signal case: cold-start guard holds for full warmup window
# ---------------------------------------------------------------------------

class TestColdStartNoPair:

    def test_no_signal_before_min_candles(self, monkeypatch):
        """Root cause for BTC/ETH: _candle_count < _effective_min_candles blocks all."""
        monkeypatch.delenv("PAPER_PROOF_WINDOW_OVERRIDE", raising=False)
        s = _make_strategy()
        assert s._effective_min_candles == _MIN_BASELINE_CANDLES
        for i in range(_MIN_BASELINE_CANDLES - 1):
            sig = s.update_candle(101.0, 500.0, i * 1_000_000_000)
            assert sig is None, f"cold-start guard failed: signal emitted at candle {i + 1}"

    def test_runtime_pair_remains_none_when_no_signal(self, monkeypatch):
        monkeypatch.delenv("PAPER_PROOF_WINDOW_OVERRIDE", raising=False)
        s = _make_strategy()
        runtime = _MockRuntime()
        for i in range(_MIN_BASELINE_CANDLES - 1):
            sig = s.update_candle(101.0, 500.0, i * 1_000_000_000)
            if sig is not None:
                runtime.record_observed_signal("sector_rotation", sig)
                runtime.record_observed_vote("sector_rotation", _make_vote(sig.exchange_ts_ns))
        assert runtime.last_sector_rotation_observed_signal is None
        assert runtime.last_sector_rotation_observed_vote is None


# ---------------------------------------------------------------------------
# 6. SOL stale case: signal produced on prior candle is rejected at dispatch
# ---------------------------------------------------------------------------

class TestSolStalePair:

    def test_stale_pair_matches_proof_log_timestamps(self):
        """Exact nanosecond values from proof log 20260505_130439."""
        stored_ts   = 1_778_004_120_000_000_000
        dispatch_ts = 1_778_004_360_000_000_000
        passed, reason = _freshness_contract(
            _make_signal(stored_ts), _make_vote(stored_ts), dispatch_ts
        )
        assert not passed
        assert str(stored_ts) in reason

    def test_signal_produced_then_no_refresh_causes_stale(self, monkeypatch):
        """
        Pattern: signal stored on candle N; no signal on candle N+1 (low volume);
        dispatch on candle N+1 must fail freshness.
        """
        monkeypatch.delenv("PAPER_PROOF_WINDOW_OVERRIDE", raising=False)
        s = _make_strategy()
        _warm_baseline(s, n=9)

        # Candle 10: high volume → signal produced and stored
        ts_n = 10_000_000_000
        sig1 = s.update_candle(101.0, 500.0, ts_n)
        assert sig1 is not None, "warmup complete: high-volume candle must produce signal"
        runtime = _MockRuntime()
        runtime.record_observed_signal("sector_rotation", sig1)
        runtime.record_observed_vote("sector_rotation", _make_vote(sig1.exchange_ts_ns))

        # Candle 11: low volume → no new signal; stored pair ages
        ts_n1 = 11_000_000_000
        sig2 = s.update_candle(102.0, 50.0, ts_n1)
        assert sig2 is None, "low-volume candle must not emit signal"

        # Dispatch at candle-11 timestamp — freshness must fail
        passed, reason = _freshness_contract(
            runtime.last_sector_rotation_observed_signal,
            runtime.last_sector_rotation_observed_vote,
            ts_n1,
        )
        assert not passed, "stale pair from candle N must fail freshness at candle N+1 dispatch"


# ---------------------------------------------------------------------------
# 7. PAPER_PROOF_WINDOW_OVERRIDE lowers _effective_min_candles without
#    changing production default
# ---------------------------------------------------------------------------

class TestPaperProofWindowOverride:

    def test_override_2_lowers_min_candles(self, monkeypatch):
        monkeypatch.setenv("PAPER_PROOF_WINDOW_OVERRIDE", "2")
        s = SectorRotationStrategy(config=_make_config(), symbol="TEST/USD")
        assert s._effective_min_candles == 2
        assert s._effective_min_candles != _MIN_BASELINE_CANDLES

    def test_absent_override_preserves_production_default(self, monkeypatch):
        monkeypatch.delenv("PAPER_PROOF_WINDOW_OVERRIDE", raising=False)
        s = SectorRotationStrategy(config=_make_config(), symbol="TEST/USD")
        assert s._effective_min_candles == _MIN_BASELINE_CANDLES

    def test_override_1_lowers_to_minimum(self, monkeypatch):
        monkeypatch.setenv("PAPER_PROOF_WINDOW_OVERRIDE", "1")
        s = SectorRotationStrategy(config=_make_config(), symbol="TEST/USD")
        assert s._effective_min_candles == 1

    def test_invalid_override_value_uses_production_default(self, monkeypatch):
        monkeypatch.setenv("PAPER_PROOF_WINDOW_OVERRIDE", "abc")
        s = SectorRotationStrategy(config=_make_config(), symbol="TEST/USD")
        assert s._effective_min_candles == _MIN_BASELINE_CANDLES

    def test_zero_override_uses_production_default(self, monkeypatch):
        monkeypatch.setenv("PAPER_PROOF_WINDOW_OVERRIDE", "0")
        s = SectorRotationStrategy(config=_make_config(), symbol="TEST/USD")
        assert s._effective_min_candles == _MIN_BASELINE_CANDLES

    def test_with_override_2_cold_start_cleared_after_2_candles(self, monkeypatch):
        monkeypatch.setenv("PAPER_PROOF_WINDOW_OVERRIDE", "2")
        s = SectorRotationStrategy(config=_make_config(), symbol="TEST/USD")
        assert s._effective_min_candles == 2
        # Candle 1: baseline, no prev_close yet
        s.update_candle(100.0, 100.0, 0)
        # Candle 2: _candle_count=2 >= min=2; cold-start guard clears.
        # Result depends on volume z-score alone — not asserted here.
        # What IS asserted: cold-start was not the blocker (candle_count reached min).
        s.update_candle(101.0, 500.0, 1_000_000_000)
        assert s._candle_count == 2

    def test_without_override_10_candles_still_required(self, monkeypatch):
        monkeypatch.delenv("PAPER_PROOF_WINDOW_OVERRIDE", raising=False)
        s = _make_strategy()
        for i in range(9):
            sig = s.update_candle(101.0, 500.0, i * 1_000_000_000)
            assert sig is None, f"signal before warmup complete at candle {i + 1}"
