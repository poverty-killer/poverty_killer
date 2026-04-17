"""
app/utils/ids.py
POVERTY_KILLER — CANONICAL TEMPORAL ID AUTHORITY (CITADEL-GRADE)

This module provides replay-safe, sortable, thread-safe ID generation for the
entire platform. IDs generated here are canonical infrastructure artifacts used
for orders, signals, events, telemetry, persistence, and forensic correlation.

DESIGN PRINCIPLES
-----------------
1. Temporal Sortability
   IDs are Snowflake-style 64-bit integers sortable by embedded timestamp.

2. Collision Resistance
   Node identity is explicit/configurable and safe-fallback derived when needed.

3. Monotonic Safety
   Clock rollback is handled deterministically with bounded policies.

4. Auditability
   Generated IDs can be decoded into timestamp/node/sequence components.

5. Operational Control
   Singleton authority is lazy-initialized and overrideable for tests,
   simulation, recovery, and dependency injection.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
import hashlib
from dataclasses import dataclass
from enum import Enum, unique
from typing import Final, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION CONSTANTS
# ============================================================================

# 2025-01-01 00:00:00 UTC in milliseconds
DEFAULT_EPOCH_MS: Final[int] = 1735689600000

# Snowflake-64 layout:
# [ timestamp | node_id | sequence ]
DEFAULT_NODE_ID_BITS: Final[int] = 10
DEFAULT_SEQUENCE_BITS: Final[int] = 12

DEFAULT_MAX_CLOCK_ROLLBACK_MS: Final[int] = 250
DEFAULT_SPIN_SLEEP_SECONDS: Final[float] = 0.0001  # 100µs micro-sleep
DEFAULT_CLIENT_ORDER_PREFIX: Final[str] = "PK"
DEFAULT_CLIENT_ORDER_FORMAT_VERSION: Final[str] = "1"


# ============================================================================
# EXCEPTIONS / POLICIES
# ============================================================================

class IDGenerationError(RuntimeError):
    """Base class for canonical ID generation failures."""


class ClockRollbackError(IDGenerationError):
    """Raised when wall-clock rollback exceeds allowed policy."""


class SequenceOverflowError(IDGenerationError):
    """Raised when sequence exhaustion cannot be recovered safely."""


class InvalidNodeIDError(IDGenerationError):
    """Raised when node ID is out of allowed range."""


@unique
class ClockRollbackPolicy(str, Enum):
    """
    Deterministic response to clock rollback.
    """
    WAIT = "WAIT"                  # wait for wall clock to catch up (bounded)
    LOGICAL_ADVANCE = "LOGICAL_ADVANCE"  # advance internal logical timestamp
    RAISE = "RAISE"                # fail fast


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass(frozen=True, slots=True)
class IDComponents:
    """Decoded Snowflake ID components."""
    id_value: int
    timestamp_ms: int
    node_id: int
    sequence: int
    epoch_ms: int

    @property
    def unix_timestamp_ms(self) -> int:
        return self.timestamp_ms

    @property
    def created_at_iso(self) -> str:
        return time.strftime(
            "%Y-%m-%dT%H:%M:%S",
            time.gmtime(self.timestamp_ms / 1000),
        ) + f".{self.timestamp_ms % 1000:03d}Z"


@dataclass(frozen=True, slots=True)
class IDGeneratorConfig:
    """
    Immutable configuration for the ID authority.
    """
    node_id: int
    epoch_ms: int = DEFAULT_EPOCH_MS
    node_id_bits: int = DEFAULT_NODE_ID_BITS
    sequence_bits: int = DEFAULT_SEQUENCE_BITS
    max_clock_rollback_ms: int = DEFAULT_MAX_CLOCK_ROLLBACK_MS
    rollback_policy: ClockRollbackPolicy = ClockRollbackPolicy.WAIT
    spin_sleep_seconds: float = DEFAULT_SPIN_SLEEP_SECONDS
    client_order_prefix: str = DEFAULT_CLIENT_ORDER_PREFIX
    client_order_format_version: str = DEFAULT_CLIENT_ORDER_FORMAT_VERSION


# ============================================================================
# GENERATOR
# ============================================================================

class IDGenerator:
    """
    Canonical Snowflake-style ID authority.

    Thread-safe within process.
    Requires deployment discipline or explicit node allocation for
    cross-process/cross-host uniqueness.
    """

    def __init__(self, config: IDGeneratorConfig):
        self.config = config

        self.max_node_id: Final[int] = (1 << config.node_id_bits) - 1
        self.max_sequence: Final[int] = (1 << config.sequence_bits) - 1
        self.node_id_shift: Final[int] = config.sequence_bits
        self.timestamp_shift: Final[int] = config.sequence_bits + config.node_id_bits

        if not (0 <= config.node_id <= self.max_node_id):
            raise InvalidNodeIDError(
                f"node_id={config.node_id} out of range 0..{self.max_node_id}"
            )

        self._lock = threading.RLock()
        self._last_timestamp_ms = -1
        self._sequence = 0

        logger.info(
            "[ID_GEN] initialized node_id=%s epoch_ms=%s node_bits=%s seq_bits=%s "
            "rollback_policy=%s max_rollback_ms=%s",
            config.node_id,
            config.epoch_ms,
            config.node_id_bits,
            config.sequence_bits,
            config.rollback_policy.value,
            config.max_clock_rollback_ms,
        )

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------

    def generate(self) -> int:
        """
        Generate a canonical 64-bit sortable ID.
        """
        with self._lock:
            now_ms = self._now_ms()
            ts_ms = self._resolve_timestamp(now_ms)

            if ts_ms == self._last_timestamp_ms:
                self._sequence = (self._sequence + 1) & self.max_sequence
                if self._sequence == 0:
                    ts_ms = self._wait_for_next_ms(self._last_timestamp_ms)
            else:
                self._sequence = 0

            self._last_timestamp_ms = ts_ms

            id_value = (
                ((ts_ms - self.config.epoch_ms) << self.timestamp_shift)
                | (self.config.node_id << self.node_id_shift)
                | self._sequence
            )

            return id_value

    def generate_str(self) -> str:
        return str(self.generate())

    def generate_event_id(self) -> int:
        return self.generate()

    def generate_signal_id(self) -> int:
        return self.generate()

    def generate_order_id(self) -> int:
        return self.generate()

    def generate_fill_id(self) -> int:
        return self.generate()

    def generate_correlation_id(self) -> int:
        return self.generate()

    def generate_request_id(self) -> int:
        return self.generate()

    def generate_client_order_id(
        self,
        *,
        sleeve: Optional[str] = None,
        strategy: Optional[str] = None,
        max_length: int = 48,
    ) -> str:
        """
        Generate exchange-facing client order ID.

        Format is intentionally ASCII-safe and bounded:
            <PREFIX><VER>-<BASE36ID>[-<TAG>...]

        Examples:
            PK1-K8Q0M2A9T
            PK1-K8Q0M2A9T-GF
            PK1-K8Q0M2A9T-SHADOW
        """
        raw_id = self.generate()
        base36_id = _to_base36(raw_id)

        tags = []
        if sleeve:
            tags.append(_sanitize_tag(sleeve))
        if strategy:
            tags.append(_sanitize_tag(strategy))

        prefix = _sanitize_tag(self.config.client_order_prefix, upper=True, max_len=8)
        version = _sanitize_tag(self.config.client_order_format_version, upper=True, max_len=4)

        parts = [f"{prefix}{version}", base36_id]
        parts.extend(tag for tag in tags if tag)

        cid = "-".join(parts)

        if len(cid) > max_length:
            cid = cid[:max_length]

        return cid

    def decode(self, id_value: int) -> IDComponents:
        """
        Decode a generated ID into its canonical components.
        """
        sequence = id_value & self.max_sequence
        node_id = (id_value >> self.node_id_shift) & self.max_node_id
        timestamp_delta = id_value >> self.timestamp_shift
        timestamp_ms = timestamp_delta + self.config.epoch_ms

        return IDComponents(
            id_value=id_value,
            timestamp_ms=timestamp_ms,
            node_id=node_id,
            sequence=sequence,
            epoch_ms=self.config.epoch_ms,
        )

    def peek_state(self) -> dict[str, int]:
        """
        Introspection helper for diagnostics and telemetry.
        """
        with self._lock:
            return {
                "node_id": self.config.node_id,
                "last_timestamp_ms": self._last_timestamp_ms,
                "sequence": self._sequence,
                "max_node_id": self.max_node_id,
                "max_sequence": self.max_sequence,
                "timestamp_shift": self.timestamp_shift,
                "node_id_shift": self.node_id_shift,
            }

    # ----------------------------------------------------------------------
    # Internal mechanics
    # ----------------------------------------------------------------------

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _resolve_timestamp(self, now_ms: int) -> int:
        """
        Resolve wall-clock timestamp into a safe monotonic timestamp.
        """
        if self._last_timestamp_ms < 0:
            return now_ms

        if now_ms >= self._last_timestamp_ms:
            return now_ms

        rollback_ms = self._last_timestamp_ms - now_ms

        logger.critical(
            "[ID_GEN] clock rollback detected node_id=%s rollback_ms=%s "
            "last_timestamp_ms=%s now_ms=%s policy=%s",
            self.config.node_id,
            rollback_ms,
            self._last_timestamp_ms,
            now_ms,
            self.config.rollback_policy.value,
        )

        if self.config.rollback_policy == ClockRollbackPolicy.RAISE:
            raise ClockRollbackError(
                f"clock moved backwards by {rollback_ms}ms "
                f"(last={self._last_timestamp_ms}, now={now_ms})"
            )

        if self.config.rollback_policy == ClockRollbackPolicy.LOGICAL_ADVANCE:
            if rollback_ms > self.config.max_clock_rollback_ms:
                logger.error(
                    "[ID_GEN] rollback exceeds configured threshold but using logical advance "
                    "rollback_ms=%s threshold_ms=%s",
                    rollback_ms,
                    self.config.max_clock_rollback_ms,
                )
            return self._last_timestamp_ms

        # WAIT policy
        if rollback_ms > self.config.max_clock_rollback_ms:
            raise ClockRollbackError(
                f"clock rollback {rollback_ms}ms exceeds max allowed "
                f"{self.config.max_clock_rollback_ms}ms"
            )

        return self._wait_for_next_ms(self._last_timestamp_ms)

    def _wait_for_next_ms(self, floor_ms: int) -> int:
        """
        Wait until wall clock exceeds floor_ms.
        Bounded micro-sleeps avoid pathological pure busy-spin.
        """
        start = time.perf_counter()
        ts_ms = self._now_ms()

        while ts_ms <= floor_ms:
            time.sleep(self.config.spin_sleep_seconds)
            ts_ms = self._now_ms()

            waited_ms = (time.perf_counter() - start) * 1000.0
            if waited_ms > max(self.config.max_clock_rollback_ms, 1000):
                raise SequenceOverflowError(
                    f"unable to advance timestamp beyond {floor_ms}ms "
                    f"after waiting {waited_ms:.3f}ms"
                )

        return ts_ms


# ============================================================================
# NODE ID DERIVATION
# ============================================================================

def _stable_host_fingerprint() -> str:
    """
    Stable-ish host/process namespace fingerprint.
    Not a substitute for explicit node assignment, but stronger than PID+sum(hostname).
    """
    hostname = socket.gethostname()
    fqdn = socket.getfqdn()
    pid = os.getpid()
    ppid = os.getppid()

    payload = f"{hostname}|{fqdn}|{pid}|{ppid}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def derive_node_id(
    *,
    explicit_node_id: Optional[int] = None,
    node_id_bits: int = DEFAULT_NODE_ID_BITS,
) -> int:
    """
    Derive a safe node ID.

    Priority:
    1. explicit parameter
    2. env PK_NODE_ID
    3. hashed host/process fingerprint fallback
    """
    max_node_id = (1 << node_id_bits) - 1

    if explicit_node_id is not None:
        if not (0 <= explicit_node_id <= max_node_id):
            raise InvalidNodeIDError(
                f"explicit node_id={explicit_node_id} out of range 0..{max_node_id}"
            )
        return explicit_node_id

    env_value = os.getenv("PK_NODE_ID")
    if env_value is not None:
        try:
            node_id = int(env_value)
        except ValueError as exc:
            raise InvalidNodeIDError(f"invalid PK_NODE_ID={env_value!r}") from exc

        if not (0 <= node_id <= max_node_id):
            raise InvalidNodeIDError(
                f"PK_NODE_ID={node_id} out of range 0..{max_node_id}"
            )
        return node_id

    digest = _stable_host_fingerprint()
    return int(digest[:8], 16) % (max_node_id + 1)


# ============================================================================
# SINGLETON AUTHORITY
# ============================================================================

_ID_AUTHORITY: Optional[IDGenerator] = None
_ID_AUTHORITY_LOCK = threading.RLock()


def build_default_config(*, explicit_node_id: Optional[int] = None) -> IDGeneratorConfig:
    node_id = derive_node_id(explicit_node_id=explicit_node_id)

    rollback_policy_raw = os.getenv("PK_ID_ROLLBACK_POLICY", ClockRollbackPolicy.WAIT.value)
    try:
        rollback_policy = ClockRollbackPolicy(rollback_policy_raw.upper())
    except ValueError:
        logger.warning(
            "[ID_GEN] invalid PK_ID_ROLLBACK_POLICY=%r, defaulting to WAIT",
            rollback_policy_raw,
        )
        rollback_policy = ClockRollbackPolicy.WAIT

    prefix = os.getenv("PK_CLIENT_ORDER_PREFIX", DEFAULT_CLIENT_ORDER_PREFIX)
    version = os.getenv("PK_CLIENT_ORDER_FORMAT_VERSION", DEFAULT_CLIENT_ORDER_FORMAT_VERSION)

    return IDGeneratorConfig(
        node_id=node_id,
        rollback_policy=rollback_policy,
        client_order_prefix=prefix,
        client_order_format_version=version,
    )


def get_id_authority() -> IDGenerator:
    """
    Lazy singleton accessor.
    """
    global _ID_AUTHORITY

    if _ID_AUTHORITY is not None:
        return _ID_AUTHORITY

    with _ID_AUTHORITY_LOCK:
        if _ID_AUTHORITY is None:
            _ID_AUTHORITY = IDGenerator(build_default_config())
        return _ID_AUTHORITY


def configure_id_authority(config: IDGeneratorConfig) -> IDGenerator:
    """
    Explicitly install singleton authority.
    Intended for bootstrap, tests, sim, replay, or controlled deployment.
    """
    global _ID_AUTHORITY
    with _ID_AUTHORITY_LOCK:
        _ID_AUTHORITY = IDGenerator(config)
        return _ID_AUTHORITY


def reset_id_authority() -> None:
    """
    Test/support utility to clear singleton authority.
    """
    global _ID_AUTHORITY
    with _ID_AUTHORITY_LOCK:
        _ID_AUTHORITY = None


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def generate_id() -> int:
    return get_id_authority().generate()


def generate_string_id() -> str:
    return get_id_authority().generate_str()


def generate_event_id() -> int:
    return get_id_authority().generate_event_id()


def generate_signal_id() -> int:
    return get_id_authority().generate_signal_id()


def generate_order_id() -> int:
    return get_id_authority().generate_order_id()


def generate_fill_id() -> int:
    return get_id_authority().generate_fill_id()


def generate_correlation_id() -> int:
    return get_id_authority().generate_correlation_id()


def generate_request_id() -> int:
    return get_id_authority().generate_request_id()


def generate_order_cid(
    *,
    sleeve: Optional[str] = None,
    strategy: Optional[str] = None,
    max_length: int = 48,
) -> str:
    return get_id_authority().generate_client_order_id(
        sleeve=sleeve,
        strategy=strategy,
        max_length=max_length,
    )


def decode_id(id_value: int) -> IDComponents:
    return get_id_authority().decode(id_value)


# ============================================================================
# HELPERS
# ============================================================================

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _to_base36(value: int) -> str:
    if value < 0:
        raise ValueError("base36 conversion requires non-negative integer")
    if value == 0:
        return "0"

    chars = []
    while value:
        value, rem = divmod(value, 36)
        chars.append(_ALPHABET[rem])
    return "".join(reversed(chars))


def _sanitize_tag(
    value: str,
    *,
    upper: bool = True,
    max_len: int = 12,
) -> str:
    """
    ASCII-safe compact tag for exchange-facing identifiers.
    Keeps only alnum characters.
    """
    cleaned = "".join(ch for ch in value if ch.isalnum())
    if upper:
        cleaned = cleaned.upper()
    return cleaned[:max_len]


__all__ = [
    "DEFAULT_EPOCH_MS",
    "DEFAULT_NODE_ID_BITS",
    "DEFAULT_SEQUENCE_BITS",
    "DEFAULT_MAX_CLOCK_ROLLBACK_MS",
    "DEFAULT_SPIN_SLEEP_SECONDS",
    "DEFAULT_CLIENT_ORDER_PREFIX",
    "DEFAULT_CLIENT_ORDER_FORMAT_VERSION",

    "IDGenerationError",
    "ClockRollbackError",
    "SequenceOverflowError",
    "InvalidNodeIDError",
    "ClockRollbackPolicy",

    "IDComponents",
    "IDGeneratorConfig",
    "IDGenerator",

    "derive_node_id",
    "build_default_config",
    "get_id_authority",
    "configure_id_authority",
    "reset_id_authority",

    "generate_id",
    "generate_string_id",
    "generate_event_id",
    "generate_signal_id",
    "generate_order_id",
    "generate_fill_id",
    "generate_correlation_id",
    "generate_request_id",
    "generate_order_cid",
    "decode_id",
]
