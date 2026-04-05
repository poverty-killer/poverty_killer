"""
Replay Engine for Sovereign Trading System

This module orchestrates deterministic replay execution by composing
the approved replay components. It is the entry point for replay operations.

Engine Boundaries:
- Orchestration only: coordinates components, manages lifecycle, routes events
- Does NOT perform: source reading, normalization, cursor tracking, verification,
  or checkpoint persistence
- Verification is delegated to ReplaySession when in VERIFY mode
- Engine tracks actual encountered expected entries for honest verified_events count

Replay Modes:
- REPLAY: Execute session, emit events to consumer, no verification
- VERIFY: Execute session with built-in verification (ReplaySession handles this)
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any, Union, Callable

from app.replay.source import open_replay_source
from app.replay.replay_session import ReplaySession, replay_session, verify_replay_session
from app.replay.verifier import VerificationResult
from app.replay.checkpoint import ReplayCheckpointManager, create_checkpoint_manager
from app.models.contracts import EventEnvelope, ReplayPosition
from app.models.enums import ReplayMode, CheckpointType
from app.utils.time_utils import set_replay_time_ns, clear_replay_time, ReplayTimeContext

logger = logging.getLogger(__name__)


class ReplayEngineError(Exception):
    """Base exception for replay engine errors."""
    pass


class ReplayEngine:
    """
    Deterministic replay engine orchestrator.
    
    Composes specialized components to provide a clean interface for replay operations.
    
    Features:
    - REPLAY mode: deterministic event iteration with consumer callback
    - VERIFY mode: deterministic iteration with built-in verification (ReplaySession)
    - Checkpoint persistence for crash recovery
    - Session management with lifecycle events
    - Honest verified_events count (actual encountered expected entries)
    
    All deterministic behavior is delegated to the approved replay components.
    """
    
    def __init__(
        self,
        source_path: Union[str, Path],
        replay_mode: ReplayMode = ReplayMode.REPLAY,
        source_identifier: Optional[str] = None,
        checkpoint_dir: Optional[Union[str, Path]] = None,
        checkpoint_interval_events: int = 1000,
        validate_monotonic: bool = True,
        validate_receive_timestamp: bool = True,
        fail_fast: bool = True
    ):
        """
        Initialize replay engine.
        
        Args:
            source_path: Path to replay source file
            replay_mode: Session mode (REPLAY or VERIFY)
            source_identifier: Optional source identifier (defaults to source_path stem)
            checkpoint_dir: Directory for checkpoints (None = no checkpointing)
            checkpoint_interval_events: Events between checkpoints
            validate_monotonic: Whether to validate timestamp monotonicity
            validate_receive_timestamp: Whether to require receive_ts_ns == exchange_ts_ns
            fail_fast: Whether to fail on first error
        
        Raises:
            ReplayEngineError: If initialization fails
        """
        self.source_path = Path(source_path)
        self.replay_mode = replay_mode
        self.source_identifier = source_identifier or self.source_path.stem
        self.checkpoint_interval_events = checkpoint_interval_events
        self.validate_monotonic = validate_monotonic
        self.validate_receive_timestamp = validate_receive_timestamp
        self.fail_fast = fail_fast
        
        # Initialize checkpoint manager if directory provided
        self.checkpoint_manager: Optional[ReplayCheckpointManager] = None
        if checkpoint_dir:
            self.checkpoint_manager = create_checkpoint_manager(
                checkpoint_dir=checkpoint_dir,
                max_checkpoints=10
            )
        
        # Session state
        self._session: Optional[ReplaySession] = None
        self._event_consumer: Optional[Callable[[EventEnvelope], None]] = None
        self._event_count = 0
        self._verified_encountered_count = 0  # Actual encountered expected entries
        self._session_start_timestamp: Optional[int] = None
        
        logger.info(
            f"ReplayEngine initialized: source={self.source_path}, "
            f"mode={replay_mode.value}, checkpoint_dir={checkpoint_dir}, "
            f"checkpoint_interval={checkpoint_interval_events}"
        )
    
    def _get_session_start_time(self) -> int:
        """
        Get session start time from first event.
        
        Note: This reopens the source file, which is acceptable for Stage 0.
        In future stages, session could cache this information.
        
        Returns:
            First event timestamp, or 0 if no events
        
        Raises:
            ReplayEngineError: If no events available
        """
        with open_replay_source(self.source_path) as source:
            for envelope in source:
                return envelope.exchange_ts_ns
        
        raise ReplayEngineError("No events in replay source")
    
    def _restore_from_checkpoint(self, session: ReplaySession) -> None:
        """
        Restore session from latest checkpoint using full replay position.
        
        Args:
            session: The session to restore
        """
        if not self.checkpoint_manager:
            return
        
        latest = self.checkpoint_manager.get_latest_checkpoint()
        if not latest:
            logger.debug("No checkpoint found, starting from beginning")
            return
        
        if not latest.replay_position:
            logger.warning("Checkpoint has no replay position, ignoring")
            return
        
        try:
            # Restore using full replay position (sequence-based)
            # Seek to index ensures exact position recovery
            session.seek_to_index(latest.replay_position.sequence)
            self._event_count = latest.wal_seq
            logger.info(
                f"Restored from checkpoint: event {latest.wal_seq}, "
                f"sequence {latest.replay_position.sequence}, "
                f"timestamp {latest.replay_position.timestamp_ns}"
            )
        except Exception as e:
            logger.warning(f"Failed to restore from checkpoint: {e}, starting from beginning")
            session.reset()
            self._event_count = 0
    
    def _create_checkpoint(self, session: ReplaySession) -> None:
        """
        Create a checkpoint at current position.
        
        Args:
            session: The current session
        """
        if not self.checkpoint_manager:
            return
        
        position = session.get_current_position()
        if not position:
            return
        
        checkpoint = self.checkpoint_manager.create_checkpoint(
            checkpoint_type=CheckpointType.WAL_SYNC,
            wal_seq=self._event_count,
            timestamp_ns=position.timestamp_ns,
            replay_position=position,
            snapshot_path=None
        )
        
        self.checkpoint_manager.save_checkpoint(checkpoint)
        logger.debug(f"Checkpoint created at event {self._event_count}, sequence {position.sequence}")
    
    def run(
        self,
        event_consumer: Callable[[EventEnvelope], None],
        expected_outputs: Optional[Dict[int, Dict[str, Any]]] = None
    ) -> VerificationResult:
        """
        Run replay session with deterministic time injection.
        
        Args:
            event_consumer: Callback for each event during replay
            expected_outputs: For VERIFY mode, expected outputs mapping
        
        Returns:
            VerificationResult with summary (failures list is empty in Stage 0)
        
        Raises:
            ReplayEngineError: If replay fails
        """
        self._event_consumer = event_consumer
        self._event_count = 0
        self._verified_encountered_count = 0
        expected_set = expected_outputs or {}
        
        try:
            # Get session start timestamp before creating session
            self._session_start_timestamp = self._get_session_start_time()
            
            # Create session based on mode
            if self.replay_mode == ReplayMode.VERIFY:
                # ReplaySession handles verification internally
                self._session = verify_replay_session(
                    source_path=self.source_path,
                    expected_outputs=expected_set,
                    source_identifier=self.source_identifier,
                    fail_fast=self.fail_fast
                )
            else:
                self._session = replay_session(
                    source_path=self.source_path,
                    replay_mode=self.replay_mode,
                    source_identifier=self.source_identifier,
                    fail_fast=self.fail_fast
                )
            
            # Restore from checkpoint if available
            self._restore_from_checkpoint(self._session)
            
            # Process events with deterministic time context
            # The context sets the base replay time; individual events advance it
            with ReplayTimeContext(self._session_start_timestamp):
                for event in self._session.iterate_events():
                    # Track encountered expected entries for honest verified count
                    if self.replay_mode == ReplayMode.VERIFY:
                        current_index = self._event_count
                        if current_index in expected_set:
                            self._verified_encountered_count += 1
                    
                    # Set replay time to event timestamp for deterministic now_ns()
                    set_replay_time_ns(event.exchange_ts_ns)
                    
                    # Deliver event to consumer
                    self._event_consumer(event)
                    
                    self._event_count += 1
                    
                    # Create checkpoint at interval
                    if self.checkpoint_manager and self._event_count % self.checkpoint_interval_events == 0:
                        self._create_checkpoint(self._session)
            
            # Extract verification results from session progress
            if self.replay_mode == ReplayMode.VERIFY and self._session:
                progress = self._session.get_progress()
                # verification_failures in session progress is an integer count
                failure_count = progress.get("verification_failures", 0)
                verification_passed = progress.get("verification_passed", True) and failure_count == 0
                
                # Return summary result with honest verified_events count
                # verified_events = actual number of expected entries encountered during replay
                return VerificationResult(
                    passed=verification_passed,
                    total_expected_events=len(expected_set),
                    total_actual_events=self._event_count,
                    verified_events=self._verified_encountered_count,
                    failures=[]  # Structured failures not available in Stage 0
                )
            
            # For REPLAY mode, return empty result
            return VerificationResult(
                passed=True,
                total_expected_events=0,
                total_actual_events=self._event_count,
                verified_events=0,
                failures=[]
            )
            
        except Exception as e:
            raise ReplayEngineError(f"Replay failed: {e}")
        finally:
            # Clean up replay time
            clear_replay_time()
            self._session = None
            self._event_consumer = None
    
    def get_progress(self) -> Dict[str, Any]:
        """
        Get current replay progress.
        
        Returns:
            Progress metrics
        """
        if self._session:
            progress = self._session.get_progress()
            progress["engine_event_count"] = self._event_count
            progress["engine_verified_encountered_count"] = self._verified_encountered_count
            return progress
        
        return {"status": "not_running"}
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get engine statistics.
        
        Returns:
            Engine statistics
        """
        stats = {
            "source_path": str(self.source_path),
            "source_identifier": self.source_identifier,
            "replay_mode": self.replay_mode.value,
            "checkpoint_interval_events": self.checkpoint_interval_events,
            "checkpointing_enabled": self.checkpoint_manager is not None,
            "event_count": self._event_count,
            "verified_encountered_count": self._verified_encountered_count
        }
        
        if self._session:
            stats["session_stats"] = self._session.get_stats()
        
        return stats


