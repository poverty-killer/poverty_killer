from __future__ import annotations

from pathlib import Path

from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.operator_credentials.store import LocalCredentialStore, alpaca_endpoint_authority
from app.operator_providers.readiness import provider_readiness_summary


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def _store(tmp_path: Path) -> LocalCredentialStore:
    return LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")


def test_credentials_save_and_get_redacts_raw_values(tmp_path):
    store = _store(tmp_path)
    secret = "alpaca-secret-value-123"

    saved = store.save_provider(
        "alpaca_paper",
        {
            "APCA_API_KEY_ID": "alpaca-key-id-123",
            "APCA_API_SECRET_KEY": secret,
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
        },
    )
    summary = store.providers_summary({})
    text = str(saved) + str(summary)

    assert saved["status"] == "SAVED"
    assert secret not in text
    assert "alpaca-key-id-123" not in text
    assert "sha256:" in text
    assert summary["secrets_values_exposed"] is False
    assert summary["raw_secret_values_included"] is False


def test_alpaca_paper_save_valid_shaped_values_succeeds_with_schema_diagnostics(tmp_path):
    store = _store(tmp_path)

    saved = store.save_provider(
        "alpaca_paper",
        {
            "APCA_API_KEY_ID": "PKFAKEALPACAKEY123",
            "APCA_API_SECRET_KEY": "fake-alpaca-secret-value-123",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
        },
    )

    assert saved["status"] == "SAVED"
    assert saved["provider_id"] == "alpaca_paper"
    assert saved["required_fields"] == ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"]
    assert saved["received_field_presence"] == {
        "APCA_API_KEY_ID": True,
        "APCA_API_SECRET_KEY": True,
        "APCA_API_BASE_URL": True,
    }
    assert saved["vault_parent_writable"] is True
    assert saved["summary"]["configured"] is True
    assert "fake-alpaca-secret-value" not in str(saved)
    assert "PKFAKEALPACAKEY" not in str(saved)


def test_alpaca_paper_missing_api_key_refuses_with_exact_reason(tmp_path):
    store = _store(tmp_path)

    result = store.save_provider(
        "alpaca_paper",
        {"APCA_API_SECRET_KEY": "fake-alpaca-secret-value-123"},
    )

    assert result["status"] == "REFUSED"
    assert result["reason_code"] == "MISSING_REQUIRED_CREDENTIAL_FIELDS"
    assert result["missing_fields"] == ["APCA_API_KEY_ID"]
    assert result["received_field_presence"]["APCA_API_KEY_ID"] is False
    assert result["received_field_presence"]["APCA_API_SECRET_KEY"] is True
    assert "fake-alpaca-secret-value" not in str(result)


def test_alpaca_paper_missing_secret_refuses_with_exact_reason(tmp_path):
    store = _store(tmp_path)

    result = store.save_provider(
        "alpaca_paper",
        {"APCA_API_KEY_ID": "PKFAKEALPACAKEY123"},
    )

    assert result["status"] == "REFUSED"
    assert result["reason_code"] == "MISSING_REQUIRED_CREDENTIAL_FIELDS"
    assert result["missing_fields"] == ["APCA_API_SECRET_KEY"]
    assert result["received_field_presence"]["APCA_API_KEY_ID"] is True
    assert result["received_field_presence"]["APCA_API_SECRET_KEY"] is False
    assert "PKFAKEALPACAKEY" not in str(result)


def test_alpaca_base_url_defaults_to_paper_endpoint_when_blank(tmp_path):
    store = _store(tmp_path)

    saved = store.save_provider(
        "alpaca_paper",
        {
            "APCA_API_KEY_ID": "PKFAKEALPACAKEY123",
            "APCA_API_SECRET_KEY": "fake-alpaca-secret-value-123",
            "APCA_API_BASE_URL": "",
        },
    )
    summary = store.provider_summary("alpaca_paper", {})
    base_row = next(row for row in summary["fields"] if row["name"] == "APCA_API_BASE_URL")

    assert saved["status"] == "SAVED"
    assert saved["received_field_presence"]["APCA_API_BASE_URL"] is False
    assert base_row["source"] == "SAFE_DEFAULT"
    assert base_row["configured"] is True


