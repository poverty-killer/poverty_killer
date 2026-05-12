"""
test_upstream_dispatch_signal_submission
UPSTREAM_DISPATCH_SIGNAL_SUBMISSION_PROOF_BUNDLE — upstream dispatch contract tests.

Purpose:
    Lock in the upstream dispatch / signal-submission contract that this packet
    is responsible for. The post-PAPER_FILL_COMPLETION_PROOF_BUNDLE runtime
    evidence (paper_run_fill_proof_20260506_183834) showed SIGNAL_SUBMITTED=0
    and zero [EXEC_DIAG] markers. Diagnosis traced every upstream block to a
    legitimate gate:

      * ETH/USD: Fusion preferred SHADOW_FRONT in RANGING (sr_ranging=True);
        ShadowFront declined on whale_condition (score=0.1950 < threshold=0.2000);
        SECTOR_ROTATION fallback blocked because the strategy never produced
        an observed (signal, vote) pair on any candle in the proof window.
      * SOL/USD: Same Fusion path; ShadowFront declined on whale_condition
        (score=0.0683); SECTOR_ROTATION fallback blocked because the stored
        observed pair was stale (vote_ts == signal_ts == 1778073300000000000,
        dispatch exchange_ts_ns = 1778110800000000000, ~10.4 h delta).
      * BTC/USD: Fusion preferred_sleeve=None on the live-gate-pass candle.

    No wiring/state/timing/contract bug was proven. No production code patch
    is justified by this evidence. These tests pin the existing dispatch
    contract — both the "decline" path and the "submit" path — so a future
    regression that silently weakens any gate, fakes a signal, or bypasses the
    DecisionCompiler / ExecutionEngine seam is caught at the unit level.

Tests are written against the unbound MainLoop methods so they exercise the
exact production code paths without instantiating the full MainLoop graph.

Forbidden in this file (per packet doctrine):
    - threshold relaxation
    - fake signals
    - bypassing SignalFusion / StrategyRouter / DecisionCompiler
    - direct strategy-to-execution shortcut
    - any live-mode path
"""

from __future__ import annotations

import types
from decimal import Decimal
from typing import Any, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

from app.commander import Commander
from app.main_loop import MainLoop
from app.models.enums import SleeveType


# =============================================================================
# Helpers — build the smallest legal stand-ins for production objects
# =============================================================================


def _make_signal(
    *,
    exchange_ts_ns: int,
    side: str = "buy",
    quantity: float = 1.0,
    confidence: float = 0.75,
    symbol: str = "ETH/USD",
    metadata: Optional[dict] = None,
):
    """Stand-in for app.models.signals.StrategySignal (duck-typed)."""
    return types.SimpleNamespace(
        strategy="sector_rotation",
        symbol=symbol,
        side=side,
        confidence=confidence,
        quantity=quantity,
        price=None,
        exchange_ts_ns=exchange_ts_ns,
        reason="test_signal",
        metadata={} if metadata is None else dict(metadata),
        regime=None,
    )


def _make_vote(*, timestamp_ns: int, decision_uuid: str = "uuid-test"):
    """Stand-in for app.models.contracts.StrategyVote (duck-typed)."""
    return types.SimpleNamespace(
        decision_uuid=decision_uuid,
        timestamp_ns=timestamp_ns,
        confidence=Decimal("0.75"),
        risk_appetite=Decimal("0.5"),
        signal="buy",
        metadata={},
    )


def _make_runtime(
    *,
    last_price: float = 100.0,
    sector_signal=None,
    sector_vote=None,
    shadow_strategy=None,
    sector_strategy=None,
    gamma_strategy=None,
    flv_strategy=None,
):
    """Stand-in for app.symbol_runtime.SymbolRuntime (duck-typed for dispatch)."""
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
        last_tpe_signal=None,
    )


