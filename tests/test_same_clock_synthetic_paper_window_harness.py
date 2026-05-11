"""
test_same_clock_synthetic_paper_window_harness
SAME_CLOCK_SYNTHETIC_PAPER_WINDOW_HARNESS_BUNDLE — tests-only proof harness.

Purpose
-------
Prove that a legitimate, fully same-clock candidate travels through the real
bot spine into a real PaperBroker fill:

    synthetic Candle / OrderBookSnapshot (exchange_ts_ns = t0_ns)
        -> SymbolRuntime.update_candle / update_order_book   (production)
        -> SymbolRuntime.record_observed_signal/vote          (production)
        -> MainLoop._dispatch_fusion                          (production)
        -> MainLoop._consume_observed_pair_sector_rotation    (production)
        -> DecisionCompiler.compile                           (call boundary)
        -> ExecutionEngine.submit_signal                      (capture seam)
        -> OrderRouter.submit_order(paper_mode=True)          (production)
        -> SovereignPaperBroker                               (production)
        -> OrderFill                                          (production object)

Same-clock invariant
--------------------
A single t0_ns drives every timestamp the spine inspects:
    candle.exchange_ts_ns == book.exchange_ts_ns
                          == signal.exchange_ts_ns
                          == vote.timestamp_ns
                          == fusion.exchange_ts_ns
                          == dispatch exchange_ts_ns
                          == now_ns()  (under ReplayTimeContext(t0_ns))

The StrategyVote is built by the real production adapter
``app.strategies.strategy_vote_adapters.adapt_sector_rotation_to_vote``;
the Candle / OrderBookSnapshot / StrategySignal are real pydantic models;
the SymbolRuntime is a real dataclass instance and ingests the candle /
book through its own production update methods.

Bypassing forbidden by packet doctrine
--------------------------------------
- threshold relaxation
- fake signals / fake fills / forced submission
- bypassing SignalFusion / StrategyRouter / DecisionCompiler / ExecutionEngine
  / OrderRouter / SovereignPaperBroker
- direct strategy-to-execution shortcut
- any live-mode path
- any --attack path
- production code edits

The only mocked seams are:
- StrategyRouter.update_macro_state / get_preferred_strategy /
  get_eligible_strategies — its policy is exercised in its own dedicated tests;
  here we only need it to admit SECTOR_ROTATION as a fallback candidate so the
  same-candle freshness gate is the deterministic axis.
- DecisionCompiler.compile — call-boundary seam, identical to the
  test_deterministic_end_to_end_harness convention; this avoids pulling the
  full DecisionCompiler graph into the unit harness while still proving the
  call shape.
- ExecutionEngine.submit_signal — capture seam; the captured StrategySignal
  is then routed through the REAL OrderRouter -> SovereignPaperBroker path
  to produce a real OrderFill.
- _build_truth_frame — stub; truth frame construction is out of scope for
  this packet and exercised by its own tests.
"""

from __future__ import annotations

import os
import types
from decimal import Decimal
from typing import Any, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

from app.main_loop import MainLoop
from app.models import OrderFill, OrderRequest, StrategySignal
from app.models.enums import OrderSide, OrderType, SleeveType
from app.models.market_data import Candle, OrderBookSnapshot
from app.execution.order_router import OrderRouter
from app.strategies.strategy_vote_adapters import adapt_sector_rotation_to_vote
from app.symbol_runtime import SymbolRuntime
from app.utils.time_utils import (
    ReplayTimeContext,
    now_ns,
    is_replay_mode,
)


# =============================================================================
# Fixture builders — every timestamp derives from t0_ns
# =============================================================================


def _build_candle(t0_ns: int, *, symbol: str = "ETH/USD", close: float = 2500.0) -> Candle:
    """Real Candle pydantic model anchored to t0_ns."""
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
    """Real OrderBookSnapshot pydantic model anchored to t0_ns."""
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
    """Real StrategySignal pydantic model with exchange_ts_ns = t0_ns."""
    return StrategySignal(
        strategy="sector_rotation",
        symbol=symbol,
        side=side,
        confidence=confidence,
        quantity=quantity,
        price=None,
        exchange_ts_ns=t0_ns,
        reason="same_clock_synthetic_paper_window_harness",
        metadata={},
        regime=None,
    )


