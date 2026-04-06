"""
StrategyRouter — Integration Tests

Covers all five routing pipeline stages:
  1. Macro-kill gate
  2. Fusion eligibility (all 5 sleeves including GAMMA_FRONT and SECTOR_ROTATION)
  3. Control mode filter
  4. Dependency constraints (empty default, active edges, unmet deps)
  5. Correlated exposure suppression (Rules 1, 2, 3)

Plus get_preferred_strategy fallback chain and update_macro_state.

All timing uses exchange_ts_ns. No wall-clock.
"""

import pytest
from unittest.mock import Mock

from app.strategies.strategy_router import StrategyRouter
from app.models.fusion import FusionDecision
from app.constants import SleeveType, ControlMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(mode: str = ControlMode.NORMAL.value) -> Mock:
    cfg = Mock()
    cfg.control_mode = mode
    return cfg


def _make_safety_gate(macro_kill: bool = False) -> Mock:
    gate = Mock()
    gate.get_macro_status.return_value = {"macro_kill_active": macro_kill}
    return gate


def _make_router(
    mode: str = ControlMode.NORMAL.value,
    macro_kill: bool = False,
    dependencies=None,
    correlated_pairs=None,
) -> StrategyRouter:
    router = StrategyRouter(
        config=_make_config(mode),
        safety_gate=_make_safety_gate(macro_kill),
        dependencies=dependencies,
        correlated_pairs=correlated_pairs,
    )
    router.update_macro_state()
    return router


