"""
SectorRotationStrategy — Tests

Covers:
  - Entry gate: cold-start, below threshold, disabled, in_position,
    macro_kill, toxicity, cooldown, price unchanged, no prev_close
  - Entry signal contract: exchange_ts_ns explicit, side, quantity, confidence
  - Exit: TTL (300s), take-profit, stop-loss, toxicity spike, macro_kill
  - Exit signal: exchange_ts_ns, cooldown setting, position state cleared
  - Overlays: update_macro_state, update_toxicity, None handling
  - Performance: get_performance snapshot
  - Reset: full state clear

Baseline mechanics:
  - _MIN_BASELINE_CANDLES=10; 9 identical candles of volume=100 are sent as
    baseline (warm-up), then the 10th candle is the trigger candidate.
  - After 9x100 + 1x500: mean=140, std=120 (population), zscore(500)=3.0 > 1.5.
  - price direction relative to prev_close=100.0 determines buy vs sell.

All timing is exchange_ts_ns. No wall-clock.
"""

import pytest
from unittest.mock import Mock

from app.strategies.sector_rotation import SectorRotationStrategy
from app.brain.toxicity_engine import ToxicityAlert, ToxicityRegime
from app.brain.sentiment_velocity import MacroSignal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(
    sector_rotation_enabled: bool = True,
    inflow_threshold: float = 1.5,
    min_confidence: float = 0.50,
) -> Mock:
    cfg = Mock()
    cfg.strategies.sector_rotation_enabled = sector_rotation_enabled
    cfg.strategies.sector_inflow_threshold = inflow_threshold
    cfg.strategies.min_confidence = min_confidence
    return cfg


def _make_strategy(
    sector_rotation_enabled: bool = True,
    inflow_threshold: float = 1.5,
    min_confidence: float = 0.50,
) -> SectorRotationStrategy:
    return SectorRotationStrategy(
        config=_make_config(sector_rotation_enabled, inflow_threshold, min_confidence),
        symbol="QQQ",
    )


def _warm_baseline(
    s: SectorRotationStrategy,
    n: int = 9,
    price: float = 100.0,
    volume: float = 100.0,
) -> None:
    """
    Send n identical candles to populate the volume baseline.
    After 9 identical candles: mean=100, variance=0, std=0.
    The 10th candle then introduces the anomaly.
    """
    for i in range(n):
        s.update_candle(price, volume, i * 1_000_000_000)


def _make_big_buy(ts_ns: int = 10_000_000_000):
    """
    price=101.0 > prev_close=100.0 -> buy.
    After 9x100 + this 500: mean=140, std=120, zscore(500)=3.0 > 1.5.
    """
    return (101.0, 500.0, ts_ns)


def _make_big_sell(ts_ns: int = 10_000_000_000):
    """price=99.0 < prev_close=100.0 -> sell."""
    return (99.0, 500.0, ts_ns)


def _make_toxic_alert() -> ToxicityAlert:
    return ToxicityAlert(
        toxicity_score=0.9,
        regime=ToxicityRegime.TOXIC,
        direction_bias="neutral",
        vpin_proxy=0.8,
        burst_pressure=0.8,
        instability_score=0.8,
        volume_anomaly=3.0,
        persistence=0.8,
        confidence=0.9,
        timestamp_ns=1_000_000_000,
        reason="test_toxic",
    )


