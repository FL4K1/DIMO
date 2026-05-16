from typing import Annotated, TypedDict, Optional, List, Dict
from langgraph.graph.message import add_messages  # Only used for messages channel 

class DimoState(TypedDict):
    """State object for DIMO agent — complete multi-layer architecture.
    
    Tracks:
    - Conversation and reasoning
    - Intent and routing decisions
    - Memory (episodic recall, facts)
    - Tool execution history
    - Agent metadata
    """
    
    # === CONVERSATION LAYER ===
    messages: Annotated[list, add_messages]
    """Core chat history. add_messages handles appending new turns."""
    
    summary: str
    """Tier 1 summary: "running distillation" of conversation."""
    
    # === ROUTING & INTENT ===
    current_intent: str
    """What is user trying to do? e.g. "coding", "planning", "chatting", "searching"."""
    
    router_result: str
    """Router output: "chat" | "search" | "tool" | "memory"."""
    
    # === MEMORY SYSTEM ===
    summary_ask_counter: int
    """Counter for proactive "should I summarize?" checks (avoid being annoying)."""
    
    episodic_memory_query: Optional[str]
    """Query string for retrieving past conversations from Qdrant (Phase 4)."""
    
    episodic_recall: Optional[List[Dict]]
    """Retrieved past conversation snippets from Qdrant (Phase 4)."""
    
    facts: Optional[Dict]
    """Retrieved declarative facts from SQLite (Phase 4). e.g. {"favorite_language": "Python"}."""
    
    # === TOOL EXECUTION ===
    next_tool: Optional[str]
    """Name of next tool to execute."""
    
    tool_history: List
    """Record of all tool calls and results in this session."""
    
    tool_output: Optional[str]
    """Most recent tool result."""
    
    # === AGENT METADATA ===
    user_profile: Optional[Dict]
    """Current user's stable info (Phase 4)."""
    
    session_id: Optional[str]
    """Unique session identifier for logging."""
    
    error_message: Optional[str]
    """Last error, if any."""
    
    # === TOOL CHAINING (Phase 2) ===
    tool_plan: Optional[List[str]]
    """Planned sequence of tools to execute. E.g. ['search', 'summarize', 'write_email']."""
    
    tool_calls_made: List
    """Record of tool calls made, with inputs and outputs."""
    
    max_iterations: int
    """Max iterations for tool chaining to prevent infinite loops."""
    
    current_iteration: int
    """Current iteration count for tool chaining."""
    
    planning_context: Optional[str]
    """LLM's reasoning: 'I need to search first, then summarize'."""
    
    should_continue: bool
    """Flag: should we loop again? Or is response final?"""
    
    loop_error_count: int
    """Count of errors in this loop cycle. Too many = stop."""