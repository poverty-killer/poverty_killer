"""Plain-English DecisionFrame explainer.

The explainer accepts existing DecisionFrame-shaped dictionaries. It never
changes scores or asks strategy/risk/execution code to recompute a decision.
"""

from __future__ import annotations

from typing import Any


def _module_rows(frame: dict[str, Any]) -> list[dict[str, Any]]:
    raw = frame.get("module_evidence") or frame.get("moduleEvidence") or {}
    if isinstance(raw, dict):
        return [dict(value) for value in raw.values() if isinstance(value, dict)]
    if isinstance(raw, list):
        return [dict(value) for value in raw if isinstance(value, dict)]
    return []


def _frame_id(frame: dict[str, Any]) -> str:
    return str(frame.get("frame_id") or frame.get("frameId") or "unknown_frame")


def _output(frame: dict[str, Any]) -> str:
    return str(frame.get("frame_output") or frame.get("output") or "NO_TRADE").upper()


def _reason_codes(frame: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = [str(item) for item in frame.get("frame_reason_codes") or frame.get("reason_codes") or ()]
    for row in rows:
        for code in row.get("reason_codes") or ():
            reasons.append(str(code))
    return list(dict.fromkeys(reason for reason in reasons if reason))


def _blockers(rows: list[dict[str, Any]], frame: dict[str, Any]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    if str(frame.get("frame_status") or "").upper() == "BLOCK":
        blockers.append({"source": "DecisionFrame", "reason": "FRAME_BLOCK"})
    for row in rows:
        status = str(row.get("status") or "").upper()
        authority = str(row.get("authority_class") or "").upper()
        if status in {"BLOCK", "MISSING_TRUTH", "STALE"} or (
            status == "DECLINED" and authority in {"MARKET_TRUTH", "RISK", "BROKER_AUTHORITY", "EXECUTION"}
        ):
            blockers.append(
                {
                    "source": str(row.get("module_name") or "unknown_module"),
                    "reason": ",".join(str(code) for code in row.get("reason_codes") or ()) or status,
                }
            )
    return blockers


def _netedge(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        name = str(row.get("module_name") or "").lower()
        if "netedge" in name or "net_edge" in name:
            return ",".join(str(code) for code in row.get("reason_codes") or ()) or str(row.get("status") or "UNKNOWN")
    return "UNKNOWN_NOT_PRESENT_IN_FRAME"


class DecisionExplainer:
    def __init__(self, decisions: list[dict[str, Any]] | None = None) -> None:
        self.decisions = [dict(item) for item in decisions or []]

    def explain_latest(self) -> dict[str, Any]:
        if not self.decisions:
            return self.no_runtime()
        return self.explain(self.decisions[0])

    def explain_by_id(self, frame_id: str) -> dict[str, Any]:
        for frame in self.decisions:
            if _frame_id(frame) == str(frame_id):
                return self.explain(frame)
        fallback = self.no_runtime()
        fallback["frame_id"] = str(frame_id)
        fallback["headline"] = "DecisionFrame evidence is not available for this frame."
        fallback["missing_truth"] = ["DECISIONFRAME_NOT_FOUND"]
        return fallback

    def no_runtime(self) -> dict[str, Any]:
        return {
            "source": "NO_ACTIVE_RUNTIME_ATTACHED",
            "frame_id": None,
            "headline": "No active DecisionFrame evidence is attached to the operator backend.",
            "evidence": [],
            "blockers": ["NO_DECISIONFRAME_EVIDENCE"],
            "next_best_action": "Start or review a governed PAPER run, then inspect archive and runtime summaries.",
            "confidence": "LOW",
            "missing_truth": ["LATEST_DECISIONFRAME", "MARKET_TRUTH_STATE", "NETEDGE_RESULT", "BROKER_BOUNDARY_STATE"],
            "scoring_changed": False,
        }

    def explain(self, frame: dict[str, Any]) -> dict[str, Any]:
        rows = _module_rows(frame)
        output = _output(frame)
        blockers = _blockers(rows, frame)
        reasons = _reason_codes(frame, rows)
        symbol = frame.get("symbol") or "unknown symbol"
        if output == "BUY" and not blockers:
            headline = f"BUY was selected for {symbol} because the frame passed its hard blockers."
            next_best = "Audit order acknowledgement, fill hydration, fees, and TCA before drawing performance conclusions."
        elif output == "SELL":
            headline = f"SELL evidence was observed for {symbol}, but sell authority remains broker-position-truth gated."
            next_best = "Confirm broker position truth and OMS reconciliation before treating SELL as executable."
        elif blockers:
            headline = f"{output} was blocked or degraded for {symbol} by required truth or guardrail evidence."
            next_best = "Resolve the listed blockers; do not lower thresholds or bypass hard gates."
        else:
            headline = f"NO_TRADE was selected for {symbol} because no executable long trade survived the frame."
            next_best = "Keep observing until fresh market truth, NetEdge, risk, and broker boundary evidence align."

        missing_truth = [
            item["source"]
            for item in blockers
            if item["reason"] in {"MISSING_TRUTH", "STALE"} or "MISSING" in item["reason"] or "STALE" in item["reason"]
        ]
        evidence = [
            {
                "module": str(row.get("module_name") or "unknown_module"),
                "authority": str(row.get("authority_class") or "UNKNOWN"),
                "status": str(row.get("status") or "UNKNOWN"),
                "signal": str(row.get("signal") or "NONE"),
                "reason_codes": tuple(str(code) for code in row.get("reason_codes") or ()),
            }
            for row in rows
        ]
        return {
            "source": "DECISIONFRAME_SUMMARY",
            "frame_id": _frame_id(frame),
            "symbol": symbol,
            "headline": headline,
            "output": output,
            "netedge_result": _netedge(rows),
            "market_truth_state": "SEE_MODULE_EVIDENCE",
            "guardrail_risk_state": "SEE_MODULE_EVIDENCE",
            "broker_boundary_state": "SEE_MODULE_EVIDENCE",
            "evidence": evidence,
            "blockers": blockers,
            "reason_codes": tuple(reasons),
            "next_best_action": next_best,
            "confidence": "MEDIUM" if evidence else "LOW",
            "missing_truth": tuple(dict.fromkeys(missing_truth)),
            "scoring_changed": False,
        }
