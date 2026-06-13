"""
Tool execution loop node — Mark-XXXIX-OR-main architecture port.

Upgrades over old loop.py:
  - Consumes the new full step-schema from planning.py (not flat tool-name list)
  - _inject_context(): fills empty file_controller write content from prior results
  - _translate_to_goal_language(): translates injected content to user's language via Ollama
  - Replan retry: on step failure calls replan() and restarts (max MAX_REPLAN_ATTEMPTS)
  - Special tool handling: save_memory and shutdown_dimo are intercepted before dispatch
  - _summarize(): after success, one-sentence Ollama summary addressed to user
  - Uses llama3:8b for loop decisions (more capable than planner's 3b)
  - Existing validate_tool_args() and execute_single_tool() are kept and enhanced
"""

import json
import os
import re as _re
import sys
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Callable

from dotenv import load_dotenv
from ollama import Client  # type: ignore
from langchain_core.messages import HumanMessage, AIMessage  # type: ignore

from app.graph.state import DimoState
from app.tools.registry import TOOL_CATALOG, get_tool
from app.utils.json_parser import extract_json_from_text
from app.config.logging import logger

load_dotenv()

OLLAMA_HOST  = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LLM_MODEL    = os.getenv("LLM_MODEL", "llama3:8b")   # executor uses 8b

MAX_REPLAN_ATTEMPTS = 2

# Matches [result from step 1], [step_1_result], [step 2 result], etc.
_PLACEHOLDER_RE = _re.compile(
    r'\[(?:result from step |result of step |step_?)(\d+)(?:[_ ]result)?\]',
    _re.IGNORECASE,
)

# ── Runtime session reference (optional, set by runtime layer) ────────────────
_session = None

def set_session(session) -> None:
    """Inject a DimoSession so the executor can update UI state."""
    global _session
    _session = session


# ══════════════════════════════════════════════════════════════════════════════
# TOOL ARGUMENT VALIDATION  (kept from old loop.py, unchanged)
# ══════════════════════════════════════════════════════════════════════════════

def validate_tool_args(tool_name: str, args: dict) -> tuple[bool, str]:
    """Validate tool name and args against registry schema."""
    if tool_name not in TOOL_CATALOG:
        return False, f"Tool '{tool_name}' not found in catalog"

    tool_info = TOOL_CATALOG[tool_name]
    schema = tool_info.get("parameters", {})
    properties = schema.get("properties", {})
    required_fields = schema.get("required", [])

    for field in required_fields:
        if field not in args:
            return False, f"Missing required parameter '{field}' for tool '{tool_name}'"

    type_mapping = {
        "string":  str,
        "number":  (int, float),
        "integer": int,
        "boolean": bool,
        "object":  dict,
        "array":   list,
    }

    for field_name, field_value in args.items():
        if field_name not in properties:
            return False, f"Unknown field: '{field_name}'"
        expected_type_name = properties[field_name].get("type")
        if expected_type_name not in type_mapping:
            continue  # skip unsupported schema types gracefully
        expected_type = type_mapping[expected_type_name]
        if not isinstance(field_value, expected_type):
            return (
                False,
                f"Field '{field_name}' expected {expected_type_name}, "
                f"got {type(field_value).__name__}",
            )

    return True, "Arguments valid"


# ══════════════════════════════════════════════════════════════════════════════
# CONTEXT INJECTION  (ported from Mark's agent/executor.py)
# ══════════════════════════════════════════════════════════════════════════════

def _inject_context(params: dict, tool: str, step_results: dict, goal: str = "") -> dict:
    """
    If a file_controller write/create step has empty or stub content,
    fill it with the concatenated results from all prior steps.
    Optionally translate the content to the language of the user's goal.

    Mirrors Mark's _inject_context() exactly.
    """
    if not step_results:
        return params

    params = dict(params)  # copy so we don't mutate the plan

    if tool == "file_controller" and params.get("action") in ("write", "create_file"):
        content = params.get("content", "")
        if not content or len(content) < 50:
            all_results = [
                v for v in step_results.values()
                if v and len(v) > 100 and v not in ("Done.", "Completed.", "")
            ]
            if all_results:
                combined  = "\n\n---\n\n".join(all_results)
                translated = _translate_to_goal_language(combined, goal)
                params["content"] = translated
                logger.info("[Executor] 💉 Injected + translated content into file write step")

    return params


