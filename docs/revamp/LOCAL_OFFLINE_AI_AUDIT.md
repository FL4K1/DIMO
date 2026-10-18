# Jarvis Local LLM Mode, Ollama Lifecycle, and Gemini Voice Audit

**Audit type:** static source inspection only
**Branch:** `revamp/marklv-parent-dimo-integration`
**HEAD at inspection:** `d8c06fc53be7b0a4d06556c96e35270448b5df14`

## 1. Executive summary

Mark-LV has useful pieces for local inference, but Local LLM Mode is not a
working conversational mode in the inspected source. `app/marklv/core/llm_client.py`
contains an Ollama REST client, model-list check, warmup call, streaming parser,
and optional OpenAI-compatible route. The active Mark-LV runtime does not call
that client. When `ai_engine == "Ollama"`, `JarvisLive.run()` enters
`_run_ollama_loop()`, which changes the UI to `IDLE`, logs that the local engine
is active, and sleeps until the setting changes. It does not call Ollama,
capture audio, accept typed input, dispatch tools, or produce responses.

There is also a configuration/UI gap: the settings dialog imports
`save_ai_engine`, but the engine click handler only updates a temporary field,
and the dialog's save signal omits the engine. Static search found no call to
`save_ai_engine()` anywhere else. The persisted setting defaults to Gemini Live.
An Ollama value placed in the config by another means would still enter the
idle loop described above.

The active Gemini path is an audio-capable **conversational Live model**. It
receives microphone audio and typed messages, uses Mark-LV declarations to
request tools, receives the dispatched results, generates the final response,
and produces speech. Therefore Gemini is currently both voice processor and
the assistant LLM. The separate Whisper/Vosk STT and Edge/Kokoro/ElevenLabs TTS
modules exist, but have no call sites in the active Mark-LV runtime. The source
does not implement a Gemini-only STT/TTS path.

The requested architecture is feasible without adopting DIMO's graph, planner,
gateway, or memory system. It needs a Mark-LV-owned provider coordinator,
truthful readiness and mode state, a typed local request/tool round-trip, and a
separately chosen speech path. The lowest-risk first implementation slice is a
testable Mark-LV Ollama readiness/ownership service with injectable HTTP and
process boundaries. It must prove endpoint, exact configured model, and a
minimal inference before any UI/runtime marks Local LLM Mode active. Keep it
unwired to voice and application state in that first slice.

## 2. Current architecture and call graphs

### Product entry point

The root `main.py:504-520` calls `app.marklv.main.main()`. The root DIMO text
and voice entry points are separate functions and are not chosen by the
default `main()`. `app/marklv/main.py:2326-2335` constructs `JarvisUI`, waits
for the API key, constructs `JarvisLive`, and runs its async loop on a
background thread. Mark-LV remains the current runtime owner.

### Typed input in the current Gemini mode

1. UI text entry callbacks in `app/marklv/ui.py` call
   `JarvisLive._on_text_command()` on a worker thread.
2. `app/marklv/main.py:839-855` returns early if `self.session` is absent;
   otherwise it sends the text as a user turn with
   `session.send_client_content()`.
3. In the normal run branch, `app/marklv/main.py:2121-2137` chooses a Gemini
   Live model, builds the Live configuration, constructs a Gemini client, and
   connects a Live session.
4. The connected session's `_receive_audio()` handles response text/audio and
   tool calls. A typed message is not sent to `core.llm_client`.

### Voice input and response in the current Gemini mode

1. `JarvisLive._listen_audio()` opens the configured microphone with
   `sounddevice` and queues PCM. If push-to-talk is on, audio is queued only
   while held; if the wake-word detector is asleep, mic frames stay local.
2. `_send_realtime()` calls `session.send_realtime_input(audio=...)` at
   `app/marklv/main.py:1294-1307`. The connected session is Gemini Live.
3. `_build_config()` at `app/marklv/main.py:960-1070` sets
   `response_modalities=["AUDIO"]`, `input_audio_transcription={}` and
   `output_audio_transcription={}`, along with the system instruction and
   Mark-LV tool declarations.