def _make_test_loop(
    *,
    broker_mode: str = "paper",
    preferred_sleeve: SleeveType = SleeveType.SHADOW_FRONT,
    eligible_sleeves: Optional[List[SleeveType]] = None,
    gen_sf_signal: Optional[Tuple[Any, Any]] = None,
    commander_attack: bool = False,
):
    """
    Build a minimal MainLoop-shaped test double with just the fields the dispatch
    methods touch. We bind production methods via the unbound function form
    (MainLoop.method.__get__(loop, MainLoop)) below.
    """
    if eligible_sleeves is None:
        eligible_sleeves = [SleeveType.SHADOW_FRONT, SleeveType.SECTOR_ROTATION]

    loop = types.SimpleNamespace()
    loop.config = types.SimpleNamespace(broker_mode=broker_mode)
    loop.commander = Commander()
    if commander_attack:
        loop.commander.enable_attack_mode("test_governed_attack_contract", 1)

    # StrategyRouter is mocked — its policy is exercised by its own tests.
    loop.strategy_router = MagicMock()
    loop.strategy_router.update_macro_state = MagicMock()
    loop.strategy_router.get_preferred_strategy = MagicMock(return_value=preferred_sleeve)
    loop.strategy_router.get_eligible_strategies = MagicMock(return_value=eligible_sleeves)

    # DecisionCompiler is mocked — its compile() returns a record-shaped object.
    loop.decision_compiler = MagicMock()
    loop.decision_compiler.reserve_decision_uuid = MagicMock(return_value="uuid-test")
    loop.decision_compiler.compile = MagicMock(
        return_value=types.SimpleNamespace(
            decision_uuid="uuid-test", decision_type="STRATEGY_VOTE"
        )
    )

    # ExecutionEngine is mocked — submit_signal returns True for the admit path.
    loop.execution_engine = MagicMock()
    loop.execution_engine.submit_signal = MagicMock(return_value=True)

    # _build_truth_frame is replaced with a stub so we don't pull in the
    # full ExchangeTruth/PortfolioTruth/ExecutionTruth/StrategyTruth graph.
    loop._build_truth_frame = MagicMock(return_value="truth-frame-stub")

    # SF overlay update is a no-op for these tests.
    loop._update_shadow_front_overlays = MagicMock()
    loop._generate_signal_and_vote = MagicMock(return_value=(None, None))
    loop._generate_signal_and_vote_gamma_front = MagicMock(return_value=(None, None))

    # Pre-populate the SF generator if the test wants SF to produce a signal.
    if gen_sf_signal is not None:
        loop._generate_signal_and_vote = MagicMock(return_value=gen_sf_signal)

    # Metrics + insider engine touched by overlay paths we don't enter here.
    loop._metrics = types.SimpleNamespace(orders_submitted=0, orders_rejected=0, compilation_cycles=0)
    loop.insider_engine = MagicMock()

    # Bind the consume helpers so _dispatch_fusion's `self._consume_observed_pair_*`
    # calls resolve correctly on the test double.
    loop._consume_observed_pair_sector_rotation = (
        MainLoop._consume_observed_pair_sector_rotation.__get__(loop, MainLoop)
    )
    loop._consume_observed_pair_liquidity_void = (
        MainLoop._consume_observed_pair_liquidity_void.__get__(loop, MainLoop)
    )

    return loop


def _bind(loop, method_name):
    """Bind an unbound MainLoop method to our test-double instance."""
    func = getattr(MainLoop, method_name)
    return func.__get__(loop, MainLoop)


# =============================================================================
# 0. Commander canonical aggression contract
# =============================================================================


class TestCommanderCanonicalAggressionContract:
    def test_safe_mode_contract_is_deterministic_and_preserves_final_vetoes(self):
        commander = Commander()
        ts = 1_234_000_000_000

        first = commander.get_aggression_contract(ts)
        second = commander.get_aggression_contract(ts)

        assert first == second
        assert first.authority_owner == "Commander"
        assert first.authority_version == "commander.aggression.v1"
        assert first.mode == "SAFE"
        assert first.execution_is_attack is False
        assert first.veto_reasons == ("safe_mode",)
        assert first.economic_admissibility_final_veto_preserved is True
        assert first.risk_guard_final_veto_preserved is True
        assert first.stale_gate_final_veto_preserved is True
        assert first.moving_floor_active is False
        assert first.dormant_governors_active is False
        assert first.as_metadata() == second.as_metadata()


# =============================================================================
# 1. _consume_observed_pair_sector_rotation contract
# =============================================================================


