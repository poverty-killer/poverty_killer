from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping, Sequence

from app.core.decision_compiler import DecisionCompiler
from app.core.truth_kernel import TruthKernel, TruthKernelStateError
from app.core.truth_reconciler import TruthReconciler
from app.execution.engine import ExecutionSpineResult
from app.market.capability_registry import VenueCapabilityRegistry, build_default_capability_registry
from app.market.venue_capabilities import (
    CapabilityAwareCandidate,
    PortalEnvironment,
    PortalPolicyMode,
    PortalSelectionRequest,
    classify_quote_session,
)
from app.models import StrategySignal
from app.models.contracts import (
    ExchangeOpenOrder,
    ExchangePosition,
    ExchangeTruth,
    ExecutionTruth,
    PortfolioPosition,
    PortfolioTruth,
    RiskTruth,
    StrategyTruth,
    StrategyTruthEntry,
    SubmittedOrder,
    TruthFrame,
)
from app.models.enums import InternalOrderStatus, OrderSide, RiskMode, StrategyID, TruthStatus
from app.risk.pre_trade_guardrails import PreTradeGuardrailRequest, evaluate_pre_trade_guardrails
from app.state.invariant_checker import InvariantChecker
from app.utils.time_utils import now_ns


STRATEGY_MISSING_FEED_TRUTH = "STRATEGY_MISSING_FEED_TRUTH"
INTELLIGENCE_MISSING_FEED_TRUTH = "INTELLIGENCE_MISSING_FEED_TRUTH"
INTEGRATED_STATE_READY = "INTEGRATED_STATE_READY"
INTEGRATED_STATE_DEGRADED_MISSING_TRUTH = "INTEGRATED_STATE_DEGRADED_MISSING_TRUTH"
INTEGRATED_STATE_BLOCKED = "INTEGRATED_STATE_BLOCKED"
INTEGRATED_STATE_CORRUPTED = "INTEGRATED_STATE_CORRUPTED"


@dataclass(frozen=True, slots=True)
class StrategyModuleEvidence:
    module_name: str
    status: str
    reason_codes: tuple[str, ...]
    symbol: str | None = None
    side: str | None = None
    confidence: Decimal | None = None
    source_data_requirements: tuple[str, ...] = ()
    timestamp_ns: int = 0
    signal: StrategySignal | None = None


@dataclass(frozen=True, slots=True)
class IntelligenceEvidence:
    engine_name: str
    status: str
    reason_codes: tuple[str, ...]
    missing_sources: tuple[str, ...] = ()
    advisory: bool = True
    blocked: bool = False
    timestamp_ns: int = 0


@dataclass(frozen=True, slots=True)
class FusionRankingArtifact:
    status: str
    reason_codes: tuple[str, ...]
    strategy_evidence: tuple[StrategyModuleEvidence, ...]
    intelligence_evidence: tuple[IntelligenceEvidence, ...]
    ranked_symbols: tuple[str, ...]
    selected_symbol: str | None


@dataclass(frozen=True, slots=True)
class CandidateArtifact:
    status: str
    reason_codes: tuple[str, ...]
    symbol: str | None
    side: str | None
    source_modules: tuple[str, ...]
    fusion: FusionRankingArtifact
    capability_identity: Mapping[str, Any]
    guardrail_verdict: Mapping[str, Any] | None
    signal: StrategySignal | None


@dataclass(frozen=True, slots=True)
class StateMutationResult:
    recorded_events: tuple[str, ...]
    failed_events: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReservationLifecycleResult:
    status: str
    reason_codes: tuple[str, ...]
    opened: bool = False
    released: bool = False
    bound_position: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    status: str
    reason_codes: tuple[str, ...]
    local_positions: tuple[str, ...]
    broker_positions: tuple[str, ...]
    local_open_orders: tuple[str, ...]
    broker_open_orders: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExposureUpdateResult:
    status: str
    reason_codes: tuple[str, ...]
    reserved_buying_power: Decimal
    active_reservations: int
    tracked_positions: int


@dataclass(frozen=True, slots=True)
class TruthKernelResult:
    status: str
    reason_codes: tuple[str, ...]
    truth_frame: TruthFrame | None = None


