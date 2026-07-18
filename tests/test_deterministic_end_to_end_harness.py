"""
test_deterministic_end_to_end_harness
UPSTREAM_DISPATCH_SIGNAL_SUBMISSION_PROOF_BUNDLE — tests-only deterministic end-to-end harness.

Purpose
-------
Prove the full intended path without random market waiting:

    fresh valid candidate
        -> MainLoop._dispatch_fusion                        (production code)
        -> DecisionCompiler.compile                         (call boundary)
        -> ExecutionEngine.submit_signal                    (call boundary)
        -> OrderRouter.submit_order                         (production code)
        -> PaperBroker                                      (production code)
        -> OrderFill                                        (production object)

The dispatch -> compile -> submit leg is exercised against the unbound
MainLoop methods so the production code paths run; DecisionCompiler and
ExecutionEngine are mocked at their seams to avoid pulling the threaded
ExecutionEngine and the full risk graph into a unit test. The submit -> fill
leg uses the real OrderRouter(paper_mode=True) -> SovereignPaperBroker code
already covered by tests/test_paper_fill_completion.py; here it is wired
deterministically off a candidate that just passed the upstream gates so the
end-to-end shape is provable in one harness run.

Negative cases re-prove that:
- a missing observed pair blocks compile and submit and produces no fill,
- a stale (different-candle) observed pair blocks compile and submit and
  produces no fill,
- the strict same-candle freshness gate has no off-by-one tolerance.

Forbidden in this file (per packet doctrine)
--------------------------------------------
- threshold relaxation
- fake signals / fake fills / forced submission
- bypassing SignalFusion / StrategyRouter / DecisionCompiler / ExecutionEngine
- direct strategy-to-execution shortcut
- any live-mode path
- production code edits
"""

from __future__ import annotations

import time
import types
from decimal import Decimal
from typing import Any, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

from app.commander import Commander
from app.main_loop import MainLoop
from app.models import OrderFill, OrderRequest, StrategySignal
from app.models.enums import (
    InternalOrderStatus,
    OrderSide,
    OrderType,
    SleeveType,
)
from app.execution.order_router import OrderRouter
from app.risk.stale_data_guard import StaleDataGuard, TemporalInput


# =============================================================================
# Helpers — duck-typed stand-ins matching the existing upstream dispatch tests
# =============================================================================


def _make_strategy_signal(
    *,
    exchange_ts_ns: int,
    side: str = "buy",
    quantity: float = 0.5,
    confidence: float = 0.9,
    symbol: str = "ETH/USD",
    strategy: str = "sector_rotation",
    price: Optional[float] = None,
) -> StrategySignal:
    """
    Real StrategySignal pydantic instance. Used both to drive dispatch and to
    seed the OrderRouter -> PaperBroker leg from the SAME object captured at
    the ExecutionEngine.submit_signal seam.
    """
    return StrategySignal(
        strategy=strategy,
        symbol=symbol,
        side=side,
        confidence=confidence,
        quantity=quantity,
        price=price,
        exchange_ts_ns=exchange_ts_ns,
        reason="harness_signal",
        metadata={},
        regime=None,
    )


def _make_vote_stub(*, timestamp_ns: int, decision_uuid: str = "uuid-harness"):
    """
    Duck-typed StrategyVote — sufficient for _dispatch_fusion which only reads
    strategy_votes[0] inside the mocked DecisionCompiler.compile and treats it
    as opaque otherwise.
    """
    return types.SimpleNamespace(
        decision_uuid=decision_uuid,
        timestamp_ns=timestamp_ns,
        confidence=Decimal("0.9"),
        risk_appetite=Decimal("0.5"),
        signal="buy",
        metadata={},
    )


def _make_runtime(
    *,
    last_price: float = 2500.0,
    sector_signal=None,
    sector_vote=None,
    shadow_strategy=None,
    sector_strategy=None,
    gamma_strategy=None,
    flv_strategy=None,
):
    """SymbolRuntime stand-in matching the existing upstream test helper."""
    guard_symbol = str(getattr(sector_signal, "symbol", None) or "ETH/USD")
    guard_ts_ns = int(getattr(sector_signal, "exchange_ts_ns", None) or 1)
    return types.SimpleNamespace(
        last_price=last_price,
        last_sector_rotation_observed_signal=sector_signal,
        last_sector_rotation_observed_vote=sector_vote,
        last_liquidity_void_observed_signal=None,
        last_liquidity_void_observed_vote=None,
        last_liquidity_void_consumed_decision_uuid=None,
        shadow_front_strategy=shadow_strategy,
        sector_rotation_strategy=sector_strategy,
        gamma_front_strategy=gamma_strategy,
        liquidity_void_strategy=flv_strategy,
        toxicity_engine=MagicMock(),
        sentiment_velocity_engine=MagicMock(),
        last_stale_data_assessment=StaleDataGuard(guard_symbol).assess(
            TemporalInput(guard_ts_ns, guard_ts_ns, guard_ts_ns)
        ),
        last_tpe_signal=None,
    )


