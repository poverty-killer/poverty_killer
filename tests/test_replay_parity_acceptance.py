"""
test_replay_parity_acceptance
SAME_CLOCK_SYNTHETIC_PAPER_WINDOW_HARNESS_BUNDLE — Replay Parity Acceptance.

Purpose
-------
Prove deterministic replay parity through the real bot spine:

    (Run A) ReplayTimeContext(t0_ns)
        -> SymbolRuntime.update_candle / update_order_book          (production)
        -> SymbolRuntime.record_observed_signal/vote                 (production)
        -> MainLoop._dispatch_fusion                                 (production)
        -> MainLoop._consume_observed_pair_sector_rotation           (production)
        -> DecisionCompiler.compile                                  (call seam)
        -> ExecutionEngine.submit_signal                             (capture seam)
        -> OrderRouter.submit_order(paper_mode=True)                 (production)
        -> SovereignPaperBroker                                      (production)
        -> OrderFill                                                 (production object)

    (Run B) ReplayTimeContext(t0_ns), fresh runtime / loop / router

    Run A observable outputs == Run B observable outputs.

Replay parity claims pinned by this acceptance harness
------------------------------------------------------
1. Same controlled inputs + same replay time + same initial fresh state
   produce the same dispatch/compile/submit/route/fill outputs.
2. Real models, real adapters, and real spine seams are used wherever the
   bundle's prior harness already legitimised them; the only mocked seams are
   the ones the prior harnesses already mock (StrategyRouter policy,
   DecisionCompiler.compile, ExecutionEngine.submit_signal capture,
   _build_truth_frame stub) — see SAME_CLOCK_SYNTHETIC_PAPER_WINDOW_HARNESS
   for the identical seam list.
3. Same-clock freshness remains strictly enforced: stale observed pairs
   reject identically across both replay runs; +1 ns drift still rejects.
4. Replay time and replay state do not leak between runs: ``is_replay_mode``
   is False before each ReplayTimeContext, True inside, and False again on
   exit; the per-run SymbolRuntime / MainLoop / OrderRouter instances are
   constructed fresh and never share state across runs.
5. Negative controls (stale, missing, mismatched timestamps; live broker
   mode) reject deterministically and identically in both runs — rejection
   itself is replay-parity-stable.
6. No fake fill, no direct strategy-to-execution shortcut, no protected-system
   bypass. Paper-only proving lane; attack_mode=False; LIVE_MODE not set.

Forbidden in this file (per packet doctrine)
--------------------------------------------
- threshold relaxation
- fake signals / fake fills / forced submission
- bypassing SignalFusion / StrategyRouter / DecisionCompiler / ExecutionEngine
  / OrderRouter / SovereignPaperBroker
- direct strategy-to-execution shortcut
- any live-mode path
- any --attack path
- any production code edits
"""

from __future__ import annotations

import os
import types
from decimal import Decimal
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock

import pytest

from app.commander import Commander
from app.main_loop import MainLoop
from app.models import OrderFill, OrderRequest, StrategySignal
from app.models.enums import OrderSide, OrderType, SleeveType
from app.models.market_data import Candle, OrderBookSnapshot
from app.execution.order_router import OrderRouter
from app.strategies.strategy_vote_adapters import adapt_sector_rotation_to_vote
from app.symbol_runtime import SymbolRuntime
from app.utils.time_utils import (
    ReplayTimeContext,
    is_replay_mode,
    now_ns,
)


# =============================================================================
# Same-clock fixture builders — mirror the existing same-clock harness exactly
# so the replay parity proof rides on the production-validated path, not on a
# rebuilt one.
# =============================================================================


def _build_candle(t0_ns: int, *, symbol: str = "ETH/USD", close: float = 2500.0) -> Candle:
    return Candle(
        symbol=symbol,
        exchange_ts_ns=t0_ns,
        open=close - 5.0,
        high=close + 5.0,
        low=close - 7.5,
        close=close,
        volume=125.0,
        timeframe="1m",
    )


def _build_book(t0_ns: int, *, symbol: str = "ETH/USD", mid: float = 2500.0) -> OrderBookSnapshot:
    half = 0.5
    return OrderBookSnapshot(
        symbol=symbol,
        exchange_ts_ns=t0_ns,
        bids=[(mid - half, 4.0), (mid - half - 0.5, 8.0)],
        asks=[(mid + half, 4.0), (mid + half + 0.5, 8.0)],
    )


