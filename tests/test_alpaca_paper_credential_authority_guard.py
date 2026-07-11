from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from app.execution.alpaca_paper_adapter import (
    EXPECTED_ALPACA_PAPER_BASE_URL,
    FORBIDDEN_ALPACA_LIVE_BASE_URL,
    alpaca_paper_preflight_account_pin_status,
    collect_alpaca_paper_read_only_preflight_truth,
    validate_alpaca_paper_credential_authority,
)


class StubTransport:
    def __init__(self, *, account_id: str | None = "paper-account-045ded") -> None:
        self.calls: list[dict[str, object]] = []
        self.account_id = account_id

    def request(self, *, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float):
        self.calls.append(
            {
                "method": method,
                "path": urlparse(url).path,
                "headers": tuple(sorted(headers)),
                "body": body,
                "timeout": timeout,
            }
        )
        path = urlparse(url).path
        if path == "/v2/account":
            payload = {"status": "ACTIVE"}
            if self.account_id is not None:
                payload["id"] = self.account_id
            return 200, payload
        if path == "/v2/positions":
            return 200, [{"symbol": "AAPL", "qty": "1"}]
        if path == "/v2/orders":
            return 200, []
        return 404, {"message": "unexpected path"}


def _write_env_file(path: Path, *, base_url: str, key_id: str, secret_key: str) -> None:
    path.write_text(
        "\n".join(
            (
                f"APCA_API_BASE_URL={base_url}",
                f"APCA_API_KEY_ID={key_id}",
                f"APCA_API_SECRET_KEY={secret_key}",
            )
        ),
        encoding="utf-8",
    )


def _set_process_env(monkeypatch, *, base_url: str, key_id: str, secret_key: str) -> None:
    monkeypatch.setenv("APCA_API_BASE_URL", base_url)
    monkeypatch.setenv("APCA_API_KEY_ID", key_id)
    monkeypatch.setenv("APCA_API_SECRET_KEY", secret_key)


def test_canonical_env_file_is_paper_execution_authority_even_when_process_env_matches(monkeypatch, tmp_path):
    env_path = tmp_path / "alpaca_paper.env"
    _write_env_file(
        env_path,
        base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
        key_id="paper-key",
        secret_key="paper-secret",
    )
    _set_process_env(
        monkeypatch,
        base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
        key_id="paper-key",
        secret_key="paper-secret",
    )

    proof = validate_alpaca_paper_credential_authority(env_path)

    assert proof.status == "CREDENTIAL_AUTHORITY_OK"
    assert proof.credential_source == "canonical_paper_env_file"
    assert proof.live_endpoint_used is False


def test_paper_endpoint_variants_normalize_for_credential_authority(monkeypatch, tmp_path):
    env_path = tmp_path / "alpaca_paper.env"
    _write_env_file(
        env_path,
        base_url=" HTTPS://PAPER-API.ALPACA.MARKETS/v2 ",
        key_id="paper-key",
        secret_key="paper-secret",
    )
    monkeypatch.delenv("APCA_API_BASE_URL", raising=False)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    proof = validate_alpaca_paper_credential_authority(env_path)

    assert proof.status == "CREDENTIAL_AUTHORITY_OK"
    assert proof.endpoint == EXPECTED_ALPACA_PAPER_BASE_URL
    assert proof.live_endpoint_used is False


