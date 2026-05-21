"""
Browser Agent for DIMO — powered by browser-use v0.12.7 + Playwright.

API changes from older browser-use versions:
  - BrowserConfig   → BrowserProfile
  - Browser         → BrowserSession
  - ChatOllama is now built into browser_use (browser_use.llm.ollama.chat)
    (do NOT use langchain_ollama here — it uses a different interface)
  - Agent takes browser_session=BrowserSession(browser_profile=BrowserProfile(...))

Key design decisions:
  - DIMO's main loop is synchronous; browser-use is async.
    We bridge this via asyncio.run() inside a dedicated thread.
  - use_vision=False for local LLMs that lack vision capability.
  - Browser profile is shared at ~/.dimo/browser_data so login sessions
    (YouTube Music, WhatsApp Web, Gemini) persist across calls.
  - A module-level BrowserSession singleton is kept alive between tasks to
    avoid the slow cold-start of launching Brave on every call.
"""

import asyncio
import logging
import os
import threading
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("dimo")

OLLAMA_HOST           = os.getenv("OLLAMA_HOST", "http://localhost:11434")
BROWSER_AGENT_MODEL   = os.getenv("BROWSER_AGENT_MODEL", "qwen2.5:7b")
BROWSER_AGENT_TIMEOUT = int(os.getenv("BROWSER_AGENT_TIMEOUT", "120"))
# IMPORTANT: Use a SEPARATE dir from browser_tools.py (~/.dimo/browser_data)
# so Playwright and browser-use never conflict over the same profile lock.
_BROWSER_DATA_DIR     = str(Path.home() / ".dimo" / "browser_data_agent")


