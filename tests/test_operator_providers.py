from __future__ import annotations

import inspect

from app.operator_providers.readiness import provider_readiness_summary, validate_provider_readonly


def test_provider_readiness_redacts_secret_values():
    payload = provider_readiness_summary(
        {
            "APCA_API_KEY_ID": "key-id-1234567890",
            "APCA_API_SECRET_KEY": "super-secret-value-abcdef",
            "OPENAI_API_KEY": "sk-hidden1234567890",
        }
    )
    text = str(payload)

    assert "super-secret-value" not in text
    assert "sk-hidden" not in text
    assert "key-id-1234567890" not in text
    assert "sha256:" in text
    assert payload["secrets_values_exposed"] is False
    assert payload["raw_secret_values_included"] is False


def test_missing_credentials_show_missing_without_values():
    payload = provider_readiness_summary({})
    alpaca = next(provider for provider in payload["providers"] if provider["provider_id"] == "alpaca_paper")

    assert alpaca["status"] == "MISSING_CREDENTIALS"
    assert alpaca["configured"] is False
    assert alpaca["can_trade"] is False
    assert alpaca["secrets_values_exposed"] is False


def test_provider_validation_is_read_only_and_does_not_call_broker():
    payload = validate_provider_readonly(
        "alpaca_paper",
        {"APCA_API_KEY_ID": "id", "APCA_API_SECRET_KEY": "secret"},
    )

    assert payload["status"] == "READY"
    assert payload["read_only_validation"] is True
    assert payload["broker_call_occurred"] is False
    assert payload["external_mutation_occurred"] is False
    assert payload["trading_mutation_occurred"] is False
    assert payload["secrets_values_exposed"] is False


def test_operator_provider_modules_do_not_import_execution_or_broker():
    from app.operator_providers import readiness, registry

    source = inspect.getsource(readiness) + inspect.getsource(registry)

    assert "from app.execution" not in source
    assert "import app.execution" not in source
    assert "from app.broker" not in source
    assert "import app.broker" not in source
