"""
Gamma-Front (Dark Pool) Strategy Candidate

Evaluates dark pool prints against a rolling dollar-value baseline.
Generates provisional entry signals based on print ratios, gated by
external macro and toxicity overlays.

PROVISIONAL BOUNDARIES & DISCLOSURES:
- Sizing: This strategy does NOT own or allocate portfolio capital. The size 
  output is an abstract risk fraction (0.0 to 1.0). 
- Ledger Truth: Internal PnL and performance tracking are unverified, local 
  approximations based on mid-price assumptions. Monetary truth is governed 
  by external accounting layers, not this file.
- Float Math: Rolling statistics, price deltas, and confidence scores utilize 
  floats for speed. Decimal is used strictly for local PnL accumulation to 
  prevent iteration drift, but this local calculation is NOT a governed ledger.
- Timing: Strictly relies on exchange_ts_ns (no wall-clock).

Exit conditions (evaluated in priority order):
    1. TTL expiry   — 60 s from entry (exchange_ts_ns)
    2. Take profit  — +2.0% from entry in position direction
    3. Stop loss    — -1.5% from entry in position direction
    4. Toxicity     — regime >= TOXIC while in position
    5. Macro kill   — macro_kill active while in position
"""

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from app.models import DarkPoolPrint, OptionsFlow, StrategySignal
from app.brain.toxicity_engine import ToxicityAlert, ToxicityRegime
from app.brain.sentiment_velocity import MacroSignal
from app.brain.rolling_stats import RollingStats
from app.constants import SleeveType, DARK_POOL_TTL_SECONDS

logger = logging.getLogger(__name__)

# Float guard for percentage bounds
_EPS: float = 1e-12

# Minimum prints before baseline is meaningful (cold-start guard)
_MIN_BASELINE_PRINTS: int = 5

# Position management thresholds
_TAKE_PROFIT_PCT: float = 0.020   # 2.0%
_STOP_LOSS_PCT: float   = 0.015   # 1.5%
_COOLDOWN_NS: int       = 30_000_000_000   # 30 s post-exit cooldown

# TTL in nanoseconds — derived from governed constant
_TTL_NS: int = int(DARK_POOL_TTL_SECONDS * 1_000_000_000)

# Rolling baseline window (prints)
_BASELINE_WINDOW: int = 50


