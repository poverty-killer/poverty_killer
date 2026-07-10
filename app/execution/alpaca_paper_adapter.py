from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Protocol

from app.operator_credentials.store import (
    ALPACA_LIVE_ENDPOINT as FORBIDDEN_ALPACA_LIVE_BASE_URL,
    ALPACA_PAPER_ENDPOINT as EXPECTED_ALPACA_PAPER_BASE_URL,
    alpaca_endpoint_authority,
    canonical_alpaca_paper_env_path,
    read_alpaca_paper_env_file,
)
from app.execution.broker_gateway import (
    BrokerAdapterIdentity,
    BrokerCredentialStatus,
    BrokerEnvironment,
    BrokerGatewayError,
    BrokerGatewayResponse,
    BrokerOrderSubmitRequest,
    NormalizedBrokerStatus,
)
from app.execution.broker_read_policy import (
    BROKER_READ_NOT_AUTHORIZED,
    BrokerReadPermissionProfile,
    broker_read_family_for_get_path,
    broker_read_profile_from_env,
    coerce_broker_read_profile,
)


ALPACA_PAPER_CREDENTIAL_KEYS = ("APCA_API_BASE_URL", "APCA_API_KEY_ID", "APCA_API_SECRET_KEY")
ALPACA_PAPER_REQUIRED_SECRET_KEYS = ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")


class AlpacaTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, Any]:
        ...


class UrllibAlpacaTransport:
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, Any]:
        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return response.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"message": raw[:300]}
            return exc.code, parsed
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise BrokerGatewayError("network_unavailable", message=type(exc).__name__) from None


@dataclass(frozen=True)
class AlpacaPaperCredentials:
    base_url: str
    key_id: str
    secret_key: str

    @property
    def status(self) -> str:
        if self.base_url and self.key_id and self.secret_key:
            return BrokerCredentialStatus.CONFIGURED.value
        return BrokerCredentialStatus.MISSING.value


@dataclass(frozen=True)
class AlpacaPaperCredentialAuthorityProof:
    status: str
    reason_codes: tuple[str, ...]
    endpoint: str
    credential_status: str
    credential_source: str
    fallback_path: str
    fallback_file_exists: bool
    process_env_present: dict[str, bool]
    fallback_file_present: dict[str, bool]
    process_env_fingerprints: dict[str, dict[str, Any]]
    fallback_file_fingerprints: dict[str, dict[str, Any]]
    effective_fingerprints: dict[str, dict[str, Any]]
    live_endpoint_used: bool = False

    def to_sanitized_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason_codes": self.reason_codes,
            "endpoint": self.endpoint,
            "credential_status": self.credential_status,
            "credential_source": self.credential_source,
            "fallback_path": self.fallback_path,
            "fallback_file_exists": self.fallback_file_exists,
            "process_env_present": dict(self.process_env_present),
            "fallback_file_present": dict(self.fallback_file_present),
            "process_env_fingerprints": dict(self.process_env_fingerprints),
            "fallback_file_fingerprints": dict(self.fallback_file_fingerprints),
            "effective_fingerprints": dict(self.effective_fingerprints),
            "live_endpoint_used": self.live_endpoint_used,
        }


@dataclass(frozen=True)
class AlpacaPaperReadOnlyReconciliationProof:
    status: str
    reason_codes: tuple[str, ...]
    endpoint: str
    environment: str
    account_status: str
    positions_count: int
    open_orders_count: int
    request_counts: dict[str, int]
    broker_truth: dict[str, Any]
    mutation_occurred: bool = False
    live_endpoint_used: bool = False

    def to_sanitized_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason_codes": self.reason_codes,
            "endpoint": self.endpoint,
            "environment": self.environment,
            "account_status": self.account_status,
            "positions_count": self.positions_count,
            "open_orders_count": self.open_orders_count,
            "request_counts": dict(self.request_counts),
            "mutation_occurred": self.mutation_occurred,
            "live_endpoint_used": self.live_endpoint_used,
            "broker_truth_keys": tuple(sorted(self.broker_truth.keys())),
        }


@dataclass(frozen=True)
class AlpacaPaperReadOnlyPreflightProof:
    status: str
    reason_codes: tuple[str, ...]
    credential_authority: AlpacaPaperCredentialAuthorityProof
    reconciliation: AlpacaPaperReadOnlyReconciliationProof | None

    def to_sanitized_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason_codes": self.reason_codes,
            "credential_authority": self.credential_authority.to_sanitized_dict(),
            "reconciliation": self.reconciliation.to_sanitized_dict() if self.reconciliation else None,
        }