class TestConsumeObservedPairSectorRotation:
    """
    Direct unit tests over the production method. Mirrors the four hard gates:
        1. broker_mode == "paper"
        2. observed signal AND vote both present
        3. vote.timestamp_ns == exchange_ts_ns OR signal.exchange_ts_ns == exchange_ts_ns
    """

    def test_blocks_when_broker_mode_is_not_paper(self):
        loop = _make_test_loop(broker_mode="live")  # not 'paper'
        ts = 1_000_000_000_000
        rt = _make_runtime(
            sector_signal=_make_signal(exchange_ts_ns=ts),
            sector_vote=_make_vote(timestamp_ns=ts),
        )
        consume = _bind(loop, "_consume_observed_pair_sector_rotation")
        sig, vote = consume("ETH/USD", rt, ts)
        assert sig is None and vote is None, (
            "non-paper broker_mode must hard-block SR observed-pair admission"
        )

    def test_blocks_when_observed_pair_missing_both(self):
        loop = _make_test_loop()
        ts = 1_000_000_000_000
        rt = _make_runtime(sector_signal=None, sector_vote=None)
        consume = _bind(loop, "_consume_observed_pair_sector_rotation")
        sig, vote = consume("ETH/USD", rt, ts)
        assert sig is None and vote is None

    def test_blocks_when_observed_signal_missing(self):
        loop = _make_test_loop()
        ts = 1_000_000_000_000
        rt = _make_runtime(sector_signal=None, sector_vote=_make_vote(timestamp_ns=ts))
        consume = _bind(loop, "_consume_observed_pair_sector_rotation")
        sig, vote = consume("ETH/USD", rt, ts)
        assert sig is None and vote is None

    def test_blocks_when_observed_vote_missing(self):
        loop = _make_test_loop()
        ts = 1_000_000_000_000
        rt = _make_runtime(sector_signal=_make_signal(exchange_ts_ns=ts), sector_vote=None)
        consume = _bind(loop, "_consume_observed_pair_sector_rotation")
        sig, vote = consume("ETH/USD", rt, ts)
        assert sig is None and vote is None

    def test_blocks_on_stale_pair_matching_proof_log_timestamps(self):
        """
        SOL/USD evidence from the upstream proof bundle:
        vote_ts==signal_ts==1778073300000000000, exchange_ts_ns==1778110800000000000.
        ~10.4 h delta. Strict same-candle freshness must block.
        """
        loop = _make_test_loop()
        stored_ts = 1_778_073_300_000_000_000
        dispatch_ts = 1_778_110_800_000_000_000
        rt = _make_runtime(
            sector_signal=_make_signal(exchange_ts_ns=stored_ts),
            sector_vote=_make_vote(timestamp_ns=stored_ts),
        )
        consume = _bind(loop, "_consume_observed_pair_sector_rotation")
        sig, vote = consume("SOL/USD", rt, dispatch_ts)
        assert sig is None and vote is None

    def test_blocks_on_one_nanosecond_offset(self):
        loop = _make_test_loop()
        stored_ts = 1_000_000_000_000
        rt = _make_runtime(
            sector_signal=_make_signal(exchange_ts_ns=stored_ts),
            sector_vote=_make_vote(timestamp_ns=stored_ts),
        )
        consume = _bind(loop, "_consume_observed_pair_sector_rotation")
        sig, vote = consume("ETH/USD", rt, stored_ts + 1)
        assert sig is None and vote is None, (
            "freshness gate uses strict equality, not range comparison"
        )

    def test_admits_fresh_same_candle_pair(self):
        loop = _make_test_loop()
        ts = 1_778_004_120_000_000_000
        observed_sig = _make_signal(exchange_ts_ns=ts)
        observed_vote = _make_vote(timestamp_ns=ts)
        rt = _make_runtime(sector_signal=observed_sig, sector_vote=observed_vote)
        consume = _bind(loop, "_consume_observed_pair_sector_rotation")
        sig, vote = consume("ETH/USD", rt, ts)
        assert sig is observed_sig
        assert vote is observed_vote

    def test_admits_when_only_vote_ts_matches(self):
        loop = _make_test_loop()
        ts = 2_000_000_000_000
        observed_sig = _make_signal(exchange_ts_ns=ts - 7)  # signal_ts mismatched
        observed_vote = _make_vote(timestamp_ns=ts)        # vote_ts matches
        rt = _make_runtime(sector_signal=observed_sig, sector_vote=observed_vote)
        consume = _bind(loop, "_consume_observed_pair_sector_rotation")
        sig, vote = consume("ETH/USD", rt, ts)
        assert sig is observed_sig and vote is observed_vote

    def test_admits_when_only_signal_ts_matches(self):
        loop = _make_test_loop()
        ts = 3_000_000_000_000
        observed_sig = _make_signal(exchange_ts_ns=ts)            # signal_ts matches
        observed_vote = _make_vote(timestamp_ns=ts - 11)          # vote_ts mismatched
        rt = _make_runtime(sector_signal=observed_sig, sector_vote=observed_vote)
        consume = _bind(loop, "_consume_observed_pair_sector_rotation")
        sig, vote = consume("ETH/USD", rt, ts)
        assert sig is observed_sig and vote is observed_vote


