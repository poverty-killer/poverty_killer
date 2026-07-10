from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from app.market.venue_capabilities import (
    CapabilityAwareCandidate,
    PortalEnvironment,
    PortalSelectionResult,
    QuoteClassificationCode,
    QuoteSessionClassification,
    VenueCapability,
)
from app.risk.stale_data_guard import StaleDataGuard, TemporalInput
from app.utils.enums import is_blocking_risk_action


ALLOW = "ALLOW"
BLOCK = "BLOCK"
REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
ADJUSTMENT_REQUIRED = "ADJUSTMENT_REQUIRED"
ADVISORY_ONLY = "ADVISORY_ONLY"

CONTRIBUTED_ALLOW = "CONTRIBUTED_ALLOW"
CONTRIBUTED_BLOCK = "CONTRIBUTED_BLOCK"
CONTRIBUTED_REQUIRE_APPROVAL = "CONTRIBUTED_REQUIRE_APPROVAL"
CONTRIBUTED_ADVISORY = "CONTRIBUTED_ADVISORY"
CONTRIBUTED_MISSING_TRUTH = "CONTRIBUTED_MISSING_TRUTH"
DORMANT_BY_POLICY = "DORMANT_BY_POLICY"
NOT_CONFIGURED = "NOT_CONFIGURED"
NOT_AUTHORIZED = "NOT_AUTHORIZED"
BLOCKED_UNSAFE_TO_ACTIVATE = "BLOCKED_UNSAFE_TO_ACTIVATE"


_BLOCKING_QUOTE_CODES = {
    QuoteClassificationCode.MARKET_CLOSED.value,
    QuoteClassificationCode.SESSION_CLOSED_STALE_QUOTE.value,
    QuoteClassificationCode.QUOTE_MISSING.value,
    QuoteClassificationCode.QUOTE_STALE.value,
    QuoteClassificationCode.QUOTE_WIDE_SPREAD.value,
    QuoteClassificationCode.CAPABILITY_UNSUPPORTED.value,
    QuoteClassificationCode.SYMBOL_UNSUPPORTED.value,
    QuoteClassificationCode.VENUE_UNSUPPORTED.value,
    QuoteClassificationCode.CREDENTIALS_MISSING.value,
    QuoteClassificationCode.ADAPTER_MISSING.value,
}


@dataclass(frozen=True, slots=True)
class GuardrailEvidence:
    module: str
    status: str
    reason_code: str
    summary: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "status": self.status,
            "reason_code": self.reason_code,
            "summary": self.summary,
            "details": _json_ready(self.details),
        }


@dataclass(frozen=True, slots=True)
class PreTradeGuardrailRequest:
    symbol: str
    side: str
    order_type: str
    time_in_force: str | None
    quantity: Decimal
    limit_price: Decimal | None
    current_price: Decimal | None = None
    internal_max_notional: Decimal | None = None
    capability: VenueCapability | None = None
    portal_selection_result: PortalSelectionResult | None = None
    quote_classification: QuoteSessionClassification | None = None
    existing_positions: Sequence[Mapping[str, Any]] = ()
    open_orders: Sequence[Mapping[str, Any]] = ()
    reservations: Sequence[Mapping[str, Any]] = ()
    add_on_allowed: bool = False
    approval_present: bool = False
    protective_context: Mapping[str, Any] | None = None
    economics_context: Mapping[str, Any] | None = None
    strategy_context: Mapping[str, Any] | None = None
    exposure_authority_evidence: Mapping[str, Any] | None = None
    stale_data_observation: TemporalInput | Mapping[str, Any] | None = None
    source: str = "pre_trade_guardrails"
    action: str | None = None


@dataclass(frozen=True, slots=True)
class PreTradeGuardrailVerdict:
    verdict: str
    route_permitted: bool
    mutation_permitted: bool
    reason_codes: tuple[str, ...]
    symbol: str
    side: str
    action: str | None
    order_type: str
    time_in_force: str | None
    requested_notional: Decimal | None
    internal_max_notional: Decimal | None
    broker_min_notional: Decimal | None
    capability_identity: Mapping[str, Any]
    module_evidence: tuple[GuardrailEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "route_permitted": self.route_permitted,
            "mutation_permitted": self.mutation_permitted,
            "reason_codes": self.reason_codes,
            "symbol": self.symbol,
            "side": self.side,
            "action": self.action,
            "order_type": self.order_type,
            "time_in_force": self.time_in_force,
            "requested_notional": _decimal_to_string(self.requested_notional),
            "internal_max_notional": _decimal_to_string(self.internal_max_notional),
            "broker_min_notional": _decimal_to_string(self.broker_min_notional),
            "capability_identity": _json_ready(self.capability_identity),
            "module_evidence": [item.to_dict() for item in self.module_evidence],
        }


