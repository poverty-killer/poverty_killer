from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


ALLOWED_STATUSES = frozenset(
    {
        "ACTIVE_NATIVE_SIGNAL",
        "ACTIVE_GUARDRAIL",
        "ACTIVE_RECONCILIATION",
        "ACTIVE_TRUTH_CHECK",
        "ACTIVE_EXECUTION_BOUNDARY",
        "DEGRADED_FALLBACK",
        "MISSING_FEED_TRUTH",
        "INTENTIONALLY_BLOCKED_SHADOW",
        "INTENTIONALLY_BLOCKED_LIVE_ONLY",
        "NOT_AVAILABLE",
        "VETOED",
        "PASSED",
        "FAILED_CLOSED",
    }
)

ALLOWED_EFFECTS = frozenset(
    {
        "RANKED",
        "ADVISORY",
        "VETO",
        "BLOCKED",
        "APPROVED",
        "SKIPPED",
        "RECONCILED",
        "INVARIANT_CHECKED",
        "SHADOW_WOULD_SUBMIT",
        "NO_MUTATION_BOUNDARY",
        "NO_EFFECT_WITH_REASON",
    }
)


@dataclass(frozen=True, slots=True)
class ParticipationSignature:
    module_name: str
    category: str
    status: str
    input_source: str
    output_summary: str
    effect: str
    reason: str
    timestamp: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_name": self.module_name,
            "category": self.category,
            "status": self.status,
            "input_source": self.input_source,
            "output_summary": self.output_summary,
            "effect": self.effect,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


def make_signature(
    *,
    module_name: str,
    category: str,
    status: str,
    input_source: str,
    output_summary: str,
    effect: str,
    reason: str,
    timestamp: int,
) -> dict[str, Any]:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"unsupported attribution status: {status}")
    if effect not in ALLOWED_EFFECTS:
        raise ValueError(f"unsupported attribution effect: {effect}")
    return ParticipationSignature(
        module_name=module_name,
        category=category,
        status=status,
        input_source=input_source,
        output_summary=output_summary,
        effect=effect,
        reason=reason,
        timestamp=int(timestamp),
    ).to_dict()


def degraded_market_fallback_signature(
    *,
    module_name: str,
    category: str,
    live_market_truth: Mapping[str, Any] | None,
    timestamp: int,
) -> dict[str, Any]:
    truth = dict(live_market_truth or {})
    available = tuple(
        key
        for key in (
            "current_price",
            "last_price",
            "bid",
            "ask",
            "spread_bps",
            "quote_fresh",
            "order_book",
            "top_of_book",
        )
        if truth.get(key) is not None
    )
    if not available:
        return make_signature(
            module_name=module_name,
            category=category,
            status="MISSING_FEED_TRUTH",
            input_source="native_feed_absent",
            output_summary="No lawful live market fallback inputs were available.",
            effect="NO_EFFECT_WITH_REASON",
            reason="MISSING_FEED_TRUTH",
            timestamp=timestamp,
        )
    return make_signature(
        module_name=module_name,
        category=category,
        status="DEGRADED_FALLBACK",
        input_source="lawful_live_market_truth:" + ",".join(available),
        output_summary="Deterministic fallback signature only; no native alpha or economic truth invented.",
        effect="ADVISORY",
        reason="native_feed_missing_using_lawful_market_truth",
        timestamp=timestamp,
    )


