from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import unquote

from app.market.venue_capabilities import (
    CapabilityAwareCandidate,
    CredentialStatus,
    PortalAssetClass,
    PortalEnvironment,
    PortalPolicyMode,
    PortalSelectionRequest,
    PortalSelectionResult,
    VenueCapability,
    normalize_asset_class,
    normalize_symbol,
)


ALPACA_PAPER_EQUITIES = (
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "TSLA",
    "AMD",
    "JPM",
    "V",
    "MA",
    "UNH",
    "HD",
    "COST",
    "AVGO",
    "CRM",
    "NFLX",
    "XOM",
    "JNJ",
    "PG",
    "KO",
    "PEP",
    "WMT",
)
ALPACA_PAPER_ETFS = ("SPY", "QQQ", "DIA", "IWM", "XLK", "XLF", "XLE", "XLV", "XLY")
ALPACA_PAPER_CRYPTO = ("BTC/USD", "ETH/USD", "SOL/USD", "LTC/USD", "AVAX/USD", "LINK/USD")
KRAKEN_CRYPTO = ("BTC/USD", "ETH/USD", "SOL/USD", "LTC/USD", "AVAX/USD", "LINK/USD")

ALPACA_CRYPTO_CATALOG_SCHEMA = "alpaca_crypto_catalog_v1"
ALPACA_CRYPTO_UNIVERSE_SCHEMA = "alpaca_crypto_universe_v1"
ALPACA_PAPER_ENDPOINT_FAMILY = "alpaca_paper"
ALPACA_PAPER_EXECUTION_ADAPTER = "alpaca_paper_rest"
ALPACA_CRYPTO_CATALOG_SOURCE = "alpaca_paper_get_v2_assets_active_crypto"
BROKER_CATALOG_REQUIRED = "BROKER_CATALOG_REQUIRED"
MARKET_DATA_UNIVERSE_SCHEMA = "market_data_universe_v1"
MARKET_DATA_OBSERVE_ONLY = "OBSERVE_ONLY"


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_account_suffix(value: Any) -> str:
    normalized = "".join(character for character in str(value or "").strip().lower() if character.isalnum())
    return normalized[-6:] if len(normalized) >= 6 else normalized


def normalize_alpaca_crypto_symbol(
    value: Any,
    *,
    quote_currencies: Sequence[str] = ("USDT", "USDC", "USD"),
) -> str:
    def valid_token(token: str) -> bool:
        return bool(token) and all("A" <= character <= "Z" or "0" <= character <= "9" for character in token)

    if not isinstance(value, str):
        return ""
    raw = unquote(value.strip()).upper().replace("-", "/").replace("_", "/")
    if raw.count("/") == 1:
        base, quote = raw.split("/", 1)
        return f"{base}/{quote}" if valid_token(base) and valid_token(quote) else ""
    if "/" in raw or not raw:
        return ""
    for quote in sorted({str(item).strip().upper() for item in quote_currencies if str(item).strip()}, key=len, reverse=True):
        if raw.endswith(quote) and len(raw) > len(quote):
            base = raw[:-len(quote)]
            return f"{base}/{quote}" if valid_token(base) and valid_token(quote) else ""
    return ""


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _strict_positive_decimal(value: Any, *, field_name: str, reasons: list[str]) -> Decimal | None:
    if isinstance(value, bool) or isinstance(value, float) or value is None or not isinstance(value, (str, Decimal, int)):
        reasons.append(f"{field_name.upper()}_INVALID")
        return None
    text = str(value).strip()
    if not text:
        reasons.append(f"{field_name.upper()}_MISSING")
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        reasons.append(f"{field_name.upper()}_INVALID")
        return None
    if not parsed.is_finite() or parsed <= Decimal("0"):
        reasons.append(f"{field_name.upper()}_NONPOSITIVE_OR_NONFINITE")
        return None
    return parsed


def _strict_broker_bool(row: Mapping[str, Any], field_name: str, reasons: list[str]) -> bool | None:
    value = row.get(field_name)
    if type(value) is not bool:
        reasons.append(f"{field_name.upper()}_TRUTH_MISSING_OR_INVALID")
        return None
    return value


@dataclass(frozen=True)
class BrokerCryptoAssetCapability:
    record_key: str
    asset_id: str
    raw_symbol: str
    normalized_symbol: str
    aliases: tuple[str, ...]
    status: str
    tradable: bool | None
    fractionable: bool | None
    marginable: bool | None
    shortable: bool | None
    min_order_size: Decimal | None
    min_trade_increment: Decimal | None
    price_increment: Decimal | None
    exchange: str
    asset_class: str
    observed_at_ns: int
    source: str
    capability_valid: bool
    reason_codes: tuple[str, ...]

    @property
    def quote_currency(self) -> str | None:
        if self.normalized_symbol.count("/") != 1:
            return None
        return self.normalized_symbol.split("/", 1)[1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_key": self.record_key,
            "asset_id": self.asset_id,
            "raw_symbol": self.raw_symbol,
            "normalized_symbol": self.normalized_symbol,
            "aliases": list(self.aliases),
            "status": self.status,
            "tradable": self.tradable,
            "fractionable": self.fractionable,
            "marginable": self.marginable,
            "shortable": self.shortable,
            "min_order_size": _decimal_text(self.min_order_size),
            "min_trade_increment": _decimal_text(self.min_trade_increment),
            "price_increment": _decimal_text(self.price_increment),
            "exchange": self.exchange,
            "asset_class": self.asset_class,
            "observed_at_ns": self.observed_at_ns,
            "source": self.source,
            "capability_valid": self.capability_valid,
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BrokerCryptoAssetCapability":
        def optional_decimal(field_name: str) -> Decimal | None:
            raw = value.get(field_name)
            if raw in (None, ""):
                return None
            if isinstance(raw, bool) or isinstance(raw, float) or not isinstance(raw, (str, Decimal, int)):
                raise ValueError(f"broker_crypto_{field_name}_invalid")
            try:
                parsed = Decimal(str(raw).strip())
            except (InvalidOperation, ValueError) as exc:
                raise ValueError(f"broker_crypto_{field_name}_invalid") from exc
            if not parsed.is_finite() or parsed <= Decimal("0"):
                raise ValueError(f"broker_crypto_{field_name}_invalid")
            return parsed

        aliases_value = value.get("aliases") or ()
        reason_codes_value = value.get("reason_codes") or ()
        if not isinstance(aliases_value, (list, tuple)):
            raise ValueError("broker_crypto_aliases_invalid")
        if not isinstance(reason_codes_value, (list, tuple)):
            raise ValueError("broker_crypto_asset_reason_codes_invalid")
        for field_name in ("tradable", "fractionable", "marginable", "shortable"):
            if value.get(field_name) is not None and type(value.get(field_name)) is not bool:
                raise ValueError(f"broker_crypto_{field_name}_invalid")
        if type(value.get("capability_valid")) is not bool:
            raise ValueError("broker_crypto_capability_valid_invalid")

        return cls(
            record_key=str(value.get("record_key") or ""),
            asset_id=str(value.get("asset_id") or ""),
            raw_symbol=str(value.get("raw_symbol") or ""),
            normalized_symbol=str(value.get("normalized_symbol") or ""),
            aliases=tuple(str(item) for item in aliases_value),
            status=str(value.get("status") or ""),
            tradable=value.get("tradable") if type(value.get("tradable")) is bool else None,
            fractionable=value.get("fractionable") if type(value.get("fractionable")) is bool else None,
            marginable=value.get("marginable") if type(value.get("marginable")) is bool else None,
            shortable=value.get("shortable") if type(value.get("shortable")) is bool else None,
            min_order_size=optional_decimal("min_order_size"),
            min_trade_increment=optional_decimal("min_trade_increment"),
            price_increment=optional_decimal("price_increment"),
            exchange=str(value.get("exchange") or ""),
            asset_class=str(value.get("asset_class") or ""),
            observed_at_ns=int(value.get("observed_at_ns") or 0),
            source=str(value.get("source") or ""),
            capability_valid=value.get("capability_valid") is True,
            reason_codes=tuple(str(item) for item in reason_codes_value),
        )


@dataclass(frozen=True)
class BrokerCryptoCatalogSnapshot:
    catalog_snapshot_id: str
    schema_version: str
    broker: str
    environment: str
    endpoint_family: str
    expected_account_suffix: str
    actual_account_suffix: str
    observed_at_ns: int
    valid_until_ns: int
    source: str
    source_hash: str
    snapshot_hash: str
    status: str
    reason_codes: tuple[str, ...]
    assets: tuple[BrokerCryptoAssetCapability, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_snapshot_id": self.catalog_snapshot_id,
            "schema_version": self.schema_version,
            "broker": self.broker,
            "environment": self.environment,
            "endpoint_family": self.endpoint_family,
            "expected_account_suffix": self.expected_account_suffix,
            "actual_account_suffix": self.actual_account_suffix,
            "observed_at_ns": self.observed_at_ns,
            "valid_until_ns": self.valid_until_ns,
            "source": self.source,
            "source_hash": self.source_hash,
            "snapshot_hash": self.snapshot_hash,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "asset_count": len(self.assets),
            "assets": [asset.to_dict() for asset in self.assets],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BrokerCryptoCatalogSnapshot":
        assets_value = value.get("assets") or ()
        reason_codes_value = value.get("reason_codes") or ()
        if not isinstance(assets_value, (list, tuple)) or not all(
            isinstance(item, Mapping) for item in assets_value
        ):
            raise ValueError("broker_crypto_catalog_assets_invalid")
        if not isinstance(reason_codes_value, (list, tuple)):
            raise ValueError("broker_crypto_catalog_reason_codes_invalid")
        return cls(
            catalog_snapshot_id=str(value.get("catalog_snapshot_id") or ""),
            schema_version=str(value.get("schema_version") or ""),
            broker=str(value.get("broker") or ""),
            environment=str(value.get("environment") or ""),
            endpoint_family=str(value.get("endpoint_family") or ""),
            expected_account_suffix=str(value.get("expected_account_suffix") or ""),
            actual_account_suffix=str(value.get("actual_account_suffix") or ""),
            observed_at_ns=int(value.get("observed_at_ns") or 0),
            valid_until_ns=int(value.get("valid_until_ns") or 0),
            source=str(value.get("source") or ""),
            source_hash=str(value.get("source_hash") or ""),
            snapshot_hash=str(value.get("snapshot_hash") or ""),
            status=str(value.get("status") or ""),
            reason_codes=tuple(str(item) for item in reason_codes_value),
            assets=tuple(BrokerCryptoAssetCapability.from_dict(item) for item in assets_value),
        )


@dataclass(frozen=True)
class CryptoUniverseMembership:
    record_key: str | None
    asset_id: str | None
    symbol: str
    included_for_entry: bool
    monitor_required: bool
    priority_rank: int | None
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_key": self.record_key,
            "asset_id": self.asset_id,
            "symbol": self.symbol,
            "included_for_entry": self.included_for_entry,
            "monitor_required": self.monitor_required,
            "priority_rank": self.priority_rank,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class BrokerCryptoUniverseSnapshot:
    universe_snapshot_id: str
    schema_version: str
    catalog_snapshot_id: str
    broker: str
    environment: str
    endpoint_family: str
    account_suffix: str
    account_status: str
    crypto_status: str
    trading_blocked: bool | None
    account_blocked: bool | None
    trade_suspended_by_user: bool | None
    execution_adapter: str
    execution_adapter_available: bool | None
    funded_quote_currencies: tuple[str, ...]
    market_data_symbols: tuple[str, ...]
    priority_symbols: tuple[str, ...]
    held_symbols: tuple[str, ...]
    open_order_symbols: tuple[str, ...]
    observed_at_ns: int
    valid_until_ns: int
    status: str
    reason_codes: tuple[str, ...]
    universe_hash: str
    memberships: tuple[CryptoUniverseMembership, ...]

    @property
    def entry_symbols(self) -> tuple[str, ...]:
        eligible = [item for item in self.memberships if item.included_for_entry]
        eligible.sort(key=lambda item: (item.priority_rank is None, item.priority_rank or 0, item.symbol))
        return tuple(item.symbol for item in eligible)

    @property
    def monitor_symbols(self) -> tuple[str, ...]:
        return tuple(sorted(item.symbol for item in self.memberships if item.monitor_required))

    @property
    def runtime_symbols(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.entry_symbols, *self.monitor_symbols)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "universe_snapshot_id": self.universe_snapshot_id,
            "schema_version": self.schema_version,
            "catalog_snapshot_id": self.catalog_snapshot_id,
            "broker": self.broker,
            "environment": self.environment,
            "endpoint_family": self.endpoint_family,
            "account_suffix": self.account_suffix,
            "account_status": self.account_status,
            "crypto_status": self.crypto_status,
            "trading_blocked": self.trading_blocked,
            "account_blocked": self.account_blocked,
            "trade_suspended_by_user": self.trade_suspended_by_user,
            "execution_adapter": self.execution_adapter,
            "execution_adapter_available": self.execution_adapter_available,
            "funded_quote_currencies": list(self.funded_quote_currencies),
            "market_data_symbols": list(self.market_data_symbols),
            "priority_symbols": list(self.priority_symbols),
            "held_symbols": list(self.held_symbols),
            "open_order_symbols": list(self.open_order_symbols),
            "observed_at_ns": self.observed_at_ns,
            "valid_until_ns": self.valid_until_ns,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "universe_hash": self.universe_hash,
            "entry_symbols": list(self.entry_symbols),
            "monitor_symbols": list(self.monitor_symbols),
            "runtime_symbols": list(self.runtime_symbols),
            "membership_count": len(self.memberships),
            "memberships": [item.to_dict() for item in self.memberships],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BrokerCryptoUniverseSnapshot":
        def optional_bool(field_name: str) -> bool | None:
            raw = value.get(field_name)
            return raw if type(raw) is bool else None

        memberships_value = value.get("memberships") or ()
        if not isinstance(memberships_value, (list, tuple)) or not all(
            isinstance(item, Mapping) for item in memberships_value
        ):
            raise ValueError("broker_crypto_universe_memberships_invalid")
        for field_name in (
            "funded_quote_currencies",
            "market_data_symbols",
            "priority_symbols",
            "held_symbols",
            "open_order_symbols",
            "reason_codes",
        ):
            field_value = value.get(field_name) or ()
            if not isinstance(field_value, (list, tuple)):
                raise ValueError(f"broker_crypto_universe_{field_name}_invalid")
        for item in memberships_value:
            priority_rank = item.get("priority_rank")
            if priority_rank is not None and (type(priority_rank) is not int or priority_rank < 0):
                raise ValueError("broker_crypto_universe_priority_rank_invalid")
            if not isinstance(item.get("reason_codes") or (), (list, tuple)):
                raise ValueError("broker_crypto_universe_membership_reason_codes_invalid")
        memberships = tuple(
            CryptoUniverseMembership(
                record_key=str(item.get("record_key")) if item.get("record_key") is not None else None,
                asset_id=str(item.get("asset_id")) if item.get("asset_id") is not None else None,
                symbol=str(item.get("symbol") or ""),
                included_for_entry=item.get("included_for_entry") is True,
                monitor_required=item.get("monitor_required") is True,
                priority_rank=item.get("priority_rank"),
                reason_codes=tuple(str(reason) for reason in item.get("reason_codes") or ()),
            )
            for item in memberships_value
        )
        return cls(
            universe_snapshot_id=str(value.get("universe_snapshot_id") or ""),
            schema_version=str(value.get("schema_version") or ""),
            catalog_snapshot_id=str(value.get("catalog_snapshot_id") or ""),
            broker=str(value.get("broker") or ""),
            environment=str(value.get("environment") or ""),
            endpoint_family=str(value.get("endpoint_family") or ""),
            account_suffix=str(value.get("account_suffix") or ""),
            account_status=str(value.get("account_status") or ""),
            crypto_status=str(value.get("crypto_status") or ""),
            trading_blocked=optional_bool("trading_blocked"),
            account_blocked=optional_bool("account_blocked"),
            trade_suspended_by_user=optional_bool("trade_suspended_by_user"),
            execution_adapter=str(value.get("execution_adapter") or ""),
            execution_adapter_available=optional_bool("execution_adapter_available"),
            funded_quote_currencies=tuple(str(item) for item in value.get("funded_quote_currencies") or ()),
            market_data_symbols=tuple(str(item) for item in value.get("market_data_symbols") or ()),
            priority_symbols=tuple(str(item) for item in value.get("priority_symbols") or ()),
            held_symbols=tuple(str(item) for item in value.get("held_symbols") or ()),
            open_order_symbols=tuple(str(item) for item in value.get("open_order_symbols") or ()),
            observed_at_ns=int(value.get("observed_at_ns") or 0),
            valid_until_ns=int(value.get("valid_until_ns") or 0),
            status=str(value.get("status") or ""),
            reason_codes=tuple(str(item) for item in value.get("reason_codes") or ()),
            universe_hash=str(value.get("universe_hash") or ""),
            memberships=memberships,
        )


def _decimal_tuple(values: Any, *, field_name: str) -> tuple[Decimal, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field_name}_sequence_required")
    normalized: list[Decimal] = []
    for value in values:
        if isinstance(value, bool) or isinstance(value, float):
            raise ValueError(f"{field_name}_exact_decimal_required")
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{field_name}_invalid") from exc
        if not parsed.is_finite() or parsed < Decimal("0"):
            raise ValueError(f"{field_name}_nonfinite_or_negative")
        normalized.append(parsed)
    return tuple(normalized)


def _strict_int(value: Any, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field_name}_integer_domain_invalid")
    return value


def _strict_bool(value: Any, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field_name}_boolean_required")
    return value


def _strict_text(
    value: Any,
    *,
    field_name: str,
    optional: bool = False,
    case: str | None = None,
) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name}_nonempty_string_required")
    normalized = value.strip()
    if case == "lower":
        return normalized.lower()
    if case == "upper":
        return normalized.upper()
    return normalized


def _normalized_symbol_sequence(value: Any, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name}_sequence_required")
    normalized = tuple(normalize_alpaca_crypto_symbol(item) for item in value)
    if any(not item for item in normalized):
        raise ValueError(f"{field_name}_symbol_invalid")
    if normalized != tuple(sorted(set(normalized))):
        raise ValueError(f"{field_name}_must_be_sorted_unique")
    return normalized


def _finite_float_tuple(values: Any, *, field_name: str, nonnegative: bool = False) -> tuple[float, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field_name}_sequence_required")
    normalized: list[float] = []
    for value in values:
        if isinstance(value, bool):
            raise ValueError(f"{field_name}_numeric_required")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name}_invalid") from exc
        if not math.isfinite(parsed) or (nonnegative and parsed < 0.0):
            raise ValueError(f"{field_name}_domain_invalid")
        normalized.append(parsed)
    return tuple(normalized)


