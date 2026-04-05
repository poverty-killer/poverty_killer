"""
Shadow Front State - Governed State Machine for Shadow-Front Strategy
CITADEL GRADE — DETERMINISTIC · REPLAY-SAFE · NO WALL-CLOCK

ANALYTICAL/NON-MONETARY BOUNDARY:
This file performs analytical state management using deterministic inputs.
It manages strategy lifecycle states (IDLE → STALKING → ARMED → IGNITION → ACTIVE → COOLDOWN)
based on analytical inputs from approved brain engines.
These are NOT monetary truth or execution guarantees.

ARCHITECTURAL ROLE:
This file is the CONVERGENCE LAYER for Shadow-Front strategy.
It consumes, does NOT re-implement:
- Whale flow state (whale_flow_engine.py)
- Sentiment state (sentiment_engine.py)
- Sentiment velocity / macro overlay (sentiment_velocity.py)
- Regime context (regime_detector.py)
- Signal fusion (signal_fusion.py)

DETERMINISTIC BEHAVIOR:
- No wall-clock time (datetime.utcnow, timedelta)
- No random number generation
- All timing uses integer nanoseconds from authoritative external sources
- All state transitions are deterministic given identical inputs
- Full replay-safe state machine
- Strict timestamp monotonicity enforced at machine level and per context channel
- Context freshness thresholds prevent stale data from driving transitions
- Timestamp future-skew rejection prevents forward-dated contexts
- Deterministic binary serialization with explicit schema version (no pickle)
- Optional serialized-state broadcast callback for hot-standby recovery (publication only)
- Deterministic state hash for integrity verification
"""

import logging
import struct
import hashlib
from typing import Optional, Dict, Any, Tuple, Callable
from enum import IntEnum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class ShadowFrontState(IntEnum):
    """
    Deterministic state machine states for Shadow-Front strategy.
    
    State lifecycle:
    IDLE → STALKING → ARMED → IGNITION → ACTIVE → COOLDOWN → IDLE
    """
    IDLE = 0          # No active whale zone, waiting
    STALKING = 1      # Whale zone active, accumulating evidence
    ARMED = 2         # Sufficient evidence, waiting for ignition
    IGNITION = 3      # Ignition triggered, ready for entry
    ACTIVE = 4        # Position held
    COOLDOWN = 5      # Post-exit cooldown


@dataclass
class StateTransition:
    """Record of a deterministic state transition."""
    from_state: ShadowFrontState
    to_state: ShadowFrontState
    timestamp_ns: int
    reason: str
    confidence: float


@dataclass
class WhaleContext:
    """Whale flow context from whale_flow_engine.py."""
    is_active: bool
    zone_low: Optional[float]
    zone_high: Optional[float]
    volume: float
    score: float
    confidence: float
    evidence_count: int
    direction_bias: int  # 0=neutral, 1=bullish, 2=bearish
    timestamp_ns: int


@dataclass
class SentimentContext:
    """Sentiment context from sentiment_engine.py and sentiment_velocity.py."""
    level: float  # -1 to 1
    velocity: float  # sentiment/sec
    acceleration: float  # sentiment/sec²
    divergence: float  # 0-1
    macro_pause: bool
    macro_kill: bool
    bull_trap_detected: bool
    stability: float  # 0-1
    confidence: float
    timestamp_ns: int


@dataclass
class RegimeContext:
    """Regime context from regime_detector.py."""
    regime_code: int  # 0=bull, 1=bear, 2=ranging, 3=crisis, 4=unknown
    confidence: float
    trending_bull: bool
    trending_bear: bool
    crisis: bool
    timestamp_ns: int


@dataclass
class FusionContext:
    """Signal fusion context from signal_fusion.py."""
    action: str  # "BUY", "SELL", "WAIT"
    confidence: float
    expected_volatility: float
    institutional_score: float
    timestamp_ns: int


