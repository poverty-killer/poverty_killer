"""
Truth Kernel for Sovereign Trading System

This module manages the five truths of the system and produces deterministic
TruthFrame snapshots at regular intervals.

Five Truths:
- ExchangeTruth: What the exchange believes exists
- ExecutionTruth: What the execution layer believes
- PortfolioTruth: What the internal ledger believes
- StrategyTruth: What each strategy believes
- RiskTruth: What the risk system permits

Boundaries:
- Owns: Truth state aggregation, TruthFrame production
- Does NOT own: Reconciliation logic (truth_reconciler.py)
- Does NOT own: Invariant enforcement (invariant_checker.py)
"""

import logging
import threading
from typing import Optional, Dict, Any, Callable, Tuple
from dataclasses import dataclass

from app.models.contracts import (
    TruthFrame, ExchangeTruth, ExecutionTruth, PortfolioTruth,
    StrategyTruth, RiskTruth
)
from app.models.enums import TruthStatus
from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)


class TruthKernelError(Exception):
    """Base exception for truth kernel errors."""
    pass


class TruthKernelStateError(TruthKernelError):
    """Raised when kernel state is invalid."""
    pass


def _safe_str(value: Any) -> str:
    """
    Safely convert enum or string to string representation.
    
    Args:
        value: Value that may be an enum or string
    
    Returns:
        String representation
    """
    if hasattr(value, "value"):
        return value.value
    return str(value)


@dataclass
class TruthKernelState:
    """
    Internal state of the truth kernel.
    Holds the latest truth from each domain.
    """
    exchange_truth: Optional[ExchangeTruth] = None
    execution_truth: Optional[ExecutionTruth] = None
    portfolio_truth: Optional[PortfolioTruth] = None
    strategy_truth: Optional[StrategyTruth] = None
    risk_truth: Optional[RiskTruth] = None
    last_truth_frame_id: Optional[str] = None
    last_frame_timestamp_ns: int = 0
    frame_count: int = 0

    def has_all_truths(self) -> bool:
        """Check if all five truths have been set."""
        return all([
            self.exchange_truth is not None,
            self.execution_truth is not None,
            self.portfolio_truth is not None,
            self.strategy_truth is not None,
            self.risk_truth is not None
        ])