def _build_vote_via_real_adapter(signal: StrategySignal, t0_ns: int):
    """
    Real StrategyVote produced by the production adapter
    ``adapt_sector_rotation_to_vote``. The adapter sets vote.timestamp_ns
    from the supplied exchange_ts_ns, locking the same-clock invariant.
    """
    return adapt_sector_rotation_to_vote(
        signal,
        exchange_ts_ns=t0_ns,
        decision_uuid="same-clock-harness-uuid",
    )


def _build_runtime(symbol: str = "ETH/USD") -> SymbolRuntime:
    """
    Real SymbolRuntime dataclass instance. We DO NOT call initialize_engines
    (that would pull the full per-symbol engine graph). Instead the test
    drives only the production methods this packet's seam needs:
    ``update_candle``, ``update_order_book``, ``record_observed_signal``,
    ``record_observed_vote``. Strategy slots are filled with MagicMock so
    StrategyRouter eligibility and registration checks succeed; the strategies
    themselves are never invoked in this harness because the candidate path
    we exercise is the OBSERVE-ONLY -> consume-observed-pair seam, not the
    on-the-fly _generate_signal_and_vote seam.
    """
    runtime = SymbolRuntime(symbol=symbol)
    runtime.shadow_front_strategy = MagicMock()
    runtime.sector_rotation_strategy = MagicMock()
    runtime.toxicity_engine = MagicMock()
    runtime.sentiment_velocity_engine = MagicMock()
    return runtime


def _build_fusion_decision(t0_ns: int, *, preferred: str = "shadow_front"):
    """
    FusionDecision-shaped namespace whose exchange_ts_ns equals t0_ns. The
    deterministic harness uses the same SimpleNamespace convention; production
    _dispatch_fusion only reads ``exchange_ts_ns``, ``attack_mode``,
    ``preferred_sleeve``, ``sector_rotation_eligible`` and ``shadow_front_eligible``.
    """
    return types.SimpleNamespace(
        exchange_ts_ns=t0_ns,
        attack_mode=False,
        preferred_sleeve=preferred,
        sector_rotation_eligible=True,
        shadow_front_eligible=True,
    )


def _build_test_loop(*, broker_mode: str = "paper") -> types.SimpleNamespace:
    """
    Minimal MainLoop-shaped test double mirroring the existing harness
    convention. StrategyRouter / DecisionCompiler / ExecutionEngine are the
    only mocked production seams; their own dedicated tests pin their
    behaviour.
    """
    loop = types.SimpleNamespace()
    loop.config = types.SimpleNamespace(broker_mode=broker_mode)

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
        return_value="same-clock-harness-uuid"
    )
    loop.decision_compiler.compile = MagicMock(
        return_value=types.SimpleNamespace(
            decision_uuid="same-clock-harness-uuid",
            decision_type="STRATEGY_VOTE",
        )
    )

    loop.execution_engine = MagicMock()
    loop.execution_engine.submit_signal = MagicMock(return_value=True)

    loop._build_truth_frame = MagicMock(return_value="truth-frame-stub")
    loop._update_shadow_front_overlays = MagicMock()
    loop._generate_signal_and_vote = MagicMock(return_value=(None, None))
    loop._generate_signal_and_vote_gamma_front = MagicMock(return_value=(None, None))

    loop._metrics = types.SimpleNamespace(
        orders_submitted=0, orders_rejected=0, compilation_cycles=0
    )
    loop.insider_engine = MagicMock()

    loop._consume_observed_pair_sector_rotation = (
        MainLoop._consume_observed_pair_sector_rotation.__get__(loop, MainLoop)
    )
    loop._consume_observed_pair_liquidity_void = (
        MainLoop._consume_observed_pair_liquidity_void.__get__(loop, MainLoop)
    )
    return loop


def _bind(loop, method_name: str):
    return getattr(MainLoop, method_name).__get__(loop, MainLoop)


def _strategy_signal_to_order_request(
    signal: StrategySignal, *, receive_ts_ns: int
) -> OrderRequest:
    """
    Build an OrderRequest from a captured StrategySignal in the same shape
    that ExecutionEngine._execute_signal builds it (id pattern, MARKET when
    no limit price, side / quantity preserved). This is a tests-only adapter
    used to feed the captured-at-submit_signal signal through the real
    OrderRouter -> SovereignPaperBroker leg deterministically. It does NOT
    bypass any production seam; receive_ts_ns is bound to t0_ns to preserve
    the same-clock invariant end-to-end.
    """
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
        metadata={"harness": "same_clock_synthetic_paper_window"},
    )


