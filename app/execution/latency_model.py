"""
app/execution/latency_model.py
POVERTY_KILLER — SOVEREIGN TEMPORAL CONGESTION AUTHORITY (CITADEL-GRADE)

This module is the canonical latency and timing perturbation authority for
simulation and paper execution. It models transport and venue timing with
bounded stochastic behavior, deterministic replay support, congestion regimes,
loss/timeout conditions, and typed telemetry.

ARCHITECTURAL ROLE
------------------
Owns locally:
- latency sampling
- packet loss / timeout simulation
- congestion state modeling
- observed latency telemetry
- latency journaling

Does NOT own:
- exchange truth generation
- system health authority
- execution authority
- network stack implementation

DESIGN PRINCIPLES
-----------------
1. Deterministic Option
   The model supports seeded pseudo-randomness for replay-safe simulation.

2. Structured Timing Surface
   Total latency is decomposed into network and processing components.

3. Conservative Degradation
   Congestion, loss, and timeout states are explicit and journaled.

4. Compatibility Preservation
   get_current_latency_ns(...) and model_packet_loss(...) are preserved while
   richer canonical APIs are added.

5. Risk Mitigation First
   Observed latency state is surfaced, not hidden behind a single number.
"""

from __future__ import annotations

import logging
import random
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation, getcontext
from enum import Enum, unique
from typing import Any, Dict, List, Optional

getcontext().prec = 28
logger = logging.getLogger(__name__)


# ============================================================================
# HELPERS
# ============================================================================

ZERO = Decimal("0")
ONE = Decimal("1")
NS_PER_MS = 1_000_000


def _d(value: Any, *, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"invalid decimal for {field_name}: {value!r}") from exc


def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
    if value < ZERO:
        raise ValueError(f"{field_name} must be >= 0, got {value}")
    return value


# ============================================================================
# ENUMS
# ============================================================================

@unique
class LatencyQuality(str, Enum):
    COMPLETE = "COMPLETE"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"


