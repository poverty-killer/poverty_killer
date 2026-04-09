"""
Fractal Liquidity Void (FLV) - Crisis Sniper Strategy
Exploits liquidity voids during market crises with TPE integration.
Detects super-voids, structural collapse, and executes fast rebound trades.
HARDENED: TPE integration, toxicity awareness, macro-kill override.

IMPORT CORRECTIONS (verified from repo this session):
- ToxicityAlert, ToxicityRegime: app.brain.toxicity_engine (not app.models)
- MacroSignal: app.brain.sentiment_velocity (not app.models)
- TopologicalSignal: app.brain.topological_engine (not app.models)
- LARSignal: confirmed nonexistent in repo (tombstone only) — removed
- StrategySignal.strategy: str field — SleeveType.FLV.value is correct
- RegimeType unused — removed from import

MACRO-KILL SEQUENCING:
- update_macro_state() sets flag and logs only — does not call _force_exit()
- update_order_book() emits exit signal while position state is intact
- Matches gamma_front governing pattern
"""

import logging
import numpy as np
from typing import Optional, Dict, Any

from app.models import OrderBookSnapshot, StrategySignal
from app.brain.toxicity_engine import ToxicityAlert, ToxicityRegime
from app.brain.sentiment_velocity import MacroSignal
from app.brain.topological_engine import TopologicalSignal
from app.constants import SleeveType, LiquidityVoidStatus

logger = logging.getLogger(__name__)

# Machine epsilon
EPS = np.finfo(float).eps


