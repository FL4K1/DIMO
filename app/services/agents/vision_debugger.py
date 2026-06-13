import os
import re
import time
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

class VisionDebugger:
    """
    Handles screenshot capture and UI/Screen debugging using Gemini Vision.
    """
    
    @staticmethod
    def _get_api_key() -> str:
        return os.getenv("GEMINI_API_KEY", "")

    @staticmethod
    def take_screenshot(logger=None) -> Optional[Path]:
        """Captures the main screen and saves it to a temporary file."""
        try:
            import pyautogui
            screenshot_path = Path.home() / "Desktop" / f"jarvis_debug_{int(time.time())}.png"
            screenshot = pyautogui.screenshot()
            screenshot.save(str(screenshot_path))
            if logger:
                logger(f"[Vision] Screenshot captured: {screenshot_path.name}")
            return screenshot_path
        except Exception as e:
            if logger:
                logger(f"[Vision] Screenshot failed: {e}")
            return None

    @staticmethod
    def _image_to_base64(path: Path) -> str:
        import base64
        return base64.b64encode(path.read_bytes()).decode("utf-8")

    @staticmethod
    def debug_screen(description: str, file_path: str = "", file_content: str = "", logger=None) -> str:
        """
        Takes a screenshot and analyzes the screen to answer a question or find a bug.
        Optionally takes code context if a file is being edited.
        """
        if logger:
            logger("[Vision] Taking screenshot for analysis...")

        screenshot_path = VisionDebugger.take_screenshot(logger)
        if not screenshot_path:
            return "Could not take screenshot. Please ensure PyAutoGUI is installed."

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=VisionDebugger._get_api_key())

            image_bytes = screenshot_path.read_bytes()

            user_question = description or "What error or problem do you see on the screen? How can it be fixed?"

            context = ""
            if file_content:
                context = f"\n\nAdditionally, here is the related file content:\n```\n{file_content[:4000]}\n```"

            analysis_prompt = f"""You are an expert programmer and debugger analyzing a screenshot.

User's question: {user_question}{context}

Please:
1. Identify any errors, exceptions, or problems visible on the screen
2. Explain what is causing the problem in simple terms
3. Provide a concrete fix or solution
4. If there's code visible, show the corrected version

Be specific and actionable. If you see an error message, quote it exactly."""

            contents = [
                types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                analysis_prompt,
            ]

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
            )

            analysis = response.text.strip()
            if logger:
                logger("[Vision] Screen analysis complete")

            # Try to save the extracted code if a file path was provided
            if file_path and file_content:
                code_match = re.search(r"```[a-zA-Z]*\n(.*?)```", analysis, re.DOTALL)
                if code_match:
                    fixed_code = code_match.group(1).strip()
                    save_path = Path(file_path)
                    save_path.write_text(fixed_code, encoding="utf-8")
                    analysis += f"\n\nFixed code has been saved to: {file_path}"
                    if logger:
                        logger(f"[Vision] Fixed code saved: {file_path}")

            return analysis

        except Exception as e:
            return f"Screen analysis failed: {e}"
        finally:
            try:
                screenshot_path.unlink()
            except Exception:
                pass
