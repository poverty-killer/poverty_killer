"""
Commander - Global Attack Toggle & System Control

Manages SAFE vs ATTACK modes, automatic de-risking, and net-profit constraints.
Single source of truth for system-wide aggression.
"""

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

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

    SAFE_KELLY_MULTIPLIER = 0.4
    ATTACK_KELLY_MULTIPLIER = 0.85

    SAFE_VPIN_THRESHOLD = 0.8
    ATTACK_VPIN_THRESHOLD = 0.65

    SAFE_CONFIDENCE_THRESHOLD = 0.95
    ATTACK_CONFIDENCE_THRESHOLD = 0.70

    SAFE_AGGRESSION_MULTIPLIER = 1.0
    ATTACK_AGGRESSION_MULTIPLIER = 1.5

    MIN_EXPECTED_NET_PROFIT_PCT = 0.5
    ATTACK_MODE_MAX_DRAWDOWN = 0.15

    def __init__(self, initial_equity: float = 20000.0, target_equity: float = 40000.0):
        """
        Initialize commander.

        Args:
            initial_equity: Starting portfolio equity
            target_equity: Target equity for automatic de-risking
        """
        initial_equity = self._validate_positive_float(initial_equity, "initial_equity")
        target_equity = self._validate_positive_float(target_equity, "target_equity")

        if target_equity < initial_equity:
            raise ValueError(
                f"target_equity ({target_equity}) cannot be less than initial_equity ({initial_equity})"
            )

        self._state = AttackState(
            initial_equity=initial_equity,
            current_equity=initial_equity,
            peak_equity=initial_equity,
            target_equity=target_equity,
        )
        self._lock = threading.RLock()
        self._mode_change_callbacks: List[Callable[[bool, str], None]] = []

        logger.info(
            "Commander initialized: initial=$%s, target=$%s",
            f"{initial_equity:,.0f}",
            f"{target_equity:,.0f}",
        )

    @staticmethod
    def _validate_positive_float(value: float, field_name: str) -> float:
        if not isinstance(value, (int, float)):
            raise TypeError(f"{field_name} must be numeric, got {type(value).__name__}")
        result = float(value)
        if result <= 0:
            raise ValueError(f"{field_name} must be positive: {value}")
        return result

    @staticmethod
    def _validate_non_negative_float(value: float, field_name: str) -> float:
        if not isinstance(value, (int, float)):
            raise TypeError(f"{field_name} must be numeric, got {type(value).__name__}")
        result = float(value)
        if result < 0:
            raise ValueError(f"{field_name} cannot be negative: {value}")
        return result

    @staticmethod
    def _validate_probability_like(value: float, field_name: str) -> float:
        if not isinstance(value, (int, float)):
            raise TypeError(f"{field_name} must be numeric, got {type(value).__name__}")
        result = float(value)
        if result < 0.0 or result > 1.0:
            raise ValueError(f"{field_name} must be in [0, 1], got {value}")
        return result

    @staticmethod
    def _validate_timestamp_ns(timestamp_ns: int) -> int:
        if not isinstance(timestamp_ns, int):
            raise TypeError(f"timestamp_ns must be int, got {type(timestamp_ns).__name__}")
        if timestamp_ns <= 0:
            raise ValueError(f"timestamp_ns must be positive: {timestamp_ns}")
        return timestamp_ns

    @staticmethod
    def _validate_reason(reason: str) -> str:
        if not isinstance(reason, str):
            raise TypeError(f"reason must be str, got {type(reason).__name__}")
        normalized = reason.strip()
        if not normalized:
            raise ValueError("reason must be non-blank")
        return normalized

    def update_equity(self, current_equity: float, timestamp_ns: int) -> None:
        """
        Update current portfolio equity.

        Args:
            current_equity: Current portfolio value
            timestamp_ns: Exchange timestamp
        """
        current_equity = self._validate_non_negative_float(current_equity, "current_equity")
        timestamp_ns = self._validate_timestamp_ns(timestamp_ns)

        with self._lock:
            self._state.current_equity = current_equity

            if current_equity > self._state.peak_equity:
                self._state.peak_equity = current_equity

            if current_equity >= self._state.target_equity and self._state.is_attack_mode:
                logger.critical(
                    "TARGET HIT: $%s >= $%s",
                    f"{current_equity:,.0f}",
                    f"{self._state.target_equity:,.0f}",
                )
                self._set_attack_mode(False, "target_hit", timestamp_ns)

            if self._state.is_attack_mode and self._state.peak_equity > 0:
                drawdown = (self._state.peak_equity - current_equity) / self._state.peak_equity
                if drawdown > self.ATTACK_MODE_MAX_DRAWDOWN:
                    logger.critical(
                        "DRAWDOWN TRIGGER: %.2f%%, exiting attack mode",
                        drawdown * 100.0,
                    )
                    self._set_attack_mode(False, "drawdown_protection", timestamp_ns)

    def _set_attack_mode(self, enabled: bool, reason: str, timestamp_ns: int) -> None:
        """
        Set attack mode with state update.

        Args:
            enabled: True for attack mode
            reason: Reason for mode change
            timestamp_ns: Exchange timestamp
        """
        reason = self._validate_reason(reason)
        timestamp_ns = self._validate_timestamp_ns(timestamp_ns)

        callbacks: List[Callable[[bool, str], None]] = []

        with self._lock:
            old_mode = self._state.is_attack_mode
            if old_mode == enabled:
                return

            self._state.is_attack_mode = enabled
            self._state.mode_reason = reason
            self._state.last_mode_toggle_ns = timestamp_ns
            callbacks = list(self._mode_change_callbacks)

        logger.critical("ATTACK MODE: %s - %s", "ENABLED" if enabled else "DISABLED", reason)

        for callback in callbacks:
            try:
                callback(enabled, reason)
            except Exception as e:
                logger.error("Mode change callback error: %s", e)

    def enable_attack_mode(self, reason: str, timestamp_ns: int) -> bool:
        """
        Enable attack mode manually.

        Args:
            reason: Reason for enabling
            timestamp_ns: Exchange timestamp

        Returns:
            True if enabled
        """
        reason = self._validate_reason(reason)
        timestamp_ns = self._validate_timestamp_ns(timestamp_ns)

        with self._lock:
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
        with self._lock:
            return (
                self.ATTACK_KELLY_MULTIPLIER
                if self._state.is_attack_mode
                else self.SAFE_KELLY_MULTIPLIER
            )

    def get_vpin_threshold(self) -> float:
        """
        Get current VPIN threshold based on mode.

        Returns:
            VPIN threshold (0.8 for SAFE, 0.65 for ATTACK)
        """
        with self._lock:
            return self.ATTACK_VPIN_THRESHOLD if self._state.is_attack_mode else self.SAFE_VPIN_THRESHOLD

    def get_confidence_threshold(self) -> float:
        """
        Get current confidence threshold based on mode.

        Returns:
            Confidence threshold (0.95 for SAFE, 0.70 for ATTACK)
        """
        with self._lock:
            return (
                self.ATTACK_CONFIDENCE_THRESHOLD
                if self._state.is_attack_mode
                else self.SAFE_CONFIDENCE_THRESHOLD
            )

    def get_aggression_multiplier(self) -> float:
        """
        Get current aggression multiplier.

        Returns:
            Aggression multiplier (1.0 for SAFE, 1.5 for ATTACK)
        """
        with self._lock:
            return (
                self.ATTACK_AGGRESSION_MULTIPLIER
                if self._state.is_attack_mode
                else self.SAFE_AGGRESSION_MULTIPLIER
            )

    def can_trade(self, expected_net_profit_pct: float, confidence: float) -> bool:
        """
        Determine if trade is allowed based on net profit and confidence.

        Args:
            expected_net_profit_pct: Expected net profit percentage
            confidence: Signal confidence

        Returns:
            True if trade is allowed
        """
        expected_net_profit_pct = self._validate_non_negative_float(
            expected_net_profit_pct,
            "expected_net_profit_pct",
        )
        confidence = self._validate_probability_like(confidence, "confidence")

        with self._lock:
            if expected_net_profit_pct < self.MIN_EXPECTED_NET_PROFIT_PCT:
                return False

            if confidence < self.get_confidence_threshold():
                return False

            if self._state.current_equity >= self._state.target_equity:
                return False

            return True

    def register_mode_change_callback(self, callback) -> None:
        """Register callback for mode changes."""
        if not callable(callback):
            raise TypeError("callback must be callable")
        with self._lock:
            self._mode_change_callbacks.append(callback)

    def get_status(self) -> Dict[str, Any]:
        """Get commander status."""
        with self._lock:
            initial_equity = self._state.initial_equity
            progress_pct = 0.0
            if initial_equity > 0:
                progress_pct = (
                    (self._state.current_equity - initial_equity) / initial_equity * 100.0
                )

            return {
                "mode": "ATTACK" if self._state.is_attack_mode else "SAFE",
                "reason": self._state.mode_reason,
                "initial_equity": self._state.initial_equity,
                "current_equity": self._state.current_equity,
                "peak_equity": self._state.peak_equity,
                "target_equity": self._state.target_equity,
                "progress_pct": progress_pct,
                "kelly_multiplier": self.get_kelly_multiplier(),
                "vpin_threshold": self.get_vpin_threshold(),
                "confidence_threshold": self.get_confidence_threshold(),
                "aggression_multiplier": self.get_aggression_multiplier(),
            }