# A single, fixed t0_ns shared by all tests so the proof artefacts are
# inspectable and deterministic. ~ 2026-04-30 09:00:00 UTC.
T0_NS: int = 1_777_948_800_000_000_000


# =============================================================================
# 1. Same-clock fixture model
# =============================================================================


class TestSameClockFixtureModel:
    """
    Establish the same-clock fixture model. Every timestamp the spine inspects
    derives from a single t0_ns.
    """

    def test_all_inputs_share_t0_ns(self):
        candle = _build_candle(T0_NS)
        book = _build_book(T0_NS)
        signal = _build_strategy_signal(T0_NS)
        vote = _build_vote_via_real_adapter(signal, T0_NS)
        fusion = _build_fusion_decision(T0_NS)

        assert candle.exchange_ts_ns == T0_NS
        assert book.exchange_ts_ns == T0_NS
        assert signal.exchange_ts_ns == T0_NS
        assert vote.timestamp_ns == T0_NS
        assert fusion.exchange_ts_ns == T0_NS

        # The vote was produced by the REAL adapter; its decision_uuid is the
        # one we supplied — confirming we did not silently lose authority.
        assert vote.decision_uuid == "same-clock-harness-uuid"

    def test_now_ns_is_deterministic_under_replay_context(self):
        """
        ReplayTimeContext is the existing test utility for binding now_ns().
        Inside the context, now_ns() must return t0_ns; outside it, replay
        mode must clear cleanly.
        """
        assert not is_replay_mode(), "replay mode must not leak across tests"
        with ReplayTimeContext(T0_NS):
            assert is_replay_mode()
            assert now_ns() == T0_NS
        assert not is_replay_mode(), "ReplayTimeContext must restore prior state on exit"

    def test_real_symbolruntime_ingests_same_clock_candle_and_book(self):
        """
        Drive the production SymbolRuntime.update_candle and update_order_book
        with same-clock fixtures. Both methods must record exchange_ts_ns =
        t0_ns into runtime state without any local-time fallback.
        """
        runtime = _build_runtime("ETH/USD")
        candle = _build_candle(T0_NS)
        book = _build_book(T0_NS)

        runtime.update_candle(candle)
        runtime.update_order_book(book)

        assert runtime.last_candle is candle
        assert runtime.last_order_book is book
        # update_order_book runs after update_candle; both must agree on t0_ns.
        assert runtime.last_update_timestamp_ns == T0_NS

    def test_real_record_observed_methods_install_same_clock_pair(self):
        """
        Production SymbolRuntime.record_observed_signal/vote must install the
        same-clock pair under the sector_rotation observed slots. No mutation
        of timestamps may occur on admission.
        """
        runtime = _build_runtime("ETH/USD")
        signal = _build_strategy_signal(T0_NS)
        vote = _build_vote_via_real_adapter(signal, T0_NS)

        runtime.record_observed_signal("sector_rotation", signal)
        runtime.record_observed_vote("sector_rotation", vote)

        assert runtime.last_sector_rotation_observed_signal is signal
        assert runtime.last_sector_rotation_observed_vote is vote
        assert runtime.last_sector_rotation_observed_signal.exchange_ts_ns == T0_NS
        assert runtime.last_sector_rotation_observed_vote.timestamp_ns == T0_NS


# =============================================================================
# 2. Real-spine candidate path — synthetic book/candle reaches MainLoop dispatch,
#    DecisionCompiler.compile is invoked, ExecutionEngine.submit_signal is
#    invoked, and the captured signal flows through the real OrderRouter ->
#    SovereignPaperBroker path to produce a real OrderFill.
# =============================================================================