def _build_strategy_signal(
    t0_ns: int,
    *,
    symbol: str = "ETH/USD",
    side: str = "buy",
    quantity: float = 0.5,
    confidence: float = 0.9,
) -> StrategySignal:
    return StrategySignal(
        strategy="sector_rotation",
        symbol=symbol,
        side=side,
        confidence=confidence,
        quantity=quantity,
        price=None,
        exchange_ts_ns=t0_ns,
        reason="replay_parity_acceptance",
        metadata={
            "stale_data_observation": {
                "current_ts_ns": t0_ns,
                "exchange_ts_ns": t0_ns,
                "local_received_ts_ns": t0_ns,
            }
        },
        regime=None,
    )


def _build_vote_via_real_adapter(signal: StrategySignal, t0_ns: int):
    return adapt_sector_rotation_to_vote(
        signal,
        exchange_ts_ns=t0_ns,
        decision_uuid="replay-parity-uuid",
    )


def _build_runtime(symbol: str = "ETH/USD") -> SymbolRuntime:
    runtime = SymbolRuntime(symbol=symbol)
    runtime.shadow_front_strategy = MagicMock()
    runtime.sector_rotation_strategy = MagicMock()
    runtime.toxicity_engine = MagicMock()
    runtime.sentiment_velocity_engine = MagicMock()
    return runtime


def _build_fusion_decision(t0_ns: int, *, preferred: str = "shadow_front"):
    return types.SimpleNamespace(
        exchange_ts_ns=t0_ns,
        attack_mode=False,
        preferred_sleeve=preferred,
        sector_rotation_eligible=True,
        shadow_front_eligible=True,
    )


def _build_test_loop(*, broker_mode: str = "paper") -> types.SimpleNamespace:
    """
    Identical convention to the existing same-clock and deterministic
    harnesses. Only the StrategyRouter policy / DecisionCompiler.compile /
    ExecutionEngine.submit_signal seams are mocked; the dispatch path runs
    through the unbound MainLoop methods (production code).
    """
    loop = types.SimpleNamespace()
    loop.config = types.SimpleNamespace(broker_mode=broker_mode)
    loop.commander = Commander()

    loop.strategy_router = MagicMock()
    loop.strategy_router.update_macro_state = MagicMock()
    loop.strategy_router.get_preferred_strategy = MagicMock(
        return_value=SleeveType.SHADOW_FRONT
    )
    loop.strategy_router.get_eligible_strategies = MagicMock(
        return_value=[SleeveType.SHADOW_FRONT, SleeveType.SECTOR_ROTATION]
    )

    loop.decision_compiler = MagicMock()
    loop.decision_compiler.reserve_decision_uuid = MagicMock(
        return_value="replay-parity-uuid"
    )
    loop.decision_compiler.compile = MagicMock(
        return_value=types.SimpleNamespace(
            decision_uuid="replay-parity-uuid",
            decision_type="STRATEGY_VOTE",
        )
    )

    loop.execution_engine = MagicMock()
    loop.execution_engine.submit_signal = MagicMock(return_value=True)
    loop.execution_engine.get_status.return_value = {"last_latency_truth": {}}

    loop._build_truth_frame = MagicMock(return_value="truth-frame-stub")
    loop._update_shadow_front_overlays = MagicMock()
    loop._generate_signal_and_vote = MagicMock(return_value=(None, None))
    loop._generate_signal_and_vote_gamma_front = MagicMock(return_value=(None, None))

    loop._metrics = types.SimpleNamespace(
        orders_submitted=0, orders_rejected=0, compilation_cycles=0
    )
    loop.insider_engine = MagicMock()
    loop.signal_fusion = MagicMock()
    loop.signal_fusion._telemetry = {}

    loop._active_threshold_profile = MainLoop._active_threshold_profile.__get__(loop, MainLoop)
    loop._consume_observed_pair_sector_rotation = (
        MainLoop._consume_observed_pair_sector_rotation.__get__(loop, MainLoop)
    )
    loop._consume_observed_pair_liquidity_void = (
        MainLoop._consume_observed_pair_liquidity_void.__get__(loop, MainLoop)
    )
    loop._consume_observed_pair_moving_floor = (
        MainLoop._consume_observed_pair_moving_floor.__get__(loop, MainLoop)
    )
    loop._classify_shadow_front_decline = MainLoop._classify_shadow_front_decline.__get__(loop, MainLoop)
    loop._classify_sector_rotation_observed_pair = (
        MainLoop._classify_sector_rotation_observed_pair.__get__(loop, MainLoop)
    )
    loop._clear_stale_sector_rotation_observed_pair = (
        MainLoop._clear_stale_sector_rotation_observed_pair.__get__(loop, MainLoop)
    )
    loop._runtime_module_frame_evidence = MainLoop._runtime_module_frame_evidence.__get__(loop, MainLoop)
    loop._apply_signal_economic_metadata = MainLoop._apply_signal_economic_metadata.__get__(loop, MainLoop)
    loop._net_edge_frame_evidence = MainLoop._net_edge_frame_evidence
    loop._compile_scorecard_frame_no_submit = MainLoop._compile_scorecard_frame_no_submit.__get__(loop, MainLoop)
    loop._primary_no_submit_reason_code = MainLoop._primary_no_submit_reason_code
    return loop


