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
    BROKER_READ_NOT_AUTHORIZED,
    FEE_HYDRATION_ALLOWED_ENV,
    PAPER_SMOKE_STRICT_READS,
    PAPER_TCA_EXTENDED_READS,
    READ_ACCOUNT,
    READ_ACCOUNT_ACTIVITIES,
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
