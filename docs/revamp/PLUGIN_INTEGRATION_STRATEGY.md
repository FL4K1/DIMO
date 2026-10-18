# DIMO Revamp — Plugin-First Architecture and Trust Boundary

**Status:** read-only source audit.  This strategy treats Mark-LV as the
authoritative application and DIMO as a source of candidate implementations,
not as a runtime foundation.

## Decision

Use a **reviewed Mark-LV plugin wrapper around a Mark-LV-owned capability** as
the standard extension pattern.  The default implementation is a small native
Mark-LV implementation of the reviewed behavior, even when DIMO provides the
idea or a reference implementation.  Reuse a narrowly scoped DIMO function
only after the function, its transitive imports, and its tests meet the review
checklist below.  A reusable bridge helper is appropriate only for multiple
approved legacy DIMO functions with the same import, validation, and result
sanitization needs; it is not a mechanism for exposing a catalog.

This choice accepts the cost of reimplementation when it removes uncertain
dependencies, implicit startup work, global state, or ambiguous error/data
handling. A plugin provides an integration and product-control boundary. It is
not a security sandbox.

## Source-backed findings: current plugin lifecycle

### Discovery, validation, naming, and model declarations

- `app/marklv/main.py` first calls `discover_actions()` for
  `app/marklv/actions/`, reserving inline tool names. It then calls
  `discover_plugins()` for `app/marklv/plugins/` with the union of inline and
  discovered action names as reserved names.
- `app/marklv/core/plugin_loader.py` sorts `*.py` files, skips leading
  underscore names (including `_template.py`), imports each remaining plugin at
  startup, and validates `PLUGIN` plus a callable module-level `run()`.
- A valid `PLUGIN` needs an identifier-like unique `name`, a nonempty
  description, and a top-level `parameters` dictionary whose type is `OBJECT`.
  The loader records optional `behavior`/`scheduling`; it does not deeply
  validate nested argument schemas.
- Core-name collisions and earlier-plugin name collisions are rejected. Import
  and validation failures are isolated to the offending file, logged, retained
  in `list_for_ui()`, and do not abort discovery of the rest.
- `PluginRegistry.get_tool_declarations()` returns only enabled valid plugins
  to the live model declaration set. `main.py` combines these with inline and
  discovered action declarations, then routes plugin names to the registry
  from `_execute_tool()`.
- `app/marklv/plugins/_template.py` documents the contract: `run(parameters,
  player=None, session_memory=None) -> str`. The loader uses signature
  inspection, so the optional UI and session arguments are passed only when the
  plugin declares them.

### Enable/disable and settings

- `app/marklv/memory/config_manager.py:get_plugin_enabled()` reads
  `plugins_enabled[plugin_name]` from Mark-LV's existing JSON configuration and
  defaults newly discovered plugins to enabled. `save_plugin_enabled()` persists
  a UI toggle.
- The registry re-reads that value for declarations, `run()`, UI listing, and
  settings schemas. A disabled plugin is omitted from advertised tool
  declarations and `PluginRegistry.run()` returns a disabled message rather
  than calling its `run()` function. **Verified: disabled state prevents normal
  registry dispatch.**
- `app/marklv/ui.py` exposes the discovered plugin rows and writes enable state
  through the existing configuration manager. Optional `PLUGIN_SETTINGS` with
  a `fields` list are rendered as namespaced settings sections; values are
  stored under `plugin_config`.
- Discovery/import still happens before the enabled check. A disabled plugin
  remains loaded in the Python process and its top-level import statements have
  already run. Disable is an execution/advertisement switch, not a safe way to
  install unreviewed code.

### Failure behavior and limitation

- Invalid or failing imports do not stop startup, but loader and runtime
  exception paths print tracebacks. `PluginRegistry.run()` includes the raw
  exception text in its model-facing failure string. A reviewed capability
  wrapper must catch and sanitize its own errors before they reach that fallback.
- Plugins run in the same interpreter, identity, environment, filesystem,
  process table, network context, and UI object graph as Mark-LV. Their code can
  import modules, read configuration and memory, create threads, make requests,
  invoke subprocesses, mutate globals, or keep references after being disabled.
  The plugin mechanism supplies modular discovery and a user toggle; it does
  not supply process, capability, dependency, data, or network isolation.

## Explicit trust boundary