4. Gemini Live returns audio and transcription text. The receiver logs
   input/output transcription and handles function calls. `_play_audio()` plays
   returned audio chunks locally.

This is audio-to-audio conversational inference with transcription metadata.
It is not a dedicated STT/TTS pipeline. The Live model can answer directly,
decide to call a tool, and generate the final spoken response.

### Tool declarations, dispatch, and result handling

`_build_config()` combines inline declarations,
`ActionRegistry.get_tool_declarations()`, and enabled plugin declarations into
the Gemini Live config (`app/marklv/main.py:1010-1035`). For a returned
function call, `_receive_audio()` calls `_execute_tool()` and then sends the
`FunctionResponse` values through `session.send_tool_response()`
(`app/marklv/main.py:1586-1595`). Thus the current model synthesizing after an
action result is Gemini Live.

`_execute_tool()` handles selected built-ins directly, then routes discovered
actions through `_action_registry.run()`, then plugins through
`_plugin_registry.run()` (`app/marklv/main.py:1126-1280`). Mark-LV's
confirmation/action path stays in that dispatcher. A local provider must call
the same Mark-LV-owned dispatch path and receive a result in its own
conversation history; it must not ask DIMO's planner or `TOOL_CATALOG` to
execute a call.

### Existing Mark-LV LLM client call graph

Static search of `app/marklv/` found no production call site for
`core.llm_client.call_llm()`, `call_llm_stream()`, or
`call_llm_text()`. `app/marklv/core/llm_client.py` is therefore a client
implementation, not an active Mark-LV turn coordinator in this checkout.

The target typed path needs to become something like:

```text
UI text -> Mark-LV local conversation coordinator
         -> selected local provider request with Mark-LV declarations
         -> validate requested function name/arguments
         -> Mark-LV inline/action/plugin dispatcher and confirmation gates
         -> append tool result to local conversation
         -> local provider follow-up/final answer -> UI
```

The target voice path can share that coordinator after obtaining a transcript:

```text
mic -> selected speech recognizer -> transcript -> same local turn coordinator
    -> Mark-LV action dispatcher -> local final text -> selected speech synthesizer
```

Neither coordinator is implemented by current `main.py` or the client module.

## 3. Existing provider capability matrix

| Path | Source behavior | Streaming / tools / history | Runtime status |
|---|---|---|---|
| Gemini Live | `main.py` connects `genai.Client(...).aio.live.connect()` and configures audio input/output, transcriptions, system prompt and function declarations. `core/gemini.py` maintains a Gemini Live model ladder. | Realtime audio and persistent session context; declarations are sent to Gemini; Mark-LV handles tool requests and sends results back to the same Live session. | Active conversational runtime when `ai_engine` is Gemini Live. Cloud. |
| Mark-LV Ollama REST client | `core/llm_client.py` uses `llm_url` default `http://localhost:11434`, `llm_model` default `llama3.2`, and `llm_provider` default `ollama`. Ollama requests use `/api/chat`; OpenAI-compatible requests use `/v1/chat/completions` in `call_llm` and `call_llm_stream`. | Has non-streaming and streaming methods, accepts a caller-supplied message list, accepts optional tools, and normalizes returned tool calls. It does not own a Mark-LV tool loop or apply an action allowlist. `call_llm_text()` always targets `/api/chat`. | Implemented module, no active Mark-LV call site found. The `llm_provider` setting is independent from UI `ai_engine`. |
| DIMO LLM gateway / graph nodes | DIMO `LLMGateway` routes model names prefixed `gemini` to Gemini and other names to Ollama. DIMO graph/router/planner/loop are a separate orchestration path. | Own planning, tool resolution, and DIMO execution semantics. | Not part of the trusted Mark-LV runtime; not recommended for this design. |
| Mark-LV STT classes | `core/stt.py` has local `WhisperSTT` and `VoskSTT`. Whisper may download a model if not cached; Vosk requires a model. | Whisper returns a completed transcript; Vosk exposes chunk processing. | Classes exist; no active Mark-LV call site found. |
| Mark-LV TTS classes | `core/tts.py` includes Edge TTS (network), Kokoro (local synthesis when installed/models available), and ElevenLabs (cloud API). | Blocking `TTSPlayer.speak()` wrapper; not connected to `JarvisLive` output. Kokoro import-recovery code can run `pip install`. | Classes exist; no active Mark-LV call site found. |

