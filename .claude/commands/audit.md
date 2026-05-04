# /audit - Repo Assimilation Mode

Activates Mode A from the claude.md constitution. Produces a full repo
inventory and liveness classification. Does not patch.

Required output:

AUDIT_REPORT

repo_map: yes / no
import_map_produced: yes / no
wiring_map_produced: yes / no

For each module discovered:

  module: <path>
  liveness: LIVE / PARTIAL / DISCONNECTED / DEAD / DUPLICATE_AUTHORITY / UNKNOWN
  authority_domain: <signal / risk / execution / sizing / fusion / routing / telemetry / support / none>
  caller_count: <number or UNKNOWN>
  consumer_count: <number or UNKNOWN>
  protected_differentiator: yes / no
  notes: <brief>

Protected differentiators (must be classified, not skipped):
- app/brain/shans_curve.py
- app/brain/entropy_decoder.py
- app/brain/regime_detector.py
- app/brain/whale_flow_engine.py
- app/brain/whale_zone_engine.py
- app/brain/signal_fusion.py
- app/strategies/strategy_router.py
- app/strategies/moving_floor.py
- app/risk/net_edge_governor.py
- app/risk/trade_efficiency_governor.py

Differentiator classification must use:
REAL / REAL_BUT_DISCONNECTED / PARTIAL / FAKE_INTEGRATED / BROKEN / STUB / DEFERRED / RETIRED

Duplicate authority candidates:
List any two modules that appear to own the same domain authority.
If found: BOARD_ESCALATION: DUPLICATE_AUTHORITY_CANDIDATE

End of audit:

next_bundle_recommendation: <bundle name and objective>
board_escalations: <list or NONE>