| Area | Decision | Evidence and reason |
|---|---|---|
| Mark-LV startup, UI/HUD, voice session, configuration, action/plugin discovery and dispatch | **Remain in Mark-LV.** | `app/marklv/main.py`, `core/action_loader.py`, `core/plugin_loader.py`, and `memory/config_manager.py` provide the active host lifecycle. |
| Per-capability schema checks, allowlisting, output size/error sanitation, telemetry, user-facing declaration, confirmation/undo connection | **Owned by the Mark-LV plugin/wrapper.** | The plugin loader validates only the top-level schema and does not enforce safety metadata. |
| DIMO pure formatting/parsing algorithms with no host side effects | **May be borrowed after review, or reimplemented.** | Eligibility is conditional; source inspection and deterministic tests must demonstrate bounded inputs/outputs and dependencies. |
| DIMO tab listing | **Currently a bounded exception through the existing action adapter.** | `_dimo_adapter.py` has an immutable one-entry allowlist and fixed capability ID. Its action does not expose `TOOL_CATALOG`. |
| DIMO registry and browser catalogs | **Excluded as a runtime integration surface.** | `app/tools/registry.py` assembles `TOOL_CATALOG`, including system, messaging, files, general browser control and graph-oriented entries. |
| DIMO graph, planner, router, execution loop, LLM gateway, and memory system | **Excluded pending separate review.** | `app/graph/graph.py` and `app/nodes/` compose orchestration; `nodes/loop.py` resolves catalog tools; `services/agents/llm_gateway.py` independently chooses Gemini or Ollama; `app/memory/` maintains a separate store/workflow. These are competing runtime foundations. |
| DIMO browser manager/session | **Remain separate and excluded from host browser unification.** | `app/browser/browser_manager.py` owns a sync persistent `~/.dimo/chromium_profile`; Mark-LV `browser_control.py` has an async `_SessionRegistry`. There is no evidence of shared sessions. |
| DIMO native file, OS, messaging, automation, vision, and external services | **Excluded by default.** | These modules can read/write files, automate input, schedule work, call cloud/network services, or return raw errors. `native/system.py` performs host actions; `native/files.py` mixes read/write/delete; `vision_debugger.py` captures screenshots and uses Gemini. |

## Standard capability pattern

Each candidate uses one plugin file and, only when justified, a small private
helper under `app/marklv/plugins/` whose name starts with `_`. The plugin file
is the explicit public and model-facing boundary; its helper is not separately
discoverable.

Its responsibilities are:

1. Declare one stable `dimo_*` plugin name, a narrow Mark-LV `OBJECT` schema,
   clear description, and only the fields it needs.
2. Bind one fixed reviewed capability. It never takes a catalog name, module
   name, selector language, executable command, or other indirect dispatch
   value from the model unless that parameter is specifically reviewed.
3. Validate arguments and enforce size, count, path, URL, or time limits before
   calling implementation code.
4. Prefer a self-contained Mark-LV implementation. If reuse is approved,
   import one reviewed function lazily and avoid broad imports such as
   `app.tools.registry`, `app.nodes`, `app.graph`, or DIMO memory/gateway
   modules.
5. Translate successes to concise bounded text and errors to stable safe codes.
   Do not return raw exceptions, tracebacks, provider responses, credentials,
   paths, or unbounded content to the model.
6. State exact metadata in the review record: risk, side effects, network need,
   local execution, result sensitivity, possible model egress, confirmation,
   reversibility, owner, and dependency set. Metadata is evidence for review,
   not automatic enforcement.
7. Use Mark-LV's established confirmation/undo mechanisms when needed, and do
   not assert that a DIMO-internal guard is sufficient.

The existing `_dimo_adapter.py` may remain as a private helper for the small
legacy adapter family. It must retain fixed IDs and an immutable allowlist. It
must not become a plugin-driven generic DIMO dispatcher or import the catalog.

## Existing `dimo_browser_list_tabs` action

Keep `app/marklv/actions/dimo_browser_list_tabs.py` in place for now. It is the
current, independently tested bounded integration, has an adapter-local switch,
and exposes exactly one model-facing name with an empty schema. Moving it to a
plugin now would create churn without new user capability.

A later migration to a plugin is reasonable only if product needs per-capability
UI enablement/settings and the replacement passes regression tests for name,
schema, disabled declaration, direct disabled invocation, sanitization, and
DIMO-session separation. The trade-off is that plugin toggles are immediate for
registry dispatch and model declarations, while the current action adapter
switch is evaluated at discovery and requires restart to affect declaration
loading. Conversely, the plugin loader imports plugin code even if disabled and
defaults plugins to enabled. A plugin migration therefore needs a reviewed
Mark-LV-owned wrapper with safe top-level imports; it must not move the current
adapter merely for architectural symmetry.

## Capability review checklist

