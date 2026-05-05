"""
test_signal_fusion
REGIME_AWARE_SR_ADMISSION — Step 2 acceptance tests.

Verifies:
- default False preserves current RANGING behavior exactly
- opt-in True enables SR as secondary/fallback in RANGING
- SHADOW_FRONT remains preferred_sleeve in RANGING in both paths
- SR remains eligible and preferred in TRENDING_BULL / TRENDING_BEAR
- SR remains deprioritized in RANGING when flag is False
- CRISIS and UNKNOWN regime eligibility maps are unaffected by the flag
- StrategyConfig field defaults and construction are correct
"""

import types
import pytest
from app.brain.signal_fusion import SignalFusion
from app.config import StrategyConfig
from app.models.enums import RegimeType, SleeveType


BASE_TS = 1_000_000_000_000  # nanoseconds — all signals injected at same ts as fuse()


# ---------------------------------------------------------------------------
# Mock payload builders
# ---------------------------------------------------------------------------

def _dir(val: int):
    return types.SimpleNamespace(value=val)


def _tox_regime(val: int):
    return types.SimpleNamespace(value=val)


def _whale(direction: int = 1, confidence: float = 0.75):
    return types.SimpleNamespace(direction=_dir(direction), confidence=confidence)


def _shans(superfluid: float = 0.20, bias: float = 0.30, confidence: float = 0.70):
    return types.SimpleNamespace(
        shans_superfluid_score=superfluid,
        shans_bias=bias,
        shans_confidence=confidence,
    )


def _tox(score: float = 0.10, regime_val: int = 0):
    # regime_val: 0=NORMAL, 1=ELEVATED — both below TOXIC(2) threshold
    return types.SimpleNamespace(toxicity_score=score, regime=_tox_regime(regime_val))


def _entropy(value: float = 0.20):
    return types.SimpleNamespace(entropy=value)


def _physical(health: float = 0.80):
    return {"health_score": health}


def _insider(active: bool = False, invalidated: bool = False, urgency: float = 0.0):
    return types.SimpleNamespace(active=active, invalidated=invalidated, urgency=urgency)


def _build_fusion(sr_ranging_eligible: bool = False) -> SignalFusion:
    strategies = types.SimpleNamespace(sector_rotation_ranging_eligible=sr_ranging_eligible)
    cfg = types.SimpleNamespace(strategies=strategies, symbol="TEST")
    return SignalFusion(config=cfg)


def _inject(fusion: SignalFusion, regime: RegimeType, ts: int = BASE_TS) -> None:
    fusion.update_whale(_whale(), ts)
    fusion.update_shans(_shans(), ts)
    fusion.update_toxicity(_tox(), ts)
    fusion.update_entropy(_entropy(), ts)
    fusion.update_physical(_physical(), ts)
    fusion.update_insider(_insider(), ts)
    fusion.update_regime((regime, 0.90), ts)


# ---------------------------------------------------------------------------
# Config field tests
# ---------------------------------------------------------------------------

class TestStrategyConfigField:
    def test_default_is_false(self):
        s = StrategyConfig()
        assert s.sector_rotation_ranging_eligible is False

    def test_opt_in_true_accepted(self):
        s = StrategyConfig(sector_rotation_ranging_eligible=True)
        assert s.sector_rotation_ranging_eligible is True

    def test_existing_fields_unchanged(self):
        s = StrategyConfig()
        assert s.sector_inflow_threshold == 1.5
        assert s.sector_rotation_enabled is True


# ---------------------------------------------------------------------------
# RANGING — default False (current behavior preserved exactly)
# ---------------------------------------------------------------------------

class TestRangingDefaultFalse:
    def test_sr_not_eligible(self):
        fusion = _build_fusion(sr_ranging_eligible=False)
        _inject(fusion, RegimeType.RANGING)
        d = fusion.fuse(BASE_TS)
        assert not d.sector_rotation_eligible

    def test_shadow_front_eligible(self):
        fusion = _build_fusion(sr_ranging_eligible=False)
        _inject(fusion, RegimeType.RANGING)
        d = fusion.fuse(BASE_TS)
        assert d.shadow_front_eligible

    def test_shadow_front_preferred(self):
        fusion = _build_fusion(sr_ranging_eligible=False)
        _inject(fusion, RegimeType.RANGING)
        d = fusion.fuse(BASE_TS)
        assert d.preferred_sleeve == SleeveType.SHADOW_FRONT.value

    def test_sr_in_deprioritized(self):
        fusion = _build_fusion(sr_ranging_eligible=False)
        _inject(fusion, RegimeType.RANGING)
        d = fusion.fuse(BASE_TS)
        assert SleeveType.SECTOR_ROTATION.value in d.deprioritized_sleeves

    def test_full_eligibility_map(self):
        fusion = _build_fusion(sr_ranging_eligible=False)
        _inject(fusion, RegimeType.RANGING)
        d = fusion.fuse(BASE_TS)
        assert d.shadow_front_eligible
        assert not d.sector_rotation_eligible
        assert not d.gamma_front_eligible
        assert not d.entropy_decoder_eligible
        assert not d.liquidity_void_eligible


