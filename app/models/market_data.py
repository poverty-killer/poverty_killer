"""
Market Data Models

Migrated from the unreachable app/models.py into the governed app/models/
package to resolve the Python package-shadowing issue.

Root cause: when app/models.py and app/models/ (package) coexist, CPython
always binds 'app.models' to the package directory. The following classes
were defined in app/models.py and were therefore inaccessible:
    Candle, OrderBookSnapshot, LiquidityMetrics,
    PhysicalVerification, WhaleFlowScore, EntropyScore

This file re-establishes those exports within the governed package.

Pydantic version: v2 native (BaseModel, ConfigDict, Field, field_validator).
Base class: BaseModel with ConfigDict(extra="forbid").
HardenedBaseModel is not used — its additions over plain BaseModel are
__slots__ = () (inert on pydantic v2 BaseModel subclasses) and
ConfigDict(extra="forbid", arbitrary_types_allowed=True). The
arbitrary_types_allowed flag is not required by any of these models as
all fields use standard Python/pydantic types only.

All definitions carried verbatim from app/models.py source.
No field semantics, validators, properties, or methods altered.

EPS is re-declared locally (used by OrderBookSnapshot.imbalance).
"""

from typing import List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, validator

# Machine epsilon — used by OrderBookSnapshot.imbalance
EPS = np.finfo(float).eps


class Candle(BaseModel):
    """
    OHLCV candle with nanosecond-precision timestamp.
    exchange_ts_ns is the source of truth - no local time.
    """

    model_config = ConfigDict(extra="forbid")

    symbol: str
    exchange_ts_ns: int = Field(description="Unix nanoseconds from exchange")
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str = "1m"
    exchange_latency_ns: Optional[int] = Field(default=None, description="NIC to processing latency")

    @property
    def exchange_ts_sec(self) -> float:
        """Convert nanoseconds to seconds for calculations."""
        return self.exchange_ts_ns / 1_000_000_000.0

    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3

    @property
    def range(self) -> float:
        return self.high - self.low

    @validator("open", "high", "low", "close")
    def validate_prices(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"Price must be positive: {v}")
        return v

    @validator("low")
    def validate_high_low(cls, v: float, values) -> float:
        high = values.get("high")
        if high is not None and high < v:
            raise ValueError(f"High ({high}) < Low ({v})")
        return v


class OrderBookSnapshot(BaseModel):
    """Order book depth snapshot with nanosecond-precision timestamp."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    exchange_ts_ns: int
    bids: List[Tuple[float, float]] = Field(description="[(price, size), ...]")
    asks: List[Tuple[float, float]] = Field(description="[(price, size), ...]")
    exchange_latency_ns: Optional[int] = None

    @property
    def exchange_ts_sec(self) -> float:
        return self.exchange_ts_ns / 1_000_000_000.0

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0][0] if self.asks else None

    @property
    def spread(self) -> float:
        if not self.asks or not self.bids:
            return float('inf')
        return self.asks[0][0] - self.bids[0][0]

    @property
    def spread_bps(self) -> float:
        mid = self.mid_price
        if mid <= 0:
            return float('inf')
        return (self.spread / mid) * 10000

    @property
    def mid_price(self) -> float:
        if not self.asks or not self.bids:
            return 0.0
        return (self.bids[0][0] + self.asks[0][0]) / 2

    def depth_at_levels(self, levels: int = 10) -> Tuple[float, float]:
        bid_depth = sum(size for _, size in self.bids[:levels])
        ask_depth = sum(size for _, size in self.asks[:levels])
        return bid_depth, ask_depth

    @property
    def imbalance(self) -> float:
        bid_depth, ask_depth = self.depth_at_levels(10)
        total = bid_depth + ask_depth
        if total < EPS:
            return 0.0
        return (bid_depth - ask_depth) / total


class LiquidityMetrics(BaseModel):
    """Derived liquidity metrics with nanosecond timestamp."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    exchange_ts_ns: int
    spread_bps: float = Field(ge=0)
    bid_depth: float = Field(ge=0)
    ask_depth: float = Field(ge=0)
    market_depth: float = Field(ge=0)
    imbalance: float = Field(ge=-1, le=1)
    is_liquid: bool
    depth_sufficient_for_size: float = Field(default=0.0, ge=0)
    refill_velocity: float = Field(default=0.0, ge=0)

    @property
    def exchange_ts_sec(self) -> float:
        return self.exchange_ts_ns / 1_000_000_000.0


class PhysicalVerification(BaseModel):
    """Physical infrastructure verification with nanosecond precision."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    exchange_ts_ns: int
    exchange: str
    exchange_latency_ns: int = Field(ge=0)
    network_rtt_ns: int = Field(ge=0)
    order_size_usd: float = Field(ge=0)
    price_impact_bps: float
    expected_impact_bps: float
    latency_impact_ratio: float
    is_toxic: bool = False
    mining_hashrate_th: Optional[float] = None
    datacenter_power_mw: Optional[float] = None
    undersea_cable_latency_ms: Optional[float] = None

    @property
    def exchange_ts_sec(self) -> float:
        return self.exchange_ts_ns / 1_000_000_000.0


class WhaleFlowScore(BaseModel):
    """Whale accumulation score with nanosecond timestamp."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    exchange_ts_ns: int
    score: float = Field(ge=0, le=1)
    z_score: float
    volume_anomaly: float
    is_accumulating: bool
    ttl_seconds: int = 60
    whale_zone_low: Optional[float] = None
    whale_zone_high: Optional[float] = None
    whale_zone_volume: float = 0.0
    whale_usd_value: float = 0.0

    @property
    def exchange_ts_sec(self) -> float:
        return self.exchange_ts_ns / 1_000_000_000.0

    def is_expired(self, current_ts_ns: int) -> bool:
        """Check if signal has expired based on TTL."""
        elapsed_ns = current_ts_ns - self.exchange_ts_ns
        elapsed_sec = elapsed_ns / 1_000_000_000.0
        return elapsed_sec > self.ttl_seconds


class EntropyScore(BaseModel):
    """Entropy score with nanosecond timestamp."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    exchange_ts_ns: int
    entropy: float = Field(ge=0, le=1)
    is_collapsed: bool
    predicted_magnitude: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    samples_used: int = Field(ge=0)

    @property
    def exchange_ts_sec(self) -> float:
        return self.exchange_ts_ns / 1_000_000_000.0


__all__ = [
    "Candle",
    "OrderBookSnapshot",
    "LiquidityMetrics",
    "PhysicalVerification",
    "WhaleFlowScore",
    "EntropyScore",
]
