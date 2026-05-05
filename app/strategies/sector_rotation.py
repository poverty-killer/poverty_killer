"""
Sector Rotation Strategy

Detects abnormal sector volume inflow via rolling Z-score and enters in the
direction implied by price relative to the prior close. Designed to front
institutional sector rotation flows before they fully propagate.

Entry gate:
    volume Z-score >= sector_inflow_threshold
    and price direction is deterministic (price != prev_close)
    and not in position, not in cooldown, not macro_kill, not TOXIC regime,
    and minimum baseline sample count satisfied.

Exit conditions (evaluated in priority order):
    1. TTL expiry   — 300 s from entry (exchange_ts_ns, no wall-clock)
    2. Take profit  — +2.0% from entry in position direction
    3. Stop loss    — -1.5% from entry in position direction
    4. Toxicity     — regime >= TOXIC while in position
    5. Macro kill   — macro_kill active while in position

Input interface: primitive (price: float, volume: float, timestamp_ns: int).
No Candle model dependency — Candle migration is deferred; this interface
avoids that blocker while remaining fully operational.

All timing uses exchange_ts_ns exclusively. No wall-clock. Replay-safe.

Residual open item: _TTL_NS = 300_000_000_000 is an implementation-level
default. No governing constant (e.g. SECTOR_ROTATION_TTL_SECONDS) exists yet
in app/constants.py. This must be closed in a future bounded constants session.
"""

import logging
import os
from typing import Any, Dict, Optional

from app.models import StrategySignal
from app.brain.toxicity_engine import ToxicityAlert, ToxicityRegime
from app.brain.sentiment_velocity import MacroSignal
from app.brain.rolling_stats import RollingStats
from app.constants import SleeveType

logger = logging.getLogger(__name__)

# Float guard
_EPS: float = 1e-12

# Minimum candles before baseline is meaningful (cold-start guard)
_MIN_BASELINE_CANDLES: int = 10

# Rolling baseline window (candles)
_BASELINE_WINDOW: int = 50

# Position management
_TAKE_PROFIT_PCT: float = 0.020   # 2.0%
_STOP_LOSS_PCT: float   = 0.015   # 1.5%
_COOLDOWN_NS: int       = 60_000_000_000   # 60 s post-exit cooldown

# TTL in nanoseconds — implementation-level default; no governing constant yet
_TTL_NS: int = 300_000_000_000   # 300 s


