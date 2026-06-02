from __future__ import annotations

from app.ai_chief_operator.model_registry import get_ai_provider_profile, registry_summary


def test_ai_provider_registry_is_provider_agnostic_and_honest():
    summary = registry_summary({})
    provider_ids = {row["provider_id"] for row in summary["providers"]}

    assert provider_ids == {
        "openai",
        "anthropic",
        "gemini",
        "xai_grok",
        "deepseek",
        "kimi_moonshot",
        "local_openai_compatible",
        "deterministic_local",
        "supreme_board_packet",
    }
    assert summary["paid_call_on_status_load"] is False
    assert summary["forced_persona_policy_required"] is True
    assert summary["secrets_values_exposed"] is False


def test_provider_profiles_expose_required_router_metadata():
    for provider_id in (
        "openai",
        "anthropic",
        "gemini",
        "xai_grok",
        "deepseek",
        "kimi_moonshot",
        "local_openai_compatible",
        "deterministic_local",
        "supreme_board_packet",
    ):
        profile = get_ai_provider_profile(provider_id)

        assert profile is not None
        assert profile.provider_id == provider_id
        assert profile.display_name
        assert profile.api_format
        assert profile.default_model
        assert profile.model_quality_map
        assert profile.cost_tier_map
        assert profile.reasoning_capability_map


def test_scaffolded_provider_does_not_fake_ready_status():
    summary = registry_summary({})
    gemini = next(row for row in summary["providers"] if row["provider_id"] == "gemini")

    assert gemini["implemented"] is False
    assert gemini["status"] == "NOT_IMPLEMENTED"
    assert gemini["configured"] is False
