# Phase B Module Truth Map Report

Date: 2026-07-09
Branch: master
Latest commit at scout: 44bbb30 phase A structural validation gate

## 1. VERDICT

- B1 Every module classified: PASS (399 modules classified exactly once).
- B2 No silent module: PASS (0 rows missing role/authority fields).
- B3 Duplicate authority surfaced: PASS (7 authorities named; 9 conflict seams logged for Phase C).

Truth-map file: reports/completion/PHASE_B_MODULE_TRUTH_MAP.md

## 2. FILES CHANGED

- CHECKPOINT_TRACKER.md
- reports/completion/PHASE_B_MODULE_TRUTH_MAP.md
- reports/completion/PHASE_B_REPORT.md

No live module code was rewritten in Phase B.

## 3. ROOT CAUSE / WHY THIS PHASE EXISTS

The repo contains a large set of valuable systems, but not all of them have a truthful current runtime role. Previous work left sophisticated modules in mixed states: active, importable-only, pre-integration, test-only, tombstoned, or explicitly rejected. Without a row-by-row map, later fixes can accidentally flatten modules, wire duplicate authority, or claim readiness from static import success alone.

## 4. SCOUT METHOD

- Re-read AGENTS.md v3, CHECKPOINT_TRACKER.md, latest handoff, and Phase A report before writing classification.
- Enumerated Python modules under app/scripts/tests/_repo_quarantine plus root entrypoints, PowerShell/VBS scripts, operator UI assets, and control/mode.txt.
- Built an AST import graph, text reference map, product-root reachability set, marker scan, and per-row classification table.
- Product roots used for static reachability: main, app.main_loop, app.api.operator_readonly_api, app.api.operator_paper_supervisor, scripts.supervise_bounded_paper.

## 5. RED-TEAM NOTE

The map could look complete while hiding silent modules if it only listed paths. To prevent that, every row carries purpose, callers, runtime status, classification, authority boundary, data source, output contract, tests, blockers, and integration plan. It could mislabel duplicate authority as fine if owner selection was implicit; the report names one Phase B owner per authority and separately lists contenders as Phase C blockers. It could mark real modules dead to avoid work; only quarantine/tombstone/explicit Board rejection can become PRESERVED-DEAD or REJECTED-PRESERVED.

## 6. MODULE INVENTORY COUNTS

- Total classified modules: 399
- WIRED: 292
- BLOCKED: 96
- PRESERVED-DEAD: 10
- REJECTED-PRESERVED: 1
- Untracked code/operator modules inventoried: 4

## 7. AUTHORITY OWNER MATRIX

| Authority | Phase B named owner | Contenders/duplicates | Phase C action |
| --- | --- | --- | --- |
| market truth | app.core.market_snapshot | app.core.truth_kernel; app.core.truth_reconciler; app.data.*; app.models.unified_market | MarketTruthSnapshot is the executable market snapshot owner; other modules must feed/reconcile, not replace executable truth. |
| risk gates | app.risk.pre_trade_guardrails | app.risk.guard; app.risk.unified_risk; app.risk.safety; app.risk.sovereign_execution_guard; app.risk.exposure_manager; app.risk.net_edge_governor; app.risk.stale_data_guard | Multiple guards can block, but Phase C must define the ordered risk verdict chain and final admission owner. |
| sizing | app.risk.position_sizing | app.execution.masking_layer; app.risk.exposure_manager; app.risk.sovereign_execution_guard; app.risk.cross_asset_risk_model | Sizing intent, masking, exposure capacity, and future cross-asset caps need explicit contributor boundaries. |
| broker/order lifecycle | app.execution.order_router | app.execution.broker_gateway; app.execution.alpaca_paper_adapter; app.execution.paper_broker; app.execution.oms_lifecycle; app.execution.orchestrator.PaperBroker | OrderRouter owns lifecycle; orchestrator duplicate is rejected; adapters/paper broker must remain subordinate. |
| portfolio/position truth | app.risk.exposure_manager | app.operator_portfolio.snapshot; app.core.truth_kernel; app.core.intelligence_portfolio_state_truth_spine; app.state.state_store; app.execution.order_router | Broker-confirmed truth, local state, exposure reservations, and UI snapshots are split; Phase C must define canonical synchronization. |
| AI advisory | app.ai_chief_operator.provider_gateway | app.ai_chief_operator.model_router; app.ai_chief_operator.provider_adapters; ui/operator-control-panel/app.js deterministic fallback text | ProviderGateway should own route truth; UI and adapters must not imply fake provider answers. |
| UI display | ui/operator-control-panel/app.js | app.api.operator_readonly_api; ui/operator-control-panel/mock-data.js; scripts/open_operator_console.ps1 | app.js owns rendering; API owns data truth; mock-data must remain labeled offline fixture only. |

## 8. DUPLICATE AUTHORITY CONFLICTS

