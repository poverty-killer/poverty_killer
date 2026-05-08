"""
Canonical Enumerations for Sovereign Trading System
ONE AUTHORITY — app/models/enums.py

All enum class definitions for the entire system live here.
utils/enums.py and constants.py are re-export shims only.

Value conventions:
  - Enums originating in this file (contract/strategy layer): lowercase values
  - Enums harvested from utils/enums.py (execution layer): UPPERCASE values preserved
    (paper_broker.py live path uses member comparisons, not raw string comparisons)
"""

from __future__ import annotations

from enum import Enum, IntEnum, unique
from typing import Final, FrozenSet


# ============================================================================
# MARKET STRUCTURE / REGIME
# ============================================================================

class RegimeType(str, Enum):
    """
    Market regime classification.
    Original 5 lowercase values used by signal_fusion/strategy layer.
    Granular values added for risk-layer helpers (is_crisis_regime).
    TRENDING alias for constants.py SigmaRiskConfig backward compat.
    """
    UNKNOWN = "unknown"
    TRENDING_BULL = "trending_bull"
    TRENDING_BEAR = "trending_bear"
    RANGING = "ranging"
    CRISIS = "crisis"
    TRENDING_LONG_STRONG = "trending_long_strong"
    TRENDING_LONG_EXHAUSTING = "trending_long_exhausting"
    TRENDING_SHORT_STRONG = "trending_short_strong"
    TRENDING_SHORT_EXHAUSTING = "trending_short_exhausting"
    RANGING_COMPRESSED = "ranging_compressed"
    RANGING_EXPANDING = "ranging_expanding"
    CRISIS_LIQUIDITY_VOID = "crisis_liquidity_void"
    CRISIS_VOLATILITY_SPIKE = "crisis_volatility_spike"
    CRISIS_INFRA_FAILURE = "crisis_infra_failure"
    REGIME_BREAK_DETECTED = "regime_break_detected"
    TRENDING = "trending"   # constants.py SigmaRiskConfig compat


# ============================================================================
# MICROSTRUCTURE (harvested from utils/enums.py — UPPERCASE values preserved)
# ============================================================================

@unique
class LiquidityRegime(str, Enum):
    """Microstructural liquidity/depth classification."""
    UNKNOWN = "UNKNOWN"
    THICK = "THICK"
    THIN = "THIN"
    HOLLOW = "HOLLOW"
    ASYMMETRIC_BID = "ASYMMETRIC_BID"
    ASYMMETRIC_ASK = "ASYMMETRIC_ASK"
    FRAGMENTED = "FRAGMENTED"
    TOXIC = "TOXIC"


@unique
class ToxicityLevel(str, Enum):
    """Adverse selection / flow toxicity severity."""
    UNKNOWN = "UNKNOWN"
    BENIGN = "BENIGN"
    ELEVATED = "ELEVATED"
    TOXIC = "TOXIC"
    EXTREME = "EXTREME"


@unique
class BookIntegrity(str, Enum):
    """Order book structural validity classification."""
    UNKNOWN = "UNKNOWN"
    HEALTHY = "HEALTHY"
    THIN = "THIN"
    HOLLOW = "HOLLOW"
    FRAGMENTED = "FRAGMENTED"
    LOCKED = "LOCKED"
    CROSSED = "CROSSED"
    STALE = "STALE"
    UNTRUSTWORTHY = "UNTRUSTWORTHY"


@unique
class Marketability(str, Enum):
    """Aggression profile of an intended order against prevailing book."""
    UNKNOWN = "UNKNOWN"
    PASSIVE = "PASSIVE"
    NEAR_TOUCH = "NEAR_TOUCH"
    MARKETABLE = "MARKETABLE"
    CROSSING = "CROSSING"
    SWEEPING = "SWEEPING"


@unique
class SlippageClass(str, Enum):
    """Expected/observed slippage severity bucket."""
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


# ============================================================================
# SIGNAL / INTENT / POSITION SEMANTICS (harvested from utils/enums.py)
# ============================================================================

@unique
class SignalDirection(str, Enum):
    """Directional output from alpha/signal generation layers."""
    UNKNOWN = "UNKNOWN"
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


