# DIMO Revamp — Phase 2: LangGraph Integration Readiness Audit

**Document:** `docs/revamp/GRAPH_INTEGRATION_READINESS.md`  
**Repository:** `FL4K1/DIMO`  
**Working Branch:** `revamp/marklv-parent-dimo-integration`  
**Review Subject:** Delegated LangGraph Sub-Orchestrator Readiness  
**Author:** Senior Software Architect  
**Status:** Read-Only Architectural Audit Complete  

---

## 1. Executive Recommendation: CONDITIONALLY READY

DIMO's LangGraph execution engine is **CONDITIONALLY READY** to be integrated as a delegated reasoning capability behind Mark-LV's action system, subject to **four mandatory security and architectural preconditions**:

1. **Safety Gate Remediation (Blocker):** The existing confirmation bridge in `app/tools/native/system.py` attempts to import a non-existent `confirm_gate` object from `core.confirm` and catches `ImportError` silently, which causes system `shutdown` and `restart` actions to **fail open** (executing immediately without user confirmation). Furthermore, file deletion (`files.py:delete`) and simulated keystroke messaging (`messaging.py`) possess zero confirmation gates or undo tracking.
2. **Read-Only / Sandboxed Tool Allowlist for Initial Adapter:** The graph adapter must initially expose only read-only, informational, and search capabilities (e.g. `web_search`, `browser_control:search`, `file_controller:list/read`). Mutating, messaging, and system-control tools must be withheld from the planner until formal authorization interceptors are implemented.
3. **Execution Timeouts & UI Progress Forwarding:** A full LangGraph traversal performs 3 to 5 sequential local LLM inferences (router, planner, tool execution, optional translation, and response synthesis), requiring 15–45 seconds on typical consumer hardware. The adapter must run asynchronously off Mark-LV's main thread and stream status updates to Mark-LV's HUD (`player.write_log`).
4. **State Initialization Integrity:** LangGraph nodes expect an explicit `DimoState` dictionary. The adapter must populate the complete state schema to prevent node crashes or unintentional routing to unhandled channels.

**Under no circumstances should the DIMO graph replace Mark-LV's main runtime or execute high-impact native tools without resolving these gaps.**

---

## 2. Traced Execution-Flow Diagram

The following diagram traces the complete end-to-end execution path from a user request in Mark-LV to LangGraph invocation and back:

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Voice / Remote
    participant JL as Mark-LV JarvisLive (main.py)
    participant ActReg as ActionRegistry (action_loader.py)
    participant Adapt as DIMO Graph Action Adapter (actions/dimo_deep_task.py)
    participant Graph as LangGraph StateGraph (graph.py)
    participant Router as Router Node (router.py)
    participant Planner as Planning Node (planning.py)
    participant Loop as Loop / Executor Node (loop.py)
    participant NativeTool as DIMO Tool Catalog (registry.py)
    participant Safety as Mark-LV Safety (core/confirm.py & undo.py)
    participant LLM as LLM Synthesis Node (llm.py)
    participant HUD as Mark-LV HUD (ui.py)

    User->>JL: "Research the latest Python releases and summarize them"
    JL->>ActReg: _execute_tool("dimo_deep_task", {"goal": "..."})
    ActReg->>Adapt: run(parameters={"goal": "..."}, ctx={"player": ui, ...})
    
    rect rgb(240, 245, 255)
        note over Adapt,Graph: Phase 1: State Setup & Graph Invocation
        Adapt->>Adapt: Build full DimoState with HumanMessage(goal)
        Adapt->>HUD: write_log("[deep_task] Initializing multi-step planning...")
        Adapt->>Graph: graph.invoke(initial_state)
    end

    rect rgb(255, 250, 240)
        note over Graph,Loop: Phase 2: Planning & Execution
        Graph->>Router: route_intent(state) [Calls Ollama router_model: 3b]
        Router-->>Graph: state["router_result"] = "tool"
        Graph->>Planner: plan_tools(state) [Calls Ollama planner_model: 3b]
        Planner-->>Graph: state["tool_plan"] = [step 1: web_search, step 2: compose_message]
        Graph->>Loop: execute_tool_loop(state)
        
        loop For each planned step
            Loop->>Loop: _resolve_placeholders(params) & _inject_context()
            Loop->>NativeTool: execute_single_tool("web_search", params)
            critical Safety Check Gate
                NativeTool-->>Safety: Check confirmation token & push undo
            end
            NativeTool-->>Loop: {"success": True, "result": "..."}
            Loop->>HUD: write_log("[deep_task] Step 1 complete...")
        end
        Loop-->>Graph: state["tool_calls_made"], state["step_results"]
    end

    rect rgb(240, 255, 245)
        note over Graph,JL: Phase 3: Synthesis & Response Return
        Graph->>LLM: call_llm(state) [Calls Ollama llm_model: 8b]
        LLM-->>Graph: state["messages"].append(AIMessage(content=summary))
        Graph-->>Adapt: final_state dict
        Adapt-->>ActReg: String summary extracted from final AIMessage
        ActReg-->>JL: Tool result string
        JL-->>User: Spoken voice reply & HUD display update
    end
