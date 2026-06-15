import os
from typing import Optional, Any
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
    def generate(
        prompt: Any,
        model: str = "gemini-2.5-flash",
        system_instruction: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Generates text from the specified model.
        Automatically routes to Gemini if the model starts with 'gemini',
        otherwise attempts to use local Ollama.
        
        Args:
            prompt: The prompt or content to generate from
            model: Model name (default: gemini-2.5-flash)
            system_instruction: System-level instruction
            max_tokens: Maximum output tokens (optional)
            temperature: Sampling temperature (optional, 0.0-1.0)
        """
        if model.startswith("gemini"):
            return LLMGateway._generate_gemini(
                prompt, model, system_instruction, max_tokens, temperature
            )
        else:
            return LLMGateway._generate_ollama(
                prompt, model, system_instruction, max_tokens, temperature
            )

    @staticmethod
    def _generate_gemini(
        prompt: Any,
        model: str,
        system_instruction: Optional[str],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
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
            
            # Build config with optional parameters
            config_kwargs = {}
            if max_tokens is not None:
                config_kwargs["max_output_tokens"] = max_tokens
            if temperature is not None:
                config_kwargs["temperature"] = temperature
            
            config = None
            if system_instruction or config_kwargs:
                config = types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    **config_kwargs
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
    def _generate_ollama(
        prompt: Any,
        model: str,
        system_instruction: Optional[str],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
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
            
            # Build options with optional parameters
            options = {}
            if max_tokens is not None:
                options["num_predict"] = max_tokens
            if temperature is not None:
                options["temperature"] = temperature
            
            response = client.chat(
                model=model,
                messages=messages,
                options=options if options else None,
            )
            return response.get("message", {}).get("content", "").strip()
        except Exception as e:
            return f"Error from Ollama: {e}"