@unique
class TradeIntent(str, Enum):
    """Portfolio/execution intent separate from exchange order side."""
    UNKNOWN = "UNKNOWN"
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    REDUCE = "REDUCE"
    ADD = "ADD"
    REVERSE = "REVERSE"
    FLATTEN = "FLATTEN"
    HEDGE = "HEDGE"
    REBALANCE = "REBALANCE"


@unique
class PositionSide(str, Enum):
    """Current or target position orientation."""
    UNKNOWN = "UNKNOWN"
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"
    HEDGED = "HEDGED"


@unique
class ExposureState(str, Enum):
    """Net portfolio exposure state used by risk/inventory layers."""
    UNKNOWN = "UNKNOWN"
    FLAT = "FLAT"
    NET_LONG = "NET_LONG"
    NET_SHORT = "NET_SHORT"
    DELTA_NEUTRAL = "DELTA_NEUTRAL"
    HEDGED = "HEDGED"
    DISLOCATED = "DISLOCATED"


# ============================================================================
# EXECUTION INSTRUCTION SPACE
# ============================================================================

class OrderSide(str, Enum):
    """
    Canonical exchange-facing side.
    Lowercase values (models convention). UNKNOWN added for UNKNOWN-safe handling.
    order_router.py bridges to paper_broker via .upper().split('.')[-1] pattern.
    """
    UNKNOWN = "unknown"
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """
    Primary order archetype.
    Original 3-value lowercase set + utils/enums.py values added.
    POST_ONLY retained from models layer (not in utils).
    """
    UNKNOWN = "unknown"
    MARKET = "market"
    LIMIT = "limit"
    POST_ONLY = "post_only"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"
    IOC = "ioc"
    FOK = "fok"
    TWAP_SLICE = "twap_slice"
    ICEBERG = "iceberg"
    PEGGED = "pegged"
    AUCTION = "auction"


@unique
class TimeInForce(str, Enum):
    """Temporal order persistence constraints."""
    UNKNOWN = "UNKNOWN"
    GTC = "GTC"
    GTD = "GTD"
    DAY = "DAY"
    IOC = "IOC"
    FOK = "FOK"
    GTX = "GTX"
    AT_OPEN = "AT_OPEN"
    AT_CLOSE = "AT_CLOSE"


@unique
class ExecutionConstraint(str, Enum):
    """Orthogonal execution flags / constraints."""
    UNKNOWN = "UNKNOWN"
    POST_ONLY = "POST_ONLY"
    REDUCE_ONLY = "REDUCE_ONLY"
    CLOSE_ONLY = "CLOSE_ONLY"
    HIDDEN = "HIDDEN"
    ICEBERG = "ICEBERG"
    NO_TRADE_THROUGH = "NO_TRADE_THROUGH"
    MAKER_PREFERENCE = "MAKER_PREFERENCE"
    TAKER_ALLOWED = "TAKER_ALLOWED"


@unique
class SelfTradePreventionMode(str, Enum):
    """Self-trade prevention policy at router/venue layer."""
    UNKNOWN = "UNKNOWN"
    NONE = "NONE"
    CANCEL_NEWEST = "CANCEL_NEWEST"
    CANCEL_OLDEST = "CANCEL_OLDEST"
    CANCEL_BOTH = "CANCEL_BOTH"
    DECREMENT_AND_CANCEL = "DECREMENT_AND_CANCEL"


@unique
class VenueCapability(str, Enum):
    """Optional venue feature flags for adapter normalization."""
    UNKNOWN = "UNKNOWN"
    POST_ONLY = "POST_ONLY"
    ICEBERG = "ICEBERG"
    REDUCE_ONLY = "REDUCE_ONLY"
    SELF_TRADE_PREVENTION = "SELF_TRADE_PREVENTION"
    MASS_CANCEL = "MASS_CANCEL"
    CANCEL_ON_DISCONNECT = "CANCEL_ON_DISCONNECT"
    PEGGED_ORDERS = "PEGGED_ORDERS"
    AUCTION_ORDERS = "AUCTION_ORDERS"


# ============================================================================
# ORDER LIFECYCLE / EXECUTION REPORT SEMANTICS
# ============================================================================

