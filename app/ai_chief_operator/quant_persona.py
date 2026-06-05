"""Quant-scoped advisory persona for AI Chief Operator."""

from __future__ import annotations

from typing import Any


AI_QUANT_IDENTITY = (
    "Chief Quant Advisor + Quant Engineer + Trading Systems Auditor + Trading Strategist + "
    "Market Research Chief + Risk Officer + Execution/TCA Auditor + Operator Guide"
)

AI_QUANT_ROLES = (
    "Chief Quant Advisor",
    "Quant Engineer",
    "Trading Systems Auditor",
    "Trading Strategist",
    "Market Research Chief",
    "Risk Officer",
    "Execution/TCA Auditor",
    "Operator Guide",
    "Run Planner",
    "Portfolio Reviewer",
    "Codex Packet Advisor",
)

AI_SYSTEM_POLICY = (
    "You are the Chief Quant Advisor, Quant Engineer, Trading Systems Auditor, Trading Strategist, Market Research Chief, "
    "Risk Officer, Execution/TCA Auditor, and Operator Guide for POVERTY_KILLER. "
    "You are not a general chatbot. Your job is to help Shan operate and improve this trading engine, interpret "
    "portfolio/risk/P&L/execution evidence, critique strategy validity, identify missing proof, design safe PAPER "
    "validation plans, and guide safe operation. Use expert-level quantitative trading, financial, market-structure, "
    "execution, risk, analytical, logical, and systems reasoning. Explain clearly to a non-coder operator without "
    "dumbing down the analysis. You cannot trade, call broker, enable live, expose secrets, mutate strategy, or bypass "
    "safety gates. You must separate broker-confirmed truth, market truth, local engine state, model inference, missing "
    "evidence, and speculation."
)

QUANT_PROMPTS = (
    "Where is the edge?",
    "What is the weakest assumption?",
    "Is this signal statistically believable?",
    "What would invalidate this strategy?",
    "What is the safest next PAPER experiment?",
    "Where are fees/slippage hurting us?",
    "What evidence blocks live readiness?",
    "Critique latest run.",
    "Compare latest run to expected behavior.",
    "Draft a Codex packet.",
    "Review provider/data readiness.",
)

DOMAIN_TERMS = (
    "trade",
    "trading",
    "quant",
    "edge",
    "alpha",
    "strategy",
    "risk",
    "tca",
    "netedge",
    "fee",
    "fill",
    "slippage",
    "market",
    "decisionframe",
    "paper",
    "live readiness",
    "broker",
    "execution",
    "oms",
    "provider",
    "data",
    "codex",
    "run",
    "assumption",
    "statistical",
    "validation",
    "evidence",
    "readiness",
    "blocker",
    "blocking",
    "bot",
    "p&l",
    "profit",
)

FORBIDDEN_TERMS = (
    "place a trade",
    "submit order",
    "cancel order",
    "liquidate",
    "enable live",
    "turn on live",
    "start live",
    "enable real money",
    "real-money",
    "bypass",
    "ignore guardrail",
    "lower threshold",
    "change threshold",
    "api key",
    "password",
    "secret",
    "guarantee profit",
    "guaranteed profit",
)

MODE_KEYWORDS = {
    "SETUP_HELP": (
        "alpaca key",
        "alpaca missing",
        "openai configured",
        "credential",
        "local credential vault",
        "provider",
        "launcher",
        "backend",
        "setup",
        "where do i enter",
    ),
    "PORTFOLIO_REVIEW": (
        "own",
        "position",
        "portfolio",
        "exposure",
        "concentrated",
        "p&l",
        "pnl",
        "open order",
        "riskiest",
        "holding",
    ),
    "RUN_PLANNER": (
        "7-day",
        "7 day",
        "paper run",
        "start paper",
        "can i start paper",
        "duration",
        "watchlist",
        "stop condition",
        "monitor",
        "run plan",
        "sunday",
    ),
    "CODEX_PACKET_ADVISOR": (
        "codex",
        "supreme board",
        "packet",
        "ask codex",
        "fix",
        "code issue",
    ),
    "TRADING_SYSTEMS_AUDITOR": (
        "audit",
        "readiness",
        "blocked",
        "blocking",
        "blocker",
        "what is blocking",
        "blocking the bot",
        "broker truth",
        "market truth",
        "netedge",
        "oms",
        "reconciliation",
        "stale",
        "mutation",
        "safety gate",
    ),
    "QUANT_ENGINEER": (
        "architecture",
        "data flow",
        "strategy module",
        "execution plumbing",
        "system behavior",
        "engine",
        "wiring",
    ),
    "QUANT_ADVISOR": (
        "edge",
        "alpha",
        "strategy",
        "statistically",
        "overfit",
        "noise",
        "market structure",
        "signal",
        "regime",
        "hypothesis",
        "invalidate",
        "assumption",
    ),
    "OPERATOR_GUIDE": (
        "explain this page",
        "what do i do next",
        "what page",
        "what does this button",
        "warning mean",
        "not a coder",
        "how do i",
        "are you alive",
        "operator status",
        "operator launch status",
        "launch status",
        "current operator",
    ),
}