```

---

## 3. Minimum Graph State & Initialization Contract

### 3.1 Analysis of Node State Expectations
- **`router.py`:** Requires `state["messages"][-1]` to exist and expose `.content` or stringifiable text. If missing, logs a warning and defaults `router_result` to `"chat"`.
- **`planning.py`:** Requires `state["messages"][-1].content` as the planning goal. Writes `state["tool_plan"]` (list of step dicts) and `state["planning_context"]`.
- **`loop.py`:** Requires `state["tool_plan"]` and accesses `state.get("step_results", {})`, `state.get("tool_calls_made", [])`, and `state.get("current_iteration")`.
- **`llm.py`:** Formats `state["messages"]`, injects `state.get("planning_context")` and `state.get("tool_calls_made", [])`, and appends an `AIMessage` to `state["messages"]`.

### 3.2 Authoritative Initialization Contract
The adapter must initialize all keys defined in `DimoState` ([`app/graph/state.py`](file:///c:/Users/Mudit%20Joshi/Desktop/Projects/DIMO/app/graph/state.py#L4-L85)). Calling `graph.invoke()` with an incomplete dictionary causes `KeyError` or unexpected branching.

```python
from langchain_core.messages import HumanMessage
from typing import Any

def create_initial_graph_state(user_goal: str, session_id: str = "marklv_delegated") -> dict[str, Any]:
    """Constructs the canonical minimum state required to execute DIMO's compiled graph."""
    return {
        # Conversation Layer
        "messages": [HumanMessage(content=user_goal.strip())],
        "summary": "",
        
        # Routing & Intent Layer
        "current_intent": "tool",
        "router_result": "tool",      # Set to 'tool' to force planner traversal
        
        # Memory Layer (Stubbed for delegated invocation)
        "summary_ask_counter": 0,
        "episodic_memory_query": None,
        "episodic_recall": None,
        "facts": None,
        "user_profile": None,
        
        # Tool Execution Layer
        "next_tool": None,
        "tool_history": [],
        "tool_output": None,
        "tool_plan": None,
        "tool_calls_made": [],
        "step_results": {},
        
        # Loop Control & Metadata
        "max_iterations": 5,
        "current_iteration": 0,
        "planning_context": None,
        "should_continue": True,
        "loop_error_count": 0,
        "session_id": session_id,
        "error_message": None,
    }
