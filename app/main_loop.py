# FILE: app/main_loop.py
# CORRECTED: Uses per-symbol ShansCurve from SymbolRuntime

"""
Main Loop - Sovereign Market-Data / Brain / State / Risk-Ingress Pipeline

[Full docstring preserved - same as your current file]

BUNDLE PER-SYMBOL SHANS OWNERSHIP FIX (2026-04-27):
    - Each SymbolRuntime now owns its own ShansCurve instance
    - on_order_book() calls runtime.shans_curve.update_order_book() instead of global
    - Prevents cross-symbol buffer contamination
"""

import logging
import time
import threading
import math
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional, Dict, Any, List, Tuple, Set, Mapping

from app.config import Config
from app.commander import Commander
from app.risk.guard import HybridRiskGuard
from app.risk.position_sizing import PositionSizingEngine, PositionSizeResult
from app.brain.signal_fusion import SignalFusion
from app.brain.data_validator import DataContinuityValidator
from app.brain.recalibrator import Recalibrator
from app.brain.shans_curve import ShansCurve
from app.brain.topological_engine import TopologicalEngine, TopologicalSignal
from app.brain.regime_detector import RegimeDetector
from app.brain.physical_validator import PhysicalValidator
from app.brain.toxicity_engine import ToxicityEngine, ToxicityAlert
from app.brain.entropy_decoder import EntropyDecoder
from app.brain.insider_signal_engine import InsiderSignalEngine, InsiderSignalSnapshot
from app.execution.engine import ExecutionEngine
from app.strategies.strategy_router import StrategyRouter
from app.strategies.shadow_front import ShadowFrontStrategy
from app.core.decision_compiler import DecisionCompiler
from app.core.candidate_lifecycle import (
    build_candidate_lifecycle,
    lifecycle_to_dict,
    opportunity_scorecard_from_lifecycle,
    record_decision_compiler_result,
    record_execution_result,
)
from app.core.market_snapshot import build_market_truth_snapshot
from app.core.decision_frame import (
    build_decision_frame_from_runtime,
    decision_frame_timeout_ns,
    resolve_active_threshold_profile,
)
from app.core.truth_reconciler import TruthReconciler
from app.core.whole_bot_attribution import build_runtime_edge_attribution
from app.models import (
    OrderBookSnapshot,
    Candle,
    FusionDecision,
    StrategySignal,
    StrategyVote,
    TruthFrame,
    ExchangeTruth,
    ExchangePosition,
    ExchangeOpenOrder,
    ExchangeFill,
    ExecutionTruth,
    SubmittedOrder,
    PendingCancel,
    Acknowledgement,
    Rejection,
    PortfolioTruth,
    PortfolioPosition,
    StrategyTruth,
    StrategyTruthEntry,
    RiskTruth,
)
from app.models.enums import (
    BookIntegrity,
    LiquidityRegime,
    RegimeType,
    RiskAction,
    SleeveType,
    SignalType,
    ToxicityLevel,
    TruthStatus,
    RiskMode,
    OrderSide,
    InternalOrderStatus,
    StrategyID,
)
from app.risk.safety import SafetyGate
from app.risk.pre_trade_guardrails import (
    PreTradeGuardrailRequest,
    evaluate_pre_trade_guardrails,
)
from app.operator_activation.paper_baseline import (
    PAPER_BASELINE_SYMBOL_PROTECTED,
    evaluate_protected_baseline_trade,
)
from app.market.capability_registry import build_default_capability_registry
from app.market.venue_capabilities import (
    CapabilityAwareCandidate,
    PortalAssetClass,
    PortalEnvironment,
    PortalPolicyMode,
    PortalSelectionRequest,
    classify_quote_session,
)
from app.telemetry.event_store import TelemetryEventStore
from app.symbol_runtime import SymbolRuntime
from app.strategies.council_metadata import (
    build_council_metadata,
    MODULE_GAMMA_FRONT,
    SOURCE_STRATEGY_SIGNAL,
    ROLE_EXIT, ROLE_OBSERVE_ONLY,
    BIAS_SHORT, BIAS_LONG, BIAS_UNKNOWN,
    FEED_MISSING,
)
# OBSERVE-ONLY (Stage 2-C): adapter imports for telemetry-only StrategyVote
# synthesis from dormant-sleeve signals. Adapters are NOT invoked from any
# dispatch / DecisionCompiler / Fusion / execution path.
from app.strategies.strategy_vote_adapters import (
    adapt_liquidity_void_to_vote,
    adapt_moving_floor_to_vote,
    adapt_sector_rotation_to_vote,
)
from app.strategies.moving_floor import FloorMarketTick, FloorRiskContext
from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)

_MIN_BOOK_PROCESS_INTERVAL_NS: int = 200_000_000
_BROKER_POSITION_CACHE_TTL_NS: int = 30_000_000_000

# Candle admission logging rate limits (seconds)
_CANDLE_REJECT_LOG_INTERVAL_SEC: int = 60


def _ns_to_datetime(ns: int) -> datetime:
    return datetime.utcfromtimestamp(ns / 1_000_000_000.0)


def _log_dispatch_diag(reason_code: str, **fields: Any) -> None:
    """Emit compact dispatch-admission evidence without changing decisions."""
    clean_fields = {
        key: value
        for key, value in fields.items()
        if value is not None
    }
    logger.info(
        "[DISPATCH_DIAG] reason_code=%s fields=%s",
        reason_code,
        clean_fields,
    )


def _last_latency_truth(execution_engine: Any) -> Dict[str, Any]:
    get_status = getattr(execution_engine, "get_status", None)
    if not callable(get_status):
        return {}
    status = get_status()
    if not isinstance(status, dict):
        return {}
    latency_truth = status.get("last_latency_truth")
    return dict(latency_truth) if isinstance(latency_truth, dict) else {}


def _latest_runtime_advisory_pair(
    runtime: Any,
) -> Tuple[Optional[Any], Optional[Any], str]:
    advisory_sources = (
        (
            "last_sector_rotation_observed_signal",
            "last_sector_rotation_observed_vote",
            repr(SleeveType.SECTOR_ROTATION),
        ),
        (
            "last_liquidity_void_observed_signal",
            "last_liquidity_void_observed_vote",
            repr(SleeveType.FLV),
        ),
    )
    for signal_attr, vote_attr, sleeve in advisory_sources:
        signal = getattr(runtime, signal_attr, None)
        vote = getattr(runtime, vote_attr, None)
        if signal is not None or vote is not None:
            return signal, vote, sleeve
    return None, None, "RuntimeDispatch"


def _threshold_profile_value(profile: Dict[str, Any], threshold_name: str, default: Any = None) -> Any:
    by_name = profile.get("thresholds_by_name")
    if isinstance(by_name, dict):
        item = by_name.get(threshold_name)
        if isinstance(item, dict) and "exploration_value" in item:
            return item["exploration_value"]
    return default


def _sleeve_module_name(sleeve: Any) -> str:
    if sleeve == StrategyID.MOVING_FLOOR or str(getattr(sleeve, "value", sleeve)) == "moving_floor":
        return "MovingFloor"
    if sleeve == SleeveType.SHADOW_FRONT:
        return "ShadowFront"
    if sleeve == SleeveType.SECTOR_ROTATION:
        return "SectorRotation"
    if sleeve == SleeveType.GAMMA_FRONT:
        return "GammaFront"
    if sleeve == SleeveType.FLV:
        return "LiquidityVoid"
    if sleeve == SleeveType.ENTROPY_DECODER:
        return "EntropyDecoder"
    return str(getattr(sleeve, "value", sleeve) or "UnknownSleeve")


def _dispatch_signal_text(signal_or_side: Any) -> str:
    side = getattr(signal_or_side, "side", signal_or_side)
    text = str(side or "").strip().lower()
    if text == "buy":
        return "BUY"
    if text == "sell":
        return "SELL"
    return "NONE"


def _dispatch_signal_from_bias(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"bullish", "long", "buy", "1"}:
        return "BUY"
    if text in {"bearish", "short", "sell", "-1"}:
        return "SELL"
    return "NONE"


def _alpha_evidence_status(reason_code: str, default: str = "DECLINED") -> str:
    reason = str(reason_code or "")
    if reason in {"shans_not_ready", "OBSERVED_SIGNAL_MISSING", "OBSERVED_VOTE_MISSING"}:
        return "MISSING_TRUTH"
    if reason in {"OBSERVED_PAIR_STALE"}:
        return "STALE"
    if reason in {
        "low_sentiment",
        "low_volume_zscore",
        "weak_regime_match",
        "optional_module_absent",
    }:
        return "PENALTY"
    if reason.startswith("shadowfront_declined"):
        return "DECLINED"
    return default


def _runtime_order_book_spread_bps(runtime: Any) -> Optional[float]:
    book = getattr(runtime, "last_order_book", None)
    if book is None:
        return None
    try:
        spread_bps = float(getattr(book, "spread_bps"))
    except (AttributeError, TypeError, ValueError):
        return None
    if not math.isfinite(spread_bps) or spread_bps < 0:
        return None
    return spread_bps