def _make_fusion(ts_ns: int, preferred: str = "shadow_front"):
    """FusionDecision stand-in — only the fields _dispatch_fusion reads."""
    return types.SimpleNamespace(
        exchange_ts_ns=ts_ns,
        attack_mode=False,
        preferred_sleeve=preferred,
        sector_rotation_eligible=True,
        shadow_front_eligible=True,
    )


def _make_test_loop(
    *,
    broker_mode: str = "paper",
    preferred_sleeve: SleeveType = SleeveType.SHADOW_FRONT,
    eligible_sleeves: Optional[List[SleeveType]] = None,
    gen_sf_signal: Optional[Tuple[Any, Any]] = None,
):
    """Minimal MainLoop-shaped test double mirroring the upstream test helper."""
    if eligible_sleeves is None:
        eligible_sleeves = [SleeveType.SHADOW_FRONT, SleeveType.SECTOR_ROTATION]

    loop = types.SimpleNamespace()
    loop.config = types.SimpleNamespace(broker_mode=broker_mode)
    loop.commander = Commander()

    loop.strategy_router = MagicMock()
    loop.strategy_router.update_macro_state = MagicMock()
    loop.strategy_router.get_preferred_strategy = MagicMock(return_value=preferred_sleeve)
    loop.strategy_router.get_eligible_strategies = MagicMock(return_value=eligible_sleeves)

    loop.decision_compiler = MagicMock()
    loop.decision_compiler.reserve_decision_uuid = MagicMock(return_value="uuid-harness")
    loop.decision_compiler.compile = MagicMock(
        return_value=types.SimpleNamespace(
            decision_uuid="uuid-harness", decision_type="STRATEGY_VOTE"
        )
    )

    loop.execution_engine = MagicMock()
    loop.execution_engine.submit_signal = MagicMock(return_value=True)
    loop.execution_engine.get_status.return_value = {"last_latency_truth": {}}

    loop._build_truth_frame = MagicMock(return_value="truth-frame-stub")
    loop._update_shadow_front_overlays = MagicMock()
    loop._generate_signal_and_vote = MagicMock(return_value=(None, None))
    loop._generate_signal_and_vote_gamma_front = MagicMock(return_value=(None, None))

    if gen_sf_signal is not None:
        loop._generate_signal_and_vote = MagicMock(return_value=gen_sf_signal)

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


def _assert_refusal_decision_recorded(loop) -> None:
    """A lawful decline is compiled for audit, but never reaches execution."""
    loop.decision_compiler.compile.assert_called_once()
    _, compile_kwargs = loop.decision_compiler.compile.call_args
    assert compile_kwargs["strategy_votes"] == []
    additional_inputs = compile_kwargs["additional_inputs"]
    assert additional_inputs["no_submit_reason_code"] in {
        "DECISION_FRAME_BLOCKED",
        "DECISION_FRAME_NO_TRADE",
    }
    lifecycle = additional_inputs["candidate_lifecycle"]
    assert lifecycle["execution_verdict"] == "BLOCKED"
    assert lifecycle["broker_post"] is False
    loop.execution_engine.submit_signal.assert_not_called()
    assert loop._metrics.orders_submitted == 0
    assert loop._metrics.compilation_cycles == 1


def _strategy_signal_to_order_request(
    signal: StrategySignal, *, receive_ts_ns: int
) -> OrderRequest:
    """
    Build an OrderRequest from a StrategySignal in the same shape that
    ExecutionEngine._execute_signal (app/execution/engine.py) builds it: same
    id pattern, MARKET order_type when no attack/limit price, side and quantity
    preserved end-to-end.

    This is a tests-only adapter. It does not bypass any production seam — the
    purpose is to feed the captured-at-submit_signal signal through the real
    OrderRouter -> PaperBroker leg deterministically.
    """
    side_map = {"buy": OrderSide.BUY, "sell": OrderSide.SELL}
    if signal.side not in side_map:
        raise AssertionError(
            f"harness only routes actionable signals; got side={signal.side!r}"
        )
    sleeve_map = {
        "sector_rotation": SleeveType.SECTOR_ROTATION,
        "shadow_front": SleeveType.SHADOW_FRONT,
        "gamma_front": SleeveType.GAMMA_FRONT,
        "flv": SleeveType.FLV,
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
        metadata={"harness": "deterministic_end_to_end"},
    )


