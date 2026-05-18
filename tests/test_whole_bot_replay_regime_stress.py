from __future__ import annotations

import inspect
import json
import os
import socket
import types
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.brain.recalibrator import Recalibrator
from app.brain.signal_fusion import SignalFusion
from app.brain.toxicity_engine import ToxicityAlert, ToxicityRegime
from app.brain.topological_engine import TopologicalSignal
from app.execution.live_read_only_adapter import ReadOnlyBrokerSnapshot
from app.models import Candle, DarkPoolPrint, OrderBookSnapshot, StrategySignal
from app.models.contracts import StrategyVote
from app.models.enums import (
    BookIntegrity,
    ExecutionMode,
    OrderSide,
    ReplayMode,
    SignalType,
    ToxicityLevel,
)
from app.models.instrument_profile import AssetClass, InstrumentProfile, InstrumentType
from app.portfolio.opportunity_ranking import OpportunityRanker
from app.risk.net_edge_governor import NetEdgeGovernor
from app.risk.trade_efficiency_governor import TradeEfficiencyGovernor
from app.strategies.adaptive_dc import AdaptiveDC, DCMarketTick
from app.strategies.gamma_front import GammaFrontStrategy
from app.strategies.hedging_flow import (
    HedgeMarketContext,
    HedgingFlow,
    PortfolioExposureSnapshot,
)
from app.strategies.liquidity_void import LiquidityVoidStrategy
from app.strategies.moving_floor import (
    FloorEventType,
    FloorMarketTick,
    TopologicalMovingFloor,
)
from app.strategies.sector_rotation import SectorRotationStrategy
from app.strategies.strategy_vote_adapters import (
    adapt_adaptive_dc_to_vote,
    adapt_gamma_front_to_vote,
    adapt_liquidity_void_to_vote,
    adapt_moving_floor_to_vote,
    adapt_sector_rotation_to_vote,
)
from app.symbol_runtime import SymbolRuntime
from app.utils.time_utils import now_ns


EXPECTED_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
ALLOWED_GET_PATHS = frozenset({"/v2/account", "/v2/positions", "/v2/orders", "/v2/clock"})
T0_NS = 1_777_948_800_000_000_000
MAX_SNAPSHOT_AGE_NS = 5_000_000_000


@dataclass(frozen=True)
class LocalReplayState:
    exposures: dict[str, Decimal] = field(default_factory=dict)
    local_open_order_ids: tuple[str, ...] = ()
    expected_currency: str = "USD"


@dataclass(frozen=True)
class ProtectiveIntent:
    module: str
    action: str
    reason: str
    requires_existing_position: bool = False
    requires_existing_exposure: bool = False


@dataclass(frozen=True)
class EntryEvidence:
    module: str
    symbol: str
    direction: str
    evidence_type: str
    governed_candidate: bool
    ranking_authority: bool = False
    execution_authority: bool = False
    duplicate_authority_claim: bool = False


@dataclass(frozen=True)
class EconomicsEvidence:
    fee_evidence_present: bool
    missing_fields: tuple[str, ...] = ()
    advisory_only: bool = True
    veto_enabled: bool = False
    pnl_claim: Decimal | None = None
    net_edge_claim: Decimal | None = None


@dataclass(frozen=True)
class IntelligenceEvidence:
    physical_ok: bool
    toxicity_ok: bool
    fusion_veto_reason: str | None = None


@dataclass(frozen=True)
class RecoveryEvidence:
    symbol_local: bool
    missing_contributor_state: bool = False
    fail_closed_reason: str | None = None
    live_auto_armed: bool = False
    duplicate_reservation_created: bool = False


@dataclass(frozen=True)
class TimingObservation:
    timing_points: tuple[str, ...]
    latency_metrics_absent: bool = True
    future_packet_reason: str = "decision_flow_latency_instrumentation_absent"


@dataclass(frozen=True)
class StressDecision:
    scenario: str
    classification: str
    eligible_for_governed_paper_decision_path: bool
    order_approved: bool
    execution_not_called: bool
    order_not_submitted: bool
    broker_mutation_absent: bool
    live_mode_absent: bool
    reason_codes: tuple[str, ...]
    selected_symbol: str | None
    candidate_count: int
    economics_veto_active: bool
    profitability_claim_made: bool
    latency_future_packet: bool


