"""
Shared Memory Manager - Lock-Free Read Architecture
Rule 10: Deterministic Loop Execution
- Shared memory blocks for all math outputs
- Lock-free reads for main loop
- Cache-aware window limits (enforced)
- Nanosecond timestamp alignment (Rule 6)
- Process-safe multiprocessing.shared_memory
- ZOMBIE PROTECTION: atexit handlers, signal cleanup, stale block removal
"""

import numpy as np
from multiprocessing import shared_memory, Manager
import mmap
import time
import os
import sys
import atexit
import signal
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
import threading
import logging

logger = logging.getLogger(__name__)

# Cache-aware limits (L2 cache ~256KB)
MAX_CORRELATION_MATRIX_SIZE = 256  # 256 x 256 = 65536 elements (256KB)
MAX_TOPOLOGY_WINDOW = 150  # 150 x 150 = 22500 elements (90KB, safe)
MAX_PRICE_HISTORY = 10000  # 10000 prices (40KB, safe)

# Nanosecond conversion
NS_PER_SECOND = 1_000_000_000

# Shared memory prefix with PID for uniqueness
PID = os.getpid()
SHM_PREFIX = f"poverty_killer_{PID}_"


@dataclass
class SharedMemoryBlock:
    """Shared memory block metadata."""
    name: str
    shape: Tuple[int, ...]
    dtype: np.dtype
    size: int
    shm: shared_memory.SharedMemory
    last_write_ns: int = 0
    version: int = 0


