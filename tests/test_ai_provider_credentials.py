from __future__ import annotations

from app.operator_credentials.store import LocalCredentialStore


def test_ai_provider_credentials_save_to_local_vault_without_raw_secret_summary(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")

    cases = {
        "openai": {"OPENAI_API_KEY": "openai-test-token-value-1234567890"},
        "anthropic": {"ANTHROPIC_API_KEY": "claude-test-token-value"},
        "gemini": {"GOOGLE_API_KEY": "google-test-token-value"},
        "xai_grok": {"XAI_API_KEY": "xai-test-token-value"},
        "deepseek": {"DEEPSEEK_API_KEY": "deepseek-test-token-value", "DEEPSEEK_BASE_URL": "https://api.deepseek.com"},
        "kimi_moonshot": {"MOONSHOT_API_KEY": "moonshot-test-token-value"},
        "local_openai_compatible": {"LOCAL_AI_BASE_URL": "http://127.0.0.1:11434/v1", "LOCAL_AI_MODEL": "local-model"},
    }

    for provider_id, values in cases.items():
        saved = store.save_provider(provider_id, values)
        summary = store.provider_summary(provider_id)
        text = str(summary)

        assert saved["status"] == "SAVED"
        assert summary["configured"] is True
        assert summary["secrets_values_exposed"] is False
        assert summary["raw_secret_values_included"] is False
        for secret in values.values():
            assert secret not in text


def test_ai_provider_alias_env_keys_satisfy_required_summary_fields(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")

    gemini = store.provider_summary("gemini", {"GOOGLE_API_KEY": "google-test-token-value"})
    kimi = store.provider_summary("kimi_moonshot", {"MOONSHOT_API_KEY": "moonshot-test-token-value"})

    assert gemini["configured"] is True
    assert any(row["name"] == "GEMINI_API_KEY" and row["source"] == "ENV_PRESENT" for row in gemini["fields"])
    assert kimi["configured"] is True
    assert any(row["name"] == "KIMI_API_KEY" and row["source"] == "ENV_PRESENT" for row in kimi["fields"])


def test_wrong_ai_provider_id_refuses_with_reason(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")

    result = store.save_provider("single_vendor_only", {"OPENAI_API_KEY": "openai-test-token"})

    assert result["status"] == "REFUSED"
    assert result["reason_code"] == "UNKNOWN_PROVIDER"
    assert result["saved"] is False
    assert result["secrets_values_exposed"] is False