### Ollama client details and caveats

- `get_llm_provider()` reads `llm_provider`; values `openai`, `lmstudio`,
  `localai`, `jan`, and `llamacpp` select OpenAI-compatible behavior; other
  values map to Ollama. `get_llm_settings()` reads `llm_url` and `llm_model`.
  Mark-LV's UI `ai_engine` is a different key and does not select this client.
- `ensure_ollama_running()` first GETs `<llm_url>/api/tags`; when unavailable,
  it calls `subprocess.Popen(["ollama", "serve"])` and polls for up to 15
  seconds. On Windows it sets `CREATE_NO_WINDOW`. This checks reachability and
  attempts a launch; it does not establish model readiness.
- The `Popen` result is not retained. There is no ownership record, duplicate
  startup lock, process health monitor, or shutdown path. API reachability
  prevents a normal duplicate in the simple case, but concurrent callers can
  both observe unavailable and race to launch. The executable is resolved by
  command lookup; no installed path, service, or GUI-app discovery is present.
- `check_model_available()` requests `/api/tags`, but considers a model found
  when the exact name, base name, or any tag with that base prefix matches. On
  an exception it returns `True` with a comment that Ollama may be starting.
  That result is not a reliable readiness proof.
- `warmup_model()` POSTs a short message to `/api/chat` with `stream=False`,
  `keep_alive=-1`, one generated token, and a 180-second request timeout. It
  returns `False` after a failure, but its own docstring calls failure
  non-fatal, and there is no active UI mode-transition call site.
- `call_llm()` and `call_llm_stream()` default to 120-second request timeouts.
  Connection failures can call `ensure_ollama_running()` and retry once. The
  module has no cloud fallback branch when its chosen provider is Ollama; the
  OpenAI-compatible route occurs only when its separate `llm_provider` config
  chooses that route. Errors are raised with exception-derived text and are
  not currently mapped to UI mode states.
- `call_llm()` can pass a caller-provided `tools` list to Ollama or OpenAI
  compatible chat and returns provider tool-call objects. The module does not
  verify names or dispatch them. Mark-LV schemas are Gemini-style uppercase
  types; no adapter converting its declarations to the provider's expected
  tool schema is present in an active path.
- `call_llm_stream()` accumulates tool call fragments/objects and yields
  sentence and done events. Cancellation, mode-transition coordination, and a
  Mark-LV tool-follow-up loop are not implemented here.

The safe `.env.example` has DIMO-specific `OLLAMA_HOST`, `ROUTER_MODEL`, and
`LLM_MODEL` examples. Those are not the Mark-LV `api_keys.json` settings and
do not establish the active Mark-LV model. No private config, certificate, or
environment values were read.

## 4. Ollama lifecycle audit

### What exists versus what is required

| Lifecycle step | Current source behavior | Gap for a truthful Local LLM Mode |
|---|---|---|
| Detect running server | `ensure_ollama_running()` pings configured `/api/tags`; `check_model_available()` also queries tags. | No shared, concurrency-safe lifecycle owner or persisted state; GET exceptions in model check can be treated as “available.” |
| Start if absent | `Popen(["ollama", "serve"])`, hidden console on Windows, poll for reachability. | No executable path discovery, service/app policy, retained process handle/PID, startup lock, ownership state, or safe cleanup policy. Success means only HTTP reachable. |
| Verify configured model | `/api/tags` and a permissive exact/base/prefix match. | Match exact configured identifier and surface missing model; never claim readiness on a failed tags request. Do not download automatically. |
| Verify inference | `warmup_model()` sends a one-token chat request with up to 180 seconds. | It is not invoked by mode selection and treats failure as non-fatal to its caller. Validate a successful response before activation. |
| Recover from inference failure | Client methods retry after connection error, attempting to start Ollama and retry once. | No active Local LLM turn uses this client; no user-visible unavailable state, controlled retry action, or guarantee against changing modes mid-request. |
| Exit / process ownership | No `Popen` handle retained; no Ollama process cleanup code found in this client. | Must distinguish preexisting user-managed service from a child started by Jarvis. Never terminate a user-managed service. First milestone should default to leaving tracked children running too until a reviewed stop policy exists. |

