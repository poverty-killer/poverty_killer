"""F4B: Sentiment velocity concurrency and liveness tests."""
import threading
from typing import List
from unittest.mock import MagicMock

import pytest

from app.brain.sentiment_velocity import SentimentVelocityEngine, SentimentVector
from app.symbol_runtime import SymbolRuntime, SentimentUpdate


def _make_runtime() -> SymbolRuntime:
    rt = SymbolRuntime(symbol="XBT/USD")
    rt.sentiment_velocity_engine = SentimentVelocityEngine()
    return rt


class TestAdmitSentimentNoRace:
    def test_no_exception_under_concurrent_update(self):
        rt = _make_runtime()
        errors: List[Exception] = []
        base_ts = 1_000_000_000_000

        def thread_fn(offset: int, count: int = 100):
            for i in range(count):
                ts = base_ts + (offset * 10_000_000_000) + (i * 1_000_000)
                try:
                    rt._admit_sentiment_update(float(i) / count, ts)
                except Exception as exc:
                    errors.append(exc)

        t1 = threading.Thread(target=thread_fn, args=(0,))
        t2 = threading.Thread(target=thread_fn, args=(1,))
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert errors == [], f"Concurrent update raised: {errors}"

    def test_last_sent_timestamp_is_valid_int_after_concurrent_updates(self):
        rt = _make_runtime()
        base_ts = 2_000_000_000_000

        def thread_fn(offset: int, count: int = 50):
            for i in range(count):
                ts = base_ts + (offset * 5_000_000_000) + (i * 2_000_000)
                rt._admit_sentiment_update(0.5, ts)

        t1 = threading.Thread(target=thread_fn, args=(0,))
        t2 = threading.Thread(target=thread_fn, args=(1,))
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert isinstance(rt._last_sent_timestamp_ns, int)
        assert rt._last_sent_timestamp_ns >= 0


class TestSentimentVelocityEngineConcurrent:
    def test_no_exception_concurrent_update(self):
        engine = SentimentVelocityEngine()
        errors: List[Exception] = []

        def feed(start_ts: int, count: int = 50):
            for i in range(count):
                ts = start_ts + i * 1_000_000_000
                try:
                    engine.update_sentiment(0.1 * (i % 10 - 5), ts)
                except Exception as exc:
                    errors.append(exc)

        base = 10_000_000_000_000
        t1 = threading.Thread(target=feed, args=(base,))
        t2 = threading.Thread(target=feed, args=(base + 1_000_000_000_000,))
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert errors == [], f"Engine raised under concurrency: {errors}"

    def test_history_bounded_after_concurrent_updates(self):
        engine = SentimentVelocityEngine(history_maxlen=100)

        def feed(start_ts: int, count: int = 200):
            for i in range(count):
                ts = start_ts + i * 1_000_000_000
                engine.update_sentiment(float(i % 10) / 10.0, ts)

        base = 20_000_000_000_000
        t1 = threading.Thread(target=feed, args=(base,))
        t2 = threading.Thread(target=feed, args=(base + 500_000_000_000,))
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert len(engine._history) <= engine.history_maxlen


class TestSentimentVelocityLiveness:
    def test_get_current_vector_after_min_history(self):
        engine = SentimentVelocityEngine(min_history_points=5)
        base_ts = 100_000_000_000_000
        for i in range(10):
            engine.update_sentiment(float(i) / 10.0 - 0.5, base_ts + i * 1_000_000_000)

        vec = engine.get_current_vector()
        assert vec is not None
        assert isinstance(vec, SentimentVector)
        assert -0.1 <= vec.velocity <= 0.1

    def test_symbol_runtime_caller_chain_returns_float(self):
        rt = _make_runtime()
        proxy = MagicMock()
        proxy.get_sentiment.return_value = 0.3
        rt.sentiment_proxy = proxy

        base_ts = 200_000_000_000_000
        for i in range(10):
            rt.update_sentiment_engine(base_ts + i * 1_000_000_000)

        velocity = rt.get_sentiment_velocity()
        assert isinstance(velocity, float)


class TestSentimentBufferNoLostUpdates:
    def test_all_sequential_timestamps_delivered(self):
        rt = _make_runtime()
        base_ts = 300_000_000_000_000
        n = 50
        for i in range(n):
            rt._admit_sentiment_update(float(i) / n, base_ts + i * 1_000_000_000)

        expected_last = base_ts + (n - 1) * 1_000_000_000
        assert rt._last_sent_timestamp_ns == expected_last
        assert len(rt._sentiment_buffer) == 0
