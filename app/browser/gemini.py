"""
gemini.py — Gemini and ChatGPT interaction tools for DIMO.

Tools:
    ask_gemini(prompt)    → Send a prompt to gemini.google.com and return the full response
    ask_chatgpt(prompt)   → Send a prompt to chatgpt.com and return the full response

Design notes:
    Both tools follow the same flow:
    1. Navigate to the chat interface (if not already there)
    2. Detect login state — return helpful message if not logged in
    3. Find the message input field using stable ARIA selectors
    4. Type and submit the prompt
    5. Wait for the AI to finish generating (poll until text stabilizes)
    6. Extract and return the complete response text

    "Wait for response to finish" strategy:
        - Wait for the send/stop button to revert from "Stop" → "Send"
          (both Gemini and ChatGPT show a stop button during generation)
        - Poll the response text every 500ms; if it hasn't grown in 3 seconds, 
          consider it done.
        - Hard cap at 60 seconds to avoid hanging.

    Response extraction:
        Gemini  → last `.response-content` or `model-response` element
        ChatGPT → last `[data-message-author-role="assistant"]` element

    Login detection:
        If the input field is not found within 10s, we check for sign-in
        buttons and return a helpful "please log in" message.
"""

import logging
import time
from app.browser.browser_manager import browser_manager, PLAYWRIGHT_AVAILABLE
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger("dimo")

_GEMINI_URL  = "https://gemini.google.com"
_CHATGPT_URL = "https://chatgpt.com"

_NAV_TIMEOUT  = 20_000
_ELEM_TIMEOUT = 12_000
_MAX_WAIT_S   = 90     # max seconds to wait for AI response


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _wait_for_response_stable(page, response_selector: str, poll_interval: float = 0.8,
                               stable_for: float = 3.0, max_wait: float = _MAX_WAIT_S) -> str:
    """
    Poll the response element until its text stops growing.

    Args:
        page:              Playwright page.
        response_selector: CSS selector for the response element.
        poll_interval:     Seconds between polls.
        stable_for:        Seconds of no-growth = done.
        max_wait:          Hard timeout in seconds.

    Returns:
        The final response text, or empty string if nothing found.
    """
    deadline = time.time() + max_wait
    last_text = ""
    stable_since = None

    while time.time() < deadline:
        try:
            elements = page.query_selector_all(response_selector)
            if elements:
                # Always use the LAST response element (newest)
                text = elements[-1].inner_text().strip()
                if text != last_text:
                    last_text = text
                    stable_since = None        # reset stability clock
                else:
                    if stable_since is None:
                        stable_since = time.time()
                    elif time.time() - stable_since >= stable_for:
                        logger.info(f"[ai] Response stable after {time.time() - (deadline - max_wait):.1f}s")
                        return text
        except Exception as e:
            logger.debug(f"[ai] Poll error (ignoring): {e}")

        time.sleep(poll_interval)

    logger.warning("[ai] Hit max wait — returning whatever we have")
    return last_text


