"""
GammaFrontStrategy — Tests

Covers:
  - Entry gate: cold-start, below threshold, disabled, in_position,
    macro_kill, toxicity, cooldown
  - Entry signal contract: exchange_ts_ns explicit, side, quantity, confidence
  - Exit: TTL, take-profit, stop-loss, toxicity spike, macro_kill
  - Exit signal: exchange_ts_ns, cooldown setting, position state cleared
  - Overlays: update_macro_state, update_toxicity, None handling
  - Performance: get_performance snapshot
  - Reset: full state clear

All timing is exchange_ts_ns. No wall-clock.
"""

from decimal import Decimal

import pytest
from unittest.mock import Mock

from app.strategies.gamma_front import GammaFrontStrategy
from app.models import DarkPoolPrint
from app.brain.toxicity_engine import ToxicityAlert, ToxicityRegime
from app.brain.sentiment_velocity import MacroSignal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(
    dark_pool_enabled: bool = True,
    volume_threshold: float = 2.0,
    min_confidence: float = 0.50,
    options_flow_enabled: bool = False,
) -> Mock:
    cfg = Mock()
    cfg.strategies.dark_pool_enabled = dark_pool_enabled
    cfg.strategies.options_flow_enabled = options_flow_enabled
    cfg.strategies.dark_pool_volume_threshold = volume_threshold
    cfg.strategies.min_confidence = min_confidence
    return cfg


def _make_strategy(
    dark_pool_enabled: bool = True,
    volume_threshold: float = 2.0,
    min_confidence: float = 0.50,
) -> GammaFrontStrategy:
    return GammaFrontStrategy(
        config=_make_config(
            dark_pool_enabled=dark_pool_enabled,
            volume_threshold=volume_threshold,
            min_confidence=min_confidence,
        ),
        symbol="SPY",
    )


def _make_dp(
    price: float = 100.0,
    size: float = 1.0,
    is_buy: bool = True,
    ts_ns: int = 1_000_000_000,
) -> DarkPoolPrint:
    return DarkPoolPrint(
        symbol="SPY",
        exchange_ts_ns=ts_ns,
        price=price,
        size=size,
        exchange="NYSE",
        is_buy=is_buy,
    )


def _warm_baseline(strategy: GammaFrontStrategy, n: int = 4) -> None:
    """
    Send n prints with dollar_value=100 (price=100, size=1) to populate baseline.
    After 4 prints: count=4, mean=100.
    """
    for i in range(n):
        strategy.update_dark_pool(_make_dp(price=100.0, size=1.0, ts_ns=i))


def _make_big_print(ts_ns: int = 5_000_000_000, is_buy: bool = True) -> DarkPoolPrint:
    """
    Print with dollar_value=500 (price=100, size=5).
    After 4 baseline prints of 100 each:
      mean after this update = (400+500)/5 = 180
      ratio = 500/180 ≈ 2.78, which exceeds threshold=2.0.
    """
    return _make_dp(price=100.0, size=5.0, ts_ns=ts_ns, is_buy=is_buy)


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


