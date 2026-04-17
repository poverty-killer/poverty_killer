"""
app/monitoring/reports.py
POVERTY_KILLER — SOVEREIGN FORENSIC REPORTING ENGINE (CITADEL-GRADE)

This module is the canonical reporting and forensic packet authority for the
platform. It transforms structured runtime state into replay-safe, auditable,
versioned report packets suitable for board review, forensic inspection,
compliance export, and operational postmortem analysis.

ARCHITECTURAL ROLE
------------------
Owns locally:
- report packet construction
- canonical report serialization
- packet metadata / schema versioning
- report journaling
- digest generation
- safe file-output support
- compatibility packet generation adapters

Does NOT own:
- source state generation
- business metric truth generation
- execution authority
- persistence backends beyond local file support

DESIGN PRINCIPLES
-----------------
1. Canonical Over Ad Hoc
   Report packets are typed, versioned, and schema-stable.

2. Decimal Preservation
   Monetary values remain exact through serialization.

3. Replay and Audit Friendliness
   Explicit timestamps, packet ids, completeness flags, and digests are included.

4. Bounded Reporting Role
   This module packages truth; it does not invent or reinterpret upstream truth.

5. Preserve-Aware Compatibility
   The simple generate_daily_packet(...) surface is retained as a compatibility
   adapter over the richer canonical engine.

6. Risk Mitigation First
   Where canonical timestamps are unavailable, the engine does not fabricate
   false deterministic truth. It marks the packet degraded and records the
   timestamp-source limitation explicitly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum, unique
from typing import Any, Dict, List, Optional, Sequence

from app.utils.ids import generate_correlation_id, generate_request_id

logger = logging.getLogger(__name__)


# ============================================================================
# HELPERS
# ============================================================================

SCHEMA_VERSION = "2.0.1"


def _d(value: Any, *, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"invalid decimal for {field_name}: {value!r}") from exc


def _canonical_json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, tuple):
        return list(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _canonical_json_dumps(payload: Any, *, pretty: bool = True) -> str:
    return json.dumps(
        payload,
        default=_canonical_json_default,
        indent=4 if pretty else None,
        sort_keys=True,
        ensure_ascii=False,
    )


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_ns() -> int:
    return time.time_ns()


# ============================================================================
# ENUMS
# ============================================================================

@unique
class ReportType(str, Enum):
    DAILY_PACKET = "DAILY_PACKET"
    BOARD_PACKET = "BOARD_PACKET"
    INCIDENT_PACKET = "INCIDENT_PACKET"
    RISK_PACKET = "RISK_PACKET"
    EXECUTION_PACKET = "EXECUTION_PACKET"
    RECOVERY_PACKET = "RECOVERY_PACKET"
    REPLAY_PACKET = "REPLAY_PACKET"


@unique
class ReportQuality(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


@unique
class TimestampSource(str, Enum):
    EXPLICIT_INPUT = "EXPLICIT_INPUT"
    LOCAL_GENERATION_TIME = "LOCAL_GENERATION_TIME"
    UNKNOWN = "UNKNOWN"


# ============================================================================
# MODELS
# ============================================================================

@dataclass(frozen=True, slots=True)
class ReportConfig:
    output_path: str = "./reports"
    environment: str = "UNKNOWN"
    pretty_json: bool = True
    atomic_write: bool = True
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class ReportMetadata:
    report_id: str
    correlation_id: int
    report_type: ReportType
    schema_version: str
    timestamp_ns: int
    timestamp_source: TimestampSource
    generated_by: str = "app.monitoring.reports"
    environment: str = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class PerformanceSummary:
    starting_equity: Decimal
    ending_equity: Decimal
    absolute_pnl: Decimal
    return_pct: Decimal
    total_trades: int
    attribution: Dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReportPacket:
    metadata: ReportMetadata
    quality: ReportQuality
    completeness_notes: tuple[str, ...]
    performance: PerformanceSummary
    health: Dict[str, Any]
    attribution_stats: Dict[str, Any]
    trade_history: List[Dict[str, Any]]
    audit_trail_length: int
    digest_sha256: Optional[str] = None


@dataclass(frozen=True, slots=True)
class ReportGenerationResult:
    success: bool
    packet: Optional[ReportPacket]
    json_payload: str
    output_file: Optional[str]
    digest_sha256: Optional[str]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReportJournalRecord:
    sequence: int
    report_id: str
    report_type: ReportType
    timestamp_ns: int
    timestamp_source: TimestampSource
    quality: ReportQuality
    output_file: Optional[str]
    digest_sha256: Optional[str]


# ============================================================================
# ENGINE
# ============================================================================

class ReportGenerator:
    """
    Sovereign audit reporter.

    Canonical packet path:
        build_packet(...) -> serialize_packet(...) -> write_packet(...)

    Legacy compatibility path:
        generate_daily_packet(...)

    Important:
    The legacy path does not fabricate deterministic/replay-safe event time
    if the caller does not provide one. It uses local generation time and
    explicitly marks the packet as degraded for forensic honesty.
    """

    def __init__(self, output_path: str = "./reports/"):
        normalized = output_path.rstrip("/\\")
        self.config = ReportConfig(output_path=normalized or "./reports")
        self.output_path = self.config.output_path

        self._journal_seq = 0
        self._journal: List[ReportJournalRecord] = []

    # ------------------------------------------------------------------
    # Canonical API
    # ------------------------------------------------------------------

    def build_packet(
        self,
        *,
        report_type: ReportType,
        timestamp_ns: int,
        equity_curve: Sequence[Decimal],
        trade_history: Sequence[Dict[str, Any]],
        attribution_stats: Dict[str, Any],
        health_summary: Dict[str, Any],
        environment: Optional[str] = None,
        timestamp_source: TimestampSource = TimestampSource.EXPLICIT_INPUT,
    ) -> ReportPacket:
        """
        Build canonical structured report packet.

        timestamp_ns should represent the caller-authoritative report time.
        If a caller cannot provide canonical time, it may use local generation
        time, but the packet should then be marked degraded via timestamp_source.
        """
        warnings: List[str] = []
        quality = ReportQuality.COMPLETE

        if timestamp_ns <= 0:
            raise ValueError("timestamp_ns must be positive")

        normalized_curve = [_d(v, field_name="equity_curve") for v in equity_curve]
        normalized_trades = [dict(t) for t in trade_history]
        normalized_attribution = self._normalize_mapping(attribution_stats)
        normalized_health = self._normalize_mapping(health_summary)

        if timestamp_source != TimestampSource.EXPLICIT_INPUT:
            quality = ReportQuality.DEGRADED
            warnings.append(f"timestamp_source={timestamp_source.value}")

        if not normalized_curve:
            quality = ReportQuality.PARTIAL if quality == ReportQuality.COMPLETE else quality
            warnings.append("equity_curve_empty")
            starting = Decimal("0")
            ending = Decimal("0")
        else:
            starting = normalized_curve[0]
            ending = normalized_curve[-1]

        absolute_pnl = ending - starting
        return_pct = Decimal("0")
        if starting > 0:
            return_pct = absolute_pnl / starting

        metadata = ReportMetadata(
            report_id=f"PKR-{generate_request_id()}",
            correlation_id=generate_correlation_id(),
            report_type=report_type,
            schema_version=self.config.schema_version,
            timestamp_ns=timestamp_ns,
            timestamp_source=timestamp_source,
            environment=environment or self.config.environment,
        )

        performance = PerformanceSummary(
            starting_equity=starting,
            ending_equity=ending,
            absolute_pnl=absolute_pnl,
            return_pct=return_pct,
            total_trades=len(normalized_trades),
            attribution=normalized_attribution,
        )

        return ReportPacket(
            metadata=metadata,
            quality=quality,
            completeness_notes=tuple(warnings),
            performance=performance,
            health=normalized_health,
            attribution_stats=normalized_attribution,
            trade_history=normalized_trades,
            audit_trail_length=len(normalized_trades),
            digest_sha256=None,
        )

    def serialize_packet(self, packet: ReportPacket) -> str:
        """
        Serialize packet canonically and embed digest.
        """
        base_dict = asdict(packet)
        base_dict["digest_sha256"] = None

        json_without_digest = _canonical_json_dumps(base_dict, pretty=self.config.pretty_json)
        digest = _sha256_hex(json_without_digest)

        final_packet = replace_digest(packet, digest)
        return _canonical_json_dumps(asdict(final_packet), pretty=self.config.pretty_json)

    def write_packet(
        self,
        packet: ReportPacket,
        *,
        filename: Optional[str] = None,
    ) -> ReportGenerationResult:
        """
        Serialize and safely write packet to local filesystem.
        """
        warnings: List[str] = []
        errors: List[str] = []

        try:
            json_payload = self.serialize_packet(packet)
            digest = replace_digest(packet, None).digest_sha256
            digest = _sha256_hex(
                _canonical_json_dumps(
                    {**asdict(packet), "digest_sha256": None},
                    pretty=self.config.pretty_json,
                )
            )

            os.makedirs(self.output_path, exist_ok=True)

            if filename is None:
                filename = f"PK_REPORT_{packet.metadata.report_id}.json"

            output_file = os.path.join(self.output_path, filename)

            if self.config.atomic_write:
                self._atomic_write(output_file, json_payload)
            else:
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(json_payload)

            finalized_packet = replace_digest(packet, digest)

            self._append_journal(
                report_id=packet.metadata.report_id,
                report_type=packet.metadata.report_type,
                timestamp_ns=packet.metadata.timestamp_ns,
                timestamp_source=packet.metadata.timestamp_source,
                quality=packet.quality,
                output_file=output_file,
                digest_sha256=digest,
            )

            logger.info("[REPORT] packet_written report_id=%s file=%s", packet.metadata.report_id, output_file)

            return ReportGenerationResult(
                success=True,
                packet=finalized_packet,
                json_payload=json_payload,
                output_file=output_file,
                digest_sha256=digest,
                warnings=tuple(warnings),
                errors=tuple(errors),
            )

        except Exception as e:
            logger.error("[REPORT_FAILED] packet_write_error: %s", e, exc_info=True)
            errors.append(str(e))
            return ReportGenerationResult(
                success=False,
                packet=None,
                json_payload="{}",
                output_file=None,
                digest_sha256=None,
                warnings=tuple(warnings),
                errors=tuple(errors),
            )

    def generate_packet(
        self,
        *,
        report_type: ReportType,
        timestamp_ns: int,
        equity_curve: Sequence[Decimal],
        trade_history: Sequence[Dict[str, Any]],
        attribution_stats: Dict[str, Any],
        health_summary: Dict[str, Any],
        environment: Optional[str] = None,
        write_to_disk: bool = False,
        timestamp_source: TimestampSource = TimestampSource.EXPLICIT_INPUT,
    ) -> ReportGenerationResult:
        packet = self.build_packet(
            report_type=report_type,
            timestamp_ns=timestamp_ns,
            equity_curve=equity_curve,
            trade_history=trade_history,
            attribution_stats=attribution_stats,
            health_summary=health_summary,
            environment=environment,
            timestamp_source=timestamp_source,
        )

        if write_to_disk:
            return self.write_packet(packet)

        payload = self.serialize_packet(packet)
        digest = _sha256_hex(
            _canonical_json_dumps(
                {**asdict(packet), "digest_sha256": None},
                pretty=self.config.pretty_json,
            )
        )

        finalized_packet = replace_digest(packet, digest)

        self._append_journal(
            report_id=packet.metadata.report_id,
            report_type=packet.metadata.report_type,
            timestamp_ns=packet.metadata.timestamp_ns,
            timestamp_source=packet.metadata.timestamp_source,
            quality=packet.quality,
            output_file=None,
            digest_sha256=digest,
        )

        return ReportGenerationResult(
            success=True,
            packet=finalized_packet,
            json_payload=payload,
            output_file=None,
            digest_sha256=digest,
            warnings=tuple(packet.completeness_notes),
            errors=tuple(),
        )

    def report_journal(self, limit: Optional[int] = None) -> List[ReportJournalRecord]:
        if limit is None or limit >= len(self._journal):
            return list(self._journal)
        return self._journal[-limit:]

    # ------------------------------------------------------------------
    # Legacy compatibility API
    # ------------------------------------------------------------------

    def generate_daily_packet(
        self,
        equity_curve: List[Decimal],
        trade_history: List[Dict],
        attribution_stats: Dict[str, Any],
        health_summary: Dict[str, Any]
    ) -> str:
        """
        Legacy compatibility adapter.

        Preserves the old method shape and return type (JSON string), while
        delegating to the richer canonical reporting engine.

        IMPORTANT:
        Because the legacy signature does not provide an explicit timestamp_ns,
        this adapter uses local generation time and marks the packet as DEGRADED
        via timestamp_source=LOCAL_GENERATION_TIME. This avoids fabricating
        false deterministic timing truth.
        """
        result = self.generate_packet(
            report_type=ReportType.DAILY_PACKET,
            timestamp_ns=_now_ns(),
            timestamp_source=TimestampSource.LOCAL_GENERATION_TIME,
            equity_curve=equity_curve,
            trade_history=trade_history,
            attribution_stats=attribution_stats,
            health_summary=health_summary,
            write_to_disk=False,
        )

        if not result.success:
            return "{}"
        return result.json_payload

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_mapping(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k, v in payload.items():
            out[str(k)] = self._normalize_value(v)
        return out

    def _normalize_value(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            return value
        if isinstance(value, Enum):
            return value.value
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return {str(k): self._normalize_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._normalize_value(v) for v in value]
        if isinstance(value, tuple):
            return [self._normalize_value(v) for v in value]
        return value

    def _atomic_write(self, path: str, payload: str) -> None:
        directory = os.path.dirname(path) or "."
        fd, temp_path = tempfile.mkstemp(dir=directory, prefix=".pkt_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
        except Exception:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            finally:
                raise

    def _append_journal(
        self,
        *,
        report_id: str,
        report_type: ReportType,
        timestamp_ns: int,
        timestamp_source: TimestampSource,
        quality: ReportQuality,
        output_file: Optional[str],
        digest_sha256: Optional[str],
    ) -> None:
        self._journal_seq += 1
        self._journal.append(
            ReportJournalRecord(
                sequence=self._journal_seq,
                report_id=report_id,
                report_type=report_type,
                timestamp_ns=timestamp_ns,
                timestamp_source=timestamp_source,
                quality=quality,
                output_file=output_file,
                digest_sha256=digest_sha256,
            )
        )


def replace_digest(packet: ReportPacket, digest: Optional[str]) -> ReportPacket:
    return ReportPacket(
        metadata=packet.metadata,
        quality=packet.quality,
        completeness_notes=packet.completeness_notes,
        performance=packet.performance,
        health=packet.health,
        attribution_stats=packet.attribution_stats,
        trade_history=packet.trade_history,
        audit_trail_length=packet.audit_trail_length,
        digest_sha256=digest,
    )


__all__ = [
    "ReportType",
    "ReportQuality",
    "TimestampSource",
    "ReportConfig",
    "ReportMetadata",
    "PerformanceSummary",
    "ReportPacket",
    "ReportGenerationResult",
    "ReportJournalRecord",
    "ReportGenerator",
]