| Review dimension | Required evidence before integration |
|---|---|
| Functionality and duplication | Trace a real implementation and call path. Compare its user outcome against Mark-LV actions/services. Reject or consolidate the proposal when Mark-LV already provides materially equivalent behavior. |
| Dependencies | Inventory direct/transitive imports, optional packages, import-time side effects, OS/browser/provider requirements, license and installation burden. No new dependency without a demonstrated capability gap. |
| Inputs and errors | Document schema, limits, malformed-input handling, legacy string-error ambiguity, timeouts, and exception behavior. The wrapper must reject unexpected input and sanitize all error paths. |
| Side effects | Identify filesystem, process, browser, clipboard, UI, network, service-account, and persistent-state effects. Set confirmation and undo requirements from actual code, not names or metadata. |
| Privacy and data flow | Classify inputs/results and log content. Trace whether output becomes model context; distinguish local execution from cloud-model egress. Bound and redact output before it reaches the model. |
| Offline/local behavior | Prove what works with network disabled, what only uses localhost, and what needs cloud/API credentials. Do not inherit DIMO's LLM gateway or provider choices. |
| Tests | Add deterministic unit tests for schema rejection, fixed dispatch, happy path, failures/redaction, enable/disable, and limits. Add isolated manual smoke tests only for reviewed side effects. |
| Rollback | Provide one reversible change set, default-off or readily disabled behavior where appropriate, and evidence that disabling/reverting leaves Mark-LV startup and existing actions unchanged. |
| Ownership | Name the Mark-LV owner for future maintenance and record whether source was reimplemented, selectively reused, or only used as a behavioral reference. |

## Staged roadmap

### Phase 0 — Establish the boundary

Record the source/dependency review template and classify existing DIMO areas.
No DIMO imports, registry exposure, graph integration, or provider changes.

**Exit:** each candidate has a documented owner, dependency list, duplicate
assessment, risk/data-flow classification, and rollback route.

### Phase 1 — Preserve the one bounded adapter

Maintain `browser.list_tabs` as the only existing DIMO bridge. Keep its
allowlist exact, output/error sanitation, and enable switch tests.

**Exit:** deterministic tests demonstrate that an unapproved DIMO catalog name
cannot be called or declared and disabled mode prevents declaration and direct
adapter invocation.

### Phase 2 — One plugin-first proof capability

Select one function that offers user value absent from Mark-LV and pass the
checklist. Implement it as a Mark-LV-owned plugin wrapper, with a native
implementation by default. Do not select a capability merely because DIMO
already has a module.

**Exit:** unit tests, a minimal isolated smoke test, a privacy decision, and a
verified enable/disable/rollback path. Existing Mark-LV declarations, startup,
provider routing, and memory remain unchanged.

### Phase 3 — Selective reuse policy

Only after more than one approved legacy function has the same narrow needs,
evaluate a private shared bridge helper. Review every transitive DIMO import;
replace code in Mark-LV where it lowers risk or dependency cost.

**Exit:** the helper has no catalog/graph/memory/gateway import, every exposed
capability has a fixed binding, and tests prove no indirect dispatch path.

### Phase 4 — Local/offline AI as a host capability

Evaluate optional local inference behind a Mark-LV-owned provider seam and its
existing configuration model. DIMO can be reference material only; do not
adopt `LLMGateway`, graph routing, or planner decisions.

**Exit:** verified offline behavior, explicit cloud fallback and egress policy,
and rollback to the current Mark-LV provider behavior without UI/startup
changes.

## Risks, unresolved questions, and go/no-go

- The current plugin loader's default-enabled setting and startup import mean
  plugins must be trusted before they are placed in the directory. A future
  quarantine/install approval model would be a separate Mark-LV plugin-system
  project, not part of this strategy.
- Plugin runtime failures can currently disclose raw exception details to a
  model. Each reviewed wrapper must catch expected and unexpected errors until
  a separately approved host-wide error-policy change exists.
- The current configuration file holds plugin settings alongside broader Mark-LV
  settings. Any capability-specific secret handling needs an explicit review;
  this audit makes no claim that arbitrary plugin settings are secret-safe.
- Source review cannot prove behavior against live browsers, providers,
  hardware, or external services. Claims here are limited to static call paths.

**Go for an individual capability only when:** it is useful and non-duplicative;
its source and dependencies are reviewed; its plugin/wrapper has fixed dispatch,
bounded arguments and output, safe errors, and tested enabled/disabled behavior;
its network/model egress and side effects are accepted; and rollback is tested.

**No-go:** importing `TOOL_CATALOG`, any DIMO graph/planner/loop/memory/gateway,
unrestricted computer/browser/file/messaging tools, unreviewed cloud capture or
network operations, or a plugin whose import-time behavior has not been
reviewed. No capability is production-ready solely because it can be discovered
as a plugin.

## Inspection record

Inspected: `app/marklv/core/plugin_loader.py`,
`app/marklv/core/action_loader.py`, `app/marklv/main.py`,
`app/marklv/plugins/_template.py`, `app/marklv/memory/config_manager.py`, the
current DIMO adapter/action, `app/tools/registry.py`, representative DIMO native
tools/browser/services, `app/nodes/`, `app/graph/`, `app/memory/`, and the
requested revamp documentation. This audit ran no application, browser, model,
network, or operating-system actions.
