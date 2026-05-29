# AI Quant Research Chief / Research OS Control Tower

This seam adds a practical advisory research layer around the operator system.

Implemented surfaces:

- AI Quant Research Chief persona and prompt guardrails.
- Provider Setup / Credential Readiness with env-var presence and masked
  fingerprints only.
- In-memory advisory Research Registry for hypotheses, experiments,
  recommendations, and promotion gates.
- Lightweight Evidence Graph linking run archive, DecisionFrame, MarketTruth,
  NetEdge/TCA, OMS, watchdog/action-center, and provider readiness summaries.
- Operator API endpoints for provider readiness, research registry, evidence
  graph, quant review, and Codex packet drafting.
- UI panels for Provider Setup and Research OS.

Safety constraints:

- No broker, execution, OMS, strategy, alpha, scoring, or threshold changes.
- No live or real-money controls.
- No automatic PAPER start from AI or research approvals.
- No real provider network calls in tests.
- No raw credentials, API keys, tokens, passwords, or raw logs in payloads.
- AI recommendations remain advisory with `can_execute=false`.

This is a foundation, not a full research institution. Backtest engines,
model registries, overfit analytics, replay depth, and live-readiness promotion
remain future governed packets.