class SanitizedAlpacaReadOnlyClient:
    def __init__(self, base_url: str, key_id: str, secret_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._key_id = key_id
        self._secret_key = secret_key
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path: str, query: dict[str, str] | None = None) -> Any:
        self._validate_get(path, query)
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "APCA-API-KEY-ID": self._key_id,
                "APCA-API-SECRET-KEY": self._secret_key,
                "Accept": "application/json",
            },
        )
        self.calls.append(("GET", path))
        try:
            with urllib.request.urlopen(request, timeout=10.0) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            raise AssertionError(f"alpaca_read_only_http_error:{exc.code}:{path}") from None
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            pytest.skip(f"Alpaca PAPER read-only network unavailable: {type(exc).__name__}")

    def _validate_get(self, path: str, query: dict[str, str] | None) -> None:
        assert self.base_url == EXPECTED_PAPER_BASE_URL
        assert path in ALLOWED_GET_PATHS
        assert path != "/v2/orders" or (query or {}).get("status") == "open"
        blocked_fragments = ("submit", "cancel", "replace", "close", "liquidate")
        assert not any(fragment in path.lower() for fragment in blocked_fragments)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _snapshot(**overrides: Any) -> ReadOnlyBrokerSnapshot:
    fields = {
        "source": "alpaca",
        "environment": "paper",
        "account_id": "paper-account",
        "account_identity_status": "known",
        "balances": ({"currency": "USD", "cash": Decimal("1000"), "buying_power": Decimal("1000"), "equity": Decimal("1000")},),
        "positions": (),
        "open_orders": (),
        "recent_fills": (),
        "receive_ts_ns": T0_NS,
        "asof_ts_ns": T0_NS,
        "read_only": True,
        "mutation_allowed": False,
    }
    fields.update(overrides)
    return ReadOnlyBrokerSnapshot(**fields)


def _broker_reasons(snapshot: ReadOnlyBrokerSnapshot, local: LocalReplayState, *, now: int = T0_NS + 1) -> list[str]:
    reasons: list[str] = []
    if not snapshot.account_id or snapshot.account_identity_status != "known":
        reasons.append("broker_account_identity_missing")
    if snapshot.receive_ts_ns is None or snapshot.receive_ts_ns <= 0 or now - snapshot.receive_ts_ns > MAX_SNAPSHOT_AGE_NS:
        reasons.append("broker_snapshot_stale_or_missing")
    if not snapshot.read_only or snapshot.mutation_allowed:
        reasons.append("broker_not_read_only")
    balance = next((item for item in snapshot.balances if item.get("currency") == local.expected_currency), None)
    if balance is None:
        reasons.append("broker_currency_mismatch")
    for position in snapshot.positions:
        symbol = position.get("symbol")
        qty = position.get("quantity")
        if not symbol or qty is None:
            reasons.append("broker_position_invalid")
            continue
        if qty != Decimal("0") and local.exposures.get(symbol, Decimal("0")) != qty:
            reasons.append("broker_position_conflicts_with_local_flat")
    for order in snapshot.open_orders:
        client_order_id = order.get("client_order_id")
        broker_order_id = order.get("broker_order_id")
        if not client_order_id or not broker_order_id or client_order_id not in local.local_open_order_ids:
            reasons.append("broker_open_order_missing_local_mapping")
    return reasons