def _make_fusion(
    shadow_front: bool = False,
    liquidity_void: bool = False,
    entropy_decoder: bool = False,
    gamma_front: bool = False,
    sector_rotation: bool = False,
    preferred_sleeve: str = None,
    deprioritized_sleeves=None,
    attack_mode: bool = True,
    confidence: float = 0.80,
    ts_ns: int = 1_000_000_000,
) -> FusionDecision:
    return FusionDecision(
        exchange_ts_ns=ts_ns,
        attack_mode=attack_mode,
        confidence=confidence,
        shadow_front_eligible=shadow_front,
        liquidity_void_eligible=liquidity_void,
        entropy_decoder_eligible=entropy_decoder,
        gamma_front_eligible=gamma_front,
        sector_rotation_eligible=sector_rotation,
        preferred_sleeve=preferred_sleeve,
        deprioritized_sleeves=deprioritized_sleeves or [],
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInit:

    def test_default_construction(self):
        router = StrategyRouter(
            config=_make_config(),
            safety_gate=_make_safety_gate(),
        )
        assert router is not None

    def test_cycle_detection_raises(self):
        deps = {
            SleeveType.GAMMA_FRONT:     [SleeveType.SECTOR_ROTATION],
            SleeveType.SECTOR_ROTATION: [SleeveType.GAMMA_FRONT],
        }
        with pytest.raises(ValueError, match="Cycle detected"):
            StrategyRouter(
                config=_make_config(),
                safety_gate=_make_safety_gate(),
                dependencies=deps,
            )

    def test_acyclic_dependency_graph_ok(self):
        deps = {SleeveType.GAMMA_FRONT: [SleeveType.SHADOW_FRONT]}
        router = StrategyRouter(
            config=_make_config(),
            safety_gate=_make_safety_gate(),
            dependencies=deps,
        )
        assert router is not None


# ---------------------------------------------------------------------------
# Macro-kill gate
# ---------------------------------------------------------------------------

class TestMacroKill:

    def test_macro_kill_returns_empty(self):
        router = _make_router(macro_kill=True)
        fusion = _make_fusion(shadow_front=True, gamma_front=True, sector_rotation=True)
        assert router.get_eligible_strategies(fusion) == []

    def test_macro_kill_preferred_returns_none(self):
        router = _make_router(macro_kill=True)
        fusion = _make_fusion(gamma_front=True)
        assert router.get_preferred_strategy(fusion) is None

    def test_update_macro_state_reads_live_from_gate(self):
        """update_macro_state must re-read from safety_gate on each call."""
        gate = _make_safety_gate(macro_kill=True)
        router = StrategyRouter(config=_make_config(), safety_gate=gate)
        router.update_macro_state()
        fusion = _make_fusion(gamma_front=True)
        assert router.get_eligible_strategies(fusion) == []

        gate.get_macro_status.return_value = {"macro_kill_active": False}
        router.update_macro_state()
        assert router.get_eligible_strategies(fusion) == [SleeveType.GAMMA_FRONT]


# ---------------------------------------------------------------------------
# Fusion eligibility — all 5 sleeves
# ---------------------------------------------------------------------------

class TestFusionEligibility:

    def test_gamma_front_eligible(self):
        router = _make_router()
        fusion = _make_fusion(gamma_front=True)
        assert router.get_eligible_strategies(fusion) == [SleeveType.GAMMA_FRONT]

    def test_sector_rotation_eligible(self):
        router = _make_router()
        fusion = _make_fusion(sector_rotation=True)
        assert router.get_eligible_strategies(fusion) == [SleeveType.SECTOR_ROTATION]

    def test_all_five_eligible_order_matches_fusion_declaration(self):
        """Output order must match FusionDecision field declaration order."""
        router = _make_router()
        fusion = _make_fusion(
            shadow_front=True,
            liquidity_void=True,
            entropy_decoder=True,
            gamma_front=True,
            sector_rotation=True,
        )
        result = router.get_eligible_strategies(fusion)
        assert result == [
            SleeveType.SHADOW_FRONT,
            SleeveType.FLV,
            SleeveType.ENTROPY_DECODER,
            SleeveType.GAMMA_FRONT,
            SleeveType.SECTOR_ROTATION,
        ]

    def test_none_eligible_returns_empty(self):
        router = _make_router()
        assert router.get_eligible_strategies(_make_fusion()) == []

    def test_only_shadow_front_eligible(self):
        router = _make_router()
        fusion = _make_fusion(shadow_front=True)
        assert router.get_eligible_strategies(fusion) == [SleeveType.SHADOW_FRONT]

    def test_only_flv_eligible(self):
        router = _make_router()
        fusion = _make_fusion(liquidity_void=True)
        assert router.get_eligible_strategies(fusion) == [SleeveType.FLV]


# ---------------------------------------------------------------------------
# Control mode filter
# ---------------------------------------------------------------------------

class TestControlModeFilter:

    def test_safe_mode_only_shadow_front(self):
        router = _make_router(mode=ControlMode.SAFE.value)
        fusion = _make_fusion(shadow_front=True, gamma_front=True, sector_rotation=True)
        assert router.get_eligible_strategies(fusion) == [SleeveType.SHADOW_FRONT]

    def test_safe_mode_shadow_not_eligible_returns_empty(self):
        router = _make_router(mode=ControlMode.SAFE.value)
        fusion = _make_fusion(gamma_front=True, sector_rotation=True)
        assert router.get_eligible_strategies(fusion) == []

    def test_crisis_opportunistic_only_flv(self):
        router = _make_router(mode=ControlMode.CRISIS_OPPORTUNISTIC.value)
        fusion = _make_fusion(liquidity_void=True, gamma_front=True, sector_rotation=True)
        assert router.get_eligible_strategies(fusion) == [SleeveType.FLV]

    def test_capital_secure_returns_empty(self):
        router = _make_router(mode=ControlMode.CAPITAL_SECURE.value)
        fusion = _make_fusion(shadow_front=True, liquidity_void=True, gamma_front=True)
        assert router.get_eligible_strategies(fusion) == []

    def test_normal_mode_passes_through_all_eligible(self):
        router = _make_router(mode=ControlMode.NORMAL.value)
        fusion = _make_fusion(gamma_front=True, sector_rotation=True)
        result = router.get_eligible_strategies(fusion)
        assert SleeveType.GAMMA_FRONT in result
        assert SleeveType.SECTOR_ROTATION in result


# ---------------------------------------------------------------------------
# Dependency constraints
# ---------------------------------------------------------------------------

class TestDependencyConstraints:

    def test_empty_deps_preserves_input_order(self):
        """Default empty graph must never reorder strategies."""
        router = _make_router()
        fusion = _make_fusion(shadow_front=True, gamma_front=True, sector_rotation=True)
        result = router.get_eligible_strategies(fusion)
        assert result == [
            SleeveType.SHADOW_FRONT,
            SleeveType.GAMMA_FRONT,
            SleeveType.SECTOR_ROTATION,
        ]

    def test_met_dependency_both_pass(self):
        deps = {SleeveType.GAMMA_FRONT: [SleeveType.SHADOW_FRONT]}
        router = _make_router(dependencies=deps)
        fusion = _make_fusion(shadow_front=True, gamma_front=True)
        result = router.get_eligible_strategies(fusion)
        assert SleeveType.SHADOW_FRONT in result
        assert SleeveType.GAMMA_FRONT in result

    def test_dependency_ordering_enforced(self):
        """
        When dep edge (GAMMA_FRONT -> SHADOW_FRONT) exists and both are eligible,
        topo sort must place SHADOW_FRONT (the dep) before GAMMA_FRONT (the dependent).
        In-scope-only semantics: dep not in candidate set is ignored, not blocking.
        """
        deps = {SleeveType.GAMMA_FRONT: [SleeveType.SHADOW_FRONT]}
        router = _make_router(dependencies=deps)
        fusion = _make_fusion(shadow_front=True, gamma_front=True)
        result = router.get_eligible_strategies(fusion)
        assert SleeveType.SHADOW_FRONT in result
        assert SleeveType.GAMMA_FRONT in result
        shadow_idx = result.index(SleeveType.SHADOW_FRONT)
        gamma_idx = result.index(SleeveType.GAMMA_FRONT)
        assert shadow_idx < gamma_idx, "Dep must appear before its dependent in output"

    def test_dep_not_in_eligible_set_treated_as_no_in_scope_dep(self):
        """
        Dep declared in graph but not in fusion-eligible set this cycle is
        treated as zero in-scope deps — strategy passes through unchanged.
        """
        deps = {SleeveType.GAMMA_FRONT: [SleeveType.ENTROPY_DECODER]}
        router = _make_router(dependencies=deps)
        fusion = _make_fusion(gamma_front=True)
        result = router.get_eligible_strategies(fusion)
        assert SleeveType.GAMMA_FRONT in result


# ---------------------------------------------------------------------------
# Correlated pair suppression
# ---------------------------------------------------------------------------

class TestCorrelatedPairSuppression:

    def test_rule1_preferred_sleeve_kept(self):
        pairs = [(SleeveType.GAMMA_FRONT, SleeveType.SECTOR_ROTATION)]
        router = _make_router(correlated_pairs=pairs)
        fusion = _make_fusion(
            gamma_front=True,
            sector_rotation=True,
            preferred_sleeve=SleeveType.GAMMA_FRONT.value,
        )
        result = router.get_eligible_strategies(fusion)
        assert SleeveType.GAMMA_FRONT in result
        assert SleeveType.SECTOR_ROTATION not in result

    def test_rule1_other_preferred_kept(self):
        pairs = [(SleeveType.GAMMA_FRONT, SleeveType.SECTOR_ROTATION)]
        router = _make_router(correlated_pairs=pairs)
        fusion = _make_fusion(
            gamma_front=True,
            sector_rotation=True,
            preferred_sleeve=SleeveType.SECTOR_ROTATION.value,
        )
        result = router.get_eligible_strategies(fusion)
        assert SleeveType.SECTOR_ROTATION in result
        assert SleeveType.GAMMA_FRONT not in result

    def test_rule2_deprioritized_suppressed(self):
        pairs = [(SleeveType.GAMMA_FRONT, SleeveType.SECTOR_ROTATION)]
        router = _make_router(correlated_pairs=pairs)
        fusion = _make_fusion(
            gamma_front=True,
            sector_rotation=True,
            deprioritized_sleeves=[SleeveType.SECTOR_ROTATION.value],
        )
        result = router.get_eligible_strategies(fusion)
        assert SleeveType.GAMMA_FRONT in result
        assert SleeveType.SECTOR_ROTATION not in result

    def test_rule3_routing_order_earlier_survives(self):
        """
        Rule 3: no preferred, no deprioritized — the strategy appearing
        earlier in the pipeline output is kept. GAMMA_FRONT is declared
        before SECTOR_ROTATION in FusionDecision field order.
        """
        pairs = [(SleeveType.GAMMA_FRONT, SleeveType.SECTOR_ROTATION)]
        router = _make_router(correlated_pairs=pairs)
        fusion = _make_fusion(gamma_front=True, sector_rotation=True)
        result = router.get_eligible_strategies(fusion)
        assert SleeveType.GAMMA_FRONT in result
        assert SleeveType.SECTOR_ROTATION not in result

    def test_single_eligible_skips_suppression(self):
        pairs = [(SleeveType.GAMMA_FRONT, SleeveType.SECTOR_ROTATION)]
        router = _make_router(correlated_pairs=pairs)
        fusion = _make_fusion(gamma_front=True)
        assert router.get_eligible_strategies(fusion) == [SleeveType.GAMMA_FRONT]

    def test_no_corr_pairs_passthrough(self):
        router = _make_router()
        fusion = _make_fusion(gamma_front=True, sector_rotation=True)
        result = router.get_eligible_strategies(fusion)
        assert SleeveType.GAMMA_FRONT in result
        assert SleeveType.SECTOR_ROTATION in result

    def test_pair_not_both_eligible_no_suppression(self):
        """If only one of the pair is eligible, no suppression occurs."""
        pairs = [(SleeveType.GAMMA_FRONT, SleeveType.SECTOR_ROTATION)]
        router = _make_router(correlated_pairs=pairs)
        fusion = _make_fusion(gamma_front=True, shadow_front=True)
        result = router.get_eligible_strategies(fusion)
        assert SleeveType.GAMMA_FRONT in result
        assert SleeveType.SHADOW_FRONT in result


# ---------------------------------------------------------------------------
# get_preferred_strategy
# ---------------------------------------------------------------------------

class TestGetPreferredStrategy:

    def test_preferred_sleeve_returned_when_eligible(self):
        router = _make_router()
        fusion = _make_fusion(
            gamma_front=True,
            sector_rotation=True,
            preferred_sleeve=SleeveType.SECTOR_ROTATION.value,
        )
        assert router.get_preferred_strategy(fusion) == SleeveType.SECTOR_ROTATION

    def test_preferred_sleeve_not_eligible_uses_fallback(self):
        router = _make_router()
        fusion = _make_fusion(
            gamma_front=True,
            preferred_sleeve=SleeveType.SECTOR_ROTATION.value,
        )
        assert router.get_preferred_strategy(fusion) == SleeveType.GAMMA_FRONT

    def test_fallback_priority_flv_over_others(self):
        router = _make_router()
        fusion = _make_fusion(liquidity_void=True, gamma_front=True, sector_rotation=True)
        assert router.get_preferred_strategy(fusion) == SleeveType.FLV

    def test_fallback_priority_shadow_front_over_new_sleeves(self):
        router = _make_router()
        fusion = _make_fusion(shadow_front=True, gamma_front=True, sector_rotation=True)
        assert router.get_preferred_strategy(fusion) == SleeveType.SHADOW_FRONT

    def test_fallback_first_eligible_when_no_priority_match(self):
        """GAMMA_FRONT and SECTOR_ROTATION only — neither is in the priority list."""
        router = _make_router()
        fusion = _make_fusion(gamma_front=True, sector_rotation=True)
        assert router.get_preferred_strategy(fusion) == SleeveType.GAMMA_FRONT

    def test_empty_eligible_returns_none(self):
        router = _make_router()
        assert router.get_preferred_strategy(_make_fusion()) is None

    def test_macro_kill_preferred_returns_none(self):
        router = _make_router(macro_kill=True)
        fusion = _make_fusion(gamma_front=True)
        assert router.get_preferred_strategy(fusion) is None
