from __future__ import annotations

import inspect
import json
import os
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
from app.execution.paper_broker import PaperBroker
from app.models import DarkPoolPrint, StrategySignal
from app.models.contracts import StrategyVote
from app.models.enums import (
    BookIntegrity,
    ExecutionMode,
    OrderSide,
    ReplayMode,
    SignalType,
    StrategyID,
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
from app.utils.time_utils import now_ns


EXPECTED_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
ALLOWED_GET_PATHS = frozenset({"/v2/account", "/v2/positions", "/v2/orders", "/v2/account/activities", "/v2/clock"})
T0_NS = 1_777_948_800_000_000_000
MAX_SNAPSHOT_AGE_NS = 5_000_000_000


@dataclass(frozen=True)
class LocalReadinessState:
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


@dataclass(frozen=True)
class EconomicsEvidence:
    fee_evidence_present: bool
    missing_fields: tuple[str, ...] = ()
    advisory_only: bool = True
    veto_enabled: bool = False


@dataclass(frozen=True)
class IntelligenceEvidence:
    physical_ok: bool
    toxicity_ok: bool
    fusion_veto_reason: str | None = None


@dataclass(frozen=True)
class ActivationDecision:
    contribution_ready: bool
    eligible_for_governed_paper_decision_path: bool
    order_approved: bool
    execution_not_called: bool
    order_not_submitted: bool
    reason_codes: tuple[str, ...]
    selected_symbol: str | None
    candidate_count: int
    economics_veto_active: bool
    profitability_claim_made: bool


class ReadOnlyAlpacaClient:
    def __init__(self, base_url: str, key_id: str, secret_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.key_id = key_id
        self.secret_key = secret_key
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
                "APCA-API-KEY-ID": self.key_id,
                "APCA-API-SECRET-KEY": self.secret_key,
                "Accept": "application/json",
            },
        )
        self.calls.append(("GET", path))
        try:
            with urllib.request.urlopen(request, timeout=10.0) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AssertionError(f"alpaca_read_only_http_error:{exc.code}:{path}:{body[:180]}") from exc

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


def _env_or_skip() -> tuple[str, str, str]:
    base_url = os.environ.get("APCA_API_BASE_URL", "").rstrip("/")
    key_id = os.environ.get("APCA_API_KEY_ID", "")
    secret_key = os.environ.get("APCA_API_SECRET_KEY", "")
    missing = [name for name, value in (("APCA_API_BASE_URL", base_url), ("APCA_API_KEY_ID", key_id), ("APCA_API_SECRET_KEY", secret_key)) if not value]
    if missing:
        pytest.skip(f"Alpaca paper read-only env missing: {', '.join(missing)}")
    if base_url != EXPECTED_PAPER_BASE_URL:
        pytest.fail(f"APCA_API_BASE_URL is not exact paper endpoint: {base_url!r}")
    return base_url, key_id, secret_key


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


def _broker_reasons(snapshot: ReadOnlyBrokerSnapshot, local: LocalReadinessState, *, now: int = T0_NS + 1) -> list[str]:
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
    broker_position_symbols = set()
    for position in snapshot.positions:
        symbol = position.get("symbol")
        qty = position.get("quantity")
        if not symbol or qty is None:
            reasons.append("broker_position_invalid")
            continue
        broker_position_symbols.add(symbol)
        if qty != Decimal("0") and local.exposures.get(symbol, Decimal("0")) != qty:
            reasons.append("broker_position_conflicts_with_local_flat")
    for order in snapshot.open_orders:
        client_order_id = order.get("client_order_id")
        broker_order_id = order.get("broker_order_id")
        if not client_order_id or not broker_order_id or client_order_id not in local.local_open_order_ids:
            reasons.append("broker_open_order_missing_local_mapping")
    return reasons


