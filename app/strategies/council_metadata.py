# FILE: app/strategies/council_metadata.py
"""
Strategy Council Metadata Convention — 6G-C
Shared key names, role constants, and metadata builder for StrategyVote.metadata.

Convention version: 6G-C
All strategy adapters must import from this module to populate metadata.
No adapter may hardcode convention key strings directly.

Purely additive helper — no dispatch, no execution, no threshold logic.
DecisionCompiler does not consume these keys in Stage 2.
Stage 3 enforcement (contribution_role authority separation) is a future bundle.
"""

# ── Metadata key names ────────────────────────────────────────────────────────

KEY_COUNCIL_VERSION               = "council_version"
KEY_SOURCE_MODULE                 = "source_module"
KEY_SOURCE_STRATEGY_ID            = "source_strategy_id"
KEY_SOURCE_OUTPUT_TYPE            = "source_output_type"
KEY_ADAPTER_NAME                  = "adapter_name"
KEY_ADAPTER_VERSION               = "adapter_version"
KEY_CONTRIBUTION_ROLE             = "contribution_role"
KEY_FRESH_ENTRY_AUTHORIZED        = "fresh_entry_authorized"
KEY_PROTECTIVE_ONLY               = "protective_only"
KEY_REQUIRES_EXISTING_POSITION    = "requires_existing_position"
KEY_EXECUTION_CANDIDATE           = "execution_candidate"
KEY_DIRECTIONAL_BIAS              = "directional_bias"
KEY_FEED_STATUS                   = "feed_status"
KEY_RAW_CONFIDENCE                = "raw_confidence"
KEY_NORMALIZED_CONFIDENCE         = "normalized_confidence"
KEY_REASON                        = "reason"
KEY_SYMBOL                        = "symbol"

# ── Contribution role values ──────────────────────────────────────────────────

ROLE_ENTRY           = "entry"
ROLE_EXIT            = "exit"
ROLE_PROTECTIVE_EXIT = "protective_exit"
ROLE_BIAS            = "bias"
ROLE_WARNING         = "warning"
ROLE_OBSERVE_ONLY         = "observe_only"
ROLE_HEDGE                = "hedge"
ROLE_ROUTING              = "routing"
ROLE_DECISION_COMPILATION = "decision_compilation"
ROLE_RISK                 = "risk"
ROLE_SIZING               = "sizing"
ROLE_NET_EDGE             = "net_edge"
ROLE_EXECUTION            = "execution"

_VALID_ROLES = frozenset({
    ROLE_ENTRY,
    ROLE_EXIT,
    ROLE_PROTECTIVE_EXIT,
    ROLE_BIAS,
    ROLE_WARNING,
    ROLE_OBSERVE_ONLY,
    ROLE_HEDGE,
    ROLE_ROUTING,
    ROLE_DECISION_COMPILATION,
    ROLE_RISK,
    ROLE_SIZING,
    ROLE_NET_EDGE,
    ROLE_EXECUTION,
})

# ── Feed status values ────────────────────────────────────────────────────────

FEED_REAL           = "real"
FEED_MISSING        = "missing"
FEED_NOT_APPLICABLE = "not_applicable"

_VALID_FEED_STATUSES = frozenset({
    FEED_REAL,
    FEED_MISSING,
    FEED_NOT_APPLICABLE,
})

# ── Directional bias values ───────────────────────────────────────────────────

BIAS_LONG    = "long"
BIAS_SHORT   = "short"
BIAS_NEUTRAL = "neutral"
BIAS_UNKNOWN = "unknown"

_VALID_BIASES = frozenset({
    BIAS_LONG,
    BIAS_SHORT,
    BIAS_NEUTRAL,
    BIAS_UNKNOWN,
})

# ── Source output type values ─────────────────────────────────────────────────

SOURCE_STRATEGY_SIGNAL              = "StrategySignal"
SOURCE_DC_SIGNAL_RECOMMENDATION     = "DCSignalRecommendation"
SOURCE_FLOOR_SIGNAL_RECOMMENDATION  = "FloorSignalRecommendation"
SOURCE_INTERNAL                     = "internal"
SOURCE_FUSION_DECISION              = "FusionDecision"
SOURCE_DECISION_RECORD              = "DecisionRecord"
SOURCE_POSITION_SIZE_RESULT         = "PositionSizeResult"
SOURCE_RISK_DECISION                = "RiskDecision"
SOURCE_NET_EDGE_EVALUATION          = "NetEdgeEvaluation"
SOURCE_EFFICIENCY_TRANSITION        = "EfficiencyTransition"
SOURCE_EXECUTION_REPORT             = "ExecutionReport"
SOURCE_ORDER_REQUEST                = "OrderRequest"
SOURCE_HEDGE_ASSESSMENT             = "HedgeAssessment"
SOURCE_HEDGE_RECOMMENDATION         = "HedgeRecommendation"
SOURCE_TOPOLOGICAL_SIGNAL           = "TopologicalSignal"
SOURCE_RECALIBRATION_STATE          = "RecalibrationState"
SOURCE_ENTROPY_SCORE                = "EntropyScore"
SOURCE_TOXICITY_ALERT               = "ToxicityAlert"
SOURCE_PHYSICAL_VERIFICATION        = "PhysicalVerification"
SOURCE_WHALE_FLOW_ALERT             = "WhaleFlowAlert"
SOURCE_WHALE_PRESENCE_ZONE          = "WhalePresenceZone"
SOURCE_SENTIMENT_VECTOR             = "SentimentVector"
SOURCE_SYMBOL_SNAPSHOT              = "SymbolSnapshot"
SOURCE_AUTHORIZATION_RECEIPT        = "AuthorizationReceipt"
SOURCE_MASKED_ORDER                 = "MaskedOrder"

