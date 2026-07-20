from __future__ import annotations

import sqlite3
import time
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from app.api.operator_paper_supervisor import (
    OperatorPaperSupervisor,
    PaperSupervisorConfig,
    ProcessStartSpec,
)
from app.config import Config
from app.instrument_registry import InstrumentRegistry
from app.market.capability_registry import (
    BROKER_CATALOG_REQUIRED,
    build_alpaca_crypto_capability_registry,
    build_alpaca_crypto_universe,
    build_default_capability_registry,
    normalize_alpaca_crypto_catalog,
    validate_alpaca_crypto_capability_evidence,
)
from app.market.venue_capabilities import PortalSelectionRequest
from app.state.state_store import StateStore
from main import RuntimeUniverseResolution, resolve_runtime_feed_symbols, resolve_runtime_universe


ACCOUNT_SUFFIX = "045ded"
BASE_NS = 1_784_000_000_000_000_000


def _asset(
    symbol: str,
    *,
    asset_id: str | None = None,
    status: str = "active",
    tradable: bool = True,
    fractionable: bool = True,
    marginable: bool = False,
    shortable: bool = False,
    min_order_size: object = "0.00001000",
    min_trade_increment: object = "0.000000001",
    price_increment: object = "0.01",
) -> dict:
    return {
        "id": asset_id or f"asset-{symbol.replace('/', '').lower()}",
        "class": "crypto",
        "exchange": "CRYPTO",
        "symbol": symbol,
        "status": status,
        "tradable": tradable,
        "fractionable": fractionable,
        "marginable": marginable,
        "shortable": shortable,
        "min_order_size": min_order_size,
        "min_trade_increment": min_trade_increment,
        "price_increment": price_increment,
    }


def _complete_payload() -> list[dict]:
    return [
        _asset("BTC/USD", asset_id="asset-btc", min_order_size="0.00001"),
        _asset("BTCUSD", asset_id="asset-btc", min_order_size="0.00001"),
        _asset("BTC%2FUSD", asset_id="asset-btc", min_order_size="0.00001"),
        _asset("ETH/USD", min_order_size="0.0001", price_increment="0.01"),
        _asset("DOGE/USD", min_order_size="1", min_trade_increment="0.1", price_increment="0.000001"),
        _asset("ADA/USD", status="inactive"),
        _asset("MARGIN/USD", marginable=True),
        _asset("SHORT/USD", shortable=True),
        _asset("NOPREC/USD", min_trade_increment=None),
    ]


def _evidence(
    *,
    observed_at_ns: int = BASE_NS,
    valid_until_ns: int = BASE_NS + 3_600_000_000_000,
    as_of_ns: int = BASE_NS + 1_000_000_000,
    payload: list[dict] | None = None,
):
    catalog = normalize_alpaca_crypto_catalog(
        payload if payload is not None else _complete_payload(),
        observed_at_ns=observed_at_ns,
        valid_until_ns=valid_until_ns,
        expected_account_suffix=ACCOUNT_SUFFIX,
        actual_account_suffix=ACCOUNT_SUFFIX,
    )
    universe = build_alpaca_crypto_universe(
        catalog,
        as_of_ns=as_of_ns,
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
        market_data_symbols=("BTC/USD", "ETHUSD", "DOGE/USD", "ADA/USD", "MARGIN/USD", "SHORT/USD", "NOPREC/USD"),
        priority_symbols=("ETH/USD", "BTC/USD"),
        held_symbols=("SOLUSD",),
        open_order_symbols=("ADA/USD",),
    )
    return catalog, universe


def _persist(path: Path, *, wall_clock: bool = False):
    if wall_clock:
        current = time.time_ns()
        catalog, universe = _evidence(
            observed_at_ns=current - 1_000_000_000,
            valid_until_ns=current + 3_600_000_000_000,
            as_of_ns=current,
        )
    else:
        catalog, universe = _evidence()
    store = StateStore(str(path))
    assert store.persist_broker_crypto_catalog_universe(catalog, universe) == "persisted"
    store.close()
    return catalog, universe