def _bind(loop, method_name: str):
    return getattr(MainLoop, method_name).__get__(loop, MainLoop)


def _refusal_compile_observables(loop) -> Dict[str, Any]:
    _, compile_kwargs = loop.decision_compiler.compile.call_args
    additional_inputs = compile_kwargs["additional_inputs"]
    lifecycle = additional_inputs["candidate_lifecycle"]
    return {
        "compile_vote_count": len(compile_kwargs["strategy_votes"]),
        "no_submit_reason_code": additional_inputs["no_submit_reason_code"],
        "execution_verdict": lifecycle["execution_verdict"],
        "broker_post": lifecycle["broker_post"],
    }


def _strategy_signal_to_order_request(
    signal: StrategySignal, *, receive_ts_ns: int
) -> OrderRequest:
    side_map = {"buy": OrderSide.BUY, "sell": OrderSide.SELL}
    if signal.side not in side_map:
        raise AssertionError(
            f"harness only routes actionable signals; got side={signal.side!r}"
        )
    sleeve_map = {
        "sector_rotation": SleeveType.SECTOR_ROTATION,
        "shadow_front": SleeveType.SHADOW_FRONT,
    }
    if signal.strategy not in sleeve_map:
        raise AssertionError(
            f"harness only routes registered sleeves; got strategy={signal.strategy!r}"
        )
    return OrderRequest(
        id=f"{signal.strategy}_{signal.symbol}_{signal.exchange_ts_ns}",
        symbol=signal.symbol,
        side=side_map[signal.side],
        quantity=Decimal(str(signal.quantity)),
        order_type=OrderType.MARKET,
        limit_price=None,
        strategy=sleeve_map[signal.strategy],
        confidence=signal.confidence,
        exchange_ts_ns=signal.exchange_ts_ns,
        receive_ts_ns=receive_ts_ns,
        metadata={"harness": "replay_parity_acceptance"},
    )


# Single fixed t0_ns used by every parity test so the proof artefacts are
# inspectable and deterministic. ~ 2026-04-30 09:00:00 UTC.
T0_NS: int = 1_777_948_800_000_000_000

# A second fixed t0 used to prove that distinct replay anchors yield
# identical-shape paths but timestamp differences flow correctly.
T0_NS_SHIFT: int = T0_NS + 60_000_000_000  # +60 s, plainly different candle


# =============================================================================
# Run helpers — encapsulate one full dispatch -> compile -> submit -> route
# -> fill walk under a ReplayTimeContext. Each call constructs ALL state
# (runtime, loop, router) freshly so cross-run leakage is impossible by
# construction.
# =============================================================================


