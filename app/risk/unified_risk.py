"""
Unified Risk Authority - Sovereign Risk Consolidation Layer

This file is the single authority for unified risk decisions across the bot.
It consumes risk signals from multiple sources and produces a deterministic,
replay-safe, immutable unified decision.

Role: UNIFICATION / EVALUATION / DECISION
Does NOT own: kill switch, data validation, divergence detection, exposure tracking
Does OWN: consolidated risk evaluation and actionable output production

All methods are deterministic and replay-safe.
No wall-clock dependence — all timestamps are explicit inputs.
All monetary/risk values use Decimal with appropriate precision.
"""

import logging
from decimal import Decimal, getcontext
from typing import Optional, List, Tuple, Dict, Any
from enum import Enum
from dataclasses import dataclass, field

# Decimal precision for risk authority (28 decimal places, sufficient for all calculations)
getcontext().prec = 28

# Import repo-truth contracts where available
from app.models.enums import RiskMode, RegimeType
from app.models.contracts import DivergenceBlock, StaleDataBlock
from app.risk.kill_switch import KillSwitch

logger = logging.getLogger(__name__)


# ============================================
# ENUMS
# ============================================

class UnifiedRiskDecision(str, Enum):
    """
    Unified risk decision output.
    
    HARD_DENY: No trading allowed. Active kill switch, stale data,
               divergence block, or hard flat condition.
    
    DEGRADED_ALLOW: Trading allowed with reduced sizing. Elevated
                    toxicity, unfavorable regime, or high exposure.
    
    FULL_ALLOW: Normal trading. All risk factors nominal.
    """
    HARD_DENY = "hard_deny"
    DEGRADED_ALLOW = "degraded_allow"
    FULL_ALLOW = "full_allow"


# ============================================
# IMMUTABLE RESULT CONTRACT
# ============================================