@unique
class OrderStatus(str, Enum):
    """
    Canonical normalized 22-state lifecycle (harvested from utils/enums.py).
    UPPERCASE values preserved — paper_broker.py live path.
    """
    UNKNOWN = "UNKNOWN"
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    VALIDATION_REJECTED = "VALIDATION_REJECTED"
    ROUTING = "ROUTING"
    ROUTED = "ROUTED"
    PENDING_NEW = "PENDING_NEW"
    SENT = "SENT"
    PENDING_ACK = "PENDING_ACK"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FULLY_FILLED = "FULLY_FILLED"
    PENDING_CANCEL = "PENDING_CANCEL"
    CANCELLED = "CANCELLED"
    CANCEL_REJECTED = "CANCEL_REJECTED"
    REPLACE_PENDING = "REPLACE_PENDING"
    REPLACED = "REPLACED"
    REPLACE_REJECTED = "REPLACE_REJECTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    DONE_FOR_DAY = "DONE_FOR_DAY"
    STALE = "STALE"
    RECOVERED = "RECOVERED"
    ORPHANED = "ORPHANED"
    RECONCILING = "RECONCILING"


class InternalOrderStatus(str, Enum):
    """
    Normalized internal execution lifecycle state.
    System's authoritative view of order state, separate from venue states.
    Used by order_router.py and contracts layer.
    """
    CREATED = "created"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"
    PENDING_CANCEL = "pending_cancel"


@unique
class ExecutionReportType(str, Enum):
    """Normalized execution report / state-change event classification."""
    UNKNOWN = "UNKNOWN"
    NEW = "NEW"
    ACK = "ACK"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILL = "FILL"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCEL = "CANCEL"
    CANCEL_REJECT = "CANCEL_REJECT"
    REPLACE_PENDING = "REPLACE_PENDING"
    REPLACE = "REPLACE"
    REPLACE_REJECT = "REPLACE_REJECT"
    REJECT = "REJECT"
    EXPIRE = "EXPIRE"
    STATUS = "STATUS"
    RECOVERY = "RECOVERY"
    BUST = "BUST"
    CORRECTION = "CORRECTION"


@unique
class FillLiquidity(str, Enum):
    """Whether a fill was maker/taker/auction/etc."""
    UNKNOWN = "UNKNOWN"
    MAKER = "MAKER"
    TAKER = "TAKER"
    AUCTION = "AUCTION"
    INTERNALIZED = "INTERNALIZED"


