from __future__ import annotations

import pytest

from app.execution.alpaca_paper_adapter import (
    EXPECTED_ALPACA_PAPER_BASE_URL,
    AlpacaPaperBrokerAdapter,
    AlpacaPaperCredentials,
)
from app.execution.broker_gateway import BrokerGatewayError
from app.execution.broker_read_policy import (
    ACCOUNT_ACTIVITY_READS_ALLOWED_ENV,
    BROKER_MUTATION_NOT_AUTHORIZED,
    BROKER_READ_NOT_AUTHORIZED,
    FEE_HYDRATION_ALLOWED_ENV,
    PAPER_ASSET_CATALOG_READS,
    PAPER_SMOKE_STRICT_READS,
    PAPER_TCA_EXTENDED_READS,
    READ_ACCOUNT,
    READ_ACCOUNT_ACTIVITIES,
    READ_ASSET_CATALOG,
    READ_FEE_HYDRATION,
    READ_ORDERS,
    READ_POSITIONS,
    broker_read_allowed,
    broker_read_profile_for_name,
)


class CaptureTransport:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def request(self, **kwargs):
        self.calls.append(dict(kwargs))
        return 200, []


def _adapter(*, profile: str = PAPER_SMOKE_STRICT_READS, transport: CaptureTransport | None = None):
    return AlpacaPaperBrokerAdapter(
        AlpacaPaperCredentials(
            base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
            key_id="paper-key",
            secret_key="paper-secret",
        ),
        transport=transport or CaptureTransport(),
        read_profile=profile,
    )


def test_strict_smoke_allows_only_account_orders_positions():
    profile = broker_read_profile_for_name(PAPER_SMOKE_STRICT_READS)

    assert broker_read_allowed(READ_ACCOUNT, profile=profile) is True
    assert broker_read_allowed(READ_ORDERS, profile=profile) is True
    assert broker_read_allowed(READ_POSITIONS, profile=profile) is True
    assert broker_read_allowed(READ_ACCOUNT_ACTIVITIES, "FILL", profile=profile) is False
    assert broker_read_allowed(READ_FEE_HYDRATION, "CFEE,FEE", profile=profile) is False
    assert broker_read_allowed("whatever", profile=profile) is False
    assert profile.to_env()[ACCOUNT_ACTIVITY_READS_ALLOWED_ENV] == "0"
    assert profile.to_env()[FEE_HYDRATION_ALLOWED_ENV] == "0"


def test_extended_tca_profile_exists_but_is_not_default():
    default_profile = broker_read_profile_for_name(None)
    extended = broker_read_profile_for_name(PAPER_TCA_EXTENDED_READS)

    assert default_profile.name == PAPER_SMOKE_STRICT_READS
    assert extended.name == PAPER_TCA_EXTENDED_READS
    assert extended.allows(READ_ACCOUNT_ACTIVITIES, "FILL") is True
    assert extended.allows(READ_FEE_HYDRATION, "CFEE,FEE") is True
    assert extended.allows(READ_ACCOUNT_ACTIVITIES, "CFEE,FEE") is True
    assert extended.allows(READ_ACCOUNT_ACTIVITIES, "DIV") is False
    assert extended.allows(READ_ACCOUNT_ACTIVITIES) is False


def test_asset_catalog_profile_allows_only_catalog_reads_and_denies_mutation():
    profile = broker_read_profile_for_name(PAPER_ASSET_CATALOG_READS)

    assert profile.allows(READ_ASSET_CATALOG) is True
    assert profile.allows(READ_ACCOUNT) is False
    assert profile.allows("assets") is False
    assert profile.mutation_allowed is False
    assert profile.to_dict()["mutation_allowed"] is False


def test_asset_catalog_profile_uses_exact_query_and_blocks_mutation_before_transport():
    transport = CaptureTransport()
    adapter = _adapter(profile=PAPER_ASSET_CATALOG_READS, transport=transport)

    response = adapter.get_crypto_asset_catalog()

    assert response.ok is True
    assert adapter.identity.supported_methods == frozenset({"GET"})
    assert transport.calls[0]["method"] == "GET"
    assert transport.calls[0]["url"].endswith("/v2/assets?status=active&asset_class=crypto")

    with pytest.raises(BrokerGatewayError) as exc_info:
        adapter.request_unsupported("POST", "/v2/orders")

    assert exc_info.value.reason_code == BROKER_MUTATION_NOT_AUTHORIZED
    assert len(transport.calls) == 1