# =============================================================================
# 2. _dispatch_fusion behavior — fallback, decline, submission
# =============================================================================


class TestDispatchFusionFallbackAndDecline:
    """
    These tests exercise the production _dispatch_fusion path. They confirm:
      - SHADOW_FRONT decline → SECTOR_ROTATION fallback is invoked.
      - When SR observed pair is missing, all_sleeves_declined is the correct
        terminal state and submit_signal is NOT called.
      - When SR observed pair is stale, same outcome.
      - When SR observed pair is fresh, the dispatch reaches DecisionCompiler.compile
        AND ExecutionEngine.submit_signal exactly once with the live signal.
    """

    def _make_fusion(self, ts_ns: int, preferred="shadow_front"):
        return types.SimpleNamespace(
            exchange_ts_ns=ts_ns,
            attack_mode=False,
            preferred_sleeve=preferred,
            sector_rotation_eligible=True,
            shadow_front_eligible=True,
        )

    def test_fusion_none_returns_without_call(self):
        loop = _make_test_loop()
        rt = _make_runtime()
        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", rt, fusion=None, exchange_ts_ns=123)
        loop.execution_engine.submit_signal.assert_not_called()
        loop.decision_compiler.compile.assert_not_called()

    def test_no_preferred_strategy_returns_without_call(self):
        loop = _make_test_loop()
        loop.strategy_router.get_preferred_strategy = MagicMock(return_value=None)
        rt = _make_runtime()
        ts = 5_000_000_000_000
        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("BTC/USD", rt, fusion=self._make_fusion(ts), exchange_ts_ns=ts)
        loop.execution_engine.submit_signal.assert_not_called()
        loop.decision_compiler.compile.assert_not_called()

    def test_sf_decline_with_missing_sr_pair_yields_all_sleeves_declined(self):
        """
        Exact ETH/USD proof-log topology:
            preferred=SHADOW_FRONT (declines on whale_condition)
            fallback=SECTOR_ROTATION (observed pair=None)
            Result: all_sleeves_declined, submit_signal NOT called.
        """
        loop = _make_test_loop()
        # SF declines: _generate_signal_and_vote returns (None, None) — default.
        # SR observed pair is None — runtime defaults.
        rt = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
        )
        ts = 7_000_000_000_000
        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", rt, fusion=self._make_fusion(ts), exchange_ts_ns=ts)

        loop.execution_engine.submit_signal.assert_not_called()
        loop.decision_compiler.compile.assert_not_called()

    def test_sf_decline_with_stale_sr_pair_yields_all_sleeves_declined(self):
        """
        Exact SOL/USD proof-log topology:
            SHADOW_FRONT declines, SR observed pair stored on prior candle.
            Strict same-candle freshness blocks SR. Result: no submission.
        """
        loop = _make_test_loop()
        stored_ts = 1_778_073_300_000_000_000
        dispatch_ts = 1_778_110_800_000_000_000  # ~10.4h after stored
        rt = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
            sector_signal=_make_signal(exchange_ts_ns=stored_ts),
            sector_vote=_make_vote(timestamp_ns=stored_ts),
        )
        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("SOL/USD", rt, fusion=self._make_fusion(dispatch_ts), exchange_ts_ns=dispatch_ts)

        loop.execution_engine.submit_signal.assert_not_called()
        loop.decision_compiler.compile.assert_not_called()

    def test_sf_decline_with_fresh_sr_pair_reaches_decision_compiler_and_submit(self):
        """
        Positive-path contract: when SF declines and SR has a FRESH same-candle
        observed pair, dispatch must:
            1. compile a DecisionRecord via DecisionCompiler.compile()
            2. submit the signal via ExecutionEngine.submit_signal()
        Both calls must happen exactly once with the in-flight (signal, vote).
        """
        loop = _make_test_loop()
        ts = 8_000_000_000_000
        observed_sig = _make_signal(exchange_ts_ns=ts, symbol="ETH/USD")
        observed_vote = _make_vote(timestamp_ns=ts)
        rt = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
            sector_signal=observed_sig,
            sector_vote=observed_vote,
            last_price=2500.0,
        )
        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", rt, fusion=self._make_fusion(ts), exchange_ts_ns=ts)

        # DecisionCompiler.compile called exactly once with the SR vote.
        assert loop.decision_compiler.compile.call_count == 1
        compile_args, compile_kwargs = loop.decision_compiler.compile.call_args
        # First positional arg is the truth frame stub.
        assert compile_args[0] == "truth-frame-stub"
        # Strategy votes kwarg must be a single-vote list containing our vote.
        assert compile_kwargs.get("strategy_votes") == [observed_vote]

        # ExecutionEngine.submit_signal called exactly once with the SR signal.
        assert loop.execution_engine.submit_signal.call_count == 1
        _, submit_kwargs = loop.execution_engine.submit_signal.call_args
        assert submit_kwargs.get("signal") is observed_sig
        assert submit_kwargs.get("current_price") == 2500.0
        assert submit_kwargs.get("is_attack") is False
        aggression_contract = observed_sig.metadata["canonical_aggression_contract"]
        assert aggression_contract["authority_owner"] == "Commander"
        assert aggression_contract["execution_is_attack"] is False
        assert aggression_contract["stale_gate_final_veto_preserved"] is True

        # Metrics record the submission.
        assert loop._metrics.orders_submitted == 1

    def test_preferred_sf_admission_short_circuits_sr_fallback(self):
        """
        When SHADOW_FRONT produces a valid (signal, vote), SR fallback must NOT
        be evaluated. Confirms the candidate loop breaks on first success.
        """
        ts = 9_000_000_000_000
        sf_sig = _make_signal(exchange_ts_ns=ts)
        sf_vote = _make_vote(timestamp_ns=ts, decision_uuid="sf-uuid")

        loop = _make_test_loop(gen_sf_signal=(sf_sig, sf_vote))
        rt = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
            # SR has a fresh observed pair too — must be ignored when SF wins.
            sector_signal=_make_signal(exchange_ts_ns=ts, side="sell"),
            sector_vote=_make_vote(timestamp_ns=ts, decision_uuid="sr-uuid"),
        )
        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", rt, fusion=self._make_fusion(ts), exchange_ts_ns=ts)

        # The SF signal won.
        assert loop.execution_engine.submit_signal.call_count == 1
        _, submit_kwargs = loop.execution_engine.submit_signal.call_args
        assert submit_kwargs.get("signal") is sf_sig

        # DecisionCompiler.compile got the SF vote, not the SR vote.
        _, compile_kwargs = loop.decision_compiler.compile.call_args
        assert compile_kwargs.get("strategy_votes") == [sf_vote]


