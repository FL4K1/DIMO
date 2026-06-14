from app.browser.browser_manager import browser_manager
from app.config.logging import logger
from playwright.sync_api import TimeoutError as PlaywrightTimeout

class BrowserService:
    """Provides high-level browser automation using DIMO's existing singleton BrowserManager."""
    
    @classmethod
    def _get_page(cls):
        return browser_manager.get_page()

    @classmethod
    def go_to(cls, url: str) -> str:
        if not url.startswith("http"):
            url = "https://" + url
        page = cls._get_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            return f"Opened: {page.url}"
        except PlaywrightTimeout:
            return f"Timeout loading: {url}"
        except Exception as e:
            logger.error(f"[BrowserService] Navigation error: {e}")
            return f"Navigation error: {e}"

    @classmethod
    def search(cls, query: str, engine: str = "google") -> str:
        engines = {
            "google":     f"https://www.google.com/search?q={query.replace(' ', '+')}",
            "bing":       f"https://www.bing.com/search?q={query.replace(' ', '+')}",
            "duckduckgo": f"https://duckduckgo.com/?q={query.replace(' ', '+')}",
        }
        url = engines.get(engine.lower(), engines["google"])
        return cls.go_to(url)

    @classmethod
    def click(cls, selector: str = None, text: str = None) -> str:
        page = cls._get_page()
        try:
            if text:
                page.get_by_text(text, exact=False).first.click(timeout=8000)
                return f"Clicked: '{text}'"
            elif selector:
                page.click(selector, timeout=8000)
                return f"Clicked: {selector}"
            return "No selector or text provided."
        except PlaywrightTimeout:
            return "Element not found or not clickable."
        except Exception as e:
            logger.error(f"[BrowserService] Click error: {e}")
            return f"Click error: {e}"

    @classmethod
    def get_text(cls) -> str:
        try:
            return cls._get_page().inner_text("body")[:5000]
        except Exception:
            return "Failed to get text."

    @classmethod
    def close(cls) -> str:
        # In DIMO native, the BrowserManager lifecycle is persistent and managed by the core.
        return "Browser closed (managed by DIMO core)."
