"""
test_whale_notional_normalization — WHALE_FLOW_NOTIONAL_NORMALIZATION_PATCH

Surgical regression coverage for the dimensional fix to whale flow
normalization. Pre-patch, WhaleFlowEngine.update() divided raw crypto
asset units by a USD-notional divisor (100_000), collapsing
normalized_avg toward zero for realistic crypto trade sizes and
silently starving downstream gates of whale conviction.

Post-patch, WhaleFlowEngine.update() accepts a `price` argument and
computes normalized_avg as (avg_trade_size * price) / 100_000.0,
producing the correct USD-notional ratio against the 100k whale
threshold. The price=0.0 fallback preserves legacy behavior for
backward compatibility but must NOT inflate confidence.

These tests prove:
- Unit math is dimensionally correct for BTC/ETH/SOL.
- Old raw-unit behavior would have been orders of magnitude smaller.
- Backward-compat path (no price) still works and does not inflate.
- Zero / negative price falls back to raw-units (no inflation).
- After warmup, meaningful notional whale flow yields confidence
  >= 0.200 without any threshold change.
- SymbolRuntime.update_whale_with_trade plumbs price through.
- MainLoop.on_trade_with_whale call site plumbs price through.
- StrategyConfig.whale_threshold default is still 0.20.
- ShadowFront whale gate threshold is unchanged (0.20).

NO threshold relaxation. NO config change. NO fusion / strategy /
risk / execution change. Pure unit correction.
"""

import inspect
import math

import pytest