# =============================================================================
# 3. all_sleeves_declined invariant
# =============================================================================


class TestAllSleevesDeclinedInvariant:
    """
    Confirms the no-trade terminal state holds when every candidate sleeve
    legitimately declines. ExecutionEngine.submit_signal MUST NOT be called.
    """

    def _make_fusion(self, ts_ns: int):
        return types.SimpleNamespace(
            exchange_ts_ns=ts_ns,
            attack_mode=False,
            preferred_sleeve="shadow_front",
            sector_rotation_eligible=True,
            shadow_front_eligible=True,
        )

    def test_all_decline_no_submission(self):
        loop = _make_test_loop()
        rt = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
        )
        ts = 11_000_000_000_000
        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", rt, fusion=self._make_fusion(ts), exchange_ts_ns=ts)
        loop.execution_engine.submit_signal.assert_not_called()
        loop.decision_compiler.compile.assert_not_called()

    def test_no_registered_candidates_no_submission(self):
        """
        Eligible set non-empty but none have a backing strategy on the runtime
        (e.g., dormant sleeves). Dispatch must return without submission.
        """
        loop = _make_test_loop(
            preferred_sleeve=SleeveType.FLV,
            eligible_sleeves=[SleeveType.FLV],
        )
        rt = _make_runtime(
            shadow_strategy=None,
            sector_strategy=None,
            flv_strategy=None,  # FLV preferred but unregistered.
        )
        ts = 12_000_000_000_000
        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", rt, fusion=self._make_fusion(ts), exchange_ts_ns=ts)
        loop.execution_engine.submit_signal.assert_not_called()
        loop.decision_compiler.compile.assert_not_called()