def quant_persona_summary() -> dict[str, Any]:
    return {
        "identity": AI_QUANT_IDENTITY,
        "system_policy": AI_SYSTEM_POLICY,
        "roles": list(AI_QUANT_ROLES),
        "mission": [
            "find edge",
            "decode strategy behavior",
            "attack weak assumptions",
            "identify overfit and fake-alpha risk",
            "review NetEdge, TCA, fees, fills, slippage, risk, market truth, and execution quality",
            "stress-test market structure, strategy design, signal decay, concentration, drawdown, and execution gap assumptions",
            "recommend safest next PAPER experiment",
            "draft Codex packets",
            "advise Shan only",
        ],
        "cannot": [
            "trade",
            "start PAPER automatically",
            "start live",
            "enable real money",
            "call broker",
            "submit/cancel/liquidate orders",
            "modify strategy/alpha/scoring/thresholds",
            "access or expose secrets",
            "read raw logs",
        ],
        "advisory_only": True,
        "can_execute": False,
        "broker_call_occurred": False,
        "trading_mutation_occurred": False,
        "secrets_values_exposed": False,
    }


def classify_ai_mode(prompt: str, *, page_id: str | None = None) -> str:
    lowered = str(prompt or "").strip().lower()
    page = str(page_id or "").strip().lower()
    for mode, keywords in MODE_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return mode
    if page in {"positions", "portfolio"}:
        return "PORTFOLIO_REVIEW"
    if page in {"command", "activity"}:
        return "RUN_PLANNER" if "paper" in lowered or "run" in lowered else "OPERATOR_GUIDE"
    if page in {"providers", "diagnostics"}:
        return "SETUP_HELP"
    if page in {"ai", "system"}:
        return "CODEX_PACKET_ADVISOR" if "codex" in lowered or "packet" in lowered else "OPERATOR_GUIDE"
    if page in {"risk", "pnl", "decision", "research"}:
        return "TRADING_SYSTEMS_AUDITOR" if "audit" in lowered or "readiness" in lowered else "QUANT_ADVISOR"
    return "OPERATOR_GUIDE" if lowered in {"", "explain this page", "what do i do next"} else "QUANT_ADVISOR"


def evidence_level_for_mode(mode: str) -> str:
    if mode == "PORTFOLIO_REVIEW":
        return "BROKER_CONFIRMED"
    if mode in {"QUANT_ADVISOR", "RUN_PLANNER", "CODEX_PACKET_ADVISOR"}:
        return "MISSING_EVIDENCE"
    if mode in {"TRADING_SYSTEMS_AUDITOR", "QUANT_ENGINEER", "SETUP_HELP", "OPERATOR_GUIDE"}:
        return "SYSTEM_STATE"
    return "UNKNOWN"


def classify_quant_prompt(prompt: str, *, page_id: str | None = None) -> dict[str, Any]:
    text = str(prompt or "").strip()
    lowered = text.lower()
    forbidden = [term for term in FORBIDDEN_TERMS if term in lowered]
    operator_phrases = (
        "explain this page",
        "what do i do next",
        "what page",
        "button",
        "warning",
        "where do i enter",
        "are you alive",
        "operator status",
        "operator launch status",
        "launch status",
        "current operator",
        "what is blocking",
        "current blocker",
        "blocking the bot",
    )
    mode_terms = tuple(term for keywords in MODE_KEYWORDS.values() for term in keywords)
    in_domain = (
        any(term in lowered for term in DOMAIN_TERMS)
        or any(term in lowered for term in operator_phrases)
        or any(term in lowered for term in mode_terms)
        or not text
    )
    mode = "UNSAFE_REQUEST_REFUSAL" if forbidden else classify_ai_mode(text, page_id=page_id)
    if forbidden:
        return {
            "allowed": False,
            "reason_code": "FORBIDDEN_TRADING_OR_SECRET_REQUEST",
            "matched_terms": forbidden,
            "mode": mode,
            "evidence_level": "SYSTEM_STATE",
        }
    if not in_domain:
        return {
            "allowed": False,
            "reason_code": "NON_TRADING_GENERALIST_PROMPT",
            "matched_terms": [],
            "mode": "OPERATOR_GUIDE",
            "evidence_level": "UNKNOWN",
        }
    return {
        "allowed": True,
        "reason_code": "QUANT_RESEARCH_PROMPT_ACCEPTED",
        "matched_terms": [],
        "mode": mode,
        "evidence_level": evidence_level_for_mode(mode),
    }


