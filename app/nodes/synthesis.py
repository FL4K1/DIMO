"""Response synthesis node for Phase 2 tool chaining.

Combines tool execution results into natural, user-friendly responses.
Formats raw tool outputs, handles errors, and creates readable summaries.
"""

import json
from typing import List, Dict, Tuple
# pyrefly: ignore [missing-import]
from langchain_core.messages import AIMessage

from app.graph.state import DimoState
from app.config.logging import logger


def filter_tool_results(tool_calls_made: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Separate successful results from error results.
    
    Args:
        tool_calls_made: List of tool call records
        
    Returns:
        Tuple of (successful_results, error_results)
    """
    successful = []
    errors = []
    
    for call in tool_calls_made:
        result = call.get("result", "")
        if "ERROR" in str(result) or "error" in str(result):
            errors.append(call)
        else:
            successful.append(call)
    
    return successful, errors


def format_tool_result(tool_name: str, result: str, index: int) -> str:
    """Format a single tool result for display.
    
    Args:
        tool_name: Name of the tool
        result: Result string from tool
        index: Index number for this result
        
    Returns:
        Formatted result string
    """
    # Tool-specific formatting
    if tool_name == "web_search":
        prefix = "Search Results"
    elif tool_name == "summarize":
        prefix = "Summary"
    else:
        prefix = f"{tool_name.title()}"
    
    # Truncate long results
    max_length = 500
    if len(result) > max_length:
        result = result[:max_length] + "..."
    
    return f"{index}. {prefix}:\n{result}\n"

def synthesize_response(state: DimoState) -> dict:
    """Combine tool results into natural language response.

    Process:
    1. Extract tool_calls_made from state
    2. Separate successful results from errors
    3. Format each result naturally
    4. Add metadata (tools used, iteration info)
    5. Create final response message
    6. Update state with synthesized response

    Note: This is a synchronous function. LangGraph supports async nodes
    but the rest of the DIMO graph is sync, so async here would return an
    unawaited coroutine and silently never execute.

    Args:
        state: Current DimoState with tool_calls_made

    Returns:
        Updated state with response message added
    """
    
    logger.info("Synthesizing response from tool results")
    
    tool_calls_made = state.get("tool_calls_made", [])
    
    if not tool_calls_made:
        logger.warning("No tool results to synthesize")
        state["error_message"] = "No tool results available"
        return state
    
    # 1. Filter results
    successful_results, errors = filter_tool_results(tool_calls_made)
    
    logger.debug(f"Tool results: {len(successful_results)} successful, {len(errors)} errors")
    
    # 2. Build response text
    response_parts = []
    
    # Add successful results
    if successful_results:
        response_parts.append("Based on the tools I executed:\n")
        
        for i, result in enumerate(successful_results, 1):
            tool_name = result.get("tool", "unknown")
            result_text = result.get("result", "No result")
            reasoning = result.get("reasoning", "")
            
            # Format the result
            formatted = format_tool_result(tool_name, str(result_text), i)
            response_parts.append(formatted)
            
            # Add reasoning if available (helps explain why tool was used)
            if reasoning and reasoning != "Unknown":
                response_parts.append(f"   (Reasoning: {reasoning})\n")
    
    # Add error summary if any
    if errors:
        response_parts.append("\nNote: Some tools encountered errors:\n")
        
        for error in errors:
            tool_name = error.get("tool", "unknown")
            error_result = error.get("result", "Unknown error")
            error_type = error.get("error_type", "unknown")
            recovery = error.get("recovery_action", "skipped")
            
            # Extract just the error message
            error_msg = str(error_result).replace("ERROR:", "").strip()
            
            response_parts.append(f"- {tool_name}: {error_msg} ({recovery})\n")
    
    # Add execution metadata
    response_parts.append("\n---")
    response_parts.append(f"Execution Summary: {len(successful_results)} tools succeeded, "
                         f"{len(errors)} encountered errors")
    response_parts.append(f"Iterations used: {state.get('current_iteration', '?')}/{state.get('max_iterations', '?')}")
    
    # 3. Create response message
    full_response = "".join(response_parts)
    
    logger.debug(f"Synthesized response length: {len(full_response)} chars")
    
    # 4. Add to messages as AI response
    response_message = AIMessage(content=full_response)
    state["messages"].append(response_message)
    
    logger.info("Response synthesized and added to messages")
    
    return state


def extract_tool_summary(state: DimoState) -> str:
    """Extract a brief summary of what tools were used.
    
    Useful for logging or display purposes.
    
    Args:
        state: Current DimoState
        
    Returns:
        Brief summary like "web_search, summarize"
    """
    tool_calls = state.get("tool_calls_made", [])
    tools_used = set()
    
    for call in tool_calls:
        tool_name = call.get("tool")
        if tool_name and "ERROR" not in str(call.get("result", "")):
            tools_used.add(tool_name)
    
    if not tools_used:
        return "No tools executed"
    
    return ", ".join(sorted(tools_used))


def synthesize_response_streaming(state: DimoState):
    """Yield formatted results as they're added to tool_calls_made"""
    
    # Format header
    yield "Based on tools executed:\n\n"
    
    # Format each result as it appears
    for i, result in enumerate(state["tool_calls_made"], 1):
        formatted = format_tool_result(
            result["tool"], 
            result["result"], 
            i
        )
        yield formatted
        
        # Let UI update between results (doesn't block)
    
    # Format footer
    yield "\n---\nExecution complete."
