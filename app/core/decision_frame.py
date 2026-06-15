from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Sequence


CONTRIBUTED = "CONTRIBUTED"
DECLINED = "DECLINED"
MISSING_TRUTH = "MISSING_TRUTH"
STALE = "STALE"
BLOCK = "BLOCK"
PENALTY = "PENALTY"
NOT_APPLICABLE = "NOT_APPLICABLE"

AUTHORITY_ALPHA = "ALPHA"
AUTHORITY_RISK = "RISK"
AUTHORITY_MARKET_TRUTH = "MARKET_TRUTH"
AUTHORITY_BROKER_AUTHORITY = "BROKER_AUTHORITY"
AUTHORITY_EXECUTION = "EXECUTION"
AUTHORITY_ADVISORY = "ADVISORY"

SIGNAL_BUY = "BUY"
SIGNAL_SELL = "SELL"
SIGNAL_NO_ACTION = "NO_ACTION"
SIGNAL_NONE = "NONE"

FRAME_PASS = "PASS"
FRAME_BLOCK = "BLOCK"

FRAME_OUTPUT_BUY = "BUY"
FRAME_OUTPUT_SELL = "SELL"
FRAME_OUTPUT_NO_TRADE = "NO_TRADE"

PROFILE_DEFAULT = "DEFAULT"
PROFILE_PAPER_EXPLORATION_ALPHA = "PAPER_EXPLORATION_ALPHA"

NS_PER_MS = 1_000_000

_HARD_AUTHORITY_CLASSES = frozenset(
    {
        AUTHORITY_MARKET_TRUTH,
        AUTHORITY_RISK,
        AUTHORITY_BROKER_AUTHORITY,
        AUTHORITY_EXECUTION,
    }
)

_MISSING_TRUTH_REASON_CODES = frozenset(
    {
        "OBSERVED_SIGNAL_MISSING",
        "OBSERVED_VOTE_MISSING",
        "shans_not_ready",
        "strategy_signal_missing",
        "fusion_not_actionable",
        "preferred_sleeve_missing",
    }
)

_STALE_REASON_CODES = frozenset({"OBSERVED_PAIR_STALE"})

_MISMATCH_REASON_CODES = frozenset(
    {
        "OBSERVED_PAIR_SYMBOL_MISMATCH",
        "OBSERVED_PAIR_CANDLE_MISMATCH",
        "SNAPSHOT_SYMBOL_MISMATCH",
        "SNAPSHOT_TIMESTAMP_MISMATCH",
    }
)