@dataclass(frozen=True)
class UnifiedRiskResult:
    """
    Immutable unified risk decision result.
    
    This is the governing output consumed by downstream systems
    (execution engine, strategy router, position sizing).
    
    All Decimal fields are quantized to appropriate precision:
    - sizing_multiplier: 4 decimal places (0.0001 precision)
    """
    decision: UnifiedRiskDecision
    allowed: bool
    sizing_multiplier: Decimal
    risk_mode: RiskMode
    reason: str
    provenance: Dict[str, Any] = field(default_factory=dict)
    timestamp_ns: int = 0
    
    def __post_init__(self):
        """Validate and quantize Decimal fields."""
        # Quantize sizing_multiplier to 4 decimal places
        if isinstance(self.sizing_multiplier, Decimal):
            quantized = self.sizing_multiplier.quantize(Decimal('0.0001'))
            object.__setattr__(self, 'sizing_multiplier', quantized)
        
        # Validate bounds
        if self.sizing_multiplier < Decimal('0') or self.sizing_multiplier > Decimal('1'):
            raise ValueError(f"sizing_multiplier must be in [0,1], got {self.sizing_multiplier}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for persistence/audit."""
        return {
            "decision": self.decision.value,
            "allowed": self.allowed,
            "sizing_multiplier": str(self.sizing_multiplier),
            "risk_mode": self.risk_mode.value if hasattr(self.risk_mode, 'value') else str(self.risk_mode),
            "reason": self.reason,
            "provenance": self.provenance,
            "timestamp_ns": self.timestamp_ns
        }


# ============================================
# UNIFIED RISK AUTHORITY
# ============================================

class UnifiedRiskAuthority:
    """
    Sovereign Unified Risk Authority.
    
    Consumes risk signals from multiple sources and produces a single,
    deterministic, replay-safe unified risk decision.
    
    Precedence order (highest to lowest):
    1. Kill switch active → HARD_DENY
    2. Hard flat override → HARD_DENY
    3. Stale data block (per-symbol) → HARD_DENY
    4. Divergence block (per-symbol) → HARD_DENY
    5. Extreme toxicity → HARD_DENY
    6. Extreme exposure → HARD_DENY
    7. Elevated toxicity → DEGRADED_ALLOW (reduced sizing)
    8. Elevated exposure → DEGRADED_ALLOW (reduced sizing)
    9. Unfavorable regime → DEGRADED_ALLOW (reduced sizing)
    10. All nominal → FULL_ALLOW
    
    All thresholds use Decimal for deterministic comparison.
    """
    
    # Default thresholds as Decimal
    DEFAULT_TOXICITY_HARD_DENY: Decimal = Decimal('0.9')
    DEFAULT_TOXICITY_DEGRADE: Decimal = Decimal('0.7')
    DEFAULT_EXPOSURE_HARD_DENY: Decimal = Decimal('0.95')
    DEFAULT_EXPOSURE_DEGRADE: Decimal = Decimal('0.8')
    DEFAULT_CRISIS_MULTIPLIER: Decimal = Decimal('0.3')
    DEFAULT_UNKNOWN_REGIME_MULTIPLIER: Decimal = Decimal('0.5')
    
    def __init__(
        self,
        toxicity_hard_deny_threshold: Decimal = DEFAULT_TOXICITY_HARD_DENY,
        toxicity_degrade_threshold: Decimal = DEFAULT_TOXICITY_DEGRADE,
        exposure_hard_deny_threshold: Decimal = DEFAULT_EXPOSURE_HARD_DENY,
        exposure_degrade_threshold: Decimal = DEFAULT_EXPOSURE_DEGRADE,
        crisis_multiplier: Decimal = DEFAULT_CRISIS_MULTIPLIER,
        unknown_regime_multiplier: Decimal = DEFAULT_UNKNOWN_REGIME_MULTIPLIER
    ):
        """
        Initialize unified risk authority with Decimal thresholds.
        
        Args:
            toxicity_hard_deny_threshold: Toxicity score above this blocks trading
            toxicity_degrade_threshold: Toxicity score above this reduces sizing
            exposure_hard_deny_threshold: Exposure % above this blocks trading
            exposure_degrade_threshold: Exposure % above this reduces sizing
            crisis_multiplier: Sizing multiplier during CRISIS regime
            unknown_regime_multiplier: Sizing multiplier during UNKNOWN regime
        """
        # Validate thresholds are in [0,1]
        for name, val in [
            ("toxicity_hard_deny_threshold", toxicity_hard_deny_threshold),
            ("toxicity_degrade_threshold", toxicity_degrade_threshold),
            ("exposure_hard_deny_threshold", exposure_hard_deny_threshold),
            ("exposure_degrade_threshold", exposure_degrade_threshold),
            ("crisis_multiplier", crisis_multiplier),
            ("unknown_regime_multiplier", unknown_regime_multiplier)
        ]:
            if val < Decimal('0') or val > Decimal('1'):
                raise ValueError(f"{name} must be in [0,1], got {val}")
        
        self.toxicity_hard_deny_threshold = toxicity_hard_deny_threshold
        self.toxicity_degrade_threshold = toxicity_degrade_threshold
        self.exposure_hard_deny_threshold = exposure_hard_deny_threshold
        self.exposure_degrade_threshold = exposure_degrade_threshold
        self.crisis_multiplier = crisis_multiplier
        self.unknown_regime_multiplier = unknown_regime_multiplier
        
        logger.info(
            f"UnifiedRiskAuthority initialized: "
            f"toxicity_hard_deny={toxicity_hard_deny_threshold}, "
            f"toxicity_degrade={toxicity_degrade_threshold}, "
            f"exposure_hard_deny={exposure_hard_deny_threshold}, "
            f"exposure_degrade={exposure_degrade_threshold}, "
            f"crisis_multiplier={crisis_multiplier}"
        )
    
    # ============================================
    # MAIN EVALUATION METHOD (SINGLE AUTHORITY PATH)
    # ============================================
    
    def evaluate(
        self,
        timestamp_ns: int,
        kill_switch: KillSwitch,
        stale_data_blocks: List[StaleDataBlock],
        divergence_blocks: List[DivergenceBlock],
        hard_flat_triggered: bool = False,
        regime: RegimeType = RegimeType.UNKNOWN,
        toxicity_score: Decimal = Decimal('0'),
        current_exposure_pct: Decimal = Decimal('0'),
        symbol: Optional[str] = None
    ) -> UnifiedRiskResult:
        """
        Evaluate all risk factors and produce unified decision.
        
        This is the SINGLE GOVERNING AUTHORITY PATH.
        All risk evaluation passes through this method.
        
        Args:
            timestamp_ns: Current timestamp (nanoseconds) for replay-safe evaluation
            kill_switch: Kill switch instance (state queried internally)
            stale_data_blocks: List of active stale data blocks from RiskTruth
            divergence_blocks: List of active divergence blocks from RiskTruth
            hard_flat_triggered: Whether hard flat mode is active
            regime: Current market regime from RegimeDetector
            toxicity_score: Current toxicity score (0-1) from ToxicityEngine
            current_exposure_pct: Current portfolio exposure as percentage (0-1)
            symbol: Optional symbol for per-symbol block checking
        
        Returns:
            UnifiedRiskResult with immutable decision and full provenance
        """
        # Validate inputs
        if timestamp_ns <= 0:
            raise ValueError(f"timestamp_ns must be positive, got {timestamp_ns}")
        
        if toxicity_score < Decimal('0') or toxicity_score > Decimal('1'):
            raise ValueError(f"toxicity_score must be in [0,1], got {toxicity_score}")
        
        if current_exposure_pct < Decimal('0') or current_exposure_pct > Decimal('1'):
            raise ValueError(f"current_exposure_pct must be in [0,1], got {current_exposure_pct}")
        
        # Query kill switch state
        kill_switch_state = kill_switch.get_state()
        kill_switch_is_killed = kill_switch.is_killed(timestamp_ns)
        
        # Build provenance for audit
        provenance: Dict[str, Any] = {
            "timestamp_ns": timestamp_ns,
            "kill_switch_state": kill_switch_state.value if hasattr(kill_switch_state, 'value') else str(kill_switch_state),
            "kill_switch_is_killed": kill_switch_is_killed,
            "stale_data_blocks_count": len(stale_data_blocks),
            "divergence_blocks_count": len(divergence_blocks),
            "hard_flat_triggered": hard_flat_triggered,
            "regime": regime.value if hasattr(regime, 'value') else str(regime),
            "toxicity_score": str(toxicity_score),
            "current_exposure_pct": str(current_exposure_pct),
            "symbol": symbol
        }
        
        reasons: List[str] = []
        sizing_multiplier = Decimal('1')
        risk_mode = RiskMode.NORMAL
        
        # ============================================
        # LEVEL 1: HARD DENY CONDITIONS (Highest Precedence)
        # ============================================
        
        # 1. Kill switch active
        if kill_switch_is_killed:
            reason = f"kill_switch_active: state={kill_switch_state.value if hasattr(kill_switch_state, 'value') else kill_switch_state}"
            reasons.append(reason)
            provenance["kill_switch_blocked"] = True
            provenance["kill_switch_cooldown_remaining_ns"] = kill_switch.get_cooldown_remaining_ns(timestamp_ns)
            
            return UnifiedRiskResult(
                decision=UnifiedRiskDecision.HARD_DENY,
                allowed=False,
                sizing_multiplier=Decimal('0'),
                risk_mode=RiskMode.HARD_FLAT,
                reason=" | ".join(reasons),
                provenance=provenance,
                timestamp_ns=timestamp_ns
            )
        
        # 2. Hard flat override
        if hard_flat_triggered:
            reasons.append("hard_flat_override_active")
            provenance["hard_flat_blocked"] = True
            
            return UnifiedRiskResult(
                decision=UnifiedRiskDecision.HARD_DENY,
                allowed=False,
                sizing_multiplier=Decimal('0'),
                risk_mode=RiskMode.HARD_FLAT,
                reason=" | ".join(reasons),
                provenance=provenance,
                timestamp_ns=timestamp_ns
            )
        
        # 3. Stale data block for symbol (if symbol provided)
        if symbol:
            for block in stale_data_blocks:
                if block.symbol == symbol:
                    blocked_until_ns = getattr(block, 'blocked_until_ns', 0)
                    reasons.append(f"stale_data_block: {symbol} until {blocked_until_ns}")
                    provenance["stale_data_blocked"] = True
                    provenance["stale_data_block_until_ns"] = blocked_until_ns
                    
                    return UnifiedRiskResult(
                        decision=UnifiedRiskDecision.HARD_DENY,
                        allowed=False,
                        sizing_multiplier=Decimal('0'),
                        risk_mode=RiskMode.SAFE_MODE,
                        reason=" | ".join(reasons),
                        provenance=provenance,
                        timestamp_ns=timestamp_ns
                    )
        
        # 4. Divergence block for symbol (if symbol provided)
        if symbol:
            for block in divergence_blocks:
                if block.symbol == symbol:
                    divergence_type = getattr(block, 'divergence_type', 'unknown')
                    blocked_until_ns = getattr(block, 'blocked_until_ns', 0)
                    reasons.append(f"divergence_block: {symbol} ({divergence_type}) until {blocked_until_ns}")
                    provenance["divergence_blocked"] = True
                    provenance["divergence_type"] = divergence_type
                    provenance["divergence_block_until_ns"] = blocked_until_ns
                    
                    return UnifiedRiskResult(
                        decision=UnifiedRiskDecision.HARD_DENY,
                        allowed=False,
                        sizing_multiplier=Decimal('0'),
                        risk_mode=RiskMode.SAFE_MODE,
                        reason=" | ".join(reasons),
                        provenance=provenance,
                        timestamp_ns=timestamp_ns
                    )
        
        # 5. Extreme toxicity
        if toxicity_score >= self.toxicity_hard_deny_threshold:
            reasons.append(f"extreme_toxicity: {toxicity_score} >= {self.toxicity_hard_deny_threshold}")
            provenance["extreme_toxicity_blocked"] = True
            provenance["toxicity_score"] = str(toxicity_score)
            
            return UnifiedRiskResult(
                decision=UnifiedRiskDecision.HARD_DENY,
                allowed=False,
                sizing_multiplier=Decimal('0'),
                risk_mode=RiskMode.SAFE_MODE,
                reason=" | ".join(reasons),
                provenance=provenance,
                timestamp_ns=timestamp_ns
            )
        
        # 6. Extreme exposure
        if current_exposure_pct >= self.exposure_hard_deny_threshold:
            reasons.append(f"extreme_exposure: {current_exposure_pct:.1%} >= {self.exposure_hard_deny_threshold:.0%}")
            provenance["extreme_exposure_blocked"] = True
            provenance["current_exposure_pct"] = str(current_exposure_pct)
            
            return UnifiedRiskResult(
                decision=UnifiedRiskDecision.HARD_DENY,
                allowed=False,
                sizing_multiplier=Decimal('0'),
                risk_mode=RiskMode.SAFE_MODE,
                reason=" | ".join(reasons),
                provenance=provenance,
                timestamp_ns=timestamp_ns
            )
        
        # ============================================
        # LEVEL 2: DEGRADED ALLOW CONDITIONS
        # ============================================
        
        risk_mode = RiskMode.NORMAL
        
        # 1. Elevated toxicity (progressive scaling)
        if toxicity_score >= self.toxicity_degrade_threshold:
            reasons.append(f"elevated_toxicity: {toxicity_score} >= {self.toxicity_degrade_threshold}")
            provenance["toxicity_degraded"] = True
            
            # Progressive scaling based on how far above degrade threshold
            # Pure Decimal arithmetic: factor = 1 - (score - degrade) / (hard_deny - degrade)
            t_range = self.toxicity_hard_deny_threshold - self.toxicity_degrade_threshold
            if t_range > Decimal('0'):
                t_above = toxicity_score - self.toxicity_degrade_threshold
                t_ratio = t_above / t_range
                # Clamp to [0,1] and apply inverse scaling
                if t_ratio > Decimal('1'):
                    t_ratio = Decimal('1')
                if t_ratio < Decimal('0'):
                    t_ratio = Decimal('0')
                t_factor = Decimal('1') - t_ratio
                sizing_multiplier = min(sizing_multiplier, t_factor)
            else:
                sizing_multiplier = min(sizing_multiplier, Decimal('0.5'))
            
            risk_mode = RiskMode.SAFE_MODE
            provenance["toxicity_factor"] = str(sizing_multiplier)
        
        # 2. Elevated exposure (progressive scaling - fully Decimal-native)
        if current_exposure_pct >= self.exposure_degrade_threshold:
            reasons.append(f"elevated_exposure: {current_exposure_pct:.1%} >= {self.exposure_degrade_threshold:.0%}")
            provenance["exposure_degraded"] = True
            
            # Progressive scaling using pure Decimal arithmetic
            # Piecewise linear scaling with increasing penalty as exposure rises:
            #   80% = 0.8x, 85% = 0.7x, 90% = 0.5x, 94% = 0.2x, 95% = 0.0x
            e_range = self.exposure_hard_deny_threshold - self.exposure_degrade_threshold
            if e_range > Decimal('0'):
                e_above = current_exposure_pct - self.exposure_degrade_threshold
                e_ratio = e_above / e_range
                # Clamp to [0,1]
                if e_ratio > Decimal('1'):
                    e_ratio = Decimal('1')
                if e_ratio < Decimal('0'):
                    e_ratio = Decimal('0')
                
                # Quadratic decay: factor = 1 - 0.8 * (ratio^2)
                # This is more conservative than linear, punishing high exposure faster
                # All Decimal: ratio^2 = ratio * ratio
                ratio_squared = e_ratio * e_ratio
                e_factor = Decimal('1') - (Decimal('0.8') * ratio_squared)
                if e_factor < Decimal('0'):
                    e_factor = Decimal('0')
                sizing_multiplier = min(sizing_multiplier, e_factor)
            else:
                sizing_multiplier = min(sizing_multiplier, Decimal('0.5'))
            
            risk_mode = RiskMode.SAFE_MODE
            provenance["exposure_factor"] = str(sizing_multiplier)
        
        # 3. Unfavorable regime
        if regime == RegimeType.CRISIS:
            reasons.append(f"unfavorable_regime: CRISIS")
            sizing_multiplier = min(sizing_multiplier, self.crisis_multiplier)
            risk_mode = RiskMode.SAFE_MODE
            provenance["regime_degraded"] = True
            provenance["regime_multiplier"] = str(self.crisis_multiplier)
        elif regime == RegimeType.UNKNOWN:
            reasons.append(f"unfavorable_regime: UNKNOWN")
            sizing_multiplier = min(sizing_multiplier, self.unknown_regime_multiplier)
            risk_mode = RiskMode.SAFE_MODE
            provenance["regime_degraded"] = True
            provenance["regime_multiplier"] = str(self.unknown_regime_multiplier)
        
        # ============================================
        # LEVEL 3: DETERMINE FINAL DECISION
        # ============================================
        
        if not reasons:
            # No degrading conditions
            return UnifiedRiskResult(
                decision=UnifiedRiskDecision.FULL_ALLOW,
                allowed=True,
                sizing_multiplier=Decimal('1'),
                risk_mode=RiskMode.NORMAL,
                reason="all_risk_factors_nominal",
                provenance=provenance,
                timestamp_ns=timestamp_ns
            )
        
        # Degraded allow with at least one condition
        # Ensure sizing_multiplier is not negative
        if sizing_multiplier < Decimal('0'):
            sizing_multiplier = Decimal('0')
        
        return UnifiedRiskResult(
            decision=UnifiedRiskDecision.DEGRADED_ALLOW,
            allowed=True,
            sizing_multiplier=sizing_multiplier,
            risk_mode=risk_mode,
            reason=" | ".join(reasons),
            provenance=provenance,
            timestamp_ns=timestamp_ns
        )
    
    # ============================================
    # CONVENIENCE METHODS (NON-AUTHORITY PATHS)
    # ============================================
    
    def evaluate_for_symbol(
        self,
        timestamp_ns: int,
        kill_switch: KillSwitch,
        stale_data_blocks: List[StaleDataBlock],
        divergence_blocks: List[DivergenceBlock],
        symbol: str,
        hard_flat_triggered: bool = False,
        regime: RegimeType = RegimeType.UNKNOWN,
        toxicity_score: Decimal = Decimal('0'),
        current_exposure_pct: Decimal = Decimal('0')
    ) -> UnifiedRiskResult:
        """
        Evaluate risk for a specific symbol.
        
        This is a convenience wrapper around evaluate() that passes the symbol
        for per-symbol block checking. It uses the SAME authority path.
        """
        return self.evaluate(
            timestamp_ns=timestamp_ns,
            kill_switch=kill_switch,
            stale_data_blocks=stale_data_blocks,
            divergence_blocks=divergence_blocks,
            hard_flat_triggered=hard_flat_triggered,
            regime=regime,
            toxicity_score=toxicity_score,
            current_exposure_pct=current_exposure_pct,
            symbol=symbol
        )
    
    def quick_check(
        self,
        timestamp_ns: int,
        kill_switch: KillSwitch,
        hard_flat_triggered: bool = False,
        symbol: Optional[str] = None,
        stale_data_blocks: Optional[List[StaleDataBlock]] = None,
        divergence_blocks: Optional[List[DivergenceBlock]] = None
    ) -> Tuple[bool, str]:
        """
        Quick check if trading should be allowed.
        
        This is a LIGHTWEIGHT CONVENIENCE method for hot-path checks.
        It does NOT replace the full evaluate() authority.
        For production decisions, use evaluate().
        
        Args:
            timestamp_ns: Current timestamp
            kill_switch: Kill switch instance
            hard_flat_triggered: Whether hard flat mode is active
            symbol: Optional symbol for per-symbol block checking
            stale_data_blocks: List of stale data blocks
            divergence_blocks: List of divergence blocks
        
        Returns:
            Tuple of (allowed, reason)
        """
        if kill_switch.is_killed(timestamp_ns):
            state = kill_switch.get_state()
            return False, f"kill_switch_active: {state.value if hasattr(state, 'value') else state}"
        
        if hard_flat_triggered:
            return False, "hard_flat_override_active"
        
        if symbol and stale_data_blocks:
            for block in stale_data_blocks:
                if block.symbol == symbol:
                    return False, f"stale_data_block: {symbol}"
        
        if symbol and divergence_blocks:
            for block in divergence_blocks:
                if block.symbol == symbol:
                    return False, f"divergence_block: {symbol}"
        
        return True, "ok"


# ============================================
# CONVENIENCE FACTORY FUNCTION
# ============================================

def create_unified_risk_authority(
    toxicity_hard_deny_threshold: Decimal = Decimal('0.9'),
    toxicity_degrade_threshold: Decimal = Decimal('0.7'),
    exposure_hard_deny_threshold: Decimal = Decimal('0.95'),
    exposure_degrade_threshold: Decimal = Decimal('0.8'),
    crisis_multiplier: Decimal = Decimal('0.3'),
    unknown_regime_multiplier: Decimal = Decimal('0.5')
) -> UnifiedRiskAuthority:
    """
    Create a configured unified risk authority.
    
    All thresholds are Decimal for deterministic comparison.
    
    Args:
        toxicity_hard_deny_threshold: Toxicity score above this blocks trading
        toxicity_degrade_threshold: Toxicity score above this reduces sizing
        exposure_hard_deny_threshold: Exposure % above this blocks trading
        exposure_degrade_threshold: Exposure % above this reduces sizing
        crisis_multiplier: Sizing multiplier during CRISIS regime
        unknown_regime_multiplier: Sizing multiplier during UNKNOWN regime
    
    Returns:
        Configured UnifiedRiskAuthority instance
    """
    return UnifiedRiskAuthority(
        toxicity_hard_deny_threshold=toxicity_hard_deny_threshold,
        toxicity_degrade_threshold=toxicity_degrade_threshold,
        exposure_hard_deny_threshold=exposure_hard_deny_threshold,
        exposure_degrade_threshold=exposure_degrade_threshold,
        crisis_multiplier=crisis_multiplier,
        unknown_regime_multiplier=unknown_regime_multiplier
    )


__all__ = [
    'UnifiedRiskDecision',
    'UnifiedRiskResult',
    'UnifiedRiskAuthority',
    'create_unified_risk_authority',
]