_MARKET_DATA_METRIC_FIELDS = frozenset(
    {
        "completeness",
        "clock_quality",
        "log_dollar_volume",
        "log_trade_count",
        "spread_median_bps",
        "spread_mad_bps",
        "log_depth_usd",
        "depth_mad_usd",
        "relative_depth_dispersion",
        "relative_spread_dispersion",
        "estimated_min_order_impact_bps",
        "robust_log_return_volatility",
        "jump_ratio",
        "gap_median_seconds",
        "gap_mad_seconds",
        "observation_span_seconds",
        "listing_age_seconds",
        "listing_age_known",
        "continuity",
        "fundable",
        "cross_venue_basis_bps",
        "cross_venue_basis_age_ms",
        "cross_venue_basis_available",
        "capacity_multiple",
        "uncertainty",
    }
)
_MARKET_DATA_HIGHER_IS_BETTER = frozenset(
    {
        "completeness",
        "clock_quality",
        "log_dollar_volume",
        "log_trade_count",
        "log_depth_usd",
        "observation_span_seconds",
        "listing_age_seconds",
        "listing_age_known",
        "continuity",
        "fundable",
        "cross_venue_basis_available",
        "capacity_multiple",
    }
)
_MARKET_DATA_LOWER_IS_BETTER = frozenset(
    {
        "spread_median_bps",
        "spread_mad_bps",
        "relative_depth_dispersion",
        "relative_spread_dispersion",
        "estimated_min_order_impact_bps",
        "robust_log_return_volatility",
        "jump_ratio",
        "gap_median_seconds",
        "gap_mad_seconds",
        "cross_venue_basis_bps",
        "cross_venue_basis_age_ms",
        "uncertainty",
    }
)
_MARKET_DATA_PERCENTILE_FIELDS = frozenset(
    _MARKET_DATA_HIGHER_IS_BETTER | _MARKET_DATA_LOWER_IS_BETTER
)
_MARKET_DATA_PARETO_FIELDS = (
    "completeness",
    "clock_quality",
    "log_dollar_volume",
    "log_trade_count",
    "spread_median_bps",
    "log_depth_usd",
    "estimated_min_order_impact_bps",
    "robust_log_return_volatility",
    "jump_ratio",
    "gap_median_seconds",
    "listing_age_seconds",
    "listing_age_known",
    "continuity",
    "fundable",
    "cross_venue_basis_available",
    "cross_venue_basis_bps",
    "cross_venue_basis_age_ms",
    "capacity_multiple",
)
_MARKET_DATA_UNIT_INTERVAL_METRICS = frozenset(
    {
        "completeness",
        "clock_quality",
        "listing_age_known",
        "continuity",
        "fundable",
        "cross_venue_basis_available",
        "uncertainty",
    }
)


def _quantile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("quantile_requires_values")
    ordered = sorted(float(value) for value in values)
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile_out_of_range")
    position = (len(ordered) - 1) * quantile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _median(values: Sequence[float]) -> float:
    return _quantile(values, 0.5)