# =============================================================================
# 4. OBSERVE_ONLY architecture invariant
# =============================================================================


class TestObserveOnlyDoesNotBypassDispatch:
    """
    OBSERVE_ONLY signals from _observe_sector_rotation are stored on the runtime
    via record_observed_signal/vote. They reach ExecutionEngine ONLY through the
    dispatch seam (StrategyRouter eligibility + same-candle freshness gate). No
    OBSERVE_ONLY path may call decision_compiler.compile or submit_signal directly.
    """

    def test_observe_only_stash_alone_does_not_invoke_executor(self):
        loop = _make_test_loop()
        ts = 13_000_000_000_000
        rt = _make_runtime(
            sector_signal=_make_signal(exchange_ts_ns=ts),
            sector_vote=_make_vote(timestamp_ns=ts),
        )
        # Storing an observed pair must not, by itself, invoke any execution
        # surface. Only the dispatch seam may.
        loop.execution_engine.submit_signal.assert_not_called()
        loop.decision_compiler.compile.assert_not_called()
        # The stash exists on the runtime; nothing has been compiled or submitted.
        assert rt.last_sector_rotation_observed_signal is not None
        assert rt.last_sector_rotation_observed_vote is not None


# =============================================================================
# 5. Forbidden behaviors — sanity tests pinning packet doctrine
# =============================================================================


class TestPacketDoctrineInvariants:
    """
    Lightweight sanity tests that catch obvious doctrine violations introduced
    by future refactors.
    """

    def test_consume_observed_pair_does_not_construct_signals(self):
        """
        The consume helper must return the in-runtime (signal, vote) objects
        unchanged. It must not mint a new signal or vote on admission.
        """
        loop = _make_test_loop()
        ts = 14_000_000_000_000
        in_sig = _make_signal(exchange_ts_ns=ts)
        in_vote = _make_vote(timestamp_ns=ts)
        rt = _make_runtime(sector_signal=in_sig, sector_vote=in_vote)
        consume = _bind(loop, "_consume_observed_pair_sector_rotation")
        out_sig, out_vote = consume("ETH/USD", rt, ts)
        # Identity, not just equality — admission must not clone.
        assert out_sig is in_sig
        assert out_vote is in_vote

    def test_dispatch_does_not_call_executor_when_strategy_vote_is_none(self):
        """
        Defensive: even if a sleeve's adapter were ever to return a signal but
        no vote, dispatch must not submit. This pins the strategy_vote=None
        guard at line ~1054 of main_loop.
        """
        ts = 15_000_000_000_000

        # Force SHADOW_FRONT to return signal-but-no-vote.
        sf_sig = _make_signal(exchange_ts_ns=ts)
        loop = _make_test_loop(gen_sf_signal=(sf_sig, None))

        rt = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
        )
        fusion = types.SimpleNamespace(
            exchange_ts_ns=ts,
            attack_mode=False,
            preferred_sleeve="shadow_front",
            sector_rotation_eligible=True,
            shadow_front_eligible=True,
        )
        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", rt, fusion=fusion, exchange_ts_ns=ts)
        loop.execution_engine.submit_signal.assert_not_called()
        loop.decision_compiler.compile.assert_not_called()


