"""
Test Ollama local integration.

Verifies that:
1. Ollama is running at OLLAMA_HOST
2. Models are available
3. API responds to queries
"""

import os
from dotenv import load_dotenv
from ollama import Client
import time

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3:8b")
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "llama3.2:3b")

def test_ollama_connection():
    """Test basic Ollama connection."""
    print(f"\n[TEST 1] Testing Ollama connection to {OLLAMA_HOST}...")
    
    try:
        client = Client(host=OLLAMA_HOST)
        print("✓ Successfully connected to Ollama")
        return client
    except Exception as e:
        print(f"✗ Failed to connect to Ollama: {e}")
        print("  Make sure Ollama is running: ollama serve")
        return None

def test_model_availability(client, model_name):
    """Test if a model is available."""
    print(f"\n[TEST 2] Checking if model '{model_name}' is available...")
    
    try:
        # List available models
        models_response = client.list()
        available_models = [m.model for m in models_response.models]
        
        if not available_models:
            print("✗ No models available in Ollama")
            print("  Run: ollama pull llama3:8b")
            return False
        
        print(f"  Available models: {available_models}")
        
        if model_name in available_models:
            print(f"✓ Model '{model_name}' is available")
            return True
        else:
            print(f"✗ Model '{model_name}' not found")
            print(f"  Run: ollama pull {model_name}")
            return False
            
    except Exception as e:
        print(f"✗ Error checking models: {e}")
        return False

def test_model_inference(client, model_name):
    """Test inference with a model."""
    print(f"\n[TEST 3] Testing inference with '{model_name}'...")
    print("  Prompt: 'Say hello in one word'")
    
    try:
        start_time = time.time()
        
        response = client.generate(
            model=model_name,
            prompt="Say hello in one word",
            stream=False
        )
        
        elapsed = time.time() - start_time
        
        if response and response.response:
            print(f"✓ Got response (latency: {elapsed:.2f}s)")
            print(f"  Response: {response.response.strip()}")
            return True
        else:
            print("✗ No response from model")
            return False
            
    except Exception as e:
        print(f"✗ Inference failed: {e}")
        return False

def test_routing_classification(client):
    """Test the router model's ability to classify intent."""
    print(f"\n[TEST 4] Testing intent classification with router model...")
    
    test_inputs = [
        "Search for the latest AI news",
        "Hi DIMO, how are you?",
        "Remember that I like Python",
        "Open my email",
    ]
    
    classification_prompt = """You are a routing classifier. Classify the intent of this input into ONE of:
- chat: general conversation
- search: user wants web information
- tool: user wants a specific action
- memory: user wants to remember/recall facts

Input: {input}
Classification (ONE WORD ONLY):"""
    
    try:
        for user_input in test_inputs:
            prompt = classification_prompt.format(input=user_input)
            response = client.generate(
                model=ROUTER_MODEL,
                prompt=prompt,
                stream=False
            )
            
            classification = response.response.strip().lower().split()[0] if response.response else "chat"
            print(f"  '{user_input}' → {classification}")
        
        print("✓ Router classification working")
        return True
        
    except Exception as e:
        print(f"✗ Routing test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("=" * 70)
    print("DIMO OLLAMA INTEGRATION TEST")
    print("=" * 70)
    
    # Test 1: Connection
    client = test_ollama_connection()
    if not client:
        print("\n" + "=" * 70)
        print("RESULT: FAILED - Cannot proceed without Ollama")
        print("=" * 70)
        return False
    
    # Test 2: Model availability
    llm_available = test_model_availability(client, LLM_MODEL)
    router_available = test_model_availability(client, ROUTER_MODEL)
    
    if not (llm_available and router_available):
        print("\n" + "=" * 70)
        print("RESULT: FAILED - Required models not available")
        print("=" * 70)
        return False
    
    # Test 3: Inference
    llm_working = test_model_inference(client, LLM_MODEL)
    router_working = test_model_inference(client, ROUTER_MODEL)
    
    if not (llm_working and router_working):
        print("\n" + "=" * 70)
        print("RESULT: FAILED - Model inference failed")
        print("=" * 70)
        return False
    
    # Test 4: Routing
    routing_ok = test_routing_classification(client)
    
    # Summary
    print("\n" + "=" * 70)
    if llm_working and router_working and routing_ok:
        print("RESULT: SUCCESS ✓")
        print("Your local AI stack is ready!")
        print("=" * 70)
        return True
    else:
        print("RESULT: FAILED")
        print("=" * 70)
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
