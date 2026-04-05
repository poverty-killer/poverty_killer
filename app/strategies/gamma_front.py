"""
Gamma-Front (Dark Pool) Strategy

Detects abnormally large dark pool prints and fronts the institutional
direction with fast entries, hard TTL, and regime-aware overlay suppression.

Entry gate:
    dark pool print dollar_value >= dark_pool_volume_threshold x rolling mean
    and not in position, not in cooldown, not macro_kill, not TOXIC regime,
    and minimum baseline sample count satisfied.

Exit conditions (evaluated in priority order):
    1. TTL expiry   — 60 s from entry (exchange_ts_ns, no wall-clock)
    2. Take profit  — +2.0% from entry in position direction
    3. Stop loss    — -1.5% from entry in position direction
    4. Toxicity     — regime >= TOXIC while in position
    5. Macro kill   — macro_kill active while in position

All timing uses exchange_ts_ns exclusively. No wall-clock. Replay-safe.
"""

import logging
from typing import Any, Dict, Optional

from app.models import DarkPoolPrint, OptionsFlow, StrategySignal
from app.brain.toxicity_engine import ToxicityAlert, ToxicityRegime
from app.brain.sentiment_velocity import MacroSignal
from app.brain.rolling_stats import RollingStats
from app.constants import SleeveType, DARK_POOL_TTL_SECONDS

logger = logging.getLogger(__name__)

# Float guard
_EPS: float = 1e-12

# Minimum prints before baseline is meaningful (cold-start guard)
_MIN_BASELINE_PRINTS: int = 5

# Position management
_TAKE_PROFIT_PCT: float = 0.020   # 2.0%
_STOP_LOSS_PCT: float   = 0.015   # 1.5%
_COOLDOWN_NS: int       = 30_000_000_000   # 30 s post-exit cooldown

# TTL in nanoseconds — derived from governed constant
_TTL_NS: int = int(DARK_POOL_TTL_SECONDS * 1_000_000_000)

# Rolling baseline window (prints)
_BASELINE_WINDOW: int = 50