def _make_macro_pause() -> MacroSignal:
    return MacroSignal(
        macro_pause=True,
        macro_kill=False,
        bull_trap_detected=False,
        divergence_score=0.5,
        confidence_boost=0.0,
        halt_seconds=0,
        reason="test_pause",
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInit:

    def test_not_in_position(self):
        s = _make_strategy()
        assert not s._local_in_position

    def test_print_count_zero(self):
        s = _make_strategy()
        assert s._print_count == 0

    def test_no_cooldown(self):
        s = _make_strategy()
        assert s._cooldown_until_ns == 0

    def test_symbol_stored(self):
        s = _make_strategy()
        assert s.symbol == "SPY"

    def test_no_position_state(self):
        s = _make_strategy()
        assert s._local_entry_price is None
        assert s._entry_ts_ns is None
        assert s._entry_side is None


# ---------------------------------------------------------------------------
# Entry gate: cold-start guard
# ---------------------------------------------------------------------------

class TestColdStartGuard:

    def test_first_four_prints_always_suppressed(self):
        """Prints 1-4 have count 1-4; all < _MIN_BASELINE_PRINTS=5 -> None."""
        s = _make_strategy()
        for i in range(4):
            result = s.update_dark_pool(_make_big_print(ts_ns=i * 1_000_000_000))
            assert result is None, f"Expected None at print {i+1}, count={s._print_count}"

    def test_fifth_print_can_trigger(self):
        """4 small baseline prints -> 5th big print reaches count=5 (not < 5)."""
        s = _make_strategy()
        _warm_baseline(s, n=4)
        signal = s.update_dark_pool(_make_big_print(ts_ns=5_000_000_000))
        assert signal is not None

    def test_baseline_always_updates_even_when_suppressed(self):
        """Baseline must accumulate even when cold-start suppresses entry."""
        s = _make_strategy()
        for i in range(3):
            s.update_dark_pool(_make_dp(price=50.0, size=2.0, ts_ns=i))
        assert s._print_count == 3
        assert s._print_stats.mean() > 0


# ---------------------------------------------------------------------------
# Entry gate: threshold
# ---------------------------------------------------------------------------

class TestEntryThreshold:

    def test_below_threshold_no_signal(self):
        s = _make_strategy(volume_threshold=2.0)
        _warm_baseline(s, n=4)
        # dollar_value=100, same as baseline mean: ratio ~1.0 after update -> below 2.0
        result = s.update_dark_pool(_make_dp(price=100.0, size=1.0, ts_ns=5_000_000_000))
        assert result is None

    def test_above_threshold_generates_signal(self):
        s = _make_strategy(volume_threshold=2.0)
        _warm_baseline(s, n=4)
        signal = s.update_dark_pool(_make_big_print())
        assert signal is not None

    def test_disabled_no_signal_regardless_of_threshold(self):
        s = _make_strategy(dark_pool_enabled=False)
        _warm_baseline(s, n=4)
        result = s.update_dark_pool(_make_big_print())
        assert result is None


# ---------------------------------------------------------------------------
# Entry gate: overlay suppressions
# ---------------------------------------------------------------------------

class TestEntryOverlays:

    def test_in_position_no_second_entry(self):
        s = _make_strategy()
        _warm_baseline(s, n=4)
        sig1 = s.update_dark_pool(_make_big_print(ts_ns=5_000_000_000))
        assert sig1 is not None
        sig2 = s.update_dark_pool(_make_big_print(ts_ns=6_000_000_000))
        assert sig2 is None

    def test_macro_kill_suppresses_entry(self):
        s = _make_strategy()
        _warm_baseline(s, n=4)
        s.update_macro_state(_make_macro_kill())
        assert s.update_dark_pool(_make_big_print()) is None

    def test_toxicity_suppresses_entry(self):
        s = _make_strategy()
        _warm_baseline(s, n=4)
        s.update_toxicity(_make_toxic_alert())
        assert s.update_dark_pool(_make_big_print()) is None

    def test_cooldown_suppresses_entry(self):
        s = _make_strategy()
        _warm_baseline(s, n=4)
        s._cooldown_until_ns = 10_000_000_000
        result = s.update_dark_pool(_make_big_print(ts_ns=5_000_000_000))
        assert result is None

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

    def test_toxicity_normal_regime_does_not_suppress(self):
        s = _make_strategy()
        _warm_baseline(s, n=4)
        normal_alert = ToxicityAlert(
            toxicity_score=0.2,
            regime=ToxicityRegime.NORMAL,
            direction_bias="neutral",
            vpin_proxy=0.2,
            burst_pressure=0.2,
            instability_score=0.2,
            volume_anomaly=0.5,
            persistence=0.2,
            confidence=0.8,
            timestamp_ns=1_000_000_000,
            reason="normal",
        )
        s.update_toxicity(normal_alert)
        assert s.update_dark_pool(_make_big_print()) is not None


# ---------------------------------------------------------------------------
# Entry signal contract
# ---------------------------------------------------------------------------

class TestEntrySignalContract:

    def _trigger_entry(self, is_buy: bool = True):
        s = _make_strategy()
        _warm_baseline(s, n=4)
        signal = s.update_dark_pool(_make_big_print(ts_ns=5_000_000_000, is_buy=is_buy))
        return s, signal

    def test_exchange_ts_ns_matches_print(self):
        _, signal = self._trigger_entry()
        assert signal is not None
        assert signal.exchange_ts_ns == 5_000_000_000

    def test_side_buy_for_is_buy_true(self):
        _, signal = self._trigger_entry(is_buy=True)
        assert signal.side == "buy"

    def test_side_sell_for_is_buy_false(self):
        _, signal = self._trigger_entry(is_buy=False)
        assert signal is not None
        assert signal.side == "sell"

    def test_symbol_matches(self):
        _, signal = self._trigger_entry()
        assert signal.symbol == "SPY"

    def test_quantity_positive(self):
        _, signal = self._trigger_entry()
        assert signal.quantity > 0

    def test_confidence_within_governed_range(self):
        # Scale: 0.65 at threshold to 0.85 at 2x threshold, +0.05 if options confirmed
        _, signal = self._trigger_entry()
        assert 0.65 <= signal.confidence <= 0.90

    def test_entry_latches_in_position(self):
        s, _ = self._trigger_entry()
        assert s._local_in_position

    def test_entry_latches_entry_price(self):
        s, _ = self._trigger_entry()
        assert s._local_entry_price == 100.0

    def test_entry_latches_entry_ts_ns(self):
        s, _ = self._trigger_entry()
        assert s._entry_ts_ns == 5_000_000_000


# ---------------------------------------------------------------------------
# Exit conditions
# ---------------------------------------------------------------------------

class TestExitConditions:

    _ENTRY_PRICE = 100.0
    _ENTRY_TS_NS = 5_000_000_000

    def _enter(self, s: GammaFrontStrategy) -> None:
        _warm_baseline(s, n=4)
        signal = s.update_dark_pool(_make_big_print(ts_ns=self._ENTRY_TS_NS))
        assert signal is not None, "Entry not generated — check test fixture"

    def test_ttl_expiry_exit(self):
        """TTL = 60s = 60_000_000_000 ns."""
        s = _make_strategy()
        self._enter(s)
        expired_ts = self._ENTRY_TS_NS + 61_000_000_000
        exit_sig = s.update_price(self._ENTRY_PRICE, expired_ts)
        assert exit_sig is not None
        assert "ttl_expired" in exit_sig.reason

    def test_take_profit_exit(self):
        """Take-profit threshold = +2.0%."""
        s = _make_strategy()
        self._enter(s)
        tp_price = self._ENTRY_PRICE * 1.021
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
        assert not s._local_in_position
        assert s._local_entry_price is None
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
        """Cooldown = 30s = 30_000_000_000 ns post-exit."""
        s = _make_strategy()
        self._enter(s)
        exit_ts = self._ENTRY_TS_NS + 1_000_000_000
        s.update_price(self._ENTRY_PRICE * 1.025, exit_ts)
        assert s._cooldown_until_ns == exit_ts + 30_000_000_000

    def test_update_price_not_in_position_returns_none(self):
        s = _make_strategy()
        assert s.update_price(100.0, 1_000_000_000) is None

    def test_sell_side_stop_loss(self):
        """Stop-loss on a sell entry: price rising = loss."""
        s = _make_strategy()
        _warm_baseline(s, n=4)
        sell_print = _make_big_print(ts_ns=self._ENTRY_TS_NS, is_buy=False)
        s.update_dark_pool(sell_print)
        assert s._entry_side == "sell"
        # Price rises 1.6% -> pnl_pct for sell = -(+0.016) = -0.016 -> beyond -1.5% SL
        sl_price = self._ENTRY_PRICE * 1.016
        exit_sig = s.update_price(sl_price, self._ENTRY_TS_NS + 1_000_000_000)
        assert exit_sig is not None
        assert "stop_loss" in exit_sig.reason


# ---------------------------------------------------------------------------
# Performance and reset
# ---------------------------------------------------------------------------

class TestPerformanceAndReset:

    def test_get_performance_initial_state(self):
        s = _make_strategy()
        perf = s.get_performance()
        assert perf["symbol"] == "SPY"
        assert perf["diagnostic_trade_count"] == 0
        assert perf["diagnostic_win_count"] == 0
        assert perf["diagnostic_provisional_pnl"] == 0.0
        assert not perf["diagnostic_position_active"]
        assert perf["diagnostic_baseline_print_count"] == 0
        assert perf["semantics_declaration"] == "LOCAL_DIAGNOSTIC_ONLY_NOT_LEDGER_TRUTH"

    def test_get_performance_after_winning_trade(self):
        s = _make_strategy()
        _warm_baseline(s, n=4)
        s.update_dark_pool(_make_big_print(ts_ns=5_000_000_000))
        s.update_price(100.0 * 1.025, 6_000_000_000)
        perf = s.get_performance()
        assert perf["diagnostic_trade_count"] == 1
        assert perf["diagnostic_win_count"] == 1
        assert perf["diagnostic_provisional_pnl"] > 0
        assert perf["diagnostic_win_rate_estimate"] == 1.0

    def test_get_performance_after_losing_trade(self):
        s = _make_strategy()
        _warm_baseline(s, n=4)
        s.update_dark_pool(_make_big_print(ts_ns=5_000_000_000))
        s.update_price(100.0 * 0.984, 6_000_000_000)
        perf = s.get_performance()
        assert perf["diagnostic_trade_count"] == 1
        assert perf["diagnostic_win_count"] == 0
        assert perf["diagnostic_provisional_pnl"] < 0

    def test_reset_clears_all_state(self):
        s = _make_strategy()
        _warm_baseline(s, n=4)
        s.update_dark_pool(_make_big_print())
        s.reset()
        assert not s._local_in_position
        assert s._local_entry_price is None
        assert s._entry_ts_ns is None
        assert s._entry_side is None
        assert s._print_count == 0
        assert s._local_trade_count == 0
        assert s._local_win_count == 0
        assert s._provisional_pnl == Decimal("0.0")
        assert s._cooldown_until_ns == 0
        assert not s._macro_kill_active
        assert not s._macro_pause_active
        assert not s._toxicity_high