def _make_macro_kill() -> MacroSignal:
    return MacroSignal(
        macro_pause=False,
        macro_kill=True,
        bull_trap_detected=False,
        divergence_score=0.9,
        confidence_boost=0.0,
        halt_seconds=30,
        reason="test_kill",
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInit:

    def test_not_in_position(self):
        s = _make_strategy()
        assert not s._in_position

    def test_candle_count_zero(self):
        s = _make_strategy()
        assert s._candle_count == 0

    def test_prev_close_none_initially(self):
        s = _make_strategy()
        assert s._prev_close is None

    def test_symbol_stored(self):
        s = _make_strategy()
        assert s.symbol == "QQQ"


# ---------------------------------------------------------------------------
# Entry gate: cold-start guard
# ---------------------------------------------------------------------------

class TestColdStartGuard:

    def test_below_min_candles_no_signal(self):
        """Candles 1-9 have count 1-9; all < _MIN_BASELINE_CANDLES=10 -> None."""
        s = _make_strategy()
        for i in range(9):
            result = s.update_candle(101.0, 500.0, i * 1_000_000_000)
            assert result is None, f"Expected None at candle {i+1}, count={s._candle_count}"

    def test_at_min_candles_can_trigger(self):
        """9 warm-up candles + 1 big candle -> count=10, can trigger."""
        s = _make_strategy()
        _warm_baseline(s, n=9)
        price, volume, ts_ns = _make_big_buy()
        signal = s.update_candle(price, volume, ts_ns)
        assert signal is not None

    def test_first_candle_sets_prev_close(self):
        """First candle sets prev_close but cannot trigger (count=1 < 10)."""
        s = _make_strategy()
        result = s.update_candle(100.0, 500.0, 0)
        assert result is None
        assert s._prev_close == 100.0

    def test_baseline_accumulates_even_when_suppressed(self):
        s = _make_strategy()
        _warm_baseline(s, n=5)
        assert s._candle_count == 5
        assert s._volume_stats.mean() > 0


# ---------------------------------------------------------------------------
# Entry gate: volume threshold and direction
# ---------------------------------------------------------------------------

class TestEntryThreshold:

    def test_below_threshold_no_signal(self):
        """
        After 9 identical vol=100 candles, a 10th vol=100 candle:
        all 10 values identical -> std=0 -> zscore=0.0 < 1.5 -> no signal.
        """
        s = _make_strategy()
        _warm_baseline(s, n=9)
        result = s.update_candle(101.0, 100.0, 10_000_000_000)
        assert result is None
        assert s.get_last_decline_reason() == "volume_zscore_below_threshold"
        detail = s.get_last_decline_detail()
        assert detail["volume"] == 100.0
        assert detail["volume_mean"] == 100.0
        assert detail["volume_std"] == 0.0
        assert detail["volume_zscore"] == 0.0
        assert detail["threshold"] == 1.5
        assert detail["candle_count"] == 10
        assert detail["min_candles"] == 10

    def test_above_threshold_buy_signal(self):
        s = _make_strategy()
        _warm_baseline(s, n=9)
        price, volume, ts_ns = _make_big_buy()
        signal = s.update_candle(price, volume, ts_ns)
        assert signal is not None
        assert signal.side == "buy"
        assert s.get_last_decline_reason() is None

    def test_above_threshold_sell_signal(self):
        s = _make_strategy()
        _warm_baseline(s, n=9)
        price, volume, ts_ns = _make_big_sell()
        signal = s.update_candle(price, volume, ts_ns)
        assert signal is not None
        assert signal.side == "sell"

    def test_price_unchanged_no_directional_signal(self):
        """If price == prev_close, direction is ambiguous -> no signal."""
        s = _make_strategy()
        _warm_baseline(s, n=9)
        result = s.update_candle(100.0, 500.0, 10_000_000_000)
        assert result is None

    def test_disabled_no_signal_regardless_of_volume(self):
        s = _make_strategy(sector_rotation_enabled=False)
        _warm_baseline(s, n=9)
        price, volume, ts_ns = _make_big_buy()
        result = s.update_candle(price, volume, ts_ns)
        assert result is None


# ---------------------------------------------------------------------------
# Entry gate: overlay suppressions
# ---------------------------------------------------------------------------

class TestEntryOverlays:

    def test_in_position_no_second_entry(self):
        s = _make_strategy()
        _warm_baseline(s, n=9)
        price, volume, ts_ns = _make_big_buy()
        sig1 = s.update_candle(price, volume, ts_ns)
        assert sig1 is not None
        sig2 = s.update_candle(price, volume, ts_ns + 1_000_000_000)
        assert sig2 is None

    def test_macro_kill_suppresses_entry(self):
        s = _make_strategy()
        _warm_baseline(s, n=9)
        s.update_macro_state(_make_macro_kill())
        price, volume, ts_ns = _make_big_buy()
        assert s.update_candle(price, volume, ts_ns) is None

    def test_toxicity_suppresses_entry(self):
        s = _make_strategy()
        _warm_baseline(s, n=9)
        s.update_toxicity(_make_toxic_alert())
        price, volume, ts_ns = _make_big_buy()
        assert s.update_candle(price, volume, ts_ns) is None

    def test_cooldown_suppresses_entry(self):
        s = _make_strategy()
        _warm_baseline(s, n=9)
        s._cooldown_until_ns = 20_000_000_000
        price, volume, ts_ns = _make_big_buy()
        assert s.update_candle(price, volume, ts_ns) is None

    def test_update_macro_state_none_is_noop(self):
        s = _make_strategy()
        s.update_macro_state(None)
        assert not s._macro_kill_active
        assert not s._macro_pause_active

    def test_update_toxicity_none_clears_flag(self):
        s = _make_strategy()
        s.update_toxicity(_make_toxic_alert())
        assert s._toxicity_high
        s.update_toxicity(None)
        assert not s._toxicity_high


# ---------------------------------------------------------------------------
# Entry signal contract
# ---------------------------------------------------------------------------

class TestEntrySignalContract:

    def _trigger_buy(self):
        s = _make_strategy()
        _warm_baseline(s, n=9)
        price, volume, ts_ns = _make_big_buy(ts_ns=10_000_000_000)
        signal = s.update_candle(price, volume, ts_ns)
        return s, signal

    def test_exchange_ts_ns_explicit(self):
        _, signal = self._trigger_buy()
        assert signal is not None
        assert signal.exchange_ts_ns == 10_000_000_000

    def test_symbol_matches(self):
        _, signal = self._trigger_buy()
        assert signal.symbol == "QQQ"

    def test_quantity_positive(self):
        _, signal = self._trigger_buy()
        assert signal.quantity > 0

    def test_confidence_within_governed_range(self):
        """Confidence scale: 0.65 (at threshold) to 0.80 (at 2x threshold)."""
        _, signal = self._trigger_buy()
        assert 0.65 <= signal.confidence <= 0.85

    def test_buy_side(self):
        _, signal = self._trigger_buy()
        assert signal.side == "buy"

    def test_entry_latches_in_position(self):
        s, _ = self._trigger_buy()
        assert s._in_position

    def test_entry_price_latched(self):
        """Entry price must be the trigger candle's close price."""
        s, _ = self._trigger_buy()
        assert s._entry_price == 101.0

    def test_entry_ts_ns_latched(self):
        s, _ = self._trigger_buy()
        assert s._entry_ts_ns == 10_000_000_000


# ---------------------------------------------------------------------------
# Exit conditions
# ---------------------------------------------------------------------------

class TestExitConditions:

    _ENTRY_TS_NS = 10_000_000_000
    _ENTRY_PRICE = 101.0

    def _enter(self, s: SectorRotationStrategy) -> None:
        _warm_baseline(s, n=9)
        price, volume, _ = _make_big_buy()
        signal = s.update_candle(price, volume, self._ENTRY_TS_NS)
        assert signal is not None, "Entry not generated — check test fixture"

    def test_ttl_expiry_exit(self):
        """TTL = 300s = 300_000_000_000 ns."""
        s = _make_strategy()
        self._enter(s)
        expired_ts = self._ENTRY_TS_NS + 301_000_000_000
        exit_sig = s.update_price(self._ENTRY_PRICE, expired_ts)
        assert exit_sig is not None
        assert "ttl_expired" in exit_sig.reason

    def test_take_profit_exit(self):
        """Take-profit threshold = +2.0%."""
        s = _make_strategy()
        self._enter(s)
        tp_price = self._ENTRY_PRICE * 1.025
        exit_sig = s.update_price(tp_price, self._ENTRY_TS_NS + 1_000_000_000)
        assert exit_sig is not None
        assert "take_profit" in exit_sig.reason

    def test_stop_loss_exit(self):
        """Stop-loss threshold = -1.5%."""
        s = _make_strategy()
        self._enter(s)
        sl_price = self._ENTRY_PRICE * 0.984
        exit_sig = s.update_price(sl_price, self._ENTRY_TS_NS + 1_000_000_000)
        assert exit_sig is not None
        assert "stop_loss" in exit_sig.reason

    def test_toxicity_spike_exit(self):
        s = _make_strategy()
        self._enter(s)
        s.update_toxicity(_make_toxic_alert())
        exit_sig = s.update_price(self._ENTRY_PRICE, self._ENTRY_TS_NS + 1_000_000_000)
        assert exit_sig is not None
        assert "toxicity_spike" in exit_sig.reason

    def test_macro_kill_exit(self):
        s = _make_strategy()
        self._enter(s)
        s.update_macro_state(_make_macro_kill())
        exit_sig = s.update_price(self._ENTRY_PRICE, self._ENTRY_TS_NS + 1_000_000_000)
        assert exit_sig is not None
        assert "macro_kill" in exit_sig.reason

    def test_no_exit_within_ttl_no_conditions(self):
        s = _make_strategy()
        self._enter(s)
        result = s.update_price(self._ENTRY_PRICE, self._ENTRY_TS_NS + 5_000_000_000)
        assert result is None

    def test_exit_clears_position_state(self):
        s = _make_strategy()
        self._enter(s)
        s.update_price(self._ENTRY_PRICE * 1.025, self._ENTRY_TS_NS + 1_000_000_000)
        assert not s._in_position
        assert s._entry_price is None
        assert s._entry_ts_ns is None
        assert s._entry_side is None

    def test_exit_signal_exchange_ts_ns_matches_tick(self):
        s = _make_strategy()
        self._enter(s)
        exit_ts = self._ENTRY_TS_NS + 1_000_000_000
        exit_sig = s.update_price(self._ENTRY_PRICE * 1.025, exit_ts)
        assert exit_sig is not None
        assert exit_sig.exchange_ts_ns == exit_ts

    def test_exit_sets_cooldown(self):
        """Cooldown = 60s = 60_000_000_000 ns post-exit."""
        s = _make_strategy()
        self._enter(s)
        exit_ts = self._ENTRY_TS_NS + 1_000_000_000
        s.update_price(self._ENTRY_PRICE * 1.025, exit_ts)
        assert s._cooldown_until_ns == exit_ts + 60_000_000_000

    def test_update_price_not_in_position_returns_none(self):
        s = _make_strategy()
        assert s.update_price(100.0, 1_000_000_000) is None

    def test_sell_side_stop_loss(self):
        """Stop-loss on sell entry: price rising = loss."""
        s = _make_strategy()
        _warm_baseline(s, n=9)
        price, volume, _ = _make_big_sell()
        s.update_candle(price, volume, self._ENTRY_TS_NS)
        assert s._entry_side == "sell"
        # Price rises 2% -> pnl_pct for sell = -(+0.02) -> beyond -1.5% SL
        sl_price = 99.0 * 1.02
        exit_sig = s.update_price(sl_price, self._ENTRY_TS_NS + 1_000_000_000)
        assert exit_sig is not None
        assert "stop_loss" in exit_sig.reason


# ---------------------------------------------------------------------------
# Performance and reset
# ---------------------------------------------------------------------------

class TestPerformanceAndReset:

    def test_get_performance_initial(self):
        s = _make_strategy()
        perf = s.get_performance()
        assert perf["symbol"] == "QQQ"
        assert perf["trade_count"] == 0
        assert perf["win_count"] == 0
        assert perf["total_pnl"] == 0.0
        assert not perf["in_position"]
        assert perf["candle_count"] == 0

    def test_get_performance_after_winning_trade(self):
        s = _make_strategy()
        _warm_baseline(s, n=9)
        price, volume, ts_ns = _make_big_buy(ts_ns=10_000_000_000)
        s.update_candle(price, volume, ts_ns)
        entry_price = s._entry_price
        s.update_price(entry_price * 1.025, 11_000_000_000)
        perf = s.get_performance()
        assert perf["trade_count"] == 1
        assert perf["win_count"] == 1
        assert perf["total_pnl"] > 0
        assert perf["win_rate"] == 1.0

    def test_get_performance_after_losing_trade(self):
        s = _make_strategy()
        _warm_baseline(s, n=9)
        price, volume, ts_ns = _make_big_buy(ts_ns=10_000_000_000)
        s.update_candle(price, volume, ts_ns)
        entry_price = s._entry_price
        s.update_price(entry_price * 0.984, 11_000_000_000)
        perf = s.get_performance()
        assert perf["trade_count"] == 1
        assert perf["win_count"] == 0
        assert perf["total_pnl"] < 0

    def test_reset_clears_all_state(self):
        s = _make_strategy()
        _warm_baseline(s, n=9)
        price, volume, ts_ns = _make_big_buy()
        s.update_candle(price, volume, ts_ns)
        s.reset()
        assert not s._in_position
        assert s._entry_price is None
        assert s._entry_ts_ns is None
        assert s._entry_side is None
        assert s._candle_count == 0
        assert s._prev_close is None
        assert s._trade_count == 0
        assert s._win_count == 0
        assert s._total_pnl == 0.0
        assert s._cooldown_until_ns == 0
        assert not s._macro_kill_active
        assert not s._macro_pause_active
        assert not s._toxicity_high


# ---------------------------------------------------------------------------
# STRATEGY_ADMISSION bundle: PAPER_PROOF_WINDOW_OVERRIDE
# ---------------------------------------------------------------------------

class TestPaperProofWindowOverride:
    """
    Tests for PAPER_PROOF_WINDOW_OVERRIDE env var.
    Production default (_MIN_BASELINE_CANDLES=10) must be unchanged when absent.
    Override must be opt-in and paper-proof / testing only.
    """

    def test_override_reduces_required_candles(self, monkeypatch):
        """
        With override=4, only 3 warmup + 1 trigger needed (total count=4).
        With n=4 data points [100,100,100,500]: mean=200, std≈173, zscore≈1.73 > 1.5.
        n=3 is insufficient (max zscore = sqrt(2)≈1.41 < threshold=1.5).
        """
        monkeypatch.setenv("PAPER_PROOF_WINDOW_OVERRIDE", "4")
        s = _make_strategy()
        _warm_baseline(s, n=3, price=100.0, volume=100.0)
        price, volume, ts_ns = _make_big_buy(ts_ns=10_000_000_000)
        signal = s.update_candle(price, volume, ts_ns)
        assert signal is not None, "Override=4 should allow admission at candle count=4"

    def test_override_absent_production_default_unchanged(self, monkeypatch):
        """Without override, production default=10 applies: 3 warmup + 1 trigger blocks."""
        monkeypatch.delenv("PAPER_PROOF_WINDOW_OVERRIDE", raising=False)
        s = _make_strategy()
        _warm_baseline(s, n=3, price=100.0, volume=100.0)
        price, volume, ts_ns = _make_big_buy(ts_ns=10_000_000_000)
        result = s.update_candle(price, volume, ts_ns)
        assert result is None, "candle_count=4 < production_default=10 must block"

    def test_override_admission_only_when_other_conditions_met(self, monkeypatch):
        """Override reduces window but cannot bypass volume threshold or direction gates."""
        monkeypatch.setenv("PAPER_PROOF_WINDOW_OVERRIDE", "4")
        s = _make_strategy()
        _warm_baseline(s, n=3, price=100.0, volume=100.0)
        # Volume same as baseline (z-score ~= 0) — below inflow_threshold=1.5
        result = s.update_candle(101.0, 100.0, 10_000_000_000)
        assert result is None, "Override bypasses freshness only; volume gate still applies"

    def test_override_observed_pair_still_blocks(self, monkeypatch):
        """
        With override=1, candle_count passes but prev_close=None on first candle
        → observed pair missing → still blocks.
        """
        monkeypatch.setenv("PAPER_PROOF_WINDOW_OVERRIDE", "1")
        s = _make_strategy()
        # First candle: count becomes 1 >= 1 (passes freshness), but prev_close=None
        result = s.update_candle(101.0, 500.0, 0)
        assert result is None, "First candle has no prev_close: observed pair missing must block"

    def test_effective_min_candles_attribute_set(self, monkeypatch):
        """_effective_min_candles attribute is set correctly from env var."""
        monkeypatch.setenv("PAPER_PROOF_WINDOW_OVERRIDE", "4")
        s = _make_strategy()
        assert s._effective_min_candles == 4

    def test_effective_min_candles_default_when_env_absent(self, monkeypatch):
        """_effective_min_candles defaults to _MIN_BASELINE_CANDLES=10 when env absent."""
        monkeypatch.delenv("PAPER_PROOF_WINDOW_OVERRIDE", raising=False)
        s = _make_strategy()
        assert s._effective_min_candles == 10


class TestSRFreshnessAndPairTelemetry:
    """
    Tests for SR_WINDOW_TOO_SHORT and SR_OBSERVED_PAIR_MISSING log markers.
    Production safeguards preserved: observed pair missing and freshness fail
    must still block regardless of telemetry.
    """

    def test_freshness_fail_still_blocks(self, monkeypatch):
        """candle_count < effective_min_candles → None returned (with or without log)."""
        monkeypatch.delenv("PAPER_PROOF_WINDOW_OVERRIDE", raising=False)
        s = _make_strategy()
        # First candle: count=1 < 10 → freshness fail blocks
        result = s.update_candle(101.0, 500.0, 0)
        assert result is None

    def test_freshness_fail_logs_sr_window_too_short(self, monkeypatch, caplog):
        """SR_WINDOW_TOO_SHORT marker is logged when freshness fails."""
        import logging
        monkeypatch.delenv("PAPER_PROOF_WINDOW_OVERRIDE", raising=False)
        s = _make_strategy()
        with caplog.at_level(logging.DEBUG):
            s.update_candle(101.0, 500.0, 0)
        assert "SR_WINDOW_TOO_SHORT" in caplog.text

    def test_observed_pair_missing_still_blocks(self, monkeypatch):
        """prev_close=None → None returned even when freshness passes."""
        monkeypatch.setenv("PAPER_PROOF_WINDOW_OVERRIDE", "1")
        s = _make_strategy()
        result = s.update_candle(101.0, 500.0, 0)  # count=1 >= 1, prev_close=None
        assert result is None

    def test_observed_pair_missing_logs_marker(self, monkeypatch, caplog):
        """SR_OBSERVED_PAIR_MISSING marker is logged when prev_close is None."""
        import logging
        monkeypatch.setenv("PAPER_PROOF_WINDOW_OVERRIDE", "1")
        s = _make_strategy()
        with caplog.at_level(logging.DEBUG):
            s.update_candle(101.0, 500.0, 0)
        assert "SR_OBSERVED_PAIR_MISSING" in caplog.text

    def test_no_fake_admission_without_required_inputs(self, monkeypatch):
        """Override active but volume z-score below threshold → no signal."""
        monkeypatch.setenv("PAPER_PROOF_WINDOW_OVERRIDE", "3")
        s = _make_strategy()
        _warm_baseline(s, n=2)
        # Small volume identical to baseline → z-score near 0 → below threshold
        result = s.update_candle(101.0, 100.0, 10_000_000_000)
        assert result is None
