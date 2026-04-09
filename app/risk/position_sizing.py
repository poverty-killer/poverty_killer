"""
Position Sizing Engine - Deterministic Capital Allocation (Citadel Grade)

This is a CRITICAL CAPITAL-ALLOCATION function.
All calculations are deterministic, replay-safe, and use Decimal for monetary values.
No wall-clock dependence. No randomness.

Primary path: stop-loss-based risk sizing (true risk management)
Fallback path: notional-based sizing when stop distance unavailable

Formula (risk-based):
    risk_capital = capital * risk_per_trade_pct * kelly_multiplier
    stop_distance_fraction = stop_loss_pct OR (atr * multiplier) / price
    quantity = risk_capital / (price * stop_distance_fraction)
    notional = quantity * price

Caps (applied after sizing, in order):
    1. Strategy cap (per-strategy % of capital)
    2. Hard global cap (25% of capital per single position)
"""

import logging
from decimal import Decimal
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass

from app.constants import (
    SleeveType,
    RegimeType,
    MAX_RISK_PER_TRADE,
    KELLY_FRACTION_MAX,
    STOP_LOSS_ATR_MULTIPLIER,
)
from app.utils.decimal_utils import (
    usd,
    crypto,
    confidence as decimal_confidence,
    safe_multiply,
    safe_divide,
    zero,
    USD_PRECISION,
    CRYPTO_PRECISION,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PositionSizeResult:
    """
    Deterministic position sizing result.

    All fields are immutable after creation.
    quantity is in base units (crypto: BTC/ETH, equity: shares, futures: contracts).
    notional_usd is the USD value of the position.
    risk_percent is the percentage of capital ACTUALLY risked (post-cap, stop-based).
    position_pct is the percentage of capital allocated (notional).
    """
    quantity: Decimal
    notional_usd: Decimal
    risk_percent: Decimal          # Stop-based risk (% of capital), 0 if not applicable
    position_pct: Decimal          # Notional allocation (% of capital)
    sizing_method: str             # "risk_based" or "notional_based"
    confidence_adjusted: bool
    regime_adjusted: bool
    volatility_adjusted: bool
    kelly_adjusted: bool
    capped_by_strategy: bool
    capped_by_global: bool
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "quantity": str(self.quantity),
            "notional_usd": str(self.notional_usd),
            "risk_percent": str(self.risk_percent),
            "position_pct": str(self.position_pct),
            "sizing_method": self.sizing_method,
            "confidence_adjusted": self.confidence_adjusted,
            "regime_adjusted": self.regime_adjusted,
            "volatility_adjusted": self.volatility_adjusted,
            "kelly_adjusted": self.kelly_adjusted,
            "capped_by_strategy": self.capped_by_strategy,
            "capped_by_global": self.capped_by_global,
            "reason": self.reason,
        }


class PositionSizingError(Exception):
    """Base exception for position sizing errors."""
    pass