### Launch strategy recommendation

Use the configured host as the source of truth. First check it. If it responds,
treat the server as externally managed and do not launch or stop a process. If
it does not respond, a later implementation may attempt one configured,
reviewed launch command, resolved from the user's environment or an explicit
setting; do not hard-code an assumed Windows installation path or silently
install the app. Record a process handle only when Jarvis itself successfully
launches one. Serialize startup attempts and recheck reachability under that
lock before launching.

Do not kill the process simply because Jarvis changes modes or exits. A future
explicit stop operation would need evidence that the tracked child still
belongs to this manager, is not a service/user instance, and can be stopped
safely. No current source supports that guarantee.

### Required readiness sequence

1. Reachability: successful response from the configured Ollama host.
2. Model presence: exact configured model identity returned by the tags API.
3. Minimal inference: successful bounded chat request to the configured model
   with a nonempty valid response.
4. Time budget: bound connection and cold-load duration separately or use a
   documented overall deadline; show the current stage and allow a safe retry.
5. Activation: only after all prior stages succeed. On failure, retain the
   previously active provider and distinguish `not installed/launch failed`,
   `server unreachable`, `model missing`, `inference failed`, and `timed out`.

`GET /api/tags` succeeding is not equivalent to the configured model being
installed or loaded, and a process launch returning is not equivalent to the
server or model being ready.

### Failure and transition handling

- **Ollama absent / command not found:** current helper prints a message and
  returns false. A UI path does not call it. Future UI should report the
  executable/launch failure and preserve the prior active mode.
- **Already running:** API reachability short-circuits launch. Treat it as
  externally owned; do not terminate it later.
- **API never reachable:** current 15-second polling returns false, but caller
  must inspect that result. Current selection path does not.
- **Model absent:** model check can report false only after a successful tags
  request; current check may accept a sibling tag and returns true on request
  errors. It is not called by active runtime.
- **Inference fails or cold-load times out:** warmup returns false; client calls
  may raise. No state transition, dialog, retry control, or active-mode
  recovery is wired to these outcomes.
- **Retry / switch while starting or inferring:** no transition coordinator or
  cancellation token exists. Use one in-flight operation ID/generation so
  stale completions cannot activate a mode after a newer selection. Cancel
  waiting/network work where supported; never kill a possibly user-managed
  server to cancel an inference.
- **Jarvis exit:** no ownership cleanup exists. Preserve current safety by not
  adding an unconditional process kill.
- **Cloud fallback:** `core/llm_client.py` does not route Ollama inference
  errors to Gemini. However, the active Gemini Live loop has a Gemini-only
  model ladder, and multiple Mark-LV action modules make separate Gemini calls
  through `core.gemini`. A future Local LLM Mode must explicitly block or
  replace such action-level cloud calls where they would be reached.

## 5. UI mode-switch design

### Existing UI surfaces

The Customize dialog shows buttons for “Gemini Live (Fast, Cloud)” and
“Ollama (Private, Local)” (`app/marklv/ui.py:1671-1686`). `_on_engine_pick()`
only assigns `_sel_engine` (`ui.py:1789-1791`). The dialog's `_save()` emits
assistant name, user name, color, and voice (`ui.py:1870-1873`); it does not
emit or save `_sel_engine`. `save_ai_engine()` exists in
`app/marklv/memory/config_manager.py:83-94`, but source search found no call to
it. `get_ai_engine()` defaults to Gemini Live.

Mark-LV already has UI state/log updates and Qt signals for thread-safe UI work
(`ui.py:2986-3003`, `ui.py:5797-5803`) plus an interface confirmation banner
for risky actions (`ui.py:5459-5478`). The inspected source has no dedicated
Ollama startup progress dialog, readiness popup, or separate voice-provider
status. The action confirmation banner is not a mode-switch dialog.

