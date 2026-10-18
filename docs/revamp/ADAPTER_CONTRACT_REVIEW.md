# Phase 1 — Adapter architecture review

**Review type:** Read-only source review. This document is the only proposed change in this review; no production source was edited.

## Working tree snapshot

- Branch: `revamp/marklv-parent-dimo-integration`.
- `HEAD`: `44af2c11aceaf85d3a17e7eb5d07aea743b05245` (`fix: fail closed on unconfirmed system actions`). The branch status showed no ahead/behind count against its configured upstream.
- No staged or tracked working-tree diffs were present in the reviewed files.
- Existing untracked items at review start were left untouched: `app/marklv/config/certs/jarvis-ca.cer`, `app/marklv/config/certs/jarvis-ca.crt`, `app/marklv/config/certs/jarvis-ca.key`, `docs/revamp/GRAPH_INTEGRATION_READINESS.md`, and an oddly named untracked filesystem entry shown by Git as `e DIMO browser tab listing in Mark-LV•`. The certificate contents were not read.
- The user's statements about the previous confirmation suite and live prompt check are treated as supplied context; not independently re-run or verified here.

## Source-backed findings

### Mark-LV's action contract is the appropriate host seam

- `app/marklv/main.py` creates `ActionRegistry` once in `JarvisLive.__init__` by scanning `app/marklv/actions/*.py`. Inline tool names are reserved. The union of inline and discovered action names is then reserved against plugins.
- `app/marklv/core/action_loader.py` discovers a module only when it has module-level `TOOL`; it validates a Python identifier name, non-empty description, top-level `{"type": "OBJECT"}` parameters and callable handler. It does **not** deeply validate JSON Schema, preserve arbitrary metadata, or apply policy based on risk/side effects.
- At live-session setup, Mark-LV combines inline declarations, discovered action declarations and plugin declarations into one model tool list. `ActionRegistry.run()` calls the handler with `parameters` and only declared context arguments (`player`, `speak`, `response`, `session_memory`). `main.py` routes action names to that registry and returns the handler's string as `FunctionResponse.response["result"]`.
- Name collisions against inline names and earlier discovered actions are rejected. An action file's presence with valid `TOOL` makes it eligible for disclosure at the next startup; there is no existing per-action enabled setting in `ActionRegistry`.
- The existing `app/marklv/actions/dimo_browser_list_tabs.py` is one allowlisted capability in practice. It declares only `dimo_browser_list_tabs`, has an empty input schema, and lazily calls `app.browser.tabs.list_open_tabs()`. This is much narrower than exposing DIMO's general catalog.
- That action currently inserts the repository root at index 0 in process-wide `sys.path` if absent. It catches import/other exceptions and returns strings. It logs a generic action message, but its output includes page titles and URLs.

### DIMO's catalog is too broad to expose directly

- `app/tools/registry.py` statically imports native DIMO tools and merges several browser catalogs into global `TOOL_CATALOG` (tabs, clipboard, browser search, YouTube music, WhatsApp, and Gemini browser actions). `get_tool(name)` returns any catalog function and `get_tool_schema_text()` describes the whole catalog.
- `app/nodes/loop.py` validates model/planner tool names against that full catalog and dispatches through `get_tool()`. The catalog includes tools with network use, external messaging, filesystem/system side effects and general browser interaction. It is the DIMO graph's execution registry, not a safe Mark-LV allowlist.
- DIMO schemas use lower-case JSON Schema type strings (`object`, `string`, etc.); Mark-LV's current action declarations use Gemini-style upper-case types (`OBJECT`, `STRING`, `INTEGER`, etc.). The current `dimo_browser_list_tabs` has no parameters, so its first bridge does not need a schema conversion.
- DIMO tool functions frequently return strings for both success and failure, for example `list_open_tabs()` returns `"No open tabs."`, `"playwright not installed"`, or `"Could not list tabs: ..."`. Those strings are not typed results. Mark-LV then wraps any handler string as a `result`; status cannot reliably be inferred without a typed DIMO result API.

### The two browser managers do not share a session by source design

