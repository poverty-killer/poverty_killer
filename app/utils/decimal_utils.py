"""
Decimal Utilities for Sovereign Trading System

All monetary values, quantities, fees, and sizes must use Decimal with fixed precision.
No floats in accounting, execution, or persistence paths.

Precision Rules:
- Crypto quantities (BTC, ETH, etc.): 8 decimal places
- USD cash and PnL: 2 decimal places
- Prices: 8 decimal places
- Fees: 8 decimal places (converted to USD for accounting)
- Confidence scores: 4 decimal places (0-1 range)
- Percentages: 4 decimal places (e.g., 5.0000 for 5%)
- Basis points: 2 decimal places (e.g., 10.00 for 0.10%)
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Union, Optional
import warnings
import math


# ============================================
# PRECISION CONSTANTS (immutable)
# ============================================

CRYPTO_PRECISION = Decimal('0.00000001')      # 8 decimal places
USD_PRECISION = Decimal('0.01')               # 2 decimal places
PRICE_PRECISION = Decimal('0.00000001')       # 8 decimal places for prices
FEE_PRECISION = Decimal('0.00000001')         # 8 decimal places for fees
SCORE_PRECISION = Decimal('0.0001')           # 4 decimal places for confidence
PERCENT_PRECISION = Decimal('0.0001')         # 4 decimal places for percentages
BPS_PRECISION = Decimal('0.01')               # 2 decimal places for basis points


# ============================================
# STRICT PARSER (Approved Input Types Only)
# ============================================

def _to_decimal(value: Union[Decimal, int, str]) -> Decimal:
    """
    Convert approved input types to Decimal.
    
    APPROVED INPUT TYPES:
    - Decimal: passed through unchanged
    - int: converted to Decimal
    - str: parsed as Decimal
    
    FLOAT INPUTS ARE REJECTED. Use decimal_from_float() explicitly if needed.
    
    Args:
        value: Input value (Decimal, int, or str)
    
    Returns:
        Decimal value
    
    Raises:
        TypeError: If value is float or any other unsupported type
    """
    if isinstance(value, Decimal):
        return value
    elif isinstance(value, int):
        return Decimal(value)
    elif isinstance(value, str):
        return Decimal(value)
    else:
        raise TypeError(
            f"Unsupported type for decimal conversion: {type(value).__name__}. "
            f"Use Decimal, int, or str. For float, use decimal_from_float() explicitly."
        )


def decimal_from_float(value: float, context: str = "") -> Decimal:
    """
    Explicit conversion from float to Decimal with warning.
    
    FLOATS ARE NOT PERMITTED IN CORE ACCOUNTING PATHS.
    This function exists only for controlled conversion from external float sources
    (e.g., exchange APIs that return floats). Each use must be justified.
    
    Args:
        value: Float value to convert
        context: Optional context string for warning (e.g., "exchange_api")
    
    Returns:
        Decimal converted from float, preferring the string representation
        to avoid binary floating‑point artifacts.
    
    Raises:
        ValueError: If value is NaN, infinite, or otherwise non‑finite
        TypeError: If value is not float
    """
    if not isinstance(value, float):
        raise TypeError(f"decimal_from_float requires float, got {type(value).__name__}")
    
    # Reject NaN and infinity – they cannot appear in monetary values
    if math.isnan(value) or math.isinf(value):
        raise ValueError(
            f"Non‑finite float cannot be converted to Decimal: {value} "
            f"(context: {context or 'unknown'})"
        )
    
    warnings.warn(
        f"Float to Decimal conversion in {context or 'unknown context'}. "
        f"Value: {value}. Floats should not appear in core accounting paths.",
        UserWarning,
        stacklevel=2
    )
    
    # First try the string representation (most human‑readable).
    # If that fails (e.g., scientific notation like '1e-10'), fall back to
    # Decimal.from_float, which uses the exact binary representation.
    try:
        return Decimal(str(value))
    except InvalidOperation:
        # The float’s string representation is not directly parseable.
        # Use the exact binary conversion (still deterministic).
        warnings.warn(
            f"Float {value} could not be parsed as a decimal string; "
            f"using exact binary conversion (context: {context or 'unknown'}).",
            UserWarning,
            stacklevel=2
        )
        return Decimal.from_float(value)


# ============================================
# FACTORY FUNCTIONS (Accept Decimal, int, str only)
# ============================================

def crypto(amount: Union[Decimal, int, str]) -> Decimal:
    """
    Create a Decimal with crypto precision (8 decimal places).
    
    Args:
        amount: Value to convert (Decimal, int, or str)
    
    Returns:
        Decimal quantized to 8 decimal places (default rounding ROUND_HALF_EVEN)
    
    Raises:
        TypeError: If amount is float
    """
    return _to_decimal(amount).quantize(CRYPTO_PRECISION)


def usd(amount: Union[Decimal, int, str]) -> Decimal:
    """
    Create a Decimal with USD precision (2 decimal places).
    
    Args:
        amount: Value to convert (Decimal, int, or str)
    
    Returns:
        Decimal quantized to 2 decimal places (default rounding ROUND_HALF_EVEN)
    
    Raises:
        TypeError: If amount is float
    """
    return _to_decimal(amount).quantize(USD_PRECISION)


def price(amount: Union[Decimal, int, str]) -> Decimal:
    """
    Create a Decimal with price precision (8 decimal places).
    
    Args:
        amount: Value to convert (Decimal, int, or str)
    
    Returns:
        Decimal quantized to 8 decimal places (default rounding ROUND_HALF_EVEN)
    
    Raises:
        TypeError: If amount is float
    """
    return _to_decimal(amount).quantize(PRICE_PRECISION)


def fee(amount: Union[Decimal, int, str]) -> Decimal:
    """
    Create a Decimal with fee precision (8 decimal places).
    
    Args:
        amount: Value to convert (Decimal, int, or str)
    
    Returns:
        Decimal quantized to 8 decimal places (default rounding ROUND_HALF_EVEN)
    
    Raises:
        TypeError: If amount is float
    """
    return _to_decimal(amount).quantize(FEE_PRECISION)


def confidence(score: Union[Decimal, int, str]) -> Decimal:
    """
    Create a Decimal with confidence score precision (4 decimal places).
    Clamps to [0, 1] range.
    
    Args:
        score: Confidence value (0-1) as Decimal, int, or str
    
    Returns:
        Decimal quantized to 4 decimal places, clamped to [0, 1]
    
    Raises:
        TypeError: If score is float
    """
    d = _to_decimal(score)
    
    # Clamp to [0, 1] and warn if the input was out‑of‑bounds
    if d < 0:
        warnings.warn(f"Confidence score clamped from {d} to 0", UserWarning, stacklevel=2)
        d = Decimal('0')
    elif d > 1:
        warnings.warn(f"Confidence score clamped from {d} to 1", UserWarning, stacklevel=2)
        d = Decimal('1')
    
    return d.quantize(SCORE_PRECISION)


def percent(pct: Union[Decimal, int, str]) -> Decimal:
    """
    Create a Decimal with percentage precision (4 decimal places).
    
    PERCENTAGE CONVENTION: 5.0000 = 5% (five percent)
    
    Args:
        pct: Percentage value (e.g., 5 for 5%) as Decimal, int, or str
    
    Returns:
        Decimal quantized to 4 decimal places (default rounding ROUND_HALF_EVEN)
    
    Raises:
        TypeError: If pct is float
    """
    return _to_decimal(pct).quantize(PERCENT_PRECISION)


def bps(basis_points: Union[Decimal, int, str]) -> Decimal:
    """
    Create a Decimal with basis point precision (2 decimal places).
    
    BASIS POINT CONVENTION: 10.00 = 10 basis points = 0.10%
    
    Args:
        basis_points: Basis point value (e.g., 10 for 0.10%) as Decimal, int, or str
    
    Returns:
        Decimal quantized to 2 decimal places (default rounding ROUND_HALF_EVEN)
    
    Raises:
        TypeError: If basis_points is float
    """
    return _to_decimal(basis_points).quantize(BPS_PRECISION)


# ============================================
# CONVERSION FUNCTIONS
# ============================================

def bps_to_percent(basis_points: Union[Decimal, int, str]) -> Decimal:
    """
    Convert basis points to percentage.
    
    CONVERSION: 10.00 bps = 0.1000% (10 basis points equals 0.10 percent)
    
    Args:
        basis_points: Basis points (e.g., 10 = 0.10%)
    
    Returns:
        Percentage value (e.g., Decimal('0.1000'))
    
    Raises:
        TypeError: If basis_points is float
    """
    bp = _to_decimal(basis_points)
    return (bp / Decimal('100')).quantize(PERCENT_PRECISION)


def percent_to_bps(percentage: Union[Decimal, int, str]) -> Decimal:
    """
    Convert percentage to basis points.
    
    CONVERSION: 0.1000% = 10.00 bps
    
    Args:
        percentage: Percentage (e.g., 0.1 for 0.1%)
    
    Returns:
        Basis points (e.g., 10.00)
    
    Raises:
        TypeError: If percentage is float
    """
    pct = _to_decimal(percentage)
    return (pct * Decimal('100')).quantize(BPS_PRECISION)


# ============================================
# ARITHMETIC HELPERS (Accept Decimal, int, str only)
# ============================================

def safe_add(
    a: Union[Decimal, int, str],
    b: Union[Decimal, int, str],
    precision: Decimal
) -> Decimal:
    """
    Safe addition with precision quantization.
    
    Args:
        a: First operand (Decimal, int, or str)
        b: Second operand (Decimal, int, or str)
        precision: Precision to quantize result (default rounding ROUND_HALF_EVEN)
    
    Returns:
        Quantized sum
    
    Raises:
        TypeError: If a or b is float
    """
    da = _to_decimal(a)
    db = _to_decimal(b)
    return (da + db).quantize(precision)


def safe_subtract(
    a: Union[Decimal, int, str],
    b: Union[Decimal, int, str],
    precision: Decimal
) -> Decimal:
    """
    Safe subtraction with precision quantization.
    
    Args:
        a: First operand (Decimal, int, or str)
        b: Second operand (Decimal, int, or str)
        precision: Precision to quantize result (default rounding ROUND_HALF_EVEN)
    
    Returns:
        Quantized difference
    
    Raises:
        TypeError: If a or b is float
    """
    da = _to_decimal(a)
    db = _to_decimal(b)
    return (da - db).quantize(precision)


def safe_multiply(
    a: Union[Decimal, int, str],
    b: Union[Decimal, int, str],
    precision: Decimal
) -> Decimal:
    """
    Safe multiplication with precision quantization.
    
    Args:
        a: First operand (Decimal, int, or str)
        b: Second operand (Decimal, int, or str)
        precision: Precision to quantize result (default rounding ROUND_HALF_EVEN)
    
    Returns:
        Quantized product
    
    Raises:
        TypeError: If a or b is float
    """
    da = _to_decimal(a)
    db = _to_decimal(b)
    return (da * db).quantize(precision)


def safe_divide(
    a: Union[Decimal, int, str],
    b: Union[Decimal, int, str],
    precision: Decimal
) -> Decimal:
    """
    Safe division with precision quantization.
    
    Args:
        a: Numerator (Decimal, int, or str)
        b: Denominator (Decimal, int, or str)
        precision: Precision to quantize result (default rounding ROUND_HALF_EVEN)
    
    Returns:
        Quantized quotient
    
    Raises:
        ZeroDivisionError: If denominator is zero
        TypeError: If a or b is float
    """
    da = _to_decimal(a)
    db = _to_decimal(b)
    
    if db == 0:
        raise ZeroDivisionError("safe_divide: denominator cannot be zero")
    
    return (da / db).quantize(precision)


def zero(precision: Decimal) -> Decimal:
    """
    Return zero quantized to the specified precision.
    
    Args:
        precision: Precision to quantize
    
    Returns:
        Decimal('0') quantized to precision
    """
    return Decimal('0').quantize(precision)


def is_zero(
    value: Union[Decimal, int, str],
    precision: Decimal
) -> bool:
    """
    Check if value is zero after quantization.
    
    Quantization comparison, not tolerance-based. A value is zero if
    value.quantize(precision) == Decimal('0').quantize(precision).
    
    Args:
        value: Value to check (Decimal, int, or str)
        precision: Precision for quantization comparison
    
    Returns:
        True if value quantizes to zero
    
    Raises:
        TypeError: If value is float
    """
    d = _to_decimal(value)
    return d.quantize(precision) == zero(precision)


# ============================================
# SERIALIZATION
# ============================================

def to_canonical_string(value: Decimal, precision: Decimal) -> str:
    """
    Convert Decimal to canonical fixed-precision string for persistence/replay.
    
    This is the ONLY serialization function permitted for persistence and replay.
    Output is deterministic and preserves exactly the decimal places implied by
    the provided precision. Trailing zeros are preserved.
    
    Example:
        to_canonical_string(Decimal('123.4567'), USD_PRECISION) -> "123.46"
        to_canonical_string(Decimal('123'), CRYPTO_PRECISION) -> "123.00000000"
    
    Args:
        value: Decimal value
        precision: Precision to quantize to before serialization (default rounding ROUND_HALF_EVEN)
    
    Returns:
        Fixed-point string with exactly the decimal places implied by precision
    """
    # Quantize to the required precision (default rounding ROUND_HALF_EVEN)
    quantized = value.quantize(precision)
    # Convert to string with fixed-point format
    # This preserves trailing zeros because quantize guarantees the decimal places
    return format(quantized, 'f')


def to_display_string(value: Decimal, precision: Optional[Decimal] = None) -> str:
    """
    Convert Decimal to human-readable display string.
    
    This function is for logging and UI display only.
    Use to_canonical_string() for persistence and replay.
    
    Args:
        value: Decimal value
        precision: Optional precision override (defaults to value's natural precision)
    
    Returns:
        Human-readable string with trailing zeros stripped after the decimal point
    """
    if precision is not None:
        quantized = value.quantize(precision)
    else:
        quantized = value
    
    normalized = quantized.normalize()
    
    # For display, we can strip trailing zeros after the decimal point
    s = format(normalized, 'f')
    if '.' in s:
        s = s.rstrip('0').rstrip('.') if '.' in s else s
    
    return s


# ============================================
# EXPORTS
# ============================================

__all__ = [
    # Precision constants
    'CRYPTO_PRECISION',
    'USD_PRECISION',
    'PRICE_PRECISION',
    'FEE_PRECISION',
    'SCORE_PRECISION',
    'PERCENT_PRECISION',
    'BPS_PRECISION',
    # Strict conversion
    'decimal_from_float',
    # Factory functions
    'crypto',
    'usd',
    'price',
    'fee',
    'confidence',
    'percent',
    'bps',
    # Conversions
    'bps_to_percent',
    'percent_to_bps',
    # Arithmetic helpers
    'safe_add',
    'safe_subtract',
    'safe_multiply',
    'safe_divide',
    'zero',
    'is_zero',
    # Serialization
    'to_canonical_string',
    'to_display_string',
]
