"""
Strategy Vote Adapters — 6G-G1
Pure helper module. Converts StrategySignal outputs from sleeve strategies
into StrategyVote contracts using the council metadata convention.

Scope:
- LiquidityVoid adapter
- SectorRotation adapter

This file performs no runtime activation, no registry, no dispatch,
no feed wiring, no Fusion eligibility, and no risk/sizing/execution
behavior. It is a pure transform helper. Adapter functions return
StrategyVote (not Optional, never None).

All metadata is built through council_metadata.build_council_metadata.
No metadata dictionaries are hand-constructed.
"""

from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, Optional
from uuid import uuid4

from app.models.contracts import StrategyVote
from app.models.enums import SignalDirection, SignalType, StrategyID
from app.models.signals import StrategySignal
from app.strategies.council_metadata import (
    BIAS_LONG,
    BIAS_NEUTRAL,
    BIAS_SHORT,
    BIAS_UNKNOWN,
    FEED_MISSING,
    FEED_REAL,
    KEY_FEED_STATUS,
    KEY_PROTECTIVE_ONLY,
    KEY_REASON,
    KEY_SOURCE_MODULE,
    KEY_SOURCE_OUTPUT_TYPE,
    MODULE_ADAPTIVE_DC,
    MODULE_GAMMA_FRONT,
    MODULE_LIQUIDITY_VOID,
    MODULE_MOVING_FLOOR,
    MODULE_SECTOR_ROTATION,
    ROLE_ENTRY,
    ROLE_EXIT,
    ROLE_PROTECTIVE_EXIT,
    SOURCE_DC_SIGNAL_RECOMMENDATION,
    SOURCE_FLOOR_SIGNAL_RECOMMENDATION,
    SOURCE_STRATEGY_SIGNAL,
    build_council_metadata,
    build_runtime_evidence_record,
)

if TYPE_CHECKING:
    from app.strategies.adaptive_dc import DCSignalRecommendation
    from app.strategies.moving_floor import FloorSignalRecommendation


# ── Preserved metadata key sets ───────────────────────────────────────────────
# Module-level constants. Keys are forwarded into build_council_metadata
# via **module_specific only when present in signal.metadata.

_SECTOR_ROTATION_PRESERVED_KEYS = (
    "volume_zscore",
    "volume",
    "inflow_threshold",
    "macro_pause_active",
    "pnl_pct",
    "hold_ns",
    "entry_price",
    "exit_price",
)

_LIQUIDITY_VOID_PRESERVED_KEYS = (
    "spread_bps",
    "tpe_coherence",
    "tpe_persistence",
    "tpe_betti_0",
    "tpe_betti_1",
    "super_void",
    "structural_collapse",
    "tpe_confidence",
    "toxicity_regime",
    "macro_pause_active",
    "entry_price",
    "exit_price",
    "pnl_pct",
    "pnl_usd",
    "hold_bars",
    "position_side",
)

_GAMMA_FRONT_PRESERVED_KEYS = (
    "print_ratio",
    "print_usd",
    "print_size",
    "print_venue",
    "macro_pause_active",
    "options_confirmed",
    "quantity_semantics",
)


# ── Module-level helpers ──────────────────────────────────────────────────────

def _side_to_signal_type(side: str) -> SignalType:
    """
    Map a StrategySignal.side string to a canonical SignalType.

    buy / long  -> SignalType.BUY
    sell / short -> SignalType.SELL
    anything else -> SignalType.FLAT (does not coerce unknown side into SELL)
    """
    if not isinstance(side, str):
        return SignalType.FLAT
    s = side.strip().lower()
    if s in ("buy", "long"):
        return SignalType.BUY
    if s in ("sell", "short"):
        return SignalType.SELL
    return SignalType.FLAT