# ============================================
# Convenience Functions
# ============================================

def run_replay(
    source_path: Union[str, Path],
    event_consumer: Callable[[EventEnvelope], None],
    replay_mode: ReplayMode = ReplayMode.REPLAY,
    checkpoint_dir: Optional[Union[str, Path]] = None,
    checkpoint_interval_events: int = 1000,
    expected_outputs: Optional[Dict[int, Dict[str, Any]]] = None,
    fail_fast: bool = True
) -> VerificationResult:
    """
    Run a replay session with the given event consumer.
    
    Args:
        source_path: Path to replay source file
        event_consumer: Callback for each event
        replay_mode: Session mode (REPLAY or VERIFY)
        checkpoint_dir: Directory for checkpoints (None = no checkpointing)
        checkpoint_interval_events: Events between checkpoints
        expected_outputs: For VERIFY mode, expected outputs mapping
        fail_fast: Whether to fail on first error
    
    Returns:
        VerificationResult with summary
    
    Raises:
        ReplayEngineError: If replay fails
    """
    engine = ReplayEngine(
        source_path=source_path,
        replay_mode=replay_mode,
        checkpoint_dir=checkpoint_dir,
        checkpoint_interval_events=checkpoint_interval_events,
        fail_fast=fail_fast
    )
    
    return engine.run(event_consumer, expected_outputs)


