"""
Unified Market Models - Predator Grade
2x Wealth Grade Innovation - HARDENED:
- Nanosecond timestamps (uint64) - no datetime overhead
- ID-based indexing for O(1) correlation matrix access
- Fixed-size NumPy array (lock-free read pattern)
- Shared-memory ready for multiprocessing
- No threading.Lock() in hot path
"""

import numpy as np
from typing import Optional, Dict, Any, List, Tuple, Union
from enum import Enum
from dataclasses import dataclass, field
from collections import deque
import threading
import time

# Machine epsilon for precision
EPS = np.finfo(float).eps


class AssetClass(Enum):
    """Universal asset classes."""
    CRYPTO = "crypto"
    EQUITY = "equity"
    ETF = "etf"
    FUTURE = "future"
    INDEX = "index"
    FOREX = "forex"


class Exchange(Enum):
    """All supported exchanges."""
    KRAKEN = "kraken"
    COINBASE = "coinbase"
    BINANCE = "binance"
    ALPACA = "alpaca"
    IBKR = "ibkr"
    TD_AMERITRADE = "td_ameritrade"


class TradingStatus(Enum):
    """Trading status for an instrument."""
    OPEN = "open"
    CLOSED = "closed"
    PRE_MARKET = "pre_market"
    POST_MARKET = "post_market"
    HALTED = "halted"


class MacroRegime(Enum):
    """Rule 12: Macro Regime Status per instrument."""
    TRENDING_BULL = "trending_bull"
    TRENDING_BEAR = "trending_bear"
    RANGING = "ranging"
    CRISIS = "crisis"
    UNKNOWN = "unknown"


@dataclass
class InstrumentSpec:
    """
    Universal Instrument Specification - Predator Grade.
    Uses nanosecond timestamps, ID-based indexing.
    """
    id: int                                      # Unique index for matrix access
    symbol: str
    asset_class: AssetClass
    exchange: Exchange
    description: str
    
    # Price and size rules
    base_tick_size: float
    base_lot_size: float
    step_size: float
    min_notional: float
    
    # Market hours (nanosecond epoch times for open/close)
    timezone: str
    market_open_ns: Optional[int] = None         # Nanoseconds since epoch
    market_close_ns: Optional[int] = None
    is_24_7: bool = False
    
    # Margin and leverage
    margin_required: float = 0.0
    max_leverage: float = 1.0
    is_marginable: bool = False
    
    # Rule 12: Macro Regime
    macro_regime: MacroRegime = MacroRegime.UNKNOWN
    regime_confidence: float = 0.5
    regime_updated_ns: int = 0                   # Nanoseconds since epoch
    
    # Correlation grouping
    correlation_group: str = ""
    
    # Volatility scaling
    volatility_multiplier: float = 1.0
    liquidity_multiplier: float = 1.0
    
    # Crypto specific
    whale_threshold_usd: Optional[float] = None
    
    # Futures specific
    multiplier: Optional[float] = None
    tick_value: Optional[float] = None
    
    # Current price and volume (nanosecond timestamp)
    current_price: float = 0.0
    current_volume: float = 0.0
    last_update_ns: int = 0
    
    def get_precision_metadata(self) -> Dict[str, Any]:
        """Get exchange-specific precision metadata (fast)."""
        exchange_adjustments = {
            Exchange.KRAKEN: {"tick_multiplier": 1.0, "lot_multiplier": 1.0},
            Exchange.ALPACA: {"tick_multiplier": 0.01, "lot_multiplier": 1.0},
            Exchange.IBKR: {"tick_multiplier": 0.01, "lot_multiplier": 1.0},
            Exchange.COINBASE: {"tick_multiplier": 1.0, "lot_multiplier": 0.000001},
        }
        
        adj = exchange_adjustments.get(self.exchange, {"tick_multiplier": 1.0, "lot_multiplier": 1.0})
        
        return {
            "tick_size": self.base_tick_size * adj["tick_multiplier"],
            "lot_size": self.base_lot_size * adj["lot_multiplier"],
            "step_size": self.step_size,
            "min_notional": self.min_notional,
            "exchange": self.exchange.value,
            "asset_class": self.asset_class.value,
            "id": self.id
        }
    
    def update_regime(self, regime: MacroRegime, confidence: float, current_ns: int) -> None:
        """Rule 12: Update macro regime with nanosecond timestamp."""
        self.macro_regime = regime
        self.regime_confidence = confidence
        self.regime_updated_ns = current_ns
    
    def update_price(self, price: float, volume: float, timestamp_ns: int) -> None:
        """Update current price with nanosecond timestamp."""
        self.current_price = price
        self.current_volume = volume
        self.last_update_ns = timestamp_ns


