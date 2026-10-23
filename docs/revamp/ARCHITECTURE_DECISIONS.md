# Architecture decisions and open questions

At most five decisions are listed. Recommendations preserve Mark-LV's behavior and treat DIMO as an addition. Recommendations are not approval to remove code.

## 1. What is the supported product entry point?

- **Options:** Keep `python main.py` as Mark-LV and make DIMO capabilities adapters inside its request/tool system; expose DIMO CLI as an explicit secondary entry; or change the default to DIMO graph.
- **Evidence:** Root `main()` dispatches to `app.marklv.main.main()`. DIMO text/voice functions remain in root `main.py` but are not selected there.
- **Pros/cons:** Mark-LV parent integration preserves the shipped UI/session path; a separate CLI supports incremental validation but leaves two entry points; changing default risks dropping GUI, phone dashboard, Gemini Live and config behavior.
- **Risk:** High user-visible startup and state migration risk.
- **Recommendation:** Keep Mark-LV as primary and document a deliberate DIMO adapter or explicit secondary entry after a supported invocation is agreed. Unknown: whether the DIMO CLI is intentionally retained.

## 2. Where should model routing live?

- **Options:** Keep provider choice in Mark-LV config/client; adapt DIMO gateway as a provider behind Mark-LV; or move product requests to DIMO's router/graph.
- **Evidence:** Mark-LV has Gemini Live model ladder and configured AI engine paths; DIMO has router/planner/loop with Ollama defaults and gateway Gemini dispatch.
- **Pros/cons:** Provider adapter can preserve current session/UI while adding local models; a graph takeover gives consistent planning but changes routing and response behavior.
- **Risk:** High privacy, availability, latency, and prompt behavior risk. Cloud fallback is feature-dependent and not fully enumerated.
- **Recommendation:** Specify a small provider/request adapter contract, then prove local-only and cloud behavior before changing the default. Unknown: desired routing policy per feature.

## 3. Which action/tool contract is authoritative?

- **Options:** Mark-LV inline + `TOOL` action + `PLUGIN` contract; DIMO `TOOL_CATALOG`; or a compatibility adapter that translates DIMO catalog entries into Mark-LV declarations/dispatch.
- **Evidence:** Mark-LV dynamically discovers files from `actions/` and `plugins/`; DIMO registry statically imports wrappers and browser catalogs. The DIMO safety bridges use Mark-LV confirmation and undo.
- **Pros/cons:** Adapter preserves plugin ecosystem and UI settings but needs schema/result compatibility; replacing registries risks losing dynamically installed tools and semantics.
- **Risk:** High, because the dispatch path can execute file, messaging, system and browser operations.
- **Recommendation:** Keep Mark-LV dispatch authoritative and prototype one low-risk DIMO tool through an adapter. Unknown: complete overlap and behavior equivalence.

## 4. How should memory be unified?

- **Options:** Keep separate stores; bridge through a common interface while retaining files; or migrate DIMO facts/session context into Mark-LV JSON.
- **Evidence:** Mark-LV memory manager supports prompt formatting, search, UI, and session summaries; DIMO has a separate JSON manager and LLM extraction.
- **Pros/cons:** Interface bridge can preserve current data/UI; migration risks category, ordering, extraction, and privacy changes. DIMO extraction may use Gemini/Ollama; provider choice is not equivalent to Mark-LV flow.
- **Risk:** High data loss/privacy risk; unknown schema compatibility and actual populated state.
- **Recommendation:** Define read/write/forget contract and test on copied data before any migration. No store is approved for deletion.

## 5. What safety and remote access contract must adapters preserve?

- **Options:** Reuse Mark-LV confirmation/undo; add equivalent DIMO gates; or centralize policy behind shared interfaces before adapter integration.
- **Evidence:** `core.confirm` uses UI-issued tokens; undo is opt-in. DIMO system wrapper bridges confirmation; DIMO file wrapper bridges undo only for create operations. Dashboard exposes login/device and command/websocket routes.
- **Pros/cons:** Reuse minimizes divergence but couples DIMO to Mark-LV import setup; new gates avoid coupling but risk policy mismatch; central interface offers consistent policy with upfront contract work.
- **Risk:** Critical for destructive/system/messaging actions and remote commands.
- **Recommendation:** Preserve the Mark-LV token gate and add explicit per-tool reversibility metadata before broad integration. Validate LAN/TLS/login behavior before exposing new tools remotely. Unknown: all routes' authorization matrix and full undo coverage.