def evaluate_pre_trade_guardrails(request: PreTradeGuardrailRequest) -> PreTradeGuardrailVerdict:
    evidence: list[GuardrailEvidence] = []
    reasons: list[str] = []
    approval_reasons: list[str] = []
    adjustment_reasons: list[str] = []

    capability = request.capability
    selected = capability
    portal_result = request.portal_selection_result
    if selected is None and portal_result is not None:
        selected = portal_result.selected

    capability_identity = _capability_identity(selected)
    requested_notional = _requested_notional(request)
    broker_min_notional = selected.min_notional if selected is not None else None

    if selected is None:
        portal_reasons = _portal_block_reasons(portal_result)
        reasons.extend(portal_reasons)
        evidence.append(
            GuardrailEvidence(
                module="portal_selection_policy",
                status=CONTRIBUTED_BLOCK,
                reason_code=portal_reasons[0],
                summary="No selected paper execution portal is available for this order intent.",
                details={"portal_status": getattr(portal_result, "status", None)},
            )
        )
    else:
        selection_reasons = _capability_block_reasons(selected, request)
        if selection_reasons:
            reasons.extend(selection_reasons)
            evidence.append(
                GuardrailEvidence(
                    module="capability_registry / venue_capabilities",
                    status=CONTRIBUTED_BLOCK,
                    reason_code=selection_reasons[0],
                    summary="Venue capability metadata does not permit the requested order shape.",
                    details=capability_identity,
                )
            )
        else:
            evidence.append(
                GuardrailEvidence(
                    module="capability_registry / venue_capabilities",
                    status=CONTRIBUTED_ALLOW,
                    reason_code="ORDER_CONSTRAINTS_SUPPORTED",
                    summary="Venue, portal, environment, asset class, order type, and TIF are supported.",
                    details=capability_identity,
                )
            )

    quote = request.quote_classification
    if quote is None:
        reasons.append("QUOTE_SESSION_TRUTH_MISSING")
        evidence.append(
            GuardrailEvidence(
                module="quote/market data path",
                status=CONTRIBUTED_MISSING_TRUTH,
                reason_code="QUOTE_SESSION_TRUTH_MISSING",
                summary="No fresh quote/session classification was supplied to the pre-trade guardrail.",
            )
        )
    else:
        quote_reasons = tuple(code for code in quote.reason_codes if code in _BLOCKING_QUOTE_CODES)
        if quote_reasons or not quote.tradable_now:
            block_code = quote_reasons[0] if quote_reasons else "QUOTE_SESSION_NOT_TRADABLE"
            reasons.append(block_code)
            evidence.append(
                GuardrailEvidence(
                    module="quote/market data path",
                    status=CONTRIBUTED_BLOCK,
                    reason_code=block_code,
                    summary="Quote/session classification blocked pre-trade routing.",
                    details={
                        "session_state": quote.session_state,
                        "reason_codes": quote.reason_codes,
                    },
                )
            )
        else:
            evidence.append(
                GuardrailEvidence(
                    module="quote/market data path",
                    status=CONTRIBUTED_ALLOW,
                    reason_code="FRESH_QUOTE_AVAILABLE",
                    summary="Fresh market data and tradable session were available.",
                    details={"session_state": quote.session_state},
                )
            )

    stale_guard_reason = _append_stale_data_guard_evidence(evidence, request)
    if stale_guard_reason:
        reasons.append(stale_guard_reason)

    if requested_notional is None:
        reasons.append("REQUESTED_NOTIONAL_MISSING")
        evidence.append(
            GuardrailEvidence(
                module="sizing/risk cap",
                status=CONTRIBUTED_BLOCK,
                reason_code="REQUESTED_NOTIONAL_MISSING",
                summary="Order notional could not be computed without quantity and price truth.",
            )
        )
    elif broker_min_notional is not None and request.internal_max_notional is not None and request.internal_max_notional < broker_min_notional:
        reasons.append("RISK_MAX_BELOW_BROKER_MIN")
        evidence.append(
            GuardrailEvidence(
                module="sizing/risk cap",
                status=CONTRIBUTED_BLOCK,
                reason_code="RISK_MAX_BELOW_BROKER_MIN",
                summary="Internal max notional is below the broker minimum; routing would guarantee rejection.",
                details={
                    "internal_max_notional": request.internal_max_notional,
                    "broker_min_notional": broker_min_notional,
                    "requested_notional": requested_notional,
                },
            )
        )
    elif request.internal_max_notional is not None and requested_notional > request.internal_max_notional:
        reasons.append("REQUESTED_NOTIONAL_ABOVE_INTERNAL_MAX")
        evidence.append(
            GuardrailEvidence(
                module="sizing/risk cap",
                status=CONTRIBUTED_BLOCK,
                reason_code="REQUESTED_NOTIONAL_ABOVE_INTERNAL_MAX",
                summary="Requested notional is above the internal risk cap for this order.",
                details={
                    "requested_notional": requested_notional,
                    "internal_max_notional": request.internal_max_notional,
                },
            )
        )
    elif broker_min_notional is not None and requested_notional < broker_min_notional:
        reasons.append("BROKER_MIN_NOTIONAL_NOT_MET")
        evidence.append(
            GuardrailEvidence(
                module="sizing/risk cap",
                status=CONTRIBUTED_BLOCK,
                reason_code="BROKER_MIN_NOTIONAL_NOT_MET",
                summary="Requested notional is below the broker minimum.",
                details={
                    "requested_notional": requested_notional,
                    "broker_min_notional": broker_min_notional,
                },
            )
        )
    else:
        evidence.append(
            GuardrailEvidence(
                module="sizing/risk cap",
                status=CONTRIBUTED_ALLOW,
                reason_code="SIZING_WITHIN_KNOWN_LIMITS",
                summary="Requested notional satisfies known internal and broker notional constraints.",
                details={
                    "requested_notional": requested_notional,
                    "internal_max_notional": request.internal_max_notional,
                    "broker_min_notional": broker_min_notional,
                },
            )
        )

    quantity_reasons = _quantity_reasons(selected, request.quantity)
    if quantity_reasons:
        reasons.extend(quantity_reasons)
        evidence.append(
            GuardrailEvidence(
                module="order constraint layer",
                status=CONTRIBUTED_BLOCK,
                reason_code=quantity_reasons[0],
                summary="Quantity does not satisfy venue quantity constraints.",
                details={
                    "quantity": request.quantity,
                    "min_quantity": getattr(selected, "min_quantity", None),
                    "quantity_step": getattr(selected, "quantity_step", None),
                },
            )
        )

    exposure_reason = _append_exposure_authority_evidence(evidence, request)
    if exposure_reason:
        reasons.append(exposure_reason)

    protective_context = request.protective_context or {}
    if protective_context.get("block_reason"):
        reasons.append(str(protective_context["block_reason"]))

    _append_advisory_evidence(evidence, request, blocked=bool(reasons))

    unique_reasons = tuple(dict.fromkeys(reasons))
    unique_approval_reasons = tuple(dict.fromkeys(approval_reasons))
    unique_adjustment_reasons = tuple(dict.fromkeys(adjustment_reasons))

    if unique_reasons:
        verdict = BLOCK
    elif unique_approval_reasons:
        verdict = REQUIRE_APPROVAL
        unique_reasons = unique_approval_reasons
    elif unique_adjustment_reasons:
        verdict = ADJUSTMENT_REQUIRED
        unique_reasons = unique_adjustment_reasons
    else:
        verdict = ALLOW
        unique_reasons = ("PRE_TRADE_GUARDRAILS_ALLOW",)

    permitted = verdict == ALLOW
    return PreTradeGuardrailVerdict(
        verdict=verdict,
        route_permitted=permitted,
        mutation_permitted=permitted,
        reason_codes=unique_reasons,
        symbol=request.symbol,
        side=request.side.lower(),
        action=_request_action(request),
        order_type=request.order_type.lower(),
        time_in_force=request.time_in_force.upper() if request.time_in_force else None,
        requested_notional=requested_notional,
        internal_max_notional=request.internal_max_notional,
        broker_min_notional=broker_min_notional,
        capability_identity=capability_identity,
        module_evidence=tuple(evidence),
    )


