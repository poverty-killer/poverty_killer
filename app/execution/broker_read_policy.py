from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping


PAPER_SMOKE_STRICT_READS = "PAPER_SMOKE_STRICT_READS"
PAPER_TCA_EXTENDED_READS = "PAPER_TCA_EXTENDED_READS"

BROKER_READ_PROFILE_ENV = "PK_BROKER_READ_PROFILE"
BROKER_READ_ALLOWLIST_ENV = "PK_BROKER_READ_ALLOWLIST"
BROKER_READ_DENY_ACCOUNT_ACTIVITIES_ENV = "PK_BROKER_READ_DENY_ACCOUNT_ACTIVITIES"
FEE_HYDRATION_ALLOWED_ENV = "PK_FEE_HYDRATION_ALLOWED"
ACCOUNT_ACTIVITY_READS_ALLOWED_ENV = "PK_ACCOUNT_ACTIVITY_READS_ALLOWED"

BROKER_READ_NOT_AUTHORIZED = "BROKER_READ_NOT_AUTHORIZED"
BROKER_READ_UNKNOWN_FAMILY = "BROKER_READ_UNKNOWN_FAMILY"

READ_ACCOUNT = "account"
READ_ORDERS = "orders"
READ_POSITIONS = "positions"
READ_ACCOUNT_ACTIVITIES = "account_activities"
READ_FILL_ACTIVITY_HYDRATION = "fill_activity_hydration"
READ_FEE_HYDRATION = "fee_hydration"
READ_FEE_ACTIVITIES = "fee_activities"
READ_TRADE_EVENTS = "trade_events"
READ_CLOCK = "clock"
READ_ASSETS = "assets"

KNOWN_READ_FAMILIES = frozenset(
    {
        READ_ACCOUNT,
        READ_ORDERS,
        READ_POSITIONS,
        READ_ACCOUNT_ACTIVITIES,
        READ_FILL_ACTIVITY_HYDRATION,
        READ_FEE_HYDRATION,
        READ_FEE_ACTIVITIES,
        READ_TRADE_EVENTS,
        READ_CLOCK,
        READ_ASSETS,
    }
)

STRICT_ALLOWED_READS = frozenset({READ_ACCOUNT, READ_ORDERS, READ_POSITIONS})
EXTENDED_ALLOWED_READS = frozenset(
    {
        READ_ACCOUNT,
        READ_ORDERS,
        READ_POSITIONS,
        READ_ACCOUNT_ACTIVITIES,
        READ_FILL_ACTIVITY_HYDRATION,
        READ_FEE_HYDRATION,
        READ_FEE_ACTIVITIES,
    }
)


def normalize_broker_read_family(family: Any, activity_type: Any | None = None) -> str:
    normalized = str(family or "").strip().lower().replace("-", "_").replace("/", "_")
    activity = str(activity_type or "").strip().upper()
    if normalized in {"account_activity", "account_activities_fill", "account_activities_fee"}:
        return READ_ACCOUNT_ACTIVITIES
    if normalized in {"fills_activities", "fill_activities", "fill_activity"}:
        return READ_FILL_ACTIVITY_HYDRATION
    if normalized in {"fees_activities", "fee_activity"}:
        return READ_FEE_ACTIVITIES
    if normalized == READ_ACCOUNT_ACTIVITIES and activity in {"CFEE", "FEE", "CFEE,FEE"}:
        return READ_ACCOUNT_ACTIVITIES
    if normalized in KNOWN_READ_FAMILIES:
        return normalized
    return normalized