class CrossAssetCorrelationMatrix:
    """
    Predator Grade Correlation Matrix.
    - Fixed-size NumPy array (O(1) access)
    - ID-based indexing (no dict lookups)
    - Lock-free read pattern (write only, read snapshot)
    - Shared-memory ready
    """
    
    def __init__(self, max_instruments: int = 256):
        """
        Initialize correlation matrix.
        
        Args:
            max_instruments: Maximum number of instruments (pre-allocated)
        """
        self.max_instruments = max_instruments
        self._matrix = np.zeros((max_instruments, max_instruments), dtype=np.float32)
        self._counts = np.zeros(max_instruments, dtype=np.int32)
        self._returns_buffer: Dict[int, deque] = {}
        self._write_lock = threading.Lock()  # Only for writes, reads are lock-free
        self._version = 0  # For cache invalidation
    
    def update(self, instrument_id: int, price: float, timestamp_ns: int) -> None:
        """
        Update returns for an instrument.
        Write operation - uses lock.
        """
        with self._write_lock:
            if instrument_id not in self._returns_buffer:
                self._returns_buffer[instrument_id] = deque(maxlen=1000)
                self._counts[instrument_id] += 1
            
            buffer = self._returns_buffer[instrument_id]
            
            if buffer:
                last_price = buffer[-1][1]
                if last_price > 0:
                    ret = (price - last_price) / last_price
                    buffer.append((timestamp_ns, price, ret))
                else:
                    buffer.append((timestamp_ns, price, 0.0))
            else:
                buffer.append((timestamp_ns, price, 0.0))
    
    def compute_correlations(self, window: int = 100) -> None:
        """
        Compute all correlations using vectorized operations.
        Updates the matrix - write operation.
        """
        with self._write_lock:
            # Build returns array for all instruments
            n = len(self._returns_buffer)
            if n < 2:
                return
            
            # Create aligned returns matrix
            returns_list = []
            ids = []
            
            for instrument_id, buffer in self._returns_buffer.items():
                rets = [r[2] for r in list(buffer)[-window:] if r[2] != 0]
                if len(rets) >= 10:
                    returns_list.append(rets)
                    ids.append(instrument_id)
            
            if len(returns_list) < 2:
                return
            
            # Convert to numpy array
            min_len = min(len(r) for r in returns_list)
            aligned_returns = np.array([r[-min_len:] for r in returns_list], dtype=np.float32)
            
            # Compute correlation matrix (vectorized)
            corr_matrix = np.corrcoef(aligned_returns)
            corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)
            
            # Update main matrix
            for i, id_i in enumerate(ids):
                for j, id_j in enumerate(ids):
                    self._matrix[id_i, id_j] = corr_matrix[i, j]
            
            self._version += 1
    
    def get_correlation(self, id1: int, id2: int) -> float:
        """O(1) correlation lookup - lock-free read."""
        return float(self._matrix[id1, id2])
    
    def get_row(self, instrument_id: int) -> np.ndarray:
        """Get entire correlation row - lock-free read."""
        return self._matrix[instrument_id, :].copy()
    
    def get_shared_memory_buffer(self) -> np.ndarray:
        """Return matrix view for shared memory - lock-free."""
        return self._matrix
    
    def get_version(self) -> int:
        """Get matrix version for cache invalidation."""
        return self._version


