from __future__ import annotations

import inspect
import types
from decimal import Decimal

from app.models import DarkPoolPrint
from app.models.contracts import StrategyVote
from app.models.enums import (
    BookIntegrity,
    ExecutionMode,
    ReplayMode,
    SignalType,
    StrategyID,
    ToxicityLevel,
)
from app.models.instrument_profile import (
    AssetClass,
    InstrumentProfile,
    InstrumentType,
)
from app.portfolio.opportunity_ranking import (
    OpportunityGrade,
    OpportunityRanker,
)
from app.strategies.adaptive_dc import AdaptiveDC, DCMarketTick
from app.strategies.council_metadata import (
    FEED_REAL,
    KEY_FEED_STATUS,
    MODULE_ADAPTIVE_DC,
    MODULE_GAMMA_FRONT,
    MODULE_LIQUIDITY_VOID,
    MODULE_SECTOR_ROTATION,
    ROLE_ENTRY,
    SOURCE_DC_SIGNAL_RECOMMENDATION,
    SOURCE_STRATEGY_SIGNAL,
)
from app.strategies.gamma_front import GammaFrontStrategy
from app.strategies.strategy_vote_adapters import (
    adapt_adaptive_dc_to_vote,
    adapt_gamma_front_to_vote,
    adapt_liquidity_void_to_vote,
    adapt_sector_rotation_to_vote,
)


T0_NS = 1_777_948_800_000_000_000
DECISION_UUID = "entry-expansion-spine-decision"


def _instrument(instrument_id: str, symbol: str) -> InstrumentProfile:
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


def _gamma_config() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        strategies=types.SimpleNamespace(
            dark_pool_enabled=True,
            options_flow_enabled=False,
            dark_pool_volume_threshold=2.0,
            min_confidence=0.65,
        )
    )


def _dark_pool_print(ts_ns: int, dollar_value: float, *, is_buy: bool = True) -> DarkPoolPrint:
    price = 100.0
    return DarkPoolPrint(
        symbol="ETH/USD",
        exchange_ts_ns=ts_ns,
        price=price,
        size=dollar_value / price,
        exchange="DARK",
        is_buy=is_buy,
        venue="dark_pool",
    )


def _assert_entry_vote_metadata(vote: StrategyVote, *, module: str, source_output_type: str) -> None:
    metadata = vote.metadata
    assert metadata["source_module"] == module
    assert metadata["source_output_type"] == source_output_type
    assert metadata["contribution_role"] == ROLE_ENTRY
    assert metadata["fresh_entry_authorized"] is True
    assert metadata["protective_only"] is False
    assert metadata["requires_existing_position"] is False
    assert metadata["execution_candidate"] is True
    assert metadata["symbol"] == "ETH/USD"


def test_opportunity_ranking_imports_and_emits_passive_entry_ranking_evidence():
    ranker = OpportunityRanker()
    report = ranker.rank(
        candidates=[
            ("eth-usd", "gamma_front", Decimal("40.0"), Decimal("0.80"), Decimal("3000")),
            ("btc-usd", "adaptive_dc", Decimal("12.0"), Decimal("0.70"), Decimal("3000")),
        ],
        instruments={
            "eth-usd": _instrument("eth-usd", "ETH/USD"),
            "btc-usd": _instrument("btc-usd", "BTC/USD"),
        },
        existing_exposures={"BTC/USD": Decimal("1000")},
        correlation_pairs={("eth-usd", "BTC/USD"): Decimal("0.10")},
        total_equity=Decimal("20000"),
        available_capital=Decimal("10000"),
        timestamp_ns=T0_NS,
    )

    assert report.timestamp_ns == T0_NS
    assert report.total_ranked == 2
    assert report.top_opportunity == "ETH/USD"
    assert report.opportunities[0].rank == 1
    assert report.opportunities[0].symbol == "ETH/USD"
    assert report.opportunities[0].strategy_id == "gamma_front"
    assert report.opportunities[0].net_edge_after_all > Decimal("0")
    assert report.opportunities[0].grade in {
        OpportunityGrade.B,
        OpportunityGrade.C,
        OpportunityGrade.D,
    }
    assert report.opportunities[0].skip is False

    ranking_metadata = {
        "source_module": "opportunity_ranking",
        "contribution_role": "passive_entry_ranking",
        "fresh_entry_authorized": False,
        "execution_candidate": False,
        "ranking_authority": False,
        "allocation_authority": False,
        "execution_authority": False,
        "top_opportunity": report.top_opportunity,
        "top_opportunity_score": str(report.top_opportunity_score),
    }
    assert ranking_metadata["source_module"] == "opportunity_ranking"
    assert ranking_metadata["contribution_role"] == "passive_entry_ranking"
    assert ranking_metadata["fresh_entry_authorized"] is False
    assert ranking_metadata["execution_candidate"] is False
    assert ranking_metadata["allocation_authority"] is False
    assert ranking_metadata["execution_authority"] is False