_VALID_SOURCE_OUTPUT_TYPES = frozenset({
    SOURCE_STRATEGY_SIGNAL,
    SOURCE_DC_SIGNAL_RECOMMENDATION,
    SOURCE_FLOOR_SIGNAL_RECOMMENDATION,
    SOURCE_INTERNAL,
    SOURCE_FUSION_DECISION,
    SOURCE_DECISION_RECORD,
    SOURCE_POSITION_SIZE_RESULT,
    SOURCE_RISK_DECISION,
    SOURCE_NET_EDGE_EVALUATION,
    SOURCE_EFFICIENCY_TRANSITION,
    SOURCE_EXECUTION_REPORT,
    SOURCE_ORDER_REQUEST,
    SOURCE_HEDGE_ASSESSMENT,
    SOURCE_HEDGE_RECOMMENDATION,
    SOURCE_TOPOLOGICAL_SIGNAL,
    SOURCE_RECALIBRATION_STATE,
    SOURCE_ENTROPY_SCORE,
    SOURCE_TOXICITY_ALERT,
    SOURCE_PHYSICAL_VERIFICATION,
    SOURCE_WHALE_FLOW_ALERT,
    SOURCE_WHALE_PRESENCE_ZONE,
    SOURCE_SENTIMENT_VECTOR,
    SOURCE_SYMBOL_SNAPSHOT,
    SOURCE_AUTHORIZATION_RECEIPT,
    SOURCE_MASKED_ORDER,
})

# ── Source module values ──────────────────────────────────────────────────────

MODULE_SHADOW_FRONT                 = "shadow_front"
MODULE_GAMMA_FRONT                  = "gamma_front"
MODULE_LIQUIDITY_VOID               = "liquidity_void"
MODULE_SECTOR_ROTATION              = "sector_rotation"
MODULE_ADAPTIVE_DC                  = "adaptive_dc"
MODULE_MOVING_FLOOR                 = "moving_floor"
MODULE_HEDGING_FLOW                 = "hedging_flow"
MODULE_STRATEGY_ROUTER              = "strategy_router"
MODULE_SIGNAL_FUSION                = "signal_fusion"
MODULE_DECISION_COMPILER            = "decision_compiler"
MODULE_POSITION_SIZING              = "position_sizing"
MODULE_RISK_GUARD                   = "risk_guard"
MODULE_HYBRID_RISK_GUARD            = "hybrid_risk_guard"
MODULE_UNIFIED_RISK                 = "unified_risk"
MODULE_SAFETY_GATE                  = "safety_gate"
MODULE_KILL_SWITCH                  = "kill_switch"
MODULE_SOVEREIGN_EXECUTION_GUARD    = "sovereign_execution_guard"
MODULE_NET_EDGE_GOVERNOR            = "net_edge_governor"
MODULE_TRADE_EFFICIENCY_GOVERNOR    = "trade_efficiency_governor"
MODULE_EXECUTION_ENGINE             = "execution_engine"
MODULE_ORDER_ROUTER                 = "order_router"
MODULE_PAPER_BROKER                 = "paper_broker"
MODULE_MASKING_LAYER                = "masking_layer"
MODULE_COMMANDER                    = "commander"
MODULE_RECALIBRATOR                 = "recalibrator"
MODULE_REGIME_DETECTOR              = "regime_detector"
MODULE_PHYSICAL_VALIDATOR           = "physical_validator"
MODULE_TOXICITY_ENGINE              = "toxicity_engine"
MODULE_TOPOLOGICAL_ENGINE           = "topological_engine"
MODULE_SHANS_CURVE                  = "shans_curve"
MODULE_INSIDER_SIGNAL_ENGINE        = "insider_signal_engine"
MODULE_ENTROPY_DECODER              = "entropy_decoder"
MODULE_MARKET_SENTIMENT_PROXY       = "market_sentiment_proxy"
MODULE_SENTIMENT_VELOCITY_ENGINE    = "sentiment_velocity_engine"
MODULE_WHALE_FLOW_ENGINE            = "whale_flow_engine"
MODULE_WHALE_ZONE_ENGINE            = "whale_zone_engine"

