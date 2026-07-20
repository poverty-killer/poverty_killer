"""
Instrument Registry - Central Symbol Metadata Management
Holds asset class metadata for crypto, equity, ETF, and futures.
Enables multi-market support with session awareness and exchange routing.
HARDENED: Proper price rounding with math.floor for limit buys and math.ceil for limit sells.
Whale threshold in USD ($500k minimum).
"""

import logging
import math
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional, List, Any, Tuple
from dataclasses import dataclass, field

from app.constants import AssetClass, MarketSession, ExchangeType

logger = logging.getLogger(__name__)


@dataclass
class InstrumentSpec:
    """
    Complete instrument specification.
    Contains all metadata needed for trading across markets.
    """
    symbol: str
    asset_class: AssetClass
    exchange: ExchangeType
    min_size: float
    step_size: float
    tick_size: float
    margin_available: bool = False
    session: MarketSession = MarketSession.CRYPTO_24_7
    description: str = ""
    
    # For equities (sector, etc.)
    sector: Optional[str] = None
    underlying: Optional[str] = None  # For ETFs and futures
    
    # For futures
    multiplier: Optional[float] = None
    margin_required: Optional[float] = None
    tick_value: Optional[float] = None
    
    # For crypto
    whale_threshold_usd: Optional[float] = None
    
    # Order limits
    max_order_size: Optional[float] = None
    min_notional: Optional[float] = None
    
    # Risk multipliers
    volatility_multiplier: float = 1.0
    liquidity_multiplier: float = 1.0
    execution_authorized: bool = False
    constraint_source: str = "static_reference_non_authoritative"
    min_size_exact: Decimal = field(init=False)
    step_size_exact: Decimal = field(init=False)
    tick_size_exact: Decimal = field(init=False)
    min_notional_exact: Optional[Decimal] = field(init=False)
    
    def __post_init__(self):
        """Validate instrument specification."""
        if self.min_size <= 0:
            raise ValueError(f"min_size must be positive for {self.symbol}")
        if self.step_size <= 0:
            raise ValueError(f"step_size must be positive for {self.symbol}")
        if self.tick_size <= 0:
            raise ValueError(f"tick_size must be positive for {self.symbol}")
        try:
            self.min_size_exact = Decimal(str(self.min_size))
            self.step_size_exact = Decimal(str(self.step_size))
            self.tick_size_exact = Decimal(str(self.tick_size))
            self.min_notional_exact = Decimal(str(self.min_notional)) if self.min_notional is not None else None
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"invalid exact Decimal constraints for {self.symbol}") from exc
        exact_values = (self.min_size_exact, self.step_size_exact, self.tick_size_exact)
        if any(not value.is_finite() or value <= Decimal("0") for value in exact_values):
            raise ValueError(f"nonpositive or nonfinite exact constraints for {self.symbol}")
        if self.min_notional_exact is not None and (
            not self.min_notional_exact.is_finite() or self.min_notional_exact <= Decimal("0")
        ):
            raise ValueError(f"nonpositive or nonfinite exact min_notional for {self.symbol}")


