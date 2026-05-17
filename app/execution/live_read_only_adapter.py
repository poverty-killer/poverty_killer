"""
Read-only broker truth boundary.

This module is a non-executing wrapper for future sandbox/read-only broker
truth. It deliberately exposes no submit/cancel/replace surface and performs
no broker/network work by itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


ALLOWED_READ_ONLY_ENVIRONMENTS = frozenset({"sandbox", "paper", "testnet", "read_only"})
MUTATING_METHOD_NAMES = frozenset(
    {
        "submit_order",
        "cancel_order",
        "replace_order",
        "place_order",
        "place_market_order",
        "place_limit_order",
    }
)


class ReadOnlyBrokerSource(Protocol):
    """Read surfaces expected from an injected broker truth provider."""

    def fetch_balances(self) -> Any: ...

    def fetch_positions(self) -> Any: ...

    def fetch_normalized_open_orders(self) -> Any: ...

    def fetch_fills(self, *args: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class ReadOnlyAdapterConfig:
    read_only_enabled: bool = False
    environment: str | None = None
    source: str | None = None
    allow_mutation: bool = False
    board_authorized_production_read: bool = False
    account_id: str | None = None
    credentials_present: bool = False
    credentials_required_for_call: bool = True


@dataclass(frozen=True)
class ReadOnlyGateDecision:
    ready: bool
    reason_codes: tuple[str, ...] = ()
    read_only: bool = True
    mutation_allowed: bool = False
    side_effects: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReadOnlyBrokerSnapshot:
    source: str
    environment: str
    account_id: str | None
    account_identity_status: str
    balances: tuple[Any, ...]
    positions: tuple[Any, ...]
    open_orders: tuple[Any, ...]
    recent_fills: tuple[Any, ...]
    order_statuses: tuple[Any, ...] = ()
    receive_ts_ns: int | None = None
    asof_ts_ns: int | None = None
    read_only: bool = True
    mutation_allowed: bool = False
    snapshot_status: str = "ready"
    reason_codes: tuple[str, ...] = ()

    def contract_mapping(self) -> dict[str, bool]:
        return {
            "account_identity_source_environment_timestamp_25q": bool(
                self.source and self.environment and self.receive_ts_ns and self.account_identity_status == "known"
            ),
            "balances_25q": bool(self.balances),
            "positions_25q": bool(self.positions),
            "open_orders_25o_25q": True,
            "recent_fills_25p_25q": True,
            "read_only_no_submit_cancel_25m_25r": self.read_only and not self.mutation_allowed,
        }


class ReadOnlyGateError(RuntimeError):
    """Raised when a read-only broker call is blocked by the gate."""

    def __init__(self, reason_codes: tuple[str, ...]):
        self.reason_codes = reason_codes
        super().__init__(",".join(reason_codes))


class LiveReadOnlyBrokerAdapter:
    """Read-only wrapper around an injected broker truth provider."""

    def __init__(self, source: ReadOnlyBrokerSource, config: ReadOnlyAdapterConfig):
        self._source = source
        self._config = config

    @property
    def config(self) -> ReadOnlyAdapterConfig:
        return self._config

    def validate_gate(
        self,
        *,
        require_credentials: bool = False,
        require_account_identity: bool = False,
        receive_ts_ns: int | None = None,
        max_snapshot_age_ns: int | None = None,
        current_ts_ns: int | None = None,
    ) -> ReadOnlyGateDecision:
        reasons: list[str] = []

        if self._config.read_only_enabled is not True:
            reasons.append("read_only_not_enabled")
        if self._config.allow_mutation is not False:
            reasons.append("mutation_not_allowed")
        if not self._config.source:
            reasons.append("source_missing")
        env = (self._config.environment or "").lower()
        if not env:
            reasons.append("environment_missing")
        elif env not in ALLOWED_READ_ONLY_ENVIRONMENTS:
            if env in {"live", "production", "prod"} and not self._config.board_authorized_production_read:
                reasons.append("production_environment_not_board_authorized")
            else:
                reasons.append("environment_not_read_only")
        if require_account_identity and not self._config.account_id:
            reasons.append("account_identity_missing")
        if require_credentials and self._config.credentials_required_for_call and not self._config.credentials_present:
            reasons.append("credentials_missing_for_read_call")
        if receive_ts_ns is None or receive_ts_ns <= 0:
            reasons.append("snapshot_timestamp_missing")
        elif max_snapshot_age_ns is not None and current_ts_ns is not None:
            if current_ts_ns - receive_ts_ns > max_snapshot_age_ns:
                reasons.append("snapshot_stale")

        unique = tuple(dict.fromkeys(reasons))
        return ReadOnlyGateDecision(
            ready=not unique,
            reason_codes=unique,
            read_only=True,
            mutation_allowed=False,
            side_effects=(),
        )

    def _ensure_read_allowed(
        self,
        *,
        require_credentials: bool,
        require_account_identity: bool = False,
        receive_ts_ns: int,
    ) -> None:
        decision = self.validate_gate(
            require_credentials=require_credentials,
            require_account_identity=require_account_identity,
            receive_ts_ns=receive_ts_ns,
        )
        if not decision.ready:
            raise ReadOnlyGateError(decision.reason_codes)

    def get_account_identity(self, *, receive_ts_ns: int) -> dict[str, Any]:
        decision = self.validate_gate(receive_ts_ns=receive_ts_ns)
        if not decision.ready:
            raise ReadOnlyGateError(decision.reason_codes)
        return {
            "source": self._config.source,
            "environment": self._config.environment,
            "account_id": self._config.account_id,
            "account_identity_status": "known" if self._config.account_id else "missing",
            "read_only": True,
            "mutation_allowed": False,
        }

    def fetch_balances(self, *, receive_ts_ns: int, require_credentials: bool = True) -> Any:
        self._ensure_read_allowed(require_credentials=require_credentials, receive_ts_ns=receive_ts_ns)
        return self._source.fetch_balances()

    def fetch_positions(self, *, receive_ts_ns: int, require_credentials: bool = True) -> Any:
        self._ensure_read_allowed(require_credentials=require_credentials, receive_ts_ns=receive_ts_ns)
        return self._source.fetch_positions()

    def fetch_open_orders(self, *, receive_ts_ns: int, require_credentials: bool = True) -> Any:
        self._ensure_read_allowed(require_credentials=require_credentials, receive_ts_ns=receive_ts_ns)
        return self._source.fetch_normalized_open_orders()

    def fetch_recent_fills(
        self,
        *,
        receive_ts_ns: int,
        require_credentials: bool = True,
        limit: int = 100,
    ) -> Any:
        self._ensure_read_allowed(require_credentials=require_credentials, receive_ts_ns=receive_ts_ns)
        return self._source.fetch_fills(limit=limit)

    def fetch_order_status_read_only(
        self,
        order_id: str,
        *,
        receive_ts_ns: int,
        require_credentials: bool = True,
    ) -> Any:
        self._ensure_read_allowed(require_credentials=require_credentials, receive_ts_ns=receive_ts_ns)
        if not order_id:
            raise ReadOnlyGateError(("order_id_missing",))
        status_reader = getattr(self._source, "get_order_status", None)
        if not callable(status_reader):
            raise ReadOnlyGateError(("order_status_reader_missing",))
        return status_reader(order_id)

    def get_exchange_truth_snapshot(
        self,
        *,
        receive_ts_ns: int,
        asof_ts_ns: int | None = None,
        require_credentials: bool = True,
        require_account_identity: bool = True,
    ) -> ReadOnlyBrokerSnapshot:
        self._ensure_read_allowed(
            require_credentials=require_credentials,
            require_account_identity=require_account_identity,
            receive_ts_ns=receive_ts_ns,
        )
        return ReadOnlyBrokerSnapshot(
            source=str(self._config.source),
            environment=str(self._config.environment),
            account_id=self._config.account_id,
            account_identity_status="known" if self._config.account_id else "missing",
            balances=tuple(self._source.fetch_balances() or ()),
            positions=tuple(self._source.fetch_positions() or ()),
            open_orders=tuple(self._source.fetch_normalized_open_orders() or ()),
            recent_fills=tuple(self._source.fetch_fills(limit=100) or ()),
            order_statuses=(),
            receive_ts_ns=receive_ts_ns,
            asof_ts_ns=asof_ts_ns,
            read_only=True,
            mutation_allowed=False,
        )


__all__ = [
    "ALLOWED_READ_ONLY_ENVIRONMENTS",
    "MUTATING_METHOD_NAMES",
    "LiveReadOnlyBrokerAdapter",
    "ReadOnlyAdapterConfig",
    "ReadOnlyBrokerSnapshot",
    "ReadOnlyGateDecision",
    "ReadOnlyGateError",
]