def _default_alpaca_paper_env_path() -> Path:
    return canonical_alpaca_paper_env_path()


def _read_alpaca_paper_env_file(env_path: Path) -> dict[str, str]:
    return read_alpaca_paper_env_file(env_path)


def _credential_fingerprint(value: str) -> dict[str, Any]:
    return {
        "present": bool(value),
        "length": len(value),
        "sha256_12": hashlib.sha256(value.encode("utf-8")).hexdigest()[:12] if value else "missing",
        "has_leading_or_trailing_space": value != value.strip(),
        "has_quote_chars": "'" in value or '"' in value,
        "has_newline": "\n" in value or "\r" in value,
    }


def validate_alpaca_paper_credential_authority(
    path: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> AlpacaPaperCredentialAuthorityProof:
    env_path = path or _default_alpaca_paper_env_path()
    env_values = {key: (env or os.environ).get(key, "") or "" for key in ALPACA_PAPER_CREDENTIAL_KEYS}
    file_values = _read_alpaca_paper_env_file(env_path)
    effective_values = {
        key: file_values.get(key, "")
        for key in ALPACA_PAPER_CREDENTIAL_KEYS
    }

    reasons: list[str] = []
    missing = [key for key in ALPACA_PAPER_REQUIRED_SECRET_KEYS if not effective_values.get(key)]
    if missing:
        reasons.append("CREDENTIALS_MISSING")

    endpoint_authority = alpaca_endpoint_authority(effective_values)
    endpoint = str(endpoint_authority["alpaca_endpoint_display"] or "")
    if endpoint_authority["paper_endpoint_only"] is not True:
        reasons.append(str(endpoint_authority["reason_code"] or "ALPACA_PAPER_ENDPOINT_REQUIRED"))
    else:
        effective_values["APCA_API_BASE_URL"] = EXPECTED_ALPACA_PAPER_BASE_URL

    process_present = {key: bool(env_values.get(key)) for key in ALPACA_PAPER_CREDENTIAL_KEYS}
    fallback_present = {key: bool(file_values.get(key)) for key in ALPACA_PAPER_CREDENTIAL_KEYS}
    credential_source = "canonical_paper_env_file"
    credentials = AlpacaPaperCredentials(
        base_url=endpoint,
        key_id=effective_values.get("APCA_API_KEY_ID", ""),
        secret_key=effective_values.get("APCA_API_SECRET_KEY", ""),
    )
    status = "CREDENTIAL_AUTHORITY_OK" if not reasons else "FAILED_CLOSED"
    return AlpacaPaperCredentialAuthorityProof(
        status=status,
        reason_codes=tuple(dict.fromkeys(reasons or ["CREDENTIAL_AUTHORITY_OK"])),
        endpoint=endpoint,
        credential_status=credentials.status,
        credential_source=credential_source,
        fallback_path=str(env_path),
        fallback_file_exists=env_path.exists(),
        process_env_present=process_present,
        fallback_file_present=fallback_present,
        process_env_fingerprints={key: _credential_fingerprint(env_values.get(key, "")) for key in ALPACA_PAPER_CREDENTIAL_KEYS},
        fallback_file_fingerprints={
            key: _credential_fingerprint(file_values.get(key, "")) for key in ALPACA_PAPER_CREDENTIAL_KEYS
        },
        effective_fingerprints={
            key: _credential_fingerprint(effective_values.get(key, "")) for key in ALPACA_PAPER_CREDENTIAL_KEYS
        },
        live_endpoint_used=endpoint_authority["alpaca_trading_endpoint_family"] == "live",
    )


def load_alpaca_paper_credentials(path: Path | None = None, *, enforce_authority: bool = True) -> AlpacaPaperCredentials:
    env_path = path or _default_alpaca_paper_env_path()
    if enforce_authority:
        proof = validate_alpaca_paper_credential_authority(env_path)
        if proof.status != "CREDENTIAL_AUTHORITY_OK":
            raise BrokerGatewayError("credential_authority_blocked", message=",".join(proof.reason_codes))
    values = _read_alpaca_paper_env_file(env_path)
    return AlpacaPaperCredentials(
        base_url=str(alpaca_endpoint_authority({"APCA_API_BASE_URL": values.get("APCA_API_BASE_URL") or ""})["alpaca_endpoint_display"] or ""),
        key_id=values.get("APCA_API_KEY_ID") or "",
        secret_key=values.get("APCA_API_SECRET_KEY") or "",
    )


class AlpacaPaperBrokerAdapter:
    adapter_id = "alpaca_paper_rest"
    venue_id = "alpaca"
    portal_id = "alpaca_paper"
    environment = BrokerEnvironment.PAPER.value
    supported_asset_classes = frozenset({"equity", "us_equity", "etf", "crypto"})
    supported_methods = frozenset({"GET", "POST", "DELETE"})

    _allowed_get_paths = frozenset({"/v2/account", "/v2/account/activities", "/v2/positions", "/v2/orders", "/v2/clock"})
    _allowed_get_prefixes = ("/v2/orders/", "/v2/assets/")

    def __init__(
        self,
        credentials: AlpacaPaperCredentials,
        *,
        transport: AlpacaTransport | None = None,
        timeout: float = 10.0,
        read_profile: BrokerReadPermissionProfile | Mapping[str, Any] | str | None = None,
    ) -> None:
        self._credentials = credentials
        self._transport = transport or UrllibAlpacaTransport()
        self._timeout = timeout
        self._read_profile = (
            coerce_broker_read_profile(read_profile)
            if read_profile is not None
            else broker_read_profile_from_env(os.environ)
        )
        self._request_counts = {"GET": 0, "POST": 0}
        self._validate_credentials()

    @classmethod
    def from_env(
        cls,
        *,
        transport: AlpacaTransport | None = None,
        timeout: float = 10.0,
        credential_path: Path | None = None,
        read_profile: BrokerReadPermissionProfile | Mapping[str, Any] | str | None = None,
    ) -> "AlpacaPaperBrokerAdapter":
        return cls(
            load_alpaca_paper_credentials(credential_path),
            transport=transport,
            timeout=timeout,
            read_profile=read_profile,
        )

    @property
    def identity(self) -> BrokerAdapterIdentity:
        return BrokerAdapterIdentity(
            adapter_id=self.adapter_id,
            venue_id=self.venue_id,
            portal_id=self.portal_id,
            environment=self.environment,
            base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
            credential_status=self._credentials.status,
            supported_methods=self.supported_methods,
            supported_asset_classes=self.supported_asset_classes,
            live_blocked=True,
        )

    @property
    def request_counts(self) -> dict[str, int]:
        return dict(self._request_counts)

    @property
    def broker_read_permission_profile(self) -> BrokerReadPermissionProfile:
        return self._read_profile

    def get_account(self) -> BrokerGatewayResponse:
        return self._request("GET", "/v2/account")

    def get_positions(self) -> BrokerGatewayResponse:
        return self._request("GET", "/v2/positions")

    def get_open_orders(self) -> BrokerGatewayResponse:
        return self._request("GET", "/v2/orders", query={"status": "open", "limit": "100", "nested": "false"})

    def get_clock(self) -> BrokerGatewayResponse:
        return self._request("GET", "/v2/clock")

    def get_asset(self, symbol: str) -> BrokerGatewayResponse:
        safe_symbol = str(symbol or "").strip().upper()
        if not safe_symbol:
            raise BrokerGatewayError("symbol_missing")
        return self._request("GET", f"/v2/assets/{urllib.parse.quote(safe_symbol, safe='')}")

    def get_order_status(self, order_id: str) -> BrokerGatewayResponse:
        safe_order_id = str(order_id or "").strip()
        if not safe_order_id:
            raise BrokerGatewayError("order_id_missing")
        return self._request("GET", f"/v2/orders/{urllib.parse.quote(safe_order_id, safe='')}")

    def get_account_activities(
        self,
        *,
        activity_types: str = "FILL",
        page_size: int = 100,
        after: str | None = None,
        until: str | None = None,
        date: str | None = None,
    ) -> BrokerGatewayResponse:
        safe_activity_types = str(activity_types or "FILL").strip().upper()
        safe_page_size = max(1, min(int(page_size or 100), 100))
        query = {"activity_types": safe_activity_types, "page_size": str(safe_page_size)}
        if after:
            query["after"] = str(after)
        if until:
            query["until"] = str(until)
        if date:
            query["date"] = str(date)
        return self._request(
            "GET",
            "/v2/account/activities",
            query=query,
        )

    def get_fee_activities(
        self,
        *,
        page_size: int = 100,
        after: str | None = None,
        until: str | None = None,
        date: str | None = None,
    ) -> BrokerGatewayResponse:
        """Read-only Alpaca account activity fetch for deferred broker fee truth."""
        return self.get_account_activities(
            activity_types="CFEE,FEE",
            page_size=page_size,
            after=after,
            until=until,
            date=date,
        )

    def submit_order(self, order: BrokerOrderSubmitRequest) -> BrokerGatewayResponse:
        payload = self._payload_for_order(order)
        return self._request("POST", "/v2/orders", payload=payload)

    def cancel_order(self, order_id: str) -> BrokerGatewayResponse:
        safe_order_id = str(order_id or "").strip()
        if not safe_order_id:
            raise BrokerGatewayError("order_id_missing")
        return self._request("DELETE", f"/v2/orders/{urllib.parse.quote(safe_order_id, safe='')}")

    def request_unsupported(self, method: str, path: str) -> BrokerGatewayResponse:
        return self._request(method, path)

    def _validate_credentials(self) -> None:
        missing = []
        if not self._credentials.base_url:
            missing.append("APCA_API_BASE_URL")
        if not self._credentials.key_id:
            missing.append("APCA_API_KEY_ID")
        if not self._credentials.secret_key:
            missing.append("APCA_API_SECRET_KEY")
        if missing:
            raise BrokerGatewayError("credentials_missing", message="missing:" + ",".join(missing))
        endpoint_authority = alpaca_endpoint_authority({"APCA_API_BASE_URL": self._credentials.base_url})
        if endpoint_authority["paper_endpoint_only"] is not True:
            raise BrokerGatewayError("live_or_nonpaper_endpoint_blocked", message="alpaca_paper_endpoint_required")

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self._credentials.key_id,
            "APCA-API-SECRET-KEY": self._credentials.secret_key,
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> BrokerGatewayResponse:
        method = method.upper()
        self._validate_request(method, path, query=query, payload=payload)
        headers = self._headers()
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        url = EXPECTED_ALPACA_PAPER_BASE_URL + path
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        self._request_counts[method] = self._request_counts.get(method, 0) + 1
        status_code, response_payload = self._transport.request(
            method=method,
            url=url,
            headers=headers,
            body=body,
            timeout=self._timeout,
        )
        return self._normalize_response(method, path, status_code, response_payload)

    def _validate_request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None,
        payload: dict[str, Any] | None,
    ) -> None:
        if method not in self.supported_methods:
            raise BrokerGatewayError("unsupported_method")
        if method == "GET":
            if payload is not None:
                raise BrokerGatewayError("get_payload_forbidden")
            if path not in self._allowed_get_paths and not any(path.startswith(prefix) for prefix in self._allowed_get_prefixes):
                raise BrokerGatewayError("unsupported_get_path")
            if path == "/v2/orders" and (query or {}).get("status") != "open":
                raise BrokerGatewayError("orders_get_must_be_open_status")
            family = broker_read_family_for_get_path(path)
            activity_type = (query or {}).get("activity_types")
            if not self._read_profile.allows(family, activity_type):
                reason = self._read_profile.denial_reason(family, activity_type)
                raise BrokerGatewayError(
                    reason,
                    message=f"{BROKER_READ_NOT_AUTHORIZED}:{self._read_profile.name}:{family}",
                )
            return
        if method == "POST":
            if path != "/v2/orders":
                raise BrokerGatewayError("unsupported_post_path")
            if payload is None:
                raise BrokerGatewayError("post_payload_missing")
            return
        if method == "DELETE":
            if payload is not None:
                raise BrokerGatewayError("delete_payload_forbidden")
            if not path.startswith("/v2/orders/"):
                raise BrokerGatewayError("unsupported_delete_path")
            if path.rstrip("/") == "/v2/orders":
                raise BrokerGatewayError("delete_order_id_required")
            return

    def _payload_for_order(self, order: BrokerOrderSubmitRequest) -> dict[str, Any]:
        reasons: list[str] = []
        if order.side.lower() != "buy":
            reasons.append("only_buy_supported")
        if order.order_type.lower() != "limit":
            reasons.append("only_limit_supported")
        if order.quantity <= Decimal("0"):
            reasons.append("quantity_nonpositive")
        if order.limit_price is None or order.limit_price <= Decimal("0"):
            reasons.append("limit_price_required")
        if not order.client_order_id.strip():
            reasons.append("client_order_id_required")
        if reasons:
            raise BrokerGatewayError("invalid_order_request", message=",".join(reasons))
        return {
            "symbol": order.symbol,
            "side": order.side.lower(),
            "type": order.order_type.lower(),
            "time_in_force": order.time_in_force.lower(),
            "qty": format(order.quantity, "f"),
            "limit_price": format(order.limit_price, "f"),
            "extended_hours": False,
            "client_order_id": order.client_order_id,
        }

    def _normalize_response(
        self,
        method: str,
        path: str,
        status_code: int,
        payload: Any,
    ) -> BrokerGatewayResponse:
        ok = 200 <= status_code < 300
        raw_status = payload.get("status") if isinstance(payload, dict) else None
        normalized_status = (
            NormalizedBrokerStatus.CANCELED.value
            if method == "DELETE" and ok
            else _normalize_status(raw_status, ok=ok)
        )
        reason_code = None
        message = None
        if not ok:
            reason_code, message = _normalize_error(payload, status_code)
            normalized_status = NormalizedBrokerStatus.REJECTED.value if method == "POST" else NormalizedBrokerStatus.UNKNOWN.value
        return BrokerGatewayResponse(
            adapter_id=self.adapter_id,
            venue_id=self.venue_id,
            portal_id=self.portal_id,
            environment=self.environment,
            request_method=method,
            endpoint_path=path,
            ok=ok,
            mutation_occurred=method in {"POST", "DELETE"} and ok,
            live_blocked=True,
            broker_order_id=(
                payload.get("id")
                if isinstance(payload, dict) and payload.get("id")
                else (path.rsplit("/", 1)[-1] if method == "DELETE" and ok else None)
            ),
            client_order_id=payload.get("client_order_id") if isinstance(payload, dict) else None,
            raw_broker_status=str(raw_status) if raw_status is not None else None,
            normalized_status=normalized_status,
            reason_code=reason_code,
            message=message,
            payload=payload,
            reconciliation_metadata={
                "http_status": status_code,
                "source": self.adapter_id,
                "requires_reconciliation": method == "POST",
            },
        )