@pytest.mark.parametrize("profile", [PAPER_SMOKE_STRICT_READS, PAPER_TCA_EXTENDED_READS, "UNKNOWN_PROFILE"])
def test_non_catalog_profiles_deny_catalog_before_transport(profile):
    transport = CaptureTransport()
    adapter = _adapter(profile=profile, transport=transport)

    with pytest.raises(BrokerGatewayError) as exc_info:
        adapter.get_crypto_asset_catalog()

    assert exc_info.value.reason_code == BROKER_READ_NOT_AUTHORIZED
    assert transport.calls == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v2/orders"),
        ("PATCH", "/v2/orders/order-1"),
        ("DELETE", "/v2/orders/order-1"),
    ],
)
def test_catalog_profile_denies_every_mutation_method_before_transport(method, path):
    transport = CaptureTransport()
    adapter = _adapter(profile=PAPER_ASSET_CATALOG_READS, transport=transport)

    with pytest.raises(BrokerGatewayError) as exc_info:
        adapter.request_unsupported(method, path)

    assert exc_info.value.reason_code == BROKER_MUTATION_NOT_AUTHORIZED
    assert transport.calls == []


def test_catalog_profile_denies_cancel_single_asset_account_and_malformed_catalog_gets():
    transport = CaptureTransport()
    adapter = _adapter(profile=PAPER_ASSET_CATALOG_READS, transport=transport)

    calls = (
        lambda: adapter.cancel_order("order-1"),
        lambda: adapter.get_asset("BTC/USD"),
        adapter.get_account,
        lambda: adapter._request("GET", "/v2/assets", query={"status": "active"}),
        lambda: adapter._request(
            "GET",
            "/v2/assets",
            query={"status": "active", "asset_class": "crypto", "extra": "forbidden"},
        ),
        lambda: adapter._request(
            "GET",
            "/v2/assets",
            query={"status": "active", "asset_class": "crypto"},
            payload={"forbidden": True},
        ),
    )
    reasons = []
    for call in calls:
        with pytest.raises(BrokerGatewayError) as exc_info:
            call()
        reasons.append(exc_info.value.reason_code)

    assert reasons == [
        BROKER_MUTATION_NOT_AUTHORIZED,
        BROKER_READ_NOT_AUTHORIZED,
        BROKER_READ_NOT_AUTHORIZED,
        "asset_catalog_query_must_be_active_crypto",
        "asset_catalog_query_must_be_active_crypto",
        "get_payload_forbidden",
    ]
    assert transport.calls == []


def test_alpaca_adapter_denies_account_activities_before_network_under_strict_profile():
    transport = CaptureTransport()
    adapter = _adapter(profile=PAPER_SMOKE_STRICT_READS, transport=transport)

    with pytest.raises(BrokerGatewayError) as exc_info:
        adapter.get_account_activities(activity_types="FILL")

    assert exc_info.value.reason_code == BROKER_READ_NOT_AUTHORIZED
    assert transport.calls == []
    assert adapter.request_counts.get("GET", 0) == 0


def test_alpaca_adapter_allows_account_orders_positions_under_strict_profile():
    transport = CaptureTransport()
    adapter = _adapter(profile=PAPER_SMOKE_STRICT_READS, transport=transport)

    adapter.get_account()
    adapter.get_open_orders()
    adapter.get_positions()

    assert [call["method"] for call in transport.calls] == ["GET", "GET", "GET"]
    assert adapter.request_counts["GET"] == 3


def test_extended_tca_profile_rejects_non_tca_account_activity_before_network():
    transport = CaptureTransport()
    adapter = _adapter(profile=PAPER_TCA_EXTENDED_READS, transport=transport)

    with pytest.raises(BrokerGatewayError) as exc_info:
        adapter.get_account_activities(activity_types="DIV")

    assert exc_info.value.reason_code == BROKER_READ_NOT_AUTHORIZED
    assert transport.calls == []
    assert adapter.request_counts.get("GET", 0) == 0