### Recommended transition behavior

Use one authoritative Mark-LV mode coordinator with separate selected and
active provider values. Selecting Local LLM Mode should open the requested
Continue/Cancel warning. On Continue, execute readiness in a worker, signal
measured stages to the UI, disable repeat starts, and keep the previous active
mode until the model passes minimal inference. Only then persist/activate the
new LLM provider and show “Local LLM Mode is active.” Keep voice service state
separate (for example `voice_input=ready/unavailable` and
`voice_output=ready/unavailable`). A failed voice service must not change the
LLM provider.

On failure, retain the exact primary message **“Jarvis cannot switch to Local LLM Mode.”** Add the measured cause, Retry where retry is meaningful, and
Cancel/Stay in Previous Mode. Never report active mode on launch-only or
reachability-only success. If active local inference later fails, state
“Local inference unavailable” and offer a safe retry; do not change provider
to Gemini without an explicit user choice.

Keep one small provider state machine rather than duplicating booleans in UI,
main loop, and provider client. A useful minimum is:

```text
selected_llm: gemini_live | ollama
active_llm:   gemini_live | ollama | none
llm_status:   idle | starting | checking_model | verifying | ready | active | failed | unavailable
voice_input:  disabled | local | gemini | ready | unavailable
voice_output: disabled | local | gemini | ready | unavailable
transition_id: monotonically increasing operation token
```

Only persist the selected provider after successful readiness, or persist it as
“selected” while retaining a distinct prior `active_llm`; never present those
as the same state. Choose one policy explicitly and test it.

## 6. Gemini voice separation

### Current Live behavior

`_build_config()` requests audio responses and both input and output
transcription. `main.py` sends raw microphone PCM to the Live session, accepts
audio and transcription, handles Live model tool calls, sends Mark-LV
`FunctionResponse`s back to Gemini, and plays Gemini audio. The Live model
generates conversational responses and final answers. **It cannot be described
as speech-only in the current implementation.**

`app/marklv/core/gemini.py` also contains one-shot Gemini services, and action
modules including `code_helper.py`, `dev_agent.py`, `file_processor.py`,
`flight_finder.py`, `web_search.py`, `desktop.py`, `computer_control.py`, and
`youtube_video.py` call Gemini independently. These are not all governed by
`ai_engine`; local-only policy cannot be achieved by switching just the main
conversation model if reachable actions still invoke these calls.

### Existing separate STT/TTS options

- `core/stt.py` contains offline Whisper and Vosk implementations, but no active
  Mark-LV runtime imports/constructs them. Whisper can attempt an automatic
  speech-model download on a cache/offline failure. Treat model download as an
  explicit setup operation in any local-mode design.
- `core/tts.py` provides Edge TTS, ElevenLabs, and Kokoro. Edge TTS sends text
  to a network service; ElevenLabs sends text to its API. Kokoro is a local
  candidate if installed and its voice/model resources are present. Its
  import-recovery path can invoke `pip install`, so it should not be adopted
  without removing/isolating that install behavior in a separately reviewed
  change.
- No Gemini-only STT or Gemini-only TTS function is wired in Mark-LV. The
  current `Gemini Live` output is model-generated speech, not a TTS call over
  locally generated text. A dedicated speech API path must be separately
  verified and must accept only transcript or final answer text as appropriate.

Therefore the target “Gemini speech input → local Ollama reasoning” is not
currently available. A speech-input choice can initially be local Whisper or
Vosk after explicit model setup. A Gemini speech-only path is a separate
capability requiring API verification and tests showing it returns a transcript
without conversational answer generation. For speech output, either implement
and verify dedicated Gemini TTS or explicitly select an existing provider;
Edge/ElevenLabs are cloud services, while Kokoro is the local candidate subject
to dependency/model setup and import-side-effect review.

## 7. Network and privacy matrix