def test_missing_base_url_defaults_to_paper_when_key_and_secret_present(monkeypatch, tmp_path):
    env_path = tmp_path / "missing_base.env"
    env_path.write_text(
        "\n".join(
            (
                "APCA_API_KEY_ID=paper-key",
                "APCA_API_SECRET_KEY=paper-secret",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("APCA_API_BASE_URL", raising=False)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    proof = validate_alpaca_paper_credential_authority(env_path)

    assert proof.status == "CREDENTIAL_AUTHORITY_OK"
    assert proof.endpoint == EXPECTED_ALPACA_PAPER_BASE_URL
    assert "CREDENTIALS_MISSING" not in proof.reason_codes


def test_mismatched_process_env_is_demoted_when_canonical_file_is_valid(monkeypatch, tmp_path):
    env_path = tmp_path / "alpaca_paper.env"
    _write_env_file(
        env_path,
        base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
        key_id="valid-file-key",
        secret_key="valid-file-secret",
    )
    _set_process_env(
        monkeypatch,
        base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
        key_id="stale-process-key",
        secret_key="stale-process-secret",
    )

    proof = validate_alpaca_paper_credential_authority(env_path)

    assert proof.status == "CREDENTIAL_AUTHORITY_OK"
    assert proof.credential_source == "canonical_paper_env_file"
    assert "STALE_PROCESS_ENV_CREDENTIALS" not in proof.reason_codes
    assert "CREDENTIAL_AUTHORITY_CONFLICT" not in proof.reason_codes
    assert proof.process_env_present["APCA_API_KEY_ID"] is True
    assert (
        proof.effective_fingerprints["APCA_API_KEY_ID"]["sha256_12"]
        != proof.process_env_fingerprints["APCA_API_KEY_ID"]["sha256_12"]
    )


def test_missing_key_or_secret_fails_closed(monkeypatch, tmp_path):
    env_path = tmp_path / "missing.env"
    monkeypatch.delenv("APCA_API_BASE_URL", raising=False)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    proof = validate_alpaca_paper_credential_authority(env_path)

    assert proof.status == "FAILED_CLOSED"
    assert "CREDENTIALS_MISSING" in proof.reason_codes


def test_live_endpoint_fails_closed(monkeypatch, tmp_path):
    env_path = tmp_path / "live.env"
    _write_env_file(
        env_path,
        base_url=FORBIDDEN_ALPACA_LIVE_BASE_URL,
        key_id="paper-key",
        secret_key="paper-secret",
    )
    monkeypatch.delenv("APCA_API_BASE_URL", raising=False)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    proof = validate_alpaca_paper_credential_authority(env_path)

    assert proof.status == "FAILED_CLOSED"
    assert "LIVE_ENDPOINT_BLOCKED" in proof.reason_codes
    assert proof.live_endpoint_used is True


def test_valid_paper_credentials_can_proceed_to_get_only_preflight(monkeypatch, tmp_path):
    env_path = tmp_path / "alpaca_paper.env"
    _write_env_file(
        env_path,
        base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
        key_id="paper-key",
        secret_key="paper-secret",
    )
    monkeypatch.delenv("APCA_API_BASE_URL", raising=False)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    transport = StubTransport()

    proof = collect_alpaca_paper_read_only_preflight_truth(credential_path=env_path, transport=transport)

    assert proof.status == "PAPER_READ_ONLY_PREFLIGHT_PASSED"
    assert proof.reconciliation is not None
    assert proof.reconciliation.request_counts == {"GET": 3, "POST": 0}
    assert proof.reconciliation.positions_count == 1
    assert proof.reconciliation.open_orders_count == 0
    assert proof.reconciliation.mutation_occurred is False
    assert proof.reconciliation.live_endpoint_used is False
    assert [call["method"] for call in transport.calls] == ["GET", "GET", "GET"]
    assert all(call["body"] is None for call in transport.calls)


def test_preflight_account_pin_status_passes_only_for_045ded(monkeypatch, tmp_path):
    env_path = tmp_path / "alpaca_paper.env"
    _write_env_file(
        env_path,
        base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
        key_id="paper-key",
        secret_key="paper-secret",
    )
    monkeypatch.delenv("APCA_API_BASE_URL", raising=False)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    proof = collect_alpaca_paper_read_only_preflight_truth(credential_path=env_path, transport=StubTransport(account_id="paper-account-045ded"))
    pin = alpaca_paper_preflight_account_pin_status(proof)

    assert pin["status"] == "PASS"
    assert pin["reason_code"] == "ALPACA_PAPER_ACCOUNT_PIN_OK"
    assert pin["expected_suffix"] == "045ded"
    assert pin["actual_suffix"] == "045ded"
    assert pin["account_pin_verified"] is True
    assert pin["broker_mutation_occurred"] is False


def test_preflight_account_pin_status_rejects_104e2a(monkeypatch, tmp_path):
    env_path = tmp_path / "alpaca_paper.env"
    _write_env_file(
        env_path,
        base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
        key_id="paper-key",
        secret_key="paper-secret",
    )
    monkeypatch.delenv("APCA_API_BASE_URL", raising=False)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    proof = collect_alpaca_paper_read_only_preflight_truth(credential_path=env_path, transport=StubTransport(account_id="paper-account-104e2a"))
    pin = alpaca_paper_preflight_account_pin_status(proof)

    assert pin["status"] == "BLOCKED"
    assert pin["reason_code"] == "ALPACA_PAPER_ACCOUNT_PIN_MISMATCH"
    assert pin["expected_suffix"] == "045ded"
    assert pin["actual_suffix"] == "104e2a"
    assert pin["account_pin_verified"] is False
    assert pin["broker_mutation_occurred"] is False


def test_preflight_account_pin_status_fails_closed_without_account_identity(monkeypatch, tmp_path):
    env_path = tmp_path / "alpaca_paper.env"
    _write_env_file(
        env_path,
        base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
        key_id="paper-key",
        secret_key="paper-secret",
    )
    monkeypatch.delenv("APCA_API_BASE_URL", raising=False)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    proof = collect_alpaca_paper_read_only_preflight_truth(credential_path=env_path, transport=StubTransport(account_id=None))
    pin = alpaca_paper_preflight_account_pin_status(proof)

    assert pin["status"] == "BLOCKED"
    assert pin["reason_code"] == "ALPACA_PAPER_ACCOUNT_PIN_NOT_PROVEN"
    assert pin["expected_suffix"] == "045ded"
    assert pin["actual_suffix"] is None
    assert pin["account_pin_verified"] is False
    assert pin["broker_mutation_occurred"] is False


def test_sanitized_diagnostics_do_not_include_raw_secrets(monkeypatch, tmp_path):
    env_path = tmp_path / "alpaca_paper.env"
    raw_key = "raw-paper-key-do-not-print"
    raw_secret = "raw-paper-secret-do-not-print"
    _write_env_file(
        env_path,
        base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
        key_id=raw_key,
        secret_key=raw_secret,
    )
    monkeypatch.delenv("APCA_API_BASE_URL", raising=False)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    proof = validate_alpaca_paper_credential_authority(env_path)
    rendered = repr(proof.to_sanitized_dict())

    assert raw_key not in rendered
    assert raw_secret not in rendered
    assert "sha256_12" in rendered
