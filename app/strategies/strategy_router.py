"""
Strategy Router — Governed Rebuild v3

Two accepted capability upgrades, both evidence-bound and doctrine-free:

  Upgrade 1 — Deterministic strategy dependency graph:
    Kahn's topological sort enforces same-cycle dependency semantics.
    Reordering only occurs when actual declared dependency edges exist among
    the candidate set. When no edges exist, incoming order is preserved exactly.
    Default dependency graph is empty — no dependency pairs are evidenced by
    any sibling strategy file or call site.

  Upgrade 2 — Correlated exposure constraints:
    Deterministic suppression of correlated strategy pairs using only valid
    routing-stage fields from FusionDecision. Tie-break Rule 3 preserves
    incoming routing order (pipeline-determined) rather than imposing new
    alphabetical ordering. Default correlated pairs are empty — no correlation
    groups are evidenced by any sibling strategy file or call site.

Both mechanisms are configurable at construction. No doctrine is hardcoded.

Routing purity:
  - No wall-clock reads.
  - No live computation in routing path.
  - No hidden shared mutable state.
  - Deterministic outputs for identical inputs.
  - Replay-safe.
"""

import logging
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

from app.constants import ControlMode, SleeveType
from app.models.fusion import FusionDecision
from app.models.contracts import StrategyVote
from app.models.enums import StrategyID
from app.strategies.council_metadata import (
    build_runtime_evidence_record,
    summarize_runtime_evidence,
)
from app.strategies.strategy_vote_adapters import (
    adapt_vote_to_runtime_evidence,
    missing_strategy_runtime_evidence,
)

logger = logging.getLogger(__name__)


_SLEEVE_MODULE_NAMES: Dict[SleeveType, str] = {
    SleeveType.SHADOW_FRONT: StrategyID.SHADOW_FRONT.value,
    SleeveType.FLV: StrategyID.LIQUIDITY_VOID.value,
    SleeveType.ENTROPY_DECODER: "entropy_decoder",
    SleeveType.GAMMA_FRONT: StrategyID.GAMMA_FRONT.value,
    SleeveType.SECTOR_ROTATION: StrategyID.SECTOR_ROTATION.value,
}

_PROTECTED_STRATEGY_MODULES: Tuple[str, ...] = (
    StrategyID.MOVING_FLOOR.value,
    StrategyID.ADAPTIVE_DC.value,
)


