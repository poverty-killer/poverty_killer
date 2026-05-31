from __future__ import annotations

from pathlib import Path

from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.operator_credentials.store import LocalCredentialStore
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
    assert diagnostics["providers"]["alpaca_paper"]["required_field_names_present"] == {
        "APCA_API_KEY_ID": True,
        "APCA_API_SECRET_KEY": True,
    }
    assert diagnostics["source_used_by_portfolio_broker_read"] == "LOCAL_SECRET_PRESENT"
    assert "alpaca-local-secret" not in text
    assert "alpaca-local-key" not in text
    assert diagnostics["secrets_values_exposed"] is False


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
