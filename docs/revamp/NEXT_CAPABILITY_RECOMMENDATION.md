# DIMO Revamp — Next Capability Recommendation

**Scope:** read-only implementation audit on `revamp/marklv-parent-dimo-integration` at `d8c06fc53be7b0a4d06556c96e35270448b5df14`.

## Recommendation

Add exactly one capability: **`browser.list_page_links`**, exposed to Mark-LV as
`dimo_browser_list_page_links`.

It should enumerate up to 20 visible HTTP(S) links from the currently active
**DIMO** browser page.  It is a useful next step after tab enumeration: a user
can inspect the links available on a page without navigation, clicking, typing,
or running DIMO's graph.  It is not a claim about the browser selected by
Mark-LV; the two browser managers remain separate.

This recommendation is conditional on the privacy and no-launch criteria in
the go/no-go section.  The adapter must return a stable unavailable result when
the DIMO manager has no live page.  It must not call `get_page()` in that case,
because that method launches Chromium.

## Candidate comparison

| Candidate | Evidence that it is implemented | Mark-LV overlap | Risk and privacy | Decision |
|---|---|---|---|---|
| **DIMO `get_page_links`** | `app/browser/clipboard.py:get_page_links()` runs a DOM query for `a[href]`, filters HTTP links, limits results to 20, and formats numbered text/URL pairs. `CLIPBOARD_CATALOG` declares it. | `browser_control` declares `get_text` and `get_url`, but its action list has no link-enumeration operation. | Read-only DOM inspection; results may reveal page structure, link text, tracking parameters, or private destinations. No network request is made by extraction itself. | **Recommend, with an existing-session guard and bounded/sanitized result.** |
| `copy_page_content` | `app/browser/clipboard.py:copy_page_content()` extracts `document.body.innerText` and caps it at 8,000 characters. | Material overlap with Mark-LV `browser_control` action `get_text`, which extracts page body text and caps it at 4,000 characters. | Higher data exposure because it returns page content; also calls `get_page()` and can launch Chromium. | Reject as duplicated and too broad for the next slice. |
| `get_page_title` / `get_current_url` | Implemented in `app/browser/clipboard.py` and `app/browser/tabs.py`. | Mark-LV `browser_control` has declared `get_url`; its page session can also expose the active page context. | Small result but can disclose a sensitive title/URL; no meaningful new workflow over existing functions. | Reject as overlapping. |
| `weather_report` | `app/tools/native/weather.py` makes a real `requests.get()` call to `wttr.in`. | Mark-LV has a `weather_report` action. | Network request; location may be personal; no extension value over the host. | Reject as duplicated. |
| `web_search` | DIMO's tool registry imports the real search implementation. | Mark-LV has a `web_search` action and imports its news helper in `main.py`. | Network requirement and query egress. | Reject as duplicated. |
| `flight_finder` | `app/tools/native/flights.py:flight_finder()` returns a fixed “Dummy Airline, 900 USD” result. | Mark-LV also has a flight action. | No real search result; the hard-coded output makes it unsuitable. | Reject as stubbed. |
| `screen_process` / vision debugging | DIMO `app/tools/native/vision.py` delegates to `VisionDebugger`; `app/services/agents/vision_debugger.py` captures a screenshot and sends it to Gemini. | Mark-LV declares an inline `screen_process` action. | Screen capture and cloud egress; possible file write; high sensitivity. | Reject as overlapping and high risk. |

## Source-backed findings

### Host action seam

- `app/marklv/core/action_loader.py` discovers non-underscore files with a
  module-level `TOOL` dictionary, validates a top-level `OBJECT` schema and
  callable handler, and dispatches through `ActionRegistry.run()`.
- `app/marklv/main.py` combines the discovered action declarations with its
  inline tools and plugins. The model therefore sees a future DIMO wrapper
  through the existing Mark-LV path; no dispatcher or provider-routing change
  is needed.
- `app/marklv/actions/_dimo_adapter.py` already provides immutable
  `CapabilitySpec` and `CapabilityOutcome`, an immutable `CAPABILITIES`
  mapping, schema and argument validation, safe outcome conversion, and the
  `DIMO_MARKLV_ADAPTER_ENABLED` switch. Its mapping currently has exactly one
  member, `browser.list_tabs`.