def test_alpaca_endpoint_authority_normalizes_safe_paper_variants():
    variants = [
        "https://paper-api.alpaca.markets",
        "https://paper-api.alpaca.markets/",
        " HTTPS://PAPER-API.ALPACA.MARKETS/v2 ",
    ]

    for raw in variants:
        authority = alpaca_endpoint_authority({"APCA_API_BASE_URL": raw})

        assert authority["paper_endpoint_only"] is True
        assert authority["alpaca_paper_endpoint_valid"] is True
        assert authority["actual_endpoint"] == "https://paper-api.alpaca.markets"
        assert authority["alpaca_endpoint_display"] == "https://paper-api.alpaca.markets"
        assert authority["alpaca_trading_endpoint_host"] == "paper-api.alpaca.markets"
        assert authority["alpaca_trading_endpoint_family"] == "paper"
        assert authority["alpaca_endpoint_blocker_code"] is None
        assert authority["alpaca_live_endpoint_blocked"] is True


def test_alpaca_endpoint_authority_missing_endpoint_is_safe_default_not_configured():
    authority = alpaca_endpoint_authority({})

    assert authority["paper_endpoint_only"] is True
    assert authority["endpoint_source"] == "SAFE_DEFAULT_PAPER_ENDPOINT"
    assert authority["alpaca_endpoint_configured"] is False
    assert authority["alpaca_endpoint_display"] == "https://paper-api.alpaca.markets"
    assert authority["alpaca_trading_endpoint_family"] == "paper"
    assert authority["alpaca_endpoint_blocker_code"] is None


def test_alpaca_endpoint_authority_rejects_live_data_and_broker_endpoints():
    cases = [
        ("https://api.alpaca.markets", "LIVE_ENDPOINT_BLOCKED", "live"),
        ("api.alpaca.markets", "LIVE_ENDPOINT_BLOCKED", "live"),
        ("https://data.alpaca.markets", "ALPACA_DATA_ENDPOINT_NOT_TRADING", "data"),
        ("https://broker-api.alpaca.markets", "ALPACA_BROKER_ENDPOINT_UNSUPPORTED", "broker"),
        ("https://broker-api.sandbox.alpaca.markets", "ALPACA_BROKER_ENDPOINT_UNSUPPORTED", "broker"),
    ]

    for raw, reason_code, family in cases:
        authority = alpaca_endpoint_authority({"APCA_API_BASE_URL": raw})

        assert authority["paper_endpoint_only"] is False
        assert authority["reason_code"] == reason_code
        assert authority["alpaca_endpoint_blocker_code"] == reason_code
        assert authority["alpaca_trading_endpoint_family"] == family
        assert authority["alpaca_live_endpoint_blocked"] is True
        assert authority["secrets_values_exposed"] is False


def test_wrong_provider_id_refuses_with_reason_and_accepted_ids(tmp_path):
    store = _store(tmp_path)

    result = store.save_provider(
        "alpaca_real_money",
        {
            "APCA_API_KEY_ID": "PKFAKEALPACAKEY123",
            "APCA_API_SECRET_KEY": "fake-alpaca-secret-value-123",
        },
    )

    assert result["status"] == "REFUSED"
    assert result["reason_code"] == "UNKNOWN_PROVIDER"
    assert "alpaca_paper" in result["accepted_provider_ids"]
    assert result["received_field_presence"] == {}
    assert "fake-alpaca-secret-value" not in str(result)


def test_credential_endpoints_return_only_fingerprints_and_delete_safely(tmp_path):
    store = _store(tmp_path)
    runtime_config = OperatorRuntimeConfig.from_env({}, repo_root=tmp_path)
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=runtime_config,
            provider_env={},
            credential_store=store,
        )
    )

    saved = _endpoint(app, "/operator/credentials/save", "POST")(
        {
            "provider_id": "openai",
            "credentials": {"OPENAI_API_KEY": "sk-test-secret-value-123456"},
        }
    )
    providers = _endpoint(app, "/operator/credentials/providers")()
    validation = _endpoint(app, "/operator/credentials/validate-readonly", "POST")({"provider_id": "openai"})
    deleted = _endpoint(app, "/operator/credentials/provider/{provider_id}", "DELETE")("openai")
    text = str(saved) + str(providers) + str(validation) + str(deleted)

    assert saved["status"] == "SAVED"
    assert validation["status"] == "READY"
    assert deleted["status"] == "DELETED"
    assert "sk-test-secret-value" not in text
    assert "sha256:" in text
    assert providers["secrets_values_exposed"] is False


