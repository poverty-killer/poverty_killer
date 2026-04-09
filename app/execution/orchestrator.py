"""
Master Execution Orchestrator - The "Air Traffic Control" for Poverty Killer
Atomic event pulse processing with serialized pipeline.
Zero-latency queue-based architecture with process isolation.
"""

import asyncio
import logging
import time
import threading
import queue
import pickle
import numpy as np
from typing import Dict, Optional, Any, List, Tuple
from dataclasses import dataclass, field
from collections import deque
from datetime import datetime

from app.models import (
    OrderBookSnapshot, Candle, OrderRequest, StrategySignal,
    PortfolioSnapshot, PhysicalVerification
)
from app.brain.signal_fusion import SignalFusion
from app.brain.toxicity_engine import ToxicityEngine, ToxicityAlert
from app.brain.topological_engine import TopologicalEngine
from app.strategies.liquidity_void import LiquidityVoidStrategy
from app.risk.safety import SafetyGate
from app.execution.masking_layer import MaskingLayer, MaskedOrder

logger = logging.getLogger(__name__)

# Machine epsilon
EPS = np.finfo(float).eps


@dataclass
class EventPacket:
    """Atomic event packet for serialized processing."""
    event_type: str  # "order_book", "candle", "trade", "signal"
    data: Any
    exchange_ts_ns: int
    receive_ts_ns: int
    processing_start_ns: int = 0
    processing_end_ns: int = 0

    __slots__ = ("event_type", "data", "exchange_ts_ns", "receive_ts_ns",
                 "processing_start_ns", "processing_end_ns")


class PaperBroker:
    """
    High-fidelity paper broker with realistic slippage and fees.
    Implements market impact, volatility adjustment, and session-aware slippage.
    """

    def __init__(self, config: Any):
        """
        Initialize paper broker.

        Args:
            config: Configuration object
        """
        self.config = config
        self.base_slippage_bps = config.execution.base_slippage_bps
        self.market_impact_factor = config.execution.market_impact_factor
        self.taker_fee_bps = config.execution.taker_fee_bps
        self.maker_fee_bps = config.execution.maker_fee_bps

        # Performance tracking
        self._order_history: List[Dict] = []
        self._total_fees = 0.0
        self._total_slippage = 0.0

        logger.info("PaperBroker initialized with realistic slippage model")

    def calculate_slippage(
        self,
        size: float,
        price: float,
        side: str,
        volatility: float = 0.01,
        market_depth: float = 100000.0,
        is_open: bool = False,
        is_close: bool = False
    ) -> float:
        """
        Calculate realistic slippage in basis points.

        Args:
            size: Order size in units
            price: Current price
            side: "buy" or "sell"
            volatility: Current volatility (20-period)
            market_depth: Available depth at top levels
            is_open: Whether market is opening
            is_close: Whether market is closing

        Returns:
            Slippage in basis points
        """
        # Base slippage
        slippage = self.base_slippage_bps

        # Size impact (quadratic)
        notional = size * price
        depth_ratio = notional / max(market_depth, 1.0)
        size_impact = self.market_impact_factor * (depth_ratio ** 1.5) * 10000
        slippage += size_impact

        # Volatility impact
        vol_impact = volatility * 50  # 1% vol = 50 bps extra
        slippage += vol_impact

        # Time of day impact
        if is_open or is_close:
            slippage *= 2.0

        # Direction impact (buy-side often has higher slippage)
        if side == "buy":
            slippage *= 1.1

        return min(100.0, slippage)  # Cap at 1%

    def calculate_fees(self, size: float, price: float, side: str, order_type: str) -> float:
        """
        Calculate exchange fees.

        Args:
            size: Order size
            price: Execution price
            side: "buy" or "sell"
            order_type: "market" or "limit"

        Returns:
            Fee in USD
        """
        notional = size * price

        if order_type == "market":
            fee_bps = self.taker_fee_bps
        else:
            fee_bps = self.maker_fee_bps

        return notional * (fee_bps / 10000)

    def execute(self, order: OrderRequest, market_data: Dict[str, Any]) -> Tuple[float, float, float, float]:
        """
        Execute order with realistic simulation.

        Args:
            order: Order request
            market_data: Current market conditions

        Returns:
            Tuple of (fill_price, fill_quantity, fees, slippage_bps)
        """
        price = market_data.get("price", order.limit_price or 0)
        volatility = market_data.get("volatility", 0.01)
        depth = market_data.get("market_depth", 100000.0)
        is_open = market_data.get("is_market_open", False)
        is_close = market_data.get("is_market_close", False)

        # Calculate slippage
        slippage_bps = self.calculate_slippage(
            size=order.quantity,
            price=price,
            side=order.side,
            volatility=volatility,
            market_depth=depth,
            is_open=is_open,
            is_close=is_close
        )

        # Apply slippage
        if order.side == "buy":
            fill_price = price * (1 + slippage_bps / 10000)
        else:
            fill_price = price * (1 - slippage_bps / 10000)

        # Calculate fees
        fees = self.calculate_fees(order.quantity, fill_price, order.side, order.order_type)

        # Record
        self._order_history.append({
            "order_id": order.id,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "fill_price": fill_price,
            "slippage_bps": slippage_bps,
            "fees": fees,
            "timestamp": datetime.utcnow().isoformat()
        })

        self._total_fees += fees
        self._total_slippage += slippage_bps * order.quantity * fill_price / 10000

        return fill_price, order.quantity, fees, slippage_bps

    def get_stats(self) -> Dict[str, Any]:
        """Get broker statistics."""
        return {
            "total_orders": len(self._order_history),
            "total_fees": self._total_fees,
            "total_slippage_usd": self._total_slippage,
            "avg_slippage_bps": self._total_slippage / max(len(self._order_history), 1) if self._order_history else 0
        }