@dataclass(frozen=True, slots=True)
class InvariantValidationResult:
    status: str
    reason_codes: tuple[str, ...]
    violation_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NormalizedIntegrationResult:
    strategy_status: str
    intelligence_status: str
    candidate: CandidateArtifact
    guardrail_verdict: Mapping[str, Any] | None
    execution_status: str
    execution_result: ExecutionSpineResult | None
    reconciliation: ReconciliationResult
    state_mutation: StateMutationResult
    reservation_lifecycle: ReservationLifecycleResult
    exposure: ExposureUpdateResult
    truth_kernel: TruthKernelResult
    invariant_checker: InvariantValidationResult
    final_machine_status: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BrokerTruthSnapshot:
    positions: tuple[Mapping[str, Any], ...] = ()
    open_orders: tuple[Mapping[str, Any], ...] = ()
    balances: Mapping[str, Any] = field(default_factory=dict)
    account: Mapping[str, Any] = field(default_factory=dict)
    fills: tuple[Mapping[str, Any], ...] = ()
    receive_ts_ns: int = 0
    fixture_truth: bool = True


@dataclass(frozen=True, slots=True)
class Seam5CycleRequest:
    symbol: str
    timestamp_ns: int
    current_price: Decimal
    asset_class: str
    strategy_modules: Mapping[str, Any] = field(default_factory=dict)
    intelligence_engines: Mapping[str, Any] = field(default_factory=dict)
    strategy_signals: Sequence[StrategySignal] = ()
    broker_truth: BrokerTruthSnapshot = field(default_factory=BrokerTruthSnapshot)
    execution_result_fixture: ExecutionSpineResult | None = None
    state_store: Any | None = None
    exposure_manager: Any | None = None
    reservation_lifecycle_coordinator: Any | None = None
    decision_compiler: DecisionCompiler | None = None
    execution_engine: Any | None = None
    preferred_portal: str = "alpaca_paper"
    portal_policy: str = PortalPolicyMode.EXPLICIT_PREFERRED_VENUE.value
    allow_execution: bool = False
    max_notional: Decimal = Decimal("5.00")


class StrategyEvidenceAdapter:
    def collect(
        self,
        *,
        symbol: str,
        timestamp_ns: int,
        modules: Mapping[str, Any],
        strategy_signals: Sequence[StrategySignal],
    ) -> tuple[StrategyModuleEvidence, ...]:
        evidence: list[StrategyModuleEvidence] = []
        signal_by_strategy = {
            str(getattr(signal, "strategy", "")).lower(): signal
            for signal in strategy_signals
        }
        required_modules = ("moving_floor", "shadow_front", "adaptive_dc")
        all_names = tuple(dict.fromkeys([*required_modules, *modules.keys()]))
        for name in all_names:
            module = modules.get(name)
            signal = signal_by_strategy.get(name) or self._pending_signal(module)
            if signal is not None and getattr(signal, "symbol", symbol) == symbol and getattr(signal, "side", "hold") != "hold":
                confidence = _decimal_or_none(getattr(signal, "confidence", None))
                evidence.append(
                    StrategyModuleEvidence(
                        module_name=name,
                        status="ACTIONABLE_SIGNAL",
                        reason_codes=("STRATEGY_SIGNAL_PRESENT",),
                        symbol=symbol,
                        side=str(getattr(signal, "side", "")),
                        confidence=confidence,
                        timestamp_ns=timestamp_ns,
                        signal=signal,
                    )
                )
                continue
            if module is None:
                reason = STRATEGY_MISSING_FEED_TRUTH
            elif name == "moving_floor":
                reason = "MOVING_FLOOR_MISSING_MARKET_TICK"
            elif name == "adaptive_dc":
                reason = "ADAPTIVE_DC_MISSING_MARKET_TICK"
            elif name == "shadow_front":
                reason = "SHADOW_FRONT_MISSING_WHALE_OR_SENTIMENT_FEED"
            else:
                reason = STRATEGY_MISSING_FEED_TRUTH
            evidence.append(
                StrategyModuleEvidence(
                    module_name=name,
                    status="MISSING_TRUTH",
                    reason_codes=(reason, STRATEGY_MISSING_FEED_TRUTH),
                    symbol=symbol,
                    source_data_requirements=self._requirements_for(name),
                    timestamp_ns=timestamp_ns,
                )
            )
        return tuple(evidence)

    @staticmethod
    def _pending_signal(module: Any) -> StrategySignal | None:
        signal = getattr(module, "_pending_signal", None)
        return signal if isinstance(signal, StrategySignal) else None

    @staticmethod
    def _requirements_for(module_name: str) -> tuple[str, ...]:
        if module_name == "moving_floor":
            return ("floor_market_tick", "book_integrity", "risk_context")
        if module_name == "shadow_front":
            return ("whale_flow", "sentiment_velocity", "position_sizing")
        if module_name == "adaptive_dc":
            return ("dc_market_tick", "risk_context")
        return ("strategy_feed",)


