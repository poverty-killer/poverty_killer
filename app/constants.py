"""
System Constants
All enum-like constants and static values for the Poverty Killer engine.
This file defines the core vocabulary of the system.
HARDENED: MAX_LEVERAGE=2.0, STALE_DATA=10s, Balanced CLASS_LIMITS

ENUM AUTHORITY: All enum class definitions have been migrated to app.models.enums.
This file re-exports them for backward compatibility.
Non-enum content (numeric constants, SigmaRiskConfig, helper dicts) is authoritative here.
"""

from typing import Dict

# ============================================================================
# ALL ENUM RE-EXPORTS (authority: app.models.enums)
# ============================================================================

from app.models.enums import (  # noqa: F401
    RegimeType,
    SleeveType,
    RiskProfile,
    ControlMode,
    OrderStatus,
    PositionStatus,
    EventType,
    ShadowFrontState,
    LiquidityVoidState,
    LiquidityVoidStatus,
    AssetClass,
    MarketSession,
    ExchangeType,
)


# ============================================
# HARD-CODED CONSTANTS (HARDENED)
# ============================================

# ===== Risk =====
KILL_SWITCH_THRESHOLD: float = 0.08
MAX_CASH_RESERVE: float = 0.30
MAX_POSITIONS_DEFAULT: int = 5
MAX_LEVERAGE_DEFAULT: float = 2.0

# ===== Drawdown Levels =====
DRAWDOWN_WARNING: float = 0.03
DRAWDOWN_CRITICAL: float = 0.05
DRAWDOWN_KILL: float = 0.08

# ===== Data =====
MAX_CANDLES_PER_SYMBOL: int = 1000
STALE_DATA_THRESHOLD_SECONDS: int = 10
DEFAULT_TIMEFRAME: str = "1m"
WEBSOCKET_MAX_QUEUE_SIZE: int = 10000

# ===== Execution =====
MAX_ORDER_RETRIES: int = 3
DEFAULT_SNAPSHOT_INTERVAL: int = 60
DEFAULT_LATENCY_MS: int = 50
LATENCY_JITTER_MS: int = 25

# ===== Strategy =====
FLV_KELLY_MULTIPLIER: float = 0.5
MIN_CONFIDENCE_THRESHOLD: float = 0.6
WHALE_TTL_SECONDS: int = 60
SENTIMENT_TTL_SECONDS: int = 30

# ===== Position Sizing =====
MAX_RISK_PER_TRADE: float = 0.02
KELLY_FRACTION_MAX: float = 0.25
STOP_LOSS_ATR_MULTIPLIER: float = 1.5

# ===== Class Limits (as % of total capital) - BALANCED TOTAL = 1.0 =====
CLASS_LIMITS: Dict[str, float] = {
    AssetClass.CRYPTO: 0.15,
    AssetClass.EQUITY: 0.35,
    AssetClass.ETF: 0.30,
    AssetClass.FUTURE: 0.20,
}

# ===== Asset-Class Specific Leverage =====
ASSET_CLASS_LEVERAGE: Dict[str, float] = {
    AssetClass.CRYPTO: 1.0,
    AssetClass.EQUITY: 1.0,
    AssetClass.ETF: 1.0,
    AssetClass.FUTURE: 2.0,
}

# ===== Session Hours (EST) =====
EQUITY_OPEN_HOUR: int = 9
EQUITY_OPEN_MINUTE: int = 30
EQUITY_CLOSE_HOUR: int = 16
EQUITY_CLOSE_MINUTE: int = 0

FUTURES_OPEN_SUNDAY_HOUR: int = 18
FUTURES_CLOSE_FRIDAY_HOUR: int = 17

# ===== Performance Metrics =====
SHARPE_ANNUALIZATION_FACTOR: int = 252
MIN_SHARPE_SAMPLES: int = 20
MIN_WIN_RATE_SAMPLES: int = 20

# ===== Logging =====
LOG_ROTATION_SIZE_MB: int = 10
LOG_RETENTION_DAYS: int = 30
HEARTBEAT_INTERVAL_SECONDS: int = 60

# ===== Database =====
DB_WAL_AUTOCHECKPOINT: int = 1000
DB_TIMEOUT_SECONDS: int = 30
DB_JOURNAL_MODE: str = "WAL"
DB_SYNC_MODE: str = "NORMAL"

# ===== Whale Detection (USD) =====
WHALE_THRESHOLD_USD: float = 500000.0

# ===== Shan's Curve =====
SHANS_CURVE_SENSITIVITY: float = 2.5
SHANS_CURVE_MIN_CONFIDENCE: float = 0.4
SHANS_CURVE_FIT_DEGREE: int = 2
SHANS_CURVE_SMOOTHING_WINDOW: int = 5
SHANS_CURVE_GHOST_TTL_SECONDS: float = 5.0
SHANS_CURVE_MIN_LIQUIDITY_USD: float = 10000.0

