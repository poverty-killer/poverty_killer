# FILE: app/symbol_runtime.py
# MODIFIED: Added ShansCurve ownership to existing SymbolRuntime
# Preserves all existing sentiment/whale logic exactly as shown
# Only adds shans_curve field + initialization + dependency injection

"""
PER-SYMBOL RUNTIME OWNERSHIP
Establishes lawful per-symbol state container for multi-symbol paper trading.

Each SymbolRuntime owns symbol-specific:
- Market data state (order book, candle, price, volatility)
- TPE signal
- Per-symbol engine instances (TopologicalEngine, ToxicityEngine, WhaleFlowEngine)
- Per-symbol strategy instance (ShadowFrontStrategy)
- Per-symbol sentiment (MarketSentimentProxy + SentimentVelocityEngine)
- Per-symbol ShansCurve (asymptotic liquidity exhaustion detector)

WHALE OVERLAY WIRING (2026-04-27):
    - Per-symbol WhaleFlowEngine created with config
    - update_whale_with_trade() calls engine.update() with real trade data
    - get_whale_score() converts WhaleFlowAlert to WhaleFlowScore for ShadowFront

SENTIMENT OVERLAY WIRING (2026-04-27):
    - Per-symbol MarketSentimentProxy derives sentiment from order books/trades
    - Per-symbol SentimentVelocityEngine processes sentiment into velocity
    - get_sentiment_velocity() returns current sentiment velocity value
    - Sentiment admission buffer prevents non-monotonic rejections while preserving
      the engine's deterministic monotonicity enforcement

PER-SYMBOL SHANS OWNERSHIP (2026-04-27):
    - Per-symbol ShansCurve instance prevents cross-symbol buffer contamination
    - Dependencies (risk_guard, data_validator, entropy_decoder) injected after creation
    - get_shans_buffer_len() returns current buffer size for diagnostics
"""

import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
from collections import deque

from app.models import OrderBookSnapshot, Candle
from app.brain.topological_engine import TopologicalEngine, TopologicalSignal
from app.brain.toxicity_engine import ToxicityEngine
from app.brain.shans_curve import ShansCurve
from app.brain.regime_detector import RegimeDetector
from app.brain.whale_flow_engine import WhaleFlowEngine, WhaleFlowAlert, WhaleDirection
from app.brain.market_sentiment_proxy import MarketSentimentProxy
from app.brain.sentiment_velocity import SentimentVelocityEngine
from app.models.market_data import WhaleFlowScore

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.strategies.shadow_front import ShadowFrontStrategy


def _whale_alert_to_score(alert: WhaleFlowAlert, symbol: str = "") -> WhaleFlowScore:
    """
    Bridge adapter: WhaleFlowAlert -> WhaleFlowScore.

    WhaleFlowAlert source fields used:
        direction: WhaleDirection (BUY=1, SELL=-1, NEUTRAL=0)
        confidence: float  -> score
        exchange_ts_ns: int
        abnormality_score: float [0,1]  -> z_score proxy (best available)
        avg_trade_size: float [0,1]     -> volume_anomaly proxy

    is_accumulating derived from BUY direction with confidence > 0.5.
    """
    score = alert.confidence
    is_accumulating = (alert.direction == WhaleDirection.BUY and alert.confidence > 0.5)

    return WhaleFlowScore(
        symbol=symbol,
        exchange_ts_ns=alert.exchange_ts_ns,
        score=score,
        z_score=alert.abnormality_score,     # Best proxy from WhaleFlowAlert
        volume_anomaly=alert.avg_trade_size, # Normalized avg trade size [0,1]
        is_accumulating=is_accumulating,
        whale_zone_low=None,
        whale_zone_high=None,
    )


@dataclass
class SentimentUpdate:
    """Pending sentiment update awaiting monotonic admission."""
    sentiment_value: float
    timestamp_ns: int