```

---

## 4. Tool Risk Matrix & Verified Protections

Inspection of [`app/tools/registry.py`](file:///c:/Users/Mudit%20Joshi/Desktop/Projects/DIMO/app/tools/registry.py#L65-L350) and native implementations under `app/tools/native/` reveals significant discrepancies in authorization enforcement:

| Tool Name | Subsystem / File | Risk Level | Description of Operation | Verified Protections in DIMO Code | Security & Safety Verdict |
|---|---|---|---|---|---|
| `web_search` | `app/tools/search.py` | **Low** | DuckDuckGo web search (headless) | Read-only network request | **Safe** for delegated execution. |
| `list_open_tabs` | `app/browser/tabs.py` | **Low** | Lists open Chromium tab titles and URLs | Read-only context query; no launch | **Safe** for delegated execution. |
| `file_controller:read` | `app/tools/native/files.py` | **Low** | Reads text file contents from disk | Read-only filesystem access | **Safe** for delegated execution. |
| `file_controller:list` | `app/tools/native/files.py` | **Low** | Directory enumeration | Read-only filesystem access | **Safe** for delegated execution. |
| `weather_report` | `app/tools/native/weather.py` | **Low** | Weather query | Read-only network request | **Safe** for delegated execution. |
| `flight_finder` | `app/tools/native/flights.py` | **Low** | Flight pricing search query | Read-only network request | **Safe** for delegated execution. |
| `youtube_video:get_info` | `app/tools/native/youtube.py` | **Low** | Video metadata fetch | Read-only network request | **Safe** for delegated execution. |
| `file_controller:create_file` | `app/tools/native/files.py` | **Medium** | Writes new file to disk | Pushes undo callable to `core.undo` (if available) | **Conditionally Safe** (requires `core.undo` on path). |
| `file_controller:write` | `app/tools/native/files.py` | **High** | Overwrites or appends to existing file | **None.** No undo, no confirmation | **Vulnerable.** Can destroy file contents without confirmation. |
| `file_controller:delete` | `app/tools/native/files.py` | **Critical** | Deletes file permanently | **None.** No undo, no confirmation | **Vulnerable.** Bypasses Mark-LV delete protections. |
| `send_whatsapp_desktop` | `app/tools/native/messaging.py` | **Critical** | Types contact & message, sends via PyAutoGUI | **None.** Simulated keystrokes sent blind | **Vulnerable.** Cannot be undone; no human approval. |
| `send_telegram_message` | `app/tools/native/messaging.py` | **Critical** | Simulates keystrokes in Telegram | **None.** Blind PyAutoGUI automation | **Vulnerable.** Cannot be undone; no human approval. |
| `computer_settings:shutdown` | `app/tools/native/system.py` | **Critical** | Shuts down host operating system | **Broken.** Imports non-existent `confirm_gate` | **Critical Vulnerability.** Fails open and executes immediately! |
| `computer_settings:restart` | `app/tools/native/system.py` | **Critical** | Reboots host operating system | **Broken.** Imports non-existent `confirm_gate` | **Critical Vulnerability.** Fails open and executes immediately! |
| `computer_control` | `app/tools/native/automation.py` | **Critical** | Arbitrary mouse/keyboard/window automation | **None.** Direct OS input injection | **Vulnerable.** Unconstrained execution. |

---

## 5. Specific Confirmation & Undo Integration Gaps

### 5.1 Critical Flaw: The `confirm_gate` Import Failure in `system.py`
In [`app/tools/native/system.py`](file:///c:/Users/Mudit%20Joshi/Desktop/Projects/DIMO/app/tools/native/system.py#L16-L36):
```python
if action in ("restart", "shutdown"):
    token = kwargs.get("token")
    try:
        from core.confirm import confirm_gate  # <--- CRITICAL BUG
        if not confirm_gate.verify(token):
            confirm_gate.request(...)
            return {"success": False, "result": "", "error": "Confirmation required..."}
    except ImportError:
        pass  # <--- SILENT FALLTHROUGH
        
