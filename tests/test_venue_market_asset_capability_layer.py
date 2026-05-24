from __future__ import annotations

from app.config import Config
from app.market.capability_registry import build_default_capability_registry
from app.market.venue_capabilities import PortalSelectionRequest, classify_quote_session
from main import (
    get_active_capability_candidates,
    get_active_symbols,
    resolve_runtime_portal,
    resolve_runtime_universe,
)


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
        capability_discovery_mode="active_markets",
    )
    assert get_active_symbols(config) == {"BTC/USD", "ETH/USD", "SOL/USD"}


def test_legacy_crypto_only_capability_discovery_mode_preserves_old_surface():
    config = Config(
        broker_mode="paper",
        active_markets=["crypto"],
        symbol_universe=["BTC/USD", "ETH/USD", "SOL/USD", "AAPL", "SPY"],
        capability_discovery_mode="active_markets",
    )

    candidates = get_active_capability_candidates(config)
    identities = {(candidate.venue_id, candidate.asset_class, candidate.normalized_symbol) for candidate in candidates}

    assert get_active_symbols(config) == {"BTC/USD", "ETH/USD", "SOL/USD"}
    assert ("kraken", "crypto", "BTC/USD") in identities
    assert ("alpaca", "crypto", "BTC/USD") in identities
    assert ("alpaca", "equity", "AAPL") not in identities
    assert ("alpaca", "etf", "SPY") not in identities


def test_registry_discovery_obeys_active_market_universe_filter():
    config = Config(
        broker_mode="paper",
        active_markets=["crypto"],
        symbol_universe=["BTC/USD", "AAPL", "SPY"],
        capability_discovery_mode="registry",
        capability_discovery_asset_classes=["crypto", "equity", "etf"],
    )

    candidates = get_active_capability_candidates(config)
    identities = {(candidate.venue_id, candidate.asset_class, candidate.normalized_symbol) for candidate in candidates}

    assert ("kraken", "crypto", "BTC/USD") in identities
    assert ("alpaca", "crypto", "BTC/USD") in identities
    assert ("alpaca", "equity", "AAPL") not in identities
    assert ("alpaca", "etf", "SPY") not in identities
    assert get_active_symbols(config) == {"BTC/USD"}


def test_multi_market_config_allows_authorized_symbols_from_included_markets():
    config = Config(
        broker_mode="paper",
        active_markets=["crypto", "equity", "etf"],
        symbol_universe=["BTC/USD", "AAPL", "SPY"],
        capability_discovery_mode="registry",
        capability_discovery_asset_classes=["crypto", "equity", "etf"],
    )

    candidates = get_active_capability_candidates(config)
    identities = {(candidate.venue_id, candidate.asset_class, candidate.normalized_symbol) for candidate in candidates}

    assert get_active_symbols(config) == {"BTC/USD", "AAPL", "SPY"}
    assert ("kraken", "crypto", "BTC/USD") in identities
    assert ("alpaca", "crypto", "BTC/USD") in identities
    assert ("alpaca", "equity", "AAPL") in identities
    assert ("alpaca", "etf", "SPY") in identities


def test_explicit_watchlist_cannot_leak_disallowed_asset_classes():
    config = Config(
        broker_mode="paper",
        active_markets=["crypto"],
        runtime_watchlist=["BTC/USD", "AAPL", "SPY"],
        symbol_universe=["BTC/USD", "AAPL", "SPY"],
    )

    resolution = resolve_runtime_universe(config)

    assert resolution.symbols == ("BTC/USD",)
    assert get_active_symbols(config) == {"BTC/USD"}


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
    assert result.selected.default_order_type == "limit"
    assert result.selected.default_time_in_force == "DAY"


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
    assert alpaca_crypto[0].supported_order_types == frozenset({"limit"})
    assert alpaca_crypto[0].supported_actions == frozenset({"buy", "sell_to_close"})
    assert alpaca_crypto[0].supported_time_in_force == frozenset({"GTC", "IOC"})
    assert alpaca_crypto[0].default_order_type == "limit"
    assert alpaca_crypto[0].default_time_in_force == "GTC"
    assert alpaca_crypto[0].min_notional is not None
    assert str(alpaca_crypto[0].min_notional) == "10.00"
    assert alpaca_crypto[0].order_constraint_source == "alpaca_crypto_orders_support_gtc_ioc_not_day"


def test_alpaca_crypto_supports_sell_to_close_but_not_sell_short():
    registry = build_default_capability_registry()
    sell_to_close = registry.resolve(
        PortalSelectionRequest(
            symbol="ETH/USD",
            asset_class="crypto",
            action="sell_to_close",
            order_type="limit",
            time_in_force="GTC",
            policy_mode="explicit_preferred_venue",
            preferred_venue="alpaca_paper",
        )
    )
    sell_short = registry.resolve(
        PortalSelectionRequest(
            symbol="ETH/USD",
            asset_class="crypto",
            action="sell_short",
            order_type="limit",
            time_in_force="GTC",
            policy_mode="explicit_preferred_venue",
            preferred_venue="alpaca_paper",
        )
    )

    assert sell_to_close.ready is True
    assert sell_to_close.selected is not None
    assert sell_to_close.selected.portal_name == "alpaca_paper"
    assert sell_short.ready is False
    assert any("ACTION_UNSUPPORTED" in reasons for reasons in sell_short.rejected.values())