- The adapter intentionally does not consult `app/tools/registry.py`.
  That registry builds the general `TOOL_CATALOG` from native and browser
  catalogs, and DIMO's graph nodes can dispatch catalog names. It is not an
  acceptable model-facing allowlist.

### Browser behavior and non-duplication

- DIMO `app/browser/browser_manager.py` is a synchronous, module-level
  Playwright singleton using `CHROMIUM_PROFILE_DIR`, defaulting to
  `~/.dimo/chromium_profile`. `list_pages()` returns an empty list when its
  context is not alive. By contrast, `get_page()` calls `_ensure_alive()` and
  launches a persistent Chromium context when needed.
- DIMO `get_page_links()` currently calls `browser_manager.get_page()` and then
  evaluates a fixed JavaScript expression. It has a real, bounded feature, but
  its legacy error string contains raw exception detail. A wrapper must not
  forward those strings directly.
- Mark-LV `app/marklv/actions/browser_control.py` owns a different async
  Playwright `_SessionRegistry`. Its declared actions include `get_text` and
  `get_url`, alongside browser control operations, but do not include a
  link-list operation. There is no source evidence that its sessions, profiles,
  active page, or tabs are shared with DIMO's manager.
- `docs/revamp/FEATURE_INVENTORY.md` identifies the separate browser systems
  and cautions against inferring that similarly named components are shared.
  `docs/revamp/MIGRATION_PLAN.md` calls for bounded read-only adapter groups.
  `docs/revamp/GRAPH_INTEGRATION_READINESS.md` supports an allowlisted approach
  but predates the current confirmation-bridge state, so its historical safety
  assessment was not used as evidence for this recommendation.

## Recommended adapter interface

The public action has no model-supplied selector, URL, tab index, or capability
name:

```python
# Internal, immutable adapter entry
CapabilitySpec(
    capability_id="browser.list_page_links",
    public_name="dimo_browser_list_page_links",
    parameters={"type": "OBJECT", "properties": {}},
    invoke=_list_dimo_page_links,
    risk="moderate",
    side_effects=("reads_visible_page_dom",),
    execution_network="none",
    execution_local_only=True,
    result_sensitivity="sensitive",
    model_egress="provider_dependent",
    confirmation="none",
    reversibility="not_applicable",
)
```

`_list_dimo_page_links({})` must:

1. Lazily import only `app.browser.browser_manager` and
   `app.browser.clipboard` using the adapter's scoped import compatibility
   mechanism.
2. Call `browser_manager.list_pages()` first. If it returns no pages, return a
   typed failure with a fixed code such as `no_active_dimo_page`. Do not call
   `clipboard.get_page_links()` in this path.
3. Call `clipboard.get_page_links()` only after that check.
4. Preserve successful numbered results exactly, including
   `"No links found on the current page."`.
5. Classify the known legacy strings before they reach the model: unavailable
   Playwright, `"Could not extract links: ..."`, and timeout strings must map
   to stable bounded adapter messages such as `dependency_unavailable`,
   `page_link_listing_failed`, and `timeout`. Catch unexpected exceptions at
   the boundary and return `internal_error`; log only the fixed capability ID
   and code.

The wrapper module should mirror the tab wrapper: create its `TOOL` only from
`action_declaration("browser.list_page_links", handler)` and call
`run_capability("browser.list_page_links", parameters)`. The action loader
will omit the declaration when the existing adapter-local switch is disabled;
direct calls will also be refused. There is no generic
`dimo_tool(name, args)` surface and no model-selected capability ID.

The `risk="moderate"` value reflects privacy exposure, not a state-changing
operation. Capability metadata remains documentation and adapter validation;
`ActionRegistry` does not enforce these fields automatically. No confirmation
is required because the operation reads an already-active DIMO page and the
proposed guard prevents browser launch. A product decision is still needed for
provider-bound tool output.

## Proposed implementation slice

| File | Change | Reason |
|---|---|---|
| `app/marklv/actions/_dimo_adapter.py` | Add one fixed invocation helper, safe legacy-result classifier/error codes, and exactly one additional immutable `CapabilitySpec`. | Maintains one reviewed allowlist; handles no-session, exception, and output boundaries centrally. |
| `app/marklv/actions/dimo_browser_list_page_links.py` | Create a thin discovered action declaration and handler for the fixed ID. | Uses the existing action loader without changing Mark-LV dispatch. |
| `Testing/test_dimo_adapter.py` | Extend deterministic adapter tests using stubbed browser-module results. | Proves the fixed route, no-launch guard, error redaction, declaration, and disabled behavior without starting a browser. |