def evaluate_activation(
    *,
    broker_snapshot: ReadOnlyBrokerSnapshot,
    local: LocalReadinessState,
    protective: tuple[ProtectiveIntent, ...],
    entries: tuple[EntryEvidence, ...],
    economics: EconomicsEvidence,
    intelligence: IntelligenceEvidence,
    now: int = T0_NS + 1,
) -> ActivationDecision:
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
    if any(entry.ranking_authority or entry.execution_authority for entry in entries):
        reasons.append("contributor_claimed_forbidden_authority")

    if economics.veto_enabled:
        reasons.append("economics_veto_forbidden")
    economics_gap = bool(economics.missing_fields)

    unique_reasons = tuple(dict.fromkeys(reasons))
    ready = not unique_reasons
    selected_symbol = executable_entries[0].symbol if executable_entries else None
    return ActivationDecision(
        contribution_ready=ready,
        eligible_for_governed_paper_decision_path=ready,
        order_approved=False,
        execution_not_called=True,
        order_not_submitted=True,
        reason_codes=unique_reasons + (("economics_gap_recorded",) if economics_gap else ()),
        selected_symbol=selected_symbol,
        candidate_count=len(executable_entries),
        economics_veto_active=False,
        profitability_claim_made=False,
    )


def _moving_floor_intent() -> ProtectiveIntent:
    floor = TopologicalMovingFloor(base_buffer=Decimal("0.0200"))
    floor.process_tick(
        FloorMarketTick("ETH/USD", Decimal("100"), T0_NS, Decimal("10"), Decimal("10"), BookIntegrity.HEALTHY, ToxicityLevel.BENIGN, ReplayMode.REPLAY, ExecutionMode.REPLAY)
    )
    floor.process_tick(
        FloorMarketTick("ETH/USD", Decimal("105"), T0_NS + 1_000_000_000, Decimal("10"), Decimal("10"), BookIntegrity.HEALTHY, ToxicityLevel.BENIGN, ReplayMode.REPLAY, ExecutionMode.REPLAY)
    )
    event, _assessment, recommendation = floor.process_tick(
        FloorMarketTick("ETH/USD", Decimal("102"), T0_NS + 2_000_000_000, Decimal("5"), Decimal("15"), BookIntegrity.HEALTHY, ToxicityLevel.BENIGN, ReplayMode.REPLAY, ExecutionMode.REPLAY)
    )
    assert event is not None and event.event_type == FloorEventType.TOPOLOGICAL_BREACH
    vote = adapt_moving_floor_to_vote(recommendation, exchange_ts_ns=T0_NS + 2_000_000_000)
    assert vote.metadata["fresh_entry_authorized"] is False
    return ProtectiveIntent("MovingFloor", "protective_exit_candidate", "topological_breach", requires_existing_position=True)


def _hedge_intent(with_exposure: bool = True) -> tuple[ProtectiveIntent, ...]:
    if not with_exposure:
        return ()
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
    assessment = hedging.assess(exposure=exposure, market=market)
    recommendation = hedging.recommend(assessment=assessment, market=market)
    assert recommendation is not None and recommendation.is_hedge is True and recommendation.side == OrderSide.SELL
    return (ProtectiveIntent("HedgingFlow", "hedge_candidate", "portfolio_delta_protection", requires_existing_exposure=True),)


def _recalibrator_freeze() -> ProtectiveIntent:
    recalibrator = Recalibrator()
    regime = recalibrator.evaluate_regime(
        price_drop_pct=0.03,
        tpe_signal=TopologicalSignal(0.20, 4, 1, 0.30, True, True, 0.90, T0_NS, "super_void_with_drawdown"),
        drop_duration_sec=60.0,
    )
    recalibrator.start_recalibration(reason=regime, duration_seconds=3600.0)
    assert recalibrator.get_status()["is_in_recalibration"] is True
    return ProtectiveIntent("Recalibrator", "freeze_trading", regime, requires_existing_position=False)


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
    return EntryEvidence("GammaFront", "ETH/USD", "buy", "candidate_vote", governed_candidate=True)


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
    return EntryEvidence("AdaptiveDC", "ETH/USD", "buy", "candidate_vote", governed_candidate=True)