def test_complete_catalog_normalizes_exact_decimals_aliases_and_reason_coded_universe():
    catalog, universe = _evidence()

    assert catalog.status == "VALID"
    assert len(catalog.assets) == 7
    btc = next(asset for asset in catalog.assets if asset.normalized_symbol == "BTC/USD")
    assert btc.aliases == ("BTC/USD", "BTC%2FUSD", "BTCUSD")
    assert btc.min_order_size == Decimal("0.00001")
    assert btc.min_trade_increment == Decimal("0.000000001")
    assert btc.price_increment == Decimal("0.01")
    assert type(btc.min_trade_increment) is Decimal
    assert universe.status == "READY"
    assert universe.entry_symbols == ("ETH/USD", "BTC/USD", "DOGE/USD")
    assert universe.monitor_symbols == ("ADA/USD", "SOL/USD")
    assert universe.runtime_symbols == ("ETH/USD", "BTC/USD", "DOGE/USD", "ADA/USD", "SOL/USD")

    exclusions = {item.symbol: item.reason_codes for item in universe.memberships if not item.included_for_entry}
    assert "BROKER_ASSET_NOT_ACTIVE" in exclusions["ADA/USD"]
    assert "CRYPTO_MARGIN_CLAIM_CONFLICT" in exclusions["MARGIN/USD"]
    assert "CRYPTO_SHORT_CLAIM_CONFLICT" in exclusions["SHORT/USD"]
    assert "MIN_TRADE_INCREMENT_INVALID" in exclusions["NOPREC/USD"]
    assert exclusions["SOL/USD"] == ("BROKER_ASSET_NOT_IN_CATALOG",)


def test_catalog_identity_is_deterministic_across_broker_row_reordering():
    forward, _ = _evidence(payload=_complete_payload())
    reverse, _ = _evidence(payload=list(reversed(_complete_payload())))

    assert reverse.catalog_snapshot_id == forward.catalog_snapshot_id
    assert reverse.snapshot_hash == forward.snapshot_hash
    assert [item.to_dict() for item in reverse.assets] == [item.to_dict() for item in forward.assets]


def test_conflicting_duplicate_symbol_is_excluded_without_hiding_other_eligible_assets():
    catalog, universe = _evidence(
        payload=[
            _asset("BTC/USD", asset_id="asset-btc-a"),
            _asset("BTCUSD", asset_id="asset-btc-b"),
            _asset("ETH/USD", asset_id="asset-eth"),
        ]
    )

    btc = next(asset for asset in catalog.assets if asset.normalized_symbol == "BTC/USD")
    btc_membership = next(item for item in universe.memberships if item.symbol == "BTC/USD")

    assert catalog.status == "VALID"
    assert "CATALOG_ASSET_EXCLUSIONS_PRESENT" in catalog.reason_codes
    assert btc.capability_valid is False
    assert "DUPLICATE_SYMBOL_CAPABILITY_CONFLICT" in btc.reason_codes
    assert btc_membership.included_for_entry is False
    assert "DUPLICATE_SYMBOL_CAPABILITY_CONFLICT" in btc_membership.reason_codes
    assert universe.entry_symbols == ("ETH/USD",)


@pytest.mark.parametrize(
    ("override", "expected_reason"),
    [
        ({"tradable": False}, "BROKER_ASSET_NOT_TRADABLE"),
        ({"fractionable": False}, "BROKER_ASSET_NOT_FRACTIONABLE"),
        ({"marginable": True}, "CRYPTO_MARGIN_CLAIM_CONFLICT"),
        ({"shortable": True}, "CRYPTO_SHORT_CLAIM_CONFLICT"),
        ({"asset_id": {"not": "a string"}}, "BROKER_ASSET_ID_INVALID"),
        ({"min_order_size": 0.1}, "MIN_ORDER_SIZE_INVALID"),
        ({"min_trade_increment": "NaN"}, "MIN_TRADE_INCREMENT_NONPOSITIVE_OR_NONFINITE"),
        ({"price_increment": "0"}, "PRICE_INCREMENT_NONPOSITIVE_OR_NONFINITE"),
    ],
)
def test_malformed_or_conflicting_broker_capability_fails_closed(override, expected_reason):
    catalog, universe = _evidence(payload=[_asset("TEST/USD", **override)])

    assert catalog.status == "VALID"
    assert catalog.assets[0].capability_valid is False
    assert expected_reason in catalog.assets[0].reason_codes
    assert universe.status == "BLOCKED"
    assert universe.entry_symbols == ()
    membership = next(item for item in universe.memberships if item.symbol == "TEST/USD")
    assert expected_reason in membership.reason_codes