def _portal_block_reasons(portal_result: PortalSelectionResult | None) -> tuple[str, ...]:
    if portal_result is None:
        return ("NO_USABLE_PORTAL",)
    reasons: list[str] = list(portal_result.reason_codes)
    candidate_by_key = {candidate.capability_key: candidate for candidate in portal_result.candidates}
    wildcard_reasons: list[str] = []
    specific_reasons: list[str] = []
    for capability_key, rejected_reasons in portal_result.rejected.items():
        candidate = candidate_by_key.get(capability_key)
        if candidate is not None and candidate.normalized_symbol == "*":
            wildcard_reasons.extend(rejected_reasons)
        else:
            specific_reasons.extend(rejected_reasons)
    reasons.extend(specific_reasons or wildcard_reasons)
    return tuple(dict.fromkeys(reasons or ["NO_USABLE_PORTAL"]))


def _capability_block_reasons(capability: VenueCapability, request: PreTradeGuardrailRequest) -> tuple[str, ...]:
    reasons: list[str] = []
    if capability.environment == PortalEnvironment.LIVE.value or capability.live_mutation:
        reasons.append("LIVE_MODE_BLOCKED")
    if capability.live_blocked and capability.environment == PortalEnvironment.LIVE.value:
        reasons.append("LIVE_BLOCKED")
    if capability.credential_status == "missing":
        reasons.append("CREDENTIALS_MISSING")
    if capability.execution_adapter in {"", "missing", None}:
        reasons.append("ADAPTER_MISSING")
    if capability.disabled_reason:
        reasons.append(capability.disabled_reason)
    if capability.unavailable_reason:
        reasons.append(capability.unavailable_reason)
    if _request_action(request) not in capability.supported_actions:
        reasons.append("ACTION_UNSUPPORTED")
    if request.order_type.lower() not in capability.supported_order_types:
        reasons.append("ORDER_TYPE_UNSUPPORTED")
    if request.time_in_force and request.time_in_force.upper() not in capability.supported_time_in_force:
        reasons.append("TIME_IN_FORCE_UNSUPPORTED")
    if capability.environment != PortalEnvironment.PAPER.value:
        reasons.append("NON_PAPER_ENVIRONMENT_BLOCKED")
    if not capability.paper_mutation:
        reasons.append("PAPER_MUTATION_UNSUPPORTED")
    return tuple(dict.fromkeys(reasons))


