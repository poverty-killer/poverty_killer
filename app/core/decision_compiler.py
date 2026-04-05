"""
Decision Compiler for Sovereign Trading System

This module is the single authority for compiling deterministic decisions
from feature outputs, strategy votes, risk overlays, execution constraints,
and truth status. It produces an immutable DecisionRecord per cycle.

Boundaries:
- Owns: Decision compilation, DecisionRecord production
- Does NOT own: Feature computation (brain), strategy logic (strategies),
  risk decisions (risk system), truth reconciliation (truth_reconciler)
- Consumes: FeatureVector, StrategyVote, RiskDecision, TruthFrame
- Produces: DecisionRecord (with decision_type and outputs)

Stage 2 Implementation Status:
- Fully implemented: DecisionRecord creation with basic aggregation
- Deferred to Stage 3: Complex strategy vote fusion, multi-strategy selection
- Deferred to Stage 5: Full feature integration with brain components
"""

import logging
from typing import Optional, Dict, Any, List
from uuid import uuid4

from app.models.contracts import (
    DecisionRecord, FeatureVector, StrategyVote, RiskDecision, TruthFrame
)
from app.models.enums import DecisionType, RiskMode
from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)


class DecisionCompilerError(Exception):
    """Base exception for decision compiler errors."""
    pass


class DecisionCompilerStateError(DecisionCompilerError):
    """Raised when required inputs are missing for compilation."""
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


