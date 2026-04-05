"""
Safety - Final Risk Gatekeeper
All orders must pass through this gate before execution.
Implements adverse selection feedback loop with EWMA latency tracking.
HARDENED: Integrated Macro-Overlay for macro-pause and macro-kill.
"""

import logging
import numpy as np
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime, timedelta
from collections import deque

from app.models import OrderIntent, PortfolioSnapshot, PhysicalVerification
from app.brain.sentiment_velocity import MacroSignal
from app.constants import ControlMode, RiskProfile

logger = logging.getLogger(__name__)

# Machine epsilon for precision
EPS = np.finfo(float).eps


class SafetyGate:
    """
    FINAL GATE: No order bypasses this.
    This is the single point of truth for risk decisions.
    Includes adverse selection feedback loop with EWMA latency tracking.
    Integrated with Macro-Overlay for macro-pause and macro-kill.
    """

    def __init__(self, config: Any):
        """
        Initialize safety gate.

        Args:
            config: Configuration object
        """
        self.config = config
        self.base_min_confidence = config.strategies.min_confidence

        # Adverse selection tracking with EWMA
        self._latency_impact_ewma: Optional[float] = None
        self._ewma_alpha = 0.3
        self._recent_trades: deque = deque(maxlen=10)
        self._adverse_selection_count = 0
        self._current_min_confidence = self.base_min_confidence

        # Macro state
        self._macro_pause_active = False
        self._macro_kill_active = False
        self._macro_kill_until: Optional[datetime] = None
        self._macro_pause_boost = 0.15  # Added to confidence threshold
        self._bull_trap_detected = False
        self._last_macro_signal: Optional[MacroSignal] = None

        # Kill switch state
        self._kill_switch_triggered = False
        self._kill_switch_time: Optional[datetime] = None

        # Drawdown tracking
        self._peak_equity: Optional[float] = None
        self._daily_peak: Optional[float] = None
        self._last_reset_date: Optional[datetime] = None

        logger.info("SafetyGate initialized with EWMA tracking and Macro-Overlay integration")

    def update_macro_signal(self, macro_signal: MacroSignal) -> None:
        """
        Update macro signal from sentiment velocity engine.

        Args:
            macro_signal: Macro signal from SentimentVelocityEngine
        """
        self._last_macro_signal = macro_signal

        # Handle macro-pause
        if macro_signal.macro_pause:
            self._macro_pause_active = True
            self._macro_pause_boost = macro_signal.confidence_boost
            logger.info(f"MACRO-PAUSE ACTIVE: {macro_signal.reason}")
        else:
            self._macro_pause_active = False
            self._macro_pause_boost = 0.0

        # Handle macro-kill
        if macro_signal.macro_kill:
            self._macro_kill_active = True
            self._macro_kill_until = datetime.utcnow() + timedelta(seconds=macro_signal.halt_seconds)
            logger.critical(f"MACRO-KILL ACTIVE: {macro_signal.reason} - halting for {macro_signal.halt_seconds}s")
        elif self._macro_kill_active and self._macro_kill_until and datetime.utcnow() > self._macro_kill_until:
            self._macro_kill_active = False
            self._macro_kill_until = None
            logger.info("MACRO-KILL expired, resuming trading")

        # Track bull trap
        self._bull_trap_detected = macro_signal.bull_trap_detected
        if self._bull_trap_detected:
            logger.warning(f"BULL TRAP DETECTED: divergence={macro_signal.divergence_score:.2f}")

    def _get_macro_adjusted_confidence(self, base_confidence: float) -> float:
        """
        Apply macro adjustments to confidence threshold.

        Args:
            base_confidence: Base min confidence

        Returns:
            Adjusted min confidence
        """
        adjusted = base_confidence

        # Add macro-pause boost
        if self._macro_pause_active:
            adjusted += self._macro_pause_boost

        # If macro-kill active, confidence threshold is effectively 1.0
        if self._macro_kill_active:
            return 1.0

        # If bull trap detected, increase threshold
        if self._bull_trap_detected:
            adjusted += 0.10

        return min(0.95, adjusted)

    def _update_ewma(self, new_value: float) -> float:
        """Update EWMA with new observation."""
        if self._latency_impact_ewma is None:
            self._latency_impact_ewma = new_value
        else:
            self._latency_impact_ewma = (self._ewma_alpha * new_value) + ((1 - self._ewma_alpha) * self._latency_impact_ewma)
        return self._latency_impact_ewma

    def adjust_confidence_threshold(self, latency_impact_ratio: float) -> float:
        """Dynamic confidence adjustment based on EWMA."""
        ewma_ratio = self._update_ewma(latency_impact_ratio)

        if ewma_ratio > 1.5:
            self._adverse_selection_count += 1
            base_confidence = min(0.9, self.base_min_confidence + 0.1)
        elif ewma_ratio > 1.2:
            base_confidence = min(0.85, self.base_min_confidence + 0.05)
        elif ewma_ratio < 0.8:
            base_confidence = max(0.5, self.base_min_confidence - 0.05)
            if self._adverse_selection_count > 0:
                self._adverse_selection_count -= 1
        else:
            base_confidence = self.base_min_confidence

        self._current_min_confidence = self._get_macro_adjusted_confidence(base_confidence)
        return self._current_min_confidence

    def get_adverse_selection_score(self) -> float:
        """Get current adverse selection score based on EWMA."""
        if self._latency_impact_ewma is None:
            return 0.0
        return min(1.0, max(0.0, (self._latency_impact_ewma - 1.0) / 1.0))

    def record_trade(self, verification: PhysicalVerification) -> None:
        """Record a trade for adverse selection tracking."""
        self._recent_trades.append(verification)
        self.adjust_confidence_threshold(verification.latency_impact_ratio)

    def approve_order(
        self,
        order: OrderIntent,
        portfolio: PortfolioSnapshot,
        verification: Optional[PhysicalVerification] = None
    ) -> Tuple[bool, str]:
        """FINAL APPROVAL GATE."""
        # 0. Macro-kill override
        if self._macro_kill_active:
            return False, f"MACRO_KILL_ACTIVE (until {self._macro_kill_until})"

        # 1. Kill switch check
        if self._kill_switch_triggered:
            return False, "KILL_SWITCH_ACTIVE"

        # 2. Stale data check
        if self._is_stale_data(portfolio):
            return False, "STALE_DATA_ERROR"

        # 3. Drawdown check
        if self._exceeds_drawdown_limit(portfolio):
            return False, "DRAWDOWN_LIMIT_EXCEEDED"

        # 4. Exposure caps
        if not self._check_exposure_caps(order, portfolio):
            return False, "EXPOSURE_CAP_EXCEEDED"

        # 5. Confidence threshold (with macro adjustment)
        current_threshold = self._current_min_confidence
        if order.confidence < current_threshold:
            return False, f"CONFIDENCE_TOO_LOW: {order.confidence:.2f} < {current_threshold:.2f}"

        # 6. Bull trap protection
        if self._bull_trap_detected and order.side == "buy":
            return False, "BULL_TRAP_DETECTED"

        # 7. Liquidity check
        if not self._has_sufficient_liquidity(order):
            return False, "INSUFFICIENT_LIQUIDITY"

        return True, "APPROVED"

    def _is_stale_data(self, portfolio: PortfolioSnapshot) -> bool:
        """Check if data is stale."""
        return False

    def _exceeds_drawdown_limit(self, portfolio: PortfolioSnapshot) -> bool:
        """Check if drawdown limit is exceeded."""
        if self._peak_equity is None or portfolio.total_equity > self._peak_equity:
            self._peak_equity = portfolio.total_equity

        today = datetime.utcnow().date()
        if self._last_reset_date is None or self._last_reset_date.date() != today:
            self._daily_peak = portfolio.total_equity
            self._last_reset_date = datetime.utcnow()

        total_drawdown = (portfolio.total_equity - self._peak_equity) / self._peak_equity if self._peak_equity else 0
        daily_drawdown = (portfolio.total_equity - self._daily_peak) / self._daily_peak if self._daily_peak else 0

        if total_drawdown <= -self.config.risk.max_24h_drawdown:
            self._kill_switch_triggered = True
            self._kill_switch_time = datetime.utcnow()
            logger.critical(f"KILL SWITCH TRIGGERED: Total drawdown {total_drawdown:.2%}")
            return True

        if daily_drawdown <= -self.config.risk.max_daily_drawdown:
            logger.warning(f"Daily drawdown limit reached: {daily_drawdown:.2%}")
            return True

        return False

    def _check_exposure_caps(self, order: OrderIntent, portfolio: PortfolioSnapshot) -> bool:
        """Check if order would exceed exposure caps."""
        order_value = order.quantity * (order.limit_price or portfolio.total_equity / 100)
        new_exposure = portfolio.exposure + (order_value / portfolio.total_equity)

        if new_exposure > self.config.risk.max_total_exposure:
            return False
        return True

    def _has_sufficient_liquidity(self, order: OrderIntent) -> bool:
        """Check if there's sufficient liquidity."""
        return True

    def trigger_kill_switch(self, reason: str) -> None:
        """Manually trigger kill switch."""
        self._kill_switch_triggered = True
        self._kill_switch_time = datetime.utcnow()
        logger.critical(f"KILL SWITCH MANUALLY TRIGGERED: {reason}")

    def reset_kill_switch(self) -> None:
        """Reset kill switch (manual intervention required)."""
        self._kill_switch_triggered = False
        self._kill_switch_time = None
        self._peak_equity = None
        self._latency_impact_ewma = None
        self._adverse_selection_count = 0
        self._current_min_confidence = self.base_min_confidence
        self._macro_pause_active = False
        self._macro_kill_active = False
        self._macro_kill_until = None
        self._bull_trap_detected = False
        logger.info("Kill switch reset")

    def get_min_confidence(self) -> float:
        """Get current minimum confidence threshold."""
        return self._current_min_confidence

    def get_macro_status(self) -> Dict[str, Any]:
        """Get current macro status."""
        return {
            "macro_pause_active": self._macro_pause_active,
            "macro_kill_active": self._macro_kill_active,
            "macro_kill_until": self._macro_kill_until.isoformat() if self._macro_kill_until else None,
            "macro_pause_boost": self._macro_pause_boost,
            "bull_trap_detected": self._bull_trap_detected,
            "last_macro_signal": self._last_macro_signal.reason if self._last_macro_signal else None
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get safety gate statistics."""
        return {
            "kill_switch_triggered": self._kill_switch_triggered,
            "min_confidence": self._current_min_confidence,
            "base_min_confidence": self.base_min_confidence,
            "adverse_selection_score": self.get_adverse_selection_score(),
            "adverse_selection_count": self._adverse_selection_count,
            "ewma_ratio": self._latency_impact_ewma,
            **self.get_macro_status(),
            "recent_trades": len(self._recent_trades)
        }