class GammaFrontStrategy:
    """
    Gamma-Front (Dark Pool) strategy candidate.

    Identifies dark pool prints that exceed a rolling dollar-value baseline
    threshold and proposes signals aligned with the institutional direction. 
    Entries are gated by toxicity regime, macro-kill/pause overlay, cooldown, 
    and minimum baseline.
    
    All position management is timestamp-driven (exchange_ts_ns only).

    Current local interface (provisional; framework integration unverified):
        update_macro_state(macro_signal: Optional[MacroSignal]) -> None
        update_toxicity(toxicity_alert: Optional[ToxicityAlert]) -> None
        update_options_flow(flow: Optional[OptionsFlow]) -> Optional[StrategySignal]  *Unverified routing path
        update_dark_pool(dp: DarkPoolPrint) -> Optional[StrategySignal]
        update_price(price: float, timestamp_ns: int) -> Optional[StrategySignal]
        get_performance() -> Dict[str, Any]
        reset() -> None
    """

    def __init__(self, config: Any, symbol: str) -> None:
        """
        Args:
            config: Top-level configuration object. 
            symbol: Instrument symbol this instance tracks.
        """
        self.config = config
        self.symbol = symbol

        # The exact schema of the injected `config` object is unverified locally.
        # This implementation structurally assumes `config.strategies` provides the 
        # following attributes, explicitly cast here to ensure local type safety.
        strat_cfg = config.strategies
        self._dark_pool_enabled: bool    = bool(strat_cfg.dark_pool_enabled)
        self._options_flow_enabled: bool = bool(strat_cfg.options_flow_enabled)
        self._volume_threshold: float    = float(strat_cfg.dark_pool_volume_threshold)
        self._min_confidence: float      = float(strat_cfg.min_confidence)

        # Rolling dollar-value baseline (retained as float for statistical window performance)
        self._print_stats: RollingStats = RollingStats(window_size=_BASELINE_WINDOW)
        self._print_count: int = 0

        # Position state
        self._local_in_position: bool               = False
        self._local_entry_price: Optional[float]    = None
        self._entry_ts_ns: Optional[int]            = None
        self._entry_side: Optional[str]             = None
        self._provisional_risk_fraction: float      = 0.0

        # Exchange-time cooldown (ns) — 0 means inactive
        self._cooldown_until_ns: int = 0

        # Overlay state
        self._macro_kill_active: bool                  = False
        self._macro_pause_active: bool                 = False
        self._toxicity_high: bool                      = False
        self._last_options_flow: Optional[OptionsFlow] = None

        # Performance tracking (Decimal isolates accumulation drift, but is NOT ledger truth)
        self._local_trade_count: int   = 0
        self._local_win_count: int     = 0
        self._provisional_pnl: Decimal = Decimal('0.0')

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
        if self._macro_kill_active and self._local_in_position:
            logger.warning(
                "GAMMA-FRONT [%s]: macro_kill active — local position exits on next price tick",
                self.symbol,
            )

    def update_toxicity(self, toxicity_alert: Optional[ToxicityAlert]) -> None:
        """Update toxicity overlay state from toxicity engine."""
        if toxicity_alert is None:
            self._toxicity_high = False
            return
        self._toxicity_high = toxicity_alert.regime >= ToxicityRegime.TOXIC

    def update_options_flow(self, flow: Optional[OptionsFlow]) -> Optional[StrategySignal]:
        """
        Update options flow confirmation state and clear stale positions if applicable.
        Only consumes flow data when options_flow_enabled=True.
        
        Integration Note: This surface may emit an administrative StrategySignal to clear 
        stale local state. Downstream ingestion of signals from this specific method 
        is unverified and depends entirely on external router compatibility.
        """
        if flow is not None:
            if self._options_flow_enabled:
                self._last_options_flow = flow
                
            # Stale state clearing utilizing the options flow timestamp
            if self._local_in_position:
                return self._evaluate_stale_position_ttl(flow.exchange_ts_ns)
                
        return None

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

        if self._local_in_position:
            # Halted-feed trap fix: Prevent stale local position latching if price updates stop.
            # Evaluate TTL against the incoming dark pool print's timestamp without booking a realized trade.
            stale_exit_signal = self._evaluate_stale_position_ttl(dp.exchange_ts_ns)
            if stale_exit_signal:
                return stale_exit_signal
            return None

        if not self._dark_pool_enabled:
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
        risk_fraction = self._calculate_provisional_risk_fraction(confidence)
        options_confirmed = self._options_confirms_direction(side, dp.exchange_ts_ns)

        reason = (
            f"dark_pool ratio={print_ratio:.1f}x "
            f"usd={dp.dollar_value:.0f} side={side} venue={dp.venue}"
        )

        # Latch local position state before returning signal
        self._local_in_position          = True
        self._local_entry_price          = dp.price
        self._entry_ts_ns                = dp.exchange_ts_ns
        self._entry_side                 = side
        self._provisional_risk_fraction  = risk_fraction

        logger.info(
            "GAMMA-FRONT ENTRY [%s]: %s @ %.4f risk_fraction=%.6f conf=%.3f",
            self.symbol, reason, dp.price, risk_fraction, confidence,
        )

        # Sizing semantics: 'quantity' represents a provisional abstract risk fraction, not executable asset size.
        return StrategySignal(
            strategy=SleeveType.GAMMA_FRONT,
            symbol=self.symbol,
            side=side,
            confidence=confidence,
            quantity=risk_fraction,
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
                "quantity_semantics": "provisional_risk_fraction_0_to_1",
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
        if not self._local_in_position:
            return None

        entry_price = self._local_entry_price
        entry_ts_ns = self._entry_ts_ns

        # Defensive guard: state must be fully latched when _local_in_position is True
        if entry_price is None or entry_ts_ns is None:
            logger.error(
                "GAMMA-FRONT [%s]: inconsistent position state "
                "(entry_price=%s entry_ts_ns=%s) — resetting",
                self.symbol, entry_price, entry_ts_ns,
            )
            self._local_in_position = False
            return None

        # Priority 1: TTL Expiry
        # Shared helper fixes the halted-feed trap while preserving exit priority
        ttl_exit_signal = self._evaluate_stale_position_ttl(timestamp_ns, price)
        if ttl_exit_signal:
            return ttl_exit_signal

        # Signed PnL relative to entry direction (float precision approximation)
        raw_pct = (price - entry_price) / entry_price
        pnl_pct = raw_pct if self._entry_side == "buy" else -raw_pct

        # Priority 2-5: Price, Toxicity, and Macro Overlays
        exit_reason: Optional[str] = None
        if pnl_pct >= (_TAKE_PROFIT_PCT - _EPS):
            exit_reason = f"take_profit pnl={pnl_pct:.4f}"
        elif pnl_pct <= -(_STOP_LOSS_PCT - _EPS):
            exit_reason = f"stop_loss pnl={pnl_pct:.4f}"
        elif self._toxicity_high:
            exit_reason = "toxicity_spike"
        elif self._macro_kill_active:
            exit_reason = "macro_kill"

        if exit_reason is None:
            return None

        return self._generate_exit_signal(price, timestamp_ns, pnl_pct, exit_reason)

    def _evaluate_stale_position_ttl(
        self, 
        current_ts_ns: int,
        current_price: Optional[float] = None
    ) -> Optional[StrategySignal]:
        """
        Bounded local helper to check and clear TTL expiry via any timestamped event.
        If current_price is provided (e.g. from update_price), it triggers a realized 
        trade exit. If current_price is None (non-price event), it cleanly releases 
        the local state without mutating local diagnostic trade accounting.
        """
        if not self._local_in_position or self._entry_ts_ns is None or self._local_entry_price is None:
            return None
            
        elapsed_ns = current_ts_ns - self._entry_ts_ns
        if elapsed_ns >= _TTL_NS:
            if current_price is not None:
                # Realized price-path exit
                raw_pct = (current_price - self._local_entry_price) / self._local_entry_price
                pnl_pct = raw_pct if self._entry_side == "buy" else -raw_pct
                return self._generate_exit_signal(
                    current_price, 
                    current_ts_ns, 
                    pnl_pct, 
                    f"ttl_expired elapsed_ns={elapsed_ns}"
                )
            else:
                # Non-price administrative stale cleanup (no accounting mutation)
                return self._generate_stale_cleanup_signal(current_ts_ns, elapsed_ns)
                
        return None

    def _generate_exit_signal(
        self,
        price: float,
        timestamp_ns: int,
        pnl_pct: float,
        reason: str,
    ) -> StrategySignal:
        """Build exit signal, update local diagnostic counters, reset position state."""
        entry_price   = self._local_entry_price   # guarded upstream
        entry_ts_ns   = self._entry_ts_ns         # guarded upstream
        risk_fraction = self._provisional_risk_fraction
        entry_side    = self._entry_side

        # Evaluate provisional PnL locally
        raw_pnl    = risk_fraction * (price - entry_price)
        signed_pnl = raw_pnl if entry_side == "buy" else -raw_pnl

        # This method is for realized price-path events ONLY. Mutates local trade accounting.
        self._local_trade_count += 1
        if signed_pnl > 0.0:
            self._local_win_count += 1
            
        # Accumulate to Decimal to avoid compounding float drift over thousands of iterations
        self._provisional_pnl += Decimal(str(signed_pnl))

        exit_side = "sell" if entry_side == "buy" else "buy"

        logger.info(
            "GAMMA-FRONT EXIT [%s]: reason=%s pnl=%.4f @ %.4f",
            self.symbol, reason, pnl_pct, price,
        )

        # Sizing semantics: 'quantity' represents a provisional abstract risk fraction, not executable asset size.
        signal = StrategySignal(
            strategy=SleeveType.GAMMA_FRONT,
            symbol=self.symbol,
            side=exit_side,
            confidence=0.90,
            quantity=risk_fraction,
            price=price,
            exchange_ts_ns=timestamp_ns,
            reason=reason,
            metadata={
                "local_entry_price":  entry_price,
                "local_exit_price":   price,
                "local_pnl_pct":      pnl_pct,
                "local_hold_ns":      timestamp_ns - entry_ts_ns,
                "quantity_semantics": "provisional_risk_fraction_0_to_1",
            },
        )

        # Clear position and set exchange-time cooldown
        self._local_in_position          = False
        self._local_entry_price          = None
        self._entry_ts_ns                = None
        self._entry_side                 = None
        self._provisional_risk_fraction  = 0.0
        self._cooldown_until_ns          = timestamp_ns + _COOLDOWN_NS

        return signal

    def _generate_stale_cleanup_signal(
        self,
        timestamp_ns: int,
        elapsed_ns: int
    ) -> StrategySignal:
        """
        Administratively clears local state for a stale position via a non-price event.
        Bypasses local trade accounting entirely (does not mutate PnL or trade counts).
        Emits a strictly 0.0 quantity, 0.0 confidence signal to block physical execution.
        """
        entry_price   = self._local_entry_price   # guarded upstream
        entry_ts_ns   = self._entry_ts_ns         # guarded upstream
        entry_side    = self._entry_side

        exit_side = "sell" if entry_side == "buy" else "buy"
        reason = f"administrative_local_state_clear_stale_ttl elapsed_ns={elapsed_ns}"

        logger.info(
            "GAMMA-FRONT [%s]: Stale local position administratively cleared via non-price event at ts=%s",
            self.symbol, timestamp_ns
        )

        # Sizing semantics: Quantity is forced to 0.0 to neutralize downstream execution intent entirely.
        signal = StrategySignal(
            strategy=SleeveType.GAMMA_FRONT,
            symbol=self.symbol,
            side=exit_side,
            confidence=0.0,       # Zero confidence marks an explicit lack of market-driven intent
            quantity=0.0,         # Zero quantity blocks translation into executable asset size
            price=entry_price,    # Flat price reference to satisfy model requirements
            exchange_ts_ns=timestamp_ns,
            reason=reason,
            metadata={
                "local_entry_price":       entry_price,
                "local_exit_price":        entry_price,
                "local_pnl_pct":           0.0,
                "local_hold_ns":           timestamp_ns - entry_ts_ns,
                "quantity_semantics":      "zero_quantity_administrative_clear",
                "is_administrative_clear": True,
                "executable_intent":       "none"
            },
        )

        # Clear position and set exchange-time cooldown
        self._local_in_position          = False
        self._local_entry_price          = None
        self._entry_ts_ns                = None
        self._entry_side                 = None
        self._provisional_risk_fraction  = 0.0
        self._cooldown_until_ns          = timestamp_ns + _COOLDOWN_NS

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

        if self._options_confirms_direction("buy" if dp.is_buy else "sell", dp.exchange_ts_ns):
            confidence = min(0.95, confidence + 0.05)

        return confidence

    def _options_confirms_direction(self, direction: str, current_ts_ns: int) -> bool:
        """Return True if last unusual options flow confirms the given direction within TTL."""
        if not self._options_flow_enabled or self._last_options_flow is None:
            return False
            
        flow = self._last_options_flow
        
        # Temporal state leakage guard: 5-minute TTL (300 seconds)
        # Prevents stale options flow from permanently boosting confidence
        flow_age_ns = current_ts_ns - flow.exchange_ts_ns
        if flow_age_ns > 300_000_000_000:
            return False
            
        if not flow.is_unusual:
            return False
            
        return (
            (direction == "buy"  and flow.side == "CALL") or
            (direction == "sell" and flow.side == "PUT")
        )

    def _calculate_provisional_risk_fraction(self, confidence: float) -> float:
        """
        Calculates an abstract risk fraction (0.0 to 1.0).
        Translation to physical inventory is outside the scope of this local strategy.
        """
        return min(1.0, max(0.01, confidence))

    # ------------------------------------------------------------------
    # INTROSPECTION
    # ------------------------------------------------------------------

    def get_performance(self) -> Dict[str, Any]:
        """
        Return provisional diagnostic metrics.
        WARNING: All values are local estimates based on mid-price assumptions. 
        They DO NOT represent physical portfolio accounting truth.
        """
        win_rate = self._local_win_count / max(self._local_trade_count, 1)
        avg_pnl  = float(self._provisional_pnl) / max(self._local_trade_count, 1)
        return {
            "symbol":                           self.symbol,
            "diagnostic_trade_count":           self._local_trade_count,
            "diagnostic_win_count":             self._local_win_count,
            "diagnostic_win_rate_estimate":     win_rate,
            "diagnostic_provisional_pnl":       float(self._provisional_pnl),
            "diagnostic_provisional_avg_pnl":   avg_pnl,
            "diagnostic_position_active":       self._local_in_position,
            "diagnostic_entry_price_estimate":  self._local_entry_price,
            "diagnostic_baseline_print_count":  self._print_count,
            "diagnostic_baseline_mean_usd":     self._print_stats.mean(),
            "semantics_declaration":            "LOCAL_DIAGNOSTIC_ONLY_NOT_LEDGER_TRUTH"
        }

    def reset(self) -> None:
        """Reset all strategy state to initial conditions."""
        self._local_in_position          = False
        self._local_entry_price          = None
        self._entry_ts_ns                = None
        self._entry_side                 = None
        self._provisional_risk_fraction  = 0.0
        self._cooldown_until_ns          = 0
        self._macro_kill_active          = False
        self._macro_pause_active         = False
        self._toxicity_high              = False
        self._last_options_flow          = None
        self._print_stats                = RollingStats(window_size=_BASELINE_WINDOW)
        self._print_count                = 0
        self._local_trade_count          = 0
        self._local_win_count            = 0
        self._provisional_pnl            = Decimal('0.0')
        logger.info("GammaFrontStrategy reset for %s", self.symbol)