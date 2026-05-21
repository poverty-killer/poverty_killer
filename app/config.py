"""
Configuration Management
Pydantic-based typed configuration with environment variable support.
All risk governance parameters are centralized and validated at startup.
HARDENED: Asset-class specific leverage, SigmaRiskConfig for regime-based scaling
"""

from typing import List, Optional, Dict, Literal
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from pydantic_settings import BaseSettings
import json
import os


def _env_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off", ""}:
        return False
    return default


def _env_list(value: str | None) -> List[str]:
    if value is None:
        return []
    stripped = value.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        return [str(item).strip() for item in json.loads(stripped) if str(item).strip()]
    return [item.strip() for item in stripped.split(",") if item.strip()]


# ============================================
# RISK CONFIGURATION
# ============================================

class RiskConfig(BaseModel):
    """
    Risk management configuration - Hard Caps Never Bypassed.
    These values are validated at startup and cannot be exceeded by any strategy.
    """
    # Global caps
    max_leverage: float = Field(default=2.0, ge=0, le=10, description="Maximum leverage across all positions")
    max_total_exposure: float = Field(default=0.70, ge=0, le=1, description="Maximum total exposure as % of equity")
    max_single_strategy_exposure: float = Field(default=0.40, ge=0, le=1, description="Maximum exposure per strategy")
    max_positions: int = Field(default=5, ge=1, le=50, description="Maximum concurrent open positions")

    # Drawdown protection
    max_daily_drawdown: float = Field(default=0.08, ge=0, le=1, description="Maximum drawdown in a single day")
    max_24h_drawdown: float = Field(default=0.08, ge=0, le=1, description="Maximum drawdown over rolling 24h")
    kill_switch_enabled: bool = Field(default=True, description="Enable automatic kill switch at 8% drawdown")

    # Cash management
    cash_reserve_percent: float = Field(default=0.30, ge=0, le=1, description="Minimum cash reserve percentage")

    # Per-asset class limits (TOTAL MUST = 1.0)
    max_crypto_exposure: float = Field(default=0.15, ge=0, le=1, description="Maximum exposure to crypto assets")
    max_equity_exposure: float = Field(default=0.35, ge=0, le=1, description="Maximum exposure to equities")
    max_etf_exposure: float = Field(default=0.30, ge=0, le=1, description="Maximum exposure to ETFs")
    max_future_exposure: float = Field(default=0.20, ge=0, le=1, description="Maximum exposure to futures")

    # Per-symbol concentration
    max_per_symbol_exposure: float = Field(default=0.10, ge=0, le=1, description="Maximum exposure to any single symbol")

    # Data safety
    stale_data_threshold_seconds: int = Field(default=10, ge=5, le=300, description="Seconds without data before trading halts")

    # Position management
    max_strategy_silence_seconds: int = Field(default=60, ge=10, le=300, description="Max seconds strategy can be silent before position unwind")

    @property
    def class_limits(self) -> Dict[str, float]:
        """Get class limits as dictionary for easy access."""
        return {
            "CRYPTO": self.max_crypto_exposure,
            "EQUITY": self.max_equity_exposure,
            "ETF": self.max_etf_exposure,
            "FUTURE": self.max_future_exposure,
        }

    def validate_class_limits_total(self) -> bool:
        """Ensure total class limits equal 1.0."""
        total = sum(self.class_limits.values())
        return abs(total - 1.0) < 0.01

    model_config = ConfigDict(extra="forbid")


# ============================================
# ASSET-CLASS SPECIFIC LEVERAGE
# ============================================

class AssetLeverageConfig(BaseModel):
    """
    Asset-class specific leverage settings.
    Futures can have higher leverage (2x) while crypto/equities are capped at 1x.
    """
    crypto: float = Field(default=1.0, ge=0.5, le=3.0, description="Max leverage for crypto")
    equity: float = Field(default=1.0, ge=0.5, le=2.0, description="Max leverage for equities")
    etf: float = Field(default=1.0, ge=0.5, le=2.0, description="Max leverage for ETFs")
    future: float = Field(default=2.0, ge=0.5, le=5.0, description="Max leverage for futures")

    def get_leverage(self, asset_class: str) -> float:
        """Get leverage for a specific asset class."""
        mapping = {
            "CRYPTO": self.crypto,
            "EQUITY": self.equity,
            "ETF": self.etf,
            "FUTURE": self.future,
        }
        return mapping.get(asset_class.upper(), 1.0)

    model_config = ConfigDict(extra="forbid")


