"""
Replay Checkpoint Manager for Sovereign Trading System

This module provides deterministic checkpoint management for replay sessions.
Enables saving and restoring replay state for crash recovery.

This module manages checkpoint metadata and references to replay positions.
It does NOT store full system snapshots; it stores checkpoint records that
reference external snapshot paths.

Checkpoint Types:
- WAL_SYNC: Write-ahead log sync point
- TRUTH_FRAME: Truth reconciliation frame checkpoint
- SNAPSHOT: Full system state snapshot (stores path, not content)

All checkpoints include:
- Deterministic checksum validation (checksum excludes the checksum field itself)
- Atomic writes with temp file rename and fsync
- Replay position tracking
"""

import logging
import hashlib
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from uuid import uuid4

from app.models.contracts import RecoveryCheckpoint, ReplayPosition
from app.models.enums import CheckpointType

logger = logging.getLogger(__name__)


class ReplayCheckpointError(Exception):
    """Base exception for replay checkpoint errors."""
    pass


class ReplayCheckpointNotFoundError(ReplayCheckpointError):
    """Raised when requested checkpoint does not exist."""
    pass


class ReplayCheckpointCorruptedError(ReplayCheckpointError):
    """Raised when checkpoint checksum validation fails."""
    pass


def _serialize_checkpoint_type(checkpoint_type: CheckpointType) -> str:
    """
    Safely serialize checkpoint type to string.
    
    Handles both CheckpointType enum and string inputs.
    
    Args:
        checkpoint_type: CheckpointType enum or string
    
    Returns:
        String representation
    """
    if hasattr(checkpoint_type, "value"):
        return checkpoint_type.value
    return str(checkpoint_type)


def _canonical_representation(
    checkpoint_id: str,
    timestamp_ns: int,
    checkpoint_type: CheckpointType,
    wal_seq: int,
    truth_frame_id: Optional[str],
    snapshot_path: Optional[str],
    replay_position: Optional[Dict[str, Any]]
) -> str:
    """
    Generate canonical string representation of checkpoint data EXCLUDING checksum.
    
    This is the canonical representation used for checksum calculation.
    
    Args:
        checkpoint_id: Checkpoint identifier
        timestamp_ns: Timestamp in nanoseconds
        checkpoint_type: Type of checkpoint (CheckpointType enum)
        wal_seq: Write-ahead log sequence number
        truth_frame_id: Associated truth frame ID
        snapshot_path: Path to binary snapshot
        replay_position: Replay position dict
    
    Returns:
        Canonical string representation for checksum
    """
    data = {
        "checkpoint_id": checkpoint_id,
        "timestamp_ns": timestamp_ns,
        "checkpoint_type": _serialize_checkpoint_type(checkpoint_type),
        "wal_seq": wal_seq,
        "truth_frame_id": truth_frame_id,
        "snapshot_path": snapshot_path,
        "replay_position": replay_position
    }
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