class DecisionCompiler:
    """
    Decision Compiler - Single authority for deterministic decisions.
    
    Features:
    - Aggregates feature vectors, strategy votes, risk decisions, truth status
    - Produces immutable DecisionRecord per cycle
    - Thread-safe (stateless per compilation)
    - Enforces that no decision is reinterpreted without a superseding record
    
    Stage 2: Basic aggregation only. Complex fusion (multi-strategy, weighted voting)
    is deferred to Stage 3.
    """
    
    def __init__(self):
        """Initialize decision compiler."""
        self._last_decision_uuid: Optional[str] = None
        logger.info("DecisionCompiler initialized")
    
    # ============================================
    # Main Compilation Entry Point
    # ============================================
    
    def compile(
        self,
        truth_frame: TruthFrame,
        feature_vectors: Optional[List[FeatureVector]] = None,
        strategy_votes: Optional[List[StrategyVote]] = None,
        risk_decision: Optional[RiskDecision] = None,
        additional_inputs: Optional[Dict[str, Any]] = None
    ) -> DecisionRecord:
        """
        Compile a deterministic decision from all inputs.
        
        Args:
            truth_frame: Current TruthFrame (required)
            feature_vectors: List of feature vectors from brain components
            strategy_votes: List of strategy votes
            risk_decision: Current risk decision
            additional_inputs: Any additional inputs for decision context
        
        Returns:
            Immutable DecisionRecord
        
        Raises:
            DecisionCompilerStateError: If truth_frame is missing
        """
        # Validate required inputs
        if truth_frame is None:
            raise DecisionCompilerStateError("truth_frame is required for decision compilation")
        
        timestamp_ns = now_ns()
        
        # Build inputs dictionary for traceability
        inputs: Dict[str, List[str]] = {}
        
        inputs["truth_frame"] = [truth_frame.truth_frame_id]
        
        if feature_vectors:
            inputs["feature_vectors"] = [fv.feature_vector_id for fv in feature_vectors]
        
        if strategy_votes:
            inputs["strategy_votes"] = [sv.vote_id for sv in strategy_votes]
        
        if risk_decision:
            inputs["risk_decision"] = [risk_decision.risk_decision_id]
        
        # Build outputs based on available inputs
        outputs = self._build_outputs(
            truth_frame=truth_frame,
            feature_vectors=feature_vectors,
            strategy_votes=strategy_votes,
            risk_decision=risk_decision,
            additional_inputs=additional_inputs
        )
        
        # Determine decision type based on actual inputs
        decision_type = self._determine_decision_type(
            strategy_votes=strategy_votes,
            risk_decision=risk_decision,
            feature_vectors=feature_vectors
        )
        
        # Create decision record
        decision_uuid = str(uuid4())
        self._last_decision_uuid = decision_uuid
        
        # Safely serialize metadata
        truth_status_str = _safe_str(truth_frame.status)
        risk_mode_str = _safe_str(risk_decision.risk_mode) if risk_decision else None
        
        record = DecisionRecord(
            decision_uuid=decision_uuid,
            timestamp_ns=timestamp_ns,
            decision_type=decision_type,
            inputs=inputs,
            outputs=outputs,
            metadata={
                "truth_status": truth_status_str,
                "risk_mode": risk_mode_str
            }
        )
        
        logger.debug(f"DecisionRecord created: {decision_uuid}, type={_safe_str(decision_type)}")
        return record
    
    # ============================================
    # Output Construction
    # ============================================
    
    def _build_outputs(
        self,
        truth_frame: TruthFrame,
        feature_vectors: Optional[List[FeatureVector]],
        strategy_votes: Optional[List[StrategyVote]],
        risk_decision: Optional[RiskDecision],
        additional_inputs: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Build outputs dictionary from inputs.
        
        Stage 2: Basic aggregation. Complex fusion deferred to Stage 3.
        """
        outputs: Dict[str, Any] = {}
        
        # Truth status (always included)
        outputs["truth_status"] = _safe_str(truth_frame.status)
        outputs["truth_frame_id"] = truth_frame.truth_frame_id
        
        # Risk mode (if available)
        if risk_decision:
            outputs["risk_mode"] = _safe_str(risk_decision.risk_mode)
            outputs["risk_decision_id"] = risk_decision.risk_decision_id
            outputs["sizing_multiplier"] = float(risk_decision.sizing_multiplier)
        
        # Strategy votes aggregation (simplified for Stage 2)
        if strategy_votes:
            outputs["strategy_votes_count"] = len(strategy_votes)
            # Stage 2: Simple aggregation - count votes by signal type
            signal_counts: Dict[str, int] = {"BUY": 0, "SELL": 0, "FLAT": 0, "NO_ACTION": 0}
            max_confidence = 0.0
            preferred_signal = "NO_ACTION"
            
            for vote in strategy_votes:
                signal_key = _safe_str(vote.signal)
                signal_counts[signal_key] = signal_counts.get(signal_key, 0) + 1
                if vote.confidence > max_confidence:
                    max_confidence = vote.confidence
                    preferred_signal = signal_key
            
            outputs["signal_counts"] = signal_counts
            outputs["preferred_signal"] = preferred_signal
            outputs["max_confidence"] = float(max_confidence)
        
        # Feature vectors summary (simplified for Stage 2)
        if feature_vectors:
            outputs["feature_vectors_count"] = len(feature_vectors)
            # Stage 2: No complex feature fusion
            # Safely extract features from the last vector if present
            if feature_vectors:
                latest_features = feature_vectors[-1].features
                # Handle both dataclass and dict formats safely
                if hasattr(latest_features, '__dict__'):
                    outputs["latest_features"] = {
                        k: float(v) if hasattr(v, '__float__') else str(v)
                        for k, v in latest_features.__dict__.items()
                        if v is not None
                    }
                elif isinstance(latest_features, dict):
                    outputs["latest_features"] = latest_features
                else:
                    outputs["latest_features"] = {}
        
        # Additional inputs
        if additional_inputs:
            outputs["additional"] = additional_inputs
        
        return outputs
    
    # ============================================
    # Decision Type Determination
    # ============================================
    
    def _determine_decision_type(
        self,
        strategy_votes: Optional[List[StrategyVote]],
        risk_decision: Optional[RiskDecision],
        feature_vectors: Optional[List[FeatureVector]]
    ) -> DecisionType:
        """
        Determine decision type based on actual inputs.
        
        Precedence (Stage 2):
        1. If risk_decision is present and indicates action, return RISK_APPROVAL
        2. Else if strategy_votes present, return STRATEGY_VOTE
        3. Else if feature_vectors present, return FEATURE_COMPUTE
        4. Else return FEATURE_COMPUTE (default)
        
        Returns:
            DecisionType enum value
        """
        # Check for risk decision that requires action
        if risk_decision is not None:
            # Any risk decision present indicates risk approval in Stage 2
            return DecisionType.RISK_APPROVAL
        
        # Check for strategy votes
        if strategy_votes:
            return DecisionType.STRATEGY_VOTE
        
        # Check for feature vectors
        if feature_vectors:
            return DecisionType.FEATURE_COMPUTE
        
        # Default to feature compute (no active inputs)
        return DecisionType.FEATURE_COMPUTE
    
    # ============================================
    # Query Methods
    # ============================================
    
    def get_last_decision_uuid(self) -> Optional[str]:
        """
        Get the UUID of the last compiled decision.
        
        Returns:
            Last decision UUID, or None if no decisions compiled
        """
        return self._last_decision_uuid
    
    # ============================================
    # Reset
    # ============================================
    
    def reset(self) -> None:
        """Reset decision compiler state."""
        self._last_decision_uuid = None
        logger.info("DecisionCompiler reset")


# ============================================
# Convenience Functions
# ============================================

def create_decision_compiler() -> DecisionCompiler:
    """
    Create a configured decision compiler.
    
    Returns:
        DecisionCompiler instance
    """
    return DecisionCompiler()


__all__ = [
    'DecisionCompiler',
    'DecisionCompilerError',
    'DecisionCompilerStateError',
    'create_decision_compiler',
]