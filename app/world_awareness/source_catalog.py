from __future__ import annotations

from .enums import SourceFamily, SourceLatencyClass, TrustTier
from .models import SourceDescriptor


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