def _side_to_bias(side: str) -> str:
    """
    Map a StrategySignal.side string to a council directional bias token.

    buy / long  -> BIAS_LONG
    sell / short -> BIAS_SHORT
    anything else -> BIAS_UNKNOWN (does not coerce unknown side into SHORT)
    """
    if not isinstance(side, str):
        return BIAS_UNKNOWN
    s = side.strip().lower()
    if s in ("buy", "long"):
        return BIAS_LONG
    if s in ("sell", "short"):
        return BIAS_SHORT
    return BIAS_UNKNOWN


def _is_exit_signal(signal: StrategySignal) -> bool:
    """
    Classify a StrategySignal as exit vs entry by metadata signature.

    Exit-path signals from sector_rotation and liquidity_void populate
    metadata with exit_price and/or pnl_pct. Entry-path signals do not.
    Detection key set kept narrow to avoid false positives from generic
    informational metadata keys.
    """
    meta = signal.metadata or {}
    return ("exit_price" in meta) or ("pnl_pct" in meta)


def _floor_direction_to_signal_type(direction: SignalDirection) -> SignalType:
    """
    Map MovingFloor recommendation direction to StrategyVote signal syntax.

    SHORT means protective sell/exit in MovingFloor's own contract, not fresh
    short-entry authority. That semantic guard lives in council metadata.
    """
    if direction == SignalDirection.SHORT:
        return SignalType.SELL
    if direction == SignalDirection.LONG:
        return SignalType.BUY
    return SignalType.FLAT


def _floor_direction_to_bias(direction: SignalDirection) -> str:
    if direction == SignalDirection.SHORT:
        return BIAS_SHORT
    if direction == SignalDirection.LONG:
        return BIAS_LONG
    if direction == SignalDirection.NEUTRAL:
        return BIAS_NEUTRAL
    return BIAS_UNKNOWN


# ── Adapters ──────────────────────────────────────────────────────────────────

def adapt_moving_floor_to_vote(
    recommendation: "FloorSignalRecommendation",
    exchange_ts_ns: int,
    decision_uuid: Optional[str] = None,
) -> StrategyVote:
    """
    Convert a MovingFloor protective recommendation into a StrategyVote.

    Pure transform. No runtime activation, no registry, no dispatch, no
    routing, no execution, and no state mutation. The returned vote is
    protective metadata only: it requires an existing position and is not a
    fresh-entry or execution candidate.
    """
    decision_uuid = decision_uuid or str(uuid4())
    confidence = Decimal(str(recommendation.confidence))
    rationale = tuple(getattr(recommendation, "rationale", ()) or ())
    reason = "|".join(str(item) for item in rationale) or "moving_floor_protective_recommendation"

    metadata = build_council_metadata(
        source_module=MODULE_MOVING_FLOOR,
        source_strategy_id=StrategyID.MOVING_FLOOR.value,
        source_output_type=SOURCE_FLOOR_SIGNAL_RECOMMENDATION,
        adapter_name="adapt_moving_floor_to_vote",
        contribution_role=ROLE_PROTECTIVE_EXIT,
        fresh_entry_authorized=False,
        protective_only=True,
        requires_existing_position=True,
        execution_candidate=False,
        directional_bias=_floor_direction_to_bias(recommendation.signal_direction),
        feed_status=FEED_REAL,
        raw_confidence=float(confidence),
        normalized_confidence=float(confidence),
        reason=reason,
        symbol=recommendation.symbol,
        authority_tier=getattr(recommendation.authority_tier, "value", recommendation.authority_tier),
        event_type=getattr(recommendation.event_type, "value", recommendation.event_type),
        worst_case_fill_price=str(recommendation.worst_case_fill_price),
        protective_semantics="exit_existing_position_only",
    )

    return StrategyVote(
        decision_uuid=decision_uuid,
        strategy_id=StrategyID.MOVING_FLOOR,
        timestamp_ns=exchange_ts_ns,
        signal=_floor_direction_to_signal_type(recommendation.signal_direction),
        confidence=confidence,
        expected_move_bps=Decimal("0"),
        expected_duration_ns=1,
        risk_appetite=Decimal("0"),
        metadata=metadata,
    )