# ---------------------------------------------------------------------------
# RANGING — opt-in True (SR becomes secondary/fallback)
# ---------------------------------------------------------------------------

class TestRangingOptInTrue:
    def test_sr_eligible(self):
        fusion = _build_fusion(sr_ranging_eligible=True)
        _inject(fusion, RegimeType.RANGING)
        d = fusion.fuse(BASE_TS)
        assert d.sector_rotation_eligible

    def test_shadow_front_remains_preferred(self):
        fusion = _build_fusion(sr_ranging_eligible=True)
        _inject(fusion, RegimeType.RANGING)
        d = fusion.fuse(BASE_TS)
        assert d.preferred_sleeve == SleeveType.SHADOW_FRONT.value

    def test_shadow_front_eligible(self):
        fusion = _build_fusion(sr_ranging_eligible=True)
        _inject(fusion, RegimeType.RANGING)
        d = fusion.fuse(BASE_TS)
        assert d.shadow_front_eligible

    def test_sr_not_in_deprioritized(self):
        fusion = _build_fusion(sr_ranging_eligible=True)
        _inject(fusion, RegimeType.RANGING)
        d = fusion.fuse(BASE_TS)
        assert SleeveType.SECTOR_ROTATION.value not in d.deprioritized_sleeves

    def test_full_eligibility_map(self):
        fusion = _build_fusion(sr_ranging_eligible=True)
        _inject(fusion, RegimeType.RANGING)
        d = fusion.fuse(BASE_TS)
        assert d.shadow_front_eligible
        assert d.sector_rotation_eligible
        assert not d.gamma_front_eligible
        assert not d.entropy_decoder_eligible
        assert not d.liquidity_void_eligible


# ---------------------------------------------------------------------------
# TRENDING — SR eligible and preferred regardless of flag
# ---------------------------------------------------------------------------

class TestTrendingUnchanged:
    @pytest.mark.parametrize("flag", [False, True])
    def test_sr_eligible_trending_bull(self, flag):
        fusion = _build_fusion(sr_ranging_eligible=flag)
        _inject(fusion, RegimeType.TRENDING_BULL)
        d = fusion.fuse(BASE_TS)
        assert d.sector_rotation_eligible
        assert d.preferred_sleeve == SleeveType.SECTOR_ROTATION.value

    @pytest.mark.parametrize("flag", [False, True])
    def test_sr_eligible_trending_bear(self, flag):
        fusion = _build_fusion(sr_ranging_eligible=flag)
        _inject(fusion, RegimeType.TRENDING_BEAR)
        d = fusion.fuse(BASE_TS)
        assert d.sector_rotation_eligible
        assert d.preferred_sleeve == SleeveType.SECTOR_ROTATION.value


# ---------------------------------------------------------------------------
# Other regimes — no regression from flag
# ---------------------------------------------------------------------------

class TestNoRegressionOtherRegimes:
    @pytest.mark.parametrize("flag", [False, True])
    def test_crisis_gamma_front_eligible(self, flag):
        fusion = _build_fusion(sr_ranging_eligible=flag)
        _inject(fusion, RegimeType.CRISIS)
        d = fusion.fuse(BASE_TS)
        assert d.gamma_front_eligible
        assert d.preferred_sleeve == SleeveType.GAMMA_FRONT.value
        assert not d.sector_rotation_eligible

    @pytest.mark.parametrize("flag", [False, True])
    def test_unknown_flv_preferred(self, flag):
        fusion = _build_fusion(sr_ranging_eligible=flag)
        _inject(fusion, RegimeType.UNKNOWN)
        d = fusion.fuse(BASE_TS)
        assert d.preferred_sleeve == SleeveType.FLV.value
        assert not d.sector_rotation_eligible