class ReplayCheckpointManager:
    """
    Deterministic checkpoint manager for replay sessions.
    
    Features:
    - Save and load checkpoints with checksum validation (checksum excludes itself)
    - Atomic writes with temp file rename and fsync
    - Checkpoint listing and cleanup
    - Deterministic serialization
    - Support for multiple checkpoint types
    """
    
    def __init__(
        self,
        checkpoint_dir: Union[str, Path],
        max_checkpoints: int = 10,
        create_dir: bool = True
    ):
        """
        Initialize checkpoint manager.
        
        Args:
            checkpoint_dir: Directory to store checkpoints
            max_checkpoints: Maximum number of checkpoints to retain
            create_dir: Create directory if it doesn't exist
        
        Raises:
            ReplayCheckpointError: If directory creation fails
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.max_checkpoints = max_checkpoints
        
        if create_dir:
            try:
                self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise ReplayCheckpointError(f"Failed to create checkpoint directory: {e}")
        
        if not self.checkpoint_dir.exists():
            raise ReplayCheckpointError(f"Checkpoint directory does not exist: {self.checkpoint_dir}")
        
        if not self.checkpoint_dir.is_dir():
            raise ReplayCheckpointError(f"Checkpoint path is not a directory: {self.checkpoint_dir}")
        
        logger.info(
            f"ReplayCheckpointManager initialized: dir={self.checkpoint_dir}, "
            f"max_checkpoints={max_checkpoints}"
        )
    
    def _get_checkpoint_path(self, checkpoint_id: str) -> Path:
        """
        Get file path for a checkpoint.
        
        Args:
            checkpoint_id: Checkpoint identifier
        
        Returns:
            Path to checkpoint file
        """
        return self.checkpoint_dir / f"{checkpoint_id}.json"
    
    def _calculate_checksum(self, checkpoint: RecoveryCheckpoint) -> str:
        """
        Calculate deterministic checksum of checkpoint data EXCLUDING the checksum field.
        
        Args:
            checkpoint: RecoveryCheckpoint instance
        
        Returns:
            SHA256 hex digest
        """
        replay_position_dict = None
        if checkpoint.replay_position:
            replay_position_dict = {
                "source": checkpoint.replay_position.source,
                "sequence": checkpoint.replay_position.sequence,
                "timestamp_ns": checkpoint.replay_position.timestamp_ns
            }
        
        canonical = _canonical_representation(
            checkpoint_id=checkpoint.checkpoint_id,
            timestamp_ns=checkpoint.timestamp_ns,
            checkpoint_type=checkpoint.checkpoint_type,
            wal_seq=checkpoint.wal_seq,
            truth_frame_id=checkpoint.truth_frame_id,
            snapshot_path=checkpoint.snapshot_path,
            replay_position=replay_position_dict
        )
        
        return hashlib.sha256(canonical.encode()).hexdigest()
    
    def _serialize_checkpoint(self, checkpoint: RecoveryCheckpoint) -> Dict[str, Any]:
        """
        Serialize checkpoint to dictionary for storage.
        
        Args:
            checkpoint: RecoveryCheckpoint to serialize
        
        Returns:
            Dictionary representation
        """
        data = {
            "checkpoint_id": checkpoint.checkpoint_id,
            "timestamp_ns": checkpoint.timestamp_ns,
            "checkpoint_type": _serialize_checkpoint_type(checkpoint.checkpoint_type),
            "wal_seq": checkpoint.wal_seq,
            "truth_frame_id": checkpoint.truth_frame_id,
            "snapshot_path": checkpoint.snapshot_path,
            "checksum": checkpoint.checksum
        }
        
        if checkpoint.replay_position:
            data["replay_position"] = {
                "source": checkpoint.replay_position.source,
                "sequence": checkpoint.replay_position.sequence,
                "timestamp_ns": checkpoint.replay_position.timestamp_ns
            }
        
        return data
    
    def _deserialize_checkpoint(self, data: Dict[str, Any]) -> RecoveryCheckpoint:
        """
        Deserialize checkpoint from dictionary.
        
        Args:
            data: Dictionary from serialized checkpoint
        
        Returns:
            RecoveryCheckpoint instance
        
        Raises:
            ReplayCheckpointError: If data is malformed
        """
        try:
            replay_position = None
            if "replay_position" in data and data["replay_position"]:
                rp = data["replay_position"]
                replay_position = ReplayPosition(
                    source=rp["source"],
                    sequence=rp["sequence"],
                    timestamp_ns=rp["timestamp_ns"]
                )
            
            # Handle checkpoint_type safely - could be string or already parsed
            checkpoint_type_raw = data["checkpoint_type"]
            if isinstance(checkpoint_type_raw, CheckpointType):
                checkpoint_type = checkpoint_type_raw
            else:
                checkpoint_type = CheckpointType(checkpoint_type_raw)
            
            return RecoveryCheckpoint(
                checkpoint_id=data["checkpoint_id"],
                timestamp_ns=data["timestamp_ns"],
                checkpoint_type=checkpoint_type,
                wal_seq=data["wal_seq"],
                truth_frame_id=data.get("truth_frame_id"),
                snapshot_path=data.get("snapshot_path"),
                checksum=data["checksum"],
                replay_position=replay_position
            )
        except (KeyError, ValueError) as e:
            raise ReplayCheckpointError(f"Failed to deserialize checkpoint: {e}")
    
    def save_checkpoint(self, checkpoint: RecoveryCheckpoint) -> str:
        """
        Save checkpoint to disk with atomic write and fsync.
        
        Atomic write process:
        1. Write to temp file
        2. fsync to ensure physical write
        3. Close file
        4. Rename temp file to target (atomic on POSIX)
        
        Args:
            checkpoint: RecoveryCheckpoint to save
        
        Returns:
            Path to saved checkpoint file
        
        Raises:
            ReplayCheckpointError: If save fails
        """
        # Verify checksum matches canonical representation
        computed_checksum = self._calculate_checksum(checkpoint)
        if computed_checksum != checkpoint.checksum:
            raise ReplayCheckpointError(
                f"Checkpoint checksum mismatch: expected {checkpoint.checksum}, "
                f"got {computed_checksum}"
            )
        
        target_path = self._get_checkpoint_path(checkpoint.checkpoint_id)
        data = self._serialize_checkpoint(checkpoint)
        temp_path = target_path.with_suffix(".tmp")
        
        try:
            # Write to temp file with fsync
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            # File is now closed and flushed to disk
            
            # Atomic rename on POSIX systems
            temp_path.replace(target_path)
            
            logger.debug(f"Saved checkpoint: {checkpoint.checkpoint_id}")
            
            # Clean up old checkpoints
            self._cleanup_old_checkpoints()
            
            return str(target_path)
            
        except Exception as e:
            # Clean up temp file on error
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            raise ReplayCheckpointError(f"Failed to save checkpoint: {e}")
    
    def load_checkpoint(
        self,
        checkpoint_id: str,
        validate_checksum: bool = True
    ) -> RecoveryCheckpoint:
        """
        Load checkpoint from disk.
        
        Args:
            checkpoint_id: Checkpoint identifier
            validate_checksum: If True, verify checksum after loading
        
        Returns:
            RecoveryCheckpoint instance
        
        Raises:
            ReplayCheckpointNotFoundError: If checkpoint not found
            ReplayCheckpointCorruptedError: If checksum validation fails
            ReplayCheckpointError: On other errors
        """
        target_path = self._get_checkpoint_path(checkpoint_id)
        
        if not target_path.exists():
            raise ReplayCheckpointNotFoundError(f"Checkpoint not found: {checkpoint_id}")
        
        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Deserialize first to get checkpoint object
            checkpoint = self._deserialize_checkpoint(data)
            
            # Validate checksum if requested
            if validate_checksum:
                computed_checksum = self._calculate_checksum(checkpoint)
                if computed_checksum != checkpoint.checksum:
                    raise ReplayCheckpointCorruptedError(
                        f"Checkpoint {checkpoint_id} corrupted: "
                        f"checksum mismatch (expected {checkpoint.checksum}, got {computed_checksum})"
                    )
            
            logger.debug(f"Loaded checkpoint: {checkpoint_id}")
            return checkpoint
            
        except json.JSONDecodeError as e:
            raise ReplayCheckpointError(f"Failed to parse checkpoint JSON: {e}")
        except ReplayCheckpointCorruptedError:
            raise
        except Exception as e:
            raise ReplayCheckpointError(f"Failed to load checkpoint: {e}")
    
    def list_checkpoints(
        self,
        checkpoint_type: Optional[CheckpointType] = None
    ) -> List[Dict[str, Any]]:
        """
        List available checkpoints.
        
        Args:
            checkpoint_type: Optional filter by checkpoint type
        
        Returns:
            List of checkpoint summaries (id, type, timestamp, wal_seq)
        """
        checkpoints = []
        
        for file_path in self.checkpoint_dir.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                checkpoint_type_val = data.get("checkpoint_type")
                if checkpoint_type and checkpoint_type_val != _serialize_checkpoint_type(checkpoint_type):
                    continue
                
                checkpoints.append({
                    "checkpoint_id": data.get("checkpoint_id"),
                    "checkpoint_type": checkpoint_type_val,
                    "timestamp_ns": data.get("timestamp_ns"),
                    "wal_seq": data.get("wal_seq"),
                    "file_path": str(file_path),
                    "file_size": file_path.stat().st_size
                })
            except Exception as e:
                logger.warning(f"Failed to read checkpoint {file_path}: {e}")
        
        # Sort by timestamp descending (newest first)
        checkpoints.sort(key=lambda x: x.get("timestamp_ns", 0), reverse=True)
        
        return checkpoints
    
    def get_latest_checkpoint(
        self,
        checkpoint_type: Optional[CheckpointType] = None
    ) -> Optional[RecoveryCheckpoint]:
        """
        Get the latest checkpoint by timestamp.
        
        Args:
            checkpoint_type: Optional filter by checkpoint type
        
        Returns:
            Latest RecoveryCheckpoint, or None if none exist
        """
        checkpoints = self.list_checkpoints(checkpoint_type)
        
        if not checkpoints:
            return None
        
        latest = checkpoints[0]
        return self.load_checkpoint(latest["checkpoint_id"])
    
    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """
        Delete a checkpoint.
        
        Args:
            checkpoint_id: Checkpoint identifier
        
        Returns:
            True if deleted, False if not found
        """
        target_path = self._get_checkpoint_path(checkpoint_id)
        
        if not target_path.exists():
            return False
        
        try:
            target_path.unlink()
            logger.debug(f"Deleted checkpoint: {checkpoint_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete checkpoint {checkpoint_id}: {e}")
            return False
    
    def _cleanup_old_checkpoints(self) -> None:
        """Delete old checkpoints exceeding max_checkpoints."""
        checkpoints = self.list_checkpoints()
        
        if len(checkpoints) <= self.max_checkpoints:
            return
        
        # Delete oldest checkpoints (already sorted newest first)
        for checkpoint in checkpoints[self.max_checkpoints:]:
            self.delete_checkpoint(checkpoint["checkpoint_id"])
        
        logger.info(f"Cleaned up {len(checkpoints) - self.max_checkpoints} old checkpoints")
    
    def create_checkpoint(
        self,
        checkpoint_type: CheckpointType,
        wal_seq: int,
        timestamp_ns: int,
        replay_position: Optional[ReplayPosition] = None,
        truth_frame_id: Optional[str] = None,
        snapshot_path: Optional[str] = None
    ) -> RecoveryCheckpoint:
        """
        Create a new checkpoint with automatic checksum calculation.
        
        timestamp_ns MUST be provided from deterministic replay time.
        Do not use wall-clock time for checkpoint timestamps.
        
        Args:
            checkpoint_type: Type of checkpoint (CheckpointType enum)
            wal_seq: Write-ahead log sequence number
            timestamp_ns: Timestamp in nanoseconds (from replay time)
            replay_position: Current replay position
            truth_frame_id: Associated truth frame ID (for TRUTH_FRAME type)
            snapshot_path: Path to binary snapshot (for SNAPSHOT type)
        
        Returns:
            RecoveryCheckpoint with computed checksum
        """
        checkpoint_id = str(uuid4())
        
        # Create checkpoint without checksum
        checkpoint = RecoveryCheckpoint(
            checkpoint_id=checkpoint_id,
            timestamp_ns=timestamp_ns,
            checkpoint_type=checkpoint_type,
            wal_seq=wal_seq,
            truth_frame_id=truth_frame_id,
            snapshot_path=snapshot_path,
            checksum="",  # Temporary, will be replaced
            replay_position=replay_position
        )
        
        # Calculate checksum from canonical representation
        checksum = self._calculate_checksum(checkpoint)
        
        # Create final checkpoint with checksum
        final_checkpoint = RecoveryCheckpoint(
            checkpoint_id=checkpoint_id,
            timestamp_ns=timestamp_ns,
            checkpoint_type=checkpoint_type,
            wal_seq=wal_seq,
            truth_frame_id=truth_frame_id,
            snapshot_path=snapshot_path,
            checksum=checksum,
            replay_position=replay_position
        )
        
        return final_checkpoint


# ============================================
# Convenience Functions
# ============================================

def create_checkpoint_manager(
    checkpoint_dir: Union[str, Path],
    max_checkpoints: int = 10
) -> ReplayCheckpointManager:
    """
    Create a configured checkpoint manager.
    
    Args:
        checkpoint_dir: Directory to store checkpoints
        max_checkpoints: Maximum number of checkpoints to retain
    
    Returns:
        ReplayCheckpointManager instance
    """
    return ReplayCheckpointManager(
        checkpoint_dir=checkpoint_dir,
        max_checkpoints=max_checkpoints
    )


__all__ = [
    'ReplayCheckpointManager',
    'ReplayCheckpointError',
    'ReplayCheckpointNotFoundError',
    'ReplayCheckpointCorruptedError',
    'create_checkpoint_manager',
]