@pytest.mark.parametrize(
    ("universe_overrides", "expected_reason"),
    [
        ({"actual_account_suffix": "104e2a"}, "CATALOG_ACCOUNT_BINDING_MISMATCH"),
        ({"account_status": "INACTIVE"}, "BROKER_ACCOUNT_NOT_ACTIVE"),
        ({"crypto_status": "INACTIVE"}, "BROKER_CRYPTO_PERMISSION_NOT_ACTIVE"),
        ({"trading_blocked": True}, "BROKER_TRADING_BLOCKED_OR_UNKNOWN"),
        ({"execution_adapter_available": False}, "ALPACA_PAPER_EXECUTION_ADAPTER_UNAVAILABLE"),
        ({"funded_quote_currencies": ()}, "QUOTE_CURRENCY_NOT_FUNDED"),
        ({"market_data_symbols": ()}, "MARKET_DATA_COVERAGE_MISSING"),
    ],
)
def test_account_adapter_funding_and_market_data_intersection_refuses(universe_overrides, expected_reason):
    catalog, _ = _evidence(payload=[_asset("BTC/USD")])
    values = {
        "as_of_ns": BASE_NS + 1,
        "expected_account_suffix": ACCOUNT_SUFFIX,
        "actual_account_suffix": ACCOUNT_SUFFIX,
        "account_status": "ACTIVE",
        "crypto_status": "ACTIVE",
        "trading_blocked": False,
        "account_blocked": False,
        "trade_suspended_by_user": False,
        "execution_adapter": "alpaca_paper_rest",
        "execution_adapter_available": True,
        "funded_quote_currencies": ("USD",),
        "market_data_symbols": ("BTC/USD",),
    }
    values.update(universe_overrides)

    universe = build_alpaca_crypto_universe(catalog, **values)

    assert universe.status == "BLOCKED"
    assert universe.entry_symbols == ()
    assert expected_reason in universe.memberships[0].reason_codes


def test_stale_catalog_blocks_new_entry_but_keeps_held_and_open_order_monitoring():
    catalog, _ = _evidence(payload=[_asset("BTC/USD"), _asset("ETH/USD")])
    universe = build_alpaca_crypto_universe(
        catalog,
        as_of_ns=catalog.valid_until_ns + 1,
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
        market_data_symbols=("BTC/USD", "ETH/USD"),
        held_symbols=("BTC/USD", "SOLUSD"),
        open_order_symbols=("ETHUSD",),
    )

    assert universe.status == "BLOCKED"
    assert universe.entry_symbols == ()
    assert universe.monitor_symbols == ("BTC/USD", "ETH/USD", "SOL/USD")
    assert all("CATALOG_STALE" in item.reason_codes for item in universe.memberships)


def test_monitor_only_symbols_never_project_as_entry_capabilities():
    catalog, universe = _evidence()
    registry = build_alpaca_crypto_capability_registry(catalog, universe)

    assert {capability.normalized_symbol for capability in registry.capabilities} == {
        "BTC/USD",
        "DOGE/USD",
        "ETH/USD",
    }
    for symbol in universe.monitor_symbols:
        result = registry.resolve(
            PortalSelectionRequest(
                symbol=symbol,
                asset_class="crypto",
                action="buy",
                order_type="limit",
                time_in_force="GTC",
                policy_mode="explicit_preferred_venue",
                preferred_venue="alpaca_paper",
            )
        )
        assert result.ready is False, symbol
        assert result.selected is None, symbol


def test_future_dated_universe_evidence_fails_closed():
    catalog, universe = _evidence()

    registry, status = validate_alpaca_crypto_capability_evidence(
        catalog,
        universe,
        expected_account_suffix=ACCOUNT_SUFFIX,
        as_of_ns=universe.observed_at_ns - 1,
    )

    assert registry.capabilities == ()
    assert status["status"] == "BLOCKED"
    assert "BROKER_CRYPTO_UNIVERSE_FROM_FUTURE" in status["reason_codes"]