# ===== Macro-Overlay & Insider Detection =====
MACRO_VELOCITY_THRESHOLD: float = 2.5
MACRO_KILL_THRESHOLD: float = 3.0
MACRO_PAUSE_BOOST: float = 0.15
MACRO_KILL_SECONDS: int = 30
DIVERGENCE_THRESHOLD: float = 0.7
MACRO_WINDOW_SECONDS: int = 300
MACRO_TTL_SECONDS: float = 60.0

# ===== Insider Detection =====
ABNORMAL_RETURN_THRESHOLD: float = 0.025
STRATEGIC_SPLIT_WINDOW_SECONDS: int = 60
OPTIONS_FLOW_THRESHOLD: float = 2.0
INSIDER_WINDOW_DAYS: int = 3
INSIDER_MIN_CONFIDENCE: float = 0.6

# ===== Liquidity Absorption Rate (LAR) =====
LAR_WINDOW_SIZE: int = 10
LAR_THRESHOLD: float = 0.5
LAR_DEPTH_LEVELS: int = 15
LAR_MIN_LIQUIDITY_USD: float = 10000.0
LAR_TTL_SECONDS: float = 5.0

# ===== Dark Pool Sync =====
DARK_POOL_TTL_SECONDS: float = 60.0
DARK_POOL_TIME_WINDOW_MS: int = 500

# ===== Market Memory Decay =====
MARKET_MEMORY_BASE_DECAY: float = 0.1
MARKET_MEMORY_TTL_SECONDS: float = 60.0

# ===== Topological Persistence Engine =====
TPE_WINDOW_SIZE: int = 50
TPE_EPSILON_MIN: float = 0.02
TPE_EPSILON_MAX: float = 0.20
TPE_EPSILON_STEPS: int = 10
TPE_TIME_WEIGHT: float = 0.5
TPE_TEMPORAL_WINDOW_MS: int = 1000
TPE_MIN_LIQUIDITY_USD: float = 10000.0


# ============================================
# SIGMA RISK CONFIGURATION (Regime-Based Scaling)
# ============================================

class SigmaRiskConfig:
    """
    Dynamic threshold scaling based on market regime.
    Used by signal_fusion.py to adjust strategy sensitivity.
    """

    TRENDING_MULTIPLIERS = {
        "whale_threshold": 0.8,
        "sentiment_threshold": 0.7,
        "confidence_multiplier": 1.2,
    }

    RANGING_MULTIPLIERS = {
        "whale_threshold": 1.2,
        "sentiment_threshold": 1.3,
        "confidence_multiplier": 0.8,
    }

    CRISIS_MULTIPLIERS = {
        "whale_threshold": 1.5,
        "sentiment_threshold": 1.5,
        "confidence_multiplier": 0.5,
    }

    @classmethod
    def get_multipliers(cls, regime: RegimeType) -> Dict[str, float]:
        """Get multipliers for a given regime."""
        if regime == RegimeType.TRENDING:
            return cls.TRENDING_MULTIPLIERS
        elif regime == RegimeType.RANGING:
            return cls.RANGING_MULTIPLIERS
        elif regime == RegimeType.CRISIS:
            return cls.CRISIS_MULTIPLIERS
        else:
            return {"whale_threshold": 1.0, "sentiment_threshold": 1.0, "confidence_multiplier": 1.0}


# ============================================
# HELPER DICTIONARIES
# ============================================

CONTROL_MODE_EXPOSURE: Dict[ControlMode, float] = {
    ControlMode.SAFE: 0.20,
    ControlMode.NORMAL: 0.40,
    ControlMode.MODERATE: 0.60,
    ControlMode.AGGRESSIVE: 0.70,
    ControlMode.CRISIS_OPPORTUNISTIC: 0.50,
    ControlMode.CAPITAL_SECURE: 0.10,
    ControlMode.EMERGENCY_HALT: 0.00,
}

RISK_PROFILE_SCALING: Dict[RiskProfile, float] = {
    RiskProfile.SAFE: 0.10,
    RiskProfile.NORMAL: 0.50,
    RiskProfile.MODERATE: 0.75,
    RiskProfile.AGGRESSIVE: 1.00,
    RiskProfile.CRISIS_OPPORTUNISTIC: 1.50,
}

ASSET_SESSION_MAP: Dict[AssetClass, MarketSession] = {
    AssetClass.CRYPTO: MarketSession.CRYPTO_24_7,
    AssetClass.EQUITY: MarketSession.EQUITY,
    AssetClass.ETF: MarketSession.EQUITY,
    AssetClass.FUTURE: MarketSession.FUTURES,
}

ASSET_EXCHANGE_MAP: Dict[AssetClass, ExchangeType] = {
    AssetClass.CRYPTO: ExchangeType.KRAKEN,
    AssetClass.EQUITY: ExchangeType.ALPACA,
    AssetClass.ETF: ExchangeType.ALPACA,
    AssetClass.FUTURE: ExchangeType.IBKR,
}

STRATEGY_ENABLED_DEFAULTS: Dict[str, bool] = {
    "shadow_front": True,
    "flv": True,
    "entropy_decoder": True,
    "physical_onchain": True,
    "convexity_switch": True,
    "hedging_flow": True,
    "adaptive_dc": True,
    "gamma_front": True,
    "sector_rotation": True,
}