def _resolve_placeholders(params: dict, step_results: dict) -> dict:
    """
    Replace [result from step N] / [step_N_result] placeholders in any string
    parameter value with the actual output stored in step_results.

    Handles these patterns (case-insensitive):
      [result from step 1]   [step_1_result]   [step 2 result]   [step1]
    """
    if not step_results or not params:
        return params

    params = dict(params)
    for k, v in list(params.items()):
        if not isinstance(v, str):
            continue
        def _sub(m, _sr=step_results):
            n = int(m.group(1))
            # Try int key first (executor stores int keys), then str key
            resolved = _sr.get(n, _sr.get(str(n), m.group(0)))
            return str(resolved)
        new_v = _PLACEHOLDER_RE.sub(_sub, v)
        if new_v != v:
            logger.info("[Executor] [placeholder] Resolved '%s' → %s chars", k, len(new_v))
        params[k] = new_v
    return params


def _translate_to_goal_language(content: str, goal: str) -> str:
    """
    Detect the language of the user's goal and translate content into it.
    Falls back to returning content unchanged on any error.
    """
    if not goal:
        return content
    try:
        client = Client(host=OLLAMA_HOST)

        # Step 1: detect language
        detect_resp = client.generate(
            model=LLM_MODEL,
            prompt=(
                f"What language is this text written in? "
                f"Reply with ONLY the language name in English (e.g. Turkish, English, French, Hindi).\n\n"
                f"Text: {goal[:200]}"
            ),
            stream=False,
            options={"num_predict": 10},
        )
        target_lang = (detect_resp.response or "English").strip()
        logger.info("[Executor] 🌐 Detected language: %s", target_lang)

        if target_lang.lower() == "english":
            return content  # no translation needed

        # Step 2: translate
        translate_resp = client.generate(
            model=LLM_MODEL,
            prompt=(
                f"You are a professional translator. Translate the following text into {target_lang}.\n"
                f"IMPORTANT:\n"
                f"- Translate EVERYTHING, leave nothing in English\n"
                f"- Keep all facts, numbers, and data intact\n"
                f"- Keep the structure and formatting\n"
                f"- Output ONLY the translated text, nothing else\n\n"
                f"Text to translate:\n{content[:4000]}"
            ),
            stream=False,
            options={"num_predict": 2048},
        )
        translated = (translate_resp.response or content).strip()
        logger.info("[Executor] ✅ Translation done (%s)", target_lang)
        return translated

    except Exception as e:
        logger.warning("[Executor] ⚠️ Translation failed: %s", e)
        return content


# ══════════════════════════════════════════════════════════════════════════════
# SPECIAL TOOL HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

def _handle_save_memory(args: dict) -> dict:
    """Handle save_memory tool directly (no bridge, writes to memory JSON)."""
    try:
        from app.memory.memory_manager import update_memory  # noqa: PLC0415
        category = args.get("category", "notes")
        key      = args.get("key", "")
        value    = args.get("value", "")
        if key and value:
            update_memory({category: {key: {"value": value}}})
            logger.info("[Executor] 💾 save_memory: %s/%s = %s", category, key, value)
            return {"success": True, "result": "ok", "error": None, "silent": True}
        return {"success": False, "result": "", "error": "Missing key or value"}
    except Exception as e:
        return {"success": False, "result": "", "error": str(e)}


def _handle_shutdown_dimo() -> dict:
    """Handle shutdown_dimo: print farewell and schedule os._exit after 1 second."""
    import time  # noqa: PLC0415
    logger.info("[Executor] DIMO shutdown requested")
    print("\nDIMO: Goodbye! Shutting down.\n")
    def _exit():
        time.sleep(1)
        os._exit(0)
    threading.Thread(target=_exit, daemon=True).start()
    return {"success": True, "result": "Shutting down.", "error": None}


