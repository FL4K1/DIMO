"""
DIMO - Digital Intelligence for Multimodal Operations

Entry point for the DIMO agent system.

Tech Stack:
- Orchestration: LangGraph + Ollama (Llama3:8b + Llama3.2:3b)
- Memory: Qdrant (Phase 4) + SQLite facts (Phase 4)
- Voice: Faster-Whisper + Piper TTS (Phase 3)
- Tools: Web search + advanced tools (Phase 5)
"""

import os
import sys
from dotenv import load_dotenv

# Initialize configuration EARLY (before building graph)
load_dotenv()

# Initialize tracing (optional, requires LANGSMITH_API_KEY)
from app.config import tracing

from langchain_core.messages import HumanMessage
from app.graph.graph import build_graph
from app.config.logging import logger
from app.config.models import verify_models

def initialize_state():
    """Create initial state for a new conversation."""
    return {
        "messages": [],
        "summary": "",
        "current_intent": "",
        "router_result": "",
        "summary_ask_counter": 0,
        "episodic_memory_query": None,
        "episodic_recall": None,
        "facts": None,
        "next_tool": None,
        "tool_history": [],
        "tool_output": None,
        "user_profile": None,
        "session_id": None,
        "error_message": None,
    }

def main():
    """Run the DIMO CLI interface."""
    
    print("\n" + "="*70)
    print("DIMO - Digital Intelligence for Multimodal Operations")
    print("="*70)
    print("Local-first AI agent with LangGraph + Ollama")
    print("Type 'exit' or 'quit' to exit")
    print("="*70 + "\n")
    
    logger.info("Starting DIMO CLI interface")
    
    # Verify models are available
    print("Verifying local AI stack...", end=" ", flush=True)
    if not verify_models():
        print("✗ FAILED\n")
        print("✗ Error: Required models not available in Ollama")
        print("  Run: ollama pull llama3:8b llama3.2:3b")
        logger.error("Model verification failed")
        return
    print("✓")
    
    try:
        # Build graph
        print("Building graph...", end=" ", flush=True)
        graph = build_graph()
        print("✓\n")
        
    except Exception as e:
        print(f"✗ Failed to build graph: {e}")
        logger.error(f"Graph build failed: {e}")
        return
    
    # Main conversation loop
    while True:
        try:
            user_input = input("You: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ["exit", "quit"]:
                print("\nGoodbye!\n")
                logger.info("User exited DIMO")
                break
            
            logger.info(f"Processing user input: {user_input}")
            
            # Prepare state
            state = initialize_state()
            state["messages"] = [HumanMessage(content=user_input)]
            
            # Execute graph
            print("\nProcessing...", end=" ", flush=True)
            result = graph.invoke(state)
            print("\n")
            
            # Extract and display response
            if result.get("messages"):
                # Get the last message (which should be the AI response)
                last_message = result["messages"][-1]
                response = last_message.content if hasattr(last_message, 'content') else str(last_message)
                
                print(f"DIMO: {response}\n")
                logger.info(f"Response generated: {response[:200]}")
            else:
                print("DIMO: I couldn't generate a response.\n")
                logger.warning("No response generated")
        
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
            logger.info("User interrupted with Ctrl+C")
            break
        
        except Exception as e:
            print(f"\n✗ Error: {e}\n")
            logger.error(f"Conversation error: {e}", exc_info=True)

if __name__ == "__main__":
    main()