# =============================================================================
# 1. Dispatch -> DecisionCompiler.compile -> ExecutionEngine.submit_signal
# =============================================================================


class TestDispatchToSubmitDeterministic:
    """
    Deterministic proof of the upstream chain WITHOUT random market waiting:
        fresh valid candidate -> dispatch -> compile() -> submit_signal()

    Each test fixes exchange_ts_ns explicitly so the same-candle freshness
    gate is the deterministic axis.
    """

    def test_fresh_sector_rotation_pair_runs_full_chain(self):
        """
        Fresh same-candle SR observed pair -> dispatch must:
          1. produce no SF signal (mocked decline),
          2. fall back to SECTOR_ROTATION,
          3. read the observed pair via _consume_observed_pair_sector_rotation,
          4. call DecisionCompiler.compile exactly once with that vote,
          5. call ExecutionEngine.submit_signal exactly once with that signal,
          6. record one orders_submitted metric tick.
        """
        loop = _make_test_loop()
        ts = 8_000_000_000_000
        observed_sig = _make_strategy_signal(exchange_ts_ns=ts, symbol="ETH/USD")
        observed_vote = _make_vote_stub(timestamp_ns=ts)
        runtime = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
            sector_signal=observed_sig,
            sector_vote=observed_vote,
            last_price=2500.0,
        )

        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", runtime, fusion=_make_fusion(ts), exchange_ts_ns=ts)

        # Compile reached exactly once with our SR vote.
        assert loop.decision_compiler.compile.call_count == 1
        _, compile_kwargs = loop.decision_compiler.compile.call_args
        assert compile_kwargs.get("strategy_votes") == [observed_vote]

        # Submit reached exactly once with our SR signal.
        assert loop.execution_engine.submit_signal.call_count == 1
        _, submit_kwargs = loop.execution_engine.submit_signal.call_args
        assert submit_kwargs.get("signal") is observed_sig
        assert submit_kwargs.get("current_price") == 2500.0
        assert submit_kwargs.get("is_attack") is False

        assert loop._metrics.orders_submitted == 1
        assert loop._metrics.compilation_cycles == 1

    def test_fresh_shadow_front_signal_runs_full_chain(self):
        """
        SF wins the candidate loop with a fresh (signal, vote) and dispatch
        must compile + submit exactly that pair, never even reading the SR
        stash.
        """
        ts = 9_000_000_000_000
        sf_signal = _make_strategy_signal(
            exchange_ts_ns=ts, strategy="shadow_front", symbol="ETH/USD"
        )
        sf_vote = _make_vote_stub(timestamp_ns=ts, decision_uuid="sf-uuid")
        loop = _make_test_loop(gen_sf_signal=(sf_signal, sf_vote))

        # SR has a fresh stash too — must be IGNORED when SF wins.
        sr_signal = _make_strategy_signal(
            exchange_ts_ns=ts, side="sell", strategy="sector_rotation"
        )
        sr_vote = _make_vote_stub(timestamp_ns=ts, decision_uuid="sr-uuid")
        runtime = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
            sector_signal=sr_signal,
            sector_vote=sr_vote,
            last_price=2500.0,
        )

        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", runtime, fusion=_make_fusion(ts), exchange_ts_ns=ts)

        assert loop.decision_compiler.compile.call_count == 1
        _, compile_kwargs = loop.decision_compiler.compile.call_args
        assert compile_kwargs.get("strategy_votes") == [sf_vote]

        assert loop.execution_engine.submit_signal.call_count == 1
        _, submit_kwargs = loop.execution_engine.submit_signal.call_args
        assert submit_kwargs.get("signal") is sf_signal
        assert submit_kwargs.get("is_attack") is False

    def test_missing_observed_pair_records_refusal_without_submit(self):
        """SF declines and the missing SR pair is recorded without execution."""
        loop = _make_test_loop()
        runtime = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
        )
        ts = 10_000_000_000_000
        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", runtime, fusion=_make_fusion(ts), exchange_ts_ns=ts)

        _assert_refusal_decision_recorded(loop)

    def test_stale_observed_pair_records_refusal_without_submit(self):
        """
        Reproduces the SOL/USD proof-log topology: SR stash carries a prior
        candle's (signal, vote); current candle ts differs by ~10.4h. Strict
        same-candle freshness must block compile and submit.
        """
        loop = _make_test_loop()
        stored_ts = 1_778_073_300_000_000_000
        candle_ts = 1_778_110_800_000_000_000  # ~10.4h after stored
        runtime = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
            sector_signal=_make_strategy_signal(
                exchange_ts_ns=stored_ts, symbol="SOL/USD"
            ),
            sector_vote=_make_vote_stub(timestamp_ns=stored_ts),
        )
        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch(
            "SOL/USD", runtime, fusion=_make_fusion(candle_ts), exchange_ts_ns=candle_ts
        )

        _assert_refusal_decision_recorded(loop)

    def test_one_nanosecond_offset_records_refusal_without_submit(self):
        """Strict equality, not range — even +1 ns drift blocks the SR fallback."""
        loop = _make_test_loop()
        stored_ts = 5_000_000_000_000
        candle_ts = stored_ts + 1
        runtime = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
            sector_signal=_make_strategy_signal(exchange_ts_ns=stored_ts),
            sector_vote=_make_vote_stub(timestamp_ns=stored_ts),
        )
        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch(
            "ETH/USD", runtime, fusion=_make_fusion(candle_ts), exchange_ts_ns=candle_ts
        )

        _assert_refusal_decision_recorded(loop)

    def test_non_paper_broker_records_refusal_without_submit(self):
        """Paper-only proving lane: live broker_mode hard-blocks SR admission."""
        loop = _make_test_loop(broker_mode="live")
        ts = 6_000_000_000_000
        runtime = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
            sector_signal=_make_strategy_signal(exchange_ts_ns=ts),
            sector_vote=_make_vote_stub(timestamp_ns=ts),
        )
        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", runtime, fusion=_make_fusion(ts), exchange_ts_ns=ts)

        _assert_refusal_decision_recorded(loop)