def evaluate_stress(
    *,
    scenario: str,
    broker_snapshot: ReadOnlyBrokerSnapshot,
    local: LocalReplayState,
    protective: tuple[ProtectiveIntent, ...],
    entries: tuple[EntryEvidence, ...],
    economics: EconomicsEvidence,
    intelligence: IntelligenceEvidence,
    recovery: RecoveryEvidence | None = None,
    timing: TimingObservation | None = None,
    now: int = T0_NS + 1,
) -> StressDecision:
    reasons = _broker_reasons(broker_snapshot, local, now=now)

    for intent in protective:
        if intent.action in {"block_new_entries", "freeze_trading", "operator_escalation"}:
            reasons.append(f"protective_{intent.action}")
        if intent.action in {"protective_exit_candidate", "hedge_candidate"}:
            has_position = bool(local.exposures)
            if intent.requires_existing_position and not has_position:
                reasons.append("protective_intent_requires_existing_position")
            if intent.requires_existing_exposure and not has_position:
                reasons.append("hedge_intent_requires_existing_exposure")

    if not intelligence.physical_ok:
        reasons.append("critical_physical_evidence_missing")
    if not intelligence.toxicity_ok:
        reasons.append("critical_toxicity_evidence_missing")
    if intelligence.fusion_veto_reason:
        reasons.append("intelligence_fusion_veto")

    executable_entries = [entry for entry in entries if entry.governed_candidate and not entry.execution_authority]
    if not executable_entries:
        reasons.append("entry_candidate_missing")
    directions = {entry.direction for entry in executable_entries}
    if len(directions) > 1:
        reasons.append("entry_contributor_conflict_unresolved")
    if any(entry.ranking_authority or entry.execution_authority or entry.duplicate_authority_claim for entry in entries):
        reasons.append("contributor_claimed_forbidden_authority")

    if not economics.advisory_only:
        reasons.append("economics_not_advisory")
    if economics.veto_enabled:
        reasons.append("economics_veto_forbidden")
    if economics.pnl_claim is not None or economics.net_edge_claim is not None:
        reasons.append("invented_economics_claim_forbidden")
    economics_gap = bool(economics.missing_fields)

    if recovery:
        if not recovery.symbol_local:
            reasons.append("recovery_symbol_locality_failed")
        if recovery.missing_contributor_state:
            reasons.append("missing_recovered_contributor_state_neutralized")
        if recovery.fail_closed_reason:
            reasons.append(recovery.fail_closed_reason)
        if recovery.live_auto_armed:
            reasons.append("recovery_auto_armed_live_forbidden")
        if recovery.duplicate_reservation_created:
            reasons.append("recovery_duplicate_reservation_forbidden")

    unique_reasons = tuple(dict.fromkeys(reasons))
    hard_veto = any(reason in unique_reasons for reason in ("critical_physical_evidence_missing", "critical_toxicity_evidence_missing", "intelligence_fusion_veto"))
    protective_block = any(reason.startswith("protective_") for reason in unique_reasons)
    broker_block = any(reason.startswith("broker_") for reason in unique_reasons)
    recovery_block = any(
        reason.startswith("recovery_")
        or reason.endswith("_fail_closed")
        or reason == "missing_recovered_contributor_state_neutralized"
        for reason in unique_reasons
    )
    forbidden = any(reason.endswith("_forbidden") or reason == "contributor_claimed_forbidden_authority" for reason in unique_reasons)
    conflict = "entry_contributor_conflict_unresolved" in unique_reasons
    missing_entry = "entry_candidate_missing" in unique_reasons

    eligible = not any((hard_veto, protective_block, broker_block, recovery_block, forbidden, conflict, missing_entry))
    if hard_veto:
        classification = "hard_veto_fail_closed"
    elif protective_block:
        classification = "protective_block_or_freeze"
    elif broker_block:
        classification = "broker_truth_no_go"
    elif recovery_block:
        classification = "recovery_neutral_fail_closed"
    elif conflict or missing_entry:
        classification = "neutral_or_no_go"
    elif forbidden:
        classification = "forbidden_authority_blocked"
    else:
        classification = "eligible_for_governed_paper_decision_path"

    return StressDecision(
        scenario=scenario,
        classification=classification,
        eligible_for_governed_paper_decision_path=eligible,
        order_approved=False,
        execution_not_called=True,
        order_not_submitted=True,
        broker_mutation_absent=True,
        live_mode_absent=True,
        reason_codes=unique_reasons + (("economics_gap_recorded",) if economics_gap else ()),
        selected_symbol=executable_entries[0].symbol if executable_entries else None,
        candidate_count=len(executable_entries),
        economics_veto_active=False,
        profitability_claim_made=False,
        latency_future_packet=bool(timing and timing.latency_metrics_absent),
    )


def _instrument(instrument_id: str = "eth-usd", symbol: str = "ETH/USD") -> InstrumentProfile:
    return InstrumentProfile(
        instrument_id=instrument_id,
        symbol=symbol,
        canonical_symbol=symbol,
        venue_symbol=symbol.replace("/", ""),
        display_symbol=symbol,
        root_symbol=symbol.split("/")[0],
        asset_class=AssetClass.CRYPTO,
        instrument_type=InstrumentType.SPOT,
        venue="KRAKEN",
        primary_exchange="KRAKEN",
        currency="USD",
        quote_currency="USD",
        base_currency=symbol.split("/")[0],
        country="US",
        region="North America",
        timezone="UTC",
        enabled=True,
        paper_tradable=True,
        live_tradable=False,
        fractional_allowed=True,
    )


def _order_book(symbol: str, ts_ns: int, mid: float) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        symbol=symbol,
        exchange_ts_ns=ts_ns,
        bids=[(mid - 1.0, 4.0), (mid - 2.0, 3.0)],
        asks=[(mid + 1.0, 3.0), (mid + 2.0, 2.0)],
    )


def _candle(symbol: str, ts_ns: int, close: float) -> Candle:
    return Candle(
        symbol=symbol,
        exchange_ts_ns=ts_ns,
        open=close,
        high=close * 1.002,
        low=close * 0.998,
        close=close,
        volume=2500.0,
        timeframe="1m",
    )


def _toxicity(ts_ns: int) -> ToxicityAlert:
    return ToxicityAlert(0.20, ToxicityRegime.NORMAL, "neutral", 0.10, 0.10, 0.10, 0.0, 0.0, 0.80, ts_ns, "25x")