def _quantity_reasons(capability: VenueCapability | None, quantity: Decimal) -> tuple[str, ...]:
    if capability is None:
        return ()
    reasons: list[str] = []
    if quantity <= Decimal("0"):
        reasons.append("QUANTITY_NOT_POSITIVE")
    if capability.min_quantity is not None and quantity < capability.min_quantity:
        reasons.append("MIN_QUANTITY_NOT_MET")
    step = capability.quantity_step
    if step is not None and step > Decimal("0"):
        try:
            remainder = quantity % step
        except InvalidOperation:
            remainder = Decimal("0")
        if remainder != Decimal("0"):
            reasons.append("QUANTITY_STEP_UNSUPPORTED")
    return tuple(dict.fromkeys(reasons))


def _append_stale_data_guard_evidence(
    evidence: list[GuardrailEvidence],
    request: PreTradeGuardrailRequest,
) -> str | None:
    observation = _coerce_temporal_input(request.stale_data_observation)
    if observation is None:
        evidence.append(
            GuardrailEvidence(
                module="StaleDataGuard",
                status=CONTRIBUTED_MISSING_TRUTH,
                reason_code="STALE_DATA_GUARD_OBSERVATION_MISSING",
                summary=(
                    "No temporal observation was supplied to StaleDataGuard; the guard did not "
                    "invent market freshness truth."
                ),
                details={"required_by_active_path": request.source == "main_loop_dispatch"},
            )
        )
        if request.source == "main_loop_dispatch":
            return "STALE_DATA_GUARD_OBSERVATION_MISSING"
        return None

    assessment = StaleDataGuard(symbol=request.symbol).assess(observation)
    action = assessment.risk_action
    blocking = is_blocking_risk_action(action)
    reason_code = _stale_guard_reason_code(assessment, blocking=blocking)
    evidence.append(
        GuardrailEvidence(
            module="StaleDataGuard",
            status=CONTRIBUTED_BLOCK if blocking else CONTRIBUTED_ALLOW,
            reason_code=reason_code,
            summary=(
                "StaleDataGuard assessed temporal market-data integrity and vetoed routing."
                if blocking
                else "StaleDataGuard assessed temporal market-data integrity and allowed routing."
            ),
            details={
                "risk_action": getattr(action, "value", str(action)),
                "risk_level": getattr(assessment.risk_level, "value", str(assessment.risk_level)),
                "severity": getattr(assessment.severity, "value", str(assessment.severity)),
                "authority_tier": getattr(assessment.authority_tier, "value", str(assessment.authority_tier)),
                "priority": getattr(assessment.priority, "value", str(assessment.priority)),
                "rationale": assessment.rationale,
                "warnings": assessment.warnings,
                "drift_ns": assessment.kinematics.drift_ns,
                "current_ts_ns": observation.current_ts_ns,
                "exchange_ts_ns": observation.exchange_ts_ns,
                "local_received_ts_ns": observation.local_received_ts_ns,
                "max_drift_ms": 500,
                "mutation_authority": False,
            },
        )
    )
    return reason_code if blocking else None


