# Baseline audit

## Repository state

- Repository: `FL4K1/DIMO` (local checkout; remote URL not re-verified in this offline audit).
- Required baseline and current `HEAD`: `00051595468d6cde66c48359c56b8d81f6be221e`.
- Branch: `revamp/marklv-parent-dimo-integration`, tracking `origin/revamp/marklv-parent-dimo-integration`.
- Working tree: no tracked changes at audit start. Three untracked certificate paths existed: `app/marklv/config/certs/jarvis-ca.cer`, `app/marklv/config/certs/jarvis-ca.crt`, `app/marklv/config/certs/jarvis-ca.key`. They were not opened or modified.
- No `AGENTS.md` was found in the repository file listing.

## Entry points and startup

- Root entry: `main.py`. Its `main()` inserts `app/marklv` on `sys.path` and imports/calls `app.marklv.main.main()`. Consequently, the documented `python main.py` currently starts Mark-LV, not the root file's DIMO `main_text()`/`main_voice()` flow.
- Mark-LV entry: `app/marklv/main.py`; `main()` creates `JarvisUI`, starts a daemon thread that waits for API key configuration and runs `JarvisLive.run()` with `asyncio.run`, then enters the Qt event loop.
- DIMO paths remain implemented in root `main.py`: `main_text()` and `main_voice()` build `app.graph.graph.build_graph()`, but the root dispatcher does not call either. Their reachability through other callers was not established.
- Mark-LV setup documentation says to run `python setup.py` from `app/marklv` to install `app/marklv/requirements.txt`; root README documents `python main.py`, optional `python main.py --voice`, `pip install -r requirements.txt`, and `playwright install chromium`. Those commands were found in docs, not executed. The current root `main()` does not parse `--voice`, so the README's voice command does not currently select `main_voice()` through that dispatcher.

## Platform and dependencies

- Root README describes Windows and Python 3.10+, and root dependencies include LangGraph/LangChain/Ollama, Playwright, faster-whisper, Piper/Edge TTS and Google GenAI.
- Mark-LV requirements include PyQt6, sounddevice, Google GenAI, Playwright, Windows-specific packages, FastAPI/Uvicorn, cryptography, and optional plugin extras. Its comments advertise Windows/macOS/Linux markers; several Mark-LV actions and DIMO tools are Windows-specific.
- Mark-LV uses JSON config under `app/marklv/config/api_keys.json` (path derived in `app/marklv/main.py` and `app/marklv/memory/config_manager.py`). DIMO loads dotenv in root `main.py`; model settings include `OLLAMA_HOST`, `ROUTER_MODEL`, and `LLM_MODEL`; `LLMGateway` reads `GEMINI_API_KEY`. Do not infer that a `.env` exists or inspect its values.
- Model/runtime services and external integrations are not validated in this audit. Ollama availability/models, microphone/audio devices, Gemini credentials/network, browser installation/logins, and Windows integrations remain environment dependent.

## Security/configuration finding

`git ls-files` shows tracked `app/marklv/config/certs/jarvis.key` and `jarvis.crt`. Three CA certificate/key paths listed above are untracked. Key contents were not read. The tracked private-key path merits owner/security review; presence alone does not establish whether the material is live or safe to publish. The dashboard code can generate certificates at runtime in the same directory. No credentials or key contents are reproduced here. No history rewriting or rotation was performed.

## Audit execution record

- Ran read-only Git metadata/status commands, `rg --files`, `rg` call-site searches, and `Get-Content` reads of source/config documentation.
- Did not run application commands, tests, dependency installation, network requests, or external integrations. No command is claimed to work based solely on documentation.
- No production code was changed. Documentation deliverables are added under `docs/revamp/`.