def test_synthetic_larger_catalog_is_deterministic_and_has_no_static_six_filter():
    payload = [
        _asset(
            f"C{index:03d}/USD",
            min_order_size="1",
            min_trade_increment="0.01",
            price_increment="0.0001",
        )
        for index in range(256)
    ]
    catalog = normalize_alpaca_crypto_catalog(
        payload,
        observed_at_ns=BASE_NS,
        valid_until_ns=BASE_NS + 10_000,
        expected_account_suffix=ACCOUNT_SUFFIX,
        actual_account_suffix=ACCOUNT_SUFFIX,
    )
    reordered = normalize_alpaca_crypto_catalog(
        payload[::2] + payload[1::2],
        observed_at_ns=BASE_NS,
        valid_until_ns=BASE_NS + 10_000,
        expected_account_suffix=ACCOUNT_SUFFIX,
        actual_account_suffix=ACCOUNT_SUFFIX,
    )
    universe = build_alpaca_crypto_universe(
        catalog,
        as_of_ns=BASE_NS + 1,
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
        market_data_symbols=(row["symbol"] for row in payload),
    )

    assert reordered.snapshot_hash == catalog.snapshot_hash
    assert len(universe.entry_symbols) == 256
    assert "C255/USD" in universe.entry_symbols


def test_state_store_atomic_restart_read_and_tamper_detection(tmp_path: Path):
    path = tmp_path / "state.db"
    catalog, universe = _persist(path)

    restarted = StateStore(str(path), read_only=True)
    evidence = restarted.get_broker_crypto_capability_evidence(
        catalog_snapshot_id=catalog.catalog_snapshot_id,
        universe_snapshot_id=universe.universe_snapshot_id,
        strict=True,
    )
    restarted.close()

    assert evidence is not None
    assert evidence["catalog"]["snapshot_hash"] == catalog.snapshot_hash
    assert evidence["universe"]["universe_hash"] == universe.universe_hash
    assert evidence["catalog"]["assets"][0]["min_trade_increment"] == "0.000000001"
    assert evidence["universe"]["account_status"] == "ACTIVE"
    assert evidence["universe"]["crypto_status"] == "ACTIVE"
    assert evidence["universe"]["trading_blocked"] is False
    assert evidence["universe"]["execution_adapter"] == "alpaca_paper_rest"
    assert evidence["universe"]["funded_quote_currencies"] == ["USD"]
    assert "DOGE/USD" in evidence["universe"]["market_data_symbols"]
    assert evidence["universe"]["held_symbols"] == ["SOL/USD"]
    assert evidence["universe"]["open_order_symbols"] == ["ADA/USD"]
    restarted_registry, restarted_status = validate_alpaca_crypto_capability_evidence(
        evidence["catalog"],
        evidence["universe"],
        expected_account_suffix=ACCOUNT_SUFFIX,
        as_of_ns=BASE_NS + 2_000_000_000,
    )
    assert restarted_status["status"] == "VERIFIED"
    assert {item.normalized_symbol for item in restarted_registry.capabilities} == {
        "BTC/USD",
        "DOGE/USD",
        "ETH/USD",
    }

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE broker_crypto_universe_memberships SET included_for_entry = 0 WHERE universe_snapshot_id = ? AND symbol = ?",
            (universe.universe_snapshot_id, "BTC/USD"),
        )
        connection.commit()
    tampered = StateStore(str(path), read_only=True)
    with pytest.raises(RuntimeError, match="universe_hash_integrity_failed"):
        tampered.get_broker_crypto_capability_evidence(
            catalog_snapshot_id=catalog.catalog_snapshot_id,
            universe_snapshot_id=universe.universe_snapshot_id,
            strict=True,
        )
    tampered.close()


def test_state_store_persistence_is_idempotent_and_rejects_malformed_structures_atomically(tmp_path: Path):
    path = tmp_path / "state.db"
    catalog, universe = _evidence()
    store = StateStore(str(path))

    assert store.persist_broker_crypto_catalog_universe(catalog, universe) == "persisted"
    assert store.persist_broker_crypto_catalog_universe(catalog, universe) == "duplicate"

    malformed_catalog = catalog.to_dict()
    malformed_catalog["assets"][0]["aliases"] = "BTC/USD"
    malformed_identity = catalog.to_dict()
    malformed_identity["assets"][0]["asset_id"] = {"not": "a string"}
    malformed_universe = universe.to_dict()
    malformed_universe["memberships"][0]["priority_rank"] = 1.5

    with pytest.raises(ValueError, match="crypto_catalog_aliases_invalid"):
        store.persist_broker_crypto_catalog_universe(malformed_catalog, universe)
    with pytest.raises(ValueError, match="crypto_catalog_asset_id_invalid"):
        store.persist_broker_crypto_catalog_universe(malformed_identity, universe)
    with pytest.raises(ValueError, match="crypto_universe_priority_rank_invalid"):
        store.persist_broker_crypto_catalog_universe(catalog, malformed_universe)
    store.close()