@dataclass(frozen=True, slots=True)
class ModuleEvidence:
    module_name: str
    authority_class: str
    status: str
    signal: str = SIGNAL_NONE
    confidence: Optional[Decimal] = None
    score_delta: Optional[Decimal] = None
    reason_codes: tuple[str, ...] = ()
    snapshot_id: Optional[str] = None
    candle_id: Optional[int] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_name": self.module_name,
            "authority_class": self.authority_class,
            "status": self.status,
            "signal": self.signal,
            "confidence": _decimal_to_float_or_none(self.confidence),
            "score_delta": _decimal_to_float_or_none(self.score_delta),
            "reason_codes": self.reason_codes,
            "snapshot_id": self.snapshot_id,
            "candle_id": self.candle_id,
            "metadata": _json_ready(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class DecisionFrame:
    frame_id: str
    snapshot_id: str
    symbol: str
    candle_id: Optional[int]
    created_at_ns: int
    expires_at_ns: int
    timeout_policy: Mapping[str, Any]
    module_evidence: tuple[ModuleEvidence, ...]
    active_threshold_profile: Mapping[str, Any]
    frame_status: str
    frame_reason_codes: tuple[str, ...]
    frame_output: str
    buy_score: Decimal = Decimal("0")
    sell_score: Decimal = Decimal("0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "snapshot_id": self.snapshot_id,
            "symbol": self.symbol,
            "candle_id": self.candle_id,
            "created_at_ns": self.created_at_ns,
            "expires_at_ns": self.expires_at_ns,
            "timeout_policy": _json_ready(self.timeout_policy),
            "module_evidence": {
                item.module_name: item.to_dict() for item in self.module_evidence
            },
            "active_threshold_profile": _json_ready(self.active_threshold_profile),
            "frame_status": self.frame_status,
            "frame_reason_codes": self.frame_reason_codes,
            "frame_output": self.frame_output,
            "buy_score": _decimal_to_float(self.buy_score),
            "sell_score": _decimal_to_float(self.sell_score),
        }


def resolve_active_threshold_profile(config: Any) -> dict[str, Any]:
    requested = bool(
        getattr(config, "paper_exploration_alpha_enabled", False)
        or getattr(config, "PAPER_EXPLORATION_ALPHA", False)
    )
    if not requested:
        return {
            "profile_name": PROFILE_DEFAULT,
            "enabled": False,
            "paper_only": False,
            "activation_status": "INACTIVE",
            "reason_codes": (),
            "thresholds": (),
            "thresholds_by_name": {},
        }

    broker_mode = str(getattr(config, "broker_mode", "") or "").lower()
    alpaca_paper = bool(getattr(config, "alpaca_paper", True))
    if broker_mode != "paper" or alpaca_paper is not True:
        return {
            "profile_name": PROFILE_PAPER_EXPLORATION_ALPHA,
            "enabled": False,
            "paper_only": True,
            "activation_status": "BLOCK",
            "reason_codes": ("PAPER_EXPLORATION_PROFILE_NON_PAPER_BLOCKED",),
            "thresholds": (),
            "thresholds_by_name": {},
        }

    strategies = getattr(config, "strategies", None)
    thresholds = (
        _threshold_change(
            "shans_ready_required",
            True,
            False,
            "PAPER_ALPHA_SHANS_READINESS_OBSERVE_ONLY_RELAXED",
        ),
        _threshold_change(
            "fusion_min_confidence",
            _float_attr(strategies, "min_confidence", 0.60),
            min(_float_attr(strategies, "min_confidence", 0.60), 0.35),
            "PAPER_ALPHA_FUSION_SELECTIVITY_RELAXED",
        ),
        _threshold_change(
            "sector_inflow_threshold",
            _float_attr(strategies, "sector_inflow_threshold", 1.50),
            min(_float_attr(strategies, "sector_inflow_threshold", 1.50), 0.75),
            "PAPER_ALPHA_SECTOR_ROTATION_INFLOW_RELAXED",
        ),
        _threshold_change(
            "sector_rotation_min_confidence",
            _float_attr(strategies, "min_confidence", 0.60),
            min(_float_attr(strategies, "min_confidence", 0.60), 0.45),
            "PAPER_ALPHA_SECTOR_ROTATION_CONFIDENCE_RELAXED",
        ),
        _threshold_change(
            "sector_rotation_min_baseline_candles",
            10,
            3,
            "PAPER_ALPHA_SECTOR_ROTATION_BASELINE_RELAXED",
        ),
        _threshold_change(
            "shadowfront_whale_threshold",
            _float_attr(strategies, "whale_threshold", 0.20),
            min(_float_attr(strategies, "whale_threshold", 0.20), 0.10),
            "PAPER_ALPHA_SHADOWFRONT_WHALE_RELAXED",
        ),
        _threshold_change(
            "shadowfront_sentiment_velocity_threshold",
            _float_attr(strategies, "sentiment_velocity_threshold", 1.50),
            min(_float_attr(strategies, "sentiment_velocity_threshold", 1.50), 0.10),
            "PAPER_ALPHA_SHADOWFRONT_SENTIMENT_RELAXED",
        ),
        _threshold_change(
            "shadowfront_min_confidence",
            _float_attr(strategies, "min_confidence", 0.60),
            min(_float_attr(strategies, "min_confidence", 0.60), 0.45),
            "PAPER_ALPHA_SHADOWFRONT_CONFIDENCE_RELAXED",
        ),
        _threshold_change(
            "minimum_opportunity_score",
            0.45,
            0.25,
            "PAPER_ALPHA_MINIMUM_OPPORTUNITY_SCORE_RELAXED",
        ),
        _threshold_change(
            "optional_alpha_quorum",
            1,
            0,
            "PAPER_ALPHA_OPTIONAL_MODULE_QUORUM_RELAXED",
        ),
    )
    return {
        "profile_name": PROFILE_PAPER_EXPLORATION_ALPHA,
        "enabled": True,
        "paper_only": True,
        "paper_only_active": True,
        "activation_status": "PASS",
        "reason_codes": ("PAPER_EXPLORATION_ALPHA_ACTIVE",),
        "thresholds": thresholds,
        "thresholds_by_name": {item["threshold_name"]: item for item in thresholds},
    }


def decision_frame_timeout_ns(config: Any, snapshot: Mapping[str, Any] | None = None) -> int:
    configured_ms = _float_or_none(getattr(config, "decision_frame_timeout_ms", None))
    if configured_ms is None or configured_ms <= 0:
        configured_ms = _float_or_none((snapshot or {}).get("candle_freshness_policy_ms"))
    if configured_ms is None or configured_ms <= 0:
        data_cfg = getattr(config, "data", None)
        polling_sec = _float_or_none(getattr(data_cfg, "polling_interval_seconds", None))
        configured_ms = max(1_000.0, (polling_sec or 1.0) * 1_000.0)
    return int(configured_ms * NS_PER_MS)


def build_decision_frame_from_runtime(
    *,
    symbol: str,
    snapshot: Mapping[str, Any] | None,
    created_at_ns: int,
    timeout_ns: int,
    active_threshold_profile: Mapping[str, Any] | None,
    signal: Any = None,
    strategy_vote: Any = None,
    fusion: Any = None,
    dispatch_evidence: Sequence[Mapping[str, Any]] = (),
    edge_attribution: Mapping[str, Any] | None = None,
    guardrail_verdict: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    snap = dict(snapshot or {})
    evidence: list[ModuleEvidence] = [
        _market_truth_evidence(symbol=symbol, snapshot=snap),
        _signal_evidence(signal, snap),
        _vote_evidence(strategy_vote, snap),
        _executable_intent_evidence(signal, strategy_vote, snap),
        _fusion_evidence(fusion, snap),
    ]
    evidence.extend(_dispatch_evidence_items(dispatch_evidence, snap))
    evidence.extend(_edge_attribution_items(edge_attribution or {}, snap))
    if guardrail_verdict is not None:
        evidence.append(_guardrail_evidence(guardrail_verdict, snap))

    frame = build_decision_frame(
        symbol=symbol,
        snapshot=snap,
        created_at_ns=created_at_ns,
        timeout_ns=timeout_ns,
        module_evidence=evidence,
        active_threshold_profile=active_threshold_profile or resolve_active_threshold_profile(None),
    )
    return frame.to_dict()


def build_decision_frame(
    *,
    symbol: str,
    snapshot: Mapping[str, Any] | None,
    created_at_ns: int,
    timeout_ns: int,
    module_evidence: Sequence[ModuleEvidence | Mapping[str, Any]],
    active_threshold_profile: Mapping[str, Any],
) -> DecisionFrame:
    snap = dict(snapshot or {})
    snapshot_id = str(snap.get("snapshot_id") or "snapshot_missing")
    candle_id = _int_or_none(snap.get("candle_id"))
    normalized_evidence = _dedupe_evidence(
        _coerce_evidence(item) for item in module_evidence
    )
    reason_codes: list[str] = []
    hard_blocked = False
    buy_score = Decimal("0")
    sell_score = Decimal("0")

    for item in normalized_evidence:
        reason_codes.extend(item.reason_codes)
        if item.snapshot_id and item.snapshot_id != snapshot_id:
            reason_codes.append("MODULE_EVIDENCE_SNAPSHOT_MISMATCH")
            hard_blocked = True
        if item.candle_id is not None and candle_id is not None and item.candle_id != candle_id:
            reason_codes.append("MODULE_EVIDENCE_CANDLE_MISMATCH")
            hard_blocked = True
        if item.status in {BLOCK, STALE} and item.authority_class in _HARD_AUTHORITY_CLASSES:
            hard_blocked = True
        if item.status == CONTRIBUTED:
            score = _to_decimal(item.confidence) + _to_decimal(item.score_delta)
            if item.signal == SIGNAL_BUY:
                buy_score += max(Decimal("0"), score)
            elif item.signal == SIGNAL_SELL:
                sell_score += max(Decimal("0"), score)

    minimum_score = _profile_threshold_value(
        active_threshold_profile,
        "minimum_opportunity_score",
        Decimal("0.45"),
    )
    if hard_blocked:
        frame_output = FRAME_OUTPUT_NO_TRADE
        frame_status = FRAME_BLOCK
    elif buy_score >= minimum_score and buy_score >= sell_score:
        frame_output = FRAME_OUTPUT_BUY
        frame_status = FRAME_PASS
    elif sell_score >= minimum_score and sell_score > buy_score:
        frame_output = FRAME_OUTPUT_SELL
        frame_status = FRAME_PASS
    else:
        frame_output = FRAME_OUTPUT_NO_TRADE
        frame_status = FRAME_PASS
        if not reason_codes:
            reason_codes.append("FRAME_SCORE_BELOW_ACTION_THRESHOLD")

    clean_reason_codes = tuple(dict.fromkeys(str(code) for code in reason_codes if str(code)))
    return DecisionFrame(
        frame_id=_frame_id(symbol=symbol, candle_id=candle_id, snapshot_id=snapshot_id),
        snapshot_id=snapshot_id,
        symbol=str(symbol),
        candle_id=candle_id,
        created_at_ns=int(created_at_ns),
        expires_at_ns=int(created_at_ns) + int(timeout_ns),
        timeout_policy={
            "timeout_ns": int(timeout_ns),
            "source": "config.decision_frame_timeout_ms_or_snapshot_candle_policy",
        },
        module_evidence=tuple(normalized_evidence),
        active_threshold_profile=active_threshold_profile,
        frame_status=frame_status,
        frame_reason_codes=clean_reason_codes,
        frame_output=frame_output,
        buy_score=_clamp_score(buy_score),
        sell_score=_clamp_score(sell_score),
    )


def _market_truth_evidence(*, symbol: str, snapshot: Mapping[str, Any]) -> ModuleEvidence:
    status = CONTRIBUTED
    reason_codes: tuple[str, ...] = ()
    if not snapshot:
        status = BLOCK
        reason_codes = ("MARKET_TRUTH_SNAPSHOT_MISSING",)
    elif snapshot.get("snapshot_status") != "PASS" or snapshot.get("executable_market_truth") is not True:
        status = BLOCK
        raw_codes = snapshot.get("snapshot_reason_codes") or ("MARKET_TRUTH_SNAPSHOT_NOT_EXECUTABLE",)
        reason_codes = tuple(str(code) for code in raw_codes if str(code))
    return ModuleEvidence(
        module_name="MarketTruthSnapshot",
        authority_class=AUTHORITY_MARKET_TRUTH,
        status=status,
        signal=SIGNAL_NONE,
        reason_codes=reason_codes,
        snapshot_id=str(snapshot.get("snapshot_id") or "") if snapshot else None,
        candle_id=_int_or_none(snapshot.get("candle_id")) if snapshot else None,
        metadata={"symbol": symbol, "snapshot_status": snapshot.get("snapshot_status") if snapshot else None},
    )


def _signal_evidence(signal: Any, snapshot: Mapping[str, Any]) -> ModuleEvidence:
    if signal is None:
        return ModuleEvidence(
            module_name="StrategySignal",
            authority_class=AUTHORITY_ALPHA,
            status=MISSING_TRUTH,
            signal=SIGNAL_NONE,
            reason_codes=("STRATEGY_SIGNAL_MISSING",),
            snapshot_id=str(snapshot.get("snapshot_id") or "") if snapshot else None,
            candle_id=_int_or_none(snapshot.get("candle_id")) if snapshot else None,
        )
    side = str(getattr(signal, "side", "") or "").lower()
    return ModuleEvidence(
        module_name="StrategySignal",
        authority_class=AUTHORITY_ALPHA,
        status=CONTRIBUTED,
        signal=SIGNAL_BUY if side == "buy" else (SIGNAL_SELL if side == "sell" else SIGNAL_NO_ACTION),
        confidence=_to_decimal(getattr(signal, "confidence", None)),
        reason_codes=(),
        snapshot_id=str(snapshot.get("snapshot_id") or "") if snapshot else None,
        candle_id=_int_or_none(getattr(signal, "exchange_ts_ns", None)),
        metadata={
            "strategy": getattr(signal, "strategy", None),
            "reason": getattr(signal, "reason", None),
            "symbol": getattr(signal, "symbol", None),
        },
    )


def _vote_evidence(strategy_vote: Any, snapshot: Mapping[str, Any]) -> ModuleEvidence:
    if strategy_vote is None:
        return ModuleEvidence(
            module_name="StrategyVote",
            authority_class=AUTHORITY_ALPHA,
            status=MISSING_TRUTH,
            signal=SIGNAL_NONE,
            reason_codes=("STRATEGY_VOTE_MISSING",),
            snapshot_id=str(snapshot.get("snapshot_id") or "") if snapshot else None,
            candle_id=_int_or_none(snapshot.get("candle_id")) if snapshot else None,
        )
    raw_signal = getattr(strategy_vote, "signal", None)
    signal_text = str(getattr(raw_signal, "value", raw_signal) or "").upper()
    if signal_text in {"BUY", "LONG"}:
        frame_signal = SIGNAL_BUY
    elif signal_text in {"SELL", "SHORT"}:
        frame_signal = SIGNAL_SELL
    elif signal_text in {"FLAT", "NO_ACTION"}:
        frame_signal = SIGNAL_NO_ACTION
    else:
        frame_signal = SIGNAL_NONE
    return ModuleEvidence(
        module_name="StrategyVote",
        authority_class=AUTHORITY_ALPHA,
        status=CONTRIBUTED,
        signal=frame_signal,
        confidence=_to_decimal(getattr(strategy_vote, "confidence", None)),
        reason_codes=(),
        snapshot_id=str(snapshot.get("snapshot_id") or "") if snapshot else None,
        candle_id=_int_or_none(getattr(strategy_vote, "timestamp_ns", None)),
        metadata={"strategy_id": str(getattr(strategy_vote, "strategy_id", ""))},
    )


def _signal_side_to_frame_signal(value: Any) -> str:
    side = str(value or "").strip().upper()
    if side in {"BUY", "LONG"}:
        return SIGNAL_BUY
    if side in {"SELL", "SHORT"}:
        return SIGNAL_SELL
    if side in {"FLAT", "NO_ACTION"}:
        return SIGNAL_NO_ACTION
    return SIGNAL_NONE


def _vote_signal_to_frame_signal(strategy_vote: Any) -> str:
    raw_signal = getattr(strategy_vote, "signal", None)
    return _signal_side_to_frame_signal(getattr(raw_signal, "value", raw_signal))


def _executable_intent_evidence(
    signal: Any,
    strategy_vote: Any,
    snapshot: Mapping[str, Any],
) -> ModuleEvidence:
    snapshot_id = str(snapshot.get("snapshot_id") or "") if snapshot else None
    candle_id = _int_or_none(snapshot.get("candle_id")) if snapshot else None
    missing: list[str] = []
    if signal is None:
        missing.append("StrategySignal")
    if strategy_vote is None:
        missing.append("StrategyVote")
    if missing:
        return ModuleEvidence(
            module_name="ExecutableIntent",
            authority_class=AUTHORITY_EXECUTION,
            status=BLOCK,
            signal=SIGNAL_NONE,
            reason_codes=("EXECUTABLE_INTENT_MISSING",),
            snapshot_id=snapshot_id,
            candle_id=candle_id,
            metadata={"missing": tuple(missing)},
        )

    signal_side = _signal_side_to_frame_signal(getattr(signal, "side", None))
    vote_signal = _vote_signal_to_frame_signal(strategy_vote)
    if signal_side not in {SIGNAL_BUY, SIGNAL_SELL} or vote_signal not in {SIGNAL_BUY, SIGNAL_SELL}:
        return ModuleEvidence(
            module_name="ExecutableIntent",
            authority_class=AUTHORITY_EXECUTION,
            status=BLOCK,
            signal=SIGNAL_NONE,
            reason_codes=("EXECUTABLE_INTENT_NON_DIRECTIONAL",),
            snapshot_id=snapshot_id,
            candle_id=candle_id,
            metadata={"signal_side": signal_side, "vote_signal": vote_signal},
        )
    if signal_side != vote_signal:
        return ModuleEvidence(
            module_name="ExecutableIntent",
            authority_class=AUTHORITY_EXECUTION,
            status=BLOCK,
            signal=SIGNAL_NONE,
            reason_codes=("EXECUTABLE_INTENT_DIRECTION_MISMATCH",),
            snapshot_id=snapshot_id,
            candle_id=candle_id,
            metadata={"signal_side": signal_side, "vote_signal": vote_signal},
        )

    return ModuleEvidence(
        module_name="ExecutableIntent",
        authority_class=AUTHORITY_EXECUTION,
        status=CONTRIBUTED,
        signal=SIGNAL_NONE,
        reason_codes=(),
        snapshot_id=snapshot_id,
        candle_id=candle_id,
        metadata={"signal_side": signal_side, "vote_signal": vote_signal},
    )


def _fusion_evidence(fusion: Any, snapshot: Mapping[str, Any]) -> ModuleEvidence:
    confidence = _to_decimal(getattr(fusion, "confidence", None))
    return ModuleEvidence(
        module_name="SignalFusion",
        authority_class=AUTHORITY_ALPHA,
        status=CONTRIBUTED if fusion is not None else MISSING_TRUTH,
        signal=SIGNAL_NO_ACTION,
        confidence=confidence if confidence > 0 else None,
        reason_codes=() if fusion is not None else ("FUSION_MISSING",),
        snapshot_id=str(snapshot.get("snapshot_id") or "") if snapshot else None,
        candle_id=_int_or_none(snapshot.get("candle_id")) if snapshot else None,
        metadata={"preferred_sleeve": getattr(fusion, "preferred_sleeve", None)},
    )


def _dispatch_evidence_items(
    dispatch_evidence: Sequence[Mapping[str, Any]],
    snapshot: Mapping[str, Any],
) -> tuple[ModuleEvidence, ...]:
    items: list[ModuleEvidence] = []
    for raw in dispatch_evidence:
        if not isinstance(raw, Mapping):
            continue
        reason = str(raw.get("reason_code") or "")
        module = str(raw.get("module") or raw.get("sleeve") or reason or "DispatchModule")
        status = _status_from_dispatch(raw)
        authority_class = str(raw.get("authority_class") or AUTHORITY_ALPHA)
        if reason in _MISMATCH_REASON_CODES:
            status = BLOCK
        elif reason in _STALE_REASON_CODES:
            status = STALE
        elif reason in _MISSING_TRUTH_REASON_CODES:
            status = MISSING_TRUTH
        elif reason.startswith("shadowfront_declined"):
            status = DECLINED
        raw_signal = str(raw.get("signal") or raw.get("side") or "").upper()
        if raw_signal in {"BUY", "LONG"}:
            frame_signal = SIGNAL_BUY
        elif raw_signal in {"SELL", "SHORT"}:
            frame_signal = SIGNAL_SELL
        elif raw_signal in {"NO_ACTION", "FLAT"}:
            frame_signal = SIGNAL_NO_ACTION
        else:
            frame_signal = SIGNAL_NONE
        items.append(
            ModuleEvidence(
                module_name=module,
                authority_class=authority_class,
                status=status,
                signal=frame_signal,
                confidence=_to_decimal_or_none(raw.get("confidence") or raw.get("score")),
                score_delta=_to_decimal_or_none(raw.get("score_delta")),
                reason_codes=(reason,) if reason else (),
                snapshot_id=str(snapshot.get("snapshot_id") or "") if snapshot else None,
                candle_id=_int_or_none(
                    raw.get("candle_id")
                    or raw.get("consumer_candle_id")
                    or snapshot.get("candle_id")
                ),
                metadata=_json_ready(dict(raw.get("evidence") or raw)),
            )
        )
    return tuple(items)


def _edge_attribution_items(
    edge_attribution: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> tuple[ModuleEvidence, ...]:
    items: list[ModuleEvidence] = []
    for name, raw in dict(edge_attribution or {}).items():
        if not isinstance(raw, Mapping):
            continue
        status = str(raw.get("status") or "")
        effect = str(raw.get("effect") or "")
        module_status = NOT_APPLICABLE
        if status in {"ACTIVE_NATIVE_SIGNAL", "PASSED", "ACTIVE_TRUTH_CHECK", "ACTIVE_GUARDRAIL"} or effect in {"APPROVED", "RANKED"}:
            module_status = CONTRIBUTED
        elif status == "MISSING_FEED_TRUTH":
            module_status = MISSING_TRUTH
        elif status == "DEGRADED_FALLBACK":
            module_status = PENALTY
        elif status in {"VETOED", "FAILED_CLOSED"}:
            module_status = BLOCK
        elif effect in {"NO_EFFECT_WITH_REASON", "SKIPPED"}:
            module_status = NOT_APPLICABLE
        items.append(
            ModuleEvidence(
                module_name=str(name),
                authority_class=_authority_from_attribution(name, raw),
                status=module_status,
                signal=SIGNAL_NONE,
                reason_codes=(str(raw.get("reason")),) if raw.get("reason") else (),
                snapshot_id=str(snapshot.get("snapshot_id") or "") if snapshot else None,
                candle_id=_int_or_none(raw.get("timestamp") or snapshot.get("candle_id")),
                metadata=_json_ready(raw),
            )
        )
    return tuple(items)


def _guardrail_evidence(
    guardrail_verdict: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> ModuleEvidence:
    route_permitted = guardrail_verdict.get("route_permitted") is True
    reason_codes = tuple(
        str(code) for code in guardrail_verdict.get("reason_codes", ()) if str(code)
    )
    return ModuleEvidence(
        module_name="PreTradeGuardrails",
        authority_class=AUTHORITY_RISK,
        status=CONTRIBUTED if route_permitted else BLOCK,
        signal=SIGNAL_NO_ACTION,
        reason_codes=reason_codes,
        snapshot_id=str(snapshot.get("snapshot_id") or "") if snapshot else None,
        candle_id=_int_or_none(snapshot.get("candle_id")) if snapshot else None,
        metadata=_json_ready(guardrail_verdict),
    )


def _status_from_dispatch(raw: Mapping[str, Any]) -> str:
    status = str(raw.get("status") or "")
    if status in {"PASS", CONTRIBUTED}:
        return CONTRIBUTED
    if status == MISSING_TRUTH:
        return MISSING_TRUTH
    if status == "DECLINED":
        return DECLINED
    if status == "PENALTY":
        return PENALTY
    if status == "BLOCK":
        return BLOCK
    if status == "STALE":
        return STALE
    if status == NOT_APPLICABLE:
        return NOT_APPLICABLE
    return NOT_APPLICABLE


def _authority_from_attribution(name: str, raw: Mapping[str, Any]) -> str:
    category = str(raw.get("category") or "").lower()
    lname = str(name).lower()
    if "risk" in category or "guardrail" in category or "risk" in lname:
        return AUTHORITY_RISK
    if "broker" in category or "venue" in category or "capability" in lname:
        return AUTHORITY_BROKER_AUTHORITY
    if "execution" in category or "execution" in lname or "router" in lname:
        return AUTHORITY_EXECUTION
    if "truth" in category or "market_data" in category:
        return AUTHORITY_MARKET_TRUTH
    if "strategy" in category or "alpha" in category or "signal" in lname:
        return AUTHORITY_ALPHA
    return AUTHORITY_ADVISORY


def _threshold_change(
    name: str,
    default_value: Any,
    exploration_value: Any,
    reason_code: str,
) -> dict[str, Any]:
    return {
        "threshold_name": name,
        "default_value": default_value,
        "exploration_value": exploration_value,
        "profile_name": PROFILE_PAPER_EXPLORATION_ALPHA,
        "paper_only": True,
        "reason_code": reason_code,
    }


def _profile_threshold_value(
    profile: Mapping[str, Any],
    threshold_name: str,
    default: Decimal,
) -> Decimal:
    by_name = profile.get("thresholds_by_name") if isinstance(profile, Mapping) else None
    if isinstance(by_name, Mapping):
        item = by_name.get(threshold_name)
        if isinstance(item, Mapping):
            return _to_decimal(item.get("exploration_value"))
    return default


def _dedupe_evidence(items: Sequence[ModuleEvidence]) -> tuple[ModuleEvidence, ...]:
    out: dict[str, ModuleEvidence] = {}
    for item in items:
        if not item.module_name:
            continue
        existing = out.get(item.module_name)
        if existing is None or _status_rank(item.status) >= _status_rank(existing.status):
            out[item.module_name] = item
    return tuple(out.values())


def _status_rank(status: str) -> int:
    return {
        BLOCK: 7,
        STALE: 6,
        CONTRIBUTED: 5,
        PENALTY: 4,
        MISSING_TRUTH: 3,
        DECLINED: 2,
        NOT_APPLICABLE: 1,
    }.get(status, 0)


def _coerce_evidence(item: ModuleEvidence | Mapping[str, Any]) -> ModuleEvidence:
    if isinstance(item, ModuleEvidence):
        return item
    return ModuleEvidence(
        module_name=str(item.get("module_name") or ""),
        authority_class=str(item.get("authority_class") or AUTHORITY_ADVISORY),
        status=str(item.get("status") or NOT_APPLICABLE),
        signal=str(item.get("signal") or SIGNAL_NONE),
        confidence=_to_decimal_or_none(item.get("confidence")),
        score_delta=_to_decimal_or_none(item.get("score_delta")),
        reason_codes=tuple(str(code) for code in item.get("reason_codes", ()) if str(code)),
        snapshot_id=str(item.get("snapshot_id")) if item.get("snapshot_id") is not None else None,
        candle_id=_int_or_none(item.get("candle_id")),
        metadata=dict(item.get("metadata") or {}),
    )


def _frame_id(*, symbol: str, candle_id: Optional[int], snapshot_id: str) -> str:
    raw = "|".join((str(symbol), str(candle_id or ""), str(snapshot_id or "")))
    return "df_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _float_attr(obj: Any, name: str, default: float) -> float:
    try:
        return float(getattr(obj, name, default))
    except (TypeError, ValueError):
        return default


def _float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _to_decimal_or_none(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    return _to_decimal(value)


def _clamp_score(value: Decimal) -> Decimal:
    if value < Decimal("0"):
        return Decimal("0")
    if value > Decimal("1"):
        return Decimal("1")
    return value.quantize(Decimal("0.0001"))


def _decimal_to_float(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.0001")))


def _decimal_to_float_or_none(value: Optional[Decimal]) -> Optional[float]:
    if value is None:
        return None
    return _decimal_to_float(value)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_json_ready(item) for item in value)
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


__all__ = [
    "AUTHORITY_ADVISORY",
    "AUTHORITY_ALPHA",
    "AUTHORITY_BROKER_AUTHORITY",
    "AUTHORITY_EXECUTION",
    "AUTHORITY_MARKET_TRUTH",
    "AUTHORITY_RISK",
    "BLOCK",
    "CONTRIBUTED",
    "DECLINED",
    "DecisionFrame",
    "FRAME_BLOCK",
    "FRAME_OUTPUT_BUY",
    "FRAME_OUTPUT_NO_TRADE",
    "FRAME_OUTPUT_SELL",
    "FRAME_PASS",
    "MISSING_TRUTH",
    "ModuleEvidence",
    "NOT_APPLICABLE",
    "PENALTY",
    "PROFILE_DEFAULT",
    "PROFILE_PAPER_EXPLORATION_ALPHA",
    "SIGNAL_BUY",
    "SIGNAL_NONE",
    "SIGNAL_NO_ACTION",
    "SIGNAL_SELL",
    "STALE",
    "build_decision_frame",
    "build_decision_frame_from_runtime",
    "decision_frame_timeout_ns",
    "resolve_active_threshold_profile",
]
