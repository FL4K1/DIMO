"""
clipboard.py — Page content extraction tools for DIMO.

Tools:
    copy_page_content()     → Extract all visible text from the current page
    get_page_title()        → Get the title of the current page
    get_page_links()        → Extract all hyperlinks from the current page
    get_element_text(selector) → Get text from a specific CSS/ARIA selector
"""

import logging
from app.browser.browser_manager import browser_manager, PLAYWRIGHT_AVAILABLE
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger("dimo")


def copy_page_content() -> str:
    """
    Extract all visible text content from the current browser page.

    Uses JavaScript's document.body.innerText which returns text as a
    human would read it (respects display:none, newlines, etc.).

    Returns:
        The full page text (may be very long), or an error string.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed. Run: pip install playwright && playwright install chromium"
    try:
        page = browser_manager.get_page()
        url = page.url
        logger.info(f"[clipboard] Extracting content from: {url}")

        text = page.evaluate("document.body.innerText")
        if not text or not text.strip():
            return f"Page at {url} has no readable text content."

        # Truncate to a reasonable size for the LLM context window
        MAX_CHARS = 8000
        if len(text) > MAX_CHARS:
            logger.info(f"[clipboard] Content truncated from {len(text)} to {MAX_CHARS} chars")
            text = text[:MAX_CHARS] + f"\n\n[... content truncated — {len(text)} total chars]"

        logger.info(f"[clipboard] Extracted {len(text)} chars from {url}")
        return text.strip()

    except Exception as e:
        logger.error(f"[clipboard] copy_page_content failed: {e}")
        return f"Could not extract page content: {e}"


def get_page_title() -> str:
    """
    Return the title of the currently active page.

    Returns:
        Page title string, or error.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed"
    try:
        page = browser_manager.get_page()
        title = page.title()
        url = page.url
        logger.info(f"[clipboard] Page title: '{title}' ({url})")
        return f"'{title}' — {url}"
    except Exception as e:
        logger.error(f"[clipboard] get_page_title failed: {e}")
        return f"Could not get page title: {e}"


def get_page_links() -> str:
    """
    Extract all hyperlinks from the current page.

    Returns:
        Formatted string of "text — url" pairs (up to 20 links), or error.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed"
    try:
        page = browser_manager.get_page()
        logger.info(f"[clipboard] Extracting links from: {page.url}")

        links = page.evaluate("""
            () => {
                const anchors = document.querySelectorAll('a[href]');
                return Array.from(anchors).slice(0, 20).map(a => ({
                    text: (a.innerText || a.getAttribute('aria-label') || '').trim().substring(0, 80),
                    href: a.href
                })).filter(l => l.href.startsWith('http'));
            }
        """)

        if not links:
            return "No links found on the current page."

        lines = [f"{i+1}. {l['text'] or '(no text)'} — {l['href']}" for i, l in enumerate(links)]
        result = "\n".join(lines)
        logger.info(f"[clipboard] Found {len(links)} links")
        return result

    except Exception as e:
        logger.error(f"[clipboard] get_page_links failed: {e}")
        return f"Could not extract links: {e}"


def get_element_text(selector: str) -> str:
    """
    Extract the text content of a specific element on the page.

    Args:
        selector: CSS selector or ARIA label to locate the element.
                  Examples: "h1", "[aria-label='Search results']", "#main-content"

    Returns:
        The element's text content, or an error string.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed"
    try:
        page = browser_manager.get_page()
        logger.info(f"[clipboard] Getting text for selector: '{selector}'")

        element = page.query_selector(selector)
        if not element:
            return f"No element found matching selector: '{selector}'"

        text = element.inner_text()
        if not text or not text.strip():
            return f"Element found but has no text: '{selector}'"

        logger.info(f"[clipboard] Got {len(text)} chars from '{selector}'")
        return text.strip()

    except PlaywrightTimeoutError:
        return f"Timed out waiting for element: '{selector}'"
    except Exception as e:
        logger.error(f"[clipboard] get_element_text failed: {e}")
        return f"Could not get element text for '{selector}': {e}"


# ── Tool catalog entries ───────────────────────────────────────────────────────
CLIPBOARD_CATALOG = {
    "copy_page_content": {
        "name": "copy_page_content",
        "description": (
            "Extract and return all visible text content from the current browser page. "
            "Use after navigating to a page when you need to read its content. "
            "Returns up to 8000 characters of page text."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
        "function": copy_page_content,
    },
    "get_page_title": {
        "name": "get_page_title",
        "description": "Get the title and URL of the currently open browser tab.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "function": get_page_title,
    },
    "get_page_links": {
        "name": "get_page_links",
        "description": "Extract all hyperlinks from the current page (up to 20 links with their text and URLs).",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "function": get_page_links,
    },
    "get_element_text": {
        "name": "get_element_text",
        "description": (
            "Get text from a specific element on the current page using a CSS selector. "
            "Example selectors: 'h1', '#main-content', '[aria-label=\"Search results\"]'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector or aria-label to target a specific element",
                }
            },
            "required": ["selector"],
        },
        "function": get_element_text,
    },
}


# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("=== clipboard.py test ===")
    try:
        from app.browser.tabs import open_url
        print(open_url("https://example.com"))
        print("\n--- Page title ---")
        print(get_page_title())
        print("\n--- Page content (first 300 chars) ---")
        content = copy_page_content()
        print(content[:300])
        print("\n--- Page links ---")
        print(get_page_links())
        print("\n--- H1 element ---")
        print(get_element_text("h1"))
    finally:
        browser_manager.shutdown()