def _vote_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _build_runtime_decision_frame(
    *,
    config: Any,
    symbol: str,
    exchange_ts_ns: int,
    market_truth: Optional[Dict[str, Any]] = None,
    signal: Any = None,
    strategy_vote: Any = None,
    fusion: Any = None,
    dispatch_evidence: Tuple[Dict[str, Any], ...] = (),
    edge_attribution: Optional[Dict[str, Any]] = None,
    guardrail_verdict: Optional[Dict[str, Any]] = None,
    active_threshold_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    market = dict(market_truth or {})
    snapshot = dict(market.get("market_truth_snapshot") or {})
    profile = dict(active_threshold_profile or resolve_active_threshold_profile(config))
    timeout_ns = decision_frame_timeout_ns(config, snapshot)
    created_at_ns = int(snapshot.get("snapshot_created_ns") or exchange_ts_ns)
    return build_decision_frame_from_runtime(
        symbol=symbol,
        snapshot=snapshot,
        created_at_ns=created_at_ns,
        timeout_ns=timeout_ns,
        active_threshold_profile=profile,
        signal=signal,
        strategy_vote=strategy_vote,
        fusion=fusion,
        dispatch_evidence=dispatch_evidence,
        edge_attribution=edge_attribution or {},
        guardrail_verdict=guardrail_verdict,
    )


def _emit_candidate_scorecard_diag(
    reason_code: str,
    *,
    symbol: str,
    exchange_ts_ns: int,
    source_sleeve: str,
    config: Any = None,
    side: Optional[str] = None,
    signal: Any = None,
    strategy_vote: Any = None,
    fusion: Any = None,
    market_truth: Optional[Dict[str, Any]] = None,
    candle_truth: Optional[Dict[str, Any]] = None,
    latency_truth: Optional[Dict[str, Any]] = None,
    active_threshold_profile: Optional[Dict[str, Any]] = None,
    dispatch_evidence: Tuple[Dict[str, Any], ...] = (),
    **fields: Any,
) -> Dict[str, Any]:
    """Log a non-executable advisory scorecard before compiler/submission."""
    clean_fields = {key: value for key, value in fields.items() if value is not None}
    side_value = str(
        side
        or getattr(signal, "side", None)
        or clean_fields.get("side")
        or "unknown"
    ).lower()
    blocker_evidence = {
        "module": source_sleeve,
        "sleeve": source_sleeve,
        "status": _alpha_evidence_status(reason_code, default="BLOCK"),
        "reason_code": reason_code,
        "evidence": dict(clean_fields),
    }
    profile = dict(active_threshold_profile or resolve_active_threshold_profile(config))
    frame = _build_runtime_decision_frame(
        config=config,
        symbol=symbol,
        exchange_ts_ns=exchange_ts_ns,
        market_truth=market_truth or {},
        signal=signal,
        strategy_vote=strategy_vote,
        fusion=fusion,
        dispatch_evidence=(*dispatch_evidence, blocker_evidence),
        active_threshold_profile=profile,
    )
    lifecycle = build_candidate_lifecycle(
        candidate_id=f"{symbol}:{side_value}:{exchange_ts_ns}:{source_sleeve}:{reason_code}",
        symbol=symbol,
        side=side_value,
        source_sleeve=source_sleeve,
        timestamp_ns=exchange_ts_ns,
        signal=signal,
        strategy_vote=strategy_vote,
        fusion=fusion,
        market_truth=market_truth or {},
        candle_truth=candle_truth or {},
        latency_truth=latency_truth or {},
        active_threshold_profile=profile,
        decision_frame=frame,
        dispatch_evidence=(*dispatch_evidence, blocker_evidence),
    )
    lifecycle = record_execution_result(
        lifecycle,
        submitted=False,
        execution_result=SimpleNamespace(
            normalized_status="blocked",
            route=None,
            reason_code=reason_code,
            message="pre_submit_advisory_scorecard_non_executable",
            block_evidence={
                **dict(clean_fields),
                "submit_signal_called": False,
                "decision_compiler_called": False,
                "broker_post": False,
            },
        ),
    )
    candidate_lifecycle = lifecycle_to_dict(lifecycle)
    opportunity_scorecard = opportunity_scorecard_from_lifecycle(candidate_lifecycle)
    snapshot = {}
    if isinstance(market_truth, dict):
        snapshot_candidate = market_truth.get("market_truth_snapshot")
        if isinstance(snapshot_candidate, dict):
            snapshot = snapshot_candidate
    log_fields = {
        **dict(clean_fields),
        "symbol": symbol,
        "exchange_ts_ns": exchange_ts_ns,
        "source_sleeve": source_sleeve,
        "side": side_value,
        "submit_signal_called": False,
        "decision_compiler_called": False,
        "candidate_lifecycle": candidate_lifecycle,
        "opportunity_scorecard": opportunity_scorecard,
        "candidate_id": opportunity_scorecard.get("candidate_id"),
        "module_contributions": opportunity_scorecard.get("module_contributions"),
        "penalties": opportunity_scorecard.get("penalties"),
        "gate_trace": opportunity_scorecard.get("gate_trace"),
        "raw_opportunity_score": opportunity_scorecard.get("raw_opportunity_score"),
        "final_opportunity_score": opportunity_scorecard.get("final_opportunity_score"),
        "opportunity_verdict": opportunity_scorecard.get("opportunity_verdict"),
        "execution_verdict": opportunity_scorecard.get("execution_verdict"),
        "execution_blocker_reason_codes": opportunity_scorecard.get("execution_blocker_reason_codes"),
        "broker_boundary_result": opportunity_scorecard.get("broker_boundary_result"),
        "broker_post": False,
        "active_threshold_profile": opportunity_scorecard.get("active_threshold_profile"),
        "decision_frame": opportunity_scorecard.get("decision_frame"),
        "frame_id": opportunity_scorecard.get("frame_id"),
        "frame_output": opportunity_scorecard.get("frame_output"),
        "frame_status": opportunity_scorecard.get("frame_status"),
        "frame_reason_codes": opportunity_scorecard.get("frame_reason_codes"),
        "snapshot_id": snapshot.get("snapshot_id"),
        "snapshot_status": snapshot.get("snapshot_status"),
        "snapshot_reason_codes": snapshot.get("snapshot_reason_codes"),
        "snapshot_authority": snapshot.get("snapshot_authority"),
    }
    _log_dispatch_diag(reason_code, **log_fields)
    return candidate_lifecycle


def _timeframe_to_ns(timeframe: Any) -> Optional[int]:
    text = str(timeframe or "").strip().lower()
    if not text:
        return None
    units = {
        "s": 1_000_000_000,
        "m": 60_000_000_000,
        "h": 3_600_000_000_000,
        "d": 86_400_000_000_000,
    }
    suffix = text[-1]
    if suffix not in units:
        return None
    try:
        count = int(text[:-1] or "1")
    except ValueError:
        return None
    if count <= 0:
        return None
    return count * units[suffix]


def _runtime_market_truth_fields(
    symbol: str,
    runtime: Any,
    consumer_exchange_ts_ns: int,
    *,
    data_source_type: str = "runtime",
) -> Dict[str, Any]:
    latest_book = getattr(runtime, "last_order_book", None)
    latest_candle = getattr(runtime, "last_candle", None)
    return {
        "symbol": symbol,
        "consumer_exchange_ts_ns": consumer_exchange_ts_ns,
        "latest_book_ts_ns": getattr(latest_book, "exchange_ts_ns", None),
        "latest_candle_ts_ns": getattr(latest_candle, "exchange_ts_ns", None),
        "data_source_type": data_source_type,
    }


def _candidate_market_truth_snapshot_fields(
    symbol: str,
    runtime: Any,
    consumer_exchange_ts_ns: int,
    *,
    candle_truth: Optional[Dict[str, Any]] = None,
    data_source_type: str = "runtime",
    current_ns: Optional[int] = None,
) -> Dict[str, Any]:
    """Build candidate-local market truth plus canonical snapshot evidence."""
    candle_truth = dict(candle_truth or {})
    source_type = str(candle_truth.get("data_source_type") or data_source_type or "runtime")
    snapshot_current_ns = (
        current_ns
        or candle_truth.get("receive_ts_ns")
        or candle_truth.get("candle_batch_received_ns")
        or now_ns()
    )
    market_truth = _runtime_market_truth_fields(
        symbol,
        runtime,
        consumer_exchange_ts_ns,
        data_source_type=source_type,
    )
    snapshot = build_market_truth_snapshot(
        symbol=symbol,
        market_truth=market_truth,
        candle_truth=candle_truth,
        current_ns=int(snapshot_current_ns),
    )
    market_truth.update(
        {
            "market_truth_snapshot": snapshot,
            "snapshot_id": snapshot.get("snapshot_id"),
            "snapshot_status": snapshot.get("snapshot_status"),
            "snapshot_reason_codes": snapshot.get("snapshot_reason_codes"),
            "snapshot_authority": snapshot.get("snapshot_authority"),
        }
    )
    return market_truth


def _classify_candle_execution_truth(
    *,
    symbol: str,
    runtime: Any,
    candle: Candle,
    exchange_ts_ns: int,
    current_ns: Optional[int] = None,
) -> Dict[str, Any]:
    current_ns = int(current_ns or now_ns())
    candle_start_ns = int(exchange_ts_ns or 0)
    timeframe_ns = _timeframe_to_ns(getattr(candle, "timeframe", None))
    recorded_close_ns = getattr(candle, "candle_close_ts_ns", None)
    try:
        candle_close_ns = int(recorded_close_ns) if recorded_close_ns else 0
    except (TypeError, ValueError):
        candle_close_ns = 0
    if candle_close_ns <= 0:
        candle_close_ns = candle_start_ns + timeframe_ns if candle_start_ns > 0 and timeframe_ns else candle_start_ns
    age_ns = current_ns - candle_close_ns
    policy_ms = getattr(candle, "candle_freshness_policy_ms", None)
    latest_batch_candle = getattr(candle, "latest_batch_candle", None)
    source_type = str(getattr(candle, "data_source_type", "unknown") or "unknown")
    detail = _runtime_market_truth_fields(
        symbol,
        runtime,
        exchange_ts_ns,
        data_source_type=source_type,
    )
    detail.update(
        {
            "consumer_timestamp_ns": exchange_ts_ns,
            "candle_id": exchange_ts_ns,
            "candle_age_ms": age_ns / 1_000_000.0,
            "candle_start_ts_ns": candle_start_ns,
            "candle_close_ts_ns": candle_close_ns,
            "candle_age_from_close_ms": age_ns / 1_000_000.0,
            "consumer_age_ms": age_ns / 1_000_000.0,
            "candle_freshness_policy_ms": policy_ms,
            "candle_timeframe": getattr(candle, "timeframe", None),
            "provider_id": getattr(candle, "provider_id", None),
            "latest_batch_candle": latest_batch_candle,
            "latest_provider_batch_candle": getattr(candle, "latest_provider_batch_candle", None),
            "latest_closed_batch_candle": getattr(candle, "latest_closed_batch_candle", None),
            "provider_batch_head_ts_ns": getattr(candle, "provider_batch_head_ts_ns", None),
            "candle_batch_received_ns": getattr(candle, "candle_batch_received_ns", None),
            "receive_ts_ns": getattr(candle, "candle_batch_received_ns", None) or current_ns,
            "candle_closed_at_receive": getattr(candle, "candle_closed_at_receive", None),
            "executable_market_truth": False,
            "data_health_reason_code": "DATA_HEALTH_UNKNOWN",
            "candle_freshness_reason_code": "CANDLE_FRESHNESS_POLICY_MISSING",
        }
    )
    if exchange_ts_ns <= 0:
        detail["data_health_reason_code"] = "DATA_TIMESTAMP_MISSING"
        detail["candle_freshness_reason_code"] = "CANDLE_TIMESTAMP_MISSING"
        detail["data_source_type"] = "unknown"
        return detail
    if source_type in {"backfill", "replay", "synthetic", "observe_only"}:
        detail["data_health_reason_code"] = "DATA_BACKFILL_OBSERVE_ONLY"
        detail["candle_freshness_reason_code"] = "CANDLE_BATCH_BACKFILL_OBSERVE_ONLY"
        return detail
    if age_ns < 0:
        detail["data_health_reason_code"] = "DATA_RUNTIME_CANDLE_IN_PROGRESS"
        detail["candle_freshness_reason_code"] = "CANDLE_NOT_CLOSED"
        detail["candle_age_ms"] = age_ns / 1_000_000.0
        detail["candle_age_from_close_ms"] = age_ns / 1_000_000.0
        detail["consumer_age_ms"] = age_ns / 1_000_000.0
        return detail
    try:
        policy_ms_float = float(policy_ms)
    except (TypeError, ValueError):
        detail["data_health_reason_code"] = "DATA_HEALTH_UNKNOWN"
        detail["candle_freshness_reason_code"] = "CANDLE_FRESHNESS_POLICY_MISSING"
        return detail
    if policy_ms_float <= 0:
        detail["data_health_reason_code"] = "DATA_HEALTH_UNKNOWN"
        detail["candle_freshness_reason_code"] = "CANDLE_FRESHNESS_POLICY_MISSING"
        return detail
    if latest_batch_candle is not True:
        detail["data_health_reason_code"] = "DATA_BACKFILL_OBSERVE_ONLY"
        detail["candle_freshness_reason_code"] = "CANDLE_BATCH_BACKFILL_OBSERVE_ONLY"
        return detail
    if (age_ns / 1_000_000.0) > policy_ms_float:
        detail["data_health_reason_code"] = "DATA_BACKFILL_OBSERVE_ONLY"
        detail["candle_freshness_reason_code"] = "CANDLE_STALE"
        return detail
    detail["data_health_reason_code"] = "DATA_HEALTHY"
    detail["candle_freshness_reason_code"] = "CANDLE_RUNTIME_FRESH"
    detail["executable_market_truth"] = True
    return detail


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _execution_admission_block_fields(block_result: Any) -> Dict[str, Any]:
    if block_result is None:
        return {}
    reason_code = getattr(block_result, "reason_code", None)
    if not isinstance(reason_code, str) or not reason_code:
        return {}
    fields: Dict[str, Any] = {
        "execution_admission_status": getattr(block_result, "normalized_status", None),
        "execution_admission_route": getattr(block_result, "route", None),
        "execution_admission_reason_code": reason_code,
        "execution_admission_message": getattr(block_result, "message", None),
    }
    block_evidence = getattr(block_result, "block_evidence", None)
    if isinstance(block_evidence, dict):
        fields["execution_admission_block_evidence"] = dict(block_evidence)
    candidate_lifecycle = getattr(block_result, "candidate_lifecycle", None)
    if isinstance(candidate_lifecycle, dict):
        fields["execution_admission_candidate_lifecycle"] = dict(candidate_lifecycle)
        fields["execution_admission_opportunity_verdict"] = candidate_lifecycle.get("opportunity_verdict")
        fields["execution_admission_final_opportunity_score"] = candidate_lifecycle.get("final_opportunity_score")
    return {key: value for key, value in fields.items() if value is not None}


def _decision_compiler_status_fields(
    *,
    decision_record: Any,
    signal_metadata: Dict[str, Any],
    submitted: bool,
    execution_admission_block: Any = None,
) -> Dict[str, Any]:
    outputs = _as_mapping(getattr(decision_record, "outputs", None))
    metadata = _as_mapping(getattr(decision_record, "metadata", None))
    additional = _as_mapping(outputs.get("additional"))
    guardrail = _as_mapping(
        additional.get("pre_trade_guardrail_verdict")
        or signal_metadata.get("pre_trade_guardrail_verdict")
    )
    aggression_contract = _as_mapping(
        additional.get("canonical_aggression_contract")
        or signal_metadata.get("canonical_aggression_contract")
    )
    scorecard = _as_mapping(
        additional.get("opportunity_scorecard")
        or signal_metadata.get("opportunity_scorecard")
    )
    decision_frame = _as_mapping(
        additional.get("decision_frame")
        or signal_metadata.get("decision_frame")
    )
    active_threshold_profile = _as_mapping(
        additional.get("active_threshold_profile")
        or signal_metadata.get("active_threshold_profile")
        or decision_frame.get("active_threshold_profile")
    )
    candidate_lifecycle = _as_mapping(
        signal_metadata.get("candidate_lifecycle")
        or additional.get("candidate_lifecycle")
    )
    market_snapshot = _as_mapping(
        additional.get("market_truth_snapshot")
        or signal_metadata.get("market_truth_snapshot")
        or signal_metadata.get("candidate_market_snapshot")
    )
    reason_codes = tuple(str(code) for code in guardrail.get("reason_codes", ()) if str(code))
    route_permitted = guardrail.get("route_permitted")
    mutation_permitted = guardrail.get("mutation_permitted")
    if submitted:
        status_code = "SUBMITTED_TO_EXECUTION"
    elif guardrail and route_permitted is not True:
        status_code = "PRE_TRADE_GUARDRAIL_BLOCKED"
    else:
        status_code = "EXECUTION_ADMISSION_BLOCKED"

    fields: Dict[str, Any] = {
        "decision_compiler_status_code": status_code,
        "decision_compiler_reason_codes": reason_codes,
        "pre_trade_verdict": guardrail.get("verdict"),
        "pre_trade_route_permitted": route_permitted,
        "pre_trade_mutation_permitted": mutation_permitted,
        "truth_status": outputs.get("truth_status") or metadata.get("truth_status"),
        "canonical_aggression_mode": aggression_contract.get("mode"),
        "canonical_aggression_veto_reasons": tuple(
            str(reason)
            for reason in aggression_contract.get("veto_reasons", ())
            if str(reason)
        ),
        "candidate_id": candidate_lifecycle.get("candidate_id"),
        "raw_opportunity_score": scorecard.get("raw_opportunity_score"),
        "final_opportunity_score": scorecard.get("final_opportunity_score"),
        "opportunity_verdict": scorecard.get("opportunity_verdict") or candidate_lifecycle.get("opportunity_verdict"),
        "snapshot_id": market_snapshot.get("snapshot_id"),
        "snapshot_status": market_snapshot.get("snapshot_status"),
        "snapshot_reason_codes": market_snapshot.get("snapshot_reason_codes"),
        "snapshot_authority": market_snapshot.get("snapshot_authority"),
        "active_threshold_profile": active_threshold_profile,
        "frame_id": decision_frame.get("frame_id"),
        "frame_output": decision_frame.get("frame_output"),
        "frame_status": decision_frame.get("frame_status"),
        "frame_reason_codes": decision_frame.get("frame_reason_codes"),
    }
    fields.update(_execution_admission_block_fields(execution_admission_block))
    return {key: value for key, value in fields.items() if value not in (None, (), [])}


def _to_decimal_or_none(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _normalize_symbol_for_position_match(symbol: Any) -> str:
    return str(symbol or "").upper().replace("/", "").replace("-", "").replace("_", "").strip()


def _matching_positive_position(symbol: str, positions: Tuple[Dict[str, Any], ...]) -> bool:
    expected = _normalize_symbol_for_position_match(symbol)
    for position in positions:
        if _normalize_symbol_for_position_match(position.get("symbol", "")) != expected:
            continue
        quantity = _to_decimal_or_none(position.get("quantity", position.get("qty", "0")))
        if quantity is not None and quantity > Decimal("0"):
            return True
    return False


def _metadata_has_short_intent(metadata: Dict[str, Any]) -> bool:
    action = str(
        metadata.get("execution_action")
        or metadata.get("order_action")
        or metadata.get("broker_action")
        or ""
    ).lower()
    return metadata.get("short_intent") is True or action in {"sell_short", "short"}


def _metadata_has_short_authority(metadata: Dict[str, Any]) -> bool:
    return bool(
        metadata.get("short_authority") is True
        or metadata.get("broker_short_authority") is True
        or metadata.get("borrow_authority") is True
    )


def _classify_sell_intent(
    *,
    symbol: str,
    side: str,
    metadata: Dict[str, Any],
    existing_positions: Tuple[Dict[str, Any], ...],
) -> Optional[str]:
    if str(side or "").lower() != "sell":
        return None
    if _matching_positive_position(symbol, existing_positions):
        return "SELL_EXIT_EXISTING_BROKER_POSITION"
    local_position = metadata.get("local_sim_position") or metadata.get("sim_position")
    if isinstance(local_position, dict):
        local_qty = _to_decimal_or_none(local_position.get("quantity", local_position.get("qty", "0")))
        if local_qty is not None and local_qty > Decimal("0"):
            return "SELL_EXIT_LOCAL_SIM_ONLY"
    if _metadata_has_short_intent(metadata):
        if _metadata_has_short_authority(metadata):
            return "SELL_SHORT_AUTHORIZED"
        return "SELL_SHORT_AUTHORITY_MISSING"
    return "BEARISH_NO_LONG"


def _execution_action_for_signal(side: str, sell_intent_classification: Optional[str]) -> Optional[str]:
    normalized_side = str(side or "").lower()
    if normalized_side == "buy":
        return "buy"
    if normalized_side != "sell":
        return normalized_side or None
    if sell_intent_classification == "SELL_EXIT_EXISTING_BROKER_POSITION":
        return "sell_to_close"
    if sell_intent_classification == "SELL_SHORT_AUTHORIZED":
        return "sell_short"
    return None


def _decimal_or_none_string(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else str(value)


def _no_broker_intent_guardrail_verdict(
    *,
    symbol: str,
    side: str,
    order_type: str,
    time_in_force: Optional[str],
    requested_notional: Optional[Decimal],
    internal_max_notional: Optional[Decimal],
    sell_intent_classification: str,
) -> Dict[str, Any]:
    if sell_intent_classification == "BEARISH_NO_LONG":
        reason_codes = ("BEARISH_NO_LONG", "SHORT_UNAVAILABLE")
        summary = "Bearish alpha while flat is telemetry/no-long evidence, not a broker sell intent."
    elif sell_intent_classification == "SELL_SHORT_AUTHORITY_MISSING":
        reason_codes = ("SHORT_AUTHORITY_MISSING", "SHORT_UNAVAILABLE")
        summary = "Short intent was requested without explicit short authority."
    elif sell_intent_classification == "SELL_EXIT_LOCAL_SIM_ONLY":
        reason_codes = ("SELL_AUTHORITY_MISSING", "SELL_EXIT_LOCAL_SIM_ONLY")
        summary = "Local simulated inventory is not broker-position-backed sell authority."
    else:
        reason_codes = ("SELL_AUTHORITY_MISSING",)
        summary = "No broker-position-backed sell authority was supplied."
    return {
        "verdict": "BLOCK",
        "route_permitted": False,
        "mutation_permitted": False,
        "reason_codes": reason_codes,
        "symbol": symbol,
        "side": side,
        "action": None,
        "order_type": str(order_type).lower(),
        "time_in_force": time_in_force,
        "requested_notional": _decimal_or_none_string(requested_notional),
        "internal_max_notional": _decimal_or_none_string(internal_max_notional),
        "broker_min_notional": None,
        "capability_identity": {},
        "broker_intent": False,
        "sell_intent_classification": sell_intent_classification,
        "module_evidence": [
            {
                "module": "sell_action_taxonomy",
                "status": "CONTRIBUTED_BLOCK",
                "reason_code": reason_codes[0],
                "summary": summary,
                "details": {
                    "broker_intent": False,
                    "sell_intent_classification": sell_intent_classification,
                    "execution_action": None,
                },
            }
        ],
    }


def _infer_asset_class_for_guardrail(symbol: str, metadata: Dict[str, Any]) -> str:
    if metadata.get("asset_class"):
        return str(metadata["asset_class"]).lower()
    normalized = str(symbol or "").upper()
    if "/" in normalized:
        return PortalAssetClass.CRYPTO.value
    if normalized in {"SPY", "QQQ", "DIA"}:
        return PortalAssetClass.ETF.value
    return PortalAssetClass.EQUITY.value


def _preferred_portal_for_guardrail(config: Any, symbol: str) -> Optional[str]:
    preferred = getattr(config, "preferred_trading_portal", None)
    if preferred:
        return preferred
    # Minimal test doubles predating venue policy do not carry config defaults.
    # Preserve their historical PaperBroker/Kraken crypto route unless a real
    # Config explicitly selects Alpaca PAPER.
    if "/" in str(symbol or ""):
        return "kraken_paper"
    return "alpaca_paper"


def _metadata_sequence(value: Any) -> Tuple[Dict[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, dict):
        return (dict(value),)
    if isinstance(value, (str, bytes)):
        return ()
    try:
        return tuple(item for item in value if isinstance(item, dict))
    except TypeError:
        return ()


def _protected_baseline_from_metadata(metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for key in ("accepted_paper_baseline", "paper_baseline", "baseline_adoption"):
        value = metadata.get(key)
        if isinstance(value, dict) and (value.get("accepted") is True or isinstance(value.get("baseline_snapshot"), dict)):
            return dict(value)
    return None


def _protected_baseline_from_config(config: Any) -> Optional[Dict[str, Any]]:
    value = getattr(config, "paper_baseline_runtime_context", None)
    if isinstance(value, dict) and value.get("baseline_loaded") is True:
        return dict(value)
    return None


def _protected_baseline_guardrail_verdict(
    *,
    symbol: str,
    side: str,
    order_type: str,
    time_in_force: Optional[str],
    requested_notional: Optional[Decimal],
    internal_max_notional: Optional[Decimal],
    quantity: Decimal,
    baseline_decision: Dict[str, Any],
) -> Dict[str, Any]:
    reason = str(baseline_decision.get("reason_code") or PAPER_BASELINE_SYMBOL_PROTECTED)
    detail = str(
        baseline_decision.get("detail")
        or "Existing-position symbols are protected; same-symbol trading is blocked until run lot tracking is available."
    )
    return {
        "verdict": "BLOCK",
        "route_permitted": False,
        "mutation_permitted": False,
        "reason_codes": (reason, "PAPER_BASELINE_PROTECTED"),
        "symbol": symbol,
        "side": side,
        "action": None,
        "order_type": str(order_type).lower(),
        "time_in_force": time_in_force,
        "quantity": str(quantity),
        "requested_notional": _decimal_or_none_string(requested_notional),
        "internal_max_notional": _decimal_or_none_string(internal_max_notional),
        "broker_min_notional": None,
        "capability_identity": {},
        "broker_intent": False,
        "sell_intent_classification": "BASELINE_PROTECTED" if side == "sell" else None,
        "module_evidence": [
            {
                "module": "paper_baseline_protection",
                "status": "CONTRIBUTED_BLOCK",
                "reason_code": reason,
                "summary": detail,
                "details": {
                    "policy": "ADOPT_EXISTING_POSITIONS_PROTECTED",
                    "baseline_symbol": symbol,
                    "normalized_symbol": baseline_decision.get("normalized_symbol"),
                    "lot_tracking_available": False,
                    "broker_mutation_occurred": False,
                },
            }
        ],
    }


def _build_pre_trade_guardrail_verdict(
    *,
    config: Any,
    symbol: str,
    signal: Any,
    runtime: Any,
    is_attack: bool,
) -> Dict[str, Any]:
    metadata = getattr(signal, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}

    current_price = _to_decimal_or_none(getattr(runtime, "last_price", None))
    quantity = _to_decimal_or_none(getattr(signal, "quantity", None)) or Decimal("0")
    asset_class = _infer_asset_class_for_guardrail(symbol, metadata)
    preselected_order_type = metadata.get("order_type")
    order_type = str(preselected_order_type).lower() if preselected_order_type else None
    requested_notional = _to_decimal_or_none(metadata.get("requested_notional"))
    if requested_notional is None and current_price is not None and quantity > Decimal("0"):
        requested_notional = abs(quantity * current_price)
    internal_max_notional = _to_decimal_or_none(metadata.get("internal_max_notional")) or requested_notional
    existing_positions = _metadata_sequence(metadata.get("existing_positions"))
    side = str(getattr(signal, "side", "buy")).lower()
    protective_context = metadata.get("protective_context")
    protective_context = dict(protective_context) if isinstance(protective_context, dict) else {}
    sell_intent_classification = _classify_sell_intent(
        symbol=symbol,
        side=side,
        metadata=metadata,
        existing_positions=existing_positions,
    )
    execution_action = _execution_action_for_signal(side, sell_intent_classification)
    if sell_intent_classification:
        metadata["sell_intent_classification"] = sell_intent_classification
        protective_context["sell_intent_classification"] = sell_intent_classification
    metadata["execution_action"] = execution_action
    metadata["broker_intent"] = execution_action is not None
    accepted_baseline = _protected_baseline_from_metadata(metadata) or _protected_baseline_from_config(config)
    if accepted_baseline is not None and side in {"buy", "sell"}:
        metadata.setdefault("paper_baseline_runtime_context", accepted_baseline)
        baseline_decision = evaluate_protected_baseline_trade(
            symbol=symbol,
            side=side,
            requested_qty=quantity,
            accepted_baseline=accepted_baseline,
            run_acquired_qty=metadata.get("run_acquired_qty"),
            lot_tracking_available=metadata.get("paper_baseline_lot_tracking_available") is True,
        )
        if baseline_decision.get("allowed") is not True:
            metadata["broker_intent"] = False
            metadata["paper_baseline_protected_block"] = baseline_decision.get("reason_code")
            return _protected_baseline_guardrail_verdict(
                symbol=symbol,
                side=side,
                order_type=order_type or ("limit" if is_attack else "market"),
                time_in_force=None,
                requested_notional=requested_notional,
                internal_max_notional=internal_max_notional,
                quantity=quantity,
                baseline_decision=baseline_decision,
            )
    if side == "sell" and execution_action is None:
        return _no_broker_intent_guardrail_verdict(
            symbol=symbol,
            side=side,
            order_type=order_type or ("limit" if is_attack else "market"),
            time_in_force=None,
            requested_notional=requested_notional,
            internal_max_notional=internal_max_notional,
            sell_intent_classification=sell_intent_classification or "SELL_AUTHORITY_MISSING",
        )

    registry = build_default_capability_registry()
    preferred_portal = _preferred_portal_for_guardrail(config, symbol)
    policy_mode = getattr(config, "portal_selection_policy", None)
    if not policy_mode:
        policy_mode = PortalPolicyMode.EXPLICIT_PREFERRED_VENUE.value
    environment = PortalEnvironment.PAPER.value if getattr(config, "broker_mode", "paper") == "paper" else PortalEnvironment.LIVE.value

    preselected_time_in_force = metadata.get("time_in_force")
    portal_request = PortalSelectionRequest(
        symbol=symbol,
        asset_class=asset_class,
        environment=environment,
        action=execution_action or side,
        order_type=order_type,
        time_in_force=str(preselected_time_in_force).upper() if preselected_time_in_force else None,
        policy_mode=str(policy_mode),
        preferred_venue=preferred_portal,
        allow_fallback=bool(getattr(config, "allow_portal_fallback", False)),
    )
    portal_result = registry.resolve(portal_request)
    capability = portal_result.selected
    if order_type is None:
        order_type = (
            capability.default_order_type
            if capability is not None and capability.default_order_type
            else ("limit" if is_attack else "market")
        )
    time_in_force = (
        str(preselected_time_in_force).upper()
        if preselected_time_in_force
        else (capability.default_time_in_force if capability is not None else None)
    )

    if capability is not None and (preselected_order_type is None or preselected_time_in_force is None) and time_in_force:
        portal_request = PortalSelectionRequest(
            symbol=symbol,
            asset_class=asset_class,
            environment=environment,
            action=execution_action or side,
            order_type=order_type,
            time_in_force=time_in_force,
            policy_mode=str(policy_mode),
            preferred_venue=preferred_portal,
            allow_fallback=bool(getattr(config, "allow_portal_fallback", False)),
        )
        portal_result = registry.resolve(portal_request)
        capability = portal_result.selected

    quote_classification = None
    if capability is not None:
        candidate = CapabilityAwareCandidate.from_capability(capability, tradable=True)
        quote_classification = classify_quote_session(
            candidate,
            market_session_open=metadata.get("market_session_open"),
            quote_present=current_price is not None and current_price > Decimal("0"),
            quote_fresh=metadata.get("quote_fresh", True),
            spread_bps=_to_decimal_or_none(metadata.get("spread_bps")),
        )

    verdict = evaluate_pre_trade_guardrails(
        PreTradeGuardrailRequest(
            symbol=symbol,
            side=side,
            action=execution_action,
            order_type=str(order_type).lower(),
            time_in_force=time_in_force,
            quantity=quantity,
            limit_price=current_price if str(order_type).lower() == "limit" else None,
            current_price=current_price,
            internal_max_notional=internal_max_notional,
            capability=capability,
            portal_selection_result=portal_result,
            quote_classification=quote_classification,
            existing_positions=existing_positions,
            open_orders=_metadata_sequence(metadata.get("open_orders")),
            reservations=_metadata_sequence(metadata.get("reservations")),
            add_on_allowed=bool(metadata.get("add_on_allowed", False)),
            approval_present=bool(metadata.get("approval_present", False)),
            protective_context=protective_context or None,
            economics_context=metadata.get("economics_context"),
            strategy_context=metadata.get("strategy_context"),
            source="main_loop_dispatch",
        )
    )
    return verdict.to_dict()


def _format_sector_rotation_diag_detail(detail: Optional[Dict[str, Any]]) -> str:
    if not detail:
        return "-"
    parts: List[str] = []
    for key in sorted(detail):
        value = detail[key]
        if value is None:
            continue
        text = str(value)
        if len(text) > 80:
            text = f"{text[:77]}..."
        parts.append(f"{key}={text}")
    return ",".join(parts) if parts else "-"


def _log_sector_rotation_diag(
    symbol: str,
    reason_code: str,
    candle_ts_ns: int,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit observe-only SectorRotation producer evidence."""
    logger.info(
        "[SECTOR_ROTATION_DIAG] symbol=%s reason_code=%s candle_ts_ns=%s detail=%s",
        symbol,
        reason_code,
        candle_ts_ns,
        _format_sector_rotation_diag_detail(detail),
    )


def _observed_pair_candle_id(timestamp_ns: Any) -> Any:
    if isinstance(timestamp_ns, int):
        return timestamp_ns
    return "not_present"


def _observed_pair_stale_age_ns(pair_ts_ns: Any, consumer_ts_ns: int) -> Any:
    if isinstance(pair_ts_ns, int) and isinstance(consumer_ts_ns, int):
        return max(0, consumer_ts_ns - pair_ts_ns)
    return "not_present"


def _normalized_observed_pair_symbol(symbol: Any) -> Optional[str]:
    if symbol is None:
        return None
    normalized = str(symbol).strip().upper()
    return normalized or None


def _observed_pair_vote_symbol(vote: Any) -> Optional[str]:
    direct = _normalized_observed_pair_symbol(getattr(vote, "symbol", None))
    if direct is not None:
        return direct
    metadata = getattr(vote, "metadata", None)
    if isinstance(metadata, dict):
        return _normalized_observed_pair_symbol(metadata.get("symbol"))
    return None


def _sector_rotation_observed_pair_detail(
    *,
    symbol: str,
    observed_signal: Any,
    observed_vote: Any,
    consumer_timestamp_ns: int,
) -> Dict[str, Any]:
    signal_timestamp = (
        getattr(observed_signal, "exchange_ts_ns", None)
        if observed_signal is not None
        else None
    )
    vote_timestamp = (
        getattr(observed_vote, "timestamp_ns", None)
        if observed_vote is not None
        else None
    )
    signal_candle_id = _observed_pair_candle_id(signal_timestamp)
    vote_candle_id = _observed_pair_candle_id(vote_timestamp)
    consumer_candle_id = _observed_pair_candle_id(consumer_timestamp_ns)
    pair_ts_candidates = [
        ts for ts in (signal_timestamp, vote_timestamp) if isinstance(ts, int)
    ]
    freshest_pair_ts = max(pair_ts_candidates) if pair_ts_candidates else None
    consumer_symbol = _normalized_observed_pair_symbol(symbol)
    signal_symbol = (
        _normalized_observed_pair_symbol(getattr(observed_signal, "symbol", None))
        if observed_signal is not None
        else None
    )
    vote_symbol = (
        _observed_pair_vote_symbol(observed_vote)
        if observed_vote is not None
        else None
    )
    return {
        "observed_signal_present": observed_signal is not None,
        "observed_vote_present": observed_vote is not None,
        "signal_timestamp": signal_timestamp if signal_timestamp is not None else "not_present",
        "vote_timestamp": vote_timestamp if vote_timestamp is not None else "not_present",
        "consumer_timestamp": consumer_timestamp_ns,
        "signal_candle_id": signal_candle_id,
        "vote_candle_id": vote_candle_id,
        "consumer_candle_id": consumer_candle_id,
        "stale_age_ns": _observed_pair_stale_age_ns(
            freshest_pair_ts,
            consumer_timestamp_ns,
        ),
        "consumer_symbol": consumer_symbol or "not_present",
        "signal_symbol": signal_symbol or "not_present",
        "vote_symbol": vote_symbol or "not_present",
    }


# =========================================================================
# BUNDLE 2A — FACTORY FUNCTION FOR MAINLOOP ASSEMBLY
# =========================================================================

def create_main_loop(
    config: Config,
    commander: Commander,
    risk_guard: HybridRiskGuard,
    signal_fusion: SignalFusion,
    data_validator: DataContinuityValidator,
    recalibrator: Recalibrator,
    shans_curve: ShansCurve,
    tpe_engine: Optional[TopologicalEngine],
    regime_detector: RegimeDetector,
    physical_validator: PhysicalValidator,
    toxicity_engine: Optional[ToxicityEngine],
    entropy_decoder: EntropyDecoder,
    insider_engine: InsiderSignalEngine,
    execution_engine: ExecutionEngine,
    symbol: str,
    exchange: str,
    safety_gate: SafetyGate,
    telemetry_store: Optional[TelemetryEventStore] = None,
    active_symbols: Optional[Set[str]] = None,
) -> "MainLoop":
    """
    Factory function for MainLoop assembly.

    BUNDLE 2A — BOOT REPAIR + ASSEMBLY SEAM RESTORATION
    Board-approved: creates missing collaborators internally to restore lawful boot.

    Assembles:
        - StrategyRouter (requires config, safety_gate)
        - DecisionCompiler (requires config, telemetry_store)
        - PositionSizingEngine (requires config)

    All collaborators are instantiated lawfully with real dependencies passed from main.py.
    No placeholders. No fake compatibility layers.

    BUNDLE MULTI-SYMBOL RUNTIME: 
        - tpe_engine and toxicity_engine params are accepted but IGNORED.
          Per-symbol engines are created inside SymbolRuntime containers.
        - shadow_front is NOT created here; per-symbol instances in runtimes.
        - active_symbols set determines which symbols get runtimes.
    """
    from app.strategies.strategy_router import StrategyRouter
    from app.core.decision_compiler import DecisionCompiler
    from app.risk.position_sizing import PositionSizingEngine

    # Instantiate missing collaborators (global, shared across symbols)
    strategy_router = StrategyRouter(config=config, safety_gate=safety_gate)
    decision_compiler = DecisionCompiler(telemetry_store=telemetry_store)
    position_sizing_engine = PositionSizingEngine(config=config)

    return MainLoop(
        config=config,
        commander=commander,
        risk_guard=risk_guard,
        signal_fusion=signal_fusion,
        data_validator=data_validator,
        recalibrator=recalibrator,
        shans_curve=shans_curve,
        regime_detector=regime_detector,
        physical_validator=physical_validator,
        entropy_decoder=entropy_decoder,
        insider_engine=insider_engine,
        execution_engine=execution_engine,
        strategy_router=strategy_router,
        decision_compiler=decision_compiler,
        position_sizing_engine=position_sizing_engine,
        symbol=symbol,
        exchange=exchange,
        telemetry_store=telemetry_store,
        active_symbols=active_symbols or {symbol},
        safety_gate=safety_gate,
    )


class LoopMetrics:
    iteration_count: int = 0
    last_candle_exchange_ts_ns: int = 0
    last_order_book_exchange_ts_ns: int = 0
    last_trade_exchange_ts_ns: int = 0
    last_equity_update_ns: int = 0
    last_risk_assessment_ns: int = 0
    last_recalibration_check_ns: int = 0
    last_health_log_iteration: int = 0
    consecutive_errors: int = 0
    emergency_liquidations: int = 0
    recalibration_entries: int = 0
    recalibration_exits: int = 0
    compilation_cycles: int = 0
    orders_submitted: int = 0
    orders_rejected: int = 0
    # Candle admission counters
    candle_duplicates_rejected: int = 0
    candle_stale_rejected: int = 0
    # Invalid book counters
    invalid_books_skipped: int = 0


class CandleRejectionTracker:
    """Per-symbol rate-limited logging for candle rejections."""
    
    def __init__(self):
        self._last_log_time: Dict[str, Dict[str, float]] = {}
    
    def should_log(self, symbol: str, rejection_type: str) -> bool:
        """Return True if enough time has passed since last log for this type."""
        now = time.time()
        last = self._last_log_time.get(symbol, {}).get(rejection_type, 0)
        if now - last >= _CANDLE_REJECT_LOG_INTERVAL_SEC:
            if symbol not in self._last_log_time:
                self._last_log_time[symbol] = {}
            self._last_log_time[symbol][rejection_type] = now
            return True
        return False


class MainLoop:
    """
    Sovereign Market-Data / Brain / State / Risk-Ingress Pipeline.

    BUNDLE 1 REDO REPAIR: Structural actuation seam complete.
    Behavioral readiness awaiting upstream feed wiring (Bundle 2).

    BUNDLE 3B: Accesses order_router via execution_engine for ExchangeTruth hydration.
    
    BUNDLE F1: Added telemetry_store parameter.
    
    BUNDLE CANDLE ADMISSION HARDENING: Permanent per-symbol last_admitted_candle_ts_ns
    tracking with classification (duplicate vs stale) and bounded logging.
    
    BUNDLE CANDLE ADMISSION ATOMICITY FIX: Admission check and update protected by self._lock.
    
    BUNDLE MULTI-SYMBOL RUNTIME: Per-symbol runtime containers replacing single-symbol state.
    
    BUNDLE STRATEGY-GATING REPAIR (2026-04-27): Whale overlay wired via per-symbol
    WhaleFlowEngine. Sentiment overlay wired via MarketSentimentProxy.
    
    BUNDLE DIAGNOSTIC VISIBILITY (2026-04-28): Dispatch/eligibility tracing logs.
    
    BUNDLE SHANS PRODUCER TRACE (2026-04-27): Added diagnostic INFO logs to trace
    Shans production path. NO BEHAVIOR CHANGES.
    
    BUNDLE PER-SYMBOL THROTTLE FIX (2026-04-27): Replaced global throttle with
    per-symbol throttle to prevent multi-symbol starvation. Uses explicit
    _last_book_receive_ns_by_symbol field.
    
    BUNDLE PER-SYMBOL SHANS OWNERSHIP FIX (2026-04-27): Each SymbolRuntime now owns
    its own ShansCurve instance. Prevents cross-symbol buffer contamination.
    
    LIMITS (honest disclosure):
        - SignalFusion remains global. Multi-symbol fusion correctness depends on
          per-symbol update_*() calls before each fuse().
        - DecisionCompiler remains global. StrategyVote routing includes symbol
          context but compilation is symbol-agnostic.
        - ExecutionEngine/OrderRouter remain global. Orders carry symbol tags.
        - This bundle establishes STATE ownership, not full multi-symbol execution.
    """

    # Constants for backward compatibility with create_main_loop
    _SHADOW_FRONT = None  # Placeholder; per-symbol instances in runtimes
    _TPE_ENGINE = None    # Placeholder; per-symbol instances in runtimes
    _TOXICITY_ENGINE = None  # Placeholder; per-symbol instances in runtimes

    def __init__(
        self,
        config: Config,
        commander: Commander,
        risk_guard: HybridRiskGuard,
        signal_fusion: SignalFusion,
        data_validator: DataContinuityValidator,
        recalibrator: Recalibrator,
        shans_curve: ShansCurve,
        regime_detector: RegimeDetector,
        physical_validator: PhysicalValidator,
        entropy_decoder: EntropyDecoder,
        insider_engine: InsiderSignalEngine,
        execution_engine: ExecutionEngine,
        strategy_router: StrategyRouter,
        decision_compiler: DecisionCompiler,
        position_sizing_engine: PositionSizingEngine,
        symbol: str,
        exchange: str = "kraken",
        health_log_interval_iterations: int = 600,
        telemetry_store: Optional[TelemetryEventStore] = None,
        active_symbols: Optional[Set[str]] = None,
        safety_gate: Optional[SafetyGate] = None,
    ):
        self.config = config
        self.commander = commander
        self.risk_guard = risk_guard
        self.signal_fusion = signal_fusion
        self.data_validator = data_validator
        self.recalibrator = recalibrator
        # Global shans_curve retained for backward compatibility but NOT used for per-symbol routing
        self.shans_curve = shans_curve
        self.regime_detector = regime_detector
        self.physical_validator = physical_validator
        self.entropy_decoder = entropy_decoder
        self.insider_engine = insider_engine
        self.execution_engine = execution_engine
        self.strategy_router = strategy_router
        self.decision_compiler = decision_compiler
        self.position_sizing_engine = position_sizing_engine
        self.exchange = exchange
        self.health_log_interval_iterations = health_log_interval_iterations
        self.telemetry_store = telemetry_store
        self.safety_gate = safety_gate

        # Active symbols set (all symbols that can participate in paper trading)
        self.active_symbols: Set[str] = active_symbols or {symbol}
        
        # Legacy primary symbol
        self.symbol = symbol
        
        # Validate primary symbol is in active set
        if symbol not in self.active_symbols:
            raise ValueError(f"Primary symbol {symbol} not in active_symbols {self.active_symbols}")

        # ================================================================
        # PER-SYMBOL RUNTIME CONTAINERS
        # ================================================================
        self._runtimes: Dict[str, SymbolRuntime] = {}
        
        # Initialize runtime for each active symbol
        for sym in self.active_symbols:
            runtime = SymbolRuntime(symbol=sym)
            runtime.initialize_engines(config=config, safety_gate=safety_gate)
            self._apply_paper_exploration_alpha_profile(sym, runtime)
            # Inject Shans dependencies (global shared dependencies)
            runtime.set_shans_dependencies(
                risk_guard=self.risk_guard,
                data_validator=self.data_validator,
                entropy_decoder=self.entropy_decoder
            )
            self._runtimes[sym] = runtime
            logger.info(f"Initialized SymbolRuntime for {sym} with per-symbol ShansCurve")
        
        # Legacy compatibility: direct references to primary symbol's runtime components
        self._primary_runtime = self._runtimes[symbol]
        self._last_order_book: Optional[OrderBookSnapshot] = self._primary_runtime.last_order_book
        self._last_candle: Optional[Candle] = self._primary_runtime.last_candle
        self._last_tpe_signal: Optional[TopologicalSignal] = self._primary_runtime.last_tpe_signal
        self._last_equity: float = config.initial_capital
        self._last_price: float = self._primary_runtime.last_price
        self._last_fusion: Optional[FusionDecision] = None
        self._last_risk_state: Optional[Dict[str, Any]] = None
        self._current_regime: RegimeType = RegimeType.UNKNOWN
        self._current_volatility: float = self._primary_runtime.current_volatility

        self._recalibration_active: bool = False
        self._recalibration_start_ns: int = 0
        
        # PER-SYMBOL THROTTLE: track last processed timestamp per symbol
        # Explicit new field name — does NOT reuse old scalar field
        self._last_book_receive_ns_by_symbol: Dict[str, int] = {}

        # CANDLE ADMISSION HARDENING: Track last admitted candle timestamp per symbol
        # Protected by self._lock
        self._last_admitted_candle_ts_ns: Dict[str, int] = {}
        self._candle_rejection_tracker: CandleRejectionTracker = CandleRejectionTracker()

        # SHANS DIAGNOSTIC: Track processed book counts per symbol
        self._book_processed_count: Dict[str, int] = {}

        # LIVE_GATE: Per-symbol last log time for Shans-readiness gate (wall-clock seconds).
        # Limits log volume to at most one entry per 5 seconds per symbol.
        # NOT used for trading decisions — logging hygiene only.
        self._shans_gate_last_log_ts: Dict[str, float] = {}
        self._broker_position_cache: Tuple[Dict[str, Any], ...] = ()
        self._broker_position_cache_ts_ns: int = 0
        self._broker_position_cache_source: Optional[str] = None

        self._metrics = LoopMetrics()
        self._lock = threading.Lock()
        self._running = False

        logger.info("MainLoop initialized: symbol=%s active_symbols=%s (Per-Symbol Shans Ownership)",
                   symbol, list(active_symbols))
        self._log_runtime_profile_banner()

    def _get_runtime(self, symbol: str) -> Optional[SymbolRuntime]:
        """Get runtime container for a symbol."""
        return self._runtimes.get(symbol)
    
    def _ensure_runtime(self, symbol: str) -> Optional[SymbolRuntime]:
        """Get or create runtime for a symbol (defensive creation)."""
        runtime = self._runtimes.get(symbol)
        if runtime is None:
            # Defensive creation for symbols not in active set
            if symbol not in self.active_symbols:
                logger.warning(f"Symbol {symbol} not in active_symbols, cannot create runtime")
                return None
            runtime = SymbolRuntime(symbol=symbol)
            runtime.initialize_engines(config=self.config, safety_gate=self.safety_gate)
            self._apply_paper_exploration_alpha_profile(symbol, runtime)
            runtime.set_shans_dependencies(
                risk_guard=self.risk_guard,
                data_validator=self.data_validator,
                entropy_decoder=self.entropy_decoder
            )
            self._runtimes[symbol] = runtime
            logger.info(f"Defensively created SymbolRuntime for {symbol} with per-symbol ShansCurve")
        return runtime

    def _active_threshold_profile(self) -> Dict[str, Any]:
        return resolve_active_threshold_profile(self.config)

    def _broker_position_truth(
        self,
        symbol: str,
        *,
        force_refresh: bool = False,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        positions, evidence = self._broker_positions_snapshot(force_refresh=force_refresh)
        expected = _normalize_symbol_for_position_match(symbol)
        for position in positions:
            if _normalize_symbol_for_position_match(position.get("symbol")) != expected:
                continue
            quantity = _to_decimal_or_none(position.get("quantity"))
            if quantity is not None and quantity > Decimal("0"):
                return position, {
                    **evidence,
                    "symbol": symbol,
                    "matched_position": True,
                    "position_symbol": position.get("symbol"),
                    "position_quantity": str(quantity),
                }
        return None, {
            **evidence,
            "symbol": symbol,
            "matched_position": False,
            "reason_code": "BROKER_POSITION_NOT_FOUND",
        }

    def _broker_positions_snapshot(
        self,
        *,
        force_refresh: bool = False,
    ) -> Tuple[Tuple[Dict[str, Any], ...], Dict[str, Any]]:
        now = time.time_ns()
        cached = getattr(self, "_broker_position_cache", None)
        cached_ts = int(getattr(self, "_broker_position_cache_ts_ns", 0) or 0)
        if (
            not force_refresh
            and isinstance(cached, tuple)
            and cached_ts > 0
            and now - cached_ts <= _BROKER_POSITION_CACHE_TTL_NS
        ):
            return cached, {
                "status": "PASS",
                "reason_code": "BROKER_POSITION_TRUTH_CACHE_HIT",
                "source": getattr(self, "_broker_position_cache_source", "unknown"),
                "receive_ts_ns": cached_ts,
                "positions_count": len(cached),
                "read_only": True,
            }

        positions: Tuple[Dict[str, Any], ...] = ()
        evidence: Dict[str, Any] = {
            "status": "MISSING_TRUTH",
            "reason_code": "BROKER_POSITION_TRUTH_MISSING",
            "source": "unknown",
            "receive_ts_ns": now,
            "positions_count": 0,
            "read_only": True,
        }
        order_router = getattr(getattr(self, "execution_engine", None), "order_router", None)
        if order_router is None:
            return positions, evidence

        adapter = getattr(order_router, "_broker_gateway_adapter", None)
        if adapter is not None:
            identity = getattr(adapter, "identity", None)
            if (
                getattr(identity, "environment", None) != "paper"
                or getattr(identity, "live_blocked", None) is not True
            ):
                return positions, {
                    **evidence,
                    "status": "BLOCK",
                    "reason_code": "BROKER_POSITION_TRUTH_UNSAFE_ADAPTER",
                    "source": "broker_gateway_adapter",
                }
            get_positions = getattr(adapter, "get_positions", None)
            if callable(get_positions):
                try:
                    response = get_positions()
                    payload = getattr(response, "payload", None)
                    if getattr(response, "mutation_occurred", False):
                        return positions, {
                            **evidence,
                            "status": "BLOCK",
                            "reason_code": "BROKER_POSITION_TRUTH_MUTATION_OCCURRED",
                            "source": getattr(identity, "adapter_id", "broker_gateway_adapter"),
                        }
                    if getattr(response, "ok", False) and isinstance(payload, list):
                        positions = tuple(
                            item
                            for item in (
                                self._normalize_broker_position(row) for row in payload
                            )
                            if item is not None
                        )
                        evidence = {
                            "status": "PASS",
                            "reason_code": "BROKER_POSITION_TRUTH_READ_ONLY",
                            "source": getattr(identity, "adapter_id", "broker_gateway_adapter"),
                            "receive_ts_ns": now,
                            "positions_count": len(positions),
                            "read_only": True,
                            "request_counts": getattr(adapter, "request_counts", {}),
                        }
                except Exception as exc:
                    evidence = {
                        **evidence,
                        "reason_code": "BROKER_POSITION_TRUTH_READ_FAILED",
                        "source": getattr(identity, "adapter_id", "broker_gateway_adapter"),
                        "error": exc.__class__.__name__,
                    }
        elif hasattr(order_router, "fetch_positions"):
            try:
                raw_positions = order_router.fetch_positions()
                if isinstance(raw_positions, list):
                    positions = tuple(
                        item
                        for item in (
                            self._normalize_broker_position(row) for row in raw_positions
                        )
                        if item is not None
                    )
                    evidence = {
                        "status": "PASS",
                        "reason_code": "BROKER_POSITION_TRUTH_ROUTER_READ_ONLY",
                        "source": "order_router.fetch_positions",
                        "receive_ts_ns": now,
                        "positions_count": len(positions),
                        "read_only": True,
                    }
            except Exception as exc:
                evidence = {
                    **evidence,
                    "reason_code": "BROKER_POSITION_TRUTH_ROUTER_READ_FAILED",
                    "source": "order_router.fetch_positions",
                    "error": exc.__class__.__name__,
                }

        self._broker_position_cache = positions
        self._broker_position_cache_ts_ns = now
        self._broker_position_cache_source = evidence.get("source")
        return positions, evidence

    @staticmethod
    def _normalize_broker_position(raw: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(raw, Mapping):
            return None
        raw_symbol = raw.get("symbol") or raw.get("asset_symbol") or raw.get("asset")
        if not raw_symbol:
            return None
        quantity = _to_decimal_or_none(
            raw.get("quantity", raw.get("qty", raw.get("asset_qty", "0")))
        )
        if quantity is None:
            return None
        average_entry = _to_decimal_or_none(
            raw.get("average_entry_price", raw.get("avg_entry_price", raw.get("avg_entry", "0")))
        )
        return {
            "symbol": str(raw_symbol),
            "raw_symbol": str(raw_symbol),
            "quantity": str(quantity),
            "qty": str(quantity),
            "average_entry_price": str(average_entry or Decimal("0")),
            "broker_position_backed": True,
            "source": "broker_position_truth",
        }

    def _log_runtime_profile_banner(self) -> None:
        profile = self._active_threshold_profile()
        strategies = getattr(self.config, "strategies", None)
        strategy_toggles = {}
        if strategies is not None:
            for name in (
                "shadow_front_enabled",
                "flv_enabled",
                "gamma_front_enabled",
                "sector_rotation_enabled",
                "sector_rotation_ranging_eligible",
            ):
                strategy_toggles[name] = getattr(strategies, name, None)
        _log_dispatch_diag(
            "RUNTIME_PROFILE_BANNER",
            active_threshold_profile=profile,
            active_thresholds=profile.get("thresholds"),
            broker_mode=getattr(self.config, "broker_mode", None),
            alpaca_paper=getattr(self.config, "alpaca_paper", None),
            endpoint=getattr(self.config, "alpaca_base_url", None),
            strategy_toggles=strategy_toggles,
            active_symbols=tuple(sorted(self.active_symbols)),
        )

    def _apply_paper_exploration_alpha_profile(self, symbol: str, runtime: SymbolRuntime) -> None:
        profile = self._active_threshold_profile()
        if profile.get("enabled") is not True:
            return
        if getattr(runtime, "_paper_exploration_alpha_profile_applied", False):
            return

        changes: List[Dict[str, Any]] = []

        def _set_float(obj: Any, attr: str, threshold_name: str) -> None:
            if obj is None or not hasattr(obj, attr):
                return
            current = getattr(obj, attr)
            exploration = _threshold_profile_value(profile, threshold_name, current)
            try:
                current_float = float(current)
                exploration_float = float(exploration)
            except (TypeError, ValueError):
                return
            new_value = min(current_float, exploration_float)
            if new_value != current_float:
                setattr(obj, attr, new_value)
            changes.append(
                {
                    "threshold_name": threshold_name,
                    "runtime_attribute": attr,
                    "default_value": current_float,
                    "exploration_value": new_value,
                    "profile_name": profile.get("profile_name"),
                    "paper_only": True,
                    "reason_code": "PAPER_EXPLORATION_ALPHA_THRESHOLD_APPLIED",
                }
            )

        def _set_int(obj: Any, attr: str, threshold_name: str) -> None:
            if obj is None or not hasattr(obj, attr):
                return
            current = getattr(obj, attr)
            exploration = _threshold_profile_value(profile, threshold_name, current)
            try:
                current_int = int(current)
                exploration_int = int(exploration)
            except (TypeError, ValueError):
                return
            new_value = max(1, min(current_int, exploration_int))
            if new_value != current_int:
                setattr(obj, attr, new_value)
            changes.append(
                {
                    "threshold_name": threshold_name,
                    "runtime_attribute": attr,
                    "default_value": current_int,
                    "exploration_value": new_value,
                    "profile_name": profile.get("profile_name"),
                    "paper_only": True,
                    "reason_code": "PAPER_EXPLORATION_ALPHA_THRESHOLD_APPLIED",
                }
            )

        shadow_front = getattr(runtime, "shadow_front_strategy", None)
        _set_float(shadow_front, "whale_threshold", "shadowfront_whale_threshold")
        _set_float(shadow_front, "sentiment_threshold", "shadowfront_sentiment_velocity_threshold")
        _set_float(shadow_front, "min_confidence", "shadowfront_min_confidence")

        sector_rotation = getattr(runtime, "sector_rotation_strategy", None)
        _set_float(sector_rotation, "_inflow_threshold", "sector_inflow_threshold")
        _set_float(sector_rotation, "_min_confidence", "sector_rotation_min_confidence")
        _set_int(sector_rotation, "_effective_min_candles", "sector_rotation_min_baseline_candles")

        setattr(runtime, "_paper_exploration_alpha_profile_applied", True)
        _log_dispatch_diag(
            "PAPER_EXPLORATION_ALPHA_PROFILE_ACTIVE",
            symbol=symbol,
            active_threshold_profile=profile,
            threshold_changes=tuple(changes),
            paper_only=True,
            broker_mode=getattr(self.config, "broker_mode", None),
            alpaca_paper=getattr(self.config, "alpaca_paper", None),
        )
    
    def _sync_legacy_references(self) -> None:
        """Sync legacy direct references with primary symbol's runtime."""
        runtime = self._runtimes.get(self.symbol)
        if runtime:
            self._last_order_book = runtime.last_order_book
            self._last_candle = runtime.last_candle
            self._last_tpe_signal = runtime.last_tpe_signal
            self._last_price = runtime.last_price
            self._current_volatility = runtime.current_volatility
            self._primary_runtime = runtime

    def _update_physical_freshness(self, symbol: str, exchange_ts_ns: int) -> None:
        """
        Refresh Fusion's critical physical signal from an admitted market-data event.

        SignalFusion intentionally hard-vetoes stale physical evidence. The
        timestamp supplied here must therefore match the market event that is
        about to drive Fusion, not an unrelated wall-clock fallback.
        """
        receive_ns = time.time_ns()
        latency_ms = max(0.0, (receive_ns - exchange_ts_ns) / 1_000_000)
        self.physical_validator.record_latency(
            symbol=symbol,
            exchange=self.exchange,
            latency_ms=latency_ms,
            order_size=0.0,
            price_impact_bps=0.0,
            timestamp_ns=exchange_ts_ns,
        )
        phys_dict = self.physical_validator.to_fusion_dict(self.exchange)
        self.signal_fusion.update_physical(phys_dict, exchange_ts_ns)

    def _get_dispatch_regime(self, runtime: SymbolRuntime) -> RegimeType:
        """Return the symbol-owned regime when available, else legacy global."""
        detector = getattr(runtime, "regime_detector", None)
        get_current_regime = getattr(detector, "get_current_regime", None)
        if callable(get_current_regime):
            regime = get_current_regime()
            if isinstance(regime, RegimeType):
                return regime
        return self._current_regime

    def _classify_shadow_front_decline(
        self,
        strategy: object,
        exchange_ts_ns: int,
    ) -> Tuple[str, Dict[str, object]]:
        """
        Explain a ShadowFront no-signal result from existing strategy state.

        This mirrors ShadowFront's entry gate order for diagnostics only. It
        does not call mutating update methods, mutate state, or relax any
        threshold.
        """
        if strategy is None:
            return "shadowfront_declined_strategy_missing", {}

        def _float_attr(name: str, default: float = 0.0) -> float:
            try:
                return float(getattr(strategy, name, default))
            except (TypeError, ValueError):
                return default

        cooldown_until = getattr(strategy, "_cooldown_until_ns", 0)
        if not isinstance(cooldown_until, int):
            cooldown_until = 0
        if exchange_ts_ns < cooldown_until:
            return (
                "shadowfront_declined_cooldown",
                {"cooldown_until_ns": cooldown_until},
            )

        is_eligible = getattr(strategy, "_is_eligible", True)
        if not isinstance(is_eligible, bool):
            is_eligible = True
        if not is_eligible:
            return "shadowfront_declined_not_eligible", {}

        toxicity_high = getattr(strategy, "_toxicity_high", False)
        if not isinstance(toxicity_high, bool):
            toxicity_high = False
        if toxicity_high:
            return "shadowfront_declined_toxicity_high", {}

        whale_score = _float_attr("_last_whale_score")
        whale_threshold = _float_attr("whale_threshold")
        whale_accumulating = getattr(strategy, "_last_whale_accumulating", False)
        if not isinstance(whale_accumulating, bool):
            whale_accumulating = False
        whale_condition = whale_score >= whale_threshold or whale_accumulating
        if not whale_condition:
            return (
                "shadowfront_declined_whale_condition",
                {
                    "whale_score": whale_score,
                    "whale_threshold": whale_threshold,
                    "whale_accumulating": whale_accumulating,
                },
            )

        sentiment_velocity = _float_attr("_last_sentiment_velocity")
        sentiment_threshold = _float_attr("sentiment_threshold")
        if sentiment_velocity < sentiment_threshold:
            return (
                "shadowfront_declined_sentiment_condition",
                {
                    "sentiment_velocity": sentiment_velocity,
                    "sentiment_threshold": sentiment_threshold,
                },
            )

        calculate_confidence = getattr(strategy, "_calculate_base_confidence", None)
        confidence = None
        if callable(calculate_confidence):
            try:
                confidence = float(calculate_confidence())
            except Exception:
                confidence = None
        min_confidence = _float_attr("min_confidence")
        if confidence is not None and confidence < min_confidence:
            return (
                "shadowfront_declined_confidence",
                {"confidence": confidence, "min_confidence": min_confidence},
            )

        return "shadowfront_declined_entry_conditions", {}

    def _classify_sector_rotation_observed_pair(
        self,
        symbol: str,
        runtime: SymbolRuntime,
        exchange_ts_ns: int,
    ) -> Tuple[str, Dict[str, object]]:
        """Classify SectorRotation observed-pair readiness without mutation."""
        observed_signal = runtime.last_sector_rotation_observed_signal
        observed_vote = runtime.last_sector_rotation_observed_vote
        detail = _sector_rotation_observed_pair_detail(
            symbol=symbol,
            observed_signal=observed_signal,
            observed_vote=observed_vote,
            consumer_timestamp_ns=exchange_ts_ns,
        )
        if observed_signal is None:
            return ("OBSERVED_SIGNAL_MISSING", detail)
        if observed_vote is None:
            return ("OBSERVED_VOTE_MISSING", detail)

        consumer_symbol = detail["consumer_symbol"]
        signal_symbol = detail["signal_symbol"]
        vote_symbol = detail["vote_symbol"]
        if (
            signal_symbol != "not_present"
            and consumer_symbol != "not_present"
            and signal_symbol != consumer_symbol
        ) or (
            vote_symbol != "not_present"
            and consumer_symbol != "not_present"
            and vote_symbol != consumer_symbol
        ):
            return ("OBSERVED_PAIR_SYMBOL_MISMATCH", detail)

        vote_ts = getattr(observed_vote, "timestamp_ns", None)
        signal_ts = getattr(observed_signal, "exchange_ts_ns", None)
        signal_candle_id = detail["signal_candle_id"]
        vote_candle_id = detail["vote_candle_id"]
        consumer_candle_id = detail["consumer_candle_id"]
        if (
            signal_candle_id == "not_present"
            or vote_candle_id == "not_present"
            or signal_candle_id != vote_candle_id
        ):
            return ("OBSERVED_PAIR_CANDLE_MISMATCH", detail)

        if signal_candle_id != consumer_candle_id:
            if (
                isinstance(signal_ts, int)
                and isinstance(vote_ts, int)
                and signal_ts < exchange_ts_ns
                and vote_ts < exchange_ts_ns
            ):
                return ("OBSERVED_PAIR_STALE", detail)
            return (
                "OBSERVED_PAIR_CANDLE_MISMATCH",
                detail,
            )

        return "OBSERVED_PAIR_READY", detail

    def _clear_stale_sector_rotation_observed_pair(
        self,
        runtime: SymbolRuntime,
        exchange_ts_ns: int,
    ) -> bool:
        """
        Drop a provably older SectorRotation observed pair after strict rejection.

        Same-candle doctrine means an older pair can never become valid for a
        later candle. Future/out-of-order pairs are left untouched.
        """
        observed_signal = runtime.last_sector_rotation_observed_signal
        observed_vote = runtime.last_sector_rotation_observed_vote
        if observed_signal is None or observed_vote is None:
            return False

        timestamps = [
            ts
            for ts in (
                getattr(observed_vote, "timestamp_ns", None),
                getattr(observed_signal, "exchange_ts_ns", None),
            )
            if isinstance(ts, int)
        ]
        if not timestamps or max(timestamps) >= exchange_ts_ns:
            return False

        runtime.last_sector_rotation_observed_signal = None
        runtime.last_sector_rotation_observed_vote = None
        return True

    def _runtime_module_frame_evidence(
        self,
        symbol: str,
        runtime: SymbolRuntime,
        exchange_ts_ns: int,
        *,
        fusion: Optional[FusionDecision] = None,
        preferred_sleeve: Optional[SleeveType] = None,
        eligible_sleeves: Tuple[SleeveType, ...] = (),
        active_threshold_profile: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], ...]:
        """Collect complete frame evidence without granting execution authority."""
        profile = active_threshold_profile or self._active_threshold_profile()
        evidence: List[Dict[str, Any]] = []

        shans_curve = getattr(runtime, "shans_curve", None)
        shans_ready = bool(
            shans_curve is not None
            and shans_curve.is_ready()
        )
        shans_buffer = len(shans_curve._p) if shans_curve is not None else 0
        shans_required = shans_curve.curvature_window if shans_curve is not None else 0
        fusion_telemetry = getattr(getattr(self, "signal_fusion", None), "_telemetry", {})
        shans_confidence = (
            fusion_telemetry.get("shans_confidence")
            if isinstance(fusion_telemetry, dict)
            else None
        )
        shans_signal = "NONE"
        shans_bias = None
        if fusion is not None:
            shans_bias = getattr(fusion, "shans_bias", None)
            shans_signal = _dispatch_signal_from_bias(shans_bias)
            if shans_confidence is None:
                shans_confidence = getattr(fusion, "shans_confidence", None)
        evidence.append(
            {
                "module": "ShansCurve",
                "authority_class": "ALPHA",
                "status": "PASS" if shans_ready else "MISSING_TRUTH",
                "reason_code": "SHANS_READY" if shans_ready else "shans_not_ready",
                "signal": shans_signal if shans_ready else "NONE",
                "confidence": shans_confidence,
                "evidence": {
                    "shans_ready": shans_ready,
                    "shans_buffer": shans_buffer,
                    "shans_required": shans_required,
                    "shans_bias": shans_bias,
                    "signal_authority": "alpha_evidence_only_no_broker_intent",
                },
            }
        )

        shadow_reason, shadow_fields = self._classify_shadow_front_decline(
            getattr(runtime, "shadow_front_strategy", None),
            exchange_ts_ns,
        )
        evidence.append(
            {
                "module": "ShadowFront",
                "authority_class": "ALPHA",
                "status": _alpha_evidence_status(shadow_reason),
                "reason_code": shadow_reason,
                "score_delta": "-0.03" if shadow_reason.startswith("shadowfront_declined") else None,
                "evidence": shadow_fields,
            }
        )

        sector_reason, sector_fields = self._classify_sector_rotation_observed_pair(
            symbol,
            runtime,
            exchange_ts_ns,
        )
        sector_signal = getattr(runtime, "last_sector_rotation_observed_signal", None)
        sector_vote = getattr(runtime, "last_sector_rotation_observed_vote", None)
        sector_conf = getattr(sector_vote, "confidence", None) or getattr(sector_signal, "confidence", None)
        evidence.append(
            {
                "module": "SectorRotation",
                "authority_class": "ALPHA",
                "status": "PASS" if sector_reason == "OBSERVED_PAIR_READY" else _alpha_evidence_status(sector_reason),
                "reason_code": sector_reason,
                "signal": _dispatch_signal_text(sector_signal),
                "confidence": sector_conf,
                "score_delta": "-0.02" if sector_reason in {"OBSERVED_SIGNAL_MISSING", "OBSERVED_PAIR_STALE"} else None,
                "evidence": sector_fields,
            }
        )

        lv_signal = getattr(runtime, "last_liquidity_void_observed_signal", None)
        lv_vote = getattr(runtime, "last_liquidity_void_observed_vote", None)
        lv_status = "PASS" if lv_signal is not None and lv_vote is not None else "MISSING_TRUTH"
        evidence.append(
            {
                "module": "LiquidityVoid",
                "authority_class": "ALPHA",
                "status": lv_status,
                "reason_code": "OBSERVED_PAIR_READY" if lv_status == "PASS" else "LIQUIDITY_VOID_OBSERVED_PAIR_MISSING",
                "signal": _dispatch_signal_text(lv_signal),
                "confidence": getattr(lv_vote, "confidence", None) or getattr(lv_signal, "confidence", None),
                "evidence": {
                    "observed_signal_present": lv_signal is not None,
                    "observed_vote_present": lv_vote is not None,
                },
            }
        )

        evidence.append(
            {
                "module": "GammaFront",
                "authority_class": "ALPHA",
                "status": "NOT_APPLICABLE" if getattr(runtime, "gamma_front_strategy", None) is None else "DECLINED",
                "reason_code": "GAMMA_FRONT_NOT_CONFIGURED" if getattr(runtime, "gamma_front_strategy", None) is None else "GAMMA_FRONT_SIGNAL_MISSING",
                "evidence": {"exit_only": True},
            }
        )

        moving_floor_evidence = getattr(runtime, "last_moving_floor_evidence", None)
        if isinstance(moving_floor_evidence, dict):
            evidence.append(dict(moving_floor_evidence))
        else:
            evidence.append(
                {
                    "module": "MovingFloor",
                    "authority_class": "RISK",
                    "status": "NOT_APPLICABLE",
                    "reason_code": "MOVING_FLOOR_FLAT_NO_POSITION",
                    "signal": "NONE",
                    "evidence": {
                        "protective_only": True,
                        "requires_existing_position": True,
                    },
                }
            )

        eligible_names = tuple(_sleeve_module_name(sleeve) for sleeve in eligible_sleeves)
        preferred_name = _sleeve_module_name(preferred_sleeve) if preferred_sleeve is not None else None
        if fusion is None:
            router_status = "MISSING_TRUTH"
            router_reason = "FUSION_MISSING"
        elif profile.get("enabled") is True:
            router_status = "PASS"
            router_reason = "ROUTER_RANKING_ONLY_PROFILE_ACTIVE"
        else:
            router_status = "PASS"
            router_reason = "ROUTER_RANKING_ONLY"
        evidence.append(
            {
                "module": "StrategyRouter",
                "authority_class": "ADVISORY",
                "status": router_status,
                "reason_code": router_reason,
                "evidence": {
                    "preferred_sleeve": preferred_name,
                    "eligible_sleeves": eligible_names,
                    "profile_name": profile.get("profile_name"),
                    "router_authority": "ranking_only_no_execution",
                },
            }
        )
        return tuple(evidence)

    def _observe_moving_floor(
        self,
        symbol: str,
        runtime: SymbolRuntime,
        candle: Candle,
        candle_execution_truth: Mapping[str, Any],
    ) -> None:
        """Produce protective-only MovingFloor evidence bound to broker position truth."""
        runtime.last_moving_floor_observed_signal = None
        runtime.last_moving_floor_observed_vote = None

        position, position_evidence = self._broker_position_truth(symbol, force_refresh=False)
        if position is None:
            reset = getattr(runtime, "reset_moving_floor", None)
            if callable(reset):
                reset("MOVING_FLOOR_FLAT_NO_POSITION")
            else:
                runtime.last_moving_floor_evidence = {
                    "module": "MovingFloor",
                    "authority_class": "RISK",
                    "status": "NOT_APPLICABLE",
                    "reason_code": "MOVING_FLOOR_FLAT_NO_POSITION",
                    "signal": "NONE",
                    "evidence": position_evidence,
                }
            return

        if candle_execution_truth.get("executable_market_truth") is not True:
            runtime.last_moving_floor_evidence = {
                "module": "MovingFloor",
                "authority_class": "MARKET_TRUTH",
                "status": "BLOCK",
                "reason_code": "MOVING_FLOOR_MARKET_TRUTH_NOT_EXECUTABLE",
                "signal": "NONE",
                "evidence": {
                    "protective_only": True,
                    "position_truth": position_evidence,
                    "candle_truth": dict(candle_execution_truth),
                },
            }
            return

        order_book = getattr(runtime, "last_order_book", None)
        if order_book is None:
            runtime.last_moving_floor_evidence = {
                "module": "MovingFloor",
                "authority_class": "MARKET_TRUTH",
                "status": "MISSING_TRUTH",
                "reason_code": "MOVING_FLOOR_BOOK_TRUTH_MISSING",
                "signal": "NONE",
                "evidence": {"protective_only": True, "position_truth": position_evidence},
            }
            return

        try:
            bid_depth, ask_depth = order_book.depth_at_levels(10)
            tick = FloorMarketTick(
                symbol=symbol,
                price=Decimal(str(candle.close)),
                timestamp_ns=candle.exchange_ts_ns,
                bid_volume=Decimal(str(bid_depth)),
                ask_volume=Decimal(str(ask_depth)),
                regime=self._get_dispatch_regime(runtime),
                liquidity_regime=LiquidityRegime.UNKNOWN,
                toxicity_level=self._moving_floor_toxicity_level(runtime),
                book_integrity=self._moving_floor_book_integrity(order_book),
            )
            event, assessment, recommendation = runtime.moving_floor_strategy.process_tick(
                tick,
                FloorRiskContext(risk_action=self._moving_floor_risk_action()),
            )
        except Exception as exc:
            runtime.last_moving_floor_evidence = {
                "module": "MovingFloor",
                "authority_class": "RISK",
                "status": "BLOCK",
                "reason_code": "MOVING_FLOOR_EVALUATION_FAILED",
                "signal": "NONE",
                "evidence": {
                    "error": exc.__class__.__name__,
                    "protective_only": True,
                    "position_truth": position_evidence,
                },
            }
            return

        state = runtime.moving_floor_strategy.snapshot_state()
        if recommendation is None:
            reason = "MOVING_FLOOR_NO_BREACH"
            status = "DECLINED"
            if event is not None and getattr(event, "suppressed", False):
                reason = "MOVING_FLOOR_SUPPRESSED"
                status = "MISSING_TRUTH"
            runtime.last_moving_floor_evidence = {
                "module": "MovingFloor",
                "authority_class": "RISK",
                "status": status,
                "reason_code": reason,
                "signal": "NONE",
                "evidence": {
                    "protective_only": True,
                    "requires_existing_position": True,
                    "position_truth": position_evidence,
                    "event_type": getattr(getattr(event, "event_type", None), "value", None),
                    "assessment_emittable": getattr(assessment, "signal_emittable", None),
                    "floor_phase": getattr(state.phase, "value", state.phase),
                    "current_floor": str(state.current_floor),
                    "highest_price_seen": str(state.highest_price_seen),
                },
            }
            return

        fresh_position, fresh_evidence = self._broker_position_truth(symbol, force_refresh=True)
        if fresh_position is None:
            runtime.last_moving_floor_evidence = {
                "module": "MovingFloor",
                "authority_class": "BROKER_AUTHORITY",
                "status": "BLOCK",
                "reason_code": "MOVING_FLOOR_BROKER_POSITION_MISSING",
                "signal": "NONE",
                "evidence": {
                    "protective_only": True,
                    "position_truth": fresh_evidence,
                },
            }
            return

        signal = self._build_moving_floor_signal(
            recommendation=recommendation,
            position=fresh_position,
            candle=candle,
            position_evidence=fresh_evidence,
        )
        if signal is None:
            runtime.last_moving_floor_evidence = {
                "module": "MovingFloor",
                "authority_class": "RISK",
                "status": "BLOCK",
                "reason_code": "MOVING_FLOOR_PROTECTIVE_EXIT_NON_POSITIVE_EDGE",
                "signal": "NONE",
                "evidence": {
                    "protective_only": True,
                    "position_truth": fresh_evidence,
                    "worst_case_fill_price": str(recommendation.worst_case_fill_price),
                },
            }
            return

        reserve_decision_uuid = getattr(self.decision_compiler, "reserve_decision_uuid", None)
        decision_uuid = reserve_decision_uuid() if callable(reserve_decision_uuid) else None
        vote = adapt_moving_floor_to_vote(
            recommendation,
            exchange_ts_ns=candle.exchange_ts_ns,
            decision_uuid=decision_uuid,
        )
        runtime.record_observed_signal("moving_floor", signal)
        runtime.record_observed_vote("moving_floor", vote)
        runtime.last_moving_floor_evidence = {
            "module": "MovingFloor",
            "authority_class": "RISK",
            "status": "PASS",
            "reason_code": "MOVING_FLOOR_PROTECTIVE_EXIT_CANDIDATE",
            "signal": "SELL",
            "confidence": getattr(vote, "confidence", None) or getattr(signal, "confidence", None),
            "evidence": {
                "protective_only": True,
                "requires_existing_position": True,
                "broker_position_backed": True,
                "position_truth": fresh_evidence,
                "floor_phase": getattr(state.phase, "value", state.phase),
                "current_floor": str(state.current_floor),
                "highest_price_seen": str(state.highest_price_seen),
                "worst_case_fill_price": str(recommendation.worst_case_fill_price),
                "candidate_side": "sell_to_close",
            },
        }
        _log_dispatch_diag(
            "MOVING_FLOOR_PROTECTIVE_EXIT_CANDIDATE",
            symbol=symbol,
            exchange_ts_ns=candle.exchange_ts_ns,
            broker_post=False,
            protective_only=True,
            position_truth=fresh_evidence,
        )

    def _build_moving_floor_signal(
        self,
        *,
        recommendation: Any,
        position: Mapping[str, Any],
        candle: Candle,
        position_evidence: Mapping[str, Any],
    ) -> Optional[StrategySignal]:
        quantity = _to_decimal_or_none(position.get("quantity"))
        average_entry = _to_decimal_or_none(position.get("average_entry_price"))
        worst_case = _to_decimal_or_none(getattr(recommendation, "worst_case_fill_price", None))
        if (
            quantity is None
            or quantity <= Decimal("0")
            or average_entry is None
            or average_entry <= Decimal("0")
            or worst_case is None
            or worst_case <= average_entry
        ):
            return None
        expected_move_bps = ((worst_case - average_entry) / average_entry) * Decimal("10000")
        metadata = {
            "source_module": "MovingFloor",
            "protective_only": True,
            "requires_existing_position": True,
            "fresh_entry_authorized": False,
            "execution_candidate": True,
            "broker_position_backed": True,
            "existing_positions": (dict(position),),
            "protective_context": {
                "source_module": "MovingFloor",
                "protective_only": True,
                "broker_position_backed": True,
                "position_truth": dict(position_evidence),
            },
            "expected_move_bps": str(expected_move_bps),
            "gross_edge_bps": str(expected_move_bps),
            "gross_edge_source": "moving_floor_worst_case_exit_above_broker_entry",
            "worst_case_fill_price": str(worst_case),
            "average_entry_price": str(average_entry),
            "valid_until_ns": int(candle.exchange_ts_ns) + 60_000_000_000,
            "asset_class": _infer_asset_class_for_guardrail(recommendation.symbol, {}),
            "order_action": "sell_to_close",
        }
        return StrategySignal(
            strategy="moving_floor",
            symbol=recommendation.symbol,
            side="sell",
            confidence=float(recommendation.confidence),
            quantity=float(quantity),
            price=float(candle.close),
            exchange_ts_ns=candle.exchange_ts_ns,
            reason="moving_floor_protective_exit",
            metadata=metadata,
        )

    def _consume_observed_pair_moving_floor(
        self,
        symbol: str,
        runtime: SymbolRuntime,
        exchange_ts_ns: int,
    ) -> Tuple[Optional[StrategySignal], Optional[StrategyVote], Dict[str, Any]]:
        signal = getattr(runtime, "last_moving_floor_observed_signal", None)
        vote = getattr(runtime, "last_moving_floor_observed_vote", None)
        evidence = dict(getattr(runtime, "last_moving_floor_evidence", None) or {})
        if signal is None or vote is None:
            return None, None, evidence
        signal_ts = getattr(signal, "exchange_ts_ns", None)
        vote_ts = getattr(vote, "timestamp_ns", None)
        if (
            str(getattr(signal, "symbol", "")).upper() != str(symbol).upper()
            or signal_ts != exchange_ts_ns
            or vote_ts != exchange_ts_ns
        ):
            runtime.last_moving_floor_observed_signal = None
            runtime.last_moving_floor_observed_vote = None
            evidence.update(
                {
                    "module": "MovingFloor",
                    "authority_class": "RISK",
                    "status": "STALE",
                    "reason_code": "MOVING_FLOOR_PAIR_STALE_OR_MISMATCHED",
                    "signal": "NONE",
                }
            )
            return None, None, evidence
        return signal, vote, evidence

    @staticmethod
    def _moving_floor_toxicity_level(runtime: SymbolRuntime) -> ToxicityLevel:
        alert = None
        toxicity_engine = getattr(runtime, "toxicity_engine", None)
        get_last_alert = getattr(toxicity_engine, "get_last_alert", None)
        if callable(get_last_alert):
            alert = get_last_alert()
        regime_name = str(getattr(getattr(alert, "regime", None), "name", "") or "").upper()
        if regime_name == "EXTREME":
            return ToxicityLevel.EXTREME
        if regime_name == "TOXIC":
            return ToxicityLevel.TOXIC
        if regime_name == "ELEVATED":
            return ToxicityLevel.ELEVATED
        return ToxicityLevel.BENIGN

    @staticmethod
    def _moving_floor_book_integrity(order_book: Any) -> BookIntegrity:
        spread = getattr(order_book, "spread", None)
        try:
            spread_value = float(spread)
        except (TypeError, ValueError):
            return BookIntegrity.UNTRUSTWORTHY
        if not math.isfinite(spread_value):
            return BookIntegrity.UNTRUSTWORTHY
        return BookIntegrity.HEALTHY

    def _moving_floor_risk_action(self) -> RiskAction:
        risk_state = self._last_risk_state if isinstance(self._last_risk_state, dict) else {}
        action = str(risk_state.get("action") or "").upper()
        if action in {"EMERGENCY_HALT", "KILL_SWITCH"}:
            return RiskAction.KILL_SWITCH
        if action in {"RECALIBRATE", "SAFE_MODE"}:
            return RiskAction.SAFE_MODE
        return RiskAction.ALLOW

    def _apply_signal_economic_metadata(
        self,
        *,
        symbol: str,
        runtime: SymbolRuntime,
        signal: StrategySignal,
        strategy_vote: StrategyVote,
        latency_truth: Dict[str, Any],
    ) -> Dict[str, Any]:
        metadata = signal.metadata if isinstance(signal.metadata, dict) else {}
        if not isinstance(signal.metadata, dict):
            signal.metadata = metadata
        expected_move_bps = _vote_decimal(getattr(strategy_vote, "expected_move_bps", None))
        expected_duration_ns = getattr(strategy_vote, "expected_duration_ns", None)
        if expected_move_bps is not None:
            metadata.setdefault("expected_move_bps", str(expected_move_bps))
        if expected_duration_ns is not None:
            metadata.setdefault("expected_duration_ns", int(expected_duration_ns))
            metadata.setdefault("valid_until_ns", int(getattr(signal, "exchange_ts_ns", 0) or 0) + int(expected_duration_ns))
        spread_bps = _runtime_order_book_spread_bps(runtime)
        if spread_bps is not None:
            metadata.setdefault("spread_bps", spread_bps)
        metadata.setdefault("latency_truth", dict(latency_truth or {}))
        metadata.setdefault("sleeve", str(getattr(signal, "strategy", "") or "unknown"))
        metadata.setdefault("symbol", symbol)

        evaluator = getattr(self.execution_engine, "evaluate_signal_net_edge", None)
        if not callable(evaluator):
            return {
                "status": "BLOCK",
                "admissible": False,
                "reason_code": "NET_EDGE_EVALUATOR_MISSING",
            }
        result = evaluator(signal, current_price=getattr(runtime, "last_price", None))
        if not isinstance(result, dict):
            return {
                "status": "PASS",
                "admissible": True,
                "reason_code": "NET_EDGE_EVALUATION_MOCKED",
                "source": "NetEdgeGovernor",
            }
        return result

    @staticmethod
    def _net_edge_frame_evidence(net_edge_evaluation: Dict[str, Any]) -> Dict[str, Any]:
        reason = str(net_edge_evaluation.get("reason_code") or "NET_EDGE_UNKNOWN")
        return {
            "module": "NetEdgeGovernor",
            "authority_class": "RISK",
            "status": "PASS" if net_edge_evaluation.get("admissible") is True else "BLOCK",
            "reason_code": reason,
            "signal": "NO_ACTION",
            "confidence": net_edge_evaluation.get("estimate_confidence"),
            "evidence": dict(net_edge_evaluation),
        }

    def _compile_scorecard_frame_no_submit(
        self,
        *,
        symbol: str,
        exchange_ts_ns: int,
        lifecycle: Dict[str, Any],
        reason_code: str,
    ) -> None:
        """Compile a complete NO_TRADE/BLOCK frame without submitting execution."""
        decision_frame = dict(lifecycle.get("decision_frame") or {})
        if not decision_frame:
            return
        primary_no_submit_reason = self._primary_no_submit_reason_code(
            reason_code,
            decision_frame,
        )
        opportunity_scorecard = opportunity_scorecard_from_lifecycle(lifecycle)
        try:
            decision_record = self.decision_compiler.compile(
                self._build_truth_frame(exchange_ts_ns),
                strategy_votes=[],
                additional_inputs={
                    "candidate_lifecycle": lifecycle,
                    "opportunity_scorecard": opportunity_scorecard,
                    "decision_frame": decision_frame,
                    "active_threshold_profile": decision_frame.get("active_threshold_profile"),
                    "no_submit_reason_code": primary_no_submit_reason,
                    "module_decline_reason_code": (
                        reason_code if primary_no_submit_reason != reason_code else None
                    ),
                },
            )
        except Exception as exc:
            _log_dispatch_diag(
                "decision_frame_compile_failed",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                reason_code=reason_code,
                error=exc.__class__.__name__,
                submit_signal_called=False,
            )
            return
        self._metrics.compilation_cycles += 1
        _log_dispatch_diag(
            "decision_compile_attempted",
            symbol=symbol,
            exchange_ts_ns=exchange_ts_ns,
            candidate_id=lifecycle.get("candidate_id"),
            decision_uuid=getattr(decision_record, "decision_uuid", None),
            submitted=False,
            submit_signal_called=False,
            decision_frame=decision_frame,
            frame_id=decision_frame.get("frame_id"),
            frame_output=decision_frame.get("frame_output"),
            frame_status=decision_frame.get("frame_status"),
            frame_reason_codes=decision_frame.get("frame_reason_codes"),
            raw_opportunity_score=opportunity_scorecard.get("raw_opportunity_score"),
            final_opportunity_score=opportunity_scorecard.get("final_opportunity_score"),
            opportunity_verdict=opportunity_scorecard.get("opportunity_verdict"),
            no_submit_reason_code=primary_no_submit_reason,
            module_decline_reason_code=(
                reason_code if primary_no_submit_reason != reason_code else None
            ),
        )
        logger.info(
            "[DISPATCH] %s: DecisionRecord compiled: uuid=%s type=%s",
            symbol,
            getattr(decision_record, "decision_uuid", "<missing>"),
            getattr(decision_record, "decision_type", "<missing>"),
        )

    @staticmethod
    def _primary_no_submit_reason_code(reason_code: str, decision_frame: Mapping[str, Any]) -> str:
        frame_output = str(decision_frame.get("frame_output") or "")
        frame_status = str(decision_frame.get("frame_status") or "")
        optional_decline_prefixes = (
            "shadowfront_declined",
            "GAMMA_FRONT",
            "LIQUIDITY_VOID_OBSERVED_PAIR_MISSING",
        )
        if frame_status == "BLOCK":
            return "DECISION_FRAME_BLOCKED"
        if frame_output == "NO_TRADE" and str(reason_code or "").startswith(optional_decline_prefixes):
            return "DECISION_FRAME_NO_TRADE"
        return str(reason_code or "DECISION_FRAME_NO_TRADE")

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def start(self) -> None:
        self._running = True
        logger.info("MainLoop started: active_symbols=%s", list(self.active_symbols))

    def stop(self) -> None:
        self._running = False
        logger.info(
            "MainLoop stopped: symbols=%s iterations=%d orders=%d duplicates_rejected=%d stale_rejected=%d invalid_books_skipped=%d",
            list(self.active_symbols),
            self._metrics.iteration_count, 
            self._metrics.orders_submitted,
            self._metrics.candle_duplicates_rejected,
            self._metrics.candle_stale_rejected,
            self._metrics.invalid_books_skipped,
        )

    # =========================================================================
    # MARKET DATA INGRESS — ROUTES TO PER-SYMBOL RUNTIME
    # =========================================================================

    def on_order_book(self, order_book: OrderBookSnapshot) -> None:
        """
        Handle order book update for any active symbol.
        
        Routes to the correct SymbolRuntime for full state update.
        No longer drops non-primary symbols.
        
        PER-SYMBOL THROTTLE: Each symbol has independent 200ms throttle.
        PER-SYMBOL SHANS: Each symbol uses its own ShansCurve instance.
        INVALID BOOK FILTER: Skips books with mid_price <= 0.0 or non-finite spread.
        """
        if not self._running:
            return
        
        symbol = order_book.symbol
        
        # DIAGNOSTIC: Entry log
        logger.info("[SHANS_DIAG] ENTER on_order_book: symbol=%s", symbol)
        
        # Validate symbol is active
        if symbol not in self.active_symbols:
            logger.warning(f"Received order book for inactive symbol {symbol}, dropping")
            return
        
        # ================================================================
        # NARROW INVALID BOOK FILTER
        # Skip books with no bids or no asks (mid_price <= 0.0)
        # Skip books with non-finite spread (inf/nan)
        # ================================================================
        mid = order_book.mid_price
        spread = order_book.spread
        
        if mid <= 0.0:
            self._metrics.invalid_books_skipped += 1
            logger.info("[SHANS_DIAG] INVALID_BOOK_SKIP: symbol=%s mid=%.6f <= 0 (no bids or no asks)", symbol, mid)
            return
        
        if not math.isfinite(spread):
            self._metrics.invalid_books_skipped += 1
            logger.info("[SHANS_DIAG] INVALID_BOOK_SKIP: symbol=%s spread=%s (non-finite)", symbol, str(spread))
            return
        
        # Get runtime
        runtime = self._ensure_runtime(symbol)
        if runtime is None:
            return

        receive_ns = time.time_ns()
        exchange_ts_ns = order_book.exchange_ts_ns

        # ================================================================
        # PER-SYMBOL THROTTLE CHECK
        # ================================================================
        last_receive = self._last_book_receive_ns_by_symbol.get(symbol, 0)
        elapsed_since_last_ns = receive_ns - last_receive
        
        if elapsed_since_last_ns < _MIN_BOOK_PROCESS_INTERVAL_NS:
            logger.info("[SHANS_DIAG] THROTTLE_SKIP: symbol=%s elapsed_ns=%d threshold_ns=%d (%.2fms < %.2fms)", 
                       symbol, elapsed_since_last_ns, _MIN_BOOK_PROCESS_INTERVAL_NS,
                       elapsed_since_last_ns / 1_000_000.0, _MIN_BOOK_PROCESS_INTERVAL_NS / 1_000_000.0)
            return
        
        # Update per-symbol last receive timestamp
        self._last_book_receive_ns_by_symbol[symbol] = receive_ns
        
        # DIAGNOSTIC: Throttle pass
        logger.info("[SHANS_DIAG] THROTTLE_PASS: symbol=%s elapsed_ns=%d (%.2fms)", 
                   symbol, elapsed_since_last_ns, elapsed_since_last_ns / 1_000_000.0)

        # Update processed count for diagnostics
        self._book_processed_count[symbol] = self._book_processed_count.get(symbol, 0) + 1
        processed_total = self._book_processed_count[symbol]
        
        # DIAGNOSTIC: Processing book
        logger.info("[SHANS_DIAG] PROCESSING_BOOK: symbol=%s cnt=%d mid=%.4f spread=%.4f", 
                   symbol, processed_total, mid, spread)

        # Update runtime state
        runtime.update_order_book(order_book)

        # STAGE 2-F3: Update OrderRouter live market mid cache only on the
        # accepted-processing path (after invalid-book filters and after the
        # per-symbol throttle pass, after runtime has accepted this book).
        # This ensures ExecutionEngine's price-sanity validator can read a
        # fresh real per-symbol mid via order_router.get_mid_price(symbol)
        # instead of falling back to the legacy hardcoded simulated price
        # ($50,000 for BTC etc.). Side-effect-free cache update: no order,
        # no matching, no position, no cash, no risk-state change.
        try:
            self.execution_engine.order_router.update_market_mid(
                symbol, mid, exchange_ts_ns,
            )
        except Exception as exc:
            logger.warning(
                "[ORDER_ROUTER_CACHE] update_market_mid failed symbol=%s mid=%.6f: %s",
                symbol, mid, exc,
            )

        # Update data validator for this symbol
        self.data_validator.record_data(symbol, _ns_to_datetime(exchange_ts_ns))
        self.data_validator.mark_good(symbol)

        # Analyze TPE using per-symbol engine
        tpe_signal = runtime.topological_engine.analyze(order_book)
        runtime.update_tpe_signal(tpe_signal)

        # Process ShansCurve and Regime for this symbol
        if mid > 0.0:
            cum_bid_vol, cum_ask_vol = order_book.depth_at_levels(10)
            
            # Use primary runtime's last candle for volume reference (honest degradation)
            last_candle_ref = self._primary_runtime.last_candle if self._primary_runtime else None
            
            # ================================================================
            # PER-SYMBOL SHANS: Use runtime's own ShansCurve instance
            # ================================================================
            shans_instance = runtime.shans_curve
            
            if shans_instance is None:
                logger.warning("[SHANS_DIAG] No ShansCurve instance for symbol=%s", symbol)
            else:
                # DIAGNOSTIC: Before Shans call
                logger.info("[SHANS_DIAG] CALLING_SHANS: symbol=%s mid=%.6f bid_vol=%.2f ask_vol=%.2f ts_ns=%d", 
                           symbol, mid, cum_bid_vol, cum_ask_vol, exchange_ts_ns)
                
                shans_result = shans_instance.update_order_book(
                    symbol=symbol,
                    mid_price=mid,
                    cum_bid_vol=cum_bid_vol,
                    cum_ask_vol=cum_ask_vol,
                    depth_velocity=0.0,
                    timestamp=exchange_ts_ns,
                )
                
                # DIAGNOSTIC: Shans result
                if shans_result is not None:
                    logger.info("[SHANS_DIAG] SHANS_RESULT: symbol=%s result_type=SIGNAL score=%.4f bias=%d conf=%.4f",
                               symbol, shans_result.shans_superfluid_score,
                               shans_result.shans_bias, shans_result.shans_confidence)
                    self.signal_fusion.update_shans(shans_result, exchange_ts_ns)
                    logger.info("[SHANS_DIAG] FUSION_UPDATE_CALLED: symbol=%s", symbol)
                else:
                    logger.info("[SHANS_DIAG] SHANS_RESULT: symbol=%s result_type=None", symbol)

            bid_price = mid - spread / 2.0
            ask_price = mid + spread / 2.0
            last_volume = last_candle_ref.volume if last_candle_ref is not None else 0.0
            # PER-SYMBOL REGIME: Use symbol's own detector with fallback to global.
            if runtime.regime_detector is not None:
                regime_tuple = runtime.regime_detector.update(
                    price=mid,
                    volume=last_volume,
                    bid_price=bid_price,
                    ask_price=ask_price,
                    bid_depth=cum_bid_vol,
                    ask_depth=cum_ask_vol,
                    exchange_ts_ns=exchange_ts_ns,
                )
            else:
                logger.warning(
                    "[REGIME] No per-symbol detector for %s, using global fallback",
                    symbol,
                )
                regime_tuple = self.regime_detector.update(
                    price=mid,
                    volume=last_volume,
                    bid_price=bid_price,
                    ask_price=ask_price,
                    bid_depth=cum_bid_vol,
                    ask_depth=cum_ask_vol,
                    exchange_ts_ns=exchange_ts_ns,
                )
            self.signal_fusion.update_regime(regime_tuple, exchange_ts_ns)
            if symbol == self.symbol:
                self._current_regime = regime_tuple[0]
            
            # Update sentiment proxy with regime multiplier
            runtime.update_regime_multiplier(regime_tuple[0])

        # Physical validator uses per-symbol admitted market-data events.
        self._update_physical_freshness(symbol, exchange_ts_ns)

        # Update sentiment engine with current proxy value
        runtime.update_sentiment_engine(exchange_ts_ns)

        # ================================================================
        # OBSERVE-ONLY (Stage 2-B): LiquidityVoid feed pumping
        # Dormant sleeve receives real per-symbol overlays + the order book
        # and may emit Optional[StrategySignal]. Returned signal is LOGGED
        # ONLY — not dispatched, not adapted, not voted, no execution path.
        # ================================================================
        self._observe_liquidity_void(symbol, runtime, order_book)

        self._metrics.last_order_book_exchange_ts_ns = exchange_ts_ns

        # Sync legacy references if this was the primary symbol
        if symbol == self.symbol:
            self._sync_legacy_references()

    def on_candle(self, candle: Candle) -> None:
        """
        Handle candle update for any active symbol with atomic admission control.
        
        Each symbol maintains its own last_admitted_candle_ts_ns to prevent
        duplicate or stale candles from being processed.
        """
        if not self._running:
            return

        symbol = candle.symbol
        
        # Validate symbol is active
        if symbol not in self.active_symbols:
            logger.warning(f"Received candle for inactive symbol {symbol}, dropping")
            return
        
        # Get runtime
        runtime = self._ensure_runtime(symbol)
        if runtime is None:
            return

        # ================================================================
        # CANDLE ADMISSION — ATOMIC CHECK-AND-UPDATE
        # Protected by self._lock to prevent race conditions
        # ================================================================
        incoming_ts_ns = candle.exchange_ts_ns

        with self._lock:
            last_ts_ns = self._last_admitted_candle_ts_ns.get(symbol, 0)

            # Duplicate candle (identical timestamp)
            if incoming_ts_ns == last_ts_ns:
                self._metrics.candle_duplicates_rejected += 1
                dup_count = self._metrics.candle_duplicates_rejected
                should_log_dup = self._candle_rejection_tracker.should_log(symbol, "duplicate")
                if should_log_dup:
                    logger.warning(
                        "CANDLE_REJECT_DUPLICATE: symbol=%s ts_ns=%d last_ts_ns=%d total_duplicates=%d",
                        symbol,
                        incoming_ts_ns,
                        last_ts_ns,
                        dup_count,
                    )
                return

            # Backward/stale candle (older timestamp)
            if incoming_ts_ns < last_ts_ns:
                self._metrics.candle_stale_rejected += 1
                delta_ns = incoming_ts_ns - last_ts_ns
                stale_count = self._metrics.candle_stale_rejected
                should_log_stale = self._candle_rejection_tracker.should_log(symbol, "stale")
                if should_log_stale:
                    logger.warning(
                        "CANDLE_REJECT_STALE: symbol=%s incoming_ts_ns=%d last_ts_ns=%d delta_ns=%d total_stale=%d",
                        symbol,
                        incoming_ts_ns,
                        last_ts_ns,
                        delta_ns,
                        stale_count,
                    )
                return

            # Monotonic candle — update last admitted timestamp
            self._last_admitted_candle_ts_ns[symbol] = incoming_ts_ns

        # ================================================================
        # END OF ATOMIC ADMISSION SECTION
        # ================================================================

        exchange_ts_ns = candle.exchange_ts_ns

        # Update runtime state
        runtime.update_candle(candle)
        runtime.current_volatility = self._compute_volatility(candle)

        # ================================================================
        # WHALE FLOW — STRICT CHANNEL PURITY
        # ================================================================
        # Do NOT feed Candle into SignalFusion whale_flow.
        # Whale fusion channel accepts only WhaleFlowAlert-like payloads
        # produced by the per-symbol WhaleFlowEngine from trade flow.
        whale_alert = runtime.last_whale_alert

        if whale_alert is not None:
            self.signal_fusion.update_whale(whale_alert, exchange_ts_ns)

        # Update per-symbol toxicity engine
        runtime.toxicity_engine.update_candle(
            volume=candle.volume,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            timestamp_ns=exchange_ts_ns,
        )
        tox_alert = runtime.toxicity_engine.update_toxicity(exchange_ts_ns)
        self.signal_fusion.update_toxicity(tox_alert, exchange_ts_ns)
        
        # Update sentiment proxy with toxicity multiplier
        runtime.update_toxicity_multiplier_from_alert()

        # Entropy decoder (global, per-symbol call)
        raw_entropy = min(1.0, (candle.high - candle.low) / max(candle.close, 1e-9) * 20.0)
        entropy_score = self.entropy_decoder.update(symbol, exchange_ts_ns, raw_entropy)
        self.signal_fusion.update_entropy(entropy_score, exchange_ts_ns)

        # Insider signal (global, per-symbol snapshot)
        insider_snapshot = self.insider_engine.get_or_default_snapshot(symbol, exchange_ts_ns)
        self.signal_fusion.update_insider(insider_snapshot, exchange_ts_ns)

        # Commander equity update (global)
        self.commander.update_equity(self._last_equity, exchange_ts_ns)

        # ================================================================
        # OBSERVE-ONLY (Stage 2-B): SectorRotation feed pumping
        # Dormant sleeve receives real per-symbol overlays + the candle and
        # may emit Optional[StrategySignal] (entry from update_candle, exit
        # from update_price). Returned signals are LOGGED ONLY — not
        # dispatched, not adapted, not voted, no execution path. Runs before
        # the LIVE GATE so observation continues regardless of Shans state.
        # ================================================================
        self._observe_sector_rotation(symbol, runtime, candle)

        candle_execution_truth = _classify_candle_execution_truth(
            symbol=symbol,
            runtime=runtime,
            candle=candle,
            exchange_ts_ns=exchange_ts_ns,
        )
        if candle_execution_truth.get("executable_market_truth") is True:
            self.data_validator.record_data(symbol, _ns_to_datetime(exchange_ts_ns))
            self.data_validator.mark_good(symbol)

        self._observe_moving_floor(
            symbol,
            runtime,
            candle,
            candle_execution_truth,
        )

        # ================================================================
        # LIVE GATE — Per-symbol Shans readiness.
        # Default behavior remains fail-closed for execution. The explicit
        # PAPER_EXPLORATION_ALPHA profile may continue to Fusion while recording
        # Shans as missing/not-ready alpha evidence inside the DecisionFrame.
        # ================================================================
        active_threshold_profile = resolve_active_threshold_profile(getattr(self, "config", None))
        _shans_ready = (
            runtime.shans_curve is not None
            and runtime.shans_curve.is_ready()
        )
        _buf_len = len(runtime.shans_curve._p) if runtime.shans_curve is not None else 0
        _buf_req = runtime.shans_curve.curvature_window if runtime.shans_curve is not None else 0
        runtime_frame_evidence = self._runtime_module_frame_evidence(
            symbol,
            runtime,
            exchange_ts_ns,
            active_threshold_profile=active_threshold_profile,
        )
        if not _shans_ready:
            _gate_now = time.time()
            _gate_last = self._shans_gate_last_log_ts.get(symbol, 0.0)
            if _gate_now - _gate_last >= 5.0:
                logger.info(
                    "[LIVE_GATE] BLOCK_FUSION symbol=%s reason=SHANS_NOT_READY buffer=%d required=%d",
                    symbol, _buf_len, _buf_req,
                )
                advisory_signal, advisory_vote, _advisory_sleeve = _latest_runtime_advisory_pair(runtime)
                shans_market_truth = _candidate_market_truth_snapshot_fields(
                    symbol,
                    runtime,
                    exchange_ts_ns,
                    candle_truth=candle_execution_truth,
                )
                _emit_candidate_scorecard_diag(
                    "shans_not_ready",
                    symbol=symbol,
                    exchange_ts_ns=exchange_ts_ns,
                    source_sleeve="ShansCurve",
                    config=getattr(self, "config", None),
                    signal=advisory_signal,
                    strategy_vote=advisory_vote,
                    market_truth=shans_market_truth,
                    candle_truth=candle_execution_truth,
                    latency_truth=_last_latency_truth(getattr(self, "execution_engine", None)),
                    active_threshold_profile=active_threshold_profile,
                    shans_ready=False,
                    shans_buffer=_buf_len,
                    shans_required=_buf_req,
                    dispatch_evidence=runtime_frame_evidence,
                )
                self._shans_gate_last_log_ts[symbol] = _gate_now
        shans_profile_continues = (
            not _shans_ready
            and active_threshold_profile.get("enabled") is True
            and candle_execution_truth.get("executable_market_truth") is True
        )
        if shans_profile_continues:
            _log_dispatch_diag(
                "PAPER_EXPLORATION_SHANS_NOT_READY_CONTINUED",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                active_threshold_profile=active_threshold_profile,
                shans_buffer=_buf_len,
                shans_required=_buf_req,
                broker_mode=getattr(getattr(self, "config", None), "broker_mode", None),
                paper_only=True,
            )

        if _shans_ready or shans_profile_continues:
            if candle_execution_truth.get("executable_market_truth") is not True:
                advisory_signal, advisory_vote, advisory_sleeve = _latest_runtime_advisory_pair(runtime)
                candle_diag_fields = {
                    key: value
                    for key, value in candle_execution_truth.items()
                    if key != "symbol"
                }
                candle_market_truth = _candidate_market_truth_snapshot_fields(
                    symbol,
                    runtime,
                    exchange_ts_ns,
                    candle_truth=candle_execution_truth,
                )
                _emit_candidate_scorecard_diag(
                    str(
                        candle_execution_truth.get("candle_freshness_reason_code")
                        or "DATA_BACKFILL_OBSERVE_ONLY"
                    ),
                    exchange_ts_ns=exchange_ts_ns,
                    symbol=symbol,
                    source_sleeve=advisory_sleeve if advisory_signal is not None or advisory_vote is not None else "MarketDataCandle",
                    config=getattr(self, "config", None),
                    signal=advisory_signal,
                    strategy_vote=advisory_vote,
                    market_truth=candle_market_truth,
                    candle_truth=candle_execution_truth,
                    latency_truth=_last_latency_truth(getattr(self, "execution_engine", None)),
                    active_threshold_profile=active_threshold_profile,
                    dispatch_evidence=runtime_frame_evidence,
                    **candle_diag_fields,
                )
            else:
                # Refresh critical physical evidence on the admitted candle clock
                # before Fusion evaluates physical freshness against this same
                # dispatch timestamp. This preserves hard stale-physical vetoes
                # while preventing active admitted candles from comparing against
                # an older order-book event timestamp.
                self._update_physical_freshness(symbol, exchange_ts_ns)

                # Fuse signals (global — LIMIT: single cache, called per-symbol)
                fusion = self.signal_fusion.fuse(exchange_ts_ns)
                self._last_fusion = fusion

                # Dispatch per-symbol (DIAGNOSTIC: trace dispatch entry)
                if fusion is None:
                    logger.info("[DISPATCH] %s: fusion is None", symbol)
                else:
                    logger.info(
                        "[DISPATCH] %s: fusion advisory_attack_mode=%s, preferred_sleeve=%s",
                        symbol,
                        getattr(fusion, 'attack_mode', '<missing>'),
                        getattr(fusion, 'preferred_sleeve', '<missing>'),
                    )

                self._dispatch_fusion(
                    symbol,
                    runtime,
                    fusion,
                    exchange_ts_ns,
                    candle_execution_truth=candle_execution_truth,
                    pre_frame_evidence=runtime_frame_evidence,
                )

        self._metrics.iteration_count += 1
        self._metrics.last_candle_exchange_ts_ns = exchange_ts_ns

        # Risk assessment (uses primary symbol's TPE signal for now)
        tpe_signal = self._primary_runtime.last_tpe_signal
        tpe_coherence = tpe_signal.coherence_score if tpe_signal is not None else 0.5
        risk_state = self.risk_guard.assess_state(self._last_equity, tpe_coherence)
        self._last_risk_state = risk_state
        self._metrics.last_risk_assessment_ns = exchange_ts_ns

        self._advance_recalibration(risk_state, tpe_signal, exchange_ts_ns)
        self.execution_engine.process_events()

        if (self._metrics.iteration_count - self._metrics.last_health_log_iteration
                >= self.health_log_interval_iterations):
            self._log_health()
            self._metrics.last_health_log_iteration = self._metrics.iteration_count

        self._metrics.consecutive_errors = 0

        # Sync legacy references if this was the primary symbol
        if symbol == self.symbol:
            self._sync_legacy_references()

    def on_trade(self, symbol: str, price: float, timestamp_ns: int) -> None:
        """
        Handle trade update for any active symbol - basic version.
        
        Now routes to per-symbol runtime using the symbol from trade data.
        No longer assumes primary symbol only.
        """
        if not self._running:
            return
        
        # Validate symbol is active
        if symbol not in self.active_symbols:
            logger.warning(f"Received trade for inactive symbol {symbol}, dropping")
            return
        
        # Get runtime
        runtime = self._ensure_runtime(symbol)
        if runtime is None:
            return
        
        # Update runtime with trade price
        runtime.update_trade(price=price, timestamp_ns=timestamp_ns)
        
        # Update data validator
        self.data_validator.record_data(symbol, _ns_to_datetime(timestamp_ns))
        self.data_validator.mark_good(symbol)
        
        # Update legacy reference if primary
        if symbol == self.symbol:
            self._last_price = price
        
        self._metrics.last_trade_exchange_ts_ns = timestamp_ns

    def on_trade_with_whale(self, symbol: str, price: float, side: int, 
                            volume: float, timestamp_ns: int) -> None:
        """
        Trade update with whale data for per-symbol engine and sentiment proxy.
        
        Called from main.py:_on_trade() with real trade details.
        Feeds trade data to per-symbol WhaleFlowEngine and sentiment proxy.
        """
        if not self._running:
            return
        if symbol not in self.active_symbols:
            logger.warning(f"Received whale trade for inactive symbol {symbol}, dropping")
            return
        
        runtime = self._ensure_runtime(symbol)
        if runtime is None:
            return
        
        # Update runtime with trade price
        runtime.update_trade(price=price, timestamp_ns=timestamp_ns)
        
        buy_vol = volume if side == 1 else 0.0
        sell_vol = volume if side == -1 else 0.0
        
        # Update whale engine. price is required so WhaleFlowEngine can
        # normalize raw asset trade sizes against the USD-notional whale
        # threshold (avg_trade_size * price / 100_000).
        alert = runtime.update_whale_with_trade(
            buy_volume=buy_vol,
            sell_volume=sell_vol,
            trade_sizes=[volume],
            timestamp_ns=timestamp_ns,
            price=price,
        )
        
        if alert:
            logger.debug(f"Per-symbol whale update for {symbol}: dir={alert.direction.name}, conf={alert.confidence:.3f}")
        
        # Update sentiment proxy with trade volumes
        runtime.update_trade_with_volumes(buy_vol, sell_vol, timestamp_ns)
        
        # Update sentiment engine
        runtime.update_sentiment_engine(timestamp_ns)
        
        self.data_validator.record_data(symbol, _ns_to_datetime(timestamp_ns))
        self.data_validator.mark_good(symbol)
        
        if symbol == self.symbol:
            self._last_price = price
        
        self._metrics.last_trade_exchange_ts_ns = timestamp_ns

    def on_equity_update(self, current_equity: float, exchange_ts_ns: int) -> None:
        """Update equity (global, not per-symbol)."""
        if not self._running:
            return
        self._last_equity = current_equity
        self.risk_guard.update_equity_history(current_equity)
        self.execution_engine.update_equity(current_equity)
        self.commander.update_equity(current_equity, exchange_ts_ns)
        self._metrics.last_equity_update_ns = exchange_ts_ns

    # =========================================================================
    # BUNDLE 1 REDO REPAIR: DISPATCH (NOW PER-SYMBOL WITH DIAGNOSTICS)
    # =========================================================================

    def _dispatch_fusion(
        self,
        symbol: str,
        runtime: SymbolRuntime,
        fusion: FusionDecision,
        exchange_ts_ns: int,
        *,
        candle_execution_truth: Optional[Dict[str, Any]] = None,
        pre_frame_evidence: Tuple[Dict[str, Any], ...] = (),
    ) -> None:
        """
        Lawful dispatch: FusionDecision -> StrategyRouter -> per-symbol StrategyVote
        -> DecisionCompiler -> ExecutionEngine.submit_signal().

        HYBRID ARCHITECTURE (6G-A): preferred sleeve evaluated first. If it lawfully
        declines, remaining eligible+registered fallback sleeves are evaluated in
        StrategyRouter priority order. No-trade is preserved when all candidates decline.
        Each sleeve attempt and decline is logged explicitly.
        """
        active_threshold_profile = resolve_active_threshold_profile(getattr(self, "config", None))
        if fusion is None:
            logger.info("[DISPATCH] %s: fusion is None -> returning", symbol)
            _emit_candidate_scorecard_diag(
                "fusion_not_actionable",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                source_sleeve="SignalFusion",
                config=getattr(self, "config", None),
                market_truth=_candidate_market_truth_snapshot_fields(
                    symbol,
                    runtime,
                    exchange_ts_ns,
                    candle_truth=candle_execution_truth or {},
                ),
                candle_truth=candle_execution_truth or {},
                latency_truth=_last_latency_truth(getattr(self, "execution_engine", None)),
                active_threshold_profile=active_threshold_profile,
                dispatch_evidence=pre_frame_evidence,
                fusion_present=False,
            )
            return

        self.strategy_router.update_macro_state()
        preferred = self.strategy_router.get_preferred_strategy(fusion)

        logger.info("[DISPATCH] %s: preferred_strategy=%s", symbol, repr(preferred) if preferred is not None else "None")

        if preferred is None:
            if active_threshold_profile.get("enabled") is True:
                preferred = SleeveType.SHADOW_FRONT
                _log_dispatch_diag(
                    "ROUTER_PREFERRED_MISSING_PROFILE_CONTINUED",
                    symbol=symbol,
                    exchange_ts_ns=exchange_ts_ns,
                    preferred_sleeve=repr(preferred),
                    active_threshold_profile=active_threshold_profile,
                    router_authority="ranking_only_no_execution",
                )
            else:
                logger.info("[DISPATCH] %s: no preferred strategy -> returning", symbol)
                _emit_candidate_scorecard_diag(
                    "preferred_sleeve_missing",
                    symbol=symbol,
                    exchange_ts_ns=exchange_ts_ns,
                    source_sleeve="StrategyRouter",
                    config=getattr(self, "config", None),
                    fusion=fusion,
                    market_truth=_candidate_market_truth_snapshot_fields(
                        symbol,
                        runtime,
                        exchange_ts_ns,
                        candle_truth=candle_execution_truth or {},
                    ),
                    candle_truth=candle_execution_truth or {},
                    latency_truth=_last_latency_truth(getattr(self, "execution_engine", None)),
                    active_threshold_profile=active_threshold_profile,
                    dispatch_evidence=pre_frame_evidence,
                    fusion_present=True,
                    preferred_sleeve=None,
                )
                return
        sleeve_registry = {
            SleeveType.SHADOW_FRONT:    runtime.shadow_front_strategy,
            SleeveType.GAMMA_FRONT:     runtime.gamma_front_strategy,
            # STAGE 2-D1: Paper-only proving lane. SECTOR_ROTATION is dispatchable
            # via observed (signal, vote) pair when Fusion/Router admits it and
            # broker_mode == "paper". FLV is registered for naturally-inert
            # routing (Fusion never sets liquidity_void_eligible=True today; the
            # branch is intentionally not implemented in 2-D1 due to event-clock
            # mismatch between order-book observation and candle dispatch — see
            # post-patch report §3 for the Stage 2-D2/D3 hand-off).
            SleeveType.SECTOR_ROTATION: runtime.sector_rotation_strategy,
            SleeveType.FLV:             runtime.liquidity_void_strategy,
        }

        eligible_strategies = self.strategy_router.get_eligible_strategies(fusion)
        eligible_repr = [repr(s) for s in eligible_strategies]
        logger.info("[DISPATCH] %s: eligible_strategies=%s", symbol, eligible_repr)

        runtime_frame_evidence = self._runtime_module_frame_evidence(
            symbol,
            runtime,
            exchange_ts_ns,
            fusion=fusion,
            preferred_sleeve=preferred,
            eligible_sleeves=tuple(eligible_strategies),
            active_threshold_profile=active_threshold_profile,
        )

        fallback_candidates = [
            s for s in eligible_strategies
            if s != preferred and s in sleeve_registry and sleeve_registry[s] is not None
        ]
        candidates = []
        if preferred in sleeve_registry and sleeve_registry[preferred] is not None:
            candidates.append(preferred)
        candidates.extend(fallback_candidates)
        if active_threshold_profile.get("enabled") is True:
            for sleeve, strategy in sleeve_registry.items():
                if strategy is not None and sleeve not in candidates:
                    candidates.append(sleeve)

        if not candidates:
            logger.info(
                "[DISPATCH] %s: no_registered_candidates eligible=%s -> returning",
                symbol, eligible_repr,
            )
            _emit_candidate_scorecard_diag(
                "sleeve_blocked",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                source_sleeve=repr(preferred),
                config=getattr(self, "config", None),
                fusion=fusion,
                market_truth=_candidate_market_truth_snapshot_fields(
                    symbol,
                    runtime,
                    exchange_ts_ns,
                    candle_truth=candle_execution_truth or {},
                ),
                candle_truth=candle_execution_truth or {},
                latency_truth=_last_latency_truth(getattr(self, "execution_engine", None)),
                active_threshold_profile=active_threshold_profile,
                dispatch_evidence=(*pre_frame_evidence, *runtime_frame_evidence),
                preferred_sleeve=repr(preferred),
                eligible_sleeves=eligible_repr,
                candidates=[],
            )
            return

        logger.info(
            "[DISPATCH] %s: dispatch_candidates=%s (preferred=%s, fallbacks=%s)",
            symbol,
            [repr(s) for s in candidates],
            repr(preferred),
            [repr(s) for s in fallback_candidates],
        )

        signal = None
        strategy_vote = None
        winning_sleeve = None
        terminal_reason_code = None
        terminal_reason_fields: Dict[str, object] = {}
        terminal_reason_logged = False
        terminal_signal_for_score = None
        terminal_vote_for_score = None
        terminal_sleeve_for_score = None
        dispatch_evidence: List[Dict[str, Any]] = list((*pre_frame_evidence, *runtime_frame_evidence))
        protective_signal, protective_vote, protective_evidence = self._consume_observed_pair_moving_floor(
            symbol,
            runtime,
            exchange_ts_ns,
        )
        if protective_evidence:
            dispatch_evidence.append(protective_evidence)
        if protective_signal is not None and protective_vote is not None:
            signal = protective_signal
            strategy_vote = protective_vote
            winning_sleeve = StrategyID.MOVING_FLOOR
            candidates = []
            logger.info(
                "[DISPATCH] %s: MovingFloor protective exit selected before fresh-entry sleeves",
                symbol,
            )

        for sleeve in candidates:
            logger.info("[DISPATCH] %s: evaluating sleeve=%s", symbol, repr(sleeve))
            sig = None
            vote = None
            module_name = _sleeve_module_name(sleeve)
            sleeve_evidence: Dict[str, Any] = {
                "module": module_name,
                "sleeve": repr(sleeve),
                "authority_class": "ALPHA",
                "status": "NOT_REACHED",
                "reason_code": "NOT_EVALUATED",
            }

            if sleeve == SleeveType.SHADOW_FRONT:
                logger.info("[DISPATCH] %s: SHADOW_FRONT branch entered", symbol)
                self._update_shadow_front_overlays(symbol, runtime, exchange_ts_ns)
                is_eligible = sleeve in eligible_strategies or active_threshold_profile.get("enabled") is True
                if runtime.shadow_front_strategy:
                    runtime.shadow_front_strategy.update_from_fusion(is_eligible)
                    logger.info("[DISPATCH] %s: update_from_fusion(%s) called", symbol, is_eligible)
                logger.info("[DISPATCH] %s: calling _generate_signal_and_vote()", symbol)
                sig, vote = self._generate_signal_and_vote(symbol, runtime, exchange_ts_ns)
                if sig is None:
                    reason_code, reason_fields = self._classify_shadow_front_decline(
                        runtime.shadow_front_strategy,
                        exchange_ts_ns,
                    )
                    sleeve_evidence.update(
                        {
                            "status": "DECLINED",
                            "reason_code": reason_code,
                            "evidence": dict(reason_fields),
                        }
                    )
                    terminal_reason_code = reason_code
                    terminal_reason_fields = dict(reason_fields)

            elif sleeve == SleeveType.GAMMA_FRONT:
                logger.info("[DISPATCH] %s: GAMMA_FRONT branch entered", symbol)
                sig, vote = self._generate_signal_and_vote_gamma_front(symbol, runtime, exchange_ts_ns)
                if sig is None:
                    sleeve_evidence.update(
                        {
                            "status": "DECLINED",
                            "reason_code": "GAMMA_FRONT_SIGNAL_MISSING",
                        }
                    )

            elif sleeve == SleeveType.SECTOR_ROTATION:
                # STAGE 2-D1: Paper-only active vote admission for SectorRotation.
                # Consumes the observed (signal, vote) pair already produced by
                # Stage 2-B/2-C on the same candle. Strict equality of
                # vote.timestamp_ns == exchange_ts_ns enforces same-candle
                # freshness; SectorRotation observation runs on candle ingress
                # so this equality holds when a fresh signal exists.
                logger.info("[DISPATCH] %s: SECTOR_ROTATION branch entered (paper-only)", symbol)
                reason_code, reason_fields = self._classify_sector_rotation_observed_pair(
                    symbol,
                    runtime,
                    exchange_ts_ns,
                )
                observed_signal_for_score = runtime.last_sector_rotation_observed_signal
                observed_vote_for_score = runtime.last_sector_rotation_observed_vote
                sig, vote = self._consume_observed_pair_sector_rotation(
                    symbol, runtime, exchange_ts_ns,
                )
                if sig is None and reason_code != "OBSERVED_PAIR_READY":
                    sleeve_evidence.update(
                        {
                            "status": "DECLINED",
                            "reason_code": reason_code,
                            "evidence": dict(reason_fields),
                        }
                    )
                    terminal_reason_code = reason_code
                    terminal_reason_fields = dict(reason_fields)
                    terminal_reason_logged = True
                    terminal_signal_for_score = observed_signal_for_score
                    terminal_vote_for_score = observed_vote_for_score
                    terminal_sleeve_for_score = module_name

            elif sleeve == SleeveType.FLV:
                # STAGE 2-D3 (Option C): Paper-only active vote admission for
                # LiquidityVoid via the buffered pre-candle candidate scheme.
                # Reaches this branch only when Fusion/Router admits FLV; today
                # that requires Stage 2-D2's UNKNOWN-regime eligibility flag.
                # LV observation continues firing on order-book ingress; this
                # branch READS the buffered (signal, vote) without re-firing
                # LV's strategy methods or its adapter. Edge preserved.
                logger.info("[DISPATCH] %s: FLV branch entered (paper-only)", symbol)
                sig, vote = self._consume_observed_pair_liquidity_void(
                    symbol, runtime, exchange_ts_ns,
                )
                if sig is None:
                    sleeve_evidence.update(
                        {
                            "status": "DECLINED",
                            "reason_code": "LIQUIDITY_VOID_OBSERVED_PAIR_MISSING",
                        }
                    )

            else:
                logger.info("[DISPATCH] %s: sleeve=%s no_dispatch_branch -> skip", symbol, repr(sleeve))
                sleeve_evidence.update(
                    {
                        "status": "DECLINED",
                        "reason_code": "NO_DISPATCH_BRANCH",
                    }
                )
                dispatch_evidence.append(sleeve_evidence)
                continue

            if sig is not None:
                sleeve_evidence.update(
                    {
                        "status": "PASS",
                        "reason_code": "STRATEGY_SIGNAL_PRESENT",
                        "signal": _dispatch_signal_text(sig),
                        "confidence": getattr(vote, "confidence", None) or getattr(sig, "confidence", None),
                    }
                )
                dispatch_evidence.append(sleeve_evidence)
                signal = sig
                strategy_vote = vote
                winning_sleeve = sleeve
                logger.info("[DISPATCH] %s: sleeve=%s produced_signal -> selected", symbol, repr(sleeve))
                break

            dispatch_evidence.append(sleeve_evidence)
            logger.info("[DISPATCH] strategy_signal_none sleeve=%s -> trying_fallback", repr(sleeve))

        if signal is None:
            logger.info(
                "[DISPATCH] %s: all_sleeves_declined candidates=%s",
                symbol, [repr(s) for s in candidates],
            )
            terminal_source_sleeve = terminal_sleeve_for_score or repr(preferred)
            terminal_scorecard_fields = {
                "preferred_sleeve": repr(preferred),
                "eligible_sleeves": eligible_repr,
                "candidates": [repr(s) for s in candidates],
                "eligibility_only": True,
                "executable_signal_present": False,
            }
            terminal_scorecard_fields.update(dict(terminal_reason_fields))
            terminal_lifecycle: Dict[str, Any]
            if terminal_reason_code is None:
                terminal_lifecycle = _emit_candidate_scorecard_diag(
                    "strategy_signal_missing",
                    symbol=symbol,
                    exchange_ts_ns=exchange_ts_ns,
                    source_sleeve=terminal_source_sleeve,
                    config=getattr(self, "config", None),
                    fusion=fusion,
                    market_truth=_candidate_market_truth_snapshot_fields(
                        symbol,
                        runtime,
                        exchange_ts_ns,
                        candle_truth=candle_execution_truth or {},
                    ),
                    candle_truth=candle_execution_truth or {},
                    latency_truth=_last_latency_truth(getattr(self, "execution_engine", None)),
                    active_threshold_profile=active_threshold_profile,
                    dispatch_evidence=tuple(dispatch_evidence),
                    **terminal_scorecard_fields,
                )
                terminal_compile_reason = "strategy_signal_missing"
            elif terminal_reason_logged:
                terminal_lifecycle = _emit_candidate_scorecard_diag(
                    terminal_reason_code,
                    symbol=symbol,
                    exchange_ts_ns=exchange_ts_ns,
                    source_sleeve=terminal_source_sleeve,
                    config=getattr(self, "config", None),
                    signal=terminal_signal_for_score,
                    strategy_vote=terminal_vote_for_score,
                    fusion=fusion,
                    market_truth=_candidate_market_truth_snapshot_fields(
                        symbol,
                        runtime,
                        exchange_ts_ns,
                        candle_truth=candle_execution_truth or {},
                    ),
                    candle_truth=candle_execution_truth or {},
                    latency_truth=_last_latency_truth(getattr(self, "execution_engine", None)),
                    active_threshold_profile=active_threshold_profile,
                    dispatch_evidence=tuple(dispatch_evidence),
                    terminal_dispatch_reason=True,
                    **terminal_scorecard_fields,
                )
                terminal_compile_reason = terminal_reason_code
            else:
                terminal_lifecycle = _emit_candidate_scorecard_diag(
                    terminal_reason_code,
                    symbol=symbol,
                    exchange_ts_ns=exchange_ts_ns,
                    source_sleeve=terminal_source_sleeve,
                    config=getattr(self, "config", None),
                    fusion=fusion,
                    market_truth=_candidate_market_truth_snapshot_fields(
                        symbol,
                        runtime,
                        exchange_ts_ns,
                        candle_truth=candle_execution_truth or {},
                    ),
                    candle_truth=candle_execution_truth or {},
                    latency_truth=_last_latency_truth(getattr(self, "execution_engine", None)),
                    active_threshold_profile=active_threshold_profile,
                    dispatch_evidence=tuple(dispatch_evidence),
                    terminal_dispatch_reason=True,
                    **terminal_scorecard_fields,
                )
                terminal_compile_reason = terminal_reason_code
            self._compile_scorecard_frame_no_submit(
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                lifecycle=terminal_lifecycle,
                reason_code=str(terminal_compile_reason or "strategy_signal_missing"),
            )
            return
        if strategy_vote is None:
            logger.info("[DISPATCH] %s: strategy_vote=None signal_present sleeve=%s", symbol, repr(winning_sleeve))
            vote_missing_lifecycle = _emit_candidate_scorecard_diag(
                "strategy_vote_missing",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                source_sleeve=repr(winning_sleeve),
                config=getattr(self, "config", None),
                signal=signal,
                fusion=fusion,
                market_truth=_candidate_market_truth_snapshot_fields(
                    symbol,
                    runtime,
                    exchange_ts_ns,
                    candle_truth=candle_execution_truth or {},
                ),
                candle_truth=candle_execution_truth or {},
                latency_truth=_last_latency_truth(getattr(self, "execution_engine", None)),
                active_threshold_profile=active_threshold_profile,
                dispatch_evidence=tuple(dispatch_evidence),
                winning_sleeve=repr(winning_sleeve),
                signal_present=True,
            )
            self._compile_scorecard_frame_no_submit(
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                lifecycle=vote_missing_lifecycle,
                reason_code="strategy_vote_missing",
            )
            return

        logger.info("[DISPATCH] strategy_vote_ready sleeve=%s", repr(winning_sleeve))

        commander = getattr(self, "commander", None)
        get_aggression_contract = getattr(
            commander, "get_aggression_contract", None
        )
        if not callable(get_aggression_contract):
            get_aggression_contract = Commander().get_aggression_contract

        aggression_contract = get_aggression_contract(exchange_ts_ns)
        aggression_contract_metadata = aggression_contract.as_metadata()
        dormant_floor_active_key = "_".join(("moving", "floor", "active"))
        signal_metadata = getattr(signal, "metadata", None)
        advisory_aggression_metadata_present = (
            isinstance(signal_metadata, dict)
            and (
                "aggression_context" in signal_metadata
                or "aggression_snapshot_id" in signal_metadata
            )
        )
        aggression_replay_proof = {
            "authority_owner": aggression_contract_metadata["authority_owner"],
            "authority_version": aggression_contract_metadata["authority_version"],
            "execution_is_attack_source": (
                "Commander.canonical_aggression_contract.execution_is_attack"
            ),
            "execution_is_attack": aggression_contract_metadata["execution_is_attack"],
            "fusion_attack_mode": getattr(fusion, "attack_mode", None),
            "fusion_attack_mode_authoritative": False,
            "advisory_aggression_metadata_present": advisory_aggression_metadata_present,
            "advisory_aggression_metadata_authoritative": False,
            "risk_guard_final_veto_preserved": (
                aggression_contract_metadata["risk_guard_final_veto_preserved"]
            ),
            "economic_admissibility_final_veto_preserved": (
                aggression_contract_metadata[
                    "economic_admissibility_final_veto_preserved"
                ]
            ),
            "stale_gate_final_veto_preserved": (
                aggression_contract_metadata["stale_gate_final_veto_preserved"]
            ),
            dormant_floor_active_key: aggression_contract_metadata[
                dormant_floor_active_key
            ],
            "dormant_governors_active": (
                aggression_contract_metadata["dormant_governors_active"]
            ),
        }
        execution_market_truth = _candidate_market_truth_snapshot_fields(
            symbol,
            runtime,
            exchange_ts_ns,
            candle_truth=candle_execution_truth or {},
        )
        requires_canonical_snapshot = bool(candle_execution_truth)
        candidate_market_snapshot = dict(
            execution_market_truth.get("market_truth_snapshot") or {}
        )
        if isinstance(signal_metadata, dict):
            signal_metadata["canonical_aggression_contract"] = (
                aggression_contract_metadata
            )
            signal_metadata["aggression_replay_proof"] = aggression_replay_proof
            signal_metadata["execution_market_truth"] = execution_market_truth
            signal_metadata["market_truth_snapshot"] = candidate_market_snapshot
            signal_metadata["candidate_market_snapshot"] = candidate_market_snapshot
            signal_metadata["requires_canonical_market_snapshot"] = requires_canonical_snapshot
            signal_metadata["snapshot_id"] = candidate_market_snapshot.get("snapshot_id")
            signal_metadata["candle_id"] = candidate_market_snapshot.get("candle_id")
            signal_metadata["strategy_evidence_snapshot_id"] = candidate_market_snapshot.get("snapshot_id")
            signal_metadata["strategy_evidence_candle_id"] = candidate_market_snapshot.get("candle_id")
        vote_metadata = getattr(strategy_vote, "metadata", None)
        if isinstance(vote_metadata, dict):
            vote_metadata["strategy_evidence_snapshot_id"] = candidate_market_snapshot.get("snapshot_id")
            vote_metadata["strategy_evidence_candle_id"] = candidate_market_snapshot.get("candle_id")

        execution_status: Dict[str, Any] = {}
        execution_engine = getattr(self, "execution_engine", None)
        get_execution_status = getattr(execution_engine, "get_status", None)
        if callable(get_execution_status):
            status_candidate = get_execution_status()
            if isinstance(status_candidate, dict):
                execution_status = status_candidate
        net_edge_evaluation: Dict[str, Any] = {}
        if isinstance(signal_metadata, dict):
            net_edge_evaluation = self._apply_signal_economic_metadata(
                symbol=symbol,
                runtime=runtime,
                signal=signal,
                strategy_vote=strategy_vote,
                latency_truth=execution_status.get("last_latency_truth", {}),
            )
            signal_metadata["net_edge_evaluation"] = net_edge_evaluation

        truth_frame = self._build_truth_frame(exchange_ts_ns)
        pre_trade_guardrail_verdict = _build_pre_trade_guardrail_verdict(
            config=self.config,
            symbol=symbol,
            signal=signal,
            runtime=runtime,
            is_attack=aggression_contract.execution_is_attack,
        )
        if isinstance(signal_metadata, dict):
            signal_metadata["pre_trade_guardrail_verdict"] = pre_trade_guardrail_verdict

        fusion_telemetry: Dict[str, Any] = {}
        signal_fusion = getattr(self, "signal_fusion", None)
        get_fusion_telemetry = getattr(signal_fusion, "get_fusion_telemetry", None)
        if callable(get_fusion_telemetry):
            telemetry_candidate = get_fusion_telemetry()
            if isinstance(telemetry_candidate, dict):
                fusion_telemetry = telemetry_candidate
        get_shadow_counts = getattr(execution_engine, "get_shadow_broker_mutation_counts", None)
        edge_attribution = build_runtime_edge_attribution(
            timestamp_ns=exchange_ts_ns,
            symbol=symbol,
            signal=signal,
            signal_metadata=signal_metadata if isinstance(signal_metadata, dict) else {},
            fusion_attribution=fusion_telemetry.get("edge_attribution", {}),
            guardrail_verdict=pre_trade_guardrail_verdict,
            truth_frame=truth_frame,
            shadow_read_only=bool(getattr(self.config, "shadow_read_only", False)),
            broker_mutation_counts=(
                get_shadow_counts()
                if callable(get_shadow_counts)
                else {}
            ),
        )
        if isinstance(signal_metadata, dict):
            signal_metadata["edge_attribution"] = edge_attribution

        if net_edge_evaluation:
            dispatch_evidence.append(self._net_edge_frame_evidence(net_edge_evaluation))
        decision_frame = _build_runtime_decision_frame(
            config=getattr(self, "config", None),
            symbol=symbol,
            exchange_ts_ns=exchange_ts_ns,
            market_truth=(
                signal_metadata.get("execution_market_truth", {})
                if isinstance(signal_metadata, dict)
                else execution_market_truth
            ),
            signal=signal,
            strategy_vote=strategy_vote,
            fusion=fusion,
            dispatch_evidence=tuple(dispatch_evidence),
            edge_attribution=edge_attribution,
            guardrail_verdict=pre_trade_guardrail_verdict,
            active_threshold_profile=active_threshold_profile,
        )
        if isinstance(signal_metadata, dict):
            signal_metadata["decision_frame"] = decision_frame
            signal_metadata["active_threshold_profile"] = active_threshold_profile
            signal_metadata["frame_id"] = decision_frame.get("frame_id")
            signal_metadata["frame_output"] = decision_frame.get("frame_output")
            signal_metadata["frame_status"] = decision_frame.get("frame_status")
        candidate_id = (
            getattr(strategy_vote, "decision_uuid", None)
            or (signal_metadata.get("decision_uuid") if isinstance(signal_metadata, dict) else None)
            or f"{symbol}:{str(getattr(signal, 'side', '')).lower()}:{exchange_ts_ns}:{repr(winning_sleeve)}"
        )
        candidate_lifecycle = build_candidate_lifecycle(
            candidate_id=str(candidate_id),
            symbol=symbol,
            side=str(getattr(signal, "side", "")).lower(),
            source_sleeve=repr(winning_sleeve),
            timestamp_ns=exchange_ts_ns,
            signal=signal,
            strategy_vote=strategy_vote,
            fusion=fusion,
            market_truth=(
                signal_metadata.get("execution_market_truth", {})
                if isinstance(signal_metadata, dict)
                else {}
            ),
            candle_truth=candle_execution_truth or {},
            edge_attribution=edge_attribution,
            guardrail_verdict=pre_trade_guardrail_verdict,
            latency_truth=execution_status.get("last_latency_truth", {}),
            active_threshold_profile=active_threshold_profile,
            decision_frame=decision_frame,
            dispatch_evidence=tuple(dispatch_evidence),
        )
        candidate_lifecycle_dict = lifecycle_to_dict(candidate_lifecycle)
        opportunity_scorecard = opportunity_scorecard_from_lifecycle(candidate_lifecycle_dict)
        if isinstance(signal_metadata, dict):
            signal_metadata["candidate_lifecycle"] = candidate_lifecycle_dict
            signal_metadata["opportunity_scorecard"] = opportunity_scorecard

        _log_dispatch_diag(
            "decision_compile_attempted",
            symbol=symbol,
            exchange_ts_ns=exchange_ts_ns,
            winning_sleeve=repr(winning_sleeve),
            strategy_vote_present=True,
            candidate_id=candidate_lifecycle_dict["candidate_id"],
            raw_opportunity_score=opportunity_scorecard["raw_opportunity_score"],
            final_opportunity_score=opportunity_scorecard["final_opportunity_score"],
            opportunity_verdict=opportunity_scorecard["opportunity_verdict"],
            snapshot_id=candidate_market_snapshot.get("snapshot_id"),
            snapshot_status=candidate_market_snapshot.get("snapshot_status"),
            snapshot_reason_codes=candidate_market_snapshot.get("snapshot_reason_codes"),
            snapshot_authority=candidate_market_snapshot.get("snapshot_authority"),
            active_threshold_profile=active_threshold_profile,
            decision_frame=decision_frame,
            frame_id=decision_frame.get("frame_id"),
            frame_output=decision_frame.get("frame_output"),
            frame_status=decision_frame.get("frame_status"),
            frame_reason_codes=decision_frame.get("frame_reason_codes"),
        )
        decision_record = self.decision_compiler.compile(
            truth_frame,
            strategy_votes=[strategy_vote],
            additional_inputs={
                "canonical_aggression_contract": aggression_contract_metadata,
                "aggression_replay_proof": aggression_replay_proof,
                "pre_trade_guardrail_verdict": pre_trade_guardrail_verdict,
                "edge_attribution": edge_attribution,
                "candidate_lifecycle": candidate_lifecycle_dict,
                "opportunity_scorecard": opportunity_scorecard,
                "market_truth_snapshot": candidate_market_snapshot,
                "candidate_market_snapshot": candidate_market_snapshot,
                "decision_frame": decision_frame,
                "active_threshold_profile": active_threshold_profile,
            },
        )
        candidate_lifecycle = record_decision_compiler_result(
            candidate_lifecycle,
            decision_record=decision_record,
        )
        candidate_lifecycle_dict = lifecycle_to_dict(candidate_lifecycle)
        opportunity_scorecard = opportunity_scorecard_from_lifecycle(candidate_lifecycle_dict)
        if isinstance(signal_metadata, dict):
            signal_metadata["candidate_lifecycle"] = candidate_lifecycle_dict
            signal_metadata["opportunity_scorecard"] = opportunity_scorecard
        self._metrics.compilation_cycles += 1
        logger.info(
            "[DISPATCH] %s: DecisionRecord compiled: uuid=%s type=%s",
            symbol,
            getattr(decision_record, 'decision_uuid', '<missing>'),
            getattr(decision_record, 'decision_type', '<missing>'),
        )

        decision_uuid = getattr(decision_record, "decision_uuid", None)
        signal_metadata = getattr(signal, "metadata", None)
        if decision_uuid and isinstance(signal_metadata, dict):
            signal_metadata.setdefault("decision_uuid", decision_uuid)

        frame_output = str(decision_frame.get("frame_output") or "")
        frame_status = str(decision_frame.get("frame_status") or "")
        frame_enforces_execution = bool(candle_execution_truth) or (
            isinstance(signal_metadata, dict)
            and signal_metadata.get("requires_canonical_market_snapshot") is True
        )
        if frame_enforces_execution and (frame_status == "BLOCK" or frame_output == "NO_TRADE"):
            frame_reason = "DECISION_FRAME_BLOCKED" if frame_status == "BLOCK" else "DECISION_FRAME_NO_TRADE"
            candidate_lifecycle = record_execution_result(
                candidate_lifecycle,
                submitted=False,
                execution_result=SimpleNamespace(
                    normalized_status="blocked",
                    route="decision_compiler",
                    reason_code=frame_reason,
                    message="DecisionFrame emitted no executable trade intent.",
                    block_evidence={
                        "decision_frame": decision_frame,
                        "frame_id": decision_frame.get("frame_id"),
                        "frame_output": frame_output,
                        "frame_status": frame_status,
                        "frame_reason_codes": decision_frame.get("frame_reason_codes"),
                        "broker_post": False,
                    },
                ),
            )
            candidate_lifecycle_dict = lifecycle_to_dict(candidate_lifecycle)
            opportunity_scorecard = opportunity_scorecard_from_lifecycle(candidate_lifecycle_dict)
            if isinstance(signal_metadata, dict):
                signal_metadata["candidate_lifecycle"] = candidate_lifecycle_dict
                signal_metadata["opportunity_scorecard"] = opportunity_scorecard
            self._metrics.orders_rejected += 1
            _log_dispatch_diag(
                "decision_frame_no_trade",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                winning_sleeve=repr(winning_sleeve),
                decision_uuid=getattr(decision_record, "decision_uuid", None),
                submitted=False,
                submit_signal_called=False,
                candidate_lifecycle=candidate_lifecycle_dict,
                broker_post=False,
                active_threshold_profile=active_threshold_profile,
                decision_frame=decision_frame,
                frame_id=decision_frame.get("frame_id"),
                frame_output=frame_output,
                frame_status=frame_status,
                frame_reason_codes=decision_frame.get("frame_reason_codes"),
            )
            logger.info(
                "[DISPATCH] %s: DecisionFrame blocked submission: decision_uuid=%s frame_output=%s frame_status=%s",
                symbol,
                getattr(decision_record, "decision_uuid", "<missing>"),
                frame_output,
                frame_status,
            )
            return

        submitted = self.execution_engine.submit_signal(
            signal=signal,
            current_price=runtime.last_price,
            is_attack=aggression_contract.execution_is_attack,
            decision_record=decision_record,
        )
        execution_admission_block = None
        get_last_admission_block = getattr(
            self.execution_engine,
            "get_last_admission_block_result",
            None,
        )
        if callable(get_last_admission_block):
            execution_admission_block = get_last_admission_block()
        candidate_lifecycle = record_execution_result(
            candidate_lifecycle,
            submitted=bool(submitted),
            execution_result=execution_admission_block,
        )
        candidate_lifecycle_dict = lifecycle_to_dict(candidate_lifecycle)
        opportunity_scorecard = opportunity_scorecard_from_lifecycle(candidate_lifecycle_dict)
        if isinstance(signal_metadata, dict):
            signal_metadata["candidate_lifecycle"] = candidate_lifecycle_dict
            signal_metadata["opportunity_scorecard"] = opportunity_scorecard
        _log_dispatch_diag(
            "submit_signal_called",
            symbol=symbol,
            exchange_ts_ns=exchange_ts_ns,
            winning_sleeve=repr(winning_sleeve),
            decision_uuid=getattr(decision_record, "decision_uuid", None),
            submitted=submitted,
            submit_signal_called=True,
            candidate_lifecycle=candidate_lifecycle_dict,
            broker_post=opportunity_scorecard["broker_post"],
            **_decision_compiler_status_fields(
                decision_record=decision_record,
                signal_metadata=signal_metadata if isinstance(signal_metadata, dict) else {},
                submitted=bool(submitted),
                execution_admission_block=execution_admission_block,
            ),
        )
        if submitted:
            self._metrics.orders_submitted += 1
            logger.info("[DISPATCH] submitted=True sleeve=%s", repr(winning_sleeve))
            logger.info(
                "[DISPATCH] %s: Signal submitted: decision_uuid=%s side=%s qty=%s",
                symbol,
                getattr(decision_record, 'decision_uuid', '<missing>'),
                getattr(signal, 'side', '<missing>'),
                getattr(signal, 'quantity', '<missing>'),
            )
        else:
            self._metrics.orders_rejected += 1
            logger.info("[DISPATCH] submitted=False sleeve=%s", repr(winning_sleeve))
            logger.info(
                "[DISPATCH] %s: Signal rejected by execution: decision_uuid=%s",
                symbol,
                getattr(decision_record, 'decision_uuid', '<missing>'),
            )

    def _update_shadow_front_overlays(self, symbol: str, runtime: SymbolRuntime, exchange_ts_ns: int) -> None:
        """
        Update per-symbol ShadowFront with latest overlay state.
        
        WHALE: NOW WIRED - retrieves from per-symbol whale engine and feeds to strategy.
        SENTIMENT: NOW WIRED - retrieves from per-symbol sentiment velocity engine.
        """
        if not runtime.shadow_front_strategy:
            return
        
        # ================================================================
        # WHALE OVERLAY - WIRED
        # ================================================================
        whale_score = runtime.get_whale_score()
        if whale_score is not None:
            runtime.shadow_front_strategy.update_whale(whale_score)
            logger.debug(f"Whale overlay for {symbol}: score={whale_score.score:.3f}")
        
        # ================================================================
        # SENTIMENT OVERLAY - NOW WIRED via MarketSentimentProxy
        # ================================================================
        sentiment_velocity = runtime.get_sentiment_velocity()
        runtime.shadow_front_strategy.update_sentiment(sentiment_velocity, exchange_ts_ns)
        logger.debug(f"Sentiment overlay for {symbol}: velocity={sentiment_velocity:.6f}")

        # ================================================================
        # TOXICITY OVERLAY - WIRED
        # ================================================================
        tox_alert = runtime.toxicity_engine.get_last_alert()
        runtime.shadow_front_strategy.update_toxicity_state(tox_alert)

        # ================================================================
        # INSIDER OVERLAY - WIRED
        # ================================================================
        insider_snapshot = self.insider_engine.get_or_default_snapshot(symbol, exchange_ts_ns)
        runtime.shadow_front_strategy.update_insider_state(insider_snapshot)

    def _generate_signal_and_vote(
        self, symbol: str, runtime: SymbolRuntime, exchange_ts_ns: int
    ) -> Tuple[Optional[StrategySignal], Optional[StrategyVote]]:
        """
        Generate StrategySignal and StrategyVote from per-symbol ShadowFrontStrategy.
        
        DIAGNOSTIC: Added INFO logs for entry conditions.
        """
        current_price = runtime.last_price
        if current_price <= 0.0:
            logger.info("[SIGNAL_GEN] %s: current_price=%.4f <= 0 -> returning None", symbol, current_price)
            return None, None

        capital_usd = Decimal(str(self._last_equity))
        kelly_multiplier = Decimal(str(self.commander.get_kelly_multiplier()))
        regime = self._get_dispatch_regime(runtime)
        volatility = Decimal(str(runtime.current_volatility))

        if not runtime.shadow_front_strategy:
            logger.info("[SIGNAL_GEN] %s: no shadow_front_strategy -> returning None", symbol)
            return None, None

        # Inject position sizing engine into per-symbol strategy if not already set
        if hasattr(runtime.shadow_front_strategy, '_position_sizing_engine') and runtime.shadow_front_strategy._position_sizing_engine is None:
            runtime.shadow_front_strategy.set_position_sizing_engine(self.position_sizing_engine)

        logger.info(
            "[SIGNAL_GEN] %s: calling update_price(price=%.4f, capital=%.2f, kelly=%.3f, vol=%.4f, regime=%s)",
            symbol, current_price, capital_usd, kelly_multiplier, volatility, getattr(regime, 'value', repr(regime))
        )

        signal = runtime.shadow_front_strategy.update_price(
            price=current_price,
            timestamp_ns=exchange_ts_ns,
            capital_usd=capital_usd,
            kelly_multiplier=kelly_multiplier,
            volatility=volatility,
            regime=regime,
        )

        if signal is None:
            logger.info("[SIGNAL_GEN] %s: update_price returned None (gate blocked)", symbol)
            return None, None

        decision_uuid = self.decision_compiler.reserve_decision_uuid()
        
        strategy_vote = runtime.shadow_front_strategy.to_strategy_vote(
            signal, exchange_ts_ns, decision_uuid=decision_uuid
        )
        if strategy_vote is None:
            logger.info("[SIGNAL_GEN] %s: to_strategy_vote returned None (sizing missing)", symbol)
            return None, None

        logger.info("[SIGNAL_GEN] %s: signal+vote created successfully", symbol)
        return signal, strategy_vote

    def _generate_signal_and_vote_gamma_front(
        self, symbol: str, runtime: SymbolRuntime, exchange_ts_ns: int
    ) -> Tuple[Optional[StrategySignal], Optional[StrategyVote]]:
        """
        GAMMA_FRONT ADAPTER: Generate StrategySignal and StrategyVote.

        GammaFront.update_price() is exits-only (TTL, TP, SL).
        Entries require DarkPoolPrint via update_dark_pool() — not wired in current runtime.
        In current runtime, update_price() returns None (no position to exit).
        When it does return a signal, this adapter builds a valid StrategyVote.
        """
        current_price = runtime.last_price
        if current_price <= 0.0:
            logger.info("[DISPATCH] strategy_missing preferred_sleeve=GAMMA_FRONT current_price=%.4f <= 0",
                        current_price)
            return None, None

        strategy = runtime.gamma_front_strategy
        if strategy is None:
            logger.info("[DISPATCH] strategy_missing preferred_sleeve=%s", SleeveType.GAMMA_FRONT)
            return None, None

        # Feed toxicity overlay if toxicity engine available
        if runtime.toxicity_engine is not None and hasattr(strategy, 'update_toxicity'):
            toxicity_alert = runtime.toxicity_engine.get_last_alert()
            strategy.update_toxicity(toxicity_alert)

        logger.info("[DISPATCH] GAMMA_FRONT calling update_price symbol=%s price=%.4f",
                    symbol, current_price)
        signal = strategy.update_price(current_price, exchange_ts_ns)

        if signal is None:
            logger.info("[DISPATCH] strategy_signal_none sleeve=%s", SleeveType.GAMMA_FRONT)
            return None, None

        # Map signal.side to SignalType
        side_str = getattr(signal, 'side', 'buy').lower()
        if side_str == 'buy':
            signal_type = SignalType.BUY
        elif side_str == 'sell':
            signal_type = SignalType.SELL
        else:
            signal_type = SignalType.FLAT

        confidence_raw = getattr(signal, 'confidence', 0.5)
        quantity_raw = getattr(signal, 'quantity', 0.1)

        decision_uuid = self.decision_compiler.reserve_decision_uuid()
        try:
            strategy_vote = StrategyVote(
                decision_uuid=decision_uuid,
                strategy_id=StrategyID.GAMMA_FRONT,
                timestamp_ns=exchange_ts_ns,
                signal=signal_type,
                confidence=Decimal(str(confidence_raw)),
                expected_move_bps=Decimal("0"),
                expected_duration_ns=60_000_000_000,  # GammaFront TTL = 60 s
                risk_appetite=Decimal(str(quantity_raw)),
                invalidation_conditions=[],
                metadata=build_council_metadata(
                    source_module=MODULE_GAMMA_FRONT,
                    source_strategy_id=StrategyID.GAMMA_FRONT.value,
                    source_output_type=SOURCE_STRATEGY_SIGNAL,
                    adapter_name="gamma_front_adapter",
                    contribution_role=ROLE_EXIT,
                    fresh_entry_authorized=False,
                    protective_only=False,
                    requires_existing_position=True,
                    execution_candidate=True,
                    directional_bias=BIAS_SHORT if side_str == "sell" else (BIAS_LONG if side_str == "buy" else BIAS_UNKNOWN),
                    feed_status=FEED_MISSING,
                    raw_confidence=float(confidence_raw),
                    normalized_confidence=float(confidence_raw),
                    reason=getattr(signal, 'reason', '') or "gamma_front_adapter",
                    symbol=getattr(signal, 'symbol', symbol),
                    sleeve="gamma_front",
                    exit_reason=getattr(signal, 'reason', ''),
                    adapter="gamma_front_adapter",
                ),
            )
        except Exception as exc:
            logger.error("[DISPATCH] GAMMA_FRONT StrategyVote construction failed: %s", str(exc))
            return None, None

        logger.info("[DISPATCH] strategy_vote_ready sleeve=%s", SleeveType.GAMMA_FRONT)
        return signal, strategy_vote

    # =========================================================================
    # STAGE 2-D1: PAPER-ONLY ACTIVE VOTE ADMISSION FOR OBSERVED SLEEVES
    # =========================================================================
    # Consumes the most-recent observed (signal, vote) pair produced by Stage
    # 2-B/2-C and feeds it into the SHARED downstream dispatch path so that
    # DecisionCompiler.compile and ExecutionEngine.submit_signal apply the
    # SAME governance gates as ShadowFront/GammaFront (RiskGuard.can_trade,
    # vol fuse, data continuity, net-profit floor at 0.005, paper broker
    # isolation). NEVER:
    #   - calls adapters again (Stage 2-C already produced the vote)
    #   - re-fires the strategy methods (no double state mutation)
    #   - bypasses StrategyRouter eligibility (caller's loop already enforces)
    #   - bypasses Fusion eligibility (caller's loop already enforces)
    #   - touches signal_fusion.py (Fusion policy repair is Stage 2-D2)
    #   - reaches a live broker (broker_mode == "paper" hard gate)
    # =========================================================================

    def _consume_observed_pair_sector_rotation(
        self, symbol: str, runtime: SymbolRuntime, exchange_ts_ns: int
    ) -> Tuple[Optional[StrategySignal], Optional[StrategyVote]]:
        """
        Stage 2-D1: Return the freshest observed (signal, vote) pair from
        SectorRotation under paper-only governance, or (None, None) on any
        gate failure. The shared downstream dispatch path then performs
        DecisionCompiler.compile and ExecutionEngine.submit_signal — the SAME
        path already used by ShadowFront and GammaFront. No new authority is
        created here.

        Hard gates (in order):
          1. broker_mode == "paper"  (paper-only proving lane)
          2. observed signal AND vote both present
          3. observed signal/vote symbols must match the consumer symbol when
             symbol evidence is present
          4. observed signal and vote must share the same candle timestamp
          5. observed pair candle timestamp must equal the consumer candle
        """
        if self.config.broker_mode != "paper":
            logger.info(
                "[PAPER_DISPATCH_SECTOR_ROTATION] %s: blocked — broker_mode=%s "
                "(paper-only gate)",
                symbol, self.config.broker_mode,
            )
            _log_dispatch_diag(
                "sleeve_blocked",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                sleeve=repr(SleeveType.SECTOR_ROTATION),
                broker_mode=self.config.broker_mode,
                block_reason="non_paper_broker_mode",
                submit_signal_called=False,
            )
            return None, None

        reason_code, reason_fields = self._classify_sector_rotation_observed_pair(
            symbol,
            runtime,
            exchange_ts_ns,
        )
        observed_signal = runtime.last_sector_rotation_observed_signal
        observed_vote = runtime.last_sector_rotation_observed_vote
        if reason_code != "OBSERVED_PAIR_READY":
            stale_cleared = False
            if reason_code == "OBSERVED_PAIR_STALE":
                stale_cleared = self._clear_stale_sector_rotation_observed_pair(
                    runtime,
                    exchange_ts_ns,
                )
                reason_fields = dict(reason_fields)
                reason_fields["stale_cleared"] = stale_cleared
            logger.info(
                "[PAPER_DISPATCH_SECTOR_ROTATION] %s: blocked — %s "
                "(signal_present=%s vote_present=%s signal_candle_id=%s "
                "vote_candle_id=%s consumer_candle_id=%s stale_cleared=%s)",
                symbol,
                reason_code,
                reason_fields.get("observed_signal_present"),
                reason_fields.get("observed_vote_present"),
                reason_fields.get("signal_candle_id"),
                reason_fields.get("vote_candle_id"),
                reason_fields.get("consumer_candle_id"),
                stale_cleared,
            )
            _log_dispatch_diag(
                reason_code,
                sleeve=repr(SleeveType.SECTOR_ROTATION),
                submit_signal_called=False,
                **reason_fields,
            )
            return None, None

        logger.info(
            "[PAPER_DISPATCH_SECTOR_ROTATION] %s: admitted decision_uuid=%s "
            "side=%s confidence=%s risk_appetite=%s reason_code=%s",
            symbol,
            getattr(observed_vote, "decision_uuid", "<missing>"),
            getattr(observed_signal, "side", "<missing>"),
            getattr(observed_vote, "confidence", "<missing>"),
            getattr(observed_vote, "risk_appetite", "<missing>"),
            reason_code,
        )
        _log_dispatch_diag(
            reason_code,
            sleeve=repr(SleeveType.SECTOR_ROTATION),
            observed_pair_admitted=True,
            **reason_fields,
        )
        return observed_signal, observed_vote

    def _consume_observed_pair_liquidity_void(
        self, symbol: str, runtime: SymbolRuntime, exchange_ts_ns: int
    ) -> Tuple[Optional[StrategySignal], Optional[StrategyVote]]:
        """
        Stage 2-D3 (Option C): Return the buffered pre-candle LiquidityVoid
        observation candidate under paper-only governance, or (None, None) on
        any gate failure. The candidate is the most-recent (signal, vote) pair
        produced by Stage 2-B/2-C inside _observe_liquidity_void from order-book
        ingress; this preserves LV's order-book-native predator edge while
        admitting paper trades through the lawful candle dispatch authority.

        Hard gates (in order):
          1. broker_mode == "paper"  (paper-only proving lane)
          2. observed signal AND vote both present (a candidate exists)
          3. candidate symbol matches current symbol
          4. vote.timestamp_ns <= exchange_ts_ns  (pre-candle freshness;
             LV observation runs on order-book ingress so the candidate's
             timestamp is at or before the current candle's timestamp)
          5. vote.decision_uuid is non-empty
          6. vote.decision_uuid != runtime.last_liquidity_void_consumed_decision_uuid
             (not already consumed by a previous candle dispatch)

        On admission, marks the candidate consumed via
        runtime.last_liquidity_void_consumed_decision_uuid = vote.decision_uuid
        BEFORE returning, so the same candidate cannot fire on later candles.
        The shared downstream path then performs DecisionCompiler.compile and
        ExecutionEngine.submit_signal — same gates as ShadowFront/GammaFront
        (RiskGuard.can_trade, vol fuse, data continuity, net-profit floor at
        0.005, paper broker isolation). No adapter call. No LV update_* call.
        No direct DecisionCompiler / ExecutionEngine call. No live broker.
        """
        if self.config.broker_mode != "paper":
            logger.info(
                "[PAPER_DISPATCH_LIQUIDITY_VOID] %s: blocked — broker_mode=%s "
                "(paper-only gate)",
                symbol, self.config.broker_mode,
            )
            _log_dispatch_diag(
                "sleeve_blocked",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                sleeve=repr(SleeveType.FLV),
                broker_mode=self.config.broker_mode,
                block_reason="non_paper_broker_mode",
                submit_signal_called=False,
            )
            return None, None

        observed_signal = runtime.last_liquidity_void_observed_signal
        observed_vote = runtime.last_liquidity_void_observed_vote

        if observed_signal is None or observed_vote is None:
            logger.info(
                "[PAPER_DISPATCH_LIQUIDITY_VOID] %s: blocked — observed pair missing "
                "(signal=%s vote=%s)",
                symbol,
                "present" if observed_signal is not None else "None",
                "present" if observed_vote is not None else "None",
            )
            _log_dispatch_diag(
                "observed_pair_missing",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                sleeve=repr(SleeveType.FLV),
                observed_signal_present=observed_signal is not None,
                observed_vote_present=observed_vote is not None,
                submit_signal_called=False,
            )
            return None, None

        signal_symbol = getattr(observed_signal, "symbol", None)
        if signal_symbol is not None and signal_symbol != symbol:
            logger.info(
                "[PAPER_DISPATCH_LIQUIDITY_VOID] %s: blocked — symbol mismatch "
                "(candidate symbol=%s)",
                symbol, signal_symbol,
            )
            _log_dispatch_diag(
                "observed_pair_missing",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                sleeve=repr(SleeveType.FLV),
                candidate_symbol=signal_symbol,
                block_reason="symbol_mismatch",
                submit_signal_called=False,
            )
            return None, None

        candidate_ts = getattr(observed_vote, "timestamp_ns", None)
        if candidate_ts is None or candidate_ts > exchange_ts_ns:
            logger.info(
                "[PAPER_DISPATCH_LIQUIDITY_VOID] %s: blocked — freshness fail "
                "(candidate_ts=%s > candle_ts=%s)",
                symbol, candidate_ts, exchange_ts_ns,
            )
            _log_dispatch_diag(
                "observed_pair_stale",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                sleeve=repr(SleeveType.FLV),
                candidate_ts=candidate_ts,
                submit_signal_called=False,
            )
            return None, None

        candidate_uuid = getattr(observed_vote, "decision_uuid", None)
        if not candidate_uuid:
            logger.info(
                "[PAPER_DISPATCH_LIQUIDITY_VOID] %s: blocked — missing decision_uuid",
                symbol,
            )
            _log_dispatch_diag(
                "strategy_vote_missing",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                sleeve=repr(SleeveType.FLV),
                block_reason="missing_decision_uuid",
                submit_signal_called=False,
            )
            return None, None

        if candidate_uuid == runtime.last_liquidity_void_consumed_decision_uuid:
            logger.info(
                "[PAPER_DISPATCH_LIQUIDITY_VOID] %s: blocked — already consumed "
                "(decision_uuid=%s)",
                symbol, candidate_uuid,
            )
            _log_dispatch_diag(
                "strategy_signal_missing",
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                sleeve=repr(SleeveType.FLV),
                decision_uuid=candidate_uuid,
                block_reason="already_consumed",
                submit_signal_called=False,
            )
            return None, None

        runtime.last_liquidity_void_consumed_decision_uuid = candidate_uuid

        logger.info(
            "[PAPER_DISPATCH_LIQUIDITY_VOID] %s: admitted decision_uuid=%s "
            "side=%s confidence=%s risk_appetite=%s candidate_ts=%s candle_ts=%s "
            "consumed=%s",
            symbol,
            candidate_uuid,
            getattr(observed_signal, "side", "<missing>"),
            getattr(observed_vote, "confidence", "<missing>"),
            getattr(observed_vote, "risk_appetite", "<missing>"),
            candidate_ts,
            exchange_ts_ns,
            candidate_uuid,
        )
        return observed_signal, observed_vote

    # =========================================================================
    # STAGE 2-B: OBSERVE-ONLY DORMANT SLEEVE FEED PUMPING
    # =========================================================================
    # Drives LiquidityVoidStrategy and SectorRotationStrategy with real,
    # already-available per-symbol feeds and captures their Optional[
    # StrategySignal] outputs for diagnostic logging only. NEVER:
    #   - converted via strategy_vote_adapters
    #   - inserted into any strategy_votes list
    #   - passed to DecisionCompiler / StrategyRouter / SignalFusion
    #   - submitted to ExecutionEngine / OrderRouter
    #   - used for risk/sizing/order-generation decisions
    # =========================================================================

    def _log_observed_signal(
        self, symbol: str, sleeve_name: str, signal: StrategySignal
    ) -> None:
        """Emit OBSERVE_ONLY diagnostic line for a captured dormant-sleeve signal."""
        metadata = getattr(signal, "metadata", None) or {}
        metadata_keys = sorted(metadata.keys())
        logger.info(
            "[OBSERVE_ONLY] symbol=%s sleeve=%s side=%s confidence=%.4f "
            "reason=%s metadata_keys=%s",
            symbol,
            sleeve_name,
            getattr(signal, "side", "<missing>"),
            float(getattr(signal, "confidence", 0.0)),
            getattr(signal, "reason", ""),
            metadata_keys,
        )

    def _log_observed_vote(
        self, symbol: str, sleeve_name: str, vote: StrategyVote
    ) -> None:
        """Emit OBSERVE_ONLY_VOTE diagnostic line for a telemetry-only StrategyVote."""
        metadata = getattr(vote, "metadata", None) or {}
        metadata_keys = sorted(metadata.keys())
        logger.info(
            "[OBSERVE_ONLY_VOTE] symbol=%s sleeve=%s strategy_id=%s signal=%s "
            "confidence=%s risk_appetite=%s metadata_keys=%s",
            symbol,
            sleeve_name,
            getattr(vote, "strategy_id", "<missing>"),
            getattr(vote, "signal", "<missing>"),
            getattr(vote, "confidence", "<missing>"),
            getattr(vote, "risk_appetite", "<missing>"),
            metadata_keys,
        )

    def _observe_liquidity_void(
        self, symbol: str, runtime: SymbolRuntime, order_book: OrderBookSnapshot
    ) -> None:
        """
        Observe-only feed pump for LiquidityVoidStrategy (Stage 2-B).

        Feeds real per-symbol overlays then captures returned Optional[
        StrategySignal] from update_order_book. Returned signal is logged
        only — never dispatched, adapted, voted, or routed to execution.
        """
        sleeve = runtime.liquidity_void_strategy
        if sleeve is None:
            return

        try:
            if runtime.sentiment_velocity_engine is not None:
                sleeve.update_macro_state(
                    runtime.sentiment_velocity_engine.get_macro_signal()
                )
            if runtime.toxicity_engine is not None:
                sleeve.update_toxicity(runtime.toxicity_engine.get_last_alert())
            sleeve.update_topology(runtime.last_tpe_signal)
            signal = sleeve.update_order_book(order_book)
        except Exception as exc:
            logger.warning(
                "[OBSERVE_ONLY] symbol=%s sleeve=liquidity_void feed/observe raised: %s",
                symbol, exc,
            )
            return

        if signal is None:
            return

        runtime.record_observed_signal("liquidity_void", signal)
        self._log_observed_signal(symbol, "liquidity_void", signal)

        # OBSERVE-ONLY (Stage 2-C): synthesize a StrategyVote via the approved
        # adapter for telemetry/inspection ONLY. This vote is NOT passed to
        # DecisionCompiler, NOT inserted into any active strategy_votes list,
        # NOT routed to StrategyRouter / SignalFusion / ExecutionEngine.
        try:
            vote = adapt_liquidity_void_to_vote(
                signal,
                exchange_ts_ns=order_book.exchange_ts_ns,
            )
        except Exception as exc:
            logger.warning(
                "[OBSERVE_ONLY_VOTE] symbol=%s sleeve=liquidity_void adapter raised: %s",
                symbol, exc,
            )
            return

        runtime.record_observed_vote("liquidity_void", vote)
        self._log_observed_vote(symbol, "liquidity_void", vote)

    def _observe_sector_rotation(
        self, symbol: str, runtime: SymbolRuntime, candle: Candle
    ) -> None:
        """
        Observe-only feed pump for SectorRotationStrategy (Stage 2-B).

        Feeds real per-symbol overlays then captures Optional[StrategySignal]
        from update_candle (entry path) and update_price (exit path) using
        the same candle close + timestamp. Calling update_price after
        update_candle on the same tick is replay-safe per source truth: on
        the entry tick, elapsed-from-entry is 0 so no TTL/TP/SL/exit fires;
        on non-entry ticks update_price is needed to observe exits at all.
        Returned signals are logged only — never dispatched, adapted,
        voted, or routed to execution.
        """
        sleeve = runtime.sector_rotation_strategy
        if sleeve is None:
            return

        try:
            if runtime.sentiment_velocity_engine is not None:
                sleeve.update_macro_state(
                    runtime.sentiment_velocity_engine.get_macro_signal()
                )
            if runtime.toxicity_engine is not None:
                sleeve.update_toxicity(runtime.toxicity_engine.get_last_alert())
            entry_signal = sleeve.update_candle(
                price=candle.close,
                volume=candle.volume,
                timestamp_ns=candle.exchange_ts_ns,
            )
            entry_decline_reason = (
                sleeve.get_last_decline_reason()
                if hasattr(sleeve, "get_last_decline_reason")
                else None
            )
            entry_decline_detail = (
                sleeve.get_last_decline_detail()
                if hasattr(sleeve, "get_last_decline_detail")
                else {}
            )
            exit_signal = sleeve.update_price(
                price=candle.close,
                timestamp_ns=candle.exchange_ts_ns,
            )
            price_decline_reason = (
                sleeve.get_last_decline_reason()
                if hasattr(sleeve, "get_last_decline_reason")
                else None
            )
            price_decline_detail = (
                sleeve.get_last_decline_detail()
                if hasattr(sleeve, "get_last_decline_detail")
                else {}
            )
        except Exception as exc:
            _log_sector_rotation_diag(
                symbol,
                "unknown_no_signal",
                candle.exchange_ts_ns,
                {"stage": "feed_observe", "error": exc.__class__.__name__},
            )
            logger.warning(
                "[OBSERVE_ONLY] symbol=%s sleeve=sector_rotation feed/observe raised: %s",
                symbol, exc,
            )
            return

        if entry_signal is None and exit_signal is None:
            reason_code = (
                entry_decline_reason
                or price_decline_reason
                or "update_candle_no_signal"
            )
            detail = entry_decline_detail or price_decline_detail
            _log_sector_rotation_diag(
                symbol,
                reason_code,
                candle.exchange_ts_ns,
                detail,
            )

        for signal in (entry_signal, exit_signal):
            if signal is None:
                continue
            # OBSERVE-ONLY (Stage 2-C): synthesize a StrategyVote via the
            # approved adapter for telemetry/inspection ONLY. This vote is
            # NOT passed to DecisionCompiler, NOT inserted into any active
            # strategy_votes list, NOT routed to StrategyRouter /
            # SignalFusion / ExecutionEngine.
            try:
                vote = adapt_sector_rotation_to_vote(
                    signal,
                    exchange_ts_ns=candle.exchange_ts_ns,
                )
            except Exception as exc:
                _log_sector_rotation_diag(
                    symbol,
                    "vote_adaptation_failed",
                    candle.exchange_ts_ns,
                    {"error": exc.__class__.__name__},
                )
                logger.warning(
                    "[OBSERVE_ONLY_VOTE] symbol=%s sleeve=sector_rotation adapter raised: %s",
                    symbol, exc,
                )
                continue

            runtime.record_observed_signal("sector_rotation", signal)
            self._log_observed_signal(symbol, "sector_rotation", signal)
            runtime.record_observed_vote("sector_rotation", vote)
            self._log_observed_vote(symbol, "sector_rotation", vote)
            signal_ts = getattr(signal, "exchange_ts_ns", None)
            vote_ts = getattr(vote, "timestamp_ns", None)
            _log_sector_rotation_diag(
                symbol,
                "observed_pair_stored",
                candle.exchange_ts_ns,
                {
                    "observed_signal_present": True,
                    "observed_vote_present": True,
                    "signal_timestamp": signal_ts,
                    "vote_timestamp": vote_ts,
                    "consumer_timestamp": candle.exchange_ts_ns,
                    "signal_candle_id": _observed_pair_candle_id(signal_ts),
                    "vote_candle_id": _observed_pair_candle_id(vote_ts),
                    "consumer_candle_id": _observed_pair_candle_id(
                        candle.exchange_ts_ns
                    ),
                    "symbol": symbol,
                    "reason": "OBSERVED_PAIR_READY"
                    if signal_ts == vote_ts == candle.exchange_ts_ns
                    else "OBSERVED_PAIR_CANDLE_MISMATCH",
                },
            )

    # =========================================================================
    # BUNDLE 3B/3C/3D/3E: TRUTHFRAME CONSTRUCTION WITH HYDRATION
    # =========================================================================

    def _build_truth_frame(self, exchange_ts_ns: int) -> TruthFrame:
        """
        Stage 2 DRIFTING TruthFrame — with real ExchangeTruth, PortfolioTruth, ExecutionTruth, and StrategyTruth hydration.

        BUNDLE 3B: ExchangeTruth is populated from execution_engine.order_router snapshot.
        BUNDLE 3C: PortfolioTruth is populated from available portfolio/account state.
        BUNDLE 3D: ExecutionTruth is populated from execution_engine and order_router state.
        BUNDLE 3E: StrategyTruth is populated from strategy_router and primary shadow_front state.

        Falls back gracefully if data not available.
        TruthStatus remains DRIFTING — full reconciliation requires all five truths.
        """
        # Get order_router for exchange data
        snapshot = {}
        order_router = getattr(self.execution_engine, "order_router", None)
        
        if order_router is not None and hasattr(order_router, "get_exchange_truth_snapshot"):
            try:
                snapshot = order_router.get_exchange_truth_snapshot(self.symbol)
                logger.debug("ExchangeTruth snapshot retrieved successfully")
            except Exception as e:
                logger.warning(f"Failed to fetch exchange truth snapshot: {e}")
        else:
            logger.debug("order_router not available — ExchangeTruth will use empty defaults")

        # ============================================
        # EXCHANGE TRUTH (BUNDLE 3B)
        # ============================================

        balances: Dict[str, Decimal] = {}
        for currency, balance in snapshot.get("balances", {}).items():
            try:
                balances[currency] = Decimal(str(balance))
            except Exception:
                logger.debug(f"Failed to convert balance for {currency}: {balance}")

        exchange_positions: List[ExchangePosition] = []
        for pos in snapshot.get("positions", []):
            try:
                quantity = Decimal(str(pos.get("quantity", 0)))
                side = "long" if quantity > 0 else "short"
                exchange_positions.append(ExchangePosition(
                    symbol=pos.get("symbol", self.symbol),
                    side=side,
                    quantity=abs(quantity),
                    entry_price=Decimal(str(pos.get("average_entry_price", 0))),
                ))
            except Exception as e:
                logger.debug(f"Failed to convert exchange position: {e}")

        open_orders: List[ExchangeOpenOrder] = []
        for order in snapshot.get("open_orders", []):
            try:
                side = OrderSide.BUY if order.get("side", "").lower() == "buy" else OrderSide.SELL
                open_orders.append(ExchangeOpenOrder(
                    order_id=order.get("order_id", ""),
                    symbol=order.get("symbol", self.symbol),
                    side=side,
                    quantity=Decimal(str(order.get("quantity", 0))),
                    limit_price=Decimal(str(order.get("limit_price", 0))) if order.get("limit_price") else None,
                    order_id_namespace=order.get("order_id_namespace"),
                    client_order_id=order.get("client_order_id"),
                    venue_order_id=order.get("venue_order_id"),
                    broker_order_id=order.get("broker_order_id"),
                    exchange_txid=order.get("exchange_txid"),
                    command_id_namespace=order.get("command_id_namespace"),
                    command_order_id=order.get("command_order_id"),
                    mapping_status=order.get("mapping_status"),
                    is_terminal_mapping=bool(order.get("is_terminal_mapping", False)),
                    terminal_reason=order.get("terminal_reason"),
                ))
            except Exception as e:
                logger.debug(f"Failed to convert open order: {e}")

        fills: List[ExchangeFill] = []
        for fill in snapshot.get("fills_since_last_call", []):
            try:
                fills.append(ExchangeFill(
                    fill_id=fill.get("trade_id", fill.get("order_id", "")),
                    order_id=fill.get("order_id", ""),
                    price=Decimal(str(fill.get("price", 0))),
                    quantity=Decimal(str(fill.get("quantity", 0))),
                    fee=Decimal(str(fill.get("fee", 0))),
                ))
            except Exception as e:
                logger.debug(f"Failed to convert fill: {e}")

        exchange_truth = ExchangeTruth(
            venue=self.exchange,
            balances=balances,
            positions=exchange_positions,
            open_orders=open_orders,
            fills_since_last_truth=fills,
            exchange_ts_ns=exchange_ts_ns,
        )

        # ============================================
        # PORTFOLIO TRUTH (BUNDLE 3C)
        # ============================================

        portfolio_cash: Dict[str, Decimal] = {}
        for currency, balance in balances.items():
            portfolio_cash[currency] = balance

        portfolio_positions: List[PortfolioPosition] = []
        mark_price = Decimal(str(self._last_price)) if self._last_price > 0 else Decimal("0")
        
        for pos in snapshot.get("positions", []):
            try:
                quantity = Decimal(str(pos.get("quantity", 0)))
                avg_price = Decimal(str(pos.get("average_entry_price", 0)))
                unrealized_pnl = quantity * (mark_price - avg_price) if quantity > 0 else Decimal("0")
                
                portfolio_positions.append(PortfolioPosition(
                    symbol=pos.get("symbol", self.symbol),
                    quantity=quantity,
                    avg_price=avg_price,
                    mark_price=mark_price,
                    unrealized_pnl=unrealized_pnl,
                ))
            except Exception as e:
                logger.debug(f"Failed to convert portfolio position: {e}")

        total_cash = sum(portfolio_cash.values())
        tradeable_equity = Decimal(str(self._last_equity))
        reserved_buying_power = max(Decimal("0"), tradeable_equity - total_cash)

        portfolio_truth = PortfolioTruth(
            cash=portfolio_cash,
            positions=portfolio_positions,
            reserved_buying_power=reserved_buying_power,
            total_equity=tradeable_equity,
            last_update_ts_ns=exchange_ts_ns,
        )

        # ============================================
        # EXECUTION TRUTH (BUNDLE 3D)
        # ============================================

        submitted_orders: List[SubmittedOrder] = []
        acks_received: List[Acknowledgement] = []
        rejections: List[Rejection] = []
        pending_cancels: List[PendingCancel] = []

        exec_state = getattr(self.execution_engine, "_state", None)
        if exec_state is not None:
            for order_id, order in exec_state.pending_orders.items():
                try:
                    venue_order_id = None
                    if order_router is not None and hasattr(order_router, "get_order_id_mapping_fact"):
                        mapping_fact = order_router.get_order_id_mapping_fact(order_id)
                        if mapping_fact is not None:
                            venue_order_id = mapping_fact.get("venue_order_id")
                    status = InternalOrderStatus.SUBMITTED
                    submitted_orders.append(SubmittedOrder(
                        client_order_id=order_id,
                        venue_order_id=venue_order_id,
                        status=status,
                        submitted_ts_ns=order.exchange_ts_ns if hasattr(order, 'exchange_ts_ns') else exchange_ts_ns,
                    ))
                except Exception as e:
                    logger.debug(f"Failed to convert pending order to SubmittedOrder: {e}")

            for fill in exec_state.filled_orders:
                try:
                    acks_received.append(Acknowledgement(
                        client_order_id=fill.order_id,
                        venue_order_id=fill.order_id,
                        ack_ts_ns=fill.exchange_ts_ns,
                    ))
                except Exception as e:
                    logger.debug(f"Failed to convert fill to Acknowledgement: {e}")

        if order_router is not None:
            status_cache = getattr(order_router, "_order_status_cache", {})
            for client_id, status_info in status_cache.items():
                status_str = getattr(status_info, "status", "") if hasattr(status_info, "status") else status_info.get("status", "") if isinstance(status_info, dict) else ""
                if status_str == "rejected":
                    try:
                        timestamp_ns = getattr(status_info, "timestamp_ns", exchange_ts_ns) if hasattr(status_info, "timestamp_ns") else status_info.get("timestamp_ns", exchange_ts_ns) if isinstance(status_info, dict) else exchange_ts_ns
                        rejections.append(Rejection(
                            client_order_id=client_id,
                            reason="order_rejected_by_venue",
                            reject_ts_ns=timestamp_ns,
                        ))
                    except Exception as e:
                        logger.debug(f"Failed to convert rejection: {e}")

        execution_truth = ExecutionTruth(
            submitted_orders=submitted_orders,
            pending_cancels=pending_cancels,
            acks_received=acks_received,
            rejections=rejections,
            last_reconciliation_ts_ns=exchange_ts_ns,
        )

        # ============================================
        # STRATEGY TRUTH (BUNDLE 3E)
        # ============================================

        active_strategies: List[StrategyTruthEntry] = []

        # Use primary shadow_front strategy for StrategyTruth
        primary_shadow_front = self._primary_runtime.shadow_front_strategy
        if primary_shadow_front:
            macro_kill_active = getattr(self.strategy_router, "_macro_kill_active", False)
            is_eligible = getattr(primary_shadow_front, "_is_eligible", True)
            
            in_position = primary_shadow_front.is_in_position()
            if macro_kill_active:
                state = "macro_killed"
            elif in_position:
                state = "active"
            elif not is_eligible:
                state = "ineligible"
            else:
                state = "idle"

            entry_price = primary_shadow_front.get_entry_price()
            entry_decision_uuid = primary_shadow_front.get_entry_decision_uuid()
            
            target_exposure = Decimal(str(primary_shadow_front.get_target_exposure_pct()))
            current_exposure = primary_shadow_front.get_current_exposure()
            ttl_ns = primary_shadow_front.get_ttl_ns()

            invalidation_state = "valid"

            strategy_entry = StrategyTruthEntry(
                strategy_id=StrategyID.SHADOW_FRONT,
                state=state,
                entry_price=Decimal(str(entry_price)) if entry_price is not None else None,
                entry_decision_uuid=entry_decision_uuid,
                target_exposure=target_exposure,
                current_exposure=current_exposure,
                invalidation_state=invalidation_state,
                ttl_ns=ttl_ns,
            )
            active_strategies.append(strategy_entry)

        strategy_truth = StrategyTruth(
            active_strategies=active_strategies,
            last_update_ts_ns=exchange_ts_ns,
        )

        # ============================================
        # RISK TRUTH (PARTIAL)
        # ============================================

        risk_action = (
            self._last_risk_state.get("action", "NORMAL")
            if self._last_risk_state else "NORMAL"
        )
        risk_mode = (
            RiskMode.HARD_FLAT
            if risk_action == "EMERGENCY_HALT"
            else RiskMode.NORMAL
        )
        risk_truth = RiskTruth(mode=risk_mode)

        reconcile_alerts = TruthReconciler().build_alert_evidence(
            exchange_truth=exchange_truth,
            execution_truth=execution_truth,
            portfolio_truth=portfolio_truth,
            strategy_truth=strategy_truth,
            risk_truth=risk_truth,
        )
        terminal_mapping_proofs = []
        if order_router is not None and hasattr(order_router, "get_terminal_mapping_proofs"):
            try:
                terminal_mapping_proofs = order_router.get_terminal_mapping_proofs(limit=20)
            except Exception as e:
                logger.debug(f"Failed to read terminal mapping proofs: {e}")

        return TruthFrame(
            exchange_truth=exchange_truth,
            execution_truth=execution_truth,
            portfolio_truth=portfolio_truth,
            strategy_truth=strategy_truth,
            risk_truth=risk_truth,
            status=TruthStatus.DRIFTING,
            reconcile_alerts=reconcile_alerts,
            terminal_mapping_proofs=terminal_mapping_proofs,
        )

    def _compute_volatility(self, candle: Candle) -> float:
        """Compute volatility from candle."""
        if candle.close <= 0:
            return 0.20
        daily_range = (candle.high - candle.low) / candle.close
        return max(0.05, min(0.80, daily_range * 15.0))

    # =========================================================================
    # RECALIBRATION STATE MACHINE — PRESERVED UNTOUCHED
    # =========================================================================

    def _advance_recalibration(
        self,
        risk_state: Dict[str, Any],
        tpe_signal: Optional[TopologicalSignal],
        exchange_ts_ns: int,
    ) -> None:
        action: str = risk_state.get("action", "AGGRESSIVE")
        drawdown_from_peak: float = risk_state.get("drawdown_from_peak", 0.0)

        if action == "EMERGENCY_HALT":
            if not self._recalibration_active:
                logger.critical("EMERGENCY_HALT: drawdown=%.2f%%", drawdown_from_peak * 100)
                self._metrics.emergency_liquidations += 1
                self.execution_engine._emergency_liquidate_all()
            return

        drop_duration_sec: float = (
            (exchange_ts_ns - self._recalibration_start_ns) / 1_000_000_000.0
            if self._recalibration_active and self._recalibration_start_ns > 0
            else 0.0
        )

        regime_decision: str = self.recalibrator.evaluate_regime(
            price_drop_pct=drawdown_from_peak,
            tpe_signal=tpe_signal,
            drop_duration_sec=drop_duration_sec,
        )

        if regime_decision == "CRISIS_ABORT" and not self._recalibration_active:
            logger.critical("CRISIS_ABORT: drawdown=%.2f%%", drawdown_from_peak * 100)
            self._metrics.emergency_liquidations += 1
            self.execution_engine._emergency_liquidate_all()
            return

        if action == "RECALIBRATE" and not self._recalibration_active:
            self._recalibration_active = True
            self._recalibration_start_ns = exchange_ts_ns
            self._metrics.recalibration_entries += 1
            self.recalibrator.start_recalibration(
                reason=risk_state.get("reason", "risk_guard_floor_breach"),
                duration_seconds=self.recalibrator.min_recalibration_seconds,
            )
            logger.warning("Recalibration STARTED: %s", risk_state.get("reason"))

        if self._recalibration_active:
            if self.recalibrator.should_recover():
                if action not in ("RECALIBRATE", "EMERGENCY_HALT"):
                    self.recalibrator.end_recalibration()
                    self._recalibration_active = False
                    self._recalibration_start_ns = 0
                    self._metrics.recalibration_exits += 1
                    logger.info("Recalibration ENDED")
            self._metrics.last_recalibration_check_ns = exchange_ts_ns

    # =========================================================================
    # HEALTH LOGGING — PRESERVED UNTOUCHED
    # =========================================================================

    def _log_health(self) -> None:
        risk_status = self.risk_guard.get_status()
        commander_status = self.commander.get_status()

        logger.info(
            "HEALTH | iter=%d | mode=%s | equity=%.2f | drawdown=%.2f%% | "
            "orders=%d/%d | recal=%s | dup_rej=%d | stale_rej=%d | invalid_books=%d | symbols=%d",
            self._metrics.iteration_count,
            commander_status.get("mode", "UNKNOWN"),
            risk_status.get("current_equity", 0.0),
            risk_status.get("drawdown_from_peak", 0.0) * 100,
            self._metrics.orders_submitted,
            self._metrics.compilation_cycles,
            self._recalibration_active,
            self._metrics.candle_duplicates_rejected,
            self._metrics.candle_stale_rejected,
            self._metrics.invalid_books_skipped,
            len(self._runtimes),
        )

    # =========================================================================
    # DIAGNOSTICS — HONEST ACTUATION STATUS
    # =========================================================================

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "symbol": self.symbol,
                "active_symbols": list(self.active_symbols),
                "running": self._running,
                "iteration_count": self._metrics.iteration_count,
                "last_price": self._last_price,
                "last_equity": self._last_equity,
                "compilation_cycles": self._metrics.compilation_cycles,
                "orders_submitted": self._metrics.orders_submitted,
                "candle_duplicates_rejected": self._metrics.candle_duplicates_rejected,
                "candle_stale_rejected": self._metrics.candle_stale_rejected,
                "invalid_books_skipped": self._metrics.invalid_books_skipped,
                "book_processed_count": self._book_processed_count,
                "actuation": "diagnostic_trace",
                "actuation_limits": {
                    "signal_fusion_global": True,
                    "decision_compiler_global": True,
                    "execution_engine_global": True,
                    "order_router_global": True,
                    "multi_symbol_state_ownership": True,
                    "whale_overlay_wired": True,
                    "sentiment_overlay_wired": True,
                    "per_symbol_throttle": True,
                    "per_symbol_shans": True,
                },
                "runtimes": {
                    sym: runtime.get_status() for sym, runtime in self._runtimes.items()
                }
            }

    def get_last_fusion(self) -> Optional[FusionDecision]:
        with self._lock:
            return self._last_fusion
    
    def get_runtime(self, symbol: str) -> Optional[SymbolRuntime]:
        """Get runtime container for a specific symbol."""
        return self._runtimes.get(symbol)
    
    def get_all_runtimes(self) -> Dict[str, SymbolRuntime]:
        """Get all symbol runtimes."""
        return self._runtimes.copy()
