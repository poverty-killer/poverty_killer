"""
POVERTY KILLER — Cross-Asset Risk Model

Pre-integration, passive model only.

This module provides cross-asset exposure, correlation, concentration,
and capacity models that complement the existing HybridRiskGuard without
replacing or duplicating its authority.

Design constraints:
- No imports from HybridRiskGuard, UnifiedRisk, or other active risk modules.
- No risk authority — passive model and report generation only.
- No order blocking/vetoing.
- No side effects.
- Decimal for all monetary/sizing values.
- Type hints required.

Board escalation markers:
- Correlation matrix requires market data (external).
- Stress scenarios are illustrative, not calibrated.
- Beta estimates require market data.
- Covariance matrix requires market data.

Author: D / DeepSeek — Stage 2-G0B
Date: 2026-05-03
Status: PRE-INTEGRATION — PASSIVE MODEL — NO RISK AUTHORITY
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, unique
from typing import Optional, Dict, List, Tuple, FrozenSet

from app.models.instrument_profile import (
    InstrumentProfile,
    AssetClass,
    RiskBucket,
    LiquidityTier,
)


# ────────────────────────────────────────────────────────────────
# Risk Enums
# ────────────────────────────────────────────────────────────────

@unique
class ExposureType(str, Enum):
    """Classification of exposure by market orientation."""
    GROSS_LONG = "gross_long"            # Sum of all long positions
    GROSS_SHORT = "gross_short"          # Sum of all short positions
    NET = "net"                          # Long - Short
    GROSS = "gross"                      # Long + Short


@unique
class ConcentrationLevel(str, Enum):
    """Concentration classification."""
    NORMAL = "normal"                    # Within limits
    ELEVATED = "elevated"               # Above warning threshold
    HIGH = "high"                        # Above soft limit
    EXTREME = "extreme"                 # Above hard limit


@unique
class StressScenario(str, Enum):
    """Pre-defined stress scenarios for loss estimation."""
    COVID_2020 = "covid_2020"            # Mar 2020-style drawdown
    GFC_2008 = "gfc_2008"               # 2008 financial crisis
    DOT_COM_2000 = "dot_com_2000"       # 2000-2002 bear market
    FLASH_CRASH_2010 = "flash_crash_2010"
    VOL_SHOCK = "vol_shock"              # VIX spike scenario
    CRYPTO_CRASH_2022 = "crypto_crash_2022"
    CORRELATION_SHOCK = "correlation_shock"  # All correlations -> 1


# ────────────────────────────────────────────────────────────────
# Risk Data Models
# ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AssetClassExposure:
    """Exposure breakdown by asset class."""
    asset_class: AssetClass
    gross_long_usd: Decimal
    gross_short_usd: Decimal
    net_usd: Decimal
    gross_usd: Decimal
    instruments: Tuple[str, ...]
    position_count: int

    @property
    def net_pct_of_total(self) -> Decimal:
        """Net exposure as percentage of total gross."""
        if self.gross_usd > Decimal("0"):
            return self.net_usd / self.gross_usd
        return Decimal("0")


@dataclass(frozen=True)
class SectorExposure:
    """Exposure breakdown by sector/industry."""
    sector: str
    gross_long_usd: Decimal
    gross_short_usd: Decimal
    net_usd: Decimal
    instruments: Tuple[str, ...]
    concentration_pct: Decimal          # Sector % of total equity


@dataclass(frozen=True)
class CorrelationClusterExposure:
    """Exposure within a correlation cluster."""
    cluster: str
    gross_usd: Decimal
    net_usd: Decimal
    instruments: Tuple[str, ...]
    concentration_pct: Decimal
    worst_case_correlation: Decimal     # Estimated intra-cluster corr in stress


@dataclass(frozen=True)
class BetaExposure:
    """Portfolio beta exposure."""
    reference_symbol: str               # Usually "SPY"
    portfolio_beta: Decimal
    equity_beta: Decimal
    futures_beta: Decimal
    crypto_beta: Decimal
    total_beta_adjusted_exposure: Decimal  # Gross × beta


@dataclass(frozen=True)
class OvernightGapRisk:
    """Estimated overnight/weekend gap risk."""
    symbol: str
    max_gap_pct_20d: Decimal
    expected_gap_pct: Decimal
    worst_case_gap_pct: Decimal
    overnight_exposure_usd: Decimal
    estimated_gap_loss_usd: Decimal


@dataclass(frozen=True)
class StressScenarioLoss:
    """Estimated loss under a specific stress scenario."""
    scenario: StressScenario
    estimated_loss_usd: Decimal
    loss_pct_of_equity: Decimal
    worst_instrument: str
    worst_instrument_loss_pct: Decimal
    assumptions: Tuple[str, ...]


@dataclass(frozen=True)
class LiquidityAdjustedExposure:
    """Exposure adjusted for liquidation time given liquidity tier."""
    symbol: str
    gross_exposure_usd: Decimal
    liquidity_tier: LiquidityTier
    estimated_liquidation_days: Decimal  # Days to exit given ADV cap
    liquidity_adjusted_exposure: Decimal  # Exposure × (1 + days/30) penalty
    is_concentrated: bool


@dataclass(frozen=True)
class CrossAssetRiskReport:
    """
    Complete cross-asset risk snapshot.

    This is passive: no risk authority, no order blocking, no execution veto.
    It provides the risk view that future components may use for sizing,
    allocation, and stress testing.
    """
    timestamp_ns: int

    # Total portfolio
    total_equity_usd: Decimal
    total_gross_exposure_usd: Decimal
    total_net_exposure_usd: Decimal
    gross_leverage: Decimal               # Gross / Equity
    net_leverage: Decimal                 # Net / Equity

    # By asset class
    asset_class_exposures: Tuple[AssetClassExposure, ...]

    # By sector
    sector_exposures: Tuple[SectorExposure, ...]

    # By correlation cluster
    cluster_exposures: Tuple[CorrelationClusterExposure, ...]

    # Beta
    beta_exposure: Optional[BetaExposure] = None

    # Concentration
    top_concentration: str = ""           # Worst concentration
    concentration_level: ConcentrationLevel = ConcentrationLevel.NORMAL
    max_single_instrument_pct: Decimal = Decimal("0")
    max_single_sector_pct: Decimal = Decimal("0")

    # Margin
    estimated_margin_used_usd: Decimal = Decimal("0")
    estimated_margin_available_usd: Decimal = Decimal("0")
    margin_utilization_pct: Decimal = Decimal("0")

    # Gap risk
    overnight_gap_risks: Tuple[OvernightGapRisk, ...] = field(default_factory=tuple)
    total_overnight_gap_risk_usd: Decimal = Decimal("0")

    # Futures
    futures_notional_usd: Decimal = Decimal("0")
    futures_notional_effective_leverage: Decimal = Decimal("0")

    # Stress
    stress_losses: Tuple[StressScenarioLoss, ...] = field(default_factory=tuple)
    max_stress_loss_usd: Decimal = Decimal("0")
    max_stress_loss_pct: Decimal = Decimal("0")

    # Liquidity
    liquidity_adjusted_exposures: Tuple[LiquidityAdjustedExposure, ...] = field(default_factory=tuple)

    # Crypto-specific
    crypto_24_7_exposure_usd: Decimal = Decimal("0")
    crypto_overnight_risk_usd: Decimal = Decimal("0")


# ────────────────────────────────────────────────────────────────
# Cross-Asset Risk Calculator (Passive)
# ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CrossAssetRiskCalculator:
    """
    Stateless cross-asset risk calculator.

    Takes portfolio state + instrument profiles + external data (prices, correlations)
    and produces a CrossAssetRiskReport. No side effects. No risk authority.
    """

    def calculate(
        self,
        positions: Dict[str, Dict[str, Decimal]],  # symbol -> {qty, avg_price}
        current_prices: Dict[str, Decimal],
        instruments: Dict[str, InstrumentProfile],
        equity: Decimal,
        correlation_estimates: Optional[Dict[Tuple[str, str], Decimal]] = None,
        beta_estimates: Optional[Dict[str, Decimal]] = None,
        stress_scenarios: Optional[FrozenSet[StressScenario]] = None,
        timestamp_ns: int = 0,
    ) -> CrossAssetRiskReport:
        """
        Calculate cross-asset risk report.

        Args:
            positions: Dict of symbol -> {quantity: Decimal, avg_price: Decimal}
            current_prices: Dict of symbol -> current mid price
            instruments: Dict of symbol -> InstrumentProfile
            equity: Total portfolio equity
            correlation_estimates: Optional correlation matrix
            beta_estimates: Optional beta estimates per symbol
            stress_scenarios: Scenarios to evaluate
            timestamp_ns: Report timestamp

        Returns:
            CrossAssetRiskReport (passive, no authority)
        """
        # Calculate exposures
        exposures: Dict[str, Decimal] = {}
        for symbol, pos in positions.items():
            qty = pos.get("quantity", Decimal("0"))
            price = current_prices.get(symbol, Decimal("0"))
            instrument = instruments.get(symbol)
            multiplier = instrument.constraints.contract_multiplier if instrument else Decimal("1")
            notional = qty * price * multiplier
            exposures[symbol] = notional

        # Gross/Net
        gross_long = sum(e for e in exposures.values() if e > Decimal("0"))
        gross_short = sum(abs(e) for e in exposures.values() if e < Decimal("0"))
        total_gross = gross_long + gross_short
        total_net = gross_long - gross_short

        if equity > Decimal("0"):
            gross_leverage = total_gross / equity
            net_leverage = total_net / equity
        else:
            gross_leverage = Decimal("0")
            net_leverage = Decimal("0")

        # Asset class exposures
        asset_class_exposures = self._calculate_asset_class_exposures(
            positions, current_prices, instruments, exposures
        )

        # Concentration
        max_single = Decimal("0")
        if exposures and equity > Decimal("0"):
            max_single = max(abs(e) for e in exposures.values()) / equity

        concentration = ConcentrationLevel.NORMAL
        if max_single > Decimal("0.40"):
            concentration = ConcentrationLevel.EXTREME
        elif max_single > Decimal("0.25"):
            concentration = ConcentrationLevel.HIGH
        elif max_single > Decimal("0.15"):
            concentration = ConcentrationLevel.ELEVATED

        # Stress losses
        stress_scenarios_set = stress_scenarios or frozenset({
            StressScenario.VOL_SHOCK,
            StressScenario.CORRELATION_SHOCK,
        })
        stress_losses = self._estimate_stress_losses(
            stress_scenarios_set, exposures, equity, instruments
        )

        max_stress_loss = max((s.estimated_loss_usd for s in stress_losses), default=Decimal("0"))
        max_stress_loss_pct = max((s.loss_pct_of_equity for s in stress_losses), default=Decimal("0"))

        return CrossAssetRiskReport(
            timestamp_ns=timestamp_ns,
            total_equity_usd=equity,
            total_gross_exposure_usd=total_gross,
            total_net_exposure_usd=total_net,
            gross_leverage=gross_leverage,
            net_leverage=net_leverage,
            asset_class_exposures=tuple(asset_class_exposures),
            sector_exposures=(),
            cluster_exposures=(),
            max_single_instrument_pct=max_single,
            concentration_level=concentration,
            stress_losses=tuple(stress_losses),
            max_stress_loss_usd=max_stress_loss,
            max_stress_loss_pct=max_stress_loss_pct,
        )

    def _calculate_asset_class_exposures(
        self,
        positions: Dict[str, Dict[str, Decimal]],
        prices: Dict[str, Decimal],
        instruments: Dict[str, InstrumentProfile],
        exposures: Dict[str, Decimal],
    ) -> List[AssetClassExposure]:
        """Group exposures by asset class."""
        by_class: Dict[AssetClass, Dict[str, List[Decimal]]] = {}

        for symbol, notional in exposures.items():
            instrument = instruments.get(symbol)
            if not instrument:
                continue
            ac = instrument.asset_class
            if ac not in by_class:
                by_class[ac] = {"longs": [], "shorts": [], "symbols": []}
            by_class[ac]["symbols"].append(symbol)
            if notional >= 0:
                by_class[ac]["longs"].append(notional)
            else:
                by_class[ac]["shorts"].append(abs(notional))

        result = []
        for ac, data in by_class.items():
            gross_long = sum(data["longs"])
            gross_short = sum(data["shorts"])
            result.append(AssetClassExposure(
                asset_class=ac,
                gross_long_usd=gross_long,
                gross_short_usd=gross_short,
                net_usd=gross_long - gross_short,
                gross_usd=gross_long + gross_short,
                instruments=tuple(data["symbols"]),
                position_count=len(data["symbols"]),
            ))
        return result

    def _estimate_stress_losses(
        self,
        scenarios: FrozenSet[StressScenario],
        exposures: Dict[str, Decimal],
        equity: Decimal,
        instruments: Dict[str, InstrumentProfile],
    ) -> List[StressScenarioLoss]:
        """
        Estimate portfolio loss under stress scenarios.

        BOARD ESCALATION: These are illustrative, not calibrated.
        Production requires full covariance matrix and historical scenario calibration.
        """
        # Illustrative shock factors per scenario per asset class
        shock_factors: Dict[StressScenario, Dict[AssetClass, Decimal]] = {
            StressScenario.VOL_SHOCK: {
                AssetClass.CRYPTO: Decimal("0.30"),
                AssetClass.EQUITY: Decimal("0.15"),
                AssetClass.ETF: Decimal("0.15"),
                AssetClass.FUTURE: Decimal("0.15"),
                AssetClass.FOREX: Decimal("0.05"),
            },
            StressScenario.CORRELATION_SHOCK: {
                AssetClass.CRYPTO: Decimal("0.40"),
                AssetClass.EQUITY: Decimal("0.25"),
                AssetClass.ETF: Decimal("0.25"),
                AssetClass.FUTURE: Decimal("0.25"),
                AssetClass.FOREX: Decimal("0.10"),
            },
            StressScenario.CRYPTO_CRASH_2022: {
                AssetClass.CRYPTO: Decimal("0.60"),
                AssetClass.EQUITY: Decimal("0.05"),
                AssetClass.ETF: Decimal("0.05"),
                AssetClass.FUTURE: Decimal("0.05"),
                AssetClass.FOREX: Decimal("0.02"),
            },
        }

        results = []
        for scenario in scenarios:
            shocks = shock_factors.get(scenario, {})
            total_loss = Decimal("0")
            worst_symbol = ""
            worst_loss_pct = Decimal("0")

            for symbol, notional in exposures.items():
                instrument = instruments.get(symbol)
                if not instrument:
                    continue
                shock = shocks.get(instrument.asset_class, Decimal("0.10"))
                loss = abs(notional) * shock
                total_loss += loss

                if notional != Decimal("0"):
                    loss_pct = loss / abs(notional)
                    if loss_pct > worst_loss_pct:
                        worst_loss_pct = loss_pct
                        worst_symbol = symbol

            if equity > Decimal("0"):
                loss_pct_of_equity = total_loss / equity
            else:
                loss_pct_of_equity = Decimal("0")

            results.append(StressScenarioLoss(
                scenario=scenario,
                estimated_loss_usd=total_loss,
                loss_pct_of_equity=loss_pct_of_equity,
                worst_instrument=worst_symbol,
                worst_instrument_loss_pct=worst_loss_pct,
                assumptions=("illustrative_only", "no_covariance_calibration"),
            ))

        return results


# ────────────────────────────────────────────────────────────────
# Module Exports
# ────────────────────────────────────────────────────────────────

__all__ = [
    "ExposureType",
    "ConcentrationLevel",
    "StressScenario",
    "AssetClassExposure",
    "SectorExposure",
    "CorrelationClusterExposure",
    "BetaExposure",
    "OvernightGapRisk",
    "StressScenarioLoss",
    "LiquidityAdjustedExposure",
    "CrossAssetRiskReport",
    "CrossAssetRiskCalculator",
]