| Mode / path | Local inference | Internet / credentials | Data leaving this machine according to source | Cloud LLM answer / fallback |
|---|---|---|---|---|
| Current Mark-LV Gemini Live | No | Gemini API key and network required. | Mic/phone audio, typed messages, system prompt, declared tools, memory/context included in the prompt, tool results, and captured screen/camera image when that tool is used are sent through the Gemini Live session. Gemini returns transcription, text, tool requests, and audio. | Yes. Gemini Live itself reasons and generates the answer; connection failure ladder tries another Gemini Live model, not Ollama. |
| Config value `ai_engine=Ollama` in current runtime | No actual turn inference | May not request network in the idle loop; any configuration UI persistence is incomplete. | No local chat/tool result path is run by `_run_ollama_loop()`. | No answer and no automatic cloud fallback in this branch; it logs active then idles. |
| `core.llm_client` Ollama methods if called | Yes, configured endpoint intended local by default | Defaults to localhost, but user config may change host. No API key needed by the shown Ollama HTTP requests. | Message history, prompt, tool declarations, and action results supplied by caller go to configured host. Locality depends on host. | No Gemini fallback in the Ollama client path. OpenAI-compatible requests can go to a remote endpoint if configured separately. |
| Target local LLM + Gemini speech services | Yes for language model | Ollama host; Gemini credential/network only for selected voice services. | If using Gemini STT, captured audio leaves for Google. If using Gemini TTS, locally generated answer text leaves for Google. Local LLM prompt, tool schemas/results, and final answer should stay local except when deliberately passed to TTS or another cloud action. | Must be no cloud LLM fallback. Speech service failure reports unavailable or uses only a separately configured speech fallback. |
| Fully local STT/LLM/TTS target | Yes | No network during inference once all packages/models/weights are already installed. | No transcript/audio/text needs to leave for inference/speech. Other actions may still use network and require their own policy. | No, if provider and action-level Gemini calls are explicitly blocked/disabled. |
| Mark-LV one-shot Gemini actions | Not necessarily | Gemini API credentials and network. | Function-specific prompt, source text, file content, image, screen, or query is sent as each action constructs it. | Direct cloud inference can occur independently of selected `ai_engine`. |

Local inference alone does not mean offline operation. Voice services,
web-search actions, remote configured model endpoints, plugins, and action
implementations each have separate network paths. Before claiming local-only,
audit and gate every action that directly imports/calls Gemini or sends data to
another cloud service.

## 8. Gaps, risks, and technical debt

### Confirmed by static source

- The UI engine selection is not persisted by its dialog save path; no
  `save_ai_engine()` call was found.
- The current Ollama engine branch is an idle loop, not a local LLM feature.
- Mark-LV's Ollama client code exists but has no active call site in the
  `app/marklv` runtime.
- `check_model_available()` treats request exceptions as model available and
  accepts base/prefix matching; it is not a strict readiness check.
- Ollama launch is an untracked `Popen` using a PATH-resolved `ollama` command.
  There is no process ownership, shutdown, cancellation, or duplicate-launch
  coordinator.
- The Gemini Live session is a conversational LLM and speech generator. Tool
  results return to Gemini Live, not to the local `llm_client`.
- Separate STT/TTS code exists but has no active Mark-LV call sites. Optional
  Whisper/Kokoro model/package setup has download/install side effects.
- Some existing Mark-LV action implementations call Gemini directly, so a
  local main-conversation provider would not by itself enforce local-only data
  handling for those actions.
- The UI's “Ollama (Private, Local)” label overstates current runtime behavior.

### Inferences / unknowns

- Whether `ollama` is installed, where it resides, whether a Windows service or
  desktop app owns the endpoint, and whether it is reachable cannot be inferred
  from source or safe example config.
- Actual configured model/provider/host and API key presence were not read;
  local private configuration was deliberately excluded.
- Cold-load performance, model tool-call quality, function schema support, and
  user experience are unverified without runtime tests.
- The source sends the configured tool declarations and context to Gemini in
  the active Live path; exact provider retention/processing policy is outside
  this static audit.
- Availability of a speech-only Gemini API and its current SDK contract is not
  established by this repository.

## 9. Recommended architecture

Keep the single authority in Mark-LV and split these responsibilities:

