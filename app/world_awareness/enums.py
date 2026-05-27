from __future__ import annotations

from enum import Enum, unique


@unique
class SourceFamily(str, Enum):
    SEC_EDGAR = "sec_edgar"
    OPENINSIDER = "openinsider"
    CAPITOL_TRADES = "capitol_trades"
    QUIVER_FREE = "quiver_free"
    OFFICIAL_ISSUER_RELEASES = "official_issuer_releases"
    OFFICIAL_CALENDARS = "official_calendars"
    OFFICIAL_MACRO_RELEASES = "official_macro_releases"


@unique
class TrustTier(str, Enum):
    OFFICIAL_PRIMARY_PUBLIC = "official_primary_public"
    FREE_PRIMARY = "free_primary"
    FREE_SECONDARY = "free_secondary"
    DERIVED_SECONDARY = "derived_secondary"


@unique
class NormalizedEventClass(str, Enum):
    REGULATORY_FILING = "regulatory_filing"
    INSIDER_ACTIVITY = "insider_activity"
    POLITICAL_DISCLOSURE = "political_disclosure"
    ISSUER_RELEASE = "issuer_release"
    CALENDAR_EVENT = "calendar_event"
    MACRO_RELEASE = "macro_release"
    ALTERNATIVE_SIGNAL = "alternative_signal"
    UNKNOWN = "unknown"


@unique
class ExternalFeedType(str, Enum):
    NEWS = "NEWS"
    INSIDER_TRANSACTION = "INSIDER_TRANSACTION"
    SEC_FILING = "SEC_FILING"
    EARNINGS_EVENT = "EARNINGS_EVENT"
    MACRO_EVENT = "MACRO_EVENT"
    ECONOMIC_CALENDAR = "ECONOMIC_CALENDAR"
    FED_EVENT = "FED_EVENT"
    CRYPTO_EVENT = "CRYPTO_EVENT"
    ONCHAIN_EVENT = "ONCHAIN_EVENT"
    SOCIAL_SENTIMENT = "SOCIAL_SENTIMENT"
    BROKER_NOTICE = "BROKER_NOTICE"
    MARKET_STRUCTURE_EVENT = "MARKET_STRUCTURE_EVENT"


@unique
class ExternalVerificationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    UNVERIFIED = "UNVERIFIED"
    CONFLICTING = "CONFLICTING"
    STALE = "STALE"


@unique
class ExternalFeedStatus(str, Enum):
    FEED_DISABLED = "FEED_DISABLED"
    CREDENTIAL_MISSING = "CREDENTIAL_MISSING"
    FEED_AVAILABLE = "FEED_AVAILABLE"
    FEED_RATE_LIMITED = "FEED_RATE_LIMITED"
    FEED_UNAVAILABLE = "FEED_UNAVAILABLE"
    FEED_STALE = "FEED_STALE"


@unique
class SourceLatencyClass(str, Enum):
    REALTIMEISH = "realtimeish"
    SOURCE_DEPENDENT = "source_dependent"
    DELAYED_PUBLIC = "delayed_public"
    DISCLOSURE_DELAYED = "disclosure_delayed"
    SCHEDULED_RELEASE = "scheduled_release"
    WINDOWED = "windowed"
    UNKNOWN = "unknown"


@unique
class DirectionalityHint(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@unique
class MagnitudeHint(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"
    UNKNOWN = "unknown"


@unique
class ConfidenceHint(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"
    UNKNOWN = "unknown"


@unique
class DecayProfileName(str, Enum):
    REGULATORY_FILING_FRESH = "regulatory_filing_fresh"
    INSIDER_DISCLOSURE_DELAYED = "insider_disclosure_delayed"
    POLITICAL_DISCLOSURE_DELAYED = "political_disclosure_delayed"
    ISSUER_RELEASE_WINDOWED = "issuer_release_windowed"
    CALENDAR_EVENT_WINDOWED = "calendar_event_windowed"
    MACRO_RELEASE_WINDOWED = "macro_release_windowed"
    GENERIC_CONTEXT = "generic_context"