class IntelligenceEvidenceAdapter:
    def collect(
        self,
        *,
        symbol: str,
        timestamp_ns: int,
        engines: Mapping[str, Any],
    ) -> tuple[IntelligenceEvidence, ...]:
        required = ("whale_flow", "toxicity", "regime_detector")
        names = tuple(dict.fromkeys([*required, *engines.keys()]))
        evidence: list[IntelligenceEvidence] = []
        for name in names:
            engine = engines.get(name)
            present = engine is not None and self._has_truth(engine, name)
            if present:
                evidence.append(
                    IntelligenceEvidence(
                        engine_name=name,
                        status="ADVISORY_TRUTH_AVAILABLE",
                        reason_codes=("INTELLIGENCE_TRUTH_AVAILABLE",),
                        advisory=True,
                        timestamp_ns=timestamp_ns,
                    )
                )
                continue
            evidence.append(
                IntelligenceEvidence(
                    engine_name=name,
                    status="MISSING_TRUTH",
                    reason_codes=(self._missing_reason(name), INTELLIGENCE_MISSING_FEED_TRUTH),
                    missing_sources=self._missing_sources(name),
                    advisory=True,
                    blocked=False,
                    timestamp_ns=timestamp_ns,
                )
            )
        return tuple(evidence)

    @staticmethod
    def _has_truth(engine: Any, name: str) -> bool:
        if name == "whale_flow":
            return getattr(engine, "_last_alert", None) is not None
        if name == "toxicity":
            getter = getattr(engine, "get_last_alert", None)
            return callable(getter) and getter() is not None
        if name == "regime_detector":
            return str(getattr(engine, "_last_regime", "UNKNOWN")).upper() != "UNKNOWN"
        return False

    @staticmethod
    def _missing_reason(name: str) -> str:
        return {
            "whale_flow": "WHALE_FLOW_MISSING_FEED",
            "toxicity": "TOXICITY_MISSING_FEED",
            "regime_detector": "REGIME_MISSING_TRUTH",
        }.get(name, INTELLIGENCE_MISSING_FEED_TRUTH)

    @staticmethod
    def _missing_sources(name: str) -> tuple[str, ...]:
        return {
            "whale_flow": ("trade_prints", "buy_sell_volume"),
            "toxicity": ("trade_flow", "candle_or_l2_proxy"),
            "regime_detector": ("price_volume_depth_history",),
        }.get(name, ("intelligence_feed",))


class SignalFusionCandidateSelector:
    def __init__(self, *, capability_registry: VenueCapabilityRegistry | None = None) -> None:
        self.capability_registry = capability_registry or build_default_capability_registry()

    def build_artifact(
        self,
        strategies: tuple[StrategyModuleEvidence, ...],
        intelligence: tuple[IntelligenceEvidence, ...],
    ) -> FusionRankingArtifact:
        actionable = [item for item in strategies if item.status == "ACTIONABLE_SIGNAL" and item.symbol]
        ranked = tuple(dict.fromkeys(item.symbol for item in actionable if item.symbol))
        if ranked:
            status = "FUSION_ACTIONABLE"
            reasons = ("FUSION_SELECTED_FROM_STRATEGY_EVIDENCE",)
            selected = ranked[0]
        else:
            status = "FUSION_DEGRADED_MISSING_TRUTH"
            reasons = ("NO_ACTIONABLE_STRATEGY_SIGNAL", "MISSING_TRUTH_PROPAGATED")
            selected = None
        if any(item.status == "MISSING_TRUTH" for item in intelligence):
            reasons = tuple(dict.fromkeys([*reasons, INTELLIGENCE_MISSING_FEED_TRUTH]))
        return FusionRankingArtifact(status, reasons, strategies, intelligence, ranked, selected)

    def select_candidate(
        self,
        *,
        fusion: FusionRankingArtifact,
        asset_class: str,
        current_price: Decimal,
        max_notional: Decimal,
        preferred_portal: str,
        portal_policy: str,
    ) -> CandidateArtifact:
        source_signal = next((item.signal for item in fusion.strategy_evidence if item.signal is not None), None)
        if fusion.selected_symbol is None or source_signal is None:
            return CandidateArtifact(
                status="CANDIDATE_BLOCKED",
                reason_codes=("NO_STRATEGY_FUSION_CANDIDATE",),
                symbol=None,
                side=None,
                source_modules=tuple(item.module_name for item in fusion.strategy_evidence),
                fusion=fusion,
                capability_identity={},
                guardrail_verdict=None,
                signal=None,
            )
        registry = self.capability_registry
        capability_request = PortalSelectionRequest(
            symbol=fusion.selected_symbol,
            asset_class=asset_class,
            environment=PortalEnvironment.PAPER.value,
            action=str(source_signal.side),
            order_type="limit",
            time_in_force=None,
            policy_mode=portal_policy,
            preferred_venue=preferred_portal,
            allow_fallback=False,
        )
        portal_result = registry.resolve(capability_request)
        capability = portal_result.selected
        if capability is not None:
            capability_request = PortalSelectionRequest(
                symbol=fusion.selected_symbol,
                asset_class=asset_class,
                environment=PortalEnvironment.PAPER.value,
                action=str(source_signal.side),
                order_type="limit",
                time_in_force=capability.default_time_in_force,
                policy_mode=portal_policy,
                preferred_venue=preferred_portal,
                allow_fallback=False,
            )
            portal_result = registry.resolve(capability_request)
            capability = portal_result.selected
        quote = None
        if capability is not None:
            quote = classify_quote_session(
                CapabilityAwareCandidate.from_capability(capability, tradable=True),
                market_session_open=None if asset_class == "crypto" else True,
                quote_present=current_price > Decimal("0"),
                quote_fresh=True,
            )
        quantity = _decimal_or_none(getattr(source_signal, "quantity", None)) or Decimal("0")
        guardrail = evaluate_pre_trade_guardrails(
            PreTradeGuardrailRequest(
                symbol=fusion.selected_symbol,
                side=str(source_signal.side),
                order_type="limit",
                time_in_force=capability.default_time_in_force if capability is not None else None,
                quantity=quantity,
                limit_price=current_price,
                current_price=current_price,
                internal_max_notional=max_notional,
                capability=capability,
                portal_selection_result=portal_result,
                quote_classification=quote,
            )
        ).to_dict()
        status = "CANDIDATE_GUARDRAIL_ALLOWED" if guardrail["route_permitted"] else "CANDIDATE_GUARDRAIL_BLOCKED"
        return CandidateArtifact(
            status=status,
            reason_codes=tuple(guardrail["reason_codes"]),
            symbol=fusion.selected_symbol,
            side=str(source_signal.side),
            source_modules=tuple(item.module_name for item in fusion.strategy_evidence if item.status == "ACTIONABLE_SIGNAL"),
            fusion=fusion,
            capability_identity=dict(guardrail.get("capability_identity") or {}),
            guardrail_verdict=guardrail,
            signal=source_signal,
        )


