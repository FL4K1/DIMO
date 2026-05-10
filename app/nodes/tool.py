"""Tool execution node.

Handles execution of tools based on routing decision.
Currently implements web search tool.
"""

from langchain_core.messages import AIMessage
from app.graph.state import DimoState
import logging

# Import only implemented tools for Phase 1-2
try:
    from app.tools.search import web_search
except ImportError:
    web_search = None

logger = logging.getLogger("dimo")

def execute_tool(state: DimoState) -> DimoState:
    """Execute tool based on routing decision.
    
    Args:
        state: Current DimoState
        
    Returns:
        Updated DimoState with tool output added to messages
    """
    
    routing = state.get("router_result", "chat")
    
    logger.info(f"Tool execution node - routing: {routing}")
    
    # Only execute tool if routed to "search" or "tool"
    if routing not in ["search", "tool"]:
        logger.debug(f"Routing '{routing}' doesn't require tool execution")
        return state
    
    try:
        # Get latest user message for tool input
        messages = state.get("messages", [])
        if not messages:
            logger.warning("No messages for tool execution")
            return state
        
        latest_message = messages[-1]
        user_input = latest_message.content if hasattr(latest_message, 'content') else str(latest_message)
        
        # Execute appropriate tool
        if routing == "search":
            logger.info(f"Executing web search for: {user_input[:100]}")
            tool_output = web_search(user_input)
            
            # Add tool result to messages
            state["messages"].append(AIMessage(
                content=f"[Search Results]\n{tool_output}"
            ))
            
            logger.debug(f"Tool output length: {len(tool_output)}")
        
        elif routing == "tool":
            # TODO: Implement other tools (app launching, etc)
            logger.info("Tool routing selected but no tool handler yet")
            state["messages"].append(AIMessage(
                content="Tool execution not yet implemented."
            ))
    
    except Exception as e:
        logger.error(f"Tool execution failed: {e}")
        state["messages"].append(AIMessage(
            content=f"Tool execution failed: {str(e)}"
        ))
    
    return state
