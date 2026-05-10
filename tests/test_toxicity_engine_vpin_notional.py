from app.brain.toxicity_engine import ToxicityEngine
import pytest

def test_default_notional_bucket_by_symbol():
    e_btc = ToxicityEngine('BTCUSD')
    assert e_btc.volume_bucket_units == pytest.approx(100_000.0)

    e_xbt = ToxicityEngine('XBTUSD')
    assert e_xbt.volume_bucket_units == pytest.approx(100_000.0)

    e_eth = ToxicityEngine('ETHUSDT')
    assert e_eth.volume_bucket_units == pytest.approx(50_000.0)

    e_sol = ToxicityEngine('SOLUSD')
    assert e_sol.volume_bucket_units == pytest.approx(20_000.0)

    e_other = ToxicityEngine('DOGEUSD')
    assert e_other.volume_bucket_units == pytest.approx(50_000.0)

def test_legacy_volume_bucket_units_honored():
    e = ToxicityEngine('ETHUSD', volume_bucket_units=12_345.0)
    assert e.volume_bucket_units == pytest.approx(12_345.0)

def test_trade_notional_bucket_slicing_and_completion():
    e = ToxicityEngine('ETHUSD')  # 50k USD bucket by default
    e.update_trade(size=1.0, price=100.0, side=+1, timestamp_ns=1)  # 100 USD
    e.update_trade(size=1000.0, price=100.0, side=+1, timestamp_ns=2)  # 100,000 USD
    # Expect two full buckets completed and 100 USD remainder
    assert len(e._bucket_vpin) == 2
    assert e._bucket_volumes[-2] == pytest.approx(50_000.0, rel=1e-9, abs=1e-6)
    assert e._bucket_volumes[-1] == pytest.approx(50_000.0, rel=1e-9, abs=1e-6)
    assert e._current_volume == pytest.approx(100.0, rel=1e-9, abs=1e-6)

def test_side_accumulation_notional():
    e = ToxicityEngine('SOLUSD')  # 20k USD bucket
    # First trade: sell 12k notional
    e.update_trade(size=120.0, price=100.0, side=-1, timestamp_ns=1)
    # Second trade: buy 9k notional; completes first bucket at 20k, leaves 1k buy remainder
    e.update_trade(size=90.0, price=100.0, side=+1, timestamp_ns=2)
    assert len(e._bucket_vpin) == 1
    assert e._bucket_sell_volumes[-1] == pytest.approx(12_000.0, rel=1e-9, abs=1e-6)
    assert e._bucket_buy_volumes[-1] == pytest.approx(8_000.0, rel=1e-9, abs=1e-6)
    assert e._current_volume == pytest.approx(1_000.0, rel=1e-9, abs=1e-6)

def test_small_size_high_price_completes_bucket():
    e = ToxicityEngine('SOLUSD')  # 20k USD bucket
    e.update_trade(size=1.0, price=20_000.0, side=+1, timestamp_ns=1)
    assert len(e._bucket_vpin) == 1
    assert e._bucket_volumes[-1] == pytest.approx(20_000.0, rel=1e-9, abs=1e-6)
    assert e._current_volume == pytest.approx(0.0, rel=1e-9, abs=1e-6)

def test_custom_volume_bucket_units_10000_honored():
    e = ToxicityEngine('DOGEUSD', volume_bucket_units=10_000.0)
    # Constructor should honor custom legacy bucket as NOTIONAL and sync internally
    assert e.volume_bucket_units == pytest.approx(10_000.0)

    # One trade exactly fills the 10k USD bucket
    e.update_trade(size=2.0, price=5_000.0, side=+1, timestamp_ns=1)  # 2 * 5,000 = 10,000
    assert len(e._bucket_vpin) == 1
    assert e._bucket_volumes[-1] == pytest.approx(10_000.0, rel=1e-9, abs=1e-6)
    assert e._bucket_buy_volumes[-1] == pytest.approx(10_000.0, rel=1e-9, abs=1e-6)
    assert e._bucket_sell_volumes[-1] == pytest.approx(0.0, rel=1e-9, abs=1e-6)
    assert e._current_volume == pytest.approx(0.0, rel=1e-9, abs=1e-6)

def test_candle_proxy_notional_history():
    e = ToxicityEngine('ETHUSD')
    e.update_candle(volume=100.0, high=0.0, low=0.0, close=2000.0, timestamp_ns=1)
    assert e._volume_history[-1] == pytest.approx(200_000.0, rel=1e-9, abs=1e-6)

def test_serialize_deserialize_roundtrip():
    e1 = ToxicityEngine('ETHUSD')
    e1.update_trade(size=250.0, price=200.0, side=+1, timestamp_ns=1)  # 50k -> completes 1 bucket
    assert len(e1._bucket_vpin) == 1
    s = e1.serialize_state()

    e2 = ToxicityEngine('ETHUSD')
    e2.deserialize_state(s)

    assert len(e2._bucket_vpin) == 1
    assert e2._bucket_volumes[-1] == pytest.approx(50_000.0, rel=1e-9, abs=1e-6)
    assert e2._bucket_buy_volumes[-1] == pytest.approx(50_000.0, rel=1e-9, abs=1e-6)
    assert e2._bucket_sell_volumes[-1] == pytest.approx(0.0, rel=1e-9, abs=1e-6)

def test_explicit_notional_bucket_value_overrides_symbol_defaults():
    e = ToxicityEngine('BTCUSD', notional_bucket_value=75_000.0)
    # Constructor should use explicit notional and sync volume_bucket_units
    assert e.volume_bucket_units == pytest.approx(75_000.0)

    # One trade exactly fills the 75k USD bucket
    e.update_trade(size=37.5, price=2000.0, side=+1, timestamp_ns=1)  # 37.5 * 2000 = 75,000
    assert len(e._bucket_vpin) == 1
    assert e._bucket_volumes[-1] == pytest.approx(75_000.0, rel=1e-9, abs=1e-6)
    assert e._bucket_buy_volumes[-1] == pytest.approx(75_000.0, rel=1e-9, abs=1e-6)
    assert e._bucket_sell_volumes[-1] == pytest.approx(0.0, rel=1e-9, abs=1e-6)
    assert e._current_volume == pytest.approx(0.0, rel=1e-9, abs=1e-6)
