from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from app.utils.time_utils import now_ns


NS_PER_MS = 1_000_000

MARKET_TRUTH_SNAPSHOT_MISSING = "MARKET_TRUTH_SNAPSHOT_MISSING"
CANDIDATE_SNAPSHOT_STALE = "CANDIDATE_SNAPSHOT_STALE"
MARKET_TRUTH_CONFLICT = "MARKET_TRUTH_CONFLICT"
SNAPSHOT_SYMBOL_MISMATCH = "SNAPSHOT_SYMBOL_MISMATCH"
SNAPSHOT_SOURCE_UNEXECUTABLE = "SNAPSHOT_SOURCE_UNEXECUTABLE"
SNAPSHOT_TIMESTAMP_MISMATCH = "SNAPSHOT_TIMESTAMP_MISMATCH"
STALE_MONITOR_EVIDENCE_IGNORED = "STALE_MONITOR_EVIDENCE_IGNORED"

SNAPSHOT_PASS = "PASS"
SNAPSHOT_BLOCK = "BLOCK"

UNEXECUTABLE_SOURCE_TYPES = frozenset({"backfill", "replay", "synthetic", "observe_only"})


@dataclass(frozen=True, slots=True)
class MarketTruthSnapshot:
    snapshot_id: str
    symbol: str
    book_ts_ns: Optional[int]
    candle_id: Optional[int]
    candle_close_ts_ns: Optional[int]
    provider_id: Optional[str]
    receive_ts_ns: Optional[int]
    book_fresh: bool
    candle_fresh: bool
    executable_market_truth: bool
    source_type: str
    snapshot_status: str
    snapshot_reason_codes: tuple[str, ...]
    snapshot_authority: str
    snapshot_created_ns: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "symbol": self.symbol,
            "book_ts_ns": self.book_ts_ns,
            "candle_id": self.candle_id,
            "candle_close_ts_ns": self.candle_close_ts_ns,
            "provider_id": self.provider_id,
            "receive_ts_ns": self.receive_ts_ns,
            "book_fresh": self.book_fresh,
            "candle_fresh": self.candle_fresh,
            "executable_market_truth": self.executable_market_truth,
            "source_type": self.source_type,
            "snapshot_status": self.snapshot_status,
            "snapshot_reason_codes": self.snapshot_reason_codes,
            "snapshot_authority": self.snapshot_authority,
            "snapshot_created_ns": self.snapshot_created_ns,
        }