@dataclass
class SymbolRuntime:
    """
    Owns all symbol-specific runtime state.
    One instance per active symbol in MainLoop.
    
    Does NOT own global components (SignalFusion, StrategyRouter, 
    DecisionCompiler, ExecutionEngine, OrderRouter).
    """
    symbol: str
    
    # Per-symbol market data state
    last_order_book: Optional[OrderBookSnapshot] = None
    last_candle: Optional[Candle] = None
    last_price: float = 0.0
    current_volatility: float = 0.20
    
    # Per-symbol TPE signal
    last_tpe_signal: Optional[TopologicalSignal] = None
    
    # Per-symbol engine instances
    topological_engine: Optional[TopologicalEngine] = None
    toxicity_engine: Optional[ToxicityEngine] = None
    whale_flow_engine: Optional[WhaleFlowEngine] = None
    shans_curve: Optional[ShansCurve] = None
    regime_detector: Optional[RegimeDetector] = None
    
    # Per-symbol sentiment components
    sentiment_proxy: Optional[MarketSentimentProxy] = None
    sentiment_velocity_engine: Optional[SentimentVelocityEngine] = None
    
    # Per-symbol strategy instances
    shadow_front_strategy: Optional[Any] = None
    gamma_front_strategy: Optional[Any] = None
    liquidity_void_strategy: Optional[Any] = None
    sector_rotation_strategy: Optional[Any] = None

    # OBSERVE-ONLY (Stage 2-B): last raw StrategySignal emitted by dormant sleeves.
    # Bounded by overwrite (only most-recent kept). NOT dispatched, NOT adapted to
    # StrategyVote, NOT inserted into any decision pipeline. Diagnostic visibility only.
    last_liquidity_void_observed_signal: Optional[Any] = None
    last_sector_rotation_observed_signal: Optional[Any] = None

    # OBSERVE-ONLY (Stage 2-C): last StrategyVote synthesized by the approved
    # adapter from a dormant-sleeve signal. Bounded by overwrite. NOT passed to
    # DecisionCompiler / StrategyRouter / SignalFusion / ExecutionEngine /
    # OrderRouter / RiskGuard / PositionSizing. Telemetry/inspection only.
    last_liquidity_void_observed_vote: Optional[Any] = None
    last_sector_rotation_observed_vote: Optional[Any] = None

    # OBSERVE-ONLY (Stage 2-D3 / Option C): consumed marker for LiquidityVoid
    # paper-dispatch. Tracks the decision_uuid of the most-recent LV observation
    # admitted by candle dispatch under the buffered pre-candle scheme. Prevents
    # the same observation from being re-admitted on subsequent candles.
    # Bounded by overwrite. Diagnostic-only — no order authority.
    last_liquidity_void_consumed_decision_uuid: Optional[str] = None

    # Last whale alert (cached for overlay conversion)
    last_whale_alert: Optional[WhaleFlowAlert] = None
    
    # Cached sentiment velocity for ShadowFront overlay
    _cached_sentiment_velocity: float = 0.0
    
    # Sentiment admission buffer (handles out-of-order timestamps)
    _sentiment_buffer: deque = field(default_factory=lambda: deque(maxlen=100))
    _last_sent_timestamp_ns: int = 0
    _sentiment_buffer_max_size: int = 100
    _sentiment_lock: threading.Lock = field(default_factory=threading.Lock)

    # Internal state
    initialized: bool = False
    last_update_timestamp_ns: int = 0
    
    def __post_init__(self):
        self.initialized = False
        if not hasattr(self, '_sentiment_buffer') or self._sentiment_buffer is None:
            self._sentiment_buffer = deque(maxlen=self._sentiment_buffer_max_size)
        if not hasattr(self, '_last_sent_timestamp_ns'):
            self._last_sent_timestamp_ns = 0
        if not hasattr(self, '_sentiment_lock') or self._sentiment_lock is None:
            self._sentiment_lock = threading.Lock()
    
    def initialize_engines(self, config: Any, safety_gate: Any) -> None:
        """Initialize per-symbol engines with configuration."""
        from app.strategies.shadow_front import ShadowFrontStrategy
        
        self.topological_engine = TopologicalEngine(symbol=self.symbol)
        self.toxicity_engine = ToxicityEngine(symbol=self.symbol)
        self.whale_flow_engine = WhaleFlowEngine(config=config)
        self.regime_detector = RegimeDetector(config=config, symbol=self.symbol)
        self.sentiment_proxy = MarketSentimentProxy(symbol=self.symbol)
        self.sentiment_velocity_engine = SentimentVelocityEngine()
        self.shadow_front_strategy = ShadowFrontStrategy(config=config, symbol=self.symbol)

        from app.strategies.gamma_front import GammaFrontStrategy
        self.gamma_front_strategy = GammaFrontStrategy(config=config, symbol=self.symbol)

        from app.strategies.liquidity_void import LiquidityVoidStrategy
        self.liquidity_void_strategy = LiquidityVoidStrategy(config=config, symbol=self.symbol)

        from app.strategies.sector_rotation import SectorRotationStrategy
        self.sector_rotation_strategy = SectorRotationStrategy(config=config, symbol=self.symbol)

        # PER-SYMBOL SHANSCURVE: Create instance with None dependencies
        # Dependencies will be injected via set_shans_dependencies() after creation
        self.shans_curve = ShansCurve(
            risk_guard=None,
            safety_gate=safety_gate,
            data_validator=None,
            entropy_decoder=None,
        )
        
        self.initialized = True
    
    def set_shans_dependencies(self, risk_guard, data_validator, entropy_decoder) -> None:
        """
        Inject ShansCurve dependencies after MainLoop initialization.
        
        ShansCurve requires risk_guard, data_validator, entropy_decoder which are
        global/shared across symbols. This method injects them after per-symbol
        ShansCurve instances are created.
        """
        if self.shans_curve:
            self.shans_curve.risk_guard = risk_guard
            self.shans_curve.data_validator = data_validator
            self.shans_curve.entropy_decoder = entropy_decoder
    
    def get_shans_buffer_len(self) -> int:
        """Get current ShansCurve buffer length for diagnostics."""
        if self.shans_curve:
            return len(self.shans_curve._p)
        return 0
    
    def update_order_book(self, order_book: OrderBookSnapshot) -> None:
        """Update order book state for this symbol."""
        self.last_order_book = order_book
        if order_book.mid_price > 0:
            self.last_price = order_book.mid_price
        self.last_update_timestamp_ns = order_book.exchange_ts_ns
        
        # Update sentiment proxy with order book imbalance
        if self.sentiment_proxy:
            bid_depth, ask_depth = order_book.depth_at_levels(10)
            self.sentiment_proxy.update_from_order_book(bid_depth, ask_depth, order_book.exchange_ts_ns)
            
            # Update price for momentum
            if order_book.mid_price > 0:
                self.sentiment_proxy.update_from_price(order_book.mid_price, order_book.exchange_ts_ns)
    
    def update_candle(self, candle: Candle) -> None:
        """Update candle and derive volatility."""
        self.last_candle = candle
        if candle.close > 0:
            self.last_price = candle.close
        self.last_update_timestamp_ns = candle.exchange_ts_ns
        self._compute_volatility(candle)
        
        # Update sentiment proxy with price
        if self.sentiment_proxy and candle.close > 0:
            self.sentiment_proxy.update_from_price(candle.close, candle.exchange_ts_ns)
    
    def update_trade(self, price: float, timestamp_ns: int) -> None:
        """Update trade price for this symbol (basic)."""
        if price > 0:
            self.last_price = price
        self.last_update_timestamp_ns = timestamp_ns
    
    def update_trade_with_volumes(self, buy_volume: float, sell_volume: float, 
                                   timestamp_ns: int) -> None:
        """
        Update trade with volume breakdown for sentiment proxy.
        
        Args:
            buy_volume: Buy volume in this update
            sell_volume: Sell volume in this update
            timestamp_ns: Exchange timestamp
        """
        if self.sentiment_proxy:
            self.sentiment_proxy.update_from_trade(buy_volume, sell_volume, timestamp_ns)
        
        self.last_update_timestamp_ns = timestamp_ns
    
    def update_whale_with_trade(self, buy_volume: float, sell_volume: float,
                                 trade_sizes: List[float], timestamp_ns: int,
                                 price: float = 0.0) -> Optional[WhaleFlowAlert]:
        """Update per-symbol whale engine with trade data.

        price is the mark price for the trade and is required by the
        WhaleFlowEngine to convert raw asset trade sizes into USD notional
        for whale-tier normalization. Default 0.0 preserves backward
        compatibility for legacy callers but must not be relied on in
        production — main_loop.on_trade_with_whale always supplies it.
        """
        if self.whale_flow_engine:
            alert = self.whale_flow_engine.update(
                buy_volume=buy_volume,
                sell_volume=sell_volume,
                trade_sizes=trade_sizes,
                exchange_ts_ns=timestamp_ns,
                price=price,
            )
            self.last_whale_alert = alert
            return alert
        return None
    
    def get_whale_score(self) -> Optional[WhaleFlowScore]:
        """Get WhaleFlowScore for ShadowFront overlay. Returns None if no alert."""
        if self.last_whale_alert is None:
            return None
        return _whale_alert_to_score(self.last_whale_alert, symbol=self.symbol)
    
    def _admit_sentiment_update(self, sentiment_value: float, timestamp_ns: int) -> bool:
        """
        Admit sentiment update to engine if timestamp monotonic.
        
        Buffers out-of-order updates and processes them in order when possible.
        Preserves the engine's deterministic monotonicity requirement.
        
        Returns:
            True if update was sent to engine (either immediately or after buffer processing)
        """
        if not self.sentiment_velocity_engine:
            return False
        
        # Ensure buffer exists (defensive)
        if not hasattr(self, '_sentiment_buffer') or self._sentiment_buffer is None:
            self._sentiment_buffer = deque(maxlen=self._sentiment_buffer_max_size)
        if not hasattr(self, '_last_sent_timestamp_ns'):
            self._last_sent_timestamp_ns = 0
        
        with self._sentiment_lock:
            # Buffer the new update
            self._sentiment_buffer.append(SentimentUpdate(sentiment_value, timestamp_ns))

            # Sort buffer by timestamp (oldest first) for deterministic processing
            sorted_buffer = sorted(self._sentiment_buffer, key=lambda x: x.timestamp_ns)

            # Process buffered updates in order, skipping duplicates and ensuring monotonicity
            updates_sent = 0
            for update in sorted_buffer:
                if update.timestamp_ns <= self._last_sent_timestamp_ns:
                    # Duplicate or older timestamp - skip (honest degradation)
                    continue

                # Send to engine
                self.sentiment_velocity_engine.update_sentiment(update.sentiment_value, update.timestamp_ns)
                self._last_sent_timestamp_ns = update.timestamp_ns
                updates_sent += 1

            # Clear processed updates from buffer
            if updates_sent > 0:
                # Keep only updates with timestamps > last_sent
                remaining = deque(maxlen=self._sentiment_buffer_max_size)
                for u in self._sentiment_buffer:
                    if u.timestamp_ns > self._last_sent_timestamp_ns:
                        remaining.append(u)
                self._sentiment_buffer = remaining

        return updates_sent > 0
    
    def update_sentiment_engine(self, exchange_ts_ns: int) -> None:
        """
        Update sentiment velocity engine with current proxy value.
        
        Uses admission buffer to handle out-of-order timestamps.
        """
        if not self.sentiment_proxy or not self.sentiment_velocity_engine:
            return
        
        sentiment_value = self.sentiment_proxy.get_sentiment()
        
        # Admit through buffer (handles monotonicity)
        self._admit_sentiment_update(sentiment_value, exchange_ts_ns)
        
        # Get current velocity for ShadowFront overlay
        current_vector = self.sentiment_velocity_engine.get_current_vector()
        if current_vector:
            self._cached_sentiment_velocity = current_vector.velocity
        else:
            self._cached_sentiment_velocity = 0.0
    
    def get_sentiment_velocity(self) -> float:
        """Get current sentiment velocity for ShadowFront overlay."""
        return self._cached_sentiment_velocity
    
    def update_regime_multiplier(self, regime) -> None:
        """Update sentiment proxy with regime multiplier."""
        if self.sentiment_proxy:
            self.sentiment_proxy.update_regime_multiplier(regime)
    
    def update_toxicity_multiplier_from_alert(self) -> None:
        """Update sentiment proxy with toxicity multiplier from engine."""
        if self.sentiment_proxy and self.toxicity_engine:
            alert = self.toxicity_engine.get_last_alert()
            if alert:
                self.sentiment_proxy.update_toxicity_multiplier(alert.regime)
    
    def update_tpe_signal(self, signal: TopologicalSignal) -> None:
        """Update topological persistence entropy signal."""
        self.last_tpe_signal = signal

    def record_observed_signal(self, sleeve_name: str, signal: Any) -> None:
        """
        OBSERVE-ONLY (Stage 2-B): record the most-recent raw StrategySignal
        emitted by a dormant sleeve. Bounded by overwrite. Diagnostic-only —
        the recorded signal is NOT dispatched, NOT adapted to StrategyVote,
        NOT routed to DecisionCompiler / StrategyRouter / SignalFusion /
        ExecutionEngine. No order authority is created by this record.
        """
        if sleeve_name == "liquidity_void":
            self.last_liquidity_void_observed_signal = signal
        elif sleeve_name == "sector_rotation":
            self.last_sector_rotation_observed_signal = signal

    def record_observed_vote(self, sleeve_name: str, vote: Any) -> None:
        """
        OBSERVE-ONLY (Stage 2-C): record the most-recent StrategyVote
        synthesized by an approved adapter from a dormant-sleeve signal.
        Bounded by overwrite. Telemetry/inspection only — the recorded vote
        is NOT passed to DecisionCompiler / StrategyRouter / SignalFusion /
        ExecutionEngine / OrderRouter / RiskGuard / PositionSizing. No order
        authority is created by this record.
        """
        if sleeve_name == "liquidity_void":
            self.last_liquidity_void_observed_vote = vote
        elif sleeve_name == "sector_rotation":
            self.last_sector_rotation_observed_vote = vote
    
    def _compute_volatility(self, candle: Candle) -> None:
        if candle.close <= 0:
            self.current_volatility = 0.20
            return
        daily_range = (candle.high - candle.low) / candle.close
        self.current_volatility = max(0.05, min(0.80, daily_range * 15.0))
    
    def get_mid_price(self) -> float:
        if self.last_order_book:
            return self.last_order_book.mid_price
        return self.last_price
    
    def is_ready(self) -> bool:
        return self.last_order_book is not None and self.last_price > 0.0
    
    def get_status(self) -> Dict[str, Any]:
        sentiment_state = None
        if self.sentiment_proxy:
            proxy_state = self.sentiment_proxy.get_state()
            sentiment_state = {
                "composite": proxy_state.composite_sentiment,
                "velocity": self._cached_sentiment_velocity,
                "buffer_size": len(self._sentiment_buffer) if hasattr(self, '_sentiment_buffer') and self._sentiment_buffer else 0
            }
        
        return {
            "symbol": self.symbol,
            "initialized": self.initialized,
            "has_order_book": self.last_order_book is not None,
            "has_candle": self.last_candle is not None,
            "last_price": self.last_price,
            "current_volatility": self.current_volatility,
            "last_update_timestamp_ns": self.last_update_timestamp_ns,
            "topological_engine_ready": self.topological_engine is not None,
            "toxicity_engine_ready": self.toxicity_engine is not None,
            "whale_flow_engine_ready": self.whale_flow_engine is not None,
            "shans_curve_ready": self.shans_curve is not None,
            "shans_buffer_len": self.get_shans_buffer_len(),
            "sentiment_proxy_ready": self.sentiment_proxy is not None,
            "sentiment_velocity_ready": self.sentiment_velocity_engine is not None,
            "last_whale_score": self.last_whale_alert.confidence if self.last_whale_alert else 0.0,
            "last_whale_direction": self.last_whale_alert.direction.name if self.last_whale_alert else "NEUTRAL",
            "sentiment_velocity": self._cached_sentiment_velocity,
            "sentiment_state": sentiment_state,
            "shadow_front_ready": self.shadow_front_strategy is not None,
            "gamma_front_ready": self.gamma_front_strategy is not None,
        }