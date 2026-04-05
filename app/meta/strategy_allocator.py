"""
Sovereign Governor - Active Risk Management Engine
The final piece of the risk-management trinity.
Features:
- Active Heat Throttling (scales ALL signals based on portfolio heat)
- Correlation Position Slashing (halves correlated positions, doesn't reject)
- Hard 10% Cash Reserve (exactly $2,000 dry powder)
- Returns ADJUSTED ALLOCATION (float), not boolean rejection
- Predatory scaling - keeps bot in the fight during correlated opportunities
"""

import logging
import threading
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import deque
from enum import Enum

from app.constants import SleeveType, AssetClass, ControlMode

logger = logging.getLogger(__name__)

# Machine epsilon
EPS = np.finfo(float).eps


class AllocationMode(Enum):
    """Allocation modes for the governor."""
    CONSERVATIVE = "conservative"    # 30% of max capital
    NORMAL = "normal"                 # 60% of max capital
    AGGRESSIVE = "aggressive"         # 85% of max capital
    ATTACK = "attack"                 # 100% of max capital (with oversight)
    EMERGENCY = "emergency"           # 0% - no new allocations


@dataclass
class StrategyAllocation:
    """Allocation for a single strategy."""
    strategy: SleeveType
    allocated_capital: float
    used_capital: float
    max_capital: float
    pnl: float
    win_rate: float
    sharpe: float
    last_allocation: datetime
    is_active: bool = True
    risk_score: float = 0.5

    __slots__ = ("strategy", "allocated_capital", "used_capital", "max_capital",
                 "pnl", "win_rate", "sharpe", "last_allocation", "is_active", "risk_score")


@dataclass
class AssetExposure:
    """Exposure for a single asset."""
    symbol: str
    asset_class: AssetClass
    current_exposure: float
    max_exposure: float
    pnl: float
    position_count: int
    strategies: List[SleeveType]

    __slots__ = ("symbol", "asset_class", "current_exposure", "max_exposure",
                 "pnl", "position_count", "strategies")