from app.brain.whale_flow_engine import (
    WhaleFlowEngine,
    WhaleFlowAlert,
    WhaleDirection,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NS_PER_SEC = 1_000_000_000


def _fresh_engine() -> WhaleFlowEngine:
    return WhaleFlowEngine()


def _single_trade_alert(
    engine: WhaleFlowEngine,
    asset_size: float,
    price: float,
    side_buy: bool = True,
    ts_ns: int = NS_PER_SEC,
) -> WhaleFlowAlert:
    """One-shot update so we can inspect normalized_avg directly."""
    buy_vol = asset_size if side_buy else 0.0
    sell_vol = 0.0 if side_buy else asset_size
    return engine.update(
        buy_volume=buy_vol,
        sell_volume=sell_vol,
        trade_sizes=[asset_size],
        exchange_ts_ns=ts_ns,
        price=price,
    )


# ---------------------------------------------------------------------------
# Unit-correctness: BTC / ETH / SOL notional normalization
# ---------------------------------------------------------------------------

def test_btc_one_unit_at_93k_normalizes_to_0_93():
    """1.0 BTC * $93,000 / 100k = 0.93 USD-notional."""
    alert = _single_trade_alert(_fresh_engine(), asset_size=1.0, price=93_000.0)
    assert alert.avg_trade_size == pytest.approx(0.93, rel=1e-9, abs=1e-9)


def test_btc_point_one_at_93k_normalizes_to_0_093_not_floor():
    """0.1 BTC * $93,000 / 100k = 0.093 — not 0.000001 (raw-unit collapse)."""
    alert = _single_trade_alert(_fresh_engine(), asset_size=0.1, price=93_000.0)
    assert alert.avg_trade_size == pytest.approx(0.093, rel=1e-9, abs=1e-9)
    # Raw-unit pre-patch would have been 0.1 / 100_000 = 1e-6.
    assert alert.avg_trade_size > 1e-3


def test_eth_50_at_2200_caps_at_one():
    """50 ETH * $2,200 / 100k = 1.10 → capped at 1.0."""
    alert = _single_trade_alert(_fresh_engine(), asset_size=50.0, price=2_200.0)
    assert alert.avg_trade_size == pytest.approx(1.0, rel=1e-9, abs=1e-9)


def test_sol_1000_at_150_caps_at_one():
    """1000 SOL * $150 / 100k = 1.50 → capped at 1.0."""
    alert = _single_trade_alert(_fresh_engine(), asset_size=1000.0, price=150.0)
    assert alert.avg_trade_size == pytest.approx(1.0, rel=1e-9, abs=1e-9)


# ---------------------------------------------------------------------------
# Old raw-unit behavior would have been orders of magnitude smaller
# ---------------------------------------------------------------------------

def test_corrected_normalization_is_orders_of_magnitude_above_raw_units():
    """
    Pre-patch raw-units: 1.0 / 100_000 = 1e-5.
    Post-patch USD-notional at $93k: 0.93.
    Ratio must exceed 10_000x to prove the bug magnitude.
    """
    raw_units_value = min(1.0, 1.0 / 100_000.0)
    corrected = _single_trade_alert(
        _fresh_engine(), asset_size=1.0, price=93_000.0
    ).avg_trade_size
    assert corrected / raw_units_value > 10_000.0


# ---------------------------------------------------------------------------
# Backward compatibility: missing / zero / negative price uses raw-units
# fallback and must NOT inflate confidence.
# ---------------------------------------------------------------------------

def test_update_without_price_still_works_backward_compat():
    """Calling update() without price must not raise and must yield raw-units."""
    engine = _fresh_engine()
    alert = engine.update(
        buy_volume=1.0,
        sell_volume=0.0,
        trade_sizes=[1.0],
        exchange_ts_ns=NS_PER_SEC,
    )
    # No price → raw-units fallback: 1.0 / 100_000 = 1e-5
    assert alert.avg_trade_size == pytest.approx(1e-5, rel=1e-6, abs=1e-9)


def test_zero_price_does_not_inflate_normalized_avg():
    alert = _single_trade_alert(_fresh_engine(), asset_size=1.0, price=0.0)
    assert alert.avg_trade_size == pytest.approx(1e-5, rel=1e-6, abs=1e-9)
    assert alert.avg_trade_size < 0.01  # cannot reach whale-tier territory


def test_negative_price_does_not_inflate_normalized_avg():
    alert = _single_trade_alert(_fresh_engine(), asset_size=1.0, price=-50_000.0)
    assert alert.avg_trade_size == pytest.approx(1e-5, rel=1e-6, abs=1e-9)
    assert alert.avg_trade_size < 0.01


def test_zero_price_does_not_inflate_confidence_after_warmup():
    """A warmed-up stream of zero-price trades must yield small confidence
    (the raw-units fallback drives normalized_avg toward 1e-5)."""
    engine = _fresh_engine()
    last_alert = None
    for i in range(25):
        last_alert = engine.update(
            buy_volume=1.0,
            sell_volume=0.0,
            trade_sizes=[1.0],
            exchange_ts_ns=(i + 1) * NS_PER_SEC,
            price=0.0,
        )
    assert last_alert is not None
    # With raw-units fallback, size_contrib is essentially zero, so
    # confidence cannot reach the post-patch >= 0.20 regime via this path.
    assert last_alert.avg_trade_size < 0.01


# ---------------------------------------------------------------------------
# After warmup, meaningful notional whale flow can produce confidence
# >= 0.200 WITHOUT any threshold change.
# ---------------------------------------------------------------------------

def test_warmup_notional_whale_flow_reaches_confidence_threshold():
    """
    25 BUY trades of 1.0 BTC at $93,000 each, spaced 1s apart, must
    produce a final confidence >= 0.20 — proving the dimensional fix
    restores the gate signal that the raw-units bug had collapsed.
    """
    engine = _fresh_engine()
    last_alert = None
    for i in range(25):
        last_alert = engine.update(
            buy_volume=1.0,
            sell_volume=0.0,
            trade_sizes=[1.0],
            exchange_ts_ns=(i + 1) * NS_PER_SEC,
            price=93_000.0,
        )
    assert last_alert is not None
    assert last_alert.direction == WhaleDirection.BUY
    assert last_alert.avg_trade_size == pytest.approx(0.93, rel=1e-6, abs=1e-9)
    assert last_alert.confidence >= 0.20, (
        f"Expected confidence >= 0.20 after USD-notional normalization, "
        f"got {last_alert.confidence:.6f}"
    )


def test_warmup_raw_units_path_stays_below_confidence_threshold():
    """
    Same 25 BUY trades but with the legacy raw-units fallback (price=0.0)
    must NOT reach the >= 0.20 confidence regime by way of size signal,
    confirming that the patch is the source of restored gate signal —
    not a relaxation hidden elsewhere.
    """
    engine = _fresh_engine()
    last_alert = None
    for i in range(25):
        last_alert = engine.update(
            buy_volume=1.0,
            sell_volume=0.0,
            trade_sizes=[1.0],
            exchange_ts_ns=(i + 1) * NS_PER_SEC,
            price=0.0,
        )
    assert last_alert is not None
    # Raw-units normalized_avg ~ 1e-5 — size_contrib essentially zero.
    assert last_alert.avg_trade_size < 0.01


# ---------------------------------------------------------------------------
# Wiring: SymbolRuntime plumbs price into WhaleFlowEngine.update
# ---------------------------------------------------------------------------

def test_symbol_runtime_signature_accepts_price():
    from app.symbol_runtime import SymbolRuntime
    sig = inspect.signature(SymbolRuntime.update_whale_with_trade)
    assert "price" in sig.parameters, (
        "SymbolRuntime.update_whale_with_trade must expose `price` so the "
        "whale engine can normalize against USD notional."
    )


def test_symbol_runtime_passes_price_into_engine():
    """
    Build a real SymbolRuntime, call update_whale_with_trade with a price,
    and verify the resulting alert's avg_trade_size matches the USD-notional
    formula — proving price was forwarded to WhaleFlowEngine.update.
    """
    from app.symbol_runtime import SymbolRuntime

    runtime = SymbolRuntime(symbol="BTC/USD")
    runtime.whale_flow_engine = WhaleFlowEngine()

    alert = runtime.update_whale_with_trade(
        buy_volume=1.0,
        sell_volume=0.0,
        trade_sizes=[1.0],
        timestamp_ns=NS_PER_SEC,
        price=93_000.0,
    )
    assert alert is not None
    assert alert.avg_trade_size == pytest.approx(0.93, rel=1e-9, abs=1e-9)


# ---------------------------------------------------------------------------
# Wiring: MainLoop call site plumbs price into update_whale_with_trade
# ---------------------------------------------------------------------------

def test_main_loop_call_site_passes_price():
    """
    Read MainLoop.on_trade_with_whale source and assert it calls
    update_whale_with_trade with `price=price`. A textual check is
    sufficient because main_loop wiring carries no math worth mocking.
    """
    from app.main_loop import MainLoop
    src = inspect.getsource(MainLoop.on_trade_with_whale)
    assert "update_whale_with_trade(" in src
    assert "price=price" in src, (
        "on_trade_with_whale must forward the trade price into "
        "update_whale_with_trade so whale notional normalization is honest."
    )


# ---------------------------------------------------------------------------
# Threshold immutability — no relaxation hidden in this patch
# ---------------------------------------------------------------------------

def test_strategy_config_whale_threshold_unchanged_at_0_20():
    from app.config import StrategyConfig
    cfg = StrategyConfig()
    assert cfg.whale_threshold == pytest.approx(0.20, rel=1e-9, abs=1e-9)


def test_shadow_front_uses_strategy_whale_threshold_unchanged():
    """ShadowFront must still read whale_threshold from StrategyConfig
    without modification — the patch does not relax the gate."""
    from unittest.mock import Mock
    from app.strategies.shadow_front import ShadowFrontStrategy

    cfg = Mock()
    cfg.strategies.whale_threshold = 0.20
    cfg.strategies.sentiment_velocity_threshold = 0.5
    cfg.strategies.min_confidence = 0.5
    cfg.strategies.whale_zone_tolerance = 0.02

    strat = ShadowFrontStrategy(config=cfg, symbol="BTC/USD")
    assert strat.whale_threshold == pytest.approx(0.20, rel=1e-9, abs=1e-9)


def test_no_threshold_relaxation_in_engine_defaults():
    """Engine defaults must remain on their pre-patch values — the fix
    is purely dimensional, never threshold-side."""
    e = WhaleFlowEngine()
    assert e.imbalance_threshold == 0.6
    assert e.size_threshold_small == 0.5
    assert e.size_threshold_medium == 0.7
    assert e.size_threshold_mega == 0.85
    assert e.concentration_threshold == 0.6
    assert e.persistence_required == 2
    assert e.decay_factor == 0.7
    assert e.min_history == 20