def _strategy_entry(strategy: str, side: str = "buy") -> EntryEvidence:
    signal = StrategySignal(strategy=strategy, symbol="ETH/USD", side=side, confidence=0.75, quantity=0.25, exchange_ts_ns=T0_NS, reason="whole_bot_contribution_activation")
    adapter = adapt_sector_rotation_to_vote if strategy == "sector_rotation" else adapt_liquidity_void_to_vote
    vote = adapter(signal, exchange_ts_ns=T0_NS)
    assert vote.metadata["execution_candidate"] is True
    return EntryEvidence(strategy, "ETH/USD", side, "strategy_vote", governed_candidate=True)


def _ranking_evidence() -> EntryEvidence:
    profile = InstrumentProfile(
        instrument_id="eth-usd",
        symbol="ETH/USD",
        canonical_symbol="ETH/USD",
        venue_symbol="ETHUSD",
        display_symbol="ETH/USD",
        root_symbol="ETH",
        asset_class=AssetClass.CRYPTO,
        instrument_type=InstrumentType.SPOT,
        venue="KRAKEN",
        primary_exchange="KRAKEN",
        currency="USD",
        quote_currency="USD",
        base_currency="ETH",
        country="US",
        region="North America",
        timezone="UTC",
        enabled=True,
        paper_tradable=True,
        live_tradable=False,
        fractional_allowed=True,
    )
    report = OpportunityRanker().rank(
        candidates=[("eth-usd", "gamma_front", Decimal("40.0"), Decimal("0.80"), Decimal("3000"))],
        instruments={"eth-usd": profile},
        existing_exposures={},
        total_equity=Decimal("20000"),
        available_capital=Decimal("10000"),
        timestamp_ns=T0_NS,
    )
    assert report.top_opportunity == "ETH/USD"
    return EntryEvidence("OpportunityRanking", "ETH/USD", "ranked", "ranking_metadata", governed_candidate=False, ranking_authority=False)


def _intelligence_ok() -> IntelligenceEvidence:
    fusion = SignalFusion(config=types.SimpleNamespace(strategies=types.SimpleNamespace(sector_rotation_ranging_eligible=False), symbol="ETH/USD"))
    fusion.update_physical({"health_score": 0.80}, T0_NS)
    fusion.update_toxicity(ToxicityAlert(0.20, ToxicityRegime.NORMAL, "neutral", 0.10, 0.10, 0.10, 0.0, 0.0, 0.80, T0_NS, "25w"), T0_NS)
    decision = fusion.fuse(T0_NS)
    telemetry = fusion.get_fusion_telemetry()
    assert decision.has_valid_sleeve
    assert "veto_reason" not in telemetry
    return IntelligenceEvidence(True, True)


def _intelligence_missing_physical() -> IntelligenceEvidence:
    fusion = SignalFusion(config=types.SimpleNamespace(strategies=types.SimpleNamespace(sector_rotation_ranging_eligible=False), symbol="ETH/USD"))
    fusion.update_toxicity(ToxicityAlert(0.20, ToxicityRegime.NORMAL, "neutral", 0.10, 0.10, 0.10, 0.0, 0.0, 0.80, T0_NS, "25w"), T0_NS)
    decision = fusion.fuse(T0_NS)
    assert "Missing critical signal [physical]" in decision.reason
    return IntelligenceEvidence(False, True, decision.reason)


def _entries() -> tuple[EntryEvidence, ...]:
    return (_ranking_evidence(), _gamma_entry(), _adaptive_entry(), _strategy_entry("sector_rotation"), _strategy_entry("liquidity_void"))