# =============================================================================
# 2. ExecutionEngine.submit_signal -> OrderRouter -> PaperBroker -> OrderFill
# =============================================================================


class TestSubmitToFillDeterministic:
    """
    The submit -> fill leg using REAL OrderRouter(paper_mode=True) and the
    sovereign PaperBroker. The signal is the same shape captured at the
    ExecutionEngine.submit_signal seam in the dispatch tests above; the
    adapter mirrors how ExecutionEngine._execute_signal builds the
    OrderRequest, so the contract under test is the production one.
    """

    def test_market_buy_signal_yields_paper_fill(self):
        ts = int(time.time_ns())
        signal = _make_strategy_signal(
            exchange_ts_ns=ts, side="buy", quantity=0.5, symbol="ETH/USD"
        )
        order = _strategy_signal_to_order_request(signal, receive_ts_ns=ts)

        router = OrderRouter(paper_mode=True)
        fill = router.submit_order(order)

        assert fill is not None, "MARKET BUY paper fill must be deterministic"
        assert isinstance(fill, OrderFill)
        assert fill.symbol == "ETH/USD"
        assert fill.quantity == Decimal("0.5")
        assert fill.price > Decimal("0")
        # Decimal discipline must hold end-to-end.
        assert isinstance(fill.quantity, Decimal)
        assert isinstance(fill.price, Decimal)
        assert isinstance(fill.fee, Decimal)

    def test_signal_side_preserved_through_fill(self):
        ts = int(time.time_ns())
        signal = _make_strategy_signal(
            exchange_ts_ns=ts, side="sell", quantity=0.25, symbol="ETH/USD"
        )
        order = _strategy_signal_to_order_request(signal, receive_ts_ns=ts)

        router = OrderRouter(paper_mode=True)
        fill = router.submit_order(order)

        assert fill is not None, "MARKET SELL paper fill must be deterministic"
        # OrderRouter passes through OrderSide; compare via .value to dodge
        # use_enum_values surfaces in either layer.
        fill_side = fill.side.value if hasattr(fill.side, "value") else fill.side
        assert fill_side == OrderSide.SELL.value
        assert fill.quantity == Decimal("0.25")

    def test_no_fill_when_no_signal_was_submitted(self):
        """
        Negative invariant: the OrderRouter must not produce a fill spontaneously.
        Concretely — a fresh router instance with no submitted order has no fill
        history. This pins "no fake success" for the harness as a whole.
        """
        router = OrderRouter(paper_mode=True)
        # The sovereign paper broker exposes execution_reports; a fresh instance
        # must hold none.
        broker = router._paper_broker  # type: ignore[attr-defined]
        assert hasattr(broker, "execution_reports")
        assert len(broker.execution_reports) == 0