class IntelligencePortfolioStateTruthSpine:
    def __init__(
        self,
        *,
        strategy_adapter: StrategyEvidenceAdapter | None = None,
        intelligence_adapter: IntelligenceEvidenceAdapter | None = None,
        candidate_selector: SignalFusionCandidateSelector | None = None,
        capability_registry: VenueCapabilityRegistry | None = None,
        truth_reconciler: TruthReconciler | None = None,
        truth_kernel: TruthKernel | None = None,
        invariant_checker: InvariantChecker | None = None,
    ) -> None:
        self.strategy_adapter = strategy_adapter or StrategyEvidenceAdapter()
        self.intelligence_adapter = intelligence_adapter or IntelligenceEvidenceAdapter()
        self.candidate_selector = candidate_selector or SignalFusionCandidateSelector(
            capability_registry=capability_registry,
        )
        self.truth_reconciler = truth_reconciler or TruthReconciler()
        self.truth_kernel = truth_kernel or TruthKernel()
        self.invariant_checker = invariant_checker or InvariantChecker()

    def run_cycle(self, request: Seam5CycleRequest) -> NormalizedIntegrationResult:
        strategies = self.strategy_adapter.collect(
            symbol=request.symbol,
            timestamp_ns=request.timestamp_ns,
            modules=request.strategy_modules,
            strategy_signals=request.strategy_signals,
        )
        intelligence = self.intelligence_adapter.collect(
            symbol=request.symbol,
            timestamp_ns=request.timestamp_ns,
            engines=request.intelligence_engines,
        )
        fusion = self.candidate_selector.build_artifact(strategies, intelligence)
        candidate = self.candidate_selector.select_candidate(
            fusion=fusion,
            asset_class=request.asset_class,
            current_price=request.current_price,
            max_notional=request.max_notional,
            preferred_portal=request.preferred_portal,
            portal_policy=request.portal_policy,
        )
        state_events: list[str] = []
        failed_events: list[str] = []
        self._record_event(request.state_store, "decision_created", {"symbol": request.symbol}, state_events, failed_events)

        execution_result = self._execute_or_fixture(request, candidate)
        execution_status = self._execution_status(execution_result, candidate)

        if candidate.guardrail_verdict and not candidate.guardrail_verdict.get("route_permitted", False):
            self._record_event(request.state_store, "candidate_blocked", candidate.guardrail_verdict, state_events, failed_events)
        elif execution_result is not None:
            self._record_event(request.state_store, f"order_{execution_status}", _execution_dict(execution_result), state_events, failed_events)

        reservation = self._apply_reservation_lifecycle(request, candidate, execution_result)
        if reservation.status != "NOT_APPLICABLE":
            self._record_event(request.state_store, "reservation_lifecycle", _dataclass_dict(reservation), state_events, failed_events)

        if execution_status == "filled" and candidate.signal is not None:
            self._bind_filled_position(request, candidate, execution_result, state_events, failed_events)

        reconciliation = self._reconcile(request, execution_result)
        exposure = self._exposure_update(request)
        truth = self._run_truth_kernel(request, reconciliation)
        invariants = self._run_invariants(request, truth.truth_frame, reconciliation, execution_result)
        self._record_event(request.state_store, "reconciliation_snapshot", _dataclass_dict(reconciliation), state_events, failed_events)
        self._record_event(request.state_store, "invariant_validation_result", _dataclass_dict(invariants), state_events, failed_events)

        final_status = self._final_status(candidate, reconciliation, truth, invariants)
        reasons = tuple(dict.fromkeys([
            *candidate.reason_codes,
            *reconciliation.reason_codes,
            *truth.reason_codes,
            *invariants.reason_codes,
        ]))
        return NormalizedIntegrationResult(
            strategy_status=fusion.status,
            intelligence_status="INTELLIGENCE_DEGRADED" if any(i.status == "MISSING_TRUTH" for i in intelligence) else "INTELLIGENCE_READY",
            candidate=candidate,
            guardrail_verdict=candidate.guardrail_verdict,
            execution_status=execution_status,
            execution_result=execution_result,
            reconciliation=reconciliation,
            state_mutation=StateMutationResult(tuple(state_events), tuple(failed_events)),
            reservation_lifecycle=reservation,
            exposure=exposure,
            truth_kernel=truth,
            invariant_checker=invariants,
            final_machine_status=final_status,
            reason_codes=reasons,
        )

    def _execute_or_fixture(
        self,
        request: Seam5CycleRequest,
        candidate: CandidateArtifact,
    ) -> ExecutionSpineResult | None:
        if candidate.guardrail_verdict and not candidate.guardrail_verdict.get("route_permitted", False):
            return None
        if request.execution_result_fixture is not None:
            return request.execution_result_fixture
        if not request.allow_execution or request.execution_engine is None or candidate.signal is None:
            return None
        compiler = request.decision_compiler or DecisionCompiler()
        truth = self._truth_frame_for_request(request, TruthStatus.RECONCILED, ())
        decision = compiler.compile(
            truth_frame=truth,
            strategy_votes=[],
            additional_inputs={
                "seam5_candidate": {
                    "symbol": candidate.symbol,
                    "source_modules": candidate.source_modules,
                },
                "pre_trade_guardrail_verdict": candidate.guardrail_verdict,
            },
        )
        signal = candidate.signal.model_copy(
            update={
                "metadata": {
                    **(candidate.signal.metadata or {}),
                    "pre_trade_guardrail_verdict": candidate.guardrail_verdict,
                    **dict(candidate.capability_identity),
                }
            }
        )
        return request.execution_engine.execute_compiled_decision(
            decision,
            signal,
            current_price=request.current_price,
            is_attack=True,
        )

    @staticmethod
    def _execution_status(result: ExecutionSpineResult | None, candidate: CandidateArtifact) -> str:
        if result is None:
            if candidate.guardrail_verdict and not candidate.guardrail_verdict.get("route_permitted", False):
                return "blocked"
            return "not_submitted"
        return str(result.normalized_status)

    def _apply_reservation_lifecycle(
        self,
        request: Seam5CycleRequest,
        candidate: CandidateArtifact,
        result: ExecutionSpineResult | None,
    ) -> ReservationLifecycleResult:
        if result is None or request.reservation_lifecycle_coordinator is None or candidate.signal is None:
            return ReservationLifecycleResult("NOT_APPLICABLE", ("NO_RESERVATION_ACTION",))
        status = str(result.normalized_status)
        client_id = result.client_order_id or f"seam5:{candidate.symbol}:{request.timestamp_ns}"
        if status in {"accepted", "open"}:
            details = request.reservation_lifecycle_coordinator.on_order_acknowledged(
                client_order_id=client_id,
                symbol=candidate.symbol or request.symbol,
                side=candidate.side or "buy",
                sleeve=getattr(candidate.signal, "strategy", "seam5"),
                qty=candidate.signal.quantity,
                price_basis=request.current_price,
                order_type="limit",
                decision_uuid=result.decision_uuid,
                price_basis_source_proven=True,
                source_lifecycle_phase="seam5_order_open",
            )
            return ReservationLifecycleResult("OPENED", ("RESERVATION_OPENED",), opened=bool(details.get("applied")), details=details)
        if status == "rejected":
            details = request.reservation_lifecycle_coordinator.on_rejected_before_ack(client_order_id=client_id)
            return ReservationLifecycleResult("REJECTED_NO_LOCK", ("REJECTION_NO_ACTIVE_RESERVATION_LOCK",), details=details)
        if status == "filled":
            ack = request.reservation_lifecycle_coordinator.on_order_acknowledged(
                client_order_id=client_id,
                symbol=candidate.symbol or request.symbol,
                side=candidate.side or "buy",
                sleeve=getattr(candidate.signal, "strategy", "seam5"),
                qty=candidate.signal.quantity,
                price_basis=request.current_price,
                order_type="limit",
                decision_uuid=result.decision_uuid,
                price_basis_source_proven=True,
                source_lifecycle_phase="seam5_pre_fill_ack",
            )
            fill = request.reservation_lifecycle_coordinator.on_full_fill(
                client_order_id=client_id,
                release_idempotency_key=f"{client_id}:seam5_full_fill:{request.timestamp_ns}",
                cumulative_filled_qty=candidate.signal.quantity,
                terminal_source="seam5_fixture_execution_result",
                source_event_id=f"{client_id}:filled",
            )
            return ReservationLifecycleResult(
                "BOUND_POSITION",
                ("RESERVATION_RELEASED_ON_FILL", "POSITION_BOUND"),
                opened=bool(ack.get("applied")),
                released=bool(fill.get("applied") or fill.get("idempotent")),
                bound_position=True,
                details={"ack": ack, "fill": fill},
            )
        return ReservationLifecycleResult("UNKNOWN_REQUIRES_RECONCILIATION", ("UNKNOWN_REQUIRES_RECONCILIATION",))

    def _bind_filled_position(
        self,
        request: Seam5CycleRequest,
        candidate: CandidateArtifact,
        result: ExecutionSpineResult | None,
        state_events: list[str],
        failed_events: list[str],
    ) -> None:
        if request.state_store is None or candidate.symbol is None or candidate.signal is None:
            return
        position_id = f"seam5:{candidate.symbol}:{result.client_order_id if result else request.timestamp_ns}"
        ok = request.state_store.insert_position(
            {
                "id": position_id,
                "symbol": candidate.symbol,
                "side": "long",
                "quantity": float(candidate.signal.quantity),
                "entry_price": float(request.current_price),
                "current_price": float(request.current_price),
                "unrealized_pnl": 0.0,
                "realized_pnl": 0.0,
                "strategy": candidate.signal.strategy,
                "opened_at": str(request.timestamp_ns),
                "updated_at": str(request.timestamp_ns),
                "last_strategy_heartbeat": str(request.timestamp_ns),
                "exchange": "fixture" if request.broker_truth.fixture_truth else "broker",
                "entry_latency_ms": None,
            }
        )
        (state_events if ok else failed_events).append("position_bound")

    def _reconcile(self, request: Seam5CycleRequest, result: ExecutionSpineResult | None) -> ReconciliationResult:
        local_positions = tuple(sorted(str(row.get("symbol", "")).upper() for row in (request.state_store.get_positions() if request.state_store else []) if row.get("symbol")))
        broker_positions = tuple(sorted(str(row.get("symbol", "")).upper() for row in request.broker_truth.positions if row.get("symbol")))
        local_orders = tuple(sorted(str(row.get("client_order_id") or row.get("id") or "") for row in (request.state_store.list_reservation_ledger(active_only=True, include_terminal=False) if request.state_store else []) if row))
        broker_orders = tuple(sorted(str(row.get("client_order_id") or row.get("id") or "") for row in request.broker_truth.open_orders if row))
        reasons: list[str] = []
        if set(local_positions) - set(broker_positions) and not request.broker_truth.fixture_truth:
            reasons.append("LOCAL_BROKER_POSITION_MISMATCH")
        if set(local_orders) - set(broker_orders) and result is not None and str(result.normalized_status) in {"accepted", "open"} and not request.broker_truth.fixture_truth:
            reasons.append("LOCAL_BROKER_OPEN_ORDER_MISMATCH")
        if not reasons:
            reasons.append("RECONCILIATION_MATCH_OR_FIXTURE_SCOPED")
        status = "DISCREPANCY" if any("MISMATCH" in reason for reason in reasons) else "RECONCILED"
        return ReconciliationResult(status, tuple(reasons), local_positions, broker_positions, local_orders, broker_orders)

    @staticmethod
    def _exposure_update(request: Seam5CycleRequest) -> ExposureUpdateResult:
        reservations = request.exposure_manager.reservations_for() if request.exposure_manager is not None else []
        positions = request.state_store.get_positions() if request.state_store is not None else []
        reserved = Decimal("0")
        for row in request.state_store.list_reservation_ledger(active_only=True, include_terminal=False) if request.state_store is not None else []:
            notional = _decimal_or_none(row.get("notional_basis"))
            if notional is not None:
                reserved += notional
        return ExposureUpdateResult("EXPOSURE_UPDATED", ("EXPOSURE_RECONCILED_FROM_STATE",), reserved, len(reservations), len(positions))

    def _run_truth_kernel(
        self,
        request: Seam5CycleRequest,
        reconciliation: ReconciliationResult,
    ) -> TruthKernelResult:
        status = TruthStatus.RECONCILED if reconciliation.status == "RECONCILED" else TruthStatus.DRIFTING
        divergence_reasons = () if status == TruthStatus.RECONCILED else reconciliation.reason_codes
        frame = self._truth_frame_for_request(request, status, divergence_reasons)
        try:
            self.truth_kernel.update_exchange_truth(frame.exchange_truth)
            self.truth_kernel.update_execution_truth(frame.execution_truth)
            self.truth_kernel.update_portfolio_truth(frame.portfolio_truth)
            self.truth_kernel.update_strategy_truth(frame.strategy_truth)
            self.truth_kernel.update_risk_truth(frame.risk_truth)
            self.truth_kernel.create_truth_frame(
                status=status,
                divergence_ns=0 if status == TruthStatus.RECONCILED else 1,
                divergence_reasons=list(divergence_reasons),
            )
            return TruthKernelResult("PASS" if status == TruthStatus.RECONCILED else "WARNING", ("TRUTH_KERNEL_RAN",), frame)
        except TruthKernelStateError as exc:
            return TruthKernelResult("MISSING_TRUTH", ("TRUTH_KERNEL_MISSING_TRUTH", str(exc)), frame)

    def _run_invariants(
        self,
        request: Seam5CycleRequest,
        frame: TruthFrame | None,
        reconciliation: ReconciliationResult,
        execution_result: ExecutionSpineResult | None,
    ) -> InvariantValidationResult:
        violations: list[str] = []
        if frame is not None:
            batch = self.invariant_checker.evaluate(frame)
            violations.extend(result.invariant_id for result in batch.results if not result.passed)
        active = request.state_store.list_reservation_ledger(active_only=True, include_terminal=False) if request.state_store else []
        broker_open = {str(row.get("client_order_id") or row.get("id") or "") for row in request.broker_truth.open_orders}
        broker_open_ids = [str(row.get("client_order_id") or row.get("id") or "") for row in request.broker_truth.open_orders if row.get("client_order_id") or row.get("id")]
        local_open_ids = [str(row.get("client_order_id") or "") for row in active if row.get("client_order_id")]
        if len(broker_open_ids) != len(set(broker_open_ids)) or len(local_open_ids) != len(set(local_open_ids)):
            violations.append("DUPLICATE_ORDER_ID")
        for row in active:
            notional = _decimal_or_none(row.get("notional_basis"))
            if notional is not None and notional < Decimal("0"):
                violations.append("NEGATIVE_RESERVED_CAPITAL")
        if not request.broker_truth.fixture_truth and request.broker_truth.receive_ts_ns <= 0:
            violations.append("STALE_TRUTH_MARKED_CURRENT")
        if not request.broker_truth.fixture_truth:
            for row in active:
                if str(row.get("client_order_id")) not in broker_open:
                    violations.append("OPEN_RESERVATION_WITHOUT_BROKER_ORDER")
        if execution_result is not None and str(execution_result.normalized_status) == "filled":
            if request.state_store is not None and not request.state_store.get_positions():
                violations.append("FILLED_ORDER_WITHOUT_BOUND_POSITION")
        if reconciliation.status == "DISCREPANCY":
            violations.append("LOCAL_BROKER_MISMATCH")
        status = "CORRUPTED" if violations else "PASS"
        return InvariantValidationResult(status, ("INVARIANT_CHECKER_RAN",), tuple(dict.fromkeys(violations)))

    def _truth_frame_for_request(
        self,
        request: Seam5CycleRequest,
        status: TruthStatus,
        reasons: tuple[str, ...],
    ) -> TruthFrame:
        exchange_positions = [
            ExchangePosition(
                symbol=str(row.get("symbol")),
                side="long",
                quantity=_decimal_or_none(row.get("qty") or row.get("quantity")) or Decimal("0"),
                entry_price=_decimal_or_none(row.get("avg_entry_price") or row.get("average_entry_price") or row.get("entry_price")) or request.current_price,
            )
            for row in request.broker_truth.positions
            if row.get("symbol")
        ]
        exchange_orders = []
        for row in request.broker_truth.open_orders:
            quantity = _decimal_or_none(row.get("qty") or row.get("quantity"))
            if not (row.get("id") or row.get("client_order_id")) or quantity is None or quantity <= 0:
                continue
            exchange_orders.append(
                ExchangeOpenOrder(
                    order_id=str(row.get("id") or row.get("client_order_id")),
                    symbol=str(row.get("symbol") or request.symbol),
                    side=OrderSide.BUY,
                    quantity=quantity,
                    limit_price=_decimal_or_none(row.get("limit_price")),
                    client_order_id=row.get("client_order_id"),
                    broker_order_id=row.get("id"),
                )
            )
        local_positions_raw = request.state_store.get_positions() if request.state_store else []
        portfolio_positions = [
            PortfolioPosition(
                symbol=str(row.get("symbol")),
                quantity=_decimal_or_none(row.get("quantity")) or Decimal("0"),
                avg_price=_decimal_or_none(row.get("entry_price")) or request.current_price,
                mark_price=_decimal_or_none(row.get("current_price")) or request.current_price,
                unrealized_pnl=_decimal_or_none(row.get("unrealized_pnl")) or Decimal("0"),
            )
            for row in local_positions_raw
            if row.get("symbol")
        ]
        active_reservations = request.state_store.list_reservation_ledger(active_only=True, include_terminal=False) if request.state_store else []
        submitted = [
            SubmittedOrder(
                client_order_id=str(row.get("client_order_id")),
                status=InternalOrderStatus.SUBMITTED,
                submitted_ts_ns=int(row.get("created_at_ns") or request.timestamp_ns),
            )
            for row in active_reservations
        ]
        return TruthFrame(
            timestamp_ns=request.timestamp_ns,
            exchange_truth=ExchangeTruth(
                venue=request.preferred_portal,
                balances={k: _decimal_or_none(v) or Decimal("0") for k, v in request.broker_truth.balances.items()},
                positions=exchange_positions,
                open_orders=exchange_orders,
                exchange_ts_ns=request.broker_truth.receive_ts_ns or request.timestamp_ns,
            ),
            execution_truth=ExecutionTruth(submitted_orders=submitted, last_reconciliation_ts_ns=request.timestamp_ns),
            portfolio_truth=PortfolioTruth(
                cash={},
                positions=portfolio_positions,
                reserved_buying_power=sum((_decimal_or_none(row.get("notional_basis")) or Decimal("0")) for row in active_reservations),
                total_equity=Decimal("0"),
                last_update_ts_ns=request.timestamp_ns,
            ),
            strategy_truth=StrategyTruth(
                active_strategies=[
                    StrategyTruthEntry(strategy_id=StrategyID.SHADOW_FRONT, state="seam5_integrated")
                ],
                last_update_ts_ns=request.timestamp_ns,
            ),
            risk_truth=RiskTruth(mode=RiskMode.NORMAL),
            status=status,
            divergence_ns=0 if status == TruthStatus.RECONCILED else 1,
            divergence_reasons=list(reasons),
        )

    @staticmethod
    def _record_event(store: Any | None, event_type: str, data: Mapping[str, Any], recorded: list[str], failed: list[str]) -> None:
        if store is None:
            return
        ok = store.log_event(event_type=f"seam5.{event_type}", source="intelligence_portfolio_state_truth_spine", data=_json_ready(data))
        (recorded if ok else failed).append(event_type)

    @staticmethod
    def _final_status(
        candidate: CandidateArtifact,
        reconciliation: ReconciliationResult,
        truth: TruthKernelResult,
        invariants: InvariantValidationResult,
    ) -> str:
        if invariants.status == "CORRUPTED":
            return INTEGRATED_STATE_CORRUPTED
        if candidate.status.endswith("BLOCKED") or reconciliation.status == "DISCREPANCY":
            return INTEGRATED_STATE_BLOCKED
        if truth.status in {"MISSING_TRUTH", "WARNING"} or candidate.fusion.status.endswith("MISSING_TRUTH"):
            return INTEGRATED_STATE_DEGRADED_MISSING_TRUTH
        return INTEGRATED_STATE_READY


def _execution_dict(result: ExecutionSpineResult) -> dict[str, Any]:
    return {
        "decision_uuid": result.decision_uuid,
        "client_order_id": result.client_order_id,
        "broker_order_id": result.broker_order_id,
        "normalized_status": result.normalized_status,
        "route": result.route,
        "reason_code": result.reason_code,
    }


def _dataclass_dict(value: Any) -> dict[str, Any]:
    return {name: _json_ready(getattr(value, name)) for name in getattr(value, "__dataclass_fields__", {})}


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return _dataclass_dict(value)
    return value