def build_market_truth_snapshot(
    *,
    symbol: str,
    market_truth: Mapping[str, Any] | None,
    candle_truth: Mapping[str, Any] | None = None,
    current_ns: Optional[int] = None,
    book_freshness_policy_ms: Optional[float] = None,
) -> dict[str, Any]:
    """
    Build canonical candidate market truth from the candidate's own evidence.

    This object is evidence. It does not invent missing market or broker facts.
    """
    current_ns = int(current_ns or now_ns())
    market = dict(market_truth or {})
    candle = dict(candle_truth or {})
    source_type = _source_type(market, candle)
    book_ts_ns = _int_or_none(market.get("latest_book_ts_ns") or candle.get("latest_book_ts_ns"))
    candle_id = _int_or_none(
        candle.get("consumer_timestamp_ns")
        or candle.get("candle_start_ts_ns")
        or market.get("consumer_exchange_ts_ns")
        or market.get("latest_candle_ts_ns")
        or candle.get("latest_candle_ts_ns")
    )
    candle_close_ts_ns = _int_or_none(candle.get("candle_close_ts_ns") or candle_id)
    receive_ts_ns = _int_or_none(
        candle.get("receive_ts_ns")
        or candle.get("candle_batch_received_ns")
        or market.get("receive_ts_ns")
    )
    provider_id = candle.get("provider_id") or market.get("provider_id")
    provider_id = str(provider_id) if provider_id is not None else None

    candle_policy_ms = _float_or_none(candle.get("candle_freshness_policy_ms"))
    book_policy_ms = _float_or_none(book_freshness_policy_ms)
    if book_policy_ms is None:
        book_policy_ms = _float_or_none(market.get("book_freshness_policy_ms"))
    if book_policy_ms is None:
        book_policy_ms = 5_000.0

    candle_code = str(candle.get("candle_freshness_reason_code") or "")
    data_code = str(candle.get("data_health_reason_code") or market.get("data_health_reason_code") or "")
    executable = bool(candle.get("executable_market_truth") or market.get("executable_market_truth"))
    candle_fresh = candle_code == "CANDLE_RUNTIME_FRESH" and executable is True
    if candle_fresh is not True and candle_close_ts_ns is not None and candle_policy_ms and candle_policy_ms > 0:
        candle_fresh = (
            source_type not in UNEXECUTABLE_SOURCE_TYPES
            and 0 <= (current_ns - candle_close_ts_ns) <= int(candle_policy_ms * NS_PER_MS)
            and executable is True
        )
    book_fresh = False
    if book_ts_ns is not None and book_policy_ms and book_policy_ms > 0:
        book_fresh = 0 <= (current_ns - book_ts_ns) <= int(book_policy_ms * NS_PER_MS)

    reason_codes: list[str] = []
    if not str(symbol or "").strip():
        reason_codes.append(SNAPSHOT_SYMBOL_MISMATCH)
    if source_type in UNEXECUTABLE_SOURCE_TYPES:
        reason_codes.append(SNAPSHOT_SOURCE_UNEXECUTABLE)
    if source_type not in {"runtime"} and source_type not in UNEXECUTABLE_SOURCE_TYPES:
        reason_codes.append(SNAPSHOT_SOURCE_UNEXECUTABLE)
    if candle_id is None or candle_close_ts_ns is None:
        reason_codes.append(SNAPSHOT_TIMESTAMP_MISMATCH)
    if data_code and data_code not in {"DATA_HEALTHY"}:
        reason_codes.append(data_code)
    if candle_code and candle_code not in {"CANDLE_RUNTIME_FRESH"}:
        reason_codes.append(candle_code)
    if executable is not True:
        reason_codes.append("MARKET_TRUTH_SNAPSHOT_NOT_EXECUTABLE")

    status = SNAPSHOT_PASS if not reason_codes and candle_fresh and executable is True else SNAPSHOT_BLOCK
    snapshot_id = _snapshot_id(
        symbol=symbol,
        source_type=source_type,
        candle_id=candle_id,
        candle_close_ts_ns=candle_close_ts_ns,
        book_ts_ns=book_ts_ns,
        provider_id=provider_id,
    )
    snapshot = MarketTruthSnapshot(
        snapshot_id=snapshot_id,
        symbol=str(symbol),
        book_ts_ns=book_ts_ns,
        candle_id=candle_id,
        candle_close_ts_ns=candle_close_ts_ns,
        provider_id=provider_id,
        receive_ts_ns=receive_ts_ns,
        book_fresh=bool(book_fresh),
        candle_fresh=bool(candle_fresh),
        executable_market_truth=bool(executable),
        source_type=source_type,
        snapshot_status=status,
        snapshot_reason_codes=tuple(dict.fromkeys(str(code) for code in reason_codes if str(code))),
        snapshot_authority="candidate_market_truth_snapshot",
        snapshot_created_ns=current_ns,
    ).to_dict()
    snapshot["candle_freshness_policy_ms"] = candle_policy_ms
    snapshot["book_freshness_policy_ms"] = book_policy_ms
    snapshot["data_health_reason_code"] = data_code or None
    snapshot["candle_freshness_reason_code"] = candle_code or None
    return snapshot


