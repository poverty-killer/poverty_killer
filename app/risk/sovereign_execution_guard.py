"""
Sovereign Execution Guard (SEG)
Authority: Sovereign Capital Doctrine v1.0 / Narrow Hardened Edition
Integrity: Strict Decimal implementation for deterministic monetary truth.
Purpose: Apex Predator global risk governor. Evaluates environment, state, 
and setup asymmetry before authorizing capital allocation.

Core Boundaries:
- Floor Ratchet is strictly governed by Cumulative Realized PnL.
- Aggression State is strictly governed by Live Equity (Distance-to-Floor).
- Risk Capital is strictly partitioned via Active Risk Base logic.

Observability Boundary:
- Audit timestamps (UTC/wall-clock) are strictly for forensic observability. 
  They are non-authoritative metadata and play ZERO role in sovereign decision law, 
  state transitions, or risk sizing.
"""

from enum import Enum
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN, getcontext
from typing import List, Dict, Optional, Set, Any
from collections import deque
from datetime import datetime, timezone

# Establish absolute precision for sovereign monetary calculations
getcontext().prec = 28

class AggressionState(Enum):
    HUNT = "HUNT"
    PRESSURED = "PRESSURED"
    DEFENSIVE = "DEFENSIVE"
    PRESERVATION = "PRESERVATION"
    FLOOR_LOCK = "FLOOR_LOCK"

class HaltState(Enum):
    ACTIVE = "ACTIVE"
    SOFT_KILL = "SOFT_KILL"         # Diminished aggression, restricts sleeves
    HARD_KILL = "HARD_KILL"         # No entries, day lock
    FORTRESS_HALT = "FORTRESS_HALT" # Fatal survival floor breached, requires manual re-arm

class ConvictionLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EXCEPTIONAL = "EXCEPTIONAL"

class SleeveTier(Enum):
    ALPHA = "ALPHA"     # Highest trust, fortress-grade
    BETA = "BETA"       # Standard directional
    GAMMA = "GAMMA"     # Mean reversion, higher convexity
    OMEGA = "OMEGA"     # Experimental / highly situational

@dataclass(frozen=True)
class SovereignGovernancePolicy:
    """Immutable policy tables extracting doctrine from operational logic."""
    
    # State Multipliers
    state_aggression_multiplier: Dict[AggressionState, Decimal] = field(default_factory=lambda: {
        AggressionState.HUNT: Decimal('1.00'),
        AggressionState.PRESSURED: Decimal('0.70'),
        AggressionState.DEFENSIVE: Decimal('0.40'),
        AggressionState.PRESERVATION: Decimal('0.15'),
        AggressionState.FLOOR_LOCK: Decimal('0.00')
    })
    
    # Toxicity Ceilings
    state_toxicity_limit: Dict[AggressionState, Decimal] = field(default_factory=lambda: {
        AggressionState.HUNT: Decimal('0.85'),
        AggressionState.PRESSURED: Decimal('0.75'),
        AggressionState.DEFENSIVE: Decimal('0.50'),
        AggressionState.PRESERVATION: Decimal('0.30'),
        AggressionState.FLOOR_LOCK: Decimal('0.00')
    })

    # Base Risk Mapping (Fraction of Active Risk Base)
    conviction_risk_fraction: Dict[ConvictionLevel, Decimal] = field(default_factory=lambda: {
        ConvictionLevel.LOW: Decimal('0.05'),
        ConvictionLevel.MEDIUM: Decimal('0.10'),
        ConvictionLevel.HIGH: Decimal('0.15'),
        ConvictionLevel.EXCEPTIONAL: Decimal('0.20')
    })

    # Pyramiding Ladder (Unit index -> Multiplier)
    pyramid_ladder: Dict[int, Decimal] = field(default_factory=lambda: {
        0: Decimal('1.00'),   # First unit
        1: Decimal('0.50'),   # Second unit
        2: Decimal('0.25')    # Third unit
    })

    # Hard Asymmetry Constraints
    min_asymmetry_base: Decimal = Decimal('2.50')
    min_asymmetry_recovery: Decimal = Decimal('3.00')