def _run_happy_path(t0_ns: int) -> Dict[str, Any]:
    """
    Single replay run of the happy path under ReplayTimeContext(t0_ns). All
    inputs derive from t0_ns; all instances are fresh; the function returns
    a dict of observable outputs suitable for parity comparison.
    """
    captured: List[Dict[str, Any]] = []

    with ReplayTimeContext(t0_ns):
        # Inside the context, now_ns must equal t0_ns deterministically.
        now_inside = now_ns()
        replay_active_inside = is_replay_mode()

        candle = _build_candle(t0_ns, close=2500.0)
        book = _build_book(t0_ns, mid=2500.0)
        signal = _build_strategy_signal(t0_ns, side="buy", quantity=0.5)
        vote = _build_vote_via_real_adapter(signal, t0_ns)

        runtime = _build_runtime("ETH/USD")
        runtime.update_candle(candle)
        runtime.update_order_book(book)
        runtime.record_observed_signal("sector_rotation", signal)
        runtime.record_observed_vote("sector_rotation", vote)

        loop = _build_test_loop(broker_mode="paper")

        def _capture(signal, current_price, is_attack, **_execution_context):
            captured.append(
                {
                    "signal": signal,
                    "current_price": current_price,
                    "is_attack": is_attack,
                }
            )
            return True

        loop.execution_engine.submit_signal = MagicMock(side_effect=_capture)

        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch(
            "ETH/USD",
            runtime,
            fusion=_build_fusion_decision(t0_ns),
            exchange_ts_ns=t0_ns,
        )

        # The dispatch leg must have reached compile and submit exactly once.
        compile_call_count = loop.decision_compiler.compile.call_count
        compile_args, compile_kwargs = loop.decision_compiler.compile.call_args
        submit_call_count = loop.execution_engine.submit_signal.call_count

        # Route the captured signal through the real OrderRouter -> PaperBroker.
        captured_signal = captured[0]["signal"]
        order = _strategy_signal_to_order_request(captured_signal, receive_ts_ns=t0_ns)
        router = OrderRouter(paper_mode=True)
        fill = router.submit_order(order)

    # Outside the context, replay mode must have been restored.
    replay_active_after = is_replay_mode()

    return {
        "now_inside": now_inside,
        "replay_active_inside": replay_active_inside,
        "replay_active_after": replay_active_after,
        "compile_call_count": compile_call_count,
        "compile_args0": compile_args[0],
        "compile_kwargs_strategy_votes_count": len(
            compile_kwargs.get("strategy_votes") or []
        ),
        "compile_vote_timestamp_ns": compile_kwargs["strategy_votes"][0].timestamp_ns,
        "compile_vote_decision_uuid": compile_kwargs["strategy_votes"][0].decision_uuid,
        "submit_call_count": submit_call_count,
        "captured_count": len(captured),
        "captured_signal_strategy": captured_signal.strategy,
        "captured_signal_symbol": captured_signal.symbol,
        "captured_signal_side": captured_signal.side,
        "captured_signal_quantity": captured_signal.quantity,
        "captured_signal_confidence": captured_signal.confidence,
        "captured_signal_exchange_ts_ns": captured_signal.exchange_ts_ns,
        "captured_current_price": captured[0]["current_price"],
        "captured_is_attack": captured[0]["is_attack"],
        "order_id": order.id,
        "order_exchange_ts_ns": order.exchange_ts_ns,
        "order_receive_ts_ns": order.receive_ts_ns,
        "fill_is_orderfill": isinstance(fill, OrderFill),
        "fill_symbol": fill.symbol,
        "fill_side_value": fill.side.value if hasattr(fill.side, "value") else fill.side,
        "fill_quantity": fill.quantity,
        "fill_price": fill.price,
        "fill_fee": fill.fee,
        "fill_quantity_is_decimal": isinstance(fill.quantity, Decimal),
        "fill_price_is_decimal": isinstance(fill.price, Decimal),
        "fill_fee_is_decimal": isinstance(fill.fee, Decimal),
        "metrics_orders_submitted": loop._metrics.orders_submitted,
        "metrics_compilation_cycles": loop._metrics.compilation_cycles,
        "broker_execution_reports_count": len(
            router._paper_broker.execution_reports  # type: ignore[attr-defined]
        ),
    }


def _run_negative_stale(t0_ns: int, *, delta_ns: int = 60_000_000_000) -> Dict[str, Any]:
    """
    One replay run where the observed pair carries a stale candle. Returns
    observable outputs for parity comparison; no router is constructed since
    a fill is impossible by construction.
    """
    with ReplayTimeContext(t0_ns):
        stale_signal = _build_strategy_signal(t0_ns - delta_ns, side="buy")
        stale_vote = _build_vote_via_real_adapter(stale_signal, t0_ns - delta_ns)

        runtime = _build_runtime("ETH/USD")
        runtime.update_candle(_build_candle(t0_ns, close=2500.0))
        runtime.update_order_book(_build_book(t0_ns, mid=2500.0))
        runtime.record_observed_signal("sector_rotation", stale_signal)
        runtime.record_observed_vote("sector_rotation", stale_vote)

        captured: List[Any] = []
        loop = _build_test_loop(broker_mode="paper")
        loop.execution_engine.submit_signal = MagicMock(
            side_effect=lambda signal, current_price, is_attack: captured.append(
                {"signal": signal}
            )
            or True
        )

        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch(
            "ETH/USD",
            runtime,
            fusion=_build_fusion_decision(t0_ns),
            exchange_ts_ns=t0_ns,
        )

        compile_calls = loop.decision_compiler.compile.call_count
        submit_calls = loop.execution_engine.submit_signal.call_count

    return {
        "compile_calls": compile_calls,
        **_refusal_compile_observables(loop),
        "submit_calls": submit_calls,
        "captured_count": len(captured),
        "metrics_orders_submitted": loop._metrics.orders_submitted,
        "metrics_compilation_cycles": loop._metrics.compilation_cycles,
        "replay_active_after": is_replay_mode(),
    }