class UnifiedMarketData:
    """
    Predator Grade Unified Market Data.
    - Nanosecond timestamps
    - ID-based indexing
    - Lock-free reads
    """
    
    def __init__(self, max_instruments: int = 256):
        self.max_instruments = max_instruments
        self._instruments: Dict[str, InstrumentSpec] = {}
        self._instruments_by_id: Dict[int, InstrumentSpec] = {}
        self._next_id = 0
        self._correlation_matrix = CrossAssetCorrelationMatrix(max_instruments)
        self._price_buffer: Dict[int, deque] = {}
        self._macro_regimes: Dict[int, MacroRegime] = {}
    
    def register_instrument(self, spec: InstrumentSpec) -> int:
        """
        Register an instrument with auto-assigned ID.
        
        Returns:
            Instrument ID
        """
        spec.id = self._next_id
        self._instruments[spec.symbol] = spec
        self._instruments_by_id[spec.id] = spec
        self._next_id += 1
        return spec.id
    
    def get_instrument_by_id(self, instrument_id: int) -> Optional[InstrumentSpec]:
        """O(1) lookup by ID."""
        return self._instruments_by_id.get(instrument_id)
    
    def get_instrument(self, symbol: str) -> Optional[InstrumentSpec]:
        return self._instruments.get(symbol)
    
    def update_price(self, symbol: str, price: float, volume: float, timestamp_ns: int) -> None:
        """Update price with nanosecond timestamp."""
        spec = self.get_instrument(symbol)
        if not spec:
            raise ValueError(f"Unknown symbol: {symbol}")
        
        spec.update_price(price, volume, timestamp_ns)
        self._correlation_matrix.update(spec.id, price, timestamp_ns)
        
        # Store price history
        if spec.id not in self._price_buffer:
            self._price_buffer[spec.id] = deque(maxlen=1000)
        self._price_buffer[spec.id].append((timestamp_ns, price, volume))
    
    def get_price(self, symbol: str) -> Optional[float]:
        spec = self.get_instrument(symbol)
        return spec.current_price if spec else None
    
    def get_market_status(self, symbol: str, current_ns: int) -> TradingStatus:
        """Get trading status using nanosecond timestamps."""
        spec = self.get_instrument(symbol)
        if not spec:
            return TradingStatus.CLOSED
        
        # Crypto is always open
        if spec.is_24_7 or spec.asset_class == AssetClass.CRYPTO:
            return TradingStatus.OPEN
        
        # Convert nanoseconds to components for time calculation
        if spec.market_open_ns is None or spec.market_close_ns is None:
            return TradingStatus.CLOSED
        
        # Simple comparison (nanoseconds)
        if spec.market_open_ns <= current_ns <= spec.market_close_ns:
            return TradingStatus.OPEN
        
        return TradingStatus.CLOSED
    
    def is_tradable(self, symbol: str, current_ns: int) -> bool:
        return self.get_market_status(symbol, current_ns) == TradingStatus.OPEN
    
    def get_all_symbols(self, asset_class: Optional[AssetClass] = None) -> List[str]:
        if asset_class:
            return [s for s, spec in self._instruments.items() if spec.asset_class == asset_class]
        return list(self._instruments.keys())
    
    def update_macro_regime(self, symbol: str, regime: MacroRegime, confidence: float, current_ns: int) -> None:
        """Rule 12: Update macro regime with nanosecond timestamp."""
        spec = self.get_instrument(symbol)
        if spec:
            spec.update_regime(regime, confidence, current_ns)
            self._macro_regimes[spec.id] = regime
    
    def get_macro_regime(self, symbol: str) -> MacroRegime:
        spec = self.get_instrument(symbol)
        return spec.macro_regime if spec else MacroRegime.UNKNOWN
    
    def get_correlation(self, symbol1: str, symbol2: str) -> float:
        spec1 = self.get_instrument(symbol1)
        spec2 = self.get_instrument(symbol2)
        if not spec1 or not spec2:
            return 0.0
        return self._correlation_matrix.get_correlation(spec1.id, spec2.id)
    
    def get_correlation_by_id(self, id1: int, id2: int) -> float:
        return self._correlation_matrix.get_correlation(id1, id2)
    
    def get_correlation_row(self, symbol: str) -> Optional[np.ndarray]:
        spec = self.get_instrument(symbol)
        if not spec:
            return None
        return self._correlation_matrix.get_row(spec.id)
    
    def get_shared_memory_buffer(self) -> np.ndarray:
        """Return correlation matrix for shared memory."""
        return self._correlation_matrix.get_shared_memory_buffer()
    
    def get_correlation_version(self) -> int:
        """Get correlation matrix version."""
        return self._correlation_matrix.get_version()
    
    def compute_correlations(self, window: int = 100) -> None:
        """Trigger correlation computation."""
        self._correlation_matrix.compute_correlations(window)


