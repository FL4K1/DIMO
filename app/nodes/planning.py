"""
Tool planning node — Mark-XXXIX-OR-main architecture port.

Replaces the old flat ["tool1", "tool2"] planner with a full step-by-step
JSON planner that mirrors agent/planner.py from Mark-XXXIX-OR-main.

Key upgrades vs. old planning.py:
  - Strict output schema: {goal, steps:[{step, tool, description, parameters, critical}]}
  - generated_code guard: any step using that tool is replaced with web_search
  - Fallback plan: if JSON parse fails, returns a single web_search step
  - replan(): accepts goal + completed steps + failed step + error → revised plan
  - Uses llama3.2:3b (fast, confirmed in DIMO's Ollama) for planning
  - Planner prompt built from TOOL_CATALOG (get_tool_schema_text())

Exports used by the LangGraph graph:
  plan_tools(state)  — LangGraph node wrapper (updates state in-place)

Exports used by the executor loop for replan:
  create_plan(goal, context)
  replan(goal, completed_steps, failed_step, error)
  _fallback_plan(goal)
"""

import json
import re
import os
import logging
from datetime import datetime

from dotenv import load_dotenv
from ollama import Client  # type: ignore

from app.graph.state import DimoState
from app.tools.registry import TOOL_CATALOG, get_tool_schema_text
from app.utils.json_parser import extract_json_from_text
from app.config.logging import logger

load_dotenv()

OLLAMA_HOST    = os.getenv("OLLAMA_HOST", "http://localhost:11434")
PLANNER_MODEL  = os.getenv("PLANNER_MODEL", "llama3.2:3b")   # fast, strict JSON


# ══════════════════════════════════════════════════════════════════════════════
# PLANNER PROMPT — mirrors Mark's PLANNER_PROMPT structure exactly
# ══════════════════════════════════════════════════════════════════════════════

def _build_planner_prompt() -> str:
    """Build the system prompt from the live TOOL_CATALOG. Called once per plan."""
    tool_schema = get_tool_schema_text()
    now = datetime.now().strftime("%A, %B %d, %Y — %I:%M %p")
    return f"""You are the planning module of DIMO, a personal AI assistant.
Your job: break any user goal into a sequence of steps using ONLY the tools listed below.

CURRENT DATE & TIME: {now}

ABSOLUTE RULES:
- NEVER use generated_code. It does not exist.
- Use web_search for ANY information retrieval, research, or current data.
- Use file_controller to save content to disk ONLY when user explicitly says "save to file", "write to file", "create a file", or "export".
- Use computer_settings or computer_control for any single system command.
- Max 5 steps. Use the minimum steps needed.
- Return ONLY valid JSON — no markdown, no explanation, no code blocks.

CONTENT GENERATION vs FILE CREATION — CRITICAL DISTINCTION:
- "write", "compose", "draft", "generate a message/email/text" → use compose_message (produces text in state, NOT a file)
- "save to file", "create a file", "write to file", "export" → use file_controller
- NEVER use code_helper or file_controller to compose a message or draft text.

STEP RESULT CHAINING:
- When a later step needs content from a prior step, use [result from step N] as the parameter value.
- Example: if step 1 composes a message, step 2 can use "message_text": "[result from step 1]"

AVAILABLE TOOLS AND THEIR PARAMETERS:

{tool_schema}

EXAMPLES:

Goal: "search for the latest Python news and save to a file on my desktop"
Steps:
  web_search | query: "latest Python news 2024"
  file_controller | action: write, path: desktop, name: python_news.txt, content: "[result from step 1]"

Goal: "What is the weather in Delhi"
Steps:
  weather_report | city: "Delhi"

Goal: "Open Notepad"
Steps:
  open_app | app_name: "Notepad"

Goal: "Send John a message on WhatsApp saying there is a meeting tomorrow"
Steps:
  send_whatsapp_desktop | receiver: "John", message_text: "There is a meeting tomorrow"

Goal: "Compose a friendly message for Arman telling him I miss him and send it on WhatsApp"
Steps:
  compose_message | subject: "missing Arman during vacation", tone: "friendly", context: "college friend", length: "medium"
  send_whatsapp_desktop | receiver: "Arman", message_text: "[result from step 1]"

Goal: "Write a professional email to my manager about the project delay and send it"
Steps:
  compose_message | subject: "project delay update for manager", tone: "professional", length: "medium"
  send_whatsapp_desktop | receiver: "Manager", message_text: "[result from step 1]"

Goal: "Update all my Steam games"
Steps:
  game_updater | action: update, platform: steam

OUTPUT — return ONLY valid JSON, no markdown, no explanation, no code blocks:
{{
  "goal": "...",
  "steps": [
    {{
      "step": 1,
      "tool": "tool_name",
      "description": "what this step does",
      "parameters": {{}},
      "critical": true
    }}
  ]
}}
"""


# ══════════════════════════════════════════════════════════════════════════════
# CORE PLANNING FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _call_planner_llm(prompt_messages: list[dict]) -> str:
    """Call Ollama with the planning prompt and return raw text."""
    client = Client(host=OLLAMA_HOST)
    # Build a single string prompt from messages
    full_prompt = "\n".join(m["content"] for m in prompt_messages)
    response = client.generate(
        model=PLANNER_MODEL,
        prompt=full_prompt,
        stream=False,
        options={"temperature": 0.1, "num_predict": 1024},
    )
    return (response.response or "").strip()


