"""Tool execution loop node for Phase 2 tool chaining.

This node executes planned tools in a loop based on LLM decisions,
implementing the ReAct pattern: Reason → Act → Loop.
"""

import json
import os
from dotenv import load_dotenv
from ollama import Client
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
    
    loop_prompt = f"""You are a task executor. You have completed some tasks already.

COMPLETED TASKS:
{completed_tasks}

REMAINING TOOLS TO EXECUTE:
{remaining_tools}

AVAILABLE TOOLS:
{tools_text}

USER REQUEST:
"{user_message}"

Your job:
1. Read what's been completed
2. Decide what to execute next from the remaining tools
3. If all tasks done, say "DONE"
4. Otherwise, return the NEXT tool with arguments

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
        raw_response = response.get("response", "").strip()
        logger.debug(f"LLM raw response: {raw_response[:200]}")
        
        # Parse JSON response using robust parser
        success, next_action = extract_json_from_text(raw_response)
        if not success:
            logger.error(f"Failed to extract JSON from LLM response: {raw_response}")
            return {"next_tool": "DONE", "args": {}, "reasoning": "JSON parse error"}
        
        return next_action
        
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return {"next_tool": "DONE", "args": {}, "reasoning": f"LLM error: {str(e)}"}


def execute_single_tool(tool_name: str, args: dict) -> str:
    """Execute a single tool by name with given arguments.
    
    Args:
        tool_name: Name of tool to execute (must be in TOOL_CATALOG)
        args: Arguments dict to pass to tool
        
    Returns:
        Tool result as string, or error message
    """
    try:
        # Validate tool exists
        if tool_name not in TOOL_CATALOG:
            error_msg = f"Tool '{tool_name}' not found in catalog"
            logger.error(error_msg)
            return error_msg
        
        # Get tool function from registry
        tool_func = get_tool(tool_name)
        if not tool_func:
            error_msg = f"Could not load tool '{tool_name}'"
            logger.error(error_msg)
            return error_msg
        
        # Execute tool with args
        logger.info(f"Executing tool '{tool_name}' with args: {args}")
        result = tool_func(**args)
        
        logger.info(f"Tool '{tool_name}' completed successfully")
        return str(result)
        
    except TypeError as e:
        error_msg = f"Invalid arguments for tool '{tool_name}': {e}"
        logger.error(error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"Tool '{tool_name}' execution failed: {e}"
        logger.error(error_msg)
        return error_msg


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

        # Validate arguments first before executing tool
        is_valid, validation_error = validate_tool_args(tool_name, args)
        if not is_valid:
            logger.error(f"Argument validation failed: {validation_error}")
            # Record validation error and skip this tool
            state["loop_error_count"] += 1
            state["tool_calls_made"].append({
                "tool": tool_name,
                "args": args,
                "result": f"ERROR: {validation_error}",
                "reasoning": reasoning
            })
            continue  # Skip to next iteration

        # 3. Execute the tool
        result = execute_single_tool(tool_name, args)

        # IMMEDIATELY record (don't wait for synthesis)
        state["tool_calls_made"].append({
            "tool": tool_name,
            "result": result,
            "args": args,
            "reasoning": reasoning
        })

        # TODO: Emit progress update or return partial state
        # This allows caller to display result immediately

        # 5. Increment iteration
        state["current_iteration"] += 1
        logger.info(f"Iteration {state['current_iteration']} / {state['max_iterations']}")

        # 6. Check for repeated errors
        if "Error" in result or "error" in result.lower():
            state["loop_error_count"] += 1
            if state["loop_error_count"] > 3:
                logger.error("Too many tool errors, stopping loop")
                break
        else:
            state["loop_error_count"] = 0  # Reset on success

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
    
    return True, "Arguments valid"