def test_ready_label_cannot_bypass_recomputed_account_and_schema_evidence():
    catalog, universe = _evidence()
    inactive_account = replace(universe, account_status="INACTIVE")
    wrong_schema = replace(catalog, schema_version="untrusted_catalog_v0")

    inactive_registry, inactive_status = validate_alpaca_crypto_capability_evidence(
        catalog,
        inactive_account,
        expected_account_suffix=ACCOUNT_SUFFIX,
        as_of_ns=BASE_NS + 2_000_000_000,
    )
    schema_registry, schema_status = validate_alpaca_crypto_capability_evidence(
        wrong_schema,
        universe,
        expected_account_suffix=ACCOUNT_SUFFIX,
        as_of_ns=BASE_NS + 2_000_000_000,
    )

    assert inactive_account.status == "READY"
    assert inactive_registry.capabilities == ()
    assert "BROKER_CRYPTO_UNIVERSE_DERIVATION_INVALID" in inactive_status["reason_codes"]
    assert schema_registry.capabilities == ()
    assert "BROKER_CRYPTO_CATALOG_SCHEMA_INVALID" in schema_status["reason_codes"]


def test_persisted_labels_cannot_hide_bad_source_or_silent_asset_exclusion():
    catalog, universe = _evidence()
    invalid_asset = replace(catalog.assets[0], capability_valid=False, reason_codes=())
    bad_source = replace(catalog, source="operator_supplied_catalog")
    silent_exclusion = replace(catalog, assets=(invalid_asset, *catalog.assets[1:]))

    _bad_source_registry, bad_source_status = validate_alpaca_crypto_capability_evidence(
        bad_source,
        universe,
        expected_account_suffix=ACCOUNT_SUFFIX,
        as_of_ns=BASE_NS + 2_000_000_000,
    )
    _silent_registry, silent_status = validate_alpaca_crypto_capability_evidence(
        silent_exclusion,
        universe,
        expected_account_suffix=ACCOUNT_SUFFIX,
        as_of_ns=BASE_NS + 2_000_000_000,
    )

    assert "BROKER_CRYPTO_CATALOG_SOURCE_INVALID" in bad_source_status["reason_codes"]
    assert "BROKER_CRYPTO_INVALID_ASSET_REASON_MISSING" in silent_status["reason_codes"]


def test_short_account_suffix_never_satisfies_catalog_pin():
    catalog = normalize_alpaca_crypto_catalog(
        [_asset("BTC/USD")],
        observed_at_ns=BASE_NS,
        valid_until_ns=BASE_NS + 10,
        expected_account_suffix="abc",
        actual_account_suffix="abc",
    )

    assert catalog.status == "BLOCKED"
    assert "CATALOG_ACCOUNT_SUFFIX_NOT_PROVEN" in catalog.reason_codes


def test_non_string_account_suffix_and_malformed_inventory_symbols_fail_closed():
    catalog = normalize_alpaca_crypto_catalog(
        [_asset("BTC/USD")],
        observed_at_ns=BASE_NS,
        valid_until_ns=BASE_NS + 10,
        expected_account_suffix=ACCOUNT_SUFFIX,
        actual_account_suffix=[ACCOUNT_SUFFIX],
    )
    valid_catalog, _ = _evidence(payload=[_asset("BTC/USD")])
    universe = build_alpaca_crypto_universe(
        valid_catalog,
        as_of_ns=BASE_NS + 1,
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
        market_data_symbols=("BTC/USD",),
        held_symbols=("NOT-A-PAIR",),
        open_order_symbols=("ALSO-NOT-A-PAIR",),
    )

    assert catalog.status == "BLOCKED"
    assert "CATALOG_ACCOUNT_SUFFIX_NOT_PROVEN" in catalog.reason_codes
    assert universe.status == "BLOCKED"
    assert "BROKER_HELD_SYMBOL_INVALID" in universe.reason_codes
    assert "BROKER_OPEN_ORDER_SYMBOL_INVALID" in universe.reason_codes
    assert universe.entry_symbols == ()