def test_alpaca_paper_read_only_truth_can_contribute_to_activation_context_when_env_available():
    base_url, key_id, secret_key = _env_or_skip()
    client = ReadOnlyAlpacaClient(base_url, key_id, secret_key)
    account = client.get_json("/v2/account")
    client.get_json("/v2/clock")
    positions = client.get_json("/v2/positions")
    orders = client.get_json("/v2/orders", {"status": "open", "limit": "50", "nested": "false"})
    try:
        activities = client.get_json("/v2/account/activities", {"activity_types": "FILL", "page_size": "100"})
    except AssertionError:
        activities = ()

    assert isinstance(account, dict) and account.get("id")
    assert isinstance(positions, list)
    assert isinstance(orders, list)
    assert all(method == "GET" for method, _path in client.calls)
    assert {path for _method, path in client.calls}.issubset(ALLOWED_GET_PATHS)

    snapshot = _snapshot(
        account_id=account.get("id"),
        balances=({"currency": account.get("currency") or "USD", "cash": _decimal_or_none(account.get("cash")), "buying_power": _decimal_or_none(account.get("buying_power")), "equity": _decimal_or_none(account.get("equity"))},),
        positions=tuple({"symbol": item.get("symbol"), "quantity": _decimal_or_none(item.get("qty"))} for item in positions),
        open_orders=tuple({"client_order_id": item.get("client_order_id"), "broker_order_id": item.get("id"), "symbol": item.get("symbol")} for item in orders),
        recent_fills=tuple(activities if isinstance(activities, list) else ()),
        receive_ts_ns=now_ns(),
    )
    decision = evaluate_activation(
        broker_snapshot=snapshot,
        local=LocalReadinessState(),
        protective=(),
        entries=_entries(),
        economics=EconomicsEvidence(True, ("slippage_bps", "net_edge", "net_pnl")),
        intelligence=_intelligence_ok(),
        now=snapshot.receive_ts_ns + 1,
    )

    assert decision.order_approved is False
    assert decision.execution_not_called is True
    assert decision.order_not_submitted is True
    if snapshot.positions or snapshot.open_orders:
        assert decision.contribution_ready is False
        assert set(decision.reason_codes) & {"broker_position_conflicts_with_local_flat", "broker_open_order_missing_local_mapping"}
    else:
        assert decision.contribution_ready is True


def test_combined_governed_activation_scenarios_without_broker_network():
    clean = evaluate_activation(
        broker_snapshot=_snapshot(),
        local=LocalReadinessState(),
        protective=(),
        entries=_entries(),
        economics=EconomicsEvidence(True, ("slippage_bps", "arrival_price", "expected_fill_price", "net_pnl", "net_edge", "profitability")),
        intelligence=_intelligence_ok(),
    )
    protective_freeze = evaluate_activation(
        broker_snapshot=_snapshot(),
        local=LocalReadinessState(exposures={"ETH/USD": Decimal("0.25")}),
        protective=(_moving_floor_intent(), *_hedge_intent(True), _recalibrator_freeze()),
        entries=_entries(),
        economics=EconomicsEvidence(True, ("slippage_bps", "net_edge")),
        intelligence=_intelligence_ok(),
    )
    broker_conflict = evaluate_activation(
        broker_snapshot=_snapshot(open_orders=({"client_order_id": "broker-only", "broker_order_id": "alpaca-order-1", "symbol": "ETH/USD"},)),
        local=LocalReadinessState(),
        protective=(),
        entries=_entries(),
        economics=EconomicsEvidence(True, ("slippage_bps", "net_edge")),
        intelligence=_intelligence_ok(),
    )
    economics_gap = evaluate_activation(
        broker_snapshot=_snapshot(),
        local=LocalReadinessState(),
        protective=(),
        entries=_entries(),
        economics=EconomicsEvidence(True, ("slippage_bps", "arrival_price", "expected_fill_price", "net_pnl", "net_edge", "profitability")),
        intelligence=_intelligence_ok(),
    )
    conflicting_entries = evaluate_activation(
        broker_snapshot=_snapshot(),
        local=LocalReadinessState(),
        protective=(),
        entries=(_strategy_entry("sector_rotation", "buy"), _strategy_entry("liquidity_void", "sell"), _ranking_evidence()),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_ok(),
    )

    assert clean.contribution_ready is True
    assert clean.eligible_for_governed_paper_decision_path is True
    assert clean.order_approved is False
    assert clean.order_not_submitted is True

    assert protective_freeze.contribution_ready is False
    assert "protective_freeze_trading" in protective_freeze.reason_codes
    assert protective_freeze.order_not_submitted is True

    assert broker_conflict.contribution_ready is False
    assert "broker_open_order_missing_local_mapping" in broker_conflict.reason_codes

    assert "economics_gap_recorded" in economics_gap.reason_codes
    assert economics_gap.economics_veto_active is False
    assert economics_gap.profitability_claim_made is False

    assert conflicting_entries.candidate_count == 2
    assert conflicting_entries.order_approved is False
    assert conflicting_entries.order_not_submitted is True


