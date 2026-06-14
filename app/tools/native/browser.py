"""
app/tools/native/browser.py
Native DIMO browser control tool entry point.
Behavioral reference: Mark-XXXIX-OR-main/actions/browser_control.py

This module is the tool function that the registry calls.
It dispatches to BrowserService which wraps DIMO's BrowserManager.
"""

from app.services.browser.browser_service import BrowserService
from app.config.logging import logger


def browser_control(
    action: str,
    url: str = "",
    query: str = "",
    engine: str = "google",
    selector: str = None,
    text: str = "",
    description: str = "",
    direction: str = "down",
    amount: int = 500,
    key: str = "Enter",
    fields: dict = None,
    clear_first: bool = True,
    incognito: bool = False,  # Ignored — DIMO uses a persistent context
) -> dict:
    """
    Controls the web browser natively using DIMO's BrowserManager.

    Actions:
        go_to        — navigate to a URL
        search       — search with a query (engine: google|bing|duckduckgo)
        click        — click element by CSS selector or visible text
        type         — type text into a field (selector, text, clear_first)
        scroll       — scroll the page (direction: up|down, amount in px)
        fill_form    — fill multiple fields ({selector: value} dict)
        smart_click  — find and click element by natural language description
        smart_type   — find and type into field by natural language description
        get_text     — extract visible page text
        press        — press a keyboard key (e.g. Enter, Escape, Tab)
        close        — close the browser
    """
    try:
        act = action.lower().strip()
        result_msg = ""

        if act == "go_to":
            result_msg = BrowserService.go_to(url)

        elif act == "search":
            result_msg = BrowserService.search(query, engine)

        elif act == "click":
            result_msg = BrowserService.click(selector=selector, text=text or None)

        elif act == "type":
            result_msg = _browser_type(selector, text, clear_first)

        elif act == "scroll":
            result_msg = _browser_scroll(direction, amount)

        elif act == "fill_form":
            result_msg = _browser_fill_form(fields or {})

        elif act == "smart_click":
            result_msg = _browser_smart_click(description)

        elif act == "smart_type":
            result_msg = _browser_smart_type(description, text)

        elif act == "get_text":
            result_msg = BrowserService.get_text()

        elif act == "press":
            result_msg = _browser_press(key)

        elif act == "close":
            result_msg = BrowserService.close()

        else:
            return {"success": False, "result": "", "error": f"Unknown browser action: '{action}'"}

        # Determine success heuristically from result message
        error_keywords = ("error", "timeout", "could not find", "failed", "not found", "not clickable")
        success = not any(kw in result_msg.lower() for kw in error_keywords)
        return {"success": success, "result": result_msg, "error": None if success else result_msg}

    except Exception as e:
        logger.error("[Native] browser_control '%s' failed: %s", action, e)
        return {"success": False, "result": "", "error": str(e)}


# ── Internal helpers (extend BrowserService for actions not yet in it) ────────

def _browser_type(selector: str, text: str, clear_first: bool = True) -> str:
    """Type text into the element identified by selector."""
    try:
        page = BrowserService._get_page()
        element = page.locator(selector).first if selector else page.locator(":focus")
        if clear_first:
            element.clear()
        element.type(text, delay=50)
        return "Text typed."
    except Exception as e:
        return f"Type error: {e}"


def _browser_scroll(direction: str = "down", amount: int = 500) -> str:
    """Scroll the page in the given direction by the given pixel amount."""
    try:
        page = BrowserService._get_page()
        y = amount if direction == "down" else -amount
        page.mouse.wheel(0, y)
        return f"Scrolled {direction}."
    except Exception as e:
        return f"Scroll error: {e}"


def _browser_fill_form(fields: dict) -> str:
    """Fill multiple form fields: {selector: value}."""
    try:
        page = BrowserService._get_page()
        results = []
        for sel, value in fields.items():
            try:
                el = page.locator(sel).first
                el.clear()
                el.type(str(value), delay=40)
                results.append(f"OK {sel}")
            except Exception as e:
                results.append(f"FAIL {sel}: {e}")
        return "Form filled: " + ", ".join(results)
    except Exception as e:
        return f"Fill form error: {e}"


def _browser_smart_click(description: str) -> str:
    """Find and click an element by natural language description."""
    try:
        page = BrowserService._get_page()
        desc_lower = description.lower()

        # Role-based hints
        role_hints = {
            "button":    ["button", "btn"],
            "link":      ["link"],
            "searchbox": ["search"],
            "textbox":   ["input", "field"],
        }
        for role, keywords in role_hints.items():
            if any(k in desc_lower for k in keywords):
                try:
                    page.get_by_role(role).first.click(timeout=5000)
                    return f"Clicked ({role}): '{description}'"
                except Exception:
                    pass

        # Text-based fallbacks
        for method, locator in [
            ("text",        page.get_by_text(description, exact=False)),
            ("placeholder", page.get_by_placeholder(description, exact=False)),
        ]:
            try:
                locator.first.click(timeout=5000)
                return f"Clicked ({method}): '{description}'"
            except Exception:
                pass

        return f"Could not find: '{description}'"
    except Exception as e:
        return f"Smart click error: {e}"


def _browser_smart_type(description: str, text: str) -> str:
    """Find and type into an input field by natural language description."""
    try:
        page = BrowserService._get_page()
        for method, locator in [
            ("placeholder", page.get_by_placeholder(description, exact=False)),
            ("label",       page.get_by_label(description, exact=False)),
            ("role",        page.get_by_role("textbox")),
        ]:
            try:
                el = locator.first
                el.clear()
                el.type(text, delay=50)
                return f"Typed into ({method}): '{description}'"
            except Exception:
                continue
        return f"Could not find input: '{description}'"
    except Exception as e:
        return f"Smart type error: {e}"


def _browser_press(key: str) -> str:
    """Press a keyboard key in the browser."""
    try:
        page = BrowserService._get_page()
        page.keyboard.press(key)
        return f"Pressed: {key}"
    except Exception as e:
        return f"Key error: {e}"