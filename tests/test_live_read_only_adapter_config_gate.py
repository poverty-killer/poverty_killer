from __future__ import annotations

from decimal import Decimal

import pytest

from app.execution.live_read_only_adapter import (
    LiveReadOnlyBrokerAdapter,
    ReadOnlyAdapterConfig,
    ReadOnlyGateError,
)


T0_NS = 1_777_948_800_000_000_000


class FakeMixedBroker:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_balances(self):
        self.calls.append("fetch_balances")
        return (
            {
                "currency": "USD",
                "total": Decimal("1000.00"),
                "available": Decimal("950.00"),
                "source": "fake_read_only_balance",
                "snapshot_ts_ns": T0_NS,
            },
        )

    def fetch_positions(self):
        self.calls.append("fetch_positions")
        return (
            {
                "symbol": "ETH/USD",
                "instrument_id": "eth-usd",
                "quantity": Decimal("0.25"),
                "source": "fake_read_only_position",
                "snapshot_ts_ns": T0_NS,
            },
        )

    def fetch_normalized_open_orders(self):
        self.calls.append("fetch_normalized_open_orders")
        return (
            {
                "client_order_id": "client-1",
                "broker_order_id": "broker-1",
                "symbol": "ETH/USD",
                "remaining_quantity": Decimal("0.50"),
                "status": "open",
                "mapping_source": "fake_read_only_open_order",
                "snapshot_ts_ns": T0_NS,
            },
        )

    def fetch_fills(self, limit: int = 100):
        self.calls.append(f"fetch_fills:{limit}")
        return (
            {
                "venue_fill_id": "fill-1",
                "client_order_id": "client-1",
                "broker_order_id": "broker-1",
                "symbol": "ETH/USD",
                "quantity": Decimal("0.50"),
                "price": Decimal("2500.50"),
                "fee": Decimal("0.10"),
                "fee_currency": "USD",
                "exchange_ts_ns": T0_NS,
                "receive_ts_ns": T0_NS + 1,
                "source": "fake_read_only_fill",
            },
        )

    def get_order_status(self, order_id: str):
        self.calls.append(f"get_order_status:{order_id}")
        return {
            "client_order_id": "client-1",
            "broker_order_id": order_id,
            "status": "open",
            "source": "fake_read_only_status",
            "exchange_ts_ns": T0_NS,
            "receive_ts_ns": T0_NS + 1,
        }

    def submit_order(self, *_args, **_kwargs):
        self.calls.append("submit_order")
        raise AssertionError("mutation method must not be called")

    def cancel_order(self, *_args, **_kwargs):
        self.calls.append("cancel_order")
        raise AssertionError("mutation method must not be called")

    def replace_order(self, *_args, **_kwargs):
        self.calls.append("replace_order")
        raise AssertionError("mutation method must not be called")


def clean_config(**overrides) -> ReadOnlyAdapterConfig:
    data = {
        "read_only_enabled": True,
        "environment": "sandbox",
        "source": "fake_broker",
        "allow_mutation": False,
        "board_authorized_production_read": False,
        "account_id": "sandbox-account-1",
        "credentials_present": True,
        "credentials_required_for_call": True,
    }
    data.update(overrides)
    return ReadOnlyAdapterConfig(**data)


def test_config_gate_fails_closed_for_default_and_ambiguous_cases():
    source = FakeMixedBroker()
    default_adapter = LiveReadOnlyBrokerAdapter(source, ReadOnlyAdapterConfig())
    default_decision = default_adapter.validate_gate(receive_ts_ns=T0_NS)

    assert default_decision.ready is False
    assert "read_only_not_enabled" in default_decision.reason_codes
    assert "environment_missing" in default_decision.reason_codes
    assert "source_missing" in default_decision.reason_codes
    assert default_decision.mutation_allowed is False
    assert default_decision.side_effects == ()
    assert source.calls == []

    cases = {
        "read_only_not_enabled": {"read_only_enabled": False},
        "mutation_not_allowed": {"allow_mutation": True},
        "environment_missing": {"environment": None},
        "production_environment_not_board_authorized": {"environment": "production"},
        "source_missing": {"source": ""},
        "account_identity_missing": {"account_id": None},
    }
    for expected_reason, overrides in cases.items():
        adapter = LiveReadOnlyBrokerAdapter(FakeMixedBroker(), clean_config(**overrides))
        decision = adapter.validate_gate(
            receive_ts_ns=T0_NS,
            require_credentials=True,
            require_account_identity=True,
        )
        assert decision.ready is False
        assert expected_reason in decision.reason_codes


