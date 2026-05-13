"""
Truth Reconciler for Sovereign Trading System

This module performs snapshot-based reconciliation of the five truths
and detects divergence across truth domains.

Responsibilities:
- Compare five truths for consistency (snapshot-based)
- Detect divergence across truth domains
- Determine overall TruthStatus (RECONCILED, DRIFTING, BROKEN)
- Generate divergence reasons for reporting
- Provide status to TruthKernel for TruthFrame production

Boundaries:
- Owns: Divergence detection, status determination
- Does NOT own: Truth state (TruthKernel)
- Does NOT own: Invariant enforcement (invariant_checker.py)
- Does NOT own: Timing-based drift detection (deferred to Stage 2+)
- Consumes: Five truths as inputs, produces status and reasons

Note: This reconciler is snapshot-based. Timing-based drift detection
(divergence duration thresholds) is deferred to Stage 2+ enhancements
and will be implemented in the invariant checker layer.
"""

import logging
from typing import Callable, Optional, Tuple, List, Dict, Any
from dataclasses import dataclass

from app.models.contracts import (
    ExchangeTruth, ExecutionTruth, PortfolioTruth,
    StrategyTruth, RiskTruth
)
from app.models.enums import TruthStatus

logger = logging.getLogger(__name__)


class TruthReconcilerError(Exception):
    """Base exception for truth reconciler errors."""
    pass


_TERMINAL_STATUS_VALUES = {"filled", "cancelled", "canceled", "expired", "rejected"}
_UNKNOWN_STATUS_VALUES = {"", "unknown", "timeout", "rate_limited", "malformed"}

_REASON_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "broker_orphan_unresolved": {
        "recommended_action": "alert_only_board_review",
        "prohibited_actions": ["auto_cancel", "broker_repair", "exposure_release", "reservation_mutation"],
        "requires_board_decision": True,
    },
    "local_pending_unresolved": {
        "recommended_action": "guarded_status_refresh_or_board_review",
        "prohibited_actions": ["auto_terminalize", "exposure_release", "reservation_mutation"],
        "requires_board_decision": True,
    },
    "terminal_local_broker_open": {
        "recommended_action": "critical_alert_board_review",
        "prohibited_actions": ["auto_cancel", "broker_repair", "exposure_release", "reservation_mutation"],
        "requires_board_decision": True,
    },
    "broker_terminal_local_pending_requires_status_proof": {
        "recommended_action": "preserve_pending_until_board_policy",
        "prohibited_actions": ["auto_terminalize", "exposure_release", "reservation_mutation"],
        "requires_board_decision": True,
    },
    "missing_mapping_unresolved": {
        "recommended_action": "fail_closed_mapping_review",
        "prohibited_actions": ["live_command", "auto_cancel", "broker_repair"],
        "requires_board_decision": True,
    },
    "duplicate_mapping_conflict": {
        "recommended_action": "fail_closed_mapping_review",
        "prohibited_actions": ["live_command", "auto_cancel", "broker_repair"],
        "requires_board_decision": True,
    },
    "same_client_mapping_conflict": {
        "recommended_action": "fail_closed_mapping_review",
        "prohibited_actions": ["live_command", "auto_cancel", "broker_repair"],
        "requires_board_decision": True,
    },
    "paper_internal_client_mismatch": {
        "recommended_action": "preserve_client_command_namespace_and_review_mapping",
        "prohibited_actions": ["namespace_collapse", "live_command", "broker_repair"],
        "requires_board_decision": False,
    },
    "status_refresh_failed": {
        "recommended_action": "alert_only_retry_under_guard_or_board_review",
        "prohibited_actions": ["auto_terminalize", "auto_cancel", "exposure_release", "reservation_mutation"],
        "requires_board_decision": True,
    },
    "restart_recovery_needed": {
        "recommended_action": "operator_recovery_review",
        "prohibited_actions": ["pending_rebuild", "auto_cancel", "exposure_release", "reservation_mutation"],
        "requires_board_decision": True,
    },
}


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


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass
class DivergenceInfo:
    """Information about a detected divergence."""
    domain_pair: str
    field: str
    expected: Any
    observed: Any
    severity: str = "warning"  # "info", "warning", "critical"
    reason_code: Optional[str] = None
    symbol: Optional[str] = None
    client_order_id: Optional[str] = None
    venue: Optional[str] = None
    broker: Optional[str] = None
    order_id_namespace: Optional[str] = None
    command_id_namespace: Optional[str] = None
    command_order_id: Optional[str] = None
    mapping_status: Optional[str] = None
    recommended_action: Optional[str] = None
    prohibited_actions: Optional[List[str]] = None
    requires_board_decision: Optional[bool] = None

    def to_reason(self) -> str:
        """Convert to human-readable reason string."""
        return f"{self.domain_pair}: {self.field} mismatch (expected {self.expected}, got {self.observed})"

    def to_alert_evidence(self) -> Dict[str, Any]:
        """Return replayable alert-only evidence for this divergence."""
        reason_code = self.reason_code or self.field
        defaults = _REASON_DEFAULTS.get(reason_code, {})
        fact = {
            "reason_code": reason_code,
            "severity": self.severity,
            "symbol": self.symbol,
            "client_order_id": self.client_order_id,
            "venue": self.venue,
            "broker": self.broker,
            "order_id_namespace": self.order_id_namespace,
            "command_id_namespace": self.command_id_namespace,
            "command_order_id": self.command_order_id,
            "mapping_status": self.mapping_status,
            "recommended_action": self.recommended_action or defaults.get("recommended_action", "alert_only_review"),
            "prohibited_actions": (
                self.prohibited_actions
                if self.prohibited_actions is not None
                else list(defaults.get("prohibited_actions", ["command_action"]))
            ),
            "requires_board_decision": (
                self.requires_board_decision
                if self.requires_board_decision is not None
                else bool(defaults.get("requires_board_decision", False))
            ),
        }
        return {key: value for key, value in fact.items() if value is not None}