def test_malformed_symbol_and_non_json_broker_value_fail_closed_without_crashing():
    malformed_symbol = normalize_alpaca_crypto_catalog(
        [_asset("BTC?X/USD")],
        observed_at_ns=BASE_NS,
        valid_until_ns=BASE_NS + 10,
        expected_account_suffix=ACCOUNT_SUFFIX,
        actual_account_suffix=ACCOUNT_SUFFIX,
    )
    non_json_value = normalize_alpaca_crypto_catalog(
        [_asset("BTC/USD", min_order_size=Decimal("0.0001"))],
        observed_at_ns=BASE_NS,
        valid_until_ns=BASE_NS + 10,
        expected_account_suffix=ACCOUNT_SUFFIX,
        actual_account_suffix=ACCOUNT_SUFFIX,
    )

    assert malformed_symbol.assets[0].capability_valid is False
    assert "BROKER_ASSET_SYMBOL_INVALID" in malformed_symbol.assets[0].reason_codes
    assert non_json_value.status == "BLOCKED"
    assert "CATALOG_PAYLOAD_NOT_JSON" in non_json_value.reason_codes


def test_static_alpaca_crypto_is_preserved_but_cannot_authorize_selection():
    static_registry = build_default_capability_registry()
    static = next(
        capability
        for capability in static_registry.capabilities_for_symbol("BTC/USD", environment="paper")
        if capability.venue_id == "alpaca"
    )
    static_result = static_registry.resolve(
        PortalSelectionRequest(
            symbol="BTC/USD",
            asset_class="crypto",
            policy_mode="explicit_preferred_venue",
            preferred_venue="alpaca_paper",
        )
    )
    catalog, universe = _evidence()
    dynamic_registry = build_alpaca_crypto_capability_registry(catalog, universe)
    dynamic_result = dynamic_registry.resolve(
        PortalSelectionRequest(
            symbol="DOGE/USD",
            asset_class="crypto",
            policy_mode="explicit_preferred_venue",
            preferred_venue="alpaca_paper",
            time_in_force="GTC",
        )
    )

    assert static.enabled is False
    assert static.fail_closed_reason_code == BROKER_CATALOG_REQUIRED
    assert static.execution_authority_source == "STATIC_REFERENCE_NEVER_EXECUTION_AUTHORITY"
    assert static_result.ready is False
    assert dynamic_result.ready is True
    assert dynamic_result.selected is not None
    assert dynamic_result.selected.broker_asset_id == "asset-dogeusd"
    assert dynamic_result.selected.min_quantity == Decimal("1")
    assert dynamic_result.selected.quantity_step == Decimal("0.1")
    assert dynamic_result.selected.price_increment == Decimal("0.000001")
    assert dynamic_result.selected.broker_marginable is False
    assert dynamic_result.selected.broker_shortable is False
    assert dynamic_result.selected.supported_actions == frozenset({"buy", "sell_to_close"})


def test_instrument_registry_crypto_is_alpaca_nonmargin_and_static_non_authoritative():
    for symbol in ("BTC/USD", "ETH/USD", "SOL/USD", "LTC/USD", "AVAX/USD", "LINK/USD"):
        instrument = InstrumentRegistry.get_instrument(symbol)

        assert instrument is not None
        assert instrument.exchange.value == "alpaca"
        assert instrument.margin_available is False
        assert instrument.execution_authorized is False
        assert instrument.constraint_source == "static_reference_non_authoritative"
        assert type(instrument.min_size_exact) is Decimal
        assert type(instrument.step_size_exact) is Decimal
        assert type(instrument.tick_size_exact) is Decimal