def _handle_compose_message(args: dict) -> dict:
    """
    Generate message text using the LLM. Returns the composed text as the
    result so it can be passed to the next step via placeholder resolution.
    """
    subject = args.get("subject", "a message")
    tone    = args.get("tone", "friendly")
    context = args.get("context", "")
    length  = args.get("length", "medium")

    length_guide = {
        "short":  "1-2 sentences only",
        "medium": "1 short paragraph (3-5 sentences)",
        "long":   "2-3 paragraphs",
    }.get(length.lower(), "1 short paragraph")

    prompt = (
        f"Write a {tone} message about: {subject}.\n"
        f"{('Background context: ' + context + chr(10)) if context else ''}"
        f"Length: {length_guide}.\n"
        f"Output ONLY the message text — no subject line, no 'Message:', no explanation."
    )
    try:
        client = Client(host=OLLAMA_HOST)
        resp = client.generate(
            model=LLM_MODEL,
            prompt=prompt,
            stream=False,
            options={"num_predict": 512, "temperature": 0.7},
        )
        text = (resp.response or "").strip()
        logger.info("[Executor] [compose_message] Generated %d chars", len(text))
        return {"success": True, "result": text, "error": None}
    except Exception as e:
        return {"success": False, "result": "", "error": f"compose_message failed: {e}"}


# ══════════════════════════════════════════════════════════════════════════════
# BROWSER TOOL ISOLATION
# Playwright sync_api cannot run inside an asyncio event loop (which LangGraph
# uses). Solution: dispatch all browser tools to a ThreadPoolExecutor worker
# thread that has NO event loop — exactly the environment sync_playwright needs.
# ══════════════════════════════════════════════════════════════════════════════

# All tools that use BrowserManager / playwright.sync_api
_BROWSER_TOOLS = {
    # WhatsApp
    "send_whatsapp_message", "read_last_messages",
    # Tabs
    "open_url", "new_tab_url", "close_current_tab", "list_open_tabs",
    "switch_to_tab", "get_current_url",
    # Page content
    "copy_page_content", "get_page_title", "get_page_links", "get_element_text",
    # Search
    "browser_search", "google_search", "bing_search",
    # YouTube music
    "play_song", "pause_music", "next_track", "prev_track", "get_now_playing",
    # Gemini / ChatGPT via browser
    "ask_gemini", "ask_chatgpt",
    # Mark's browser_control wrapper (also uses Playwright)
    "browser_control",
}

# Single shared executor — one thread is enough; Playwright is NOT thread-safe
# across multiple concurrent calls, but serial execution is fine.
_browser_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dimo-browser")


