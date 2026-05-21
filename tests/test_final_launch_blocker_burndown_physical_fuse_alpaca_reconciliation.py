from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlparse

from app.core.decision_compiler import DecisionCompiler
from app.core.truth_reconciler import TruthReconciler
from app.execution.alpaca_paper_adapter import (
    EXPECTED_ALPACA_PAPER_BASE_URL,
    AlpacaPaperBrokerAdapter,
    AlpacaPaperCredentials,
    collect_alpaca_paper_read_only_reconciliation_truth,
)
from app.models.contracts import (
    ExchangePosition,
    ExchangeTruth,
    ExecutionTruth,
    PortfolioPosition,
    PortfolioTruth,
    RiskTruth,
    StrategyTruth,
    TruthFrame,
)
from app.models.enums import TruthStatus
from app.monitoring.health import evaluate_physical_fuse_readiness


T0_NS = 1_779_300_000_000_000_000


class StubTransport:
    def __init__(self, responses: dict[tuple[str, str], tuple[int, object]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def request(self, *, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float):
        self.calls.append(
            {
                "method": method,
                "path": urlparse(url).path,
                "body": body,
                "timeout": timeout,
            }
        )
        path = urlparse(url).path
        return self.responses.get((method, path), (404, {"message": "missing fixture response"}))


def _creds() -> AlpacaPaperCredentials:
    return AlpacaPaperCredentials(
        base_url=EXPECTED_ALPACA_PAPER_BASE_URL,
        key_id="deterministic-key",
        secret_key="deterministic-secret",
    )


def _truth_frame() -> TruthFrame:
    return TruthFrame(
        truth_frame_id="final-blocker-burndown-truth",
        timestamp_ns=T0_NS,
        exchange_truth=ExchangeTruth(venue="alpaca_paper", exchange_ts_ns=T0_NS),
        execution_truth=ExecutionTruth(last_reconciliation_ts_ns=T0_NS),
        portfolio_truth=PortfolioTruth(last_update_ts_ns=T0_NS),
        strategy_truth=StrategyTruth(last_update_ts_ns=T0_NS),
        risk_truth=RiskTruth(),
        status=TruthStatus.RECONCILED,
    )


def _exchange_truth(qty: str = "1") -> ExchangeTruth:
    return ExchangeTruth(
        venue="alpaca_paper",
        balances={"USD": Decimal("1000")},
        positions=[
            ExchangePosition(
                symbol="AAPL",
                side="long",
                quantity=Decimal(qty),
                entry_price=Decimal("100"),
            )
        ],
        open_orders=[],
        exchange_ts_ns=T0_NS,
    )


def _portfolio_truth(qty: str = "1") -> PortfolioTruth:
    return PortfolioTruth(
        cash={"USD": Decimal("1000")},
        positions=[
            PortfolioPosition(
                symbol="AAPL",
                quantity=Decimal(qty),
                avg_price=Decimal("100"),
                mark_price=Decimal("100"),
                unrealized_pnl=Decimal("0"),
            )
        ],
        last_update_ts_ns=T0_NS,
    )


def test_physical_fuse_active_blocks_autonomous_paper_readiness():
    status = evaluate_physical_fuse_readiness(
        {
            "physical_fuse_triggered": True,
            "current_equity": 14000,
            "high_water_mark": 20000,
            "physical_fuse": 15000,
            "drawdown_from_peak": 0.30,
        }
    )

    assert status.status == "PHYSICAL_FUSE_ACTIVE"
    assert status.blocks_autonomous_paper is True
    assert "PHYSICAL_FUSE_BLOCKS_AUTONOMOUS_PAPER" in status.reason_codes


def test_physical_fuse_cannot_clear_without_current_safe_operator_reset():
    status = evaluate_physical_fuse_readiness(
        {
            "physical_fuse_triggered": True,
            "current_equity": 20000,
            "high_water_mark": 20000,
            "physical_fuse": 15000,
            "drawdown_from_peak": 0,
        }
    )

    assert status.status == "PHYSICAL_FUSE_STALE"
    assert status.blocks_autonomous_paper is True
    assert status.requires_operator_action is True
    assert "PHYSICAL_FUSE_REQUIRES_OPERATOR_ACTION" in status.reason_codes


def test_cleared_physical_fuse_reports_launch_nonblocking():
    status = evaluate_physical_fuse_readiness(
        {
            "physical_fuse_triggered": False,
            "current_equity": 20000,
            "high_water_mark": 20000,
            "physical_fuse": 15000,
            "drawdown_from_peak": 0,
        }
    )

    assert status.status == "PHYSICAL_FUSE_CLEARED"
    assert status.blocks_autonomous_paper is False


def test_rest_dns_partial_truth_does_not_masquerade_as_full_health():
    compiler = DecisionCompiler()
    record = compiler.compile(
        truth_frame=_truth_frame(),
        additional_inputs={
            "market_truth_summary": {
                "status": "MARKET_DATA_PARTIAL_TRUTH",
                "feed_truth_status": "WEBSOCKET_ACTIVE_REST_DNS_FAILED",
                "missing_truth": ("MISSING_CANDLE_TRUTH", "MISSING_ORDER_BOOK_TRUTH"),
            }
        },
    )

    assert record.metadata["market_truth_summary"]["status"] == "MARKET_DATA_PARTIAL_TRUTH"
    assert record.metadata["market_truth_summary"]["feed_truth_status"] != "MARKET_DATA_FULL_TRUTH"


def test_missing_alpaca_reconciliation_truth_blocks_readiness():
    transport = StubTransport(
        {
            ("GET", "/v2/account"): (503, {"message": "service unavailable"}),
            ("GET", "/v2/positions"): (200, []),
            ("GET", "/v2/orders"): (200, []),
        }
    )
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport)

    proof = collect_alpaca_paper_read_only_reconciliation_truth(adapter)

    assert proof.status == "FAILED_CLOSED"
    assert "BROKER_READ_ONLY_GET_FAILED" in proof.reason_codes
    assert proof.request_counts == {"GET": 3, "POST": 0}
    assert proof.mutation_occurred is False


def test_alpaca_paper_read_only_truth_satisfies_reconciliation_fixture_path():
    transport = StubTransport(
        {
            ("GET", "/v2/account"): (200, {"id": "paper-account", "status": "ACTIVE", "cash": "1000"}),
            ("GET", "/v2/positions"): (200, [{"symbol": "AAPL", "qty": "1", "avg_entry_price": "100"}]),
            ("GET", "/v2/orders"): (200, []),
        }
    )
    adapter = AlpacaPaperBrokerAdapter(_creds(), transport=transport)

    proof = collect_alpaca_paper_read_only_reconciliation_truth(adapter)

    assert proof.status == "BROKER_READ_ONLY_RECONCILED"
    assert proof.endpoint == EXPECTED_ALPACA_PAPER_BASE_URL
    assert proof.environment == "paper"
    assert proof.account_status == "read"
    assert proof.positions_count == 1
    assert proof.open_orders_count == 0
    assert proof.request_counts == {"GET": 3, "POST": 0}
    assert all(call["method"] == "GET" for call in transport.calls)
    assert all(call["body"] is None for call in transport.calls)


def test_broker_local_conflict_fails_closed_and_local_state_cannot_override_broker_truth():
    reconciler = TruthReconciler()

    status, reasons = reconciler.reconcile(
        _exchange_truth(qty="1"),
        ExecutionTruth(last_reconciliation_ts_ns=T0_NS),
        _portfolio_truth(qty="2"),
        StrategyTruth(last_update_ts_ns=T0_NS),
        RiskTruth(),
    )

    assert status == TruthStatus.BROKEN
    assert any("position.AAPL.quantity" in reason for reason in reasons)
    assert _exchange_truth(qty="1").positions[0].quantity == Decimal("1")


def test_readiness_metadata_records_fuse_and_reconciliation_status_without_fake_truth():
    proof_transport = StubTransport(
        {
            ("GET", "/v2/account"): (200, {"id": "paper-account", "status": "ACTIVE", "cash": "1000"}),
            ("GET", "/v2/positions"): (200, [{"symbol": "AAPL", "qty": "1"}]),
            ("GET", "/v2/orders"): (200, []),
        }
    )
    proof = collect_alpaca_paper_read_only_reconciliation_truth(
        AlpacaPaperBrokerAdapter(_creds(), transport=proof_transport)
    )
    fuse = evaluate_physical_fuse_readiness(
        {
            "physical_fuse_triggered": True,
            "current_equity": 20000,
            "high_water_mark": 20000,
            "physical_fuse": 15000,
            "drawdown_from_peak": 0,
        }
    )

    record = DecisionCompiler().compile(
        truth_frame=_truth_frame(),
        additional_inputs={
            "broker_truth_attribution": {
                "AlpacaPaperReadOnly": proof.to_sanitized_dict(),
            },
            "truth_reconciliation_attribution": {
                "status": proof.status,
                "broker_truth_canonical": True,
                "local_state_supporting_only": True,
            },
            "health_readiness_summary": {
                "physical_fuse": fuse.to_dict(),
                "final_readiness": "NOT_READY_FOR_AUTONOMOUS_PAPER",
            },
        },
    )

    assert record.metadata["broker_truth_attribution"]["AlpacaPaperReadOnly"]["request_counts"]["POST"] == 0
    assert record.metadata["truth_reconciliation_attribution"]["broker_truth_canonical"] is True
    assert record.outputs["additional"]["health_readiness_summary"]["physical_fuse"]["status"] == "PHYSICAL_FUSE_STALE"
    assert "secret" not in str(record.metadata).lower()