No other production file should change. In particular, do not change
`app/browser/clipboard.py`, either browser manager, `app/tools/registry.py`,
`ActionRegistry`, `main.py`, provider routing, or DIMO graph nodes.

## Tests and manual smoke checks

### Deterministic unit tests

- Assert the immutable allowlist contains only `browser.list_tabs` and
  `browser.list_page_links`; unknown IDs and all catalog-only names fail
  closed.
- Assert the new `TOOL` name is exactly `dimo_browser_list_page_links` and its
  schema is the empty `OBJECT` schema. Reject any argument before invoking the
  capability.
- Stub `list_pages()` as empty and assert the implementation does not call the
  link extractor or `get_page()`.
- Inject a normal numbered result and `"No links found on the current page."`
  and assert byte-for-byte output preservation.
- Inject each legacy failure form, including a synthetic secret in the suffix,
  and assert the returned error has only the fixed safe code/message and never
  contains the suffix.
- Assert a thrown extractor exception maps to `internal_error` without a
  traceback or raw exception text.
- Assert metadata validation accepts the reviewed fields but does not itself
  claim to install a confirmation or egress gate.
- With `DIMO_MARKLV_ADAPTER_ENABLED=false`, assert both the `TOOL` declaration
  is absent and direct invocation returns the existing disabled result.

### Manual smoke check

Use a disposable DIMO profile and a harmless local/test page containing several
ordinary links. Start DIMO Chromium intentionally, invoke the action once, and
verify the list is capped at 20 and no navigation/focus/profile modification
occurs. In a separate clean process with no DIMO manager, invoke it and verify
that no Chromium process starts. Inspect the Mark-LV declarations to verify the
new one explicit `dimo_` action appears and no DIMO catalog names do.

Do not use a personal browsing profile for a cloud-backed Mark-LV smoke test
until the privacy decision below is approved.

## Risk, privacy, rollback, and go/no-go

The operation has no intended network request, OS action, browser navigation,
or persistent state mutation. It reads potentially sensitive local browser
data. Mark-LV sends action results into its active model conversation;
`app/marklv/core/llm_client.py` can route to Ollama or an OpenAI-compatible
endpoint, while the wider live path can use Gemini. Thus local extraction does
not guarantee local-only result handling. The correct metadata is therefore
`execution_network="none"`, `execution_local_only=True`,
`result_sensitivity="sensitive"`, and `model_egress="provider_dependent"`.

Rollback is limited to removing the new wrapper and the single capability
entry/helper, or disabling `DIMO_MARKLV_ADAPTER_ENABLED` and restarting
Mark-LV. The latter leaves existing Mark-LV actions and the already integrated
tab action unavailable together, which is acceptable only as the adapter-wide
emergency switch. A targeted code revert restores the current one-capability
allowlist.

**Go only if all conditions hold:**

- Product ownership accepts that page links may be sensitive and approves their
  possible transmission to the configured model provider, or validates a
  local-provider deployment.
- The implementation checks for an already-live DIMO page before invoking the
  legacy extractor and has a deterministic test proving no launch path.
- The allowlist is explicit and contains no catalog import, model-supplied
  capability ID, selector, URL, or arbitrary function route.
- Unit tests prove schema rejection, stable sanitization, output preservation,
  disabled discovery, and failure to expose additional DIMO capabilities.
- The manual smoke check passes with a disposable profile.

**No-go** if the only workable implementation launches a browser, reads a
Mark-LV or native-browser session instead of the DIMO session, forwards raw
legacy exception strings, requires a provider/startup/dispatcher change, or
cannot limit output to the bounded link list.

## Inspection record and limitations

Inspected: `app/marklv/actions/` (including `browser_control.py` and the DIMO
adapter/action), `app/marklv/core/action_loader.py`,
`app/marklv/core/llm_client.py`, `app/marklv/main.py`,
`app/tools/registry.py`, selected `app/tools/native/` implementations,
`app/browser/`, `app/nodes/`, `app/services/`, and the three requested revamp
documents.

This was static source review only. No browser, model, network, operating-system
action, graph run, or automated test was executed. The live browser profile
semantics, provider chosen in a real session, and the behavior of external
websites remain unverified.