def _coerce_temporal_input(value: TemporalInput | Mapping[str, Any] | None) -> TemporalInput | None:
    if isinstance(value, TemporalInput):
        return value
    if not isinstance(value, Mapping):
        return None
    current_ts_ns = _to_int(value.get("current_ts_ns") or value.get("snapshot_created_ns"))
    exchange_ts_ns = _to_int(
        value.get("exchange_ts_ns")
        or value.get("candle_close_ts_ns")
        or value.get("candle_id")
        or value.get("latest_candle_ts_ns")
    )
    if current_ts_ns is None or exchange_ts_ns is None:
        return None
    local_received_ts_ns = _to_int(value.get("local_received_ts_ns") or value.get("receive_ts_ns"))
    return TemporalInput(
        current_ts_ns=current_ts_ns,
        exchange_ts_ns=exchange_ts_ns,
        local_received_ts_ns=local_received_ts_ns,
    )


def _stale_guard_reason_code(assessment: Any, *, blocking: bool) -> str:
    if not blocking:
        return "STALE_DATA_GUARD_ALLOW"
    first_rationale = next((str(item) for item in assessment.rationale if str(item)), "")
    if "absolute_drift_limit_breach" in first_rationale:
        return "STALE_DATA_GUARD_ABSOLUTE_DRIFT_LIMIT_BREACH"
    if first_rationale.startswith("invariant_violation:"):
        return "STALE_DATA_GUARD_INVARIANT_VIOLATION"
    action = getattr(assessment.risk_action, "value", str(assessment.risk_action))
    return f"STALE_DATA_GUARD_{_sanitize_reason(action)}"


def _sanitize_reason(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in str(value).upper())
    return "_".join(part for part in cleaned.split("_") if part) or "BLOCK"


def _requested_notional(request: PreTradeGuardrailRequest) -> Decimal | None:
    price = request.limit_price if request.limit_price is not None else request.current_price
    if price is None:
        return None
    if request.quantity <= Decimal("0") or price <= Decimal("0"):
        return None
    return abs(request.quantity * price)


def _append_exposure_authority_evidence(
    evidence: list[GuardrailEvidence],
    request: PreTradeGuardrailRequest,
) -> str | None:
    authority = request.exposure_authority_evidence
    if not isinstance(authority, Mapping):
        evidence.append(
            GuardrailEvidence(
                module="ExposureManager",
                status=CONTRIBUTED_MISSING_TRUTH,
                reason_code="EXPOSURE_MANAGER_EVIDENCE_MISSING",
                summary="Canonical portfolio-risk authority evidence was not supplied to the guardrail.",
                details={
                    "required_by_active_path": request.source == "main_loop_dispatch",
                    "source": request.source,
                    "note": "ExecutionEngine fails closed for broker-intent orders that require this evidence.",
                },
            )
        )
        return None

    status = str(authority.get("status") or CONTRIBUTED_MISSING_TRUTH)
    reason = str(authority.get("reason_code") or "EXPOSURE_MANAGER_UNKNOWN")
    evidence.append(
        GuardrailEvidence(
            module="ExposureManager",
            status=status,
            reason_code=reason,
            summary=str(authority.get("summary") or "ExposureManager supplied canonical portfolio-risk evidence."),
            details=authority,
        )
    )
    if status == CONTRIBUTED_BLOCK or authority.get("route_permitted") is False or authority.get("authorized") is False:
        return reason
    return None


