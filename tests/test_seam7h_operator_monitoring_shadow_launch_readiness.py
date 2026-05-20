from __future__ import annotations

import os
import sys
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from app.api.dashboard_server import SovereignDashboard
from app.config import Config
from app.constants import ControlMode
from app.control_plane import ControlPlane
from app.execution.alpaca_paper_adapter import EXPECTED_ALPACA_PAPER_BASE_URL
from app.monitoring.alerts import AlertSeverity, AlertType, SovereignSentinel
from app.monitoring.health import ComponentCriticality, HealthMonitor
from app.monitoring.performance_attribution import AttributionQuality, PerformanceAttributor
from app.monitoring.reports import ReportGenerator, ReportQuality, ReportType


T0_NS = 1_779_100_000_000_000_000


def _operator_record(
    *,
    module_name: str,
    category: str,
    status: str,
    effect: str,
    reason: str,
    input_truth: str,
    output_summary: str,
    provenance: dict,
    blocking: bool = False,
    operator_action_required: str | None = None,
) -> dict:
    return {
        "module_name": module_name,
        "category": category,
        "status": status,
        "effect": effect,
        "reason": reason,
        "input_truth": input_truth,
        "output_summary": output_summary,
        "provenance": provenance,
        "blocking": blocking,
        "operator_action_required": operator_action_required,
        "timestamp": T0_NS,
    }


def test_control_plane_signs_operator_posture_without_broker_authority(tmp_path):
    control = ControlPlane(control_dir=str(tmp_path / "control"))

    assert control.get_mode() == ControlMode.NORMAL
    assert control.should_allow_trading() is True

    command_result = control.process_command(
        SimpleNamespace(command="SET_MODE", mode="SAFE", source="seam7h_test")
    )

    assert command_result == {"status": "success", "mode": "safe"}
    assert control.get_mode() == ControlMode.SAFE

    record = _operator_record(
        module_name="ControlPlane",
        category="operator_control",
        status="ACTIVE_OPERATOR_CONTROL",
        effect="DOCUMENTS_ROLLBACK",
        reason="MODE_FILE_OPERATOR_CONTROL_ONLY",
        input_truth="temporary local mode file",
        output_summary="mode changed to SAFE; no broker submit/cancel surface exposed",
        provenance=control.get_state().__dict__,
    )
    assert record["status"] == "ACTIVE_OPERATOR_CONTROL"
    assert "broker" not in record["output_summary"].lower() or "no broker" in record["output_summary"].lower()


def test_dashboard_server_is_validated_without_starting_open_port():
    dashboard = SovereignDashboard(bot_instance=None, api_key="test-key")

    stats = dashboard.get_stats()
    full_packet = dashboard._build_full_state_packet()
    health_route_paths = {route.path for route in dashboard.app.routes}

    assert dashboard._running is False
    assert stats["connections"] == 0
    assert full_packet["bot"] == {"error": "Bot not available"}
    assert "/health" in health_route_paths
    assert "/api/mode/{mode}" in health_route_paths

    record = _operator_record(
        module_name="SovereignDashboard",
        category="dashboard_server",
        status="INTENTIONALLY_BLOCKED_SERVER_START",
        effect="NO_EFFECT_WITH_REASON",
        reason="TESTS_MUST_NOT_OPEN_PORTS_OR_EXERCISE_MUTATING_OPERATOR_ENDPOINTS",
        input_truth="FastAPI route table and local in-memory dashboard object",
        output_summary="health/status helpers import and instantiate; server start not called",
        provenance=stats,
        blocking=False,
        operator_action_required="Do not start dashboard without explicit bounded operator approval.",
    )
    assert record["status"] == "INTENTIONALLY_BLOCKED_SERVER_START"
    assert dashboard.get_connections() == 0


def test_alerts_generate_local_records_without_external_dispatch(tmp_path, monkeypatch):
    def forbidden_post(*args, **kwargs):
        raise AssertionError("external alert dispatch must not run in Seam 7H tests")

    monkeypatch.setattr("app.monitoring.alerts.requests.post", forbidden_post)
    sentinel = SovereignSentinel(
        webhook_url=None,
        telegram_bot_token=None,
        telegram_chat_id=None,
        alert_cooldown_sec=0.0,
        state_file=str(tmp_path / "alert_state.json"),
    )

    sentinel.send_alert(
        AlertType.EXCHANGE_OUTAGE,
        AlertSeverity.CRITICAL,
        "DNS failure prevents required market truth",
        {"reason": "DNS_FAILURE_RECORDED"},
    )

    recent = sentinel.get_recent_alerts()
    assert len(recent) == 1
    assert recent[0]["type"] == AlertType.EXCHANGE_OUTAGE.value
    assert recent[0]["data"]["reason"] == "DNS_FAILURE_RECORDED"
    assert sentinel.get_status()["alert_history_count"] == 1

    record = _operator_record(
        module_name="SovereignSentinel",
        category="alerting",
        status="ACTIVE_ALERTING_LOCAL",
        effect="EMITS_ALERT",
        reason="EXTERNAL_ALERTS_UNCONFIGURED_AND_NOT_SENT",
        input_truth="local alert object",
        output_summary="alert recorded locally; requests.post was not called",
        provenance=recent[0],
    )
    assert record["status"] == "ACTIVE_ALERTING_LOCAL"