class TruthKernel:
    """
    Truth Kernel - Aggregates and manages the five truths.
    
    Features:
    - Maintains current state of all five truths
    - Produces deterministic TruthFrame snapshots
    - Supports update callbacks for each truth domain
    - Thread-safe state management
    
    The kernel does NOT perform reconciliation. It delegates divergence
    detection and truth status determination to the truth_reconciler
    when provided via create_truth_frame_from_reconciler.
    """
    
    def __init__(self):
        """Initialize truth kernel."""
        self._state = TruthKernelState()
        self._lock = threading.RLock()
        self._frame_callbacks: list[Callable[[TruthFrame], None]] = []
        
        logger.info("TruthKernel initialized")
    
    # ============================================
    # Truth Updates
    # ============================================
    
    def update_exchange_truth(self, exchange_truth: ExchangeTruth) -> None:
        """
        Update exchange truth.
        
        Args:
            exchange_truth: Current exchange truth snapshot
        """
        with self._lock:
            self._state.exchange_truth = exchange_truth
            logger.debug(f"ExchangeTruth updated: venue={exchange_truth.venue}")
    
    def update_execution_truth(self, execution_truth: ExecutionTruth) -> None:
        """
        Update execution truth.
        
        Args:
            execution_truth: Current execution truth snapshot
        """
        with self._lock:
            self._state.execution_truth = execution_truth
            logger.debug(f"ExecutionTruth updated: orders={len(execution_truth.submitted_orders)}")
    
    def update_portfolio_truth(self, portfolio_truth: PortfolioTruth) -> None:
        """
        Update portfolio truth.
        
        Args:
            portfolio_truth: Current portfolio truth snapshot
        """
        with self._lock:
            self._state.portfolio_truth = portfolio_truth
            logger.debug(f"PortfolioTruth updated: equity={portfolio_truth.total_equity}")
    
    def update_strategy_truth(self, strategy_truth: StrategyTruth) -> None:
        """
        Update strategy truth.
        
        Args:
            strategy_truth: Current strategy truth snapshot
        """
        with self._lock:
            self._state.strategy_truth = strategy_truth
            logger.debug(f"StrategyTruth updated: strategies={len(strategy_truth.active_strategies)}")
    
    def update_risk_truth(self, risk_truth: RiskTruth) -> None:
        """
        Update risk truth.
        
        Args:
            risk_truth: Current risk truth snapshot
        """
        with self._lock:
            self._state.risk_truth = risk_truth
            mode_str = _safe_str(risk_truth.mode)
            logger.debug(f"RiskTruth updated: mode={mode_str}")
    
    # ============================================
    # TruthFrame Production
    # ============================================
    
    def get_current_truths(self) -> Dict[str, Any]:
        """
        Get current state of all five truths.
        
        Returns:
            Dictionary containing current truth states
        
        Raises:
            TruthKernelStateError: If not all truths have been set
        """
        with self._lock:
            if not self._state.has_all_truths():
                missing = []
                if self._state.exchange_truth is None:
                    missing.append("exchange")
                if self._state.execution_truth is None:
                    missing.append("execution")
                if self._state.portfolio_truth is None:
                    missing.append("portfolio")
                if self._state.strategy_truth is None:
                    missing.append("strategy")
                if self._state.risk_truth is None:
                    missing.append("risk")
                
                raise TruthKernelStateError(
                    f"Cannot produce TruthFrame: missing truths: {', '.join(missing)}"
                )
            
            return {
                "exchange": self._state.exchange_truth,
                "execution": self._state.execution_truth,
                "portfolio": self._state.portfolio_truth,
                "strategy": self._state.strategy_truth,
                "risk": self._state.risk_truth
            }
    
    def create_truth_frame(
        self,
        status: TruthStatus,
        divergence_ns: int = 0,
        divergence_reasons: Optional[list[str]] = None
    ) -> TruthFrame:
        """
        Create a TruthFrame from current state with explicit status.
        
        This method produces a deterministic snapshot of all five truths.
        The caller must provide the reconciliation status.
        
        Args:
            status: Reconciliation status of this frame
            divergence_ns: Duration of divergence in nanoseconds
            divergence_reasons: List of divergence reasons
        
        Returns:
            TruthFrame containing current truth snapshots
        
        Raises:
            TruthKernelStateError: If not all truths have been set
        """
        with self._lock:
            truths = self.get_current_truths()
            
            timestamp_ns = now_ns()
            self._state.frame_count += 1
            self._state.last_frame_timestamp_ns = timestamp_ns
            
            frame = TruthFrame(
                timestamp_ns=timestamp_ns,
                exchange_truth=truths["exchange"],
                execution_truth=truths["execution"],
                portfolio_truth=truths["portfolio"],
                strategy_truth=truths["strategy"],
                risk_truth=truths["risk"],
                status=status,
                divergence_ns=divergence_ns,
                divergence_reasons=divergence_reasons or []
            )
            
            self._state.last_truth_frame_id = frame.truth_frame_id
            
            status_str = _safe_str(status)
            logger.debug(f"TruthFrame created: id={frame.truth_frame_id}, status={status_str}")
            
            # Notify callbacks
            for callback in self._frame_callbacks:
                try:
                    callback(frame)
                except Exception as e:
                    logger.error(f"TruthFrame callback failed: {e}")
            
            return frame
    
    def create_truth_frame_from_reconciler(
        self,
        reconciler: Any,
        divergence_ns: int = 0
    ) -> TruthFrame:
        """
        Create a TruthFrame using a reconciler to determine status.
        
        This method delegates divergence detection and status determination
        to the provided reconciler. The reconciler MUST implement the
        get_truth_status method.
        
        Args:
            reconciler: Truth reconciler with get_truth_status() method
            divergence_ns: Duration of divergence if known
        
        Returns:
            TruthFrame with status determined by reconciler
        
        Raises:
            TruthKernelStateError: If reconciler is missing required method
            TruthKernelStateError: If not all truths have been set
        """
        with self._lock:
            # Validate reconciler interface
            if not hasattr(reconciler, 'get_truth_status'):
                raise TruthKernelStateError(
                    "Reconciler missing required method 'get_truth_status'"
                )
            
            if not callable(getattr(reconciler, 'get_truth_status')):
                raise TruthKernelStateError(
                    "Reconciler.get_truth_status is not callable"
                )
            
            truths = self.get_current_truths()
            
            # Delegate to reconciler for status determination
            try:
                status, reasons = reconciler.get_truth_status(
                    exchange_truth=truths["exchange"],
                    execution_truth=truths["execution"],
                    portfolio_truth=truths["portfolio"],
                    strategy_truth=truths["strategy"],
                    risk_truth=truths["risk"]
                )
            except Exception as e:
                raise TruthKernelStateError(
                    f"Reconciler.get_truth_status failed: {e}"
                )
            
            timestamp_ns = now_ns()
            self._state.frame_count += 1
            self._state.last_frame_timestamp_ns = timestamp_ns
            
            frame = TruthFrame(
                timestamp_ns=timestamp_ns,
                exchange_truth=truths["exchange"],
                execution_truth=truths["execution"],
                portfolio_truth=truths["portfolio"],
                strategy_truth=truths["strategy"],
                risk_truth=truths["risk"],
                status=status,
                divergence_ns=divergence_ns,
                divergence_reasons=reasons
            )
            
            self._state.last_truth_frame_id = frame.truth_frame_id
            
            status_str = _safe_str(status)
            logger.debug(f"TruthFrame created via reconciler: id={frame.truth_frame_id}, status={status_str}")
            
            # Notify callbacks
            for callback in self._frame_callbacks:
                try:
                    callback(frame)
                except Exception as e:
                    logger.error(f"TruthFrame callback failed: {e}")
            
            return frame
    
    # ============================================
    # State Inspection
    # ============================================
    
    def has_all_truths(self) -> bool:
        """
        Check if all five truths have been set.
        
        Returns:
            True if all truths are present
        """
        with self._lock:
            return self._state.has_all_truths()
    
    def get_last_truth_frame_id(self) -> Optional[str]:
        """
        Get the ID of the last produced TruthFrame.
        
        Returns:
            Last TruthFrame ID, or None if no frames produced
        """
        with self._lock:
            return self._state.last_truth_frame_id
    
    def get_last_frame_timestamp_ns(self) -> int:
        """
        Get the timestamp of the last produced TruthFrame.
        
        Returns:
            Timestamp in nanoseconds, or 0 if no frames produced
        """
        with self._lock:
            return self._state.last_frame_timestamp_ns
    
    def get_frame_count(self) -> int:
        """
        Get the number of TruthFrames produced.
        
        Returns:
            Frame count
        """
        with self._lock:
            return self._state.frame_count
    
    def get_current_exchange_truth(self) -> Optional[ExchangeTruth]:
        """Get current exchange truth."""
        with self._lock:
            return self._state.exchange_truth
    
    def get_current_execution_truth(self) -> Optional[ExecutionTruth]:
        """Get current execution truth."""
        with self._lock:
            return self._state.execution_truth
    
    def get_current_portfolio_truth(self) -> Optional[PortfolioTruth]:
        """Get current portfolio truth."""
        with self._lock:
            return self._state.portfolio_truth
    
    def get_current_strategy_truth(self) -> Optional[StrategyTruth]:
        """Get current strategy truth."""
        with self._lock:
            return self._state.strategy_truth
    
    def get_current_risk_truth(self) -> Optional[RiskTruth]:
        """Get current risk truth."""
        with self._lock:
            return self._state.risk_truth
    
    # ============================================
    # Callbacks
    # ============================================
    
    def register_frame_callback(self, callback: Callable[[TruthFrame], None]) -> None:
        """
        Register a callback to be called when a TruthFrame is produced.
        
        Args:
            callback: Function that accepts a TruthFrame
        """
        with self._lock:
            self._frame_callbacks.append(callback)
            logger.debug(f"Registered TruthFrame callback: {callback.__name__}")
    
    # ============================================
    # Reset
    # ============================================
    
    def reset(self) -> None:
        """Reset truth kernel state."""
        with self._lock:
            self._state = TruthKernelState()
            self._frame_callbacks.clear()
            logger.info("TruthKernel reset")
    
    def reset_truth(self, truth_name: str) -> None:
        """
        Reset a specific truth.
        
        Args:
            truth_name: One of 'exchange', 'execution', 'portfolio', 'strategy', 'risk'
        
        Raises:
            ValueError: If truth_name is invalid
        """
        with self._lock:
            if truth_name == 'exchange':
                self._state.exchange_truth = None
            elif truth_name == 'execution':
                self._state.execution_truth = None
            elif truth_name == 'portfolio':
                self._state.portfolio_truth = None
            elif truth_name == 'strategy':
                self._state.strategy_truth = None
            elif truth_name == 'risk':
                self._state.risk_truth = None
            else:
                raise ValueError(f"Invalid truth name: {truth_name}")
            
            logger.info(f"Reset {truth_name} truth")


# ============================================
# Convenience Functions
# ============================================

def create_truth_kernel() -> TruthKernel:
    """
    Create and initialize a truth kernel.
    
    Returns:
        Configured TruthKernel instance
    """
    return TruthKernel()


__all__ = [
    'TruthKernel',
    'TruthKernelError',
    'TruthKernelStateError',
    'create_truth_kernel',
]