# ============================================
# SIGMA RISK CONFIGURATION (Regime-Based Scaling)
# ============================================

class SigmaRiskConfig(BaseModel):
    """
    Dynamic threshold scaling based on market regime.
    Used by signal_fusion.py to adjust strategy sensitivity.
    """

    # Trending regime - more aggressive, lower thresholds
    trending_whale_threshold_multiplier: float = Field(default=0.8, ge=0.5, le=1.5)
    trending_sentiment_threshold_multiplier: float = Field(default=0.7, ge=0.5, le=1.5)
    trending_confidence_multiplier: float = Field(default=1.2, ge=0.5, le=2.0)

    # Ranging regime - more conservative, higher thresholds
    ranging_whale_threshold_multiplier: float = Field(default=1.2, ge=0.5, le=2.0)
    ranging_sentiment_threshold_multiplier: float = Field(default=1.3, ge=0.5, le=2.0)
    ranging_confidence_multiplier: float = Field(default=0.8, ge=0.5, le=1.5)

    # Crisis regime - highly conservative, FLV only
    crisis_whale_threshold_multiplier: float = Field(default=1.5, ge=0.5, le=3.0)
    crisis_sentiment_threshold_multiplier: float = Field(default=1.5, ge=0.5, le=3.0)
    crisis_confidence_multiplier: float = Field(default=0.5, ge=0.3, le=1.0)

    def get_multipliers(self, regime: str) -> Dict[str, float]:
        """Get multipliers for a given regime."""
        if regime == "TRENDING":
            return {
                "whale_threshold": self.trending_whale_threshold_multiplier,
                "sentiment_threshold": self.trending_sentiment_threshold_multiplier,
                "confidence": self.trending_confidence_multiplier,
            }
        elif regime == "RANGING":
            return {
                "whale_threshold": self.ranging_whale_threshold_multiplier,
                "sentiment_threshold": self.ranging_sentiment_threshold_multiplier,
                "confidence": self.ranging_confidence_multiplier,
            }
        elif regime == "CRISIS":
            return {
                "whale_threshold": self.crisis_whale_threshold_multiplier,
                "sentiment_threshold": self.crisis_sentiment_threshold_multiplier,
                "confidence": self.crisis_confidence_multiplier,
            }
        else:
            return {
                "whale_threshold": 1.0,
                "sentiment_threshold": 1.0,
                "confidence": 1.0,
            }

    model_config = ConfigDict(extra="forbid")


# ============================================
# STRATEGY CONFIGURATION
# ============================================