def test_gamma_front_emits_governed_entry_candidate_vote_without_execution_authority():
    strategy = GammaFrontStrategy(config=_gamma_config(), symbol="ETH/USD")

    for i in range(5):
        assert strategy.update_dark_pool(_dark_pool_print(T0_NS + i, 100_000.0)) is None

    signal = strategy.update_dark_pool(_dark_pool_print(T0_NS + 10, 1_000_000.0))
    assert signal is not None
    assert signal.strategy == "gamma_front"
    assert signal.side == "buy"
    assert signal.quantity > 0
    assert signal.metadata["quantity_semantics"] == "provisional_risk_fraction_0_to_1"

    vote = adapt_gamma_front_to_vote(
        signal,
        exchange_ts_ns=signal.exchange_ts_ns,
        decision_uuid=DECISION_UUID,
    )

    assert isinstance(vote, StrategyVote)
    assert vote.strategy_id == StrategyID.GAMMA_FRONT.value
    assert vote.signal == SignalType.BUY.value
    _assert_entry_vote_metadata(
        vote,
        module=MODULE_GAMMA_FRONT,
        source_output_type=SOURCE_STRATEGY_SIGNAL,
    )
    assert vote.metadata["adapter_name"] == "adapt_gamma_front_to_vote"
    assert vote.metadata["sizing_semantics"] == "provisional_risk_fraction_not_physical_quantity"
    assert vote.metadata["quantity_semantics"] == "provisional_risk_fraction_0_to_1"
    assert vote.metadata["print_ratio"] >= 2.0


def test_adaptive_dc_emits_governed_entry_candidate_vote_without_direct_execution():
    engine = AdaptiveDC(initial_theta=Decimal("0.005"))
    first_tick = DCMarketTick(
        symbol="ETH/USD",
        price=Decimal("100.00"),
        timestamp_ns=T0_NS,
        book_integrity=BookIntegrity.HEALTHY,
        toxicity_level=ToxicityLevel.BENIGN,
        replay_mode=ReplayMode.REPLAY,
        execution_mode=ExecutionMode.REPLAY,
    )
    second_tick = DCMarketTick(
        symbol="ETH/USD",
        price=Decimal("101.00"),
        timestamp_ns=T0_NS + 10_000_000,
        book_integrity=BookIntegrity.HEALTHY,
        toxicity_level=ToxicityLevel.BENIGN,
        replay_mode=ReplayMode.REPLAY,
        execution_mode=ExecutionMode.REPLAY,
    )

    event_0, assessment_0, recommendation_0 = engine.process_tick(first_tick)
    assert event_0 is not None
    assert assessment_0 is not None
    assert recommendation_0 is None

    event_1, assessment_1, recommendation_1 = engine.process_tick(second_tick)
    assert event_1 is not None
    assert assessment_1 is not None
    assert recommendation_1 is not None

    vote = adapt_adaptive_dc_to_vote(
        recommendation_1,
        exchange_ts_ns=second_tick.timestamp_ns,
        decision_uuid=DECISION_UUID,
    )

    assert isinstance(vote, StrategyVote)
    assert vote.strategy_id == StrategyID.ADAPTIVE_DC.value
    assert vote.signal == SignalType.BUY.value
    _assert_entry_vote_metadata(
        vote,
        module=MODULE_ADAPTIVE_DC,
        source_output_type=SOURCE_DC_SIGNAL_RECOMMENDATION,
    )
    assert vote.metadata["adapter_name"] == "adapt_adaptive_dc_to_vote"
    assert vote.metadata["recommendation_semantics"] == "entry_candidate_only_governed_path_required"
    assert Decimal(vote.metadata["theta"]) == engine.theta


def test_existing_entry_adapters_remain_entry_metadata_only():
    from app.models.signals import StrategySignal

    sector_signal = StrategySignal(
        strategy="sector_rotation",
        symbol="ETH/USD",
        side="buy",
        confidence=0.75,
        quantity=0.25,
        exchange_ts_ns=T0_NS,
        reason="entry_expansion_sector_rotation",
    )
    liquidity_signal = StrategySignal(
        strategy="liquidity_void",
        symbol="ETH/USD",
        side="buy",
        confidence=0.72,
        quantity=0.20,
        exchange_ts_ns=T0_NS,
        reason="entry_expansion_liquidity_void",
        metadata={"spread_bps": 4.0, "tpe_confidence": 0.7},
    )

    sector_vote = adapt_sector_rotation_to_vote(sector_signal, T0_NS, DECISION_UUID)
    liquidity_vote = adapt_liquidity_void_to_vote(liquidity_signal, T0_NS, DECISION_UUID)

    _assert_entry_vote_metadata(
        sector_vote,
        module=MODULE_SECTOR_ROTATION,
        source_output_type=SOURCE_STRATEGY_SIGNAL,
    )
    _assert_entry_vote_metadata(
        liquidity_vote,
        module=MODULE_LIQUIDITY_VOID,
        source_output_type=SOURCE_STRATEGY_SIGNAL,
    )
    assert liquidity_vote.metadata[KEY_FEED_STATUS] == FEED_REAL
    assert liquidity_vote.metadata["activation_path"] == "governed_observed_pair_active_candidate"
    assert (
        liquidity_vote.metadata["active_promotion_requires"]
        == "fusion_router_admission_same_candle_netedge_and_broker_guards"
    )


def test_entry_expansion_modules_do_not_directly_execute_or_activate_dormant_authority():
    forbidden_tokens = (
        "ExecutionEngine",
        "OrderRouter",
        "PaperBroker",
        "broker_adapter",
        "live_broker",
        "submit_order",
        "_execute_signal",
        "NetEdgeGovernor",
        "TradeEfficiencyGovernor",
        "StrategyAllocator",
        "SovereignGovernor",
    )
    surfaces = (
        OpportunityRanker,
        GammaFrontStrategy,
        AdaptiveDC,
        adapt_gamma_front_to_vote,
        adapt_adaptive_dc_to_vote,
    )

    for surface in surfaces:
        source = inspect.getsource(surface)
        for token in forbidden_tokens:
            assert token not in source