def _intelligence_ok() -> IntelligenceEvidence:
    fusion = SignalFusion(config=types.SimpleNamespace(strategies=types.SimpleNamespace(sector_rotation_ranging_eligible=False), symbol="ETH/USD"))
    fusion.update_physical({"health_score": 0.80}, T0_NS)
    fusion.update_toxicity(_toxicity(T0_NS), T0_NS)
    decision = fusion.fuse(T0_NS)
    telemetry = fusion.get_fusion_telemetry()
    assert decision.has_valid_sleeve
    assert "veto_reason" not in telemetry
    return IntelligenceEvidence(True, True)


def _intelligence_missing_physical() -> IntelligenceEvidence:
    fusion = SignalFusion(config=types.SimpleNamespace(strategies=types.SimpleNamespace(sector_rotation_ranging_eligible=False), symbol="ETH/USD"))
    fusion.update_toxicity(_toxicity(T0_NS), T0_NS)
    decision = fusion.fuse(T0_NS)
    assert "Missing critical signal [physical]" in decision.reason
    return IntelligenceEvidence(False, True, decision.reason)


def _intelligence_stale_toxicity() -> IntelligenceEvidence:
    fusion = SignalFusion(config=types.SimpleNamespace(strategies=types.SimpleNamespace(sector_rotation_ranging_eligible=False), symbol="ETH/USD"))
    fusion.update_physical({"health_score": 0.80}, T0_NS)
    fusion.update_toxicity(_toxicity(T0_NS - 31_000_000_000), T0_NS - 31_000_000_000)
    decision = fusion.fuse(T0_NS)
    assert "Stale critical signal [toxicity]" in decision.reason
    return IntelligenceEvidence(True, False, decision.reason)


def _gamma_entry() -> EntryEvidence:
    config = types.SimpleNamespace(strategies=types.SimpleNamespace(dark_pool_enabled=True, options_flow_enabled=False, dark_pool_volume_threshold=2.0, min_confidence=0.65))
    strategy = GammaFrontStrategy(config=config, symbol="ETH/USD")
    for i in range(5):
        strategy.update_dark_pool(
            DarkPoolPrint(
                symbol="ETH/USD",
                exchange_ts_ns=T0_NS + i,
                price=100.0,
                size=1000.0,
                exchange="DARK",
                is_buy=True,
                venue="dark_pool",
            )
        )
    signal = strategy.update_dark_pool(
        DarkPoolPrint(
            symbol="ETH/USD",
            exchange_ts_ns=T0_NS + 10,
            price=100.0,
            size=10000.0,
            exchange="DARK",
            is_buy=True,
            venue="dark_pool",
        )
    )
    assert signal is not None
    vote = adapt_gamma_front_to_vote(signal, exchange_ts_ns=signal.exchange_ts_ns)
    assert vote.signal == SignalType.BUY.value
    return EntryEvidence("GammaFront", "ETH/USD", "buy", "deterministic_trend_stress_candidate", governed_candidate=True)


def _adaptive_entry() -> EntryEvidence:
    engine = AdaptiveDC(initial_theta=Decimal("0.005"))
    engine.process_tick(
        DCMarketTick(
            symbol="ETH/USD",
            price=Decimal("100.00"),
            timestamp_ns=T0_NS,
            book_integrity=BookIntegrity.HEALTHY,
            toxicity_level=ToxicityLevel.BENIGN,
            replay_mode=ReplayMode.REPLAY,
            execution_mode=ExecutionMode.REPLAY,
        )
    )
    _event, _assessment, recommendation = engine.process_tick(
        DCMarketTick(
            symbol="ETH/USD",
            price=Decimal("101.00"),
            timestamp_ns=T0_NS + 10_000_000,
            book_integrity=BookIntegrity.HEALTHY,
            toxicity_level=ToxicityLevel.BENIGN,
            replay_mode=ReplayMode.REPLAY,
            execution_mode=ExecutionMode.REPLAY,
        )
    )
    assert recommendation is not None
    vote = adapt_adaptive_dc_to_vote(recommendation, exchange_ts_ns=T0_NS + 10_000_000)
    assert isinstance(vote, StrategyVote)
    return EntryEvidence("AdaptiveDC", "ETH/USD", "buy", "deterministic_trend_stress_candidate", governed_candidate=True)


def _strategy_entry(strategy: str, side: str = "buy") -> EntryEvidence:
    signal = StrategySignal(strategy=strategy, symbol="ETH/USD", side=side, confidence=0.75, quantity=0.25, exchange_ts_ns=T0_NS, reason="25x_replay_regime_stress")
    adapter = adapt_sector_rotation_to_vote if strategy == "sector_rotation" else adapt_liquidity_void_to_vote
    vote = adapter(signal, exchange_ts_ns=T0_NS)
    assert vote.metadata["execution_candidate"] is True
    return EntryEvidence(strategy, "ETH/USD", side, "deterministic_replay_vote", governed_candidate=True)


