"""Static operator provider registry.

Profiles describe configuration/readiness expectations only. They do not hold
secret values and do not perform validation calls.
"""

from __future__ import annotations

from app.operator_providers.models import ProviderProfile


PROVIDER_PROFILES: tuple[ProviderProfile, ...] = (
    ProviderProfile(
        provider_id="alpaca_paper",
        display_name="Alpaca Paper Broker/Data",
        category="broker",
        purpose="Governed PAPER broker and account/order/fill truth source.",
        required_env_vars=("APCA_API_KEY_ID", "APCA_API_SECRET_KEY"),
        optional_env_vars=("APCA_API_BASE_URL", "APCA_DATA_URL"),
        implemented=True,
        enabled_by_default=True,
        read_only_validation_supported=True,
        can_trade=False,
        setup_instructions="Set Alpaca PAPER env vars in the local runtime environment. Operator UI only sees presence and masked fingerprints.",
    ),
    ProviderProfile(
        provider_id="coinbase_public",
        display_name="Coinbase Public",
        category="market_data",
        purpose="Public crypto market-data route for executable market truth when runtime wiring selects it.",
        implemented=True,
        enabled_by_default=True,
        read_only_validation_supported=False,
        setup_instructions="No credentials required for public-read readiness. Runtime market-truth gates still decide executability.",
    ),
    ProviderProfile(
        provider_id="kraken_public",
        display_name="Kraken Public",
        category="market_data",
        purpose="Public crypto market-data route and latency/freshness comparison source.",
        implemented=True,
        enabled_by_default=True,
        read_only_validation_supported=False,
        setup_instructions="No credentials required for public-read readiness. Runtime market-truth gates still decide executability.",
    ),
    ProviderProfile(
        provider_id="alpaca_news",
        display_name="Alpaca News",
        category="news",
        purpose="Read-only World Awareness news provider; advisory evidence only.",
        required_env_vars=("APCA_API_KEY_ID", "APCA_API_SECRET_KEY"),
        implemented=True,
        enabled_by_default=False,
        read_only_validation_supported=True,
        setup_instructions="Enable through World Awareness config after Alpaca credentials are present. Feed cannot trade or score by itself.",
    ),
    ProviderProfile(
        provider_id="nasdaq_data",
        display_name="Nasdaq Data Placeholder",
        category="market_data",
        purpose="Future equities/options market-data and corporate-action provider lane.",
        required_env_vars=("NASDAQ_DATA_API_KEY",),
        implemented=False,
        setup_instructions="Reserved for a separate provider packet with contract, validation, and source-truth rules.",
    ),
    ProviderProfile(
        provider_id="polygon",
        display_name="Polygon Placeholder",
        category="market_data",
        purpose="Future equities/options/crypto market-data provider lane.",
        required_env_vars=("POLYGON_API_KEY",),
        implemented=False,
        setup_instructions="Reserved for a separate provider packet with rate limits, entitlement checks, and truth labels.",
    ),
    ProviderProfile(
        provider_id="finnhub",
        display_name="Finnhub Placeholder",
        category="alternative_data",
        purpose="Future news, filings, sentiment, and fundamentals advisory provider.",
        required_env_vars=("FINNHUB_API_KEY",),
        implemented=False,
        setup_instructions="Reserved for World Awareness/advisory use after validation and replay labeling.",
    ),
    ProviderProfile(
        provider_id="fred_economic_calendar",
        display_name="FRED / Economic Calendar Placeholder",
        category="economic_calendar",
        purpose="Future macro calendar and rate/economic release context provider.",
        required_env_vars=("FRED_API_KEY",),
        implemented=False,
        setup_instructions="Reserved for scheduled-release advisory context; no direct trade authority.",
    ),
    ProviderProfile(
        provider_id="openai",
        display_name="OpenAI Placeholder",
        category="ai_provider",
        purpose="Future real-model provider for AI Quant Research Chief advisory analysis.",
        required_env_vars=("OPENAI_API_KEY",),
        optional_env_vars=("OPENAI_MODEL",),
        implemented=False,
        read_only_validation_supported=True,
        setup_instructions="Set env vars only in the local runtime environment. Tests and default operation make no real model calls.",
    ),
    ProviderProfile(
        provider_id="anthropic",
        display_name="Anthropic / Claude Placeholder",
        category="ai_provider",
        purpose="Future real-model provider for AI Quant Research Chief advisory analysis.",
        required_env_vars=("ANTHROPIC_API_KEY",),
        optional_env_vars=("ANTHROPIC_MODEL",),
        implemented=False,
        read_only_validation_supported=True,
        setup_instructions="Set env vars only in the local runtime environment. Tests and default operation make no real model calls.",
    ),
    ProviderProfile(
        provider_id="execution_quality_lab",
        display_name="Execution Quality Lab",
        category="execution_analytics",
        purpose="Future TCA, slippage, spread capture, and implementation-shortfall analytics lane.",
        implemented=False,
        setup_instructions="Uses broker-confirmed fills/TCA evidence only when a future packet wires richer analytics.",
    ),
    ProviderProfile(
        provider_id="asset_class_reference",
        display_name="Asset-Class Reference Data",
        category="asset_class_data",
        purpose="Future asset metadata, venues, calendars, borrow/margin, and instrument capability lane.",
        implemented=False,
        setup_instructions="Reserved for governed reference-data contracts before use in strategy/risk decisions.",
    ),
)


def list_provider_profiles() -> tuple[ProviderProfile, ...]:
    return PROVIDER_PROFILES