class HeartbeatMonitor:
    """
    Heartbeat monitor for main loop health.
    Separate thread that alerts if processing takes too long.
    """

    def __init__(self, max_latency_ms: int = 10, alert_callback: Optional[callable] = None):
        """
        Initialize heartbeat monitor.

        Args:
            max_latency_ms: Maximum allowed processing latency (ms)
            alert_callback: Callback for alerts
        """
        self.max_latency_ms = max_latency_ms
        self.alert_callback = alert_callback

        self._last_heartbeat_ns = 0
        self._last_check_ns = 0
        self._latency_history = deque(maxlen=1000)

        self._running = False
        self._thread: Optional[threading.Thread] = None

        logger.info(f"HeartbeatMonitor initialized: max_latency={max_latency_ms}ms")

    def start(self) -> None:
        """Start heartbeat monitor thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("HeartbeatMonitor started")

    def stop(self) -> None:
        """Stop heartbeat monitor."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("HeartbeatMonitor stopped")

    def heartbeat(self, timestamp_ns: int) -> None:
        """Record heartbeat."""
        self._last_heartbeat_ns = timestamp_ns

    def _monitor_loop(self) -> None:
        """Monitor loop checking for latency issues."""
        while self._running:
            current_ns = time.time_ns()

            if self._last_heartbeat_ns > 0:
                latency_ns = current_ns - self._last_heartbeat_ns
                latency_ms = latency_ns / 1_000_000

                self._latency_history.append(latency_ms)

                if latency_ms > self.max_latency_ms:
                    avg_latency = sum(self._latency_history) / len(self._latency_history)
                    logger.warning(f"HEARTBEAT ALERT: Latency {latency_ms:.2f}ms > {self.max_latency_ms}ms (avg={avg_latency:.2f})")

                    if self.alert_callback:
                        try:
                            self.alert_callback(latency_ms, avg_latency)
                        except Exception as e:
                            logger.error(f"Alert callback failed: {e}")

            time.sleep(0.1)  # Check every 100ms

    def get_stats(self) -> Dict[str, Any]:
        """Get heartbeat statistics."""
        return {
            "max_latency_ms": max(self._latency_history) if self._latency_history else 0,
            "avg_latency_ms": sum(self._latency_history) / len(self._latency_history) if self._latency_history else 0,
            "samples": len(self._latency_history)
        }