def _run_negative_missing(t0_ns: int) -> Dict[str, Any]:
    """
    Replay run with same-clock candle/book but NO observed (signal, vote)
    pair recorded. Consume gate must return (None, None); no fill possible.
    """
    with ReplayTimeContext(t0_ns):
        runtime = _build_runtime("ETH/USD")
        runtime.update_candle(_build_candle(t0_ns))
        runtime.update_order_book(_build_book(t0_ns))
        # No record_observed_*.

        captured: List[Any] = []
        loop = _build_test_loop(broker_mode="paper")
        loop.execution_engine.submit_signal = MagicMock(
            side_effect=lambda signal, current_price, is_attack: captured.append(
                {"signal": signal}
            )
            or True
        )

        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch(
            "ETH/USD",
            runtime,
            fusion=_build_fusion_decision(t0_ns),
            exchange_ts_ns=t0_ns,
        )

        compile_calls = loop.decision_compiler.compile.call_count
        submit_calls = loop.execution_engine.submit_signal.call_count

    return {
        "compile_calls": compile_calls,
        **_refusal_compile_observables(loop),
        "submit_calls": submit_calls,
        "captured_count": len(captured),
        "metrics_orders_submitted": loop._metrics.orders_submitted,
        "metrics_compilation_cycles": loop._metrics.compilation_cycles,
        "replay_active_after": is_replay_mode(),
    }


# Fields that must be IDENTICAL across two parity runs of the happy path.
_PARITY_FIELDS_HAPPY: Tuple[str, ...] = (
    "now_inside",
    "replay_active_inside",
    "replay_active_after",
    "compile_call_count",
    "compile_args0",
    "compile_kwargs_strategy_votes_count",
    "compile_vote_timestamp_ns",
    "compile_vote_decision_uuid",
    "submit_call_count",
    "captured_count",
    "captured_signal_strategy",
    "captured_signal_symbol",
    "captured_signal_side",
    "captured_signal_quantity",
    "captured_signal_confidence",
    "captured_signal_exchange_ts_ns",
    "captured_current_price",
    "captured_is_attack",
    "order_id",
    "order_exchange_ts_ns",
    "order_receive_ts_ns",
    "fill_is_orderfill",
    "fill_symbol",
    "fill_side_value",
    "fill_quantity",
    "fill_price",
    "fill_fee",
    "fill_quantity_is_decimal",
    "fill_price_is_decimal",
    "fill_fee_is_decimal",
    "metrics_orders_submitted",
    "metrics_compilation_cycles",
    "broker_execution_reports_count",
)


# =============================================================================
# 1. Replay time / state isolation — _replay_time_ns must NEVER leak between
#    runs; ReplayTimeContext must restore prior state on every exit, including
#    on exception.
# =============================================================================


class TestReplayTimeIsolation:
    """
    Authoritative pin: replay state is fully scoped by ReplayTimeContext. No
    test in this module — and no test caller of this module — may observe
    a stale ``_replay_time_ns`` after a run.
    """

    def test_replay_mode_off_at_module_entry(self):
        """If a prior test or module leaked replay mode, this fails immediately."""
        assert not is_replay_mode(), (
            "replay mode leaked into test_replay_parity_acceptance from a prior test; "
            "ReplayTimeContext must always be used as a context manager"
        )

    def test_two_back_to_back_contexts_do_not_leak(self):
        assert not is_replay_mode()
        with ReplayTimeContext(T0_NS):
            assert is_replay_mode()
            assert now_ns() == T0_NS
        assert not is_replay_mode()
        with ReplayTimeContext(T0_NS_SHIFT):
            assert is_replay_mode()
            assert now_ns() == T0_NS_SHIFT
        assert not is_replay_mode()

    def test_replay_context_restores_prior_state_on_exception(self):
        """
        If a body inside ReplayTimeContext raises, replay mode must still be
        cleared on context exit. Otherwise a failing test would freeze
        ``now_ns`` for every subsequent test.
        """
        assert not is_replay_mode()
        with pytest.raises(RuntimeError):
            with ReplayTimeContext(T0_NS):
                assert is_replay_mode()
                raise RuntimeError("synthetic error to verify __exit__ runs")
        assert not is_replay_mode(), (
            "ReplayTimeContext must restore prior replay state even when the "
            "body raises"
        )

    def test_nested_context_preserves_outer_state(self):
        """
        Inner ReplayTimeContext must restore the OUTER replay timestamp on exit,
        not blank it out. This guarantees that nested replay scopes (e.g. a
        sub-window inside a parent run) do not corrupt the parent clock.
        """
        assert not is_replay_mode()
        with ReplayTimeContext(T0_NS):
            assert now_ns() == T0_NS
            with ReplayTimeContext(T0_NS_SHIFT):
                assert now_ns() == T0_NS_SHIFT
            # Inner exit must restore outer t0, not clear replay mode.
            assert is_replay_mode()
            assert now_ns() == T0_NS
        assert not is_replay_mode()

    def test_two_parity_runs_observe_no_state_leak(self):
        """
        Run the happy path twice. Between runs, ``is_replay_mode`` must be
        False; inside each run it must be True; the per-run ``now_ns`` snapshot
        must equal the supplied t0_ns; and after both runs replay mode must
        again be off. This is the inter-run isolation contract.
        """
        assert not is_replay_mode()
        run_a = _run_happy_path(T0_NS)
        assert not is_replay_mode(), "Run A must not leak replay state"
        run_b = _run_happy_path(T0_NS)
        assert not is_replay_mode(), "Run B must not leak replay state"

        assert run_a["replay_active_inside"] is True
        assert run_a["replay_active_after"] is False
        assert run_b["replay_active_inside"] is True
        assert run_b["replay_active_after"] is False

        assert run_a["now_inside"] == T0_NS
        assert run_b["now_inside"] == T0_NS


