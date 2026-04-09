"""
Kill Switch - Hard Protection / Trading-Stop Authority

This file is the hard protection / escalation / trading-stop authority for
critical risk conditions. It maintains deterministic kill state, exposes
whether trading is blocked, records trigger provenance, and supports
replay-safe escalation and reset semantics.

What this file truly enforces directly:
- Hard kill state that blocks trading when triggered
- Multiple trigger types (drawdown, manual, emergency, volatility, etc.)
- Deterministic state transitions with explicit nanosecond timestamps
- Auto-recovery cooldown period with COOLDOWN state (blocked, waiting for reset)
- Manual reset requirement for safety-critical triggers
- Replay-safe persistence export/import

What this file only signals (does not enforce directly):
- Actual position liquidation (delegated to execution engine)
- Order cancellation (delegated to order router)
- Portfolio state changes (delegated to portfolio manager)

All authoritative state transitions require explicit timestamp_ns.
No silent wall-clock dependence. Query methods are pure.
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Any, Optional, List
from enum import Enum

from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)


class KillSwitchType(Enum):
    """
    Type of kill switch trigger.
    
    Persisted by stable name, not auto() value, for schema safety.
    """
    DRAWDOWN = "drawdown"          # Drawdown limit exceeded
    MANUAL = "manual"              # Manual operator trigger
    EMERGENCY = "emergency"        # Emergency (VoL fuse, physical fuse)
    VOLATILITY = "volatility"      # Volatility spike
    STALE_DATA = "stale_data"      # Stale market data
    LAG = "lag"                    # Excessive latency
    EXCHANGE_OUTAGE = "exchange_outage"  # Exchange connectivity lost
    CORRUPTION = "corruption"      # State corruption detected


class KillSwitchState(Enum):
    """
    Current kill switch state.
    
    Persisted by stable name, not auto() value, for schema safety.
    
    State transitions:
    NORMAL -> TRIGGERED (on trigger with auto-recovery)
    NORMAL -> MANUAL_RESET_REQUIRED (on trigger with manual reset)
    TRIGGERED -> COOLDOWN (after auto-recovery period expires via advance_state)
    COOLDOWN -> NORMAL (only via explicit reset - no auto-transition)
    MANUAL_RESET_REQUIRED -> NORMAL (only via explicit reset)
    
    TRIGGERED semantics:
        - Blocked state entered immediately on trigger
        - Trading is blocked
        - Cooldown timer starts counting
    
    COOLDOWN semantics:
        - Blocked recovery-hold state entered after cooldown expiry
        - Trading remains blocked
        - Explicit reset() required to return to NORMAL
        - No automatic transition to NORMAL
    
    NORMAL semantics:
        - No kill active
        - Trading allowed
        - Only reached via explicit reset()
    """
    NORMAL = "normal"                      # No kill active, trading allowed
    TRIGGERED = "triggered"                # Kill active, trading blocked, cooldown pending
    COOLDOWN = "cooldown"                  # Blocked recovery-hold state after cooldown expiry
    MANUAL_RESET_REQUIRED = "manual_reset_required"  # Requires operator intervention


@dataclass(frozen=True, slots=True)
class KillSwitchRecord:
    """
    Immutable record of a kill switch trigger event.
    
    All fields are immutable after creation for deterministic replay.
    """
    trigger_type: KillSwitchType
    triggered_at_ns: int
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    requires_manual_reset: bool = False
    auto_recover_after_ns: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for persistence."""
        return {
            "trigger_type": self.trigger_type.value,
            "triggered_at_ns": self.triggered_at_ns,
            "reason": self.reason,
            "metadata": self.metadata,
            "requires_manual_reset": self.requires_manual_reset,
            "auto_recover_after_ns": self.auto_recover_after_ns,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KillSwitchRecord":
        """Deserialize from dictionary."""
        return cls(
            trigger_type=KillSwitchType(data["trigger_type"]),
            triggered_at_ns=data["triggered_at_ns"],
            reason=data["reason"],
            metadata=data.get("metadata", {}),
            requires_manual_reset=data.get("requires_manual_reset", False),
            auto_recover_after_ns=data.get("auto_recover_after_ns"),
        )


class KillSwitch:
    """
    Hard protection / trading-stop authority.
    
    Features:
    - Deterministic kill state with explicit nanosecond timestamps
    - Multiple trigger types with provenance
    - Auto-recovery cooldown with COOLDOWN state (blocked, requires reset)
    - Manual reset requirement for safety-critical triggers
    - Replay-safe persistence export/import
    - NO SILENT WALL-CLOCK DEPENDENCE (all transitions require explicit timestamp)
    - Pure query methods (no state mutation on read)
    
    State Machine Truth:
        NORMAL → TRIGGERED (on trigger with auto-recovery)
        NORMAL → MANUAL_RESET_REQUIRED (on trigger with manual reset)
        TRIGGERED → COOLDOWN (after auto-recovery period expires via advance_state)
        COOLDOWN → NORMAL (only via explicit reset)
        MANUAL_RESET_REQUIRED → NORMAL (only via explicit reset)
    
    CRITICAL: COOLDOWN does NOT auto-transition to NORMAL.
    Explicit reset() is required to return to NORMAL from any blocked state.
    
    What this file enforces directly:
        - `can_trade(timestamp_ns)` returns False when kill is active
        - `is_killed(timestamp_ns)` returns True when kill is active
        - State transitions are logged and recorded
    
    What this file delegates (does not enforce directly):
        - Position liquidation (execution engine responsibility)
        - Order cancellation (order router responsibility)
        - Portfolio unwinding (portfolio manager responsibility)
    
    The kill switch is the AUTHORITY that signals these actions should occur,
    but the actual execution is handled by downstream components.
    """
    
    def __init__(self):
        """Initialize kill switch in NORMAL state with no active triggers."""
        self._state: KillSwitchState = KillSwitchState.NORMAL
        self._active_record: Optional[KillSwitchRecord] = None
        self._trigger_history: List[KillSwitchRecord] = []
        self._last_state_change_ns: int = 0
        self._cooldown_until_ns: int = 0
        
        logger.info("KillSwitch initialized: state=NORMAL")
    
    # =========================================================================
    # TRIGGER METHODS (State-Advancing, Require Explicit Timestamp)
    # =========================================================================
    
    def trigger(
        self,
        trigger_type: KillSwitchType,
        reason: str,
        timestamp_ns: int,
        metadata: Optional[Dict[str, Any]] = None,
        requires_manual_reset: bool = False,
        auto_recover_after_ns: Optional[int] = None,
    ) -> bool:
        """
        Trigger the kill switch.
        
        Args:
            trigger_type: Type of kill switch trigger
            reason: Human-readable reason for trigger
            timestamp_ns: Trigger timestamp (MUST be provided, no default)
            metadata: Additional context data
            requires_manual_reset: If True, cannot auto-recover; enters MANUAL_RESET_REQUIRED
            auto_recover_after_ns: Auto-recovery duration if applicable (enters TRIGGERED)
        
        Returns:
            True if trigger was applied, False if already in stricter state
        
        Note:
            This is an authoritative state-transition method.
            timestamp_ns MUST be provided by caller (no wall-clock default).
        """
        # Always record trigger in history for provenance
        record = KillSwitchRecord(
            trigger_type=trigger_type,
            triggered_at_ns=timestamp_ns,
            reason=reason,
            metadata=metadata or {},
            requires_manual_reset=requires_manual_reset,
            auto_recover_after_ns=auto_recover_after_ns,
        )
        self._trigger_history.append(record)
        
        # If already in MANUAL_RESET_REQUIRED, no further state change (highest severity)
        if self._state == KillSwitchState.MANUAL_RESET_REQUIRED:
            logger.debug(f"KillSwitch already in MANUAL_RESET_REQUIRED, recording trigger only: {reason}")
            return False
        
        # Determine new state based on trigger type and current state
        if requires_manual_reset:
            new_state = KillSwitchState.MANUAL_RESET_REQUIRED
            new_cooldown_until_ns = 0
            self._active_record = record
            self._state = new_state
            self._last_state_change_ns = timestamp_ns
            self._cooldown_until_ns = new_cooldown_until_ns
            logger.critical(f"KILL SWITCH TRIGGERED (MANUAL RESET REQUIRED): {trigger_type.value} - {reason}")
            return True
        
        # Auto-recoverable trigger (enters TRIGGERED state with cooldown)
        if auto_recover_after_ns is not None and auto_recover_after_ns > 0:
            new_state = KillSwitchState.TRIGGERED
            new_cooldown_until_ns = timestamp_ns + auto_recover_after_ns
            self._active_record = record
            self._state = new_state
            self._last_state_change_ns = timestamp_ns
            self._cooldown_until_ns = new_cooldown_until_ns
            logger.critical(f"KILL SWITCH TRIGGERED (auto-recovery in {auto_recover_after_ns / 1_000_000_000:.0f}s): {reason}")
            return True
        
        # Default: triggered with no auto-recovery (must be manually reset)
        new_state = KillSwitchState.TRIGGERED
        self._active_record = record
        self._state = new_state
        self._last_state_change_ns = timestamp_ns
        self._cooldown_until_ns = 0
        logger.critical(f"KILL SWITCH TRIGGERED: {trigger_type.value} - {reason}")
        return True
    
    def trigger_drawdown(
        self, drawdown_pct: Decimal, limit_pct: Decimal, timestamp_ns: int
    ) -> bool:
        """Convenience method for drawdown limit trigger."""
        return self.trigger(
            trigger_type=KillSwitchType.DRAWDOWN,
            reason=f"Drawdown {drawdown_pct:.2%} exceeded limit {limit_pct:.2%}",
            timestamp_ns=timestamp_ns,
            metadata={"drawdown_pct": str(drawdown_pct), "limit_pct": str(limit_pct)},
            requires_manual_reset=False,
            auto_recover_after_ns=None,
        )
    
    def trigger_emergency(self, reason: str, timestamp_ns: int) -> bool:
        """Convenience method for emergency trigger (always requires manual reset)."""
        return self.trigger(
            trigger_type=KillSwitchType.EMERGENCY,
            reason=reason,
            timestamp_ns=timestamp_ns,
            requires_manual_reset=True,
            auto_recover_after_ns=None,
        )
    
    def trigger_manual(self, reason: str, timestamp_ns: int) -> bool:
        """Convenience method for manual operator trigger (always requires manual reset)."""
        return self.trigger(
            trigger_type=KillSwitchType.MANUAL,
            reason=reason,
            timestamp_ns=timestamp_ns,
            requires_manual_reset=True,
            auto_recover_after_ns=None,
        )
    
    # =========================================================================
    # STATE ADVANCEMENT (Explicit, No Hidden Side Effects)
    # =========================================================================
    
    def advance_state(self, timestamp_ns: int) -> bool:
        """
        Advance state machine based on current time.
        
        This is the ONLY method that should be called to advance time-dependent
        state transitions. It is explicit and requires a timestamp.
        
        Transitions performed:
            TRIGGERED -> COOLDOWN when timestamp_ns >= cooldown_until_ns
        
        CRITICAL: COOLDOWN does NOT auto-transition to NORMAL.
        Explicit reset() is required to return to NORMAL.
        
        Args:
            timestamp_ns: Current timestamp for state advancement
        
        Returns:
            True if state changed, False otherwise
        """
        if self._state == KillSwitchState.TRIGGERED and self._cooldown_until_ns > 0:
            if timestamp_ns >= self._cooldown_until_ns:
                # Move to COOLDOWN state (blocked, waiting for reset)
                self._state = KillSwitchState.COOLDOWN
                self._last_state_change_ns = timestamp_ns
                logger.info(f"KillSwitch: TRIGGERED -> COOLDOWN at {timestamp_ns}")
                return True
        
        return False
    
    def reset(self, timestamp_ns: int, reason: str = "manual_reset") -> bool:
        """
        Manually reset the kill switch to NORMAL state.
        
        This is the ONLY way to exit COOLDOWN or MANUAL_RESET_REQUIRED states.
        There is no automatic transition from COOLDOWN to NORMAL.
        
        Args:
            timestamp_ns: Reset timestamp (MUST be provided, no default)
            reason: Reason for reset
        
        Returns:
            True if reset was applied, False if already normal
        """
        if self._state == KillSwitchState.NORMAL:
            logger.debug(f"KillSwitch reset called but already NORMAL: {reason}")
            return False
        
        old_state = self._state
        self._state = KillSwitchState.NORMAL
        self._active_record = None
        self._cooldown_until_ns = 0
        self._last_state_change_ns = timestamp_ns
        
        logger.info(f"KillSwitch reset: {old_state.value} -> NORMAL ({reason})")
        return True
    
    # =========================================================================
    # PURE QUERY METHODS (No State Mutation)
    # =========================================================================
    
    def is_killed(self, timestamp_ns: int) -> bool:
        """
        Check if kill switch is active (trading blocked).
        
        PURE QUERY: Does NOT mutate state. Use `advance_state()` separately.
        
        Args:
            timestamp_ns: Current timestamp for cooldown comparison
        
        Returns:
            True if trading should be blocked
        """
        if self._state == KillSwitchState.NORMAL:
            return False
        
        if self._state == KillSwitchState.MANUAL_RESET_REQUIRED:
            return True
        
        if self._state == KillSwitchState.TRIGGERED:
            # Check if still in triggered period (not yet cooldown)
            if self._cooldown_until_ns > 0 and timestamp_ns < self._cooldown_until_ns:
                return True
            # If past cooldown, state should have been advanced to COOLDOWN
            # But we don't mutate here - caller must call advance_state()
            return True  # Still killed until explicitly advanced
        
        if self._state == KillSwitchState.COOLDOWN:
            return True  # COOLDOWN is a blocked state
        
        return True  # Default safe
    
    def can_trade(self, timestamp_ns: int) -> bool:
        """
        Check if trading is allowed.
        
        PURE QUERY: Does NOT mutate state.
        
        Args:
            timestamp_ns: Current timestamp for cooldown comparison
        
        Returns:
            True if trading is allowed, False if killed
        """
        return not self.is_killed(timestamp_ns)
    
    def get_state(self) -> KillSwitchState:
        """Get current kill switch state (pure read)."""
        return self._state
    
    def get_active_record(self) -> Optional[KillSwitchRecord]:
        """Get the currently active kill switch record, if any (pure read)."""
        return self._active_record
    
    def get_trigger_history(self, limit: int = 100) -> List[KillSwitchRecord]:
        """Get recent trigger history (pure read)."""
        return self._trigger_history[-limit:]
    
    def get_last_state_change_ns(self) -> int:
        """Get timestamp of last state change (pure read)."""
        return self._last_state_change_ns
    
    def get_cooldown_remaining_ns(self, timestamp_ns: int) -> int:
        """
        Get remaining cooldown time in nanoseconds.
        
        PURE QUERY: Does NOT mutate state.
        
        Args:
            timestamp_ns: Current timestamp
        
        Returns:
            Remaining nanoseconds, or 0 if no cooldown active
        """
        if self._state != KillSwitchState.TRIGGERED or self._cooldown_until_ns <= 0:
            return 0
        
        remaining = self._cooldown_until_ns - timestamp_ns
        return max(0, remaining)
    
    def get_cooldown_until_ns(self) -> int:
        """Get timestamp when cooldown ends (pure read)."""
        return self._cooldown_until_ns
    
    # =========================================================================
    # PERSISTENCE (State-Advancing Only on Load)
    # =========================================================================
    
    def export_state(self) -> Dict[str, Any]:
        """
        Export kill switch state for persistence.
        
        Returns:
            Dictionary with serializable state
        """
        return {
            "state": self._state.value,
            "active_record": self._active_record.to_dict() if self._active_record else None,
            "trigger_history": [r.to_dict() for r in self._trigger_history[-100:]],
            "last_state_change_ns": self._last_state_change_ns,
            "cooldown_until_ns": self._cooldown_until_ns,
            "schema_version": 1,
        }
    
    def import_state(self, state: Dict[str, Any], timestamp_ns: int) -> None:
        """
        Import kill switch state from persistence.
        
        Args:
            state: Dictionary from export_state()
            timestamp_ns: Current timestamp for state validation
        
        Raises:
            ValueError: If state schema is invalid
        """
        schema_version = state.get("schema_version", 1)
        if schema_version != 1:
            raise ValueError(f"Unsupported schema version: {schema_version}")
        
        # Restore state
        state_value = state.get("state")
        if state_value:
            self._state = KillSwitchState(state_value)
        
        # Restore active record
        active_record_data = state.get("active_record")
        if active_record_data:
            self._active_record = KillSwitchRecord.from_dict(active_record_data)
        else:
            self._active_record = None
        
        # Restore trigger history
        history_data = state.get("trigger_history", [])
        self._trigger_history = [KillSwitchRecord.from_dict(r) for r in history_data]
        
        # Restore timestamps
        self._last_state_change_ns = state.get("last_state_change_ns", 0)
        self._cooldown_until_ns = state.get("cooldown_until_ns", 0)
        
        # Validate state consistency and advance if needed
        self.advance_state(timestamp_ns)
        
        logger.info(f"KillSwitch state imported: {self._state.value}")
    
    def reset_all(self, timestamp_ns: int) -> None:
        """
        Reset all state including history.
        
        Args:
            timestamp_ns: Reset timestamp for state change record
        """
        self._state = KillSwitchState.NORMAL
        self._active_record = None
        self._trigger_history.clear()
        self._last_state_change_ns = timestamp_ns
        self._cooldown_until_ns = 0
        logger.info("KillSwitch reset_all: all state cleared")
    
    # =========================================================================
    # DIAGNOSTICS (Pure Read)
    # =========================================================================
    
    def get_status(self, timestamp_ns: int) -> Dict[str, Any]:
        """
        Get current status for monitoring.
        
        PURE QUERY: Does NOT mutate state. Caller must provide timestamp.
        
        Args:
            timestamp_ns: Current timestamp for cooldown calculation
        
        Returns:
            Status dictionary
        """
        return {
            "state": self._state.value,
            "is_killed": self.is_killed(timestamp_ns),
            "active_trigger": self._active_record.to_dict() if self._active_record else None,
            "trigger_count": len(self._trigger_history),
            "last_state_change_ns": self._last_state_change_ns,
            "cooldown_remaining_ns": self.get_cooldown_remaining_ns(timestamp_ns),
            "cooldown_remaining_sec": self.get_cooldown_remaining_ns(timestamp_ns) / 1_000_000_000,
            "cooldown_until_ns": self._cooldown_until_ns,
        }


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def create_kill_switch() -> KillSwitch:
    """
    Create a configured kill switch instance.
    
    Returns:
        KillSwitch instance
    """
    return KillSwitch()


__all__ = [
    'KillSwitch',
    'KillSwitchType',
    'KillSwitchState',
    'KillSwitchRecord',
    'create_kill_switch',
]