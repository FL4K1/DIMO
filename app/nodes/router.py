"""Router node for intent classification.

Routes user input to appropriate handler based on intent classification.
"""

import os
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from ollama import Client
from app.graph.state import DimoState
import logging

load_dotenv()
logger = logging.getLogger("dimo")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "llama3.2:3b")

ROUTER_PROMPT = """You are a highly strict, deterministic routing classifier for an AI agent named DIMO.

Your ONLY job is to classify the user's intent into EXACTLY ONE of these categories:
- chat
- search
- tool
- memory

=== CATEGORY DEFINITIONS & STRICT RULES ===

1. [tool]
User wants the system to PERFORM AN ACTION.
This includes ANY interaction with third-party apps, browsers, devices, or APIs.
CRITICAL: If the user mentions "WhatsApp", "message", "YouTube", "music", "play", "Spotify", "Gemini", "ChatGPT", or "open", it is ALWAYS a tool.
Examples:
- "Send a whatsapp message to Mom" -> tool
- "Play Blinding Lights on YouTube" -> tool
- "Pause the music" -> tool
- "Ask Gemini to write a poem" -> tool
- "Set a timer for 5 minutes" -> tool

2. [search]
User explicitly wants to LOOK UP current information on the internet.
Examples:
- "Search for python tutorials" -> search
- "What is the weather today?" -> search
- "Look up the latest news on AI" -> search

3. [memory]
User wants DIMO to remember a fact or recall past conversations.
Examples:
- "Remember that my favorite color is blue" -> memory
- "What did I tell you about my dog?" -> memory

4. [chat]
Everything else. General conversation, greetings, opinions, and personal instructions.
CRITICAL: If it doesn't clearly require an external tool, web search, or database memory, it is chat.
Examples:
- "Hello DIMO" -> chat
- "I want you to call me Sir from now on" -> chat
- "How are you feeling?" -> chat
- "What is 2+2?" -> chat (math doesn't need a tool)

User input: {input}

Respond with ONLY the category name (one word: chat, search, tool, or memory). No punctuation, no explanation."""

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
        state["current_intent"] = classification
        logger.info(f"Classified as: {classification}")
        
    except Exception as e:
        logger.error(f"Router failed: {e}, defaulting to chat")
        state["router_result"] = "chat"
        state["current_intent"] = "chat"
    
    return state