def test_main_resolver_requires_pinned_strict_durable_universe_and_ignores_static_subset(tmp_path: Path):
    path = tmp_path / "state.db"
    catalog, universe = _persist(path)
    config = Config(
        broker_mode="paper",
        active_markets=["crypto"],
        runtime_watchlist=["BTC/USD"],
        runtime_catalog_snapshot_id=catalog.catalog_snapshot_id,
        runtime_universe_snapshot_id=universe.universe_snapshot_id,
        runtime_capability_state_store_path=str(path),
    )

    resolution = resolve_runtime_universe(config, require_broker_catalog=True, as_of_ns=BASE_NS + 2_000_000_000)
    missing_pin = resolve_runtime_universe(
        Config(broker_mode="paper", active_markets=["crypto"], runtime_watchlist=["BTC/USD"]),
        require_broker_catalog=True,
        as_of_ns=BASE_NS,
    )
    static_reference = resolve_runtime_universe(config, require_broker_catalog=False)
    unknown_priority = resolve_runtime_universe(
        Config(
            broker_mode="paper",
            active_markets=["crypto"],
            runtime_watchlist=["NOTLISTED/USD"],
            runtime_catalog_snapshot_id=catalog.catalog_snapshot_id,
            runtime_universe_snapshot_id=universe.universe_snapshot_id,
            runtime_capability_state_store_path=str(path),
        ),
        require_broker_catalog=True,
        as_of_ns=BASE_NS + 2_000_000_000,
    )
    malformed_priority = resolve_runtime_universe(
        Config(
            broker_mode="paper",
            active_markets=["crypto"],
            runtime_watchlist=["NOT-A-PAIR"],
            runtime_catalog_snapshot_id=catalog.catalog_snapshot_id,
            runtime_universe_snapshot_id=universe.universe_snapshot_id,
            runtime_capability_state_store_path=str(path),
        ),
        require_broker_catalog=True,
        as_of_ns=BASE_NS + 2_000_000_000,
    )

    assert resolution.execution_authorized is True
    assert resolution.reason == "UNIVERSE_READY_FROM_BROKER_CATALOG"
    assert resolution.symbols == ("BTC/USD", "ETH/USD", "DOGE/USD", "ADA/USD", "SOL/USD")
    assert resolution.entry_symbols == ("BTC/USD", "ETH/USD", "DOGE/USD")
    assert resolution.capability_registry is not None
    assert {cap.normalized_symbol for cap in resolution.capability_registry.capabilities} == {
        "BTC/USD",
        "ETH/USD",
        "DOGE/USD",
    }
    assert missing_pin.reason == "BROKER_CRYPTO_UNIVERSE_PIN_REQUIRED"
    assert missing_pin.symbols == ()
    assert static_reference.symbols == ("BTC/USD",)
    assert static_reference.execution_authorized is False
    assert static_reference.reason == "STATIC_UNIVERSE_REFERENCE_ONLY"
    assert unknown_priority.symbols == ()
    assert unknown_priority.execution_authorized is False
    assert unknown_priority.reason == "PRIORITY_SYMBOL_NOT_IN_BROKER_RUNTIME_UNIVERSE:NOTLISTED/USD"
    assert malformed_priority.symbols == ()
    assert malformed_priority.execution_authorized is False
    assert malformed_priority.reason == "PRIORITY_SYMBOL_INVALID:NOT-A-PAIR"


def test_broker_derived_feed_enrollment_does_not_depend_on_static_instrument_rows():
    resolution = RuntimeUniverseResolution(
        symbols=("NEWCOIN/USD", "BTC/USD"),
        source="DURABLE_BROKER_CRYPTO_UNIVERSE",
        reason="UNIVERSE_READY_FROM_BROKER_CATALOG",
        execution_authorized=True,
        entry_symbols=("NEWCOIN/USD",),
        monitor_symbols=("BTC/USD",),
    )

    enrolled = resolve_runtime_feed_symbols(
        resolution.symbols,
        universe_resolution=resolution,
        provider_asset_classes={"crypto"},
    )
    unsupported_provider = resolve_runtime_feed_symbols(
        resolution.symbols,
        universe_resolution=resolution,
        provider_asset_classes={"equity"},
    )

    assert enrolled == ("BTC/USD", "NEWCOIN/USD")
    assert unsupported_provider == ()


class _FakeProcess:
    pid = 43210

    def poll(self):
        return None


class _FakeRunner:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.started_specs: list[ProcessStartSpec] = []

    def is_available(self, repo_root: Path):
        return repo_root == self.repo_root, None

    def start(self, spec: ProcessStartSpec):
        self.started_specs.append(spec)
        return _FakeProcess()


def _account_pin_ok(_env) -> dict:
    return {
        "source": "STAGE3_OFFLINE_ACCOUNT_PIN_FIXTURE",
        "status": "PASS",
        "reason_code": "ALPACA_PAPER_ACCOUNT_PIN_OK",
        "expected_suffix": ACCOUNT_SUFFIX,
        "actual_suffix": ACCOUNT_SUFFIX,
        "paper_account_pinned": True,
        "broker_read_occurred": False,
        "account_request_occurred": False,
        "broker_mutation_occurred": False,
        "secrets_values_exposed": False,
    }


