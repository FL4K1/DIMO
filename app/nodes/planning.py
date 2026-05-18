"""Tool planning node for Phase 2 tool chaining.

This node decides what sequence of tools to use based on
the user's request and current intent.
"""

import json
import os
import time
import logging
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from ollama import Client

from app.graph.state import DimoState
from app.tools.registry import TOOL_CATALOG
from app.utils.json_parser import extract_json_from_text
from app.config.logging import logger


load_dotenv()
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3:8b")


def plan_tools(state: DimoState) -> dict:
    """Decide which tools to use based on current state and user intent.
    
    This function:
    1. Extracts the user's last message and current_intent
    2. Builds a prompt showing available tools (from registry)
    3. Calls the LLM with this prompt
    4. Parses the response to get tool sequence
    5. Updates state with tool_plan and planning_context
    
    Args:
        state: Current DimoState
        
    Returns:
        Updated state with tool_plan and planning_context
    """
    
    # === 1. Extract user message and intent ===
    user_message = state.get("messages", [])[-1].content if state.get("messages") else "No message"
    current_intent = state.get("current_intent") or "unknown"

    # === 2. Build prompt with tool catalog ===
    # Format available tools from registry
    tools_text = ""
    for tool_name, tool_info in TOOL_CATALOG.items():
        tools_text += f"- {tool_info['name']}: {tool_info['description']}\n"
        tools_text += f"  Parameters: {tool_info['parameters']}\n\n"
    
    planning_prompt = f"""You are a tool planning agent. Your job is to analyze a user request and decide which tools to use.

AVAILABLE TOOLS:
{tools_text}

USER INTENT: {current_intent}

USER REQUEST:
"{user_message}"

RULES:
1. Only recommend tools that are relevant to the request
2. Return ONLY valid JSON, no other text
3. If no tools are needed, return empty list

RESPOND IN THIS EXACT JSON FORMAT:
{{
    "reasoning": "Brief explanation of why you chose these tools",
    "tools": ["tool_name1", "tool_name2"]
}}
"""
    
    logger.info(f"Planning tools for intent: {current_intent}")

    # === 3. Call LLM ===
    try:
        with Client(host=OLLAMA_HOST) as client:
            response = client.generate(
                model=LLM_MODEL,
                prompt=planning_prompt,
                stream=False
            )
        raw_output = response.response.strip() if response.response else "{\"tools\": []}"
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raw_output = '{"tools": []}'

    # === 4. Parse response to get tool sequence ===
    try:
        success, plan_data = extract_json_from_text(raw_output)
        if not success:
            logger.error(f"Could not extract JSON from LLM response: {raw_output}")
            tool_plan = []
            reasoning = "Error parsing plan"
        else:
            tool_plan = plan_data.get("tools", [])
            reasoning = plan_data.get("reasoning", "")
    except Exception as e:
        logger.error(f"Error parsing plan: {e}")
        tool_plan = []
        reasoning = "Error parsing plan"

    # === 5. Update state with tool_plan and planning_context ===
    
    state["tool_plan"] = tool_plan
    state["planning_context"] = reasoning
    
    logger.info(f"Planned tools: {tool_plan}")
    logger.debug(f"Planning reasoning: {reasoning}")

    return state