class TestSameClockRealSpinePaperFill:

    def test_same_clock_candidate_traverses_dispatch_compile_submit_route_fill(self):
        """
        Single-shot end-to-end proof. Inside ReplayTimeContext(T0_NS):
          1. Build same-clock Candle / OrderBookSnapshot / StrategySignal /
             StrategyVote (vote built by the production adapter).
          2. Real SymbolRuntime ingests the candle and book via its production
             update methods, then records the observed (signal, vote) pair via
             its production record_* methods.
          3. Real MainLoop._dispatch_fusion runs against this runtime; it
             invokes the real _consume_observed_pair_sector_rotation, which
             admits the pair under strict same-candle freshness.
          4. DecisionCompiler.compile is called exactly once with the real
             vote; ExecutionEngine.submit_signal is called exactly once with
             the real signal and is_attack=False.
          5. The captured StrategySignal is routed through the real
             OrderRouter(paper_mode=True) -> SovereignPaperBroker path; a real
             OrderFill is produced with Decimal-clean fields and no live-mode
             leak.
        """
        with ReplayTimeContext(T0_NS):
            assert now_ns() == T0_NS

            # ---- Same-clock fixtures ------------------------------------
            candle = _build_candle(T0_NS, close=2500.0)
            book = _build_book(T0_NS, mid=2500.0)
            signal = _build_strategy_signal(T0_NS, side="buy", quantity=0.5)
            vote = _build_vote_via_real_adapter(signal, T0_NS)

            # ---- Real SymbolRuntime ingestion ---------------------------
            runtime = _build_runtime("ETH/USD")
            runtime.update_candle(candle)
            runtime.update_order_book(book)
            runtime.record_observed_signal("sector_rotation", signal)
            runtime.record_observed_vote("sector_rotation", vote)

            # Capture the signal at the ExecutionEngine.submit_signal seam.
            captured: List[dict] = []
            def _capture(signal, current_price, is_attack):
                captured.append(
                    {"signal": signal, "current_price": current_price, "is_attack": is_attack}
                )
                return True

            loop = _build_test_loop(broker_mode="paper")
            loop.execution_engine.submit_signal = MagicMock(side_effect=_capture)

            # ---- Real production dispatch -------------------------------
            dispatch = _bind(loop, "_dispatch_fusion")
            dispatch(
                "ETH/USD",
                runtime,
                fusion=_build_fusion_decision(T0_NS),
                exchange_ts_ns=T0_NS,
            )

            # The real production chain reached compile and submit exactly
            # once each, with the same-clock vote and signal we installed.
            assert loop.decision_compiler.compile.call_count == 1
            _, compile_kwargs = loop.decision_compiler.compile.call_args
            assert compile_kwargs.get("strategy_votes") == [vote]
            # First positional arg is the truth frame stub.
            compile_args, _ = loop.decision_compiler.compile.call_args
            assert compile_args[0] == "truth-frame-stub"

            assert loop.execution_engine.submit_signal.call_count == 1
            assert len(captured) == 1
            captured_signal = captured[0]["signal"]
            assert captured_signal is signal
            assert captured[0]["is_attack"] is False
            # current_price flows from runtime.last_price, which update_candle
            # set to candle.close inside the same-clock window.
            assert captured[0]["current_price"] == candle.close

            # ---- Real OrderRouter -> PaperBroker -> OrderFill ----------
            order = _strategy_signal_to_order_request(captured_signal, receive_ts_ns=T0_NS)
            router = OrderRouter(paper_mode=True)
            assert router.paper_mode is True, "OrderRouter must be paper, not live"
            fill = router.submit_order(order)

            # Real OrderFill, real PaperBroker — no fake fill.
            assert fill is not None
            assert isinstance(fill, OrderFill)
            assert fill.symbol == captured_signal.symbol
            assert fill.quantity == Decimal(str(captured_signal.quantity))
            assert fill.price > Decimal("0")

            # Decimal discipline must hold end-to-end.
            assert isinstance(fill.quantity, Decimal)
            assert isinstance(fill.price, Decimal)
            assert isinstance(fill.fee, Decimal)

            # Same-clock invariants hold on the captured signal AND on the
            # OrderRequest that fed the broker.
            assert captured_signal.exchange_ts_ns == T0_NS
            assert order.exchange_ts_ns == T0_NS
            assert order.receive_ts_ns == T0_NS

            # Submission metric ticked exactly once.
            assert loop._metrics.orders_submitted == 1
            assert loop._metrics.compilation_cycles == 1

    def test_market_sell_through_same_clock_seam_yields_real_fill(self):
        """
        Side-coverage variant. SELL must reach a real OrderFill via the same
        real OrderRouter -> PaperBroker leg, with same-clock invariants
        preserved on the route side as well.
        """
        with ReplayTimeContext(T0_NS):
            signal = _build_strategy_signal(T0_NS, side="sell", quantity=0.25)
            vote = _build_vote_via_real_adapter(signal, T0_NS)

            runtime = _build_runtime("ETH/USD")
            runtime.update_candle(_build_candle(T0_NS, close=2500.0))
            runtime.update_order_book(_build_book(T0_NS, mid=2500.0))
            runtime.record_observed_signal("sector_rotation", signal)
            runtime.record_observed_vote("sector_rotation", vote)

            captured: List[dict] = []
            loop = _build_test_loop(broker_mode="paper")
            loop.execution_engine.submit_signal = MagicMock(
                side_effect=lambda signal, current_price, is_attack:
                    captured.append({"signal": signal, "current_price": current_price,
                                     "is_attack": is_attack}) or True
            )

            dispatch = _bind(loop, "_dispatch_fusion")
            dispatch(
                "ETH/USD",
                runtime,
                fusion=_build_fusion_decision(T0_NS),
                exchange_ts_ns=T0_NS,
            )

            assert len(captured) == 1
            captured_signal = captured[0]["signal"]
            assert captured_signal is signal
            assert captured[0]["is_attack"] is False

            order = _strategy_signal_to_order_request(captured_signal, receive_ts_ns=T0_NS)
            router = OrderRouter(paper_mode=True)
            fill = router.submit_order(order)

            assert fill is not None
            assert isinstance(fill, OrderFill)
            fill_side = fill.side.value if hasattr(fill.side, "value") else fill.side
            assert fill_side == OrderSide.SELL.value
            assert fill.quantity == Decimal("0.25")