| # | authority/seam | contender modules | why it matters |
| ---: | --- | --- | --- |
| 1 | market truth | app.core.truth_kernel; app.core.truth_reconciler; app.data.*; app.models.unified_market | MarketTruthSnapshot is the executable market snapshot owner; other modules must feed/reconcile, not replace executable truth. |
| 2 | risk gates | app.risk.guard; app.risk.unified_risk; app.risk.safety; app.risk.sovereign_execution_guard; app.risk.exposure_manager; app.risk.net_edge_governor; app.risk.stale_data_guard | Multiple guards can block, but Phase C must define the ordered risk verdict chain and final admission owner. |
| 3 | sizing | app.execution.masking_layer; app.risk.exposure_manager; app.risk.sovereign_execution_guard; app.risk.cross_asset_risk_model | Sizing intent, masking, exposure capacity, and future cross-asset caps need explicit contributor boundaries. |
| 4 | broker/order lifecycle | app.execution.broker_gateway; app.execution.alpaca_paper_adapter; app.execution.paper_broker; app.execution.oms_lifecycle; app.execution.orchestrator.PaperBroker | OrderRouter owns lifecycle; orchestrator duplicate is rejected; adapters/paper broker must remain subordinate. |
| 5 | portfolio/position truth | app.operator_portfolio.snapshot; app.core.truth_kernel; app.core.intelligence_portfolio_state_truth_spine; app.state.state_store; app.execution.order_router | Broker-confirmed truth, local state, exposure reservations, and UI snapshots are split; Phase C must define canonical synchronization. |
| 6 | AI advisory | app.ai_chief_operator.model_router; app.ai_chief_operator.provider_adapters; ui/operator-control-panel/app.js deterministic fallback text | ProviderGateway should own route truth; UI and adapters must not imply fake provider answers. |
| 7 | UI display | app.api.operator_readonly_api; ui/operator-control-panel/mock-data.js; scripts/open_operator_console.ps1 | app.js owns rendering; API owns data truth; mock-data must remain labeled offline fixture only. |
| 8 | execution spine | app.execution.orchestrator | Explicit Board-rejected duplicate execution/order/position owner; preserve only as reference. |
| 9 | namespace/model authority | app/models.py vs app/models/ package | Tombstone file is shadowed and preserved dead; package app.models is canonical public API. |

## 9. CLASSIFICATION POLICY

- No module was deleted, stubbed, flattened, or reclassified out of existence.
- Importable-only is not treated as PAPER readiness.
- Test-only source modules are BLOCKED unless they have a current product caller or an explicit lawful contract/fixture role.
- Pre-integration/passive/disconnected modules are BLOCKED, not dead, unless the repo explicitly says tombstone/quarantine/rejected.
- Unknown runtime behavior is carried as blocker text rather than guessed.

## 10. MODULE STATUS SUMMARY

The full per-module status is in the truth map. Top blocker codes:
- TEST_ONLY_STATIC_CALLER_NO_PRODUCT_CALLER: 39
- NO_PRODUCT_REACHABILITY_FROM_ACTIVE_ROOTS: 29
- PRE_INTEGRATION: 14
- NO_STATIC_CALLER_FOUND: 4
- NOT_WIRED: 3
- Placeholder/under-construction module cannot truthfully run as a completed component.: 3
- UNDER_CONSTRUCTION: 1
- DISCONNECTED_FROM_LIVE_SPINE: 1
- NO_CURRENT_RUNTIME_IMPACT: 1
- NOT_YET_INTEGRATED: 1
- ControlPlane artifact exists: 1
- but ControlPlane has no current product caller beyond tests.: 1

## 11. WHAT WORKS

- Phase A proof says root/intended pytest collection is clean, py_compile is clean, and import smoke is clean.
- The active runtime spine is visible: main.py -> app.main_loop -> ExecutionEngine -> OrderRouter, with app.execution.orchestrator explicitly rejected.
- The operator backend/UI exists as a local read-only/governed control plane: app.api.operator_readonly_api plus ui/operator-control-panel assets.
- AI Chief has provider gateway/adapters/settings and explicit advisory-only route truth surfaces.
- PAPER supervisor/launcher/audit scripts exist, but no PAPER run was authorized in this phase.

## 12. WHAT IS NOT WIRED / NOT WORKING

- 96 modules are not product-wired or are pre-integration/under-construction/test-only by static evidence.
- Risk authority is fragmented across pre_trade_guardrails, HybridRiskGuard, UnifiedRiskAuthority, SafetyGate, ExposureManager, NetEdgeGovernor, stale-data guards, and sovereign execution guard.
- Portfolio/position truth is split between broker read snapshots, ExposureManager, StateStore, TruthKernel, OrderRouter/PaperBroker, and intelligence truth spine.
- Market/instrument modeling has disconnected sophisticated modules (unified_market, instrument_profile, cross_asset_risk_model, opportunity_ranking) that cannot be silently discarded.
- World-awareness adapters are mostly catalog/pre-integration/non-live-attached; their advisory lane needs explicit provider/runtime wiring and compliance boundaries.
- Legacy/manual control-plane mode file exists but is not product-reachable from the active operator cockpit path.
- Several audit scripts are present as untracked code/operator modules; they are inventoried but not baseline-owned yet.
- The latest handoff still reports PAPER revalidation as blocked/partial because credential/source truth and final TCA/fee truth were not complete.