def test_credentials_provider_summary_declares_gitignored_local_store_without_values(tmp_path):
    store = _store(tmp_path)

    summary = store.providers_summary({})
    text = str(summary)

    assert str(summary["store_path"]).replace("\\", "/").endswith(".operator_secrets/provider_credentials.json")
    assert summary["precedence"] == "ENV_PRESENT_OVERRIDES_LOCAL_SECRET"
    assert summary["secrets_values_exposed"] is False
    assert summary["raw_secret_values_included"] is False
    assert "APCA_API_KEY_ID" in text
    assert "APCA_API_SECRET_KEY" in text
    assert "paste secrets into chat" not in text


def test_alpaca_readonly_validation_is_presence_and_endpoint_only_no_network(tmp_path):
    store = _store(tmp_path)
    store.save_provider(
        "alpaca_paper",
        {
            "APCA_API_KEY_ID": "placeholder-paper-key",
            "APCA_API_SECRET_KEY": "placeholder-paper-secret",
        },
    )

    result = store.validate_readonly("alpaca_paper", {})
    text = str(result)

    assert result["status"] == "READY"
    assert result["read_only_validation"] is True
    assert result["broker_call_occurred"] is False
    assert result["external_mutation_occurred"] is False
    assert result["trading_mutation_occurred"] is False
    assert result["paper_endpoint_authority"]["paper_endpoint_only"] is True
    assert result["paper_endpoint_authority"]["alpaca_live_endpoint_blocked"] is True
    assert "placeholder-paper-key" not in text
    assert "placeholder-paper-secret" not in text


def test_provider_readiness_reads_local_secret_presence(tmp_path):
    store = _store(tmp_path)
    store.save_provider(
        "alpaca_paper",
        {
            "APCA_API_KEY_ID": "local-key",
            "APCA_API_SECRET_KEY": "local-secret",
        },
    )

    readiness = provider_readiness_summary({}, credential_store=store)
    alpaca = next(provider for provider in readiness["providers"] if provider["provider_id"] == "alpaca_paper")

    assert alpaca["configured"] is True
    assert alpaca["status"] == "CONFIGURED"
    assert {row["source"] for row in alpaca["env_status"] if row["configured"]} == {"LOCAL_SECRET_PRESENT"}
    assert "local-secret" not in str(readiness)


def test_shared_alpaca_credentials_resolve_for_paper_and_news_without_raw_values(tmp_path):
    store = _store(tmp_path)
    store.save_provider(
        "alpaca_news",
        {
            "APCA_API_KEY_ID": "shared-local-key",
            "APCA_API_SECRET_KEY": "shared-local-secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
        },
    )

    credentials = store.providers_summary({})
    readiness = provider_readiness_summary({}, credential_store=store)
    paper_summary = next(row for row in credentials["providers"] if row["provider_id"] == "alpaca_paper")
    paper_readiness = next(row for row in readiness["providers"] if row["provider_id"] == "alpaca_paper")
    text = str(credentials) + str(readiness)

    assert paper_summary["configured"] is True
    assert paper_summary["source"] == "LOCAL_SECRET_PRESENT"
    assert paper_readiness["configured"] is True
    assert paper_readiness["status"] == "CONFIGURED"
    assert "shared-local-secret" not in text
    assert "shared-local-key" not in text