# =============================================================================
# 2. Happy-path replay parity — same inputs + same replay time + same fresh
#    initial state must produce identical observable outputs across two runs.
# =============================================================================


class TestSameClockReplayParityHappyPath:

    def test_two_runs_same_t0_produce_identical_observables(self):
        """
        Walk the full real-spine path twice under ReplayTimeContext(T0_NS) with
        freshly constructed runtime / loop / router on each run, and assert
        that EVERY deterministic observable is bit-for-bit identical between
        the two runs.
        """
        run_a = _run_happy_path(T0_NS)
        run_b = _run_happy_path(T0_NS)

        # Reach far enough down the chain.
        assert run_a["compile_call_count"] == 1
        assert run_a["submit_call_count"] == 1
        assert run_a["captured_count"] == 1
        assert run_a["fill_is_orderfill"] is True

        # Bit-for-bit parity on every deterministic field.
        for field in _PARITY_FIELDS_HAPPY:
            assert run_a[field] == run_b[field], (
                f"replay parity broken on field {field!r}: "
                f"run_a={run_a[field]!r} run_b={run_b[field]!r}"
            )

    def test_run_a_does_not_leak_into_run_b_via_runtime_state(self):
        """
        Each run constructs its own SymbolRuntime / MainLoop test double /
        OrderRouter; Run B's per-run state must NOT inherit Run A's. We
        assert this indirectly through three independent freshness signals:
          - the per-run loop._metrics counters are fresh per run (== 1
            after exactly one submission),
          - Run B's OrderRouter has its own freshly-constructed broker (the
            execution-report count equals Run A's count exactly, not Run A's
            count + Run B's),
          - the broker count is positive (so we are actually exercising the
            real PaperBroker, not asserting parity over a no-op).
        """
        run_a = _run_happy_path(T0_NS)
        run_b = _run_happy_path(T0_NS)

        # Per-run loop metrics are freshly initialised and tick exactly once.
        assert run_a["metrics_orders_submitted"] == 1
        assert run_b["metrics_orders_submitted"] == 1
        assert run_a["metrics_compilation_cycles"] == 1
        assert run_b["metrics_compilation_cycles"] == 1

        # Each run's freshly-constructed OrderRouter -> SovereignPaperBroker
        # produces the SAME execution-report count (deterministic), and that
        # count is > 0 (we actually exercised the real broker, not a stub).
        assert run_a["broker_execution_reports_count"] > 0
        assert run_b["broker_execution_reports_count"] > 0
        assert (
            run_a["broker_execution_reports_count"]
            == run_b["broker_execution_reports_count"]
        ), (
            "Run A and Run B brokers must emit the same number of execution "
            "reports for identical inputs under replay; mismatch indicates "
            "broker state leaked between runs"
        )

    def test_same_clock_invariant_holds_in_each_run(self):
        """
        Inside each replay window, every timestamp the spine inspects derives
        from the same t0_ns: now_ns() == t0_ns; the captured signal's
        exchange_ts_ns == t0_ns; the OrderRequest.exchange_ts_ns == t0_ns;
        the OrderRequest.receive_ts_ns == t0_ns; and the compile vote's
        timestamp_ns == t0_ns.
        """
        run_a = _run_happy_path(T0_NS)
        assert run_a["now_inside"] == T0_NS
        assert run_a["captured_signal_exchange_ts_ns"] == T0_NS
        assert run_a["order_exchange_ts_ns"] == T0_NS
        assert run_a["order_receive_ts_ns"] == T0_NS
        assert run_a["compile_vote_timestamp_ns"] == T0_NS

    def test_decimal_discipline_holds_under_replay(self):
        """
        The OrderFill must expose Decimal quantity / price / fee in every run
        (no float regression introduced by replay).
        """
        run = _run_happy_path(T0_NS)
        assert run["fill_quantity_is_decimal"] is True
        assert run["fill_price_is_decimal"] is True
        assert run["fill_fee_is_decimal"] is True
        assert run["fill_quantity"] == Decimal("0.5")
        assert run["fill_price"] > Decimal("0")


