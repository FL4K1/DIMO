"""Model configuration and management.

Manages Ollama model connections and parameters.
"""

import os
from dotenv import load_dotenv
from ollama import Client
import logging

load_dotenv()
logger = logging.getLogger("dimo")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "llama3.2:3b")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3:8b")

# Model parameters
MODEL_CONFIG = {
    "router": {
        "name": ROUTER_MODEL,
        "temperature": 0.3,  # Deterministic routing
        "top_p": 0.9,
        "top_k": 40,
    },
    "llm": {
        "name": LLM_MODEL,
        "temperature": 0.7,  # Creative reasoning
        "top_p": 0.95,
        "top_k": 40,
    }
}

def get_ollama_client():
    """Get Ollama client."""
    try:
        return Client(host=OLLAMA_HOST)
    except Exception as e:
        logger.error(f"Failed to connect to Ollama at {OLLAMA_HOST}: {e}")
        raise

def verify_models():
    """Verify both router and LLM models are available."""
    try:
        client = get_ollama_client()
        models_response = client.list()
        available_models = [m.model for m in models_response.models]
        
        router_available = ROUTER_MODEL in available_models
        llm_available = LLM_MODEL in available_models
        
        logger.info(f"Router model available: {router_available}")
        logger.info(f"LLM model available: {llm_available}")
        
        return router_available and llm_available
    except Exception as e:
        logger.error(f"Failed to verify models: {e}")
        return False
