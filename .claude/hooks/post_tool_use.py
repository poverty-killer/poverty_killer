#!/usr/bin/env python3
"""
G0 PostToolUse hook for POVERTY_KILLER Claude Terminal.

Append-only journal of edit events. Never blocks. Fail-open on any error so
that journaling problems do not interrupt Claude Code's tool flow.

Writes one JSON object per line to state/session_journal.jsonl with:
  ts, tool, file_path, packet, summary
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict


_THIS = Path(__file__).resolve()
REPO_ROOT = _THIS.parent.parent.parent
JOURNAL_PATH = REPO_ROOT / "state" / "session_journal.jsonl"


def _summary_for(tool: str, tool_input: Dict[str, Any]) -> str:
    if tool in ("Edit", "Write", "MultiEdit"):
        path = tool_input.get("file_path") or tool_input.get("filePath") or ""
        return f"{tool}:{path}"
    if tool == "Bash":
        cmd = tool_input.get("command") or ""
        return f"Bash:{cmd[:120]}"
    return f"{tool}"


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw or not raw.strip():
            return 0
        try:
            event = json.loads(raw)
        except Exception:
            return 0
        if not isinstance(event, dict):
            return 0
        tool = event.get("tool_name") or event.get("tool") or ""
        tool_input = event.get("tool_input") or event.get("toolInput") or {}
        if not isinstance(tool_input, dict):
            tool_input = {}
        path = tool_input.get("file_path") or tool_input.get("filePath") or ""
        record = {
            "ts": int(time.time()),
            "tool": tool,
            "file_path": path,
            "packet": (os.environ.get("POVERTY_KILLER_PACKET") or "").strip(),
            "summary": _summary_for(tool, tool_input),
        }
        JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Journaling MUST never block tool flow.
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