class StrategyConfig(BaseModel):
    """
    Strategy-specific parameters for all 9 strategies.
    Each strategy has its own thresholds and toggles.
    """

    # ===== Shadow-Front =====
    # whale_score is normalized 0-1 by WhaleFlowEngine (WhaleFlowScore.score field, ge=0, le=1).
    # Threshold is on the same normalized scale. Not a z-score.
    whale_threshold: float = Field(default=0.20, ge=0, le=1, description="Normalized 0-1 threshold for whale score detection (WhaleFlowScore.score, not z-score)")
    sentiment_velocity_threshold: float = Field(default=1.5, ge=0, description="Z-score threshold for sentiment ignition")
    min_confidence: float = Field(default=0.6, ge=0, le=1, description="Minimum confidence for trade entry")
    whale_zone_tolerance: float = Field(default=0.02, ge=0, le=0.05, description="Max price deviation from whale zone (%)")

    # ===== FLV (Fractal Liquidity Void) =====
    flv_max_hold_bars: int = Field(default=10, ge=1, le=30, description="Maximum bars to hold FLV position")
    flv_kelly_multiplier: float = Field(default=0.5, ge=0, le=1, description="Kelly fraction multiplier for FLV")
    flv_volume_anomaly_threshold: float = Field(default=3.0, ge=1, description="Volume anomaly Z-score for crisis detection")
    flv_spread_expansion_threshold: float = Field(default=5.0, ge=1, description="Spread expansion multiple for crisis detection")

    # ===== Entropy Decoder =====
    entropy_window_seconds: int = Field(default=60, ge=10, le=600, description="Window for entropy calculation")
    entropy_collapse_percentile: int = Field(default=5, ge=1, le=50, description="Percentile for entropy collapse detection")
    entropy_min_samples: int = Field(default=100, ge=10, description="Minimum trades for entropy calculation")

    # ===== Physical-On-Chain Validator =====
    physical_data_sources_enabled: bool = Field(default=False, description="Enable physical infrastructure data")
    divergence_threshold: float = Field(default=0.5, ge=0, le=2, description="Z-score divergence for signal generation")

    # ===== Convexity Switch =====
    momentum_threshold: float = Field(default=0.7, ge=0, le=1, description="Correlation threshold for momentum regime")
    carry_threshold: float = Field(default=0.3, ge=0, le=1, description="Correlation threshold for carry regime")

    # ===== Hedging Flow Arbitrage =====
    basis_spike_threshold: float = Field(default=2.0, ge=0, description="Z-score for basis spread spike")
    hedge_unwind_window_hours: int = Field(default=24, ge=1, le=72, description="Window for hedge unwind prediction")

    # ===== Adaptive DC Optimizer =====
    dc_min_threshold: float = Field(default=0.002, ge=0.001, le=0.01, description="Minimum threshold for directional changes")
    dc_max_threshold: float = Field(default=0.02, ge=0.005, le=0.05, description="Maximum threshold for directional changes")

    # ===== Gamma-Front (Dark Pool) =====
    dark_pool_enabled: bool = Field(default=True, description="Enable dark pool data tracking")
    options_flow_enabled: bool = Field(default=False, description="Enable options flow data (requires paid API)")
    dark_pool_volume_threshold: float = Field(default=5.0, ge=1, description="Multiple of average trade size for dark pool print")

    # ===== Sector Rotation =====
    sector_inflow_threshold: float = Field(default=1.5, ge=0, description="Volume Z-score for sector inflow detection")
    sector_rotation_ranging_eligible: bool = Field(default=False, description="Opt-in: allow SectorRotation as secondary/fallback in RANGING regime (default OFF preserves current SHADOW_FRONT priority)")

    # ===== Strategy Toggles =====
    shadow_front_enabled: bool = True
    flv_enabled: bool = True
    entropy_decoder_enabled: bool = True
    physical_onchain_enabled: bool = True
    convexity_switch_enabled: bool = True
    hedging_flow_enabled: bool = True
    adaptive_dc_enabled: bool = True
    gamma_front_enabled: bool = True
    sector_rotation_enabled: bool = True

    model_config = ConfigDict(extra="forbid")


# ============================================
# DATA CONFIGURATION
# ============================================

class DataConfig(BaseModel):
    """Data ingestion and storage configuration."""

    max_candles_per_symbol: int = Field(default=1000, ge=100, le=10000, description="Maximum candles to keep per symbol")
    websocket_reconnect_delay: int = Field(default=5, ge=1, le=60, description="Seconds to wait before reconnecting")
    websocket_max_queue_size: int = Field(default=10000, ge=100, le=100000, description="Maximum queued messages before dropping")
    websocket_ping_interval: int = Field(default=30, ge=10, le=120, description="WebSocket ping interval seconds")
    polling_interval_seconds: float = Field(default=1.0, ge=0.1, le=60, description="REST polling interval for non-WS symbols")
    feature_window_slow: int = Field(default=50, ge=10, description="Slow feature window size")
    feature_window_fast: int = Field(default=10, ge=3, description="Fast feature window size")

    model_config = ConfigDict(extra="forbid")


# ============================================
# EXECUTION CONFIGURATION
# ============================================