result = service.execute_action(action, value)  # <--- SHUTDOWN EXECUTES IMMEDIATELY!
```
- **Code Reality:** Mark-LV's [`app/marklv/core/confirm.py`](file:///c:/Users/Mudit%20Joshi/Desktop/Projects/DIMO/app/marklv/core/confirm.py#L68-L153) exposes top-level functions `request()`, `resolve()`, and `bind()`. There is **no object or class named `confirm_gate`**.
- **Consequence:** `from core.confirm import confirm_gate` raises `ImportError` on every invocation. The `except ImportError: pass` block silently catches the error, bypasses confirmation entirely, and calls `service.execute_action("shutdown")`.
- **Verdict:** DIMO's system tool is completely unguarded against accidental or hallucinated shutdown commands.

### 5.2 Retry-Loop Storm on Pending Confirmations
Even if `core/confirm.py:request()` were correctly called:
- `request()` registers a UI banner and returns immediately with `[CONFIRMATION_PENDING]`.
- Inside [`app/nodes/loop.py`](file:///c:/Users/Mudit%20Joshi/Desktop/Projects/DIMO/app/nodes/loop.py#L616-L650), any tool return where `success=False` is treated as a transient failure. The loop immediately **retries the step 3 times in rapid succession**, triggering multiple confirmation requests and logging error warnings before aborting to `replan()`.
- The LangGraph loop model assumes synchronous, non-interactive tool resolution and has no native concept of parking state while awaiting out-of-band human confirmation.

### 5.3 Asymmetric Undo Coverage in File Controller
In [`app/tools/native/files.py`](file:///c:/Users/Mudit%20Joshi/Desktop/Projects/DIMO/app/tools/native/files.py#L21-L68):
- `create_file` and `create_folder` push an undo closure to `core.undo.push_undo` wrapping `send2trash`.
- However, `action == "delete"` and `action == "write"` (destructive overwrite) do **not** register undo entries or backups.
- Mark-LV's parent file action ([`app/marklv/actions/file_controller.py`](file:///c:/Users/Mudit%20Joshi/Desktop/Projects/DIMO/app/marklv/actions/file_controller.py#L280-L310)) captures file contents into rollback closures before writing. Invoking DIMO's `file_controller` via the graph bypasses these protections.

---

## 6. Proposed Ownership Boundaries

To eliminate competing architectures and preserve system stability, responsibilities must be strictly partitioned:

| System Responsibility | Owner | Architectural Boundary & Mechanism |
|---|---|---|
| **Top-Level User Interaction** | **Mark-LV** | Qt HUD, voice wake-word, Push-To-Talk, and phone dashboard belong exclusively to Mark-LV. |
| **Multi-Step Reasoning & Planning** | **DIMO LangGraph** | Invoked strictly as a worker sub-agent (`dimo_deep_task`) for complex multi-tool goals. |
| **Tool Execution Authorization** | **Mark-LV** | All high-impact and destructive actions must be vetted by Mark-LV before execution. |
| **Hardware Audio & Voice Output** | **Mark-LV** | Gemini Live audio streaming and local TTS owned by Mark-LV. LangGraph never opens audio devices. |
| **Persistent Long-Term Memory** | **Mark-LV** | Mark-LV's `memory.json` remains authoritative. DIMO fact extraction acts only as an advisory feeder. |
| **Intermediate Progress Reporting** | **Bridge** | LangGraph loop updates forwarded via `player.write_log` to Mark-LV HUD in real time. |

---

## 7. Smallest Viable Adapter Design (`dimo_deep_task`)

The smallest, safest adapter that can integrate LangGraph without compromising system protections is a single Mark-LV Action file: `app/marklv/actions/dimo_deep_task.py`.

### 7.1 Action Declaration Contract
```python
TOOL = {
    "name": "dimo_deep_task",
    "description": (
        "Delegates a complex, multi-step goal to DIMO's autonomous planning engine. "
        "Use this for research, multi-query web investigations, data synthesis, "
        "and tasks requiring chained reasoning across multiple tools."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "goal": {
                "type": "STRING",
                "description": "Clear natural language description of the complex task to accomplish."
            }
        },
        "required": ["goal"]
    },
    "handler": dimo_deep_task_handler,
}
```

### 7.2 Handler Architecture & Invariants
```python
def dimo_deep_task_handler(parameters: dict = None, player=None, **kwargs) -> str:
    goal = (parameters or {}).get("goal", "").strip()
    if not goal:
        return "No goal specified for deep task."

    # 1. Verification of Ollama availability
    if not _check_ollama_ready():
        return "Autonomous planner is currently unavailable (Ollama is not running on localhost:11434)."

    # 2. Construction of full canonical DimoState
    initial_state = create_initial_graph_state(user_goal=goal)

    # 3. Execution off-thread with timeout guard
    try:
        from app.graph.graph import build_graph
        graph = build_graph()
        
        if player:
            player.write_log(f"[deep_task] Planning: {goal[:50]}...")

        # Run with 60-second execution deadline
        result = _run_with_timeout(lambda: graph.invoke(initial_state), timeout=60.0)
        
        # 4. Extract synthetic response from final AIMessage
        if result and result.get("messages"):
            last_msg = result["messages"][-1]
            return last_msg.content if hasattr(last_msg, "content") else str(last_msg)
            
        return "Deep task completed, but no response was generated."

    except TimeoutError:
        return f"Deep task timed out after 60 seconds while processing: '{goal[:40]}'."
    except Exception as e:
        return f"Deep task encountered an error: {e}"