def _sanitize_plan(plan: dict, goal: str) -> dict:
    """
    Post-process plan dict:
    - Guard against generated_code (replace with web_search, matching Mark exactly)
    - Enforce max 5 steps
    """
    steps = plan.get("steps", [])
    for step in steps:
        if step.get("tool") in ("generated_code",):
            logger.warning(
                "[Planner] ⚠️ generated_code detected in step %s — replacing with web_search",
                step.get("step"),
            )
            desc = step.get("description", goal)
            step["tool"] = "web_search"
            step["parameters"] = {"query": desc[:200]}
    # Enforce max 5 steps
    plan["steps"] = steps[:5]
    return plan


def _parse_plan_text(text: str, goal: str) -> dict | None:
    """Strip markdown fences and parse JSON. Returns None on failure."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try extract_json_from_text as second chance
        ok, data = extract_json_from_text(cleaned)
        if not ok or not isinstance(data, dict):
            return None
    if "steps" not in data or not isinstance(data["steps"], list):
        return None
    return data


def _fallback_plan(goal: str) -> dict:
    """Single-step web_search fallback when the LLM fails to produce valid JSON."""
    logger.info("[Planner] 🔄 Using fallback plan")
    return {
        "goal": goal,
        "steps": [
            {
                "step": 1,
                "tool": "web_search",
                "description": f"Search for: {goal}",
                "parameters": {"query": goal},
                "critical": True,
            }
        ],
    }


def create_plan(goal: str, context: str = "") -> dict:
    """
    Create a step-by-step tool plan for a user goal.

    Args:
        goal:    The user's full request string.
        context: Optional additional context (e.g. conversation history excerpt).

    Returns:
        Plan dict: {goal, steps:[{step, tool, description, parameters, critical}]}
        Falls back to _fallback_plan() if the LLM response cannot be parsed.
    """
    system_prompt = _build_planner_prompt()
    user_content  = f"Goal: {goal}"
    if context:
        user_content += f"\n\nContext: {context}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_content},
    ]

    try:
        raw = _call_planner_llm(messages)
        plan = _parse_plan_text(raw, goal)
        if plan is None:
            logger.warning("[Planner] ⚠️ JSON parse failed — using fallback")
            return _fallback_plan(goal)

        plan = _sanitize_plan(plan, goal)
        logger.info("[Planner] ✅ Plan: %d steps", len(plan["steps"]))
        for s in plan["steps"]:
            logger.info("  Step %s: [%s] %s", s["step"], s["tool"], s["description"])
        return plan

    except Exception as e:
        logger.error("[Planner] ⚠️ Planning failed: %s", e)
        return _fallback_plan(goal)


def replan(
    goal:            str,
    completed_steps: list,
    failed_step:     dict,
    error:           str,
) -> dict:
    """
    Create a revised plan after a step failure. Matches Mark's replan() exactly.

    Args:
        goal:            Original user goal.
        completed_steps: Steps that already succeeded (do not repeat).
        failed_step:     The step dict that failed.
        error:           Error message from the failed step.

    Returns:
        Revised plan dict (remaining work only).
    """
    system_prompt = _build_planner_prompt()

    completed_summary = "\n".join(
        f"  - Step {s.get('step', '?')} ({s.get('tool', '?')}): DONE"
        for s in completed_steps
    ) or "  (none)"

    prompt = (
        f"Goal: {goal}\n\n"
        f"Already completed:\n{completed_summary}\n\n"
        f"Failed step: [{failed_step.get('tool')}] {failed_step.get('description')}\n"
        f"Error: {error}\n\n"
        "Create a REVISED plan for the remaining work only. "
        "Do not repeat completed steps. Return ONLY valid JSON."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": prompt},
    ]

    try:
        raw  = _call_planner_llm(messages)
        plan = _parse_plan_text(raw, goal)
        if plan is None:
            logger.warning("[Planner] ⚠️ Replan JSON parse failed — using fallback")
            return _fallback_plan(goal)

        plan = _sanitize_plan(plan, goal)
        logger.info("[Planner] 🔄 Revised plan: %d steps", len(plan["steps"]))
        return plan

    except Exception as e:
        logger.error("[Planner] ⚠️ Replan failed: %s", e)
        return _fallback_plan(goal)


# ══════════════════════════════════════════════════════════════════════════════
# LANGGRAPH NODE WRAPPER
# ══════════════════════════════════════════════════════════════════════════════

def plan_tools(state: DimoState) -> dict:
    """
    LangGraph node: produce a step plan and store it in state.

    Reads:  state["messages"][-1].content  (user request)
            state["current_intent"] / state["router_result"]
    Writes: state["tool_plan"]       — list of step dicts (full schema)
            state["planning_context"] — reasoning / goal string for LLM node
    """
    messages = state.get("messages", [])
    user_message = messages[-1].content if messages else "No message"

    current_intent = (
        state.get("current_intent")
        or state.get("router_result")
        or "unknown"
    )

    logger.info("[Planner] Planning tools for intent: %s", current_intent)
    logger.info("[Planner] User request: %s", user_message[:120])

    plan = create_plan(goal=user_message)

    # Store the full step list (not just tool names) so the executor can use
    # parameters, descriptions, and critical flags directly.
    state["tool_plan"]        = plan.get("steps", [])
    state["planning_context"] = plan.get("goal", user_message)

    logger.info("[Planner] Stored %d steps in state", len(state["tool_plan"]))
    return state