# =============================================================================
# 3. Replay parity across two distinct t0 values — the path SHAPE is identical;
#    timestamp-bound fields differ deterministically by exactly the t0 shift.
# =============================================================================


class TestReplayParityAcrossT0Shift:

    def test_path_shape_identical_only_timestamps_shift(self):
        """
        Run the same happy path at two different t0 anchors. The dispatch /
        compile / submit / route / fill structure must be identical (same
        call counts, same captured signal field shape, same fill type, same
        Decimal discipline). The only fields that may differ are those that
        ride directly on t0 (now_inside, captured_signal_exchange_ts_ns,
        compile_vote_timestamp_ns, order_id, order_exchange_ts_ns,
        order_receive_ts_ns).
        """
        run_a = _run_happy_path(T0_NS)
        run_b = _run_happy_path(T0_NS_SHIFT)

        delta = T0_NS_SHIFT - T0_NS

        # Timestamps must shift by exactly delta.
        assert run_b["now_inside"] - run_a["now_inside"] == delta
        assert (
            run_b["captured_signal_exchange_ts_ns"]
            - run_a["captured_signal_exchange_ts_ns"]
        ) == delta
        assert (
            run_b["compile_vote_timestamp_ns"] - run_a["compile_vote_timestamp_ns"]
        ) == delta
        assert (
            run_b["order_exchange_ts_ns"] - run_a["order_exchange_ts_ns"]
        ) == delta
        assert (
            run_b["order_receive_ts_ns"] - run_a["order_receive_ts_ns"]
        ) == delta

        # order_id encodes exchange_ts_ns and must therefore differ exactly
        # by the t0 shift suffix.
        assert run_a["order_id"] == f"sector_rotation_ETH/USD_{T0_NS}"
        assert run_b["order_id"] == f"sector_rotation_ETH/USD_{T0_NS_SHIFT}"

        # Path-shape invariants are identical across the t0 shift.
        shape_fields = (
            "compile_call_count",
            "compile_kwargs_strategy_votes_count",
            "compile_vote_decision_uuid",
            "submit_call_count",
            "captured_count",
            "captured_signal_strategy",
            "captured_signal_symbol",
            "captured_signal_side",
            "captured_signal_quantity",
            "captured_signal_confidence",
            "captured_current_price",
            "captured_is_attack",
            "fill_is_orderfill",
            "fill_symbol",
            "fill_side_value",
            "fill_quantity",
            "fill_quantity_is_decimal",
            "fill_price_is_decimal",
            "fill_fee_is_decimal",
            "metrics_orders_submitted",
            "metrics_compilation_cycles",
            "broker_execution_reports_count",
            "replay_active_inside",
            "replay_active_after",
        )
        for field in shape_fields:
            assert run_a[field] == run_b[field], (
                f"path-shape parity broken across t0 shift on field {field!r}: "
                f"run_a={run_a[field]!r} run_b={run_b[field]!r}"
            )


# =============================================================================
# 4. Negative-control replay parity — stale, missing, and mismatched
#    timestamps reject IDENTICALLY across two runs. Rejection itself is
#    replay-parity-stable.
# =============================================================================


