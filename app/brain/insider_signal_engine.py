"""
Insider Signal Engine - Informed Participant Intelligence Engine
CITADEL GRADE — DETERMINISTIC · REPLAY-SAFE · NO WALL-CLOCK

ANALYTICAL/NON-MONETARY BOUNDARY:
This engine transforms structured observations of informed-participant activity
into bounded directional pressure, confidence, freshness, contradiction,
invalidation, and actionable symbol snapshots.
All values are analytical estimates, not legal/compliance truth.
No privileged data access. No SEC/news/congressional connectors.

ROLE: Urgency / Escalation Source for Fusion
- Primary output: urgency = confidence * (1 + cluster_strength), capped at 2.0
- Secondary outputs: directional_bias, net_pressure, confidence
- NOT: primary direction oracle (whale_flow_engine owns that)
- NOT: generic market activity detector
- NOT: replacement for entropy or regime detection

What this engine can truthfully detect (from observable data):
- Unusual trade clustering (cluster_strength)
- Cross-entity alignment (multiple entities acting similarly)
- Sustained directional pressure (net_pressure, directional_bias)
- Freshness decay (older evidence weighs less)

What this engine cannot truthfully claim:
- Actual insider knowledge (no privileged data)
- Entity resolution beyond placeholder IDs
- Event catalyst detection (requires external event feed)
- Production-calibrated source reliability (weights are provisional)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, getcontext
from enum import Enum, auto
from typing import Dict, List, Optional, Sequence, Tuple, Mapping, Any, Set
from collections import deque

# Decimal precision for all analytical scoring
getcontext().prec = 28

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
# ============================================================================

class ObservationDirection(Enum):
    """Direction of an informed-participant observation."""
    BUY = auto()
    SELL = auto()
    UNKNOWN = auto()


class ObservationSourceType(Enum):
    """Source type classification for an observation."""
    FLOW = auto()      # Order flow / trade-based
    ENTITY = auto()    # Entity-specific (e.g., known participant)
    EVENT = auto()     # Event-driven (e.g., scheduled announcement)
    CLUSTER = auto()   # Detected cluster of activity
    OTHER = auto()     # Other validated source


class DirectionalBias(Enum):
    """Overall directional bias of a symbol snapshot."""
    BULLISH = auto()
    BEARISH = auto()
    NEUTRAL = auto()


class SymbolTier(Enum):
    """
    Tier for dead-zone and threshold configuration.
    
    PERSISTENCE NOTE: Uses stable symbolic names (value property) for
    serialization, NOT auto() integer values. This ensures schema stability
    across Python versions and enum reorderings.
    """
    LIQUID = "liquid"      # High liquidity, lower thresholds
    MID = "mid"            # Medium liquidity, standard thresholds
    ILLIQUID = "illiquid"  # Low liquidity, higher thresholds


# ============================================================================
# CONSTANTS
# ============================================================================

# State limits
DEFAULT_MAX_SYMBOLS = 100
DEFAULT_MAX_OBSERVATIONS_PER_SYMBOL = 200
DEFAULT_MAX_DEDUPE_IDS_PER_SYMBOL = 500
DEFAULT_MAX_ENTITIES_PER_SYMBOL = 50
DEFAULT_DEDUPE_WINDOW_NS = 86400_000_000_000  # 24 hours

# Decimal thresholds
DECIMAL_ZERO = Decimal('0')
DECIMAL_ONE = Decimal('1')
DECIMAL_HALF = Decimal('0.5')
DECIMAL_TENTH = Decimal('0.1')
DECIMAL_HUNDREDTH = Decimal('0.01')
DECIMAL_THOUSANDTH = Decimal('0.001')

# Score bounds
MIN_SCORE = DECIMAL_ZERO
MAX_SCORE = DECIMAL_ONE
MIN_CONFIDENCE = DECIMAL_ZERO
MAX_CONFIDENCE = DECIMAL_ONE

# Decay parameters (nanoseconds)
DEFAULT_DECAY_HALF_LIFE_NS = 3600_000_000_000  # 1 hour
DEFAULT_FRESHNESS_HALF_LIFE_NS = 1800_000_000_000  # 30 minutes
DEFAULT_PRUNE_AGE_NS = 86400_000_000_000       # 24 hours
DEFAULT_CLUSTER_HALF_LIFE_NS = 600_000_000_000  # 10 minutes
DEFAULT_ENTITY_REPUTATION_HALF_LIFE_NS = 7200_000_000_000  # 2 hours

# Active state thresholds (base for LIQUID tier)
DEFAULT_ACTIVE_MIN_CONFIDENCE = Decimal('0.55')
DEFAULT_ACTIVE_MIN_FRESHNESS = Decimal('0.4')
DEFAULT_DEGRADED_MAX_CONFIDENCE = Decimal('0.35')
DEFAULT_INVALIDATION_THRESHOLD = Decimal('0.7')

# Per-tier multipliers
TIER_MULTIPLIERS = {
    SymbolTier.LIQUID: {
        "active_min_confidence": Decimal('0.55'),
        "active_min_freshness": Decimal('0.4'),
        "degraded_max_confidence": Decimal('0.35'),
        "bias_threshold": Decimal('0.05'),
        "chatter_threshold": Decimal('0.02'),
    },
    SymbolTier.MID: {
        "active_min_confidence": Decimal('0.60'),
        "active_min_freshness": Decimal('0.45'),
        "degraded_max_confidence": Decimal('0.40'),
        "bias_threshold": Decimal('0.06'),
        "chatter_threshold": Decimal('0.03'),
    },
    SymbolTier.ILLIQUID: {
        "active_min_confidence": Decimal('0.70'),
        "active_min_freshness": Decimal('0.50'),
        "degraded_max_confidence": Decimal('0.45'),
        "bias_threshold": Decimal('0.08'),
        "chatter_threshold": Decimal('0.04'),
    },
}

# Cluster strength parameters
CLUSTER_TIME_WINDOW_NS = 300_000_000_000  # 5 minutes
CLUSTER_MIN_OBSERVATIONS = 3
CLUSTER_MAX_STRENGTH = DECIMAL_ONE

# Entity reputation parameters
ENTITY_REPUTATION_MAX = Decimal('1.5')
ENTITY_REPUTATION_DEFAULT = Decimal('1.0')
ENTITY_REPUTATION_BOOST_PER_OBSERVATION = Decimal('0.05')
ENTITY_REPUTATION_MAX_BOOST = Decimal('0.5')

# Cross-entity coordination
CROSS_ENTITY_ALIGNMENT_BOOST_MAX = Decimal('0.15')
CROSS_ENTITY_MIN_ENTITIES = 2

# Toxicity modifier bounds
TOXICITY_PENALTY_MAX = Decimal('0.5')
REGIME_MULTIPLIER_MAX = Decimal('1.5')
REGIME_MULTIPLIER_MIN = Decimal('0.5')

# Contradiction scaling
CONTRADICTION_BASE_FACTOR = Decimal('0.3')
CONTRADICTION_MAX = DECIMAL_ONE

# Dead-zone suppression
DEAD_ZONE_DECAY_FACTOR = Decimal('0.95')

# State schema version
STATE_SCHEMA_VERSION = 6  # Incremented: SymbolTier now uses stable symbolic names

# Direction code for persistence
DIRECTION_CODE_BUY = 1
DIRECTION_CODE_SELL = -1
DIRECTION_CODE_UNKNOWN = 0


# ============================================================================
# OBSERVATION MODEL
# ============================================================================

@dataclass(frozen=True, slots=True)
class InsiderObservation:
    """
    Structured observation of informed-participant activity.
    
    All Decimal fields must be in [0, 1] range except where noted.
    """
    observation_id: str
    timestamp_ns: int
    symbol: str
    entity_id: str
    direction: ObservationDirection
    intensity: Decimal                # 0-1, strength of the signal
    notional_weight: Decimal          # 0-1, relative size/importance
    source_reliability: Decimal       # 0-1, trust in source
    event_proximity_weight: Decimal   # 0-1, closeness to catalyst
    novelty_weight: Decimal           # 0-1, new information content
    corroboration_weight: Decimal     # 0-1, agreement with others
    invalidation_weight: Decimal      # 0-1, counter-evidence strength
    source_type: ObservationSourceType
    tags: Tuple[str, ...] = ()
    notes: str = ""


# ============================================================================
# SNAPSHOT MODEL
# ============================================================================

@dataclass(frozen=True, slots=True)
class InsiderSignalSnapshot:
    """
    Immutable snapshot of a symbol's informed-participant state.
    
    PRIMARY OUTPUT FOR FUSION: urgency property (Decimal) and to_float() bridge.
    
    Urgency interpretation:
        - 0.0-0.5: Low urgency, normal conditions
        - 0.5-1.0: Elevated urgency, consider escalation
        - 1.0-1.5: High urgency, escalate
        - 1.5-2.0: Extreme urgency, attack mode co-trigger
    """
    symbol: str
    timestamp_ns: int
    last_observation_ns: int
    last_directional_observation_ns: int
    last_state_transition_ns: int
    bullish_score: Decimal
    bearish_score: Decimal
    net_pressure: Decimal
    confidence: Decimal
    freshness: Decimal
    cluster_strength: Decimal
    contradiction_pressure: Decimal
    invalidation_pressure: Decimal
    directional_bias: DirectionalBias
    active: bool
    degraded: bool
    invalidated: bool
    supporting_observation_count: int

    @property
    def urgency(self) -> Decimal:
        """
        Primary output for fusion as Decimal (precision-preserving).
        
        urgency = confidence * (1 + cluster_strength), capped at 2.0.
        This is the scalar that should be passed to fusion for:
        - Confidence boosting (insider_mult, insider_factor)
        - Attack mode co-trigger (with shans_superfluid > 0.8)
        
        Returns:
            Decimal urgency in [0, 2.0]
        """
        raw = self.confidence * (DECIMAL_ONE + self.cluster_strength)
        if raw > Decimal('2.0'):
            return Decimal('2.0')
        if raw < DECIMAL_ZERO:
            return DECIMAL_ZERO
        return raw

    def to_float(self) -> float:
        """
        Explicit float bridge for downstream compatibility.
        
        SignalFusion.update_insider() expects float. This method makes
        the precision boundary explicit rather than implicit.
        
        Returns:
            Float representation of urgency, clamped to [0.0, 2.0]
        """
        return float(self.urgency)

    def to_dict(self) -> Dict[str, Any]:
        """
        Explicit serialization for snapshot export.
        
        Returns a JSON-serializable dictionary with stable field names
        and stringified Decimal values.
        """
        return {
            "symbol": self.symbol,
            "timestamp_ns": self.timestamp_ns,
            "last_observation_ns": self.last_observation_ns,
            "last_directional_observation_ns": self.last_directional_observation_ns,
            "last_state_transition_ns": self.last_state_transition_ns,
            "bullish_score": str(self.bullish_score),
            "bearish_score": str(self.bearish_score),
            "net_pressure": str(self.net_pressure),
            "confidence": str(self.confidence),
            "freshness": str(self.freshness),
            "cluster_strength": str(self.cluster_strength),
            "contradiction_pressure": str(self.contradiction_pressure),
            "invalidation_pressure": str(self.invalidation_pressure),
            "directional_bias": self.directional_bias.value,
            "active": self.active,
            "degraded": self.degraded,
            "invalidated": self.invalidated,
            "supporting_observation_count": self.supporting_observation_count,
            "urgency_float": self.to_float(),
        }


# ============================================================================
# INTERNAL STATE MODELS
# ============================================================================

@dataclass(slots=True)
class _EntityActivity:
    """Per-entity activity tracking with reputation and directional totals."""
    last_timestamp_ns: int = 0
    bullish_contribution: Decimal = DECIMAL_ZERO
    bearish_contribution: Decimal = DECIMAL_ZERO
    observation_count: int = 0
    reputation: Decimal = ENTITY_REPUTATION_DEFAULT
    
    @property
    def net_contribution(self) -> Decimal:
        return self.bullish_contribution - self.bearish_contribution


@dataclass(slots=True)
class _SymbolState:
    """Mutable internal state for a single symbol."""
    # Core scores
    bullish_score: Decimal = DECIMAL_ZERO
    bearish_score: Decimal = DECIMAL_ZERO
    
    # State flags
    active: bool = False
    degraded: bool = False
    invalidated: bool = False
    
    # Derived values (cached)
    confidence: Decimal = DECIMAL_ZERO
    freshness: Decimal = DECIMAL_ONE
    cluster_strength: Decimal = DECIMAL_ZERO
    contradiction_pressure: Decimal = DECIMAL_ZERO
    invalidation_pressure: Decimal = DECIMAL_ZERO
    
    # Temporal tracking
    last_observation_ns: int = 0
    last_directional_observation_ns: int = 0
    last_decay_ns: int = 0
    last_state_transition_ns: int = 0
    last_invalidation_ns: int = 0
    last_invalidation_reason: str = ""
    
    # Tier configuration (persisted by stable symbolic name)
    tier: SymbolTier = SymbolTier.MID
    
    # Supporting data
    supporting_observation_count: int = 0
    directional_observation_count: int = 0
    
    # Deduplication: deque + set for O(1) membership
    observation_ids_deque: deque = field(default_factory=lambda: deque(maxlen=DEFAULT_MAX_DEDUPE_IDS_PER_SYMBOL))
    observation_ids_set: Set[str] = field(default_factory=set)
    
    # Recent observation history (for clustering)
    recent_observations: deque = field(default_factory=lambda: deque(maxlen=DEFAULT_MAX_OBSERVATIONS_PER_SYMBOL))
    
    # Per-entity activity
    entity_activity: Dict[str, _EntityActivity] = field(default_factory=dict)
    
    def add_observation_id(self, obs_id: str, timestamp_ns: int) -> bool:
        """Add observation ID to dedupe structures. Returns True if new."""
        if obs_id in self.observation_ids_set:
            return False
        self.observation_ids_deque.append((obs_id, timestamp_ns))
        self.observation_ids_set.add(obs_id)
        
        # Prune old IDs beyond window
        while self.observation_ids_deque and self.observation_ids_deque[0][1] < timestamp_ns - DEFAULT_DEDUPE_WINDOW_NS:
            old_id, _ = self.observation_ids_deque.popleft()
            self.observation_ids_set.discard(old_id)
        
        return True
    
    def has_observation_id(self, obs_id: str) -> bool:
        """Check if observation ID is already seen."""
        return obs_id in self.observation_ids_set
    
    def collapse_dead_zone(self, thresholds: Dict[str, Decimal]) -> None:
        """Collapse tiny residuals toward zero."""
        chatter_threshold = thresholds.get("chatter_threshold", Decimal('0.02'))
        if self.bullish_score < chatter_threshold:
            self.bullish_score = DECIMAL_ZERO
        if self.bearish_score < chatter_threshold:
            self.bearish_score = DECIMAL_ZERO
        if abs(self.bullish_score - self.bearish_score) < chatter_threshold:
            if self.bullish_score < chatter_threshold and self.bearish_score < chatter_threshold:
                self.bullish_score = DECIMAL_ZERO
                self.bearish_score = DECIMAL_ZERO
    
    def _has_state_changed(self, old_active: bool, old_degraded: bool, old_invalidated: bool) -> bool:
        """Check if state flags have changed."""
        return (old_active != self.active or 
                old_degraded != self.degraded or 
                old_invalidated != self.invalidated)
    
    def _recompute_derived(self, thresholds: Dict[str, Decimal]) -> None:
        """Recompute confidence and state flags from current scores."""
        # Base from net pressure magnitude
        net_abs = abs(self.bullish_score - self.bearish_score)
        
        # Reduce by contradiction
        contra_factor = DECIMAL_ONE - (self.contradiction_pressure * CONTRADICTION_BASE_FACTOR)
        if contra_factor < DECIMAL_ZERO:
            contra_factor = DECIMAL_ZERO
        
        # Reduce by invalidation
        inval_factor = DECIMAL_ONE - self.invalidation_pressure
        if inval_factor < DECIMAL_ZERO:
            inval_factor = DECIMAL_ZERO
        
        # Cluster strength boosts confidence
        cluster_boost = self.cluster_strength * Decimal('0.2')
        
        new_confidence = net_abs * contra_factor * inval_factor + cluster_boost
        if new_confidence > MAX_CONFIDENCE:
            new_confidence = MAX_CONFIDENCE
        if new_confidence < MIN_CONFIDENCE:
            new_confidence = MIN_CONFIDENCE
        
        # Dead-zone suppression
        chatter_threshold = thresholds.get("chatter_threshold", Decimal('0.02'))
        if new_confidence < chatter_threshold and net_abs < chatter_threshold:
            new_confidence = DECIMAL_ZERO
        
        self.confidence = new_confidence
        
        # Derive flags
        active_min_confidence = thresholds.get("active_min_confidence", DEFAULT_ACTIVE_MIN_CONFIDENCE)
        active_min_freshness = thresholds.get("active_min_freshness", DEFAULT_ACTIVE_MIN_FRESHNESS)
        degraded_max_confidence = thresholds.get("degraded_max_confidence", DEFAULT_DEGRADED_MAX_CONFIDENCE)
        
        invalidated = (
            self.invalidation_pressure >= DEFAULT_INVALIDATION_THRESHOLD or
            (self.confidence < active_min_confidence * Decimal('0.3') and 
             self.directional_observation_count > 0)
        )
        
        active = (
            not invalidated and
            self.confidence >= active_min_confidence and
            self.freshness >= active_min_freshness and
            self.directional_observation_count > 0
        )
        
        degraded = (
            not invalidated and not active and
            self.confidence >= degraded_max_confidence and
            self.directional_observation_count > 0
        )
        
        self.invalidated = invalidated
        self.active = active
        self.degraded = degraded


# ============================================================================
# INSIDER SIGNAL ENGINE
# ============================================================================

class InsiderSignalEngine:
    """
    Deterministic informed-participant intelligence engine.
    
    Transforms structured observations into bounded directional pressure,
    confidence, freshness, contradiction, invalidation, and actionable snapshots.
    
    PRIMARY OUTPUT: InsiderSignalSnapshot.urgency (Decimal) and .to_float()
    This is the scalar that downstream fusion should consume for:
        - Confidence boosting (insider_mult, insider_factor)
        - Attack mode co-trigger (with shans_superfluid > 0.8)
    
    SECONDARY OUTPUTS:
        - directional_bias: BULLISH/BEARISH/NEUTRAL (use with caution)
        - net_pressure: signed directional strength
        - confidence: analytical confidence in the snapshot
    
    TRUTHFUL CAPABILITIES (from observable data):
        - Detects unusual trade clustering (cluster_strength)
        - Detects cross-entity alignment (multiple entities acting similarly)
        - Tracks sustained directional pressure (net_pressure)
        - Applies exponential decay to age out stale evidence
    
    LIMITATIONS (explicit, not hidden):
        - Entity IDs are placeholders without external resolution
        - Source reliability weights are provisional
        - No event catalyst detection (requires external feed)
        - No actual privileged data access
    
    All operations are replay-safe, nanosecond-timestamped, and Decimal-only.
    No external dependencies on peer engines.
    """
    
    def __init__(
        self,
        max_symbols: int = DEFAULT_MAX_SYMBOLS,
        decay_half_life_ns: int = DEFAULT_DECAY_HALF_LIFE_NS,
        freshness_half_life_ns: int = DEFAULT_FRESHNESS_HALF_LIFE_NS,
        prune_age_ns: int = DEFAULT_PRUNE_AGE_NS,
        cluster_half_life_ns: int = DEFAULT_CLUSTER_HALF_LIFE_NS,
        entity_reputation_half_life_ns: int = DEFAULT_ENTITY_REPUTATION_HALF_LIFE_NS,
    ):
        """
        Initialize the insider signal engine.
        
        Args:
            max_symbols: Maximum number of symbols to track
            decay_half_life_ns: Half-life for score decay in nanoseconds
            freshness_half_life_ns: Half-life for freshness decay
            prune_age_ns: Age after which symbols are pruned
            cluster_half_life_ns: Half-life for cluster density decay
            entity_reputation_half_life_ns: Half-life for entity reputation decay
        """
        self._max_symbols = max_symbols
        self._decay_half_life_ns = decay_half_life_ns
        self._freshness_half_life_ns = freshness_half_life_ns
        self._prune_age_ns = prune_age_ns
        self._cluster_half_life_ns = cluster_half_life_ns
        self._entity_reputation_half_life_ns = entity_reputation_half_life_ns
        
        # Per-symbol state
        self._symbols: Dict[str, _SymbolState] = {}
        
        logger.info(
            f"InsiderSignalEngine initialized: max_symbols={max_symbols}, "
            f"decay_half_life_ns={decay_half_life_ns}, "
            f"freshness_half_life_ns={freshness_half_life_ns}"
        )
    
    # =========================================================================
    # VALIDATION HELPERS
    # =========================================================================
    
    @staticmethod
    def _clamp_decimal(value: Decimal, min_val: Decimal = MIN_SCORE, max_val: Decimal = MAX_SCORE) -> Decimal:
        """Clamp a Decimal value to [min_val, max_val]."""
        if value < min_val:
            return min_val
        if value > max_val:
            return max_val
        return value
    
    def _get_tier_thresholds(self, tier: SymbolTier) -> Dict[str, Decimal]:
        """Get thresholds for a given tier."""
        return TIER_MULTIPLIERS.get(tier, TIER_MULTIPLIERS[SymbolTier.MID])
    
    @staticmethod
    def _validate_observation(obs: InsiderObservation) -> None:
        """Validate an observation's fields."""
        if not obs.observation_id:
            raise ValueError("observation_id must be non-empty")
        if not obs.symbol:
            raise ValueError("symbol must be non-empty")
        if not isinstance(obs.timestamp_ns, int) or obs.timestamp_ns <= 0:
            raise ValueError(f"timestamp_ns must be positive int: {obs.timestamp_ns}")
        
        for field_name in ['intensity', 'notional_weight', 'source_reliability',
                          'event_proximity_weight', 'novelty_weight', 
                          'corroboration_weight', 'invalidation_weight']:
            val = getattr(obs, field_name)
            if not isinstance(val, Decimal):
                raise ValueError(f"{field_name} must be Decimal, got {type(val)}")
            if val < DECIMAL_ZERO or val > DECIMAL_ONE:
                raise ValueError(f"{field_name} must be in [0,1], got {val}")
    
    @staticmethod
    def _validate_modifier(modifier: Optional[Decimal], name: str, max_val: Decimal = DECIMAL_ONE) -> Optional[Decimal]:
        """Validate an optional modifier Decimal."""
        if modifier is None:
            return None
        if not isinstance(modifier, Decimal):
            raise ValueError(f"{name} must be Decimal or None")
        if modifier < DECIMAL_ZERO or modifier > max_val:
            raise ValueError(f"{name} must be in [0,{max_val}], got {modifier}")
        return modifier
    
    # =========================================================================
    # PRIVATE SCORING HELPERS
    # =========================================================================
    
    def _compute_base_contribution(self, obs: InsiderObservation, entity_reputation: Decimal) -> Tuple[Decimal, Decimal]:
        """
        Compute base bullish and bearish contributions from an observation.
        
        Returns:
            Tuple of (bullish_contribution, bearish_contribution)
        """
        # Weighted combination of observation attributes
        weight = (
            obs.intensity * Decimal('0.25') +
            obs.notional_weight * Decimal('0.15') +
            obs.source_reliability * Decimal('0.20') +
            obs.novelty_weight * Decimal('0.10') +
            obs.event_proximity_weight * Decimal('0.10') +
            obs.corroboration_weight * Decimal('0.20')
        )
        weight = self._clamp_decimal(weight)
        
        # Apply entity reputation boost (capped)
        reputation_boost = (entity_reputation - ENTITY_REPUTATION_DEFAULT) / ENTITY_REPUTATION_MAX
        reputation_boost = self._clamp_decimal(reputation_boost, min_val=DECIMAL_ZERO, max_val=Decimal('0.3'))
        weight = weight * (DECIMAL_ONE + reputation_boost)
        weight = self._clamp_decimal(weight)
        
        # Directional allocation
        if obs.direction == ObservationDirection.BUY:
            return weight, DECIMAL_ZERO
        elif obs.direction == ObservationDirection.SELL:
            return DECIMAL_ZERO, weight
        else:  # UNKNOWN
            return DECIMAL_ZERO, DECIMAL_ZERO
    
    def _apply_context_modifiers(
        self,
        contribution: Decimal,
        regime_multiplier: Optional[Decimal],
        toxicity_penalty: Optional[Decimal]
    ) -> Decimal:
        """Apply optional external modifiers to a contribution."""
        result = contribution
        
        if regime_multiplier is not None:
            result = result * regime_multiplier
        
        if toxicity_penalty is not None:
            result = result * (DECIMAL_ONE - toxicity_penalty)
        
        return self._clamp_decimal(result)
    
    def _compute_cluster_strength(self, state: _SymbolState, current_ts_ns: int) -> Decimal:
        """
        Compute exponentially decaying temporal cluster density.
        
        Uses bounded recent observation history with recency weighting.
        Decay factor = 0.5 ** (age_ns / cluster_half_life_ns)
        """
        if len(state.recent_observations) < CLUSTER_MIN_OBSERVATIONS:
            return DECIMAL_ZERO
        
        total_weight = DECIMAL_ZERO
        aligned_weight = DECIMAL_ZERO
        
        for obs_ts, direction_code in state.recent_observations:
            age_ns = current_ts_ns - obs_ts
            if age_ns < 0:
                continue
            
            # Direct exponential decay: 0.5 ** (age_ns / half_life_ns)
            if age_ns == 0:
                weight = DECIMAL_ONE
            else:
                exponent = Decimal(age_ns) / Decimal(self._cluster_half_life_ns)
                weight = Decimal('0.5') ** exponent
            weight = self._clamp_decimal(weight)
            
            total_weight += weight
            
            # direction_code: 1 = buy, -1 = sell, 0 = unknown
            direction_value = Decimal(direction_code)
            aligned_weight += weight * direction_value
        
        if total_weight <= DECIMAL_ZERO:
            return DECIMAL_ZERO
        
        # Weighted average of directional alignment (abs value)
        cluster_abs = abs(aligned_weight / total_weight)
        cluster_abs = self._clamp_decimal(cluster_abs)
        
        # Density bonus
        density = Decimal(len(state.recent_observations)) / Decimal(CLUSTER_MIN_OBSERVATIONS)
        density = self._clamp_decimal(density, max_val=Decimal('1.5'))
        
        result = cluster_abs * density * Decimal('0.7')
        return self._clamp_decimal(result, max_val=CLUSTER_MAX_STRENGTH)
    
    def _compute_cross_entity_alignment(self, state: _SymbolState, current_ts_ns: int) -> Decimal:
        """
        Detect alignment among multiple distinct entities within recent window.
        
        Returns boost factor in [1.0, 1.0 + CROSS_ENTITY_ALIGNMENT_BOOST_MAX].
        """
        window_start = current_ts_ns - CLUSTER_TIME_WINDOW_NS
        
        # Collect net directional bias per entity
        entity_biases: List[Decimal] = []
        
        for entity_id, activity in state.entity_activity.items():
            if activity.last_timestamp_ns >= window_start and activity.observation_count >= 1:
                entity_biases.append(activity.net_contribution)
        
        if len(entity_biases) < CROSS_ENTITY_MIN_ENTITIES:
            return DECIMAL_ONE
        
        # Count entities with positive vs negative net bias
        positive_count = sum(1 for b in entity_biases if b > DECIMAL_ZERO)
        negative_count = sum(1 for b in entity_biases if b < DECIMAL_ZERO)
        
        if positive_count >= CROSS_ENTITY_MIN_ENTITIES:
            alignment = Decimal(positive_count) / Decimal(len(entity_biases))
        elif negative_count >= CROSS_ENTITY_MIN_ENTITIES:
            alignment = Decimal(negative_count) / Decimal(len(entity_biases))
        else:
            alignment = DECIMAL_ZERO
        
        boost = DECIMAL_ONE + (alignment * CROSS_ENTITY_ALIGNMENT_BOOST_MAX)
        return self._clamp_decimal(boost, min_val=DECIMAL_ONE, max_val=DECIMAL_ONE + CROSS_ENTITY_ALIGNMENT_BOOST_MAX)
    
    def _update_contradiction_pressure(self, state: _SymbolState, new_bullish: Decimal, new_bearish: Decimal) -> Decimal:
        """
        Update contradiction pressure scaled to existing state strength.
        """
        current_net = state.bullish_score - state.bearish_score
        new_net = new_bullish - new_bearish
        
        # Scale contradiction by current state strength
        current_strength = abs(current_net)
        opposition = abs(new_net) if (current_net * new_net) < DECIMAL_ZERO else DECIMAL_ZERO
        
        # Contradiction increase scales with current strength
        increase = opposition * current_strength * CONTRADICTION_BASE_FACTOR
        state.contradiction_pressure = self._clamp_decimal(
            state.contradiction_pressure + increase,
            max_val=CONTRADICTION_MAX
        )
        
        # Natural decay
        state.contradiction_pressure = state.contradiction_pressure * Decimal('0.98')
        state.contradiction_pressure = self._clamp_decimal(state.contradiction_pressure)
        
        return state.contradiction_pressure
    
    def _update_invalidation_pressure(self, state: _SymbolState, obs_invalidation: Decimal) -> Decimal:
        """Update invalidation pressure from observation invalidation weight."""
        if obs_invalidation > DECIMAL_ZERO:
            state.invalidation_pressure = self._clamp_decimal(
                state.invalidation_pressure + obs_invalidation * Decimal('0.3')
            )
        else:
            state.invalidation_pressure = self._clamp_decimal(
                state.invalidation_pressure * Decimal('0.98')
            )
        
        return state.invalidation_pressure
    
    def _apply_decay_to_state(self, state: _SymbolState, current_ts_ns: int) -> None:
        """
        Apply deterministic decay to a symbol's state.
        Does NOT mutate last_observation_ns.
        
        Decay factor = 0.5 ** (elapsed_ns / half_life_ns)
        """
        if state.last_decay_ns == 0:
            state.last_decay_ns = current_ts_ns
            return
        
        if current_ts_ns <= state.last_decay_ns:
            return
        
        elapsed_ns = current_ts_ns - state.last_decay_ns
        if elapsed_ns <= 0:
            return
        
        # Score decay factor: 0.5 ** (elapsed_ns / decay_half_life_ns)
        if elapsed_ns == 0:
            decay_factor = DECIMAL_ONE
        else:
            exponent = Decimal(elapsed_ns) / Decimal(self._decay_half_life_ns)
            decay_factor = Decimal('0.5') ** exponent
        decay_factor = self._clamp_decimal(decay_factor, min_val=DECIMAL_ZERO, max_val=DECIMAL_ONE)
        
        # Apply decay to scores
        state.bullish_score = state.bullish_score * decay_factor
        state.bearish_score = state.bearish_score * decay_factor
        
        # Freshness decay (from last directional observation)
        # Freshness factor = 0.5 ** (age_ns / freshness_half_life_ns)
        if state.last_directional_observation_ns > 0:
            freshness_age_ns = current_ts_ns - state.last_directional_observation_ns
            if freshness_age_ns > 0:
                if freshness_age_ns == 0:
                    freshness_factor = DECIMAL_ONE
                else:
                    freshness_exponent = Decimal(freshness_age_ns) / Decimal(self._freshness_half_life_ns)
                    freshness_factor = Decimal('0.5') ** freshness_exponent
                state.freshness = self._clamp_decimal(freshness_factor, max_val=DECIMAL_ONE)
        else:
            state.freshness = DECIMAL_ZERO
        
        # Invalidation pressure decay
        state.invalidation_pressure = state.invalidation_pressure * decay_factor
        state.contradiction_pressure = state.contradiction_pressure * decay_factor
        
        # Cluster strength decay: 0.5 ** (elapsed_ns / cluster_half_life_ns)
        if elapsed_ns == 0:
            cluster_factor = DECIMAL_ONE
        else:
            cluster_exponent = Decimal(elapsed_ns) / Decimal(self._cluster_half_life_ns)
            cluster_factor = Decimal('0.5') ** cluster_exponent
        state.cluster_strength = state.cluster_strength * cluster_factor
        state.cluster_strength = self._clamp_decimal(state.cluster_strength)
        
        # Entity reputation decay: 0.5 ** (elapsed_ns / entity_reputation_half_life_ns)
        if elapsed_ns == 0:
            reputation_factor = DECIMAL_ONE
        else:
            reputation_exponent = Decimal(elapsed_ns) / Decimal(self._entity_reputation_half_life_ns)
            reputation_factor = Decimal('0.5') ** reputation_exponent
        
        for entity in state.entity_activity.values():
            entity.reputation = entity.reputation * reputation_factor
            entity.reputation = self._clamp_decimal(
                entity.reputation, 
                min_val=ENTITY_REPUTATION_DEFAULT * Decimal('0.5'), 
                max_val=ENTITY_REPUTATION_MAX
            )
            entity.bullish_contribution = entity.bullish_contribution * decay_factor
            entity.bearish_contribution = entity.bearish_contribution * decay_factor
        
        state.last_decay_ns = current_ts_ns
    
    # =========================================================================
    # PUBLIC METHODS
    # =========================================================================
    
    def set_symbol_tier(self, symbol: str, tier: SymbolTier) -> None:
        """Set the tier for a symbol (affects dead-zone thresholds)."""
        if symbol not in self._symbols:
            self._symbols[symbol] = _SymbolState()
        self._symbols[symbol].tier = tier
    
    def ingest_observation(
        self,
        observation: InsiderObservation,
        regime_multiplier: Optional[Decimal] = None,
        toxicity_penalty: Optional[Decimal] = None,
    ) -> InsiderSignalSnapshot:
        """
        Ingest a single observation and return updated snapshot.
        
        Args:
            observation: The observation to ingest
            regime_multiplier: Optional external regime modifier (0.5-1.5)
            toxicity_penalty: Optional external toxicity penalty (0-0.5)
        
        Returns:
            Updated InsiderSignalSnapshot for the observation's symbol
        """
        self._validate_observation(observation)
        regime_multiplier = self._validate_modifier(regime_multiplier, "regime_multiplier", REGIME_MULTIPLIER_MAX)
        if toxicity_penalty is not None:
            toxicity_penalty = self._validate_modifier(toxicity_penalty, "toxicity_penalty", TOXICITY_PENALTY_MAX)
        
        symbol = observation.symbol
        ts_ns = observation.timestamp_ns
        
        # Get or create symbol state
        if symbol not in self._symbols:
            if len(self._symbols) >= self._max_symbols:
                # Prune oldest symbol by last_observation_ns
                oldest = min(self._symbols.items(), key=lambda x: x[1].last_observation_ns)
                del self._symbols[oldest[0]]
                logger.debug(f"Max symbols reached, pruned: {oldest[0]}")
            self._symbols[symbol] = _SymbolState()
        
        state = self._symbols[symbol]
        thresholds = self._get_tier_thresholds(state.tier)
        
        # Enforce monotonic timestamp (allow equal timestamps for batch replay)
        if ts_ns < state.last_observation_ns:
            logger.warning(f"Rejecting out-of-order observation for {symbol}: {ts_ns} < {state.last_observation_ns}")
            return self.snapshot_for_symbol(symbol)
        
        # Apply decay before update
        self._apply_decay_to_state(state, ts_ns)
        
        # Deduplicate observation ID
        if not state.add_observation_id(observation.observation_id, ts_ns):
            # Duplicate observation, return current snapshot
            return self.snapshot_for_symbol(symbol)
        
        # Update entity reputation and directional totals
        if observation.entity_id:
            if observation.entity_id not in state.entity_activity:
                if len(state.entity_activity) >= DEFAULT_MAX_ENTITIES_PER_SYMBOL:
                    oldest_entity = min(state.entity_activity.items(), key=lambda x: x[1].last_timestamp_ns)
                    del state.entity_activity[oldest_entity[0]]
                state.entity_activity[observation.entity_id] = _EntityActivity()
            
            entity = state.entity_activity[observation.entity_id]
            entity.last_timestamp_ns = ts_ns
            entity.observation_count += 1
            
            # Update reputation with decay already applied
            reputation_boost = ENTITY_REPUTATION_BOOST_PER_OBSERVATION
            entity.reputation = self._clamp_decimal(
                entity.reputation + reputation_boost,
                min_val=ENTITY_REPUTATION_DEFAULT,
                max_val=ENTITY_REPUTATION_MAX
            )
        
        entity_reputation = state.entity_activity.get(observation.entity_id, _EntityActivity()).reputation if observation.entity_id else ENTITY_REPUTATION_DEFAULT
        
        # Compute base contribution
        bullish_base, bearish_base = self._compute_base_contribution(observation, entity_reputation)
        
        # Apply external modifiers
        bullish_contrib = self._apply_context_modifiers(bullish_base, regime_multiplier, toxicity_penalty)
        bearish_contrib = self._apply_context_modifiers(bearish_base, regime_multiplier, toxicity_penalty)
        
        # Update entity directional totals
        if observation.entity_id and observation.entity_id in state.entity_activity:
            entity = state.entity_activity[observation.entity_id]
            entity.bullish_contribution += bullish_contrib
            entity.bearish_contribution += bearish_contrib
        
        # Update scores
        state.bullish_score = self._clamp_decimal(state.bullish_score + bullish_contrib)
        state.bearish_score = self._clamp_decimal(state.bearish_score + bearish_contrib)
        
        # Update contradiction pressure
        self._update_contradiction_pressure(state, bullish_contrib, bearish_contrib)
        
        # Update invalidation pressure from observation
        self._update_invalidation_pressure(state, observation.invalidation_weight)
        
        # Update supporting counts
        state.supporting_observation_count += 1
        if observation.direction != ObservationDirection.UNKNOWN:
            state.directional_observation_count += 1
        
        # Update temporal tracking
        state.last_observation_ns = ts_ns
        if observation.direction != ObservationDirection.UNKNOWN:
            state.last_directional_observation_ns = ts_ns
            # Freshness resets to 1 on directional observation
            state.freshness = DECIMAL_ONE
        else:
            # UNKNOWN observations do not reset directional freshness
            pass
        
        # Add to recent observations for clustering (store direction code)
        direction_code = DIRECTION_CODE_BUY if observation.direction == ObservationDirection.BUY else (DIRECTION_CODE_SELL if observation.direction == ObservationDirection.SELL else DIRECTION_CODE_UNKNOWN)
        state.recent_observations.append((ts_ns, direction_code))
        
        # Update cluster strength
        state.cluster_strength = self._compute_cluster_strength(state, ts_ns)
        
        # Apply cross-entity alignment boost
        cross_entity_boost = self._compute_cross_entity_alignment(state, ts_ns)
        state.cluster_strength = self._clamp_decimal(state.cluster_strength * cross_entity_boost, max_val=CLUSTER_MAX_STRENGTH)
        
        # Collapse dead zone
        state.collapse_dead_zone(thresholds)
        
        # Store old flags for transition detection
        old_active = state.active
        old_degraded = state.degraded
        old_invalidated = state.invalidated
        
        # Recompute derived state
        state._recompute_derived(thresholds)
        
        # Update state transition timestamp ONLY if flags actually changed
        if state._has_state_changed(old_active, old_degraded, old_invalidated):
            state.last_state_transition_ns = ts_ns
        
        return self.snapshot_for_symbol(symbol)
    
    def ingest_batch(
        self,
        observations: Sequence[InsiderObservation],
        regime_multiplier: Optional[Decimal] = None,
        toxicity_penalty: Optional[Decimal] = None,
    ) -> Dict[str, InsiderSignalSnapshot]:
        """
        Ingest a batch of observations.
        
        Args:
            observations: Sequence of observations to ingest
            regime_multiplier: Optional external regime modifier
            toxicity_penalty: Optional external toxicity penalty
        
        Returns:
            Dictionary mapping symbol to snapshot
        """
        sorted_obs = sorted(observations, key=lambda o: (o.timestamp_ns, o.observation_id))
        
        result = {}
        for obs in sorted_obs:
            snapshot = self.ingest_observation(obs, regime_multiplier, toxicity_penalty)
            result[obs.symbol] = snapshot
        
        return result
    
    def apply_decay(self, timestamp_ns: int) -> None:
        """
        Apply deterministic decay to all symbols at a given timestamp.
        Does NOT mutate last_observation_ns.
        
        Args:
            timestamp_ns: Current timestamp for decay calculation
        """
        if not isinstance(timestamp_ns, int) or timestamp_ns <= 0:
            raise ValueError(f"timestamp_ns must be positive int: {timestamp_ns}")
        
        for state in self._symbols.values():
            old_active = state.active
            old_degraded = state.degraded
            old_invalidated = state.invalidated
            
            self._apply_decay_to_state(state, timestamp_ns)
            thresholds = self._get_tier_thresholds(state.tier)
            state.collapse_dead_zone(thresholds)
            state._recompute_derived(thresholds)
            
            if state._has_state_changed(old_active, old_degraded, old_invalidated):
                state.last_state_transition_ns = timestamp_ns
    
    def invalidate(
        self,
        symbol: str,
        timestamp_ns: int,
        invalidation_weight: Decimal,
        reason: str = "",
    ) -> Optional[InsiderSignalSnapshot]:
        """
        Explicitly invalidate a symbol's state.
        
        Args:
            symbol: Symbol to invalidate
            timestamp_ns: Current timestamp
            invalidation_weight: Strength of invalidation (0-1)
            reason: Optional reason for invalidation
        
        Returns:
            Updated snapshot, or None if symbol not tracked
        """
        if symbol not in self._symbols:
            return None
        
        invalidation_weight = self._clamp_decimal(invalidation_weight)
        state = self._symbols[symbol]
        
        old_active = state.active
        old_degraded = state.degraded
        old_invalidated = state.invalidated
        
        self._apply_decay_to_state(state, timestamp_ns)
        
        state.invalidation_pressure = self._clamp_decimal(
            state.invalidation_pressure + invalidation_weight * Decimal('0.5')
        )
        
        if reason:
            state.last_invalidation_reason = reason
        
        state.last_invalidation_ns = timestamp_ns
        # Do NOT mutate last_observation_ns - invalidation is not an observation
        
        thresholds = self._get_tier_thresholds(state.tier)
        state.collapse_dead_zone(thresholds)
        state._recompute_derived(thresholds)
        
        if state._has_state_changed(old_active, old_degraded, old_invalidated):
            state.last_state_transition_ns = timestamp_ns
        
        return self.snapshot_for_symbol(symbol)
    
    def snapshot_for_symbol(self, symbol: str) -> Optional[InsiderSignalSnapshot]:
        """
        Get current snapshot for a symbol (read-only, pure).
        
        Returns:
            Snapshot or None if symbol not tracked
        """
        state = self._symbols.get(symbol)
        if state is None:
            return None
        
        thresholds = self._get_tier_thresholds(state.tier)
        
        # Derive bias without recomputing full state
        if state.invalidated:
            bias = DirectionalBias.NEUTRAL
        else:
            net = state.bullish_score - state.bearish_score
            bias_threshold = thresholds.get("bias_threshold", Decimal('0.05'))
            if net > bias_threshold:
                bias = DirectionalBias.BULLISH
            elif net < -bias_threshold:
                bias = DirectionalBias.BEARISH
            else:
                bias = DirectionalBias.NEUTRAL
        
        return InsiderSignalSnapshot(
            symbol=symbol,
            timestamp_ns=max(state.last_observation_ns, state.last_state_transition_ns, state.last_invalidation_ns),
            last_observation_ns=state.last_observation_ns,
            last_directional_observation_ns=state.last_directional_observation_ns,
            last_state_transition_ns=state.last_state_transition_ns,
            bullish_score=state.bullish_score,
            bearish_score=state.bearish_score,
            net_pressure=state.bullish_score - state.bearish_score,
            confidence=state.confidence,
            freshness=state.freshness,
            cluster_strength=state.cluster_strength,
            contradiction_pressure=state.contradiction_pressure,
            invalidation_pressure=state.invalidation_pressure,
            directional_bias=bias,
            active=state.active,
            degraded=state.degraded,
            invalidated=state.invalidated,
            supporting_observation_count=state.supporting_observation_count,
        )
    
    def reset_symbol(self, symbol: str) -> None:
        """Reset state for a specific symbol."""
        if symbol in self._symbols:
            del self._symbols[symbol]
            logger.debug(f"Reset symbol: {symbol}")
    
    def prune(self, timestamp_ns: int) -> None:
        """
        Prune stale symbols based on truthful staleness (last_observation_ns).
        
        Args:
            timestamp_ns: Current timestamp for age calculation
        """
        if not isinstance(timestamp_ns, int) or timestamp_ns <= 0:
            raise ValueError(f"timestamp_ns must be positive int: {timestamp_ns}")
        
        to_prune = []
        for symbol, state in self._symbols.items():
            # Use last_observation_ns as the truth for evidence staleness
            age_ns = timestamp_ns - state.last_observation_ns
            if age_ns > self._prune_age_ns:
                to_prune.append(symbol)
            elif not state.active and not state.degraded and state.directional_observation_count == 0:
                to_prune.append(symbol)
            elif state.invalidated and age_ns > self._prune_age_ns // 2:
                to_prune.append(symbol)
        
        for symbol in to_prune:
            del self._symbols[symbol]
            logger.debug(f"Pruned stale symbol: {symbol}")
    
    def export_state(self) -> Dict[str, InsiderSignalSnapshot]:
        """
        Export current snapshots for all tracked symbols (read-only, pure).
        
        Returns:
            Dictionary mapping symbol to snapshot
        """
        result = {}
        for symbol in self._symbols:
            snapshot = self.snapshot_for_symbol(symbol)
            if snapshot is not None:
                result[symbol] = snapshot
        return result
    
    # =========================================================================
    # DETERMINISTIC PERSISTENCE
    # =========================================================================
    
    def export_state_payload(self) -> Dict[str, Any]:
        """
        Export deterministic serialization-safe state payload.
        
        Returns:
            Dictionary with version and deterministically ordered serializable state
        """
        payload = {
            "schema_version": STATE_SCHEMA_VERSION,
            "symbols": {},
        }
        
        # Sort symbols deterministically
        for symbol in sorted(self._symbols.keys()):
            state = self._symbols[symbol]
            
            # Sort entity activity deterministically
            entity_activity_payload = {}
            for entity_id in sorted(state.entity_activity.keys()):
                act = state.entity_activity[entity_id]
                entity_activity_payload[entity_id] = {
                    "last_timestamp_ns": act.last_timestamp_ns,
                    "bullish_contribution": str(act.bullish_contribution),
                    "bearish_contribution": str(act.bearish_contribution),
                    "observation_count": act.observation_count,
                    "reputation": str(act.reputation),
                }
            
            # Sort recent observations by timestamp (already ordered, but ensure)
            recent_obs_payload = [(ts, direction_code) for ts, direction_code in state.recent_observations]
            
            # Persist tier by stable symbolic name (value property), not auto() integer
            tier_value = state.tier.value if state.tier else SymbolTier.MID.value
            
            symbol_payload = {
                "tier": tier_value,
                "bullish_score": str(state.bullish_score),
                "bearish_score": str(state.bearish_score),
                "active": state.active,
                "degraded": state.degraded,
                "invalidated": state.invalidated,
                "confidence": str(state.confidence),
                "freshness": str(state.freshness),
                "cluster_strength": str(state.cluster_strength),
                "contradiction_pressure": str(state.contradiction_pressure),
                "invalidation_pressure": str(state.invalidation_pressure),
                "last_observation_ns": state.last_observation_ns,
                "last_directional_observation_ns": state.last_directional_observation_ns,
                "last_decay_ns": state.last_decay_ns,
                "last_state_transition_ns": state.last_state_transition_ns,
                "last_invalidation_ns": state.last_invalidation_ns,
                "supporting_observation_count": state.supporting_observation_count,
                "directional_observation_count": state.directional_observation_count,
                "observation_ids": [(oid, ts) for oid, ts in state.observation_ids_deque],
                "recent_observations": recent_obs_payload,
                "entity_activity": entity_activity_payload,
                "last_invalidation_reason": state.last_invalidation_reason,
            }
            payload["symbols"][symbol] = symbol_payload
        
        return payload
    
    def load_state_payload(self, payload: Mapping[str, Any]) -> None:
        """
        Load deterministic state payload with strict validation.
        
        Args:
            payload: Dictionary from export_state_payload()
        
        Raises:
            ValueError: If payload schema version mismatches or structure is invalid
        """
        schema_version = payload.get("schema_version")
        
        # Support both version 5 (legacy auto() integers) and version 6 (stable symbolic names)
        # Version 5 is still loadable; version 6 is the current format
        if schema_version not in (5, 6):
            raise ValueError(
                f"Schema version mismatch: expected 5 or 6, "
                f"got {schema_version}"
            )
        
        symbols_data = payload.get("symbols", {})
        if not isinstance(symbols_data, dict):
            raise ValueError("symbols must be a dict")
        
        # Validate symbol count
        if len(symbols_data) > self._max_symbols:
            raise ValueError(f"Symbol count {len(symbols_data)} exceeds max {self._max_symbols}")
        
        new_symbols = {}
        
        for symbol, sym_data in symbols_data.items():
            if not isinstance(sym_data, dict):
                raise ValueError(f"symbol data for {symbol} must be a dict")
            
            try:
                state = _SymbolState()
                
                # Tier: handle both legacy (int) and current (str) formats
                tier_value = sym_data.get("tier")
                if tier_value is not None:
                    if isinstance(tier_value, int):
                        # Legacy format: convert int to SymbolTier via value mapping
                        # Legacy mapping: 0=Liquid, 1=Mid, 2=Illiquid (auto() order)
                        legacy_map = {
                            0: SymbolTier.LIQUID,
                            1: SymbolTier.MID,
                            2: SymbolTier.ILLIQUID,
                        }
                        if tier_value in legacy_map:
                            state.tier = legacy_map[tier_value]
                        else:
                            raise ValueError(f"Invalid legacy tier value for {symbol}: {tier_value}")
                    elif isinstance(tier_value, str):
                        # Current format: stable symbolic name
                        try:
                            state.tier = SymbolTier(tier_value)
                        except ValueError:
                            raise ValueError(f"Invalid tier string for {symbol}: {tier_value}")
                    else:
                        raise ValueError(f"Invalid tier type for {symbol}: {type(tier_value)}")
                
                # Decimal fields - validate bounds
                bullish_score = Decimal(str(sym_data.get("bullish_score", "0")))
                bearish_score = Decimal(str(sym_data.get("bearish_score", "0")))
                if bullish_score < MIN_SCORE or bullish_score > MAX_SCORE:
                    raise ValueError(f"bullish_score out of bounds for {symbol}: {bullish_score}")
                if bearish_score < MIN_SCORE or bearish_score > MAX_SCORE:
                    raise ValueError(f"bearish_score out of bounds for {symbol}: {bearish_score}")
                state.bullish_score = bullish_score
                state.bearish_score = bearish_score
                
                state.active = bool(sym_data.get("active", False))
                state.degraded = bool(sym_data.get("degraded", False))
                state.invalidated = bool(sym_data.get("invalidated", False))
                
                confidence = Decimal(str(sym_data.get("confidence", "0")))
                freshness = Decimal(str(sym_data.get("freshness", "1")))
                cluster_strength = Decimal(str(sym_data.get("cluster_strength", "0")))
                contradiction_pressure = Decimal(str(sym_data.get("contradiction_pressure", "0")))
                invalidation_pressure = Decimal(str(sym_data.get("invalidation_pressure", "0")))
                
                if confidence < MIN_CONFIDENCE or confidence > MAX_CONFIDENCE:
                    raise ValueError(f"confidence out of bounds for {symbol}: {confidence}")
                if freshness < MIN_SCORE or freshness > MAX_SCORE:
                    raise ValueError(f"freshness out of bounds for {symbol}: {freshness}")
                if cluster_strength < MIN_SCORE or cluster_strength > MAX_SCORE:
                    raise ValueError(f"cluster_strength out of bounds for {symbol}: {cluster_strength}")
                if contradiction_pressure < MIN_SCORE or contradiction_pressure > MAX_SCORE:
                    raise ValueError(f"contradiction_pressure out of bounds for {symbol}: {contradiction_pressure}")
                if invalidation_pressure < MIN_SCORE or invalidation_pressure > MAX_SCORE:
                    raise ValueError(f"invalidation_pressure out of bounds for {symbol}: {invalidation_pressure}")
                
                state.confidence = confidence
                state.freshness = freshness
                state.cluster_strength = cluster_strength
                state.contradiction_pressure = contradiction_pressure
                state.invalidation_pressure = invalidation_pressure
                
                # Timestamp fields
                last_observation_ns = int(sym_data.get("last_observation_ns", 0))
                last_directional_observation_ns = int(sym_data.get("last_directional_observation_ns", 0))
                last_decay_ns = int(sym_data.get("last_decay_ns", 0))
                last_state_transition_ns = int(sym_data.get("last_state_transition_ns", 0))
                last_invalidation_ns = int(sym_data.get("last_invalidation_ns", 0))
                
                if last_observation_ns < 0 or last_directional_observation_ns < 0 or last_decay_ns < 0:
                    raise ValueError(f"Negative timestamp for {symbol}")
                
                state.last_observation_ns = last_observation_ns
                state.last_directional_observation_ns = last_directional_observation_ns
                state.last_decay_ns = last_decay_ns
                state.last_state_transition_ns = last_state_transition_ns
                state.last_invalidation_ns = last_invalidation_ns
                
                state.supporting_observation_count = int(sym_data.get("supporting_observation_count", 0))
                state.directional_observation_count = int(sym_data.get("directional_observation_count", 0))
                state.last_invalidation_reason = str(sym_data.get("last_invalidation_reason", ""))
                
                # Validate counts
                if state.supporting_observation_count < 0 or state.directional_observation_count < 0:
                    raise ValueError(f"Negative observation count for {symbol}")
                
                # Restore dedupe structures - validate length
                obs_ids = sym_data.get("observation_ids", [])
                if len(obs_ids) > DEFAULT_MAX_DEDUPE_IDS_PER_SYMBOL:
                    raise ValueError(f"Too many observation_ids for {symbol}: {len(obs_ids)}")
                for obs_id, obs_ts in obs_ids:
                    if not isinstance(obs_id, str) or not isinstance(obs_ts, int) or obs_ts < 0:
                        raise ValueError(f"Invalid observation_id entry for {symbol}")
                    state.observation_ids_deque.append((obs_id, obs_ts))
                    state.observation_ids_set.add(obs_id)
                
                # Restore recent observations - validate length and direction codes
                recent_obs = sym_data.get("recent_observations", [])
                if len(recent_obs) > DEFAULT_MAX_OBSERVATIONS_PER_SYMBOL:
                    raise ValueError(f"Too many recent_observations for {symbol}: {len(recent_obs)}")
                for ts, direction_code in recent_obs:
                    if not isinstance(ts, int) or ts < 0:
                        raise ValueError(f"Invalid timestamp in recent_observations for {symbol}")
                    if direction_code not in (DIRECTION_CODE_BUY, DIRECTION_CODE_SELL, DIRECTION_CODE_UNKNOWN):
                        raise ValueError(f"Invalid direction_code in recent_observations for {symbol}: {direction_code}")
                    state.recent_observations.append((ts, direction_code))
                
                # Restore entity activity - validate size
                entity_activity = sym_data.get("entity_activity", {})
                if len(entity_activity) > DEFAULT_MAX_ENTITIES_PER_SYMBOL:
                    raise ValueError(f"Too many entities for {symbol}: {len(entity_activity)}")
                for entity_id, act_data in entity_activity.items():
                    if not isinstance(act_data, dict):
                        raise ValueError(f"Invalid entity activity data for {symbol}, {entity_id}")
                    act = _EntityActivity()
                    act.last_timestamp_ns = int(act_data.get("last_timestamp_ns", 0))
                    act.bullish_contribution = Decimal(str(act_data.get("bullish_contribution", "0")))
                    act.bearish_contribution = Decimal(str(act_data.get("bearish_contribution", "0")))
                    act.observation_count = int(act_data.get("observation_count", 0))
                    act.reputation = Decimal(str(act_data.get("reputation", str(ENTITY_REPUTATION_DEFAULT))))
                    
                    # Validate bounds
                    if act.reputation < ENTITY_REPUTATION_DEFAULT * Decimal('0.5') or act.reputation > ENTITY_REPUTATION_MAX:
                        raise ValueError(f"Entity reputation out of bounds for {symbol}, {entity_id}: {act.reputation}")
                    if act.observation_count < 0:
                        raise ValueError(f"Negative observation count for entity {entity_id}")
                    
                    state.entity_activity[entity_id] = act
                
                # Recompute derived state to ensure invariants
                thresholds = self._get_tier_thresholds(state.tier)
                state.collapse_dead_zone(thresholds)
                state._recompute_derived(thresholds)
                
                new_symbols[symbol] = state
                
            except (ValueError, TypeError, KeyError) as e:
                raise ValueError(f"Failed to load symbol {symbol}: {e}")
        
        self._symbols = new_symbols
        logger.info(f"Loaded state payload for {len(self._symbols)} symbols")
    
    def reset(self) -> None:
        """Reset all internal state for deterministic replay safety."""
        self._symbols.clear()
        logger.info("InsiderSignalEngine reset")