@dataclass(frozen=True)
class SleeveMetadata:
    """Cryptographic-style capability registration for strategy sleeves."""
    sleeve_id: str
    tier: SleeveTier
    fortress_grade: bool
    pyramid_allowed: bool
    allowed_states: Set[AggressionState]

@dataclass(frozen=True)
class TradeSetup:
    """
    Rich, strictly typed packet required for authorization requests.
    Validates its own mathematical bounds before the Governor processes it.
    Fields like regime_snapshot and specific BPS metrics are captured into the 
    forensic audit ledger, ensuring exact authorization context is preserved.
    """
    sleeve_id: str
    direction: int                      # 1 for Long, -1 for Short
    expected_r_multiple: Decimal
    expected_move_bps: Decimal
    stop_distance_bps: Decimal
    target_distance_bps: Decimal
    toxicity_score: Decimal             # 0.0 to 1.0
    regime_snapshot: str                # e.g., "HIGH_VOL_EXPANSION"
    conviction: ConvictionLevel
    is_pyramid_unit: bool
    existing_units: int

    def __post_init__(self):
        """Deterministically defends the contract boundary before entry into decision law."""
        if self.direction not in (1, -1):
            raise ValueError("Direction must be 1 (Long) or -1 (Short)")
        if not (Decimal('0') <= self.toxicity_score <= Decimal('1')):
            raise ValueError(f"Toxicity score {self.toxicity_score} must be between 0.0 and 1.0")
        if self.expected_r_multiple < Decimal('0'):
            raise ValueError("Expected R-multiple cannot be negative")
        if self.stop_distance_bps <= Decimal('0') or self.target_distance_bps <= Decimal('0'):
            raise ValueError("Stop and Target distances must be strictly positive")
        if self.expected_move_bps < self.target_distance_bps:
            raise ValueError("Expected move BPS logically cannot be less than target distance BPS")
        if self.is_pyramid_unit and self.existing_units < 1:
            raise ValueError("Pyramid unit flag is True, but existing_units is < 1")
        if not self.is_pyramid_unit and self.existing_units != 0:
            raise ValueError("Pyramid unit flag is False, but existing_units != 0")

@dataclass(frozen=True)
class AuthorizationReceipt:
    """Deterministic, immutable proof of authorization state and limits."""
    is_authorized: bool
    authorized_risk_usd: Decimal
    rejection_reason: str
    aggression_state: AggressionState
    halt_state: HaltState
    recovery_mode: bool
    active_risk_base: Decimal
    multiplier_stack_summary: Dict[str, str]

@dataclass(frozen=True)
class AuditRecord:
    """Bounded transition log entry."""
    timestamp: str  # Observability metadata only; non-governing
    event_type: str
    old_value: str
    new_value: str
    reason: str
    metadata: Dict[str, Any]

@dataclass
class DynamicRiskState:
    """Snapshot of total sovereign capital state."""
    initial_capital: Decimal
    live_equity: Decimal
    cumulative_realized_pnl: Decimal
    high_water_mark: Decimal
    locked_floor: Decimal
    predator_capital: Decimal
    active_risk_base: Decimal
    floor_distance: Decimal
    floor_distance_pct: Decimal
    aggression_state: AggressionState
    recovery_mode: bool
    daily_realized_pnl: Decimal
    rolling_5_trade_pnl: Decimal
    consecutive_losses: int
    halt_state: HaltState
    authorized_sleeves: List[str]