# ============================================
# HELPER FUNCTIONS (Nanosecond Conversions)
# ============================================

def datetime_to_ns(dt) -> int:
    """Convert datetime to nanoseconds since epoch."""
    return int(dt.timestamp() * 1_000_000_000)


def ns_to_datetime(ns: int):
    """Convert nanoseconds to datetime."""
    from datetime import datetime
    return datetime.fromtimestamp(ns / 1_000_000_000)


def now_ns() -> int:
    """Get current time in nanoseconds (high precision)."""
    return time.time_ns()


def time_to_ns(hour: int, minute: int = 0, second: int = 0) -> int:
    """
    Convert hour/minute/second to nanoseconds since epoch for today.
    Used for market open/close times.
    """
    from datetime import datetime, timezone
    dt = datetime.now(timezone.utc).replace(hour=hour, minute=minute, second=second, microsecond=0)
    return int(dt.timestamp() * 1_000_000_000)


# ============================================
# FACTORY FUNCTIONS
# ============================================

def create_unified_market_data(max_instruments: int = 256) -> UnifiedMarketData:
    """Create predator grade unified market data."""
    return UnifiedMarketData(max_instruments)


def create_correlation_matrix(max_instruments: int = 256) -> CrossAssetCorrelationMatrix:
    """Create predator grade correlation matrix."""
    return CrossAssetCorrelationMatrix(max_instruments)


# ============================================
# PREDEFINED INSTRUMENTS (Predator Grade)
# ============================================