class PositionSizingEngine:
    """
    Deterministic position sizing engine (Citadel Grade).

    PRIMARY PATH: Stop-loss-based risk sizing
        - Uses risk_per_trade_pct from config (default 2%)
        - Uses stop_loss_pct (fractional) or ATR-based stop distance
        - ATR is assumed to be a raw dollar distance (e.g., in USD)
        - Stop distance is converted to FRACTIONAL form before denominator use
        - Quantity = (capital * risk_pct * kelly) / (price * stop_distance_fraction)

    FALLBACK PATH: Notional-based sizing
        - Used when stop_loss_pct and atr are both None
        - Quantity = (capital * confidence * kelly) / price

    All caps are applied as notional limits after base sizing:
        - Strategy cap (per-strategy % of capital)
        - Hard global cap (25% of capital per single position)

    STOP DISTANCE SEMANTICS (CRITICAL):
        - stop_loss_pct branch: already a fractional stop distance (e.g., 0.015 = 1.5%)
        - atr branch: atr is assumed to be raw dollar distance (e.g., atr = 1500 for BTC)
          Converted to fractional: stop_distance_fraction = (atr * multiplier) / price
        - Both branches produce a DIMENSIONLESS FRACTIONAL stop distance
        - Denominator = price * stop_distance_fraction = price * (stop_distance_fraction)
        - This yields quantity = risk_capital / (price * fraction) = risk_capital / stop_dollar
        - Where stop_dollar = price * stop_distance_fraction = dollar distance to stop

    Features:
        - Kelly fraction from Commander (0.4 SAFE, 0.85 ATTACK), upper-clamped to 0.25
        - No lower clamp on Kelly (preserves zero and small values as passed)
        - Regime-based scaling (trending=1.0, ranging=0.5, crisis=0.1)
        - Volatility adjustment (inverse: higher vol = smaller size)
        - Decimal-only for monetary precision
        - No wall-clock, no randomness, replay-safe
    """

    def __init__(self, config: Any):
        """
        Initialize position sizing engine.

        Args:
            config: Configuration object with risk and strategy parameters
        """
        self.config = config

        # Risk parameters (from config with constants fallback)
        self.risk_per_trade_pct = Decimal(str(getattr(config.risk, 'max_risk_per_trade', MAX_RISK_PER_TRADE)))
        self.stop_loss_atr_multiplier = Decimal(str(STOP_LOSS_ATR_MULTIPLIER))

        # Kelly upper bound only (no lower clamp)
        self.kelly_fraction_max = Decimal(str(KELLY_FRACTION_MAX))

        # Strategy-specific caps as percentage of total capital
        # These are MAXIMUM POSITION SIZE limits, not risk limits
        self.strategy_caps = {
            SleeveType.SHADOW_FRONT: Decimal('0.40'),      # 40% of capital max
            SleeveType.FLV: Decimal('0.30'),               # 30% of capital max
            SleeveType.ENTROPY_DECODER: Decimal('0.25'),   # 25% of capital max
            SleeveType.GAMMA_FRONT: Decimal('0.20'),       # 20% of capital max
            SleeveType.SECTOR_ROTATION: Decimal('0.25'),   # 25% of capital max
        }

        # Hard global cap: maximum 25% of capital in any single position
        # This is a final safety ceiling applied after strategy caps
        self.hard_cap_pct = Decimal('0.25')

        # Volatility scaling parameters
        self.volatility_target = Decimal('0.20')   # 20% annualized target vol
        self.volatility_min_multiplier = Decimal('0.25')
        self.volatility_max_multiplier = Decimal('2.0')

        logger.info(
            "PositionSizingEngine initialized: risk_per_trade=%.2f%%, kelly_max=%.2f, hard_cap=%.0f%%",
            float(self.risk_per_trade_pct * 100), float(self.kelly_fraction_max), float(self.hard_cap_pct * 100)
        )

    def _get_regime_multiplier(self, regime: RegimeType) -> Decimal:
        """
        Get regime-based sizing multiplier.

        Args:
            regime: Current market regime

        Returns:
            Multiplier (1.0 = full size, 0.1 = 10% size)
        """
        if regime == RegimeType.TRENDING_BULL or regime == RegimeType.TRENDING_BEAR:
            return Decimal('1.0')
        elif regime == RegimeType.RANGING:
            return Decimal('0.5')
        elif regime == RegimeType.CRISIS:
            return Decimal('0.1')
        else:
            return Decimal('0.5')  # UNKNOWN

    def _get_volatility_multiplier(self, volatility: Decimal) -> Decimal:
        """
        Get volatility-based sizing multiplier.

        Inverse relationship: higher volatility = smaller position size.
        Uses target volatility normalization.

        Args:
            volatility: Current volatility (annualized, as decimal, e.g., 0.25 = 25%)

        Returns:
            Multiplier clamped to [volatility_min_multiplier, volatility_max_multiplier]
        """
        if volatility <= Decimal('0'):
            return Decimal('1.0')

        # Inverse scaling: multiplier = target_vol / max(volatility, min_vol)
        min_vol = Decimal('0.05')
        vol_clamped = max(min_vol, volatility)
        multiplier = self.volatility_target / vol_clamped

        # Clamp to configured bounds
        return max(self.volatility_min_multiplier, min(self.volatility_max_multiplier, multiplier))

    def _get_strategy_cap_pct(self, strategy: Union[SleeveType, str]) -> Decimal:
        """
        Get strategy-specific capital cap as percentage of total capital.

        Args:
            strategy: Strategy identifier

        Returns:
            Cap percentage (e.g., 0.40 = 40% of capital)
        """
        if isinstance(strategy, str):
            try:
                strategy = SleeveType(strategy)
            except ValueError:
                return Decimal('0.25')  # Default fallback

        return self.strategy_caps.get(strategy, Decimal('0.25'))

    def _compute_fractional_stop_distance(
        self,
        price: Decimal,
        stop_loss_pct: Optional[Decimal],
        atr: Optional[Decimal],
    ) -> tuple[Optional[Decimal], str]:
        """
        Compute fractional stop distance from either stop_loss_pct or ATR.

        DIMENSIONAL SEMANTICS (CRITICAL):
            - stop_loss_pct branch: already fractional (e.g., 0.015 = 1.5%)
            - atr branch: atr is assumed to be raw dollar distance
              Converted: fractional = (atr * multiplier) / price

        Args:
            price: Current asset price in USD
            stop_loss_pct: Optional fractional stop distance (e.g., 0.015)
            atr: Optional raw dollar ATR distance (e.g., 1500 for BTC)

        Returns:
            Tuple of (fractional_stop_distance, source_description)
            Returns (None, reason) if no valid stop distance available
        """
        if stop_loss_pct is not None and stop_loss_pct > Decimal('0'):
            return stop_loss_pct, "stop_loss_pct"

        if atr is not None and atr > Decimal('0') and price > Decimal('0'):
            # ATR is raw dollar distance. Convert to fractional stop distance.
            raw_stop_dollar = atr * self.stop_loss_atr_multiplier
            fractional_stop = raw_stop_dollar / price
            return fractional_stop, f"atr (raw={atr}, multiplier={self.stop_loss_atr_multiplier})"

        return None, "no_stop_distance"

    def _apply_caps(
        self,
        notional_usd: Decimal,
        capital_usd: Decimal,
        strategy: Union[SleeveType, str],
    ) -> tuple[Decimal, bool, bool]:
        """
        Apply strategy and global caps to notional value.

        Args:
            notional_usd: Proposed notional value
            capital_usd: Total capital
            strategy: Strategy identifier

        Returns:
            Tuple of (capped_notional, capped_by_strategy, capped_by_global)
        """
        capped_by_strategy = False
        capped_by_global = False

        # Strategy cap
        strategy_cap_pct = self._get_strategy_cap_pct(strategy)
        strategy_max_usd = capital_usd * strategy_cap_pct
        if notional_usd > strategy_max_usd:
            notional_usd = strategy_max_usd
            capped_by_strategy = True

        # Hard global cap
        hard_max_usd = capital_usd * self.hard_cap_pct
        if notional_usd > hard_max_usd:
            notional_usd = hard_max_usd
            capped_by_global = True

        return notional_usd, capped_by_strategy, capped_by_global

    def calculate_risk_based_size(
        self,
        capital_usd: Decimal,
        confidence: Decimal,
        volatility: Decimal,
        regime: RegimeType,
        strategy: Union[SleeveType, str],
        price: Decimal,
        kelly_multiplier: Decimal,
        stop_loss_pct: Optional[Decimal] = None,
        atr: Optional[Decimal] = None,
    ) -> PositionSizeResult:
        """
        Calculate position size using stop-loss-based risk sizing (PRIMARY PATH).

        Formula:
            risk_capital = capital * risk_per_trade_pct * kelly * regime * vol
            stop_distance_fraction = fractional stop distance from stop_loss_pct or ATR
            quantity = risk_capital / (price * stop_distance_fraction)
            notional = quantity * price

        After caps, risk_percent is recomputed from FINAL realized quantity.

        Args:
            capital_usd: Total capital in USD (must be > 0)
            confidence: Signal confidence (0-1) - applied to risk capital
            volatility: Current volatility (annualized, as decimal)
            regime: Current market regime
            strategy: Strategy requesting position
            price: Current asset price in USD
            kelly_multiplier: Kelly fraction from Commander (0.4 SAFE, 0.85 ATTACK)
            stop_loss_pct: Stop loss as fractional distance (e.g., 0.015 = 1.5%)
            atr: Average True Range in RAW DOLLARS (e.g., 1500 for BTC)

        Returns:
            PositionSizeResult with quantity and metadata

        Raises:
            PositionSizingError: If capital_usd <= 0, confidence out of range,
                                 or no valid stop distance provided
        """
        # Validate inputs
        if capital_usd <= Decimal('0'):
            raise PositionSizingError(f"capital_usd must be > 0, got {capital_usd}")
        if confidence < Decimal('0') or confidence > Decimal('1'):
            raise PositionSizingError(f"confidence must be in [0,1], got {confidence}")
        if price <= Decimal('0'):
            raise PositionSizingError(f"price must be > 0, got {price}")

        # Compute fractional stop distance
        stop_distance_fraction, stop_source = self._compute_fractional_stop_distance(
            price, stop_loss_pct, atr
        )
        if stop_distance_fraction is None or stop_distance_fraction <= Decimal('0'):
            raise PositionSizingError(
                f"Risk-based sizing requires stop_loss_pct or atr > 0"
            )

        # Convert confidence to Decimal with proper precision
        confidence_dec = decimal_confidence(confidence)

        # Kelly: upper clamp only (preserve zero and small positive values)
        clamped_kelly = kelly_multiplier
        kelly_adjusted = False
        if clamped_kelly > self.kelly_fraction_max:
            clamped_kelly = self.kelly_fraction_max
            kelly_adjusted = True
        # Ensure non-negative (defensive)
        if clamped_kelly < Decimal('0'):
            clamped_kelly = Decimal('0')
            kelly_adjusted = True

        # Regime adjustment
        regime_mult = self._get_regime_multiplier(regime)
        regime_adjusted = regime_mult < Decimal('1.0')

        # Volatility adjustment
        vol_mult = self._get_volatility_multiplier(volatility)
        volatility_adjusted = vol_mult < Decimal('1.0')

        # Risk capital calculation (pre-cap theoretical budget)
        risk_capital = capital_usd
        risk_capital = risk_capital * self.risk_per_trade_pct
        risk_capital = risk_capital * confidence_dec
        risk_capital = risk_capital * clamped_kelly
        risk_capital = risk_capital * regime_mult
        risk_capital = risk_capital * vol_mult

        # Denominator: price * stop_distance_fraction
        # This yields dollar distance to stop: price * fraction = dollar amount
        denominator = price * stop_distance_fraction
        if denominator <= Decimal('0'):
            raise PositionSizingError(f"Invalid denominator: price={price}, stop_distance_fraction={stop_distance_fraction}")

        # Quantity from risk capital and stop distance
        quantity = risk_capital / denominator
        quantity = quantity.quantize(CRYPTO_PRECISION)

        notional_usd = quantity * price
        notional_usd = notional_usd.quantize(USD_PRECISION)

        # Apply caps
        capped_notional, capped_by_strategy, capped_by_global = self._apply_caps(
            notional_usd, capital_usd, strategy
        )

        # If caps reduced notional, recalculate quantity and realized risk
        if capped_notional < notional_usd:
            notional_usd = capped_notional
            quantity = (capped_notional / price).quantize(CRYPTO_PRECISION)

        # Compute REALIZED risk percent from FINAL position (post-cap)
        # Realized risk = final notional * stop_distance_fraction / capital
        realized_risk_usd = notional_usd * stop_distance_fraction
        realized_risk_percent = safe_divide(realized_risk_usd, capital_usd, USD_PRECISION)

        position_pct = safe_divide(notional_usd, capital_usd, USD_PRECISION)

        # Build reason string
        reason_parts = [f"stop={stop_source}"]
        if confidence_dec < Decimal('1.0'):
            reason_parts.append(f"conf={confidence_dec:.3f}")
        if kelly_adjusted:
            reason_parts.append(f"kelly_upper_clamped={clamped_kelly:.3f}")
        if regime_adjusted:
            reason_parts.append(f"regime={regime.value}")
        if volatility_adjusted:
            reason_parts.append(f"vol={volatility:.3f}")
        if capped_by_strategy:
            cap_pct = self._get_strategy_cap_pct(strategy)
            reason_parts.append(f"strategy_capped={cap_pct:.0%}")
        if capped_by_global:
            reason_parts.append(f"global_capped={self.hard_cap_pct:.0%}")

        reason = "; ".join(reason_parts)

        return PositionSizeResult(
            quantity=quantity,
            notional_usd=notional_usd,
            risk_percent=realized_risk_percent,
            position_pct=position_pct,
            sizing_method="risk_based",
            confidence_adjusted=confidence_dec < Decimal('1.0'),
            regime_adjusted=regime_adjusted,
            volatility_adjusted=volatility_adjusted,
            kelly_adjusted=kelly_adjusted,
            capped_by_strategy=capped_by_strategy,
            capped_by_global=capped_by_global,
            reason=reason,
        )

    def calculate_notional_based_size(
        self,
        capital_usd: Decimal,
        confidence: Decimal,
        volatility: Decimal,
        regime: RegimeType,
        strategy: Union[SleeveType, str],
        price: Decimal,
        kelly_multiplier: Decimal,
    ) -> PositionSizeResult:
        """
        Calculate position size using notional-based sizing (FALLBACK PATH).

        Used when stop_loss_pct and atr are both unavailable.
        Formula: notional = capital * confidence * kelly * regime * vol

        Args:
            capital_usd: Total capital in USD (must be > 0)
            confidence: Signal confidence (0-1)
            volatility: Current volatility (annualized, as decimal)
            regime: Current market regime
            strategy: Strategy requesting position
            price: Current asset price in USD
            kelly_multiplier: Kelly fraction from Commander

        Returns:
            PositionSizeResult with quantity and metadata
        """
        # Validate inputs
        if capital_usd <= Decimal('0'):
            raise PositionSizingError(f"capital_usd must be > 0, got {capital_usd}")
        if confidence < Decimal('0') or confidence > Decimal('1'):
            raise PositionSizingError(f"confidence must be in [0,1], got {confidence}")
        if price <= Decimal('0'):
            raise PositionSizingError(f"price must be > 0, got {price}")

        # Convert confidence to Decimal with proper precision
        confidence_dec = decimal_confidence(confidence)

        # Kelly: upper clamp only (preserve zero and small positive values)
        clamped_kelly = kelly_multiplier
        kelly_adjusted = False
        if clamped_kelly > self.kelly_fraction_max:
            clamped_kelly = self.kelly_fraction_max
            kelly_adjusted = True
        if clamped_kelly < Decimal('0'):
            clamped_kelly = Decimal('0')
            kelly_adjusted = True

        # Regime adjustment
        regime_mult = self._get_regime_multiplier(regime)
        regime_adjusted = regime_mult < Decimal('1.0')

        # Volatility adjustment
        vol_mult = self._get_volatility_multiplier(volatility)
        volatility_adjusted = vol_mult < Decimal('1.0')

        # Notional calculation
        notional_usd = capital_usd
        notional_usd = notional_usd * confidence_dec
        notional_usd = notional_usd * clamped_kelly
        notional_usd = notional_usd * regime_mult
        notional_usd = notional_usd * vol_mult
        notional_usd = notional_usd.quantize(USD_PRECISION)

        # Apply caps
        capped_notional, capped_by_strategy, capped_by_global = self._apply_caps(
            notional_usd, capital_usd, strategy
        )
        notional_usd = capped_notional

        # Calculate quantity
        quantity = (notional_usd / price).quantize(CRYPTO_PRECISION)

        # Percentages
        risk_percent = Decimal('0')  # Not applicable in fallback mode
        position_pct = safe_divide(notional_usd, capital_usd, USD_PRECISION)

        # Build reason string
        reason_parts = ["notional_fallback"]
        if confidence_dec < Decimal('1.0'):
            reason_parts.append(f"conf={confidence_dec:.3f}")
        if kelly_adjusted:
            reason_parts.append(f"kelly_upper_clamped={clamped_kelly:.3f}")
        if regime_adjusted:
            reason_parts.append(f"regime={regime.value}")
        if volatility_adjusted:
            reason_parts.append(f"vol={volatility:.3f}")
        if capped_by_strategy:
            cap_pct = self._get_strategy_cap_pct(strategy)
            reason_parts.append(f"strategy_capped={cap_pct:.0%}")
        if capped_by_global:
            reason_parts.append(f"global_capped={self.hard_cap_pct:.0%}")

        reason = "; ".join(reason_parts)

        return PositionSizeResult(
            quantity=quantity,
            notional_usd=notional_usd,
            risk_percent=risk_percent,
            position_pct=position_pct,
            sizing_method="notional_based",
            confidence_adjusted=confidence_dec < Decimal('1.0'),
            regime_adjusted=regime_adjusted,
            volatility_adjusted=volatility_adjusted,
            kelly_adjusted=kelly_adjusted,
            capped_by_strategy=capped_by_strategy,
            capped_by_global=capped_by_global,
            reason=reason,
        )

    def calculate_position_size(
        self,
        capital_usd: Decimal,
        confidence: Decimal,
        volatility: Decimal,
        regime: RegimeType,
        strategy: Union[SleeveType, str],
        price: Decimal,
        kelly_multiplier: Decimal = Decimal('0.85'),
        stop_loss_pct: Optional[Decimal] = None,
        atr: Optional[Decimal] = None,
    ) -> PositionSizeResult:
        """
        Calculate deterministic position size.

        PRIMARY PATH (risk-based): Uses stop_loss_pct or atr for true risk sizing.
        FALLBACK PATH (notional-based): Used when both stop_loss_pct and atr are None.

        Args:
            capital_usd: Total capital in USD (must be > 0)
            confidence: Signal confidence (0-1)
            volatility: Current volatility (annualized, as decimal)
            regime: Current market regime
            strategy: Strategy requesting position
            price: Current asset price in USD
            kelly_multiplier: Kelly fraction from Commander (0.4 SAFE, 0.85 ATTACK)
            stop_loss_pct: Optional stop loss as fractional distance (e.g., 0.015 = 1.5%)
            atr: Optional Average True Range in RAW DOLLARS (e.g., 1500 for BTC)

        Returns:
            PositionSizeResult with quantity and metadata

        Raises:
            PositionSizingError: If capital_usd <= 0 or confidence out of range
        """
        # Validate inputs
        if capital_usd <= Decimal('0'):
            raise PositionSizingError(f"capital_usd must be > 0, got {capital_usd}")
        if confidence < Decimal('0') or confidence > Decimal('1'):
            raise PositionSizingError(f"confidence must be in [0,1], got {confidence}")
        if price <= Decimal('0'):
            raise PositionSizingError(f"price must be > 0, got {price}")

        # Primary path: risk-based sizing (requires stop distance)
        if stop_loss_pct is not None or atr is not None:
            try:
                return self.calculate_risk_based_size(
                    capital_usd=capital_usd,
                    confidence=confidence,
                    volatility=volatility,
                    regime=regime,
                    strategy=strategy,
                    price=price,
                    kelly_multiplier=kelly_multiplier,
                    stop_loss_pct=stop_loss_pct,
                    atr=atr,
                )
            except PositionSizingError as e:
                logger.warning(f"Risk-based sizing failed: {e}, falling back to notional-based")
                # Fall through to notional-based

        # Fallback path: notional-based sizing
        return self.calculate_notional_based_size(
            capital_usd=capital_usd,
            confidence=confidence,
            volatility=volatility,
            regime=regime,
            strategy=strategy,
            price=price,
            kelly_multiplier=kelly_multiplier,
        )

    def get_strategy_cap_percent(self, strategy: Union[SleeveType, str]) -> Decimal:
        """Get strategy-specific cap percentage."""
        return self._get_strategy_cap_pct(strategy)

    def get_hard_cap_percent(self) -> Decimal:
        """Get hard global cap percentage."""
        return self.hard_cap_pct

    def get_risk_per_trade_percent(self) -> Decimal:
        """Get risk per trade percentage from config."""
        return self.risk_per_trade_pct


# ============================================
# Convenience Functions
# ============================================

def create_position_sizing_engine(config: Any) -> PositionSizingEngine:
    """
    Create a configured position sizing engine.

    Args:
        config: Configuration object

    Returns:
        PositionSizingEngine instance
    """
    return PositionSizingEngine(config)


__all__ = [
    'PositionSizingEngine',
    'PositionSizingError',
    'PositionSizeResult',
    'create_position_sizing_engine',
]