def adapt_liquidity_void_to_vote(
    signal: StrategySignal,
    exchange_ts_ns: int,
    decision_uuid: Optional[str] = None,
) -> StrategyVote:
    """
    Convert a LiquidityVoid StrategySignal into a StrategyVote.

    Pure transform. No runtime activation, no dispatch, no feed wiring,
    no Fusion eligibility, no risk/sizing/execution behavior.
    """
    is_exit = _is_exit_signal(signal)
    sig_type = _side_to_signal_type(signal.side)
    bias = _side_to_bias(signal.side)
    decision_uuid = decision_uuid or str(uuid4())
    source_metadata = signal.metadata or {}

    preserved_meta: Dict[str, Any] = {}
    for key in _LIQUIDITY_VOID_PRESERVED_KEYS:
        if key in source_metadata:
            preserved_meta[key] = source_metadata[key]

    metadata = build_council_metadata(
        source_module=MODULE_LIQUIDITY_VOID,
        source_strategy_id=StrategyID.LIQUIDITY_VOID.value,
        source_output_type=SOURCE_STRATEGY_SIGNAL,
        adapter_name="adapt_liquidity_void_to_vote",
        contribution_role=ROLE_EXIT if is_exit else ROLE_ENTRY,
        fresh_entry_authorized=not is_exit,
        protective_only=False,
        requires_existing_position=is_exit,
        execution_candidate=True,
        directional_bias=bias,
        feed_status=FEED_REAL,
        raw_confidence=signal.confidence,
        normalized_confidence=signal.confidence,
        reason=signal.reason or "liquidity_void_strategy_vote",
        symbol=signal.symbol,
        activation_path="governed_observed_pair_active_candidate",
        active_promotion_requires="fusion_router_admission_same_candle_netedge_and_broker_guards",
        **preserved_meta,
    )

    return StrategyVote(
        decision_uuid=decision_uuid,
        strategy_id=StrategyID.LIQUIDITY_VOID,
        timestamp_ns=exchange_ts_ns,
        signal=sig_type,
        confidence=Decimal(str(signal.confidence)),
        expected_move_bps=Decimal("200"),
        expected_duration_ns=300_000_000_000,
        risk_appetite=Decimal(str(signal.quantity)),
        metadata=metadata,
    )


def adapt_gamma_front_to_vote(
    signal: StrategySignal,
    exchange_ts_ns: int,
    decision_uuid: Optional[str] = None,
) -> StrategyVote:
    """
    Convert a GammaFront StrategySignal into a StrategyVote.

    Pure transform only. GammaFront quantity remains its declared provisional
    risk fraction metadata; this adapter does not translate it into physical
    inventory, route orders, or mutate runtime state.
    """
    is_exit = _is_exit_signal(signal)
    sig_type = _side_to_signal_type(signal.side)
    bias = _side_to_bias(signal.side)
    decision_uuid = decision_uuid or str(uuid4())
    source_metadata = signal.metadata or {}

    preserved_meta: Dict[str, Any] = {}
    for key in _GAMMA_FRONT_PRESERVED_KEYS:
        if key in source_metadata:
            preserved_meta[key] = source_metadata[key]

    metadata = build_council_metadata(
        source_module=MODULE_GAMMA_FRONT,
        source_strategy_id=StrategyID.GAMMA_FRONT.value,
        source_output_type=SOURCE_STRATEGY_SIGNAL,
        adapter_name="adapt_gamma_front_to_vote",
        contribution_role=ROLE_EXIT if is_exit else ROLE_ENTRY,
        fresh_entry_authorized=not is_exit,
        protective_only=False,
        requires_existing_position=is_exit,
        execution_candidate=True,
        directional_bias=bias,
        feed_status=FEED_REAL,
        raw_confidence=signal.confidence,
        normalized_confidence=signal.confidence,
        reason=signal.reason or "gamma_front_strategy_vote",
        symbol=signal.symbol,
        sizing_semantics="provisional_risk_fraction_not_physical_quantity",
        **preserved_meta,
    )

    return StrategyVote(
        decision_uuid=decision_uuid,
        strategy_id=StrategyID.GAMMA_FRONT,
        timestamp_ns=exchange_ts_ns,
        signal=sig_type,
        confidence=Decimal(str(signal.confidence)),
        expected_move_bps=Decimal("200"),
        expected_duration_ns=300_000_000_000,
        risk_appetite=Decimal(str(signal.quantity)),
        metadata=metadata,
    )


