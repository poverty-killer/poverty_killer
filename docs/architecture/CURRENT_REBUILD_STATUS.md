# POVERTY_KILLER Current Rebuild Status

Latest pushed master:
- f0bd38e - Add OpenCode Supreme Board governance
- a8ce4fa - Fix ToxicityEngine VPIN notional buckets
- f192725 - Relax SignalFusion noncritical input vetoes

Current stage:
- Core active runtime spine exists.
- Advanced modules are intentional pre-integration assets.
- Full quant engine integration is not complete.
- Live-money mode is not approved.

Active spine:
main.py -> app/main_loop.py -> app/core/decision_compiler.py -> app/execution/engine.py -> app/execution/order_router.py -> app/execution/paper_broker.py

Board doctrine:
- Every repo file is presumed intentional until repo truth proves otherwise.
- Unwired does not mean junk.
- Untracked does not mean junk.
- Dirty does not mean junk.
- Dormant does not mean useless.
- Work must be seam-based, not isolated bug-fix driven.
- Context spine gives direction; repo truth gives proof.
- Exact-file staging only.
- No live mode.
