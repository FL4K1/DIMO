"""
search.py — Browser-based search tools for DIMO.

Tools:
    browser_search(query)  → Search DuckDuckGo (primary, no CAPTCHA)
    bing_search(query)     → Search Bing (fallback)
    google_search(query)   → Search Google (may hit CAPTCHA)

Design notes:
    - DuckDuckGo is the primary browser search: no account, no CAPTCHA, clean results.
    - Bing is the secondary option.
    - Google is kept but often CAPTCHAs automation — prefer headless web_search for speed.
    - All tools navigate the real browser and scrape visible text.
"""

import logging
import urllib.parse
import time
from app.browser.browser_manager import browser_manager, PLAYWRIGHT_AVAILABLE
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger("dimo")

_DDG_URL    = "https://duckduckgo.com/?q={query}&ia=web"
_BING_URL   = "https://www.bing.com/search?q={query}"
_GOOGLE_URL = "https://www.google.com/search?q={query}&hl=en"


def browser_search(query: str, max_results: int = 5) -> str:
    """
    Search DuckDuckGo in the browser and return top results.

    DuckDuckGo does not CAPTCHA automation, making this the most
    reliable browser-based search option.

    Args:
        query:       Search terms.
        max_results: Number of results to return (default 5, max 10).

    Returns:
        Formatted string of results, or error string.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed. Run: pip install playwright && playwright install chromium"

    max_results = min(max(1, max_results), 10)
    encoded = urllib.parse.quote_plus(query)
    url = _DDG_URL.format(query=encoded)

    try:
        page = browser_manager.get_page()
        logger.info(f"[search] DuckDuckGo: '{query}'")
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(2)   # DDG renders results via JS

        results = page.evaluate(f"""
            () => {{
                const items = [];
                const cards = document.querySelectorAll('[data-testid="result"], article[data-testid]');
                for (const card of cards) {{
                    if (items.length >= {max_results}) break;
                    const titleEl   = card.querySelector('h2 a, [data-testid="result-title-a"]');
                    const snippetEl = card.querySelector('[data-testid="result-snippet"]');
                    const title   = titleEl   ? titleEl.innerText.trim()   : '';
                    const href    = titleEl   ? titleEl.href               : '';
                    const snippet = snippetEl ? snippetEl.innerText.trim() : '';
                    if (title && href && href.startsWith('http')) {{
                        items.push({{ title, href, snippet }});
                    }}
                }}
                return items;
            }}
        """)

        if not results:
            # Fallback: grab external links from the page
            results = page.evaluate(f"""
                () => {{
                    const items = [];
                    const links = document.querySelectorAll('a[href^="https"]');
                    for (const a of links) {{
                        if (items.length >= {max_results}) break;
                        const text = a.innerText.trim();
                        if (text.length > 10 && !a.href.includes('duckduckgo.com')) {{
                            items.push({{ title: text.substring(0, 80), href: a.href, snippet: '' }});
                        }}
                    }}
                    return items;
                }}
            """)

        if not results:
            return f"DuckDuckGo search for '{query}' returned no results. Try web_search instead."

        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet']}")
            lines.append(f"   {r['href']}")
            lines.append("")

        result_str = "\n".join(lines).strip()
        logger.info(f"[search] Returned {len(results)} DDG results for '{query}'")
        return f"Search results for '{query}':\n\n{result_str}"

    except PlaywrightTimeoutError:
        logger.error(f"[search] Timeout for '{query}'")
        return f"Browser search timed out for: '{query}'"
    except Exception as e:
        logger.error(f"[search] browser_search failed: {e}")
        return f"Browser search failed: {e}"


def google_search(query: str, max_results: int = 5) -> str:
    """
    Search Google and return top organic results.

    NOTE: Google frequently blocks automation with a CAPTCHA.
    Prefer browser_search (DuckDuckGo) for reliable results.

    Args:
        query:       Search terms.
        max_results: Number of results (default 5, max 10).

    Returns:
        Formatted results string, or error/fallback string.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed. Run: pip install playwright && playwright install chromium"

    max_results = min(max(1, max_results), 10)
    encoded = urllib.parse.quote_plus(query)
    url = _GOOGLE_URL.format(query=encoded)

    try:
        page = browser_manager.get_page()
        logger.info(f"[search] Google: '{query}'")
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(1.5)

        page_text = page.evaluate("document.body.innerText") or ""
        if any(kw in page_text.lower() for kw in ["captcha", "i'm not a robot", "before you continue"]):
            logger.warning("[search] Google CAPTCHA detected — falling back to browser_search")
            return browser_search(query, max_results)

        results = page.evaluate(f"""
            () => {{
                const items = [];
                const cards = document.querySelectorAll('#search .g, #rso .g');
                for (const card of cards) {{
                    if (items.length >= {max_results}) break;
                    const titleEl   = card.querySelector('h3');
                    const linkEl    = card.querySelector('a[href]');
                    const snippetEl = card.querySelector('.VwiC3b, .yXK7lf');
                    const title   = titleEl   ? titleEl.innerText.trim()   : '';
                    const href    = linkEl    ? linkEl.href                : '';
                    const snippet = snippetEl ? snippetEl.innerText.trim() : '';
                    if (title && href && href.startsWith('http')) {{
                        items.push({{ title, href, snippet }});
                    }}
                }}
                return items;
            }}
        """)

        if not results:
            logger.warning("[search] Google results not parsed — falling back to browser_search")
            return browser_search(query, max_results)

        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet']}")
            lines.append(f"   {r['href']}")
            lines.append("")

        result_str = "\n".join(lines).strip()
        logger.info(f"[search] Returned {len(results)} Google results for '{query}'")
        return f"Google search results for '{query}':\n\n{result_str}"

    except PlaywrightTimeoutError:
        return f"Google search timed out for: '{query}'"
    except Exception as e:
        logger.error(f"[search] google_search failed: {e}")
        return f"Google search failed: {e}"