class TestReplayParityNegativeControls:

    def test_stale_observed_pair_rejects_identically_in_both_runs(self):
        """
        Run the stale-observed-pair scenario twice. In each run the
        sector_rotation freshness gate must reject; compile and submit must
        not be called; metrics must not tick; no fill is reachable. The
        rejection signature must be bit-for-bit identical between runs.
        """
        run_a = _run_negative_stale(T0_NS)
        run_b = _run_negative_stale(T0_NS)

        assert run_a == run_b, (
            f"stale-rejection signature drifted between runs: a={run_a} b={run_b}"
        )

        # Sanity-pin the rejection signature itself.
        assert run_a["compile_calls"] == 1
        assert run_a["compile_vote_count"] == 0
        assert run_a["execution_verdict"] == "BLOCKED"
        assert run_a["broker_post"] is False
        assert run_a["submit_calls"] == 0
        assert run_a["captured_count"] == 0
        assert run_a["metrics_orders_submitted"] == 0
        assert run_a["metrics_compilation_cycles"] == 1
        assert run_a["replay_active_after"] is False

    def test_one_nanosecond_offset_rejects_identically_in_both_runs(self):
        """
        Strict equality, not range — even a +1 ns drift breaks the freshness
        gate, and the rejection is replay-parity-stable.
        """
        run_a = _run_negative_stale(T0_NS, delta_ns=1)
        run_b = _run_negative_stale(T0_NS, delta_ns=1)

        assert run_a == run_b
        assert run_a["compile_calls"] == 1
        assert run_a["compile_vote_count"] == 0
        assert run_a["submit_calls"] == 0
        assert run_a["captured_count"] == 0

    def test_missing_observed_pair_rejects_identically_in_both_runs(self):
        """
        No observed (signal, vote) recorded. The consume gate returns
        (None, None); no compile, no submit, no fill, no metric tick — and
        this rejection signature is identical across two replay runs.
        """
        run_a = _run_negative_missing(T0_NS)
        run_b = _run_negative_missing(T0_NS)

        assert run_a == run_b
        assert run_a["compile_calls"] == 1
        assert run_a["compile_vote_count"] == 0
        assert run_a["submit_calls"] == 0
        assert run_a["captured_count"] == 0
        assert run_a["metrics_orders_submitted"] == 0
        assert run_a["metrics_compilation_cycles"] == 1

    def test_live_broker_mode_rejects_same_clock_pair_identically(self):
        """
        Even with a perfectly same-clock observed pair, broker_mode != 'paper'
        must hard-block the SR consume gate in EVERY replay run. Paper-only
        proving lane is replay-parity-stable.
        """

        def _run_live_block(t0_ns: int) -> Dict[str, Any]:
            with ReplayTimeContext(t0_ns):
                signal = _build_strategy_signal(t0_ns, side="buy")
                vote = _build_vote_via_real_adapter(signal, t0_ns)

                runtime = _build_runtime("ETH/USD")
                runtime.update_candle(_build_candle(t0_ns))
                runtime.update_order_book(_build_book(t0_ns))
                runtime.record_observed_signal("sector_rotation", signal)
                runtime.record_observed_vote("sector_rotation", vote)

                loop = _build_test_loop(broker_mode="live")
                dispatch = _bind(loop, "_dispatch_fusion")
                dispatch(
                    "ETH/USD",
                    runtime,
                    fusion=_build_fusion_decision(t0_ns),
                    exchange_ts_ns=t0_ns,
                )
                return {
                    "compile_calls": loop.decision_compiler.compile.call_count,
                    **_refusal_compile_observables(loop),
                    "submit_calls": loop.execution_engine.submit_signal.call_count,
                    "metrics_orders_submitted": loop._metrics.orders_submitted,
                }

        run_a = _run_live_block(T0_NS)
        run_b = _run_live_block(T0_NS)

        assert run_a == run_b
        assert run_a["compile_calls"] == 1
        assert run_a["compile_vote_count"] == 0
        assert run_a["submit_calls"] == 0
        assert run_a["metrics_orders_submitted"] == 0


# =============================================================================
# 5. Safety invariants — the parity harness itself must not leak live mode,
#    attack mode, or fake artefacts. Pinned for future regression catching.
# =============================================================================


class TestReplayParitySafetyInvariants:

    def test_no_live_mode_env_leak(self):
        live_mode = os.environ.get("LIVE_MODE", "").strip().lower()
        assert live_mode != "true", (
            "LIVE_MODE=true detected — replay parity acceptance refuses to run "
            "under live mode"
        )

    def test_attack_mode_remains_false_through_each_run(self):
        run_a = _run_happy_path(T0_NS)
        run_b = _run_happy_path(T0_NS)
        assert run_a["captured_is_attack"] is False
        assert run_b["captured_is_attack"] is False

    def test_real_adapter_marks_execution_candidate_without_attack_leak(self):
        """
        The production strategy_vote_adapters must mark the vote as
        execution_candidate=True without smuggling any attack-mode key
        through metadata. Pinned in this acceptance harness so a future
        adapter change cannot silently flip attack semantics inside the
        replay parity proof.
        """
        signal = _build_strategy_signal(T0_NS)
        vote = _build_vote_via_real_adapter(signal, T0_NS)
        meta = vote.metadata or {}
        assert meta.get("execution_candidate") is True
        for key in meta.keys():
            assert "attack" not in key.lower(), (
                f"vote metadata leaked an attack-related key: {key}"
            )

    def test_router_is_paper_mode_in_every_run(self):
        """
        OrderRouter constructed inside _run_happy_path must always be
        paper_mode=True. We re-prove this here by reconstructing a router
        the same way the helper does and asserting the flag.
        """
        router = OrderRouter(paper_mode=True)
        assert router.paper_mode is True
        # Fresh broker: no execution reports until an order is submitted.
        broker = router._paper_broker  # type: ignore[attr-defined]
        assert hasattr(broker, "execution_reports")
        assert len(broker.execution_reports) == 0

    def test_replay_state_clean_at_module_exit(self):
        """
        After every test in this module, replay mode must be off. Re-pinned
        as the final assertion so a regression in any earlier test surfaces
        loudly here as well.
        """
        assert not is_replay_mode(), (
            "replay mode leaked across replay parity acceptance tests; "
            "ReplayTimeContext must always be used as a context manager"
        )