_VALID_SOURCE_MODULES = frozenset({
    MODULE_SHADOW_FRONT,
    MODULE_GAMMA_FRONT,
    MODULE_LIQUIDITY_VOID,
    MODULE_SECTOR_ROTATION,
    MODULE_ADAPTIVE_DC,
    MODULE_MOVING_FLOOR,
    MODULE_HEDGING_FLOW,
    MODULE_STRATEGY_ROUTER,
    MODULE_SIGNAL_FUSION,
    MODULE_DECISION_COMPILER,
    MODULE_POSITION_SIZING,
    MODULE_RISK_GUARD,
    MODULE_HYBRID_RISK_GUARD,
    MODULE_UNIFIED_RISK,
    MODULE_SAFETY_GATE,
    MODULE_KILL_SWITCH,
    MODULE_SOVEREIGN_EXECUTION_GUARD,
    MODULE_NET_EDGE_GOVERNOR,
    MODULE_TRADE_EFFICIENCY_GOVERNOR,
    MODULE_EXECUTION_ENGINE,
    MODULE_ORDER_ROUTER,
    MODULE_PAPER_BROKER,
    MODULE_MASKING_LAYER,
    MODULE_COMMANDER,
    MODULE_RECALIBRATOR,
    MODULE_REGIME_DETECTOR,
    MODULE_PHYSICAL_VALIDATOR,
    MODULE_TOXICITY_ENGINE,
    MODULE_TOPOLOGICAL_ENGINE,
    MODULE_SHANS_CURVE,
    MODULE_INSIDER_SIGNAL_ENGINE,
    MODULE_ENTROPY_DECODER,
    MODULE_MARKET_SENTIMENT_PROXY,
    MODULE_SENTIMENT_VELOCITY_ENGINE,
    MODULE_WHALE_FLOW_ENGINE,
    MODULE_WHALE_ZONE_ENGINE,
})

# ── Convention version ────────────────────────────────────────────────────────

COUNCIL_CONVENTION_VERSION = "6G-C"


# ── Builder ───────────────────────────────────────────────────────────────────

def build_council_metadata(
    source_module: str,
    source_strategy_id: str,
    source_output_type: str,
    adapter_name: str,
    contribution_role: str,
    fresh_entry_authorized: bool,
    protective_only: bool,
    requires_existing_position: bool,
    execution_candidate: bool,
    directional_bias: str,
    feed_status: str,
    raw_confidence: float,
    normalized_confidence: float,
    reason: str,
    symbol: str,
    adapter_version: str = "1",
    **module_specific: object,
) -> dict:
    """
    Build a convention-compliant StrategyVote metadata dict.

    Validates the four vocabulary-constrained fields before construction.
    All required convention keys are populated. Module-specific additional
    keys may be passed as keyword arguments and are merged into the result.

    Raises ValueError if any constrained field holds an invalid value.
    Stage 3 DecisionCompiler will enforce contribution_role semantics;
    this helper enforces vocabulary only.
    """
    if contribution_role not in _VALID_ROLES:
        raise ValueError(
            f"build_council_metadata: invalid contribution_role={contribution_role!r}. "
            f"Must be one of {sorted(_VALID_ROLES)}"
        )
    if feed_status not in _VALID_FEED_STATUSES:
        raise ValueError(
            f"build_council_metadata: invalid feed_status={feed_status!r}. "
            f"Must be one of {sorted(_VALID_FEED_STATUSES)}"
        )
    if directional_bias not in _VALID_BIASES:
        raise ValueError(
            f"build_council_metadata: invalid directional_bias={directional_bias!r}. "
            f"Must be one of {sorted(_VALID_BIASES)}"
        )
    if source_output_type not in _VALID_SOURCE_OUTPUT_TYPES:
        raise ValueError(
            f"build_council_metadata: invalid source_output_type={source_output_type!r}. "
            f"Must be one of {sorted(_VALID_SOURCE_OUTPUT_TYPES)}"
        )
    if source_module not in _VALID_SOURCE_MODULES:
        raise ValueError(
            f"build_council_metadata: invalid source_module={source_module!r}. "
            f"Must be one of {sorted(_VALID_SOURCE_MODULES)}"
        )

    base = {
        KEY_COUNCIL_VERSION:              COUNCIL_CONVENTION_VERSION,
        KEY_SOURCE_MODULE:                source_module,
        KEY_SOURCE_STRATEGY_ID:           source_strategy_id,
        KEY_SOURCE_OUTPUT_TYPE:           source_output_type,
        KEY_ADAPTER_NAME:                 adapter_name,
        KEY_ADAPTER_VERSION:              adapter_version,
        KEY_CONTRIBUTION_ROLE:            contribution_role,
        KEY_FRESH_ENTRY_AUTHORIZED:       fresh_entry_authorized,
        KEY_PROTECTIVE_ONLY:              protective_only,
        KEY_REQUIRES_EXISTING_POSITION:   requires_existing_position,
        KEY_EXECUTION_CANDIDATE:          execution_candidate,
        KEY_DIRECTIONAL_BIAS:             directional_bias,
        KEY_FEED_STATUS:                  feed_status,
        KEY_RAW_CONFIDENCE:               raw_confidence,
        KEY_NORMALIZED_CONFIDENCE:        normalized_confidence,
        KEY_REASON:                       reason,
        KEY_SYMBOL:                       symbol,
    }
    base.update(module_specific)
    return base