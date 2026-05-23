from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.brain.data_validator import DataContinuityValidator
from app.commander import Commander
from app.core.market_snapshot import (
    CANDIDATE_SNAPSHOT_STALE,
    MARKET_TRUTH_CONFLICT,
    MARKET_TRUTH_SNAPSHOT_MISSING,
    SNAPSHOT_SOURCE_UNEXECUTABLE,
    SNAPSHOT_SYMBOL_MISMATCH,
    SNAPSHOT_TIMESTAMP_MISMATCH,
    STALE_MONITOR_EVIDENCE_IGNORED,
    build_market_truth_snapshot,
)
from app.execution.engine import ExecutionEngine
from app.models.signals import StrategySignal
from app.utils.time_utils import now_ns


NS_PER_SECOND = 1_000_000_000


def _ns_datetime(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc)


def _risk_guard():
    risk_guard = MagicMock()
    risk_guard.can_trade.return_value = True
    risk_guard.is_vol_fuse_triggered.return_value = False
    risk_guard.register_recalibrate_callback = MagicMock()
    risk_guard.register_emergency_callback = MagicMock()
    risk_guard.register_zombie_callback = MagicMock()
    risk_guard.register_lag_callback = MagicMock()
    risk_guard.register_vol_fuse_callback = MagicMock()
    risk_guard.record_fees = MagicMock()
    return risk_guard


def _masking_layer():
    masking_layer = MagicMock()
    masking_layer.mask_order.return_value = SimpleNamespace(masked_size=Decimal("0.10"))
    return masking_layer


def _engine(router, *, data_validator=None) -> ExecutionEngine:
    engine = ExecutionEngine(
        commander=Commander(),
        risk_guard=_risk_guard(),
        order_router=router,
        masking_layer=_masking_layer(),
        data_validator=data_validator,
        signal_ttl_ms=300_000.0,
    )
    engine._state.is_running = True
    engine._state.last_regime = "neutral"
    return engine


def _guardrail(symbol: str = "SOL/USD") -> dict:
    return {
        "verdict": "ALLOW",
        "route_permitted": True,
        "mutation_permitted": True,
        "reason_codes": ("PRE_TRADE_GUARDRAILS_ALLOW",),
        "symbol": symbol,
        "side": "buy",
        "order_type": "limit",
        "time_in_force": "GTC",
    }


def _snapshot_payload(
    *,
    symbol: str = "SOL/USD",
    current_ns: int,
    source_type: str = "runtime",
    candle_age_sec: int = 10,
    candle_policy_ms: float = 60_000.0,
    book_age_sec: int | None = 1,
    receive_age_sec: int | None = 0,
    executable: bool = True,
) -> tuple[dict, dict, dict]:
    candle_close_ts_ns = current_ns - candle_age_sec * NS_PER_SECOND
    candle_id = candle_close_ts_ns - 60 * NS_PER_SECOND
    latest_book_ts_ns = (
        current_ns - book_age_sec * NS_PER_SECOND
        if book_age_sec is not None
        else None
    )
    receive_ts_ns = (
        current_ns - receive_age_sec * NS_PER_SECOND
        if receive_age_sec is not None
        else None
    )
    executable_source = source_type == "runtime" and executable
    market_truth = {
        "symbol": symbol,
        "consumer_exchange_ts_ns": candle_id,
        "latest_book_ts_ns": latest_book_ts_ns,
        "latest_candle_ts_ns": candle_id,
        "data_source_type": source_type,
    }
    candle_truth = {
        "consumer_timestamp_ns": candle_id,
        "candle_id": candle_id,
        "candle_start_ts_ns": candle_id,
        "candle_close_ts_ns": candle_close_ts_ns,
        "candle_freshness_policy_ms": candle_policy_ms,
        "data_source_type": source_type,
        "provider_id": "coinbase_public",
        "receive_ts_ns": receive_ts_ns,
        "data_health_reason_code": "DATA_HEALTHY" if executable_source else "DATA_BACKFILL_OBSERVE_ONLY",
        "candle_freshness_reason_code": "CANDLE_RUNTIME_FRESH" if executable_source else "CANDLE_BATCH_BACKFILL_OBSERVE_ONLY",
        "executable_market_truth": executable_source,
    }
    snapshot = build_market_truth_snapshot(
        symbol=symbol,
        market_truth=market_truth,
        candle_truth=candle_truth,
        current_ns=current_ns,
    )
    market_truth["market_truth_snapshot"] = snapshot
    return market_truth, candle_truth, snapshot