class SovereignExecutionGuard:
    def __init__(self, initial_capital: float = 20000.0, absolute_survival_floor: float = 17500.0):
        # 1. Doctrine Policies
        self.policy = SovereignGovernancePolicy()
        
        # 2. Core Capital (Decimal Conversion for Absolute Truth)
        self.initial_capital = Decimal(str(initial_capital))
        self.absolute_survival_floor = Decimal(str(absolute_survival_floor))
        
        # 3. Persistent Realized Tracking (Controls Floor)
        self.cumulative_realized_pnl = Decimal('0.00')
        self.locked_floor = self.initial_capital
        self.high_water_mark = self.initial_capital
        
        # 4. Ephemeral Live Tracking (Controls State)
        self.live_equity = self.initial_capital
        
        # 5. Session / Day Tracking
        self.daily_realized_pnl = Decimal('0.00')
        self.consecutive_losses = 0
        self.recent_trade_history: deque = deque(maxlen=5)
        
        # 6. Lifecycle States
        self.current_state = AggressionState.FLOOR_LOCK
        self.halt_state = HaltState.ACTIVE
        self.recovery_mode = False
        
        # 7. Registries and Audit Ledgers
        self.registered_sleeves: Dict[str, SleeveMetadata] = {}
        self.audit_ledger: deque = deque(maxlen=1000)

        self._log_audit("INITIALIZATION", "NONE", "ACTIVE", "Guard Booted", {"capital": str(self.initial_capital)})

    # ==========================================
    # LIFECYCLE & REGISTRATION MANAGEMENT
    # ==========================================

    def register_sleeve(self, metadata: SleeveMetadata) -> None:
        """Registers an available strategy sleeve with its capability metadata."""
        self.registered_sleeves[metadata.sleeve_id] = metadata
        self._log_audit("SLEEVE_REGISTERED", "NONE", metadata.sleeve_id, "Sleeve mounted", {"tier": metadata.tier.value})

    def start_new_session(self, current_live_equity: float) -> None:
        """
        Lawful session reset. 
        Clears ephemeral daily counters (Daily PnL drops to 0, which clears HARD_KILL).
        Consecutive losses PERSIST across sessions. Therefore, SOFT_KILL will dynamically 
        persist if consecutive losses remain >= 3.
        """
        if self.halt_state == HaltState.FORTRESS_HALT:
            self._log_audit("SESSION_START_REJECTED", "N/A", "FORTRESS_HALT", "Cannot start session while in Fortress Halt", {})
            return

        old_halt = self.halt_state
        self.daily_realized_pnl = Decimal('0.00')
        self.live_equity = Decimal(str(current_live_equity))
        
        # Explicit re-evaluation ensures SOFT_KILL persists if driven by consecutive losses,
        # but clears if it was solely driven by the previous session's daily loss pct.
        self._evaluate_halt_ladder()
        
        self._log_audit("SESSION_STARTED", old_halt.value, self.halt_state.value, "New session initialized, daily PnL reset", {"consec_losses": self.consecutive_losses, "equity": str(self.live_equity)})

    def manual_rearm(self, current_live_equity: float, rearm_reason: str) -> None:
        """The only lawful way to escape a Fortress Halt."""
        if self.halt_state != HaltState.FORTRESS_HALT:
            return
            
        old_state = self.halt_state.value
        self.halt_state = HaltState.ACTIVE
        self.live_equity = Decimal(str(current_live_equity))
        
        # Re-arm forces a structural recalibration of HWM to prevent instant recovery mode locking
        self.high_water_mark = self.live_equity
        
        self.update_live_equity(current_live_equity)
        self._log_audit("MANUAL_REARM", old_state, "ACTIVE", rearm_reason, {"new_equity": str(self.live_equity)})

    def _log_audit(self, event_type: str, old_val: str, new_val: str, reason: str, meta: Dict[str, Any]) -> None:
        """
        Internal bounded ledger for sovereign audit trails.
        The timestamp is strictly for forensic observability, not sovereign governance.
        """
        record = AuditRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            old_value=old_val,
            new_value=new_val,
            reason=reason,
            metadata=meta
        )
        self.audit_ledger.append(record)

    # ==========================================
    # CORE MONEY DOCTRINE (STATE TRANSITIONS)
    # ==========================================

    def register_trade_result(self, realized_pnl_usd: float) -> None:
        """
        Transition triggered ONLY when a trade fully closes.
        This governs Floor Ratchets and Cumulative Risk Tracking.
        """
        pnl_dec = Decimal(str(realized_pnl_usd))
        
        # 1. Update Accumulators
        self.cumulative_realized_pnl += pnl_dec
        self.daily_realized_pnl += pnl_dec
        self.recent_trade_history.append(pnl_dec)
        
        if pnl_dec < Decimal('0'):
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        # 2. Floor Ratchet Logic (Doctrine 4)
        if self.cumulative_realized_pnl > Decimal('0'):
            tier1_cap = Decimal('5000.00')
            tier2_cap = Decimal('10000.00')
            
            tier1 = min(self.cumulative_realized_pnl, tier1_cap) * Decimal('0.25')
            tier2 = max(Decimal('0'), min(self.cumulative_realized_pnl - tier1_cap, tier2_cap)) * Decimal('0.40')
            tier3 = max(Decimal('0'), self.cumulative_realized_pnl - (tier1_cap + tier2_cap)) * Decimal('0.55')
            
            calculated_floor = self.initial_capital + tier1 + tier2 + tier3
            
            if calculated_floor > self.locked_floor:
                old_floor = self.locked_floor
                self.locked_floor = calculated_floor
                self._log_audit("FLOOR_RATCHET", str(old_floor), str(self.locked_floor), "Realized PnL tier threshold breached", {"cumulative_pnl": str(self.cumulative_realized_pnl)})

    def update_live_equity(self, current_live_equity: float) -> DynamicRiskState:
        """
        Transition triggered on equity updates.
        This governs Aggression States, Distance-to-Floor, and Halt Ladders.
        """
        self.live_equity = Decimal(str(current_live_equity))
        
        # High-Water Mark (Doctrine 5)
        if self.live_equity > self.high_water_mark:
            self.high_water_mark = self.live_equity

        # Recovery Mode (Doctrine 14)
        old_recovery = self.recovery_mode
        if self.live_equity <= (self.high_water_mark * Decimal('0.93')):
            self.recovery_mode = True
        elif self.live_equity >= (self.high_water_mark * Decimal('0.97')):
            self.recovery_mode = False
            
        if old_recovery != self.recovery_mode:
            self._log_audit("RECOVERY_MODE_TOGGLE", str(old_recovery), str(self.recovery_mode), "HWM threshold crossed", {"equity": str(self.live_equity), "hwm": str(self.high_water_mark)})

        # Absolute Survival (Doctrine 3)
        if self.live_equity <= self.absolute_survival_floor and self.halt_state != HaltState.FORTRESS_HALT:
            self.halt_state = HaltState.FORTRESS_HALT
            self._set_aggression_state(AggressionState.FLOOR_LOCK, "Absolute Survival Breached")
            return self.get_state()

        # Distance to Floor & Aggression States (Doctrine 7)
        floor_distance = self.live_equity - self.locked_floor
        
        if floor_distance <= Decimal('0'):
            self._set_aggression_state(AggressionState.FLOOR_LOCK, "Equity at or below locked floor")
        else:
            floor_distance_pct = floor_distance / self.live_equity
            
            if floor_distance_pct >= Decimal('0.12'):
                new_state = AggressionState.HUNT
            elif floor_distance_pct >= Decimal('0.08'):
                new_state = AggressionState.PRESSURED
            elif floor_distance_pct >= Decimal('0.04'):
                new_state = AggressionState.DEFENSIVE
            elif floor_distance_pct >= Decimal('0.02'):
                new_state = AggressionState.PRESERVATION
            else:
                new_state = AggressionState.FLOOR_LOCK
                
            self._set_aggression_state(new_state, f"D% updated to {floor_distance_pct:.4f}")

        self._evaluate_halt_ladder()
        return self.get_state()

    def _set_aggression_state(self, new_state: AggressionState, reason: str) -> None:
        if self.current_state != new_state:
            old_state = self.current_state
            self.current_state = new_state
            self._log_audit("STATE_CHANGE", old_state.value, new_state.value, reason, {})

    def _evaluate_halt_ladder(self) -> None:
        """Doctrine 15: Sovereign Halt Ladder (Excludes Fortress Halt override)"""
        if self.halt_state == HaltState.FORTRESS_HALT or self.live_equity == Decimal('0'):
            return
            
        daily_loss_pct = abs(min(Decimal('0'), self.daily_realized_pnl)) / self.live_equity
        
        old_halt = self.halt_state
        if daily_loss_pct > Decimal('0.025'):
            self.halt_state = HaltState.HARD_KILL
        elif daily_loss_pct > Decimal('0.015') or self.consecutive_losses >= 3:
            self.halt_state = HaltState.SOFT_KILL
        else:
            self.halt_state = HaltState.ACTIVE
            
        if old_halt != self.halt_state:
            self._log_audit("HALT_LADDER_ESCALATION", old_halt.value, self.halt_state.value, "Daily limits or loss streaks triggered", {"daily_loss_pct": str(daily_loss_pct), "consec_losses": self.consecutive_losses})

    def _get_authorized_sleeves(self) -> Set[str]:
        """Doctrine 16: Sleeve Restriction Matrix, unified securely with active gate logic."""
        if self.current_state == AggressionState.FLOOR_LOCK or self.halt_state in [HaltState.HARD_KILL, HaltState.FORTRESS_HALT]:
            return set()
            
        authorized = set()
        for s_id, meta in self.registered_sleeves.items():
            if self.current_state not in meta.allowed_states:
                continue
            if self.recovery_mode and not meta.fortress_grade:
                continue
            if self.current_state == AggressionState.PRESERVATION and not (meta.tier == SleeveTier.ALPHA or meta.fortress_grade):
                continue
            authorized.add(s_id)
            
        return authorized

    # ==========================================
    # THE GATEKEEPER: SETUP AUTHORIZATION
    # ==========================================

    def request_authorization(self, setup: TradeSetup) -> AuthorizationReceipt:
        """
        Doctrine 12 & 13: Setup Authorization Doctrine.
        Rich inspection of the setup packet against immutable policy.
        The packet is already guaranteed mathematically viable via TradeSetup.__post_init__.
        """
        stack_summary = {
            "direction": str(setup.direction),
            "regime": setup.regime_snapshot,
            "target_bps": str(setup.target_distance_bps),
            "stop_bps": str(setup.stop_distance_bps)
        }

        # 1. Hard Survival Overrides
        if self.halt_state in [HaltState.HARD_KILL, HaltState.FORTRESS_HALT]:
            return self._deny(setup, f"HALT STATE ACTIVE: {self.halt_state.value}", stack_summary)
            
        if self.current_state == AggressionState.FLOOR_LOCK:
            return self._deny(setup, "FLOOR LOCK ACTIVE (D% < 2%)", stack_summary)

        # 2. Sleeve Metadata Governance (Doctrine 16)
        if setup.sleeve_id not in self._get_authorized_sleeves():
            return self._deny(setup, f"SLEEVE {setup.sleeve_id} RESTRICTED IN CURRENT DOCTRINE STATE", stack_summary)

        # 3. Minimum Asymmetry Constraints (Doctrine 13)
        req_asymmetry = self.policy.min_asymmetry_recovery if self.recovery_mode else self.policy.min_asymmetry_base
        if setup.expected_r_multiple < req_asymmetry:
            return self._deny(setup, f"R-MULTIPLE {setup.expected_r_multiple} < {req_asymmetry} LIMIT", stack_summary)

        # 4. Toxicity Tolerance (By State & Recovery)
        tox_limit = self.policy.state_toxicity_limit[self.current_state]
        if self.recovery_mode:
            tox_limit = tox_limit * Decimal('0.50')  # Halve toxicity tolerance in recovery
        if setup.toxicity_score > tox_limit:
            return self._deny(setup, f"TOXICITY {setup.toxicity_score} > {tox_limit} LIMIT", stack_summary)

        # 5. Pyramiding Doctrine (Doctrine 11)
        pyramid_multiplier = Decimal('1.0')
        if setup.is_pyramid_unit:
            sleeve_meta = self.registered_sleeves[setup.sleeve_id]
            if not sleeve_meta.pyramid_allowed:
                return self._deny(setup, "SLEEVE PROHIBITED FROM PYRAMIDING", stack_summary)
            if self.current_state not in [AggressionState.HUNT, AggressionState.PRESSURED]:
                return self._deny(setup, f"PYRAMIDING FORBIDDEN IN STATE {self.current_state.value}", stack_summary)
            if self.recovery_mode and setup.conviction != ConvictionLevel.EXCEPTIONAL:
                return self._deny(setup, "PYRAMIDING IN RECOVERY REQUIRES EXCEPTIONAL CONVICTION", stack_summary)
                
            pyramid_multiplier = self.policy.pyramid_ladder.get(setup.existing_units, Decimal('0.00'))
            if pyramid_multiplier == Decimal('0.00'):
                return self._deny(setup, f"PYRAMID LADDER LIMIT EXCEEDED AT UNIT {setup.existing_units}", stack_summary)
            
            stack_summary['pyramid_mult'] = str(pyramid_multiplier)

        # 6. Active Risk Base Calculation (Doctrine 6)
        predator_capital = max(Decimal('0'), self.live_equity - self.locked_floor)
        active_risk_base = min(predator_capital, Decimal('0.20') * self.live_equity)
        
        if active_risk_base <= Decimal('0'):
            return self._deny(setup, "ZERO ACTIVE RISK BASE", stack_summary)

        # 7. Multiplier Stack
        base_risk_fraction = self.policy.conviction_risk_fraction[setup.conviction]
        base_risk = active_risk_base * base_risk_fraction
        stack_summary['base_conviction_fraction'] = str(base_risk_fraction)

        state_multiplier = self.policy.state_aggression_multiplier[self.current_state]
        multiplier = state_multiplier
        stack_summary['state_multiplier'] = str(state_multiplier)

        if self.recovery_mode:
            multiplier *= Decimal('0.50')
            stack_summary['recovery_multiplier'] = '0.50'

        # Throttle Stack (Doctrine 9 & 10)
        daily_loss_pct = abs(min(Decimal('0'), self.daily_realized_pnl)) / self.live_equity
        if daily_loss_pct > Decimal('0.015'):
            multiplier *= Decimal('0.50')
            stack_summary['daily_throttle'] = '0.50'
            
        rolling_pnl = sum(self.recent_trade_history) if self.recent_trade_history else Decimal('0')
        if rolling_pnl < Decimal('0') and abs(rolling_pnl) > (Decimal('0.035') * self.live_equity):
            multiplier *= Decimal('0.50')
            stack_summary['rolling_throttle'] = '0.50'
            
        if self.consecutive_losses == 2:
            multiplier *= Decimal('0.70')
            stack_summary['consec_loss_throttle'] = '0.70'
        elif self.consecutive_losses == 3:
            multiplier *= Decimal('0.40')
            stack_summary['consec_loss_throttle'] = '0.40'
        elif self.consecutive_losses >= 4:
            return self._deny(setup, "4 CONSECUTIVE LOSSES (DAY LOCK ACTIVE)", stack_summary)

        # 8. Final Synthesis & Hard Caps
        adjusted_risk = base_risk * multiplier * pyramid_multiplier

        max_cap_equity = Decimal('0.0075') * self.live_equity
        max_cap_arb = Decimal('0.20') * active_risk_base
        absolute_max = min(max_cap_equity, max_cap_arb)

        final_authorized_risk = min(adjusted_risk, absolute_max).quantize(Decimal('0.01'), rounding=ROUND_DOWN)

        # 9. Dust Rejection
        if final_authorized_risk <= Decimal('1.00'):
            return self._deny(setup, "AUTHORIZED RISK DECAYED TO DUST", stack_summary)

        # 10. Receipt Issuance
        receipt = AuthorizationReceipt(
            is_authorized=True,
            authorized_risk_usd=final_authorized_risk,
            rejection_reason="AUTHORIZED",
            aggression_state=self.current_state,
            halt_state=self.halt_state,
            recovery_mode=self.recovery_mode,
            active_risk_base=active_risk_base,
            multiplier_stack_summary=stack_summary
        )
        self._log_audit("AUTHORIZATION_GRANTED", "0.00", str(final_authorized_risk), f"Setup Authorized [{setup.sleeve_id}]", stack_summary)
        return receipt

    def _deny(self, setup: TradeSetup, reason: str, stack: Dict[str, str]) -> AuthorizationReceipt:
        """Standardized issuance of denial receipts."""
        predator_capital = max(Decimal('0'), self.live_equity - self.locked_floor)
        active_risk_base = min(predator_capital, Decimal('0.20') * self.live_equity)
        
        receipt = AuthorizationReceipt(
            is_authorized=False,
            authorized_risk_usd=Decimal('0.00'),
            rejection_reason=reason,
            aggression_state=self.current_state,
            halt_state=self.halt_state,
            recovery_mode=self.recovery_mode,
            active_risk_base=active_risk_base,
            multiplier_stack_summary=stack
        )
        self._log_audit("AUTHORIZATION_DENIED", "0.00", "0.00", reason, {"sleeve_id": setup.sleeve_id})
        return receipt

    # ==========================================
    # DATA & AUDIT EXPORTS
    # ==========================================

    def get_state(self) -> DynamicRiskState:
        """Returns the fully computed current state of Sovereign Capital."""
        predator_capital = max(Decimal('0'), self.live_equity - self.locked_floor)
        active_risk_base = min(predator_capital, Decimal('0.20') * self.live_equity)
        floor_distance = self.live_equity - self.locked_floor
        
        return DynamicRiskState(
            initial_capital=self.initial_capital,
            live_equity=self.live_equity,
            cumulative_realized_pnl=self.cumulative_realized_pnl,
            high_water_mark=self.high_water_mark,
            locked_floor=self.locked_floor,
            predator_capital=predator_capital,
            active_risk_base=active_risk_base,
            floor_distance=floor_distance,
            floor_distance_pct=floor_distance / self.live_equity if self.live_equity > Decimal('0') else Decimal('0'),
            aggression_state=self.current_state,
            recovery_mode=self.recovery_mode,
            daily_realized_pnl=self.daily_realized_pnl,
            rolling_5_trade_pnl=sum(self.recent_trade_history) if self.recent_trade_history else Decimal('0.00'),
            consecutive_losses=self.consecutive_losses,
            halt_state=self.halt_state,
            authorized_sleeves=list(self._get_authorized_sleeves())
        )

    def export_audit_trail(self, count: int = 50) -> List[Dict[str, Any]]:
        """Returns the most recent N sovereign state transitions."""
        history = list(self.audit_ledger)
        return [
            {
                "timestamp": r.timestamp,
                "event_type": r.event_type,
                "old": r.old_value,
                "new": r.new_value,
                "reason": r.reason,
                "meta": r.metadata
            } for r in history[-count:]
        ]