1. **Provider selection:** one Mark-LV setting selects active conversational
   LLM. Keep configured/selected state distinct from successfully active state.
2. **Ollama manager:** Mark-LV owns a serialized, cancellable lifecycle and
   typed readiness outcomes. It checks host, exact model presence, and a
   minimal inference. It tracks a child only if it launched it. It never
   terminates an independently managed service and never installs Ollama or
   downloads a model silently.
3. **Local turn coordinator:** Mark-LV sends typed text/history and approved
   tool declarations to the selected local client; validates returned tool
   names/arguments against the Mark-LV registries; dispatches through existing
   inline/action/plugin and confirmation paths; appends results to local
   conversation history; requests the local model's final response.
4. **Voice services:** independent Mark-LV input and output provider settings.
   Their failure state must not change the selected LLM. Gemini may be used
   only through verified speech-only requests; current Gemini Live must not run
   as a parallel conversational model in Local LLM Mode.
5. **UI state:** show LLM and voice status independently. Keep startup progress
   observable, cancel stale state updates, preserve the previous active LLM
   until the new one is ready, and expose Retry/Stay controls.
6. **Action cloud policy:** review or gate every Mark-LV action/plugin that
   calls Gemini or another external service. Local LLM mode does not
   automatically make action execution local.

Do not implement mode management as a plugin. Do not adopt DIMO's `LLMGateway`,
graph, planner, tool loop, or memory system. `core/llm_client.py` may be treated
as source material or selectively reused after review, but it needs strict
readiness, process ownership, schema conversion, dispatch integration, and
safe errors before it can satisfy the target.

## 10. Smallest reversible implementation plan

1. **Recommended first slice — testable Ollama readiness/ownership service.**
   Implement a Mark-LV-owned service with injected HTTP and launcher interfaces.
   It reports structured states for endpoint reachable, configured model
   present, minimal inference passed, timeout, and failure. Serialize startup;
   preserve externally owned servers and track any launched child. Do not wire
   it into `JarvisLive`, persist a mode, or change UI behavior in this slice.
2. **Typed local turn path.** Add a Mark-LV coordinator that uses the local
   client, converts only supported Mark-LV tool declarations, validates tool
   calls, reuses Mark-LV dispatch and confirmation, and returns tool results to
   local inference. Keep the existing Gemini mode unchanged and fail closed
   without cloud fallback.
3. **Transactional provider selection/UI.** Repair engine persistence as part
   of an explicit provider-state design. Add warning, worker progress, readiness
   success, exact failure message, retry/cancel, preservation of prior active
   mode, and separate voice status. Do not mark Local LLM Mode active until
   step 1 and a real request work.
4. **Voice separation.** Add a dedicated speech path after typed local turns
   work. Prefer already-installed local STT/TTS where practical. If selecting
   Gemini speech services, verify speech-only API contracts and separately
   prove audio/text egress. Remove any silent package/model download from the
   chosen path.
5. **Action and privacy pass.** Inventory direct Gemini/network calls reachable
   from local mode; add explicit provider policy or local alternatives. Verify
   no call can create a cloud LLM answer while Local LLM Mode is active.

Rollback each slice independently. First slice can be removed without changing
startup. Typed coordinator can remain behind an explicit provider branch; revert
its wiring to the current Gemini path. UI state can revert separately without
deleting config data. Voice integration can be disabled independently. Do not
delete either existing memory store or change the default entry point.

## 11. Proposed validation matrix — not run

All items below are proposals only. No tests or runtime checks were executed.