def adapt_adaptive_dc_to_vote(
    recommendation: "DCSignalRecommendation",
    exchange_ts_ns: int,
    decision_uuid: Optional[str] = None,
) -> StrategyVote:
    """
    Convert an AdaptiveDC recommendation into a StrategyVote.

    Pure transform only. It marks the recommendation as a governed entry
    candidate and does not bypass the governed decision, risk, or order
    routing path.
    """
    decision_uuid = decision_uuid or str(uuid4())
    confidence = Decimal(str(recommendation.confidence))
    rationale = tuple(getattr(recommendation, "rationale", ()) or ())
    reason = "|".join(str(item) for item in rationale) or "adaptive_dc_entry_candidate"

    metadata = build_council_metadata(
        source_module=MODULE_ADAPTIVE_DC,
        source_strategy_id=StrategyID.ADAPTIVE_DC.value,
        source_output_type=SOURCE_DC_SIGNAL_RECOMMENDATION,
        adapter_name="adapt_adaptive_dc_to_vote",
        contribution_role=ROLE_ENTRY,
        fresh_entry_authorized=True,
        protective_only=False,
        requires_existing_position=False,
        execution_candidate=True,
        directional_bias=_floor_direction_to_bias(recommendation.signal_direction),
        feed_status=FEED_REAL,
        raw_confidence=float(confidence),
        normalized_confidence=float(confidence),
        reason=reason,
        symbol=recommendation.symbol,
        event_type=getattr(recommendation.event_type, "value", recommendation.event_type),
        event_direction=getattr(recommendation.event_direction, "value", recommendation.event_direction),
        theta=str(recommendation.theta),
        authority_tier=getattr(recommendation.authority_tier, "value", recommendation.authority_tier),
        recommendation_semantics="entry_candidate_only_governed_path_required",
    )

    return StrategyVote(
        decision_uuid=decision_uuid,
        strategy_id=StrategyID.ADAPTIVE_DC,
        timestamp_ns=exchange_ts_ns,
        signal=_floor_direction_to_signal_type(recommendation.signal_direction),
        confidence=confidence,
        expected_move_bps=Decimal("200"),
        expected_duration_ns=300_000_000_000,
        risk_appetite=confidence,
        metadata=metadata,
    )


