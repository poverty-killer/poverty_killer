"""Operator-facing historical test foundation.

This package is advisory/read-only. It does not import broker, execution, OMS,
strategy, alpha, threshold, or runtime mutation modules.
"""

from app.operator_historical_tests.service import HistoricalTestService, run_historical_test

__all__ = ["HistoricalTestService", "run_historical_test"]