def _guardrail_module_index(guardrail_verdict: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    if not isinstance(guardrail_verdict, Mapping):
        return {}
    indexed: dict[str, Mapping[str, Any]] = {}
    for item in guardrail_verdict.get("module_evidence", ()) or ():
        if isinstance(item, Mapping) and item.get("module"):
            indexed[str(item["module"])] = item
    return indexed


def _effect_from_guardrail(verdict: Mapping[str, Any] | None) -> str:
    if isinstance(verdict, Mapping) and verdict.get("route_permitted") is True:
        return "APPROVED"
    return "BLOCKED"


def build_runtime_edge_attribution(
    *,
    timestamp_ns: int,
    symbol: str | None = None,
    signal: Any | None = None,
    signal_metadata: Mapping[str, Any] | None = None,
    fusion_attribution: Mapping[str, Any] | None = None,
    guardrail_verdict: Mapping[str, Any] | None = None,
    truth_frame: Any | None = None,
    shadow_read_only: bool = False,
    broker_mutation_counts: Mapping[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    metadata = dict(signal_metadata or {})
    attribution: dict[str, dict[str, Any]] = {
        str(name): dict(value)
        for name, value in dict(fusion_attribution or {}).items()
        if isinstance(value, Mapping)
    }
    guardrail_modules = _guardrail_module_index(guardrail_verdict)
    strategy_name = str(getattr(signal, "strategy", "") or "").lower()
    live_market_truth = {
        "current_price": metadata.get("current_price") or getattr(signal, "price", None),
        "last_price": metadata.get("last_price"),
        "bid": metadata.get("bid"),
        "ask": metadata.get("ask"),
        "spread_bps": metadata.get("spread_bps"),
        "quote_fresh": metadata.get("quote_fresh"),
        "order_book": metadata.get("order_book"),
        "top_of_book": metadata.get("top_of_book"),
    }

    def put_once(name: str, value: dict[str, Any]) -> None:
        attribution.setdefault(name, value)

    put_once(
        "SignalFusion",
        make_signature(
            module_name="SignalFusion",
            category="signal_decision_path",
            status="PASSED" if fusion_attribution else "MISSING_FEED_TRUTH",
            input_source="fusion_telemetry" if fusion_attribution else "fusion_telemetry_absent",
            output_summary="Fusion telemetry carried into DecisionRecord when available.",
            effect="ADVISORY" if fusion_attribution else "NO_EFFECT_WITH_REASON",
            reason="FUSION_ATTRIBUTION_PRESENT" if fusion_attribution else "FUSION_ATTRIBUTION_MISSING",
            timestamp=timestamp_ns,
        ),
    )

    for module_name in ("MovingFloor", "AdaptiveDC"):
        put_once(
            module_name,
            degraded_market_fallback_signature(
                module_name=module_name,
                category="strategy_alpha",
                live_market_truth=live_market_truth,
                timestamp=timestamp_ns,
            ),
        )

    put_once(
        "ShadowFront",
        make_signature(
            module_name="ShadowFront",
            category="strategy_alpha",
            status="ACTIVE_NATIVE_SIGNAL" if strategy_name == "shadow_front" else "DEGRADED_FALLBACK",
            input_source="strategy_signal" if strategy_name == "shadow_front" else "lawful_live_market_truth",
            output_summary=(
                f"Strategy signal selected for {symbol}."
                if strategy_name == "shadow_front"
                else "No native ShadowFront signal selected; fallback is advisory only."
            ),
            effect="RANKED" if strategy_name == "shadow_front" else "ADVISORY",
            reason="STRATEGY_SIGNAL_PRESENT" if strategy_name == "shadow_front" else "NATIVE_SIGNAL_NOT_SELECTED",
            timestamp=timestamp_ns,
        ),
    )

    put_once(
        "InsiderSignalEngine",
        make_signature(
            module_name="InsiderSignalEngine",
            category="specialized_portal",
            status="MISSING_FEED_TRUTH",
            input_source="lawful_insider_portal",
            output_summary="No lawful insider/corporate live feed truth was supplied; no MNPI or synthetic portal data used.",
            effect="NO_EFFECT_WITH_REASON",
            reason="MISSING_FEED_TRUTH",
            timestamp=timestamp_ns,
        ),
    )

    for module_name, reason in (
        ("NetEdgeGovernor", "NET_EDGE_MISSING_TRUTH"),
        ("TradeEfficiencyGovernor", "TRADE_EFFICIENCY_MISSING_TRUTH"),
    ):
        evidence = guardrail_modules.get(module_name, {})
        put_once(
            module_name,
            make_signature(
                module_name=module_name,
                category="governor_economics",
                status="MISSING_FEED_TRUTH",
                input_source="pre_trade_guardrail.module_evidence",
                output_summary=str(evidence.get("summary") or "No verified economic truth supplied."),
                effect="ADVISORY",
                reason=str(evidence.get("reason_code") or reason),
                timestamp=timestamp_ns,
            ),
        )

    put_once(
        "PreTradeGuardrails",
        make_signature(
            module_name="PreTradeGuardrails",
            category="risk_guardrails",
            status="ACTIVE_GUARDRAIL" if guardrail_verdict else "MISSING_FEED_TRUTH",
            input_source="guardrail_verdict" if guardrail_verdict else "guardrail_verdict_absent",
            output_summary=str((guardrail_verdict or {}).get("reason_codes", ("GUARDRAIL_MISSING",))),
            effect=_effect_from_guardrail(guardrail_verdict),
            reason=str((guardrail_verdict or {}).get("verdict", "MISSING_GUARDRAIL_TRUTH")),
            timestamp=timestamp_ns,
        ),
    )

    truth_status = str(getattr(truth_frame, "status", "MISSING_TRUTH")) if truth_frame is not None else "MISSING_TRUTH"
    put_once(
        "TruthKernel",
        make_signature(
            module_name="TruthKernel",
            category="state_truth_reconciliation",
            status="ACTIVE_TRUTH_CHECK" if truth_frame is not None else "MISSING_FEED_TRUTH",
            input_source="truth_frame" if truth_frame is not None else "truth_frame_absent",
            output_summary=f"truth_status={truth_status}",
            effect="INVARIANT_CHECKED" if truth_frame is not None else "NO_EFFECT_WITH_REASON",
            reason="TRUTH_FRAME_PRESENT" if truth_frame is not None else "TRUTH_KERNEL_MISSING_TRUTH",
            timestamp=timestamp_ns,
        ),
    )
    put_once(
        "InvariantChecker",
        make_signature(
            module_name="InvariantChecker",
            category="state_truth_reconciliation",
            status="MISSING_FEED_TRUTH",
            input_source="runtime_dispatch_snapshot",
            output_summary="No complete invariant snapshot is available in hot dispatch; Seam 5 invariant subset covers state/truth cycles.",
            effect="NO_EFFECT_WITH_REASON",
            reason="INVARIANT_SNAPSHOT_MISSING_IN_DISPATCH",
            timestamp=timestamp_ns,
        ),
    )
    put_once(
        "Reconciliation",
        make_signature(
            module_name="Reconciliation",
            category="state_truth_reconciliation",
            status="MISSING_FEED_TRUTH",
            input_source="broker_account_positions_open_orders",
            output_summary="Broker reconciliation truth not attached to this hot dispatch packet.",
            effect="NO_EFFECT_WITH_REASON",
            reason="BROKER_RECONCILIATION_SNAPSHOT_MISSING",
            timestamp=timestamp_ns,
        ),
    )
    put_once(
        "StateStore",
        make_signature(
            module_name="StateStore",
            category="state_truth_reconciliation",
            status="PASSED",
            input_source="runtime_state_store",
            output_summary="StateStore is initialized; local state is supporting evidence only.",
            effect="ADVISORY",
            reason="LOCAL_STATE_SUPPORTING_EVIDENCE_ONLY",
            timestamp=timestamp_ns,
        ),
    )

    put_once(
        "CapabilityRegistry",
        make_signature(
            module_name="CapabilityRegistry",
            category="market_venue_capability",
            status="PASSED" if guardrail_verdict else "MISSING_FEED_TRUTH",
            input_source="portal_policy_and_capability_identity",
            output_summary=str((guardrail_verdict or {}).get("capability_identity", {})),
            effect="ADVISORY",
            reason="CAPABILITY_IDENTITY_ATTACHED" if guardrail_verdict else "CAPABILITY_IDENTITY_MISSING",
            timestamp=timestamp_ns,
        ),
    )
    put_once(
        "AlpacaPaperAdapter",
        make_signature(
            module_name="AlpacaPaperAdapter",
            category="execution_path",
            status="INTENTIONALLY_BLOCKED_SHADOW" if shadow_read_only else "ACTIVE_EXECUTION_BOUNDARY",
            input_source="alpaca_paper_capability",
            output_summary="PAPER endpoint only; mutation disabled in shadow mode.",
            effect="NO_MUTATION_BOUNDARY" if shadow_read_only else "APPROVED",
            reason="SHADOW_READ_ONLY_ACTIVE" if shadow_read_only else "PAPER_GATEWAY_AVAILABLE",
            timestamp=timestamp_ns,
        ),
    )
    for module_name in ("ExecutionEngine", "OrderRouter", "BrokerGateway"):
        put_once(
            module_name,
            make_signature(
                module_name=module_name,
                category="execution_path",
                status="ACTIVE_EXECUTION_BOUNDARY",
                input_source="decision_to_execution_spine",
                output_summary="Broker mutation boundary is governed by ExecutionEngine and shadow gate.",
                effect="NO_MUTATION_BOUNDARY" if shadow_read_only else "APPROVED",
                reason="SHADOW_MODE_BLOCKS_MUTATION" if shadow_read_only else "NORMAL_PAPER_PATH_PRESERVED",
                timestamp=timestamp_ns,
            ),
        )

    counts = dict(broker_mutation_counts or {})
    put_once(
        "ShadowReadOnlyGate",
        make_signature(
            module_name="ShadowReadOnlyGate",
            category="execution_path",
            status="INTENTIONALLY_BLOCKED_SHADOW" if shadow_read_only else "NOT_AVAILABLE",
            input_source="shadow_read_only_runtime_flag",
            output_summary=f"broker_mutation_counts={counts}" if counts else "shadow gate inactive",
            effect="NO_MUTATION_BOUNDARY" if shadow_read_only else "NO_EFFECT_WITH_REASON",
            reason="SHADOW_READ_ONLY_BLOCKED_BROKER_MUTATION" if shadow_read_only else "SHADOW_READ_ONLY_DISABLED",
            timestamp=timestamp_ns,
        ),
    )
    return attribution


def build_startup_attribution(
    *,
    timestamp_ns: int,
    broker_mode: str,
    shadow_read_only: bool,
    active_symbols: Any,
    capability_candidates: Any,
) -> dict[str, dict[str, Any]]:
    attribution = build_runtime_edge_attribution(
        timestamp_ns=timestamp_ns,
        symbol=None,
        signal=None,
        signal_metadata={},
        fusion_attribution={},
        guardrail_verdict=None,
        truth_frame=None,
        shadow_read_only=shadow_read_only,
        broker_mutation_counts={
            "POST": 0,
            "PATCH": 0,
            "DELETE": 0,
            "cancel": 0,
            "replace": 0,
            "sell": 0,
            "rebalance": 0,
        }
        if shadow_read_only
        else {},
    )
    attribution["RuntimeBootstrap"] = make_signature(
        module_name="RuntimeBootstrap",
        category="operator_controls",
        status="PASSED" if broker_mode == "paper" else "FAILED_CLOSED",
        input_source="main.py",
        output_summary=(
            f"broker_mode={broker_mode}; shadow_read_only={shadow_read_only}; "
            f"active_symbols={list(active_symbols or ())}; capability_candidates={len(tuple(capability_candidates or ()))}"
        ),
        effect="ADVISORY" if broker_mode == "paper" else "VETO",
        reason="PAPER_RUNTIME_BOOTSTRAPPED" if broker_mode == "paper" else "LIVE_MODE_FORBIDDEN",
        timestamp=timestamp_ns,
    )
    return attribution