def validate_market_snapshot_for_execution(
    snapshot: Mapping[str, Any] | None,
    *,
    signal_symbol: str,
    signal_exchange_ts_ns: Optional[int],
    current_ns: Optional[int] = None,
    monitor_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Validate the candidate snapshot as execution-admission authority.

    Older monitor evidence is preserved as diagnostics and cannot override a
    newer candidate snapshot. Newer contradictory same-symbol truth fails shut.
    """
    current_ns = int(current_ns or now_ns())
    if not isinstance(snapshot, Mapping) or not snapshot:
        return _block(
            MARKET_TRUTH_SNAPSHOT_MISSING,
            signal_symbol=signal_symbol,
            current_ns=current_ns,
            snapshot=None,
            monitor_evidence=monitor_evidence,
        )

    snap = dict(snapshot)
    reason_codes: list[str] = []
    snapshot_symbol = str(snap.get("symbol") or "")
    if snapshot_symbol != str(signal_symbol):
        reason_codes.append(SNAPSHOT_SYMBOL_MISMATCH)

    source_type = str(snap.get("source_type") or "unknown").lower()
    if source_type in UNEXECUTABLE_SOURCE_TYPES or source_type != "runtime":
        reason_codes.append(SNAPSHOT_SOURCE_UNEXECUTABLE)

    candle_id = _int_or_none(snap.get("candle_id"))
    signal_ts = _int_or_none(signal_exchange_ts_ns)
    if signal_ts is not None and candle_id is not None and signal_ts != candle_id:
        reason_codes.append(SNAPSHOT_TIMESTAMP_MISMATCH)
    elif candle_id is None:
        reason_codes.append(SNAPSHOT_TIMESTAMP_MISMATCH)

    if snap.get("executable_market_truth") is not True:
        reason_codes.extend(_snapshot_reason_codes(snap) or ("MARKET_TRUTH_SNAPSHOT_NOT_EXECUTABLE",))

    stale_code = _snapshot_staleness_reason(snap, current_ns=current_ns)
    if stale_code:
        reason_codes.append(stale_code)

    if reason_codes:
        return _block(
            tuple(dict.fromkeys(reason_codes)),
            signal_symbol=signal_symbol,
            current_ns=current_ns,
            snapshot=snap,
            monitor_evidence=monitor_evidence,
        )

    monitor = dict(monitor_evidence or {})
    if monitor and monitor.get("data_healthy") is not True:
        monitor_symbol = monitor.get("symbol")
        if monitor_symbol is not None and str(monitor_symbol) != str(signal_symbol):
            return _block(
                MARKET_TRUTH_CONFLICT,
                signal_symbol=signal_symbol,
                current_ns=current_ns,
                snapshot=snap,
                monitor_evidence=monitor,
            )
        monitor_ts = _int_or_none(monitor.get("last_valid_data_ns"))
        snapshot_ts = _snapshot_authority_ts(snap)
        if monitor_ts is not None and snapshot_ts is not None and monitor_ts >= snapshot_ts:
            return _block(
                MARKET_TRUTH_CONFLICT,
                signal_symbol=signal_symbol,
                current_ns=current_ns,
                snapshot=snap,
                monitor_evidence=monitor,
            )
        return _pass(
            STALE_MONITOR_EVIDENCE_IGNORED,
            signal_symbol=signal_symbol,
            current_ns=current_ns,
            snapshot=snap,
            monitor_evidence=monitor,
        )

    return _pass(
        "CANONICAL_MARKET_SNAPSHOT_ACCEPTED",
        signal_symbol=signal_symbol,
        current_ns=current_ns,
        snapshot=snap,
        monitor_evidence=monitor,
    )


def _snapshot_staleness_reason(snapshot: Mapping[str, Any], *, current_ns: int) -> Optional[str]:
    source_type = str(snapshot.get("source_type") or "unknown").lower()
    if source_type in UNEXECUTABLE_SOURCE_TYPES:
        return SNAPSHOT_SOURCE_UNEXECUTABLE
    candle_close_ts_ns = _int_or_none(snapshot.get("candle_close_ts_ns"))
    if candle_close_ts_ns is None:
        return SNAPSHOT_TIMESTAMP_MISMATCH
    candle_policy_ms = _float_or_none(snapshot.get("candle_freshness_policy_ms"))
    if candle_policy_ms is None or candle_policy_ms <= 0:
        return SNAPSHOT_TIMESTAMP_MISMATCH
    candle_age_ns = current_ns - candle_close_ts_ns
    if candle_age_ns < 0 or candle_age_ns > int(candle_policy_ms * NS_PER_MS):
        return CANDIDATE_SNAPSHOT_STALE

    book_ts_ns = _int_or_none(snapshot.get("book_ts_ns"))
    book_policy_ms = _float_or_none(snapshot.get("book_freshness_policy_ms"))
    if book_ts_ns is not None and book_policy_ms and book_policy_ms > 0:
        book_age_ns = current_ns - book_ts_ns
        if book_age_ns < 0 or book_age_ns > int(book_policy_ms * NS_PER_MS):
            return CANDIDATE_SNAPSHOT_STALE
    return None


def _pass(
    reason_code: str,
    *,
    signal_symbol: str,
    current_ns: int,
    snapshot: Mapping[str, Any],
    monitor_evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return _evidence(
        data_healthy=True,
        reason_codes=(reason_code,),
        signal_symbol=signal_symbol,
        current_ns=current_ns,
        snapshot=snapshot,
        monitor_evidence=monitor_evidence,
        snapshot_status=SNAPSHOT_PASS,
    )


def _block(
    reason_code: str | tuple[str, ...],
    *,
    signal_symbol: str,
    current_ns: int,
    snapshot: Mapping[str, Any] | None,
    monitor_evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    codes = reason_code if isinstance(reason_code, tuple) else (reason_code,)
    return _evidence(
        data_healthy=False,
        reason_codes=codes,
        signal_symbol=signal_symbol,
        current_ns=current_ns,
        snapshot=snapshot,
        monitor_evidence=monitor_evidence,
        snapshot_status=SNAPSHOT_BLOCK,
    )


def _evidence(
    *,
    data_healthy: bool,
    reason_codes: tuple[str, ...],
    signal_symbol: str,
    current_ns: int,
    snapshot: Mapping[str, Any] | None,
    monitor_evidence: Mapping[str, Any] | None,
    snapshot_status: str,
) -> dict[str, Any]:
    clean_codes = tuple(dict.fromkeys(str(code) for code in reason_codes if str(code)))
    primary = clean_codes[0] if clean_codes else "DATA_HEALTHY"
    snap = dict(snapshot or {})
    evidence = {
        "symbol": signal_symbol,
        "data_healthy": data_healthy,
        "data_health_reason_code": primary,
        "snapshot_status": snapshot_status,
        "snapshot_reason_codes": clean_codes,
        "snapshot_authority": snap.get("snapshot_authority") or "candidate_market_truth_snapshot",
        "snapshot_id": snap.get("snapshot_id"),
        "book_ts_ns": snap.get("book_ts_ns"),
        "candle_id": snap.get("candle_id"),
        "candle_close_ts_ns": snap.get("candle_close_ts_ns"),
        "provider_id": snap.get("provider_id"),
        "receive_ts_ns": snap.get("receive_ts_ns"),
        "book_fresh": snap.get("book_fresh"),
        "candle_fresh": snap.get("candle_fresh"),
        "executable_market_truth": snap.get("executable_market_truth"),
        "source_type": snap.get("source_type"),
        "data_source_type": snap.get("source_type"),
        "current_ns": current_ns,
        "market_truth_snapshot": snap if snap else None,
    }
    if monitor_evidence:
        evidence["monitor_evidence"] = dict(monitor_evidence)
    return {key: value for key, value in evidence.items() if value is not None}


def _snapshot_reason_codes(snapshot: Mapping[str, Any]) -> tuple[str, ...]:
    codes = snapshot.get("snapshot_reason_codes")
    if isinstance(codes, tuple):
        return tuple(str(code) for code in codes if str(code))
    if isinstance(codes, list):
        return tuple(str(code) for code in codes if str(code))
    if isinstance(codes, str) and codes:
        return (codes,)
    return ()


def _snapshot_authority_ts(snapshot: Mapping[str, Any]) -> Optional[int]:
    candidates = (
        _int_or_none(snapshot.get("book_ts_ns")),
        _int_or_none(snapshot.get("candle_close_ts_ns")),
        _int_or_none(snapshot.get("candle_id")),
        _int_or_none(snapshot.get("receive_ts_ns")),
    )
    values = tuple(value for value in candidates if value is not None)
    return max(values) if values else None


def _source_type(market_truth: Mapping[str, Any], candle_truth: Mapping[str, Any]) -> str:
    return str(
        candle_truth.get("data_source_type")
        or candle_truth.get("source_type")
        or market_truth.get("data_source_type")
        or market_truth.get("source_type")
        or "unknown"
    ).lower()


def _snapshot_id(
    *,
    symbol: str,
    source_type: str,
    candle_id: Optional[int],
    candle_close_ts_ns: Optional[int],
    book_ts_ns: Optional[int],
    provider_id: Optional[str],
) -> str:
    raw = "|".join(
        (
            str(symbol),
            str(source_type),
            str(candle_id or ""),
            str(candle_close_ts_ns or ""),
            str(book_ts_ns or ""),
            str(provider_id or ""),
        )
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"mts_{digest}"


def _int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "MarketTruthSnapshot",
    "MARKET_TRUTH_SNAPSHOT_MISSING",
    "CANDIDATE_SNAPSHOT_STALE",
    "MARKET_TRUTH_CONFLICT",
    "SNAPSHOT_SYMBOL_MISMATCH",
    "SNAPSHOT_SOURCE_UNEXECUTABLE",
    "SNAPSHOT_TIMESTAMP_MISMATCH",
    "STALE_MONITOR_EVIDENCE_IGNORED",
    "build_market_truth_snapshot",
    "validate_market_snapshot_for_execution",
]