# =============================================================================
# 3. Negative / guard assertions — when the same-clock invariant is broken,
#    or when paper-only governance is violated, the real spine must NOT reach
#    a fill. No fake success is permitted.
# =============================================================================


class TestSameClockNegativeAndGuards:

    def test_mismatched_exchange_ts_ns_blocks_compile_submit_and_fill(self):
        """
        Strict same-candle freshness gate. The observed pair carries timestamp
        t0_ns - DELTA on BOTH the signal and the vote; dispatch runs at t0_ns.
        Neither vote_ts == exchange_ts_ns nor signal_ts == exchange_ts_ns is
        true, so _consume_observed_pair_sector_rotation must return (None,
        None). compile, submit, and PaperBroker must never be reached.
        """
        DELTA_NS = 60_000_000_000  # +60 s, plainly different candle
        with ReplayTimeContext(T0_NS):
            stale_signal = _build_strategy_signal(T0_NS - DELTA_NS, side="buy")
            stale_vote = _build_vote_via_real_adapter(stale_signal, T0_NS - DELTA_NS)

            runtime = _build_runtime("ETH/USD")
            runtime.update_candle(_build_candle(T0_NS, close=2500.0))
            runtime.update_order_book(_build_book(T0_NS, mid=2500.0))
            runtime.record_observed_signal("sector_rotation", stale_signal)
            runtime.record_observed_vote("sector_rotation", stale_vote)

            captured: List[dict] = []
            loop = _build_test_loop(broker_mode="paper")
            loop.execution_engine.submit_signal = MagicMock(
                side_effect=lambda signal, current_price, is_attack:
                    captured.append({"signal": signal}) or True
            )

            dispatch = _bind(loop, "_dispatch_fusion")
            dispatch(
                "ETH/USD",
                runtime,
                fusion=_build_fusion_decision(T0_NS),
                exchange_ts_ns=T0_NS,
            )

            loop.decision_compiler.compile.assert_not_called()
            loop.execution_engine.submit_signal.assert_not_called()
            assert captured == []
            assert loop._metrics.orders_submitted == 0

            # And no OrderRouter is constructed: a fill is impossible by
            # construction here, which is exactly the invariant.

    def test_one_nanosecond_offset_still_blocks_fill(self):
        """
        Strict equality, not range — even a +1 ns drift breaks the freshness
        gate and no fill is produced.
        """
        with ReplayTimeContext(T0_NS):
            stale_signal = _build_strategy_signal(T0_NS - 1, side="buy")
            stale_vote = _build_vote_via_real_adapter(stale_signal, T0_NS - 1)

            runtime = _build_runtime("ETH/USD")
            runtime.update_candle(_build_candle(T0_NS))
            runtime.update_order_book(_build_book(T0_NS))
            runtime.record_observed_signal("sector_rotation", stale_signal)
            runtime.record_observed_vote("sector_rotation", stale_vote)

            loop = _build_test_loop(broker_mode="paper")
            dispatch = _bind(loop, "_dispatch_fusion")
            dispatch(
                "ETH/USD",
                runtime,
                fusion=_build_fusion_decision(T0_NS),
                exchange_ts_ns=T0_NS,
            )

            loop.decision_compiler.compile.assert_not_called()
            loop.execution_engine.submit_signal.assert_not_called()

    def test_live_broker_mode_blocks_paper_dispatch_even_when_same_clock(self):
        """
        Paper-only proving lane. Even with a perfectly same-clock observed
        pair, broker_mode != "paper" must hard-block the SR consume gate so
        no signal ever reaches ExecutionEngine.
        """
        with ReplayTimeContext(T0_NS):
            signal = _build_strategy_signal(T0_NS, side="buy")
            vote = _build_vote_via_real_adapter(signal, T0_NS)

            runtime = _build_runtime("ETH/USD")
            runtime.update_candle(_build_candle(T0_NS))
            runtime.update_order_book(_build_book(T0_NS))
            runtime.record_observed_signal("sector_rotation", signal)
            runtime.record_observed_vote("sector_rotation", vote)

            loop = _build_test_loop(broker_mode="live")
            dispatch = _bind(loop, "_dispatch_fusion")
            dispatch(
                "ETH/USD",
                runtime,
                fusion=_build_fusion_decision(T0_NS),
                exchange_ts_ns=T0_NS,
            )

            loop.decision_compiler.compile.assert_not_called()
            loop.execution_engine.submit_signal.assert_not_called()

    def test_missing_observed_pair_blocks_fill(self):
        """
        Same-clock candle and book ingested, but no observed (signal, vote)
        recorded. The consume gate returns (None, None); no fill possible.
        """
        with ReplayTimeContext(T0_NS):
            runtime = _build_runtime("ETH/USD")
            runtime.update_candle(_build_candle(T0_NS))
            runtime.update_order_book(_build_book(T0_NS))
            # NB: no record_observed_*

            loop = _build_test_loop(broker_mode="paper")
            dispatch = _bind(loop, "_dispatch_fusion")
            dispatch(
                "ETH/USD",
                runtime,
                fusion=_build_fusion_decision(T0_NS),
                exchange_ts_ns=T0_NS,
            )

            loop.decision_compiler.compile.assert_not_called()
            loop.execution_engine.submit_signal.assert_not_called()

    def test_fresh_router_holds_no_execution_reports(self):
        """
        OrderRouter must not produce a fill spontaneously. A fresh
        paper-mode router instance with no submitted order has no execution
        reports — the same invariant the deterministic harness pins, repeated
        here so the same-clock harness contains its own no-fake-success
        anchor.
        """
        router = OrderRouter(paper_mode=True)
        broker = router._paper_broker  # type: ignore[attr-defined]
        assert hasattr(broker, "execution_reports")
        assert len(broker.execution_reports) == 0


