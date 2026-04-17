"""
Master Execution Orchestrator - The "Air Traffic Control" for Poverty Killer

REJECTED-DUAL-AUTHORITY — Board ruling 2026-04-15.
This file is NOT a plausible co-equal future owner of the runtime spine.
It MUST NOT be wired. It MUST NOT be repaired toward wiring.

REJECTION BASIS (irreconcilable with live spine):
1. Instantiates own SignalFusion(config) at line 324 — creates a second independent
   fusion brain alongside main.py:SovereignHeartbeat.signal_fusion. No reconciliation
   path exists. Two caches, two FusionDecisions, one market feed = irresolvable split.
2. Contains internal PaperBroker class (line 105) — duplicates app/execution/paper_broker.py
   (SovereignPaperBroker). Internal broker has no order lifecycle, no fill engine,
   no cancel path, no reconciliation. Not the same contract.
3. Bypasses OrderRouter entirely — calls self.paper_broker.execute() directly.
   The live spine is: ExecutionEngine → OrderRouter → SovereignPaperBroker.
   MasterOrchestrator skips all three.
4. Position tracking is an internal dict — not the live ExecutionEngine position state.

LIVE SPINE (authoritative):
    main.py:SovereignHeartbeat → ExecutionEngine → OrderRouter → SovereignPaperBroker

RETAINED FOR: reference only. Do not maintain. Do not repair. Do not wire.
Board may delete at any time.

Signal_fusion call sites were repaired (Board-authorized pass) before this ruling.
Those repairs are preserved in case any logic is extracted for reference purposes.
"""

import logging
import time
import threading
import queue
from decimal import Decimal, getcontext
from typing import Dict, Optional, Any, List, Tuple
from dataclasses import dataclass
from collections import deque
from datetime import datetime

# Decimal precision for orchestrator math
getcontext().prec = 28

# Repo-truth imports
from app.models import (
    OrderBookSnapshot, Candle, OrderRequest, StrategySignal,
    PortfolioSnapshot, PhysicalVerification
)
from app.models.enums import RegimeType, SleeveType
from app.models.contracts import StaleDataBlock, DivergenceBlock
from app.models.entropy_score import EntropyScore

from app.brain.signal_fusion import SignalFusion
from app.brain.toxicity_engine import ToxicityEngine, ToxicityAlert
from app.brain.topological_engine import TopologicalEngine
from app.brain.insider_signal_engine import (
    InsiderSignalEngine,
    InsiderObservation,
    InsiderSignalSnapshot,
    ObservationDirection,
    ObservationSourceType,
)
from app.brain.entropy_decoder import EntropyDecoder
from app.brain.whale_zone_engine import WhaleZoneEngine, WhalePresenceZone
from app.strategies.liquidity_void import LiquidityVoidStrategy
from app.strategies.shadow_front import ShadowFrontStrategy
from app.risk.safety import SafetyGate
from app.risk.kill_switch import KillSwitch, KillSwitchState
from app.risk.unified_risk import UnifiedRiskAuthority, UnifiedRiskResult, UnifiedRiskDecision
from app.risk.position_sizing import PositionSizingEngine, PositionSizeResult
from app.execution.masking_layer import MaskingLayer, MaskedOrder

# Instrument registry for size validation (imported but not modified)
from app.instrument_registry import InstrumentRegistry

logger = logging.getLogger(__name__)

# Constants for fallback behavior (explicit, non-arbitrary)
DEFAULT_LIQUIDITY_USD: float = 100_000.0  # $100k default when no order book
DEFAULT_VOLATILITY: Decimal = Decimal('0.01')  # 1% default volatility
MIN_VOLATILITY: Decimal = Decimal('0.005')  # 0.5% floor
MAX_VOLATILITY: Decimal = Decimal('0.05')  # 5% cap
MIN_PRICE_HISTORY: int = 10  # Minimum samples for volatility calculation
VOLATILITY_WINDOW: int = 20  # Rolling window for volatility
RETURNS_MIN_SAMPLES: int = 5  # Minimum returns for std dev
DEFAULT_ENTROPY: float = 0.5  # Neutral entropy when not available


@dataclass
class EventPacket:
    """Atomic event packet for serialized processing."""
    event_type: str  # "order_book", "candle", "trade", "signal"
    data: Any
    exchange_ts_ns: int
    receive_ts_ns: int  # MONITORING ONLY - not used in authoritative decisions
    processing_start_ns: int = 0
    processing_end_ns: int = 0

    __slots__ = ("event_type", "data", "exchange_ts_ns", "receive_ts_ns",
                 "processing_start_ns", "processing_end_ns")