# =============================================================================
# 3. End-to-end tying: dispatch capture -> real router -> fill
# =============================================================================


class TestEndToEndChain:
    """
    Single-test deterministic proof that wires the dispatch capture and the
    real OrderRouter together: capture the StrategySignal at the
    ExecutionEngine.submit_signal seam, then route it through the real
    OrderRouter -> PaperBroker leg and verify a real OrderFill emerges. No
    timing waits, no random market data.
    """

    def test_fresh_candidate_traverses_dispatch_compile_submit_route_fill(self):
        captured: List[Any] = []

        loop = _make_test_loop()
        # Replace submit_signal with a capturer that still returns True so
        # _metrics.orders_submitted ticks (no production behavior changed).
        def _capture(signal, current_price, is_attack, **_execution_context):
            captured.append(
                {"signal": signal, "current_price": current_price, "is_attack": is_attack}
            )
            return True

        loop.execution_engine.submit_signal = MagicMock(side_effect=_capture)

        ts = int(time.time_ns())
        signal = _make_strategy_signal(
            exchange_ts_ns=ts, side="buy", quantity=0.5, symbol="ETH/USD"
        )
        vote = _make_vote_stub(timestamp_ns=ts, decision_uuid="e2e-uuid")
        runtime = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
            sector_signal=signal,
            sector_vote=vote,
            last_price=2500.0,
        )

        # Dispatch leg: production code chooses SR fallback after SF declines.
        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", runtime, fusion=_make_fusion(ts), exchange_ts_ns=ts)

        # The chain must have reached compile and submit exactly once each.
        assert loop.decision_compiler.compile.call_count == 1
        assert loop.execution_engine.submit_signal.call_count == 1
        assert len(captured) == 1
        captured_signal = captured[0]["signal"]
        assert captured_signal is signal
        assert captured[0]["is_attack"] is False
        assert captured[0]["current_price"] == 2500.0

        # Submit -> fill leg: send the SAME captured StrategySignal through the
        # real OrderRouter -> PaperBroker pipe.
        order = _strategy_signal_to_order_request(captured_signal, receive_ts_ns=ts)
        router = OrderRouter(paper_mode=True)
        fill = router.submit_order(order)

        # Real OrderFill must be produced with the same identity surface as the
        # captured signal.
        assert fill is not None
        assert isinstance(fill, OrderFill)
        assert fill.symbol == captured_signal.symbol
        assert fill.quantity == Decimal(str(captured_signal.quantity))
        assert fill.price > Decimal("0")
        assert isinstance(fill.fee, Decimal)


# =============================================================================
# 4. Negative end-to-end: invalid upstream candidate must NOT produce a fill
# =============================================================================


class TestEndToEndNegativeChain:
    """
    Mirrors TestEndToEndChain but with an invalid upstream candidate. Because
    the dispatch leg legitimately declines, no signal is captured and no fill
    can be produced. We assert ALL of:
        - an immutable refusal decision is compiled,
        - submit_signal not called,
        - the (intentionally not built) OrderRequest path is never invoked.
    This is the harness-level equivalent of "no fake success."
    """

    def test_missing_observed_pair_yields_refusal_record_no_submit_no_fill(self):
        captured: List[Any] = []

        loop = _make_test_loop()
        loop.execution_engine.submit_signal = MagicMock(
            side_effect=lambda **_: captured.append(_) or True
        )

        ts = int(time.time_ns())
        runtime = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
            # No sector_signal / sector_vote stash.
        )

        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", runtime, fusion=_make_fusion(ts), exchange_ts_ns=ts)

        _assert_refusal_decision_recorded(loop)
        assert captured == []

        # And no OrderRouter is constructed: a downstream fill is impossible
        # by construction here, which is exactly the invariant.
        assert loop._metrics.orders_submitted == 0

    def test_stale_observed_pair_yields_refusal_record_no_submit_no_fill(self):
        captured: List[Any] = []

        loop = _make_test_loop()
        loop.execution_engine.submit_signal = MagicMock(
            side_effect=lambda **_: captured.append(_) or True
        )

        stored_ts = 2_000_000_000_000
        candle_ts = stored_ts + 60_000_000_000  # +60s, plainly different candle
        runtime = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
            sector_signal=_make_strategy_signal(exchange_ts_ns=stored_ts),
            sector_vote=_make_vote_stub(timestamp_ns=stored_ts),
        )

        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch(
            "ETH/USD", runtime, fusion=_make_fusion(candle_ts), exchange_ts_ns=candle_ts
        )

        _assert_refusal_decision_recorded(loop)
        assert captured == []