def _ranking_metadata(*, high: bool = False) -> EntryEvidence:
    report = OpportunityRanker().rank(
        candidates=[("eth-usd", "gamma_front", Decimal("40.0" if high else "4.0"), Decimal("0.80" if high else "0.20"), Decimal("3000"))],
        instruments={"eth-usd": _instrument()},
        existing_exposures={},
        total_equity=Decimal("20000"),
        available_capital=Decimal("10000"),
        timestamp_ns=T0_NS,
    )
    assert report.total_ranked == 1
    return EntryEvidence("OpportunityRanking", "ETH/USD", "ranked", "ranking_metadata_only", governed_candidate=False)


def _trend_entries() -> tuple[EntryEvidence, ...]:
    return (_ranking_metadata(high=True), _gamma_entry(), _adaptive_entry(), _strategy_entry("sector_rotation"), _strategy_entry("liquidity_void"))


def _moving_floor_intent() -> ProtectiveIntent:
    floor = TopologicalMovingFloor(base_buffer=Decimal("0.0200"))
    floor.process_tick(FloorMarketTick("ETH/USD", Decimal("100"), T0_NS, Decimal("10"), Decimal("10"), BookIntegrity.HEALTHY, ToxicityLevel.BENIGN, ReplayMode.REPLAY, ExecutionMode.REPLAY))
    floor.process_tick(FloorMarketTick("ETH/USD", Decimal("105"), T0_NS + 1_000_000_000, Decimal("10"), Decimal("10"), BookIntegrity.HEALTHY, ToxicityLevel.BENIGN, ReplayMode.REPLAY, ExecutionMode.REPLAY))
    event, _assessment, recommendation = floor.process_tick(FloorMarketTick("ETH/USD", Decimal("102"), T0_NS + 2_000_000_000, Decimal("5"), Decimal("15"), BookIntegrity.HEALTHY, ToxicityLevel.BENIGN, ReplayMode.REPLAY, ExecutionMode.REPLAY))
    assert event is not None and event.event_type == FloorEventType.TOPOLOGICAL_BREACH
    vote = adapt_moving_floor_to_vote(recommendation, exchange_ts_ns=T0_NS + 2_000_000_000)
    assert vote.metadata["fresh_entry_authorized"] is False
    return ProtectiveIntent("MovingFloor", "protective_exit_candidate", "topological_breach", requires_existing_position=True)


def _hedge_intent() -> ProtectiveIntent:
    hedging = HedgingFlow()
    exposure = PortfolioExposureSnapshot(
        net_delta=Decimal("20000"),
        total_equity=Decimal("100000"),
        target_symbol="BTC/USD",
        sleeve="portfolio_delta",
    )
    market = HedgeMarketContext(
        symbol="BTC/USD",
        price=Decimal("50000"),
        book_integrity=BookIntegrity.HEALTHY,
        toxicity_level=ToxicityLevel.BENIGN,
        replay_mode=ReplayMode.REPLAY,
        execution_mode=ExecutionMode.REPLAY,
    )
    recommendation = hedging.recommend(assessment=hedging.assess(exposure=exposure, market=market), market=market)
    assert recommendation is not None and recommendation.is_hedge is True and recommendation.side == OrderSide.SELL
    return ProtectiveIntent("HedgingFlow", "hedge_candidate", "portfolio_delta_protection", requires_existing_exposure=True)


def _recalibrator_freeze() -> ProtectiveIntent:
    recalibrator = Recalibrator()
    regime = recalibrator.evaluate_regime(
        price_drop_pct=0.03,
        tpe_signal=TopologicalSignal(0.20, 4, 1, 0.30, True, True, 0.90, T0_NS, "super_void_with_drawdown"),
        drop_duration_sec=60.0,
    )
    recalibrator.start_recalibration(reason=regime, duration_seconds=3600.0)
    assert recalibrator.get_status()["is_in_recalibration"] is True
    return ProtectiveIntent("Recalibrator", "freeze_trading", regime)


