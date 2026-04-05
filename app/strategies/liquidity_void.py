"""
Fractal Liquidity Void (FLV) - Crisis Sniper Strategy
Exploits liquidity voids during market crises with TPE integration.
Detects super-voids, structural collapse, and executes fast rebound trades.
HARDENED: TPE integration, toxicity awareness, macro-kill override.
"""

import logging
import numpy as np
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta

from app.models import (
    OrderBookSnapshot, StrategySignal, ToxicityAlert,
    MacroSignal, TopologicalSignal, LARSignal
)
from app.constants import SleeveType, RegimeType, LiquidityVoidStatus

logger = logging.getLogger(__name__)

# Machine epsilon
EPS = np.finfo(float).eps


class LiquidityVoidStrategy:
    """
    Fractal Liquidity Void (FLV) - Crisis sniper.
    Activates only in CRISIS regime or when super-void detected.
    Executes fast, controlled snap trades with hard time stops.
    """

    def __init__(self, config: Any, symbol: str):
        """
        Initialize FLV strategy.

        Args:
            config: Configuration object
            symbol: Trading symbol
        """
        self.config = config
        self.symbol = symbol
        self.status = LiquidityVoidStatus.INACTIVE

        # Strategy parameters - FIXED: use self.attribute
        self.max_hold_bars = config.strategies.flv_max_hold_bars
        self.kelly_multiplier = config.strategies.flv_kelly_multiplier
        self.volume_anomaly_threshold = config.strategies.flv_volume_anomaly_threshold
        self.spread_expansion_threshold = config.strategies.flv_spread_expansion_threshold

        # Position tracking
        self.entry_price: Optional[float] = None
        self.entry_time_ns: Optional[int] = None
        self.exit_price: Optional[float] = None
        self.exit_time_ns: Optional[int] = None
        self.position_size: float = 0.0
        self.pnl: float = 0.0
        self.hold_bars: int = 0

        # Signal tracking
        self._entry_signal_time_ns: Optional[int] = None
        self._last_toxicity_alert: Optional[ToxicityAlert] = None
        self._last_topology: Optional[TopologicalSignal] = None
        self._last_lar: Optional[LARSignal] = None
        self._macro_kill_active = False

        # Performance
        self._trade_count = 0
        self._win_count = 0
        self._total_pnl = 0.0

        logger.info(f"LiquidityVoidStrategy initialized for {symbol}: max_hold={self.max_hold_bars}, "
                   f"kelly_mult={self.kelly_multiplier}")

    def update_macro_state(self, macro_signal: Optional[MacroSignal]) -> None:
        """
        Update macro state from sentiment velocity.

        Args:
            macro_signal: Current macro signal
        """
        if macro_signal:
            self._macro_kill_active = macro_signal.macro_kill
            if self._macro_kill_active and self.status == LiquidityVoidStatus.ENTERED:
                logger.warning(f"MACRO-KILL ACTIVE - exiting FLV position for {self.symbol}")
                self._force_exit()

    def update_toxicity(self, toxicity_alert: Optional[ToxicityAlert]) -> None:
        """
        Update toxicity state.

        Args:
            toxicity_alert: Current toxicity alert
        """
        self._last_toxicity_alert = toxicity_alert

    def update_topology(self, topology: Optional[TopologicalSignal]) -> None:
        """
        Update topological state from TPE.

        Args:
            topology: Current topological signal
        """
        self._last_topology = topology

    def update_lar(self, lar: Optional[LARSignal]) -> None:
        """
        Update LAR state.

        Args:
            lar: Current LAR signal
        """
        self._last_lar = lar

    def update_order_book(self, order_book: OrderBookSnapshot) -> Optional[StrategySignal]:
        """
        Update with new order book and check for entry/exit.

        Args:
            order_book: Current order book snapshot

        Returns:
            StrategySignal if action needed, else None
        """
        # Macro-kill overrides everything
        if self._macro_kill_active:
            if self.status == LiquidityVoidStatus.ENTERED:
                return self._generate_exit_signal(order_book.mid_price, order_book.exchange_ts_ns, "macro_kill")
            return None

        # Check for entry conditions
        if self.status == LiquidityVoidStatus.INACTIVE or self.status == LiquidityVoidStatus.SCANNING:
            if self._should_enter(order_book):
                self._entry_signal_time_ns = order_book.exchange_ts_ns
                self.status = LiquidityVoidStatus.DETECTED
                return self._generate_entry_signal(order_book)

        # Check for exit conditions
        if self.status == LiquidityVoidStatus.ENTERED:
            if self._should_exit(order_book):
                return self._generate_exit_signal(order_book.mid_price, order_book.exchange_ts_ns, "exit_conditions")

        # Update hold bars counter
        if self.status == LiquidityVoidStatus.ENTERED:
            self.hold_bars += 1
            if self.hold_bars >= self.max_hold_bars:
                return self._generate_exit_signal(order_book.mid_price, order_book.exchange_ts_ns, "max_hold_reached")

        return None

    def _should_enter(self, order_book: OrderBookSnapshot) -> bool:
        """
        Determine if entry conditions are met.

        Args:
            order_book: Current order book

        Returns:
            True if should enter
        """
        # 1. TPE super-void detection (primary signal)
        tpe_void = False
        if self._last_topology and self._last_topology.super_void_detected:
            tpe_void = True
            logger.info(f"TPE super-void detected for {self.symbol}")

        # 2. LAR collapse detection (secondary signal)
        lar_collapse = False
        if self._last_lar and self._last_lar.is_collapsing:
            lar_collapse = True
            logger.info(f"LAR collapse detected for {self.symbol}")

        # 3. Spread expansion
        spread_wide = order_book.spread_bps > self.spread_expansion_threshold

        # 4. Volume anomaly (would come from trade feed)
        volume_anomaly = False  # Placeholder

        # 5. Toxicity - high toxicity means stand down
        if self._last_toxicity_alert and self._last_toxicity_alert.is_toxic:
            logger.debug(f"High toxicity - standing down for {self.symbol}")
            return False

        # Entry requires: (TPE void OR LAR collapse) AND spread wide
        if (tpe_void or lar_collapse) and spread_wide:
            logger.info(f"FLV entry conditions met for {self.symbol}: tpe_void={tpe_void}, "
                       f"lar_collapse={lar_collapse}, spread={order_book.spread_bps:.1f}bps")
            return True

        return False

    def _should_exit(self, order_book: OrderBookSnapshot) -> bool:
        """
        Determine if exit conditions are met.

        Args:
            order_book: Current order book

        Returns:
            True if should exit
        """
        if self.entry_price is None:
            return True

        current_price = order_book.mid_price
        pnl_percent = (current_price - self.entry_price) / self.entry_price

        # Take profit: +1.5% (FLV targets smaller, faster moves)
        if pnl_percent >= 0.015:
            logger.info(f"FLV take profit: {pnl_percent:.2%}")
            return True

        # Stop loss: -1.0% (tighter stop for FLV)
        if pnl_percent <= -0.01:
            logger.info(f"FLV stop loss: {pnl_percent:.2%}")
            return True

        # Spread normalization - exit when liquidity returns
        if order_book.spread_bps < self.spread_expansion_threshold / 2:
            logger.info(f"Spread normalized: {order_book.spread_bps:.1f}bps")
            return True

        # TPE void closed
        if self._last_topology and not self._last_topology.super_void_detected:
            logger.info("TPE void closed")
            return True

        # LAR collapse reversed
        if self._last_lar and not self._last_lar.is_collapsing:
            logger.info("LAR collapse reversed")
            return True

        # Toxicity spike - exit immediately
        if self._last_toxicity_alert and self._last_toxicity_alert.is_toxic:
            logger.warning(f"Toxicity spike during position - exiting")
            return True

        return False

    def _generate_entry_signal(self, order_book: OrderBookSnapshot) -> StrategySignal:
        """
        Generate entry signal.

        Args:
            order_book: Current order book

        Returns:
            StrategySignal
        """
        current_price = order_book.mid_price

        # Calculate position size (FLV uses half Kelly)
        base_size = self._calculate_position_size(current_price)
        position_size = base_size * self.kelly_multiplier

        # Determine direction based on void type
        side = "buy"  # FLV typically goes long on voids

        # If LAR indicates sell-side collapse, could go short
        if self._last_lar and self._last_lar.acceleration < -1.0:
            side = "sell"

        # Calculate confidence
        confidence = 0.0
        if self._last_topology and self._last_topology.super_void_detected:
            confidence += 0.5
        if self._last_lar and self._last_lar.is_collapsing:
            confidence += 0.3
        confidence = min(0.95, confidence)

        signal = StrategySignal(
            strategy=SleeveType.FLV,
            symbol=self.symbol,
            side=side,
            confidence=confidence,
            quantity=position_size,
            price=current_price,
            exchange_ts_ns=order_book.exchange_ts_ns,
            reason=f"tpe_void={self._last_topology.super_void_detected if self._last_topology else False}, "
                   f"lar_collapse={self._last_lar.is_collapsing if self._last_lar else False}",
            metadata={
                "spread_bps": order_book.spread_bps,
                "tpe_coherence": self._last_topology.coherence_score if self._last_topology else 0,
                "lar_acceleration": self._last_lar.acceleration if self._last_lar else 0,
                "super_void": self._last_topology.super_void_detected if self._last_topology else False
            }
        )

        # Update position tracking
        self.entry_price = current_price
        self.entry_time_ns = order_book.exchange_ts_ns
        self.position_size = position_size
        self.hold_bars = 0
        self.status = LiquidityVoidStatus.ENTERED

        logger.info(f"FLV ENTRY: {self.symbol} @ {current_price:.2f}, size={position_size:.4f}, "
                   f"side={side}, confidence={confidence:.2f}")

        return signal

    def _generate_exit_signal(self, price: float, timestamp_ns: int, reason: str) -> Optional[StrategySignal]:
        """
        Generate exit signal.

        Args:
            price: Current price
            timestamp_ns: Exchange timestamp
            reason: Exit reason

        Returns:
            StrategySignal or None
        """
        if self.entry_price is None or self.position_size == 0:
            return None

        # Calculate P&L
        if self.entry_price:
            pnl_percent = (price - self.entry_price) / self.entry_price
            self.pnl = self.position_size * (price - self.entry_price)
        else:
            pnl_percent = 0.0
            self.pnl = 0.0

        # Update performance tracking
        self._trade_count += 1
        if self.pnl > 0:
            self._win_count += 1
        self._total_pnl += self.pnl

        signal = StrategySignal(
            strategy=SleeveType.FLV,
            symbol=self.symbol,
            side="sell" if self.entry_price else "buy",
            confidence=0.8,
            quantity=self.position_size,
            price=price,
            exchange_ts_ns=timestamp_ns,
            reason=reason,
            metadata={
                "entry_price": self.entry_price,
                "exit_price": price,
                "pnl_percent": pnl_percent,
                "hold_bars": self.hold_bars,
                "reason": reason
            }
        )

        logger.info(f"FLV EXIT: {self.symbol} @ {price:.2f}, PnL={pnl_percent:.2%}, reason={reason}")

        # Reset position
        self.entry_price = None
        self.entry_time_ns = None
        self.position_size = 0.0
        self.hold_bars = 0
        self.status = LiquidityVoidStatus.CLOSED

        return signal

    def _force_exit(self) -> None:
        """Force exit on macro-kill."""
        self.status = LiquidityVoidStatus.CLOSED
        self.entry_price = None
        self.entry_time_ns = None
        self.position_size = 0.0
        self.hold_bars = 0
        logger.info(f"FLV force exit for {self.symbol} due to macro-kill")

    def _calculate_position_size(self, price: float) -> float:
        """
        Calculate position size with risk management.

        Args:
            price: Current price

        Returns:
            Position size in units
        """
        # Base size from available capital
        max_risk_usd = 20000.0 * 0.01  # $200 max risk

        # Stop distance in percentage (tighter for FLV)
        stop_distance = 0.01  # 1% stop

        # Position size based on risk
        base_size = max_risk_usd / (price * stop_distance)

        # Apply TPE confidence boost
        if self._last_topology and self._last_topology.super_void_detected:
            base_size *= 1.2

        # Apply LAR confidence boost
        if self._last_lar and self._last_lar.is_collapsing:
            base_size *= 1.1

        # Cap size
        max_size = 0.5  # Max 0.5 BTC for FLV
        return min(max_size, base_size)

    def get_performance(self) -> Dict[str, Any]:
        """Get strategy performance metrics."""
        win_rate = self._win_count / max(self._trade_count, 1)
        avg_pnl = self._total_pnl / max(self._trade_count, 1)

        return {
            "symbol": self.symbol,
            "trade_count": self._trade_count,
            "win_count": self._win_count,
            "win_rate": win_rate,
            "total_pnl": self._total_pnl,
            "avg_pnl": avg_pnl,
            "status": self.status.value,
            "in_position": self.status == LiquidityVoidStatus.ENTERED,
            "hold_bars": self.hold_bars,
            "entry_price": self.entry_price
        }

    def reset(self) -> None:
        """Reset strategy state."""
        self.status = LiquidityVoidStatus.INACTIVE
        self.entry_price = None
        self.entry_time_ns = None
        self.exit_price = None
        self.exit_time_ns = None
        self.position_size = 0.0
        self.pnl = 0.0
        self.hold_bars = 0
        self._entry_signal_time_ns = None
        self._trade_count = 0
        self._win_count = 0
        self._total_pnl = 0.0
        logger.info(f"LiquidityVoidStrategy reset for {self.symbol}")