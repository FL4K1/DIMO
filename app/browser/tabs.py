"""
tabs.py — Tab and URL management tools for DIMO.

Tools:
    open_url(url)              → Navigate the active tab to a URL
    new_tab_url(url)           → Open a URL in a brand-new tab
    close_current_tab()        → Close the active tab
    list_open_tabs()           → Return a formatted list of all open tabs
    switch_to_tab(index)       → Bring a tab to front by index (0-based)
    get_current_url()          → Return the URL of the active page
"""

import logging
from app.browser.browser_manager import browser_manager, PLAYWRIGHT_AVAILABLE
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger("dimo")


def open_url(url: str) -> str:
    """
    Navigate the active Chromium tab to the given URL.

    Args:
        url: Full URL including scheme (e.g. "https://example.com").

    Returns:
        Success message with page title, or error string.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed. Run: pip install playwright && playwright install chromium"
    try:
        page = browser_manager.get_page()
        logger.info(f"[tabs] Navigating to: {url}")
        page.goto(url, wait_until="domcontentloaded")
        title = page.title()
        logger.info(f"[tabs] Loaded: '{title}' at {url}")
        return f"Opened {url} — page title: '{title}'"
    except PlaywrightTimeoutError:
        logger.error(f"[tabs] Timeout loading {url}")
        return f"Timed out while loading {url}. The page may be slow or unreachable."
    except Exception as e:
        logger.error(f"[tabs] open_url failed: {e}")
        return f"Could not open {url}: {e}"


def new_tab_url(url: str) -> str:
    """
    Open a URL in a new browser tab.

    Args:
        url: Full URL to open.

    Returns:
        Success message with page title, or error string.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed"
    try:
        logger.info(f"[tabs] Opening new tab: {url}")
        page = browser_manager.new_tab(url)
        title = page.title()
        logger.info(f"[tabs] New tab loaded: '{title}'")
        return f"Opened new tab for {url} — title: '{title}'"
    except PlaywrightTimeoutError:
        return f"Timed out loading {url} in new tab."
    except Exception as e:
        logger.error(f"[tabs] new_tab_url failed: {e}")
        return f"Could not open new tab for {url}: {e}"


def close_current_tab() -> str:
    """
    Close the currently active tab.

    Returns:
        Confirmation string, or error.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed"
    try:
        pages = browser_manager.list_pages()
        if not pages:
            return "No open tabs to close."
        active = browser_manager.get_page()
        url = active.url
        browser_manager.close_tab(active)
        logger.info(f"[tabs] Closed tab: {url}")
        return f"Closed tab: {url}"
    except Exception as e:
        logger.error(f"[tabs] close_current_tab failed: {e}")
        return f"Could not close tab: {e}"


def list_open_tabs() -> str:
    """
    Return a numbered list of all open tabs with their titles and URLs.

    Returns:
        Formatted string, e.g.:
        "0. Example Domain — https://example.com
         1. YouTube Music — https://music.youtube.com"
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed"
    try:
        pages = browser_manager.list_pages()
        if not pages:
            return "No open tabs."
        lines = []
        for i, page in enumerate(pages):
            try:
                title = page.title() or "(no title)"
            except Exception:
                title = "(unavailable)"
            lines.append(f"{i}. {title} — {page.url}")
        result = "\n".join(lines)
        logger.info(f"[tabs] {len(pages)} open tab(s)")
        return result
    except Exception as e:
        logger.error(f"[tabs] list_open_tabs failed: {e}")
        return f"Could not list tabs: {e}"


def switch_to_tab(index: int) -> str:
    """
    Bring a tab to the front by its index (0-based).

    Args:
        index: Zero-based index from list_open_tabs().

    Returns:
        Confirmation string, or error.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed"
    try:
        pages = browser_manager.list_pages()
        if not pages:
            return "No open tabs."
        if index < 0 or index >= len(pages):
            return f"Invalid tab index {index}. There are {len(pages)} open tabs (0–{len(pages)-1})."
        page = pages[index]
        page.bring_to_front()
        browser_manager.set_active_page(page)
        title = page.title()
        logger.info(f"[tabs] Switched to tab {index}: '{title}'")
        return f"Switched to tab {index}: '{title}' ({page.url})"
    except Exception as e:
        logger.error(f"[tabs] switch_to_tab failed: {e}")
        return f"Could not switch to tab {index}: {e}"


def get_current_url() -> str:
    """
    Return the URL of the currently active page.

    Returns:
        URL string, or error.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed"
    try:
        page = browser_manager.get_page()
        url = page.url
        logger.info(f"[tabs] Current URL: {url}")
        return url
    except Exception as e:
        logger.error(f"[tabs] get_current_url failed: {e}")
        return f"Could not get current URL: {e}"


# ── Tool catalog entries ────────────────────────────────────────────────────────
TABS_CATALOG = {
    "open_url": {
        "name": "open_url",
        "description": (
            "Navigate the browser to a specific URL. Use this to visit any website. "
            "Examples: 'open https://github.com', 'go to https://music.youtube.com'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL including https://"},
            },
            "required": ["url"],
        },
        "function": open_url,
    },
    "new_tab_url": {
        "name": "new_tab_url",
        "description": "Open a URL in a new browser tab, keeping the current tab open.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL to open in new tab"},
            },
            "required": ["url"],
        },
        "function": new_tab_url,
    },
    "close_current_tab": {
        "name": "close_current_tab",
        "description": "Close the currently active browser tab.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "function": close_current_tab,
    },
    "list_open_tabs": {
        "name": "list_open_tabs",
        "description": "List all open browser tabs with their titles and URLs.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "function": list_open_tabs,
    },
    "switch_to_tab": {
        "name": "switch_to_tab",
        "description": "Switch the browser focus to a tab by its index number (from list_open_tabs).",
        "parameters": {
            "type": "object",
            "properties": {
                "index": {"type": "number", "description": "Zero-based tab index"},
            },
            "required": ["index"],
        },
        "function": switch_to_tab,
    },
    "get_current_url": {
        "name": "get_current_url",
        "description": "Get the URL of the current active browser tab.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "function": get_current_url,
    },
}


# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("=== tabs.py test ===")
    try:
        print(open_url("https://example.com"))
        print(list_open_tabs())
        print(new_tab_url("https://playwright.dev"))
        print(list_open_tabs())
        print(switch_to_tab(0))
        print(close_current_tab())
        print(list_open_tabs())
        print(get_current_url())
    finally:
        browser_manager.shutdown()