def _symbol_recovery_evidence() -> tuple[RecoveryEvidence, RecoveryEvidence]:
    btc = SymbolRuntime("BTC/USD")
    eth = SymbolRuntime("ETH/USD")
    btc.update_order_book(_order_book("BTC/USD", T0_NS, 50_000.0))
    btc.update_candle(_candle("BTC/USD", T0_NS + 1, 50_010.0))
    eth.update_order_book(_order_book("ETH/USD", T0_NS + 2, 2_500.0))
    eth.update_candle(_candle("ETH/USD", T0_NS + 3, 2_505.0))

    recovered_btc = SymbolRuntime.import_recovery_state(btc.export_recovery_state(), expected_symbol="BTC/USD", current_ts_ns=T0_NS + 4, max_state_age_ns=10)
    recovered_eth = SymbolRuntime.import_recovery_state(eth.export_recovery_state(), expected_symbol="ETH/USD", current_ts_ns=T0_NS + 4, max_state_age_ns=10)
    assert recovered_btc.symbol == "BTC/USD"
    assert recovered_eth.symbol == "ETH/USD"
    assert recovered_btc.last_price != recovered_eth.last_price
    assert recovered_btc.recovery_status == "hydrated_market_state_only"
    assert recovered_btc.last_sector_rotation_observed_vote is None
    assert not hasattr(recovered_btc, "submit_order")

    stale = SymbolRuntime.import_recovery_state(btc.export_recovery_state(), expected_symbol="BTC/USD", current_ts_ns=T0_NS + 1_000_000_000, max_state_age_ns=10)
    assert stale.recovery_status == "stale_fail_closed"
    assert stale.is_ready() is False
    return (
        RecoveryEvidence(symbol_local=True, missing_contributor_state=True),
        RecoveryEvidence(symbol_local=True, fail_closed_reason=stale.recovery_status),
    )


def test_whole_bot_replay_regime_stress_classifies_required_regimes_without_execution():
    clean = _snapshot()
    quiet = evaluate_stress(
        scenario="quiet_no_trade",
        broker_snapshot=clean,
        local=LocalReplayState(),
        protective=(),
        entries=(_ranking_metadata(high=False),),
        economics=EconomicsEvidence(True, ("slippage_bps", "arrival_price", "expected_fill_price", "net_pnl", "net_edge", "profitability")),
        intelligence=_intelligence_ok(),
    )
    trend = evaluate_stress(
        scenario="trend_supportive",
        broker_snapshot=clean,
        local=LocalReplayState(),
        protective=(),
        entries=_trend_entries(),
        economics=EconomicsEvidence(True, ("slippage_bps", "net_edge", "net_pnl")),
        intelligence=_intelligence_ok(),
    )
    choppy = evaluate_stress(
        scenario="choppy_conflicting",
        broker_snapshot=clean,
        local=LocalReplayState(),
        protective=(),
        entries=(_strategy_entry("sector_rotation", "buy"), _strategy_entry("liquidity_void", "sell"), _ranking_metadata(high=True)),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_ok(),
    )
    protective = evaluate_stress(
        scenario="protective_breach_capital_defense",
        broker_snapshot=clean,
        local=LocalReplayState(exposures={"ETH/USD": Decimal("0.25")}),
        protective=(_moving_floor_intent(), _hedge_intent(), _recalibrator_freeze()),
        entries=_trend_entries(),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_ok(),
    )
    stale = evaluate_stress(
        scenario="stale_or_missing_critical_data",
        broker_snapshot=clean,
        local=LocalReplayState(),
        protective=(),
        entries=_trend_entries(),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_stale_toxicity(),
    )
    missing = evaluate_stress(
        scenario="missing_critical_physical_data",
        broker_snapshot=clean,
        local=LocalReplayState(),
        protective=(),
        entries=_trend_entries(),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_missing_physical(),
    )
    economics_gap = evaluate_stress(
        scenario="economics_gap",
        broker_snapshot=clean,
        local=LocalReplayState(),
        protective=(),
        entries=_trend_entries(),
        economics=EconomicsEvidence(True, ("slippage_bps", "arrival_price", "expected_fill_price", "net_pnl", "net_edge", "profitability")),
        intelligence=_intelligence_ok(),
    )
    recovered, recovered_stale = _symbol_recovery_evidence()
    recovery_missing = evaluate_stress(
        scenario="recovery_restart_missing_contributor_state",
        broker_snapshot=clean,
        local=LocalReplayState(),
        protective=(),
        entries=(),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_ok(),
        recovery=recovered,
    )
    recovery_stale = evaluate_stress(
        scenario="recovery_restart_stale_symbol_state",
        broker_snapshot=clean,
        local=LocalReplayState(),
        protective=(),
        entries=_trend_entries(),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_ok(),
        recovery=recovered_stale,
    )
    timing = evaluate_stress(
        scenario="latency_timing_observation",
        broker_snapshot=clean,
        local=LocalReplayState(),
        protective=(),
        entries=_trend_entries(),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_ok(),
        timing=TimingObservation(("fixture_exchange_ts_ns", "snapshot_receive_ts_ns", "decision_eval_ts_ns")),
    )

    assert quiet.classification == "neutral_or_no_go"
    assert "entry_candidate_missing" in quiet.reason_codes
    assert trend.classification == "eligible_for_governed_paper_decision_path"
    assert trend.eligible_for_governed_paper_decision_path is True
    assert trend.order_approved is False
    assert choppy.classification == "neutral_or_no_go"
    assert "entry_contributor_conflict_unresolved" in choppy.reason_codes
    assert protective.classification == "protective_block_or_freeze"
    assert "protective_freeze_trading" in protective.reason_codes
    assert stale.classification == "hard_veto_fail_closed"
    assert "critical_toxicity_evidence_missing" in stale.reason_codes
    assert missing.classification == "hard_veto_fail_closed"
    assert "critical_physical_evidence_missing" in missing.reason_codes
    assert economics_gap.classification == "eligible_for_governed_paper_decision_path"
    assert "economics_gap_recorded" in economics_gap.reason_codes
    assert economics_gap.economics_veto_active is False
    assert economics_gap.profitability_claim_made is False
    assert recovery_missing.classification == "recovery_neutral_fail_closed"
    assert "missing_recovered_contributor_state_neutralized" in recovery_missing.reason_codes
    assert recovery_stale.classification == "recovery_neutral_fail_closed"
    assert "stale_fail_closed" in recovery_stale.reason_codes
    assert timing.latency_future_packet is True

    for decision in (quiet, trend, choppy, protective, stale, missing, economics_gap, recovery_missing, recovery_stale, timing):
        assert decision.execution_not_called is True
        assert decision.order_not_submitted is True
        assert decision.broker_mutation_absent is True
        assert decision.live_mode_absent is True


