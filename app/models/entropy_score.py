"""
Entropy Score - Deterministic Market Entropy Contract
CITADEL GRADE — DETERMINISTIC · REPLAY-SAFE · NO FLOAT CONTAMINATION

ANALYTICAL/NON-MONETARY BOUNDARY:
This model represents analytical entropy scores derived from market microstructure.
All values are analytical estimates, not monetary truth.
"""

from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict, field_validator


class EntropyScore(BaseModel):
    """
    Deterministic entropy score from entropy_decoder engine.
    
    - entropy: Normalized entropy score in [0, 1]
    - predicted_magnitude: Predicted move magnitude in [0.5, 15.0] (percentage points)
    - confidence: Analytical confidence in [0, 1]
    - timestamp: Integer nanoseconds (replay-safe, no wall-clock)
    """
    
    symbol: str = Field(..., description="Trading symbol")
    timestamp: int = Field(..., description="Nanosecond timestamp (exchange or authoritative)")
    entropy: Decimal = Field(..., ge=0, le=1, description="Normalized entropy score (0-1)")
    is_collapsed: bool = Field(..., description="True if entropy has collapsed below threshold")
    predicted_magnitude: Decimal = Field(..., ge=Decimal('0.5'), le=Decimal('15.0'), description="Predicted move magnitude (0.5-15.0 percentage points)")
    confidence: Decimal = Field(..., ge=0, le=1, description="Confidence in entropy estimate (0-1)")
    samples_used: int = Field(..., ge=0, description="Number of samples used in calculation")
    
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )
    
    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        """Ensure symbol is non-empty."""
        if not v or not v.strip():
            raise ValueError("symbol must be non-empty")
        return v.strip()
    
    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: int) -> int:
        """Ensure timestamp is positive nanosecond integer."""
        if v <= 0:
            raise ValueError(f"timestamp must be positive integer nanoseconds, got {v}")
        return v
    
    @field_validator("samples_used")
    @classmethod
    def validate_samples_used(cls, v: int) -> int:
        """Ensure samples_used is non-negative."""
        if v < 0:
            raise ValueError(f"samples_used must be >= 0, got {v}")
        return v
    
    @field_validator("entropy", "confidence")
    @classmethod
    def validate_decimal_bounds(cls, v: Decimal) -> Decimal:
        """Ensure Decimal fields are within [0, 1]."""
        if v < 0 or v > 1:
            raise ValueError(f"Decimal value must be in [0,1], got {v}")
        return v
    
    @field_validator("predicted_magnitude")
    @classmethod
    def validate_predicted_magnitude(cls, v: Decimal) -> Decimal:
        """Ensure predicted_magnitude is within [0.5, 15.0] per decoder evidence."""
        if v < Decimal('0.5') or v > Decimal('15.0'):
            raise ValueError(f"predicted_magnitude must be in [0.5, 15.0], got {v}")
        return v