def test_alpaca_save_refreshes_credentials_readiness_launch_and_diagnostics(tmp_path):
    store = _store(tmp_path)
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    app = create_operator_app(provider=provider)

    saved = _endpoint(app, "/operator/credentials/save", "POST")(
        {
            "provider_id": "alpaca_paper",
            "credentials": {
                "APCA_API_KEY_ID": "alpaca-local-key",
                "APCA_API_SECRET_KEY": "alpaca-local-secret",
                "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            },
        }
    )
    credentials = _endpoint(app, "/operator/credentials/providers")()
    readiness = _endpoint(app, "/operator/providers/readiness")()
    launch = _endpoint(app, "/operator/launch-readiness")()
    diagnostics = _endpoint(app, "/operator/credentials/diagnostics")()
    text = str(saved) + str(credentials) + str(readiness) + str(launch) + str(diagnostics)

    alpaca = next(row for row in credentials["providers"] if row["provider_id"] == "alpaca_paper")
    assert saved["status"] == "SAVED"
    assert alpaca["configured"] is True
    assert "LOCAL_SECRET_PRESENT" in alpaca["source"]
    assert readiness["ready_or_configured_count"] >= 1
    assert launch["alpaca_paper_credentials_configured"] is True
    assert "alpaca_paper_credentials" not in launch["reason_codes"]
    assert diagnostics["vault_file_exists"] is True
    assert diagnostics["vault_writable"] is True
    assert "alpaca_paper" in diagnostics["accepted_provider_ids"]
    assert diagnostics["received_provider_id_last_save"] == "alpaca_paper"
    assert diagnostics["last_save_status"] == "SAVED"
    assert diagnostics["last_save_refusal_reason"] is None
    assert diagnostics["last_save_received_field_presence"] == {
        "APCA_API_KEY_ID": True,
        "APCA_API_SECRET_KEY": True,
        "APCA_API_BASE_URL": True,
    }
    assert diagnostics["providers"]["alpaca_paper"]["required_field_names_present"] == {
        "APCA_API_KEY_ID": True,
        "APCA_API_SECRET_KEY": True,
    }
    assert diagnostics["source_used_by_portfolio_broker_read"] == "LOCAL_SECRET_PRESENT"
    assert "alpaca-local-secret" not in text
    assert "alpaca-local-key" not in text
    assert diagnostics["secrets_values_exposed"] is False


def test_local_alpaca_vault_truth_matches_cards_provider_table_launch_and_portfolio(tmp_path):
    class FailingReadOnlyClient:
        def get_json(self, path, headers):
            raise RuntimeError("simulated read failure")

    store = _store(tmp_path)
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
        portfolio_client=FailingReadOnlyClient(),
    )
    app = create_operator_app(provider=provider)

    saved = _endpoint(app, "/operator/credentials/save", "POST")(
        {
            "provider_id": "alpaca_paper",
            "credentials": {
                "APCA_API_KEY_ID": "alpaca-local-key",
                "APCA_API_SECRET_KEY": "alpaca-local-secret",
                "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            },
        }
    )
    credential_cards = _endpoint(app, "/operator/credentials/providers")()
    provider_table = _endpoint(app, "/operator/providers")()
    readiness = _endpoint(app, "/operator/providers/readiness")()
    diagnostics = _endpoint(app, "/operator/credentials/diagnostics")()
    launch = _endpoint(app, "/operator/launch-readiness")()
    portfolio = _endpoint(app, "/operator/portfolio")()
    text = str((saved, credential_cards, provider_table, readiness, diagnostics, launch, portfolio))

    card_alpaca = next(row for row in credential_cards["providers"] if row["provider_id"] == "alpaca_paper")
    table_alpaca = next(row for row in provider_table["providers"] if row["provider_id"] == "alpaca_paper")
    readiness_alpaca = next(row for row in readiness["providers"] if row["provider_id"] == "alpaca_paper")

    assert saved["status"] == "SAVED"
    assert card_alpaca["configured"] is True
    assert card_alpaca["source"] == "LOCAL_SECRET_PRESENT"
    assert table_alpaca["configured"] is True
    assert table_alpaca["status"] == "CONFIGURED"
    assert table_alpaca["credential_source"] == "LOCAL_SECRET_PRESENT"
    assert readiness_alpaca["configured"] is True
    assert readiness_alpaca["credential_source"] == "LOCAL_SECRET_PRESENT"
    assert diagnostics["source_used_by_credential_cards"] == "LOCAL_SECRET_PRESENT"
    assert diagnostics["source_used_by_provider_table"] == "LOCAL_SECRET_PRESENT"
    assert diagnostics["source_used_by_provider_readiness"] == "LOCAL_SECRET_PRESENT"
    assert diagnostics["source_used_by_launch_readiness"] == "LOCAL_SECRET_PRESENT"
    assert diagnostics["source_used_by_portfolio"] == "LOCAL_SECRET_PRESENT"
    assert diagnostics["source_used_by_paper_supervisor"] == "LOCAL_SECRET_PRESENT"
    assert launch["alpaca_paper_credentials_configured"] is True
    assert portfolio["status"] == "BROKER_READ_FAILED"
    assert portfolio["unavailable_reason"] == "BROKER_READ_FAILED"
    assert "alpaca-local-secret" not in text
    assert "alpaca-local-key" not in text
    assert "MISSING_CREDENTIALALS" not in text


def test_credential_diagnostics_records_last_refusal_reason_without_raw_values(tmp_path):
    store = _store(tmp_path)
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )
    app = create_operator_app(provider=provider)

    refused = _endpoint(app, "/operator/credentials/save", "POST")(
        {
            "provider_id": "alpaca_paper",
            "credentials": {"APCA_API_KEY_ID": "PKFAKEALPACAKEY123"},
        }
    )
    diagnostics = _endpoint(app, "/operator/credentials/diagnostics")()
    text = str(refused) + str(diagnostics)

    assert refused["status"] == "REFUSED"
    assert refused["reason_code"] == "MISSING_REQUIRED_CREDENTIAL_FIELDS"
    assert diagnostics["received_provider_id_last_save"] == "alpaca_paper"
    assert diagnostics["last_save_status"] == "REFUSED"
    assert diagnostics["last_save_refusal_reason"] == "MISSING_REQUIRED_CREDENTIAL_FIELDS"
    assert diagnostics["last_save_missing_fields"] == ["APCA_API_SECRET_KEY"]
    assert diagnostics["last_save_received_field_presence"]["APCA_API_KEY_ID"] is True
    assert diagnostics["last_save_received_field_presence"]["APCA_API_SECRET_KEY"] is False
    assert "PKFAKEALPACAKEY" not in text
    assert diagnostics["raw_secret_values_included"] is False