def test_broker_truth_conflict_and_optional_real_paper_read_only_stress():
    open_order_conflict = evaluate_stress(
        scenario="broker_open_order_conflict",
        broker_snapshot=_snapshot(open_orders=({"client_order_id": "broker-only", "broker_order_id": "alpaca-order-1", "symbol": "ETH/USD"},)),
        local=LocalReplayState(),
        protective=(),
        entries=_trend_entries(),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_ok(),
    )
    position_conflict = evaluate_stress(
        scenario="broker_position_conflict",
        broker_snapshot=_snapshot(positions=({"symbol": "ETH/USD", "quantity": Decimal("0.25")},)),
        local=LocalReplayState(),
        protective=(),
        entries=_trend_entries(),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_ok(),
    )
    stale_snapshot = evaluate_stress(
        scenario="stale_broker_snapshot",
        broker_snapshot=_snapshot(receive_ts_ns=T0_NS - MAX_SNAPSHOT_AGE_NS - 1),
        local=LocalReplayState(),
        protective=(),
        entries=_trend_entries(),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_ok(),
    )
    empty_broker_truth = evaluate_stress(
        scenario="empty_broker_truth_valid",
        broker_snapshot=_snapshot(positions=(), open_orders=()),
        local=LocalReplayState(),
        protective=(),
        entries=_trend_entries(),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_ok(),
    )

    assert open_order_conflict.classification == "broker_truth_no_go"
    assert "broker_open_order_missing_local_mapping" in open_order_conflict.reason_codes
    assert position_conflict.classification == "broker_truth_no_go"
    assert "broker_position_conflicts_with_local_flat" in position_conflict.reason_codes
    assert stale_snapshot.classification == "broker_truth_no_go"
    assert "broker_snapshot_stale_or_missing" in stale_snapshot.reason_codes
    assert empty_broker_truth.classification == "eligible_for_governed_paper_decision_path"

    base_url = (os.environ.get("APCA_API_BASE_URL") or "").rstrip("/")
    key_id = os.environ.get("APCA_API_KEY_ID") or ""
    secret_key = os.environ.get("APCA_API_SECRET_KEY") or ""
    if not base_url or not key_id or not secret_key:
        pytest.skip("Alpaca PAPER read-only env missing")
    if base_url != EXPECTED_PAPER_BASE_URL:
        pytest.fail(f"APCA_API_BASE_URL is not exact paper endpoint: {base_url!r}")

    client = SanitizedAlpacaReadOnlyClient(base_url, key_id, secret_key)
    account = client.get_json("/v2/account")
    client.get_json("/v2/clock")
    positions = client.get_json("/v2/positions")
    orders = client.get_json("/v2/orders", {"status": "open", "limit": "50", "nested": "false"})

    snapshot = _snapshot(
        account_id=account.get("id"),
        balances=({"currency": account.get("currency") or "USD", "cash": _decimal_or_none(account.get("cash")), "buying_power": _decimal_or_none(account.get("buying_power")), "equity": _decimal_or_none(account.get("equity"))},),
        positions=tuple({"symbol": item.get("symbol"), "quantity": _decimal_or_none(item.get("qty"))} for item in positions),
        open_orders=tuple({"client_order_id": item.get("client_order_id"), "broker_order_id": item.get("id"), "symbol": item.get("symbol")} for item in orders),
        receive_ts_ns=now_ns(),
    )
    real_read_only = evaluate_stress(
        scenario="real_alpaca_paper_read_only_broker_truth",
        broker_snapshot=snapshot,
        local=LocalReplayState(),
        protective=(),
        entries=_trend_entries(),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_ok(),
        now=(snapshot.receive_ts_ns or now_ns()) + 1,
    )

    assert all(method == "GET" for method, _path in client.calls)
    assert {path for _method, path in client.calls}.issubset(ALLOWED_GET_PATHS)
    assert real_read_only.order_approved is False
    assert real_read_only.order_not_submitted is True
    assert real_read_only.broker_mutation_absent is True


