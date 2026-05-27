from __future__ import annotations

from app.api.operator_session_store import OperatorSessionStore


def test_operator_session_store_writes_and_loads_latest_session(tmp_path):
    path = tmp_path / "operator" / "sessions.jsonl"
    store = OperatorSessionStore(path=path)
    first = {
        "session_id": "paper_1",
        "requested_at": "2026-05-27T00:00:00+00:00",
        "status": "EXITED",
        "profile": "PAPER_EXPLORATION_ALPHA",
    }
    second = {
        "session_id": "paper_2",
        "requested_at": "2026-05-27T01:00:00+00:00",
        "status": "RUNNING",
        "profile": "PAPER_EXPLORATION_ALPHA",
    }

    store.write_session(first)
    store.write_session(second)
    reloaded = OperatorSessionStore(path=path)

    assert reloaded.latest_session()["session_id"] == "paper_2"
    assert reloaded.status()["session_count"] == 2
    assert reloaded.status()["status"] == "READY"


def test_operator_session_store_handles_corrupt_lines_safely(tmp_path):
    path = tmp_path / "operator" / "sessions.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("not-json\n", encoding="utf-8")

    store = OperatorSessionStore(path=path)

    assert store.latest_session() is None
    assert store.status()["status"] == "DEGRADED"
    assert store.status()["corrupt_line_count"] == 1