def bing_search(query: str, max_results: int = 5) -> str:
    """
    Search Bing and return top results.

    Args:
        query:       Search terms.
        max_results: Number of results to return.

    Returns:
        Formatted results string, or error string.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed"

    max_results = min(max(1, max_results), 10)
    encoded = urllib.parse.quote_plus(query)
    url = _BING_URL.format(query=encoded)

    try:
        page = browser_manager.get_page()
        logger.info(f"[search] Bing: '{query}'")
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(1)

        results = page.evaluate(f"""
            () => {{
                const items = [];
                const cards = document.querySelectorAll('#b_results li.b_algo');
                for (const card of cards) {{
                    if (items.length >= {max_results}) break;
                    const titleEl   = card.querySelector('h2 a');
                    const snippetEl = card.querySelector('.b_caption p');
                    const title   = titleEl   ? titleEl.innerText.trim()   : '';
                    const href    = titleEl   ? titleEl.href               : '';
                    const snippet = snippetEl ? snippetEl.innerText.trim() : '';
                    if (title && href.startsWith('http')) {{
                        items.push({{ title, href, snippet }});
                    }}
                }}
                return items;
            }}
        """)

        if not results:
            return f"Bing search for '{query}' returned no parseable results."

        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet']}")
            lines.append(f"   {r['href']}")
            lines.append("")

        result_str = "\n".join(lines).strip()
        logger.info(f"[search] Returned {len(results)} Bing results")
        return f"Bing search results for '{query}':\n\n{result_str}"

    except Exception as e:
        logger.error(f"[search] bing_search failed: {e}")
        return f"Bing search failed: {e}"


# ── Tool catalog entries ───────────────────────────────────────────────────────
SEARCH_BROWSER_CATALOG = {
    "browser_search": {
        "name": "browser_search",
        "description": (
            "Search the web using DuckDuckGo in the browser. Reliable, no CAPTCHA, no account needed. "
            "Returns titles, snippets, and URLs. Use for browser-visible searches. "
            "For fast headless search, use web_search instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "number", "description": "Number of results (1-10, default 5)"},
            },
            "required": ["query"],
        },
        "function": browser_search,
    },
    "google_search": {
        "name": "google_search",
        "description": (
            "Search Google in the browser. NOTE: Google often blocks automation. "
            "Prefer browser_search (DuckDuckGo) for reliability."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "number", "description": "Number of results (1-10, default 5)"},
            },
            "required": ["query"],
        },
        "function": google_search,
    },
    "bing_search": {
        "name": "bing_search",
        "description": "Search Bing in the browser and return top results.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "number", "description": "Number of results (default 5)"},
            },
            "required": ["query"],
        },
        "function": bing_search,
    },
}


# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("=== search.py test ===")
    try:
        result = browser_search("Python Playwright tutorial", max_results=3)
        print(result)
    finally:
        browser_manager.shutdown()
