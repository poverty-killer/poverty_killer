from __future__ import annotations

from app.config import Config
from app.market.capability_registry import build_default_capability_registry
from app.market.venue_capabilities import PortalSelectionRequest
from main import get_active_capability_candidates, get_active_symbols, resolve_runtime_portal


def test_kraken_crypto_preservation_for_current_runtime_symbols():
    registry = build_default_capability_registry()

    for symbol in ("BTC/USD", "ETH/USD", "SOL/USD"):
        kraken = [
            cap
            for cap in registry.capabilities_for_symbol(symbol, environment="paper")
            if cap.venue_id == "kraken" and cap.asset_class == "crypto"
        ]
        assert len(kraken) == 1
        assert kraken[0].portal_name == "kraken_paper"
        assert kraken[0].execution_adapter == "sovereign_paper_broker"

    config = Config(
        broker_mode="paper",
        active_markets=["crypto"],
        symbol_universe=["BTC/USD", "ETH/USD", "SOL/USD"],
    )
    assert get_active_symbols(config) == {"BTC/USD", "ETH/USD", "SOL/USD"}


def test_alpaca_paper_equity_capability_is_selectable_by_operator_preference():
    config = Config(
        broker_mode="paper",
        active_markets=["equity"],
        symbol_universe=["AAPL"],
        portal_selection_policy="explicit_preferred_venue",
        preferred_trading_portal="alpaca_paper",
    )

    result = resolve_runtime_portal(config, symbol="AAPL", asset_class="equity")

    assert result.ready is True
    assert result.selected is not None
    assert result.selected.venue_id == "alpaca"
    assert result.selected.environment == "paper"
    assert result.selected.asset_class == "equity"
    assert result.selected.execution_adapter == "alpaca_paper_rest"
    assert result.selected.live_blocked is True


def test_alpaca_paper_etf_capability_is_distinct_and_etf_capable():
    registry = build_default_capability_registry()
    result = registry.resolve(
        PortalSelectionRequest(
            symbol="SPY",
            asset_class="etf",
            policy_mode="explicit_preferred_venue",
            preferred_venue="alpaca_paper",
        )
    )

    assert result.ready is True
    assert result.selected is not None
    assert result.selected.asset_class == "etf"
    assert result.selected.metadata["etf_capable"] is True


def test_alpaca_paper_crypto_capability_is_represented():
    registry = build_default_capability_registry()
    alpaca_crypto = [
        cap
        for cap in registry.capabilities_for_symbol("BTC/USD", environment="paper")
        if cap.venue_id == "alpaca" and cap.asset_class == "crypto"
    ]

    assert len(alpaca_crypto) == 1
    assert alpaca_crypto[0].quote_source == "alpaca_data_crypto_latest_quote"
    assert alpaca_crypto[0].execution_adapter == "alpaca_paper_rest"


def test_multi_venue_crypto_identity_does_not_collapse_to_plain_symbol():
    registry = build_default_capability_registry()
    caps = registry.capabilities_for_symbol("BTC/USD", environment="paper")
    keys = {cap.capability_key for cap in caps if cap.asset_class == "crypto"}

    assert "kraken_paper:crypto:BTC/USD" in keys
    assert "alpaca_paper:crypto:BTC/USD" in keys
    assert len(keys) == 2


def test_operator_preferred_alpaca_paper_selects_alpaca_when_supported():
    config = Config(
        broker_mode="paper",
        active_markets=["crypto"],
        symbol_universe=["BTC/USD"],
        portal_selection_policy="explicit_preferred_venue",
        preferred_trading_portal="alpaca_paper",
    )

    result = resolve_runtime_portal(config, symbol="BTC/USD", asset_class="crypto")

    assert result.ready is True
    assert result.selected is not None
    assert result.selected.portal_name == "alpaca_paper"


def test_unsupported_preferred_portal_fails_closed_without_fallback():
    config = Config(
        broker_mode="paper",
        active_markets=["equity"],
        symbol_universe=["AAPL"],
        portal_selection_policy="explicit_preferred_venue",
        preferred_trading_portal="kraken_paper",
        allow_portal_fallback=False,
    )

    result = resolve_runtime_portal(config, symbol="AAPL", asset_class="equity")

    assert result.ready is False
    assert result.reason_codes == ("PREFERRED_PORTAL_UNSUPPORTED",)


def test_ambiguous_crypto_fails_closed_when_capability_first_has_no_tiebreak():
    registry = build_default_capability_registry()
    result = registry.resolve(
        PortalSelectionRequest(
            symbol="BTC/USD",
            asset_class="crypto",
            policy_mode="capability_first",
        )
    )

    assert result.ready is False
    assert result.ambiguous is True
    assert result.reason_codes == ("AMBIGUOUS_PORTAL",)


def test_future_venues_are_represented_disabled_and_fail_closed():
    registry = build_default_capability_registry()
    coinbase = [cap for cap in registry.capabilities if cap.venue_id == "coinbase"]

    assert len(coinbase) == 1
    assert coinbase[0].enabled is False
    assert coinbase[0].disabled_reason == "ADAPTER_MISSING"
    assert coinbase[0].paper_mutation is False


def test_live_environment_remains_blocked():
    registry = build_default_capability_registry()
    result = registry.resolve(
        PortalSelectionRequest(
            symbol="AAPL",
            asset_class="equity",
            environment="live",
            policy_mode="explicit_preferred_venue",
            preferred_venue="alpaca_live_blocked",
        )
    )

    assert result.ready is False
    assert "LIVE_BLOCKED" in result.reason_codes or any(
        "LIVE_BLOCKED" in reasons for reasons in result.rejected.values()
    )


def test_capability_presence_does_not_authorize_mutation_by_default():
    registry = build_default_capability_registry()
    result = registry.resolve(
        PortalSelectionRequest(
            symbol="AAPL",
            asset_class="equity",
            policy_mode="explicit_preferred_venue",
            preferred_venue="alpaca_paper",
        )
    )
    candidate = result.selected

    assert candidate is not None
    assert candidate.paper_mutation is True
    assert candidate.mutation_authorized_by_default is False


def test_runtime_candidate_surface_is_no_longer_kraken_only():
    config = Config(
        broker_mode="paper",
        active_markets=["crypto", "equity", "etf"],
        symbol_universe=["BTC/USD", "AAPL", "SPY"],
    )

    candidates = get_active_capability_candidates(config)
    identities = {(candidate.venue_id, candidate.asset_class, candidate.normalized_symbol) for candidate in candidates}

    assert ("kraken", "crypto", "BTC/USD") in identities
    assert ("alpaca", "crypto", "BTC/USD") in identities
    assert ("alpaca", "equity", "AAPL") in identities
    assert ("alpaca", "etf", "SPY") in identities
    assert all(candidate.mutation_authorized is False for candidate in candidates)
