"""Tool execution loop node for Phase 2 tool chaining.

This node executes planned tools in a loop based on LLM decisions,
implementing the ReAct pattern: Reason → Act → Loop.
"""

import json
import os
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from ollama import Client
# pyrefly: ignore [missing-import]
from langchain_core.messages import HumanMessage, AIMessage

from app.graph.state import DimoState
from app.tools.registry import TOOL_CATALOG, get_tool
from app.utils.json_parser import extract_json_from_text
from app.config.logging import logger


load_dotenv()
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3:8b")


def ask_llm_next_action(state: DimoState) -> dict:
    """Ask the LLM what tool to execute next based on current state.
    
    Args:
        state: Current DimoState with conversation history
        
    Returns:
        Parsed JSON dict with next_tool, args, and reasoning
    """
    # Build prompt with current state
    user_message = state.get("messages", [])[-1].content if state.get("messages") else "No message"
    completed_tasks = json.dumps(state.get("tool_calls_made", []), indent=2)
    remaining_tools = state.get("tool_plan", [])
    
    # Format available tools
    tools_text = ""
    for tool_name, tool_info in TOOL_CATALOG.items():
        tools_text += f"- {tool_info['name']}: {tool_info['description']}\n"
        tools_text += f"  Parameters: {tool_info['parameters']}\n\n"
    
    # Filter completed tools from remaining tools
    completed_tool_names = [call.get("tool") for call in state.get("tool_calls_made", []) if call.get("result", {}).get("success", False)]
    remaining_tools = [t for t in state.get("tool_plan", []) if t not in completed_tool_names]
    
    loop_prompt = f"""You are a strict task execution router.

COMPLETED TASKS:
{completed_tasks}

REMAINING TOOLS PLANNED:
{remaining_tools}

AVAILABLE TOOLS:
{tools_text}

USER REQUEST:
"{user_message}"

Your job:
1. Look at COMPLETED TASKS. If the user request is already fulfilled by these tasks, you MUST return "next_tool": "DONE".
2. If there are no REMAINING TOOLS PLANNED, you MUST return "next_tool": "DONE".
3. NEVER repeat a tool that is already in COMPLETED TASKS if it succeeded.
4. Otherwise, choose the next tool to execute.

RESPOND IN THIS EXACT JSON FORMAT:
{{
    "next_tool": "tool_name",
    "args": {{"key": "value"}},
    "reasoning": "Why this next step?"
}}

If next_tool is DONE, args can be empty: {{}}.
"""
    
    logger.info("Asking LLM what tool to execute next")

    try:
        client = Client(host=OLLAMA_HOST)
        response = client.generate(
            model=LLM_MODEL,
            prompt=loop_prompt,
            stream=False
        )
        raw_response = response.response.strip() if response.response else ""
        logger.info(f"LLM raw response: {raw_response}")

        # Parse JSON response using robust parser
        success, next_action = extract_json_from_text(raw_response)
        if not success:
            logger.error(f"Failed to extract JSON from LLM response: {raw_response}")
            return {"next_tool": "DONE", "args": {}, "reasoning": "JSON parse error"}

        return next_action

    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return {"next_tool": "DONE", "args": {}, "reasoning": f"LLM error: {str(e)}"}


def execute_single_tool(tool_name: str, args: dict) -> dict:
    """Execute a single tool by name with given arguments.
    
    Returns:
        Structured result dict: {"success": bool, "result": str, "error": str | None}
    """
    try:
        if tool_name not in TOOL_CATALOG:
            return {"success": False, "result": "", "error": f"Tool '{tool_name}' not found in catalog"}
        
        tool_func = get_tool(tool_name)
        if not tool_func:
            return {"success": False, "result": "", "error": f"Could not load tool '{tool_name}'"}
        
        logger.info(f"Executing tool '{tool_name}' with args: {args}")
        result = tool_func(**args)
        
        # Check if the tool already returned a structured dict (e.g. updated browser tools)
        if isinstance(result, dict) and "success" in result:
            return result
        
        # Legacy fallback: parse string for obvious errors
        result_str = str(result)
        is_error = "error" in result_str.lower() or "failed" in result_str.lower() or "could not" in result_str.lower() or "timed out" in result_str.lower()
        
        if is_error:
            logger.warning(f"Tool '{tool_name}' returned error string: {result_str}")
            return {"success": False, "result": result_str, "error": result_str}
        
        logger.info(f"Tool '{tool_name}' completed successfully")
        return {"success": True, "result": result_str, "error": None}
        
    except TypeError as e:
        error_msg = f"Invalid arguments for tool '{tool_name}': {e}"
        logger.error(error_msg)
        return {"success": False, "result": "", "error": error_msg}
    except Exception as e:
        error_msg = f"Tool '{tool_name}' execution failed: {e}"
        logger.error(error_msg)
        return {"success": False, "result": "", "error": error_msg}


