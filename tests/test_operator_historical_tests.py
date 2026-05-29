from __future__ import annotations

from datetime import date

from app.api.operator_readonly_api import OperatorSnapshotProvider, create_operator_app
from app.api.operator_runtime_config import OperatorRuntimeConfig
from app.operator_historical_tests.service import HistoricalTestService, run_historical_test


def _endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if route.path == path and method in (route.methods or set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


class FakeHistoricalDataClient:
    def __init__(self) -> None:
        self.calls = []

    def fetch_bars(self, *, symbols, start_date, end_date, timeframe):
        self.calls.append(
            {
                "symbols": symbols,
                "start_date": start_date,
                "end_date": end_date,
                "timeframe": timeframe,
                "method": "GET_HISTORICAL_BARS_ONLY",
            }
        )
        return {symbol: [{"t": start_date, "c": "100"}] for symbol in symbols}


def test_four_month_preset_is_available_and_honest_without_harness():
    service = HistoricalTestService(today=date(2026, 5, 29))

    summary = service.summary()
    result = service.run({"date_range_preset": "last_4_months", "watchlist": "BTC/USD,ETH/USD,SOL/USD"})

    assert summary["presets"][0]["id"] == "last_4_months"
    assert summary["presets"][0]["end_date"] == "2026-05-29"
    assert result["request"]["start_date"] == "2026-01-27"
    assert result["status"] == "NOT_IMPLEMENTED_READY_FOR_HARNESS"
    assert result["result"]["final_equity"] is None
    assert result["result"]["total_return"] is None
    assert result["result"]["max_drawdown"] is None
    assert result["result"]["simulated_trade_count"] == 0
    assert "NO_FAKE_PERFORMANCE_NUMBERS" in result["result"]["reason_codes"]
    assert result["broker_trading_call_occurred"] is False
    assert result["broker_mutation_occurred"] is False
    assert result["live_enabled"] is False
    assert result["real_money_enabled"] is False


def test_fake_historical_data_client_can_be_used_without_fake_pnl():
    client = FakeHistoricalDataClient()

    result = run_historical_test(
        {"date_range_preset": "last_4_months", "timeframe": "1Hour"},
        market_data_client=client,
        today=date(2026, 5, 29),
    )

    assert client.calls
    assert client.calls[0]["method"] == "GET_HISTORICAL_BARS_ONLY"
    assert result["status"] == "DATA_READY_SIMULATION_NOT_AVAILABLE"
    assert result["result"]["data_freshness_completeness"]["total_bars_loaded"] == 3
    assert result["result"]["final_equity"] is None
    assert result["result"]["per_symbol_summary"][0]["simulated_trades"] == 0
    assert result["read_only_market_data_only"] is True
    assert result["paper_started"] is False


def test_operator_historical_endpoints_are_read_only_and_report_caveats(tmp_path):
    service = HistoricalTestService(today=date(2026, 5, 29))
    app = create_operator_app(
        provider=OperatorSnapshotProvider(
            runtime_config=OperatorRuntimeConfig.from_env({}, repo_root=tmp_path),
            historical_tests=service,
        )
    )

    summary = _endpoint(app, "/operator/historical-tests")()
    run = _endpoint(app, "/operator/historical-tests/run", "POST")({"date_range_preset": "last_4_months"})
    detail = _endpoint(app, "/operator/historical-tests/{test_id}", "GET")(run["test_id"])
    report = _endpoint(app, "/operator/historical-tests/{test_id}/report", "GET")(run["test_id"])

    assert summary["can_execute"] is False
    assert run["can_execute"] is False
    assert run["broker_trading_call_occurred"] is False
    assert run["trading_mutation_occurred"] is False
    assert detail["test_id"] == run["test_id"]
    assert report["logs_mutated"] is False
    assert "not future-profit proof" in report["markdown"].lower()
    assert "Final equity: unknown" in report["markdown"]
