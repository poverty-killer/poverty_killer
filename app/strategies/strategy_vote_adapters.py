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
from typing import Any, Dict, Optional
from uuid import uuid4

from app.models.contracts import StrategyVote
from app.models.enums import SignalType, StrategyID
from app.models.signals import StrategySignal
from app.strategies.council_metadata import (
    BIAS_LONG,
    BIAS_SHORT,
    BIAS_UNKNOWN,
    FEED_MISSING,
    MODULE_LIQUIDITY_VOID,
    MODULE_SECTOR_ROTATION,
    ROLE_ENTRY,
    ROLE_EXIT,
    SOURCE_STRATEGY_SIGNAL,
    build_council_metadata,
)


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


# ── Adapters ──────────────────────────────────────────────────────────────────

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
        feed_status=FEED_MISSING,
        raw_confidence=signal.confidence,
        normalized_confidence=signal.confidence,
        reason=signal.reason or "liquidity_void_strategy_vote",
        symbol=signal.symbol,
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
        feed_status=FEED_MISSING,
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


__all__ = [
    "adapt_liquidity_void_to_vote",
    "adapt_sector_rotation_to_vote",
]
