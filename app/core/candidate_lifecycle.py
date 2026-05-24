from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


PASS = "PASS"
BLOCK = "BLOCK"
NOT_REACHED = "NOT_REACHED"
PENALTY = "PENALTY"
DECLINED = "DECLINED"

FATAL_REJECT = "FATAL_REJECT"
OPPORTUNITY_PENALTY = "OPPORTUNITY_PENALTY"
STRATEGY_DECLINED = "STRATEGY_DECLINED"
DISPATCH_BLOCKER = "DISPATCH_BLOCKER"
EXECUTION_BLOCKER = "EXECUTION_BLOCKER"
BROKER_AUTHORITY_BLOCKER = "BROKER_AUTHORITY_BLOCKER"

GOOD_CANDIDATE_NOT_EXECUTABLE = "GOOD_CANDIDATE_NOT_EXECUTABLE"
GOOD_CANDIDATE_EXECUTABLE = "GOOD_CANDIDATE_EXECUTABLE"
PLAUSIBLE_CANDIDATE = "PLAUSIBLE_CANDIDATE"
WEAK_CANDIDATE = "WEAK_CANDIDATE"

_GOOD_SCORE = Decimal("0.70")
_PLAUSIBLE_SCORE = Decimal("0.45")

_FATAL_REASON_CODES = frozenset(
    {
        "LIVE_MODE_BLOCKED",
        "LIVE_BLOCKED",
        "NON_PAPER_ENVIRONMENT_BLOCKED",
        "REAL_MONEY_MODE_BLOCKED",
        "LIVE_ENDPOINT_BLOCKED",
        "FAKE_TRUTH_BLOCKED",
        "SYNTHETIC_TRUTH_PRETENDING_LIVE",
        "INVALID_SYMBOL",
        "SIDE_MALFORMED",
        "QUANTITY_MALFORMED",
        "PRICE_MALFORMED",
        "BROKER_TRUTH_CONFLICT",
        "MARKET_TRUTH_CORRUPTION",
        "RISK_KILL_SWITCH_ACTIVE",
        "UNIVERSE_AUTHORITY_MISSING",
    }
)

_BROKER_AUTHORITY_REASON_CODES = frozenset(
    {
        "ACTION_UNSUPPORTED",
        "SELL_AUTHORITY_MISSING",
        "SELL_EXIT_LOCAL_SIM_ONLY",
        "SELL_SHORT_UNSUPPORTED",
        "PREFERRED_PORTAL_UNSUPPORTED",
        "NO_USABLE_PORTAL",
        "ADAPTER_MISSING",
    }
)

_EXECUTION_REASON_CODES = frozenset(
    {
        "SAFE_MODE_ACTIVE",
        "DATA_UNHEALTHY",
        "PRE_TRADE_GUARDRAIL_BLOCKED",
        "ECONOMIC_ADMISSIBILITY_BLOCKED",
        "EXECUTION_ENGINE_NOT_RUNNING",
        "RECALIBRATION_ACTIVE",
        "RISK_GUARD_BLOCKED",
        "VOL_FUSE_TRIGGERED",
        "QUOTE_SESSION_TRUTH_MISSING",
        "QUOTE_MISSING",
        "QUOTE_STALE",
        "QUOTE_WIDE_SPREAD",
        "QUOTE_SESSION_NOT_TRADABLE",
        "MARKET_CLOSED",
        "SESSION_CLOSED_STALE_QUOTE",
        "DECISION_FRAME_BLOCKED",
        "DECISION_FRAME_NO_TRADE",
    }
)

_DATA_TRUTH_REASON_CODES = frozenset(
    {
        "CANDLE_STALE",
        "DATA_BACKFILL_OBSERVE_ONLY",
        "CANDLE_BATCH_BACKFILL_OBSERVE_ONLY",
        "CANDLE_NOT_CLOSED",
        "DATA_RUNTIME_CANDLE_IN_PROGRESS",
        "DATA_TIMESTAMP_MISSING",
        "CANDLE_TIMESTAMP_MISSING",
        "CANDLE_FRESHNESS_POLICY_MISSING",
        "MARKET_TRUTH_SNAPSHOT_MISSING",
        "MARKET_TRUTH_SNAPSHOT_NOT_EXECUTABLE",
        "CANDIDATE_SNAPSHOT_STALE",
        "MARKET_TRUTH_CONFLICT",
        "SNAPSHOT_SYMBOL_MISMATCH",
        "SNAPSHOT_SOURCE_UNEXECUTABLE",
        "SNAPSHOT_TIMESTAMP_MISMATCH",
        "STALE_MONITOR_EVIDENCE_IGNORED",
    }
)