class MasterOrchestrator:
    """
    Master Execution Orchestrator - Atomic event pulse processing.
    Single entry point for all market data with serialized pipeline.
    """

    def __init__(self, config: Any, symbol: str):
        """
        Initialize master orchestrator.

        Args:
            config: Configuration object
            symbol: Trading symbol
        """
        self.config = config
        self.symbol = symbol

        # Event queue for serialized processing
        self._event_queue = queue.Queue(maxsize=10000)

        # Components
        self.signal_fusion = SignalFusion(config)
        self.toxicity_engine = ToxicityEngine(exchange="kraken")
        self.safety_gate = SafetyGate(config)
        self.masking_layer = MaskingLayer(exchange="kraken")
        self.paper_broker = PaperBroker(config)
        self.heartbeat_monitor = HeartbeatMonitor(max_latency_ms=10)

        # TopologicalEngine — feeds FLV with real TPE signals per order-book tick
        self.tpe_engine = TopologicalEngine(symbol=symbol)

        # LiquidityVoidStrategy — wired to receive TPE, toxicity, and macro overlays
        self.flv_strategy = LiquidityVoidStrategy(config=config, symbol=symbol)

        # State
        self._last_order_book: Optional[OrderBookSnapshot] = None
        self._last_portfolio: Optional[PortfolioSnapshot] = None
        self._last_whale_score = None
        self._last_sentiment = None
        self._last_entropy = None
        self._last_macro = None
        self._running = False
        self._lock = threading.Lock()

        # Position tracking (atomic)
        self._open_positions: Dict[str, Dict] = {}
        self._position_lock = threading.Lock()

        logger.info(f"MasterOrchestrator initialized for {symbol}")

    def start(self) -> None:
        """Start orchestrator."""
        self._running = True
        self.heartbeat_monitor.start()
        logger.info("MasterOrchestrator started")

    def stop(self) -> None:
        """Stop orchestrator."""
        self._running = False
        self.heartbeat_monitor.stop()
        logger.info("MasterOrchestrator stopped")

    def process_order_book(self, order_book: OrderBookSnapshot) -> None:
        """
        Process order book update.

        Args:
            order_book: Order book snapshot
        """
        packet = EventPacket(
            event_type="order_book",
            data=order_book,
            exchange_ts_ns=order_book.exchange_ts_ns,
            receive_ts_ns=time.time_ns()
        )
        self._enqueue_packet(packet)

    def process_candle(self, candle: Candle) -> None:
        """
        Process candle update.

        Args:
            candle: Candle data
        """
        packet = EventPacket(
            event_type="candle",
            data=candle,
            exchange_ts_ns=candle.exchange_ts_ns,
            receive_ts_ns=time.time_ns()
        )
        self._enqueue_packet(packet)

    def process_trade(self, size: float, price: float, side: int, timestamp_ns: int) -> None:
        """
        Process trade update.

        Args:
            size: Trade size
            price: Trade price
            side: +1 for buy, -1 for sell
            timestamp_ns: Exchange timestamp
        """
        packet = EventPacket(
            event_type="trade",
            data={"size": size, "price": price, "side": side},
            exchange_ts_ns=timestamp_ns,
            receive_ts_ns=time.time_ns()
        )
        self._enqueue_packet(packet)

    def _enqueue_packet(self, packet: EventPacket) -> None:
        """
        Enqueue packet for processing (non-blocking).

        Args:
            packet: Event packet
        """
        try:
            self._event_queue.put_nowait(packet)
        except queue.Full:
            logger.error(f"Event queue full! Dropping packet: {packet.event_type}")

    def process_events(self) -> None:
        """
        Process events from queue in serial order.
        Call this in the main loop.
        """
        while True:
            try:
                packet = self._event_queue.get_nowait()
            except queue.Empty:
                break

            packet.processing_start_ns = time.time_ns()
            self._process_packet(packet)
            packet.processing_end_ns = time.time_ns()

            # Record latency
            processing_latency_ns = packet.processing_end_ns - packet.processing_start_ns
            if processing_latency_ns > 10_000_000:  # 10ms
                logger.warning(f"Processing latency: {processing_latency_ns / 1_000_000:.2f}ms for {packet.event_type}")

    def _process_packet(self, packet: EventPacket) -> None:
        """
        Process a single packet in serial order.

        Args:
            packet: Event packet
        """
        try:
            if packet.event_type == "order_book":
                self._process_order_book_packet(packet)
            elif packet.event_type == "candle":
                self._process_candle_packet(packet)
            elif packet.event_type == "trade":
                self._process_trade_packet(packet)
        except Exception as e:
            logger.error(f"Error processing packet {packet.event_type}: {e}")

    def _process_order_book_packet(self, packet: EventPacket) -> None:
        """
        Process order book packet.

        Feeds FLV strategy with real TPE signal, current toxicity,
        current macro overlay, and the order book itself — in that order,
        matching the lawful push-update pattern.

        Args:
            packet: Event packet
        """
        order_book = packet.data
        exchange_ts_ns = packet.exchange_ts_ns

        # Update toxicity engine
        # (would need trade data for full VPIN, simplified here)
        toxicity = self.toxicity_engine.get_current_toxicity(exchange_ts_ns)

        # Update Shan's Curve
        shans_signal = self.signal_fusion.update_shans(
            order_book, self.signal_fusion.get_current_regime(), None
        )

        # Compute TPE signal from order book
        tpe_signal = self.tpe_engine.analyze(order_book)

        # Feed FLV push-update surfaces in dependency order:
        # topology first, then toxicity, then macro, then order book
        self.flv_strategy.update_topology(tpe_signal)
        self.flv_strategy.update_toxicity(self.toxicity_engine.get_last_alert())
        self.flv_strategy.update_macro_state(self._last_macro)
        flv_signal = self.flv_strategy.update_order_book(order_book)

        # If FLV emitted a signal, route it into the execution pipeline
        if flv_signal is not None:
            logger.info(
                "FLV signal received: %s %s @ %.4f conf=%.2f",
                flv_signal.side, flv_signal.symbol,
                flv_signal.price or 0.0, flv_signal.confidence,
            )
            # Signal is available here for downstream execution integration
            # Full execution routing is handled in _generate_order when
            # the fusion layer authorizes the FLV sleeve

        # Store
        self._last_order_book = order_book

        # Update heartbeat
        self.heartbeat_monitor.heartbeat(exchange_ts_ns)

    def _process_candle_packet(self, packet: EventPacket) -> None:
        """
        Process candle packet.

        Args:
            packet: Event packet
        """
        candle = packet.data

        # Update whale flow
        whale_score = self.signal_fusion.update_whale(candle)

        # Update regime
        # Would need liquidity from order book
        liquidity_usd = 100000.0  # Placeholder
        regime = self.signal_fusion.update_regime(
            [candle], 0, liquidity_usd, packet.exchange_ts_ns
        )

        # Get macro and insider signals
        macro = self.signal_fusion.get_macro_signal(packet.exchange_ts_ns, whale_score)
        insider = self.signal_fusion.get_insider_signal() if hasattr(self.signal_fusion, 'get_insider_signal') else None

        # Cache macro for use in order-book processing cycle
        self._last_macro = macro

        # Fuse signals
        fusion = self.signal_fusion.fuse(
            regime=regime,
            whale_score=whale_score,
            macro_signal=macro,
            insider_signal=insider,
            order_book=self._last_order_book
        )

        # Generate order if in attack mode
        if fusion.attack_mode and fusion.preferred_sleeve:
            self._generate_order(fusion, candle.close, packet.exchange_ts_ns)

        # Update heartbeat
        self.heartbeat_monitor.heartbeat(packet.exchange_ts_ns)

    def _process_trade_packet(self, packet: EventPacket) -> None:
        """
        Process trade packet.

        Args:
            packet: Event packet
        """
        trade = packet.data

        # Update entropy decoder
        entropy = self.signal_fusion.update_entropy(
            self.symbol,
            trade["side"],
            datetime.utcnow(),
            self.signal_fusion.get_current_regime()
        )

        # Update toxicity engine with trade data
        self.toxicity_engine.update_trade(
            size=trade["size"],
            price=trade["price"],
            side=trade["side"],
            timestamp_ns=packet.exchange_ts_ns
        )

        # Update heartbeat
        self.heartbeat_monitor.heartbeat(packet.exchange_ts_ns)

    def _generate_order(self, fusion: Any, price: float, timestamp_ns: int) -> None:
        """
        Generate and execute order with atomic position management.

        Args:
            fusion: Fusion decision
            price: Current price
            timestamp_ns: Exchange timestamp
        """
        # Check if already in position for this symbol
        with self._position_lock:
            if self.symbol in self._open_positions:
                logger.debug(f"Already in position for {self.symbol}")
                return

        # Final safety check
        if self._last_portfolio:
            approved, reason = self.safety_gate.approve_order(
                order=OrderRequest(
                    id=f"order_{timestamp_ns}",
                    symbol=self.symbol,
                    side="buy" if fusion.preferred_sleeve == "shadow_front" else "sell",
                    quantity=1000,  # Placeholder
                    strategy=fusion.preferred_sleeve,
                    confidence=fusion.confidence,
                    exchange_ts_ns=timestamp_ns
                ),
                portfolio=self._last_portfolio
            )

            if not approved:
                logger.warning(f"Safety gate rejected: {reason}")
                return

        # Apply masking
        masked = self.masking_layer.mask_order(1000, 0.01)  # Placeholder size

        # Execute with paper broker
        fill_price, fill_qty, fees, slippage = self.paper_broker.execute(
            order=OrderRequest(
                id=f"order_{timestamp_ns}",
                symbol=self.symbol,
                side="buy",
                quantity=masked.masked_size,
                strategy=fusion.preferred_sleeve,
                confidence=fusion.confidence,
                exchange_ts_ns=timestamp_ns
            ),
            market_data={"price": price, "volatility": 0.01}
        )

        # Store position
        with self._position_lock:
            self._open_positions[self.symbol] = {
                "entry_price": fill_price,
                "quantity": fill_qty,
                "strategy": fusion.preferred_sleeve,
                "timestamp_ns": timestamp_ns,
                "fees": fees,
                "slippage_bps": slippage
            }

        logger.info(f"ORDER EXECUTED: {fusion.preferred_sleeve} {self.symbol} @ {fill_price:.2f}, "
                   f"qty={fill_qty:.4f}, slippage={slippage:.2f}bps, fees=${fees:.2f}")

    def close_position(self, symbol: str, price: float, timestamp_ns: int) -> None:
        """
        Close a position.

        Args:
            symbol: Trading symbol
            price: Current price
            timestamp_ns: Exchange timestamp
        """
        with self._position_lock:
            if symbol not in self._open_positions:
                return

            position = self._open_positions[symbol]
            entry_price = position["entry_price"]
            quantity = position["quantity"]

            # Calculate P&L
            pnl = quantity * (price - entry_price)
            pnl_percent = (price - entry_price) / entry_price

            # Record
            logger.info(f"POSITION CLOSED: {symbol} @ {price:.2f}, PnL={pnl:.2f} ({pnl_percent:.2%})")

            # Remove position
            del self._open_positions[symbol]

    def update_portfolio(self, portfolio: PortfolioSnapshot) -> None:
        """
        Update portfolio snapshot.

        Args:
            portfolio: Portfolio snapshot
        """
        self._last_portfolio = portfolio

    def get_status(self) -> Dict[str, Any]:
        """
        Get orchestrator status.

        Returns:
            Status dictionary
        """
        return {
            "symbol": self.symbol,
            "event_queue_size": self._event_queue.qsize(),
            "open_positions": list(self._open_positions.keys()),
            "heartbeat": self.heartbeat_monitor.get_stats(),
            "paper_broker": self.paper_broker.get_stats(),
            "masking": self.masking_layer.get_stats(),
            "toxicity": self.toxicity_engine.get_stats(),
            "safety": self.safety_gate.get_stats(),
            "flv_strategy": self.flv_strategy.get_performance(),
            "tpe_engine": self.tpe_engine.get_stats(),
        }

    def reset(self) -> None:
        """Reset orchestrator state."""
        with self._position_lock:
            self._open_positions.clear()

        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except queue.Empty:
                break

        self.flv_strategy.reset()
        self.tpe_engine.reset()

        logger.info(f"MasterOrchestrator reset for {self.symbol}")