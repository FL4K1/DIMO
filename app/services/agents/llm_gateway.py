import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

class LLMGateway:
    """
    Unified gateway for calling Language Models (Gemini, Ollama).
    """

    @staticmethod
    def _get_gemini_api_key() -> str:
        return os.getenv("GEMINI_API_KEY", "")

    @staticmethod
    def generate(prompt: str, model: str = "gemini-2.5-flash", system_instruction: Optional[str] = None) -> str:
        """
        Generates text from the specified model.
        Automatically routes to Gemini if the model starts with 'gemini',
        otherwise attempts to use local Ollama.
        """
        if model.startswith("gemini"):
            return LLMGateway._generate_gemini(prompt, model, system_instruction)
        else:
            return LLMGateway._generate_ollama(prompt, model, system_instruction)

    @staticmethod
    def _generate_gemini(prompt: str, model: str, system_instruction: Optional[str]) -> str:
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            return "Error: google-genai is not installed."

        api_key = LLMGateway._get_gemini_api_key()
        if not api_key:
            return "Error: Gemini API key not found in config/api_keys.json."

        try:
            client = genai.Client(api_key=api_key)
            
            # Use system instructions if provided
            config = None
            if system_instruction:
                config = types.GenerateContentConfig(
                    system_instruction=system_instruction
                )

            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config
            )
            return response.text.strip()
        except Exception as e:
            return f"Error from Gemini: {e}"

    @staticmethod
    def _generate_ollama(prompt: str, model: str, system_instruction: Optional[str]) -> str:
        try:
            from ollama import Client
        except ImportError:
            return "Error: ollama python package is not installed."

        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        try:
            client = Client(host=host)
            
            messages = []
            if system_instruction:
                messages.append({"role": "system", "content": system_instruction})
            messages.append({"role": "user", "content": prompt})
            
            response = client.chat(
                model=model,
                messages=messages
            )
            return response.get("message", {}).get("content", "").strip()
        except Exception as e:
            return f"Error from Ollama: {e}"