class ExecutionConfig(BaseModel):
    """Execution realism for paper trading. Simulates real-world conditions."""

    # Latency simulation
    latency_buffer_ms: int = Field(default=50, ge=0, le=5000, description="Base latency for order execution (ms)")
    latency_jitter_ms: int = Field(default=25, ge=0, le=500, description="Random jitter to simulate network variance (ms)")

    # Slippage
    slippage_model_enabled: bool = True
    base_slippage_bps: float = Field(default=1.0, ge=0, le=50, description="Base slippage in basis points")
    market_impact_factor: float = Field(default=0.1, ge=0, le=1, description="Market impact per 1% of volume")

    # Fees
    fee_model_enabled: bool = True
    taker_fee_bps: float = Field(default=16.0, ge=0, le=100, description="Taker fee in basis points")
    maker_fee_bps: float = Field(default=8.0, ge=0, le=50, description="Maker fee in basis points")

    # Order management
    max_order_retries: int = Field(default=3, ge=0, le=10, description="Maximum retries for failed orders")
    retry_delay_seconds: float = Field(default=1.0, ge=0.1, le=10, description="Delay between retries")

    model_config = ConfigDict(extra="forbid")


# ============================================
# MAIN CONFIGURATION
# ============================================

class Config(BaseSettings):
    """
    Main configuration class.
    Loads from environment variables and .env file.
    All settings are validated at startup.
    """

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # ============================================
    # Broker Configuration
    # ============================================
    broker_mode: Literal["paper", "live"] = Field(default="paper", description="paper = simulation, live = real trading")
    shadow_read_only: bool = Field(
        default=False,
        description="Bot-wide read-only runtime gate: allow decisions/telemetry, block broker mutation.",
    )
    reservation_lifecycle_paper_enabled: bool = Field(
        default=False,
        description="Enable paper-only reservation lifecycle mutation. Ignored unless broker_mode is paper.",
    )
    portal_selection_policy: Literal["explicit_preferred_venue", "capability_first", "fail_closed"] = Field(
        default="explicit_preferred_venue",
        description="How the venue capability registry resolves multiple matching portals.",
    )
    preferred_trading_portal: Optional[str] = Field(
        default="alpaca_paper",
        description="Operator-selected portal for explicit_preferred_venue policy.",
    )
    allow_portal_fallback: bool = Field(
        default=False,
        description="Allow fallback when the explicit preferred portal is unsupported.",
    )
    enabled_trading_portals: List[str] = Field(
        default=["kraken_paper", "alpaca_paper"],
        description="Configured paper portals available to capability selection.",
    )
    capability_discovery_mode: Literal["registry", "active_markets"] = Field(
        default="registry",
        description=(
            "registry exposes configured capability metadata across supported asset classes; "
            "active_markets preserves legacy market-filtered runtime discovery."
        ),
    )
    capability_discovery_asset_classes: List[str] = Field(
        default=["crypto", "equity", "etf"],
        description="Asset classes exposed by registry-driven capability discovery.",
    )

    # Legacy market-data venue override. Runtime provider selection should use
    # the provider router; this remains only for explicit compatibility.
    primary_feed_venue: Optional[str] = Field(
        default=None,
        description="Optional explicit legacy market-data venue override."
    )
    market_data_providers: List[str] = Field(
        default=[],
        description="Explicit ordered market-data provider candidates for router selection.",
    )
    crypto_market_data_providers: List[str] = Field(
        default=[],
        description="Explicit ordered executable crypto market-data provider candidates.",
    )
    equity_market_data_providers: List[str] = Field(
        default=[],
        description="Explicit ordered executable equity/ETF market-data provider candidates.",
    )
    options_market_data_providers: List[str] = Field(
        default=[],
        description="Explicit ordered executable options market-data provider candidates.",
    )
    event_providers: List[str] = Field(
        default=[],
        description="Explicit ordered advisory event provider candidates.",
    )
    reference_data_providers: List[str] = Field(
        default=[],
        description="Explicit ordered reference market-data provider candidates.",
    )
    runtime_watchlist: List[str] = Field(
        default=[],
        description="Explicit runtime watchlist. Empty watchlist fails closed before feed startup.",
    )

    # Active market classes — user-controlled declaration of which markets are live.
    # Symbols in symbol_universe whose asset class is NOT in this list are explicitly
    # inactive and will not be fed or traded.
    # Default: ["crypto"] — matches current Kraken-only bring-up.
    # To activate equities: add "equity" here and wire an Alpaca feed.
    # Valid values: crypto, equity, etf, future
    active_markets: List[str] = Field(
        default=["crypto"],
        description="Active market asset classes. Valid: crypto, equity, etf, future."
    )

    @field_validator("active_markets", mode="before")
    @classmethod
    def validate_active_markets(cls, v):
        valid = {"crypto", "equity", "etf", "future"}
        if isinstance(v, str):
            v = json.loads(v) if v.startswith("[") else [v]
        unknown = set(str(m).lower() for m in v) - valid
        if unknown:
            raise ValueError(f"Unknown market class(es): {unknown}. Valid: {valid}")
        return [str(m).lower() for m in v]

    @field_validator("enabled_trading_portals", mode="before")
    @classmethod
    def parse_enabled_trading_portals(cls, v):
        if isinstance(v, str):
            return json.loads(v) if v.startswith("[") else [v]
        return v

    @field_validator(
        "market_data_providers",
        "crypto_market_data_providers",
        "equity_market_data_providers",
        "options_market_data_providers",
        "event_providers",
        "reference_data_providers",
        "runtime_watchlist",
        mode="before",
    )
    @classmethod
    def parse_provider_lists(cls, v):
        if isinstance(v, str):
            return json.loads(v) if v.startswith("[") else [item.strip() for item in v.split(",") if item.strip()]
        return v

    @field_validator("capability_discovery_asset_classes", mode="before")
    @classmethod
    def parse_capability_discovery_asset_classes(cls, v):
        valid = {"crypto", "equity", "us_equity", "etf", "future"}
        if isinstance(v, str):
            v = json.loads(v) if v.startswith("[") else [v]
        unknown = set(str(m).lower() for m in v) - valid
        if unknown:
            raise ValueError(f"Unknown capability discovery asset class(es): {unknown}. Valid: {valid}")
        return [str(m).lower() for m in v]

    @model_validator(mode="after")
    def validate_shadow_read_only_no_live_mode(self):
        if self.shadow_read_only and self.broker_mode != "paper":
            raise ValueError("shadow_read_only requires broker_mode='paper'; live mode is forbidden")
        return self

    # Kraken (Crypto)
    kraken_api_key: Optional[str] = Field(default=None, description="Kraken API key")
    kraken_api_secret: Optional[str] = Field(default=None, description="Kraken API secret")

    # Alpaca (US Equities & ETFs)
    alpaca_api_key: Optional[str] = Field(default=None, description="Alpaca API key")
    alpaca_api_secret: Optional[str] = Field(default=None, description="Alpaca API secret")
    alpaca_paper: bool = Field(default=True, description="Use Alpaca paper trading")

    # Interactive Brokers (Futures)
    ibkr_host: str = Field(default="127.0.0.1", description="IBKR TWS/Gateway host")
    ibkr_port: int = Field(default=7497, description="IBKR port (7497 for TWS, 4001 for Gateway)")
    ibkr_client_id: int = Field(default=1, description="IBKR client ID")

    # ============================================
    # Trading Parameters
    # ============================================
    initial_capital: float = Field(default=20000.0, gt=0, description="Starting capital in USD")

    symbol_universe: List[str] = Field(default=[], description="Explicit legacy symbol universe")

    # ============================================
    # Sub-configurations
    # ============================================
    risk: RiskConfig = Field(default_factory=RiskConfig)
    asset_leverage: AssetLeverageConfig = Field(default_factory=AssetLeverageConfig)
    sigma_risk: SigmaRiskConfig = Field(default_factory=SigmaRiskConfig)
    strategies: StrategyConfig = Field(default_factory=StrategyConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)

    # ============================================
    # System Parameters
    # ============================================
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO", description="Logging level")
    snapshot_interval_seconds: int = Field(default=60, ge=10, le=3600, description="JSON snapshot frequency")
    report_interval_hours: int = Field(default=24, ge=1, le=168, description="Daily report frequency")
    control_mode: Literal[
        "SAFE", "NORMAL", "MODERATE", "AGGRESSIVE",
        "CRISIS_OPPORTUNISTIC", "CAPITAL_SECURE", "EMERGENCY_HALT"
    ] = Field(default="NORMAL", description="Operator control mode")

    # ============================================
    # Helper Methods
    # ============================================

    @field_validator("symbol_universe", mode="before")
    @classmethod
    def parse_symbol_universe(cls, v):
        """Parse symbol universe from string or list."""
        if isinstance(v, str):
            return json.loads(v)
        return v

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment."""
        overrides = {
            "shadow_read_only": _env_bool(
                os.environ.get("POVERTY_KILLER_SHADOW_READ_ONLY"),
                default=False,
            )
        }
        env_to_field = {
            "POVERTY_KILLER_RUNTIME_WATCHLIST": "runtime_watchlist",
            "POVERTY_KILLER_MARKET_DATA_PROVIDERS": "market_data_providers",
            "POVERTY_KILLER_CRYPTO_MARKET_DATA_PROVIDERS": "crypto_market_data_providers",
            "POVERTY_KILLER_EQUITY_MARKET_DATA_PROVIDERS": "equity_market_data_providers",
            "POVERTY_KILLER_OPTIONS_MARKET_DATA_PROVIDERS": "options_market_data_providers",
            "POVERTY_KILLER_EVENT_PROVIDERS": "event_providers",
            "POVERTY_KILLER_REFERENCE_DATA_PROVIDERS": "reference_data_providers",
        }
        for env_key, field_name in env_to_field.items():
            if env_key in os.environ:
                overrides[field_name] = _env_list(os.environ.get(env_key))
        return cls(**overrides)

    def get_class_limit(self, asset_class: str) -> float:
        """Get exposure limit for an asset class."""
        limits = {
            "CRYPTO": self.risk.max_crypto_exposure,
            "EQUITY": self.risk.max_equity_exposure,
            "ETF": self.risk.max_etf_exposure,
            "FUTURE": self.risk.max_future_exposure,
        }
        return limits.get(asset_class.upper(), 0.20)

    def get_asset_leverage(self, asset_class: str) -> float:
        """Get asset-class specific leverage."""
        return self.asset_leverage.get_leverage(asset_class)

    def get_available_capital(self) -> float:
        """Calculate deployable capital after cash reserve."""
        return self.initial_capital * (1 - self.risk.cash_reserve_percent)

    def is_strategy_enabled(self, strategy_name: str) -> bool:
        """Check if a specific strategy is enabled."""
        enabled_map = {
            "shadow_front": self.strategies.shadow_front_enabled,
            "flv": self.strategies.flv_enabled,
            "entropy_decoder": self.strategies.entropy_decoder_enabled,
            "physical_onchain": self.strategies.physical_onchain_enabled,
            "convexity_switch": self.strategies.convexity_switch_enabled,
            "hedging_flow": self.strategies.hedging_flow_enabled,
            "adaptive_dc": self.strategies.adaptive_dc_enabled,
            "gamma_front": self.strategies.gamma_front_enabled,
            "sector_rotation": self.strategies.sector_rotation_enabled,
        }
        return enabled_map.get(strategy_name, False)

    def get_sigma_multipliers(self, regime: str) -> Dict[str, float]:
        """Get regime-based sigma multipliers."""
        return self.sigma_risk.get_multipliers(regime)

    def validate_critical_values(self) -> List[str]:
        """
        Validate critical configuration values.
        Returns list of warnings or errors.
        """
        issues = []

        # Check class limits total equals 1.0
        if not self.risk.validate_class_limits_total():
            total = sum(self.risk.class_limits.values())
            issues.append(f"Warning: Class limits total {total:.0%} != 100%")

        # Check kill switch threshold
        if self.risk.kill_switch_enabled and self.risk.max_24h_drawdown > 0.10:
            issues.append(f"Warning: Kill switch threshold {self.risk.max_24h_drawdown:.0%} > 10%")

        # Check cash reserve
        if self.risk.cash_reserve_percent < 0.20:
            issues.append(f"Warning: Cash reserve {self.risk.cash_reserve_percent:.0%} < 20%")

        # Check initial capital
        if self.initial_capital < 1000:
            issues.append(f"Warning: Initial capital ${self.initial_capital:,.2f} is very low")

        # Check asset leverage
        if self.asset_leverage.future > 3.0:
            issues.append(f"Warning: Futures leverage {self.asset_leverage.future}x is high")

        return issues