class GammaFrontStrategy:
    """
    Gamma-Front (Dark Pool) strategy.

    Identifies dark pool prints that exceed a rolling dollar-value baseline
    threshold and fronts the institutional direction. Entries are gated by
    toxicity regime, macro-kill/pause overlay, cooldown, and minimum baseline.
    All position management is timestamp-driven (exchange_ts_ns only).

    Public interface (matches sibling strategy pattern):
        update_macro_state(macro_signal: Optional[MacroSignal]) -> None
        update_toxicity(toxicity_alert: Optional[ToxicityAlert]) -> None
        update_options_flow(flow: Optional[OptionsFlow]) -> None
        update_dark_pool(dp: DarkPoolPrint) -> Optional[StrategySignal]
        update_price(price: float, timestamp_ns: int) -> Optional[StrategySignal]
        get_performance() -> Dict[str, Any]
        reset() -> None
    """

    def __init__(self, config: Any, symbol: str) -> None:
        """
        Args:
            config: Top-level configuration object. Strategy-specific fields
                    accessed via config.strategies.* (sibling pattern).
            symbol: Instrument symbol this instance tracks.
        """
        self.config = config
        self.symbol = symbol

        strat_cfg = config.strategies
        self._dark_pool_enabled: bool  = strat_cfg.dark_pool_enabled
        self._options_flow_enabled: bool = strat_cfg.options_flow_enabled
        self._volume_threshold: float  = float(strat_cfg.dark_pool_volume_threshold)
        self._min_confidence: float    = float(strat_cfg.min_confidence)

        # Rolling dollar-value baseline
        self._print_stats: RollingStats = RollingStats(window_size=_BASELINE_WINDOW)
        self._print_count: int = 0

        # Position state
        self._in_position: bool            = False
        self._entry_price: Optional[float] = None
        self._entry_ts_ns: Optional[int]   = None
        self._entry_side: Optional[str]    = None
        self._position_size: float         = 0.0

        # Exchange-time cooldown (ns) — 0 means inactive
        self._cooldown_until_ns: int = 0

        # Overlay state
        self._macro_kill_active: bool  = False
        self._macro_pause_active: bool = False
        self._toxicity_high: bool      = False
        self._last_options_flow: Optional[Any] = None

        # Performance tracking
        self._trade_count: int  = 0
        self._win_count: int    = 0
        self._total_pnl: float  = 0.0

        logger.info(
            "GammaFrontStrategy initialized for %s: "
            "dark_pool_enabled=%s, volume_threshold=%.1fx, ttl_s=%.0f",
            symbol, self._dark_pool_enabled,
            self._volume_threshold, DARK_POOL_TTL_SECONDS,
        )

    # ------------------------------------------------------------------
    # OVERLAY STATE UPDATES
    # ------------------------------------------------------------------

    def update_macro_state(self, macro_signal: Optional[MacroSignal]) -> None:
        """Update macro overlay state from sentiment velocity engine."""
        if macro_signal is None:
            return
        self._macro_kill_active  = macro_signal.macro_kill
        self._macro_pause_active = macro_signal.macro_pause
        if self._macro_kill_active and self._in_position:
            logger.warning(
                "GAMMA-FRONT [%s]: macro_kill active — position exits on next price tick",
                self.symbol,
            )

    def update_toxicity(self, toxicity_alert: Optional[ToxicityAlert]) -> None:
        """Update toxicity overlay state from toxicity engine."""
        if toxicity_alert is None:
            self._toxicity_high = False
            return
        self._toxicity_high = toxicity_alert.regime >= ToxicityRegime.TOXIC

    def update_options_flow(self, flow: Optional[Any]) -> None:
        """
        Update options flow confirmation state.
        Only consumed when options_flow_enabled=True (default=False).
        """
        if self._options_flow_enabled:
            self._last_options_flow = flow

    # ------------------------------------------------------------------
    # PRIMARY SIGNAL INPUT: DARK POOL PRINT
    # ------------------------------------------------------------------

    def update_dark_pool(self, dp: DarkPoolPrint) -> Optional[StrategySignal]:
        """
        Evaluate incoming dark pool print. Always updates rolling baseline.

        Returns:
            StrategySignal for entry if all conditions met, else None.
        """
        # Always update baseline regardless of guards
        self._print_stats.update(dp.dollar_value)
        self._print_count += 1

        if not self._dark_pool_enabled:
            return None
        if self._in_position:
            return None
        if dp.exchange_ts_ns < self._cooldown_until_ns:
            return None
        if self._macro_kill_active:
            return None
        if self._toxicity_high:
            return None
        if self._print_count < _MIN_BASELINE_PRINTS:
            return None

        mean_dollar = self._print_stats.mean()
        if mean_dollar < _EPS:
            return None

        print_ratio = dp.dollar_value / mean_dollar
        if print_ratio < self._volume_threshold:
            return None

        return self._generate_entry_signal(dp, print_ratio)

    def _generate_entry_signal(
        self,
        dp: DarkPoolPrint,
        print_ratio: float,
    ) -> Optional[StrategySignal]:
        """Build entry signal from qualifying dark pool print."""
        confidence = self._compute_confidence(dp, print_ratio)

        if self._macro_pause_active:
            confidence *= 0.75

        if confidence < self._min_confidence:
            logger.debug(
                "GAMMA-FRONT [%s]: confidence %.3f below min %.3f — suppressed",
                self.symbol, confidence, self._min_confidence,
            )
            return None

        side = "buy" if dp.is_buy else "sell"
        position_size = self._calculate_position_size(dp.price, confidence)
        options_confirmed = self._options_confirms_direction(side)

        reason = (
            f"dark_pool ratio={print_ratio:.1f}x "
            f"usd={dp.dollar_value:.0f} side={side} venue={dp.venue}"
        )

        # Latch position state before returning signal
        self._in_position   = True
        self._entry_price   = dp.price
        self._entry_ts_ns   = dp.exchange_ts_ns
        self._entry_side    = side
        self._position_size = position_size

        logger.info(
            "GAMMA-FRONT ENTRY [%s]: %s @ %.4f size=%.6f conf=%.3f",
            self.symbol, reason, dp.price, position_size, confidence,
        )

        return StrategySignal(
            strategy=SleeveType.GAMMA_FRONT,
            symbol=self.symbol,
            side=side,
            confidence=confidence,
            quantity=position_size,
            price=dp.price,
            exchange_ts_ns=dp.exchange_ts_ns,
            reason=reason,
            metadata={
                "print_ratio":        print_ratio,
                "print_usd":          dp.dollar_value,
                "print_size":         dp.size,
                "print_venue":        dp.venue,
                "macro_pause_active": self._macro_pause_active,
                "options_confirmed":  options_confirmed,
            },
        )

    # ------------------------------------------------------------------
    # PRICE UPDATE + POSITION EXIT MANAGEMENT
    # ------------------------------------------------------------------

    def update_price(self, price: float, timestamp_ns: int) -> Optional[StrategySignal]:
        """
        Evaluate exit conditions against current price.

        Args:
            price:        Current mid/last price.
            timestamp_ns: Exchange timestamp in nanoseconds.

        Returns:
            StrategySignal for exit if triggered, else None.
        """
        if not self._in_position:
            return None

        entry_price = self._entry_price
        entry_ts_ns = self._entry_ts_ns

        # Defensive guard: state must be fully latched when in_position is True
        if entry_price is None or entry_ts_ns is None:
            logger.error(
                "GAMMA-FRONT [%s]: inconsistent position state "
                "(entry_price=%s entry_ts_ns=%s) — resetting",
                self.symbol, entry_price, entry_ts_ns,
            )
            self._in_position = False
            return None

        # Signed PnL relative to entry direction
        raw_pct = (price - entry_price) / entry_price
        pnl_pct = raw_pct if self._entry_side == "buy" else -raw_pct

        exit_reason: Optional[str] = None

        elapsed_ns = timestamp_ns - entry_ts_ns
        if elapsed_ns >= _TTL_NS:
            exit_reason = f"ttl_expired elapsed_ns={elapsed_ns}"
        elif pnl_pct >= _TAKE_PROFIT_PCT:
            exit_reason = f"take_profit pnl={pnl_pct:.4f}"
        elif pnl_pct <= -_STOP_LOSS_PCT:
            exit_reason = f"stop_loss pnl={pnl_pct:.4f}"
        elif self._toxicity_high:
            exit_reason = "toxicity_spike"
        elif self._macro_kill_active:
            exit_reason = "macro_kill"

        if exit_reason is None:
            return None

        return self._generate_exit_signal(price, timestamp_ns, pnl_pct, exit_reason)

    def _generate_exit_signal(
        self,
        price: float,
        timestamp_ns: int,
        pnl_pct: float,
        reason: str,
    ) -> StrategySignal:
        """Build exit signal, update performance counters, reset position state."""
        entry_price = self._entry_price   # guarded above
        entry_ts_ns = self._entry_ts_ns   # guarded above
        quantity    = self._position_size
        entry_side  = self._entry_side

        raw_pnl    = quantity * (price - entry_price)
        signed_pnl = raw_pnl if entry_side == "buy" else -raw_pnl

        self._trade_count += 1
        if signed_pnl > 0.0:
            self._win_count += 1
        self._total_pnl += signed_pnl

        exit_side = "sell" if entry_side == "buy" else "buy"

        logger.info(
            "GAMMA-FRONT EXIT [%s]: reason=%s pnl=%.4f @ %.4f",
            self.symbol, reason, pnl_pct, price,
        )

        signal = StrategySignal(
            strategy=SleeveType.GAMMA_FRONT,
            symbol=self.symbol,
            side=exit_side,
            confidence=0.90,
            quantity=quantity,
            price=price,
            exchange_ts_ns=timestamp_ns,
            reason=reason,
            metadata={
                "entry_price": entry_price,
                "exit_price":  price,
                "pnl_pct":     pnl_pct,
                "hold_ns":     timestamp_ns - entry_ts_ns,
            },
        )

        # Clear position and set exchange-time cooldown
        self._in_position       = False
        self._entry_price       = None
        self._entry_ts_ns       = None
        self._entry_side        = None
        self._position_size     = 0.0
        self._cooldown_until_ns = timestamp_ns + _COOLDOWN_NS

        return signal

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    def _compute_confidence(self, dp: DarkPoolPrint, print_ratio: float) -> float:
        """
        Scale confidence linearly from 0.65 at threshold to 0.85 at 2x threshold.
        Options flow confirmation adds +0.05, capped at 0.95.
        """
        min_conf = 0.65
        max_conf = 0.85
        overshoot = (print_ratio - self._volume_threshold) / max(self._volume_threshold, _EPS)
        scale = min(max(overshoot, 0.0), 1.0)
        confidence = min_conf + scale * (max_conf - min_conf)

        if self._options_confirms_direction("buy" if dp.is_buy else "sell"):
            confidence = min(0.95, confidence + 0.05)

        return confidence

    def _options_confirms_direction(self, direction: str) -> bool:
        """Return True if last unusual options flow confirms the given direction."""
        if not self._options_flow_enabled or self._last_options_flow is None:
            return False
        flow = self._last_options_flow
        if not flow.is_unusual:
            return False
        return (
            (direction == "buy"  and flow.side == "CALL") or
            (direction == "sell" and flow.side == "PUT")
        )

    def _calculate_position_size(self, price: float, confidence: float) -> float:
        """
        Risk-based position size using fixed simulated capital.
        1% max risk per trade (tighter than shadow_front's 2% — dark pool
        fronting carries higher adverse-selection risk).
        """
        if price < _EPS:
            return 0.0
        max_risk_usd  = 20_000.0 * 0.01   # $200
        stop_distance = _STOP_LOSS_PCT
        base_size = max_risk_usd / (price * stop_distance)
        size = base_size * confidence
        return max(1e-6, min(0.5, size))

    # ------------------------------------------------------------------
    # INTROSPECTION
    # ------------------------------------------------------------------

    def get_performance(self) -> Dict[str, Any]:
        """Return performance metrics snapshot (read-only, no state mutation)."""
        win_rate = self._win_count / max(self._trade_count, 1)
        avg_pnl  = self._total_pnl / max(self._trade_count, 1)
        return {
            "symbol":         self.symbol,
            "trade_count":    self._trade_count,
            "win_count":      self._win_count,
            "win_rate":       win_rate,
            "total_pnl":      self._total_pnl,
            "avg_pnl":        avg_pnl,
            "in_position":    self._in_position,
            "entry_price":    self._entry_price,
            "print_count":    self._print_count,
            "print_mean_usd": self._print_stats.mean(),
        }

    def reset(self) -> None:
        """Reset all strategy state to initial conditions."""
        self._in_position        = False
        self._entry_price        = None
        self._entry_ts_ns        = None
        self._entry_side         = None
        self._position_size      = 0.0
        self._cooldown_until_ns  = 0
        self._macro_kill_active  = False
        self._macro_pause_active = False
        self._toxicity_high      = False
        self._last_options_flow  = None
        self._print_stats        = RollingStats(window_size=_BASELINE_WINDOW)
        self._print_count        = 0
        self._trade_count        = 0
        self._win_count          = 0
        self._total_pnl          = 0.0
        logger.info("GammaFrontStrategy reset for %s", self.symbol)