class PaperBroker:
    """
    High-fidelity paper broker with realistic slippage and fees.
    This is simulation-only; live trading uses different path.
    """

    def __init__(self, config: Any):
        self.config = config
        self.base_slippage_bps = config.execution.base_slippage_bps
        self.market_impact_factor = config.execution.market_impact_factor
        self.taker_fee_bps = config.execution.taker_fee_bps
        self.maker_fee_bps = config.execution.maker_fee_bps

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
        slippage = self.base_slippage_bps
        notional = size * price
        depth_ratio = notional / max(market_depth, 1.0)
        size_impact = self.market_impact_factor * (depth_ratio ** 1.5) * 10000
        slippage += size_impact
        vol_impact = volatility * 50
        slippage += vol_impact
        if is_open or is_close:
            slippage *= 2.0
        if side == "buy":
            slippage *= 1.1
        return min(100.0, slippage)

    def calculate_fees(self, size: float, price: float, side: str, order_type: str) -> float:
        notional = size * price
        fee_bps = self.taker_fee_bps if order_type == "market" else self.maker_fee_bps
        return notional * (fee_bps / 10000)

    def execute(self, order: OrderRequest, market_data: Dict[str, Any]) -> Tuple[float, float, float, float]:
        price = market_data.get("price", order.limit_price or 0)
        volatility = market_data.get("volatility", 0.01)
        depth = market_data.get("market_depth", 100000.0)
        is_open = market_data.get("is_market_open", False)
        is_close = market_data.get("is_market_close", False)

        slippage_bps = self.calculate_slippage(
            size=order.quantity,
            price=price,
            side=order.side,
            volatility=volatility,
            market_depth=depth,
            is_open=is_open,
            is_close=is_close
        )

        if order.side == "buy":
            fill_price = price * (1 + slippage_bps / 10000)
        else:
            fill_price = price * (1 - slippage_bps / 10000)

        fees = self.calculate_fees(order.quantity, fill_price, order.side, order.order_type)

        self._order_history.append({
            "order_id": order.id,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "fill_price": fill_price,
            "slippage_bps": slippage_bps,
            "fees": fees,
            "timestamp": datetime.utcnow().isoformat()  # MONITORING ONLY
        })

        self._total_fees += fees
        self._total_slippage += slippage_bps * order.quantity * fill_price / 10000

        return fill_price, order.quantity, fees, slippage_bps

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_orders": len(self._order_history),
            "total_fees": self._total_fees,
            "total_slippage_usd": self._total_slippage,
            "avg_slippage_bps": self._total_slippage / max(len(self._order_history), 1) if self._order_history else 0
        }


class HeartbeatMonitor:
    """
    Heartbeat monitor for main loop health.

    IMPORTANT: This is MONITORING ONLY. Uses wall-clock for telemetry.
    Does NOT affect authoritative bot decisions.
    """

    def __init__(self, max_latency_ms: int = 10, alert_callback: Optional[callable] = None):
        self.max_latency_ms = max_latency_ms
        self.alert_callback = alert_callback
        self._last_heartbeat_ns = 0
        self._latency_history = deque(maxlen=1000)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        logger.info(f"HeartbeatMonitor initialized: max_latency={max_latency_ms}ms")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("HeartbeatMonitor started")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("HeartbeatMonitor stopped")

    def heartbeat(self, timestamp_ns: int) -> None:
        """Record heartbeat timestamp (monitoring only)."""
        self._last_heartbeat_ns = timestamp_ns

    def _monitor_loop(self) -> None:
        """Monitoring loop - uses wall-clock for telemetry only."""
        while self._running:
            current_ns = time.time_ns()  # MONITORING ONLY
            if self._last_heartbeat_ns > 0:
                latency_ns = current_ns - self._last_heartbeat_ns
                latency_ms = latency_ns / 1_000_000
                self._latency_history.append(latency_ms)
                if latency_ms > self.max_latency_ms:
                    avg_latency = sum(self._latency_history) / len(self._latency_history) if self._latency_history else 0
                    logger.warning(f"HEARTBEAT ALERT: Latency {latency_ms:.2f}ms > {self.max_latency_ms}ms")
                    if self.alert_callback:
                        try:
                            self.alert_callback(latency_ms, avg_latency)
                        except Exception as e:
                            logger.error(f"Alert callback failed: {e}")
            time.sleep(0.1)

    def get_stats(self) -> Dict[str, Any]:
        """Get monitoring statistics (telemetry only, not authoritative)."""
        return {
            "max_latency_ms": max(self._latency_history) if self._latency_history else 0,
            "avg_latency_ms": sum(self._latency_history) / len(self._latency_history) if self._latency_history else 0,
            "samples": len(self._latency_history)
        }


