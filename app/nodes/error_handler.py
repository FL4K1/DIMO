"""Error handling node for Phase 2 tool execution.

Handles tool failures gracefully with retry logic, error classification,
and recovery strategies.
"""

import json
import os
import traceback
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from ollama import Client  # Reserved for Phase 2.5 LLM-assisted recovery

from app.graph.state import DimoState
from app.config.logging import logger


load_dotenv()
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3:8b")


def classify_error(error: Exception) -> str:
    """Classify error type for recovery strategy.
    
    Returns:
        "transient" - Temporary (network, timeout) → RETRY
        "persistent" - Permanent (bad args, tool broken) → SKIP
        "unknown" - Unclassified → ASK LLM
    """
    error_str = str(error).lower()
    
    # Transient errors (temporary failures, often recoverable)
    transient_patterns = [
        "timeout",
        "connection",
        "network",
        "temporarily",
        "busy",
        "unavailable",
        "rate limit",
    ]
    
    # Persistent errors (permanent failures, won't recover)
    persistent_patterns = [
        "invalid argument",
        "not found",
        "does not exist",
        "type error",
        "not implemented",
        "permission denied",
    ]
    
    for pattern in transient_patterns:
        if pattern in error_str:
            return "transient"
    
    for pattern in persistent_patterns:
        if pattern in error_str:
            return "persistent"
    
    return "unknown"


def log_error_context(state: DimoState, tool_name: str, args: dict, 
                      error: Exception, error_type: str) -> None:
    """Log comprehensive error context for debugging.
    
    Captures: tool, arguments, error message, traceback, state context.
    """
    logger.error(f"\n{'='*60}")
    logger.error(f"TOOL ERROR: {tool_name}")
    logger.error(f"  Error Type: {error_type} ({error.__class__.__name__})")
    logger.error(f"  Error Message: {str(error)}")
    logger.error(f"  Tool Arguments: {json.dumps(args, indent=2)}")
    logger.error(f"  Current Iteration: {state.get('current_iteration', '?')}")
    logger.error(f"  Error Count: {state.get('loop_error_count', '?')}")
    logger.error(f"  Tools Completed: {len(state.get('tool_calls_made', []))}")
    logger.error(f"  Traceback: {traceback.format_exc()}")
    logger.error(f"{'='*60}\n")


def decide_recovery(state: DimoState, tool_name: str, error_type: str) -> str:
    """Decide recovery strategy based on error classification and state.
    
    Returns:
        "retry" - Attempt tool again
        "skip" - Skip this tool, continue to next
        "abort" - Stop entire loop
    """
    error_count = state.get("loop_error_count", 0)
    max_iterations = state.get("max_iterations", 5)
    current_iteration = state.get("current_iteration", 0)
    
    # Too many errors overall → abort
    if error_count >= 3:
        logger.warning(f"Error count ({error_count}) >= 3, aborting loop")
        return "abort"
    
    # Too close to iteration limit → abort to preserve attempts
    if current_iteration >= max_iterations - 1:
        logger.warning(f"Near iteration limit ({current_iteration}/{max_iterations}), aborting")
        return "abort"
    
    # Transient errors → retry once
    if error_type == "transient":
        logger.warning(f"Transient error for '{tool_name}', will retry")
        return "retry"
    
    # Persistent errors → skip
    if error_type == "persistent":
        logger.warning(f"Persistent error for '{tool_name}', will skip")
        return "skip"
    
    # Unknown errors → skip (conservative)
    logger.warning(f"Unknown error type for '{tool_name}', will skip")
    return "skip"


def handle_tool_error(state: DimoState, tool_name: str, args: dict,
                      error: Exception) -> dict:
    """Handle tool execution errors with recovery strategy.
    
    Process:
    1. Classify error type (transient/persistent/unknown)
    2. Log comprehensive context for debugging
    3. Decide recovery action (retry/skip/abort)
    4. Update state with error tracking
    5. Return recovery decision
    
    Args:
        state: Current DimoState
        tool_name: Name of tool that failed
        args: Arguments passed to tool
        error: Exception that was raised
        
    Returns:
        Updated state with error tracking and recovery action
    """
    
    logger.warning(f"Tool '{tool_name}' failed, initiating error recovery")
    
    # 1. Classify the error
    error_type = classify_error(error)
    logger.debug(f"Error classified as: {error_type}")
    
    # 2. Log full context
    log_error_context(state, tool_name, args, error, error_type)
    
    # 3. Decide recovery strategy
    recovery_action = decide_recovery(state, tool_name, error_type)
    logger.info(f"Recovery action for '{tool_name}': {recovery_action}")
    
    # 4. Update state error tracking
    state["loop_error_count"] += 1
    
    # 5. Record the error in tool_calls_made for audit trail
    state["tool_calls_made"].append({
        "tool": tool_name,
        "args": args,
        "result": f"ERROR ({error_type}): {str(error)}",
        "error_type": error_type,
        "recovery_action": recovery_action,
        "reasoning": f"Tool failed with {error_type} error, {recovery_action}ing"
    })
    
    # 6. Update state with recovery action
    state["error_message"] = f"Tool '{tool_name}' failed: {str(error)}"
    state["should_continue"] = recovery_action != "abort"
    
    return state, recovery_action


def should_retry_tool(state: DimoState, tool_name: str) -> bool:
    """Check if we should retry a tool based on state.
    
    Retry is allowed only if:
    - We haven't hit error limit
    - We have iterations remaining
    - Tool hasn't been retried already
    
    Args:
        state: Current DimoState
        tool_name: Tool to potentially retry
        
    Returns:
        True if retry is allowed, False otherwise
    """
    error_count = state.get("loop_error_count", 0)
    current_iteration = state.get("current_iteration", 0)
    max_iterations = state.get("max_iterations", 5)
    
    # Check thresholds
    if error_count >= 3:
        logger.debug(f"Cannot retry: error count ({error_count}) >= 3")
        return False
    
    if current_iteration >= max_iterations:
        logger.debug(f"Cannot retry: iteration limit ({current_iteration}/{max_iterations})")
        return False
    
    logger.debug(f"Retry allowed for '{tool_name}'")
    return True