def collect_alpaca_paper_read_only_reconciliation_truth(
    adapter: AlpacaPaperBrokerAdapter,
) -> AlpacaPaperReadOnlyReconciliationProof:
    """
    Collect canonical Alpaca PAPER read-only broker truth through adapter GETs.

    This helper does not submit orders and does not mutate broker state. It
    exists to bundle account, positions, and open-orders truth with request
    counts for readiness/reconciliation evidence.
    """
    identity = adapter.identity
    reasons: list[str] = []
    if identity.base_url != EXPECTED_ALPACA_PAPER_BASE_URL:
        reasons.append("ALPACA_PAPER_ENDPOINT_REQUIRED")
    if identity.environment != BrokerEnvironment.PAPER.value:
        reasons.append("ALPACA_ENVIRONMENT_NOT_PAPER")
    if identity.live_blocked is not True:
        reasons.append("LIVE_ENDPOINT_NOT_BLOCKED")

    try:
        account = adapter.get_account()
        positions = adapter.get_positions()
        open_orders = adapter.get_open_orders()
    except BrokerGatewayError as exc:
        return AlpacaPaperReadOnlyReconciliationProof(
            status="MISSING_BROKER_TRUTH",
            reason_codes=tuple(dict.fromkeys([*reasons, exc.reason_code])),
            endpoint=identity.base_url,
            environment=identity.environment,
            account_status="missing",
            positions_count=0,
            open_orders_count=0,
            request_counts=dict(adapter.request_counts),
            broker_truth={},
            mutation_occurred=False,
            live_endpoint_used=identity.base_url == FORBIDDEN_ALPACA_LIVE_BASE_URL,
        )

    responses = (account, positions, open_orders)
    if any(not response.ok for response in responses):
        reasons.append("BROKER_READ_ONLY_GET_FAILED")
    if any(response.mutation_occurred for response in responses):
        reasons.append("BROKER_READ_ONLY_MUTATION_OCCURRED")

    counts = dict(adapter.request_counts)
    if counts.get("POST", 0) != 0:
        reasons.append("POST_COUNT_NONZERO")

    broker_truth = {
        "account": account.payload,
        "positions": positions.payload if isinstance(positions.payload, list) else [],
        "open_orders": open_orders.payload if isinstance(open_orders.payload, list) else [],
    }
    status = "BROKER_READ_ONLY_RECONCILED" if not reasons else "FAILED_CLOSED"
    account_status = "read" if account.ok else "missing"
    return AlpacaPaperReadOnlyReconciliationProof(
        status=status,
        reason_codes=tuple(dict.fromkeys(reasons or ["BROKER_READ_ONLY_GETS_SUCCEEDED"])),
        endpoint=identity.base_url,
        environment=identity.environment,
        account_status=account_status,
        positions_count=len(broker_truth["positions"]),
        open_orders_count=len(broker_truth["open_orders"]),
        request_counts=counts,
        broker_truth=broker_truth,
        mutation_occurred=any(response.mutation_occurred for response in responses),
        live_endpoint_used=identity.base_url == FORBIDDEN_ALPACA_LIVE_BASE_URL,
    )