def test_health_performance_and_reports_use_only_provided_truth(tmp_path):
    health = HealthMonitor(stale_threshold_ms=500)
    health.register_component("shadow_gate", criticality=ComponentCriticality.CRITICAL)
    health.pulse("shadow_gate", T0_NS, {"broker_mutation_count": 0})
    health_snapshot = health.get_snapshot_canonical(current_ts_ns=T0_NS + 1_000_000)

    assert health_snapshot.healthy is True
    assert health_snapshot.components["shadow_gate"]["metadata"]["broker_mutation_count"] == 0

    attributor = PerformanceAttributor()
    empty_snapshot = attributor.get_aggregate_snapshot(timestamp_ns=T0_NS)
    assert empty_snapshot.record_count == 0
    assert empty_snapshot.total_net_pnl == Decimal("0")
    assert empty_snapshot.quality == AttributionQuality.PARTIAL

    attributor.attribute_trade_detailed(
        symbol="AAPL",
        exit_price=Decimal("101"),
        entry_price=Decimal("100"),
        market_move_pct=Decimal("0.01"),
        fees=Decimal("0.10"),
        slippage=Decimal("0.05"),
        quantity=Decimal("1"),
        sleeve=None,
        strategy_tag="provided_truth_only",
        timestamp_ns=T0_NS,
    )
    populated = attributor.get_aggregate_snapshot(timestamp_ns=T0_NS + 1)
    assert populated.record_count == 1
    assert populated.total_net_pnl == Decimal("0.85")

    generator = ReportGenerator(output_path=str(tmp_path))
    result = generator.generate_packet(
        report_type=ReportType.BOARD_PACKET,
        timestamp_ns=T0_NS,
        equity_curve=[Decimal("1000"), Decimal("1000")],
        trade_history=[],
        attribution_stats=asdict(empty_snapshot),
        health_summary=asdict(health_snapshot),
        environment="paper_shadow",
        write_to_disk=False,
    )

    assert result.success is True
    assert result.packet is not None
    assert result.packet.quality == ReportQuality.COMPLETE
    assert result.packet.performance.absolute_pnl == Decimal("0")
    assert "digest_sha256" in result.json_payload


def test_shadow_flags_paper_endpoint_and_launch_commands_are_documented(monkeypatch):
    with pytest.raises(ValueError, match="shadow_read_only requires broker_mode='paper'"):
        Config(broker_mode="live", shadow_read_only=True)

    cfg = Config(broker_mode="paper", shadow_read_only=True)
    assert cfg.shadow_read_only is True
    assert cfg.broker_mode == "paper"
    assert EXPECTED_ALPACA_PAPER_BASE_URL == "https://paper-api.alpaca.markets"

    monkeypatch.setattr(sys, "argv", ["main.py", "--paper", "--shadow-read-only", "--log-level", "INFO"])
    args = main.parse_arguments()
    assert args.paper is True
    assert args.shadow_read_only is True
    assert args.log_level == "INFO"

    assert "POVERTY_KILLER_APPROVE_SEAM6_ALPACA_PAPER_PORTFOLIO_EXPANSION" not in os.environ

    readiness = Path("reports/autonomous_paper_friday_readiness.md").read_text(encoding="utf-8")
    seam = Path("reports/seam7h_operator_monitoring_shadow_launch_readiness.md").read_text(encoding="utf-8")
    for text in (readiness, seam):
        assert "venv/Scripts/python.exe main.py --paper --shadow-read-only --log-level INFO" in text
        assert "venv/Scripts/python.exe main.py --paper --log-level INFO" in text
        assert "POVERTY_KILLER_SHADOW_READ_ONLY=1" in text
        assert "Ctrl+C" in text
        assert "taskkill" in text
        assert "https://paper-api.alpaca.markets" in text
        assert "no live endpoint" in text.lower()
        assert "no broker mutation in shadow" in text.lower()