class InstrumentRegistry:
    """
    Central registry for all tradable instruments.
    Provides metadata, session checking, and exchange routing.
    """
    
    # Complete instrument catalog
    INSTRUMENTS: Dict[str, InstrumentSpec] = {}
    
    @classmethod
    def _init_crypto(cls):
        """Initialize crypto instruments with USD whale thresholds."""
        # Whale threshold: $500,000 USD minimum
        cls.INSTRUMENTS["BTC/USD"] = InstrumentSpec(
            symbol="BTC/USD",
            asset_class=AssetClass.CRYPTO,
            exchange=ExchangeType.ALPACA,
            min_size=0.0001,
            step_size=0.0001,
            tick_size=0.01,
            margin_available=False,
            session=MarketSession.CRYPTO_24_7,
            description="Bitcoin / US Dollar",
            whale_threshold_usd=500000.0,  # $500,000 USD
            max_order_size=100.0,
            min_notional=10.0,
            volatility_multiplier=1.5,
            liquidity_multiplier=1.0,
        )
        
        cls.INSTRUMENTS["ETH/USD"] = InstrumentSpec(
            symbol="ETH/USD",
            asset_class=AssetClass.CRYPTO,
            exchange=ExchangeType.ALPACA,
            min_size=0.001,
            step_size=0.001,
            tick_size=0.01,
            margin_available=False,
            session=MarketSession.CRYPTO_24_7,
            description="Ethereum / US Dollar",
            whale_threshold_usd=500000.0,  # $500,000 USD
            max_order_size=1000.0,
            min_notional=10.0,
            volatility_multiplier=1.3,
            liquidity_multiplier=1.0,
        )
        
        cls.INSTRUMENTS["SOL/USD"] = InstrumentSpec(
            symbol="SOL/USD",
            asset_class=AssetClass.CRYPTO,
            exchange=ExchangeType.ALPACA,
            min_size=0.01,
            step_size=0.01,
            tick_size=0.01,
            margin_available=False,
            session=MarketSession.CRYPTO_24_7,
            description="Solana / US Dollar",
            whale_threshold_usd=500000.0,  # $500,000 USD
            max_order_size=10000.0,
            min_notional=10.0,
            volatility_multiplier=1.8,
            liquidity_multiplier=0.8,
        )

        alpaca_confirmed_crypto = (
            (
                "LTC/USD",
                "Litecoin / US Dollar",
                0.022079929,
                0.000000001,
                0.000000001,
                1.6,
                0.8,
            ),
            (
                "AVAX/USD",
                "Avalanche / US Dollar",
                0.148669924,
                0.000000001,
                0.000000001,
                1.9,
                0.7,
            ),
            (
                "LINK/USD",
                "Chainlink / US Dollar",
                0.12300123,
                0.000000001,
                0.000000001,
                1.7,
                0.75,
            ),
        )
        for (
            symbol,
            description,
            min_order_size,
            min_trade_increment,
            price_increment,
            volatility_multiplier,
            liquidity_multiplier,
        ) in alpaca_confirmed_crypto:
            cls.INSTRUMENTS[symbol] = InstrumentSpec(
                symbol=symbol,
                asset_class=AssetClass.CRYPTO,
                exchange=ExchangeType.ALPACA,
                min_size=min_order_size,
                step_size=min_trade_increment,
                tick_size=price_increment,
                margin_available=False,
                session=MarketSession.CRYPTO_24_7,
                description=description,
                whale_threshold_usd=500000.0,
                min_notional=10.0,
                volatility_multiplier=volatility_multiplier,
                liquidity_multiplier=liquidity_multiplier,
            )
    
    @classmethod
    def _init_equities(cls):
        """Initialize equity instruments."""
        # Nasdaq high-growth tech (Information Asymmetry targets)
        nasdaq_stocks = [
            ("AAPL", "Apple Inc.", "TECH"),
            ("MSFT", "Microsoft Corp.", "TECH"),
            ("NVDA", "NVIDIA Corp.", "TECH"),
            ("AMZN", "Amazon.com Inc.", "CONSUMER"),
            ("META", "Meta Platforms Inc.", "TECH"),
            ("GOOGL", "Alphabet Inc.", "TECH"),
        ]
        
        for symbol, name, sector in nasdaq_stocks:
            cls.INSTRUMENTS[symbol] = InstrumentSpec(
                symbol=symbol,
                asset_class=AssetClass.EQUITY,
                exchange=ExchangeType.ALPACA,
                min_size=1,
                step_size=1,
                tick_size=0.01,
                margin_available=True,
                session=MarketSession.EQUITY,
                description=name,
                sector=sector,
                volatility_multiplier=1.2,
                liquidity_multiplier=1.0,
                min_notional=1.0,
            )
        
        # S&P 500 components
        sp500_stocks = [
            ("JPM", "JPMorgan Chase", "FINANCIALS"),
            ("JNJ", "Johnson & Johnson", "HEALTHCARE"),
            ("WMT", "Walmart Inc.", "CONSUMER"),
        ]
        
        for symbol, name, sector in sp500_stocks:
            cls.INSTRUMENTS[symbol] = InstrumentSpec(
                symbol=symbol,
                asset_class=AssetClass.EQUITY,
                exchange=ExchangeType.ALPACA,
                min_size=1,
                step_size=1,
                tick_size=0.01,
                margin_available=True,
                session=MarketSession.EQUITY,
                description=name,
                sector=sector,
                volatility_multiplier=1.0,
                liquidity_multiplier=1.0,
                min_notional=1.0,
            )
    
    @classmethod
    def _init_etfs(cls):
        """Initialize ETF instruments."""
        etfs = [
            ("SPY", "SPDR S&P 500 ETF", "SPX"),
            ("QQQ", "Invesco QQQ Trust", "NDX"),
            ("DIA", "SPDR Dow Jones Industrial Average", "DJI"),
        ]
        
        for symbol, name, underlying in etfs:
            cls.INSTRUMENTS[symbol] = InstrumentSpec(
                symbol=symbol,
                asset_class=AssetClass.ETF,
                exchange=ExchangeType.ALPACA,
                min_size=1,
                step_size=1,
                tick_size=0.01,
                margin_available=True,
                session=MarketSession.EQUITY,
                description=name,
                underlying=underlying,
                volatility_multiplier=0.9,
                liquidity_multiplier=1.2,
                min_notional=1.0,
            )
    
    @classmethod
    def _init_futures(cls):
        """Initialize futures instruments (CME via IBKR)."""
        futures = [
            ("ES", "E-mini S&P 500 Future", "SPX", 50.0, 12000.0, 12.50),
            ("NQ", "E-mini Nasdaq 100 Future", "NDX", 20.0, 15000.0, 5.00),
            ("YM", "E-mini Dow Future", "DJI", 5.0, 8000.0, 5.00),
        ]
        
        for symbol, name, underlying, multiplier, margin, tick_value in futures:
            cls.INSTRUMENTS[symbol] = InstrumentSpec(
                symbol=symbol,
                asset_class=AssetClass.FUTURE,
                exchange=ExchangeType.IBKR,
                min_size=1,
                step_size=1,
                tick_size=0.25,
                margin_available=True,
                session=MarketSession.FUTURES,
                description=name,
                underlying=underlying,
                multiplier=multiplier,
                margin_required=margin,
                tick_value=tick_value,
                volatility_multiplier=2.0,
                liquidity_multiplier=1.0,
                min_notional=margin,  # Minimum capital required
            )
    
    @classmethod
    def initialize(cls):
        """Initialize all instrument catalogs."""
        cls._init_crypto()
        cls._init_equities()
        cls._init_etfs()
        cls._init_futures()
        logger.info(f"InstrumentRegistry initialized with {len(cls.INSTRUMENTS)} instruments")
    
    @classmethod
    def get_instrument(cls, symbol: str) -> Optional[InstrumentSpec]:
        """Get instrument specification by symbol."""
        if not cls.INSTRUMENTS:
            cls.initialize()
        return cls.INSTRUMENTS.get(symbol)
    
    @classmethod
    def get_asset_class(cls, symbol: str) -> Optional[AssetClass]:
        """Get asset class for a symbol."""
        inst = cls.get_instrument(symbol)
        return inst.asset_class if inst else None
    
    @classmethod
    def get_exchange(cls, symbol: str) -> Optional[ExchangeType]:
        """Get exchange for a symbol."""
        inst = cls.get_instrument(symbol)
        return inst.exchange if inst else None
    
    @classmethod
    def get_session(cls, symbol: str) -> MarketSession:
        """Get trading session for a symbol."""
        inst = cls.get_instrument(symbol)
        return inst.session if inst else MarketSession.CRYPTO_24_7
    
    @classmethod
    def get_min_size(cls, symbol: str) -> float:
        """Get minimum order size."""
        inst = cls.get_instrument(symbol)
        return inst.min_size if inst else 0.0
    
    @classmethod
    def get_step_size(cls, symbol: str) -> float:
        """Get order size step increment."""
        inst = cls.get_instrument(symbol)
        return inst.step_size if inst else 0.0
    
    @classmethod
    def get_tick_size(cls, symbol: str) -> float:
        """Get price tick size."""
        inst = cls.get_instrument(symbol)
        return inst.tick_size if inst else 0.0
    
    @classmethod
    def round_quantity(cls, symbol: str, quantity: float) -> float:
        """
        Round quantity to valid step size.
        
        Args:
            symbol: Trading symbol
            quantity: Desired quantity
            
        Returns:
            Rounded quantity
        """
        inst = cls.get_instrument(symbol)
        if not inst:
            return quantity
        
        # Round to nearest step size
        steps = round(quantity / inst.step_size)
        rounded = steps * inst.step_size
        
        # Ensure not below minimum
        rounded = max(rounded, inst.min_size)
        
        return rounded
    
    @classmethod
    def round_price(cls, symbol: str, price: float, side: str) -> float:
        """
        Round price to valid tick size with proper direction for order type.
        
        For limit orders:
        - BUY orders: round DOWN (floor) to ensure order is fillable
        - SELL orders: round UP (ceil) to ensure order is fillable
        This prevents orders from being placed at prices that don't exist on the exchange.
        
        Args:
            symbol: Trading symbol
            price: Desired price
            side: Order side ("buy" or "sell")
            
        Returns:
            Rounded price
        """
        inst = cls.get_instrument(symbol)
        if not inst:
            return price
        
        tick = inst.tick_size
        if tick == 0:
            return price
        
        # Round based on order side
        if side == "buy":
            # BUY: round down (floor) to ensure order is at or below market
            rounded = math.floor(price / tick) * tick
        else:  # sell
            # SELL: round up (ceil) to ensure order is at or above market
            rounded = math.ceil(price / tick) * tick
        
        # Ensure positive
        rounded = max(rounded, tick)
        
        return rounded
    
    @classmethod
    def is_tradable_now(cls, symbol: str, current_time: Optional[datetime] = None) -> bool:
        """
        Check if market is open for this instrument.
        
        Args:
            symbol: Trading symbol
            current_time: Current time (defaults to UTC now)
            
        Returns:
            True if market is open
        """
        inst = cls.get_instrument(symbol)
        if not inst:
            return False
        
        if current_time is None:
            current_time = datetime.utcnow()
        
        session = inst.session
        
        if session == MarketSession.CRYPTO_24_7:
            return True
        
        if session == MarketSession.EQUITY:
            return cls._is_equity_hours(current_time)
        
        if session == MarketSession.FUTURES:
            return cls._is_futures_hours(current_time)
        
        return False
    
    @classmethod
    def _is_equity_hours(cls, dt: datetime) -> bool:
        """Check if during equity trading hours (9:30 AM - 4:00 PM EST)."""
        # Convert to EST
        try:
            import pytz
            est = pytz.timezone('US/Eastern')
            dt_est = dt.astimezone(est)
        except ImportError:
            # Fallback - assume UTC
            dt_est = dt
        
        # Weekend
        if dt_est.weekday() >= 5:
            return False
        
        market_open = dt_est.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = dt_est.replace(hour=16, minute=0, second=0, microsecond=0)
        
        return market_open <= dt_est <= market_close
    
    @classmethod
    def _is_futures_hours(cls, dt: datetime) -> bool:
        """Check if during futures trading hours (Sunday 6pm - Friday 5pm EST)."""
        try:
            import pytz
            est = pytz.timezone('US/Eastern')
            dt_est = dt.astimezone(est)
        except ImportError:
            dt_est = dt
        
        # Sunday after 6pm is open
        if dt_est.weekday() == 6 and dt_est.hour >= 18:
            return True
        
        # Monday-Thursday: all day
        if 0 <= dt_est.weekday() <= 3:
            return True
        
        # Friday: before 5pm
        if dt_est.weekday() == 4 and dt_est.hour < 17:
            return True
        
        return False
    
    @classmethod
    def get_risk_multiplier(cls, symbol: str) -> float:
        """
        Get risk multiplier based on asset class and volatility.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Risk multiplier (higher = more risky)
        """
        inst = cls.get_instrument(symbol)
        if not inst:
            return 1.0
        
        base_multipliers = {
            AssetClass.CRYPTO: 1.5,
            AssetClass.EQUITY: 1.0,
            AssetClass.ETF: 0.8,
            AssetClass.FUTURE: 2.0,
        }
        
        base = base_multipliers.get(inst.asset_class, 1.0)
        return base * inst.volatility_multiplier
    
    @classmethod
    def get_liquidity_multiplier(cls, symbol: str) -> float:
        """
        Get liquidity multiplier for position sizing.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Liquidity multiplier (higher = more liquid)
        """
        inst = cls.get_instrument(symbol)
        if not inst:
            return 1.0
        return inst.liquidity_multiplier
    
    @classmethod
    def get_all_symbols(cls, asset_class: Optional[AssetClass] = None) -> List[str]:
        """
        Get all symbols, optionally filtered by asset class.
        
        Args:
            asset_class: Optional asset class filter
            
        Returns:
            List of symbols
        """
        if not cls.INSTRUMENTS:
            cls.initialize()
        
        if asset_class:
            return [
                sym for sym, inst in cls.INSTRUMENTS.items()
                if inst.asset_class == asset_class
            ]
        return list(cls.INSTRUMENTS.keys())
    
    @classmethod
    def get_symbols_by_exchange(cls, exchange: ExchangeType) -> List[str]:
        """Get all symbols traded on a specific exchange."""
        if not cls.INSTRUMENTS:
            cls.initialize()
        
        return [
            sym for sym, inst in cls.INSTRUMENTS.items()
            if inst.exchange == exchange
        ]
    
    @classmethod
    def validate_order(cls, symbol: str, quantity: float, price: Optional[float] = None, side: Optional[str] = None) -> Tuple[bool, str]:
        """
        Validate order against instrument constraints.
        
        Args:
            symbol: Trading symbol
            quantity: Order quantity
            price: Order price (for limit orders)
            side: Order side ("buy" or "sell") for price rounding validation
            
        Returns:
            (is_valid, error_message)
        """
        inst = cls.get_instrument(symbol)
        if not inst:
            return False, f"Unknown symbol: {symbol}"
        if not inst.execution_authorized:
            return False, (
                f"Static instrument reference is not execution-authorized: {symbol} "
                f"({inst.constraint_source})"
            )
        
        # Check minimum size
        if quantity < inst.min_size:
            return False, f"Quantity {quantity} below minimum {inst.min_size}"
        
        # Check step size
        steps = quantity / inst.step_size
        if abs(steps - round(steps)) > 1e-10:
            return False, f"Quantity {quantity} not multiple of step size {inst.step_size}"
        
        # Check max order size
        if inst.max_order_size and quantity > inst.max_order_size:
            return False, f"Quantity {quantity} exceeds max {inst.max_order_size}"
        
        # Check notional value
        if inst.min_notional and price:
            notional = quantity * price
            if notional < inst.min_notional:
                return False, f"Notional {notional:.2f} below minimum {inst.min_notional:.2f}"
        
        # Validate price is on tick boundary if side provided
        if price and side:
            rounded_price = cls.round_price(symbol, price, side)
            if abs(price - rounded_price) > 1e-10:
                return False, f"Price {price} not on tick boundary (tick={inst.tick_size}). Suggested: {rounded_price}"
        
        return True, "OK"
    
    @classmethod
    def get_whale_threshold_usd(cls, symbol: str) -> float:
        """
        Get whale detection threshold in USD.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Whale threshold in USD (minimum $500,000)
        """
        inst = cls.get_instrument(symbol)
        if inst and inst.whale_threshold_usd:
            return inst.whale_threshold_usd
        return 500000.0  # Default $500,000 USD