- DIMO `app/browser/browser_manager.py` owns a module-level synchronous Playwright `BrowserManager` singleton. It launches a persistent Chromium context in `CHROMIUM_PROFILE_DIR`, defaulting to `~/.dimo/chromium_profile`, and exposes that context's pages through `list_pages()`. It returns an empty list if its context is not alive; `list_open_tabs()` does not itself launch the browser.
- Mark-LV `app/marklv/actions/browser_control.py` owns a separate `_SessionRegistry` singleton of `_BrowserSession` instances, one per browser name. Its interactive sessions use async Playwright and persistent profiles, generally targeting the user's real Chrome/Edge/Firefox/etc. profile or a Mark-LV fallback profile. Its `browser_control` action supports navigation, clicks, typing, screenshots, tab closing, session switching and closing sessions.
- The DIMO action calls the DIMO module-level manager directly; it does not query Mark-LV's `_SessionRegistry`, connect to an existing native browser, or inspect Mark-LV's active page. Distinct manager objects, Playwright APIs, profile selection, and session registries mean there is no source evidence of a shared browser context or shared tab list. Do not promise cross-manager tab visibility.
- Importing `app.browser.browser_manager` loads dotenv and the optional Playwright sync API, but actual Chromium launch is deferred until page access. Listing tabs on an unstarted manager returns no pages.

### Local execution does not mean local-only request data

`list_open_tabs()` is a local browser-context read and does not navigate or mutate tabs. The resulting titles and URLs are handed back as a tool result in Mark-LV's active model session. In the current product path that model session may be Gemini Live/cloud. Thus `execution_network=none` can be true while `end_to_end_local_only=false` or provider-dependent; browser URLs may be sent to the model provider. This is a meaningful privacy risk, even for a read-only capability.

## Recommendation: reusable, explicit allowlisted adapter with thin action modules

Use a small DIMO adapter helper plus one Mark-LV action module per exposed capability. Do not register or enumerate `TOOL_CATALOG`, and do not create a generic model-callable `dimo_tool(name, args)` action.

Why this shape:

1. Mark-LV's existing action discovery remains authoritative and automatically adds a selected action to the established model declarations and dispatch path.
2. A helper can centralize allowlist checks, argument checks, result/error conversion, and metadata policy once more than one DIMO capability is approved.
3. Each discovered wrapper remains an explicit reviewable boundary with a stable `dimo_*` public name, bounded schema, and selected function. The model cannot choose an arbitrary DIMO catalog name.
4. The first implementation should still be tiny: keep the already present tab-list action as the only entry, route it through the helper, and do not touch Mark-LV startup, `ActionRegistry`, provider routing, browser managers, or DIMO's full tool registry.

### Proposed internal interface

```python
@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str            # fixed internal key, e.g. "browser.list_tabs"
    public_name: str               # Mark-LV model tool, e.g. "dimo_browser_list_tabs"
    description: str
    parameters: dict                # validated against the supported schema subset
    invoke: Callable[[dict], CapabilityOutcome]
    risk: Literal["low", "moderate", "high", "critical"]
    side_effects: tuple[str, ...]
    execution_network: Literal["none", "optional", "required"]
    execution_local_only: bool
    result_sensitivity: Literal["public", "personal", "sensitive"]
    model_egress: Literal["none", "local_provider", "cloud_provider", "provider_dependent"]
    confirmation: Literal["none", "marklv_ui"]
    reversibility: Literal["not_applicable", "undo", "partial", "irreversible", "unknown"]

@dataclass(frozen=True)
class CapabilityOutcome:
    ok: bool
    text: str
    error_code: str | None = None
```

Expose only an immutable, source-reviewed mapping from a short capability ID to a spec/function. The action wrapper supplies its fixed ID; model arguments never contain the ID. The adapter verifies that the ID is allowlisted, rejects unknown arguments and unsupported schema features, invokes only that spec, and returns `outcome.text` as the Mark-LV action string. If `ok` is false, render a bounded, non-secret error string with the code; do not feed raw exception text or stack traces to the model. Log a safe error code and correlation/action name without arguments, page URLs, credentials, or output text.

For the current DIMO API, which returns strings, preserve the text as-is for the first proof slice and classify thrown exceptions as adapter errors. Treat legacy strings such as `"playwright not installed"` as opaque text, not a reliable machine-level error status. Before adding more capabilities or branching on success/failure, add a typed DIMO result method while retaining the existing string API for DIMO callers. Do not parse free-form error prefixes as the long-term contract.

### Tool contract translation