class LiquidityVoidStrategy:
    """
    Fractal Liquidity Void (FLV) - Crisis sniper.
    Activates on TPE super-void or structural collapse detection.
    Executes fast, controlled snap trades with hard time stops.

    Primary entry triggers (TPE-driven):
      - super_void_detected: pre-crash void signal
      - structural_collapse: market structure breaking
    Both require spread expansion confirmation.

    Macro-kill sequencing: flag set in update_macro_state(),
    exit signal emitted by update_order_book() while state intact.
    """

    def __init__(self, config: Any, symbol: str):
        self.config = config
        self.symbol = symbol
        self.status = LiquidityVoidStatus.INACTIVE

        self.max_hold_bars: int = config.strategies.flv_max_hold_bars
        self.kelly_multiplier: float = config.strategies.flv_kelly_multiplier
        self.volume_anomaly_threshold: float = config.strategies.flv_volume_anomaly_threshold
        self.spread_expansion_threshold: float = config.strategies.flv_spread_expansion_threshold

        self.entry_price: Optional[float] = None
        self.entry_time_ns: Optional[int] = None
        self.exit_price: Optional[float] = None
        self.exit_time_ns: Optional[int] = None
        self.position_size: float = 0.0
        self.position_side: str = "buy"
        self.pnl: float = 0.0
        self.hold_bars: int = 0

        self._entry_signal_time_ns: Optional[int] = None
        self._last_toxicity_alert: Optional[ToxicityAlert] = None
        self._last_topology: Optional[TopologicalSignal] = None
        self._macro_kill_active: bool = False
        self._macro_pause_active: bool = False

        self._trade_count: int = 0
        self._win_count: int = 0
        self._total_pnl: float = 0.0

        logger.info(
            "LiquidityVoidStrategy initialized for %s: max_hold=%d, kelly_mult=%.2f",
            symbol, self.max_hold_bars, self.kelly_multiplier,
        )

    def update_macro_state(self, macro_signal: Optional[MacroSignal]) -> None:
        """
        Update macro overlay flags. Sets flags only.
        Does NOT call _force_exit(). Does NOT reset position state.
        Exit signal emitted by update_order_book() while state intact.
        Matches gamma_front governing pattern.
        """
        if macro_signal is None:
            self._macro_kill_active = False
            self._macro_pause_active = False
            return

        self._macro_kill_active = macro_signal.macro_kill
        self._macro_pause_active = macro_signal.macro_pause

        if self._macro_kill_active and self.status == LiquidityVoidStatus.ENTERED:
            logger.warning(
                "FLV [%s]: macro_kill active - position exits on next order_book tick",
                self.symbol,
            )

    def update_toxicity(self, toxicity_alert: Optional[ToxicityAlert]) -> None:
        """Update toxicity state from ToxicityEngine."""
        self._last_toxicity_alert = toxicity_alert

    def update_topology(self, topology: Optional[TopologicalSignal]) -> None:
        """Update topological state from TopologicalEngine."""
        self._last_topology = topology

    def update_order_book(self, order_book: OrderBookSnapshot) -> Optional[StrategySignal]:
        """
        Update with new order book and check for entry/exit.
        Macro-kill exit emitted here while position state is intact.
        """
        # Macro-kill: emit exit while state intact
        if self._macro_kill_active:
            if self.status == LiquidityVoidStatus.ENTERED:
                return self._generate_exit_signal(
                    order_book.mid_price, order_book.exchange_ts_ns, "macro_kill"
                )
            return None

        # Entry
        if self.status in (LiquidityVoidStatus.INACTIVE, LiquidityVoidStatus.SCANNING):
            if self._should_enter(order_book):
                self._entry_signal_time_ns = order_book.exchange_ts_ns
                self.status = LiquidityVoidStatus.DETECTED
                return self._generate_entry_signal(order_book)

        # Exit
        if self.status == LiquidityVoidStatus.ENTERED:
            if self._should_exit(order_book):
                return self._generate_exit_signal(
                    order_book.mid_price, order_book.exchange_ts_ns, "exit_conditions"
                )

        # Hold-bar TTL
        if self.status == LiquidityVoidStatus.ENTERED:
            self.hold_bars += 1
            if self.hold_bars >= self.max_hold_bars:
                return self._generate_exit_signal(
                    order_book.mid_price, order_book.exchange_ts_ns, "max_hold_reached"
                )

        return None

    def _should_enter(self, order_book: OrderBookSnapshot) -> bool:
        """
        TPE-driven entry gate.

        Primary triggers: super_void_detected OR structural_collapse
        Required confirmation: spread > spread_expansion_threshold
        Hard veto: toxicity >= TOXIC
        """
        # Toxicity hard veto
        if (
            self._last_toxicity_alert is not None
            and self._last_toxicity_alert.regime >= ToxicityRegime.TOXIC
        ):
            logger.debug("FLV entry vetoed: toxicity=%s for %s",
                         self._last_toxicity_alert.regime.name, self.symbol)
            return False

        # TPE primary triggers
        tpe_void = (
            self._last_topology is not None
            and self._last_topology.super_void_detected
        )
        tpe_collapse = (
            self._last_topology is not None
            and self._last_topology.structural_collapse
        )

        if tpe_void:
            logger.info("TPE super-void detected for %s", self.symbol)
        if tpe_collapse:
            logger.info("TPE structural collapse detected for %s", self.symbol)

        # Spread confirmation
        spread_wide = order_book.spread_bps > self.spread_expansion_threshold

        if (tpe_void or tpe_collapse) and spread_wide:
            logger.info(
                "FLV entry conditions met for %s: tpe_void=%s, tpe_collapse=%s, "
                "spread=%.1fbps",
                self.symbol, tpe_void, tpe_collapse, order_book.spread_bps,
            )
            return True

        return False

    def _should_exit(self, order_book: OrderBookSnapshot) -> bool:
        """Exit gate — any trigger sufficient."""
        if self.entry_price is None:
            return True

        current_price = order_book.mid_price
        pnl_pct = (
            (current_price - self.entry_price) / (self.entry_price + EPS)
            if self.position_side == "buy"
            else (self.entry_price - current_price) / (self.entry_price + EPS)
        )

        if pnl_pct >= 0.015:
            logger.info("FLV take profit: %.2f%% for %s", pnl_pct * 100, self.symbol)
            return True

        if pnl_pct <= -0.010:
            logger.info("FLV stop loss: %.2f%% for %s", pnl_pct * 100, self.symbol)
            return True

        if order_book.spread_bps < self.spread_expansion_threshold / 2.0:
            logger.info("FLV spread normalized: %.1fbps for %s",
                        order_book.spread_bps, self.symbol)
            return True

        if self._last_topology is not None and not self._last_topology.super_void_detected:
            logger.info("FLV TPE void closed for %s", self.symbol)
            return True

        if (
            self.position_side == "sell"
            and self._last_topology is not None
            and not self._last_topology.structural_collapse
        ):
            logger.info("FLV structural collapse reversed — exiting sell for %s", self.symbol)
            return True

        if (
            self._last_toxicity_alert is not None
            and self._last_toxicity_alert.regime >= ToxicityRegime.TOXIC
        ):
            logger.warning("FLV toxicity spike %s — exiting for %s",
                           self._last_toxicity_alert.regime.name, self.symbol)
            return True

        return False

    def _generate_entry_signal(self, order_book: OrderBookSnapshot) -> StrategySignal:
        """
        Generate entry signal.

        Direction:
          structural_collapse only (no super_void) -> sell
          super_void (with or without collapse) -> buy

        Confidence:
          coherence_score * 0.40 + persistence_score * 0.30
          + 0.20 if super_void + 0.10 if collapse, capped 0.95
        """
        current_price = order_book.mid_price

        tpe_void = (
            self._last_topology is not None and self._last_topology.super_void_detected
        )
        tpe_collapse = (
            self._last_topology is not None and self._last_topology.structural_collapse
        )

        side = "sell" if (tpe_collapse and not tpe_void) else "buy"

        confidence = 0.0
        if self._last_topology is not None:
            confidence += self._last_topology.coherence_score * 0.40
            confidence += self._last_topology.persistence_score * 0.30
            if tpe_void:
                confidence += 0.20
            if tpe_collapse:
                confidence += 0.10
        confidence = min(0.95, confidence)

        base_size = self._calculate_position_size(current_price)
        position_size = base_size * self.kelly_multiplier

        signal = StrategySignal(
            strategy=SleeveType.FLV.value,
            symbol=self.symbol,
            side=side,
            confidence=confidence,
            quantity=position_size,
            price=current_price,
            exchange_ts_ns=order_book.exchange_ts_ns,
            reason=(
                f"tpe_void={tpe_void}, tpe_collapse={tpe_collapse}, "
                f"spread={order_book.spread_bps:.1f}bps"
            ),
            metadata={
                "spread_bps": order_book.spread_bps,
                "tpe_coherence": (
                    self._last_topology.coherence_score if self._last_topology else 0.0
                ),
                "tpe_persistence": (
                    self._last_topology.persistence_score if self._last_topology else 0.0
                ),
                "tpe_betti_0": self._last_topology.betti_0 if self._last_topology else 0,
                "tpe_betti_1": self._last_topology.betti_1 if self._last_topology else 0,
                "super_void": tpe_void,
                "structural_collapse": tpe_collapse,
                "tpe_confidence": (
                    self._last_topology.confidence if self._last_topology else 0.0
                ),
                "toxicity_regime": (
                    self._last_toxicity_alert.regime.name
                    if self._last_toxicity_alert else "UNKNOWN"
                ),
                "macro_pause_active": self._macro_pause_active,
            },
        )

        self.entry_price = current_price
        self.entry_time_ns = order_book.exchange_ts_ns
        self.position_size = position_size
        self.position_side = side
        self.hold_bars = 0
        self.status = LiquidityVoidStatus.ENTERED

        logger.info(
            "FLV ENTRY: %s @ %.4f side=%s size=%.6f confidence=%.2f",
            self.symbol, current_price, side, position_size, confidence,
        )
        return signal

    def _generate_exit_signal(
        self, price: float, timestamp_ns: int, reason: str
    ) -> Optional[StrategySignal]:
        """Generate exit signal. State read before reset."""
        if self.entry_price is None or self.position_size < EPS:
            return None

        pnl_pct = (
            (price - self.entry_price) / (self.entry_price + EPS)
            if self.position_side == "buy"
            else (self.entry_price - price) / (self.entry_price + EPS)
        )
        self.pnl = self.position_size * self.entry_price * pnl_pct

        self._trade_count += 1
        if self.pnl > 0:
            self._win_count += 1
        self._total_pnl += self.pnl

        exit_side = "sell" if self.position_side == "buy" else "buy"

        signal = StrategySignal(
            strategy=SleeveType.FLV.value,
            symbol=self.symbol,
            side=exit_side,
            confidence=0.85,
            quantity=self.position_size,
            price=price,
            exchange_ts_ns=timestamp_ns,
            reason=reason,
            metadata={
                "entry_price": self.entry_price,
                "exit_price": price,
                "pnl_pct": pnl_pct,
                "pnl_usd": self.pnl,
                "hold_bars": self.hold_bars,
                "position_side": self.position_side,
                "reason": reason,
            },
        )

        logger.info(
            "FLV EXIT: %s @ %.4f PnL=%.2f%% ($%.2f) reason=%s",
            self.symbol, price, pnl_pct * 100, self.pnl, reason,
        )

        # Reset AFTER signal construction
        self.exit_price = price
        self.exit_time_ns = timestamp_ns
        self.entry_price = None
        self.entry_time_ns = None
        self.position_size = 0.0
        self.position_side = "buy"
        self.hold_bars = 0
        self.status = LiquidityVoidStatus.CLOSED

        return signal

    def _force_exit(self) -> None:
        """
        Emergency state reset only. Does not emit a signal.
        NOT called from update_macro_state(). NOT called in normal operation.
        """
        self.status = LiquidityVoidStatus.CLOSED
        self.entry_price = None
        self.entry_time_ns = None
        self.position_size = 0.0
        self.position_side = "buy"
        self.hold_bars = 0
        logger.warning("FLV _force_exit: state reset without signal for %s", self.symbol)

    def _calculate_position_size(self, price: float) -> float:
        """Base position size before kelly scaling."""
        if price <= EPS:
            return 0.0

        max_risk_usd = 20_000.0 * 0.01
        stop_distance = 0.010

        base_size = max_risk_usd / (price * stop_distance + EPS)

        if self._last_topology is not None:
            if self._last_topology.super_void_detected:
                base_size *= 1.20
            elif self._last_topology.structural_collapse:
                base_size *= 1.10

        return min(0.5, base_size)

    def get_performance(self) -> Dict[str, Any]:
        """Get strategy performance metrics."""
        return {
            "symbol": self.symbol,
            "trade_count": self._trade_count,
            "win_count": self._win_count,
            "win_rate": self._win_count / max(self._trade_count, 1),
            "total_pnl": self._total_pnl,
            "avg_pnl": self._total_pnl / max(self._trade_count, 1),
            "status": self.status.value,
            "in_position": self.status == LiquidityVoidStatus.ENTERED,
            "hold_bars": self.hold_bars,
            "entry_price": self.entry_price,
            "position_side": self.position_side,
            "macro_kill_active": self._macro_kill_active,
            "macro_pause_active": self._macro_pause_active,
            "toxicity_regime": (
                self._last_toxicity_alert.regime.name
                if self._last_toxicity_alert else "UNKNOWN"
            ),
            "tpe_super_void": (
                self._last_topology.super_void_detected if self._last_topology else False
            ),
            "tpe_structural_collapse": (
                self._last_topology.structural_collapse if self._last_topology else False
            ),
            "tpe_coherence": (
                self._last_topology.coherence_score if self._last_topology else 0.0
            ),
            "tpe_confidence": (
                self._last_topology.confidence if self._last_topology else 0.0
            ),
        }

    def reset(self) -> None:
        """Reset all mutable state. Config and symbol preserved."""
        self.status = LiquidityVoidStatus.INACTIVE
        self.entry_price = None
        self.entry_time_ns = None
        self.exit_price = None
        self.exit_time_ns = None
        self.position_size = 0.0
        self.position_side = "buy"
        self.pnl = 0.0
        self.hold_bars = 0
        self._entry_signal_time_ns = None
        self._last_toxicity_alert = None
        self._last_topology = None
        self._macro_kill_active = False
        self._macro_pause_active = False
        self._trade_count = 0
        self._win_count = 0
        self._total_pnl = 0.0
        logger.info("LiquidityVoidStrategy reset for %s", self.symbol)