class SovereignGovernor:
    """
    Sovereign Governor - Active Risk Management Engine.
    
    The final gatekeeper for capital allocation.
    Features:
    - ACTIVE HEAT THROTTLING: Scales ALL signals based on portfolio heat
    - CORRELATION POSITION SLASHING: Halves correlated positions, doesn't reject
    - Hard 10% Cash Reserve: Exactly $2,000 dry powder
    - Returns ADJUSTED ALLOCATION (float), not boolean rejection
    """
    
    def __init__(
        self,
        total_capital: float = 20000.0,
        cash_reserve_pct: float = 0.10,  # HARD 10% - Sovereign Requirement
        max_strategy_exposure_pct: float = 0.40,
        max_asset_exposure_pct: float = 0.20,
        correlation_kill_threshold: float = 0.85,
        allocation_cooldown_sec: float = 60.0,
        performance_decay_hours: float = 24.0,
        min_win_rate: float = 0.40,
        min_sharpe: float = 0.5,
        heat_throttle_70_pct: float = 0.7,   # 70% exposure = 0.7 multiplier
        heat_throttle_90_pct: float = 0.2,   # 90% exposure = 0.2 multiplier
        correlation_slash_factor: float = 0.5  # Correlated positions = half size
    ):
        """
        Initialize sovereign governor.

        Args:
            total_capital: Total portfolio capital
            cash_reserve_pct: HARD 10% cash reserve (Sovereign requirement)
            max_strategy_exposure_pct: Max exposure per strategy
            max_asset_exposure_pct: Max exposure per asset
            correlation_kill_threshold: Correlation threshold for slashing
            allocation_cooldown_sec: Cooldown between allocations
            performance_decay_hours: Hours before performance metrics decay
            min_win_rate: Minimum win rate to allocate
            min_sharpe: Minimum Sharpe ratio to allocate
            heat_throttle_70_pct: Multiplier when exposure >70%
            heat_throttle_90_pct: Multiplier when exposure >90%
            correlation_slash_factor: Multiply by this when correlated (0.5 = half)
        """
        self.total_capital = total_capital
        self.cash_reserve_pct = cash_reserve_pct  # HARD 10%
        self.max_strategy_exposure_pct = max_strategy_exposure_pct
        self.max_asset_exposure_pct = max_asset_exposure_pct
        self.correlation_kill_threshold = correlation_kill_threshold
        self.allocation_cooldown_sec = allocation_cooldown_sec
        self.performance_decay_hours = performance_decay_hours
        self.min_win_rate = min_win_rate
        self.min_sharpe = min_sharpe
        self.heat_throttle_70_pct = heat_throttle_70_pct
        self.heat_throttle_90_pct = heat_throttle_90_pct
        self.correlation_slash_factor = correlation_slash_factor
        
        # Deployable capital after cash reserve (HARD 10%)
        self.deployable_capital = total_capital * (1 - cash_reserve_pct)
        
        # Strategy allocations
        self._strategy_allocations: Dict[SleeveType, StrategyAllocation] = {}
        self._strategy_lock = threading.Lock()
        
        # Asset exposures
        self._asset_exposures: Dict[str, AssetExposure] = {}
        self._asset_lock = threading.Lock()
        
        # Correlation tracking
        self._correlation_matrix: Dict[Tuple[str, str], float] = {}
        self._correlation_history: Dict[Tuple[str, str], deque] = {}
        
        # Performance history
        self._strategy_performance: Dict[SleeveType, deque] = {}
        
        # Allocation mode
        self._mode = AllocationMode.NORMAL
        self._mode_lock = threading.Lock()
        
        # Last allocation times
        self._last_allocation_time: Dict[SleeveType, datetime] = {}
        
        # Heat tracking
        self._heat_history: deque = deque(maxlen=100)
        self._last_heat_multiplier: float = 1.0
        
        # Initialize strategy allocations
        self._init_strategy_allocations()
        
        logger.info(f"SovereignGovernor initialized: total_capital=${total_capital:,.2f}, "
                   f"deployable=${self.deployable_capital:,.2f}, "
                   f"cash_reserve={cash_reserve_pct:.0%} (HARD 10%), "
                   f"max_strategy={max_strategy_exposure_pct:.0%}, "
                   f"max_asset={max_asset_exposure_pct:.0%}, "
                   f"correlation_slash={correlation_slash_factor:.0%}, "
                   f"heat_70={heat_throttle_70_pct:.0%}, heat_90={heat_throttle_90_pct:.0%}")
    
    # ============================================
    # INITIALIZATION
    # ============================================
    
    def _init_strategy_allocations(self) -> None:
        """Initialize allocation structures for all strategies."""
        strategy_max = self.deployable_capital * self.max_strategy_exposure_pct
        
        self._strategy_allocations = {
            SleeveType.SHADOW_FRONT: StrategyAllocation(
                strategy=SleeveType.SHADOW_FRONT,
                allocated_capital=strategy_max,
                used_capital=0.0,
                max_capital=strategy_max,
                pnl=0.0,
                win_rate=0.5,
                sharpe=0.5,
                last_allocation=datetime.utcnow(),
                is_active=True,
                risk_score=0.4
            ),
            SleeveType.FLV: StrategyAllocation(
                strategy=SleeveType.FLV,
                allocated_capital=strategy_max,
                used_capital=0.0,
                max_capital=strategy_max,
                pnl=0.0,
                win_rate=0.5,
                sharpe=0.5,
                last_allocation=datetime.utcnow(),
                is_active=True,
                risk_score=0.6
            ),
            SleeveType.ENTROPY_DECODER: StrategyAllocation(
                strategy=SleeveType.ENTROPY_DECODER,
                allocated_capital=strategy_max,
                used_capital=0.0,
                max_capital=strategy_max,
                pnl=0.0,
                win_rate=0.5,
                sharpe=0.5,
                last_allocation=datetime.utcnow(),
                is_active=True,
                risk_score=0.5
            ),
            SleeveType.GAMMA_FRONT: StrategyAllocation(
                strategy=SleeveType.GAMMA_FRONT,
                allocated_capital=strategy_max,
                used_capital=0.0,
                max_capital=strategy_max,
                pnl=0.0,
                win_rate=0.5,
                sharpe=0.5,
                last_allocation=datetime.utcnow(),
                is_active=True,
                risk_score=0.55
            ),
            SleeveType.SECTOR_ROTATION: StrategyAllocation(
                strategy=SleeveType.SECTOR_ROTATION,
                allocated_capital=strategy_max,
                used_capital=0.0,
                max_capital=strategy_max,
                pnl=0.0,
                win_rate=0.5,
                sharpe=0.5,
                last_allocation=datetime.utcnow(),
                is_active=True,
                risk_score=0.45
            ),
        }
        
        # Initialize performance history
        for strategy in SleeveType:
            self._strategy_performance[strategy] = deque(maxlen=100)
    
    # ============================================
    # ACTIVE HEAT THROTTLING (NEW - Sovereign Requirement)
    # ============================================
    
    def get_heat_multiplier(self) -> float:
        """
        Get active heat multiplier based on total exposure.
        Scales ALL signals based on portfolio heat.
        
        Returns:
            Multiplier (0.2 to 1.0) to apply to all allocations
        """
        total_exposure = self.get_total_exposure()
        usage_pct = total_exposure / max(self.deployable_capital, 1.0)
        
        # Track heat history
        self._heat_history.append(usage_pct)
        
        if usage_pct >= 0.90:
            multiplier = self.heat_throttle_90_pct
        elif usage_pct >= 0.70:
            multiplier = self.heat_throttle_70_pct
        else:
            multiplier = 1.0
        
        self._last_heat_multiplier = multiplier
        
        # Log when throttling is active
        if multiplier < 1.0:
            logger.info(f"HEAT THROTTLING ACTIVE: exposure={usage_pct:.1%}, multiplier={multiplier:.1%}")
        
        return multiplier
    
    def get_heat_metrics(self) -> Dict[str, Any]:
        """Get heat metrics for monitoring."""
        total_exposure = self.get_total_exposure()
        usage_pct = total_exposure / max(self.deployable_capital, 1.0)
        
        return {
            "total_exposure": total_exposure,
            "deployable_capital": self.deployable_capital,
            "usage_pct": usage_pct,
            "heat_multiplier": self.get_heat_multiplier(),
            "heat_throttle_70": self.heat_throttle_70_pct,
            "heat_throttle_90": self.heat_throttle_90_pct,
            "is_throttled": usage_pct >= 0.70,
            "heat_history": list(self._heat_history)[-20:]
        }
    
    # ============================================
    # CORRELATION POSITION SLASHING (NEW - Sovereign Requirement)
    # ============================================
    
    def get_correlation_slash_factor(self, symbol: str, existing_exposures: List[str]) -> float:
        """
        Get correlation slash factor for a position.
        Does NOT reject trades. Instead, returns a multiplier to apply.
        
        Args:
            symbol: Proposed symbol
            existing_exposures: Current positions

        Returns:
            Slash factor (1.0 = no slash, 0.5 = half size, etc.)
        """
        max_correlation = 0.0
        for existing in existing_exposures:
            correlation = self.get_correlation(symbol, existing)
            max_correlation = max(max_correlation, abs(correlation))
        
        if max_correlation > self.correlation_kill_threshold:
            # Slash by correlation_slash_factor (default 0.5 = half size)
            logger.info(f"CORRELATION SLASH: {symbol} correlated {max_correlation:.2f} with {existing_exposures} -> {self.correlation_slash_factor:.0%} size")
            return self.correlation_slash_factor
        
        return 1.0
    
    # ============================================
    # ADJUSTED ALLOCATION (RETURNS FLOAT, NOT BOOLEAN)
    # ============================================
    
    def calculate_adjusted_allocation(
        self,
        strategy: SleeveType,
        requested_capital: float,
        symbol: str,
        asset_class: AssetClass
    ) -> Tuple[float, str]:
        """
        Calculate adjusted allocation amount.
        Does NOT reject - always returns an amount (could be 0).
        
        Args:
            strategy: Strategy requesting allocation
            requested_capital: Capital requested
            symbol: Asset symbol
            asset_class: Asset class

        Returns:
            Tuple of (adjusted_allocation, reason)
        """
        # 1. Mode check
        if self.get_mode() == AllocationMode.EMERGENCY:
            return 0.0, "EMERGENCY_MODE"
        
        # 2. Cooldown check
        last_time = self._last_allocation_time.get(strategy)
        if last_time:
            elapsed = (datetime.utcnow() - last_time).total_seconds()
            if elapsed < self.allocation_cooldown_sec:
                return 0.0, f"COOLDOWN: {elapsed:.1f}s < {self.allocation_cooldown_sec}s"
        
        # 3. Strategy-specific checks
        with self._strategy_lock:
            if strategy not in self._strategy_allocations:
                return 0.0, f"UNKNOWN_STRATEGY: {strategy}"
            
            alloc = self._strategy_allocations[strategy]
            
            # Performance thresholds (scored, not hard reject)
            performance_factor = 1.0
            if alloc.win_rate < self.min_win_rate:
                performance_factor *= 0.5
                logger.debug(f"Low win rate {alloc.win_rate:.2%} for {strategy.value} -> scaling to {performance_factor:.0%}")
            
            if alloc.sharpe < self.min_sharpe:
                performance_factor *= 0.7
                logger.debug(f"Low Sharpe {alloc.sharpe:.2f} for {strategy.value} -> scaling to {performance_factor:.0%}")
            
            # Available capital
            available = max(0.0, alloc.max_capital - alloc.used_capital)
            if available <= 0:
                return 0.0, f"STRATEGY_LIMIT: no capital available"
            
            # Performance-adjusted request
            requested = requested_capital * performance_factor
        
        # 4. Asset class limit check (scaled, not hard reject)
        class_exposure = self.get_exposure_by_class(asset_class)
        class_limit = self.deployable_capital * self._get_class_limit(asset_class)
        class_available = max(0.0, class_limit - class_exposure)
        
        if class_available <= 0:
            return 0.0, f"CLASS_LIMIT: {asset_class.value} full"
        
        requested = min(requested, class_available)
        
        # 5. Single asset limit check (scaled, not hard reject)
        asset_exposure = self.get_asset_exposure(symbol)
        asset_limit = self.deployable_capital * self.max_asset_exposure_pct
        current = asset_exposure.current_exposure if asset_exposure else 0.0
        asset_available = max(0.0, asset_limit - current)
        
        requested = min(requested, asset_available)
        
        # 6. Correlation slash (NEW - Sovereign requirement)
        existing_symbols = list(self._asset_exposures.keys())
        correlation_factor = self.get_correlation_slash_factor(symbol, existing_symbols)
        requested = requested * correlation_factor
        
        # 7. Active heat throttling (NEW - Sovereign requirement)
        heat_multiplier = self.get_heat_multiplier()
        requested = requested * heat_multiplier
        
        # 8. Mode scaling
        mode_multiplier = self.get_exposure_multiplier()
        requested = requested * mode_multiplier
        
        # 9. Final clamp
        requested = max(0.0, min(requested, self.deployable_capital))
        
        # Build reason string
        reason_parts = []
        if performance_factor < 1.0:
            reason_parts.append(f"perf={performance_factor:.0%}")
        if correlation_factor < 1.0:
            reason_parts.append(f"corr_slash={correlation_factor:.0%}")
        if heat_multiplier < 1.0:
            reason_parts.append(f"heat={heat_multiplier:.0%}")
        if mode_multiplier < 1.0:
            reason_parts.append(f"mode={mode_multiplier:.0%}")
        
        reason = " | ".join(reason_parts) if reason_parts else "full"
        
        logger.debug(f"Allocation for {strategy.value}/{symbol}: requested ${requested_capital:,.2f} -> adjusted ${requested:,.2f} ({reason})")
        
        return requested, reason
    
    # ============================================
    # ALLOCATE (Uses adjusted allocation)
    # ============================================
    
    def allocate(
        self,
        strategy: SleeveType,
        requested_capital: float,
        symbol: str,
        asset_class: AssetClass
    ) -> Tuple[bool, float, str]:
        """
        Allocate capital to a strategy (returns adjusted amount).

        Args:
            strategy: Strategy to allocate to
            requested_capital: Capital requested
            symbol: Asset symbol
            asset_class: Asset class

        Returns:
            Tuple of (success, allocated_amount, reason)
        """
        adjusted, reason = self.calculate_adjusted_allocation(
            strategy, requested_capital, symbol, asset_class
        )
        
        if adjusted <= 0:
            return False, 0.0, reason
        
        # Update strategy allocation
        with self._strategy_lock:
            if strategy in self._strategy_allocations:
                self._strategy_allocations[strategy].used_capital += adjusted
                self._strategy_allocations[strategy].last_allocation = datetime.utcnow()
        
        # Update asset exposure
        exposure = self.get_asset_exposure(symbol)
        if exposure:
            exposure.current_exposure += adjusted
            if strategy not in exposure.strategies:
                exposure.strategies.append(strategy)
            exposure.position_count += 1
        else:
            self._asset_exposures[symbol] = AssetExposure(
                symbol=symbol,
                asset_class=asset_class,
                current_exposure=adjusted,
                max_exposure=self.deployable_capital * self.max_asset_exposure_pct,
                pnl=0.0,
                position_count=1,
                strategies=[strategy]
            )
        
        # Record allocation time
        self._last_allocation_time[strategy] = datetime.utcnow()
        
        logger.info(f"Allocated ${adjusted:,.2f} to {strategy.value} for {symbol} ({reason})")
        return True, adjusted, reason
    
    def deallocate(self, strategy: SleeveType, capital: float, symbol: str) -> None:
        """
        Deallocate capital from a strategy.

        Args:
            strategy: Strategy to deallocate from
            capital: Capital amount
            symbol: Asset symbol
        """
        with self._strategy_lock:
            if strategy in self._strategy_allocations:
                self._strategy_allocations[strategy].used_capital -= capital
                if self._strategy_allocations[strategy].used_capital < 0:
                    self._strategy_allocations[strategy].used_capital = 0
        
        # Update asset exposure
        exposure = self.get_asset_exposure(symbol)
        if exposure:
            exposure.current_exposure -= capital
            exposure.position_count -= 1
            if exposure.current_exposure <= 0:
                if strategy in exposure.strategies:
                    exposure.strategies.remove(strategy)
                if exposure.position_count <= 0 and exposure.current_exposure <= 0:
                    with self._asset_lock:
                        if symbol in self._asset_exposures:
                            del self._asset_exposures[symbol]
        
        logger.info(f"Deallocated ${capital:,.2f} from {strategy.value} for {symbol}")
    
    # ============================================
    # MODE MANAGEMENT
    # ============================================
    
    def set_mode(self, mode: AllocationMode, reason: str = "") -> None:
        """Set allocation mode."""
        with self._mode_lock:
            old_mode = self._mode
            self._mode = mode
            logger.info(f"Allocation mode changed: {old_mode.value} -> {mode.value} ({reason})")
    
    def get_mode(self) -> AllocationMode:
        """Get current allocation mode."""
        with self._mode_lock:
            return self._mode
    
    def get_exposure_multiplier(self) -> float:
        """Get exposure multiplier based on mode."""
        multipliers = {
            AllocationMode.CONSERVATIVE: 0.3,
            AllocationMode.NORMAL: 0.6,
            AllocationMode.AGGRESSIVE: 0.85,
            AllocationMode.ATTACK: 1.0,
            AllocationMode.EMERGENCY: 0.0
        }
        return multipliers.get(self._mode, 0.6)
    
    # ============================================
    # PERFORMANCE TRACKING
    # ============================================
    
    def update_strategy_performance(
        self,
        strategy: SleeveType,
        pnl: float,
        win_rate: Optional[float] = None,
        sharpe: Optional[float] = None
    ) -> None:
        """Update strategy performance metrics."""
        with self._strategy_lock:
            if strategy not in self._strategy_allocations:
                return
            
            allocation = self._strategy_allocations[strategy]
            allocation.pnl += pnl
            
            if win_rate is not None:
                allocation.win_rate = win_rate
            if sharpe is not None:
                allocation.sharpe = sharpe
            
            # Add to performance history
            self._strategy_performance[strategy].append({
                "timestamp": datetime.utcnow(),
                "pnl": pnl,
                "win_rate": allocation.win_rate,
                "sharpe": allocation.sharpe
            })
            
            # Decay old performance
            self._decay_performance(strategy)
    
    def _decay_performance(self, strategy: SleeveType) -> None:
        """Decay old performance metrics."""
        if strategy not in self._strategy_performance:
            return
        
        history = list(self._strategy_performance[strategy])
        if len(history) < 10:
            return
        
        weights = np.exp(np.linspace(-1, 0, len(history)))
        weights = weights / weights.sum()
        
        weighted_win_rate = 0.0
        weighted_sharpe = 0.0
        weight_sum = 0.0
        
        for i, entry in enumerate(history):
            age_hours = (datetime.utcnow() - entry["timestamp"]).total_seconds() / 3600
            decay_factor = np.exp(-age_hours / self.performance_decay_hours)
            weight = weights[i] * decay_factor
            
            weighted_win_rate += entry["win_rate"] * weight
            weighted_sharpe += entry["sharpe"] * weight
            weight_sum += weight
        
        if weight_sum > 0:
            with self._strategy_lock:
                if strategy in self._strategy_allocations:
                    self._strategy_allocations[strategy].win_rate = weighted_win_rate / weight_sum
                    self._strategy_allocations[strategy].sharpe = weighted_sharpe / weight_sum
    
    # ============================================
    # CORRELATION TRACKING
    # ============================================
    
    def update_correlation(
        self,
        asset1: str,
        asset2: str,
        correlation: float,
        timestamp: Optional[datetime] = None
    ) -> None:
        """Update correlation between two assets."""
        key = tuple(sorted([asset1, asset2]))
        if key not in self._correlation_history:
            self._correlation_history[key] = deque(maxlen=100)
        
        self._correlation_history[key].append({
            "timestamp": timestamp or datetime.utcnow(),
            "correlation": correlation
        })
        
        recent = [c["correlation"] for c in list(self._correlation_history[key])[-20:]]
        self._correlation_matrix[key] = np.mean(recent)
    
    def get_correlation(self, asset1: str, asset2: str) -> float:
        """Get correlation between two assets."""
        key = tuple(sorted([asset1, asset2]))
        return self._correlation_matrix.get(key, 0.0)
    
    # ============================================
    # ASSET EXPOSURE MANAGEMENT
    # ============================================
    
    def update_asset_exposure(
        self,
        symbol: str,
        asset_class: AssetClass,
        exposure: float,
        pnl: float = 0.0
    ) -> None:
        """Update exposure for an asset."""
        with self._asset_lock:
            if symbol not in self._asset_exposures:
                max_exposure = self.deployable_capital * self.max_asset_exposure_pct
                self._asset_exposures[symbol] = AssetExposure(
                    symbol=symbol,
                    asset_class=asset_class,
                    current_exposure=exposure,
                    max_exposure=max_exposure,
                    pnl=pnl,
                    position_count=0,
                    strategies=[]
                )
            else:
                self._asset_exposures[symbol].current_exposure = exposure
                self._asset_exposures[symbol].pnl = pnl
    
    def get_asset_exposure(self, symbol: str) -> Optional[AssetExposure]:
        """Get exposure for an asset."""
        with self._asset_lock:
            return self._asset_exposures.get(symbol)
    
    def get_total_exposure(self) -> float:
        """Get total portfolio exposure."""
        with self._asset_lock:
            return sum(e.current_exposure for e in self._asset_exposures.values())
    
    def get_exposure_by_class(self, asset_class: AssetClass) -> float:
        """Get total exposure for an asset class."""
        with self._asset_lock:
            return sum(e.current_exposure for e in self._asset_exposures.values() 
                      if e.asset_class == asset_class)
    
    def _get_class_limit(self, asset_class: AssetClass) -> float:
        """Get exposure limit for asset class."""
        limits = {
            AssetClass.CRYPTO: 0.25,
            AssetClass.EQUITY: 0.40,
            AssetClass.ETF: 0.30,
            AssetClass.FUTURE: 0.20
        }
        return limits.get(asset_class, 0.25)
    
    # ============================================
    # PORTFOLIO HEAT MAP (ACTIVE)
    # ============================================
    
    def get_heat_map(self) -> Dict[str, Any]:
        """Get active portfolio heat map."""
        with self._strategy_lock:
            strategy_health = {}
            for strategy, alloc in self._strategy_allocations.items():
                usage_pct = alloc.used_capital / max(alloc.max_capital, 1.0)
                strategy_health[strategy.value] = {
                    "used_capital": alloc.used_capital,
                    "max_capital": alloc.max_capital,
                    "usage_pct": usage_pct,
                    "win_rate": alloc.win_rate,
                    "sharpe": alloc.sharpe,
                    "pnl": alloc.pnl,
                    "risk_score": alloc.risk_score,
                    "health": self._get_health_color(usage_pct, alloc.win_rate, alloc.sharpe)
                }
        
        with self._asset_lock:
            asset_heat = {}
            for symbol, exposure in self._asset_exposures.items():
                usage_pct = exposure.current_exposure / max(exposure.max_exposure, 1.0)
                asset_heat[symbol] = {
                    "asset_class": exposure.asset_class.value,
                    "current_exposure": exposure.current_exposure,
                    "max_exposure": exposure.max_exposure,
                    "usage_pct": usage_pct,
                    "pnl": exposure.pnl,
                    "position_count": exposure.position_count,
                    "strategies": [s.value for s in exposure.strategies],
                    "health": self._get_asset_health_color(usage_pct, exposure.pnl)
                }
        
        total_exposure = self.get_total_exposure()
        total_usage_pct = total_exposure / max(self.deployable_capital, 1.0)
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "mode": self.get_mode().value,
            "total_capital": self.total_capital,
            "cash_reserve": self.total_capital - total_exposure,
            "cash_reserve_pct": (self.total_capital - total_exposure) / self.total_capital,
            "deployable_capital": self.deployable_capital,
            "total_exposure": total_exposure,
            "total_usage_pct": total_usage_pct,
            "heat_multiplier": self.get_heat_multiplier(),
            "is_throttled": total_usage_pct >= 0.70,
            "strategy_health": strategy_health,
            "asset_heat": asset_heat,
            "overall_health": self._get_overall_health(total_usage_pct)
        }
    
    def _get_health_color(self, usage_pct: float, win_rate: float, sharpe: float) -> str:
        """Get health color for a strategy."""
        if usage_pct > 0.9:
            return "red"
        if usage_pct > 0.7:
            return "yellow"
        if win_rate < 0.4 or sharpe < 0.5:
            return "yellow"
        return "green"
    
    def _get_asset_health_color(self, usage_pct: float, pnl: float) -> str:
        """Get health color for an asset."""
        if usage_pct > 0.9:
            return "red"
        if usage_pct > 0.7:
            return "yellow"
        if pnl < -100:
            return "yellow"
        return "green"
    
    def _get_overall_health(self, total_usage_pct: float) -> str:
        """Get overall portfolio health."""
        if total_usage_pct > 0.9:
            return "CRITICAL"
        if total_usage_pct > 0.7:
            return "WARNING"
        return "HEALTHY"
    
    # ============================================
    # DIAGNOSTICS
    # ============================================
    
    def get_status(self) -> Dict[str, Any]:
        """Get governor status."""
        total_exposure = self.get_total_exposure()
        return {
            "mode": self.get_mode().value,
            "total_capital": self.total_capital,
            "cash_reserve": self.total_capital - total_exposure,
            "cash_reserve_pct": (self.total_capital - total_exposure) / self.total_capital,
            "deployable_capital": self.deployable_capital,
            "total_exposure": total_exposure,
            "exposure_pct": total_exposure / max(self.deployable_capital, 1.0),
            "heat_multiplier": self.get_heat_multiplier(),
            "strategy_count": len(self._strategy_allocations),
            "asset_count": len(self._asset_exposures),
            "correlation_pairs": len(self._correlation_matrix)
        }
    
    def get_strategy_allocation(self, strategy: SleeveType) -> Optional[Dict[str, Any]]:
        """Get allocation for a specific strategy."""
        with self._strategy_lock:
            if strategy not in self._strategy_allocations:
                return None
            alloc = self._strategy_allocations[strategy]
            return {
                "strategy": strategy.value,
                "allocated_capital": alloc.allocated_capital,
                "used_capital": alloc.used_capital,
                "available_capital": alloc.allocated_capital - alloc.used_capital,
                "max_capital": alloc.max_capital,
                "usage_pct": alloc.used_capital / max(alloc.max_capital, 1.0),
                "pnl": alloc.pnl,
                "win_rate": alloc.win_rate,
                "sharpe": alloc.sharpe,
                "is_active": alloc.is_active,
                "risk_score": alloc.risk_score
            }
    
    def reset(self) -> None:
        """Reset governor state."""
        with self._strategy_lock:
            for strategy in self._strategy_allocations:
                self._strategy_allocations[strategy].used_capital = 0.0
                self._strategy_allocations[strategy].pnl = 0.0
        
        with self._asset_lock:
            self._asset_exposures.clear()
        
        self._correlation_matrix.clear()
        self._correlation_history.clear()
        self._last_allocation_time.clear()
        self._heat_history.clear()
        
        logger.info("SovereignGovernor reset")