class ShadowFrontStateMachine:
    """
    Governed state machine for Shadow-Front strategy.
    
    This machine consumes analytical outputs from approved brain engines
    and produces deterministic state transitions. It does NOT re-implement
    detection logic — it converges signals into state management.
    
    TIMING AUTHORITY:
    - All timestamps must be provided by external authoritative source
    - No internal time generation
    - Machine-level monotonic timestamp enforcement
    - Per-context monotonic timestamp enforcement
    - Context freshness thresholds prevent stale data
    - Future-skew rejection prevents forward-dated contexts (no drift validation on stale age)
    
    SERIALIZATION:
    - deterministic binary serialization with explicit schema version
    - no pickle, no json, no dynamic reflection
    - upstream contexts are NOT serialized (re-hydrated externally)
    
    STATE BROADCAST (OPTIONAL):
    - optional callback-based publication of serialized state
    - publication channel only, NOT a source of truth
    - does NOT affect state transitions
    
    INTEGRITY VERIFICATION:
    - deterministic SHA256 hash from serialized bytes
    - for hot-standby recovery validation only
    - not a trading signal
    
    INPUT INTEGRATION:
    - WhaleContext from whale_flow_engine.py
    - SentimentContext from sentiment_engine.py + sentiment_velocity.py
    - RegimeContext from regime_detector.py
    - FusionContext from signal_fusion.py
    """
    
    # Context freshness thresholds (nanoseconds)
    DEFAULT_WHALE_FRESHNESS_NS = 60_000_000_000  # 60 seconds
    DEFAULT_SENTIMENT_FRESHNESS_NS = 30_000_000_000  # 30 seconds
    DEFAULT_REGIME_FRESHNESS_NS = 120_000_000_000  # 120 seconds
    DEFAULT_FUSION_FRESHNESS_NS = 10_000_000_000  # 10 seconds
    
    # Serialization schema version
    SERIALIZATION_VERSION = 3
    
    def __init__(
        self,
        symbol: str,
        stalking_evidence_min: int = 2,
        armed_confidence_threshold: float = 0.65,
        ignition_velocity_threshold: float = 0.03,
        cooldown_seconds: int = 30,
        max_position_hold_seconds: int = 1800,
        entry_zone_tolerance: float = 0.02,
        take_profit_pct: float = 0.02,
        stop_loss_pct: float = 0.015,
        macro_kill_suppress_seconds: int = 30,
        whale_freshness_ns: Optional[int] = None,
        sentiment_freshness_ns: Optional[int] = None,
        regime_freshness_ns: Optional[int] = None,
        fusion_freshness_ns: Optional[int] = None,
        state_broadcast_fn: Optional[Callable[[memoryview], None]] = None
    ):
        """
        Initialize governed state machine.
        
        Args:
            symbol: Trading symbol
            stalking_evidence_min: Minimum whale evidence count for STALKING→ARMED
            armed_confidence_threshold: Confidence threshold for ARMING
            ignition_velocity_threshold: Sentiment velocity threshold for ignition
            cooldown_seconds: Cooldown duration in seconds
            max_position_hold_seconds: Maximum position hold time
            entry_zone_tolerance: Price tolerance for whale zone entry (0.02 = 2%)
            take_profit_pct: Take profit percentage (0.02 = 2%)
            stop_loss_pct: Stop loss percentage (0.015 = 1.5%)
            macro_kill_suppress_seconds: Macro kill suppression duration
            whale_freshness_ns: Whale context freshness threshold (nanoseconds)
            sentiment_freshness_ns: Sentiment context freshness threshold
            regime_freshness_ns: Regime context freshness threshold
            fusion_freshness_ns: Fusion context freshness threshold
            state_broadcast_fn: Optional callback for state broadcast (receives memoryview of serialized bytes)
        """
        self.symbol = symbol
        self.stalking_evidence_min = stalking_evidence_min
        self.armed_confidence_threshold = armed_confidence_threshold
        self.ignition_velocity_threshold = ignition_velocity_threshold
        self.cooldown_seconds_ns = cooldown_seconds * 1_000_000_000
        self.max_position_hold_ns = max_position_hold_seconds * 1_000_000_000
        self.entry_zone_tolerance = entry_zone_tolerance
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.macro_kill_suppress_ns = macro_kill_suppress_seconds * 1_000_000_000
        
        # Context freshness thresholds
        self.whale_freshness_ns = whale_freshness_ns or self.DEFAULT_WHALE_FRESHNESS_NS
        self.sentiment_freshness_ns = sentiment_freshness_ns or self.DEFAULT_SENTIMENT_FRESHNESS_NS
        self.regime_freshness_ns = regime_freshness_ns or self.DEFAULT_REGIME_FRESHNESS_NS
        self.fusion_freshness_ns = fusion_freshness_ns or self.DEFAULT_FUSION_FRESHNESS_NS
        
        # Optional state broadcast callback (receives memoryview of serialized bytes)
        self._state_broadcast_fn = state_broadcast_fn
        
        # Current state
        self._current_state: ShadowFrontState = ShadowFrontState.IDLE
        self._last_transition: Optional[StateTransition] = None
        self._transition_history: list = []  # Max 100, managed externally
        
        # Machine-level monotonic timestamp guard
        self._last_update_ts_ns: Optional[int] = None
        
        # Whale context with per-channel monotonic guard
        self._whale: Optional[WhaleContext] = None
        self._whale_last_ts_ns: Optional[int] = None
        self._whale_zone_start_ns: Optional[int] = None
        
        # Sentiment context with per-channel monotonic guard
        self._sentiment: Optional[SentimentContext] = None
        self._sentiment_last_ts_ns: Optional[int] = None
        
        # Regime context with per-channel monotonic guard
        self._regime: Optional[RegimeContext] = None
        self._regime_last_ts_ns: Optional[int] = None
        
        # Fusion context with per-channel monotonic guard
        self._fusion: Optional[FusionContext] = None
        self._fusion_last_ts_ns: Optional[int] = None
        
        # Position tracking
        self._entry_price: Optional[float] = None
        self._entry_time_ns: Optional[int] = None
        self._position_size: float = 0.0
        self._pnl: float = 0.0
        
        # Cooldown tracking
        self._cooldown_until_ns: Optional[int] = None
        
        # Macro kill suppression
        self._macro_kill_until_ns: Optional[int] = None
        
        # Signal counters (for analytics, not state logic)
        self._whale_update_count: int = 0
        self._ignition_trigger_count: int = 0
        
        logger.info(f"ShadowFrontStateMachine initialized for {symbol}")
        logger.info(f"  State machine — deterministic, replay-safe, no wall-clock")
        logger.info(f"  Freshness thresholds: whale={self.whale_freshness_ns/1e9}s, "
                   f"sentiment={self.sentiment_freshness_ns/1e9}s, "
                   f"regime={self.regime_freshness_ns/1e9}s, "
                   f"fusion={self.fusion_freshness_ns/1e9}s")
        if self._state_broadcast_fn:
            logger.info("  State broadcast callback enabled (optional publication channel)")
    
    # ============================================
    # FRESHNESS HELPERS
    # ============================================
    
    def _is_context_fresh(self, timestamp_ns: int, current_ts_ns: int, max_age_ns: int) -> bool:
        """Check if context timestamp is within freshness threshold."""
        if timestamp_ns <= 0:
            return False
        age_ns = current_ts_ns - timestamp_ns
        return 0 <= age_ns <= max_age_ns
    
    def _is_whale_fresh(self, current_ts_ns: int) -> bool:
        """Check if whale context is fresh enough to use."""
        if self._whale is None:
            return False
        return self._is_context_fresh(self._whale.timestamp_ns, current_ts_ns, self.whale_freshness_ns)
    
    def _is_sentiment_fresh(self, current_ts_ns: int) -> bool:
        """Check if sentiment context is fresh enough to use."""
        if self._sentiment is None:
            return False
        return self._is_context_fresh(self._sentiment.timestamp_ns, current_ts_ns, self.sentiment_freshness_ns)
    
    def _is_regime_fresh(self, current_ts_ns: int) -> bool:
        """Check if regime context is fresh enough to use."""
        if self._regime is None:
            return False
        return self._is_context_fresh(self._regime.timestamp_ns, current_ts_ns, self.regime_freshness_ns)
    
    def _is_fusion_fresh(self, current_ts_ns: int) -> bool:
        """Check if fusion context is fresh enough to use."""
        if self._fusion is None:
            return False
        return self._is_context_fresh(self._fusion.timestamp_ns, current_ts_ns, self.fusion_freshness_ns)
    
    # ============================================
    # TIMESTAMP VALIDATION (FUTURE-SKEW ONLY)
    # ============================================
    
    def _validate_context_timestamp(self, context_ts_ns: int, current_ts_ns: int, context_name: str) -> bool:
        """
        Validate context timestamp against current timestamp.
        
        Rules:
        - Must be positive int
        - Must not be ahead of current_ts_ns (future-skew rejection)
        - Stale age is NOT rejected here — freshness model handles usability
        """
        if not isinstance(context_ts_ns, int) or context_ts_ns <= 0:
            logger.warning(f"Invalid {context_name} timestamp: {context_ts_ns} — rejecting update")
            return False
        
        if context_ts_ns > current_ts_ns:
            logger.warning(f"{context_name} timestamp {context_ts_ns} ahead of current {current_ts_ns} — rejecting")
            return False
        
        return True
    
    def _check_channel_monotonicity(self, channel_name: str, new_ts_ns: int, last_ts_ns: Optional[int]) -> bool:
        """
        Enforce per-channel monotonicity: new timestamp must be > last timestamp.
        
        Returns True if update allowed, False if should reject.
        """
        if last_ts_ns is not None and new_ts_ns <= last_ts_ns:
            logger.warning(f"Non-monotonic {channel_name} update: {new_ts_ns} <= last {last_ts_ns} — rejecting")
            return False
        return True
    
    # ============================================
    # CONTEXT UPDATE METHODS WITH PER-CHANNEL MONOTONICITY
    # ============================================
    
    def update_whale_context(self, context: WhaleContext, current_ts_ns: int) -> None:
        """
        Update whale flow context from whale_flow_engine.py.
        
        Per-channel monotonicity enforced: cannot overwrite newer context.
        Future-skew validation prevents forward-dated contexts.
        """
        if not isinstance(current_ts_ns, int) or current_ts_ns <= 0:
            logger.warning(f"Invalid timestamp for whale update: {current_ts_ns}")
            return
        
        if not self._validate_context_timestamp(context.timestamp_ns, current_ts_ns, "whale_context"):
            return
        
        if not self._check_channel_monotonicity("whale_context", context.timestamp_ns, self._whale_last_ts_ns):
            return
        
        self._whale = context
        self._whale_last_ts_ns = context.timestamp_ns
        self._whale_update_count += 1
        
        # If whale zone active and we're in IDLE, transition to STALKING
        if context.is_active and self._current_state == ShadowFrontState.IDLE:
            self._transition_to(ShadowFrontState.STALKING, current_ts_ns, 
                               f"whale_zone_detected_score={context.score:.2f}")
            self._whale_zone_start_ns = context.timestamp_ns
    
    def update_sentiment_context(self, context: SentimentContext, current_ts_ns: int) -> None:
        """
        Update sentiment context from sentiment_engine.py + sentiment_velocity.py.
        
        Per-channel monotonicity enforced: cannot overwrite newer context.
        Future-skew validation prevents forward-dated contexts.
        """
        if not isinstance(current_ts_ns, int) or current_ts_ns <= 0:
            logger.warning(f"Invalid timestamp for sentiment update: {current_ts_ns}")
            return
        
        if not self._validate_context_timestamp(context.timestamp_ns, current_ts_ns, "sentiment_context"):
            return
        
        if not self._check_channel_monotonicity("sentiment_context", context.timestamp_ns, self._sentiment_last_ts_ns):
            return
        
        self._sentiment = context
        self._sentiment_last_ts_ns = context.timestamp_ns
        
        # Check for macro kill suppression (only if context fresh)
        if self._is_sentiment_fresh(current_ts_ns) and context.macro_kill:
            self._macro_kill_until_ns = current_ts_ns + self.macro_kill_suppress_ns
            if self._current_state not in (ShadowFrontState.IDLE, ShadowFrontState.COOLDOWN):
                self._transition_to(ShadowFrontState.COOLDOWN, current_ts_ns,
                                   f"macro_kill_suppression_vel={context.velocity:.3f}")
                self._cooldown_until_ns = current_ts_ns + self.cooldown_seconds_ns
        
        # Check for ignition in ARMED state (requires fresh sentiment)
        elif (self._current_state == ShadowFrontState.ARMED and 
              self._is_sentiment_fresh(current_ts_ns) and
              abs(context.velocity) >= self.ignition_velocity_threshold and
              not context.macro_pause and not context.macro_kill):
            self._transition_to(ShadowFrontState.IGNITION, current_ts_ns,
                               f"sentiment_ignition_vel={context.velocity:.3f}_accel={context.acceleration:.3f}")
            self._ignition_trigger_count += 1
    
    def update_regime_context(self, context: RegimeContext, current_ts_ns: int) -> None:
        """
        Update regime context from regime_detector.py.
        
        Per-channel monotonicity enforced: cannot overwrite newer context.
        Future-skew validation prevents forward-dated contexts.
        """
        if not isinstance(current_ts_ns, int) or current_ts_ns <= 0:
            logger.warning(f"Invalid timestamp for regime update: {current_ts_ns}")
            return
        
        if not self._validate_context_timestamp(context.timestamp_ns, current_ts_ns, "regime_context"):
            return
        
        if not self._check_channel_monotonicity("regime_context", context.timestamp_ns, self._regime_last_ts_ns):
            return
        
        self._regime = context
        self._regime_last_ts_ns = context.timestamp_ns
        
        # Crisis regime overrides: force cooldown (only if regime context fresh)
        if self._is_regime_fresh(current_ts_ns) and context.crisis and self._current_state not in (ShadowFrontState.IDLE, ShadowFrontState.COOLDOWN):
            self._transition_to(ShadowFrontState.COOLDOWN, current_ts_ns,
                               f"crisis_regime_{context.regime_code}")
            self._cooldown_until_ns = current_ts_ns + self.cooldown_seconds_ns
    
    def update_fusion_context(self, context: FusionContext, current_ts_ns: int) -> None:
        """
        Update signal fusion context from signal_fusion.py.
        
        Per-channel monotonicity enforced: cannot overwrite newer context.
        Future-skew validation prevents forward-dated contexts.
        """
        if not isinstance(current_ts_ns, int) or current_ts_ns <= 0:
            logger.warning(f"Invalid timestamp for fusion update: {current_ts_ns}")
            return
        
        if not self._validate_context_timestamp(context.timestamp_ns, current_ts_ns, "fusion_context"):
            return
        
        if not self._check_channel_monotonicity("fusion_context", context.timestamp_ns, self._fusion_last_ts_ns):
            return
        
        self._fusion = context
        self._fusion_last_ts_ns = context.timestamp_ns
    
    # ============================================
    # CONFLICT RESOLUTION MODEL WITH FRESHNESS GATES
    # ============================================
    
    def _calculate_conflict_penalty(self, current_ts_ns: int) -> float:
        """
        Calculate conflict penalty based on disagreements between contexts.
        
        ONLY fresh contexts affect penalties. Stale contexts are ignored.
        
        Returns penalty factor in [0.5, 1.0] where:
        - 1.0 = no conflict (full confidence)
        - 0.5 = severe conflict (50% confidence reduction)
        """
        penalty = 1.0
        
        # Need at minimum whale context
        if self._whale is None:
            return 1.0
        
        whale_fresh = self._is_whale_fresh(current_ts_ns)
        sentiment_fresh = self._is_sentiment_fresh(current_ts_ns)
        regime_fresh = self._is_regime_fresh(current_ts_ns)
        fusion_fresh = self._is_fusion_fresh(current_ts_ns)
        
        # Stale whale context penalty
        if not whale_fresh:
            penalty *= 0.7
        
        # Conflict 1: Whale direction vs sentiment level (only if sentiment fresh)
        if sentiment_fresh and self._sentiment is not None:
            if self._whale.direction_bias == 1 and self._sentiment.level < -0.2:
                penalty *= 0.75
            elif self._whale.direction_bias == 2 and self._sentiment.level > 0.2:
                penalty *= 0.75
        
        # Conflict 2: Whale direction vs sentiment velocity (only if sentiment fresh)
        if sentiment_fresh and self._sentiment is not None:
            if self._whale.direction_bias == 1 and self._sentiment.velocity < -0.01:
                penalty *= 0.8
            elif self._whale.direction_bias == 2 and self._sentiment.velocity > 0.01:
                penalty *= 0.8
        
        # Conflict 3: Fusion action opposition (only if fusion fresh)
        if fusion_fresh and self._fusion is not None:
            if self._whale.direction_bias == 1 and self._fusion.action == "SELL":
                penalty *= 0.7
            elif self._whale.direction_bias == 2 and self._fusion.action == "BUY":
                penalty *= 0.7
        
        # Conflict 4: Macro suppression (only if sentiment fresh)
        if sentiment_fresh and self._sentiment is not None:
            if self._sentiment.macro_pause:
                penalty *= 0.85
            if self._sentiment.macro_kill:
                penalty *= 0.6
            if self._sentiment.bull_trap_detected and self._whale.direction_bias == 1:
                penalty *= 0.7
        
        # Conflict 5: Regime opposition (only if regime fresh)
        if regime_fresh and self._regime is not None:
            if self._regime.crisis:
                penalty *= 0.5
            else:
                if self._whale.direction_bias == 1 and self._regime.trending_bear:
                    penalty *= 0.8
                elif self._whale.direction_bias == 2 and self._regime.trending_bull:
                    penalty *= 0.8
        
        return max(0.5, min(1.0, penalty))
    
    def _calculate_alignment_bonus(self, current_ts_ns: int) -> float:
        """
        Calculate alignment bonus when multiple fresh contexts agree.
        
        ONLY fresh contexts affect bonuses. Stale contexts are ignored.
        
        Returns bonus factor in [1.0, 1.25] where:
        - 1.0 = no special alignment
        - 1.25 = strong alignment across multiple signals
        """
        bonus = 1.0
        
        if self._whale is None:
            return 1.0
        
        sentiment_fresh = self._is_sentiment_fresh(current_ts_ns)
        regime_fresh = self._is_regime_fresh(current_ts_ns)
        fusion_fresh = self._is_fusion_fresh(current_ts_ns)
        
        # Alignment 1: Whale + sentiment level agreement (only if sentiment fresh)
        if sentiment_fresh and self._sentiment is not None:
            if self._whale.direction_bias == 1 and self._sentiment.level > 0.3:
                bonus *= 1.1
            elif self._whale.direction_bias == 2 and self._sentiment.level < -0.3:
                bonus *= 1.1
        
        # Alignment 2: Whale + sentiment velocity (only if sentiment fresh)
        if sentiment_fresh and self._sentiment is not None:
            if self._whale.direction_bias == 1 and self._sentiment.velocity > 0.02:
                bonus *= 1.1
            elif self._whale.direction_bias == 2 and self._sentiment.velocity < -0.02:
                bonus *= 1.1
        
        # Alignment 3: Fusion action confirmation (only if fusion fresh)
        if fusion_fresh and self._fusion is not None:
            if self._whale.direction_bias == 1 and self._fusion.action == "BUY":
                bonus *= 1.1
            elif self._whale.direction_bias == 2 and self._fusion.action == "SELL":
                bonus *= 1.1
        
        # Alignment 4: Regime confirmation (only if regime fresh)
        if regime_fresh and self._regime is not None:
            if self._whale.direction_bias == 1 and self._regime.trending_bull:
                bonus *= 1.05
            elif self._whale.direction_bias == 2 and self._regime.trending_bear:
                bonus *= 1.05
        
        return min(1.25, bonus)
    
    # ============================================
    # STATE TRANSITION LOGIC
    # ============================================
    
    def _calculate_armed_confidence(self, current_ts_ns: int) -> float:
        """
        Calculate confidence for ARMED state based on accumulated evidence.
        
        Includes conflict penalty and alignment bonus from the conflict model.
        Only fresh contexts affect confidence.
        """
        if self._whale is None:
            return 0.0
        
        # Base whale confidence
        evidence_factor = min(1.0, self._whale.evidence_count / self.stalking_evidence_min)
        base_confidence = self._whale.confidence * evidence_factor
        
        # Apply conflict penalty and alignment bonus (both use freshness internally)
        conflict_penalty = self._calculate_conflict_penalty(current_ts_ns)
        alignment_bonus = self._calculate_alignment_bonus(current_ts_ns)
        
        confidence = base_confidence * conflict_penalty * alignment_bonus
        
        # Stale sentiment/regime/fusion reduce confidence
        if not self._is_sentiment_fresh(current_ts_ns):
            confidence *= 0.9
        if not self._is_regime_fresh(current_ts_ns):
            confidence *= 0.95
        if not self._is_fusion_fresh(current_ts_ns):
            confidence *= 0.95
        
        return min(1.0, max(0.0, confidence))
    
    def _should_advance_to_armed(self, current_ts_ns: int) -> bool:
        """Determine if state should advance from STALKING to ARMED."""
        if self._whale is None:
            return False
        
        # Must have sufficient evidence
        if self._whale.evidence_count < self.stalking_evidence_min:
            return False
        
        # Must have fresh whale context
        if not self._is_whale_fresh(current_ts_ns):
            return False
        
        # Must have confidence above threshold
        confidence = self._calculate_armed_confidence(current_ts_ns)
        if confidence < self.armed_confidence_threshold:
            return False
        
        # Must not be macro-suppressed (only if sentiment fresh)
        if self._is_sentiment_fresh(current_ts_ns) and self._sentiment:
            if self._sentiment.macro_pause or self._sentiment.macro_kill:
                return False
        
        # Must not be in crisis regime (only if regime fresh)
        if self._is_regime_fresh(current_ts_ns) and self._regime and self._regime.crisis:
            return False
        
        return True
    
    def _should_enter_position(self, current_price: float, current_ts_ns: int) -> bool:
        """
        Determine if entry condition is met in IGNITION state.
        """
        # Must be in IGNITION state
        if self._current_state != ShadowFrontState.IGNITION:
            return False
        
        # Must have whale zone (fresh)
        if self._whale is None or not self._whale.is_active:
            return False
        if not self._is_whale_fresh(current_ts_ns):
            return False
        
        # Price must be within whale zone
        if self._whale.zone_low is None or self._whale.zone_high is None:
            return False
        
        low = self._whale.zone_low * (1 - self.entry_zone_tolerance)
        high = self._whale.zone_high * (1 + self.entry_zone_tolerance)
        
        if not (low <= current_price <= high):
            return False
        
        # Must have fusion confirmation if fresh (not sell signal)
        if self._is_fusion_fresh(current_ts_ns) and self._fusion:
            if self._fusion.action == "SELL":
                return False
        
        # Must have sufficient confidence (including conflict model)
        confidence = self._calculate_armed_confidence(current_ts_ns)
        if confidence < self.armed_confidence_threshold:
            return False
        
        # Must have fresh sentiment for ignition (velocity confirmation)
        if not self._is_sentiment_fresh(current_ts_ns):
            return False
        
        return True
    
    def _should_exit_position(self, current_price: float, current_ts_ns: int) -> Tuple[bool, str]:
        """Determine if position should be exited."""
        if self._entry_price is None or self._entry_time_ns is None:
            return False, ""
        
        # Calculate P&L percentage
        pnl_pct = (current_price - self._entry_price) / self._entry_price
        
        # Take profit
        if pnl_pct >= self.take_profit_pct:
            return True, f"take_profit_pct={pnl_pct:.3f}"
        
        # Stop loss
        if pnl_pct <= -self.stop_loss_pct:
            return True, f"stop_loss_pct={pnl_pct:.3f}"
        
        # Max hold time
        hold_ns = current_ts_ns - self._entry_time_ns
        if hold_ns >= self.max_position_hold_ns:
            return True, f"max_hold_time_{hold_ns/1_000_000_000:.0f}s"
        
        # Whale zone exit (if whale context fresh)
        if self._is_whale_fresh(current_ts_ns) and self._whale:
            if self._whale.zone_low and self._whale.zone_high:
                if current_price < self._whale.zone_low * 0.98 or current_price > self._whale.zone_high * 1.02:
                    return True, "price_exited_whale_zone"
        
        # Sentiment collapse (if fresh)
        if self._is_sentiment_fresh(current_ts_ns) and self._sentiment:
            if self._sentiment.velocity < -0.02 and self._sentiment.level < 0:
                return True, f"sentiment_collapse_vel={self._sentiment.velocity:.3f}"
        
        # Macro kill (if fresh)
        if self._is_sentiment_fresh(current_ts_ns) and self._sentiment and self._sentiment.macro_kill:
            return True, "macro_kill_active"
        
        return False, ""
    
    def _should_cooldown_expire(self, current_ts_ns: int) -> bool:
        """Check if cooldown has expired."""
        if self._cooldown_until_ns is None:
            return True
        return current_ts_ns >= self._cooldown_until_ns
    
    def _should_macro_kill_expire(self, current_ts_ns: int) -> bool:
        """Check if macro kill suppression has expired."""
        if self._macro_kill_until_ns is None:
            return True
        return current_ts_ns >= self._macro_kill_until_ns
    
    def _transition_to(self, new_state: ShadowFrontState, timestamp_ns: int, reason: str) -> None:
        """Execute deterministic state transition."""
        old_state = self._current_state
        self._current_state = new_state
        
        # Use current timestamp for confidence calculation
        confidence = self._calculate_armed_confidence(timestamp_ns) if self._whale else 0.0
        
        transition = StateTransition(
            from_state=old_state,
            to_state=new_state,
            timestamp_ns=timestamp_ns,
            reason=reason,
            confidence=confidence
        )
        
        self._last_transition = transition
        self._transition_history.append(transition)
        
        # Keep history bounded
        if len(self._transition_history) > 100:
            self._transition_history.pop(0)
        
        logger.info(f"ShadowFront[{self.symbol}]: {old_state.name} -> {new_state.name} ({reason})")
        
        # Broadcast state on transition (if callback configured)
        self._broadcast_serialized_state()
    
    # ============================================
    # DETERMINISTIC BINARY SERIALIZATION
    # ============================================
    
    def serialize_state(self) -> bytes:
        """
        Serialize machine state to deterministic binary format.
        
        Schema version 3:
        - version: uint8 (3)
        - current_state: uint8
        - last_update_ts_ns: uint64
        - last_transition_timestamp_ns: uint64
        - last_transition_from_state: uint8
        - last_transition_to_state: uint8
        - last_transition_confidence: float64
        - last_transition_reason_len: uint16
        - last_transition_reason: bytes (fixed 128 bytes, padded with nulls)
        - cooldown_until_ns: uint64 (0 = None sentinel)
        - macro_kill_until_ns: uint64 (0 = None sentinel)
        - entry_price: float64 (0.0 sentinel for None)
        - entry_time_ns: uint64 (0 = None sentinel)
        - position_size: float64
        - pnl: float64
        - whale_zone_start_ns: uint64 (0 = None sentinel)
        - whale_update_count: uint32
        - ignition_trigger_count: uint32
        - whale_last_ts_ns: uint64 (0 = None sentinel)
        - sentiment_last_ts_ns: uint64 (0 = None sentinel)
        - regime_last_ts_ns: uint64 (0 = None sentinel)
        - fusion_last_ts_ns: uint64 (0 = None sentinel)
        """
        # Prepare reason with fixed 128-byte field
        reason_str = self._last_transition.reason if self._last_transition else ""
        reason_bytes = reason_str.encode('utf-8')[:127]  # Leave room for null terminator
        reason_padded = reason_bytes.ljust(128, b'\x00')
        
        # Sentinels: 0 for None timestamps, 0.0 for None price
        cooldown_val = self._cooldown_until_ns if self._cooldown_until_ns is not None else 0
        macro_kill_val = self._macro_kill_until_ns if self._macro_kill_until_ns is not None else 0
        entry_price_val = self._entry_price if self._entry_price is not None else 0.0
        entry_time_val = self._entry_time_ns if self._entry_time_ns is not None else 0
        whale_zone_start_val = self._whale_zone_start_ns if self._whale_zone_start_ns is not None else 0
        whale_last_ts_val = self._whale_last_ts_ns if self._whale_last_ts_ns is not None else 0
        sentiment_last_ts_val = self._sentiment_last_ts_ns if self._sentiment_last_ts_ns is not None else 0
        regime_last_ts_val = self._regime_last_ts_ns if self._regime_last_ts_ns is not None else 0
        fusion_last_ts_val = self._fusion_last_ts_ns if self._fusion_last_ts_ns is not None else 0
        
        last_transition_ts = self._last_transition.timestamp_ns if self._last_transition else 0
        last_transition_from = self._last_transition.from_state.value if self._last_transition else 0
        last_transition_to = self._last_transition.to_state.value if self._last_transition else 0
        last_transition_conf = self._last_transition.confidence if self._last_transition else 0.0
        
        # Pack struct
        fmt = '>B B Q Q B B d H 128s Q Q d Q d d Q I I Q Q Q Q'
        
        return struct.pack(
            fmt,
            self.SERIALIZATION_VERSION,
            self._current_state.value,
            self._last_update_ts_ns or 0,
            last_transition_ts,
            last_transition_from,
            last_transition_to,
            last_transition_conf,
            len(reason_str),
            reason_padded,
            cooldown_val,
            macro_kill_val,
            entry_price_val,
            entry_time_val,
            self._position_size,
            self._pnl,
            whale_zone_start_val,
            self._whale_update_count,
            self._ignition_trigger_count,
            whale_last_ts_val,
            sentiment_last_ts_val,
            regime_last_ts_val,
            fusion_last_ts_val
        )
    
    def deserialize_state(self, data: bytes) -> None:
        """
        Restore machine state from deterministic binary format.
        
        This method restores machine-owned state only.
        Upstream contexts (whale, sentiment, regime, fusion) must be re-hydrated externally.
        
        Args:
            data: Binary data from serialize_state()
        """
        fmt = '>B B Q Q B B d H 128s Q Q d Q d d Q I I Q Q Q Q'
        expected_size = struct.calcsize(fmt)
        
        if len(data) < expected_size:
            logger.error(f"Serialized data too short: {len(data)} < {expected_size}")
            return
        
        unpacked = struct.unpack(fmt, data[:expected_size])
        
        idx = 0
        version = unpacked[idx]; idx += 1
        if version != self.SERIALIZATION_VERSION:
            logger.warning(f"Serialization version mismatch: {version} != {self.SERIALIZATION_VERSION}")
            return
        
        self._current_state = ShadowFrontState(unpacked[idx]); idx += 1
        self._last_update_ts_ns = unpacked[idx] if unpacked[idx] != 0 else None; idx += 1
        
        last_transition_ts = unpacked[idx]; idx += 1
        last_transition_from = unpacked[idx]; idx += 1
        last_transition_to = unpacked[idx]; idx += 1
        last_transition_conf = unpacked[idx]; idx += 1
        reason_len = unpacked[idx]; idx += 1
        reason_bytes = unpacked[idx]; idx += 1
        reason_str = reason_bytes[:reason_len].decode('utf-8', errors='replace').rstrip('\x00')
        
        if last_transition_ts != 0:
            self._last_transition = StateTransition(
                from_state=ShadowFrontState(last_transition_from),
                to_state=ShadowFrontState(last_transition_to),
                timestamp_ns=last_transition_ts,
                reason=reason_str,
                confidence=last_transition_conf
            )
        else:
            self._last_transition = None
        
        self._cooldown_until_ns = unpacked[idx] if unpacked[idx] != 0 else None; idx += 1
        self._macro_kill_until_ns = unpacked[idx] if unpacked[idx] != 0 else None; idx += 1
        self._entry_price = unpacked[idx] if unpacked[idx] != 0.0 else None; idx += 1
        self._entry_time_ns = unpacked[idx] if unpacked[idx] != 0 else None; idx += 1
        self._position_size = unpacked[idx]; idx += 1
        self._pnl = unpacked[idx]; idx += 1
        self._whale_zone_start_ns = unpacked[idx] if unpacked[idx] != 0 else None; idx += 1
        self._whale_update_count = unpacked[idx]; idx += 1
        self._ignition_trigger_count = unpacked[idx]; idx += 1
        self._whale_last_ts_ns = unpacked[idx] if unpacked[idx] != 0 else None; idx += 1
        self._sentiment_last_ts_ns = unpacked[idx] if unpacked[idx] != 0 else None; idx += 1
        self._regime_last_ts_ns = unpacked[idx] if unpacked[idx] != 0 else None; idx += 1
        self._fusion_last_ts_ns = unpacked[idx] if unpacked[idx] != 0 else None; idx += 1
        
        # Clear transition history on deserialize (history is not persisted)
        self._transition_history.clear()
        
        # Clear upstream contexts (must be re-hydrated externally)
        self._whale = None
        self._sentiment = None
        self._regime = None
        self._fusion = None
        
        logger.info(f"ShadowFront[{self.symbol}]: State deserialized to {self._current_state.name}")
    
    # ============================================
    # DETERMINISTIC STATE HASHING
    # ============================================
    
    def compute_state_hash(self) -> bytes:
        """
        Compute deterministic SHA256 hash from serialized state bytes.
        
        Uses canonical serialized representation for integrity verification.
        Hash is NOT a trading signal. NOT a replacement for full replay validation.
        
        Returns:
            32-byte SHA256 hash
        """
        serialized = self.serialize_state()
        return hashlib.sha256(serialized).digest()
    
    def state_hash_hex(self) -> str:
        """Return state hash as hex string for logging/integrity checks."""
        return self.compute_state_hash().hex()
    
    # ============================================
    # OPTIONAL STATE BROADCAST (PUBLICATION ONLY)
    # ============================================
    
    def _broadcast_serialized_state(self) -> None:
        """
        Broadcast serialized state via optional callback.
        
        This is a publication channel ONLY. Does NOT affect state transitions.
        If callback fails or is None, degrades safely without error.
        Callback receives memoryview of serialized bytes for buffer-style passing.
        """
        if self._state_broadcast_fn is None:
            return
        
        try:
            serialized = self.serialize_state()
            self._state_broadcast_fn(memoryview(serialized))
        except Exception as e:
            logger.warning(f"State broadcast failed for {self.symbol}: {e}")
    
    def publish_state(self) -> None:
        """
        Explicitly publish current state via optional callback.
        
        Useful for hot-standby recovery or downstream observers.
        Does NOT affect state machine logic.
        """
        self._broadcast_serialized_state()
    
    # ============================================
    # MAIN UPDATE METHOD
    # ============================================
    
    def update(self, current_price: float, current_ts_ns: int) -> Optional[str]:
        """
        Main update method — evaluates state and returns action if needed.
        
        Args:
            current_price: Current market price
            current_ts_ns: Current authoritative timestamp
            
        Returns:
            Action string: "enter", "exit", or None
        """
        # Validate timestamp
        if not isinstance(current_ts_ns, int) or current_ts_ns <= 0:
            logger.warning(f"Invalid timestamp for update: {current_ts_ns}")
            return None
        
        # Enforce machine-level timestamp monotonicity
        if self._last_update_ts_ns is not None:
            if current_ts_ns <= self._last_update_ts_ns:
                logger.warning(f"Non-monotonic update timestamp: {current_ts_ns} <= last {self._last_update_ts_ns}")
                return None
        
        self._last_update_ts_ns = current_ts_ns
        
        # Check macro kill expiry
        if self._macro_kill_until_ns is not None and self._should_macro_kill_expire(current_ts_ns):
            self._macro_kill_until_ns = None
        
        action = None
        
        # State machine transitions
        if self._current_state == ShadowFrontState.STALKING:
            if self._should_advance_to_armed(current_ts_ns):
                self._transition_to(ShadowFrontState.ARMED, current_ts_ns,
                                   f"evidence_sufficient_conf={self._calculate_armed_confidence(current_ts_ns):.2f}")
        
        elif self._current_state == ShadowFrontState.ARMED:
            # Decay if whale zone lost or stale
            if self._whale is None or not self._whale.is_active or not self._is_whale_fresh(current_ts_ns):
                self._transition_to(ShadowFrontState.IDLE, current_ts_ns, "whale_zone_lost_or_stale")
        
        elif self._current_state == ShadowFrontState.IGNITION:
            # Check for entry
            if self._should_enter_position(current_price, current_ts_ns):
                action = "enter"
            
            # Timeout if ignition takes too long (30 seconds)
            elif self._last_transition and (current_ts_ns - self._last_transition.timestamp_ns) > 30_000_000_000:
                self._transition_to(ShadowFrontState.ARMED, current_ts_ns, "ignition_timeout")
        
        elif self._current_state == ShadowFrontState.ACTIVE:
            # Check for exit
            should_exit, reason = self._should_exit_position(current_price, current_ts_ns)
            if should_exit:
                self._transition_to(ShadowFrontState.COOLDOWN, current_ts_ns, reason)
                self._cooldown_until_ns = current_ts_ns + self.cooldown_seconds_ns
                action = "exit"
        
        elif self._current_state == ShadowFrontState.COOLDOWN:
            if self._should_cooldown_expire(current_ts_ns):
                self._transition_to(ShadowFrontState.IDLE, current_ts_ns, "cooldown_expired")
                self._cooldown_until_ns = None
        
        return action
    
    # ============================================
    # POSITION MANAGEMENT
    # ============================================
    
    def record_entry(self, price: float, size: float, timestamp_ns: int) -> None:
        """
        Record position entry after receiving "enter" action.
        
        Validates that machine is in IGNITION state before recording.
        
        Args:
            price: Entry price
            size: Position size
            timestamp_ns: Entry timestamp
        """
        if self._current_state != ShadowFrontState.IGNITION:
            logger.warning(f"record_entry called in invalid state: {self._current_state.name}")
            return
        
        self._entry_price = price
        self._entry_time_ns = timestamp_ns
        self._position_size = size
        self._pnl = 0.0
        
        self._transition_to(ShadowFrontState.ACTIVE, timestamp_ns, "entry_executed")
    
    def record_exit(self, price: float, pnl: float, timestamp_ns: int) -> None:
        """
        Record position exit after receiving "exit" action.
        
        Validates that machine is in ACTIVE or COOLDOWN state before recording.
        
        Args:
            price: Exit price
            pnl: Profit/loss
            timestamp_ns: Exit timestamp
        """
        if self._current_state not in (ShadowFrontState.ACTIVE, ShadowFrontState.COOLDOWN):
            logger.warning(f"record_exit called in invalid state: {self._current_state.name}")
            return
        
        self._entry_price = None
        self._entry_time_ns = None
        self._position_size = 0.0
        self._pnl = pnl
    
    # ============================================
    # QUERY METHODS
    # ============================================
    
    def get_current_state(self) -> ShadowFrontState:
        """Return current state."""
        return self._current_state
    
    def get_state_name(self) -> str:
        """Return current state name as string."""
        return self._current_state.name
    
    def is_ready_for_entry(self) -> bool:
        """Check if state machine is ready for position entry."""
        return self._current_state == ShadowFrontState.IGNITION
    
    def is_in_position(self) -> bool:
        """Check if currently in a position."""
        return self._current_state == ShadowFrontState.ACTIVE
    
    def get_entry_price(self) -> Optional[float]:
        """Return entry price if in position."""
        return self._entry_price
    
    def get_position_size(self) -> float:
        """Return current position size."""
        return self._position_size
    
    def get_pnl(self) -> float:
        """Return current P&L."""
        return self._pnl
    
    def get_whale_zone(self) -> Tuple[Optional[float], Optional[float]]:
        """Return current whale zone (low, high)."""
        if self._whale:
            return self._whale.zone_low, self._whale.zone_high
        return None, None
    
    def get_whale_confidence(self) -> float:
        """Return current whale confidence."""
        return self._whale.confidence if self._whale else 0.0
    
    def get_armed_confidence(self, current_ts_ns: int) -> float:
        """Return current armed confidence score."""
        return self._calculate_armed_confidence(current_ts_ns)
    
    def get_conflict_penalty(self, current_ts_ns: int) -> float:
        """Return current conflict penalty factor."""
        return self._calculate_conflict_penalty(current_ts_ns)
    
    def get_alignment_bonus(self, current_ts_ns: int) -> float:
        """Return current alignment bonus factor."""
        return self._calculate_alignment_bonus(current_ts_ns)
    
    def get_transition_history(self, count: int = 10) -> list:
        """Return recent transition history."""
        return self._transition_history[-count:]
    
    def get_status(self, current_ts_ns: int) -> Dict[str, Any]:
        """Get current status for monitoring."""
        # Calculate cooldown remaining
        cooldown_remaining = 0.0
        if self._cooldown_until_ns is not None:
            remaining_ns = max(0, self._cooldown_until_ns - current_ts_ns)
            cooldown_remaining = remaining_ns / 1_000_000_000.0
        
        # Calculate macro kill remaining
        macro_kill_remaining = 0.0
        if self._macro_kill_until_ns is not None:
            remaining_ns = max(0, self._macro_kill_until_ns - current_ts_ns)
            macro_kill_remaining = remaining_ns / 1_000_000_000.0
        
        return {
            "symbol": self.symbol,
            "state": self._current_state.name,
            "in_position": self.is_in_position(),
            "whale_active": self._whale is not None and self._whale.is_active,
            "whale_fresh": self._is_whale_fresh(current_ts_ns),
            "whale_confidence": self.get_whale_confidence(),
            "armed_confidence": self.get_armed_confidence(current_ts_ns),
            "conflict_penalty": self.get_conflict_penalty(current_ts_ns),
            "alignment_bonus": self.get_alignment_bonus(current_ts_ns),
            "entry_price": self._entry_price,
            "position_size": self._position_size,
            "pnl": self._pnl,
            "cooldown_remaining_sec": cooldown_remaining,
            "macro_kill_remaining_sec": macro_kill_remaining,
            "whale_update_count": self._whale_update_count,
            "ignition_trigger_count": self._ignition_trigger_count,
            "last_transition": self._last_transition.reason if self._last_transition else None,
            "last_transition_time_ns": self._last_transition.timestamp_ns if self._last_transition else None,
            "last_update_time_ns": self._last_update_ts_ns,
            "state_hash": self.state_hash_hex()
        }
    
    def reset(self, current_ts_ns: int) -> None:
        """
        Reset state machine completely.
        
        Args:
            current_ts_ns: Current timestamp for transition record
        """
        self._transition_to(ShadowFrontState.IDLE, current_ts_ns, "manual_reset")
        self._whale = None
        self._sentiment = None
        self._regime = None
        self._fusion = None
        self._entry_price = None
        self._entry_time_ns = None
        self._position_size = 0.0
        self._pnl = 0.0
        self._cooldown_until_ns = None
        self._macro_kill_until_ns = None
        self._whale_zone_start_ns = None
        self._whale_update_count = 0
        self._ignition_trigger_count = 0
        self._whale_last_ts_ns = None
        self._sentiment_last_ts_ns = None
        self._regime_last_ts_ns = None
        self._fusion_last_ts_ns = None
        logger.info(f"ShadowFront[{self.symbol}]: State machine reset")