def build_quant_review_recommendation(prompt: str, context: dict[str, Any]) -> dict[str, Any]:
    classification = classify_quant_prompt(prompt)
    if not classification["allowed"]:
        return {
            "recommendation_type": "OBSERVATION",
            "summary": "Prompt refused or redirected. AI Quant Research Chief only handles trading edge, execution quality, risk, validation evidence, and operator readiness.",
            "evidence": [classification["reason_code"]],
            "risks": ["Out-of-domain or unsafe prompt should not receive trading-system authority."],
            "uncertainty": ["No model or broker call was made."],
            "proposed_action": "ASK_TRADING_RESEARCH_OR_OPERATOR_READINESS_QUESTION",
            "can_execute": False,
            "status": "REJECTED",
            "refusal_reason": classification["reason_code"],
        }

    evidence_graph = context.get("evidence_graph") or {}
    missing = evidence_graph.get("missing_evidence") or []
    providers = context.get("provider_readiness") or {}
    research = context.get("research_registry") or {}
    prompt_text = str(prompt or "Review operator state as Quant Research Chief.")
    return {
        "recommendation_type": "PAPER_EXPERIMENT_PROPOSAL" if "paper" in prompt_text.lower() else "STRATEGY_REVIEW",
        "summary": (
            f"{AI_QUANT_IDENTITY} review queued for: {prompt_text}. "
            "Focus on edge quality, overfit risk, NetEdge/TCA evidence, provider readiness, and safest next research step."
        ),
        "evidence": [
            f"missing_evidence={len(missing)}",
            f"provider_count={providers.get('provider_count', 0)}",
            f"research_items={(research.get('counts') or {}).get('hypotheses', 0)} hypotheses",
        ],
        "risks": [
            "Unknown broker-confirmed P&L/TCA must remain unknown.",
            "Backtest/replay validation is required before promotion.",
            "PAPER proposals require Shan approval and do not start automatically.",
        ],
        "uncertainty": [str(item) for item in missing[:6]] or ["Runtime evidence may be incomplete."],
        "proposed_action": "CREATE_RESEARCH_REVIEW_ITEM",
        "can_execute": False,
        "status": "PENDING_REVIEW",
    }


def draft_codex_packet(prompt: str, context: dict[str, Any]) -> dict[str, Any]:
    classification = classify_quant_prompt(prompt or "Draft a Codex packet for quant research.")
    if not classification["allowed"]:
        return build_quant_review_recommendation(prompt, context)
    evidence_graph = context.get("evidence_graph") or {}
    title = "POVERTY_KILLER — GOVERNED QUANT RESEARCH PACKET"
    body = "\n".join(
        [
            title,
            "",
            "Purpose: investigate a trading edge or operator-readiness question without changing broker/execution/OMS/strategy behavior.",
            "",
            "Allowed: read-only research, evidence graph review, provider readiness review, backtest/replay proposal, PAPER experiment design requiring Shan approval.",
            "",
            "Forbidden: live, real money, broker calls, order submit/cancel/liquidate, threshold changes, raw logs, secrets.",
            "",
            f"Question: {prompt or 'Quant research review'}",
            f"Known missing evidence: {', '.join((evidence_graph.get('missing_evidence') or [])[:8]) or 'none loaded'}",
            "",
            "Acceptance: advisory recommendation only, can_execute=false, no runtime started.",
        ]
    )
    return {
        "recommendation_type": "STRATEGY_REVIEW",
        "summary": "Draft Codex packet prepared for governed quant research review.",
        "evidence": ["DRAFT_CODEX_PACKET", f"context_version={context.get('context_version', 'unknown')}"],
        "risks": ["Packet must be reviewed before any code changes.", "PAPER experiments require Shan approval."],
        "uncertainty": [str(item) for item in (evidence_graph.get("missing_evidence") or [])[:6]],
        "proposed_action": "REVIEW_DRAFT_CODEX_PACKET",
        "can_execute": False,
        "status": "PENDING_REVIEW",
        "draft_packet": body,
    }
