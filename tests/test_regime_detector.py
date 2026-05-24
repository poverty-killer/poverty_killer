from pathlib import Path

from app.brain.regime_detector import RegimeDetector
from app.config import Config
from app.models.enums import RegimeType
from app.symbol_runtime import SymbolRuntime


def test_regime_detector_accepts_legacy_config_constructor():
    cfg = Config()

    detector = RegimeDetector(config=cfg)

    assert detector.symbol is None


def test_regime_detector_accepts_symbol_constructor_contract():
    cfg = Config()

    detector = RegimeDetector(config=cfg, symbol="BTC/USD")
    regime, confidence = detector.update(
        price=50_000.0,
        volume=2_500.0,
        bid_price=49_999.0,
        ask_price=50_001.0,
        bid_depth=12.0,
        ask_depth=10.0,
        exchange_ts_ns=1_777_948_800_000_000_000,
    )

    assert detector.symbol == "BTC/USD"
    assert isinstance(regime, RegimeType)
    assert 0.0 <= confidence <= 1.0


def test_symbol_runtime_instantiates_symbol_bound_regime_detector():
    cfg = Config()

    runtime = SymbolRuntime(symbol="BTC/USD")
    runtime.initialize_engines(config=cfg, safety_gate=None)

    assert runtime.initialized is True
    assert isinstance(runtime.regime_detector, RegimeDetector)
    assert runtime.regime_detector.symbol == "BTC/USD"


def test_symbol_runtime_startup_constructs_crypto_watchlist_regime_detectors():
    cfg = Config()

    for symbol in ("BTC/USD", "ETH/USD", "SOL/USD"):
        runtime = SymbolRuntime(symbol=symbol)
        runtime.initialize_engines(config=cfg, safety_gate=None)

        assert runtime.initialized is True
        assert isinstance(runtime.regime_detector, RegimeDetector)
        assert runtime.regime_detector.symbol == symbol


def test_runtime_log_sources_are_windows_ascii_safe_for_arrows():
    right_arrow = chr(0x2192)
    for path in (
        Path("app/brain/signal_fusion.py"),
        Path("app/main_loop.py"),
    ):
        assert right_arrow not in path.read_text(encoding="utf-8")


def test_main_runtime_health_timestamp_uses_timezone_aware_utc():
    source = Path("main.py").read_text(encoding="utf-8")

    assert "datetime.utcnow()" not in source
    assert "datetime.now(timezone.utc).isoformat()" in source
