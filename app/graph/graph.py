"""Graph compilation and setup.

Assembles nodes and edges into the LangGraph execution graph.
"""

from langgraph.graph import StateGraph, START, END
from app.graph.state import DimoState
from app.nodes.router import route_intent
from app.nodes.llm import call_llm
from app.nodes.tool import execute_tool
import logging

logger = logging.getLogger("dimo")

def build_graph():
    """Build and compile the DIMO graph.
    
    Returns:
        Compiled LangGraph graph ready for invocation
    """
    
    logger.info("Building DIMO graph...")
    
    graph = StateGraph(DimoState)
    
    # Add nodes
    graph.add_node("router", route_intent)
    graph.add_node("llm", call_llm)
    graph.add_node("tool", execute_tool)
    
    logger.debug("Nodes added: router, llm, tool")
    
    # Add edges
    # Start → router
    graph.add_edge(START, "router")
    
    # router → conditional routing
    graph.add_conditional_edges(
        "router",
        lambda state: state.get("router_result", "chat"),
        {
            "chat": "llm",
            "search": "tool",
            "tool": "tool",
            "memory": "llm",  # Memory routing will be handled by LLM
        }
    )
    
    # tool → llm (tool results go to LLM for synthesis)
    graph.add_edge("tool", "llm")
    
    # llm → end
    graph.add_edge("llm", END)
    
    logger.debug("Edges configured")
    
    # Compile
    compiled_graph = graph.compile()
    
    logger.info("✓ Graph compiled successfully")
    
    return compiled_graph