```

### 7.3 Tool Sandboxing Invariant
During initial deployment, the adapter must restrict `TOOL_CATALOG` exposed to `planning.py` to an allowlist of read-only tools:
`ALLOWED_GRAPH_TOOLS = {"web_search", "weather_report", "flight_finder", "list_open_tabs", "file_controller:read", "file_controller:list"}`.

---

## 8. Phased Validation Plan with Rollback Conditions

| Phase | Test Objective | Validation Method | Success Metric | Rollback Trigger |
|---|---|---|---|---|
| **Phase 2.1: Pre-Integration Sandbox** | Verify graph compilation and state traversal in isolation | Run headless test script invoking `build_graph()` with read-only search goal | Graph completes `router -> planning -> loop -> llm` without exceptions | Any crash on missing state keys or unhandled node output |
| **Phase 2.2: Safety Gate Interceptor** | Fix `system.py` confirmation bridge | Unit test asserting `confirm_gate` import is replaced with `core.confirm.request` | `restart` and `shutdown` refuse execution without active HUD token | Any possibility of unconfirmed shutdown execution |
| **Phase 2.3: Adapter Discovery** | Verify Mark-LV auto-discovers `dimo_deep_task` | Isolated test with `ActionRegistry.discover_actions()` | `ActionRegistry.has("dimo_deep_task") == True` | Action collision or rejection by `_validate()` |
| **Phase 2.4: Timeout & Failure Invariant** | Verify graceful degradation when Ollama is offline | Invoke action with simulated connection timeout | Returns user-friendly error string within 5s; no freeze | Unhandled exception or thread deadlock |

---

## 9. Exact First Implementation Task

If and when integration is approved, the exact first implementation task must be:

**Task:** Remediate the Confirmation Gate Vulnerability in `app/tools/native/system.py`  
- **Action:** Replace the invalid `from core.confirm import confirm_gate` with the correct `core.confirm.request()` API, and remove the dangerous `except ImportError: pass` fallthrough.  
- **Scope:** 15 lines in `app/tools/native/system.py`.  
- **Prerequisite for Graph:** Must be completed and verified before any action adapter exposes system management or destructive operations to LangGraph planning.

---

## 10. Unresolved Questions Requiring Runtime Investigation

1. **Multi-Model VRAM Contention:**
   - *Question:* When running locally, does concurrent execution of `llama3:8b` (loop/LLM) and `llama3.2:3b` (router/planner) in Ollama cause GPU memory eviction, thrashing, or high latency on 6GB/8GB VRAM systems?
   - *Test Required:* Benchmark memory footprint and turn latency during back-to-back tool replan cycles on target hardware.
2. **Re-entrant Thread Safety in Playwright:**
   - *Question:* `loop.py` uses a single-worker `ThreadPoolExecutor` (`dimo-browser`) for Playwright calls. If Mark-LV's parent `browser_control` action is invoked simultaneously by a voice command while LangGraph is running, do the two Playwright contexts conflict?
   - *Test Required:* Stress test concurrent browser navigation from both Mark-LV HUD and LangGraph loop.
3. **Session Interruption Handling:**
   - *Question:* When a user taps Mark-LV's HUD "INTERRUPT" button or speaks a barge-in command, how should an active background LangGraph thread be cleanly cancelled without leaving orphaned sub-processes or zombie browser pages?
   - *Test Required:* Design a cooperative cancellation token passed into `DimoState`.

---

## 11. Acceptance Checklist

- [x] Clear readiness determination made with concrete justifications.
- [x] Complete traced execution-flow diagram provided.
- [x] Authoritative `DimoState` initialization contract specified.
- [x] Comprehensive Tool Risk Matrix covering all native capabilities.
- [x] Critical safety flaw in `system.py` confirmation bridge identified with exact code references.
- [x] Clear ownership boundaries established between Mark-LV parent and DIMO graph.
- [x] Smallest viable adapter design (`dimo_deep_task`) documented.
- [x] Phased validation plan with explicit rollback conditions defined.
- [x] Zero application source code modified during this audit.
