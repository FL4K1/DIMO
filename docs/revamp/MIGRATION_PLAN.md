# Safe migration plan

Each phase is bounded, independently testable and reversible. Mark-LV remains the parent behavior; DIMO capabilities enter as additions. Deletion or merging is **not approved** without runtime/test evidence and review.

## Phase 0 — Establish behavioral baseline

- **Scope:** Add characterization notes and safe startup/registry/provider smoke checks; document supported entry points, provider modes, UI/session, confirmation, undo, memory and dashboard behavior.
- **Likely owner:** Codex for harness/documentation; Opus review for safety coverage.
- **Test/reversal:** Checks run in disposable config/data directories and avoid external side effects. Revert only the new checks/docs if they prove unstable.
- **Exit:** Known manual checklist and captured pass/fail environment results; no product behavior change.

## Phase 1 — Define a narrow adapter contract

- **Scope:** Contract for one DIMO tool declaration and dispatch result flowing through Mark-LV's existing action/tool handling; explicit capability metadata for confirmation, undo and network use. Do not move all tools.
- **Likely owner:** Codex implementation, Opus architecture/safety review.
- **Test/reversal:** Contract fixture and one inert/local read-only example; disable adapter by config/feature gate and verify Mark-LV baseline remains.
- **Exit:** One DIMO capability visible/callable in Mark-LV and produces the expected result with unchanged native flows.

## Phase 2 — Integrate bounded DIMO tool groups

- **Scope:** Add tools in small groups through the adapter; start with read-only local or browser-independent tools. Preserve plugin registry and existing Mark-LV handlers.
- **Likely owner:** Codex for bounded wrappers; Opus for design review; Flash for inventory/metadata chores; Kilo for independent smoke checks.
- **Test/reversal:** Per-tool safe tests, schema validation, and feature-gated rollback. Side-effect tools stay excluded until their safeguards are demonstrated.
- **Exit:** Each group has an inventory entry, tests/manual checks, and rollback evidence.

## Phase 3 — Provider and local/offline policy

- **Scope:** Add local Ollama capability behind Mark-LV's model/request seam; explicitly define cloud opt-in/fallback per feature. Keep Gemini Live path available during trial.
- **Likely owner:** Opus for provider boundaries; Codex for adapter; Kilo for offline/network test matrix.
- **Test/reversal:** Offline run with local model, cloud disabled, cloud enabled as separate scenario; revert provider adapter switch without affecting UI/session.
- **Exit:** Verified data-flow policy and behavior for each declared model-backed feature.

## Phase 4 — Memory and dashboard compatibility

- **Scope:** Add shared memory operations through an interface while preserving existing stores; expose only approved capabilities to dashboard/mobile. No bulk migration in this phase.
- **Likely owner:** Opus for data/safety contract; Codex for interface; Kilo for auth, backup/restore and manual validation.
- **Test/reversal:** Copy-based roundtrip/search/forget tests; dashboard tests on local network and disposable accounts; gate new routes and restore from backup.
- **Exit:** Verified access controls and data roundtrip; migration decision remains separate.

## Deferred

Any deletion, rename, wholesale model/tool/memory consolidation, public API change, dependency upgrade, or root-entry default switch requires its own evidence-backed decision and compatibility plan. Similar names alone are insufficient evidence. No Phase 2+ implementation is started by this audit.