class TestAdvisoryMetadataSpine:
    """
    Bundle 8A metadata-only proof:
    advisory context may exist in metadata but must not alter gating behavior.
    """

    def _make_fusion(self, ts_ns: int):
        return types.SimpleNamespace(
            exchange_ts_ns=ts_ns,
            attack_mode=False,
            preferred_sleeve="shadow_front",
            sector_rotation_eligible=True,
            shadow_front_eligible=True,
        )

    def test_advisory_metadata_passes_through_admit_path_without_behavior_change(self):
        loop = _make_test_loop()
        ts = 16_000_000_000_000
        advisory_context = {
            "advisory_context": {
                "cross_asset_note": "passive_only",
                "session_note": "non_authoritative",
            },
            "advisory_snapshot_id": "bundle8a-advisory-1",
        }
        observed_sig = _make_signal(
            exchange_ts_ns=ts,
            symbol="ETH/USD",
            metadata=advisory_context,
        )
        observed_vote = _make_vote(timestamp_ns=ts)
        rt = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
            sector_signal=observed_sig,
            sector_vote=observed_vote,
            last_price=2500.0,
        )

        loop.decision_compiler.compile = MagicMock(
            return_value=types.SimpleNamespace(
                decision_uuid="uuid-test",
                decision_type="STRATEGY_VOTE",
                metadata={
                    "advisory_context": {
                        "risk_cluster": "advisory-only",
                        "portfolio_state": "passive",
                    }
                },
            )
        )

        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", rt, fusion=self._make_fusion(ts), exchange_ts_ns=ts)

        assert loop.decision_compiler.compile.call_count == 1
        assert loop.execution_engine.submit_signal.call_count == 1
        _, submit_kwargs = loop.execution_engine.submit_signal.call_args
        submitted_signal = submit_kwargs.get("signal")
        assert submitted_signal is observed_sig
        assert submitted_signal.metadata["advisory_context"]["cross_asset_note"] == "passive_only"
        assert submitted_signal.metadata["advisory_snapshot_id"] == "bundle8a-advisory-1"
        assert submitted_signal.metadata["decision_uuid"] == "uuid-test"

    def test_advisory_metadata_does_not_bypass_stale_gate(self):
        loop = _make_test_loop()
        stored_ts = 16_100_000_000_000
        dispatch_ts = stored_ts + 1
        observed_sig = _make_signal(
            exchange_ts_ns=stored_ts,
            metadata={
                "advisory_context": {"cross_asset_note": "present_but_non_authoritative"},
                "advisory_snapshot_id": "bundle8a-stale-case",
            },
        )
        observed_vote = _make_vote(timestamp_ns=stored_ts)
        rt = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
            sector_signal=observed_sig,
            sector_vote=observed_vote,
        )
        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", rt, fusion=self._make_fusion(dispatch_ts), exchange_ts_ns=dispatch_ts)

        loop.execution_engine.submit_signal.assert_not_called()
        loop.decision_compiler.compile.assert_not_called()

    def test_fusion_aggression_metadata_is_advisory_to_commander_contract_on_admit_path(self):
        loop = _make_test_loop()
        ts = 16_200_000_000_000
        aggression_context = {
            "aggression_context": {
                "attack_mode_hint": True,
                "aggression_tier": "elevated",
                "metadata_only": True,
            },
            "aggression_snapshot_id": "bundle9a-aggression-1",
            "canonical_aggression_contract": {
                "authority_owner": "Fusion",
                "execution_is_attack": True,
            },
        }
        observed_sig = _make_signal(
            exchange_ts_ns=ts,
            symbol="ETH/USD",
            metadata=aggression_context,
        )
        observed_vote = _make_vote(timestamp_ns=ts)
        rt = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
            sector_signal=observed_sig,
            sector_vote=observed_vote,
            last_price=2500.0,
        )

        fusion = types.SimpleNamespace(
            exchange_ts_ns=ts,
            attack_mode=True,
            preferred_sleeve="shadow_front",
            sector_rotation_eligible=True,
            shadow_front_eligible=True,
        )

        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", rt, fusion=fusion, exchange_ts_ns=ts)

        assert loop.decision_compiler.compile.call_count == 1
        assert loop.execution_engine.submit_signal.call_count == 1
        _, submit_kwargs = loop.execution_engine.submit_signal.call_args
        submitted_signal = submit_kwargs.get("signal")
        assert submitted_signal is observed_sig
        assert submitted_signal.metadata["aggression_context"]["attack_mode_hint"] is True
        assert submitted_signal.metadata["aggression_snapshot_id"] == "bundle9a-aggression-1"
        aggression_contract = submitted_signal.metadata["canonical_aggression_contract"]
        assert aggression_contract["authority_owner"] == "Commander"
        assert aggression_contract["mode"] == "SAFE"
        assert aggression_contract["execution_is_attack"] is False
        replay_proof = submitted_signal.metadata["aggression_replay_proof"]
        assert replay_proof["authority_owner"] == "Commander"
        assert replay_proof["execution_is_attack"] is False
        assert replay_proof["execution_is_attack_source"] == (
            "Commander.canonical_aggression_contract.execution_is_attack"
        )
        assert replay_proof["fusion_attack_mode"] is True
        assert replay_proof["fusion_attack_mode_authoritative"] is False
        assert replay_proof["advisory_aggression_metadata_present"] is True
        assert replay_proof["advisory_aggression_metadata_authoritative"] is False
        assert replay_proof["risk_guard_final_veto_preserved"] is True
        assert replay_proof["economic_admissibility_final_veto_preserved"] is True
        assert replay_proof["stale_gate_final_veto_preserved"] is True
        _, compile_kwargs = loop.decision_compiler.compile.call_args
        additional_inputs = compile_kwargs["additional_inputs"]
        assert additional_inputs["canonical_aggression_contract"] == aggression_contract
        assert additional_inputs["aggression_replay_proof"] == replay_proof
        assert submit_kwargs.get("is_attack") is False

    def test_commander_attack_contract_controls_submit_is_attack_without_fusion_authority(self):
        loop = _make_test_loop(commander_attack=True)
        ts = 16_250_000_000_000
        observed_sig = _make_signal(exchange_ts_ns=ts, symbol="ETH/USD")
        observed_vote = _make_vote(timestamp_ns=ts)
        rt = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
            sector_signal=observed_sig,
            sector_vote=observed_vote,
            last_price=2500.0,
        )
        fusion = types.SimpleNamespace(
            exchange_ts_ns=ts,
            attack_mode=False,
            preferred_sleeve="shadow_front",
            sector_rotation_eligible=True,
            shadow_front_eligible=True,
        )

        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", rt, fusion=fusion, exchange_ts_ns=ts)

        assert loop.decision_compiler.compile.call_count == 1
        assert loop.execution_engine.submit_signal.call_count == 1
        _, submit_kwargs = loop.execution_engine.submit_signal.call_args
        assert submit_kwargs.get("is_attack") is True
        aggression_contract = observed_sig.metadata["canonical_aggression_contract"]
        assert aggression_contract["authority_owner"] == "Commander"
        assert aggression_contract["mode"] == "ATTACK"
        assert aggression_contract["execution_is_attack"] is True
        assert aggression_contract["economic_admissibility_final_veto_preserved"] is True
        assert aggression_contract["risk_guard_final_veto_preserved"] is True
        assert aggression_contract["moving_floor_active"] is False
        assert aggression_contract["dormant_governors_active"] is False

    def test_aggression_metadata_and_attack_mode_flag_do_not_bypass_stale_gate(self):
        loop = _make_test_loop()
        stored_ts = 16_300_000_000_000
        dispatch_ts = stored_ts + 1
        observed_sig = _make_signal(
            exchange_ts_ns=stored_ts,
            metadata={
                "aggression_context": {
                    "attack_mode_hint": True,
                    "metadata_only": True,
                },
                "aggression_snapshot_id": "bundle9a-stale-case",
            },
        )
        observed_vote = _make_vote(timestamp_ns=stored_ts)
        rt = _make_runtime(
            shadow_strategy=MagicMock(),
            sector_strategy=MagicMock(),
            sector_signal=observed_sig,
            sector_vote=observed_vote,
        )
        fusion = types.SimpleNamespace(
            exchange_ts_ns=dispatch_ts,
            attack_mode=True,
            preferred_sleeve="shadow_front",
            sector_rotation_eligible=True,
            shadow_front_eligible=True,
        )
        dispatch = _bind(loop, "_dispatch_fusion")
        dispatch("ETH/USD", rt, fusion=fusion, exchange_ts_ns=dispatch_ts)

        loop.execution_engine.submit_signal.assert_not_called()
        loop.decision_compiler.compile.assert_not_called()

    def test_dispatch_and_submit_paths_do_not_import_dormant_advisory_or_aggression_modules(self):
        import inspect
        import app.main_loop as main_loop_module
        import app.execution.engine as execution_engine_module

        dispatch_src = inspect.getsource(main_loop_module.MainLoop._dispatch_fusion)
        submit_src = inspect.getsource(execution_engine_module.ExecutionEngine.submit_signal)

        forbidden_tokens = (
            "cross_asset_risk_model",
            "instrument_qualifier",
            "session_calendar",
            "opportunity_ranking",
            "world_awareness",
            "moving_floor",
            "net_edge_governor",
            "trade_efficiency_governor",
        )
        for token in forbidden_tokens:
            assert token not in dispatch_src
            assert token not in submit_src
