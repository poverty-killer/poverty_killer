# Poverty Killer System Map - Operator Explainer

## Runtime Launcher
The governed local launcher starts only the operator API/UI. Bounded PAPER runs
are started by server-side operator intents through the PAPER supervisor.

## MarketTruthSnapshot
MarketTruthSnapshot is the executable market-data authority. Stale, synthetic,
backfill, replay, mismatched, or missing truth must remain non-executable.

## DecisionFrame
DecisionFrame records why a BUY, SELL, or NO_TRADE decision emerged from the
current evidence. Operator explainers may summarize it, but must not change
scores, thresholds, or routing behavior.

## NetEdge
NetEdge is an economic gate. Operator dashboards can report whether realized vs
modeled evidence is available, but cannot relax economic thresholds.

## ExecutionEngine
ExecutionEngine is not an operator UI dependency. This seam does not import or
modify it; broker mutation remains outside read-only operator intelligence.

## BrokerBoundary
BrokerBoundary is the broker authority layer. AI, UI, reports, and explainers
cannot call it directly or submit/cancel/liquidate orders.

## OMS
OMS owns order lifecycle truth and shutdown reconciliation. The operator surface
may display summaries and conflicts, never rewrite OMS state.

## Fill / TCA / Fee Hydration
Fill, TCA, and broker fee hydration are evidence streams. Unknown fee, P&L, and
TCA values stay unknown until broker-confirmed or existing runtime evidence is
available.

## Operator API
The supported API path is `/operator/*`. It is read-only except governed PAPER
process intents and advisory queues explicitly modeled as safe local state.

## Supervisor
The PAPER supervisor tracks bounded local PAPER processes, duplicate-run
prevention, log paths, session metadata, and audit events.

## UI
The operator control panel displays source labels, truth labels, run archive,
action center, watchdog alerts, AI recommendations, and live lock status. It has
no manual trade, force trade, or live start controls.

## World Awareness
World Awareness is advisory only. It cannot bypass MarketTruthSnapshot, NetEdge,
risk guardrails, BrokerBoundary, OMS, or hard gates.

## AI Chief Operator
AI Chief is advisory only. Providers are disabled by default or mock-only in
tests. Recommendations require Shan review and cannot execute trading actions.

## Live Readiness Gates
Live is locked. Real-money mode is blocked. Any future live readiness requires a
separate governance packet and evidence bundle.

## Safe To Touch
Read-only operator summaries, UI display contracts, reports, tests, local alert
queues, advisory AI context, and governance queue metadata are safe touch zones
when governed.

## Must Not Touch
Do not touch broker adapters, execution mutation paths, OMS internals, strategy
or alpha behavior, thresholds, live endpoints, real-money controls, secrets,
runtime logs/state/DB files, or quarantined dashboard code without explicit
Board authorization.