def _run_browser_tool(tool_func: Callable, args: dict, timeout: int = 120) -> dict:
    """
    Run a Playwright-backed tool in a dedicated worker thread.

    The thread has no asyncio event loop so sync_playwright() works correctly.
    A 120-second timeout prevents hanging DIMO if a page never loads.
    """
    future = _browser_executor.submit(tool_func, **args)
    try:
        result = future.result(timeout=timeout)
        return result if isinstance(result, dict) else {"success": True, "result": str(result), "error": None}
    except FuturesTimeoutError:
        future.cancel()
        return {"success": False, "result": "", "error": f"Browser tool timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "result": "", "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SINGLE TOOL EXECUTION
# ══════════════════════════════════════════════════════════════════════════════

def execute_single_tool(tool_name: str, args: dict) -> dict:
    """
    Execute a single tool by name with given args.

    Special tools (save_memory, shutdown_dimo) are handled directly.
    All others are dispatched via the registry function.

    Returns:
        {success: bool, result: str, error: str | None}
    """
    # ── Special tools intercepted before registry lookup ──────────────────────
    if tool_name == "save_memory":
        return _handle_save_memory(args)
    if tool_name == "shutdown_dimo":
        return _handle_shutdown_dimo()
    if tool_name == "compose_message":
        return _handle_compose_message(args)

    # ── Messaging tools — dispatch directly to Mark's pyautogui actions ───────
    if tool_name == "send_whatsapp_desktop":
        receiver     = args.get("receiver", "")
        message_text = args.get("message_text", "")
        logger.info("[Executor] [WhatsApp-desktop] → %s: %s", receiver, message_text[:50])
        from app.tools.native.messaging import send_message as _sm  # noqa: PLC0415
        return _sm(receiver=receiver, message_text=message_text, platform="WhatsApp")

    if tool_name == "send_telegram_message":
        receiver     = args.get("receiver", "")
        message_text = args.get("message_text", "")
        logger.info("[Executor] [Telegram-desktop] → %s", receiver)
        from app.tools.native.messaging import send_message as _sm  # noqa: PLC0415
        return _sm(receiver=receiver, message_text=message_text, platform="Telegram")

    if tool_name == "send_instagram_dm":
        receiver     = args.get("receiver", "")
        message_text = args.get("message_text", "")
        logger.info("[Executor] [Instagram-DM] → %s", receiver)
        from app.tools.native.messaging import send_message as _sm  # noqa: PLC0415
        return _sm(receiver=receiver, message_text=message_text, platform="Instagram")

    if tool_name == "agent_task":
        # Delegate to the planner/executor recursively for complex goals
        from app.nodes.planning import create_plan  # noqa: PLC0415
        goal = args.get("goal", "")
        sub_plan = create_plan(goal)
        sub_steps = sub_plan.get("steps", [])
        results = []
        for step in sub_steps:
            sub_tool   = step.get("tool", "web_search")
            sub_params = step.get("parameters", {})
            r = execute_single_tool(sub_tool, sub_params)
            results.append(f"[{sub_tool}]: {r.get('result', '')}")
        combined = "\n".join(results)
        return {"success": True, "result": combined or "Agent task completed.", "error": None}

    # ── Registry tools ────────────────────────────────────────────────────────
    if tool_name not in TOOL_CATALOG:
        return {"success": False, "result": "", "error": f"Tool '{tool_name}' not found"}

    tool_func = get_tool(tool_name)
    if not tool_func:
        return {"success": False, "result": "", "error": f"Tool '{tool_name}' has no function"}

    logger.info("[Executor] Executing '%s' with args: %s", tool_name, args)
    if _session:
        _session.set_state("THINKING")

    # ── Browser tools: run in isolated thread (no asyncio loop) ──────────────
    if tool_name in _BROWSER_TOOLS:
        logger.info("[Executor] [browser-thread] Routing '%s' to browser worker", tool_name)
        return _run_browser_tool(tool_func, args)

    # ── Non-browser tools: call directly ─────────────────────────────────────
    try:
        result = tool_func(**args)
    except TypeError as e:
        return {"success": False, "result": "", "error": f"Invalid args for '{tool_name}': {e}"}
    except Exception as e:
        return {"success": False, "result": "", "error": f"Tool '{tool_name}' failed: {e}"}

    # Normalise to structured dict
    if isinstance(result, dict) and "success" in result:
        out = result
    else:
        result_str = str(result).strip() if result else "Done."
        is_error = any(
            kw in result_str.lower()
            for kw in ("error", "failed", "could not", "timed out", "exception")
        )
        out = {
            "success": not is_error,
            "result":  result_str,
            "error":   result_str if is_error else None,
        }

    logger.info("[Executor] %s '%s' → %s", "✅" if out["success"] else "❌", tool_name, str(out.get("result", ""))[:80])
    return out


# ══════════════════════════════════════════════════════════════════════════════
# LLM-GUIDED LOOP DECISION (kept from old loop.py for backward compat)
# ══════════════════════════════════════════════════════════════════════════════

def ask_llm_next_action(state: DimoState) -> dict:
    """Ask the LLM what step to execute next (used when tool_plan has full step dicts)."""
    user_message    = state.get("messages", [])[-1].content if state.get("messages") else ""
    completed_tasks = json.dumps(state.get("tool_calls_made", []), indent=2)
    tool_plan       = state.get("tool_plan", [])

    # If tool_plan contains full step dicts (new schema), determine next unrun step
    if tool_plan and isinstance(tool_plan[0], dict) and "tool" in tool_plan[0]:
        completed_tools = {
            c.get("tool") for c in state.get("tool_calls_made", [])
            if c.get("result", {}).get("success", False)
        }
        for step in tool_plan:
            if step.get("tool") not in completed_tools:
                return {
                    "next_tool": step["tool"],
                    "args":      step.get("parameters", {}),
                    "reasoning": step.get("description", ""),
                    "_step":     step,  # carry full step for context injection
                }
        return {"next_tool": "DONE", "args": {}, "reasoning": "All planned steps done"}

    # Legacy: tool_plan is a flat list of tool names — ask LLM
    tools_text = ""
    for tname, tinfo in TOOL_CATALOG.items():
        tools_text += f"- {tinfo['name']}: {tinfo['description'][:80]}\n"

    completed_tool_names = [
        c.get("tool") for c in state.get("tool_calls_made", [])
        if c.get("result", {}).get("success", False)
    ]
    remaining = [t for t in (tool_plan if isinstance(tool_plan, list) else []) if t not in completed_tool_names]

    loop_prompt = f"""You are a strict task execution router.

COMPLETED TASKS:
{completed_tasks}

REMAINING TOOLS PLANNED:
{remaining}

AVAILABLE TOOLS:
{tools_text}

USER REQUEST:
"{user_message}"

Rules:
1. If the user request is already fulfilled, return "next_tool": "DONE".
2. If no remaining tools, return "next_tool": "DONE".
3. NEVER repeat a successful tool with the same args.
4. Otherwise, choose the next tool.

Return ONLY JSON: {{"next_tool": "tool_name", "args": {{}}, "reasoning": "why"}}
"""

    try:
        client = Client(host=OLLAMA_HOST)
        resp   = client.generate(model=LLM_MODEL, prompt=loop_prompt, stream=False)
        raw    = (resp.response or "").strip()
        ok, action = extract_json_from_text(raw)
        if not ok:
            return {"next_tool": "DONE", "args": {}, "reasoning": "parse error"}
        if isinstance(action, list):
            action = action[0] if action else {}
        return action if isinstance(action, dict) else {"next_tool": "DONE", "args": {}, "reasoning": "unexpected type"}
    except Exception as e:
        logger.error("[Executor] LLM loop error: %s", e)
        return {"next_tool": "DONE", "args": {}, "reasoning": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# POST-EXECUTION SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

def _summarize(goal: str, completed_steps: list) -> str:
    """Generate a natural one-sentence summary of what was accomplished."""
    fallback = f"All done. Completed {len(completed_steps)} steps for: {goal[:60]}."
    try:
        client    = Client(host=OLLAMA_HOST)
        steps_str = "\n".join(f"- {s.get('description', s.get('tool', '?'))}" for s in completed_steps)
        prompt    = (
            f'User goal: "{goal}"\n'
            f"Completed steps:\n{steps_str}\n\n"
            "Write a single natural sentence summarizing what was accomplished. "
            "Be direct and positive. No markdown."
        )
        resp = client.generate(
            model=LLM_MODEL,
            prompt=prompt,
            stream=False,
            options={"num_predict": 80},
        )
        return (resp.response or fallback).strip()
    except Exception:
        return fallback


# ══════════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION LOOP — LangGraph node
# ══════════════════════════════════════════════════════════════════════════════

def execute_tool_loop(state: DimoState) -> dict:
    """
    LangGraph node: execute planned tools in order, with replan-on-failure.

    Upgrades over old loop.py:
    - Reads full step dicts from tool_plan (parameters, description, critical)
    - Injects context between steps (_inject_context)
    - Retries failed steps up to 3 times
    - Calls replan() on persistent failures (max MAX_REPLAN_ATTEMPTS)
    - Intercepts save_memory and shutdown_dimo directly
    """
    from app.nodes.planning import replan  # noqa: PLC0415  (avoid circular at module load)

    user_message    = state.get("messages", [])[-1].content if state.get("messages") else ""
    tool_plan       = state.get("tool_plan", [])
    replan_attempts = 0
    completed_steps: list[dict] = []
    step_results:    dict       = state.get("step_results", {})      # step_num → result_str

    # Support both new (list of step dicts) and legacy (list of tool name strings)
    if tool_plan and isinstance(tool_plan[0], str):
        # Legacy flat list — convert to minimal step dicts
        tool_plan = [
            {"step": i + 1, "tool": t, "description": t, "parameters": {}, "critical": True}
            for i, t in enumerate(tool_plan)
        ]

    if not tool_plan:
        logger.info("[Executor] No tool plan — skipping loop")
        return state

    logger.info("[Executor] 🎯 Goal: %s", user_message[:100])
    logger.info("[Executor] Plan: %d steps", len(tool_plan))

    while True:
        steps   = tool_plan
        success = True
        failed_step:  dict = {}
        failed_error: str  = ""

        for step in steps:
            step_num = step.get("step", "?")
            tool     = step.get("tool", "web_search")
            desc     = step.get("description", "")
            params   = dict(step.get("parameters", {}))

            # Skip already completed steps (after a replan)
            if step_num in {s.get("step") for s in completed_steps}:
                continue

            # Resolve [result from step N] placeholders first
            params = _resolve_placeholders(params, step_results)
            # Then inject context for file writes
            params = _inject_context(params, tool, step_results, goal=user_message)

            logger.info("[Executor] ▶️ Step %s: [%s] %s", step_num, tool, desc)

            # Validate args
            is_valid, val_error = validate_tool_args(tool, params)
            _BYPASS_VALIDATION = {
                "save_memory", "shutdown_dimo", "agent_task",
                "compose_message",
                "send_whatsapp_desktop", "send_telegram_message", "send_instagram_dm",
            }
            if not is_valid and tool not in _BYPASS_VALIDATION:
                logger.error("[Executor] ❌ Arg validation: %s", val_error)
                state["loop_error_count"] = state.get("loop_error_count", 0) + 1
                state["tool_calls_made"].append({
                    "tool": tool, "args": params, "step": step_num,
                    "result": {"success": False, "result": "", "error": val_error},
                    "reasoning": desc,
                })
                if step.get("critical", True):
                    failed_step  = step
                    failed_error = val_error
                    success      = False
                    break
                continue

            # Retry loop (up to 3 attempts per step)
            step_ok  = False
            attempts = 0
            while attempts < 3:
                attempts += 1
                try:
                    result_dict = execute_single_tool(tool, params)
                    state["tool_calls_made"].append({
                        "tool":      tool,
                        "args":      params,
                        "step":      step_num,
                        "result":    result_dict,
                        "reasoning": desc,
                    })

                    if result_dict.get("success"):
                        step_results[step_num] = result_dict.get("result", "Done.")
                        completed_steps.append(step)
                        state["current_iteration"] = state.get("current_iteration", 0) + 1
                        logger.info("[Executor] ✅ Step %s done: %s", step_num, str(result_dict.get("result", ""))[:80])
                        step_ok = True
                        break
                    else:
                        err = result_dict.get("error", "unknown error")
                        logger.warning("[Executor] ⚠️ Step %s attempt %d: %s", step_num, attempts, err)
                        if attempts >= 3:
                            failed_step  = step
                            failed_error = err
                            success      = False

                except Exception as e:
                    logger.error("[Executor] ❌ Step %s attempt %d exception: %s", step_num, attempts, e)
                    if attempts >= 3:
                        failed_step  = step
                        failed_error = str(e)
                        success      = False

            if not step_ok:
                success = False
                break

            # Guard: shutdown_dimo exits immediately
            if tool == "shutdown_dimo":
                return state

        if success:
            summary = _summarize(user_message, completed_steps)
            state["tool_output"] = summary
            if _session:
                _session.set_state("SPEAKING")
            logger.info("[Executor] 🏁 All steps completed. Summary: %s", summary[:100])
            break

        # ── Replan on failure ─────────────────────────────────────────────────
        if replan_attempts >= MAX_REPLAN_ATTEMPTS:
            logger.error("[Executor] Max replan attempts reached (%d)", replan_attempts)
            state["tool_output"] = f"Task failed after {replan_attempts} replan attempts."
            state["error_message"] = failed_error
            break

        logger.info("[Executor] 🔄 Replanning after step failure (attempt %d/%d)", replan_attempts + 1, MAX_REPLAN_ATTEMPTS)
        replan_attempts += 1
        revised = replan(user_message, completed_steps, failed_step, failed_error)
        tool_plan = revised.get("steps", [])

    state["step_results"] = step_results
    logger.info("[Executor] Loop done. %d tools executed total.", len(state.get("tool_calls_made", [])))
    return state