class TruthReconciler:
    """
    Truth Reconciler - Detects divergence across the five truths.
    
    Features:
    - Compares ExchangeTruth vs ExecutionTruth (order presence)
    - Compares ExchangeTruth vs PortfolioTruth (positions, balances)
    - Compares PortfolioTruth vs StrategyTruth (strategy expectations)
    - Compares StrategyTruth vs RiskTruth (risk mode compatibility)
    - Determines overall TruthStatus based on divergence severity
    - Thread-safe (stateless, pure functions)
    
    The reconciler is stateless; all divergence detection is performed
    on the provided truth snapshots.
    
    Timing-based drift detection (divergence duration thresholds) is
    deferred to the invariant checker layer in Stage 2+.
    """
    
    def __init__(self):
        """Initialize truth reconciler."""
        logger.info("TruthReconciler initialized (snapshot-based, no timing thresholds)")
    
    # ============================================
    # Reconciliation Methods
    # ============================================
    
    def reconcile(
        self,
        exchange_truth: ExchangeTruth,
        execution_truth: ExecutionTruth,
        portfolio_truth: PortfolioTruth,
        strategy_truth: StrategyTruth,
        risk_truth: RiskTruth,
        status_refresh: Optional[Callable[[str], str]] = None,
    ) -> Tuple[TruthStatus, List[str]]:
        """
        Reconcile the five truths and determine status.
        
        Args:
            exchange_truth: Exchange truth snapshot
            execution_truth: Execution truth snapshot
            portfolio_truth: Portfolio truth snapshot
            strategy_truth: Strategy truth snapshot
            risk_truth: Risk truth snapshot
        
        Returns:
            Tuple of (TruthStatus, list of divergence reasons)
        """
        divergences: List[DivergenceInfo] = []
        
        # Compare Exchange vs Execution
        divergences.extend(self._compare_exchange_execution(
            exchange_truth,
            execution_truth,
            status_refresh=status_refresh,
        ))
        
        # Compare Exchange vs Portfolio
        divergences.extend(self._compare_exchange_portfolio(exchange_truth, portfolio_truth))
        
        # Compare Portfolio vs Strategy
        divergences.extend(self._compare_portfolio_strategy(portfolio_truth, strategy_truth))
        
        # Compare Strategy vs Risk
        divergences.extend(self._compare_strategy_risk(strategy_truth, risk_truth))
        
        # Determine status based on divergences
        status, reasons = self._determine_status(divergences)
        
        # Log critical divergences
        for d in divergences:
            if d.severity == "critical":
                logger.warning(f"Critical divergence: {d.to_reason()}")
        
        return status, reasons
    
    def get_truth_status(
        self,
        exchange_truth: ExchangeTruth,
        execution_truth: ExecutionTruth,
        portfolio_truth: PortfolioTruth,
        strategy_truth: StrategyTruth,
        risk_truth: RiskTruth,
        status_refresh: Optional[Callable[[str], str]] = None,
    ) -> Tuple[TruthStatus, List[str]]:
        """
        Alias for reconcile() for compatibility with TruthKernel.
        
        Args:
            exchange_truth: Exchange truth snapshot
            execution_truth: Execution truth snapshot
            portfolio_truth: Portfolio truth snapshot
            strategy_truth: Strategy truth snapshot
            risk_truth: Risk truth snapshot
        
        Returns:
            Tuple of (TruthStatus, list of divergence reasons)
        """
        return self.reconcile(
            exchange_truth=exchange_truth,
            execution_truth=execution_truth,
            portfolio_truth=portfolio_truth,
            strategy_truth=strategy_truth,
            risk_truth=risk_truth,
            status_refresh=status_refresh,
        )

    def build_alert_evidence(
        self,
        exchange_truth: ExchangeTruth,
        execution_truth: ExecutionTruth,
        portfolio_truth: PortfolioTruth,
        strategy_truth: StrategyTruth,
        risk_truth: RiskTruth,
        status_refresh: Optional[Callable[[str], str]] = None,
    ) -> List[Dict[str, Any]]:
        """Build alert-only reconcile evidence without command authority."""
        divergences: List[DivergenceInfo] = []
        divergences.extend(self._compare_exchange_execution(
            exchange_truth,
            execution_truth,
            status_refresh=status_refresh,
        ))
        divergences.extend(self._compare_exchange_portfolio(exchange_truth, portfolio_truth))
        divergences.extend(self._compare_portfolio_strategy(portfolio_truth, strategy_truth))
        divergences.extend(self._compare_strategy_risk(strategy_truth, risk_truth))
        return [d.to_alert_evidence() for d in divergences]
    
    # ============================================
    # Domain Pair Comparisons
    # ============================================
    
    def _compare_exchange_execution(
        self,
        exchange: ExchangeTruth,
        execution: ExecutionTruth,
        status_refresh: Optional[Callable[[str], str]] = None,
    ) -> List[DivergenceInfo]:
        """
        Compare ExchangeTruth vs ExecutionTruth.
        
        Detects:
        - Orders acknowledged by exchange but not recorded by execution
        - Orders recorded by execution but not acknowledged by exchange
        """
        divergences: List[DivergenceInfo] = []
        
        # Compare explicit client IDs only. Raw exchange order IDs may be
        # exchange_txid, venue_order_id, broker_order_id, or paper proof IDs.
        exchange_client_ids = set()
        exchange_orders_by_client: Dict[str, ExchangeOpenOrder] = {}
        execution_order_ids = {order.client_order_id for order in execution.submitted_orders}

        for order in exchange.open_orders:
            client_order_id = _optional_str(getattr(order, "client_order_id", None))
            mapping_status = _optional_str(getattr(order, "mapping_status", None))
            order_namespace = _optional_str(getattr(order, "order_id_namespace", None)) or "unknown"
            raw_order_id = _optional_str(getattr(order, "order_id", None)) or "unknown"
            command_namespace = _optional_str(getattr(order, "command_id_namespace", None))
            command_order_id = _optional_str(getattr(order, "command_order_id", None))
            symbol = _optional_str(getattr(order, "symbol", None))
            broker = _optional_str(getattr(order, "broker", None)) or _optional_str(getattr(exchange, "venue", None))

            if client_order_id:
                exchange_client_ids.add(client_order_id)
                exchange_orders_by_client[client_order_id] = order

            if mapping_status == "terminal_local_broker_open":
                divergences.append(DivergenceInfo(
                    domain_pair="exchange/execution",
                    field="terminal_local_broker_open",
                    expected=f"terminal local mapping not open at broker for client {client_order_id}",
                    observed=f"broker open order {order_namespace}:{raw_order_id}",
                    severity="critical",
                    reason_code="terminal_local_broker_open",
                    symbol=symbol,
                    client_order_id=client_order_id,
                    venue=_optional_str(getattr(exchange, "venue", None)),
                    broker=broker,
                    order_id_namespace=order_namespace,
                    command_id_namespace=command_namespace,
                    command_order_id=command_order_id,
                    mapping_status=mapping_status,
                ))
                continue

            if mapping_status in {
                "missing_mapping_unresolved",
                "duplicate_mapping_conflict",
                "same_client_mapping_conflict",
                "broker_terminal_local_pending_requires_status_proof",
                "status_refresh_failed",
                "restart_recovery_needed",
            }:
                divergences.append(DivergenceInfo(
                    domain_pair="exchange/execution",
                    field=mapping_status,
                    expected="command-safe order ID mapping",
                    observed=f"{mapping_status} for {order_namespace}:{raw_order_id}",
                    severity="critical" if mapping_status in {
                        "duplicate_mapping_conflict",
                        "same_client_mapping_conflict",
                    } else "warning",
                    reason_code=mapping_status,
                    symbol=symbol,
                    client_order_id=client_order_id,
                    venue=_optional_str(getattr(exchange, "venue", None)),
                    broker=broker,
                    order_id_namespace=order_namespace,
                    command_id_namespace=command_namespace,
                    command_order_id=command_order_id,
                    mapping_status=mapping_status,
                ))
                continue

            if (
                order_namespace == "paper_broker_internal_order_id"
                and command_namespace == "client_order_id"
                and client_order_id
                and command_order_id
                and command_order_id != client_order_id
            ):
                divergences.append(DivergenceInfo(
                    domain_pair="exchange/execution",
                    field="paper_internal_client_mismatch",
                    expected=f"paper command_order_id {client_order_id}",
                    observed=f"paper command_order_id {command_order_id}",
                    severity="warning",
                    reason_code="paper_internal_client_mismatch",
                    symbol=symbol,
                    client_order_id=client_order_id,
                    venue=_optional_str(getattr(exchange, "venue", None)),
                    broker=broker,
                    order_id_namespace=order_namespace,
                    command_id_namespace=command_namespace,
                    command_order_id=command_order_id,
                    mapping_status=mapping_status,
                ))

            if not client_order_id:
                divergences.append(DivergenceInfo(
                    domain_pair="exchange/execution",
                    field="broker_orphan_unresolved",
                    expected="broker open order resolved to local client_order_id",
                    observed=f"unmapped broker open order {order_namespace}:{raw_order_id}",
                    severity="warning",
                    reason_code="broker_orphan_unresolved",
                    symbol=symbol,
                    venue=_optional_str(getattr(exchange, "venue", None)),
                    broker=broker,
                    order_id_namespace=order_namespace,
                    command_id_namespace=command_namespace,
                    command_order_id=command_order_id,
                    mapping_status=mapping_status,
                ))

        # Orders in exchange but not in execution after namespace normalization.
        missing_in_execution = exchange_client_ids - execution_order_ids
        for client_order_id in missing_in_execution:
            order = exchange_orders_by_client.get(client_order_id)
            mapping_status = _optional_str(getattr(order, "mapping_status", None)) if order else None
            reason_code = "restart_recovery_needed" if mapping_status == "mapped" else "broker_orphan_unresolved"
            divergences.append(DivergenceInfo(
                domain_pair="exchange/execution",
                field=reason_code,
                expected=f"client order {client_order_id} in execution",
                observed=f"client order {client_order_id} only in exchange",
                severity="warning",
                reason_code=reason_code,
                symbol=_optional_str(getattr(order, "symbol", None)) if order else None,
                client_order_id=client_order_id,
                venue=_optional_str(getattr(exchange, "venue", None)),
                broker=_optional_str(getattr(exchange, "venue", None)),
                order_id_namespace=_optional_str(getattr(order, "order_id_namespace", None)) if order else None,
                command_id_namespace=_optional_str(getattr(order, "command_id_namespace", None)) if order else None,
                command_order_id=_optional_str(getattr(order, "command_order_id", None)) if order else None,
                mapping_status=mapping_status,
            ))

        # Orders in execution but not in normalized exchange open orders.
        missing_in_exchange = execution_order_ids - exchange_client_ids
        for client_order_id in missing_in_exchange:
            divergences.append(DivergenceInfo(
                domain_pair="exchange/execution",
                field="local_pending_unresolved",
                expected=f"client order {client_order_id} acknowledged/open at broker",
                observed=f"client order {client_order_id} only in execution",
                severity="critical",
                reason_code="local_pending_unresolved",
                client_order_id=client_order_id,
                venue=_optional_str(getattr(exchange, "venue", None)),
                broker=_optional_str(getattr(exchange, "venue", None)),
            ))
            if status_refresh is None:
                continue
            try:
                status_result = status_refresh(client_order_id)
            except Exception as exc:
                refreshed_status = "unknown"
                observed = f"status refresh exception: {exc.__class__.__name__}"
            else:
                if isinstance(status_result, dict):
                    refreshed_status = _safe_str(
                        status_result.get("status_classification")
                        or status_result.get("status_raw")
                        or "unknown"
                    ).lower()
                    observed = f"guarded status evidence returned {refreshed_status}"
                else:
                    refreshed_status = _safe_str(status_result).lower()
                    observed = f"guarded status refresh returned {refreshed_status}"

            if refreshed_status == "terminal_observed" or refreshed_status in _TERMINAL_STATUS_VALUES:
                divergences.append(DivergenceInfo(
                    domain_pair="exchange/execution",
                    field="broker_terminal_local_pending_requires_status_proof",
                    expected="local pending preserved until board-approved terminal policy",
                    observed=observed,
                    severity="warning",
                    reason_code="broker_terminal_local_pending_requires_status_proof",
                    client_order_id=client_order_id,
                    venue=_optional_str(getattr(exchange, "venue", None)),
                    broker=_optional_str(getattr(exchange, "venue", None)),
                ))
            elif refreshed_status in {
                "unknown_or_failed",
                "mapping_missing_or_unsafe",
                "broker_orphan_no_mapping",
                *_UNKNOWN_STATUS_VALUES,
            }:
                divergences.append(DivergenceInfo(
                    domain_pair="exchange/execution",
                    field="status_refresh_failed",
                    expected="guarded status refresh returned readable non-terminal status",
                    observed=observed,
                    severity="warning",
                    reason_code="status_refresh_failed",
                    client_order_id=client_order_id,
                    venue=_optional_str(getattr(exchange, "venue", None)),
                    broker=_optional_str(getattr(exchange, "venue", None)),
                ))
        
        return divergences
    
    def _compare_exchange_portfolio(
        self,
        exchange: ExchangeTruth,
        portfolio: PortfolioTruth
    ) -> List[DivergenceInfo]:
        """
        Compare ExchangeTruth vs PortfolioTruth.
        
        Detects:
        - Position quantity mismatches
        - Balance mismatches
        """
        divergences: List[DivergenceInfo] = []
        
        # Build position maps
        exchange_positions = {pos.symbol: pos for pos in exchange.positions}
        portfolio_positions = {pos.symbol: pos for pos in portfolio.positions}
        
        all_symbols = set(exchange_positions.keys()) | set(portfolio_positions.keys())
        
        for symbol in all_symbols:
            exchange_pos = exchange_positions.get(symbol)
            portfolio_pos = portfolio_positions.get(symbol)
            
            if exchange_pos is None and portfolio_pos is not None:
                divergences.append(DivergenceInfo(
                    domain_pair="exchange/portfolio",
                    field=f"position.{symbol}",
                    expected="no position",
                    observed=f"position {portfolio_pos.quantity} in portfolio",
                    severity="critical"
                ))
            elif exchange_pos is not None and portfolio_pos is None:
                divergences.append(DivergenceInfo(
                    domain_pair="exchange/portfolio",
                    field=f"position.{symbol}",
                    expected=f"position {exchange_pos.quantity} in exchange",
                    observed="no position in portfolio",
                    severity="critical"
                ))
            elif exchange_pos is not None and portfolio_pos is not None:
                # Compare quantities (allow small tolerance for rounding)
                qty_diff = abs(exchange_pos.quantity - portfolio_pos.quantity)
                if qty_diff > 0.00000001:  # 1e-8 tolerance for crypto
                    divergences.append(DivergenceInfo(
                        domain_pair="exchange/portfolio",
                        field=f"position.{symbol}.quantity",
                        expected=exchange_pos.quantity,
                        observed=portfolio_pos.quantity,
                        severity="critical"
                    ))
        
        # Compare cash balances
        for currency in set(exchange.balances.keys()) | set(portfolio.cash.keys()):
            exchange_balance = exchange.balances.get(currency, 0)
            portfolio_cash = portfolio.cash.get(currency, 0)
            balance_diff = abs(exchange_balance - portfolio_cash)
            if balance_diff > 0.01:  # $0.01 tolerance for USD, 1e-8 for crypto
                divergences.append(DivergenceInfo(
                    domain_pair="exchange/portfolio",
                    field=f"balance.{currency}",
                    expected=exchange_balance,
                    observed=portfolio_cash,
                    severity="critical"
                ))
        
        return divergences
    
    def _compare_portfolio_strategy(
        self,
        portfolio: PortfolioTruth,
        strategy: StrategyTruth
    ) -> List[DivergenceInfo]:
        """
        Compare PortfolioTruth vs StrategyTruth.
        
        Detects:
        - Strategy expects position that portfolio doesn't have
        - Portfolio has position that strategy doesn't expect
        
        Note: This is a simplified snapshot-based check. Full reconciliation
        requires strategy-symbol mapping and will be enhanced in Stage 3.
        """
        divergences: List[DivergenceInfo] = []
        
        # Build set of strategy IDs that claim to be in position
        active_strategies_with_exposure = [
            s.strategy_id for s in strategy.active_strategies
            if s.entry_price is not None and s.current_exposure > 0
        ]
        
        # Check if any strategy expects exposure when portfolio has no positions
        if active_strategies_with_exposure and not portfolio.positions:
            divergences.append(DivergenceInfo(
                domain_pair="portfolio/strategy",
                field="strategy_expectations",
                expected=f"strategies {active_strategies_with_exposure} expect positions",
                observed="no positions in portfolio",
                severity="warning"
            ))
        
        # Check if portfolio has positions when no strategies claim to be active
        if portfolio.positions and not active_strategies_with_exposure:
            divergences.append(DivergenceInfo(
                domain_pair="portfolio/strategy",
                field="portfolio_positions",
                expected="no active strategies expecting positions",
                observed=f"{len(portfolio.positions)} positions in portfolio",
                severity="warning"
            ))
        
        return divergences
    
    def _compare_strategy_risk(
        self,
        strategy: StrategyTruth,
        risk: RiskTruth
    ) -> List[DivergenceInfo]:
        """
        Compare StrategyTruth vs RiskTruth.
        
        Detects:
        - Strategy active when risk is HARD_FLAT
        - Strategy risk appetite exceeds risk limits
        
        Note: Risk appetite comparison is simplified for Stage 2.
        Full risk limit enforcement belongs in invariant_checker.py.
        """
        divergences: List[DivergenceInfo] = []
        
        # Safely get risk mode string
        risk_mode_str = _safe_str(risk.mode)
        
        # Check if any strategy is active when risk is HARD_FLAT
        if risk_mode_str == "hard_flat" and strategy.active_strategies:
            divergences.append(DivergenceInfo(
                domain_pair="strategy/risk",
                field="active_strategies",
                expected="no active strategies in HARD_FLAT mode",
                observed=f"{len(strategy.active_strategies)} active strategies",
                severity="critical"
            ))
        
        # Check if any strategy exposure exceeds risk max leverage
        for strat in strategy.active_strategies:
            if strat.current_exposure > risk.max_leverage:
                divergences.append(DivergenceInfo(
                    domain_pair="strategy/risk",
                    field=f"strategy.{strat.strategy_id}.exposure",
                    expected=f"exposure <= {risk.max_leverage}",
                    observed=strat.current_exposure,
                    severity="warning"
                ))
        
        return divergences
    
    # ============================================
    # Status Determination
    # ============================================
    
    def _determine_status(
        self,
        divergences: List[DivergenceInfo]
    ) -> Tuple[TruthStatus, List[str]]:
        """
        Determine overall TruthStatus based on divergence severity.
        
        Rules:
        - No divergences: RECONCILED
        - Warnings only: DRIFTING
        - Critical divergences: BROKEN
        
        Note: Timing-based drift detection (divergence duration) is deferred
        to the invariant checker layer in Stage 2+.
        
        Args:
            divergences: List of detected divergences
        
        Returns:
            Tuple of (TruthStatus, list of reason strings)
        """
        reasons = [d.to_reason() for d in divergences]
        
        critical_divergences = [d for d in divergences if d.severity == "critical"]
        warning_divergences = [d for d in divergences if d.severity == "warning"]
        
        if critical_divergences:
            return TruthStatus.BROKEN, reasons
        
        if warning_divergences:
            return TruthStatus.DRIFTING, reasons
        
        return TruthStatus.RECONCILED, reasons
    
    def is_reconciled(self, status: TruthStatus) -> bool:
        """
        Check if status indicates reconciled state.
        
        Args:
            status: TruthStatus to check
        
        Returns:
            True if status is RECONCILED
        """
        return status == TruthStatus.RECONCILED
    
    def is_drifting(self, status: TruthStatus) -> bool:
        """
        Check if status indicates drifting state.
        
        Args:
            status: TruthStatus to check
        
        Returns:
            True if status is DRIFTING
        """
        return status == TruthStatus.DRIFTING
    
    def is_broken(self, status: TruthStatus) -> bool:
        """
        Check if status indicates broken state.
        
        Args:
            status: TruthStatus to check
        
        Returns:
            True if status is BROKEN
        """
        return status == TruthStatus.BROKEN


# ============================================
# Convenience Functions
# ============================================

def create_truth_reconciler() -> TruthReconciler:
    """
    Create a configured truth reconciler.
    
    Returns:
        Configured TruthReconciler instance
    """
    return TruthReconciler()


__all__ = [
    'TruthReconciler',
    'TruthReconcilerError',
    'DivergenceInfo',
    'create_truth_reconciler',
]
