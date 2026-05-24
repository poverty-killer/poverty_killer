"""
POVERTY KILLER — Universal Instrument Profile

Pre-integration, passive model only.

This module defines the canonical InstrumentProfile that will eventually
replace bare symbol strings throughout the engine. It is the single source
of truth for every tradable instrument across crypto, equities, ETFs,
futures, forex, and commodities.

Design constraints:
- No imports from current runtime modules (MainLoop, SignalFusion, Risk, etc.)
- No side effects at import time.
- No network calls.
- No broker calls.
- No wall-clock authority.
- Deterministic and replay-safe.
- Decimal for all monetary/size/tick/notional values.
- Type hints required throughout.

Board escalation markers:
- Fields marked with "BOARD ESCALATION: EXTERNAL DATA REQUIRED" will need
  production-grade data sources during integration (G2+).
- Fields marked with placeholder defaults are explicitly provisional
  and must be replaced with real data during integration.

Author: D / DeepSeek — Stage 2-G0B
Date: 2026-05-03
Status: PRE-INTEGRATION — NO LIVE WIRING
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, IntEnum, unique
from typing import Optional, Tuple, FrozenSet, List, Dict, Any


# ────────────────────────────────────────────────────────────────
# Asset Classification Enums
# ────────────────────────────────────────────────────────────────

@unique
class AssetClass(str, Enum):
    """Top-level asset classification for instrument grouping."""
    CRYPTO = "crypto"
    EQUITY = "equity"
    ETF = "etf"
    INDEX = "index"          # Reference-only; not tradable directly
    FUTURE = "future"
    FOREX = "forex"
    COMMODITY = "commodity"
    OPTION = "option"        # Requires separate Board approval for activation


@unique
class InstrumentType(str, Enum):
    """Granular instrument type within each asset class."""
    # Crypto
    SPOT = "spot"
    PERPETUAL_SWAP = "perpetual_swap"
    # Equities
    COMMON_STOCK = "common_stock"
    PREFERRED_STOCK = "preferred_stock"
    ADR = "adr"
    REIT = "reit"
    RIGHT = "right"
    WARRANT = "warrant"
    # ETFs
    ETF_EQUITY = "etf_equity"
    ETF_BOND = "etf_bond"
    ETF_COMMODITY = "etf_commodity"
    ETF_CURRENCY = "etf_currency"
    ETF_LEVERAGED = "etf_leveraged"
    ETF_INVERSE = "etf_inverse"
    # Index
    INDEX_EQUITY = "index_equity"
    INDEX_VOLATILITY = "index_volatility"
    # Futures
    FUTURE_EQUITY_INDEX = "future_equity_index"
    FUTURE_COMMODITY = "future_commodity"
    FUTURE_CURRENCY = "future_currency"
    FUTURE_INTEREST_RATE = "future_interest_rate"
    # Forex
    SPOT_FX = "spot_fx"
    FOREX_FORWARD = "forex_forward"
    # Commodities
    COMMODITY_PHYSICAL = "commodity_physical"


@unique
class SettlementType(str, Enum):
    """How the instrument settles post-trade."""
    T_PLUS_0 = "t+0"           # Crypto spot, perpetuals
    T_PLUS_1 = "t+1"
    T_PLUS_2 = "t+2"           # US equities standard
    MARK_TO_MARKET = "mark_to_market"  # Futures daily settlement
    PHYSICAL = "physical"       # Physical commodities
    CASH = "cash"              # Cash-settled options


@unique
class SessionModel(str, Enum):
    """Session cadence model for the instrument."""
    CONTINUOUS_24_7 = "continuous_24_7"
    US_EQUITY_REGULAR = "us_equity_regular"
    US_EQUITY_EXTENDED = "us_equity_extended"
    US_FUTURES_CME = "us_futures_cme"
    US_FUTURES_CME_EXTENDED = "us_futures_cme_extended"
    FOREX_WEEKLY = "forex_weekly"


@unique
class AuctionModel(str, Enum):
    """Auction participation model."""
    NONE = "none"                     # Continuous markets (crypto)
    NYSE_OPENING = "nyse_opening"     # 9:30 ET opening auction
    NYSE_CLOSING = "nyse_closing"     # 16:00 ET closing auction
    CME_SETTLEMENT = "cme_settlement" # CME settlement auction


@unique
class LiquidityTier(IntEnum):
    """Relative liquidity classification for capacity estimation."""
    ULTRA_LIQUID = 0    # SPY, BTC, ES — effectively unlimited retail capacity
    DEEPLY_LIQUID = 1   # QQQ, ETH, AAPL, MSFT, NQ
    LIQUID = 2          # DIA, IWM, SOL, NVDA
    MODERATE = 3        # Mid-cap equities, small ETFs
    THIN = 4            # Small-cap, illiquid ETFs
    RESTRICTED = 5      # Reference-only, or capacity so small it's not actionable


@unique
class RiskBucket(str, Enum):
    """Risk classification bucket for cross-asset grouping."""
    CRYPTO_MAJOR = "crypto_major"
    CRYPTO_ALT = "crypto_alt"
    EQUITY_LARGE_CAP = "equity_large_cap"
    EQUITY_MID_CAP = "equity_mid_cap"
    EQUITY_SMALL_CAP = "equity_small_cap"
    ETF_BROAD_MARKET = "etf_broad_market"
    ETF_SECTOR = "etf_sector"
    FUTURE_EQUITY_INDEX = "future_equity_index"
    FUTURE_COMMODITY = "future_commodity"
    FUTURE_CURRENCY = "future_currency"
    FOREX_MAJOR = "forex_major"
    FOREX_MINOR = "forex_minor"
    INDEX_REFERENCE = "index_reference"  # Not tradable


# ────────────────────────────────────────────────────────────────
# Core Instrument Models
# ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InstrumentConstraints:
    """
    Hard trading constraints derived from instrument profile and venue rules.

    All monetary/size fields use Decimal for precision and replay-safety.
    """
    tick_size: Decimal
    lot_size: Decimal
    min_order_size: Decimal
    min_notional_usd: Decimal
    max_order_quantity: Decimal
    contract_multiplier: Decimal = Decimal("1.0")
    point_value: Decimal = Decimal("1.0")
    supported_order_types: FrozenSet[str] = field(default_factory=lambda: frozenset({"market", "limit"}))
    supported_time_in_force: FrozenSet[str] = field(default_factory=lambda: frozenset({"GTC", "IOC", "DAY"}))
    participation_rate_limit: Decimal = Decimal("0.05")  # 5% of ADV per order
    adv_participation_cap: Decimal = Decimal("0.15")      # 15% of ADV total position
    max_spread_bps: Decimal = Decimal("25.0")
    max_slippage_bps: Decimal = Decimal("50.0")

    def __post_init__(self):
        """Validate constraint consistency."""
        assert self.tick_size > Decimal("0"), f"tick_size must be positive: {self.tick_size}"
        assert self.lot_size > Decimal("0"), f"lot_size must be positive: {self.lot_size}"
        assert self.min_order_size >= self.lot_size, f"min_order_size must be >= lot_size"
        assert self.min_notional_usd >= Decimal("0"), f"min_notional_usd must be non-negative"
        assert self.contract_multiplier > Decimal("0"), f"contract_multiplier must be positive"
        assert self.point_value > Decimal("0"), f"point_value must be positive"
        assert Decimal("0") <= self.participation_rate_limit <= Decimal("1")
        assert Decimal("0") <= self.adv_participation_cap <= Decimal("1")


@dataclass(frozen=True)
class ExpiryInfo:
    """Contract expiry and roll mechanics for futures/options."""
    has_expiry: bool = False
    expiry_date_ns: Optional[int] = None       # Timestamp of contract expiry
    first_notice_date_ns: Optional[int] = None # For physical delivery futures
    last_trading_date_ns: Optional[int] = None
    roll_schedule: Optional[str] = None        # "quarterly", "monthly", etc.
    roll_window_start_ns: Optional[int] = None  # When roll begins before expiry
    roll_window_end_ns: Optional[int] = None
    # BOARD ESCALATION: EXTERNAL DATA REQUIRED for exact expiry/roll calendars
    # These are placeholder values; production requires a contract calendar source.


@dataclass(frozen=True)
class InstrumentProfile:
    """
    Universal instrument master — single source of truth for any tradable instrument.

    This replaces bare symbol strings throughout the engine. Every field is
    immutable (frozen dataclass) to prevent accidental mutation during runtime.

    Design follows Citadel-grade instrument master principles:
    - Identity: Who is this instrument?
    - Tradability: Can we trade it now?
    - Contract Mechanics: How does it settle/multiply/tick?
    - Market Mechanics: When and how does it trade?
    - Execution Constraints: How can we interact with it?
    - Cost/Risk References: What models apply?
    """

    # ── Identity ──────────────────────────────────────────────
    instrument_id: str
    symbol: str                         # Canonical symbol (e.g., "BTC/USD", "SPY")
    canonical_symbol: str               # Normalized for internal use
    venue_symbol: str                   # Symbol as the venue expects it
    display_symbol: str                 # Human-readable
    root_symbol: str                    # For futures: "ES" from "ESM26"
    asset_class: AssetClass
    instrument_type: InstrumentType
    venue: str                          # "KRAKEN", "NYSE", "NASDAQ", "CME", etc.
    primary_exchange: str               # MIC code or exchange identifier
    currency: str                       # "USD"
    quote_currency: str                 # For pairs: "USD" in BTC/USD
    base_currency: Optional[str]        # For pairs: "BTC" in BTC/USD
    country: str                        # "US", "GB", etc.
    region: str                         # "North America", "Europe", etc.
    timezone: str                       # "America/New_York", "UTC", etc.

    # ── Tradability ──────────────────────────────────────────
    enabled: bool = False               # Master kill-switch; MUST be False for non-current
    paper_tradable: bool = False        # Can trade in paper mode
    live_tradable: bool = False         # Can trade live (requires Board approval)
    reference_only: bool = False        # Index reference; cannot be traded
    shortable: bool = False             # Short selling permitted
    fractional_allowed: bool = False    # Fractional shares/contracts
    borrow_required: bool = False       # Must locate/borrow before short
    locate_required: bool = False       # Hard locate required (equities)
    marginable: bool = False            # Margin trading allowed
    options_underlying: bool = False    # Options exist on this instrument

    # ── Contract Mechanics ────────────────────────────────────
    constraints: InstrumentConstraints = field(
        default_factory=lambda: InstrumentConstraints(
            tick_size=Decimal("0.01"),
            lot_size=Decimal("1"),
            min_order_size=Decimal("1"),
            min_notional_usd=Decimal("10"),
            max_order_quantity=Decimal("1000000"),
        )
    )
    expiry: ExpiryInfo = field(default_factory=ExpiryInfo)
    settlement_type: SettlementType = SettlementType.T_PLUS_0
    mark_to_market_frequency: str = "continuous"  # "daily", "continuous", "none"

    # ── Market Mechanics ─────────────────────────────────────
    session_model: SessionModel = SessionModel.CONTINUOUS_24_7
    auction_model: AuctionModel = AuctionModel.NONE
    halt_behavior: str = "none"           # "suspend_signals", "cancel_open_orders", "none"
    circuit_breaker_levels: Tuple[float, ...] = field(default_factory=tuple)
    overnight_gap_policy: str = "none"    # "reject_open_orders", "warn", "none"
    extended_hours_policy: str = "none"   # "allow", "paper_only", "reject"

    # ── Cost/Risk References ─────────────────────────────────
    fee_model_id: str = "default_crypto"
    slippage_model_id: str = "default_crypto"
    margin_model_id: str = "none"
    borrow_model_id: Optional[str] = None
    tax_lot_model_id: Optional[str] = None
    risk_bucket: RiskBucket = RiskBucket.CRYPTO_MAJOR
    correlation_cluster: str = ""
    sector: str = ""
    industry: str = ""
    beta_reference: str = ""              # Symbol for beta calculation
    benchmark_reference: str = ""         # Benchmark for relative comparisons
    liquidity_tier: LiquidityTier = LiquidityTier.LIQUID

    # ── Reference Data ───────────────────────────────────────
    adv_shares: Optional[Decimal] = None          # Average daily volume in shares/contracts
    adv_notional_usd: Optional[Decimal] = None    # Average daily volume in USD
    market_cap_usd: Optional[Decimal] = None
    float_shares: Optional[Decimal] = None
    short_interest_pct: Optional[Decimal] = None

    def __post_init__(self):
        """Validate profile consistency."""
        if self.reference_only:
            assert not self.paper_tradable, f"reference_only {self.symbol} cannot be paper_tradable"
            assert not self.live_tradable, f"reference_only {self.symbol} cannot be live_tradable"
        if self.shortable:
            assert self.borrow_required or not self.locate_required, \
                f"shortable {self.symbol} must have borrow/locate model"
        if self.asset_class == AssetClass.INDEX:
            assert self.reference_only, f"Index {self.symbol} must be reference_only"
        if self.constraints.contract_multiplier != Decimal("1"):
            assert self.asset_class in (AssetClass.FUTURE, AssetClass.OPTION), \
                f"contract_multiplier > 1 only valid for futures/options: {self.symbol}"

    def notional_value(self, quantity: Decimal, price: Decimal) -> Decimal:
        """Calculate notional value accounting for contract multiplier."""
        return quantity * price * self.constraints.contract_multiplier

    def round_quantity(self, quantity: Decimal) -> Decimal:
        """Round quantity to lot_size."""
        lot = self.constraints.lot_size
        return (quantity / lot).to_integral_value() * lot

    def round_price(self, price: Decimal) -> Decimal:
        """Round price to tick_size."""
        tick = self.constraints.tick_size
        return (price / tick).to_integral_value() * tick

    def to_dict(self) -> Dict[str, Any]:
        """Safe dict representation for serialization."""
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "canonical_symbol": self.canonical_symbol,
            "venue_symbol": self.venue_symbol,
            "display_symbol": self.display_symbol,
            "root_symbol": self.root_symbol,
            "asset_class": self.asset_class.value,
            "instrument_type": self.instrument_type.value,
            "venue": self.venue,
            "primary_exchange": self.primary_exchange,
            "currency": self.currency,
            "quote_currency": self.quote_currency,
            "base_currency": self.base_currency,
            "country": self.country,
            "region": self.region,
            "timezone": self.timezone,
            "enabled": self.enabled,
            "paper_tradable": self.paper_tradable,
            "live_tradable": self.live_tradable,
            "reference_only": self.reference_only,
            "shortable": self.shortable,
            "fractional_allowed": self.fractional_allowed,
            "borrow_required": self.borrow_required,
            "locate_required": self.locate_required,
            "marginable": self.marginable,
            "options_underlying": self.options_underlying,
            "tick_size": str(self.constraints.tick_size),
            "lot_size": str(self.constraints.lot_size),
            "min_order_size": str(self.constraints.min_order_size),
            "min_notional_usd": str(self.constraints.min_notional_usd),
            "contract_multiplier": str(self.constraints.contract_multiplier),
            "point_value": str(self.constraints.point_value),
            "settlement_type": self.settlement_type.value,
            "session_model": self.session_model.value,
            "auction_model": self.auction_model.value,
            "liquidity_tier": self.liquidity_tier.name,
            "risk_bucket": self.risk_bucket.value,
            "correlation_cluster": self.correlation_cluster,
            "sector": self.sector,
            "industry": self.industry,
        }


@dataclass(frozen=True)
class InstrumentQualificationResult:
    """
    Pre-integration qualification output.

    Produced by app/markets/instrument_qualifier.py.
    Consumed by: nothing yet (pre-integration).
    """
    instrument_id: str
    symbol: str
    qualified: bool
    grade: str              # "A", "B", "C", "D", "F"
    score: Decimal          # 0.0 — 1.0
    hard_blocks: Tuple[str, ...] = field(default_factory=tuple)
    soft_warnings: Tuple[str, ...] = field(default_factory=tuple)
    capacity_usd: Decimal = Decimal("0")
    max_position_notional: Decimal = Decimal("0")
    max_order_notional: Decimal = Decimal("0")
    reason_codes: Tuple[str, ...] = field(default_factory=tuple)
    evidence: Dict[str, Any] = field(default_factory=dict)
    timestamp_ns: int = 0


# ────────────────────────────────────────────────────────────────
# Module Exports
# ────────────────────────────────────────────────────────────────

__all__ = [
    "AssetClass",
    "InstrumentType",
    "SettlementType",
    "SessionModel",
    "AuctionModel",
    "LiquidityTier",
    "RiskBucket",
    "InstrumentConstraints",
    "ExpiryInfo",
    "InstrumentProfile",
    "InstrumentQualificationResult",
]