def adapt_sector_rotation_to_vote(
    signal: StrategySignal,
    exchange_ts_ns: int,
    decision_uuid: Optional[str] = None,
) -> StrategyVote:
    """
    Convert a SectorRotation StrategySignal into a StrategyVote.

    Pure transform. No runtime activation, no dispatch, no feed wiring,
    no Fusion eligibility, no risk/sizing/execution behavior.
    """
    is_exit = _is_exit_signal(signal)
    sig_type = _side_to_signal_type(signal.side)
    bias = _side_to_bias(signal.side)
    decision_uuid = decision_uuid or str(uuid4())
    source_metadata = signal.metadata or {}

    preserved_meta: Dict[str, Any] = {}
    for key in _SECTOR_ROTATION_PRESERVED_KEYS:
        if key in source_metadata:
            preserved_meta[key] = source_metadata[key]

    metadata = build_council_metadata(
        source_module=MODULE_SECTOR_ROTATION,
        source_strategy_id=StrategyID.SECTOR_ROTATION.value,
        source_output_type=SOURCE_STRATEGY_SIGNAL,
        adapter_name="adapt_sector_rotation_to_vote",
        contribution_role=ROLE_EXIT if is_exit else ROLE_ENTRY,
        fresh_entry_authorized=not is_exit,
        protective_only=False,
        requires_existing_position=is_exit,
        execution_candidate=True,
        directional_bias=bias,
        feed_status=FEED_REAL,
        raw_confidence=signal.confidence,
        normalized_confidence=signal.confidence,
        reason=signal.reason or "sector_rotation_strategy_vote",
        symbol=signal.symbol,
        **preserved_meta,
    )

    return StrategyVote(
        decision_uuid=decision_uuid,
        strategy_id=StrategyID.SECTOR_ROTATION,
        timestamp_ns=exchange_ts_ns,
        signal=sig_type,
        confidence=Decimal(str(signal.confidence)),
        expected_move_bps=Decimal("200"),
        expected_duration_ns=300_000_000_000,
        risk_appetite=Decimal(str(signal.quantity)),
        metadata=metadata,
    )


def adapt_vote_to_runtime_evidence(vote: StrategyVote) -> dict:
    """
    Convert a StrategyVote into the Seam 7E runtime evidence contract.

    Pure transform only. This preserves provenance and does not authorize
    dispatch, execution, broker routing, sizing, or risk approval.
    """
    metadata = dict(vote.metadata or {})
    module_name = str(metadata.get(KEY_SOURCE_MODULE) or vote.strategy_id)
    protective_only = bool(metadata.get(KEY_PROTECTIVE_ONLY, False))
    feed_status = str(metadata.get(KEY_FEED_STATUS) or FEED_MISSING)
    status = "ACTIVE_PROTECTION" if protective_only else "ACTIVE_STRATEGY_VOTE"
    effect = "PROTECT_TOTAL_PROFIT" if protective_only else "VOTE"
    if feed_status == FEED_MISSING:
        status = "MISSING_FEED_TRUTH"
        effect = "NO_EFFECT_WITH_REASON"

    return build_runtime_evidence_record(
        module_name=module_name,
        category="strategy_alpha",
        status=status,
        input_truth=f"strategy_vote.feed_status:{feed_status}",
        output_summary=str(metadata.get(KEY_SOURCE_OUTPUT_TYPE) or "StrategyVote"),
        effect=effect,
        score_or_direction=vote.signal,
        confidence=vote.confidence,
        reason=str(metadata.get(KEY_REASON) or "STRATEGY_VOTE_PRESENT"),
        timestamp_ns=vote.timestamp_ns,
        provenance={
            "vote_id": vote.vote_id,
            "decision_uuid": vote.decision_uuid,
            "strategy_id": str(vote.strategy_id),
            "metadata": metadata,
        },
    )


def missing_strategy_runtime_evidence(
    *,
    module_name: str,
    reason: str,
    timestamp_ns: int,
    category: str = "strategy_alpha",
) -> dict:
    """
    Represent a strategy module that could not lawfully emit native evidence.
    """
    return build_runtime_evidence_record(
        module_name=module_name,
        category=category,
        status="MISSING_FEED_TRUTH",
        input_truth="native_strategy_input_absent",
        output_summary="No native strategy vote or signal was supplied; no alpha was invented.",
        effect="NO_EFFECT_WITH_REASON",
        reason=reason,
        timestamp_ns=timestamp_ns,
        provenance={"adapter": "missing_strategy_runtime_evidence"},
    )


__all__ = [
    "adapt_adaptive_dc_to_vote",
    "adapt_gamma_front_to_vote",
    "adapt_liquidity_void_to_vote",
    "adapt_moving_floor_to_vote",
    "adapt_sector_rotation_to_vote",
    "adapt_vote_to_runtime_evidence",
    "missing_strategy_runtime_evidence",
]
