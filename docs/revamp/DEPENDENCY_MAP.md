# Dependency and request maps

## Startup observed in root entry

```text
python main.py
  -> main.py:main()
     -> prepend app/marklv to sys.path (supports Mark-LV's absolute imports)
     -> app.marklv.main:main()
        -> JarvisUI("face.png")
        -> background runner waits for API-key configuration
           -> JarvisLive(ui).run() [asyncio event loop]
              -> Mark-LV registries and config / audio / model session
              -> DashboardServer is attempted during run setup
        -> Qt root.mainloop()
```

`main.py` also defines DIMO `main_text()`/`main_voice()` with model verification, graph construction and a terminal interaction loop. The module's final `main()` does not call them. Their alternate invocation route is unknown from inspected callers.

## Mark-LV user request (observed design/call sites)

```text
HUD text callback or Gemini Live voice input
  -> JarvisLive request/session handling (app/marklv/main.py)
  -> system prompt assembled from Mark-LV memory + inline declarations
     + discovered actions + discovered plugins
  -> Gemini Live function call (configured/live model path)
  -> inline tool dispatch OR actions/<file>.py registry OR plugins/<file>.py registry
  -> confirmation gate / optional undo registration / action or plugin result
  -> tool result returned to live session; follow-up model response/audio
  -> session log; session summary saved at end; durable memory/config updates
```

Exact event ordering varies by tool path; validate before refactoring. Dashboard `/api/command` and phone-audio websocket feed the UI/session callbacks; UI and local microphone share request handling.

## DIMO graph request (implemented but not root default)

```text
main_text() / main_voice()
  -> simple short input: fast_chat_response (ROUTER_MODEL, Ollama), bypass graph
  -> otherwise StateGraph: router -> [chat/memory -> llm] or [search/tool -> planning -> loop -> llm]
  -> loop validates TOOL_CATALOG, calls app.tools.native/browser/service implementation
  -> LLM synthesis -> response to caller
  -> background app.memory extraction after full graph result
```

DIMO graph setup: `app/graph/graph.py`; state: `app/graph/state.py`; routing/planning/execution/synthesis: `app/nodes/`. Voice implementation is separate in `app/nodes/voice.py`.

## Bridge points and overlaps

- `main.py` imports Mark-LV only in its final dispatcher and adds `app/marklv` to `sys.path` to satisfy absolute imports such as `core.*`, `actions.*`, `memory.*`, and `dashboard.*`.
- `app/tools/native/system.py` imports `core.confirm` for dangerous setting changes; `app/tools/native/files.py` imports `core.undo` and `send2trash` for create operations. These imports depend on Mark-LV's `sys.path` mutation and become unavailable if DIMO's graph is invoked without that path setup.
- Mark-LV imports mostly its own top-level package modules; DIMO imports primarily `app.*`. Search found no broad Mark-LV-to-DIMO import dependency, but there are intentional DIMO-to-Mark-LV safety bridges.
- DIMO includes LangGraph state/nodes/tools and separate memory, browser and model gateway. Mark-LV includes Gemini Live UI/session, inline tools plus dynamic action/plugin registries, own memory/config, audio and remote dashboard. Similar feature names do not establish duplicate behavior.
- No static Python import cycle was established by this text audit. Runtime/plugin imports are dynamic; import order and `sys.path` behavior need execution-level validation.

## Model/network and persistence boundaries

- Mark-LV's Gemini Live session is cloud-backed; `core/gemini.py` has live model selection/failure handling. Mark-LV's `core/llm_client.py` and persisted engine config support other provider paths including Ollama.
- DIMO `config/models.py`, nodes and `LLMGateway` support local Ollama; gateway calls Gemini for model names prefixed `gemini`. Browser/search/weather/flight integrations can use the network regardless of local model selection.
- Mark-LV config/memory use JSON beneath `app/marklv`; DIMO memory uses `app/memory/long_term.json`. Dashboard uses HTTP endpoints/websockets and certificate/login code. Data flows and credential persistence should be validated using disposable profiles.