@dataclass(frozen=True, slots=True)
class CandidateGate:
    gate: str
    status: str
    classification: str
    reason_codes: tuple[str, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "status": self.status,
            "classification": self.classification,
            "reason_codes": self.reason_codes,
            "evidence": _json_ready(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class CandidateLifecycleRecord:
    candidate_id: str
    symbol: str
    side: str
    source_sleeve: str
    timestamp_ns: int
    gates: tuple[CandidateGate, ...]
    module_contributions: Mapping[str, Any]
    module_declines: Mapping[str, Any]
    penalties: Mapping[str, Any]
    raw_opportunity_score: Decimal
    final_opportunity_score: Decimal
    opportunity_verdict: str
    execution_verdict: str = NOT_REACHED
    execution_blocker_reason_codes: tuple[str, ...] = ()
    broker_boundary_result: str = NOT_REACHED
    broker_post: bool = False
    final_outcome: str = NOT_REACHED
    active_threshold_profile: Mapping[str, Any] = field(default_factory=dict)
    decision_frame: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "symbol": self.symbol,
            "side": self.side,
            "source_sleeve": self.source_sleeve,
            "timestamp_ns": self.timestamp_ns,
            "raw_opportunity_score": _decimal_to_float(self.raw_opportunity_score),
            "module_contributions": _json_ready(self.module_contributions),
            "module_declines": _json_ready(self.module_declines),
            "penalties": _json_ready(self.penalties),
            "active_threshold_profile": _json_ready(self.active_threshold_profile),
            "decision_frame": _json_ready(self.decision_frame),
            "final_opportunity_score": _decimal_to_float(self.final_opportunity_score),
            "opportunity_verdict": self.opportunity_verdict,
            "execution_verdict": self.execution_verdict,
            "execution_blocker_reason_codes": self.execution_blocker_reason_codes,
            "broker_boundary_result": self.broker_boundary_result,
            "broker_post": self.broker_post,
            "final_outcome": self.final_outcome,
            "gates": tuple(gate.to_dict() for gate in self.gates),
        }


def build_candidate_lifecycle(
    *,
    candidate_id: str,
    symbol: str,
    side: str,
    source_sleeve: str,
    timestamp_ns: int,
    signal: Any | None = None,
    strategy_vote: Any | None = None,
    fusion: Any | None = None,
    market_truth: Mapping[str, Any] | None = None,
    candle_truth: Mapping[str, Any] | None = None,
    edge_attribution: Mapping[str, Any] | None = None,
    guardrail_verdict: Mapping[str, Any] | None = None,
    latency_truth: Mapping[str, Any] | None = None,
    active_threshold_profile: Mapping[str, Any] | None = None,
    decision_frame: Mapping[str, Any] | None = None,
    dispatch_evidence: Sequence[Mapping[str, Any]] = (),
) -> CandidateLifecycleRecord:
    market_snapshot = _merged_market_truth(market_truth, candle_truth)
    guardrail = dict(guardrail_verdict or {})
    latency = dict(latency_truth or {})
    reason_codes = _collect_reason_codes(guardrail, market_snapshot, latency)
    raw_score, module_contributions = _module_contributions(
        signal=signal,
        strategy_vote=strategy_vote,
        fusion=fusion,
        edge_attribution=edge_attribution,
        dispatch_evidence=dispatch_evidence,
    )
    module_declines = _module_declines(edge_attribution, dispatch_evidence)
    penalties = _build_penalties(market_snapshot, latency)
    threshold_profile = dict(active_threshold_profile or {})
    frame = dict(decision_frame or {})
    final_score = _clamp_score(raw_score + sum(_to_decimal(item.get("score_delta")) for item in penalties.values()))
    gates = (
        CandidateGate(
            gate="candidate_created",
            status=PASS,
            classification="candidate_lifecycle",
            reason_codes=(),
            evidence={"candidate_id": candidate_id, "source_sleeve": source_sleeve},
        ),
        _market_truth_gate(market_snapshot),
        CandidateGate(
            gate="strategy_module_evidence",
            status=PASS if module_contributions else DECLINED,
            classification="strategy_module_evidence",
            reason_codes=tuple(
                str(item.get("reason_code"))
                for item in dispatch_evidence
                if isinstance(item, Mapping) and item.get("status") == DECLINED and item.get("reason_code")
            ),
            evidence={
                "module_contributions": module_contributions,
                "module_declines": module_declines,
            },
        ),
        CandidateGate(
            gate="opportunity_scorecard",
            status=PASS,
            classification="opportunity_scoring",
            reason_codes=tuple(penalties),
            evidence={
                "raw_opportunity_score": _decimal_to_float(raw_score),
                "final_opportunity_score": _decimal_to_float(final_score),
                "penalties": penalties,
                "active_threshold_profile": threshold_profile,
                "decision_frame": frame,
            },
        ),
        CandidateGate(
            gate="decision_compiler_result",
            status=NOT_REACHED,
            classification="decision_compiler",
        ),
        _guardrail_gate(guardrail),
        CandidateGate(
            gate="execution_admission_result",
            status=NOT_REACHED,
            classification=EXECUTION_BLOCKER,
        ),
        CandidateGate(
            gate="broker_boundary_result",
            status=NOT_REACHED,
            classification="broker_boundary",
            evidence={"broker_post": False},
        ),
        CandidateGate(
            gate="final_outcome",
            status=NOT_REACHED,
            classification="candidate_outcome",
        ),
    )
    verdict = _opportunity_verdict(
        final_score=final_score,
        reason_codes=reason_codes,
        execution_blocked=False,
        broker_blocked=bool(_BROKER_AUTHORITY_REASON_CODES.intersection(reason_codes)),
    )
    return CandidateLifecycleRecord(
        candidate_id=str(candidate_id),
        symbol=str(symbol),
        side=str(side).lower(),
        source_sleeve=str(source_sleeve),
        timestamp_ns=int(timestamp_ns),
        gates=gates,
        module_contributions=module_contributions,
        module_declines=module_declines,
        penalties=penalties,
        active_threshold_profile=threshold_profile,
        decision_frame=frame,
        raw_opportunity_score=raw_score,
        final_opportunity_score=final_score,
        opportunity_verdict=verdict,
    )


def record_decision_compiler_result(
    record: CandidateLifecycleRecord | Mapping[str, Any],
    *,
    decision_record: Any,
) -> CandidateLifecycleRecord:
    lifecycle = _coerce_record(record)
    decision_uuid = getattr(decision_record, "decision_uuid", None)
    decision_type = getattr(decision_record, "decision_type", None)
    gates = _replace_gate(
        lifecycle.gates,
        CandidateGate(
            gate="decision_compiler_result",
            status=PASS,
            classification="decision_compiler",
            evidence={
                "decision_uuid": decision_uuid,
                "decision_type": getattr(decision_type, "value", decision_type),
            },
        ),
    )
    return replace(lifecycle, gates=gates)


def record_execution_result(
    record: CandidateLifecycleRecord | Mapping[str, Any],
    *,
    submitted: bool,
    execution_result: Any = None,
) -> CandidateLifecycleRecord:
    lifecycle = _coerce_record(record)
    reason_codes = _execution_reason_codes(execution_result)
    route = getattr(execution_result, "route", None) if execution_result is not None else None
    normalized_status = (
        str(getattr(execution_result, "normalized_status", "") or "")
        if execution_result is not None
        else ""
    )
    broker_post = bool(
        execution_result is not None
        and str(route or "") in {"alpaca_paper_rest", "broker_gateway"}
        and normalized_status not in {"", "blocked"}
        and getattr(execution_result, "client_order_id", None)
    )

    if submitted:
        execution_status = PASS
        execution_verdict = "ADMITTED"
        final_outcome = "EXECUTION_QUEUE_ADMITTED"
        broker_boundary = "ORDER_ROUTER_NOT_REACHED_ASYNC_QUEUE"
    elif execution_result is not None:
        execution_status = BLOCK
        execution_verdict = "BLOCKED"
        final_outcome = "EXECUTION_BLOCKED"
        broker_boundary = NOT_REACHED
    else:
        execution_status = NOT_REACHED
        execution_verdict = NOT_REACHED
        final_outcome = NOT_REACHED
        broker_boundary = NOT_REACHED

    if broker_post:
        broker_boundary = "BROKER_GATEWAY_REACHED"
        final_outcome = normalized_status.upper() if normalized_status else "BROKER_GATEWAY_REACHED"
    elif route == "order_router" or getattr(execution_result, "client_order_id", None):
        broker_boundary = "ORDER_ROUTER_REACHED"
        final_outcome = normalized_status.upper() if normalized_status else "ORDER_ROUTER_REACHED"
    elif route == "shadow_read_only":
        broker_boundary = "SHADOW_READ_ONLY_BLOCKED_BROKER_MUTATION"
        final_outcome = "BROKER_MUTATION_BLOCKED"

    blocker_classification = _blocker_classification(reason_codes)
    gates = lifecycle.gates
    gates = _replace_gate(
        gates,
        CandidateGate(
            gate="execution_admission_result",
            status=execution_status,
            classification=blocker_classification,
            reason_codes=reason_codes,
            evidence=_execution_evidence(execution_result),
        ),
    )
    gates = _replace_gate(
        gates,
        CandidateGate(
            gate="broker_boundary_result",
            status=PASS if broker_boundary not in {NOT_REACHED, "ORDER_ROUTER_NOT_REACHED_ASYNC_QUEUE"} else NOT_REACHED,
            classification="broker_boundary",
            reason_codes=reason_codes if broker_boundary != NOT_REACHED else (),
            evidence={
                "broker_boundary_result": broker_boundary,
                "broker_post": broker_post,
                "route": route,
                "normalized_status": normalized_status,
            },
        ),
    )
    gates = _replace_gate(
        gates,
        CandidateGate(
            gate="final_outcome",
            status=PASS if final_outcome not in {NOT_REACHED, "EXECUTION_BLOCKED"} else execution_status,
            classification="candidate_outcome",
            reason_codes=reason_codes,
            evidence={"final_outcome": final_outcome},
        ),
    )
    opportunity_verdict = _opportunity_verdict(
        final_score=lifecycle.final_opportunity_score,
        reason_codes=tuple(dict.fromkeys((*lifecycle.execution_blocker_reason_codes, *reason_codes))),
        execution_blocked=execution_verdict == "BLOCKED",
        broker_blocked=bool(_BROKER_AUTHORITY_REASON_CODES.intersection(reason_codes)),
    )
    return replace(
        lifecycle,
        gates=gates,
        opportunity_verdict=opportunity_verdict,
        execution_verdict=execution_verdict,
        execution_blocker_reason_codes=reason_codes,
        broker_boundary_result=broker_boundary,
        broker_post=broker_post,
        final_outcome=final_outcome,
    )


def lifecycle_to_dict(record: CandidateLifecycleRecord | Mapping[str, Any] | None) -> dict[str, Any]:
    if record is None:
        return {}
    return _coerce_record(record).to_dict()


def opportunity_scorecard_from_lifecycle(
    record: CandidateLifecycleRecord | Mapping[str, Any] | None,
) -> dict[str, Any]:
    lifecycle = lifecycle_to_dict(record)
    if not lifecycle:
        return {}
    return {
        "candidate_id": lifecycle["candidate_id"],
        "symbol": lifecycle["symbol"],
        "side": lifecycle["side"],
        "raw_opportunity_score": lifecycle["raw_opportunity_score"],
        "module_contributions": lifecycle["module_contributions"],
        "module_declines": lifecycle["module_declines"],
        "penalties": lifecycle["penalties"],
        "active_threshold_profile": lifecycle["active_threshold_profile"],
        "decision_frame": lifecycle["decision_frame"],
        "frame_id": lifecycle["decision_frame"].get("frame_id") if isinstance(lifecycle["decision_frame"], Mapping) else None,
        "frame_output": lifecycle["decision_frame"].get("frame_output") if isinstance(lifecycle["decision_frame"], Mapping) else None,
        "frame_status": lifecycle["decision_frame"].get("frame_status") if isinstance(lifecycle["decision_frame"], Mapping) else None,
        "frame_reason_codes": lifecycle["decision_frame"].get("frame_reason_codes") if isinstance(lifecycle["decision_frame"], Mapping) else None,
        "gate_trace": lifecycle["gates"],
        "final_opportunity_score": lifecycle["final_opportunity_score"],
        "opportunity_verdict": lifecycle["opportunity_verdict"],
        "execution_verdict": lifecycle["execution_verdict"],
        "execution_blocker_reason_codes": lifecycle["execution_blocker_reason_codes"],
        "broker_boundary_result": lifecycle["broker_boundary_result"],
        "broker_post": lifecycle["broker_post"],
    }


def _module_contributions(
    *,
    signal: Any | None,
    strategy_vote: Any | None,
    fusion: Any | None,
    edge_attribution: Mapping[str, Any] | None,
    dispatch_evidence: Sequence[Mapping[str, Any]],
) -> tuple[Decimal, dict[str, Any]]:
    numeric: list[Decimal] = []
    contributions: dict[str, Any] = {}

    signal_conf = _to_decimal(getattr(signal, "confidence", None))
    if signal_conf > Decimal("0"):
        numeric.append(signal_conf)
        contributions["StrategySignal"] = {
            "status": PASS,
            "score": _decimal_to_float(signal_conf),
            "strategy": getattr(signal, "strategy", None),
            "reason": getattr(signal, "reason", None),
        }

    vote_conf = _to_decimal(getattr(strategy_vote, "confidence", None))
    if vote_conf > Decimal("0"):
        numeric.append(vote_conf)
        contributions["StrategyVote"] = {
            "status": PASS,
            "score": _decimal_to_float(vote_conf),
            "strategy_id": str(getattr(strategy_vote, "strategy_id", "")),
            "signal": str(getattr(strategy_vote, "signal", "")),
        }

    fusion_conf = _to_decimal(getattr(fusion, "confidence", None))
    if fusion_conf > Decimal("0"):
        numeric.append(fusion_conf)
        contributions["SignalFusion"] = {
            "status": PASS,
            "score": _decimal_to_float(fusion_conf),
            "preferred_sleeve": getattr(fusion, "preferred_sleeve", None),
        }

    for item in dispatch_evidence:
        if not isinstance(item, Mapping):
            continue
        module = str(item.get("module") or item.get("sleeve") or "")
        if not module or item.get("status") != PASS:
            continue
        contributions.setdefault(module, _json_ready(item))

    for name, item in dict(edge_attribution or {}).items():
        if not isinstance(item, Mapping):
            continue
        status = str(item.get("status") or "")
        effect = str(item.get("effect") or "")
        if status in {"ACTIVE_NATIVE_SIGNAL", "PASSED", "ACTIVE_TRUTH_CHECK", "ACTIVE_GUARDRAIL"} or effect in {"RANKED", "APPROVED"}:
            contributions.setdefault(str(name), _json_ready(item))

    if not numeric:
        return Decimal("0"), contributions
    return _clamp_score(sum(numeric) / Decimal(len(numeric))), contributions


def _module_declines(
    edge_attribution: Mapping[str, Any] | None,
    dispatch_evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    declines: dict[str, Any] = {}
    for item in dispatch_evidence:
        if not isinstance(item, Mapping):
            continue
        module = str(item.get("module") or item.get("sleeve") or "")
        if module and item.get("status") in {DECLINED, BLOCK}:
            declines[module] = _json_ready(item)

    for name, item in dict(edge_attribution or {}).items():
        if not isinstance(item, Mapping):
            continue
        status = str(item.get("status") or "")
        effect = str(item.get("effect") or "")
        if status in {"MISSING_FEED_TRUTH", "DEGRADED_FALLBACK", "VETOED", "FAILED_CLOSED"} or effect in {"NO_EFFECT_WITH_REASON", "SKIPPED"}:
            declines.setdefault(str(name), _json_ready(item))
    return declines


def _build_penalties(
    market_truth: Mapping[str, Any],
    latency_truth: Mapping[str, Any],
) -> dict[str, Any]:
    penalties: dict[str, Any] = {}
    candle_code = str(market_truth.get("candle_freshness_reason_code") or "")
    data_code = str(market_truth.get("data_health_reason_code") or "")
    if candle_code in {"CANDLE_STALE"}:
        penalties["freshness_penalty"] = {
            "status": PENALTY,
            "score_delta": Decimal("-0.10"),
            "reason_code": candle_code,
            "evidence": _json_ready(market_truth),
        }
    elif candle_code in {"CANDLE_BATCH_BACKFILL_OBSERVE_ONLY"} or data_code in {"DATA_BACKFILL_OBSERVE_ONLY"}:
        penalties["freshness_penalty"] = {
            "status": PENALTY,
            "score_delta": Decimal("-0.15"),
            "reason_code": candle_code or data_code,
            "evidence": _json_ready(market_truth),
        }
    elif candle_code in {"CANDLE_NOT_CLOSED"} or data_code in {"DATA_RUNTIME_CANDLE_IN_PROGRESS"}:
        penalties["freshness_penalty"] = {
            "status": PENALTY,
            "score_delta": Decimal("-0.15"),
            "reason_code": candle_code or data_code,
            "evidence": _json_ready(market_truth),
        }
    elif candle_code in {"CANDLE_FRESHNESS_POLICY_MISSING", "CANDLE_TIMESTAMP_MISSING"} or data_code == "DATA_TIMESTAMP_MISSING":
        penalties["freshness_penalty"] = {
            "status": PENALTY,
            "score_delta": Decimal("-0.20"),
            "reason_code": candle_code or data_code,
            "evidence": _json_ready(market_truth),
        }

    latency_status = str(latency_truth.get("status") or "")
    latency_source = str(latency_truth.get("source") or "")
    if latency_status and latency_status != "LATENCY_OK":
        threshold = _to_decimal(latency_truth.get("threshold_ms"))
        latency_ms = _to_decimal(latency_truth.get("latency_ms"))
        if threshold > Decimal("0") and latency_ms > threshold:
            over_ratio = min(Decimal("1.0"), (latency_ms - threshold) / threshold)
            delta = -(Decimal("0.05") + (over_ratio * Decimal("0.10")))
        elif "market_data" in latency_source:
            delta = Decimal("-0.07")
        else:
            delta = Decimal("-0.10")
        penalties["latency_penalty"] = {
            "status": PENALTY,
            "score_delta": delta.quantize(Decimal("0.0001")),
            "reason_code": str(latency_truth.get("reason_code") or latency_status),
            "evidence": _json_ready(latency_truth),
        }
    return penalties


def _market_truth_gate(market_truth: Mapping[str, Any]) -> CandidateGate:
    candle_code = str(market_truth.get("candle_freshness_reason_code") or "")
    data_code = str(market_truth.get("data_health_reason_code") or "")
    snapshot_codes = market_truth.get("snapshot_reason_codes") or ()
    if isinstance(snapshot_codes, str):
        snapshot_codes = (snapshot_codes,)
    reason_codes = tuple(
        dict.fromkeys(
            code
            for code in (
                data_code,
                candle_code,
                *(str(code) for code in snapshot_codes if str(code)),
            )
            if code
        )
    )
    if market_truth.get("executable_market_truth") is True:
        status = PASS
        classification = "market_truth_snapshot"
    elif _DATA_TRUTH_REASON_CODES.intersection(reason_codes):
        status = PENALTY
        classification = OPPORTUNITY_PENALTY
    else:
        status = NOT_REACHED
        classification = "market_truth_snapshot"
    return CandidateGate(
        gate="market_truth_snapshot",
        status=status,
        classification=classification,
        reason_codes=reason_codes,
        evidence=_json_ready(market_truth),
    )


def _guardrail_gate(guardrail: Mapping[str, Any]) -> CandidateGate:
    if not guardrail:
        return CandidateGate(
            gate="pre_trade_guardrail_result",
            status=NOT_REACHED,
            classification=EXECUTION_BLOCKER,
            reason_codes=("PRE_TRADE_GUARDRAIL_MISSING",),
        )
    reason_codes = tuple(str(code) for code in guardrail.get("reason_codes", ()) if str(code))
    if guardrail.get("route_permitted") is True:
        status = PASS
        classification = "pre_trade_guardrail"
    else:
        status = BLOCK
        classification = _blocker_classification(reason_codes)
    return CandidateGate(
        gate="pre_trade_guardrail_result",
        status=status,
        classification=classification,
        reason_codes=reason_codes,
        evidence=_json_ready(guardrail),
    )


def _blocker_classification(reason_codes: Sequence[str]) -> str:
    codes = set(reason_codes)
    if codes.intersection(_FATAL_REASON_CODES):
        return FATAL_REJECT
    if codes.intersection(_BROKER_AUTHORITY_REASON_CODES):
        return BROKER_AUTHORITY_BLOCKER
    if codes.intersection(_EXECUTION_REASON_CODES):
        return EXECUTION_BLOCKER
    if codes.intersection(_DATA_TRUTH_REASON_CODES):
        return EXECUTION_BLOCKER
    return EXECUTION_BLOCKER if codes else "execution_admission"


def _opportunity_verdict(
    *,
    final_score: Decimal,
    reason_codes: Sequence[str],
    execution_blocked: bool,
    broker_blocked: bool,
) -> str:
    codes = set(reason_codes)
    if codes.intersection(_FATAL_REASON_CODES):
        return FATAL_REJECT
    if final_score >= _GOOD_SCORE and (execution_blocked or broker_blocked):
        return GOOD_CANDIDATE_NOT_EXECUTABLE
    if final_score >= _GOOD_SCORE:
        return GOOD_CANDIDATE_EXECUTABLE
    if final_score >= _PLAUSIBLE_SCORE:
        return PLAUSIBLE_CANDIDATE
    return WEAK_CANDIDATE


def _execution_reason_codes(execution_result: Any) -> tuple[str, ...]:
    if execution_result is None:
        return ()
    codes: list[str] = []
    reason = getattr(execution_result, "reason_code", None)
    if reason:
        codes.append(str(reason))
    guardrail = getattr(execution_result, "pre_trade_guardrail_verdict", None)
    if isinstance(guardrail, Mapping):
        codes.extend(str(code) for code in guardrail.get("reason_codes", ()) if str(code))
    evidence = getattr(execution_result, "block_evidence", None)
    if isinstance(evidence, Mapping):
        for key in ("latency_truth_reason_code", "data_health_reason_code", "candle_freshness_reason_code"):
            if evidence.get(key):
                codes.append(str(evidence[key]))
        snapshot_codes = evidence.get("snapshot_reason_codes") or ()
        if isinstance(snapshot_codes, str):
            snapshot_codes = (snapshot_codes,)
        codes.extend(str(code) for code in snapshot_codes if str(code))
    return tuple(dict.fromkeys(codes))


def _execution_evidence(execution_result: Any) -> dict[str, Any]:
    if execution_result is None:
        return {}
    evidence = {
        "normalized_status": getattr(execution_result, "normalized_status", None),
        "route": getattr(execution_result, "route", None),
        "reason_code": getattr(execution_result, "reason_code", None),
        "message": getattr(execution_result, "message", None),
        "client_order_id": getattr(execution_result, "client_order_id", None),
        "broker_order_id": getattr(execution_result, "broker_order_id", None),
    }
    block_evidence = getattr(execution_result, "block_evidence", None)
    if isinstance(block_evidence, Mapping):
        evidence["block_evidence"] = dict(block_evidence)
    return {key: value for key, value in evidence.items() if value is not None}


def _collect_reason_codes(
    guardrail: Mapping[str, Any],
    market_truth: Mapping[str, Any],
    latency_truth: Mapping[str, Any],
) -> tuple[str, ...]:
    codes: list[str] = []
    codes.extend(str(code) for code in guardrail.get("reason_codes", ()) if str(code))
    for key in ("data_health_reason_code", "candle_freshness_reason_code"):
        if market_truth.get(key):
            codes.append(str(market_truth[key]))
    snapshot_codes = market_truth.get("snapshot_reason_codes") or ()
    if isinstance(snapshot_codes, str):
        snapshot_codes = (snapshot_codes,)
    codes.extend(str(code) for code in snapshot_codes if str(code))
    for key in ("reason_code", "status"):
        if latency_truth.get(key):
            codes.append(str(latency_truth[key]))
    return tuple(dict.fromkeys(codes))


def _merged_market_truth(
    market_truth: Mapping[str, Any] | None,
    candle_truth: Mapping[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(market_truth or {})
    merged.update(dict(candle_truth or {}))
    return merged


def _replace_gate(gates: Sequence[CandidateGate], gate: CandidateGate) -> tuple[CandidateGate, ...]:
    replaced = False
    out: list[CandidateGate] = []
    for item in gates:
        if item.gate == gate.gate:
            out.append(gate)
            replaced = True
        else:
            out.append(item)
    if not replaced:
        out.append(gate)
    return tuple(out)


def _coerce_record(record: CandidateLifecycleRecord | Mapping[str, Any]) -> CandidateLifecycleRecord:
    if isinstance(record, CandidateLifecycleRecord):
        return record
    gates = tuple(
        CandidateGate(
            gate=str(item.get("gate")),
            status=str(item.get("status")),
            classification=str(item.get("classification")),
            reason_codes=tuple(str(code) for code in item.get("reason_codes", ()) if str(code)),
            evidence=dict(item.get("evidence") or {}),
        )
        for item in record.get("gates", ())
        if isinstance(item, Mapping)
    )
    return CandidateLifecycleRecord(
        candidate_id=str(record.get("candidate_id") or ""),
        symbol=str(record.get("symbol") or ""),
        side=str(record.get("side") or ""),
        source_sleeve=str(record.get("source_sleeve") or ""),
        timestamp_ns=int(record.get("timestamp_ns") or 0),
        gates=gates,
        module_contributions=dict(record.get("module_contributions") or {}),
        module_declines=dict(record.get("module_declines") or {}),
        penalties=dict(record.get("penalties") or {}),
        raw_opportunity_score=_to_decimal(record.get("raw_opportunity_score")),
        final_opportunity_score=_to_decimal(record.get("final_opportunity_score")),
        opportunity_verdict=str(record.get("opportunity_verdict") or WEAK_CANDIDATE),
        execution_verdict=str(record.get("execution_verdict") or NOT_REACHED),
        execution_blocker_reason_codes=tuple(
            str(code) for code in record.get("execution_blocker_reason_codes", ()) if str(code)
        ),
        broker_boundary_result=str(record.get("broker_boundary_result") or NOT_REACHED),
        broker_post=bool(record.get("broker_post", False)),
        final_outcome=str(record.get("final_outcome") or NOT_REACHED),
        active_threshold_profile=dict(record.get("active_threshold_profile") or {}),
        decision_frame=dict(record.get("decision_frame") or {}),
    )


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _clamp_score(value: Decimal) -> Decimal:
    if value < Decimal("0"):
        return Decimal("0")
    if value > Decimal("1"):
        return Decimal("1")
    return value.quantize(Decimal("0.0001"))


def _decimal_to_float(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.0001")))


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
    "PASS",
    "BLOCK",
    "NOT_REACHED",
    "PENALTY",
    "DECLINED",
    "FATAL_REJECT",
    "EXECUTION_BLOCKER",
    "BROKER_AUTHORITY_BLOCKER",
    "GOOD_CANDIDATE_NOT_EXECUTABLE",
    "CandidateLifecycleRecord",
    "build_candidate_lifecycle",
    "opportunity_scorecard_from_lifecycle",
    "record_decision_compiler_result",
    "record_execution_result",
    "lifecycle_to_dict",
]