def _signal(*, symbol: str = "SOL/USD", candle_id: int, metadata: dict) -> StrategySignal:
    return StrategySignal(
        strategy="sector_rotation",
        symbol=symbol,
        side="buy",
        confidence=0.90,
        quantity=0.10,
        price=150.0,
        exchange_ts_ns=candle_id,
        reason="canonical_market_snapshot_test",
        metadata={
            "expected_move": "0.02",
            "pre_trade_guardrail_verdict": _guardrail(symbol),
            **metadata,
        },
    )


def _canonical_metadata(market_truth: dict, snapshot: dict) -> dict:
    return {
        "execution_market_truth": market_truth,
        "market_truth_snapshot": snapshot,
        "candidate_market_snapshot": snapshot,
        "requires_canonical_market_snapshot": True,
        "snapshot_id": snapshot["snapshot_id"],
        "candle_id": snapshot["candle_id"],
    }


def test_fresh_canonical_snapshot_reaches_execution_engine_with_stale_monitor_ignored():
    router = MagicMock()
    validator = DataContinuityValidator(max_stale_age_sec=5.0)
    current_ns = now_ns()
    validator.record_data("SOL/USD", _ns_datetime(current_ns - 30 * NS_PER_SECOND))
    market_truth, _, snapshot = _snapshot_payload(current_ns=current_ns)
    signal = _signal(
        candle_id=snapshot["candle_id"],
        metadata=_canonical_metadata(market_truth, snapshot),
    )
    engine = _engine(router, data_validator=validator)

    evidence = engine._data_health_block_evidence(signal, current_ns=current_ns)
    admitted = engine.submit_signal(signal, Decimal("150.00"), is_attack=False)

    assert evidence["data_healthy"] is True
    assert evidence["data_health_reason_code"] == STALE_MONITOR_EVIDENCE_IGNORED
    assert admitted is True
    assert engine.get_last_admission_block_result() is None
    assert engine.get_status()["execution_queue_size"] == 1
    router.submit_order.assert_not_called()


def test_stale_candidate_snapshot_blocks_before_router_submit():
    router = MagicMock()
    validator = DataContinuityValidator(max_stale_age_sec=5.0)
    current_ns = now_ns()
    validator.record_data("SOL/USD", _ns_datetime(current_ns))
    market_truth, _, snapshot = _snapshot_payload(
        current_ns=current_ns,
        candle_age_sec=90,
        book_age_sec=None,
    )
    signal = _signal(
        candle_id=snapshot["candle_id"],
        metadata=_canonical_metadata(market_truth, snapshot),
    )
    engine = _engine(router, data_validator=validator)

    admitted = engine.submit_signal(signal, Decimal("150.00"), is_attack=False)
    block = engine.get_last_admission_block_result()

    assert admitted is False
    assert block.reason_code == "DATA_UNHEALTHY"
    assert block.block_evidence["data_health_reason_code"] == CANDIDATE_SNAPSHOT_STALE
    assert CANDIDATE_SNAPSHOT_STALE in block.block_evidence["snapshot_reason_codes"]
    router.submit_order.assert_not_called()