def test_adversarial_contributor_boundaries_and_missing_evidence_do_not_execute():
    no_position_exit = evaluate_activation(
        broker_snapshot=_snapshot(),
        local=LocalReadinessState(),
        protective=(_moving_floor_intent(),),
        entries=_entries(),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_ok(),
    )
    missing_hedge_exposure = evaluate_activation(
        broker_snapshot=_snapshot(),
        local=LocalReadinessState(),
        protective=_hedge_intent(False),
        entries=_entries(),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_ok(),
    )
    missing_critical_intel = evaluate_activation(
        broker_snapshot=_snapshot(),
        local=LocalReadinessState(),
        protective=(),
        entries=_entries(),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_missing_physical(),
    )
    ranking_alone = evaluate_activation(
        broker_snapshot=_snapshot(),
        local=LocalReadinessState(),
        protective=(),
        entries=(_ranking_evidence(),),
        economics=EconomicsEvidence(True, ("net_edge",)),
        intelligence=_intelligence_ok(),
    )
    hidden_veto = evaluate_activation(
        broker_snapshot=_snapshot(),
        local=LocalReadinessState(),
        protective=(),
        entries=_entries(),
        economics=EconomicsEvidence(True, ("net_edge",), veto_enabled=True),
        intelligence=_intelligence_ok(),
    )

    assert "protective_intent_requires_existing_position" in no_position_exit.reason_codes
    assert missing_hedge_exposure.contribution_ready is True
    assert missing_hedge_exposure.order_approved is False
    assert "critical_physical_evidence_missing" in missing_critical_intel.reason_codes
    assert "intelligence_fusion_veto" in missing_critical_intel.reason_codes
    assert "entry_candidate_missing" in ranking_alone.reason_codes
    assert "economics_veto_forbidden" in hidden_veto.reason_codes

    for decision in (no_position_exit, missing_hedge_exposure, missing_critical_intel, ranking_alone, hidden_veto):
        assert decision.execution_not_called is True
        assert decision.order_not_submitted is True
        assert decision.order_approved is False


def test_whole_bot_activation_harness_preserves_authority_boundaries():
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
    )
    forbidden_tokens = ("broker_adapter", "live_broker", "submit_order", "_execute_signal")
    for surface in protected_surfaces:
        source = inspect.getsource(surface)
        for token in forbidden_tokens:
            assert token not in source

    order_router_source = Path("app/execution/order_router.py").read_text(encoding="utf-8-sig")
    broker_source = inspect.getsource(PaperBroker)
    assert "NetEdgeGovernor" not in order_router_source
    assert "TradeEfficiencyGovernor" not in order_router_source
    assert "NetEdgeGovernor" not in broker_source
    assert "TradeEfficiencyGovernor" not in broker_source

    broker_adapter_source = Path("app/execution/broker_adapter.py").read_text(encoding="utf-8-sig")
    live_broker_source = Path("app/execution/live_broker.py").read_text(encoding="utf-8-sig")
    assert "PRE-INTEGRATION" in broker_adapter_source
    assert "NO IMPLEMENTATION" in broker_adapter_source
    assert "Under construction" in live_broker_source