class CachedRiskState:
    """Cached risk state from the last authoritative evaluation."""

    def __init__(self):
        self.last_result: Optional[UnifiedRiskResult] = None
        self.last_timestamp_ns: int = 0
        self.last_symbol: Optional[str] = None

    def update(self, result: UnifiedRiskResult, timestamp_ns: int, symbol: str) -> None:
        self.last_result = result
        self.last_timestamp_ns = timestamp_ns
        self.last_symbol = symbol

    def get_for_display(self, symbol: str) -> Optional[UnifiedRiskResult]:
        """Get cached result for display (monitoring only, not authoritative)."""
        if self.last_symbol == symbol and self.last_result:
            return self.last_result
        return None


class MasterOrchestrator:
    """
    Master Execution Orchestrator - DORMANT candidate surface.

    NOT the single authority. NOT wired. NOT in live path.
    Live authority is main.py:SovereignHeartbeat.

    SignalFusion — LIVE CONTRACT (repaired):
        Live API: update_*(payload: Any, timestamp_ns: int),
                  fuse(current_ts_ns: int),
                  get_last_fusion() -> Optional[FusionDecision].
        All 7 broken call sites repaired.
        Regime detection not yet wired — (RegimeType.UNKNOWN, 0.0) placeholder.
        Missing ingest paths (separate Board items): shans, physical, toxicity.

    Authoritative decisions use deterministic timestamps from events (preserved).
    Monitoring/status uses cached state, not fresh recomputation (preserved).
    """

    def __init__(self, config: Any, symbol: str, kill_switch: KillSwitch):
        """
        Initialize master orchestrator.

        Args:
            config: Configuration object
            symbol: Trading symbol
            kill_switch: Kill switch instance (authoritative)
        """
        self.config = config
        self.symbol = symbol
        self._kill_switch = kill_switch

        # Event queue for serialized processing
        self._event_queue = queue.Queue(maxsize=10000)

        # Components
        self.signal_fusion = SignalFusion(config)
        self.toxicity_engine = ToxicityEngine(symbol=symbol)
        self.safety_gate = SafetyGate(config)
        self.masking_layer = MaskingLayer(exchange="kraken")
        self.paper_broker = PaperBroker(config)
        self.heartbeat_monitor = HeartbeatMonitor(max_latency_ms=10)

        # Repaired authorities (closed files, treated as canonical)
        self.insider_engine = InsiderSignalEngine()
        self.position_sizing = PositionSizingEngine(config)
        self.unified_risk = UnifiedRiskAuthority()

        # NEW: Entropy decoder (structural coherence intelligence)
        self.entropy_decoder = EntropyDecoder()

        # NEW: Whale zone engine (accumulation structure context)
        self.whale_zone_engine = WhaleZoneEngine(config)

        # TopologicalEngine — feeds FLV with real TPE signals
        self.tpe_engine = TopologicalEngine(symbol=symbol)

        # LiquidityVoidStrategy — wired to receive TPE, toxicity, and macro overlays
        self.flv_strategy = LiquidityVoidStrategy(config=config, symbol=symbol)

        # NEW: ShadowFrontStrategy — flagship alpha, receives updates
        self.shadow_front = ShadowFrontStrategy(config, symbol)

        # Initialize instrument registry for size validation
        InstrumentRegistry.initialize()

        # State
        self._last_order_book: Optional[OrderBookSnapshot] = None
        self._last_portfolio: Optional[PortfolioSnapshot] = None
        self._last_whale_score = None
        self._last_sentiment = None
        self._last_entropy: Optional[EntropyScore] = None
        self._last_macro = None
        self._last_regime = RegimeType.UNKNOWN
        self._last_whale_zone: Optional[WhalePresenceZone] = None
        self._running = False
        self._lock = threading.Lock()

        # Risk state from external sources
        self._stale_data_blocks: List[StaleDataBlock] = []
        self._divergence_blocks: List[DivergenceBlock] = []
        self._hard_flat_triggered: bool = False

        # Position tracking (atomic)
        self._open_positions: Dict[str, Dict] = {}
        self._position_lock = threading.Lock()

        # Price history for volatility calculation (rolling window)
        self._price_history: deque = deque(maxlen=VOLATILITY_WINDOW * 2)
        self._last_price: float = 0.0

        # Cached risk state for monitoring (NOT authoritative)
        self._cached_risk = CachedRiskState()

        logger.info(f"MasterOrchestrator initialized for {symbol}")
        logger.info("  Repaired authorities integrated: kill_switch, unified_risk, position_sizing, insider_engine")
        logger.info("  Intelligence integration: entropy_decoder, whale_zone_engine, shadow_front")
        logger.info("  Authoritative decisions use deterministic timestamps only")
        logger.info("  Monitoring/status uses cached state, not fresh recomputation")

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

    def update_risk_state(
        self,
        stale_data_blocks: List[StaleDataBlock],
        divergence_blocks: List[DivergenceBlock],
        hard_flat_triggered: bool = False
    ) -> None:
        """
        Update risk state from external risk truth.

        Args:
            stale_data_blocks: Current stale data blocks
            divergence_blocks: Current divergence blocks
            hard_flat_triggered: Whether hard flat mode is active
        """
        with self._lock:
            self._stale_data_blocks = stale_data_blocks
            self._divergence_blocks = divergence_blocks
            self._hard_flat_triggered = hard_flat_triggered

    def process_order_book(self, order_book: OrderBookSnapshot) -> None:
        """Process order book update."""
        packet = EventPacket(
            event_type="order_book",
            data=order_book,
            exchange_ts_ns=order_book.exchange_ts_ns,
            receive_ts_ns=time.time_ns()  # MONITORING ONLY
        )
        self._enqueue_packet(packet)

    def process_candle(self, candle: Candle) -> None:
        """Process candle update."""
        # Update price history for volatility calculation
        self._price_history.append(candle.close)
        self._last_price = candle.close

        packet = EventPacket(
            event_type="candle",
            data=candle,
            exchange_ts_ns=candle.exchange_ts_ns,
            receive_ts_ns=time.time_ns()  # MONITORING ONLY
        )
        self._enqueue_packet(packet)

    def process_trade(self, size: float, price: float, side: int, timestamp_ns: int) -> None:
        """Process trade update."""
        packet = EventPacket(
            event_type="trade",
            data={"size": size, "price": price, "side": side},
            exchange_ts_ns=timestamp_ns,
            receive_ts_ns=time.time_ns()  # MONITORING ONLY
        )
        self._enqueue_packet(packet)

    def _enqueue_packet(self, packet: EventPacket) -> None:
        """Enqueue packet for processing (non-blocking)."""
        try:
            self._event_queue.put_nowait(packet)
        except queue.Full:
            logger.error(f"Event queue full! Dropping packet: {packet.event_type}")

    def process_events(self) -> None:
        """Process events from queue in serial order."""
        while True:
            try:
                packet = self._event_queue.get_nowait()
            except queue.Empty:
                break

            packet.processing_start_ns = time.time_ns()  # MONITORING ONLY
            self._process_packet(packet)
            packet.processing_end_ns = time.time_ns()  # MONITORING ONLY

            processing_latency_ns = packet.processing_end_ns - packet.processing_start_ns
            if processing_latency_ns > 10_000_000:
                logger.warning(f"Processing latency: {processing_latency_ns / 1_000_000:.2f}ms for {packet.event_type}")

    def _process_packet(self, packet: EventPacket) -> None:
        """Process a single packet in serial order."""
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
        """Process order book packet with FLV strategy integration."""
        order_book = packet.data
        exchange_ts_ns = packet.exchange_ts_ns

        # Update toxicity engine
        self.toxicity_engine.update_toxicity(exchange_ts_ns)

        # Compute TPE signal from order book
        tpe_signal = self.tpe_engine.analyze(order_book)

        # Feed FLV push-update surfaces in dependency order
        self.flv_strategy.update_topology(tpe_signal)
        self.flv_strategy.update_toxicity(self.toxicity_engine.get_last_alert())
        self.flv_strategy.update_macro_state(self._last_macro)
        flv_signal = self.flv_strategy.update_order_book(order_book)

        if flv_signal is not None:
            logger.info(
                "FLV signal received: %s %s @ %.4f conf=%.2f",
                flv_signal.side, flv_signal.symbol,
                flv_signal.price or 0.0, flv_signal.confidence,
            )

        self._last_order_book = order_book
        self.heartbeat_monitor.heartbeat(exchange_ts_ns)

    def _process_candle_packet(self, packet: EventPacket) -> None:
        """Process candle packet with fusion and order generation."""
        candle = packet.data
        exchange_ts_ns = packet.exchange_ts_ns

        # Update whale flow — update_whale(payload, timestamp_ns) mutates cache, returns None
        self.signal_fusion.update_whale(candle, exchange_ts_ns)

        # Update regime — regime detection engine not wired; UNKNOWN keeps cache fresh (300s TTL)
        self.signal_fusion.update_regime((RegimeType.UNKNOWN, 0.0), exchange_ts_ns)

        # NEW: Update whale zone engine with candle data
        self.whale_zone_engine.update(
            symbol=self.symbol,
            close=candle.close,
            high=candle.high,
            low=candle.low,
            volume=candle.volume,
            vwap=candle.typical_price,
            exchange_ts_ns=exchange_ts_ns
        )
        self._last_whale_zone = self.whale_zone_engine.get_zone(self.symbol)

        # NEW: Update entropy decoder (structural coherence intelligence)
        raw_entropy = getattr(candle, 'entropy', DEFAULT_ENTROPY)
        entropy_score = self.entropy_decoder.update(
            symbol=self.symbol,
            exchange_ts_ns=exchange_ts_ns,
            raw_entropy=raw_entropy
        )
        self._last_entropy = entropy_score
        # update_entropy(payload, timestamp_ns) — live API
        self.signal_fusion.update_entropy(entropy_score, exchange_ts_ns)

        # ShadowFront strategy updates
        # Sentiment velocity — would come from sentiment engine; default to 0 if not available
        sentiment_velocity = getattr(candle, 'sentiment_velocity', 0.0)
        self.shadow_front.update_sentiment(sentiment_velocity, exchange_ts_ns)

        # Macro signal engine not wired — _last_macro stays None; flv uses it as-is

        # Toxicity state
        toxicity_alert = self.toxicity_engine.get_last_alert()
        self.shadow_front.update_toxicity_state(toxicity_alert)

        # Fuse signals — live API: fuse(current_ts_ns: int)
        fusion = self.signal_fusion.fuse(exchange_ts_ns)

        # Generate order if attack mode AND unified risk allows
        if fusion.attack_mode and fusion.preferred_sleeve:
            self._generate_order_with_risk_gating(fusion, candle.close, exchange_ts_ns)

        self.heartbeat_monitor.heartbeat(exchange_ts_ns)

    def _process_trade_packet(self, packet: EventPacket) -> None:
        """
        Process trade packet with insider engine integration.

        Insider urgency is consumed DIRECTLY from the repaired engine's
        authoritative urgency property. No local recomputation.
        """
        trade = packet.data
        exchange_ts_ns = packet.exchange_ts_ns

        # Quick kill switch check before processing (uses deterministic timestamp)
        if self._kill_switch.is_killed(exchange_ts_ns):
            logger.debug(f"Kill switch active, skipping trade processing for {self.symbol}")
            return

        # Update toxicity engine with trade data
        self.toxicity_engine.update_trade(
            size=trade["size"],
            price=trade["price"],
            side=trade["side"],
            timestamp_ns=exchange_ts_ns
        )

        # --- Insider Signal Engine Integration ---
        side_val = trade.get("side", 0)
        direction = ObservationDirection.BUY if side_val > 0 else (
            ObservationDirection.SELL if side_val < 0 else ObservationDirection.UNKNOWN
        )

        size = trade.get("size", 0.0)
        price = trade.get("price", 0.0)
        intensity = min(1.0, size / 100000.0)
        notional_weight = min(1.0, (size * price) / 1_000_000.0)

        observation = InsiderObservation(
            observation_id=f"trade_{exchange_ts_ns}_{self.symbol}",
            timestamp_ns=exchange_ts_ns,
            symbol=self.symbol,
            entity_id=f"exchange_{self.symbol}",
            direction=direction,
            intensity=Decimal(str(intensity)),
            notional_weight=Decimal(str(notional_weight)),
            source_reliability=Decimal('0.7'),
            event_proximity_weight=Decimal('0.5'),
            novelty_weight=Decimal('0.5'),
            corroboration_weight=Decimal('0.5'),
            invalidation_weight=Decimal('0.0'),
            source_type=ObservationSourceType.FLOW,
            tags=("trade",),
        )

        snapshot = self.insider_engine.ingest_observation(observation)

        # Consume the engine's authoritative urgency directly
        if snapshot and snapshot.active and snapshot.confidence > Decimal('0.3'):
            urgency = float(snapshot.urgency)
            urgency = min(2.0, max(0.0, urgency))
            self.signal_fusion.update_insider(urgency, exchange_ts_ns)
            logger.debug(
                "Insider urgency updated from engine: %s urgency=%.3f",
                self.symbol, urgency
            )

        self.heartbeat_monitor.heartbeat(exchange_ts_ns)

    def _calculate_liquidity_usd(self) -> float:
        """
        Calculate liquidity depth from order book if available.

        Fallback: DEFAULT_LIQUIDITY_USD ($100k) when no order book.
        This is a conservative estimate for initial conditions.
        """
        if self._last_order_book:
            bid_depth, ask_depth = self._last_order_book.depth_at_levels(10)
            mid = self._last_order_book.mid_price or 1.0
            return float(bid_depth + ask_depth) * mid
        return DEFAULT_LIQUIDITY_USD

    def _calculate_volatility(self) -> Decimal:
        """
        Calculate rolling volatility from price history.

        Uses annualized volatility from daily returns.
        Falls back to DEFAULT_VOLATILITY (1%) with bounded range [0.5%, 5%].
        """
        if len(self._price_history) < MIN_PRICE_HISTORY:
            return DEFAULT_VOLATILITY

        prices = list(self._price_history)[-VOLATILITY_WINDOW:]
        if len(prices) < 2:
            return DEFAULT_VOLATILITY

        # Calculate returns
        returns = []
        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                ret = (prices[i] - prices[i-1]) / prices[i-1]
                returns.append(ret)

        if len(returns) < RETURNS_MIN_SAMPLES:
            return DEFAULT_VOLATILITY

        # Standard deviation of returns
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        volatility = (variance ** 0.5) * (252 ** 0.5)  # Annualized

        # Clamp to reasonable range
        vol = max(float(MIN_VOLATILITY), min(float(MAX_VOLATILITY), volatility))
        return Decimal(str(vol))

    def _calculate_exposure_pct(self) -> Decimal:
        """Calculate current exposure percentage from open positions."""
        if not self._open_positions:
            return Decimal('0')

        total_exposure = Decimal('0')
        for pos in self._open_positions.values():
            quantity = Decimal(str(pos.get("quantity", 0)))
            price = Decimal(str(pos.get("entry_price", 0)))
            total_exposure += quantity * price

        capital = Decimal(str(self._get_current_capital()))
        if capital <= 0:
            return Decimal('0')

        return total_exposure / capital

    def _get_current_capital(self) -> float:
        """Get current capital from portfolio or config default."""
        if self._last_portfolio:
            return float(self._last_portfolio.total_equity) if hasattr(self._last_portfolio, 'total_equity') else self.config.initial_capital
        return self.config.initial_capital

    def _get_kelly_multiplier(self) -> Decimal:
        """
        Get current Kelly multiplier.

        Derivation: Based on attack mode from last fusion decision.
        Mapping is explicit and bounded:
        - Attack mode (confidence > threshold): 0.85 (aggressive)
        - Safe mode: 0.40 (conservative)
        """
        last_fusion = self.signal_fusion.get_last_fusion()
        is_attack = last_fusion.attack_mode if last_fusion else False
        return Decimal('0.85') if is_attack else Decimal('0.4')

    def _get_toxicity_score(self) -> Decimal:
        """Get current toxicity score as Decimal."""
        alert = self.toxicity_engine.get_last_alert()
        if alert:
            return Decimal(str(alert.toxicity_score))
        return Decimal('0')

    def _get_min_order_size(self, symbol: str) -> float:
        """
        Get minimum order size from instrument registry.

        Fallback: instrument-specific heuristics when registry lookup fails.
        These heuristics are conservative estimates for major instruments.
        """
        spec = InstrumentRegistry.get_instrument(symbol)
        if spec:
            return spec.min_size

        # Fallback heuristics (conservative estimates)
        if symbol in ("BTC/USD", "ETH/USD"):
            return 0.0001  # 0.0001 BTC/ETH minimum
        elif symbol in ("AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL"):
            return 1.0  # 1 share minimum
        else:
            return 0.001  # Generic minimum

    def _generate_order_with_risk_gating(self, fusion: Any, price: float, timestamp_ns: int) -> None:
        """
        Generate and execute order with full risk gating.

        This is the SINGLE AUTHORITATIVE ORDER GENERATION PATH.
        All risk evaluation uses deterministic timestamps from events.

        Integrates:
        1. Kill switch check (deterministic, uses timestamp_ns)
        2. Entropy gating (structural coherence check using real EntropyScore fields)
        3. Whale zone structural context
        4. Unified risk evaluation (deterministic, uses timestamp_ns)
        5. Position sizing (using repaired engine)
        6. Safety gate (final approval)
        7. Execution (paper broker)
        8. Cache result for monitoring

        CRITICAL FIX: Order side is determined ONCE and propagated truthfully
        through safety gate, execution, and position storage.
        """
        # ============================================
        # LEVEL 1: KILL SWITCH CHECK (Deterministic)
        # ============================================
        if self._kill_switch.is_killed(timestamp_ns):
            kill_state = self._kill_switch.get_state()
            logger.warning(f"Kill switch active ({kill_state}), order rejected for {self.symbol}")
            return

        # ============================================
        # LEVEL 1.5: ENTROPY GATING (Structural coherence)
        # ============================================
        # EntropyScore has: is_collapsed (bool), confidence (Decimal)
        # No collapse_quality field — use only what exists
        if self._last_entropy:
            if self._last_entropy.is_collapsed and self._last_entropy.confidence > Decimal('0.7'):
                logger.warning(f"Entropy collapse detected (conf={self._last_entropy.confidence:.2f}), order rejected for {self.symbol}")
                return

        # ============================================
        # LEVEL 2: DETERMINE ORDER SIDE (Single source of truth)
        # ============================================
        # Map preferred sleeve to order side
        # Shadow-Front typically buys, FLV can buy or sell based on signal
        if fusion.preferred_sleeve == "shadow_front":
            order_side = "buy"
        elif fusion.preferred_sleeve == "liquidity_void":
            # FLV side comes from its signal metadata if available
            order_side = "buy"  # Default, will be overridden by FLV signal if present
        else:
            order_side = "buy"  # Default for other strategies

        # Override from FLV signal if available
        if fusion.preferred_sleeve == "liquidity_void" and hasattr(fusion, 'flv_side_override'):
            order_side = fusion.flv_side_override

        # ============================================
        # LEVEL 2.5: WHALE ZONE STRUCTURAL CONTEXT
        # ============================================
        # If whale zone is active and confidence is high, boost sizing slightly
        zone_multiplier = Decimal('1.0')
        if self._last_whale_zone and self._last_whale_zone.confidence > 0.7:
            if self._last_whale_zone.presence or self._last_whale_zone.proximity > 0.5:
                zone_multiplier = Decimal('1.1')  # 10% boost for being in accumulation zone
                logger.debug(f"Whale zone active: confidence={self._last_whale_zone.confidence:.2f}, boost={zone_multiplier}")

        # ============================================
        # LEVEL 3: UNIFIED RISK EVALUATION (Deterministic)
        # ============================================
        with self._lock:
            toxicity_score = self._get_toxicity_score()
            exposure_pct = self._calculate_exposure_pct()

            risk_result = self.unified_risk.evaluate_for_symbol(
                timestamp_ns=timestamp_ns,
                kill_switch=self._kill_switch,
                stale_data_blocks=self._stale_data_blocks,
                divergence_blocks=self._divergence_blocks,
                symbol=self.symbol,
                hard_flat_triggered=self._hard_flat_triggered,
                regime=self._last_regime,
                toxicity_score=toxicity_score,
                current_exposure_pct=exposure_pct
            )

            # Cache for monitoring
            self._cached_risk.update(risk_result, timestamp_ns, self.symbol)

        if not risk_result.allowed:
            logger.warning(f"Unified risk denied order for {self.symbol}: {risk_result.reason}")
            return

        # ============================================
        # LEVEL 4: POSITION SIZING (Deterministic)
        # ============================================
        sizing_multiplier = risk_result.sizing_multiplier * zone_multiplier

        # Map sleeve type to strategy enum
        sleeve_map = {
            "shadow_front": SleeveType.SHADOW_FRONT,
            "liquidity_void": SleeveType.FLV,
            "entropy_decoder": SleeveType.ENTROPY_DECODER,
            "gamma_front": SleeveType.GAMMA_FRONT,
            "sector_rotation": SleeveType.SECTOR_ROTATION,
        }
        strategy = sleeve_map.get(fusion.preferred_sleeve, SleeveType.SHADOW_FRONT)

        # Get current capital and volatility
        current_capital = Decimal(str(self._get_current_capital()))
        volatility = self._calculate_volatility()
        kelly = self._get_kelly_multiplier()

        # Calculate position size using repaired engine
        try:
            size_result = self.position_sizing.calculate_position_size(
                capital_usd=current_capital,
                confidence=Decimal(str(fusion.confidence)),
                volatility=volatility,
                regime=self._last_regime,
                strategy=strategy,
                price=Decimal(str(price)),
                kelly_multiplier=kelly,
                stop_loss_pct=Decimal('0.015')  # Default 1.5% stop (configurable)
            )
        except Exception as e:
            logger.error(f"Position sizing failed: {e}")
            size_result = None

        if size_result and size_result.quantity > 0:
            raw_quantity = size_result.quantity
            # Apply unified risk sizing multiplier and zone multiplier
            quantity = float(raw_quantity * sizing_multiplier)
        else:
            # Fallback: minimum size based on instrument
            quantity = self._get_min_order_size(self.symbol)

        # Ensure minimum size (already enforced by _get_min_order_size)
        min_size = self._get_min_order_size(self.symbol)
        quantity = max(quantity, min_size)

        # ============================================
        # LEVEL 5: CHECK EXISTING POSITION
        # ============================================
        with self._position_lock:
            if self.symbol in self._open_positions:
                logger.debug(f"Already in position for {self.symbol}")
                return

        # ============================================
        # LEVEL 6: SAFETY GATE APPROVAL (using determined side)
        # ============================================
        if self._last_portfolio:
            order_intent = OrderRequest(
                id=f"order_{timestamp_ns}",
                symbol=self.symbol,
                side=order_side,
                quantity=quantity,
                strategy=fusion.preferred_sleeve,
                confidence=fusion.confidence,
                exchange_ts_ns=timestamp_ns
            )
            approved, reason = self.safety_gate.approve_order(
                order=order_intent,
                portfolio=self._last_portfolio
            )

            if not approved:
                logger.warning(f"Safety gate rejected: {reason}")
                return

        # ============================================
        # LEVEL 7: EXECUTION (using determined side consistently)
        # ============================================
        volatility_float = float(volatility)
        masked = self.masking_layer.mask_order(quantity, volatility_float)

        # Create execution order with the SAME side determined above
        exec_order = OrderRequest(
            id=f"order_{timestamp_ns}",
            symbol=self.symbol,
            side=order_side,
            quantity=masked.masked_size,
            strategy=fusion.preferred_sleeve,
            confidence=fusion.confidence,
            exchange_ts_ns=timestamp_ns
        )

        fill_price, fill_qty, fees, slippage = self.paper_broker.execute(
            order=exec_order,
            market_data={"price": price, "volatility": volatility_float}
        )

        # Store position with the correct side
        with self._position_lock:
            self._open_positions[self.symbol] = {
                "entry_price": fill_price,
                "quantity": fill_qty,
                "side": order_side,
                "strategy": fusion.preferred_sleeve,
                "timestamp_ns": timestamp_ns,
                "fees": fees,
                "slippage_bps": slippage,
                "risk_multiplier": float(sizing_multiplier),
                "risk_decision": risk_result.decision.value,
                "zone_confidence": self._last_whale_zone.confidence if self._last_whale_zone else 0.0,
                "entropy_confidence": float(self._last_entropy.confidence) if self._last_entropy else 0.5
            }

        logger.info(
            f"ORDER EXECUTED: {fusion.preferred_sleeve} {self.symbol} "
            f"side={order_side} @ {fill_price:.2f}, "
            f"qty={fill_qty:.4f}, slippage={slippage:.2f}bps, fees=${fees:.2f}, "
            f"risk_multiplier={float(sizing_multiplier):.2f}, "
            f"zone_boost={float(zone_multiplier):.2f}"
        )

    def close_position(self, symbol: str, price: float, timestamp_ns: int) -> None:
        """Close a position."""
        with self._position_lock:
            if symbol not in self._open_positions:
                return

            position = self._open_positions[symbol]
            entry_price = position["entry_price"]
            quantity = position["quantity"]
            side = position.get("side", "buy")

            # Opposite side to close
            close_side = "sell" if side == "buy" else "buy"
            pnl = quantity * (price - entry_price) if side == "buy" else quantity * (entry_price - price)
            pnl_percent = (price - entry_price) / entry_price if side == "buy" else (entry_price - price) / entry_price

            logger.info(f"POSITION CLOSED: {symbol} side={side} close={close_side} @ {price:.2f}, PnL={pnl:.2f} ({pnl_percent:.2%})")
            del self._open_positions[symbol]

    def update_portfolio(self, portfolio: PortfolioSnapshot) -> None:
        """Update portfolio snapshot."""
        self._last_portfolio = portfolio

    def get_status(self) -> Dict[str, Any]:
        """
        Get orchestrator status for monitoring.

        IMPORTANT: This reports CACHED authoritative state.
        It does NOT perform fresh risk evaluation.
        For authoritative decisions, use the order generation path.
        """
        with self._lock:
            # Use cached risk result, NOT fresh evaluation
            cached_risk = self._cached_risk.get_for_display(self.symbol)

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
                # Intelligence status
                "entropy_last_score": float(self._last_entropy.entropy) if self._last_entropy else None,
                "entropy_collapsed": self._last_entropy.is_collapsed if self._last_entropy else None,
                "entropy_confidence": float(self._last_entropy.confidence) if self._last_entropy else None,
                "whale_zone_active": self._last_whale_zone.presence if self._last_whale_zone else False,
                "whale_zone_confidence": self._last_whale_zone.confidence if self._last_whale_zone else 0.0,
                "shadow_front_in_position": self.shadow_front.is_in_position() if hasattr(self.shadow_front, 'is_in_position') else False,
                # Cached authoritative risk state (not recomputed)
                "unified_risk_allowed": cached_risk.allowed if cached_risk else None,
                "unified_risk_decision": cached_risk.decision.value if cached_risk else None,
                "unified_risk_multiplier": float(cached_risk.sizing_multiplier) if cached_risk else None,
                "unified_risk_reason": cached_risk.reason if cached_risk else None,
                # Kill switch state (cached, not recomputed)
                "kill_switch_state": self._kill_switch.get_state().value if hasattr(self._kill_switch.get_state(), 'value') else str(self._kill_switch.get_state()),
                # Current exposure (computed, not cached)
                "current_exposure_pct": float(self._calculate_exposure_pct()),
                "current_volatility": float(self._calculate_volatility()),
                "current_regime": self._last_regime.value if hasattr(self._last_regime, 'value') else str(self._last_regime),
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
        self.insider_engine.reset()
        self.entropy_decoder.reset()
        self.whale_zone_engine.reset(self.symbol)
        self.shadow_front.reset()
        self._price_history.clear()
        self._cached_risk = CachedRiskState()
        self._last_entropy = None
        self._last_whale_zone = None

        logger.info(f"MasterOrchestrator reset for {self.symbol}")