- **Names:** Keep the existing `dimo_browser_list_tabs`; require a `dimo_` prefix for future adapters and collision-check through Mark-LV's existing `reserved_names`/duplicate checks. Internal capability IDs never appear in model declarations.
- **Schemas:** The wrapper owns the public Mark-LV Gemini schema. Convert only an explicit supported subset from DIMO lower-case types to Mark-LV upper-case types (`object→OBJECT`, `string→STRING`, `integer→INTEGER`, `number→NUMBER`, `boolean→BOOLEAN`, `array→ARRAY`). Recursively validate properties/required/enum as implemented; reject unknown schema keys/types instead of forwarding arbitrary schemas. Empty-object schema remains empty for tab listing. Deep validation is adapter-side because `ActionRegistry._validate()` checks only top-level shape.
- **Arguments:** Accept only a dict; validate required, declared and typed properties against the spec before invocation. Reject unknown fields (even though action-loader discovery currently does not validate call args). The current action accepts no arguments, so `{}` is valid and any supplied key should fail closed.
- **Results:** Keep Mark-LV's existing `FunctionResponse` shape `{"result": <string>}`. A typed success's text is preserved; a typed error becomes a short error result with stable code. No nested DIMO catalog object is passed through.
- **Exceptions:** Catch at adapter boundary, map import/dependency/timeout/internal failures to stable error codes, and avoid raw traceback or sensitive exception details in model output. `ActionRegistry.run()` remains the final fallback catch, but logs a traceback; do not rely on it as policy handling.
- **Metadata:** Metadata is local adapter policy, not model schema. Current `ActionRegistry` will ignore any extra `TOOL` keys, so do not assume metadata is enforced merely by placing it in a `TOOL` dict. Validate specs in the adapter and use the fields for allowlist review and tests. Add central `ActionRegistry` policy hooks only if a later phase needs Mark-LV itself to enforce gates; this read-only review does not recommend changing it now.

### Metadata values for the first capability

| Field | `browser.list_tabs` value | Meaning |
|---|---|---|
| `risk` | `low` | Potential impact if misused. Low operation impact does not mean low privacy impact. |
| `side_effects` | `()` | No navigation, launch, tab focus change, or close is requested. Importing the optional browser module has process-level import effects and must stay lazy. |
| `execution_network` | `none` | The read operation itself does not need a network request; page URLs may already refer to network sites. |
| `execution_local_only` | `true` | Browser page enumeration runs locally. |
| `result_sensitivity` | `sensitive` | Titles and URLs can expose personal browsing activity; conservatively classify output as sensitive. |
| `model_egress` | `provider_dependent` (currently cloud-capable) | Tool output is inserted into the active model conversation; current Gemini Live path can transmit it to a cloud provider. |
| `confirmation` | `none` | No state change is requested; confirmation gate is unnecessary. Revisit if output sharing policy requires an explicit consent gate. |
| `reversibility` | `not_applicable` | Read-only; no state change to reverse. |

For future capabilities, use `unknown` conservatively for reversibility and egress until validated. Confirmation requirements must name the enforcing mechanism; metadata alone is not a safety gate. Do not approve high-risk, destructive, messaging, or unrestricted computer-control capabilities in this phase.

## Proposed files for the implementation phase

This review itself creates only `docs/revamp/ADAPTER_CONTRACT_REVIEW.md`.

| File | Proposed action | Reason |
|---|---|---|
| `app/marklv/actions/_dimo_adapter.py` | Create helper with frozen spec/outcome types, one explicit allowlist, schema/argument validation, safe errors, and a disable switch. Leading underscore means current discovery skips it as an action module. | Reuse policy without adding a new Mark-LV dispatcher or exposing DIMO catalog. |
| `app/marklv/actions/dimo_browser_list_tabs.py` | Modify existing wrapper to use the fixed allowlisted capability and retain its public tool name/schema. Avoid per-call `sys.path.insert`; use the repository package import already available in normal root startup, with a narrowly scoped fallback only if packaging requires it. | Keeps current Mark-LV `TOOL` boundary and limits first change to one read-only DIMO capability. |
| `Testing/test_dimo_adapter.py` | Create deterministic unit tests with a stub invoker; test allowlist, schema/argument rejection, output/error mapping, metadata validation, and disabled registration. | Prove policy without launching a browser, model, dashboard, or external integration. |
| `app/browser/tabs.py` | **Defer.** If the adapter later needs machine-readable failures, add a typed result API alongside existing string functions, preserving `list_open_tabs()` for DIMO graph callers. | Avoid broadening the first slice; current text-only function cannot reliably identify failures. |
| `app/marklv/core/action_loader.py`, `app/marklv/main.py`, `app/tools/registry.py`, `app/tools/native/system.py`, `app/marklv/actions/browser_control.py`, `app/browser/browser_manager.py` | **No changes proposed for the first slice.** | Existing host seam is sufficient. The full catalog and both browser managers must remain separate. |

