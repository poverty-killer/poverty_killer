from __future__ import annotations

from app.ai_chief_operator.config import AIChiefConfig
from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.operator_credentials.store import LocalCredentialStore


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def test_supreme_board_packet_bridge_generates_safe_copy_ready_packet(tmp_path):
    store = LocalCredentialStore(tmp_path / ".operator_secrets" / "provider_credentials.json")
    store.save_provider("openai", {"OPENAI_API_KEY": "openai-packet-test-token-1234567890"})
    provider = OperatorSnapshotProvider(
        runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
        provider_env={},
        credential_store=store,
        ai_config=AIChiefConfig(provider="disabled", enabled=False),
    )
    app = create_operator_app(provider=provider)

    packet = _endpoint(app, "/operator/ai/supreme-board-packet", "POST")(
        {
            "question": "Plan a 7-day PAPER run and identify missing evidence before live.",
            "page_context": {"page_id": "command", "page_title": "Run PAPER"},
        }
    )
    text = str(packet)

    assert packet["status"] == "PACKET_READY"
    assert packet["answer_source"] == "SUPREME_BOARD_PACKET"
    assert packet["cost_mode"] == "CHATGPT_PRO_MANUAL"
    assert packet["persona_enforced"] is True
    assert "Chief Quant Advisor" in packet["packet"]
    assert "Execution/TCA Auditor" in packet["packet"]
    assert "No live trading enablement." in packet["packet"]
    assert "openai-packet-test-token" not in text
    assert "sha256:" not in text
    assert packet["broker_call_occurred"] is False
    assert packet["trading_mutation_occurred"] is False
    assert packet["live_enabled"] is False
    assert packet["real_money_enabled"] is False