@dataclass(frozen=True)
class BrokerReadPermissionProfile:
    name: str
    allowed_families: frozenset[str]
    denied_families: frozenset[str]

    @property
    def account_activity_reads_allowed(self) -> bool:
        return self.allows(READ_ACCOUNT_ACTIVITIES)

    @property
    def fee_hydration_allowed(self) -> bool:
        return self.allows(READ_FEE_HYDRATION) and self.account_activity_reads_allowed

    def allows(self, family: Any, activity_type: Any | None = None) -> bool:
        normalized = normalize_broker_read_family(family, activity_type)
        if normalized not in KNOWN_READ_FAMILIES:
            return False
        if normalized in self.denied_families:
            return False
        return normalized in self.allowed_families

    def denial_reason(self, family: Any, activity_type: Any | None = None) -> str:
        normalized = normalize_broker_read_family(family, activity_type)
        if normalized not in KNOWN_READ_FAMILIES:
            return BROKER_READ_UNKNOWN_FAMILY
        return BROKER_READ_NOT_AUTHORIZED

    def to_env(self) -> dict[str, str]:
        return {
            BROKER_READ_PROFILE_ENV: self.name,
            BROKER_READ_ALLOWLIST_ENV: ",".join(sorted(self.allowed_families)),
            BROKER_READ_DENY_ACCOUNT_ACTIVITIES_ENV: "0" if self.account_activity_reads_allowed else "1",
            FEE_HYDRATION_ALLOWED_ENV: "1" if self.fee_hydration_allowed else "0",
            ACCOUNT_ACTIVITY_READS_ALLOWED_ENV: "1" if self.account_activity_reads_allowed else "0",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.name,
            "allowed_families": sorted(self.allowed_families),
            "denied_families": sorted(self.denied_families),
            "account_activity_read_authorized": self.account_activity_reads_allowed,
            "fee_hydration_allowed": self.fee_hydration_allowed,
            "deny_unknown_read_family": True,
        }


def broker_read_profile_for_name(name: Any) -> BrokerReadPermissionProfile:
    normalized = str(name or PAPER_SMOKE_STRICT_READS).strip().upper()
    if normalized == PAPER_TCA_EXTENDED_READS:
        return BrokerReadPermissionProfile(
            name=PAPER_TCA_EXTENDED_READS,
            allowed_families=EXTENDED_ALLOWED_READS,
            denied_families=KNOWN_READ_FAMILIES - EXTENDED_ALLOWED_READS,
        )
    return BrokerReadPermissionProfile(
        name=PAPER_SMOKE_STRICT_READS,
        allowed_families=STRICT_ALLOWED_READS,
        denied_families=KNOWN_READ_FAMILIES - STRICT_ALLOWED_READS,
    )


def coerce_broker_read_profile(value: Any | None = None) -> BrokerReadPermissionProfile:
    if isinstance(value, BrokerReadPermissionProfile):
        return value
    if isinstance(value, Mapping):
        return broker_read_profile_for_name(value.get("profile") or value.get("name"))
    return broker_read_profile_for_name(value)


def broker_read_profile_from_env(env: Mapping[str, str] | None = None) -> BrokerReadPermissionProfile:
    source = env if env is not None else os.environ
    return broker_read_profile_for_name(source.get(BROKER_READ_PROFILE_ENV) or PAPER_SMOKE_STRICT_READS)


def broker_read_allowed(
    family: Any,
    activity_type: Any | None = None,
    *,
    profile: BrokerReadPermissionProfile | Mapping[str, Any] | str | None = None,
    env: Mapping[str, str] | None = None,
) -> bool:
    active_profile = coerce_broker_read_profile(profile) if profile is not None else broker_read_profile_from_env(env)
    return active_profile.allows(family, activity_type)


def broker_read_family_for_get_path(path: str) -> str:
    clean_path = str(path or "").split("?", 1)[0].rstrip("/")
    if clean_path == "/v2/account":
        return READ_ACCOUNT
    if clean_path == "/v2/orders" or clean_path.startswith("/v2/orders/"):
        return READ_ORDERS
    if clean_path == "/v2/positions":
        return READ_POSITIONS
    if clean_path == "/v2/account/activities" or clean_path.startswith("/v2/account/activities/"):
        return READ_ACCOUNT_ACTIVITIES
    if clean_path == "/v2/clock":
        return READ_CLOCK
    if clean_path.startswith("/v2/assets/"):
        return READ_ASSETS
    return clean_path.strip("/").replace("/", "_") or BROKER_READ_UNKNOWN_FAMILY