# =============================================================================
# 4. Safety invariants — explicit assertions that the harness itself does not
#    leak live mode, attack mode, or fake artefacts. Pinned for future
#    regression catching.
# =============================================================================


class TestSameClockSafetyInvariants:

    def test_no_live_mode_env_leak(self):
        """
        The test environment must not have LIVE_MODE=true active. If it does,
        the harness should fail loudly rather than silently exercise a path
        that could promote a fill.
        """
        live_mode = os.environ.get("LIVE_MODE", "").strip().lower()
        assert live_mode != "true", (
            "LIVE_MODE=true detected — same-clock harness refuses to run under live mode"
        )

    def test_attack_mode_remains_false_through_dispatch(self):
        """
        Fusion is built with attack_mode=False; the real _dispatch_fusion
        must propagate is_attack=False to ExecutionEngine.submit_signal. This
        catches any future regression that accidentally promotes a same-clock
        candidate through the attack lane.
        """
        with ReplayTimeContext(T0_NS):
            signal = _build_strategy_signal(T0_NS)
            vote = _build_vote_via_real_adapter(signal, T0_NS)
            runtime = _build_runtime("ETH/USD")
            runtime.update_candle(_build_candle(T0_NS))
            runtime.update_order_book(_build_book(T0_NS))
            runtime.record_observed_signal("sector_rotation", signal)
            runtime.record_observed_vote("sector_rotation", vote)

            captured: List[dict] = []
            loop = _build_test_loop(broker_mode="paper")
            loop.execution_engine.submit_signal = MagicMock(
                side_effect=lambda signal, current_price, is_attack:
                    captured.append({"is_attack": is_attack}) or True
            )

            fusion = _build_fusion_decision(T0_NS)
            assert fusion.attack_mode is False

            dispatch = _bind(loop, "_dispatch_fusion")
            dispatch("ETH/USD", runtime, fusion=fusion, exchange_ts_ns=T0_NS)

            assert len(captured) == 1
            assert captured[0]["is_attack"] is False

    def test_attack_mode_flag_and_aggression_metadata_remain_passive_in_submit_path(self):
        """
        Even if fusion.attack_mode=True and aggression metadata is present on
        the observed signal, the live dispatch seam must still submit with
        is_attack=False and preserve the existing paper harness behavior.
        """
        with ReplayTimeContext(T0_NS):
            signal = _build_strategy_signal(T0_NS, side="buy", quantity=0.5)
            signal.metadata = {
                "aggression_context": {
                    "attack_mode_hint": True,
                    "aggression_tier": "elevated",
                    "metadata_only": True,
                },
                "aggression_snapshot_id": "bundle9a-same-clock-1",
            }
            vote = _build_vote_via_real_adapter(signal, T0_NS)
            runtime = _build_runtime("ETH/USD")
            runtime.update_candle(_build_candle(T0_NS, close=2500.0))
            runtime.update_order_book(_build_book(T0_NS, mid=2500.0))
            runtime.record_observed_signal("sector_rotation", signal)
            runtime.record_observed_vote("sector_rotation", vote)

            captured: List[dict] = []
            loop = _build_test_loop(broker_mode="paper")
            loop.execution_engine.submit_signal = MagicMock(
                side_effect=lambda signal, current_price, is_attack:
                    captured.append(
                        {
                            "signal": signal,
                            "current_price": current_price,
                            "is_attack": is_attack,
                        }
                    ) or True
            )

            fusion = types.SimpleNamespace(
                exchange_ts_ns=T0_NS,
                attack_mode=True,
                preferred_sleeve="shadow_front",
                sector_rotation_eligible=True,
                shadow_front_eligible=True,
            )
            dispatch = _bind(loop, "_dispatch_fusion")
            dispatch("ETH/USD", runtime, fusion=fusion, exchange_ts_ns=T0_NS)

            assert len(captured) == 1
            assert captured[0]["is_attack"] is False
            assert captured[0]["signal"].metadata["aggression_snapshot_id"] == "bundle9a-same-clock-1"

            order = _strategy_signal_to_order_request(captured[0]["signal"], receive_ts_ns=T0_NS)
            router = OrderRouter(paper_mode=True)
            fill = router.submit_order(order)
            assert fill is not None
            assert isinstance(fill, OrderFill)

    def test_real_adapter_metadata_flags_execution_candidate_not_attack(self):
        """
        The production adapter must mark the vote as execution_candidate=True
        (admissible into the dispatch chain) WITHOUT promoting any attack-mode
        flag. Pin this explicitly so a future adapter change cannot silently
        flip attack semantics inside same-clock paper proofs.
        """
        signal = _build_strategy_signal(T0_NS)
        vote = _build_vote_via_real_adapter(signal, T0_NS)
        meta = vote.metadata or {}
        # Council metadata key conventions are pinned by council_metadata
        # builder; the key we pin here is the one strategy_vote_adapters sets
        # explicitly: execution_candidate. We assert it is True and that no
        # attack-mode key has been silently smuggled through metadata.
        assert meta.get("execution_candidate") is True
        for key in meta.keys():
            assert "attack" not in key.lower(), (
                f"vote metadata leaked an attack-related key: {key}"
            )

    def test_replay_context_does_not_leak_after_test_module(self):
        """
        After every test that uses ReplayTimeContext, replay mode must clear.
        This guards against a future test forgetting to use the context
        manager and silently freezing now_ns() across the suite.
        """
        # If a prior test in this module leaked replay mode, this fails.
        assert not is_replay_mode(), (
            "replay mode leaked across tests in same-clock harness; ReplayTimeContext "
            "must always be used as a context manager"
        )
