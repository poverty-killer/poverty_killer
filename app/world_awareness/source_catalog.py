from __future__ import annotations

from .enums import SourceFamily, SourceLatencyClass, TrustTier
from .models import SourceDescriptor

_PREMIUM_GATED_SOURCES = {
    SourceFamily.QUIVER_FREE,
}


def build_source_catalog() -> dict[SourceFamily, SourceDescriptor]:
    """
    Returns the subordinate pre-integration source catalog for the
    world-awareness subsystem.

    This catalog is intentionally non-authoritative and non-live-attached.
    """

    return {
        SourceFamily.SEC_EDGAR: SourceDescriptor(
            source_family=SourceFamily.SEC_EDGAR,
            source_name="data.sec.gov",
            trust_tier=TrustTier.FREE_PRIMARY,
            source_latency_class=SourceLatencyClass.SOURCE_DEPENDENT,
            source_url="https://www.sec.gov/edgar/search/",
            integration_status="not_live_attached",
            notes=[
                "Regulatory primary public surface.",
                "Suitable for subordinate filing-context ingestion.",
            ],
        ),
        SourceFamily.OPENINSIDER: SourceDescriptor(
            source_family=SourceFamily.OPENINSIDER,
            source_name="openinsider",
            trust_tier=TrustTier.FREE_SECONDARY,
            source_latency_class=SourceLatencyClass.DELAYED_PUBLIC,
            source_url="http://openinsider.com/",
            integration_status="not_live_attached",
            notes=[
                "Secondary public aggregator for insider disclosures.",
                "Delayed-public subordinate context source.",
            ],
        ),
        SourceFamily.CAPITOL_TRADES: SourceDescriptor(
            source_family=SourceFamily.CAPITOL_TRADES,
            source_name="capitol_trades",
            trust_tier=TrustTier.FREE_SECONDARY,
            source_latency_class=SourceLatencyClass.DISCLOSURE_DELAYED,
            source_url="https://www.capitoltrades.com/",
            integration_status="not_live_attached",
            notes=[
                "Political disclosure public aggregator.",
                "Disclosure-delayed subordinate context source.",
            ],
        ),
        SourceFamily.QUIVER_FREE: SourceDescriptor(
            source_family=SourceFamily.QUIVER_FREE,
            source_name="quiver_quantitative_free",
            trust_tier=TrustTier.FREE_SECONDARY,
            source_latency_class=SourceLatencyClass.SOURCE_DEPENDENT,
            source_url="https://www.quiverquant.com/",
            integration_status="not_live_attached",
            notes=[
                "Alternative public aggregator surface.",
                "Subordinate context only.",
            ],
        ),
        SourceFamily.OFFICIAL_ISSUER_RELEASES: SourceDescriptor(
            source_family=SourceFamily.OFFICIAL_ISSUER_RELEASES,
            source_name="official_issuer_releases",
            trust_tier=TrustTier.OFFICIAL_PRIMARY_PUBLIC,
            source_latency_class=SourceLatencyClass.SCHEDULED_RELEASE,
            source_url=None,
            integration_status="not_live_attached",
            notes=[
                "Official issuer-hosted release family.",
                "Primary public release source family.",
            ],
        ),
        SourceFamily.OFFICIAL_CALENDARS: SourceDescriptor(
            source_family=SourceFamily.OFFICIAL_CALENDARS,
            source_name="official_calendars",
            trust_tier=TrustTier.OFFICIAL_PRIMARY_PUBLIC,
            source_latency_class=SourceLatencyClass.WINDOWED,
            source_url=None,
            integration_status="not_live_attached",
            notes=[
                "Official calendar/release family.",
                "Registered to prevent under-specification of event-calendar stack.",
            ],
        ),
        SourceFamily.OFFICIAL_MACRO_RELEASES: SourceDescriptor(
            source_family=SourceFamily.OFFICIAL_MACRO_RELEASES,
            source_name="official_macro_releases",
            trust_tier=TrustTier.OFFICIAL_PRIMARY_PUBLIC,
            source_latency_class=SourceLatencyClass.SCHEDULED_RELEASE,
            source_url=None,
            integration_status="not_live_attached",
            notes=[
                "Official macro/economic release family.",
                "Subordinate scheduled-release context source.",
            ],
        ),
    }


def list_source_descriptors() -> list[SourceDescriptor]:
    return list(build_source_catalog().values())


def get_source_descriptor(source_family: SourceFamily) -> SourceDescriptor:
    catalog = build_source_catalog()
    return catalog[source_family]


def source_status_signature(
    source_family: SourceFamily,
    *,
    local_cache_available: bool = False,
    replay_available: bool = False,
    public_configured: bool = False,
    premium_key_configured: bool = False,
    compliance_verified: bool = False,
    live_attachment_enabled: bool = False,
) -> dict[str, str]:
    """
    Return a contribution-readiness status for a source without fetching data.

    This is deliberately catalog-only. It does not authorize live attachment,
    network calls, scraping, or canonical truth claims.
    """
    descriptor = get_source_descriptor(source_family)

    if local_cache_available:
        status = "ACTIVE_LOCAL_CACHE"
        input_truth = "local_cache_available"
        reason = "LOCAL_CACHE_AVAILABLE"
        effect = "SOURCE_STATUS"
        summary = f"{descriptor.source_name} can contribute cached advisory evidence."
    elif replay_available:
        status = "ACTIVE_REPLAY"
        input_truth = "replay_available"
        reason = "REPLAY_AVAILABLE"
        effect = "SOURCE_STATUS"
        summary = f"{descriptor.source_name} can contribute replay-labeled advisory evidence."
    elif public_configured and compliance_verified:
        status = "ACTIVE_PUBLIC_CONFIGURED"
        input_truth = "public_configured_compliance_verified"
        reason = "PUBLIC_SOURCE_CONFIGURED"
        effect = "SOURCE_STATUS"
        summary = f"{descriptor.source_name} is configured as a lawful public advisory source."
    elif source_family in _PREMIUM_GATED_SOURCES and not premium_key_configured:
        status = "INTENTIONALLY_BLOCKED_PREMIUM_KEY_MISSING"
        input_truth = "premium_key_missing"
        reason = "PREMIUM_KEY_MISSING"
        effect = "INTENTIONALLY_BLOCKED"
        summary = f"{descriptor.source_name} blocked until premium/free-tier credential status is explicit."
    elif live_attachment_enabled and not compliance_verified:
        status = "INTENTIONALLY_BLOCKED_COMPLIANCE_UNVERIFIED"
        input_truth = "compliance_not_verified"
        reason = "COMPLIANCE_UNVERIFIED"
        effect = "INTENTIONALLY_BLOCKED"
        summary = f"{descriptor.source_name} blocked until lawful live-source compliance is verified."
    elif not live_attachment_enabled:
        status = "INTENTIONALLY_BLOCKED_LIVE_ONLY"
        input_truth = "live_attachment_disabled"
        reason = "LIVE_ATTACHMENT_DISABLED"
        effect = "INTENTIONALLY_BLOCKED"
        summary = f"{descriptor.source_name} is cataloged but not live-attached."
    else:
        status = "MISSING_FEED_TRUTH"
        input_truth = "no_cache_replay_or_configured_public_feed"
        reason = "MISSING_FEED_TRUTH"
        effect = "MISSING_TRUTH"
        summary = f"{descriptor.source_name} has no available cache, replay, or configured public feed truth."

    return {
        "module_name": "SourceCatalog",
        "source_name": descriptor.source_name,
        "status": status,
        "input_truth": input_truth,
        "output_summary": summary,
        "effect": effect,
        "reason": reason,
    }