def collect_alpaca_paper_read_only_preflight_truth(
    *,
    credential_path: Path | None = None,
    transport: AlpacaTransport | None = None,
    timeout: float = 10.0,
) -> AlpacaPaperReadOnlyPreflightProof:
    """
    Validate Alpaca PAPER credential authority, then perform GET-only broker preflight.

    This preflight is intentionally non-mutating. It blocks stale process env
    credentials before constructing the adapter, then collects account,
    positions, and open-order truth through the existing read-only helper.
    """
    authority = validate_alpaca_paper_credential_authority(credential_path)
    if authority.status != "CREDENTIAL_AUTHORITY_OK":
        return AlpacaPaperReadOnlyPreflightProof(
            status="FAILED_CLOSED",
            reason_codes=authority.reason_codes,
            credential_authority=authority,
            reconciliation=None,
        )

    try:
        adapter = AlpacaPaperBrokerAdapter.from_env(
            transport=transport,
            timeout=timeout,
            credential_path=credential_path,
        )
    except BrokerGatewayError as exc:
        return AlpacaPaperReadOnlyPreflightProof(
            status="FAILED_CLOSED",
            reason_codes=tuple(dict.fromkeys([*authority.reason_codes, exc.reason_code])),
            credential_authority=authority,
            reconciliation=None,
        )

    reconciliation = collect_alpaca_paper_read_only_reconciliation_truth(adapter)
    reasons = list(authority.reason_codes)
    if reconciliation.status != "BROKER_READ_ONLY_RECONCILED":
        reasons.extend(reconciliation.reason_codes)
    if reconciliation.request_counts.get("POST", 0) != 0:
        reasons.append("POST_COUNT_NONZERO")
    if reconciliation.mutation_occurred:
        reasons.append("BROKER_READ_ONLY_MUTATION_OCCURRED")
    if reconciliation.live_endpoint_used:
        reasons.append("LIVE_ENDPOINT_USED")
    status = "PAPER_READ_ONLY_PREFLIGHT_PASSED" if reconciliation.status == "BROKER_READ_ONLY_RECONCILED" and not (
        reconciliation.request_counts.get("POST", 0)
        or reconciliation.mutation_occurred
        or reconciliation.live_endpoint_used
    ) else "FAILED_CLOSED"
    return AlpacaPaperReadOnlyPreflightProof(
        status=status,
        reason_codes=tuple(dict.fromkeys(reasons)),
        credential_authority=authority,
        reconciliation=reconciliation,
    )