def test_credentials_are_lazy_but_missing_credentials_block_actual_read_call():
    source = FakeMixedBroker()
    adapter = LiveReadOnlyBrokerAdapter(source, clean_config(credentials_present=False))

    identity = adapter.get_account_identity(receive_ts_ns=T0_NS)
    assert identity["account_id"] == "sandbox-account-1"
    assert identity["read_only"] is True
    assert source.calls == []

    with pytest.raises(ReadOnlyGateError) as exc:
        adapter.fetch_balances(receive_ts_ns=T0_NS, require_credentials=True)

    assert exc.value.reason_codes == ("credentials_missing_for_read_call",)
    assert source.calls == []


def test_wrapper_method_surface_exposes_reads_only_and_no_mutation_methods():
    adapter = LiveReadOnlyBrokerAdapter(FakeMixedBroker(), clean_config())

    assert callable(adapter.get_account_identity)
    assert callable(adapter.fetch_balances)
    assert callable(adapter.fetch_positions)
    assert callable(adapter.fetch_open_orders)
    assert callable(adapter.fetch_recent_fills)
    assert callable(adapter.fetch_order_status_read_only)
    assert callable(adapter.get_exchange_truth_snapshot)

    for name in ("submit_order", "cancel_order", "replace_order", "place_order", "place_market_order", "place_limit_order"):
        assert not hasattr(adapter, name)
        with pytest.raises(AttributeError):
            getattr(adapter, name)


def test_read_methods_call_only_read_surfaces_even_when_underlying_can_mutate():
    source = FakeMixedBroker()
    adapter = LiveReadOnlyBrokerAdapter(source, clean_config())

    assert adapter.fetch_balances(receive_ts_ns=T0_NS) != ()
    assert adapter.fetch_positions(receive_ts_ns=T0_NS) != ()
    assert adapter.fetch_open_orders(receive_ts_ns=T0_NS) != ()
    assert adapter.fetch_recent_fills(receive_ts_ns=T0_NS, limit=3) != ()
    status = adapter.fetch_order_status_read_only("broker-1", receive_ts_ns=T0_NS)

    assert status["status"] == "open"
    assert source.calls == [
        "fetch_balances",
        "fetch_positions",
        "fetch_normalized_open_orders",
        "fetch_fills:3",
        "get_order_status:broker-1",
    ]
    assert "submit_order" not in source.calls
    assert "cancel_order" not in source.calls
    assert "replace_order" not in source.calls


def test_snapshot_shape_carries_account_environment_identity_and_contract_mapping():
    source = FakeMixedBroker()
    adapter = LiveReadOnlyBrokerAdapter(source, clean_config())
    snapshot = adapter.get_exchange_truth_snapshot(
        receive_ts_ns=T0_NS,
        asof_ts_ns=T0_NS - 1,
        require_credentials=True,
        require_account_identity=True,
    )
    mapping = snapshot.contract_mapping()

    assert snapshot.source == "fake_broker"
    assert snapshot.environment == "sandbox"
    assert snapshot.account_id == "sandbox-account-1"
    assert snapshot.account_identity_status == "known"
    assert snapshot.receive_ts_ns == T0_NS
    assert snapshot.asof_ts_ns == T0_NS - 1
    assert snapshot.read_only is True
    assert snapshot.mutation_allowed is False
    assert snapshot.balances[0]["available"] == Decimal("950.00")
    assert snapshot.positions[0]["instrument_id"] == "eth-usd"
    assert snapshot.open_orders[0]["broker_order_id"] == "broker-1"
    assert snapshot.recent_fills[0]["fee_currency"] == "USD"
    assert mapping["account_identity_source_environment_timestamp_25q"] is True
    assert mapping["balances_25q"] is True
    assert mapping["positions_25q"] is True
    assert mapping["open_orders_25o_25q"] is True
    assert mapping["recent_fills_25p_25q"] is True
    assert mapping["read_only_no_submit_cancel_25m_25r"] is True


def test_snapshot_timestamp_missing_or_stale_blocks_readiness_before_source_call():
    source = FakeMixedBroker()
    adapter = LiveReadOnlyBrokerAdapter(source, clean_config())

    missing = adapter.validate_gate(receive_ts_ns=None)
    stale = adapter.validate_gate(
        receive_ts_ns=T0_NS,
        current_ts_ns=T0_NS + 10_000_000_000,
        max_snapshot_age_ns=5_000_000_000,
    )
    with pytest.raises(ReadOnlyGateError) as exc:
        adapter.get_exchange_truth_snapshot(receive_ts_ns=0)

    assert missing.reason_codes == ("snapshot_timestamp_missing",)
    assert stale.reason_codes == ("snapshot_stale",)
    assert "snapshot_timestamp_missing" in exc.value.reason_codes
    assert source.calls == []
