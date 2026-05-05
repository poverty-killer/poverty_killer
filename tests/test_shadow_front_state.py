"""
test_shadow_front_state — ShadowFrontStrategy threshold unit correction tests.

STRATEGY_ADMISSION bundle — targeted gate coverage:
  - whale_threshold attribute name (not whale_threshold_z after unit correction)
  - whale_score=0.05 blocks at whale gate
  - whale_score at/above corrected threshold (0.20) with valid support can admit
  - whale_score=0.23 with missing sentiment support blocks at Gate 3
  - accumulating=True passes whale gate regardless of score
  - accumulating=False with score below threshold blocks at Gate 2
  - sizing engine absent → blocks (fail-closed)
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock

from app.strategies.shadow_front import ShadowFrontStrategy
from app.models.market_data import WhaleFlowScore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(whale_threshold=0.20, sentiment_threshold=0.5, min_confidence=0.5):
    cfg = Mock()
    cfg.strategies.whale_threshold = whale_threshold
    cfg.strategies.sentiment_velocity_threshold = sentiment_threshold
    cfg.strategies.min_confidence = min_confidence
    cfg.strategies.whale_zone_tolerance = 0.02
    return cfg


def _make_strategy(whale_threshold=0.20, sentiment_threshold=0.5, min_confidence=0.5):
    return ShadowFrontStrategy(
        config=_make_config(whale_threshold, sentiment_threshold, min_confidence),
        symbol="BTC/USD",
    )


def _make_sizing_engine(quantity=Decimal("0.01")):
    result = Mock()
    result.quantity = quantity
    result.risk_percent = Decimal("0.02")
    result.position_pct = Decimal("0.05")
    engine = Mock()
    engine.calculate_position_size.return_value = result
    return engine


def _make_whale_score(score: float, is_accumulating: bool = False):
    return WhaleFlowScore(
        symbol="BTC/USD",
        exchange_ts_ns=1_000_000_000,
        score=score,
        z_score=score * 10,
        volume_anomaly=1.0,
        is_accumulating=is_accumulating,
    )


def _try_entry(s, sentiment_velocity=2.0, price=50000.0):
    """Inject sentiment state and attempt update_price entry."""
    s.update_sentiment(sentiment_velocity, 1_000_000_000)
    return s.update_price(
        price=price,
        timestamp_ns=2_000_000_000,
        capital_usd=Decimal("20000"),
        kelly_multiplier=Decimal("0.5"),
        volatility=Decimal("0.02"),
        regime=None,
    )


# ---------------------------------------------------------------------------
# Threshold attribute name and unit correctness
# ---------------------------------------------------------------------------

class TestThresholdAttributeName:

    def test_attribute_is_whale_threshold_not_z(self):
        """After unit correction, attribute is whale_threshold (not whale_threshold_z)."""
        s = _make_strategy(whale_threshold=0.20)
        assert hasattr(s, "whale_threshold")
        assert not hasattr(s, "whale_threshold_z")

    def test_threshold_value_reads_from_config(self):
        s = _make_strategy(whale_threshold=0.18)
        assert s.whale_threshold == pytest.approx(0.18)

    def test_threshold_default_is_normalized(self):
        """Default threshold 0.20 is in normalized 0-1 range, not z-score domain."""
        s = _make_strategy(whale_threshold=0.20)
        assert 0.0 <= s.whale_threshold <= 1.0


# ---------------------------------------------------------------------------
# Gate 2: whale score threshold (normalized scale)
# ---------------------------------------------------------------------------

class TestWhaleGateNormalizedThreshold:

    def test_whale_score_below_threshold_blocks(self):
        """whale_score=0.05 < threshold=0.20 and not accumulating → Gate 2 blocks."""
        s = _make_strategy(whale_threshold=0.20)
        s.update_whale(_make_whale_score(score=0.05, is_accumulating=False))
        result = _try_entry(s, sentiment_velocity=2.0)
        assert result is None

    def test_whale_score_at_threshold_passes_gate(self):
        """whale_score=0.20 >= threshold=0.20 → Gate 2 passes (sizing engine still needed)."""
        s = _make_strategy(whale_threshold=0.20)
        s.set_position_sizing_engine(_make_sizing_engine())
        s.update_whale(_make_whale_score(score=0.20, is_accumulating=False))
        result = _try_entry(s, sentiment_velocity=2.0)
        assert result is not None

    def test_whale_score_above_threshold_passes_gate(self):
        """whale_score=0.25 >= threshold=0.20 → Gate 2 passes."""
        s = _make_strategy(whale_threshold=0.20)
        s.set_position_sizing_engine(_make_sizing_engine())
        s.update_whale(_make_whale_score(score=0.25, is_accumulating=False))
        result = _try_entry(s, sentiment_velocity=2.0)
        assert result is not None

    def test_corrected_threshold_not_z_score_domain(self):
        """
        Old z-score threshold=2.0 blocked all observed scores (0.06-0.23).
        Corrected threshold=0.20 allows scores in that range.
        Score=0.23 must now pass Gate 2 (not blocked by the old 2.0 threshold).
        """
        s = _make_strategy(whale_threshold=0.20)
        s.set_position_sizing_engine(_make_sizing_engine())
        s.update_whale(_make_whale_score(score=0.23, is_accumulating=False))
        result = _try_entry(s, sentiment_velocity=2.0)
        assert result is not None, (
            "whale_score=0.23 should pass the corrected 0.20 threshold; "
            "if this fails, the threshold is still in z-score domain"
        )


# ---------------------------------------------------------------------------
# Gate 2: accumulating path
# ---------------------------------------------------------------------------

class TestAccumulatingPath:

    def test_accumulating_true_passes_gate_regardless_of_score(self):
        """accumulating=True bypasses score comparison in whale gate."""
        s = _make_strategy(whale_threshold=0.20)
        s.set_position_sizing_engine(_make_sizing_engine())
        s.update_whale(_make_whale_score(score=0.05, is_accumulating=True))
        result = _try_entry(s, sentiment_velocity=2.0)
        assert result is not None

    def test_accumulating_false_with_score_below_threshold_blocks(self):
        """accumulating=False + score < threshold → Gate 2 blocks."""
        s = _make_strategy(whale_threshold=0.20)
        s.set_position_sizing_engine(_make_sizing_engine())
        s.update_whale(_make_whale_score(score=0.05, is_accumulating=False))
        result = _try_entry(s, sentiment_velocity=2.0)
        assert result is None

    def test_accumulating_path_still_needs_sentiment(self):
        """accumulating=True passes Gate 2 but sentiment Gate 3 still applies."""
        s = _make_strategy(whale_threshold=0.20, sentiment_threshold=0.5)
        s.set_position_sizing_engine(_make_sizing_engine())
        s.update_whale(_make_whale_score(score=0.05, is_accumulating=True))
        result = _try_entry(s, sentiment_velocity=0.0)  # below threshold
        assert result is None


# ---------------------------------------------------------------------------
# Gate 3: missing sentiment support blocks even when whale gate passes
# ---------------------------------------------------------------------------

class TestSentimentGateWithValidWhale:

    def test_whale_023_missing_sentiment_blocks_at_gate3(self):
        """
        whale_score=0.23 passes Gate 2 (>= 0.20).
        sentiment_velocity=0.0 < threshold=0.5 blocks at Gate 3.
        Other required gate conditions are absent.
        """
        s = _make_strategy(whale_threshold=0.20, sentiment_threshold=0.5)
        s.set_position_sizing_engine(_make_sizing_engine())
        s.update_whale(_make_whale_score(score=0.23, is_accumulating=False))
        result = _try_entry(s, sentiment_velocity=0.0)
        assert result is None

    def test_whale_023_below_sentiment_threshold_blocks(self):
        """Sentinel: any sentiment velocity below threshold blocks regardless of whale score."""
        s = _make_strategy(whale_threshold=0.20, sentiment_threshold=0.5)
        s.set_position_sizing_engine(_make_sizing_engine())
        s.update_whale(_make_whale_score(score=0.23, is_accumulating=False))
        result = _try_entry(s, sentiment_velocity=0.3)  # 0.3 < 0.5
        assert result is None


# ---------------------------------------------------------------------------
# Sizing engine absent — fail-closed
# ---------------------------------------------------------------------------

class TestSizingEngineAbsentFailClosed:

    def test_no_sizing_engine_blocks_even_with_all_gates_passed(self):
        """No sizing engine → fail-closed in _check_entry_conditions."""
        s = _make_strategy(whale_threshold=0.20, sentiment_threshold=0.5)
        # No call to set_position_sizing_engine
        s.update_whale(_make_whale_score(score=0.25, is_accumulating=False))
        result = _try_entry(s, sentiment_velocity=2.0)
        assert result is None

    def test_sizing_engine_zero_quantity_blocks(self):
        """Sizing engine present but returns zero quantity → no signal."""
        s = _make_strategy(whale_threshold=0.20)
        s.set_position_sizing_engine(_make_sizing_engine(quantity=Decimal("0")))
        s.update_whale(_make_whale_score(score=0.25, is_accumulating=False))
        result = _try_entry(s, sentiment_velocity=2.0)
        assert result is None