def run_replay_with_verification(
    source_path: Union[str, Path],
    event_consumer: Callable[[EventEnvelope], None],
    expected_outputs: Dict[int, Dict[str, Any]],
    checkpoint_dir: Optional[Union[str, Path]] = None,
    checkpoint_interval_events: int = 1000,
    fail_fast: bool = True
) -> VerificationResult:
    """
    Run a replay session with built-in verification.
    
    Verification is handled by ReplaySession during event iteration.
    Returns a summary result with honest verified_events count.
    
    Args:
        source_path: Path to replay source file
        event_consumer: Callback for each event
        expected_outputs: Expected outputs mapping
        checkpoint_dir: Directory for checkpoints (None = no checkpointing)
        checkpoint_interval_events: Events between checkpoints
        fail_fast: Whether to fail on first error
    
    Returns:
        VerificationResult with summary
    
    Raises:
        ReplayEngineError: If replay fails
    """
    return run_replay(
        source_path=source_path,
        event_consumer=event_consumer,
        replay_mode=ReplayMode.VERIFY,
        checkpoint_dir=checkpoint_dir,
        checkpoint_interval_events=checkpoint_interval_events,
        expected_outputs=expected_outputs,
        fail_fast=fail_fast
    )


__all__ = [
    'ReplayEngine',
    'ReplayEngineError',
    'run_replay',
    'run_replay_with_verification',
]