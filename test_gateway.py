from app.services.agents.llm_gateway import LLMGateway

def test_gemini():
    print("Testing Gemini...")
    res = LLMGateway.generate(
        prompt="Say the exact word 'BINGO'.", 
        model="gemini-2.5-flash", 
        system_instruction="You are a helpful assistant."
    )
    assert "BINGO" in res.upper(), f"Unexpected result: {res}"
    print("Gemini passed.")

if __name__ == "__main__":
    test_gemini()
    print("All LLMGateway tests passed.")