def _normalize_status(raw_status: Any, *, ok: bool) -> str:
    status = str(raw_status or "").lower()
    if status in {"accepted", "new", "pending_new"}:
        return NormalizedBrokerStatus.ACCEPTED.value
    if status in {"open", "accepted_for_bidding"}:
        return NormalizedBrokerStatus.OPEN.value
    if status == "filled":
        return NormalizedBrokerStatus.FILLED.value
    if status == "partially_filled":
        return NormalizedBrokerStatus.PARTIALLY_FILLED.value
    if status in {"canceled", "cancelled"}:
        return NormalizedBrokerStatus.CANCELED.value
    if status == "expired":
        return NormalizedBrokerStatus.EXPIRED.value
    if status == "rejected":
        return NormalizedBrokerStatus.REJECTED.value
    if ok:
        return NormalizedBrokerStatus.ACCEPTED.value
    return NormalizedBrokerStatus.UNKNOWN.value


def _normalize_error(payload: Any, status_code: int) -> tuple[str, str]:
    if isinstance(payload, dict):
        broker_code = payload.get("code")
        message = str(payload.get("message") or payload.get("error") or "")
        if "minimal amount of order" in message or "cost basis" in message:
            return "MIN_NOTIONAL_NOT_MET", message
        if "time_in_force" in message:
            return "TIME_IN_FORCE_UNSUPPORTED", message
        if broker_code is not None:
            return f"BROKER_{broker_code}", message or f"HTTP {status_code}"
        return f"HTTP_{status_code}", message or f"HTTP {status_code}"
    return f"HTTP_{status_code}", f"HTTP {status_code}"