def test_session_aware_classification_keeps_closed_equity_visible_but_blocked():
    config = Config(
        broker_mode="paper",
        active_markets=["equity"],
        symbol_universe=["AAPL"],
        capability_discovery_mode="registry",
        capability_discovery_asset_classes=["equity"],
    )
    candidates = get_active_capability_candidates(config)
    equity = next(candidate for candidate in candidates if candidate.normalized_symbol == "AAPL")

    classification = classify_quote_session(
        equity,
        market_session_open=False,
        quote_present=True,
        quote_fresh=False,
    )

    assert classification.raw_symbol == "AAPL"
    assert classification.portal_name == "alpaca_paper"
    assert classification.session_state == "closed"
    assert "MARKET_CLOSED" in classification.reason_codes
    assert "SESSION_CLOSED_STALE_QUOTE" in classification.reason_codes
    assert "CAPABILITY_UNSUPPORTED" not in classification.reason_codes
    assert classification.tradable_now is False


def test_crypto_quote_classification_does_not_inherit_equity_market_close():
    config = Config(
        broker_mode="paper",
        active_markets=["crypto"],
        symbol_universe=["BTC/USD"],
        capability_discovery_mode="registry",
        capability_discovery_asset_classes=["crypto"],
    )
    candidates = get_active_capability_candidates(config)
    alpaca_crypto = next(candidate for candidate in candidates if candidate.venue_id == "alpaca")

    classification = classify_quote_session(
        alpaca_crypto,
        market_session_open=False,
        quote_present=True,
        quote_fresh=True,
        spread_bps=1,
    )

    assert classification.session_state == "continuous"
    assert classification.reason_codes == ("FRESH_QUOTE_AVAILABLE",)
    assert "MARKET_CLOSED" not in classification.reason_codes
    assert classification.tradable_now is True


def test_alpaca_paper_equity_and_etf_can_use_buy_limit_day_when_supported():
    registry = build_default_capability_registry()

    for symbol, asset_class in (("AAPL", "equity"), ("SPY", "etf")):
        result = registry.resolve(
            PortalSelectionRequest(
                symbol=symbol,
                asset_class=asset_class,
                action="buy",
                order_type="limit",
                time_in_force="DAY",
                policy_mode="explicit_preferred_venue",
                preferred_venue="alpaca_paper",
            )
        )

        assert result.ready is True
        assert result.selected is not None
        assert result.selected.portal_name == "alpaca_paper"
        assert result.selected.default_time_in_force == "DAY"
        assert result.selected.live_blocked is True


def test_alpaca_paper_crypto_blocks_buy_limit_day_and_selects_allowed_default_tif():
    registry = build_default_capability_registry()
    day_result = registry.resolve(
        PortalSelectionRequest(
            symbol="SOL/USD",
            asset_class="crypto",
            action="buy",
            order_type="limit",
            time_in_force="DAY",
            policy_mode="explicit_preferred_venue",
            preferred_venue="alpaca_paper",
        )
    )

    assert day_result.ready is False
    assert "TIME_IN_FORCE_UNSUPPORTED" in day_result.reason_codes or any(
        "TIME_IN_FORCE_UNSUPPORTED" in reasons for reasons in day_result.rejected.values()
    )

    config = Config(
        broker_mode="paper",
        active_markets=["crypto"],
        symbol_universe=["SOL/USD"],
        portal_selection_policy="explicit_preferred_venue",
        preferred_trading_portal="alpaca_paper",
    )
    runtime_result = resolve_runtime_portal(config, symbol="SOL/USD", asset_class="crypto")

    assert runtime_result.ready is True
    assert runtime_result.selected is not None
    assert runtime_result.selected.default_order_type == "limit"
    assert runtime_result.selected.default_time_in_force == "GTC"
    assert runtime_result.selected.default_time_in_force in runtime_result.selected.supported_time_in_force
    assert "DAY" not in runtime_result.selected.supported_time_in_force


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
    alpaca_crypto = [
        candidate
        for candidate in candidates
        if candidate.venue_id == "alpaca" and candidate.asset_class == "crypto" and candidate.normalized_symbol == "BTC/USD"
    ]
    assert len(alpaca_crypto) == 1
    assert alpaca_crypto[0].default_order_type == "limit"
    assert alpaca_crypto[0].default_time_in_force == "GTC"
    assert "DAY" not in alpaca_crypto[0].supported_time_in_force