def test_env_credentials_override_local_credentials_safely(tmp_path):
    store = _store(tmp_path)
    store.save_provider(
        "alpaca_paper",
        {
            "APCA_API_KEY_ID": "local-key",
            "APCA_API_SECRET_KEY": "local-secret",
        },
    )

    readiness = provider_readiness_summary(
        {"APCA_API_KEY_ID": "env-key", "APCA_API_SECRET_KEY": "env-secret"},
        credential_store=store,
    )
    alpaca = next(provider for provider in readiness["providers"] if provider["provider_id"] == "alpaca_paper")

    assert {row["source"] for row in alpaca["env_status"] if row["name"] in {"APCA_API_KEY_ID", "APCA_API_SECRET_KEY"}} == {"ENV_PRESENT"}
    assert "env-secret" not in str(readiness)
    assert "local-secret" not in str(readiness)


def test_local_secrets_are_not_in_ai_context(tmp_path):
    store = _store(tmp_path)
    store.save_provider(
        "openai",
        {"OPENAI_API_KEY": "sk-context-secret-value-1234567890"},
    )
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
    )

    context = provider._ai_context()
    text = str(context)

    assert "sk-context-secret-value" not in text
    assert "sha256:" not in text
    assert context["secrets_values_exposed"] is False


def test_mock_data_contains_no_raw_secret_values():
    text = Path("ui/operator-control-panel/mock-data.js").read_text(encoding="utf-8")

    assert "sk-" not in text
    assert "alpaca-secret" not in text
    assert "raw_secret" not in text.lower()


def test_desktop_launcher_checks_backend_cwd_and_credential_diagnostics():
    text = Path("scripts/open_operator_console_hidden.ps1").read_text(encoding="utf-8")

    assert 'cd /d `"$RepoRoot`"' in text
    assert "WorkingDirectory $RepoRoot" in text
    assert "/operator/credentials/diagnostics" in text
    assert "credential_vault_relative_path" in text
    assert ".operator_secrets/provider_credentials.json" in text