def test_supervisor_passes_full_broker_universe_and_priority_cannot_grant_symbol(tmp_path: Path):
    path = tmp_path / "state.db"
    catalog, universe = _persist(path, wall_clock=True)
    runner = _FakeRunner(tmp_path)
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(
            repo_root=tmp_path,
            process_env={
                "APCA_API_KEY_ID": "test-paper-key",
                "APCA_API_SECRET_KEY": "test-paper-secret",
                "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            },
            state_store_path=str(path),
            catalog_snapshot_id=catalog.catalog_snapshot_id,
            universe_snapshot_id=universe.universe_snapshot_id,
        ),
        runner=runner,
        account_identity_checker=_account_pin_ok,
    )
    supervisor._paper_broker_preflight = {
        "status": "PASS",
        "reason_code": "PAPER_BROKER_PREFLIGHT_PASS",
        "account_identity_assertion": _account_pin_ok({}),
        "broker_call_occurred": False,
        "broker_mutation_occurred": False,
    }
    request = {
        "mode": "PAPER",
        "profile": "PAPER_EXPLORATION_ALPHA",
        "duration_seconds": 300,
        "watchlist": ["BTC/USD"],
        "approve_autonomous_paper": True,
    }

    snapshot = supervisor.status_snapshot()
    priority_refusal = supervisor.paper_start_request_refusal(dict(request, watchlist=["NOTLISTED/USD"]))
    result = supervisor.start_paper(request)

    assert snapshot["paper_start_allowed"] is True
    assert snapshot["broker_crypto_capability_evidence"]["durable_integrity_verified"] is True
    assert snapshot["watchlist_authority"] == "PRIORITY_ONLY_NOT_EXECUTION_ELIGIBILITY"
    assert result["allowed"] is True
    assert result["broker_call_occurred"] is False
    assert result["broker_mutation_occurred"] is False
    assert result["session"]["watchlist"] == ["BTC/USD", "ETH/USD", "DOGE/USD", "ADA/USD", "SOL/USD"]
    spec = runner.started_specs[0]
    watchlist_index = spec.command.index("-Watchlist")
    assert spec.command[watchlist_index + 1] == "BTC/USD,ETH/USD,DOGE/USD,ADA/USD,SOL/USD"
    assert spec.env["POVERTY_KILLER_CATALOG_SNAPSHOT_ID"] == catalog.catalog_snapshot_id
    assert spec.env["POVERTY_KILLER_UNIVERSE_SNAPSHOT_ID"] == universe.universe_snapshot_id
    assert priority_refusal == "PRIORITY_SYMBOL_NOT_ENTRY_ELIGIBLE"


def test_supervisor_rechecks_capability_freshness_immediately_before_process_start(tmp_path: Path, monkeypatch):
    path = tmp_path / "state.db"
    catalog, universe = _persist(path, wall_clock=True)
    runner = _FakeRunner(tmp_path)
    supervisor = OperatorPaperSupervisor(
        config=PaperSupervisorConfig(
            repo_root=tmp_path,
            process_env={
                "APCA_API_KEY_ID": "test-paper-key",
                "APCA_API_SECRET_KEY": "test-paper-secret",
                "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            },
            state_store_path=str(path),
            catalog_snapshot_id=catalog.catalog_snapshot_id,
            universe_snapshot_id=universe.universe_snapshot_id,
        ),
        runner=runner,
        account_identity_checker=_account_pin_ok,
    )
    supervisor._paper_broker_preflight = {
        "status": "PASS",
        "reason_code": "PAPER_BROKER_PREFLIGHT_PASS",
        "account_identity_assertion": _account_pin_ok({}),
        "broker_call_occurred": False,
        "broker_mutation_occurred": False,
    }
    original = supervisor._managed_crypto_capability_evidence
    calls = 0

    def expires_after_validation(*, account_suffix):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original(account_suffix=account_suffix)
        return None, {
            "status": "BLOCKED",
            "reason_code": "BROKER_CRYPTO_UNIVERSE_STALE",
            "runtime_symbols": list(universe.runtime_symbols),
            "broker_call_occurred": False,
            "broker_mutation_occurred": False,
        }

    monkeypatch.setattr(supervisor, "_managed_crypto_capability_evidence", expires_after_validation)
    result = supervisor.start_paper(
        {
            "mode": "PAPER",
            "profile": "PAPER_EXPLORATION_ALPHA",
            "duration_seconds": 300,
            "watchlist": ["BTC/USD"],
            "approve_autonomous_paper": True,
        }
    )

    assert result["allowed"] is False
    assert result["reason_code"] == "BROKER_CRYPTO_UNIVERSE_STALE"
    assert runner.started_specs == []