| Scenario | Expected assertion | Status |
|---|---|---|
| Ollama already running | Reachability succeeds; no launcher call; manager does not claim process ownership. | **not run** |
| Jarvis-started Ollama | One child launched, endpoint polled, owner handle recorded only for that child. | **not run** |
| Executable missing / launch failure | Stable cause; no active-mode change; actionable error. | **not run** |
| Duplicate startup attempt | Concurrent/repeated transition reuses one in-flight startup; no second process. | **not run** |
| Configured model missing | Exact identifier check fails; no silent pull; previous active provider remains. | **not run** |
| Model load/readiness timeout | Bounded timeout; visible failed state; retry remains possible. | **not run** |
| API reachable but inference fails | Readiness does not pass on tags-only success. | **not run** |
| Successful transition | Active local mode changes only after minimal inference passes. | **not run** |
| Failure dialog text | Primary message exactly “Jarvis cannot switch to Local LLM Mode.” | **not run** |
| Prior mode on transition failure | Prior active provider remains selected for requests; no half-switched state. | **not run** |
| Retry after failure | New attempt begins once; stale completion cannot overwrite current state. | **not run** |
| Mode switch during startup/inference | Request cancellation or stale-result suppression; no old task activates provider. | **not run** |
| Exit with external Ollama | Jarvis does not terminate user-managed server. | **not run** |
| Exit with Jarvis-owned child | Only tracked child is eligible for a separately defined safe stop policy. | **not run** |
| Local inference failure | No automatic Gemini/OpenAI cloud LLM fallback. | **not run** |
| Gemini transcription → local LLM | Transcript enters local request; no Gemini conversational answer is requested. | **not run** |
| Gemini TTS speaks local response | Only local model final text is passed to selected speech service. | **not run** |
| Gemini voice failure | Voice unavailable is reported; no cloud LLM fallback occurs. | **not run** |
| Separate voice/LLM status | Local LLM can remain active while voice provider reports unavailable, and vice versa. | **not run** |
| Local tool call | Local tool request is schema/name validated and dispatched through Mark-LV registries. | **not run** |
| Tool result follow-up | Action result is appended to the local conversation and final answer comes from local model. | **not run** |
| Confirmation behavior | Existing Mark-LV UI-issued confirmation remains authoritative and model cannot self-confirm. | **not run** |
| Action-level cloud calls | Local mode blocks or explicitly surfaces every direct Gemini/network call reachable from its actions. | **not run** |

Run deterministic unit tests with injected HTTP/process fakes first. Hardware,
real Ollama/model, voice-device, cloud speech, and provider egress checks require
a later approved integration-validation phase; none are claimed here.

## 12. Go/no-go and next step

**Feasibility:** the target architecture is feasible as an incremental Mark-LV
extension. Current source does not implement it end to end. It does not support
the claim that Ollama mode is active, nor that Gemini Live is limited to
transcription/TTS.

**Go** to implementation only when a local provider can pass endpoint, exact
model, and minimal inference checks; the selected provider remains inactive
until readiness passes; one local typed turn and tool-result follow-up use the
Mark-LV dispatcher; failures retain the prior mode; and no error path silently
uses a cloud LLM. Voice work is a later separate go decision after the speech
provider egress is explicit.

**No-go** for wiring the current idle Ollama loop as a finished mode, calling
Gemini Live “speech-only,” adopting DIMO graph/gateway/memory as the local
foundation, or declaring offline privacy while cloud-capable actions remain
reachable without policy.

**Single recommended next implementation step:** build and unit-test the
Mark-LV-owned, injectable Ollama readiness/ownership service, without wiring it
to startup or UI. This is the lowest-risk prerequisite: it can prove readiness
and process ownership independently before any mode can claim to be active.

## Audit method and inspected files

Static reads/searches covered `main.py`; `app/marklv/main.py`, `ui.py`,
`memory/config_manager.py`, `core/llm_client.py`, `core/gemini.py`, `core/stt.py`,
`core/tts.py`, `core/installer.py`, action declarations/dispatch, and relevant
Mark-LV action implementations with Gemini call sites; DIMO
`app/services/agents/llm_gateway.py`, `app/nodes/{router,planning,llm,loop}.py`,
and related graph/memory references; safe `.env.example`; Mark-LV requirements;
and relevant architecture, feature inventory, migration, plugin strategy,
baseline, dependency, and validation documents.

No private `api_keys.json`, `.env`, certificates, or private-key contents were
read. No packages were installed. No service, process, model, network request,
external API, GUI, microphone, speaker, or OS action was started. No tests or
runtime checks were run. Findings about execution are source-backed call-path
facts; performance, machine configuration, and external API behavior remain
unverified.