def get_predefined_instruments() -> List[InstrumentSpec]:
    """Get list of predefined instruments with nanosecond timestamps."""
    
    # Pre-compute market open/close times in nanoseconds
    # These would normally come from session_manager with proper timezone handling
    equity_open_ns = time_to_ns(13, 30)  # 9:30 AM EST = 13:30 UTC (simplified)
    equity_close_ns = time_to_ns(20, 0)  # 4:00 PM EST = 20:00 UTC
    
    futures_open_ns = time_to_ns(22, 0)  # 6:00 PM EST = 22:00 UTC (simplified)
    futures_close_ns = time_to_ns(21, 0)  # 5:00 PM EST = 21:00 UTC next day (simplified)
    
    instruments = []
    next_id = 0
    
    # ========== CRYPTO (Kraken) ==========
    instruments.append(InstrumentSpec(
        id=next_id,
        symbol="BTC/USD",
        asset_class=AssetClass.CRYPTO,
        exchange=Exchange.KRAKEN,
        description="Bitcoin / US Dollar",
        base_tick_size=0.01,
        base_lot_size=0.0001,
        step_size=0.0001,
        min_notional=10.0,
        timezone="UTC",
        is_24_7=True,
        is_marginable=True,
        max_leverage=2.0,
        correlation_group="CRYPTO",
        volatility_multiplier=1.5,
        liquidity_multiplier=1.0,
        whale_threshold_usd=500000.0
    ))
    next_id += 1
    
    instruments.append(InstrumentSpec(
        id=next_id,
        symbol="ETH/USD",
        asset_class=AssetClass.CRYPTO,
        exchange=Exchange.KRAKEN,
        description="Ethereum / US Dollar",
        base_tick_size=0.01,
        base_lot_size=0.001,
        step_size=0.001,
        min_notional=10.0,
        timezone="UTC",
        is_24_7=True,
        is_marginable=True,
        max_leverage=2.0,
        correlation_group="CRYPTO",
        volatility_multiplier=1.3,
        liquidity_multiplier=1.0,
        whale_threshold_usd=500000.0
    ))
    next_id += 1
    
    # ========== EQUITIES (Alpaca) ==========
    instruments.append(InstrumentSpec(
        id=next_id,
        symbol="AAPL",
        asset_class=AssetClass.EQUITY,
        exchange=Exchange.ALPACA,
        description="Apple Inc.",
        base_tick_size=0.01,
        base_lot_size=1,
        step_size=1,
        min_notional=1.0,
        timezone="US/Eastern",
        market_open_ns=equity_open_ns,
        market_close_ns=equity_close_ns,
        is_24_7=False,
        is_marginable=True,
        max_leverage=1.0,
        correlation_group="TECH",
        volatility_multiplier=1.2,
        liquidity_multiplier=1.0
    ))
    next_id += 1
    
    instruments.append(InstrumentSpec(
        id=next_id,
        symbol="MSFT",
        asset_class=AssetClass.EQUITY,
        exchange=Exchange.ALPACA,
        description="Microsoft Corp.",
        base_tick_size=0.01,
        base_lot_size=1,
        step_size=1,
        min_notional=1.0,
        timezone="US/Eastern",
        market_open_ns=equity_open_ns,
        market_close_ns=equity_close_ns,
        is_24_7=False,
        is_marginable=True,
        max_leverage=1.0,
        correlation_group="TECH",
        volatility_multiplier=1.1,
        liquidity_multiplier=1.0
    ))
    next_id += 1
    
    instruments.append(InstrumentSpec(
        id=next_id,
        symbol="NVDA",
        asset_class=AssetClass.EQUITY,
        exchange=Exchange.ALPACA,
        description="NVIDIA Corp.",
        base_tick_size=0.01,
        base_lot_size=1,
        step_size=1,
        min_notional=1.0,
        timezone="US/Eastern",
        market_open_ns=equity_open_ns,
        market_close_ns=equity_close_ns,
        is_24_7=False,
        is_marginable=True,
        max_leverage=1.0,
        correlation_group="TECH",
        volatility_multiplier=1.4,
        liquidity_multiplier=1.0
    ))
    next_id += 1
    
    # ========== ETFs (Alpaca) ==========
    instruments.append(InstrumentSpec(
        id=next_id,
        symbol="SPY",
        asset_class=AssetClass.ETF,
        exchange=Exchange.ALPACA,
        description="SPDR S&P 500 ETF Trust",
        base_tick_size=0.01,
        base_lot_size=1,
        step_size=1,
        min_notional=1.0,
        timezone="US/Eastern",
        market_open_ns=equity_open_ns,
        market_close_ns=equity_close_ns,
        is_24_7=False,
        is_marginable=True,
        max_leverage=1.0,
        correlation_group="INDEX",
        volatility_multiplier=0.9,
        liquidity_multiplier=1.2
    ))
    next_id += 1
    
    instruments.append(InstrumentSpec(
        id=next_id,
        symbol="QQQ",
        asset_class=AssetClass.ETF,
        exchange=Exchange.ALPACA,
        description="Invesco QQQ Trust",
        base_tick_size=0.01,
        base_lot_size=1,
        step_size=1,
        min_notional=1.0,
        timezone="US/Eastern",
        market_open_ns=equity_open_ns,
        market_close_ns=equity_close_ns,
        is_24_7=False,
        is_marginable=True,
        max_leverage=1.0,
        correlation_group="INDEX",
        volatility_multiplier=1.0,
        liquidity_multiplier=1.1
    ))
    next_id += 1
    
    # ========== FUTURES (IBKR) ==========
    instruments.append(InstrumentSpec(
        id=next_id,
        symbol="ES",
        asset_class=AssetClass.FUTURE,
        exchange=Exchange.IBKR,
        description="E-mini S&P 500 Future",
        base_tick_size=0.25,
        base_lot_size=1,
        step_size=1,
        min_notional=12000.0,
        timezone="US/Eastern",
        market_open_ns=futures_open_ns,
        market_close_ns=futures_close_ns,
        is_24_7=False,
        is_marginable=True,
        max_leverage=2.0,
        correlation_group="INDEX",
        volatility_multiplier=2.0,
        liquidity_multiplier=1.0,
        multiplier=50.0,
        tick_value=12.50
    ))
    next_id += 1
    
    instruments.append(InstrumentSpec(
        id=next_id,
        symbol="NQ",
        asset_class=AssetClass.FUTURE,
        exchange=Exchange.IBKR,
        description="E-mini Nasdaq 100 Future",
        base_tick_size=0.25,
        base_lot_size=1,
        step_size=1,
        min_notional=15000.0,
        timezone="US/Eastern",
        market_open_ns=futures_open_ns,
        market_close_ns=futures_close_ns,
        is_24_7=False,
        is_marginable=True,
        max_leverage=2.0,
        correlation_group="INDEX",
        volatility_multiplier=2.2,
        liquidity_multiplier=1.0,
        multiplier=20.0,
        tick_value=5.00
    ))
    next_id += 1
    
    return instruments