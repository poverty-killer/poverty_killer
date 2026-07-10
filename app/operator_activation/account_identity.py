"""Read-only Alpaca PAPER account identity pin for launch/start safety."""

from __future__ import annotations

from typing import Any, Mapping

from app.operator_credentials.store import (
    ALPACA_PAPER_ACCOUNT_PIN_SOURCE,
    alpaca_paper_account_pin_config,
    expected_alpaca_paper_account_suffix,
    normalize_alpaca_account_suffix,
)
from app.operator_portfolio.snapshot import ReadOnlyBrokerClient, build_account_identity_snapshot


ACCOUNT_PIN_OK = "ALPACA_PAPER_ACCOUNT_PIN_OK"
ACCOUNT_PIN_MISMATCH = "ALPACA_PAPER_ACCOUNT_PIN_MISMATCH"
ACCOUNT_PIN_NOT_PROVEN = "ALPACA_PAPER_ACCOUNT_PIN_NOT_PROVEN"
ACCOUNT_PIN_CHECK_FAILED = "ALPACA_PAPER_ACCOUNT_PIN_CHECK_FAILED"


def _base_assertion(
    *,
    status: str,
    reason_code: str,
    detail: str,
    expected_suffix: str,
    actual_suffix: str | None = None,
    identity_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = dict(identity_snapshot or {})
    return {
        "source": "OPERATOR_ALPACA_PAPER_ACCOUNT_PIN",
        "schema_version": "alpaca-paper-account-pin-v1",
        "pin_source": ALPACA_PAPER_ACCOUNT_PIN_SOURCE,
        "pin_config": alpaca_paper_account_pin_config(),
        "status": status,
        "reason_code": reason_code,
        "detail": detail,
        "expected_suffix": expected_suffix,
        "actual_suffix": actual_suffix,
        "paper_account_pinned": status == "PASS",
        "broker_identity_snapshot": snapshot,
        "broker_read_attempted": snapshot.get("broker_read_attempted") is True,
        "broker_read_occurred": snapshot.get("broker_read_occurred") is True,
        "account_request_occurred": snapshot.get("account_request_occurred") is True,
        "broker_mutation_occurred": False,
        "order_submission_occurred": False,
        "cancel_occurred": False,
        "liquidation_occurred": False,
        "live_enabled": False,
        "real_money_enabled": False,
        "secrets_values_exposed": False,
        "raw_secret_values_included": False,
    }


def blocked_account_identity_assertion(reason_code: str, detail: str) -> dict[str, Any]:
    expected = expected_alpaca_paper_account_suffix()
    return _base_assertion(
        status="BLOCKED",
        reason_code=str(reason_code or ACCOUNT_PIN_NOT_PROVEN),
        detail=detail,
        expected_suffix=expected,
    )


def build_alpaca_paper_account_identity_assertion(
    env: Mapping[str, str],
    *,
    client: ReadOnlyBrokerClient | None = None,
    expected_suffix: str | None = None,
    broker_read_authorized: bool = True,
) -> dict[str, Any]:
    expected = normalize_alpaca_account_suffix(expected_suffix or expected_alpaca_paper_account_suffix(env))
    if not expected:
        return _base_assertion(
            status="BLOCKED",
            reason_code=ACCOUNT_PIN_NOT_PROVEN,
            detail="No canonical Alpaca PAPER account suffix pin is configured.",
            expected_suffix="",
        )

    try:
        snapshot = build_account_identity_snapshot(
            env,
            client=client,
            broker_read_authorized=broker_read_authorized,
        )
    except Exception as exc:  # pragma: no cover - defensive fail-closed boundary.
        return _base_assertion(
            status="BLOCKED",
            reason_code=ACCOUNT_PIN_CHECK_FAILED,
            detail=f"Account identity assertion failed closed: {exc.__class__.__name__}.",
            expected_suffix=expected,
        )

    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), Mapping) else {}
    actual = normalize_alpaca_account_suffix(summary.get("account_id"))
    if snapshot.get("status") != "BROKER_CONFIRMED" or not actual:
        reason = str(snapshot.get("unavailable_reason") or ACCOUNT_PIN_NOT_PROVEN)
        return _base_assertion(
            status="BLOCKED",
            reason_code=ACCOUNT_PIN_NOT_PROVEN,
            detail=f"Expected Alpaca PAPER account suffix {expected}, but broker account identity is not proven: {reason}.",
            expected_suffix=expected,
            actual_suffix=actual,
            identity_snapshot=snapshot,
        )

    if actual != expected:
        return _base_assertion(
            status="BLOCKED",
            reason_code=ACCOUNT_PIN_MISMATCH,
            detail=f"Expected Alpaca PAPER account suffix {expected}, got {actual}.",
            expected_suffix=expected,
            actual_suffix=actual,
            identity_snapshot=snapshot,
        )

    return _base_assertion(
        status="PASS",
        reason_code=ACCOUNT_PIN_OK,
        detail=f"Broker-reported Alpaca PAPER account suffix matches the pinned account {expected}.",
        expected_suffix=expected,
        actual_suffix=actual,
        identity_snapshot=snapshot,
    )


def account_identity_assertion_passed(assertion: Mapping[str, Any] | None) -> bool:
    return isinstance(assertion, Mapping) and assertion.get("status") == "PASS"
