from __future__ import annotations

import time
from collections.abc import Iterable

from app.api.operator_paper_supervisor import OperatorPaperSupervisor
from app.market.capability_registry import (
    BrokerCryptoCatalogSnapshot,
    BrokerCryptoUniverseSnapshot,
    VenueCapabilityRegistry,
    build_alpaca_crypto_capability_registry,
    build_alpaca_crypto_universe,
    normalize_alpaca_crypto_catalog,
    normalize_alpaca_crypto_symbol,
)
from app.state.state_store import StateStore


ACCOUNT_SUFFIX = "045ded"
DEFAULT_CRYPTO_SYMBOLS = (
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "LTC/USD",
    "AVAX/USD",
    "LINK/USD",
    "DOGE/USD",
)


def build_mock_broker_crypto_capability_evidence(
    symbols: Iterable[str] = DEFAULT_CRYPTO_SYMBOLS,
    *,
    now_ns: int | None = None,
) -> tuple[BrokerCryptoCatalogSnapshot, BrokerCryptoUniverseSnapshot]:
    """Build current offline evidence through the production capability owners."""
    normalized_symbols = tuple(
        dict.fromkeys(
            normalized
            for symbol in symbols
            if (normalized := normalize_alpaca_crypto_symbol(symbol))
        )
    )
    if not normalized_symbols:
        raise ValueError("mock_broker_crypto_symbols_required")
    observed_at_ns = int(now_ns or time.time_ns())
    catalog = normalize_alpaca_crypto_catalog(
        [
            {
                "id": f"test-asset-{symbol.replace('/', '').lower()}",
                "class": "crypto",
                "exchange": "CRYPTO",
                "symbol": symbol,
                "status": "active",
                "tradable": True,
                "fractionable": True,
                "marginable": False,
                "shortable": False,
                "min_order_size": "0.000000001",
                "min_trade_increment": "0.000000001",
                "price_increment": "0.000000001",
            }
            for symbol in normalized_symbols
        ],
        observed_at_ns=observed_at_ns - 1_000_000,
        valid_until_ns=observed_at_ns + 3_600_000_000_000,
        expected_account_suffix=ACCOUNT_SUFFIX,
        actual_account_suffix=ACCOUNT_SUFFIX,
    )
    universe = build_alpaca_crypto_universe(
        catalog,
        as_of_ns=observed_at_ns,
        expected_account_suffix=ACCOUNT_SUFFIX,
        actual_account_suffix=ACCOUNT_SUFFIX,
        account_status="ACTIVE",
        crypto_status="ACTIVE",
        trading_blocked=False,
        account_blocked=False,
        trade_suspended_by_user=False,
        execution_adapter="alpaca_paper_rest",
        execution_adapter_available=True,
        funded_quote_currencies=("USD",),
        market_data_symbols=normalized_symbols,
        priority_symbols=normalized_symbols,
    )
    return catalog, universe


def mock_broker_crypto_capability_registry(
    symbols: Iterable[str] = DEFAULT_CRYPTO_SYMBOLS,
) -> VenueCapabilityRegistry:
    catalog, universe = build_mock_broker_crypto_capability_evidence(symbols)
    return build_alpaca_crypto_capability_registry(catalog, universe)


def install_mock_broker_crypto_capability_evidence(
    supervisor: OperatorPaperSupervisor,
    symbols: Iterable[str] = DEFAULT_CRYPTO_SYMBOLS,
) -> tuple[BrokerCryptoCatalogSnapshot, BrokerCryptoUniverseSnapshot]:
    catalog, universe = build_mock_broker_crypto_capability_evidence(symbols)
    state_path = supervisor._state_store_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    store = StateStore(str(state_path))
    try:
        result = store.persist_broker_crypto_catalog_universe(catalog, universe)
        if result not in {"persisted", "duplicate"}:
            raise AssertionError(f"unexpected capability persistence result: {result}")
    finally:
        store.close()
    supervisor.config.catalog_snapshot_id = catalog.catalog_snapshot_id
    supervisor.config.universe_snapshot_id = universe.universe_snapshot_id
    return catalog, universe