class StrategyRouter:
    """
    Routes capital to eligible strategies for a given fusion decision cycle.

    Routing pipeline (applied in order, each stage filters the previous):
      1. Macro-kill gate — hard override, returns empty immediately.
      2. Fusion eligibility — reads FusionDecision boolean eligibility flags.
      3. Control mode filter — operator mode gates (SAFE, CRISIS_OPPORTUNISTIC,
         CAPITAL_SECURE).
      4. Dependency constraints — Kahn's topological sort, truly topology-aware.
         Reorders only when actual declared edges require it. Preserves incoming
         order otherwise. Default dependency graph is empty.
      5. Correlated exposure suppression — deterministic three-rule tie-break
         using only FusionDecision routing-stage fields. Rule 3 preserves
         pipeline routing order. Default correlated pairs are empty.

    Both `dependencies` and `correlated_pairs` are injected at construction.
    No doctrine is hardcoded without direct code evidence.
    """

    def __init__(
        self,
        config: Any,
        safety_gate: Any,
        dependencies: Optional[Dict[SleeveType, List[SleeveType]]] = None,
        correlated_pairs: Optional[List[Tuple[SleeveType, SleeveType]]] = None,
    ) -> None:
        """
        Initialize strategy router.

        Args:
            config: Configuration object exposing control_mode.
            safety_gate: Safety gate instance exposing get_macro_status().
            dependencies: Strategy dependency graph. Maps each strategy to the
                list of strategies that must also be eligible in the same cycle.
                Must be a DAG — a cycle raises ValueError at init.
                Defaults to {} (no dependencies).
            correlated_pairs: Pairs of strategies considered correlated in
                market exposure. When both are eligible, the lower-priority one
                is suppressed via deterministic tie-break.
                Defaults to [] (no suppression).

        Raises:
            ValueError: If the dependency graph contains a cycle.
        """
        self.config = config
        self.safety_gate = safety_gate
        self._macro_kill_active: bool = False

        self._dependencies: Dict[SleeveType, List[SleeveType]] = (
            dependencies if dependencies is not None else {}
        )
        self._correlated_pairs: List[Tuple[SleeveType, SleeveType]] = (
            correlated_pairs if correlated_pairs is not None else []
        )

        cycle = self._detect_cycle()
        if cycle:
            raise ValueError(
                f"Cycle detected in strategy dependency graph: {cycle}. "
                "StrategyRouter cannot initialize with a cyclic graph."
            )

        logger.info(
            "StrategyRouter initialized — %d dependency edges, %d correlated pairs",
            sum(len(v) for v in self._dependencies.values()),
            len(self._correlated_pairs),
        )

    # ============================================
    # MACRO STATE
    # ============================================

    def update_macro_state(self) -> None:
        """Update macro kill state from safety gate. Called by external driver."""
        macro_status = self.safety_gate.get_macro_status()
        self._macro_kill_active = macro_status.get("macro_kill_active", False)

    # ============================================
    # PRIMARY ROUTING INTERFACE
    # ============================================

    def get_eligible_strategies(self, fusion: FusionDecision) -> List[SleeveType]:
        """
        Get deterministically ordered list of eligible strategies for this cycle.

        Each pipeline stage filters the output of the previous stage.
        When no dependency edges exist, output order equals input order from
        stage 2. When edges exist, output order is topology-safe.

        Args:
            fusion: FusionDecision for this routing cycle.

        Returns:
            Ordered list of eligible SleeveType values. Empty on macro-kill.
        """
        if self._macro_kill_active:
            logger.debug("Macro-kill active — all strategies suppressed")
            return []

        fusion_eligible = self._collect_fusion_eligible(fusion)
        mode_filtered = self._filter_by_control_mode(fusion_eligible)
        dep_filtered = self._apply_dependency_constraints(mode_filtered)
        return self._apply_correlation_constraints(dep_filtered, fusion)

    def get_preferred_strategy(self, fusion: FusionDecision) -> Optional[SleeveType]:
        """
        Get the single preferred strategy from the eligible set.

        Selects fusion.preferred_sleeve if it survived the full pipeline.
        Falls back to the base-version priority order (FLV > SHADOW_FRONT >
        ENTROPY_DECODER) restricted to the eligible set, preserving existing
        public behavior. Final fallback is the first element of the eligible list.

        Args:
            fusion: FusionDecision for this routing cycle.

        Returns:
            Preferred SleeveType or None if macro-kill or no eligible strategies.
        """
        if self._macro_kill_active:
            return None

        eligible = self.get_eligible_strategies(fusion)
        if not eligible:
            return None

        eligible_set: Set[SleeveType] = set(eligible)

        if fusion.preferred_sleeve:
            try:
                preferred = SleeveType(fusion.preferred_sleeve)
                if preferred in eligible_set:
                    return preferred
            except ValueError:
                pass

        # Restore base-version priority fallback, restricted to eligible set.
        if SleeveType.FLV in eligible_set:
            return SleeveType.FLV
        if SleeveType.SHADOW_FRONT in eligible_set:
            return SleeveType.SHADOW_FRONT
        if SleeveType.ENTROPY_DECODER in eligible_set:
            return SleeveType.ENTROPY_DECODER

        return eligible[0]

    def collect_strategy_runtime_evidence(
        self,
        fusion: FusionDecision,
        *,
        strategy_votes: Optional[List[StrategyVote]] = None,
        timestamp_ns: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Surface router/vote evidence for SignalFusion and DecisionRecord metadata.

        This is evidence wiring only. It does not call strategy engines, allocate
        capital, submit orders, or grant execution authority.
        """
        ts = int(timestamp_ns or fusion.exchange_ts_ns)
        eligible = self.get_eligible_strategies(fusion)
        eligible_set = set(eligible)
        records: List[dict] = []
        vote_modules: Set[str] = set()

        for vote in strategy_votes or []:
            evidence = adapt_vote_to_runtime_evidence(vote)
            records.append(evidence)
            vote_modules.add(str(evidence["module_name"]))

        for sleeve, module_name in _SLEEVE_MODULE_NAMES.items():
            if module_name in vote_modules:
                continue
            if sleeve in eligible_set:
                records.append(
                    build_runtime_evidence_record(
                        module_name=module_name,
                        category="strategy_alpha",
                        status="ACTIVE_STRATEGY_VOTE",
                        input_truth="fusion_decision.eligibility_flags",
                        output_summary="Strategy sleeve eligible in router pipeline; native vote not supplied in this packet.",
                        effect="RANK",
                        score_or_direction=sleeve.value,
                        confidence=fusion.confidence,
                        reason="ROUTER_ELIGIBLE_FROM_FUSION",
                        timestamp_ns=ts,
                        provenance={
                            "preferred_sleeve": fusion.preferred_sleeve,
                            "eligible_sleeves": [s.value for s in eligible],
                            "router_authority": "ranking_only_no_execution",
                        },
                    )
                )
            else:
                records.append(
                    build_runtime_evidence_record(
                        module_name=module_name,
                        category="strategy_alpha",
                        status="ABSTAIN",
                        input_truth="fusion_decision.eligibility_flags",
                        output_summary="Strategy sleeve was not eligible in this routing cycle.",
                        effect="NO_EFFECT_WITH_REASON",
                        reason="SLEEVE_NOT_ELIGIBLE",
                        timestamp_ns=ts,
                        provenance={
                            "preferred_sleeve": fusion.preferred_sleeve,
                            "eligible_sleeves": [s.value for s in eligible],
                            "router_authority": "ranking_only_no_execution",
                        },
                    )
                )

        for module_name in _PROTECTED_STRATEGY_MODULES:
            if module_name not in vote_modules:
                records.append(
                    missing_strategy_runtime_evidence(
                        module_name=module_name,
                        reason="NO_PROTECTIVE_OR_ALPHA_VOTE_SUPPLIED",
                        timestamp_ns=ts,
                    )
                )

        return {
            "strategy_attribution": records,
            "strategy_router_summary": summarize_runtime_evidence(tuple(records)),
            "eligible_sleeves": tuple(s.value for s in eligible),
            "preferred_sleeve": fusion.preferred_sleeve,
            "authority": "ranking_only_no_execution",
        }

    # ============================================
    # STAGE 1 — FUSION ELIGIBILITY COLLECTION
    # ============================================

    def _collect_fusion_eligible(self, fusion: FusionDecision) -> List[SleeveType]:
        """
        Collect strategies marked eligible by the FusionDecision flags.

        Checks the five strategies currently gated by FusionDecision.
        Order matches FusionDecision field declaration order. This order is
        preserved through all downstream stages when no dependency edges exist.
        """
        eligible: List[SleeveType] = []
        if fusion.shadow_front_eligible:
            eligible.append(SleeveType.SHADOW_FRONT)
        if fusion.liquidity_void_eligible:
            eligible.append(SleeveType.FLV)
        if fusion.entropy_decoder_eligible:
            eligible.append(SleeveType.ENTROPY_DECODER)
        if fusion.gamma_front_eligible:
            eligible.append(SleeveType.GAMMA_FRONT)
        if fusion.sector_rotation_eligible:
            eligible.append(SleeveType.SECTOR_ROTATION)
        return eligible

    # ============================================
    # STAGE 2 — CONTROL MODE FILTER
    # ============================================

    def _filter_by_control_mode(self, strategies: List[SleeveType]) -> List[SleeveType]:
        """
        Filter strategies by operator control mode.

        Preserved exactly from the approved base version — no additions.
        SAFE: only SHADOW_FRONT allowed.
        CRISIS_OPPORTUNISTIC: only FLV allowed.
        CAPITAL_SECURE: no new entries.
        All other modes: pass through unchanged.
        """
        mode = self.config.control_mode
        if mode == ControlMode.SAFE.value:
            return [s for s in strategies if s == SleeveType.SHADOW_FRONT]
        elif mode == ControlMode.CRISIS_OPPORTUNISTIC.value:
            return [s for s in strategies if s == SleeveType.FLV]
        elif mode == ControlMode.CAPITAL_SECURE.value:
            return []
        return strategies

    # ============================================
    # STAGE 3 — DEPENDENCY CONSTRAINTS (TOPOLOGY-AWARE)
    # ============================================

    def _topological_sort(self, candidates: List[SleeveType]) -> List[SleeveType]:
        """
        Kahn's algorithm topological sort on the candidate subgraph.

        ORDER PRESERVATION RULE: if no dependency edges exist among the
        candidate set, the incoming candidate order is returned unchanged.
        Reordering only occurs when actual declared edges require it. This
        prevents the sort from introducing new alphabetical ordering when
        no dependency relationship justifies a change.

        When edges do exist, the sort produces a dependency-safe order:
        for every declared edge (dep → strategy), dep appears before strategy
        in the output. All queue tie-breaks use SleeveType.value alphabetical
        ordering for determinism when multiple zero-in-degree nodes compete.

        Args:
            candidates: Strategies to sort.

        Returns:
            Candidate list in appropriate order. Empty list on cycle detection
            in the candidate subgraph (already error-logged).
        """
        if not candidates:
            return []

        candidate_set: Set[SleeveType] = set(candidates)

        # Check whether any dependency edges exist among the candidate set.
        # If none, preserve incoming order exactly — no reordering justified.
        has_edges = any(
            dep in candidate_set
            for strategy in candidates
            for dep in self._dependencies.get(strategy, [])
        )
        if not has_edges:
            return list(candidates)

        # Edges exist — apply Kahn's sort.
        in_degree: Dict[SleeveType, int] = {s: 0 for s in candidates}
        adj: Dict[SleeveType, List[SleeveType]] = {s: [] for s in candidates}

        for strategy in candidates:
            for dep in self._dependencies.get(strategy, []):
                if dep in candidate_set:
                    in_degree[strategy] += 1
                    adj[dep].append(strategy)

        queue: deque[SleeveType] = deque(
            sorted(
                [s for s in candidates if in_degree[s] == 0],
                key=lambda x: x.value,
            )
        )
        result: List[SleeveType] = []

        while queue:
            node = queue.popleft()
            result.append(node)
            new_zero: List[SleeveType] = []
            for successor in adj[node]:
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    new_zero.append(successor)
            queue.extend(sorted(new_zero, key=lambda x: x.value))

        if len(result) != len(candidates):
            logger.error(
                "Cycle detected in candidate dependency subgraph: %s — "
                "topological sort aborted. Dependency constraints unenforced.",
                [s.value for s in candidates],
            )
            return []

        return result

    def _apply_dependency_constraints(
        self,
        candidates: List[SleeveType],
    ) -> List[SleeveType]:
        """
        Evaluate strategy eligibility in topological order.

        For each strategy (in dependency-safe order from _topological_sort):
          - Collect its declared dependencies present as candidates this cycle.
          - Confirm eligible only if ALL in-scope dependencies are already
            confirmed eligible in this same pass.

        Same-cycle semantics: both the strategy and its declared dependencies
        must be eligible in the current FusionDecision. Not from a prior cycle.

        When the dependency graph is empty (default), all candidates pass
        through in their original order — every strategy has zero in-scope
        deps, all are confirmed immediately.

        On cycle detection: falls back to unfiltered candidates (error already
        logged in _topological_sort). Does not silently suppress.

        Args:
            candidates: Mode-filtered strategies from stage 2.

        Returns:
            Dependency-filtered strategies in pipeline order.
        """
        if not candidates:
            return []

        sorted_strategies = self._topological_sort(candidates)
        if not sorted_strategies:
            return list(candidates)

        candidate_set: Set[SleeveType] = set(candidates)
        eligible_set: Set[SleeveType] = set()

        for strategy in sorted_strategies:
            deps = self._dependencies.get(strategy, [])
            in_scope_deps = [d for d in deps if d in candidate_set]
            if all(dep in eligible_set for dep in in_scope_deps):
                eligible_set.add(strategy)
            else:
                missing = [d.value for d in in_scope_deps if d not in eligible_set]
                logger.debug(
                    "Strategy %s suppressed — unmet in-scope dependencies: %s",
                    strategy.value,
                    missing,
                )

        return [s for s in sorted_strategies if s in eligible_set]

    def _detect_cycle(self) -> Optional[List[str]]:
        """
        Detect cycle in the full dependency graph at init time.

        DFS with three-color marking (white / gray / black).
        Called once in __init__ — not in the routing hot path.

        Returns:
            List of strategy values forming the detected cycle, or None if acyclic.
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[SleeveType, int] = {s: WHITE for s in self._dependencies}
        path: List[SleeveType] = []

        def dfs(node: SleeveType) -> Optional[List[str]]:
            color[node] = GRAY
            path.append(node)
            for dep in self._dependencies.get(node, []):
                if dep not in color:
                    color[dep] = WHITE
                if color[dep] == GRAY:
                    idx = path.index(dep)
                    return [s.value for s in path[idx:]] + [dep.value]
                if color[dep] == WHITE:
                    found = dfs(dep)
                    if found:
                        return found
            color[node] = BLACK
            path.pop()
            return None

        for strategy in sorted(self._dependencies.keys(), key=lambda x: x.value):
            if color.get(strategy, WHITE) == WHITE:
                found = dfs(strategy)
                if found:
                    return found
        return None

    # ============================================
    # STAGE 4 — CORRELATED EXPOSURE SUPPRESSION
    # ============================================

    def _apply_correlation_constraints(
        self,
        eligible: List[SleeveType],
        fusion: FusionDecision,
    ) -> List[SleeveType]:
        """
        Suppress the lower-priority member of each correlated pair.

        Builds a routing_order index from the incoming eligible list so that
        the tie-break in _resolve_correlated_suppression can preserve the
        pipeline-determined ordering rather than imposing alphabetical order.

        Processes pairs in definition order. Once suppressed, a strategy is
        excluded from further pair evaluations. Preserves input order in output.

        When correlated_pairs is empty (default), returns eligible unchanged.

        Args:
            eligible: Dependency-filtered strategies from stage 3.
            fusion: FusionDecision for routing-stage tie-break fields.

        Returns:
            Eligible strategies with correlated overlaps resolved.
        """
        if len(eligible) <= 1 or not self._correlated_pairs:
            return eligible

        eligible_set: Set[SleeveType] = set(eligible)
        routing_order: Dict[SleeveType, int] = {s: i for i, s in enumerate(eligible)}
        suppressed: Set[SleeveType] = set()

        for pair_a, pair_b in self._correlated_pairs:
            if pair_a not in eligible_set or pair_b not in eligible_set:
                continue
            if pair_a in suppressed or pair_b in suppressed:
                continue
            suppress_target = self._resolve_correlated_suppression(
                pair_a, pair_b, fusion, routing_order
            )
            suppressed.add(suppress_target)
            logger.debug(
                "Correlated suppression: %s suppressed (pair: %s / %s)",
                suppress_target.value,
                pair_a.value,
                pair_b.value,
            )

        return [s for s in eligible if s not in suppressed]

    def _resolve_correlated_suppression(
        self,
        a: SleeveType,
        b: SleeveType,
        fusion: FusionDecision,
        routing_order: Dict[SleeveType, int],
    ) -> SleeveType:
        """
        Determine which of two correlated strategies to suppress.

        Uses ONLY valid routing-stage fields from FusionDecision, plus the
        routing_order derived from the pipeline-determined eligible sequence.
        Returns the strategy to SUPPRESS (lower priority).

        Tie-break hierarchy:
          Rule 1 — fusion.preferred_sleeve: keep the explicitly preferred
                   strategy; suppress the other. Highest routing authority.
          Rule 2 — fusion.deprioritized_sleeves: suppress the strategy that
                   is explicitly deprioritized when only one of the pair is.
          Rule 3 — routing_order: keep the strategy that appeared earlier in
                   the deterministic pipeline output; suppress the one that
                   appeared later. Preserves existing routing order rather
                   than imposing new alphabetical ordering doctrine.

        No wall-clock. No live computation. Pure function of arguments.

        Args:
            a: First strategy in the correlated pair.
            b: Second strategy in the correlated pair.
            fusion: FusionDecision providing routing-stage tie-break fields.
            routing_order: Position index of each strategy in the eligible list.

        Returns:
            The SleeveType to suppress.
        """
        preferred: Optional[str] = fusion.preferred_sleeve
        deprioritized: Set[str] = set(fusion.deprioritized_sleeves)

        # Rule 1: Explicit fusion preference — suppress the non-preferred.
        if preferred == a.value:
            return b
        if preferred == b.value:
            return a

        # Rule 2: Explicit deprioritization — suppress the deprioritized one.
        a_deprior = a.value in deprioritized
        b_deprior = b.value in deprioritized
        if a_deprior and not b_deprior:
            return a
        if b_deprior and not a_deprior:
            return b

        # Rule 3: Preserve routing order — suppress the strategy that appeared
        # later in the pipeline-determined eligible sequence. This respects the
        # ordering already established by upstream pipeline stages without
        # imposing new alphabetical ordering doctrine.
        if routing_order.get(a, 0) <= routing_order.get(b, 0):
            return b  # a appeared earlier — keep a, suppress b
        return a      # b appeared earlier — keep b, suppress a