The helper's disable switch should be a startup-time adapter-local allowlist/flag, defaulting to the current single reviewed capability to preserve present behavior. When disabled, the action module should expose no `TOOL` declaration (the loader already skips files whose `TOOL` is `None`), and the adapter must refuse direct invocation too. This adds no changes to existing Mark-LV user configuration semantics; disabling requires a restart because discovery runs once. A rollback can remove the adapter helper and restore the existing wrapper, or revert the single implementation commit.

## Minimal implementation and validation plan

1. Add the helper and route only `browser.list_tabs` through it. Leave `TOOL_CATALOG` unused by this bridge; do not enumerate or import all tools.
2. Unit tests with a stub `invoke`:
   - only the fixed capability is callable; unknown IDs and future unallowlisted IDs fail closed;
   - the emitted declaration contains exactly the selected `dimo_browser_list_tabs` action and empty object schema;
   - unknown args, wrong arg types and malformed/unsupported schemas fail before invocation;
   - no-tab output is preserved, a typed error maps to the expected stable result, thrown exceptions are sanitized, and raw exception details are not included;
   - metadata validation rejects unsafe or incomplete specs and does not infer confirmation/reversibility from name;
   - disabled state removes the model declaration and direct invocation returns unavailable.
3. Action-registry smoke test with a temporary action directory or isolated import: confirm Mark-LV discovers exactly the one DIMO action alongside existing actions, and existing inline/plugin registries remain unchanged. Do not run the full application for this automated check.
4. Manual integration check in a disposable DIMO Chromium profile containing only a harmless local/test page: confirm the action reports page index/title/URL and does not launch Chromium when no session exists. Then inspect the model tool declaration list and confirm no other DIMO catalog names appear. Do not use the user's real browser profile for this check.
5. Before a real Gemini Live manual check, use synthetic page data or obtain explicit product/privacy approval for sending URLs to the configured cloud model. A local browser read can still produce cloud-bound model content.

No tests or runtime checks were run for this review. Suggested test names/steps above are proposals, not claimed results.

## Risks and unresolved questions

- **Sensitive model egress:** Should browser titles/URLs be withheld, redacted, summarized locally, or explicitly approved before returning to a cloud-backed Mark-LV session? This is the key go/no-go issue for real user tabs.
- **Browser semantics:** Is DIMO's separate `~/.dimo/chromium_profile` session intentionally the target, or should future tools operate on Mark-LV's selected real browser? The answer changes privacy and automation behavior; do not merge sessions implicitly.
- **Result contract:** DIMO's legacy string-returning functions blur successful text and errors. Typed outcomes are required before adding routing decisions or multiple DIMO capability families.
- **Metadata enforcement:** Current Mark-LV loader does not carry custom policy metadata. The adapter can enforce a fixed allowlist locally; more general confirmation policy would require a carefully reviewed core contract in a later phase.
- **Import path:** The existing wrapper mutates global `sys.path`. Validate packaged/frozen startup before removing the fallback; absolute-import compatibility with Mark-LV modules is intentional.
- **Disable semantics:** Action discovery occurs at startup. A runtime toggle requires restart; no live revocation API exists in the inspected `ActionRegistry`.
- **Existing action exposure:** The current read-only tool appears in Mark-LV's aggregate declaration list automatically. Verify this is intended before merging any follow-up change; this review did not start Jarvis or inspect a live provider session.

## Go / no-go criteria

**Go for one bounded implementation slice only if all are true:**

- Product owner accepts that tab titles/URLs are sensitive and decides how to handle possible cloud-model egress.
- The allowlist has exactly one capability and no path from model-supplied names to `get_tool()` or arbitrary DIMO callables.
- Unit tests prove schema validation, safe failure mapping, metadata validation, and disable behavior.
- A stubbed action-registry smoke test confirms Mark-LV's existing startup/inline/plugin declarations are unchanged.
- Manual test uses a disposable browser profile and shows no browser launch when there is no active DIMO context.
- Rollback is a single adapter/wrapper revert and leaves all pre-existing Mark-LV actions and configuration intact.

**No-go** for full DIMO catalog exposure, generic `dimo_tool` dispatch, browser-manager unification, destructive/system/messaging/computer-control integration, provider-routing changes, default-entry changes, or any removal/rename/consolidation in this phase.