def _append_advisory_evidence(
    evidence: list[GuardrailEvidence],
    request: PreTradeGuardrailRequest,
    *,
    blocked: bool,
) -> None:
    protective = request.protective_context or {}
    if protective.get("block_reason"):
        evidence.append(
            GuardrailEvidence(
                module="protective modules/council",
                status=CONTRIBUTED_BLOCK,
                reason_code=str(protective["block_reason"]),
                summary="Protective module supplied an explicit block reason.",
            )
        )
    else:
        evidence.append(
            GuardrailEvidence(
                module="protective modules/council",
                status=CONTRIBUTED_ADVISORY,
                reason_code="PROTECTIVE_INTENT_METADATA_ONLY",
                summary="Protective/council metadata is recorded as advisory and has no broker mutation authority.",
            )
        )

    economics = request.economics_context or {}
    if economics.get("verified") is True:
        evidence.append(
            GuardrailEvidence(
                module="economics advisory",
                status=CONTRIBUTED_ADVISORY,
                reason_code="ECONOMICS_ADVISORY_RECORDED",
                summary="Economic advisory metadata was supplied but remains non-authoritative.",
            )
        )
    else:
        evidence.append(
            GuardrailEvidence(
                module="economics advisory",
                status=CONTRIBUTED_MISSING_TRUTH,
                reason_code="ECONOMICS_ADVISORY_MISSING_TRUTH",
                summary="No verified economic truth was supplied; no PnL, slippage, edge, or profitability is invented.",
            )
        )

    for module, reason in (
        ("NetEdgeGovernor", "NET_EDGE_MISSING_TRUTH"),
        ("TradeEfficiencyGovernor", "TRADE_EFFICIENCY_MISSING_TRUTH"),
    ):
        evidence.append(
            GuardrailEvidence(
                module=module,
                status=CONTRIBUTED_MISSING_TRUTH,
                reason_code=reason,
                summary="Governor is represented in the verdict without inventing missing market/economic truth.",
            )
        )

    evidence.append(
        GuardrailEvidence(
            module="SovereignExecutionGuard",
            status=DORMANT_BY_POLICY,
            reason_code="SOVEREIGN_EXECUTION_GUARD_DORMANT_PENDING_PHASE_HI_ARM",
            summary=(
                "SovereignExecutionGuard is a mutation-capable capital authorization model and "
                "stays intentionally dormant until live-arming policy authorizes it."
            ),
            details={
                "bucket": "mutation_capable_dormant_by_policy",
                "broker_mutation_authority": False,
                "execution_authorization_authority": False,
                "phase_required": "Phase H/I live arming",
            },
        )
    )
    evidence.append(
        GuardrailEvidence(
            module="StrategyAllocator / SovereignGovernor",
            status=CONTRIBUTED_ADVISORY,
            reason_code="ALLOCATOR_GOVERNOR_DELEGATED_TO_EXPOSURE_MANAGER",
            summary="Portfolio heat, concentration, and correlation authority is delegated to ExposureManager.",
        )
    )
    evidence.append(
        GuardrailEvidence(
            module="DecisionCompiler",
            status=CONTRIBUTED_ADVISORY,
            reason_code="GUARDRAIL_VERDICT_ATTACHED_TO_DECISION_INPUTS",
            summary="DecisionCompiler receives the guardrail verdict as evidence, not as a second execution authority.",
        )
    )
    evidence.append(
        GuardrailEvidence(
            module="ExecutionEngine",
            status=CONTRIBUTED_BLOCK if blocked else CONTRIBUTED_ALLOW,
            reason_code=(
                "EXECUTION_ENGINE_BLOCKS_BEFORE_ROUTER"
                if blocked
                else "EXECUTION_ENGINE_ENFORCES_ROUTE_PERMITTED"
            ),
            summary="ExecutionEngine enforces the pre-trade verdict before OrderRouter.",
        )
    )


def _capability_identity(capability: VenueCapability | None) -> dict[str, Any]:
    if capability is None:
        return {}
    return {
        "venue_id": capability.venue_id,
        "portal_name": capability.portal_name,
        "environment": capability.environment,
        "asset_class": capability.asset_class,
        "symbol": capability.symbol,
        "execution_adapter": capability.execution_adapter,
        "reconciliation_adapter": capability.reconciliation_adapter,
        "capability_key": capability.capability_key,
        "supported_order_types": sorted(capability.supported_order_types),
        "supported_actions": sorted(capability.supported_actions),
        "supported_time_in_force": sorted(capability.supported_time_in_force),
        "default_order_type": capability.default_order_type,
        "default_time_in_force": capability.default_time_in_force,
        "order_constraint_source": capability.order_constraint_source,
    }


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _request_action(request: PreTradeGuardrailRequest) -> str:
    return str(request.action or request.side or "").lower()


def _decimal_to_string(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


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