class FillStatus(str, Enum):
    """Fill status from reconciliation (models layer, lowercase)."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    RECONCILED = "reconciled"


class CancelStatus(str, Enum):
    """Cancel request status (models layer, lowercase)."""
    PENDING = "pending"
    ACKED = "acked"
    CONFIRMED = "confirmed"
    FAILED = "failed"


@unique
class RecoveryState(str, Enum):
    """Persistence/restart reconciliation state."""
    UNKNOWN = "UNKNOWN"
    PRISTINE = "PRISTINE"
    RECOVERING = "RECOVERING"
    RECONCILED = "RECONCILED"
    AMBIGUOUS = "AMBIGUOUS"
    ORPHANED = "ORPHANED"
    LOST = "LOST"


@unique
class PersistenceState(str, Enum):
    """Storage durability state for replay and crash consistency."""
    UNKNOWN = "UNKNOWN"
    TRANSIENT = "TRANSIENT"
    JOURNALED = "JOURNALED"
    SNAPSHOTTED = "SNAPSHOTTED"
    RECOVERED = "RECOVERED"


# ============================================================================
# RISK / GOVERNANCE / INVARIANT CONTROL
# ============================================================================

@unique
class RiskLevel(IntEnum):
    """Hazard severity level (IntEnum for numeric comparison)."""
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4
    VETO = 5
    PANIC = 6


@unique
class RiskAction(str, Enum):
    """Deterministic control directive issued by risk authority."""
    UNKNOWN = "UNKNOWN"
    ALLOW = "ALLOW"
    ADVISE = "ADVISE"
    THROTTLE = "THROTTLE"
    REDUCE_SIZE = "REDUCE_SIZE"
    REDUCE_FREQUENCY = "REDUCE_FREQUENCY"
    BLOCK_NEW_LONG = "BLOCK_NEW_LONG"
    BLOCK_NEW_SHORT = "BLOCK_NEW_SHORT"
    BLOCK_ALL_NEW = "BLOCK_ALL_NEW"
    FORCE_DELEVER = "FORCE_DELEVER"
    FORCE_FLAT = "FORCE_FLAT"
    SAFE_MODE = "SAFE_MODE"
    KILL_SWITCH = "KILL_SWITCH"


class InvariantViolationSeverity(str, Enum):
    """
    Governance response tier for invariant breaches.
    Expanded: ADVISORY + KILL_SWITCH harvested from utils to resolve conflict.
    """
    INFO = "info"
    ADVISORY = "advisory"
    WARNING = "warning"
    SAFE_MODE = "safe_mode"
    HARD_FLAT = "hard_flat"
    KILL_SWITCH = "kill_switch"


@unique
class HazardVelocity(str, Enum):
    """Velocity-of-risk movement classification."""
    UNKNOWN = "UNKNOWN"
    STABLE = "STABLE"
    ACCELERATING = "ACCELERATING"
    DECAPITATING = "DECAPITATING"


@unique
class RiskVetoReason(str, Enum):
    """Canonical reasons for risk-layer denial or forced intervention."""
    UNKNOWN = "UNKNOWN"
    MAX_DRAWDOWN = "MAX_DRAWDOWN"
    VELOCITY_OF_LOSS = "VELOCITY_OF_LOSS"
    PCV_BREACH = "PCV_BREACH"
    EXPOSURE_LIMIT = "EXPOSURE_LIMIT"
    CONCENTRATION_LIMIT = "CONCENTRATION_LIMIT"
    LEVERAGE_LIMIT = "LEVERAGE_LIMIT"
    LIQUIDITY_TOXICITY = "LIQUIDITY_TOXICITY"
    BOOK_UNTRUSTWORTHY = "BOOK_UNTRUSTWORTHY"
    STALE_MARKET_DATA = "STALE_MARKET_DATA"
    CLOCK_SKEW = "CLOCK_SKEW"
    SESSION_CLOSED = "SESSION_CLOSED"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    SAFE_MODE_ACTIVE = "SAFE_MODE_ACTIVE"
    INFRA_DEGRADATION = "INFRA_DEGRADATION"
    COMPLIANCE_BLOCK = "COMPLIANCE_BLOCK"


# ============================================================================
# FAILURE / REJECTION / CANCELLATION REASONS
# ============================================================================

@unique
class RejectReason(str, Enum):
    """Canonical order rejection reasons."""
    UNKNOWN = "UNKNOWN"
    INVALID_SYMBOL = "INVALID_SYMBOL"
    INVALID_SIDE = "INVALID_SIDE"
    INVALID_ORDER_TYPE = "INVALID_ORDER_TYPE"
    INVALID_TIF = "INVALID_TIF"
    INVALID_PRICE = "INVALID_PRICE"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    INVALID_NOTIONAL = "INVALID_NOTIONAL"
    MIN_NOTIONAL_BREACH = "MIN_NOTIONAL_BREACH"
    LOT_SIZE_BREACH = "LOT_SIZE_BREACH"
    TICK_SIZE_BREACH = "TICK_SIZE_BREACH"
    POST_ONLY_WOULD_CROSS = "POST_ONLY_WOULD_CROSS"
    REDUCE_ONLY_VIOLATION = "REDUCE_ONLY_VIOLATION"
    STALE_QUOTE = "STALE_QUOTE"
    STALE_SIGNAL = "STALE_SIGNAL"
    DUPLICATE_CLIENT_ORDER_ID = "DUPLICATE_CLIENT_ORDER_ID"
    RATE_LIMIT = "RATE_LIMIT"
    RISK_REJECT = "RISK_REJECT"
    SESSION_CLOSED = "SESSION_CLOSED"
    SYMBOL_HALTED = "SYMBOL_HALTED"
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
    VENUE_REJECT = "VENUE_REJECT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@unique
class CancelReason(str, Enum):
    """Canonical cancel causes."""
    UNKNOWN = "UNKNOWN"
    USER_REQUEST = "USER_REQUEST"
    STRATEGY_REPLACED = "STRATEGY_REPLACED"
    STALE_ALPHA = "STALE_ALPHA"
    QUOTE_DRIFT = "QUOTE_DRIFT"
    INVENTORY_CONTROL = "INVENTORY_CONTROL"
    RISK_VETO = "RISK_VETO"
    DUPLICATE_ORDER = "DUPLICATE_ORDER"
    DISCONNECT_RECOVERY = "DISCONNECT_RECOVERY"
    CANCEL_ON_DISCONNECT = "CANCEL_ON_DISCONNECT"
    SESSION_END = "SESSION_END"
    VENUE_MASS_CANCEL = "VENUE_MASS_CANCEL"
    SHUTDOWN = "SHUTDOWN"
    FORCE_FLAT = "FORCE_FLAT"


@unique
class InfraFaultType(str, Enum):
    """Infrastructure degradation / fault classification."""
    UNKNOWN = "UNKNOWN"
    CLOCK_DRIFT = "CLOCK_DRIFT"
    QUEUE_BACKUP = "QUEUE_BACKUP"
    DROPPED_MESSAGES = "DROPPED_MESSAGES"
    DUPLICATE_MESSAGES = "DUPLICATE_MESSAGES"
    SERIALIZATION_FAILURE = "SERIALIZATION_FAILURE"
    PERSISTENCE_FAILURE = "PERSISTENCE_FAILURE"
    SOCKET_DEGRADED = "SOCKET_DEGRADED"
    VENUE_DISCONNECT = "VENUE_DISCONNECT"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    HYDRATION_FAILURE = "HYDRATION_FAILURE"
    UNKNOWN_RESPONSE = "UNKNOWN_RESPONSE"


# ============================================================================
# STRATEGY / SLEEVE / CONTROL PLANE
# ============================================================================

class SleeveType(str, Enum):
    """
    Strategy sleeve identifiers. Lowercase values (models convention).
    LIQUIDITY_VOID + POVERTY_KILLER_AGGREGATE harvested from utils to resolve conflict.
    """
    SHADOW_FRONT = "shadow_front"
    FLV = "flv"
    ENTROPY_DECODER = "entropy_decoder"
    PHYSICAL_ONCHAIN = "physical_onchain"
    CONVEXITY_SWITCH = "convexity_switch"
    HEDGING_FLOW = "hedging_flow"
    ADAPTIVE_DC = "adaptive_dc"
    GAMMA_FRONT = "gamma_front"
    SECTOR_ROTATION = "sector_rotation"
    LIQUIDITY_VOID = "liquidity_void"
    POVERTY_KILLER_AGGREGATE = "pk_agg"


@unique
class ExecutionMode(str, Enum):
    """Global operational mode affecting latency, safety, and autonomy."""
    UNKNOWN = "UNKNOWN"
    LIVE = "LIVE"
    ALPHA = "ALPHA"
    GAMMA = "GAMMA"
    SAFE = "SAFE"
    DEGRADED = "DEGRADED"
    RECOVERY = "RECOVERY"
    REPLAY = "REPLAY"
    SIMULATION = "SIMULATION"


@unique
class LatencyTier(str, Enum):
    """Latency budget class for workload policy."""
    UNKNOWN = "UNKNOWN"
    SUB_500US = "SUB_500US"
    SUB_1MS = "SUB_1MS"
    SUB_10MS = "SUB_10MS"
    BEST_EFFORT = "BEST_EFFORT"


@unique
class DegradationMode(str, Enum):
    """System-wide degraded operating state."""
    UNKNOWN = "UNKNOWN"
    NORMAL = "NORMAL"
    THROTTLED = "THROTTLED"
    STALE_DATA_GUARD = "STALE_DATA_GUARD"
    VENUE_DEGRADED = "VENUE_DEGRADED"
    ROUTER_DEGRADED = "ROUTER_DEGRADED"
    PERSISTENCE_DEGRADED = "PERSISTENCE_DEGRADED"
    FAILOVER = "FAILOVER"
    READ_ONLY = "READ_ONLY"


@unique
class AuthorityTier(str, Enum):
    """Authority strength of a directive/event."""
    UNKNOWN = "UNKNOWN"
    ADVISORY = "ADVISORY"
    SOFT_BLOCK = "SOFT_BLOCK"
    HARD_BLOCK = "HARD_BLOCK"
    TERMINAL = "TERMINAL"


class ControlMode(str, Enum):
    """
    Operator control modes. Can be changed remotely via control/mode.txt.
    Harvested from constants.py. These never override hard caps or kill switch.
    """
    SAFE = "safe"
    NORMAL = "normal"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"
    CRISIS_OPPORTUNISTIC = "crisis_opportunistic"
    CAPITAL_SECURE = "capital_secure"
    EMERGENCY_HALT = "emergency_halt"


class RiskProfile(str, Enum):
    """Risk profiles — scaling factors within hard caps. Harvested from constants.py."""
    SAFE = "safe"
    NORMAL = "normal"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"
    CRISIS_OPPORTUNISTIC = "crisis_opportunistic"


class AssetClass(str, Enum):
    """Asset classes for multi-market support. Harvested from constants.py."""
    CRYPTO = "crypto"
    EQUITY = "equity"
    ETF = "etf"
    FUTURE = "future"


class MarketSession(str, Enum):
    """Trading sessions by asset class. Harvested from constants.py."""
    CRYPTO_24_7 = "24_7"
    EQUITY = "equity"
    FUTURES = "futures"


class ExchangeType(str, Enum):
    """Supported exchanges by asset class. Harvested from constants.py."""
    KRAKEN = "kraken"
    ALPACA = "alpaca"
    IBKR = "ibkr"


class PositionStatus(str, Enum):
    """Position lifecycle status. Harvested from constants.py."""
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"
    STUCK = "stuck"


# ============================================================================
# EVENTS / TELEMETRY / ROUTING
# ============================================================================

class EventType(str, Enum):
    """
    System-wide canonical event categories.
    MERGED: models replay/audit namespace + utils HFT namespace + constants pub/sub namespace.
    Each namespace uses distinct member names — no value conflicts.
    """
    # models/enums.py namespace — replay/audit/contract layer
    TRADE = "trade"
    QUOTE = "quote"
    ORDER_BOOK_SNAPSHOT = "order_book_snapshot"
    ORDER_BOOK_DELTA = "order_book_delta"
    CLOCK_TICK = "clock_tick"
    FEATURE_VECTOR = "feature_vector"
    STRATEGY_VOTE = "strategy_vote"
    RISK_DECISION = "risk_decision"
    ORDER_INTENT = "order_intent"
    CANCEL_INTENT = "cancel_intent"
    EXECUTION_EVENT = "execution_event"
    FILL_EVENT = "fill_event"
    CANCEL_EVENT = "cancel_event"
    DECISION_RECORD = "decision_record"
    TRUTH_FRAME = "truth_frame"
    DIVERGENCE_EVENT = "divergence_event"
    RECOVERY_CHECKPOINT = "recovery_checkpoint"
    AUDIT_EVENT = "audit_event"
    HEARTBEAT = "heartbeat"
    REPLAY_START = "replay_start"
    REPLAY_END = "replay_end"
    # utils/enums.py namespace — HFT trading/telemetry layer
    L1_TICK = "L1_TICK"
    L2_BOOK_UPDATE = "L2_BOOK_UPDATE"
    TRADE_PRINT = "TRADE_PRINT"
    WHALE_PRINT = "WHALE_PRINT"
    DARK_POOL_SIGNAL = "DARK_POOL_SIGNAL"
    ALPHA_SIGNAL = "ALPHA_SIGNAL"
    STRATEGY_INTENT = "STRATEGY_INTENT"
    RISK_ADVISORY = "RISK_ADVISORY"
    ORDER_COMMAND = "ORDER_COMMAND"
    EXECUTION_REPORT = "EXECUTION_REPORT"
    POSITION_UPDATE = "POSITION_UPDATE"
    LATENCY_HEARTBEAT = "LATENCY_HEARTBEAT"
    CONTROL_PLANE_CMD = "CONTROL_PLANE_CMD"
    HYDRATION_SNAPSHOT = "HYDRATION_SNAPSHOT"
    RECOVERY_EVENT = "RECOVERY_EVENT"
    INFRA_ALERT = "INFRA_ALERT"
    # constants.py namespace — pub/sub routing layer
    MARKET_DATA = "market_data"
    SIGNAL = "signal"
    ORDER = "order"
    FILL = "fill"
    RISK = "risk"
    ERROR = "error"
    STATE_CHANGE = "state_change"
    CONTROL = "control"
    HEALTH = "health"


@unique
class EventSource(str, Enum):
    """Originating subsystem for an event."""
    UNKNOWN = "UNKNOWN"
    EXCHANGE = "EXCHANGE"
    MARKET_DATA = "MARKET_DATA"
    STRATEGY = "STRATEGY"
    SLEEVE = "SLEEVE"
    RISK = "RISK"
    COMMANDER = "COMMANDER"
    ORCHESTRATOR = "ORCHESTRATOR"
    ENGINE = "ENGINE"
    ORDER_ROUTER = "ORDER_ROUTER"
    PERSISTENCE = "PERSISTENCE"
    HYDRATION = "HYDRATION"
    RECOVERY = "RECOVERY"
    CONTROL_PLANE = "CONTROL_PLANE"
    SIMULATOR = "SIMULATOR"


@unique
class PriorityClass(str, Enum):
    """Scheduling/dispatch urgency classification."""
    UNKNOWN = "UNKNOWN"
    REALTIME = "REALTIME"
    URGENT = "URGENT"
    NORMAL = "NORMAL"
    DEFERRED = "DEFERRED"


class ReplayMode(str, Enum):
    """
    Replay/execution context mode.
    Original REPLAY + VERIFY preserved; UNKNOWN/LIVE/RECOVERY/SYNTHETIC/BACKFILL
    added from utils to resolve conflict.
    """
    UNKNOWN = "unknown"
    REPLAY = "replay"
    VERIFY = "verify"
    LIVE = "live"
    RECOVERY = "recovery"
    SYNTHETIC = "synthetic"
    BACKFILL = "backfill"


# ============================================================================
# SYSTEM STATE / TRUTH
# ============================================================================

class TruthStatus(str, Enum):
    """Status of TruthFrame reconciliation."""
    RECONCILED = "reconciled"
    DRIFTING = "drifting"
    BROKEN = "broken"


class RiskMode(str, Enum):
    """System-wide risk mode from RiskTruth."""
    NORMAL = "normal"
    SAFE_MODE = "safe_mode"
    HARD_FLAT = "hard_flat"
    REPLAY_ONLY = "replay_only"
    READ_ONLY_DIAGNOSTIC = "read_only_diagnostic"


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


# ============================================================================
# DIVERGENCE / STATE MACHINES / STRATEGY STATES
# ============================================================================

class DivergenceType(str, Enum):
    """Types of divergence between truths."""
    EXCHANGE_EXECUTION = "exchange_execution"
    EXECUTION_PORTFOLIO = "execution_portfolio"
    PORTFOLIO_STRATEGY = "portfolio_strategy"
    STRATEGY_RISK = "strategy_risk"
    TRUTH_CONSENSUS = "truth_consensus"


class ShadowFrontState(str, Enum):
    """ShadowFront strategy state machine states."""
    IDLE = "idle"
    SILENT_ACCUMULATION = "silent_accumulation"
    ARMED = "armed"
    IGNITION = "ignition"
    ACTIVE = "active"
    COOLDOWN = "cooldown"


class LiquidityVoidState(str, Enum):
    """LiquidityVoid strategy state machine states."""
    INACTIVE = "inactive"
    SCANNING = "scanning"
    DETECTED = "detected"
    ENTERED = "entered"
    EXITING = "exiting"
    CLOSED = "closed"


# Backward-compat alias for constants.py LiquidityVoidStatus
LiquidityVoidStatus = LiquidityVoidState


# ============================================================================
# REPLAY / PERSISTENCE / SOURCE
# ============================================================================

class SourceType(str, Enum):
    """Source format for replay data. Stage 0 uses JSONL only."""
    JSONL = "jsonl"


class CheckpointType(str, Enum):
    """RecoveryCheckpoint checkpoint types."""
    WAL_SYNC = "wal_sync"
    TRUTH_FRAME = "truth_frame"
    SNAPSHOT = "snapshot"


# ============================================================================
# CONTRACT ENUMS
# ============================================================================

class DecisionType(str, Enum):
    """DecisionRecord decision types."""
    FEATURE_COMPUTE = "feature_compute"
    STRATEGY_VOTE = "strategy_vote"
    RISK_APPROVAL = "risk_approval"
    ORDER_INTENT = "order_intent"
    CANCEL_INTENT = "cancel_intent"
    RECOVERY_ACTION = "recovery_action"


class ExecutionEventType(str, Enum):
    """ExecutionEvent event types."""
    SUBMIT = "submit"
    ACK = "ack"
    REJECT = "reject"
    CANCEL_REQUEST = "cancel_request"
    CANCEL_ACK = "cancel_ack"
    PARTIAL_FILL = "partial_fill"
    FULL_FILL = "full_fill"


class SignalType(str, Enum):
    """StrategyVote signal types."""
    BUY = "buy"
    SELL = "sell"
    FLAT = "flat"
    NO_ACTION = "no_action"


class StrategyID(str, Enum):
    """Strategy identifiers for StrategyVote.strategy_id field."""
    SHADOW_FRONT = "shadow_front"
    LIQUIDITY_VOID = "liquidity_void"
    GAMMA_FRONT = "gamma_front"
    SECTOR_ROTATION = "sector_rotation"
    ADAPTIVE_DC = "adaptive_dc"
    MOVING_FLOOR = "moving_floor"


class ResolutionType(str, Enum):
    """DivergenceEvent resolution types."""
    PENDING = "pending"
    RECONCILED = "reconciled"
    HARD_FLAT = "hard_flat"
    MANUAL_INTERVENTION = "manual_intervention"


# ============================================================================
# BRAIN ENGINE ENUMS
# ============================================================================

class CollapseQuality(str, Enum):
    """Entropy collapse quality grade — used by entropy_decoder engine."""
    NONE = "none"
    WEAK = "weak"
    EXTREME = "extreme"
    STRUCTURAL = "structural"


# ============================================================================
# CRISIS REGIME HELPER
# ============================================================================

CRISIS_REGIMES: Final[FrozenSet[RegimeType]] = frozenset({
    RegimeType.CRISIS,
    RegimeType.CRISIS_LIQUIDITY_VOID,
    RegimeType.CRISIS_VOLATILITY_SPIKE,
    RegimeType.CRISIS_INFRA_FAILURE,
})


def is_crisis_regime(regime: RegimeType) -> bool:
    """True if regime is any crisis variant."""
    return regime in CRISIS_REGIMES


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Regime
    'RegimeType', 'CRISIS_REGIMES', 'is_crisis_regime',
    # Microstructure
    'LiquidityRegime', 'ToxicityLevel', 'BookIntegrity', 'Marketability', 'SlippageClass',
    # Signal/intent/position
    'SignalDirection', 'TradeIntent', 'PositionSide', 'ExposureState',
    # Execution instruction
    'OrderSide', 'OrderType', 'TimeInForce', 'ExecutionConstraint',
    'SelfTradePreventionMode', 'VenueCapability',
    # Order lifecycle
    'OrderStatus', 'InternalOrderStatus', 'ExecutionReportType', 'FillLiquidity',
    'FillStatus', 'CancelStatus', 'RecoveryState', 'PersistenceState',
    # Risk/governance
    'RiskLevel', 'RiskAction', 'InvariantViolationSeverity', 'HazardVelocity', 'RiskVetoReason',
    # Failure/rejection
    'RejectReason', 'CancelReason', 'InfraFaultType',
    # Strategy/sleeve/control
    'SleeveType', 'ExecutionMode', 'LatencyTier', 'DegradationMode', 'AuthorityTier',
    'ControlMode', 'RiskProfile', 'AssetClass', 'MarketSession', 'ExchangeType', 'PositionStatus',
    # Events/telemetry
    'EventType', 'EventSource', 'PriorityClass', 'ReplayMode',
    # System state
    'TruthStatus', 'RiskMode', 'AlertSeverity',
    # Divergence/state machines
    'DivergenceType', 'ShadowFrontState', 'LiquidityVoidState', 'LiquidityVoidStatus',
    # Replay/persistence
    'SourceType', 'CheckpointType',
    # Contract enums
    'DecisionType', 'ExecutionEventType', 'SignalType', 'StrategyID', 'ResolutionType',
    # Brain engine
    'CollapseQuality',
]