def _find_brave_exe() -> str | None:
    """Locate the Brave browser executable on Windows."""
    candidates = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        str(Path.home() / "AppData" / "Local" / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    logger.warning("[BROWSER AGENT] Brave executable not found — falling back to default Chromium")
    return None


# ── Optional import guards ────────────────────────────────────────────────────
try:
    # pyrefly: ignore [missing-import]
    from browser_use import Agent, BrowserSession, BrowserProfile
    # pyrefly: ignore [missing-import]
    from browser_use.llm.ollama.chat import ChatOllama as BrowserUseChatOllama
    BROWSER_USE_AVAILABLE = True
    logger.info("[BROWSER AGENT] browser-use v0.12+ loaded successfully")
except Exception as e:
    BROWSER_USE_AVAILABLE = False
    logger.warning(f"[BROWSER AGENT] browser-use unavailable: {e}")
    logger.warning("  Run: pip install browser-use && playwright install chromium")

# ── Module-level BrowserSession singleton ─────────────────────────────────────
_session_instance: "BrowserSession | None" = None
_session_lock = threading.Lock()


def _get_session() -> "BrowserSession":
    """Return a shared BrowserSession using bundled Chromium, creating it if needed.

    Uses browser-use's own bundled Chromium (NOT Brave) to avoid any profile
    lock conflicts with browser_tools.py which uses Brave via Playwright.
    Each tool has its own profile directory so they can run simultaneously.
    """
    global _session_instance
    with _session_lock:
        if _session_instance is not None:
            return _session_instance

        brave_exe = _find_brave_exe()
        profile_kwargs: dict = dict(
            headless=False,
            # Separate profile dir — avoids lock conflict with browser_tools.py
            user_data_dir=_BROWSER_DATA_DIR,
            keep_alive=True,
            # Disable extension auto-downloads — saves 30s+ on first run
            enable_default_extensions=False,
            disable_security=True,
        )
        if brave_exe:
            # Use Brave instead of bundled Chromium — consistent with the rest of DIMO
            profile_kwargs["browser_binary_path"] = brave_exe
            logger.info(f"[BROWSER AGENT] Using Brave: {brave_exe}")
        else:
            logger.info("[BROWSER AGENT] Brave not found — using bundled Chromium")

        profile = BrowserProfile(**profile_kwargs)
        _session_instance = BrowserSession(browser_profile=profile)
        logger.info(f"[BROWSER AGENT] BrowserSession created (profile: {_BROWSER_DATA_DIR})")
        return _session_instance


async def _run_browser_task_async(task: str, max_steps: int = 25) -> str:
    """
    Internal async implementation. Creates a browser-use Agent for the task
    and runs it, returning the final result string.
    """
    if not BROWSER_USE_AVAILABLE:
        return "browser-use not installed. Run: pip install browser-use && playwright install chromium"

    # Use browser-use's built-in ChatOllama (not langchain_ollama)
    llm = BrowserUseChatOllama(
        model=BROWSER_AGENT_MODEL,
        host=OLLAMA_HOST,
        ollama_options={"num_ctx": 32000, "temperature": 0},
    )

    session = _get_session()

    agent = Agent(
        task=task,
        llm=llm,
        browser=session,          # 'browser' is the alias for browser_session
        use_vision=False,         # Text-only — works with all Ollama models
        max_actions_per_step=5,
        max_failures=3,
        use_thinking=False,       # Disable thinking to reduce token usage
        enable_planning=False,    # Disable planning for local LLMs
    )

    logger.info(f"[BROWSER AGENT] Starting task: {task[:120]}")

    try:
        history = await agent.run(max_steps=max_steps)
        # Extract the final result from the agent's history
        result = history.final_result()
        if result:
            logger.info(f"[BROWSER AGENT] Task complete: {str(result)[:200]}")
            return str(result)
        # Fallback: get the last action description
        if history.action_names():
            last_actions = history.action_names()[-3:]
            return f"Task completed. Last actions: {', '.join(last_actions)}"
        return "Task completed."
    except Exception as e:
        logger.error(f"[BROWSER AGENT] Task failed: {e}")
        return f"Browser task failed: {e}"


def browser_task(task: str, timeout: int = None) -> str:
    """
    Execute any browser task autonomously using natural language.

    The browser-use Agent will:
      - Navigate to the right website in Brave
      - Click, type, scroll as needed
      - Return the result or confirmation

    Args:
        task:    Plain English description of what to do in the browser.
                 Be specific — e.g. "Go to YouTube Music, search for Blinding
                 Lights by The Weeknd, and click the first song to play it."
        timeout: Max seconds to wait (default: BROWSER_AGENT_TIMEOUT env var).

    Returns:
        String describing what was accomplished, or an error message.
    """
    if not BROWSER_USE_AVAILABLE:
        return (
            "browser-use not available. "
            "Run: pip install browser-use && playwright install chromium"
        )

    _timeout = timeout or BROWSER_AGENT_TIMEOUT
    result_container: list[str] = []
    exception_container: list[Exception] = []

    def _thread_target():
        """Run the async task in a dedicated event loop (thread-safe)."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_run_browser_task_async(task))
            result_container.append(result)
        except Exception as e:
            exception_container.append(e)
        finally:
            loop.close()

    thread = threading.Thread(target=_thread_target, daemon=True)
    thread.start()
    thread.join(timeout=_timeout)

    if thread.is_alive():
        logger.warning(f"[BROWSER AGENT] Task timed out after {_timeout}s")
        return (
            f"Browser task timed out after {_timeout}s. "
            "The browser is still open — check it manually."
        )

    if exception_container:
        err = exception_container[0]
        logger.error(f"[BROWSER AGENT] Uncaught exception: {err}")
        return f"Browser task error: {err}"

    return result_container[0] if result_container else "Task completed (no result returned)."


def browser_agent_close() -> str:
    """Close the shared BrowserSession and free resources."""
    global _session_instance
    with _session_lock:
        if _session_instance is not None:
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(_session_instance.close())
                loop.close()
            except Exception:
                pass
            _session_instance = None
            logger.info("[BROWSER AGENT] BrowserSession closed.")
    return "Browser agent closed."


# ── Tool catalog entry ────────────────────────────────────────────────────────
BROWSER_AGENT_CATALOG: dict = {
    "browser_task": {
        "name": "browser_task",
        "description": (
            "Perform ANY complex browser task using natural language in Brave browser. "
            "Use this for: playing a specific song on YouTube Music, chatting with Gemini/ChatGPT/Claude, "
            "sending WhatsApp messages, searching and clicking results, filling forms, "
            "reading page content, shopping, booking, and any other web interaction. "
            "Describe exactly what to do — the AI browser agent will handle it. "
            "Examples: 'Go to music.youtube.com and play Blinding Lights by The Weeknd', "
            "'Open Gemini and ask it about rising gold prices', "
            "'Send a WhatsApp message to Mom saying I will be late'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Clear natural language description of the browser task to perform"
                },
                "timeout": {
                    "type": "number",
                    "description": "Max seconds to wait (optional, default 120)"
                },
            },
            "required": ["task"],
        },
        "function": browser_task,
    },
}