def test_adversarial_authority_attempts_are_blocked_and_surfaces_remain_non_executing():
    trend_with_freeze = evaluate_stress(
        scenario="trend_candidate_with_protective_freeze",
        broker_snapshot=_snapshot(),
        local=LocalReplayState(exposures={"ETH/USD": Decimal("0.25")}),
        protective=(_recalibrator_freeze(),),
        entries=_trend_entries(),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_ok(),
    )
    entry_support_stale_critical = evaluate_stress(
        scenario="entry_support_but_stale_critical_data",
        broker_snapshot=_snapshot(),
        local=LocalReplayState(),
        protective=(),
        entries=_trend_entries(),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_stale_toxicity(),
    )
    high_ranking_broker_conflict = evaluate_stress(
        scenario="high_ranking_broker_conflict",
        broker_snapshot=_snapshot(open_orders=({"client_order_id": "broker-only", "broker_order_id": "alpaca-order-1", "symbol": "ETH/USD"},)),
        local=LocalReplayState(),
        protective=(),
        entries=(_ranking_metadata(high=True), _gamma_entry()),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_ok(),
    )
    duplicate_claim = evaluate_stress(
        scenario="attempted_duplicate_candidate_authority",
        broker_snapshot=_snapshot(),
        local=LocalReplayState(),
        protective=(),
        entries=(EntryEvidence("InjectedDuplicateAuthority", "ETH/USD", "buy", "adversarial", True, duplicate_authority_claim=True),),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_ok(),
    )
    hidden_veto = evaluate_stress(
        scenario="attempted_economics_veto_activation",
        broker_snapshot=_snapshot(),
        local=LocalReplayState(),
        protective=(),
        entries=_trend_entries(),
        economics=EconomicsEvidence(True, ("net_edge",), veto_enabled=True),
        intelligence=_intelligence_ok(),
    )
    invented_economics = evaluate_stress(
        scenario="attempted_fake_pnl_net_edge",
        broker_snapshot=_snapshot(),
        local=LocalReplayState(),
        protective=(),
        entries=_trend_entries(),
        economics=EconomicsEvidence(True, (), pnl_claim=Decimal("1.0"), net_edge_claim=Decimal("0.25")),
        intelligence=_intelligence_ok(),
    )

    assert trend_with_freeze.classification == "protective_block_or_freeze"
    assert entry_support_stale_critical.classification == "hard_veto_fail_closed"
    assert high_ranking_broker_conflict.classification == "broker_truth_no_go"
    assert duplicate_claim.classification == "forbidden_authority_blocked"
    assert "contributor_claimed_forbidden_authority" in duplicate_claim.reason_codes
    assert hidden_veto.classification == "forbidden_authority_blocked"
    assert hidden_veto.economics_veto_active is False
    assert invented_economics.classification == "forbidden_authority_blocked"
    assert invented_economics.profitability_claim_made is False

    protected_surfaces = (
        TopologicalMovingFloor,
        HedgingFlow,
        Recalibrator,
        OpportunityRanker,
        GammaFrontStrategy,
        AdaptiveDC,
        SectorRotationStrategy,
        LiquidityVoidStrategy,
        NetEdgeGovernor,
        TradeEfficiencyGovernor,
        adapt_moving_floor_to_vote,
        adapt_gamma_front_to_vote,
        adapt_adaptive_dc_to_vote,
        adapt_sector_rotation_to_vote,
        adapt_liquidity_void_to_vote,
        SymbolRuntime.export_recovery_state,
        SymbolRuntime.import_recovery_state,
    )
    forbidden_tokens = ("broker_adapter", "live_broker", "submit_order", "_execute_signal", "cancel_order", "replace_order")
    for surface in protected_surfaces:
        source = inspect.getsource(surface)
        for token in forbidden_tokens:
            assert token not in source

    broker_adapter_source = Path("app/execution/broker_adapter.py").read_text(encoding="utf-8-sig")
    live_broker_source = Path("app/execution/live_broker.py").read_text(encoding="utf-8-sig")
    assert "PRE-INTEGRATION" in broker_adapter_source
    assert "NO IMPLEMENTATION" in broker_adapter_source
    assert "Under construction" in live_broker_source