@unique
class LatencyMode(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    STOCHASTIC = "STOCHASTIC"


@unique
class CongestionState(str, Enum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    CONGESTED = "CONGESTED"
    UNSTABLE = "UNSTABLE"


@unique
class LatencyEventType(str, Enum):
    LATENCY_SAMPLED = "LATENCY_SAMPLED"
    PACKET_LOSS = "PACKET_LOSS"
    PACKET_TIMEOUT = "PACKET_TIMEOUT"
    CONGESTION_TRANSITION = "CONGESTION_TRANSITION"


# ============================================================================
# MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class LatencyPolicyConfig:
    base_latency_ms: Decimal = Decimal("20")
    jitter_ms: Decimal = Decimal("10")
    exchange_processing_ms: Decimal = Decimal("5")

    packet_loss_rate: Decimal = Decimal("0.0001")
    timeout_rate: Decimal = Decimal("0.00005")

    degraded_multiplier: Decimal = Decimal("1.5")
    congested_multiplier: Decimal = Decimal("2.5")
    unstable_multiplier: Decimal = Decimal("4.0")

    congestion_transition_rate: Decimal = Decimal("0.01")
    degradation_transition_rate: Decimal = Decimal("0.03")

    deterministic_seed: Optional[int] = None
    journal_capacity: int = 50000

    def __post_init__(self) -> None:
        for field_name in [
            "base_latency_ms",
            "jitter_ms",
            "exchange_processing_ms",
            "packet_loss_rate",
            "timeout_rate",
            "degraded_multiplier",
            "congested_multiplier",
            "unstable_multiplier",
            "congestion_transition_rate",
            "degradation_transition_rate",
        ]:
            dec = _ensure_non_negative(_d(getattr(self, field_name), field_name=field_name), field_name)
            object.__setattr__(self, field_name, dec)

        for field_name in [
            "packet_loss_rate",
            "timeout_rate",
            "congestion_transition_rate",
            "degradation_transition_rate",
        ]:
            if getattr(self, field_name) > ONE:
                raise ValueError(f"{field_name} cannot exceed 1")

        if self.journal_capacity < 100:
            raise ValueError("journal_capacity must be >= 100")


@dataclass(frozen=True, slots=True)
class LatencySample:
    total_latency_ns: int
    network_latency_ns: int
    exchange_processing_ns: int
    jitter_component_ns: int

    packet_lost: bool
    timed_out: bool

    mode: LatencyMode
    congestion_state: CongestionState
    confidence: Decimal
    quality: LatencyQuality
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LatencyStatsSnapshot:
    sample_count: int
    avg_total_latency_ns: int
    max_total_latency_ns: int
    packet_loss_count: int
    timeout_count: int
    current_congestion_state: CongestionState
    quality: LatencyQuality


@dataclass(frozen=True, slots=True)
class LatencyJournalRecord:
    sequence: int
    event_type: LatencyEventType
    sample_count: int
    congestion_state: CongestionState
    payload: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# ENGINE
# ============================================================================

class LatencyModel:
    """
    Sovereign timing authority.

    Legacy:
        get_current_latency_ns(...)
        model_packet_loss(...)
        get_stats(...)

    Canonical:
        sample_latency(...)
        telemetry_snapshot(...)
        journal(...)
    """

    def __init__(
        self,
        base_latency_ms: int = 20,
        jitter_ms: int = 10,
        exchange_processing_ms: int = 5
    ):
        self.policy = LatencyPolicyConfig(
            base_latency_ms=Decimal(str(base_latency_ms)),
            jitter_ms=Decimal(str(jitter_ms)),
            exchange_processing_ms=Decimal(str(exchange_processing_ms)),
        )

        # Preserve legacy attribute names
        self.base = base_latency_ms
        self.jitter = jitter_ms
        self.processing = exchange_processing_ms

        self._rng = random.Random(self.policy.deterministic_seed)
        self._mode = LatencyMode.DETERMINISTIC if self.policy.deterministic_seed is not None else LatencyMode.STOCHASTIC
        self._congestion_state = CongestionState.NORMAL

        self._samples: List[LatencySample] = []
        self._journal: List[LatencyJournalRecord] = []
        self._journal_seq = 0

    # ------------------------------------------------------------------
    # Legacy compatibility API
    # ------------------------------------------------------------------

    def get_current_latency_ns(self) -> int:
        """
        Legacy-compatible latency sample.
        Returns only total latency nanoseconds.
        """
        return self.sample_latency().total_latency_ns

    def model_packet_loss(self, loss_rate: float = 0.0001) -> bool:
        """
        Legacy-compatible packet loss Bernoulli.

        This path is preserved, but canonical simulations should prefer
        sample_latency(...), which models latency/loss/timeout together.
        """
        loss_rate_dec = _ensure_non_negative(_d(loss_rate, field_name="loss_rate"), "loss_rate")
        if loss_rate_dec > ONE:
            raise ValueError("loss_rate cannot exceed 1")
        dropped = self._rng.random() < float(loss_rate_dec)
        if dropped:
            self._append_journal(
                event_type=LatencyEventType.PACKET_LOSS,
                payload={"legacy_loss_rate": str(loss_rate_dec)},
            )
        return dropped

    def get_stats(self) -> Dict[str, float]:
        """
        Legacy-compatible stats surface.

        Unlike the original stub, this returns observed sample stats where
        available, not merely policy echoes.
        """
        snap = self.telemetry_snapshot()
        return {
            "avg_latency": float(Decimal(snap.avg_total_latency_ns) / Decimal(NS_PER_MS)) if snap.sample_count > 0 else float(self.policy.base_latency_ms + self.policy.exchange_processing_ms),
            "expected_jitter": float(self.policy.jitter_ms),
        }

    # ------------------------------------------------------------------
    # Canonical API
    # ------------------------------------------------------------------

    def sample_latency(self) -> LatencySample:
        """
        Canonical timing sample.
        """
        prior_state = self._congestion_state
        self._maybe_transition_congestion()

        notes: List[str] = []
        quality = LatencyQuality.COMPLETE
        confidence = Decimal("1.0")

        state_multiplier = self._state_multiplier(self._congestion_state)

        base_network_ms = self.policy.base_latency_ms * state_multiplier
        processing_ms = self.policy.exchange_processing_ms * state_multiplier

        # bounded-ish gaussian sample with congestion scaling
        jitter_sigma_ms = self.policy.jitter_ms * state_multiplier
        jitter_sample_ms = Decimal(str(self._rng.gauss(0.0, float(jitter_sigma_ms))))

        # lower bound: network latency should not go negative
        network_ms = max(Decimal("0"), base_network_ms + jitter_sample_ms)
        total_ms = network_ms + processing_ms

        packet_lost = self._rng.random() < float(self.policy.packet_loss_rate * self._loss_multiplier(self._congestion_state))
        timed_out = False
        if not packet_lost:
            timed_out = self._rng.random() < float(self.policy.timeout_rate * self._timeout_multiplier(self._congestion_state))

        if packet_lost:
            quality = LatencyQuality.DEGRADED
            confidence = Decimal("0.6")
            notes.append("packet_lost")
        if timed_out:
            quality = LatencyQuality.DEGRADED
            confidence = min(confidence, Decimal("0.5"))
            notes.append("packet_timeout")
        if self._congestion_state != CongestionState.NORMAL:
            quality = LatencyQuality.DEGRADED
            confidence = min(confidence, Decimal("0.8"))
            notes.append(f"congestion_state={self._congestion_state.value}")

        sample = LatencySample(
            total_latency_ns=int(total_ms * NS_PER_MS),
            network_latency_ns=int(network_ms * NS_PER_MS),
            exchange_processing_ns=int(processing_ms * NS_PER_MS),
            jitter_component_ns=int(jitter_sample_ms * NS_PER_MS),
            packet_lost=packet_lost,
            timed_out=timed_out,
            mode=self._mode,
            congestion_state=self._congestion_state,
            confidence=confidence,
            quality=quality,
            notes=tuple(notes),
        )

        self._samples.append(sample)
        self._append_journal(
            event_type=LatencyEventType.LATENCY_SAMPLED,
            payload={
                "total_latency_ns": sample.total_latency_ns,
                "packet_lost": sample.packet_lost,
                "timed_out": sample.timed_out,
                "quality": sample.quality.value,
            },
        )

        if prior_state != self._congestion_state:
            self._append_journal(
                event_type=LatencyEventType.CONGESTION_TRANSITION,
                payload={
                    "from": prior_state.value,
                    "to": self._congestion_state.value,
                },
            )

        return sample

    def telemetry_snapshot(self) -> LatencyStatsSnapshot:
        if not self._samples:
            return LatencyStatsSnapshot(
                sample_count=0,
                avg_total_latency_ns=0,
                max_total_latency_ns=0,
                packet_loss_count=0,
                timeout_count=0,
                current_congestion_state=self._congestion_state,
                quality=LatencyQuality.PARTIAL,
            )

        sample_count = len(self._samples)
        total_sum = sum(s.total_latency_ns for s in self._samples)
        max_latency = max(s.total_latency_ns for s in self._samples)
        packet_loss_count = sum(1 for s in self._samples if s.packet_lost)
        timeout_count = sum(1 for s in self._samples if s.timed_out)

        quality = LatencyQuality.COMPLETE
        if packet_loss_count > 0 or timeout_count > 0 or self._congestion_state != CongestionState.NORMAL:
            quality = LatencyQuality.DEGRADED

        return LatencyStatsSnapshot(
            sample_count=sample_count,
            avg_total_latency_ns=int(total_sum / sample_count),
            max_total_latency_ns=max_latency,
            packet_loss_count=packet_loss_count,
            timeout_count=timeout_count,
            current_congestion_state=self._congestion_state,
            quality=quality,
        )

    def journal(self, limit: Optional[int] = None) -> List[LatencyJournalRecord]:
        if limit is None or limit >= len(self._journal):
            return list(self._journal)
        return self._journal[-limit:]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _maybe_transition_congestion(self) -> None:
        state = self._congestion_state
        roll = Decimal(str(self._rng.random()))

        if state == CongestionState.NORMAL:
            if roll < self.policy.congestion_transition_rate:
                self._congestion_state = CongestionState.DEGRADED
            return

        if state == CongestionState.DEGRADED:
            if roll < self.policy.congestion_transition_rate / Decimal("2"):
                self._congestion_state = CongestionState.CONGESTED
            elif roll < self.policy.degradation_transition_rate:
                self._congestion_state = CongestionState.NORMAL
            return

        if state == CongestionState.CONGESTED:
            if roll < self.policy.congestion_transition_rate / Decimal("4"):
                self._congestion_state = CongestionState.UNSTABLE
            elif roll < self.policy.degradation_transition_rate:
                self._congestion_state = CongestionState.DEGRADED
            return

        # UNSTABLE
        if roll < self.policy.degradation_transition_rate:
            self._congestion_state = CongestionState.CONGESTED

    def _state_multiplier(self, state: CongestionState) -> Decimal:
        if state == CongestionState.DEGRADED:
            return self.policy.degraded_multiplier
        if state == CongestionState.CONGESTED:
            return self.policy.congested_multiplier
        if state == CongestionState.UNSTABLE:
            return self.policy.unstable_multiplier
        return Decimal("1.0")

    def _loss_multiplier(self, state: CongestionState) -> Decimal:
        if state == CongestionState.DEGRADED:
            return Decimal("2.0")
        if state == CongestionState.CONGESTED:
            return Decimal("5.0")
        if state == CongestionState.UNSTABLE:
            return Decimal("10.0")
        return Decimal("1.0")

    def _timeout_multiplier(self, state: CongestionState) -> Decimal:
        if state == CongestionState.DEGRADED:
            return Decimal("2.0")
        if state == CongestionState.CONGESTED:
            return Decimal("4.0")
        if state == CongestionState.UNSTABLE:
            return Decimal("8.0")
        return Decimal("1.0")

    def _append_journal(
        self,
        *,
        event_type: LatencyEventType,
        payload: Dict[str, Any],
    ) -> None:
        self._journal_seq += 1
        self._journal.append(
            LatencyJournalRecord(
                sequence=self._journal_seq,
                event_type=event_type,
                sample_count=len(self._samples),
                congestion_state=self._congestion_state,
                payload=payload,
            )
        )
        if len(self._journal) > self.policy.journal_capacity:
            self._journal = self._journal[-self.policy.journal_capacity:]


__all__ = [
    "LatencyQuality",
    "LatencyMode",
    "CongestionState",
    "LatencyEventType",
    "LatencyPolicyConfig",
    "LatencySample",
    "LatencyStatsSnapshot",
    "LatencyJournalRecord",
    "LatencyModel",
]