class SectorRotationStrategy:
    """
    Sector Rotation strategy.

    Detects abnormal volume inflow via rolling Z-score and fronts the implied
    institutional direction. Entries are gated by toxicity regime, macro-kill/
    pause overlay, cooldown, and minimum baseline. Price direction relative to
    previous close determines entry side. All position management is timestamp-
    driven (exchange_ts_ns only).

    Public interface (matches sibling strategy pattern):
        update_macro_state(macro_signal: Optional[MacroSignal]) -> None
        update_toxicity(toxicity_alert: Optional[ToxicityAlert]) -> None
        update_candle(price: float, volume: float, timestamp_ns: int) -> Optional[StrategySignal]
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
        self._sector_rotation_enabled: bool = strat_cfg.sector_rotation_enabled
        self._inflow_threshold: float       = float(strat_cfg.sector_inflow_threshold)
        self._min_confidence: float         = float(strat_cfg.min_confidence)

        # Rolling volume baseline
        self._volume_stats: RollingStats = RollingStats(window_size=_BASELINE_WINDOW)
        self._candle_count: int = 0

        # Previous close for direction determination
        self._prev_close: Optional[float] = None

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

        # Performance tracking
        self._trade_count: int  = 0
        self._win_count: int    = 0
        self._total_pnl: float  = 0.0

        # PAPER_PROOF_WINDOW_OVERRIDE: paper proof / testing only.
        # Production default (_MIN_BASELINE_CANDLES=10) is preserved when env var is absent.
        # Set PAPER_PROOF_WINDOW_OVERRIDE=<int> to admit earlier in short proof windows.
        _ppwo = os.environ.get("PAPER_PROOF_WINDOW_OVERRIDE", "").strip()
        self._effective_min_candles: int = (
            int(_ppwo) if _ppwo.isdigit() and int(_ppwo) >= 1 else _MIN_BASELINE_CANDLES
        )
        if self._effective_min_candles != _MIN_BASELINE_CANDLES:
            logger.info(
                "SECTOR-ROTATION [%s]: PAPER_PROOF_WINDOW_OVERRIDE=%s active — "
                "effective_min_candles=%d (production default=%d)",
                symbol, _ppwo, self._effective_min_candles, _MIN_BASELINE_CANDLES,
            )

        logger.info(
            "SectorRotationStrategy initialized for %s: "
            "sector_rotation_enabled=%s, inflow_threshold=%.2f, ttl_s=%.0f",
            symbol, self._sector_rotation_enabled,
            self._inflow_threshold, _TTL_NS / 1_000_000_000,
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
                "SECTOR-ROTATION [%s]: macro_kill active — position exits on next price tick",
                self.symbol,
            )

    def update_toxicity(self, toxicity_alert: Optional[ToxicityAlert]) -> None:
        """Update toxicity overlay state from toxicity engine."""
        if toxicity_alert is None:
            self._toxicity_high = False
            return
        self._toxicity_high = toxicity_alert.regime >= ToxicityRegime.TOXIC

    # ------------------------------------------------------------------
    # PRIMARY SIGNAL INPUT: CANDLE / BAR UPDATE
    # ------------------------------------------------------------------

    def update_candle(
        self,
        price: float,
        volume: float,
        timestamp_ns: int,
    ) -> Optional[StrategySignal]:
        """
        Evaluate incoming candle/bar. Always updates rolling volume baseline
        and advances prev_close.

        Args:
            price:        Close price of the bar.
            volume:       Bar volume (shares, contracts, or base units).
            timestamp_ns: Exchange timestamp in nanoseconds (bar close time).

        Returns:
            StrategySignal for entry if all conditions met, else None.
        """
        # Always update baseline regardless of guards
        self._volume_stats.update(volume)
        self._candle_count += 1

        prev_close = self._prev_close
        self._prev_close = price   # advance before any early return

        if not self._sector_rotation_enabled:
            return None
        if self._in_position:
            return None
        if timestamp_ns < self._cooldown_until_ns:
            return None
        if self._macro_kill_active:
            return None
        if self._toxicity_high:
            return None
        if self._candle_count < self._effective_min_candles:
            logger.debug(
                "[SR_WINDOW_TOO_SHORT] %s: candle_count=%d < min=%d — freshness fail",
                self.symbol, self._candle_count, self._effective_min_candles,
            )
            return None

        # Direction requires a known previous close
        if prev_close is None or abs(prev_close) < _EPS:
            if prev_close is None:
                logger.debug(
                    "[SR_OBSERVED_PAIR_MISSING] %s: prev_close not yet observed — observed pair missing",
                    self.symbol,
                )
            return None

        # Volume Z-score gate
        volume_zscore = self._volume_stats.zscore(volume)
        if volume_zscore < self._inflow_threshold:
            return None

        # Direction from price relative to previous close
        if price > prev_close:
            side = "buy"
        elif price < prev_close:
            side = "sell"
        else:
            # Price unchanged — no directional signal
            return None

        return self._generate_entry_signal(price, volume, volume_zscore, side, timestamp_ns)

    def _generate_entry_signal(
        self,
        price: float,
        volume: float,
        volume_zscore: float,
        side: str,
        timestamp_ns: int,
    ) -> Optional[StrategySignal]:
        """Build entry signal from qualifying candle."""
        confidence = self._compute_confidence(volume_zscore)

        if self._macro_pause_active:
            confidence *= 0.75

        if confidence < self._min_confidence:
            logger.debug(
                "SECTOR-ROTATION [%s]: confidence %.3f below min %.3f — suppressed",
                self.symbol, confidence, self._min_confidence,
            )
            return None

        position_size = self._calculate_position_size(price, confidence)

        reason = (
            f"sector_inflow zscore={volume_zscore:.2f} "
            f"vol={volume:.0f} side={side}"
        )

        # Latch position state before returning signal
        self._in_position   = True
        self._entry_price   = price
        self._entry_ts_ns   = timestamp_ns
        self._entry_side    = side
        self._position_size = position_size

        logger.info(
            "SECTOR-ROTATION ENTRY [%s]: %s @ %.4f size=%.6f conf=%.3f",
            self.symbol, reason, price, position_size, confidence,
        )

        return StrategySignal(
            strategy=SleeveType.SECTOR_ROTATION.value,
            symbol=self.symbol,
            side=side,
            confidence=confidence,
            quantity=position_size,
            price=price,
            exchange_ts_ns=timestamp_ns,
            reason=reason,
            metadata={
                "volume_zscore":      volume_zscore,
                "volume":             volume,
                "inflow_threshold":   self._inflow_threshold,
                "macro_pause_active": self._macro_pause_active,
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
                "SECTOR-ROTATION [%s]: inconsistent position state "
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
            "SECTOR-ROTATION EXIT [%s]: reason=%s pnl=%.4f @ %.4f",
            self.symbol, reason, pnl_pct, price,
        )

        signal = StrategySignal(
            strategy=SleeveType.SECTOR_ROTATION.value,
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

    def _compute_confidence(self, volume_zscore: float) -> float:
        """
        Scale confidence linearly from 0.65 at threshold to 0.80 at 2x threshold.
        Lower ceiling than GammaFront (0.85) — sector rotation carries lower
        signal specificity than a qualifying dark pool print.
        """
        min_conf = 0.65
        max_conf = 0.80
        overshoot = (volume_zscore - self._inflow_threshold) / max(self._inflow_threshold, _EPS)
        scale = min(max(overshoot, 0.0), 1.0)
        return min_conf + scale * (max_conf - min_conf)

    def _calculate_position_size(self, price: float, confidence: float) -> float:
        """
        Risk-based position size using fixed simulated capital.
        1.5% max risk per trade — between shadow_front (2%) and gamma_front (1%).
        Sector rotation signals are directionally meaningful but carry higher
        adverse-selection risk than dark pool prints due to lower specificity.
        """
        if price < _EPS:
            return 0.0
        max_risk_usd  = 20_000.0 * 0.015   # $300
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
            "symbol":          self.symbol,
            "trade_count":     self._trade_count,
            "win_count":       self._win_count,
            "win_rate":        win_rate,
            "total_pnl":       self._total_pnl,
            "avg_pnl":         avg_pnl,
            "in_position":     self._in_position,
            "entry_price":     self._entry_price,
            "candle_count":    self._candle_count,
            "volume_mean":     self._volume_stats.mean(),
            "volume_std":      self._volume_stats.std(),
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
        self._prev_close         = None
        self._volume_stats       = RollingStats(window_size=_BASELINE_WINDOW)
        self._candle_count       = 0
        self._trade_count        = 0
        self._win_count          = 0
        self._total_pnl          = 0.0
        logger.info("SectorRotationStrategy reset for %s", self.symbol)
