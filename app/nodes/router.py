"""Router node for intent classification.

Routes user input to appropriate handler based on intent classification.
"""

import os
from dotenv import load_dotenv
from ollama import Client
from app.graph.state import DimoState
import logging

load_dotenv()
logger = logging.getLogger("dimo")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "llama3.2:3b")

# Intent classification prompt
ROUTER_PROMPT = """You are a routing classifier for an AI assistant named DIMO.

Your task: Classify the user's intent into ONE category.

Categories:
- chat: General conversation, questions, discussion
- search: User wants information from the web
- tool: User wants to perform an action (open app, set reminder, etc)
- memory: User wants to remember or recall facts

User input: {input}

Respond with ONLY the category name (one word). No explanation."""

def route_intent(state: DimoState) -> DimoState:
    """Classify user intent and route to appropriate handler.
    
    Args:
        state: Current DimoState
        
    Returns:
        Updated DimoState with router_result set
    """
    
    # Get the latest user message
    if not state.get("messages"):
        logger.warning("No messages in state")
        state["router_result"] = "chat"
        return state
    
    latest_message = state["messages"][-1]
    user_input = latest_message.content if hasattr(latest_message, 'content') else str(latest_message)
    
    logger.info(f"=== ROUTER NODE CALLED ===")
    logger.info(f"Routing intent for input: {user_input[:100]}")
    
    try:
        client = Client(host=OLLAMA_HOST)
        
        # Create prompt
        prompt = ROUTER_PROMPT.format(input=user_input)
        
        # Call router model
        response = client.generate(
            model=ROUTER_MODEL,
            prompt=prompt,
            stream=False
        )
        
        # Extract classification
        classification = response.response.strip().lower().split()[0]
        
        # Validate classification
        valid_classifications = ["chat", "search", "tool", "memory"]
        if classification not in valid_classifications:
            logger.warning(f"Invalid classification: {classification}, defaulting to chat")
            classification = "chat"
        
        state["router_result"] = classification
        logger.info(f"Classified as: {classification}")
        
    except Exception as e:
        logger.error(f"Router failed: {e}, defaulting to chat")
        state["router_result"] = "chat"
    
    return state