def execute_tool_loop(state: DimoState) -> dict:
    """Execute tools and yield results as they complete"""

    while state["current_iteration"] < state["max_iterations"]:
        next_action = ask_llm_next_action(state)

        # ── Guard: LLM sometimes returns a JSON array instead of an object ──
        # extract_json_from_text hands back whatever the parser found, which
        # may be a list like [{"next_tool": ...}].  Calling .get() on a list
        # raises AttributeError, so we unwrap single-element arrays here.
        if isinstance(next_action, list):
            if next_action:
                next_action = next_action[0]
                logger.debug("Unwrapped list response from LLM: using index 0.")
            else:
                logger.error("LLM returned empty list — treating as DONE.")
                break

        if not isinstance(next_action, dict):
            logger.error(
                "Unexpected next_action type %s — treating as DONE.",
                type(next_action).__name__,
            )
            break

        if next_action.get("next_tool") == "DONE":
            break

        tool_name = next_action.get("next_tool")
        args = next_action.get("args", {})
        reasoning = next_action.get("reasoning", "")

        logger.info(f"LLM decided to execute '{tool_name}': {reasoning}")
        
        # Strict infinite loop guard: check if this EXACT tool+args was already successful
        already_run = any(
            c.get("tool") == tool_name 
            and c.get("args") == args 
            and c.get("result", {}).get("success", False)
            for c in state.get("tool_calls_made", [])
        )
        if already_run:
            logger.warning(f"LLM tried to repeat successful tool '{tool_name}' with same args. Breaking loop.")
            break

        # Validate arguments first before executing tool
        is_valid, validation_error = validate_tool_args(tool_name, args)
        if not is_valid:
            logger.error(f"Argument validation failed: {validation_error}")
            state["loop_error_count"] += 1
            state["current_iteration"] += 1
            state["tool_calls_made"].append({
                "tool": tool_name,
                "args": args,
                "result": {"success": False, "result": "", "error": validation_error},
                "reasoning": reasoning
            })
            # Secondary guard: same non-existent tool chosen 3 times → give up immediately
            consecutive_same = sum(
                1 for c in state["tool_calls_made"][-3:]
                if c.get("tool") == tool_name and not c.get("result", {}).get("success", False)
            )
            if consecutive_same >= 3:
                logger.error(f"Tool '{tool_name}' failed validation 3 times in a row — stopping loop")
                break
            continue

        # 3. Execute the tool
        result_dict = execute_single_tool(tool_name, args)

        # IMMEDIATELY record
        state["tool_calls_made"].append({
            "tool": tool_name,
            "result": result_dict,
            "args": args,
            "reasoning": reasoning
        })

        # 5. Increment iteration
        state["current_iteration"] += 1
        logger.info(f"Iteration {state['current_iteration']} / {state['max_iterations']}")

        # 6. Check for repeated errors
        if not result_dict.get("success", False):
            state["loop_error_count"] += 1
            if state["loop_error_count"] > 3:
                logger.error("Too many tool errors, stopping loop")
                break
        else:
            state["loop_error_count"] = 0  # Reset on success
            # Optional: break early if success achieved (prevents multi-tool chains, but safer)
            # break

    if state["current_iteration"] >= state["max_iterations"]:
        logger.warning(f"Reached max iterations limit ({state['max_iterations']})")

    logger.info(f"Tool execution loop completed. Executed {len(state['tool_calls_made'])} tools")
    return state





def validate_tool_args(tool_name: str, args: dict) -> tuple[bool, str]:
    """Validate tool name and args against registry schema.
    
    Returns:
        (is_valid: bool, error_message: str)
    """
    # Check tool exists
    # Check args match schema
    # Check required params present

    if tool_name not in TOOL_CATALOG:
        return False, f"Tool '{tool_name}' not found in catalog"
    else: 
        tool_info = TOOL_CATALOG.get(tool_name)

    schema = tool_info.get("parameters", {})
    properties = schema.get("properties", {})
    required_fields = schema.get("required", [])

    # checking req fields 
    for field in required_fields:
        if field not in args:
            return False, f"Missing required parameter '{field}' for tool '{tool_name}'"


    # checking type mapping 
    type_mapping = {
        "string" : str, 
        "number" : (int, float), 
        "boolean" : bool, 
        "object" : dict, 
        "array" : list
    }

    # 5. Validate provided args
    for field_name, field_value in args.items():
        
        # Reject unknown fields
        if field_name not in properties:
            return False, f"Unknown field: '{field_name}'"
        
        # Get expected type
        expected_type_name = properties[field_name].get("type")
        
        if expected_type_name not in type_mapping:
            return False, f"Unsupported schema type: '{expected_type_name}'"
        
        expected_type = type_mapping[expected_type_name]
        
        # Type check
        if not isinstance(field_value, expected_type):
            return (
                False,
                f"Field '{field_name}' expected "
                f"{expected_type_name}, got {type(field_value).__name__}"
            )
    
    return True, "Arguments valid"










