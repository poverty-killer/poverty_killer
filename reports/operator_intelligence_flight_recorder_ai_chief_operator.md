# Operator Intelligence / Flight Recorder / AI Chief Operator Seam

This seam adds operator-facing intelligence without changing trading behavior.

Implemented surfaces:

- Run Archive / Flight Recorder from operator session metadata and referenced
  runtime logs.
- Persistent run report generation under runtime report directories.
- Decision explainer for DecisionFrame-shaped evidence.
- Action Center aggregation of readiness, storage, fee, World Awareness,
  watchdog, and AI review states.
- Honest P&L/TCA dashboard summaries that preserve unknown values.
- Safe local watchdog alert model with no external delivery.
- Codebase/system map explainer for the operator.
- AI Chief provider gateway, context redaction, advisory recommendation schema,
  and governance queue.

Safety constraints:

- No live endpoint.
- No real-money mode.
- No AI direct broker calls.
- No AI order submission, cancel, liquidate, or force-trade controls.
- No strategy, alpha, threshold, broker, OMS, or execution behavior changes.
- No fake broker truth, fills, fees, P&L, or TCA.
- No secrets in prompts, logs, or API responses.

The expected acceptance state is `CONDITIONAL_PASS` when some live runtime
telemetry is unavailable, because unknown evidence remains explicitly unknown.
