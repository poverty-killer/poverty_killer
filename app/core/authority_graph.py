"""Read-only final-decision authority graph.

This module names ownership boundaries. It intentionally stores module names as
strings instead of importing the modules it describes, so inspecting the graph
cannot mutate broker, OMS, strategy, risk, credential, or runtime state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


AUTHORITY_GRAPH_VERSION = "authority-graph-v1"

AuthorityName = Literal[
    "market_truth",
    "risk_gates",
    "sizing",
    "broker_order_lifecycle",
    "portfolio_position_truth",
    "ai_advisory",
    "ui_display",
]

ContributorStatus = Literal["WIRED", "BLOCKED", "REJECTED_PRESERVED", "PRESERVED_DEAD"]

ORDERED_AUTHORITIES: tuple[AuthorityName, ...] = (
    "market_truth",
    "risk_gates",
    "sizing",
    "broker_order_lifecycle",
    "portfolio_position_truth",
    "ai_advisory",
    "ui_display",
)

EXPECTED_PHASE_B_CONFLICT_IDS = frozenset(range(1, 10))


@dataclass(frozen=True, slots=True)
class AuthorityOwner:
    authority: AuthorityName
    module: str
    path: str
    final_decision: str
    allowed_scope: str
    blocked_scope: tuple[str, ...]
    phase_b_conflict_ids: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "module": self.module,
            "path": self.path,
            "final_decision": self.final_decision,
            "final_decision_owner": True,
            "allowed_scope": self.allowed_scope,
            "blocked_scope": self.blocked_scope,
            "phase_b_conflict_ids": self.phase_b_conflict_ids,
        }


@dataclass(frozen=True, slots=True)
class AuthorityContributor:
    authority: AuthorityName
    module: str
    path: str
    role: str
    contribution: str
    boundary: str
    status: ContributorStatus
    blocked_reason: str | None = None
    phase_b_conflict_ids: tuple[int, ...] = ()
    can_override_owner: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "module": self.module,
            "path": self.path,
            "role": self.role,
            "contribution": self.contribution,
            "boundary": self.boundary,
            "status": self.status,
            "blocked_reason": self.blocked_reason,
            "phase_b_conflict_ids": self.phase_b_conflict_ids,
            "can_override_owner": self.can_override_owner,
        }


@dataclass(frozen=True, slots=True)
class AuthorityEntry:
    owner: AuthorityOwner
    contributors: tuple[AuthorityContributor, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.owner.authority,
            "owner": self.owner.to_dict(),
            "contributors": [item.to_dict() for item in self.contributors],
        }


@dataclass(frozen=True, slots=True)
class ConflictResolution:
    conflict_id: int
    seam: str
    final_owner: str
    reference_module: str
    status: ContributorStatus
    boundary: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "seam": self.seam,
            "final_owner": self.final_owner,
            "reference_module": self.reference_module,
            "status": self.status,
            "boundary": self.boundary,
            "reason": self.reason,
        }


def _contributor(
    authority: AuthorityName,
    module: str,
    path: str,
    role: str,
    contribution: str,
    boundary: str,
    *,
    status: ContributorStatus = "WIRED",
    blocked_reason: str | None = None,
    conflict_ids: tuple[int, ...] = (),
) -> AuthorityContributor:
    return AuthorityContributor(
        authority=authority,
        module=module,
        path=path,
        role=role,
        contribution=contribution,
        boundary=boundary,
        status=status,
        blocked_reason=blocked_reason,
        phase_b_conflict_ids=conflict_ids,
    )


AUTHORITY_GRAPH: dict[AuthorityName, AuthorityEntry] = {
    "market_truth": AuthorityEntry(
        owner=AuthorityOwner(
            authority="market_truth",
            module="app.core.market_snapshot.MarketTruthSnapshot",
            path="app/core/market_snapshot.py",
            final_decision="executable market truth snapshot for execution admission",
            allowed_scope=(
                "Build and validate canonical runtime MarketTruthSnapshot; stale, synthetic, "
                "backfill, replay, mismatched, or missing data stays non-executable."
            ),
            blocked_scope=(
                "inventing market truth",
                "treating advisory/news/replay data as executable",
                "overriding stale/TTL or source-type failure codes",
            ),
            phase_b_conflict_ids=(1,),
        ),
        contributors=(
            _contributor(
                "market_truth",
                "app.core.truth_reconciler",
                "app/core/truth_reconciler.py",
                "reconciler",
                "Compares exchange/execution truth and reports conflict evidence.",
                "May report drift; cannot make stale or conflicting market rows executable.",
                conflict_ids=(1,),
            ),
            _contributor(
                "market_truth",
                "app.core.truth_kernel",
                "app/core/truth_kernel.py",
                "diagnostic",
                "Normalizes truth-state diagnostics for downstream explainers.",
                "Blocked from final authority until product reachability is proven.",
                status="BLOCKED",
                blocked_reason="TEST_ONLY_STATIC_CALLER_NO_PRODUCT_CALLER",
                conflict_ids=(1,),
            ),
            _contributor(
                "market_truth",
                "app.data.feed_provider_router",
                "app/data/feed_provider_router.py",
                "signal",
                "Routes provider feed evidence toward runtime market data consumers.",
                "Provider routing cannot bypass MarketTruthSnapshot executable validation.",
                conflict_ids=(1,),
            ),
            _contributor(
                "market_truth",
                "app.data.market_feeds",
                "app/data/market_feeds.py",
                "signal",
                "Maintains market-feed utility surfaces and test-backed feed contracts.",
                "Blocked from final authority; feed data must enter through the snapshot owner.",
                status="BLOCKED",
                blocked_reason="TEST_ONLY_STATIC_CALLER_NO_PRODUCT_CALLER",
                conflict_ids=(1,),
            ),
            _contributor(
                "market_truth",
                "app.data.aggregator",
                "app/data/aggregator.py",
                "signal",
                "Aggregates candidate feed data for modeling surfaces.",
                "Blocked from final executable authority until product wiring is proven.",
                status="BLOCKED",
                blocked_reason="TEST_ONLY_STATIC_CALLER_NO_PRODUCT_CALLER",
                conflict_ids=(1,),
            ),
            _contributor(
                "market_truth",
                "app.data.ghost_tick_detector",
                "app/data/ghost_tick_detector.py",
                "diagnostic",
                "Detects suspect tick evidence.",
                "Can warn or block as evidence only; cannot replace MarketTruthSnapshot.",
                status="BLOCKED",
                blocked_reason="TEST_ONLY_STATIC_CALLER_NO_PRODUCT_CALLER",
                conflict_ids=(1,),
            ),
            _contributor(
                "market_truth",
                "app.models.unified_market",
                "app/models/unified_market.py",
                "reference_model",
                "Sophisticated unified market model retained for future integration.",
                "Disconnected model cannot become executable truth until wired under MarketTruthSnapshot.",
                status="BLOCKED",
                blocked_reason="DISCONNECTED_FROM_LIVE_SPINE",
                conflict_ids=(1,),
            ),
        ),
    ),
    "risk_gates": AuthorityEntry(
        owner=AuthorityOwner(
            authority="risk_gates",
            module="app.risk.pre_trade_guardrails.evaluate_pre_trade_guardrails",
            path="app/risk/pre_trade_guardrails.py",
            final_decision="pre-broker route and mutation admission verdict",
            allowed_scope=(
                "Assemble hard pre-trade admission evidence into ALLOW/BLOCK/"
                "REQUIRE_APPROVAL/ADJUSTMENT_REQUIRED verdicts."
            ),
            blocked_scope=(
                "weakening NetEdge, stale/TTL, sizing, strategy, or risk thresholds",
                "approving broker mutation without supplied market and broker-position truth",
                "turning advisory-only evidence into execution permission",
            ),
            phase_b_conflict_ids=(2,),
        ),
        contributors=(
            _contributor(
                "risk_gates",
                "app.risk.guard",
                "app/risk/guard.py",
                "gate_input",
                "Legacy/current guard evidence for drawdown, daily loss, and kill-switch style checks.",
                "May block or provide evidence through the guardrail chain; cannot be a parallel final verdict.",
                conflict_ids=(2,),
            ),
            _contributor(
                "risk_gates",
                "app.risk.safety",
                "app/risk/safety.py",
                "gate_input",
                "Runtime safety checks and fail-closed policy evidence.",
                "Can contribute block evidence only under pre-trade guardrails.",
                conflict_ids=(2,),
            ),
            _contributor(
                "risk_gates",
                "app.risk.net_edge_governor",
                "app/risk/net_edge_governor.py",
                "economic_gate_input",
                "NetEdge economic gate evidence.",
                "Hard economic gate remains non-weakenable and cannot be bypassed by UI/AI.",
                conflict_ids=(2,),
            ),
            _contributor(
                "risk_gates",
                "app.risk.exposure_manager",
                "app/risk/exposure_manager.py",
                "portfolio_risk_evidence",
                "Effective exposure and reservation evidence for admission decisions.",
                "Does not submit broker orders and does not replace final pre-trade verdict ownership.",
                conflict_ids=(2,),
            ),
            _contributor(
                "risk_gates",
                "app.risk.unified_risk",
                "app/risk/unified_risk.py",
                "constitutional_risk_model",
                "Advanced composite risk model retained as risk evidence.",
                "Blocked from active final admission authority until product wiring is proven.",
                status="BLOCKED",
                blocked_reason="TEST_ONLY_STATIC_CALLER_NO_PRODUCT_CALLER",
                conflict_ids=(2,),
            ),
            _contributor(
                "risk_gates",
                "app.risk.stale_data_guard",
                "app/risk/stale_data_guard.py",
                "freshness_gate_input",
                "Staleness and source-health hazard evidence.",
                "Blocked from active final verdict ownership; MarketTruthSnapshot stale failure remains hard.",
                status="BLOCKED",
                blocked_reason="TEST_ONLY_STATIC_CALLER_NO_PRODUCT_CALLER",
                conflict_ids=(2,),
            ),
            _contributor(
                "risk_gates",
                "app.risk.sovereign_execution_guard",
                "app/risk/sovereign_execution_guard.py",
                "gate_input",
                "Sovereign execution guard model reserved for final chain integration.",
                "Blocked from current final verdict ownership; cannot create a second admission path.",
                status="BLOCKED",
                blocked_reason="NO_STATIC_CALLER_FOUND",
                conflict_ids=(2,),
            ),
        ),
    ),
    "sizing": AuthorityEntry(
        owner=AuthorityOwner(
            authority="sizing",
            module="app.risk.position_sizing.PositionSizingEngine",
            path="app/risk/position_sizing.py",
            final_decision="deterministic order size before broker admission",
            allowed_scope=(
                "Compute Decimal-safe stop-loss/Kelly/regime/volatility adjusted size "
                "with strategy and global caps."
            ),
            blocked_scope=(
                "loosening sizing or masking thresholds",
                "letting strategy/UI/AI choose final quantity",
                "bypassing exposure or broker minimum evidence",
            ),
            phase_b_conflict_ids=(3,),
        ),
        contributors=(
            _contributor(
                "sizing",
                "app.execution.masking_layer",
                "app/execution/masking_layer.py",
                "masking_input",
                "Applies execution masking/liquidity-shaping evidence after size intent.",
                "Cannot increase size beyond PositionSizingEngine and risk caps.",
                conflict_ids=(3,),
            ),
            _contributor(
                "sizing",
                "app.risk.exposure_manager",
                "app/risk/exposure_manager.py",
                "capacity_input",
                "Provides exposure capacity and reservation pressure.",
                "May reduce/block capacity through risk evidence; cannot become final sizing owner.",
                conflict_ids=(3,),
            ),
            _contributor(
                "sizing",
                "app.risk.sovereign_execution_guard",
                "app/risk/sovereign_execution_guard.py",
                "sizing_gate_input",
                "Reserved sovereign guard cap/evidence model.",
                "Blocked from active sizing authority until wired under PositionSizingEngine.",
                status="BLOCKED",
                blocked_reason="NO_STATIC_CALLER_FOUND",
                conflict_ids=(3,),
            ),
            _contributor(
                "sizing",
                "app.risk.cross_asset_risk_model",
                "app/risk/cross_asset_risk_model.py",
                "cross_asset_cap_input",
                "Cross-asset concentration/correlation model for future caps.",
                "Pre-integration only; cannot change final quantity today.",
                status="BLOCKED",
                blocked_reason="PRE_INTEGRATION",
                conflict_ids=(3,),
            ),
        ),
    ),
    "broker_order_lifecycle": AuthorityEntry(
        owner=AuthorityOwner(
            authority="broker_order_lifecycle",
            module="app.execution.order_router.OrderRouter",
            path="app/execution/order_router.py",
            final_decision="broker/order lifecycle command, id mapping, status, and reconciliation surface",
            allowed_scope=(
                "Route lawful PAPER/live-read-only-safe broker adapter requests, maintain "
                "order-id mapping, open-order status, fills, and lifecycle evidence."
            ),
            blocked_scope=(
                "manual buy/sell or force-trade controls",
                "fake orders, fills, fees, TCA, P&L, or broker truth",
                "naked SELL or SELL without broker-position-backed authority",
            ),
            phase_b_conflict_ids=(4,),
        ),
        contributors=(
            _contributor(
                "broker_order_lifecycle",
                "app.execution.broker_gateway",
                "app/execution/broker_gateway.py",
                "broker_adapter_boundary",
                "Normalizes external broker gateway requests/responses.",
                "Adapter boundary cannot initiate orders outside OrderRouter lifecycle.",
                conflict_ids=(4,),
            ),
            _contributor(
                "broker_order_lifecycle",
                "app.execution.alpaca_paper_adapter",
                "app/execution/alpaca_paper_adapter.py",
                "paper_adapter",
                "Alpaca PAPER adapter for broker request/response evidence.",
                "Cannot provide live or real-money authority and cannot fake broker acknowledgement.",
                conflict_ids=(4,),
            ),
            _contributor(
                "broker_order_lifecycle",
                "app.execution.paper_broker",
                "app/execution/paper_broker.py",
                "internal_paper_broker",
                "Sovereign internal paper broker path used by OrderRouter.",
                "Subordinate to OrderRouter; cannot be an alternate OMS/lifecycle owner.",
                conflict_ids=(4,),
            ),
            _contributor(
                "broker_order_lifecycle",
                "app.execution.oms_lifecycle",
                "app/execution/oms_lifecycle.py",
                "oms_state_machine",
                "Canonical OMS state normalization and terminal/open status rules.",
                "Owns lifecycle state vocabulary, not broker mutation authority.",
                conflict_ids=(4,),
            ),
            _contributor(
                "broker_order_lifecycle",
                "app.execution.broker_adapter",
                "app/execution/broker_adapter.py",
                "contract",
                "Broker adapter protocol/contract surface.",
                "Contract only; no direct broker mutation outside OrderRouter.",
                conflict_ids=(4,),
            ),
            _contributor(
                "broker_order_lifecycle",
                "app.execution.orchestrator",
                "app/execution/orchestrator.py",
                "reference_only_rejected_duplicate",
                "Historical duplicate execution/order/position orchestrator preserved for audit.",
                "Board-rejected duplicate; must never be reactivated as authority in this phase.",
                status="REJECTED_PRESERVED",
                blocked_reason="EXPLICIT_BOARD_REJECTED_DUPLICATE_AUTHORITY",
                conflict_ids=(4, 8),
            ),
        ),
    ),
    "portfolio_position_truth": AuthorityEntry(
        owner=AuthorityOwner(
            authority="portfolio_position_truth",
            module="app.risk.exposure_manager.ExposureManager",
            path="app/risk/exposure_manager.py",
            final_decision="internal portfolio-risk, reservation, and effective exposure truth",
            allowed_scope=(
                "Maintain filled inventory, pending reservations, effective exposure, "
                "snapshot quality, and reconciliation-attribution state for runtime risk."
            ),
            blocked_scope=(
                "inventing broker-confirmed positions",
                "submitting or cancelling broker orders",
                "overriding broker truth after acknowledgement",
            ),
            phase_b_conflict_ids=(5,),
        ),
        contributors=(
            _contributor(
                "portfolio_position_truth",
                "app.operator_portfolio.snapshot",
                "app/operator_portfolio/snapshot.py",
                "broker_confirmed_read_model",
                "Read-only operator portfolio snapshot from broker/account APIs when authorized.",
                "Broker-confirmed source evidence after acknowledgement; UI read model cannot mutate exposure state.",
                conflict_ids=(5,),
            ),
            _contributor(
                "portfolio_position_truth",
                "app.execution.order_router",
                "app/execution/order_router.py",
                "order_position_evidence",
                "Order lifecycle, fills, active mappings, and normalized open-order evidence.",
                "Lifecycle evidence feeds reconciliation/exposure; it is not final exposure owner here.",
                conflict_ids=(5,),
            ),
            _contributor(
                "portfolio_position_truth",
                "app.state.state_store",
                "app/state/state_store.py",
                "durable_state_input",
                "Durable local state for runtime/recovery evidence.",
                "Persistence cannot become broker truth or override reconciliation conflicts.",
                conflict_ids=(5,),
            ),
            _contributor(
                "portfolio_position_truth",
                "app.core.truth_kernel",
                "app/core/truth_kernel.py",
                "diagnostic",
                "Portfolio truth diagnostics and attribution evidence.",
                "Blocked from current product final ownership until product reachability is proven.",
                status="BLOCKED",
                blocked_reason="TEST_ONLY_STATIC_CALLER_NO_PRODUCT_CALLER",
                conflict_ids=(5,),
            ),
            _contributor(
                "portfolio_position_truth",
                "app.core.intelligence_portfolio_state_truth_spine",
                "app/core/intelligence_portfolio_state_truth_spine.py",
                "portfolio_evidence",
                "Intelligence portfolio-state truth spine for analysis/explainers.",
                "Blocked from current runtime ownership until product wiring is proven.",
                status="BLOCKED",
                blocked_reason="TEST_ONLY_STATIC_CALLER_NO_PRODUCT_CALLER",
                conflict_ids=(5,),
            ),
        ),
    ),
    "ai_advisory": AuthorityEntry(
        owner=AuthorityOwner(
            authority="ai_advisory",
            module="app.ai_chief_operator.provider_gateway.AIProviderGateway",
            path="app/ai_chief_operator/provider_gateway.py",
            final_decision="advisory AI route truth, provider/model mode, and answer envelope",
            allowed_scope=(
                "Route advisory prompts, label provider/model/fallback truth, redact secrets, "
                "and return non-executing recommendations."
            ),
            blocked_scope=(
                "calling broker",
                "enabling live or real-money mode",
                "mutating strategy, thresholds, OMS, broker paths, or risk policy",
                "hiding provider fallback or exposing raw secrets",
            ),
            phase_b_conflict_ids=(6,),
        ),
        contributors=(
            _contributor(
                "ai_advisory",
                "app.ai_chief_operator.model_router",
                "app/ai_chief_operator/model_router.py",
                "route_input",
                "Chooses route mode/model policy evidence for provider gateway decisions.",
                "Cannot bypass gateway envelope, advisory-only policy, or secret redaction.",
                conflict_ids=(6,),
            ),
            _contributor(
                "ai_advisory",
                "app.ai_chief_operator.provider_adapters",
                "app/ai_chief_operator/provider_adapters.py",
                "provider_adapter",
                "Executes provider-specific advisory model calls when gateway authorizes them.",
                "No adapter may trade, call broker, or silently replace route truth.",
                conflict_ids=(6,),
            ),
            _contributor(
                "ai_advisory",
                "ui/operator-control-panel/app.js",
                "ui/operator-control-panel/app.js",
                "display_fallback_label",
                "Displays AI mode, fallback, and advisory-only status to the operator.",
                "UI text cannot imply a provider answered when gateway says fallback/deterministic.",
                conflict_ids=(6,),
            ),
        ),
    ),
    "ui_display": AuthorityEntry(
        owner=AuthorityOwner(
            authority="ui_display",
            module="ui/operator-control-panel/app.js",
            path="ui/operator-control-panel/app.js",
            final_decision="operator cockpit rendering and control-state presentation",
            allowed_scope=(
                "Render backend truth labels, source labels, button states, diagnostics, "
                "offline fixture labels, and operator navigation."
            ),
            blocked_scope=(
                "becoming a trading engine",
                "treating mock data as backend truth",
                "showing green readiness without backend proof",
                "exposing secrets or unsafe manual controls",
            ),
            phase_b_conflict_ids=(7,),
        ),
        contributors=(
            _contributor(
                "ui_display",
                "app.api.operator_readonly_api",
                "app/api/operator_readonly_api.py",
                "backend_data_provider",
                "Supplies read-only/governed operator API payloads and safe PAPER process intents.",
                "API owns backend data truth; UI owns display only and cannot mutate broker directly.",
                conflict_ids=(7,),
            ),
            _contributor(
                "ui_display",
                "ui/operator-control-panel/mock-data.js",
                "ui/operator-control-panel/mock-data.js",
                "offline_fixture",
                "Offline browser fixture data for no-backend demos/tests.",
                "Must stay visibly labeled and must never override backend-loaded truth.",
                conflict_ids=(7,),
            ),
            _contributor(
                "ui_display",
                "scripts/open_operator_console.ps1",
                "scripts/open_operator_console.ps1",
                "launcher",
                "Operator launch helper for local console access.",
                "Launcher starts/opens UI; it does not own rendering, truth, or broker authority.",
                conflict_ids=(7,),
            ),
        ),
    ),
}


NON_AUTHORITY_CONFLICT_RESOLUTIONS: tuple[ConflictResolution, ...] = (
    ConflictResolution(
        conflict_id=9,
        seam="namespace/model authority",
        final_owner="app.models package",
        reference_module="app.models.py_tombstone",
        status="PRESERVED_DEAD",
        boundary="app/models/ is the canonical public package; app/models.py is a shadowed tombstone.",
        reason="Tombstone is preserved for governance history and cannot become module authority.",
    ),
)


def authority_entries() -> tuple[AuthorityEntry, ...]:
    return tuple(AUTHORITY_GRAPH[name] for name in ORDERED_AUTHORITIES)


def owner_for(authority: AuthorityName) -> AuthorityOwner:
    return AUTHORITY_GRAPH[authority].owner


def contributors_for(authority: AuthorityName) -> tuple[AuthorityContributor, ...]:
    return AUTHORITY_GRAPH[authority].contributors


def authority_graph_summary() -> dict[str, Any]:
    ok, messages = validate_authority_graph()
    return {
        "source": "AUTHORITY_GRAPH",
        "version": AUTHORITY_GRAPH_VERSION,
        "authority_count": len(ORDERED_AUTHORITIES),
        "authorities": [entry.to_dict() for entry in authority_entries()],
        "non_authority_conflict_resolutions": [
            item.to_dict() for item in NON_AUTHORITY_CONFLICT_RESOLUTIONS
        ],
        "integrity": {"ok": ok, "messages": messages},
        "broker_mutation_occurred": False,
        "trading_mutation_occurred": False,
        "live_enabled": False,
        "real_money_enabled": False,
        "secrets_values_exposed": False,
    }


def validate_authority_graph() -> tuple[bool, tuple[str, ...]]:
    messages: list[str] = []
    if tuple(AUTHORITY_GRAPH) != ORDERED_AUTHORITIES:
        messages.append("AUTHORITY_GRAPH_ORDER_OR_MEMBERSHIP_MISMATCH")

    owner_modules: dict[AuthorityName, str] = {}
    conflict_ids: set[int] = set()

    for authority in ORDERED_AUTHORITIES:
        entry = AUTHORITY_GRAPH.get(authority)
        if entry is None:
            messages.append(f"MISSING_AUTHORITY:{authority}")
            continue
        owner = entry.owner
        if owner.authority != authority:
            messages.append(f"OWNER_AUTHORITY_MISMATCH:{authority}:{owner.authority}")
        if not owner.module or not owner.path or not owner.final_decision:
            messages.append(f"OWNER_INCOMPLETE:{authority}")
        if authority in owner_modules:
            messages.append(f"DUPLICATE_OWNER_AUTHORITY:{authority}")
        owner_modules[authority] = owner.module
        conflict_ids.update(owner.phase_b_conflict_ids)

        if not entry.contributors:
            messages.append(f"NO_CONTRIBUTORS:{authority}")
        for contributor in entry.contributors:
            if contributor.authority != authority:
                messages.append(f"CONTRIBUTOR_AUTHORITY_MISMATCH:{authority}:{contributor.module}")
            if contributor.can_override_owner:
                messages.append(f"CONTRIBUTOR_CAN_OVERRIDE_OWNER:{authority}:{contributor.module}")
            if contributor.status in {"BLOCKED", "REJECTED_PRESERVED", "PRESERVED_DEAD"} and not contributor.blocked_reason:
                messages.append(f"BLOCKED_CONTRIBUTOR_WITHOUT_REASON:{authority}:{contributor.module}")
            if contributor.status == "WIRED" and contributor.blocked_reason:
                messages.append(f"WIRED_CONTRIBUTOR_HAS_BLOCKER:{authority}:{contributor.module}")
            conflict_ids.update(contributor.phase_b_conflict_ids)

    for resolution in NON_AUTHORITY_CONFLICT_RESOLUTIONS:
        if not resolution.final_owner or not resolution.reference_module:
            messages.append(f"NON_AUTHORITY_RESOLUTION_INCOMPLETE:{resolution.conflict_id}")
        conflict_ids.add(resolution.conflict_id)

    missing_conflicts = EXPECTED_PHASE_B_CONFLICT_IDS - conflict_ids
    extra_conflicts = conflict_ids - EXPECTED_PHASE_B_CONFLICT_IDS
    if missing_conflicts:
        messages.append(f"MISSING_PHASE_B_CONFLICT_IDS:{tuple(sorted(missing_conflicts))}")
    if extra_conflicts:
        messages.append(f"UNKNOWN_PHASE_B_CONFLICT_IDS:{tuple(sorted(extra_conflicts))}")

    return not messages, tuple(messages)


def assert_authority_graph_integrity() -> None:
    ok, messages = validate_authority_graph()
    if not ok:
        raise AssertionError("; ".join(messages))