def _median_mad(values: Sequence[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    center = _median(values)
    mad = _median([abs(float(value) - center) for value in values])
    return center, mad


def _winsorized(values: Sequence[float]) -> tuple[float, ...]:
    if not values:
        return ()
    lower = _quantile(values, 0.05)
    upper = _quantile(values, 0.95)
    return tuple(min(upper, max(lower, float(value))) for value in values)


@dataclass(frozen=True)
class MarketBreadthObservation:
    """Causal per-symbol evidence used only for observe-only transport ranking."""

    symbol: str
    provider_id: str
    execution_location: str
    observed_at_ns: int
    latest_source_event_ns: int
    expected_samples: int
    received_samples: int
    dollar_volumes: tuple[Decimal, ...]
    trade_counts: tuple[int, ...]
    spreads_bps: tuple[float, ...]
    depth_usd: tuple[Decimal, ...]
    log_returns: tuple[float, ...]
    event_lag_ms: tuple[float, ...]
    gap_seconds: tuple[float, ...]
    observation_started_ns: int
    listing_started_ns: int | None
    listing_age_source: str | None
    quote_currency: str
    quote_currency_fundable: bool
    execution_mid: Decimal
    cross_venue_mid: Decimal | None
    cross_venue_provider_id: str | None
    cross_venue_source_event_ns: int | None
    cross_venue_received_at_ns: int | None
    min_order_size: Decimal
    min_trade_increment: Decimal
    price_increment: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "provider_id": self.provider_id,
            "execution_location": self.execution_location,
            "observed_at_ns": self.observed_at_ns,
            "latest_source_event_ns": self.latest_source_event_ns,
            "expected_samples": self.expected_samples,
            "received_samples": self.received_samples,
            "dollar_volumes": [_decimal_text(value) for value in self.dollar_volumes],
            "trade_counts": list(self.trade_counts),
            "spreads_bps": list(self.spreads_bps),
            "depth_usd": [_decimal_text(value) for value in self.depth_usd],
            "log_returns": list(self.log_returns),
            "event_lag_ms": list(self.event_lag_ms),
            "gap_seconds": list(self.gap_seconds),
            "observation_started_ns": self.observation_started_ns,
            "listing_started_ns": self.listing_started_ns,
            "listing_age_source": self.listing_age_source,
            "quote_currency": self.quote_currency,
            "quote_currency_fundable": self.quote_currency_fundable,
            "execution_mid": _decimal_text(self.execution_mid),
            "cross_venue_mid": _decimal_text(self.cross_venue_mid),
            "cross_venue_provider_id": self.cross_venue_provider_id,
            "cross_venue_source_event_ns": self.cross_venue_source_event_ns,
            "cross_venue_received_at_ns": self.cross_venue_received_at_ns,
            "min_order_size": _decimal_text(self.min_order_size),
            "min_trade_increment": _decimal_text(self.min_trade_increment),
            "price_increment": _decimal_text(self.price_increment),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MarketBreadthObservation":
        exact_fields = ("execution_mid", "min_order_size", "min_trade_increment", "price_increment")
        exact: dict[str, Decimal] = {}
        for field_name in exact_fields:
            parsed = _decimal_tuple((value.get(field_name),), field_name=field_name)[0]
            if parsed <= 0:
                raise ValueError(f"{field_name}_must_be_positive")
            exact[field_name] = parsed
        cross_value = value.get("cross_venue_mid")
        cross_mid = None
        if cross_value is not None:
            cross_mid = _decimal_tuple((cross_value,), field_name="cross_venue_mid")[0]
            if cross_mid <= 0:
                raise ValueError("cross_venue_mid_must_be_positive")
        trade_counts_value = value.get("trade_counts")
        if not isinstance(trade_counts_value, (list, tuple)) or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in trade_counts_value
        ):
            raise ValueError("trade_counts_nonnegative_integer_sequence_required")
        return cls(
            symbol=normalize_alpaca_crypto_symbol(value.get("symbol")),
            provider_id=_strict_text(value.get("provider_id"), field_name="provider_id"),
            execution_location=_strict_text(
                value.get("execution_location"),
                field_name="execution_location",
                case="lower",
            ),
            observed_at_ns=_strict_int(value.get("observed_at_ns"), field_name="observed_at_ns", minimum=1),
            latest_source_event_ns=_strict_int(
                value.get("latest_source_event_ns"), field_name="latest_source_event_ns", minimum=1
            ),
            expected_samples=_strict_int(value.get("expected_samples"), field_name="expected_samples", minimum=1),
            received_samples=_strict_int(value.get("received_samples"), field_name="received_samples"),
            dollar_volumes=_decimal_tuple(value.get("dollar_volumes") or (), field_name="dollar_volumes"),
            trade_counts=tuple(trade_counts_value),
            spreads_bps=_finite_float_tuple(value.get("spreads_bps") or (), field_name="spreads_bps", nonnegative=True),
            depth_usd=_decimal_tuple(value.get("depth_usd") or (), field_name="depth_usd"),
            log_returns=_finite_float_tuple(value.get("log_returns") or (), field_name="log_returns"),
            event_lag_ms=_finite_float_tuple(value.get("event_lag_ms") or (), field_name="event_lag_ms", nonnegative=True),
            gap_seconds=_finite_float_tuple(value.get("gap_seconds") or (), field_name="gap_seconds", nonnegative=True),
            observation_started_ns=_strict_int(
                value.get("observation_started_ns"), field_name="observation_started_ns", minimum=1
            ),
            listing_started_ns=(
                _strict_int(value["listing_started_ns"], field_name="listing_started_ns", minimum=1)
                if value.get("listing_started_ns") is not None
                else None
            ),
            listing_age_source=_strict_text(
                value.get("listing_age_source"),
                field_name="listing_age_source",
                optional=True,
            ),
            quote_currency=_strict_text(
                value.get("quote_currency"),
                field_name="quote_currency",
                case="upper",
            ),
            quote_currency_fundable=_strict_bool(
                value.get("quote_currency_fundable"), field_name="quote_currency_fundable"
            ),
            execution_mid=exact["execution_mid"],
            cross_venue_mid=cross_mid,
            cross_venue_provider_id=(
                _strict_text(
                    value.get("cross_venue_provider_id"),
                    field_name="cross_venue_provider_id",
                    optional=True,
                )
            ),
            cross_venue_source_event_ns=(
                _strict_int(
                    value["cross_venue_source_event_ns"],
                    field_name="cross_venue_source_event_ns",
                    minimum=1,
                )
                if value.get("cross_venue_source_event_ns") is not None
                else None
            ),
            cross_venue_received_at_ns=(
                _strict_int(
                    value["cross_venue_received_at_ns"],
                    field_name="cross_venue_received_at_ns",
                    minimum=1,
                )
                if value.get("cross_venue_received_at_ns") is not None
                else None
            ),
            min_order_size=exact["min_order_size"],
            min_trade_increment=exact["min_trade_increment"],
            price_increment=exact["price_increment"],
        )


@dataclass(frozen=True)
class MarketDataRankedMembership:
    symbol: str
    rank: int
    pareto_front: int
    percentile_median: float
    uncertainty: float
    protected: bool
    deep_selected: bool
    residence_started_ns: int | None
    execution_authorized: bool
    activation_mode: str
    listing_started_ns: int | None
    listing_age_source: str | None
    cross_venue_provider_id: str | None
    cross_venue_source_event_ns: int | None
    cross_venue_received_at_ns: int | None
    metrics: tuple[tuple[str, float], ...]
    percentiles: tuple[tuple[str, float], ...]
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "rank": self.rank,
            "pareto_front": self.pareto_front,
            "percentile_median": self.percentile_median,
            "uncertainty": self.uncertainty,
            "protected": self.protected,
            "deep_selected": self.deep_selected,
            "residence_started_ns": self.residence_started_ns,
            "execution_authorized": self.execution_authorized,
            "activation_mode": self.activation_mode,
            "listing_started_ns": self.listing_started_ns,
            "listing_age_source": self.listing_age_source,
            "cross_venue_provider_id": self.cross_venue_provider_id,
            "cross_venue_source_event_ns": self.cross_venue_source_event_ns,
            "cross_venue_received_at_ns": self.cross_venue_received_at_ns,
            "metrics": {key: value for key, value in self.metrics},
            "percentiles": {key: value for key, value in self.percentiles},
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MarketDataRankedMembership":
        metrics = value.get("metrics") or {}
        percentiles = value.get("percentiles") or {}
        if not isinstance(metrics, Mapping) or not isinstance(percentiles, Mapping):
            raise ValueError("market_data_membership_metrics_mapping_required")
        if set(metrics) != _MARKET_DATA_METRIC_FIELDS or set(percentiles) != _MARKET_DATA_PERCENTILE_FIELDS:
            raise ValueError("market_data_membership_metric_schema_invalid")
        if any(isinstance(number, bool) for number in (*metrics.values(), *percentiles.values())):
            raise ValueError("market_data_membership_boolean_metric_invalid")
        normalized_metrics = tuple(sorted((str(key), float(number)) for key, number in metrics.items()))
        normalized_percentiles = tuple(sorted((str(key), float(number)) for key, number in percentiles.items()))
        if any(not math.isfinite(number) for _, number in (*normalized_metrics, *normalized_percentiles)):
            raise ValueError("market_data_membership_nonfinite_metric")
        if any(number < 0.0 for _, number in normalized_metrics):
            raise ValueError("market_data_membership_negative_metric")
        if any(not 0.0 <= number <= 1.0 for _, number in normalized_percentiles):
            raise ValueError("market_data_membership_percentile_domain_invalid")
        if isinstance(value.get("percentile_median"), bool) or isinstance(value.get("uncertainty"), bool):
            raise ValueError("market_data_membership_boolean_summary_invalid")
        percentile_median = float(value.get("percentile_median") or 0.0)
        uncertainty = float(value.get("uncertainty") or 0.0)
        if not math.isfinite(percentile_median) or not 0.0 <= percentile_median <= 1.0:
            raise ValueError("market_data_membership_percentile_median_invalid")
        if not math.isfinite(uncertainty) or not 0.0 <= uncertainty <= 1.0:
            raise ValueError("market_data_membership_uncertainty_invalid")
        reason_codes_value = value.get("reason_codes") or ()
        if (
            not isinstance(reason_codes_value, (list, tuple))
            or not reason_codes_value
            or any(not isinstance(item, str) or not item.strip() for item in reason_codes_value)
            or len(set(reason_codes_value)) != len(reason_codes_value)
        ):
            raise ValueError("market_data_membership_reason_codes_invalid")
        return cls(
            symbol=normalize_alpaca_crypto_symbol(value.get("symbol")),
            rank=_strict_int(value.get("rank"), field_name="market_data_membership_rank", minimum=1),
            pareto_front=_strict_int(
                value.get("pareto_front"), field_name="market_data_membership_pareto_front", minimum=1
            ),
            percentile_median=percentile_median,
            uncertainty=uncertainty,
            protected=_strict_bool(value.get("protected"), field_name="market_data_membership_protected"),
            deep_selected=_strict_bool(
                value.get("deep_selected"), field_name="market_data_membership_deep_selected"
            ),
            residence_started_ns=(
                _strict_int(
                    value["residence_started_ns"],
                    field_name="market_data_membership_residence_started_ns",
                    minimum=1,
                )
                if value.get("residence_started_ns") is not None
                else None
            ),
            execution_authorized=_strict_bool(
                value.get("execution_authorized"),
                field_name="market_data_membership_execution_authorized",
            ),
            activation_mode=_strict_text(
                value.get("activation_mode"),
                field_name="market_data_membership_activation_mode",
            ),
            listing_started_ns=(
                _strict_int(
                    value["listing_started_ns"],
                    field_name="market_data_membership_listing_started_ns",
                    minimum=1,
                )
                if value.get("listing_started_ns") is not None
                else None
            ),
            listing_age_source=_strict_text(
                value.get("listing_age_source"),
                field_name="market_data_membership_listing_age_source",
                optional=True,
            ),
            cross_venue_provider_id=(
                _strict_text(
                    value.get("cross_venue_provider_id"),
                    field_name="market_data_membership_cross_venue_provider_id",
                    optional=True,
                )
            ),
            cross_venue_source_event_ns=(
                _strict_int(
                    value["cross_venue_source_event_ns"],
                    field_name="market_data_membership_cross_venue_source_event_ns",
                    minimum=1,
                )
                if value.get("cross_venue_source_event_ns") is not None
                else None
            ),
            cross_venue_received_at_ns=(
                _strict_int(
                    value["cross_venue_received_at_ns"],
                    field_name="market_data_membership_cross_venue_received_at_ns",
                    minimum=1,
                )
                if value.get("cross_venue_received_at_ns") is not None
                else None
            ),
            metrics=normalized_metrics,
            percentiles=normalized_percentiles,
            reason_codes=tuple(reason_codes_value),
        )


@dataclass(frozen=True)
class MarketDataUniverseSnapshot:
    snapshot_id: str
    schema_version: str
    catalog_snapshot_id: str
    broker_universe_snapshot_id: str
    as_of_ns: int
    observation_cutoff_ns: int
    created_at_ns: int
    activation_mode: str
    execution_authorized: bool
    provider_id: str
    execution_location: str
    held_symbols: tuple[str, ...]
    open_order_symbols: tuple[str, ...]
    lifecycle_symbols: tuple[str, ...]
    deep_candidate_limit: int
    deep_subscription_limit: int
    min_residence_ns: int
    unranked_symbols: tuple[str, ...]
    memberships: tuple[MarketDataRankedMembership, ...]
    snapshot_hash: str

    @property
    def deep_symbols(self) -> tuple[str, ...]:
        return tuple(item.symbol for item in self.memberships if item.deep_selected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "schema_version": self.schema_version,
            "catalog_snapshot_id": self.catalog_snapshot_id,
            "broker_universe_snapshot_id": self.broker_universe_snapshot_id,
            "as_of_ns": self.as_of_ns,
            "observation_cutoff_ns": self.observation_cutoff_ns,
            "created_at_ns": self.created_at_ns,
            "activation_mode": self.activation_mode,
            "execution_authorized": self.execution_authorized,
            "provider_id": self.provider_id,
            "execution_location": self.execution_location,
            "held_symbols": list(self.held_symbols),
            "open_order_symbols": list(self.open_order_symbols),
            "lifecycle_symbols": list(self.lifecycle_symbols),
            "deep_candidate_limit": self.deep_candidate_limit,
            "deep_subscription_limit": self.deep_subscription_limit,
            "min_residence_ns": self.min_residence_ns,
            "unranked_symbols": list(self.unranked_symbols),
            "memberships": [item.to_dict() for item in self.memberships],
            "snapshot_hash": self.snapshot_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MarketDataUniverseSnapshot":
        memberships_value = value.get("memberships") or ()
        if not isinstance(memberships_value, (list, tuple)):
            raise ValueError("market_data_memberships_sequence_required")
        held_symbols = _normalized_symbol_sequence(
            value.get("held_symbols"), field_name="market_data_universe_held_symbols"
        )
        open_order_symbols = _normalized_symbol_sequence(
            value.get("open_order_symbols"), field_name="market_data_universe_open_order_symbols"
        )
        lifecycle_symbols = _normalized_symbol_sequence(
            value.get("lifecycle_symbols"), field_name="market_data_universe_lifecycle_symbols"
        )
        unranked_symbols = _normalized_symbol_sequence(
            value.get("unranked_symbols"), field_name="market_data_universe_unranked_symbols"
        )
        snapshot = cls(
            snapshot_id=_strict_text(
                value.get("snapshot_id"), field_name="market_data_universe_snapshot_id"
            ),
            schema_version=_strict_text(
                value.get("schema_version"), field_name="market_data_universe_schema_version"
            ),
            catalog_snapshot_id=_strict_text(
                value.get("catalog_snapshot_id"), field_name="market_data_universe_catalog_snapshot_id"
            ),
            broker_universe_snapshot_id=_strict_text(
                value.get("broker_universe_snapshot_id"),
                field_name="market_data_universe_broker_universe_snapshot_id",
            ),
            as_of_ns=_strict_int(value.get("as_of_ns"), field_name="market_data_universe_as_of_ns", minimum=1),
            observation_cutoff_ns=_strict_int(
                value.get("observation_cutoff_ns"), field_name="market_data_universe_observation_cutoff_ns", minimum=1
            ),
            created_at_ns=_strict_int(
                value.get("created_at_ns"), field_name="market_data_universe_created_at_ns", minimum=1
            ),
            activation_mode=_strict_text(
                value.get("activation_mode"), field_name="market_data_universe_activation_mode"
            ),
            execution_authorized=_strict_bool(
                value.get("execution_authorized"), field_name="market_data_universe_execution_authorized"
            ),
            provider_id=_strict_text(
                value.get("provider_id"), field_name="market_data_universe_provider_id"
            ),
            execution_location=_strict_text(
                value.get("execution_location"),
                field_name="market_data_universe_execution_location",
                case="lower",
            ),
            held_symbols=held_symbols,
            open_order_symbols=open_order_symbols,
            lifecycle_symbols=lifecycle_symbols,
            deep_candidate_limit=_strict_int(
                value.get("deep_candidate_limit"), field_name="market_data_universe_deep_candidate_limit", minimum=1
            ),
            deep_subscription_limit=_strict_int(
                value.get("deep_subscription_limit"),
                field_name="market_data_universe_deep_subscription_limit",
                minimum=1,
            ),
            min_residence_ns=_strict_int(
                value.get("min_residence_ns"), field_name="market_data_universe_min_residence_ns"
            ),
            unranked_symbols=unranked_symbols,
            memberships=tuple(MarketDataRankedMembership.from_dict(item) for item in memberships_value),
            snapshot_hash=_strict_text(
                value.get("snapshot_hash"), field_name="market_data_universe_snapshot_hash"
            ),
        )
        stable = snapshot.to_dict()
        stable.pop("snapshot_id", None)
        stable.pop("snapshot_hash", None)
        expected_hash = _stable_hash(stable)
        if snapshot.schema_version != MARKET_DATA_UNIVERSE_SCHEMA:
            raise ValueError("market_data_universe_schema_invalid")
        if snapshot.snapshot_hash != expected_hash or snapshot.snapshot_id != f"market-universe-{expected_hash[:24]}":
            raise ValueError("market_data_universe_integrity_invalid")
        if snapshot.activation_mode != MARKET_DATA_OBSERVE_ONLY or snapshot.execution_authorized:
            raise ValueError("market_data_universe_observe_only_required")
        if not snapshot.catalog_snapshot_id or not snapshot.broker_universe_snapshot_id:
            raise ValueError("market_data_universe_lineage_required")
        if snapshot.as_of_ns <= 0 or snapshot.created_at_ns < snapshot.as_of_ns:
            raise ValueError("market_data_universe_time_invalid")
        if snapshot.observation_cutoff_ns <= 0 or snapshot.observation_cutoff_ns > snapshot.as_of_ns:
            raise ValueError("market_data_universe_observation_cutoff_invalid")
        if snapshot.execution_location != "alpaca" or not snapshot.provider_id.startswith("alpaca_crypto_"):
            raise ValueError("market_data_universe_execution_location_invalid")
        if (
            snapshot.deep_candidate_limit <= 0
            or snapshot.deep_subscription_limit <= 0
            or snapshot.deep_candidate_limit > snapshot.deep_subscription_limit
            or snapshot.min_residence_ns < 0
        ):
            raise ValueError("market_data_universe_capacity_invalid")
        symbols = tuple(item.symbol for item in snapshot.memberships)
        if not symbols or any(not symbol for symbol in symbols) or len(set(symbols)) != len(symbols):
            raise ValueError("market_data_universe_membership_symbols_invalid")
        if set(symbols) & set(snapshot.unranked_symbols):
            raise ValueError("market_data_universe_ranked_unranked_overlap")
        ranks = tuple(item.rank for item in snapshot.memberships)
        if ranks != tuple(range(1, len(ranks) + 1)):
            raise ValueError("market_data_universe_membership_ranks_invalid")
        protected = frozenset((*snapshot.held_symbols, *snapshot.open_order_symbols, *snapshot.lifecycle_symbols))
        if not protected.issubset(symbols):
            raise ValueError("market_data_universe_protected_symbol_missing")
        if len(snapshot.deep_symbols) > snapshot.deep_subscription_limit:
            raise ValueError("market_data_universe_deep_capacity_exceeded")
        if len(set(snapshot.deep_symbols) - protected) > snapshot.deep_candidate_limit:
            raise ValueError("market_data_universe_dynamic_deep_capacity_exceeded")
        percentiles_by_symbol = {item.symbol: dict(item.percentiles) for item in snapshot.memberships}
        expected_fronts = _pareto_fronts(percentiles_by_symbol)
        expected_order = sorted(
            snapshot.memberships,
            key=lambda item: (
                expected_fronts[item.symbol],
                item.uncertainty,
                -item.percentile_median,
                item.symbol,
            ),
        )
        if tuple(item.symbol for item in expected_order) != symbols:
            raise ValueError("market_data_universe_membership_order_invalid")
        for membership in snapshot.memberships:
            if membership.activation_mode != MARKET_DATA_OBSERVE_ONLY or membership.execution_authorized:
                raise ValueError("market_data_universe_membership_authority_invalid")
            if membership.protected != (membership.symbol in protected):
                raise ValueError("market_data_universe_membership_protection_invalid")
            if membership.protected and not membership.deep_selected:
                raise ValueError("market_data_universe_protected_symbol_not_deep")
            if membership.deep_selected != (membership.residence_started_ns is not None):
                raise ValueError("market_data_universe_residence_state_invalid")
            if membership.residence_started_ns is not None and not 0 < membership.residence_started_ns <= snapshot.as_of_ns:
                raise ValueError("market_data_universe_residence_time_invalid")
            metrics = dict(membership.metrics)
            percentiles = dict(membership.percentiles)
            if membership.pareto_front != expected_fronts[membership.symbol]:
                raise ValueError("market_data_universe_pareto_front_invalid")
            if not math.isclose(
                membership.percentile_median,
                _median(tuple(percentiles.values())),
                rel_tol=0.0,
                abs_tol=1e-15,
            ):
                raise ValueError("market_data_universe_percentile_median_invalid")
            if not math.isclose(membership.uncertainty, metrics["uncertainty"], rel_tol=0.0, abs_tol=1e-15):
                raise ValueError("market_data_universe_uncertainty_mismatch")
            if any(not 0.0 <= metrics[field_name] <= 1.0 for field_name in _MARKET_DATA_UNIT_INTERVAL_METRICS):
                raise ValueError("market_data_universe_unit_interval_metric_invalid")
            if "DYNAMIC_MEMBERSHIP_OBSERVE_ONLY" not in membership.reason_codes:
                raise ValueError("market_data_universe_observe_only_reason_missing")
            if membership.protected != ("PROTECTED_LIFECYCLE_DEEP_REQUIRED" in membership.reason_codes):
                raise ValueError("market_data_universe_protection_reason_invalid")
            listing_fields_present = membership.listing_started_ns is not None or membership.listing_age_source is not None
            if listing_fields_present and (
                membership.listing_started_ns is None
                or not membership.listing_age_source
                or not 0 < membership.listing_started_ns <= snapshot.observation_cutoff_ns
            ):
                raise ValueError("market_data_universe_listing_provenance_invalid")
            cross_fields_present = (
                membership.cross_venue_provider_id is not None
                or membership.cross_venue_source_event_ns is not None
                or membership.cross_venue_received_at_ns is not None
            )
            if cross_fields_present and (
                not membership.cross_venue_provider_id
                or membership.cross_venue_provider_id.startswith("alpaca_crypto_")
                or membership.cross_venue_source_event_ns is None
                or membership.cross_venue_received_at_ns is None
                or not 0
                < membership.cross_venue_source_event_ns
                <= membership.cross_venue_received_at_ns
                <= snapshot.as_of_ns
                or membership.cross_venue_source_event_ns > snapshot.observation_cutoff_ns
            ):
                raise ValueError("market_data_universe_cross_venue_provenance_invalid")
            if (metrics["cross_venue_basis_available"] == 1.0) != cross_fields_present:
                raise ValueError("market_data_universe_cross_venue_metric_mismatch")
            if (metrics["listing_age_known"] == 1.0) != listing_fields_present:
                raise ValueError("market_data_universe_listing_metric_mismatch")
        return snapshot


def _observation_metrics(observation: MarketBreadthObservation, *, as_of_ns: int) -> dict[str, float]:
    if (
        not observation.symbol
        or observation.execution_location != "alpaca"
        or observation.provider_id != "alpaca_crypto_rest"
    ):
        raise ValueError("execution_location_observation_required")
    if observation.observed_at_ns <= 0 or observation.latest_source_event_ns <= 0:
        raise ValueError("observation_timestamp_required")
    if observation.observed_at_ns > as_of_ns or observation.latest_source_event_ns > as_of_ns:
        raise ValueError("future_market_observation_refused")
    if observation.latest_source_event_ns > observation.observed_at_ns:
        raise ValueError("source_event_after_observation_refused")
    if observation.expected_samples <= 0 or not 1 <= observation.received_samples <= observation.expected_samples:
        raise ValueError("observation_sample_counts_invalid")
    if (
        not observation.quote_currency
        or observation.observation_started_ns <= 0
        or observation.observation_started_ns > observation.latest_source_event_ns
    ):
        raise ValueError("observation_history_or_quote_truth_invalid")
    listing_fields_present = observation.listing_started_ns is not None or observation.listing_age_source is not None
    if listing_fields_present and (
        observation.listing_started_ns is None
        or not observation.listing_age_source
        or observation.listing_started_ns <= 0
        or observation.listing_started_ns > observation.latest_source_event_ns
    ):
        raise ValueError("listing_age_provenance_invalid")
    cross_fields_present = any(
        value is not None
        for value in (
            observation.cross_venue_mid,
            observation.cross_venue_provider_id,
            observation.cross_venue_source_event_ns,
            observation.cross_venue_received_at_ns,
        )
    )
    if cross_fields_present and (
        observation.cross_venue_mid is None
        or not observation.cross_venue_provider_id
        or observation.cross_venue_provider_id.startswith("alpaca_crypto_")
        or observation.cross_venue_source_event_ns is None
        or observation.cross_venue_received_at_ns is None
        or observation.cross_venue_source_event_ns <= 0
        or not observation.cross_venue_source_event_ns
        <= observation.cross_venue_received_at_ns
        <= observation.observed_at_ns
        <= as_of_ns
    ):
        raise ValueError("cross_venue_advisory_provenance_invalid")
    if observation.execution_mid <= 0 or any(
        value <= 0 for value in (observation.min_order_size, observation.min_trade_increment, observation.price_increment)
    ):
        raise ValueError("observation_execution_constraints_invalid")

    dollar_volume = [float(value) for value in observation.dollar_volumes]
    depth_usd = [float(value) for value in observation.depth_usd]
    if any(not math.isfinite(value) or value < 0.0 for value in (*dollar_volume, *depth_usd)):
        raise ValueError("observation_decimal_conversion_invalid")
    if any(count < 0 for count in observation.trade_counts):
        raise ValueError("observation_trade_count_invalid")
    spreads = _finite_float_tuple(observation.spreads_bps, field_name="spreads_bps", nonnegative=True)
    returns = _finite_float_tuple(observation.log_returns, field_name="log_returns")
    lags = _finite_float_tuple(observation.event_lag_ms, field_name="event_lag_ms", nonnegative=True)
    gaps = _finite_float_tuple(observation.gap_seconds, field_name="gap_seconds", nonnegative=True)
    primary_lengths = {
        len(dollar_volume),
        len(observation.trade_counts),
        len(spreads),
        len(depth_usd),
        len(lags),
    }
    expected_derived_length = max(0, observation.received_samples - 1)
    if primary_lengths != {observation.received_samples} or len(returns) != expected_derived_length or len(gaps) != expected_derived_length:
        raise ValueError("observation_sample_array_lengths_invalid")

    winsor_volume = _winsorized(dollar_volume)
    winsor_trades = _winsorized([float(value) for value in observation.trade_counts])
    spread_median, spread_mad = _median_mad(spreads)
    depth_median, depth_mad = _median_mad(depth_usd)
    return_median, return_mad = _median_mad(returns)
    lag_median, lag_mad = _median_mad(lags)
    gap_median, gap_mad = _median_mad(gaps)
    minimum_quantity_lots = (
        observation.min_order_size / observation.min_trade_increment
    ).to_integral_value(rounding=ROUND_CEILING)
    minimum_executable_quantity = max(Decimal("1"), minimum_quantity_lots) * observation.min_trade_increment
    reference_price_ticks = (
        observation.execution_mid / observation.price_increment
    ).to_integral_value(rounding=ROUND_CEILING)
    executable_reference_price = max(Decimal("1"), reference_price_ticks) * observation.price_increment
    min_order_notional = float(executable_reference_price * minimum_executable_quantity)
    capacity_multiple = depth_median / max(min_order_notional, 1e-12)
    impact_bps = min_order_notional / max(depth_median, 1e-12) * 10_000.0
    basis_bps = 0.0
    if observation.cross_venue_mid is not None:
        basis_bps = float(abs(observation.cross_venue_mid - observation.execution_mid) / observation.execution_mid * Decimal("10000"))
    basis_age_ms = (
        max(0.0, (observation.observed_at_ns - int(observation.cross_venue_source_event_ns or 0)) / 1_000_000.0)
        if observation.cross_venue_source_event_ns is not None
        else 0.0
    )
    effective_samples = min(observation.received_samples, len(returns), len(gaps))
    completeness = observation.received_samples / observation.expected_samples
    continuity = min(1.0, effective_samples / max(1.0, float(observation.expected_samples)))
    robust_volatility = 1.4826 * return_mad
    jump_ratio = max((abs(value - return_median) for value in returns), default=0.0) / max(robust_volatility, 1e-12)
    relative_depth_dispersion = depth_mad / max(depth_median, 1e-12)
    relative_spread_dispersion = spread_mad / max(spread_median, 1e-12)
    uncertainty = min(
        1.0,
        max(
            1.0 - completeness,
            1.0 / math.sqrt(max(1, effective_samples)),
            min(1.0, relative_depth_dispersion + relative_spread_dispersion),
            0.0 if observation.listing_started_ns is not None else 1.0,
            0.0 if observation.cross_venue_mid is not None else 1.0,
        ),
    )
    metrics = {
        "completeness": completeness,
        "clock_quality": 1.0 / (1.0 + (lag_median + lag_mad) / 1000.0),
        "log_dollar_volume": _median([math.log1p(value) for value in winsor_volume]) if winsor_volume else 0.0,
        "log_trade_count": _median([math.log1p(value) for value in winsor_trades]) if winsor_trades else 0.0,
        "spread_median_bps": spread_median,
        "spread_mad_bps": spread_mad,
        "log_depth_usd": math.log1p(max(0.0, depth_median)),
        "depth_mad_usd": depth_mad,
        "relative_depth_dispersion": relative_depth_dispersion,
        "relative_spread_dispersion": relative_spread_dispersion,
        "estimated_min_order_impact_bps": impact_bps,
        "robust_log_return_volatility": robust_volatility,
        "jump_ratio": jump_ratio,
        "gap_median_seconds": gap_median,
        "gap_mad_seconds": gap_mad,
        "observation_span_seconds": (observation.latest_source_event_ns - observation.observation_started_ns) / 1_000_000_000.0,
        "listing_age_seconds": (
            (as_of_ns - int(observation.listing_started_ns or as_of_ns)) / 1_000_000_000.0
        ),
        "listing_age_known": 1.0 if observation.listing_started_ns is not None else 0.0,
        "continuity": continuity,
        "fundable": 1.0 if observation.quote_currency_fundable else 0.0,
        "cross_venue_basis_bps": basis_bps,
        "cross_venue_basis_age_ms": basis_age_ms,
        "cross_venue_basis_available": 1.0 if observation.cross_venue_mid is not None else 0.0,
        "capacity_multiple": capacity_multiple,
        "uncertainty": uncertainty,
    }
    if set(metrics) != _MARKET_DATA_METRIC_FIELDS:
        raise RuntimeError("market_data_metric_schema_internal_mismatch")
    if any(not math.isfinite(value) or value < 0.0 for value in metrics.values()):
        raise ValueError("market_data_observation_metric_domain_invalid")
    if any(not 0.0 <= metrics[field_name] <= 1.0 for field_name in _MARKET_DATA_UNIT_INTERVAL_METRICS):
        raise ValueError("market_data_observation_unit_interval_metric_invalid")
    return metrics


def _empirical_percentiles(
    metrics_by_symbol: Mapping[str, Mapping[str, float]],
) -> dict[str, dict[str, float]]:
    fields = tuple(sorted(_MARKET_DATA_PERCENTILE_FIELDS))
    result = {symbol: {} for symbol in metrics_by_symbol}
    for field_name in fields:
        basis_field = field_name in {"cross_venue_basis_bps", "cross_venue_basis_age_ms"}
        ordered = sorted(
            (float(metrics[field_name]), symbol)
            for symbol, metrics in metrics_by_symbol.items()
            if not basis_field or metrics["cross_venue_basis_available"] == 1.0
        )
        if basis_field:
            for symbol, metrics in metrics_by_symbol.items():
                if metrics["cross_venue_basis_available"] == 0.0:
                    result[symbol][field_name] = 0.0
        if not ordered:
            continue
        denominator = max(1, len(ordered) - 1)
        index_by_value: dict[float, list[int]] = {}
        for index, (value, _) in enumerate(ordered):
            index_by_value.setdefault(value, []).append(index)
        for value, symbol in ordered:
            average_index = sum(index_by_value[value]) / len(index_by_value[value])
            percentile = average_index / denominator if len(ordered) > 1 else 1.0
            result[symbol][field_name] = (
                percentile if field_name in _MARKET_DATA_HIGHER_IS_BETTER else 1.0 - percentile
            )
    return result


def _pareto_fronts(percentiles: Mapping[str, Mapping[str, float]]) -> dict[str, int]:
    fields = _MARKET_DATA_PARETO_FIELDS
    symbols = tuple(sorted(percentiles))
    dominates: list[list[int]] = [[] for _ in symbols]
    domination_count = [0 for _ in symbols]

    def relation(left: int, right: int) -> int:
        left_vector = percentiles[symbols[left]]
        right_vector = percentiles[symbols[right]]
        left_no_worse = all(left_vector[field] >= right_vector[field] for field in fields)
        right_no_worse = all(right_vector[field] >= left_vector[field] for field in fields)
        if left_no_worse and any(left_vector[field] > right_vector[field] for field in fields):
            return 1
        if right_no_worse and any(right_vector[field] > left_vector[field] for field in fields):
            return -1
        return 0

    for left in range(len(symbols)):
        for right in range(left + 1, len(symbols)):
            comparison = relation(left, right)
            if comparison > 0:
                dominates[left].append(right)
                domination_count[right] += 1
            elif comparison < 0:
                dominates[right].append(left)
                domination_count[left] += 1

    current = [index for index, count in enumerate(domination_count) if count == 0]
    fronts: dict[str, int] = {}
    front_number = 1
    while current:
        next_front: list[int] = []
        for index in sorted(current, key=lambda item: symbols[item]):
            fronts[symbols[index]] = front_number
            for dominated_index in dominates[index]:
                domination_count[dominated_index] -= 1
                if domination_count[dominated_index] == 0:
                    next_front.append(dominated_index)
        current = next_front
        front_number += 1
    if len(fronts) != len(symbols):
        raise ValueError("pareto_front_construction_failed")
    return fronts


def build_market_data_universe_snapshot(
    observations: Sequence[MarketBreadthObservation | Mapping[str, Any]],
    *,
    catalog_snapshot_id: str,
    broker_universe_snapshot_id: str,
    as_of_ns: int,
    created_at_ns: int,
    held_symbols: Sequence[str] = (),
    open_order_symbols: Sequence[str] = (),
    lifecycle_symbols: Sequence[str] = (),
    prior_snapshot: MarketDataUniverseSnapshot | Mapping[str, Any] | None = None,
    deep_candidate_limit: int = 12,
    deep_subscription_limit: int = 30,
    min_residence_ns: int = 900_000_000_000,
    unranked_symbols: Sequence[str] = (),
) -> MarketDataUniverseSnapshot:
    """Build an immutable, causal, observe-only deep-membership snapshot."""
    if not catalog_snapshot_id or not broker_universe_snapshot_id:
        raise ValueError("market_data_universe_lineage_required")
    if as_of_ns <= 0 or created_at_ns < as_of_ns:
        raise ValueError("market_data_universe_time_invalid")
    if deep_candidate_limit <= 0 or deep_subscription_limit <= 0 or deep_candidate_limit > deep_subscription_limit:
        raise ValueError("market_data_universe_capacity_invalid")
    if min_residence_ns < 0:
        raise ValueError("market_data_universe_residence_invalid")

    normalized = tuple(
        MarketBreadthObservation.from_dict(item.to_dict() if isinstance(item, MarketBreadthObservation) else item)
        for item in observations
    )
    if not normalized:
        raise ValueError("market_data_observations_required")
    if len({item.symbol for item in normalized}) != len(normalized) or any(not item.symbol for item in normalized):
        raise ValueError("market_data_observation_symbol_invalid_or_duplicate")
    normalized_unranked = tuple(
        sorted(
            {
                normalized_symbol
                for symbol in unranked_symbols
                if (normalized_symbol := normalize_alpaca_crypto_symbol(symbol))
            }
        )
    )
    if len(normalized_unranked) != len(tuple(unranked_symbols)):
        raise ValueError("market_data_unranked_symbols_invalid_or_duplicate")
    if set(normalized_unranked) & {item.symbol for item in normalized}:
        raise ValueError("market_data_ranked_unranked_overlap")
    provider_ids = {item.provider_id for item in normalized}
    locations = {item.execution_location for item in normalized}
    if len(provider_ids) != 1 or locations != {"alpaca"}:
        raise ValueError("single_execution_location_provider_required")

    metrics_by_symbol = {item.symbol: _observation_metrics(item, as_of_ns=as_of_ns) for item in normalized}
    observation_by_symbol = {item.symbol: item for item in normalized}
    percentiles = _empirical_percentiles(metrics_by_symbol)
    fronts = _pareto_fronts(percentiles)
    median_percentile = {
        symbol: _median(tuple(values.values())) for symbol, values in percentiles.items()
    }
    ordered_symbols = sorted(
        metrics_by_symbol,
        key=lambda symbol: (
            fronts[symbol],
            metrics_by_symbol[symbol]["uncertainty"],
            -median_percentile[symbol],
            symbol,
        ),
    )
    rank_by_symbol = {symbol: index + 1 for index, symbol in enumerate(ordered_symbols)}

    protected = {
        normalize_alpaca_crypto_symbol(symbol)
        for symbol in (*held_symbols, *open_order_symbols, *lifecycle_symbols)
    }
    protected.discard("")
    missing_protected = protected - set(metrics_by_symbol)
    if missing_protected:
        raise ValueError("protected_symbol_observation_missing:" + ",".join(sorted(missing_protected)))
    if protected & set(normalized_unranked):
        raise ValueError("protected_symbol_cannot_be_unranked")
    if len(protected) > deep_subscription_limit:
        raise ValueError("protected_deep_capacity_exceeded")

    prior = None
    if prior_snapshot is not None:
        prior = MarketDataUniverseSnapshot.from_dict(
            prior_snapshot.to_dict() if isinstance(prior_snapshot, MarketDataUniverseSnapshot) else prior_snapshot
        )
        if prior.as_of_ns > as_of_ns or prior.created_at_ns > as_of_ns:
            raise ValueError("future_prior_universe_refused")
        if prior.catalog_snapshot_id != catalog_snapshot_id or prior.broker_universe_snapshot_id != broker_universe_snapshot_id:
            raise ValueError("prior_market_data_universe_lineage_mismatch")
        prior_scope = {item.symbol for item in prior.memberships} | set(prior.unranked_symbols)
        current_scope = set(metrics_by_symbol) | set(normalized_unranked)
        if prior_scope != current_scope:
            raise ValueError("prior_market_data_universe_symbol_scope_mismatch")
        if (
            prior.deep_candidate_limit != deep_candidate_limit
            or prior.deep_subscription_limit != deep_subscription_limit
            or prior.min_residence_ns != min_residence_ns
        ):
            raise ValueError("prior_market_data_universe_config_mismatch")
    prior_by_symbol = {item.symbol: item for item in prior.memberships} if prior else {}
    selected = set(protected)
    candidate_capacity = min(deep_candidate_limit, deep_subscription_limit - len(selected))
    resident_candidates = [
        symbol
        for symbol in ordered_symbols
        if symbol not in protected
        and symbol in prior_by_symbol
        and prior_by_symbol[symbol].deep_selected
        and prior_by_symbol[symbol].residence_started_ns is not None
        and as_of_ns - int(prior_by_symbol[symbol].residence_started_ns or 0) < min_residence_ns
    ]
    for symbol in resident_candidates[:candidate_capacity]:
        selected.add(symbol)
    for symbol in ordered_symbols:
        if len(selected - protected) >= candidate_capacity:
            break
        selected.add(symbol)

    memberships: list[MarketDataRankedMembership] = []
    for symbol in ordered_symbols:
        previous = prior_by_symbol.get(symbol)
        residence_started_ns = None
        if symbol in selected:
            residence_started_ns = (
                previous.residence_started_ns
                if previous is not None and previous.deep_selected and previous.residence_started_ns is not None
                else as_of_ns
            )
        reasons = ["DYNAMIC_MEMBERSHIP_OBSERVE_ONLY"]
        if symbol in protected:
            reasons.append("PROTECTED_LIFECYCLE_DEEP_REQUIRED")
        elif symbol in resident_candidates and symbol in selected:
            reasons.append("MINIMUM_RESIDENCE_RETAINED")
        elif symbol in selected:
            reasons.append("PARETO_RANKED_DEEP_OBSERVATION")
        else:
            reasons.append("BREADTH_OBSERVATION_ONLY")
        memberships.append(
            MarketDataRankedMembership(
                symbol=symbol,
                rank=rank_by_symbol[symbol],
                pareto_front=fronts[symbol],
                percentile_median=median_percentile[symbol],
                uncertainty=metrics_by_symbol[symbol]["uncertainty"],
                protected=symbol in protected,
                deep_selected=symbol in selected,
                residence_started_ns=residence_started_ns,
                execution_authorized=False,
                activation_mode=MARKET_DATA_OBSERVE_ONLY,
                listing_started_ns=observation_by_symbol[symbol].listing_started_ns,
                listing_age_source=observation_by_symbol[symbol].listing_age_source,
                cross_venue_provider_id=observation_by_symbol[symbol].cross_venue_provider_id,
                cross_venue_source_event_ns=observation_by_symbol[symbol].cross_venue_source_event_ns,
                cross_venue_received_at_ns=observation_by_symbol[symbol].cross_venue_received_at_ns,
                metrics=tuple(sorted(metrics_by_symbol[symbol].items())),
                percentiles=tuple(sorted(percentiles[symbol].items())),
                reason_codes=tuple(reasons),
            )
        )

    stable = {
        "schema_version": MARKET_DATA_UNIVERSE_SCHEMA,
        "catalog_snapshot_id": catalog_snapshot_id,
        "broker_universe_snapshot_id": broker_universe_snapshot_id,
        "as_of_ns": as_of_ns,
        "observation_cutoff_ns": max(
            max(item.latest_source_event_ns, int(item.cross_venue_source_event_ns or 0))
            for item in normalized
        ),
        "created_at_ns": created_at_ns,
        "activation_mode": MARKET_DATA_OBSERVE_ONLY,
        "execution_authorized": False,
        "provider_id": next(iter(provider_ids)),
        "execution_location": "alpaca",
        "held_symbols": sorted({normalize_alpaca_crypto_symbol(item) for item in held_symbols if normalize_alpaca_crypto_symbol(item)}),
        "open_order_symbols": sorted({normalize_alpaca_crypto_symbol(item) for item in open_order_symbols if normalize_alpaca_crypto_symbol(item)}),
        "lifecycle_symbols": sorted({normalize_alpaca_crypto_symbol(item) for item in lifecycle_symbols if normalize_alpaca_crypto_symbol(item)}),
        "deep_candidate_limit": deep_candidate_limit,
        "deep_subscription_limit": deep_subscription_limit,
        "min_residence_ns": min_residence_ns,
        "unranked_symbols": list(normalized_unranked),
        "memberships": [item.to_dict() for item in memberships],
    }
    snapshot_hash = _stable_hash(stable)
    return MarketDataUniverseSnapshot(
        snapshot_id=f"market-universe-{snapshot_hash[:24]}",
        snapshot_hash=snapshot_hash,
        memberships=tuple(memberships),
        schema_version=str(stable["schema_version"]),
        catalog_snapshot_id=str(stable["catalog_snapshot_id"]),
        broker_universe_snapshot_id=str(stable["broker_universe_snapshot_id"]),
        as_of_ns=int(stable["as_of_ns"]),
        observation_cutoff_ns=int(stable["observation_cutoff_ns"]),
        created_at_ns=int(stable["created_at_ns"]),
        activation_mode=str(stable["activation_mode"]),
        execution_authorized=False,
        provider_id=str(stable["provider_id"]),
        execution_location=str(stable["execution_location"]),
        held_symbols=tuple(stable["held_symbols"]),
        open_order_symbols=tuple(stable["open_order_symbols"]),
        lifecycle_symbols=tuple(stable["lifecycle_symbols"]),
        deep_candidate_limit=int(stable["deep_candidate_limit"]),
        deep_subscription_limit=int(stable["deep_subscription_limit"]),
        min_residence_ns=int(stable["min_residence_ns"]),
        unranked_symbols=tuple(stable["unranked_symbols"]),
    )


def _normalize_alpaca_crypto_asset_row(
    row: Mapping[str, Any],
    *,
    row_index: int,
    observed_at_ns: int,
    source: str,
) -> BrokerCryptoAssetCapability:
    reasons: list[str] = []
    raw_asset_id = row.get("id")
    asset_id = raw_asset_id.strip() if isinstance(raw_asset_id, str) else ""
    if raw_asset_id is not None and not isinstance(raw_asset_id, str):
        reasons.append("BROKER_ASSET_ID_INVALID")
    raw_symbol_value = row.get("symbol")
    raw_symbol = raw_symbol_value.strip().upper() if isinstance(raw_symbol_value, str) else ""
    if raw_symbol_value is not None and not isinstance(raw_symbol_value, str):
        reasons.append("BROKER_ASSET_SYMBOL_INVALID")
    normalized_symbol = normalize_alpaca_crypto_symbol(raw_symbol)
    raw_status = row.get("status")
    status = raw_status.strip().lower() if isinstance(raw_status, str) else ""
    if raw_status is not None and not isinstance(raw_status, str):
        reasons.append("BROKER_ASSET_STATUS_INVALID")
    raw_asset_class = row.get("class") if row.get("class") is not None else row.get("asset_class")
    asset_class = raw_asset_class.strip().lower() if isinstance(raw_asset_class, str) else ""
    if raw_asset_class is not None and not isinstance(raw_asset_class, str):
        reasons.append("BROKER_ASSET_CLASS_INVALID")
    raw_exchange = row.get("exchange")
    exchange = raw_exchange.strip().upper() if isinstance(raw_exchange, str) else ""
    if raw_exchange is not None and not isinstance(raw_exchange, str):
        reasons.append("BROKER_ASSET_EXCHANGE_INVALID")
    aliases = tuple(dict.fromkeys(alias for alias in (raw_symbol, normalized_symbol) if alias))

    if not asset_id:
        reasons.append("BROKER_ASSET_ID_MISSING")
    if not normalized_symbol:
        reasons.append("BROKER_ASSET_SYMBOL_INVALID")
    if status != "active":
        reasons.append("BROKER_ASSET_NOT_ACTIVE")
    if asset_class != PortalAssetClass.CRYPTO.value:
        reasons.append("BROKER_ASSET_CLASS_NOT_CRYPTO")
    if not exchange:
        reasons.append("BROKER_ASSET_EXCHANGE_MISSING")

    tradable = _strict_broker_bool(row, "tradable", reasons)
    fractionable = _strict_broker_bool(row, "fractionable", reasons)
    marginable = _strict_broker_bool(row, "marginable", reasons)
    shortable = _strict_broker_bool(row, "shortable", reasons)
    if tradable is not True:
        reasons.append("BROKER_ASSET_NOT_TRADABLE")
    if fractionable is not True:
        reasons.append("BROKER_ASSET_NOT_FRACTIONABLE")
    if marginable is not False:
        reasons.append("CRYPTO_MARGIN_CLAIM_CONFLICT")
    if shortable is not False:
        reasons.append("CRYPTO_SHORT_CLAIM_CONFLICT")

    min_order_size = _strict_positive_decimal(row.get("min_order_size"), field_name="min_order_size", reasons=reasons)
    min_trade_increment = _strict_positive_decimal(
        row.get("min_trade_increment"),
        field_name="min_trade_increment",
        reasons=reasons,
    )
    price_increment = _strict_positive_decimal(row.get("price_increment"), field_name="price_increment", reasons=reasons)
    reasons = list(dict.fromkeys(reasons))
    capability_valid = not reasons
    reason_codes = tuple(reasons or ["BROKER_ASSET_CAPABILITY_VALID"])
    record_identity = {
        "asset_id": asset_id,
        "raw_symbol": raw_symbol,
        "source": source,
    }
    if not asset_id or not raw_symbol:
        record_identity["row_index"] = row_index
    return BrokerCryptoAssetCapability(
        record_key=f"asset-{_stable_hash(record_identity)[:24]}",
        asset_id=asset_id,
        raw_symbol=raw_symbol,
        normalized_symbol=normalized_symbol,
        aliases=aliases,
        status=status,
        tradable=tradable,
        fractionable=fractionable,
        marginable=marginable,
        shortable=shortable,
        min_order_size=min_order_size,
        min_trade_increment=min_trade_increment,
        price_increment=price_increment,
        exchange=exchange,
        asset_class=asset_class,
        observed_at_ns=observed_at_ns,
        source=source,
        capability_valid=capability_valid,
        reason_codes=reason_codes,
    )


def _deduplicate_catalog_assets(
    assets: Sequence[BrokerCryptoAssetCapability],
) -> tuple[BrokerCryptoAssetCapability, ...]:
    groups: dict[str, list[BrokerCryptoAssetCapability]] = {}
    for asset in assets:
        key = asset.normalized_symbol or f"INVALID:{asset.record_key}"
        groups.setdefault(key, []).append(asset)

    normalized: list[BrokerCryptoAssetCapability] = []
    for key in sorted(groups):
        rows = sorted(
            groups[key],
            key=lambda row: (row.raw_symbol != row.normalized_symbol, row.raw_symbol, row.record_key),
        )
        if len(rows) == 1:
            normalized.append(rows[0])
            continue
        reference = rows[0]
        comparison_fields = (
            "asset_id",
            "status",
            "tradable",
            "fractionable",
            "marginable",
            "shortable",
            "min_order_size",
            "min_trade_increment",
            "price_increment",
            "exchange",
            "asset_class",
        )
        conflict = any(
            any(getattr(candidate, field_name) != getattr(reference, field_name) for field_name in comparison_fields)
            for candidate in rows[1:]
        )
        alias_values = ([reference.normalized_symbol] if reference.normalized_symbol else []) + sorted(
            alias for row in rows for alias in row.aliases if alias != reference.normalized_symbol
        )
        aliases = tuple(dict.fromkeys(alias_values))
        if conflict:
            reasons = tuple(
                dict.fromkeys(
                    [
                        *(reason for row in rows for reason in row.reason_codes if reason != "BROKER_ASSET_CAPABILITY_VALID"),
                        "DUPLICATE_SYMBOL_CAPABILITY_CONFLICT",
                    ]
                )
            )
            normalized.append(replace(reference, aliases=aliases, capability_valid=False, reason_codes=reasons))
            continue
        normalized.append(
            replace(
                reference,
                aliases=aliases,
                record_key=f"asset-{_stable_hash({'asset_id': reference.asset_id, 'symbol': key})[:24]}",
            )
        )
    return tuple(normalized)


def normalize_alpaca_crypto_catalog(
    payload: Any,
    *,
    observed_at_ns: int,
    valid_until_ns: int,
    expected_account_suffix: str,
    actual_account_suffix: str,
    endpoint_family: str = ALPACA_PAPER_ENDPOINT_FAMILY,
    source: str = ALPACA_CRYPTO_CATALOG_SOURCE,
) -> BrokerCryptoCatalogSnapshot:
    """Normalize an offline broker payload without granting order authority."""
    reasons: list[str] = []
    expected_suffix = _safe_account_suffix(expected_account_suffix) if isinstance(expected_account_suffix, str) else ""
    actual_suffix = _safe_account_suffix(actual_account_suffix) if isinstance(actual_account_suffix, str) else ""
    if endpoint_family != ALPACA_PAPER_ENDPOINT_FAMILY:
        reasons.append("CATALOG_ENDPOINT_NOT_ALPACA_PAPER")
    if len(expected_suffix) != 6 or len(actual_suffix) != 6:
        reasons.append("CATALOG_ACCOUNT_SUFFIX_NOT_PROVEN")
    elif expected_suffix != actual_suffix:
        reasons.append("CATALOG_ACCOUNT_SUFFIX_MISMATCH")
    if int(observed_at_ns or 0) <= 0:
        reasons.append("CATALOG_OBSERVED_AT_INVALID")
    if int(valid_until_ns or 0) <= int(observed_at_ns or 0):
        reasons.append("CATALOG_VALIDITY_WINDOW_INVALID")

    rows: Sequence[Any]
    if not isinstance(payload, (list, tuple)):
        reasons.append("CATALOG_PAYLOAD_NOT_LIST")
        rows = ()
    else:
        rows = payload
    if not rows:
        reasons.append("CATALOG_EMPTY")

    parsed: list[BrokerCryptoAssetCapability] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            malformed_key = f"asset-{_stable_hash({'row_index': index, 'source': source})[:24]}"
            parsed.append(
                BrokerCryptoAssetCapability(
                    record_key=malformed_key,
                    asset_id="",
                    raw_symbol="",
                    normalized_symbol="",
                    aliases=(),
                    status="",
                    tradable=None,
                    fractionable=None,
                    marginable=None,
                    shortable=None,
                    min_order_size=None,
                    min_trade_increment=None,
                    price_increment=None,
                    exchange="",
                    asset_class="",
                    observed_at_ns=int(observed_at_ns or 0),
                    source=source,
                    capability_valid=False,
                    reason_codes=("BROKER_ASSET_RECORD_NOT_OBJECT",),
                )
            )
            continue
        parsed.append(
            _normalize_alpaca_crypto_asset_row(
                row,
                row_index=index,
                observed_at_ns=int(observed_at_ns or 0),
                source=source,
            )
        )
    assets = _deduplicate_catalog_assets(parsed)
    if any(not asset.capability_valid for asset in assets):
        reasons.append("CATALOG_ASSET_EXCLUSIONS_PRESENT")

    try:
        canonical_source_payload = (
            sorted(payload, key=lambda item: _stable_hash(item))
            if isinstance(payload, (list, tuple))
            else payload
        )
        source_hash = _stable_hash(canonical_source_payload)
    except (TypeError, ValueError):
        reasons.append("CATALOG_PAYLOAD_NOT_JSON")
        source_hash = _stable_hash({"invalid_json_payload": True})
    stable = {
        "schema_version": ALPACA_CRYPTO_CATALOG_SCHEMA,
        "broker": "alpaca",
        "environment": PortalEnvironment.PAPER.value,
        "endpoint_family": endpoint_family,
        "expected_account_suffix": expected_suffix,
        "actual_account_suffix": actual_suffix,
        "observed_at_ns": int(observed_at_ns or 0),
        "valid_until_ns": int(valid_until_ns or 0),
        "source": source,
        "source_hash": source_hash,
        "assets": [asset.to_dict() for asset in assets],
    }
    snapshot_hash = _stable_hash(stable)
    blocking = [reason for reason in reasons if reason != "CATALOG_ASSET_EXCLUSIONS_PRESENT"]
    status = "BLOCKED" if blocking else "VALID"
    reason_codes = tuple(dict.fromkeys(reasons or ["CATALOG_VALID"]))
    return BrokerCryptoCatalogSnapshot(
        catalog_snapshot_id=f"catalog-{snapshot_hash[:24]}",
        schema_version=ALPACA_CRYPTO_CATALOG_SCHEMA,
        broker="alpaca",
        environment=PortalEnvironment.PAPER.value,
        endpoint_family=endpoint_family,
        expected_account_suffix=expected_suffix,
        actual_account_suffix=actual_suffix,
        observed_at_ns=int(observed_at_ns or 0),
        valid_until_ns=int(valid_until_ns or 0),
        source=source,
        source_hash=source_hash,
        snapshot_hash=snapshot_hash,
        status=status,
        reason_codes=reason_codes,
        assets=assets,
    )


def build_alpaca_crypto_universe(
    catalog: BrokerCryptoCatalogSnapshot | Mapping[str, Any],
    *,
    as_of_ns: int,
    expected_account_suffix: str,
    actual_account_suffix: str,
    account_status: str,
    crypto_status: str,
    trading_blocked: bool | None,
    account_blocked: bool | None,
    trade_suspended_by_user: bool | None,
    execution_adapter: str,
    execution_adapter_available: bool,
    funded_quote_currencies: Iterable[str],
    market_data_symbols: Iterable[str],
    priority_symbols: Iterable[str] = (),
    held_symbols: Iterable[str] = (),
    open_order_symbols: Iterable[str] = (),
) -> BrokerCryptoUniverseSnapshot:
    normalized_catalog = (
        catalog if isinstance(catalog, BrokerCryptoCatalogSnapshot) else BrokerCryptoCatalogSnapshot.from_dict(catalog)
    )
    global_reasons: list[str] = []
    expected_suffix = _safe_account_suffix(expected_account_suffix) if isinstance(expected_account_suffix, str) else ""
    actual_suffix = _safe_account_suffix(actual_account_suffix) if isinstance(actual_account_suffix, str) else ""
    normalized_account_status = str(account_status or "").strip().upper()
    normalized_crypto_status = str(crypto_status or "").strip().upper()
    normalized_execution_adapter = str(execution_adapter or "").strip()
    normalized_adapter_available = (
        execution_adapter_available if type(execution_adapter_available) is bool else None
    )
    if normalized_catalog.status != "VALID":
        global_reasons.append("CATALOG_NOT_VALID")
    if normalized_catalog.endpoint_family != ALPACA_PAPER_ENDPOINT_FAMILY:
        global_reasons.append("CATALOG_ENDPOINT_NOT_ALPACA_PAPER")
    if normalized_catalog.expected_account_suffix != expected_suffix or normalized_catalog.actual_account_suffix != actual_suffix:
        global_reasons.append("CATALOG_ACCOUNT_BINDING_MISMATCH")
    if len(expected_suffix) != 6 or expected_suffix != actual_suffix:
        global_reasons.append("ACCOUNT_SUFFIX_MISMATCH_OR_UNKNOWN")
    if int(as_of_ns or 0) < normalized_catalog.observed_at_ns:
        global_reasons.append("CATALOG_FROM_FUTURE")
    if int(as_of_ns or 0) > normalized_catalog.valid_until_ns:
        global_reasons.append("CATALOG_STALE")
    if normalized_account_status != "ACTIVE":
        global_reasons.append("BROKER_ACCOUNT_NOT_ACTIVE")
    if normalized_crypto_status != "ACTIVE":
        global_reasons.append("BROKER_CRYPTO_PERMISSION_NOT_ACTIVE")
    for field_name, value in (
        ("TRADING_BLOCKED", trading_blocked),
        ("ACCOUNT_BLOCKED", account_blocked),
        ("TRADE_SUSPENDED_BY_USER", trade_suspended_by_user),
    ):
        if value is not False:
            global_reasons.append(f"BROKER_{field_name}_OR_UNKNOWN")
    if (
        normalized_execution_adapter != ALPACA_PAPER_EXECUTION_ADAPTER
        or normalized_adapter_available is not True
    ):
        global_reasons.append("ALPACA_PAPER_EXECUTION_ADAPTER_UNAVAILABLE")

    funded = {str(item).strip().upper() for item in funded_quote_currencies if str(item).strip()}
    market_coverage = {
        normalized
        for item in market_data_symbols
        if (normalized := normalize_alpaca_crypto_symbol(item))
    }
    priority = [
        normalized
        for item in priority_symbols
        if (normalized := normalize_alpaca_crypto_symbol(item))
    ]
    priority_rank = {symbol: index for index, symbol in enumerate(dict.fromkeys(priority))}
    held: set[str] = set()
    invalid_held_symbol = False
    for item in held_symbols:
        normalized = normalize_alpaca_crypto_symbol(item)
        if normalized:
            held.add(normalized)
        elif str(item or "").strip():
            invalid_held_symbol = True
    open_orders: set[str] = set()
    invalid_open_order_symbol = False
    for item in open_order_symbols:
        normalized = normalize_alpaca_crypto_symbol(item)
        if normalized:
            open_orders.add(normalized)
        elif str(item or "").strip():
            invalid_open_order_symbol = True
    if invalid_held_symbol:
        global_reasons.append("BROKER_HELD_SYMBOL_INVALID")
    if invalid_open_order_symbol:
        global_reasons.append("BROKER_OPEN_ORDER_SYMBOL_INVALID")
    monitor = held | open_orders
    funded_values = tuple(sorted(funded))
    market_coverage_values = tuple(sorted(market_coverage))
    priority_values = tuple(dict.fromkeys(priority))
    held_values = tuple(sorted(held))
    open_order_values = tuple(sorted(open_orders))

    memberships: list[CryptoUniverseMembership] = []
    catalog_symbols: set[str] = set()
    for asset in normalized_catalog.assets:
        symbol = asset.normalized_symbol
        if symbol:
            catalog_symbols.add(symbol)
        reasons = [reason for reason in asset.reason_codes if reason != "BROKER_ASSET_CAPABILITY_VALID"]
        reasons.extend(global_reasons)
        if not asset.quote_currency or asset.quote_currency not in funded:
            reasons.append("QUOTE_CURRENCY_NOT_FUNDED")
        if not symbol or symbol not in market_coverage:
            reasons.append("MARKET_DATA_COVERAGE_MISSING")
        reasons = list(dict.fromkeys(reasons))
        included = asset.capability_valid and not reasons
        memberships.append(
            CryptoUniverseMembership(
                record_key=asset.record_key,
                asset_id=asset.asset_id or None,
                symbol=symbol or asset.raw_symbol or f"INVALID:{asset.record_key}",
                included_for_entry=included,
                monitor_required=bool(symbol and symbol in monitor),
                priority_rank=priority_rank.get(symbol),
                reason_codes=tuple(reasons or ["ENTRY_ELIGIBLE_BROKER_CATALOG"]),
            )
        )

    for symbol in sorted(monitor - catalog_symbols):
        memberships.append(
            CryptoUniverseMembership(
                record_key=None,
                asset_id=None,
                symbol=symbol,
                included_for_entry=False,
                monitor_required=True,
                priority_rank=priority_rank.get(symbol),
                reason_codes=tuple(dict.fromkeys(["BROKER_ASSET_NOT_IN_CATALOG", *global_reasons])),
            )
        )

    memberships.sort(key=lambda item: item.symbol)
    eligible_count = sum(1 for item in memberships if item.included_for_entry)
    universe_reasons = list(dict.fromkeys(global_reasons))
    if eligible_count == 0:
        universe_reasons.append("NO_ENTRY_ELIGIBLE_CRYPTO_ASSETS")
    status = "READY" if eligible_count > 0 and not global_reasons else "BLOCKED"
    if status == "READY":
        universe_reasons.append("UNIVERSE_READY_FROM_BROKER_CATALOG")
    stable = {
        "schema_version": ALPACA_CRYPTO_UNIVERSE_SCHEMA,
        "catalog_snapshot_id": normalized_catalog.catalog_snapshot_id,
        "broker": normalized_catalog.broker,
        "environment": normalized_catalog.environment,
        "endpoint_family": normalized_catalog.endpoint_family,
        "account_suffix": actual_suffix,
        "account_status": normalized_account_status,
        "crypto_status": normalized_crypto_status,
        "trading_blocked": trading_blocked,
        "account_blocked": account_blocked,
        "trade_suspended_by_user": trade_suspended_by_user,
        "execution_adapter": normalized_execution_adapter,
        "execution_adapter_available": normalized_adapter_available,
        "funded_quote_currencies": list(funded_values),
        "market_data_symbols": list(market_coverage_values),
        "priority_symbols": list(priority_values),
        "held_symbols": list(held_values),
        "open_order_symbols": list(open_order_values),
        "observed_at_ns": int(as_of_ns or 0),
        "valid_until_ns": normalized_catalog.valid_until_ns,
        "status": status,
        "reason_codes": universe_reasons,
        "memberships": [item.to_dict() for item in memberships],
    }
    universe_hash = _stable_hash(stable)
    return BrokerCryptoUniverseSnapshot(
        universe_snapshot_id=f"universe-{universe_hash[:24]}",
        schema_version=ALPACA_CRYPTO_UNIVERSE_SCHEMA,
        catalog_snapshot_id=normalized_catalog.catalog_snapshot_id,
        broker=normalized_catalog.broker,
        environment=normalized_catalog.environment,
        endpoint_family=normalized_catalog.endpoint_family,
        account_suffix=actual_suffix,
        account_status=normalized_account_status,
        crypto_status=normalized_crypto_status,
        trading_blocked=trading_blocked,
        account_blocked=account_blocked,
        trade_suspended_by_user=trade_suspended_by_user,
        execution_adapter=normalized_execution_adapter,
        execution_adapter_available=normalized_adapter_available,
        funded_quote_currencies=funded_values,
        market_data_symbols=market_coverage_values,
        priority_symbols=priority_values,
        held_symbols=held_values,
        open_order_symbols=open_order_values,
        observed_at_ns=int(as_of_ns or 0),
        valid_until_ns=normalized_catalog.valid_until_ns,
        status=status,
        reason_codes=tuple(universe_reasons),
        universe_hash=universe_hash,
        memberships=tuple(memberships),
    )


@dataclass(frozen=True)
class VenueCapabilityRegistry:
    capabilities: tuple[VenueCapability, ...]

    def configured_portals(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(cap.portal_key for cap in self.capabilities))

    def usable_portals(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(cap.portal_key for cap in self.capabilities if cap.enabled and not cap.live_blocked))

    def capabilities_for_symbol(self, symbol: str, *, environment: str | None = None) -> tuple[VenueCapability, ...]:
        return tuple(
            cap
            for cap in self.capabilities
            if cap.matches_symbol(symbol) and (environment is None or cap.environment == environment)
        )

    def capabilities_for_asset_class(self, asset_class: str, *, environment: str | None = None) -> tuple[VenueCapability, ...]:
        return tuple(
            cap
            for cap in self.capabilities
            if cap.matches_asset_class(asset_class) and (environment is None or cap.environment == environment)
        )

    def resolve(self, request: PortalSelectionRequest) -> PortalSelectionResult:
        candidates = self.capabilities_for_symbol(request.symbol, environment=request.environment)
        if request.asset_class is not None:
            candidates = tuple(cap for cap in candidates if cap.matches_asset_class(request.asset_class))

        usable: list[VenueCapability] = []
        rejected: dict[str, tuple[str, ...]] = {}
        for cap in candidates:
            ok, reasons = cap.supports_request(request)
            if ok:
                usable.append(cap)
            else:
                rejected[cap.capability_key] = reasons

        mode = PortalPolicyMode(request.policy_mode)
        if mode == PortalPolicyMode.FAIL_CLOSED:
            reasons = ("FAIL_CLOSED_POLICY",) if usable else ("NO_USABLE_PORTAL",)
            return PortalSelectionResult(None, tuple(candidates), rejected, "blocked", reasons)

        if mode == PortalPolicyMode.EXPLICIT_PREFERRED_VENUE:
            preferred = normalize_symbol(request.preferred_venue or "")
            preferred_matches = [
                cap
                for cap in usable
                if normalize_symbol(cap.venue_id) == preferred
                or normalize_symbol(cap.portal_key) == preferred
                or normalize_symbol(cap.portal_name) == preferred
            ]
            if len(preferred_matches) == 1:
                return PortalSelectionResult(preferred_matches[0], tuple(candidates), rejected, "selected", ())
            if not request.allow_fallback:
                return PortalSelectionResult(None, tuple(candidates), rejected, "blocked", ("PREFERRED_PORTAL_UNSUPPORTED",))
            usable = [cap for cap in usable if cap not in preferred_matches]

        if len(usable) == 1:
            return PortalSelectionResult(usable[0], tuple(candidates), rejected, "selected", ())
        if len(usable) > 1:
            return PortalSelectionResult(None, tuple(candidates), rejected, "blocked", ("AMBIGUOUS_PORTAL",))
        return PortalSelectionResult(None, tuple(candidates), rejected, "blocked", ("NO_USABLE_PORTAL",))

    def build_candidate_identities(
        self,
        *,
        symbols: Iterable[str],
        active_markets: Iterable[str],
        environment: str = PortalEnvironment.PAPER.value,
        discovery_mode: str = "active_markets",
    ) -> tuple[CapabilityAwareCandidate, ...]:
        active = {normalize_asset_class(market) for market in active_markets}
        requested_symbols = {normalize_symbol(symbol) for symbol in symbols}
        identities: list[CapabilityAwareCandidate] = []
        capability_source = (
            self.capabilities
            if discovery_mode == "registry"
            else tuple(cap for symbol in symbols for cap in self.capabilities_for_symbol(symbol, environment=environment))
        )
        seen: set[str] = set()
        for cap in capability_source:
            if cap.environment != environment:
                continue
            if cap.normalized_symbol != "*" and cap.normalized_symbol not in requested_symbols:
                continue
            if cap.asset_class not in active and not (
                cap.asset_class == PortalAssetClass.US_EQUITY.value and PortalAssetClass.EQUITY.value in active
            ):
                continue
            if cap.capability_key in seen:
                continue
            seen.add(cap.capability_key)
            request = PortalSelectionRequest(
                symbol=cap.symbol,
                asset_class=cap.asset_class,
                environment=environment,
                policy_mode=PortalPolicyMode.CAPABILITY_FIRST.value,
                order_type=cap.default_order_type or "limit",
                time_in_force=cap.default_time_in_force,
            )
            ok, reasons = cap.supports_request(request)
            identities.append(CapabilityAwareCandidate.from_capability(cap, tradable=ok, reasons=reasons))
        return tuple(identities)


def _broker_crypto_evidence_reasons(
    catalog: BrokerCryptoCatalogSnapshot,
    universe: BrokerCryptoUniverseSnapshot,
    *,
    expected_account_suffix: str,
    as_of_ns: int,
) -> tuple[str, ...]:
    reasons: list[str] = []
    expected_suffix = _safe_account_suffix(expected_account_suffix)
    if catalog.schema_version != ALPACA_CRYPTO_CATALOG_SCHEMA:
        reasons.append("BROKER_CRYPTO_CATALOG_SCHEMA_INVALID")
    if universe.schema_version != ALPACA_CRYPTO_UNIVERSE_SCHEMA:
        reasons.append("BROKER_CRYPTO_UNIVERSE_SCHEMA_INVALID")
    if catalog.broker != "alpaca" or universe.broker != "alpaca":
        reasons.append("BROKER_CRYPTO_BROKER_LINEAGE_INVALID")
    if catalog.environment != PortalEnvironment.PAPER.value or universe.environment != PortalEnvironment.PAPER.value:
        reasons.append("BROKER_CRYPTO_ENVIRONMENT_LINEAGE_INVALID")
    if catalog.endpoint_family != ALPACA_PAPER_ENDPOINT_FAMILY or universe.endpoint_family != ALPACA_PAPER_ENDPOINT_FAMILY:
        reasons.append("BROKER_CRYPTO_ENDPOINT_LINEAGE_INVALID")
    if catalog.source != ALPACA_CRYPTO_CATALOG_SOURCE:
        reasons.append("BROKER_CRYPTO_CATALOG_SOURCE_INVALID")
    if len(catalog.source_hash) != 64 or any(character not in "0123456789abcdef" for character in catalog.source_hash):
        reasons.append("BROKER_CRYPTO_CATALOG_SOURCE_HASH_INVALID")
    if catalog.status != "VALID":
        reasons.append("BROKER_CRYPTO_CATALOG_NOT_VALID")
    if universe.status != "READY":
        reasons.append("BROKER_CRYPTO_UNIVERSE_NOT_READY")
    if (
        len(expected_suffix) != 6
        or catalog.expected_account_suffix != expected_suffix
        or catalog.actual_account_suffix != expected_suffix
        or universe.account_suffix != expected_suffix
    ):
        reasons.append("BROKER_CRYPTO_ACCOUNT_LINEAGE_INVALID")
    if universe.catalog_snapshot_id != catalog.catalog_snapshot_id:
        reasons.append("BROKER_CRYPTO_CATALOG_LINEAGE_INVALID")
    if catalog.observed_at_ns <= 0 or universe.observed_at_ns < catalog.observed_at_ns:
        reasons.append("BROKER_CRYPTO_OBSERVED_TIME_INVALID")
    if catalog.valid_until_ns <= catalog.observed_at_ns or universe.valid_until_ns != catalog.valid_until_ns:
        reasons.append("BROKER_CRYPTO_VALIDITY_LINEAGE_INVALID")
    if int(as_of_ns) < universe.observed_at_ns:
        reasons.append("BROKER_CRYPTO_UNIVERSE_FROM_FUTURE")
    if int(as_of_ns) > universe.valid_until_ns:
        reasons.append("BROKER_CRYPTO_UNIVERSE_STALE")

    asset_keys: set[str] = set()
    normalized_symbols: set[str] = set()
    invalid_asset_present = False
    for asset in catalog.assets:
        if not asset.record_key or asset.record_key in asset_keys:
            reasons.append("BROKER_CRYPTO_ASSET_RECORD_KEY_INVALID")
        asset_keys.add(asset.record_key)
        if asset.observed_at_ns != catalog.observed_at_ns or asset.source != catalog.source:
            reasons.append("BROKER_CRYPTO_ASSET_PROVENANCE_INVALID")
        if asset.normalized_symbol:
            if asset.normalized_symbol in normalized_symbols:
                reasons.append("BROKER_CRYPTO_DUPLICATE_NORMALIZED_SYMBOL")
            normalized_symbols.add(asset.normalized_symbol)
        if asset.capability_valid:
            exact_values = (asset.min_order_size, asset.min_trade_increment, asset.price_increment)
            if (
                not asset.asset_id
                or not asset.normalized_symbol
                or not asset.exchange
                or asset.status != "active"
                or asset.asset_class != PortalAssetClass.CRYPTO.value
                or asset.tradable is not True
                or asset.fractionable is not True
                or asset.marginable is not False
                or asset.shortable is not False
                or any(value is None or not value.is_finite() or value <= Decimal("0") for value in exact_values)
                or asset.reason_codes != ("BROKER_ASSET_CAPABILITY_VALID",)
            ):
                reasons.append("BROKER_CRYPTO_VALID_ASSET_SEMANTICS_INVALID")
        else:
            invalid_asset_present = True
            if not asset.reason_codes or "BROKER_ASSET_CAPABILITY_VALID" in asset.reason_codes:
                reasons.append("BROKER_CRYPTO_INVALID_ASSET_REASON_MISSING")

    if invalid_asset_present:
        if "CATALOG_ASSET_EXCLUSIONS_PRESENT" not in catalog.reason_codes:
            reasons.append("BROKER_CRYPTO_CATALOG_EXCLUSION_SUMMARY_MISSING")
    elif catalog.reason_codes != ("CATALOG_VALID",):
        reasons.append("BROKER_CRYPTO_CATALOG_REASON_SUMMARY_INVALID")

    catalog_stable = {
        "schema_version": catalog.schema_version,
        "broker": catalog.broker,
        "environment": catalog.environment,
        "endpoint_family": catalog.endpoint_family,
        "expected_account_suffix": catalog.expected_account_suffix,
        "actual_account_suffix": catalog.actual_account_suffix,
        "observed_at_ns": catalog.observed_at_ns,
        "valid_until_ns": catalog.valid_until_ns,
        "source": catalog.source,
        "source_hash": catalog.source_hash,
        "assets": [asset.to_dict() for asset in catalog.assets],
    }
    expected_catalog_hash = _stable_hash(catalog_stable)
    if (
        catalog.snapshot_hash != expected_catalog_hash
        or catalog.catalog_snapshot_id != f"catalog-{expected_catalog_hash[:24]}"
    ):
        reasons.append("BROKER_CRYPTO_CATALOG_HASH_INVALID")

    rebuilt = build_alpaca_crypto_universe(
        catalog,
        as_of_ns=universe.observed_at_ns,
        expected_account_suffix=catalog.expected_account_suffix,
        actual_account_suffix=universe.account_suffix,
        account_status=universe.account_status,
        crypto_status=universe.crypto_status,
        trading_blocked=universe.trading_blocked,
        account_blocked=universe.account_blocked,
        trade_suspended_by_user=universe.trade_suspended_by_user,
        execution_adapter=universe.execution_adapter,
        execution_adapter_available=universe.execution_adapter_available,
        funded_quote_currencies=universe.funded_quote_currencies,
        market_data_symbols=universe.market_data_symbols,
        priority_symbols=universe.priority_symbols,
        held_symbols=universe.held_symbols,
        open_order_symbols=universe.open_order_symbols,
    )
    if rebuilt.universe_hash != universe.universe_hash or rebuilt.universe_snapshot_id != universe.universe_snapshot_id:
        reasons.append("BROKER_CRYPTO_UNIVERSE_DERIVATION_INVALID")
    if not universe.entry_symbols:
        reasons.append("BROKER_CRYPTO_ENTRY_UNIVERSE_EMPTY")
    return tuple(dict.fromkeys(reasons))


def build_alpaca_crypto_capability_registry(
    catalog: BrokerCryptoCatalogSnapshot | Mapping[str, Any],
    universe: BrokerCryptoUniverseSnapshot | Mapping[str, Any],
) -> VenueCapabilityRegistry:
    """Project verified broker facts into the existing capability owner."""
    normalized_catalog = (
        catalog if isinstance(catalog, BrokerCryptoCatalogSnapshot) else BrokerCryptoCatalogSnapshot.from_dict(catalog)
    )
    normalized_universe = (
        universe if isinstance(universe, BrokerCryptoUniverseSnapshot) else BrokerCryptoUniverseSnapshot.from_dict(universe)
    )
    evidence_reasons = _broker_crypto_evidence_reasons(
        normalized_catalog,
        normalized_universe,
        expected_account_suffix=normalized_catalog.expected_account_suffix,
        as_of_ns=normalized_universe.observed_at_ns,
    )
    if evidence_reasons:
        return VenueCapabilityRegistry(())

    assets = {asset.record_key: asset for asset in normalized_catalog.assets}
    capabilities: list[VenueCapability] = []
    for membership in normalized_universe.memberships:
        if not membership.included_for_entry or membership.record_key is None:
            continue
        asset = assets.get(membership.record_key)
        if asset is None or not asset.capability_valid or asset.normalized_symbol != membership.symbol:
            continue
        capabilities.append(
            VenueCapability(
                venue_id="alpaca",
                portal_name="alpaca_paper",
                environment=PortalEnvironment.PAPER.value,
                asset_class=PortalAssetClass.CRYPTO.value,
                symbol=asset.normalized_symbol,
                normalized_symbol=asset.normalized_symbol,
                venue_symbol_format=asset.raw_symbol,
                quote_source="alpaca_crypto_market_data_required",
                market_data_available=True,
                tradability_source="alpaca_broker_asset_catalog",
                supported_order_types=frozenset({"limit"}),
                supported_actions=frozenset({"buy", "sell_to_close"}),
                supported_time_in_force=frozenset({"GTC", "IOC"}),
                default_order_type="limit",
                default_time_in_force="GTC",
                fractional_support=asset.fractionable is True,
                min_notional=None,
                min_quantity=asset.min_order_size,
                quantity_step=asset.min_trade_increment,
                price_increment=asset.price_increment,
                market_session_status_source="alpaca_crypto_clock",
                execution_adapter=ALPACA_PAPER_EXECUTION_ADAPTER,
                reconciliation_adapter="alpaca_paper_rest_reconciliation",
                read_only=True,
                paper_mutation=True,
                sandbox_mutation=False,
                live_mutation=False,
                live_blocked=True,
                credential_status=CredentialStatus.CONFIGURED.value,
                order_constraint_source="alpaca_broker_asset_catalog",
                broker_asset_id=asset.asset_id,
                broker_status=asset.status,
                broker_tradable=asset.tradable,
                broker_fractionable=asset.fractionable,
                broker_marginable=asset.marginable,
                broker_shortable=asset.shortable,
                broker_exchange=asset.exchange,
                observed_at_ns=normalized_universe.observed_at_ns,
                valid_until_ns=normalized_universe.valid_until_ns,
                catalog_snapshot_id=normalized_catalog.catalog_snapshot_id,
                capability_source_hash=normalized_catalog.snapshot_hash,
                execution_authority_source="BROKER_CATALOG_DERIVED_ELIGIBILITY",
                metadata={
                    "universe_snapshot_id": normalized_universe.universe_snapshot_id,
                    "universe_hash": normalized_universe.universe_hash,
                    "entry_membership_reason_codes": membership.reason_codes,
                    "quote_currency": asset.quote_currency,
                    "static_fixture": False,
                },
            )
        )
    return VenueCapabilityRegistry(tuple(capabilities))


def validate_alpaca_crypto_capability_evidence(
    catalog: BrokerCryptoCatalogSnapshot | Mapping[str, Any],
    universe: BrokerCryptoUniverseSnapshot | Mapping[str, Any],
    *,
    expected_account_suffix: str,
    as_of_ns: int,
) -> tuple[VenueCapabilityRegistry, dict[str, Any]]:
    """Validate immutable evidence and project it through the sole capability owner."""
    normalized_catalog = (
        catalog if isinstance(catalog, BrokerCryptoCatalogSnapshot) else BrokerCryptoCatalogSnapshot.from_dict(catalog)
    )
    normalized_universe = (
        universe if isinstance(universe, BrokerCryptoUniverseSnapshot) else BrokerCryptoUniverseSnapshot.from_dict(universe)
    )
    reasons = _broker_crypto_evidence_reasons(
        normalized_catalog,
        normalized_universe,
        expected_account_suffix=expected_account_suffix,
        as_of_ns=as_of_ns,
    )
    registry = VenueCapabilityRegistry(()) if reasons else build_alpaca_crypto_capability_registry(
        normalized_catalog,
        normalized_universe,
    )
    projected_symbols = tuple(capability.normalized_symbol for capability in registry.capabilities)
    if not reasons and set(projected_symbols) != set(normalized_universe.entry_symbols):
        reasons = ("BROKER_CRYPTO_CAPABILITY_PROJECTION_INCOMPLETE",)
        registry = VenueCapabilityRegistry(())
    status = {
        "status": "VERIFIED" if not reasons else "BLOCKED",
        "reason_code": "BROKER_CRYPTO_CAPABILITY_EVIDENCE_VERIFIED" if not reasons else reasons[0],
        "reason_codes": ["BROKER_CRYPTO_CAPABILITY_EVIDENCE_VERIFIED"] if not reasons else list(reasons),
        "catalog_snapshot_id": normalized_catalog.catalog_snapshot_id or None,
        "universe_snapshot_id": normalized_universe.universe_snapshot_id or None,
        "observed_at_ns": normalized_universe.observed_at_ns,
        "valid_until_ns": normalized_universe.valid_until_ns,
        "entry_symbols": list(normalized_universe.entry_symbols),
        "monitor_symbols": list(normalized_universe.monitor_symbols),
        "runtime_symbols": list(normalized_universe.runtime_symbols),
        "entry_symbol_count": len(normalized_universe.entry_symbols),
        "monitor_symbol_count": len(normalized_universe.monitor_symbols),
        "runtime_symbol_count": len(normalized_universe.runtime_symbols),
        "watchlist_authority": "PRIORITY_ONLY_NOT_EXECUTION_ELIGIBILITY",
    }
    return registry, status


def _alpaca_equity_capability(symbol: str, *, asset_class: str, etf_capable: bool = False) -> VenueCapability:
    return VenueCapability(
        venue_id="alpaca",
        portal_name="alpaca_paper",
        environment=PortalEnvironment.PAPER.value,
        asset_class=asset_class,
        symbol=symbol,
        normalized_symbol=normalize_symbol(symbol),
        venue_symbol_format=symbol,
        quote_source="alpaca_data_latest_quote",
        market_data_available=True,
        tradability_source="static_capability_fixture",
        supported_order_types=frozenset({"limit"}),
        supported_time_in_force=frozenset({"DAY"}),
        default_order_type="limit",
        default_time_in_force="DAY",
        fractional_support=True,
        min_notional=Decimal("1.00"),
        min_quantity=None,
        quantity_step=Decimal("0.000001"),
        market_session_status_source="alpaca_paper_clock",
        execution_adapter="alpaca_paper_rest",
        reconciliation_adapter="alpaca_paper_rest_reconciliation",
        read_only=True,
        paper_mutation=True,
        sandbox_mutation=False,
        live_mutation=False,
        live_blocked=True,
        credential_status=CredentialStatus.CONFIGURED.value,
        order_constraint_source="alpaca_equity_order_constraints",
        metadata={"etf_capable": etf_capable},
    )


def _alpaca_crypto_capability(symbol: str) -> VenueCapability:
    return VenueCapability(
        venue_id="alpaca",
        portal_name="alpaca_paper",
        environment=PortalEnvironment.PAPER.value,
        asset_class=PortalAssetClass.CRYPTO.value,
        symbol=symbol,
        normalized_symbol=normalize_symbol(symbol),
        venue_symbol_format=symbol,
        quote_source="alpaca_data_crypto_latest_quote",
        market_data_available=True,
        tradability_source="static_reference_fixture_non_authoritative",
        supported_order_types=frozenset({"limit"}),
        supported_actions=frozenset({"buy", "sell_to_close"}),
        supported_time_in_force=frozenset({"GTC", "IOC"}),
        default_order_type="limit",
        default_time_in_force="GTC",
        fractional_support=True,
        min_notional=Decimal("10.00"),
        min_quantity=None,
        quantity_step=None,
        market_session_status_source="alpaca_crypto_clock",
        execution_adapter="alpaca_paper_rest",
        reconciliation_adapter="alpaca_paper_rest_reconciliation",
        read_only=True,
        paper_mutation=False,
        sandbox_mutation=False,
        live_mutation=False,
        live_blocked=True,
        credential_status=CredentialStatus.CONFIGURED.value,
        enabled=False,
        disabled_reason=BROKER_CATALOG_REQUIRED,
        unavailable_reason=BROKER_CATALOG_REQUIRED,
        fail_closed_reason_code=BROKER_CATALOG_REQUIRED,
        order_constraint_source="alpaca_crypto_orders_support_gtc_ioc_not_day",
        execution_authority_source="STATIC_REFERENCE_NEVER_EXECUTION_AUTHORITY",
        metadata={"static_fixture": True, "execution_authoritative": False},
    )


def _kraken_crypto_capability(symbol: str) -> VenueCapability:
    venue_symbol = symbol.replace("/", "")
    if symbol == "BTC/USD":
        venue_symbol = "XBTUSD"
    return VenueCapability(
        venue_id="kraken",
        portal_name="kraken_paper",
        environment=PortalEnvironment.PAPER.value,
        asset_class=PortalAssetClass.CRYPTO.value,
        symbol=symbol,
        normalized_symbol=normalize_symbol(symbol),
        venue_symbol_format=venue_symbol,
        quote_source="kraken_websocket_or_polling",
        market_data_available=True,
        tradability_source="instrument_registry",
        supported_order_types=frozenset({"limit", "market"}),
        supported_time_in_force=frozenset({"DAY", "GTC", "IOC"}),
        default_order_type="limit",
        default_time_in_force="GTC",
        fractional_support=True,
        min_notional=Decimal("10.00"),
        min_quantity=None,
        quantity_step=None,
        market_session_status_source="crypto_24_7",
        execution_adapter="sovereign_paper_broker",
        reconciliation_adapter="sovereign_paper_broker_snapshot",
        read_only=True,
        paper_mutation=True,
        sandbox_mutation=False,
        live_mutation=False,
        live_blocked=True,
        credential_status=CredentialStatus.CONFIGURED.value,
    )


def _disabled_placeholder(venue_id: str, reason: str) -> VenueCapability:
    return VenueCapability(
        venue_id=venue_id,
        portal_name=f"{venue_id}_disabled",
        environment=PortalEnvironment.PAPER.value,
        asset_class=PortalAssetClass.UNKNOWN.value,
        symbol="*",
        normalized_symbol="*",
        venue_symbol_format="UNKNOWN",
        quote_source="unconfigured",
        market_data_available=False,
        tradability_source="unconfigured",
        supported_order_types=frozenset(),
        supported_time_in_force=frozenset(),
        default_order_type=None,
        default_time_in_force=None,
        fractional_support=False,
        min_notional=None,
        min_quantity=None,
        quantity_step=None,
        market_session_status_source="unconfigured",
        execution_adapter="missing",
        reconciliation_adapter="missing",
        read_only=False,
        paper_mutation=False,
        sandbox_mutation=False,
        live_mutation=False,
        live_blocked=True,
        supported_actions=frozenset(),
        credential_status=(
            CredentialStatus.MISSING.value if reason == "CREDENTIALS_MISSING" else CredentialStatus.UNKNOWN.value
        ),
        enabled=False,
        disabled_reason=reason,
        unavailable_reason=reason,
        fail_closed_reason_code=reason,
    )


def _live_blocked_placeholder() -> VenueCapability:
    return VenueCapability(
        venue_id="alpaca",
        portal_name="alpaca_live_blocked",
        environment=PortalEnvironment.LIVE.value,
        asset_class=PortalAssetClass.UNKNOWN.value,
        symbol="*",
        normalized_symbol="*",
        venue_symbol_format="UNKNOWN",
        quote_source="live_blocked",
        market_data_available=False,
        tradability_source="live_blocked",
        supported_order_types=frozenset(),
        supported_time_in_force=frozenset(),
        default_order_type=None,
        default_time_in_force=None,
        fractional_support=False,
        min_notional=None,
        min_quantity=None,
        quantity_step=None,
        market_session_status_source="live_blocked",
        execution_adapter="live_blocked",
        reconciliation_adapter="live_blocked",
        read_only=False,
        paper_mutation=False,
        sandbox_mutation=False,
        live_mutation=False,
        live_blocked=True,
        supported_actions=frozenset(),
        credential_status=CredentialStatus.MISSING.value,
        enabled=False,
        disabled_reason="LIVE_BLOCKED",
        unavailable_reason="LIVE_BLOCKED",
        fail_closed_reason_code="LIVE_BLOCKED",
    )


def build_default_capability_registry() -> VenueCapabilityRegistry:
    capabilities: list[VenueCapability] = []
    capabilities.extend(_kraken_crypto_capability(symbol) for symbol in KRAKEN_CRYPTO)
    capabilities.extend(
        _alpaca_equity_capability(symbol, asset_class=PortalAssetClass.EQUITY.value)
        for symbol in ALPACA_PAPER_EQUITIES
    )
    capabilities.extend(
        _alpaca_equity_capability(symbol, asset_class=PortalAssetClass.ETF.value, etf_capable=True)
        for symbol in ALPACA_PAPER_ETFS
    )
    capabilities.extend(_alpaca_crypto_capability(symbol) for symbol in ALPACA_PAPER_CRYPTO)
    capabilities.append(_live_blocked_placeholder())
    for venue_id, reason in (
        ("coinbase", "ADAPTER_MISSING"),
        ("interactive_brokers", "CREDENTIALS_MISSING"),
        ("schwab", "NOT_CONFIGURED"),
        ("tradier", "CAPABILITY_UNPROVEN"),
        ("binance_us", "ADAPTER_MISSING"),
    ):
        capabilities.append(_disabled_placeholder(venue_id, reason))
    return VenueCapabilityRegistry(tuple(capabilities))
