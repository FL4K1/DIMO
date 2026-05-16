"""Graph compilation and setup.

Assembles nodes and edges into the LangGraph execution graph.
Phase 2: Includes planning and tool chaining loop.
"""

from langgraph.graph import StateGraph, START, END
from app.graph.state import DimoState
from app.nodes.router import route_intent
from app.nodes.planning import plan_tools
from app.nodes.loop import execute_tool_loop
from app.nodes.llm import call_llm
import logging

logger = logging.getLogger("dimo")

def build_graph():
    """Build and compile the DIMO graph.
    
    Phase 2 Architecture:
    - router: Classify intent (chat, search, tool, memory)
    - planning: Decide tool sequence (for search/tool intents)
    - loop: Execute tools in ReAct loop (for search/tool intents)
    - llm: Reasoning and response synthesis
    
    Flow:
    - chat/memory: router → llm → END
    - search/tool: router → planning → loop → llm → END
    
    Returns:
        Compiled LangGraph graph ready for invocation
    """
    
    logger.info("Building DIMO Phase 2 graph with tool chaining...")
    
    graph = StateGraph(DimoState)
    
    # === Add Nodes ===
    graph.add_node("router", route_intent)
    graph.add_node("planning", plan_tools)
    graph.add_node("loop", execute_tool_loop)
    graph.add_node("llm", call_llm)
    
    logger.debug("Nodes added: router, planning, loop, llm")
    
    # === Add Edges ===
    
    # START → router
    graph.add_edge(START, "router")
    
    # router → conditional routing
    # - "chat" and "memory" go directly to LLM
    # - "search" and "tool" go through planning and loop
    graph.add_conditional_edges(
        "router",
        lambda state: state.get("router_result", "chat"),
        {
            "chat": "llm",          # Direct to LLM
            "search": "planning",   # Planning → Loop → LLM
            "tool": "planning",     # Planning → Loop → LLM
            "memory": "llm",        # Direct to LLM (memory synthesis)
        }
    )
    
    # planning → loop (planning feeds into loop)
    graph.add_edge("planning", "loop")
    
    # loop → llm (tool results synthesized by LLM)
    graph.add_edge("loop", "llm")
    
    # llm → end
    graph.add_edge("llm", END)
    
    logger.debug("Edges configured: START -> router -> {planning,llm} -> loop -> llm -> END")
    
    # === Compile ===
    compiled_graph = graph.compile()
    
    logger.info("[OK] Phase 2 graph compiled successfully")
    
    return compiled_graph