def test_newer_contradictory_same_symbol_monitor_truth_blocks_conflict():
    router = MagicMock()
    validator = DataContinuityValidator(max_stale_age_sec=5.0)
    current_ns = now_ns()
    market_truth, _, snapshot = _snapshot_payload(
        current_ns=current_ns,
        candle_age_sec=10,
        book_age_sec=None,
        receive_age_sec=None,
    )
    validator.record_data("SOL/USD", _ns_datetime(current_ns - 6 * NS_PER_SECOND))
    signal = _signal(
        candle_id=snapshot["candle_id"],
        metadata=_canonical_metadata(market_truth, snapshot),
    )
    engine = _engine(router, data_validator=validator)

    admitted = engine.submit_signal(signal, Decimal("150.00"), is_attack=False)
    block = engine.get_last_admission_block_result()

    assert admitted is False
    assert block.reason_code == "DATA_UNHEALTHY"
    assert block.block_evidence["data_health_reason_code"] == MARKET_TRUTH_CONFLICT
    assert MARKET_TRUTH_CONFLICT in block.block_evidence["snapshot_reason_codes"]
    router.submit_order.assert_not_called()


def test_snapshot_missing_fails_closed_on_canonical_path():
    router = MagicMock()
    current_ns = now_ns()
    signal = _signal(
        candle_id=current_ns,
        metadata={"requires_canonical_market_snapshot": True},
    )
    engine = _engine(router)

    admitted = engine.submit_signal(signal, Decimal("150.00"), is_attack=False)
    block = engine.get_last_admission_block_result()

    assert admitted is False
    assert block.reason_code == "DATA_UNHEALTHY"
    assert block.block_evidence["data_health_reason_code"] == MARKET_TRUTH_SNAPSHOT_MISSING
    router.submit_order.assert_not_called()


def test_symbol_and_timestamp_mismatches_block_canonical_snapshot():
    router = MagicMock()
    current_ns = now_ns()
    market_truth, _, snapshot = _snapshot_payload(symbol="SOL/USD", current_ns=current_ns)
    engine = _engine(router)

    symbol_mismatch = _signal(
        symbol="ETH/USD",
        candle_id=snapshot["candle_id"],
        metadata=_canonical_metadata(market_truth, snapshot),
    )
    admitted_symbol = engine.submit_signal(symbol_mismatch, Decimal("150.00"), is_attack=False)
    symbol_block = engine.get_last_admission_block_result()

    timestamp_mismatch = _signal(
        candle_id=snapshot["candle_id"] + 1,
        metadata=_canonical_metadata(market_truth, snapshot),
    )
    admitted_timestamp = engine.submit_signal(timestamp_mismatch, Decimal("150.00"), is_attack=False)
    timestamp_block = engine.get_last_admission_block_result()

    assert admitted_symbol is False
    assert symbol_block.block_evidence["data_health_reason_code"] == SNAPSHOT_SYMBOL_MISMATCH
    assert admitted_timestamp is False
    assert timestamp_block.block_evidence["data_health_reason_code"] == SNAPSHOT_TIMESTAMP_MISMATCH
    router.submit_order.assert_not_called()


@pytest.mark.parametrize("source_type", ("backfill", "replay", "synthetic"))
def test_backfill_replay_synthetic_snapshots_block_executable_admission(source_type: str):
    router = MagicMock()
    current_ns = now_ns()
    market_truth, _, snapshot = _snapshot_payload(
        current_ns=current_ns,
        source_type=source_type,
        executable=False,
    )
    signal = _signal(
        candle_id=snapshot["candle_id"],
        metadata=_canonical_metadata(market_truth, snapshot),
    )
    engine = _engine(router)

    admitted = engine.submit_signal(signal, Decimal("150.00"), is_attack=False)
    block = engine.get_last_admission_block_result()

    assert admitted is False
    assert block.reason_code == "DATA_UNHEALTHY"
    assert block.block_evidence["data_health_reason_code"] == SNAPSHOT_SOURCE_UNEXECUTABLE
    assert SNAPSHOT_SOURCE_UNEXECUTABLE in block.block_evidence["snapshot_reason_codes"]
    router.submit_order.assert_not_called()