def _wait_for_generation_done(page, stop_btn_selector: str, timeout: float = _MAX_WAIT_S) -> None:
    """
    Wait until the 'Stop generating' button disappears (generation complete).
    Falls through silently if the button was never found (already done).
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            btn = page.query_selector(stop_btn_selector)
            if not btn or not btn.is_visible():
                return   # generation done
        except Exception:
            return
        time.sleep(0.5)


# ─────────────────────────────────────────────────────────────────────────────
# Gemini
# ─────────────────────────────────────────────────────────────────────────────

def ask_gemini(prompt: str) -> str:
    """
    Send a prompt to Gemini (gemini.google.com) and return the full response.

    The tool:
    - Navigates to Gemini if not already there
    - Detects if login is needed and returns a helpful message
    - Types and submits the prompt
    - Waits for the full response to generate
    - Returns the complete response text

    Args:
        prompt: Question or instruction for Gemini.

    Returns:
        Structured result dict.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return {"success": False, "result": "", "error": "playwright not installed"}

    try:
        page = browser_manager.get_page()
        logger.info(f"[gemini] Prompt: '{prompt[:80]}...'")

        # Navigate to Gemini if not already there
        if not page.url.startswith(_GEMINI_URL):
            page.goto(_GEMINI_URL, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
            time.sleep(2)

        # ── Detect login state ─────────────────────────────────────────────────
        # Input selectors (in order of preference)
        input_selectors = [
            "rich-textarea div[contenteditable='true']",
            "[aria-label='Enter a prompt here']",
            "textarea[placeholder*='prompt']",
            "div[contenteditable='true'][aria-multiline='true']",
            "p[data-placeholder]",
        ]
        input_el = None
        for sel in input_selectors:
            try:
                el = page.wait_for_selector(sel, timeout=_ELEM_TIMEOUT, state="visible")
                if el:
                    input_el = el
                    break
            except PlaywrightTimeoutError:
                continue

        if input_el is None:
            # Check for sign-in button
            signin_selectors = [
                "a[href*='accounts.google']",
                "button:has-text('Sign in')",
                "[aria-label*='Sign in']",
            ]
            for sel in signin_selectors:
                try:
                    el = page.query_selector(sel)
                    if el:
                        return {
                            "success": False, 
                            "result": "", 
                            "error": "Gemini requires a Google login. Please sign in at gemini.google.com in the Chromium window, then try again."
                        }
                except Exception:
                    continue
            return {"success": False, "result": "", "error": "Could not find the Gemini input field. The page may have changed."}

        # ── Type and submit ────────────────────────────────────────────────────
        input_el.click()
        time.sleep(0.3)
        input_el.fill("")       # clear any previous text
        input_el.type(prompt, delay=20)
        time.sleep(0.3)

        # Submit: try Enter first, then look for send button
        try:
            send_selectors = [
                "button[aria-label='Send message']",
                "button[aria-label='Submit']",
                "button[data-testid='send-button']",
                "mat-icon[fonticon='send']",
            ]
            sent = False
            for sel in send_selectors:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click()
                        sent = True
                        break
                except Exception:
                    continue
            if not sent:
                input_el.press("Enter")
        except Exception:
            input_el.press("Enter")

        logger.info("[gemini] Prompt submitted — waiting for response")
        time.sleep(1.5)

        # ── Wait for generation to complete ────────────────────────────────────
        # Gemini shows a stop button during generation
        _wait_for_generation_done(page, "button[aria-label='Stop generating response']")

        # ── Extract the response ───────────────────────────────────────────────
        # Gemini response selectors (in order of reliability)
        response_selectors = [
            "model-response .response-content",
            "model-response",
            ".response-content",
            "message-content",
            "[data-response-index]",
            ".ProseMirror",          # editor-based response
        ]

        for sel in response_selectors:
            text = _wait_for_response_stable(page, sel, max_wait=60)
            if text:
                logger.info(f"[gemini] Response extracted ({len(text)} chars)")
                return {"success": True, "result": text, "error": None}

        # Last-resort: scrape main content area
        main_content = page.evaluate("""
            () => {
                const el = document.querySelector('main, [role="main"], .conversation-container');
                return el ? el.innerText.trim() : '';
            }
        """)
        if main_content:
            return {"success": True, "result": main_content, "error": None}

        return {"success": False, "result": "", "error": "Gemini responded but the response could not be extracted from the page."}

    except PlaywrightTimeoutError as e:
        logger.error(f"[gemini] Timeout: {e}")
        return {"success": False, "result": "", "error": f"Gemini timed out: {e}"}
    except Exception as e:
        logger.error(f"[gemini] ask_gemini failed: {e}")
        return {"success": False, "result": "", "error": f"Gemini interaction failed: {e}"}


# ─────────────────────────────────────────────────────────────────────────────
# ChatGPT
# ─────────────────────────────────────────────────────────────────────────────

def ask_chatgpt(prompt: str) -> str:
    """
    Send a prompt to ChatGPT (chatgpt.com) and return the full response.

    The tool:
    - Navigates to chatgpt.com if not already there
    - Detects if login is needed and returns a helpful message
    - Types and submits the prompt
    - Waits for the full response (polls until text stabilizes)
    - Returns the complete response text

    Args:
        prompt: Question or instruction for ChatGPT.

    Returns:
        Structured result dict.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return {"success": False, "result": "", "error": "playwright not installed"}

    try:
        page = browser_manager.get_page()
        logger.info(f"[chatgpt] Prompt: '{prompt[:80]}...'")

        # Navigate to ChatGPT if not already there
        if not page.url.startswith(_CHATGPT_URL):
            page.goto(_CHATGPT_URL, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
            time.sleep(2.5)

        # ── Detect login state ─────────────────────────────────────────────────
        input_selectors = [
            "#prompt-textarea",
            "[data-id='root'] textarea",
            "div[contenteditable='true'][id='prompt-textarea']",
            "textarea[placeholder*='Message']",
            "[aria-label='Message ChatGPT']",
        ]
        input_el = None
        for sel in input_selectors:
            try:
                el = page.wait_for_selector(sel, timeout=_ELEM_TIMEOUT, state="visible")
                if el:
                    input_el = el
                    break
            except PlaywrightTimeoutError:
                continue

        if input_el is None:
            # Check for log in prompt
            signin_kws = ["log in", "sign in", "get started"]
            page_text = page.evaluate("document.body.innerText").lower()
            if any(kw in page_text for kw in signin_kws):
                return {
                    "success": False, 
                    "result": "", 
                    "error": "ChatGPT requires login. Please sign in at chatgpt.com in the Chromium window, then try again."
                }
            return {"success": False, "result": "", "error": "Could not find the ChatGPT input field. The page layout may have changed."}

        # ── Type and submit ────────────────────────────────────────────────────
        input_el.click()
        time.sleep(0.3)

        # ChatGPT's textarea needs JS fill for contenteditable divs
        tag = page.evaluate("el => el.tagName.toLowerCase()", input_el)
        if tag == "textarea":
            input_el.fill("")
            input_el.type(prompt, delay=20)
        else:
            # contenteditable div
            input_el.fill("")
            input_el.type(prompt, delay=20)

        time.sleep(0.3)

        # Submit
        sent = False
        send_selectors = [
            "button[data-testid='send-button']",
            "button[aria-label='Send prompt']",
            "button[aria-label='Send message']",
            "button svg[viewBox*='send']",   # SVG icon inside button
        ]
        for sel in send_selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    sent = True
                    break
            except Exception:
                continue
        if not sent:
            input_el.press("Enter")

        logger.info("[chatgpt] Prompt submitted — waiting for response")
        time.sleep(2)

        # ── Wait for generation to finish ──────────────────────────────────────
        # ChatGPT shows a stop button while generating
        stop_selectors = [
            "button[aria-label='Stop streaming']",
            "button[data-testid='stop-button']",
            "button:has-text('Stop')",
        ]
        for stop_sel in stop_selectors:
            _wait_for_generation_done(page, stop_sel, timeout=_MAX_WAIT_S)

        # ── Extract the response ───────────────────────────────────────────────
        response_selectors = [
            "[data-message-author-role='assistant'] .markdown",
            "[data-message-author-role='assistant']",
            ".prose",
            ".message.assistant .content",
            "article[data-testid*='conversation-turn'] p",
        ]

        for sel in response_selectors:
            text = _wait_for_response_stable(page, sel, max_wait=60)
            if text:
                logger.info(f"[chatgpt] Response extracted ({len(text)} chars)")
                return {"success": True, "result": text, "error": None}

        # Last-resort: main content
        main_content = page.evaluate("""
            () => {
                const el = document.querySelector('main, #__next main');
                return el ? el.innerText.trim() : '';
            }
        """)
        if main_content:
            # Filter out UI chrome — look for last substantial block
            lines = [l for l in main_content.split('\n') if len(l.strip()) > 20]
            if lines:
                return {"success": True, "result": "\n".join(lines[-30:]), "error": None}

        return {"success": False, "result": "", "error": "ChatGPT responded but the response could not be extracted from the page."}

    except PlaywrightTimeoutError as e:
        logger.error(f"[chatgpt] Timeout: {e}")
        return {"success": False, "result": "", "error": f"ChatGPT timed out: {e}"}
    except Exception as e:
        logger.error(f"[chatgpt] ask_chatgpt failed: {e}")
        return {"success": False, "result": "", "error": f"ChatGPT interaction failed: {e}"}


# ── Tool catalog entries ───────────────────────────────────────────────────────
GEMINI_CATALOG = {
    "ask_gemini": {
        "name": "ask_gemini",
        "description": (
            "Send a question or prompt to Google Gemini (gemini.google.com) and return "
            "the full AI response. Requires a Google account — log in once in the browser. "
            "Use for complex questions, writing help, code, analysis, or any task for Gemini."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The question or instruction to send to Gemini",
                }
            },
            "required": ["prompt"],
        },
        "function": ask_gemini,
    },
    "ask_chatgpt": {
        "name": "ask_chatgpt",
        "description": (
            "Send a question or prompt to ChatGPT (chatgpt.com) and return the full AI response. "
            "Requires an OpenAI account — log in once in the browser. "
            "Use when the user specifically requests ChatGPT, or as an alternative to Gemini."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The question or instruction to send to ChatGPT",
                }
            },
            "required": ["prompt"],
        },
        "function": ask_chatgpt,
    },
}


# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("=== gemini.py test ===")
    try:
        print("Testing Gemini...")
        result = ask_gemini("What is 2 + 2? Reply in one sentence.")
        print(f"Gemini: {result[:300]}")

        print("\nTesting ChatGPT...")
        result2 = ask_chatgpt("What is the capital of France? Reply in one sentence.")
        print(f"ChatGPT: {result2[:300]}")
    finally:
        browser_manager.shutdown()