class SharedMemoryManager:
    """
    Shared Memory Manager - Lock-Free Read Architecture.
    
    Features:
    - Pre-allocated shared memory blocks with PID prefix
    - Lock-free reads (main loop never waits)
    - Cache-aware window limits enforced
    - Nanosecond timestamp alignment
    - Version tracking for cache invalidation
    - ZOMBIE PROTECTION: atexit, signal handlers, stale cleanup
    """
    
    def __init__(self, max_instruments: int = 256, cleanup_stale: bool = True):
        """
        Initialize shared memory manager.
        
        Args:
            max_instruments: Maximum number of instruments
            cleanup_stale: Remove stale blocks from previous runs
        """
        self.max_instruments = min(max_instruments, MAX_CORRELATION_MATRIX_SIZE)
        self.pid = PID
        self.prefix = SHM_PREFIX
        self._blocks: Dict[str, SharedMemoryBlock] = {}
        self._write_lock = threading.Lock()
        self._read_versions: Dict[str, int] = {}
        self._cleaned_up = False
        
        # Clean up stale blocks from previous runs
        if cleanup_stale:
            self._cleanup_stale_blocks()
        
        # Register cleanup handlers
        atexit.register(self.cleanup)
        self._register_signal_handlers()
        
        # Pre-allocate all shared memory blocks
        self._create_blocks()
        
        logger.info(f"SharedMemoryManager initialized: PID={self.pid}, max_instruments={self.max_instruments}")
    
    def _cleanup_stale_blocks(self) -> None:
        """
        Remove stale shared memory blocks from previous runs.
        Identifies blocks by checking if they belong to a dead process.
        """
        try:
            # List all shared memory blocks
            import resource
            shm_list = []
            
            # On Linux, check /dev/shm
            shm_dir = "/dev/shm"
            if os.path.exists(shm_dir):
                for filename in os.listdir(shm_dir):
                    if filename.startswith("poverty_killer_"):
                        shm_list.append(filename)
            
            # Parse PID from block name
            for name in shm_list:
                try:
                    parts = name.split("_")
                    if len(parts) >= 3:
                        block_pid = int(parts[2])
                        # Check if process is alive
                        try:
                            os.kill(block_pid, 0)
                        except OSError:
                            # Process dead, remove block
                            logger.info(f"Removing stale shared memory block: {name}")
                            try:
                                shm = shared_memory.SharedMemory(name=name, create=False)
                                shm.close()
                                shm.unlink()
                            except Exception as e:
                                logger.debug(f"Could not unlink {name}: {e}")
                except (ValueError, IndexError):
                    pass
                    
        except Exception as e:
            logger.debug(f"Stale cleanup error: {e}")
    
    def _register_signal_handlers(self) -> None:
        """Register signal handlers for clean shutdown."""
        def signal_handler(signum, frame):
            logger.info(f"Signal {signum} received, cleaning up shared memory...")
            self.cleanup()
            sys.exit(0)
        
        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
        except ValueError:
            # Not in main thread, can't set signals
            pass
    
    def _create_blocks(self) -> None:
        """Pre-allocate all shared memory blocks with PID prefix."""
        
        # 1. Correlation Matrix (N x N float32)
        corr_shape = (self.max_instruments, self.max_instruments)
        self._create_block("correlation_matrix", corr_shape, np.float32)
        
        # 2. Price History (max_history x max_instruments)
        price_shape = (MAX_PRICE_HISTORY, self.max_instruments)
        self._create_block("price_history", price_shape, np.float32)
        
        # 3. Volume History
        self._create_block("volume_history", price_shape, np.float32)
        
        # 4. Regime Labels (max_history x 1)
        regime_shape = (MAX_PRICE_HISTORY,)
        self._create_block("regime_labels", regime_shape, np.int32)
        
        # 5. Entropy History
        self._create_block("entropy_history", (MAX_PRICE_HISTORY,), np.float32)
        
        # 6. Void Score History
        self._create_block("void_history", (MAX_PRICE_HISTORY,), np.float32)
        
        # 7. Cascade Risk History
        self._create_block("cascade_history", (MAX_PRICE_HISTORY,), np.float32)
        
        # 8. Hawkes Intensity History
        self._create_block("hawkes_history", (MAX_PRICE_HISTORY,), np.float32)
        
        # 9. Stealth Accumulation History
        self._create_block("stealth_history", (MAX_PRICE_HISTORY,), np.float32)
        
        # 10. Algorithmic Randomness History
        self._create_block("randomness_history", (MAX_PRICE_HISTORY,), np.float32)
        
        # 11. Timestamp History (nanoseconds)
        self._create_block("timestamp_history", (MAX_PRICE_HISTORY,), np.uint64)
        
        # 12. Feature Vector (latest features)
        self._create_block("feature_vector", (20,), np.float32)
        
        # 13. Feature Timestamp (nanoseconds)
        self._create_block("feature_timestamp", (1,), np.uint64)
        
        # 14. Feature Version
        self._create_block("feature_version", (1,), np.uint32)
        
        # 15. Heartbeat (for zombie detection)
        self._create_block("heartbeat", (2,), np.uint64)  # [last_update_ns, pid]
        
        # Initialize heartbeat with PID and current time
        self._update_heartbeat()
        
        logger.info(f"Created {len(self._blocks)} shared memory blocks")
    
    def _create_block(self, name: str, shape: Tuple[int, ...], dtype: np.dtype) -> None:
        """Create a shared memory block with PID prefix."""
        full_name = f"{self.prefix}{name}"
        size = np.prod(shape) * dtype.itemsize
        
        try:
            # Try to create new block
            shm = shared_memory.SharedMemory(name=full_name, create=True, size=size)
            logger.debug(f"Created shared memory: {full_name}")
        except FileExistsError:
            # Block exists, attach to it
            shm = shared_memory.SharedMemory(name=full_name, create=False)
            logger.debug(f"Attached to existing shared memory: {full_name}")
        
        # Initialize with zeros
        buffer = np.ndarray(shape, dtype=dtype, buffer=shm.buf)
        buffer.fill(0)
        
        self._blocks[name] = SharedMemoryBlock(
            name=full_name,
            shape=shape,
            dtype=dtype,
            size=size,
            shm=shm
        )
    
    def _update_heartbeat(self) -> None:
        """Update heartbeat block for zombie detection."""
        writer, _ = self.get_writer("heartbeat", now_ns())
        if writer is not None and len(writer) >= 2:
            writer[0] = now_ns()
            writer[1] = self.pid
    
    def get_reader(self, name: str) -> Optional[np.ndarray]:
        """
        Get read-only view of shared memory block.
        Lock-free - main loop can read without waiting.
        
        Returns:
            Numpy array view (read-only)
        """
        block = self._blocks.get(name)
        if not block:
            return None
        
        # Return view of the buffer
        return np.ndarray(block.shape, dtype=block.dtype, buffer=block.shm.buf)
    
    def get_writer(self, name: str, timestamp_ns: int) -> Tuple[Optional[np.ndarray], int]:
        """
        Get writable view of shared memory block.
        Updates version and timestamp.
        
        Args:
            name: Block name
            timestamp_ns: Current nanosecond timestamp
            
        Returns:
            Tuple of (numpy array view, new version)
        """
        with self._write_lock:
            block = self._blocks.get(name)
            if not block:
                return None, 0
            
            block.last_write_ns = timestamp_ns
            block.version += 1
            
            # Update heartbeat periodically (every 10 writes)
            if block.version % 10 == 0:
                self._update_heartbeat()
            
            return np.ndarray(block.shape, dtype=block.dtype, buffer=block.shm.buf), block.version
    
    def write_correlation_matrix(self, matrix: np.ndarray, timestamp_ns: int) -> int:
        """Write correlation matrix to shared memory."""
        if matrix.shape[0] > self.max_instruments:
            logger.warning(f"Correlation matrix too large: {matrix.shape[0]} > {self.max_instruments}")
            matrix = matrix[:self.max_instruments, :self.max_instruments]
        
        writer, version = self.get_writer("correlation_matrix", timestamp_ns)
        if writer is not None:
            writer[:, :] = matrix[:self.max_instruments, :self.max_instruments]
        
        return version
    
    def write_price_history(
        self,
        instrument_id: int,
        price: float,
        timestamp_ns: int,
        index: int
    ) -> None:
        """Write single price to history."""
        writer, _ = self.get_writer("price_history", timestamp_ns)
        if writer is not None:
            writer[index % MAX_PRICE_HISTORY, instrument_id] = price
        
        ts_writer, _ = self.get_writer("timestamp_history", timestamp_ns)
        if ts_writer is not None:
            ts_writer[index % MAX_PRICE_HISTORY] = timestamp_ns
    
    def write_feature_vector(self, features: np.ndarray, timestamp_ns: int) -> int:
        """Write feature vector to shared memory."""
        writer, version = self.get_writer("feature_vector", timestamp_ns)
        if writer is not None:
            min_len = min(len(features), len(writer))
            writer[:min_len] = features[:min_len]
        
        ts_writer, _ = self.get_writer("feature_timestamp", timestamp_ns)
        if ts_writer is not None:
            ts_writer[0] = timestamp_ns
        
        ver_writer, _ = self.get_writer("feature_version", timestamp_ns)
        if ver_writer is not None:
            ver_writer[0] = version
        
        return version
    
    def get_feature_vector(self) -> Tuple[Optional[np.ndarray], int, int]:
        """Get latest feature vector (lock-free read)."""
        features = self.get_reader("feature_vector")
        timestamp = self.get_reader("feature_timestamp")
        version = self.get_reader("feature_version")
        
        if features is None or timestamp is None or version is None:
            return None, 0, 0
        
        ts = timestamp[0] if len(timestamp) > 0 else 0
        ver = version[0] if len(version) > 0 else 0
        
        return features.copy(), ts, ver
    
    def get_correlation_row(self, instrument_id: int) -> Optional[np.ndarray]:
        """Get correlation row for instrument (lock-free read)."""
        matrix = self.get_reader("correlation_matrix")
        if matrix is None or instrument_id >= matrix.shape[0]:
            return None
        
        return matrix[instrument_id, :].copy()
    
    def get_latest_price(self, instrument_id: int, index: int) -> Optional[float]:
        """Get latest price for instrument."""
        prices = self.get_reader("price_history")
        if prices is None:
            return None
        
        return float(prices[index % MAX_PRICE_HISTORY, instrument_id])
    
    def get_price_window(
        self,
        instrument_id: int,
        current_index: int,
        window: int
    ) -> np.ndarray:
        """Get price window for instrument (vectorized)."""
        window = min(window, MAX_TOPOLOGY_WINDOW)
        prices = self.get_reader("price_history")
        
        if prices is None:
            return np.zeros(window)
        
        result = np.zeros(window)
        for i in range(window):
            idx = (current_index - i) % MAX_PRICE_HISTORY
            result[i] = prices[idx, instrument_id]
        
        return result
    
    def get_version(self, name: str) -> int:
        """Get current version of a block."""
        block = self._blocks.get(name)
        return block.version if block else 0
    
    def has_updated(self, name: str, last_version: int) -> bool:
        """Check if block has been updated since last read."""
        return self.get_version(name) != last_version
    
    def is_alive(self) -> bool:
        """Check if this manager is still alive (heartbeat check)."""
        try:
            heartbeat = self.get_reader("heartbeat")
            if heartbeat is None or len(heartbeat) < 2:
                return True
            last_update = heartbeat[0]
            pid_in_block = heartbeat[1]
            return pid_in_block == self.pid and (now_ns() - last_update) < 10_000_000_000  # 10 seconds
        except Exception:
            return True
    
    def cleanup(self) -> None:
        """Clean up all shared memory blocks (idempotent)."""
        if self._cleaned_up:
            return
        
        self._cleaned_up = True
        logger.info("Cleaning up shared memory blocks...")
        
        for name, block in list(self._blocks.items()):
            try:
                # Write zero to indicate death
                writer = self.get_writer(name, now_ns())
                if writer is not None:
                    writer.fill(0)
                
                block.shm.close()
                block.shm.unlink()
                logger.debug(f"Unlinked shared memory: {block.name}")
            except Exception as e:
                logger.warning(f"Failed to unlink {name}: {e}")
        
        self._blocks.clear()
        logger.info("Shared memory cleanup complete")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get shared memory statistics."""
        return {
            "blocks": len(self._blocks),
            "max_instruments": self.max_instruments,
            "max_price_history": MAX_PRICE_HISTORY,
            "max_topology_window": MAX_TOPOLOGY_WINDOW,
            "max_correlation_size": MAX_CORRELATION_MATRIX_SIZE,
            "pid": self.pid,
            "prefix": self.prefix,
            "block_sizes": {name: block.size for name, block in self._blocks.items()}
        }


# ============================================
# HELPER FUNCTIONS
# ============================================

def now_ns() -> int:
    """Get current time in nanoseconds."""
    return time.time_ns()


def seconds_to_ns(seconds: float) -> int:
    """Convert seconds to nanoseconds."""
    return int(seconds * NS_PER_SECOND)


def ns_to_seconds(ns: int) -> float:
    """Convert nanoseconds to seconds."""
    return ns / NS_PER_SECOND


def create_shared_memory_manager(max_instruments: int = 256, cleanup_stale: bool = True) -> SharedMemoryManager:
    """
    Create a configured shared memory manager with zombie protection.
    
    Args:
        max_instruments: Maximum number of instruments
        cleanup_stale: Remove stale blocks from previous runs
        
    Returns:
        SharedMemoryManager instance
    """
    return SharedMemoryManager(max_instruments=max_instruments, cleanup_stale=cleanup_stale)


# ============================================
# CONTEXT MANAGER FOR CLEANUP
# ============================================

class SharedMemoryContext:
    """Context manager for shared memory with automatic cleanup."""
    
    def __init__(self, max_instruments: int = 256, cleanup_stale: bool = True):
        self.manager = create_shared_memory_manager(max_instruments, cleanup_stale)
    
    def __enter__(self) -> SharedMemoryManager:
        return self.manager
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.manager.cleanup()


# ============================================
# MANUAL CLEANUP FUNCTION (For emergency use)
# ============================================

def cleanup_all_poverty_killer_blocks() -> int:
    """
    Manually clean up all Poverty Killer shared memory blocks.
    Useful if the bot crashed and left orphaned blocks.
    
    Returns:
        Number of blocks cleaned
    """
    count = 0
    shm_dir = "/dev/shm"
    
    if not os.path.exists(shm_dir):
        logger.warning(f"Shared memory directory not found: {shm_dir}")
        return 0
    
    for filename in os.listdir(shm_dir):
        if filename.startswith("poverty_killer_"):
            try:
                logger.info(f"Removing orphaned block: {filename}")
                shm = shared_memory.SharedMemory(name=filename, create=False)
                shm.close()
                shm.unlink()
                count += 1
            except Exception as e:
                logger.debug(f"Could not remove {filename}: {e}")
    
    return count