"""LLM node for reasoning and response generation.

This is the main "thinking" step where DIMO processes context
and generates responses.
"""

import time
import os
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from ollama import Client
# pyrefly: ignore [missing-import]
from langchain_core.messages import AIMessage
from app.graph.state import DimoState
import logging


load_dotenv()
logger = logging.getLogger("dimo")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3:8b")

def call_llm(state: DimoState) -> DimoState:
    """Call the main LLM for reasoning and response generation.
    
    Args:
        state: Current DimoState
        
    Returns:
        Updated DimoState with LLM response added to messages
    """
    
    logger.info("=== LLM NODE CALLED ===")
    logger.info(f"Messages count: {len(state.get('messages', []))}")
    logger.info(f"Tool calls made: {len(state.get('tool_calls_made', []))}")
    logger.info(f"Current iteration: {state.get('current_iteration')}/{state.get('max_iterations')}")
    
    try:
        # Format conversation history for prompt
        messages = state.get("messages", [])
        if not messages:
            logger.warning("No messages to process")
            return state
        
        # Build conversation context
        conversation = []
        for msg in messages:
            role = "User" if msg.__class__.__name__ == "HumanMessage" else "Assistant"
            content = msg.content if hasattr(msg, 'content') else str(msg)
            conversation.append(f"{role}: {content}")
        
        prompt = "\n".join(conversation) + "\nAssistant:"
        
        # Call LLM
        start_time = time.time()
        logger.debug(f"Prompt length: {len(prompt)} chars")
        logger.debug(f"Full prompt:\n{prompt}")

        with Client(host=OLLAMA_HOST) as client:
            response = client.generate(
                model=LLM_MODEL,
                prompt=prompt,
                stream=False
            )
        
        elapsed = time.time() - start_time
        
        # Extract response
        llm_response = response.response.strip() if response.response else "I couldn't generate a response."
        
        logger.info(f"LLM response generated (latency: {elapsed:.2f}s, length: {len(llm_response)} chars)")
        
        # Add to messages
        state["messages"].append(AIMessage(content=llm_response))
        logger.debug(f"Response preview: {llm_response[:200]}")
        
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        state["messages"].append(AIMessage(content=f"I encountered an error: {str(e)}"))
    
    return state