## 13. UNKNOWN / NEEDS RUNTIME

No row needed a fifth UNKNOWN classification. Where runtime behavior could not be proven from repo truth, the row is classified BLOCKED with blockers such as NO_STATIC_CALLER_FOUND, NO_PRODUCT_REACHABILITY_FROM_ACTIVE_ROOTS, TEST_ONLY_STATIC_CALLER_NO_PRODUCT_CALLER, PRE_INTEGRATION, or DISCONNECTED_FROM_LIVE_SPINE.

## 14. NO SILENT MODULE PROOF

Every row has a purpose and an authority boundary. Silent rows found: 0.

## 15. TESTS / CHECKS

- Phase A proof reused: pytest --collect-only clean, py_compile clean, import smoke clean.
- Phase B truth-map invariant check: PASS, 399 rows counted with WIRED 292 / BLOCKED 96 / PRESERVED-DEAD 10 / REJECTED-PRESERVED 1.
- Root pytest collection after Phase B docs: PASS, `1778 tests collected in 5.09s`.
- Warnings observed: existing Pydantic deprecation warnings during collection; no collection errors.

## 16. RUNTIME PROOF

No server, broker, PAPER run, live read, credential read, or browser runtime was started in Phase B. This was intentional: Phase B is an inventory/classification phase. Runtime status fields are static repo evidence plus Phase A import/collection proof, not broker proof.

## 17. SAFETY CONFIRMATION

No Sacred Law, gate, threshold, broker path, credential value, state file, log file, DB/runtime file, or live/PAPER execution behavior was changed. Duplicate authority was named, not consolidated by deletion. No secrets were read into reports.

## 18. LIMITATIONS

Static import reachability can miss dynamic imports, subprocess calls, and UI runtime branches. Rows therefore distinguish product-reachable, script-root, UI asset, test proof, importable-only, dead, and blocked states. Phase C must verify actual authority graph behavior with focused tests and runtime-safe endpoint probes.

## 19. EXACT STAGING RECOMMENDATION

Stage exactly these files only:

```text
CHECKPOINT_TRACKER.md
reports/completion/PHASE_B_MODULE_TRUTH_MAP.md
reports/completion/PHASE_B_REPORT.md
```

Do not stage state/*, logs, .operator_config, .operator_secrets, .pytest_tmp, AGENTS.prev.md, untracked audit scripts, untracked handoffs, or operator_perf reports in this commit.

## 20. NEXT PHASE PLAN

Phase C should convert this map into an authority graph: define the exact ordered chain for the seven authorities, wire blocked contributors under their owner without flattening them, remove duplicate final-decision paths by governance/wiring (not deletion), and add tests that prove each owner is unique and every contributor is audible.

## Current Dirty / Untracked List at Scout

```text
M reports/codex_handoff_latest.md
 M state/override_log.jsonl
 M state/risk_state.backup
 M state/risk_state.json
 M state/risk_state.tmp
 M state/session_journal.jsonl
?? .pytest_tmp/
?? AGENTS.prev.md
?? POVERTY_KILLER_AUDIT_REPORT.txt
?? reports/codex_handoff_2026-06-02_operator_truth_sync_ai_router.md
?? reports/codex_handoff_2026-06-07_final_ai_provider_truth.md
?? reports/codex_handoff_2026-06-12_operator_control_plane_fast_synced.md
?? reports/codex_handoff_2026-06-20_p3n_24h_final_360.md
?? reports/codex_handoff_2026-06-21_p3or_funded_revalidation_blocked.md
?? reports/codex_handoff_2026-06-21_pk_ui1_operator_cockpit_build.md
?? reports/completion/PHASE_B_MODULE_TRUTH_MAP.md
?? reports/completion/PHASE_B_REPORT.md
?? reports/operator_perf/
?? scripts/_paper_audit_common.py
?? scripts/audit_oms_shutdown.py
?? scripts/audit_paper_run.py
?? scripts/audit_safety_markers.py
warning: unable to access 'C:\Users\shahn/.config/git/ignore': Permission denied
warning: unable to access 'C:\Users\shahn/.config/git/ignore': Permission denied
```

## Latest Handoff / Phase A Evidence Read

- CHECKPOINT_TRACKER.md read: Phase A PASS, Phase B was NOT_STARTED before this work.
- reports/codex_handoff_latest.md read: latest handoff still reported PAPER revalidation partial/fail and credential/source/TCA gaps.
- reports/completion/PHASE_A_REPORT.md read: A1-A4 passed with 1778 root tests collected, py_compile clean, import smoke clean, unsafe quarantine excluded.
