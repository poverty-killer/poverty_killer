"""
Commander - Global Attack Toggle & System Control
Manages SAFE vs ATTACK modes, automatic de-risking, and net-profit constraints.
Single source of truth for system-wide aggression.
"""

import logging
import threading
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class AttackState:
    """Current attack mode state."""
    is_attack_mode: bool = False
    initial_equity: float = 20000.0
    current_equity: float = 20000.0
    peak_equity: float = 20000.0
    target_equity: float = 40000.0
    mode_reason: str = ""
    last_mode_toggle_ns: Optional[int] = None


class Commander:
    """
    Global system commander.
    Manages SAFE/ATTACK modes, automatic de-risking, and net-profit constraints.
    """

    def __init__(self, initial_equity: float = 20000.0, target_equity: float = 40000.0):
        """
        Initialize commander.

        Args:
            initial_equity: Starting portfolio equity
            target_equity: Target equity for automatic de-risking
        """
        self._state = AttackState(
            initial_equity=initial_equity,
            current_equity=initial_equity,
            peak_equity=initial_equity,
            target_equity=target_equity
        )
        self._lock = threading.Lock()
        self._mode_change_callbacks = []

        logger.info(f"Commander initialized: initial=${initial_equity:,.0f}, target=${target_equity:,.0f}")

    def update_equity(self, current_equity: float, timestamp_ns: int) -> None:
        """
        Update current portfolio equity.

        Args:
            current_equity: Current portfolio value
            timestamp_ns: Exchange timestamp
        """
        with self._lock:
            self._state.current_equity = current_equity

            # Update peak equity
            if current_equity > self._state.peak_equity:
                self._state.peak_equity = current_equity

            # Check for automatic de-risking (target hit)
            if current_equity >= self._state.target_equity and self._state.is_attack_mode:
                logger.critical(f"TARGET HIT: ${current_equity:,.0f} >= ${self._state.target_equity:,.0f}")
                self._set_attack_mode(False, "target_hit", timestamp_ns)

            # Check for drawdown protection in attack mode
            if self._state.is_attack_mode:
                drawdown = (self._state.peak_equity - current_equity) / self._state.peak_equity
                if drawdown > 0.15:  # 15% drawdown in attack mode triggers safe mode
                    logger.critical(f"DRAWDOWN TRIGGER: {drawdown:.2%}, exiting attack mode")
                    self._set_attack_mode(False, "drawdown_protection", timestamp_ns)

    def _set_attack_mode(self, enabled: bool, reason: str, timestamp_ns: int) -> None:
        """
        Set attack mode with state update.

        Args:
            enabled: True for attack mode
            reason: Reason for mode change
            timestamp_ns: Exchange timestamp
        """
        with self._lock:
            old_mode = self._state.is_attack_mode
            if old_mode == enabled:
                return

            self._state.is_attack_mode = enabled
            self._state.mode_reason = reason
            self._state.last_mode_toggle_ns = timestamp_ns

            logger.critical(f"ATTACK MODE: {'ENABLED' if enabled else 'DISABLED'} - {reason}")

            # Notify callbacks
            for callback in self._mode_change_callbacks:
                try:
                    callback(enabled, reason)
                except Exception as e:
                    logger.error(f"Mode change callback error: {e}")

    def enable_attack_mode(self, reason: str, timestamp_ns: int) -> bool:
        """
        Enable attack mode manually.

        Args:
            reason: Reason for enabling
            timestamp_ns: Exchange timestamp

        Returns:
            True if enabled
        """
        # Check if target already hit
        if self._state.current_equity >= self._state.target_equity:
            logger.warning("Cannot enable attack mode: target already hit")
            return False

        self._set_attack_mode(True, reason, timestamp_ns)
        return True

    def disable_attack_mode(self, reason: str, timestamp_ns: int) -> None:
        """
        Disable attack mode.

        Args:
            reason: Reason for disabling
            timestamp_ns: Exchange timestamp
        """
        self._set_attack_mode(False, reason, timestamp_ns)

    def is_attack_mode(self) -> bool:
        """Check if attack mode is active."""
        with self._lock:
            return self._state.is_attack_mode

    def get_kelly_multiplier(self) -> float:
        """
        Get current Kelly multiplier based on mode.

        Returns:
            Kelly multiplier (0.4 for SAFE, 0.85 for ATTACK)
        """
        return 0.85 if self._state.is_attack_mode else 0.4

    def get_vpin_threshold(self) -> float:
        """
        Get current VPIN threshold based on mode.

        Returns:
            VPIN threshold (0.8 for SAFE, 0.65 for ATTACK)
        """
        return 0.65 if self._state.is_attack_mode else 0.8

    def get_confidence_threshold(self) -> float:
        """
        Get current confidence threshold based on mode.

        Returns:
            Confidence threshold (0.95 for SAFE, 0.70 for ATTACK)
        """
        return 0.70 if self._state.is_attack_mode else 0.95

    def get_aggression_multiplier(self) -> float:
        """
        Get current aggression multiplier.

        Returns:
            Aggression multiplier (1.0 for SAFE, 1.5 for ATTACK)
        """
        return 1.5 if self._state.is_attack_mode else 1.0

    def can_trade(self, expected_net_profit_pct: float, confidence: float) -> bool:
        """
        Determine if trade is allowed based on net profit and confidence.

        Args:
            expected_net_profit_pct: Expected net profit percentage
            confidence: Signal confidence

        Returns:
            True if trade is allowed
        """
        with self._lock:
            # Minimum net profit requirement (0.5% of notional)
            if expected_net_profit_pct < 0.5:
                return False

            # Confidence threshold based on mode
            min_confidence = self.get_confidence_threshold()
            if confidence < min_confidence:
                return False

            # Check if target already hit (no more trades)
            if self._state.current_equity >= self._state.target_equity:
                return False

            return True

    def register_mode_change_callback(self, callback) -> None:
        """Register callback for mode changes."""
        self._mode_change_callbacks.append(callback)

    def get_status(self) -> Dict[str, Any]:
        """Get commander status."""
        with self._lock:
            return {
                "mode": "ATTACK" if self._state.is_attack_mode else "SAFE",
                "reason": self._state.mode_reason,
                "initial_equity": self._state.initial_equity,
                "current_equity": self._state.current_equity,
                "peak_equity": self._state.peak_equity,
                "target_equity": self._state.target_equity,
                "progress_pct": (self._state.current_equity - self._state.initial_equity) / self._state.initial_equity * 100,
                "kelly_multiplier": self.get_kelly_multiplier(),
                "vpin_threshold": self.get_vpin_threshold(),
                "confidence_threshold": self.get_confidence_threshold(),
                "aggression_multiplier": self.get_aggression_multiplier()
            }