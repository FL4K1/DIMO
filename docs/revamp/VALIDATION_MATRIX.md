# Validation matrix

No application or test commands were run during the audit. Commands below are candidates found in repository docs or inferred from test files; run only in a prepared disposable environment and classify side effects first. A documented command is not evidence that it works.

| Area | Candidate validation | Side effects / manual checks |
|---|---|---|
| Root startup | `python main.py` (documented) | Starts Qt and waits for config/API-key setup; verify actual startup path and graceful shutdown. |
| Mark-LV setup | `python app/marklv/setup.py` (setup docs describe `python setup.py` from Mark-LV directory; exact root invocation not verified) | Installs dependencies; do not run as an audit smoke test. |
| DIMO startup tests | `python Testing/test_startup.py` | Imports registry, planner, executor, browser and memory; may initialize browser/system components. Inspect before execution. |
| DIMO test collection | `pytest --collect-only Testing` (candidate inferred; pytest availability unknown) | Collection imports modules. Does not validate external services. |
| DIMO test scripts | `python Testing/test_*.py` | Many are standalone live integration scripts despite `test_` names; inspect each before running. Messaging, browser, GUI automation, flights, vision, code execution and model tests may change state or contact services. |
| Registry/tool schema | `python Testing/audit_tools.py` or safe unit fixtures | `audit_tools.py` includes callable tool paths; inspect its allowlist before running. Ensure tools are not actually executed against user state. |
| Ollama/local model | `python Testing/test_ollama.py` | Contacts Ollama and performs inference; use only with an approved local test instance and test prompts. |
| Gateway/cloud | `python Testing/test_gateway.py` | May call Gemini and depends on configured credentials/network. Do not expose env/config values in logs. |
| GUI/HUD/avatar | Manual launch through root entry | Supported desktop, Qt/audio rendering, PTT, text input, interrupt and shutdown. |
| Mark-LV actions/plugins | Fixture-based discovery tests for `discover_actions` and `discover_plugins` | Use temporary copied plugin directories; verify invalid imports and collisions are isolated; do not install arbitrary plugins. |
| Confirmation/undo | Manual interface tests plus deterministic token/stack tests | Verify model cannot mint confirmation, UI approval/rejection/expiry, and inverse operation coverage per tool. |
| Memory | Tests against copied config/memory files | Save/search/forget/session summary and no secret logging; test cloud/local extraction separately. |
| Dashboard/mobile | Manual local-only FastAPI checks, then phone/LAN checks in isolated network | Login, device pairing/revocation, TLS, command authorization, upload limits, websocket audio, firewall binding. Never output certificate/private-key material. |
| Offline behavior | Run marked-local feature checks with network disabled and Ollama available | Verify cloud requests fail closed or behave as documented; browser/search/weather/flight features are network-dependent. |

## Environment caveats

The repository has two requirements files and different stacks. Root README commands describe DIMO while root `main.py` currently dispatches to Mark-LV. No dependency installation, model download, browser launch, network access, hardware check, or test execution occurred in this audit. Tracked `app/marklv/config/certs/jarvis.key` and untracked CA key/certificate paths require security review; their contents were not inspected or reported.
