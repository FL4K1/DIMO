"""
BrowserManager — Persistent Chromium singleton for DIMO.

Architecture:
    This module owns a single Playwright BrowserContext launched with
    `launch_persistent_context`. That means:
      - Cookies, localStorage, and IndexedDB are saved to disk between runs.
      - After a one-time manual login to WhatsApp Web / YouTube Music / Gemini /
        ChatGPT, every future DIMO session is already authenticated — no
        credentials stored in code.
      - A single Chromium process is shared by all browser tools, avoiding the
        startup cost of launching a new browser per action.

Thread safety:
    A threading.Lock guards context creation and page operations so the tool
    loop can safely call browser tools from multiple iterations without racing.

Auto-recovery:
    If Chromium crashes between tool calls, the next `get_page()` call detects
    the dead context and re-launches automatically.

Configuration (.env):
    CHROMIUM_PROFILE_DIR  — where to save the persistent profile
                            (default: ~/.dimo/chromium_profile)
    BROWSER_HEADLESS      — "true" / "false"  (default: false)
    BROWSER_SLOW_MO       — milliseconds between actions (default: 0)
    BROWSER_TIMEOUT       — default Playwright timeout ms (default: 15000)
"""

import os
import threading
import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("dimo")

# ── Configuration ─────────────────────────────────────────────────────────────
_PROFILE_DIR = os.getenv(
    "CHROMIUM_PROFILE_DIR",
    str(Path.home() / ".dimo" / "chromium_profile"),
)
_HEADLESS = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
_SLOW_MO = int(os.getenv("BROWSER_SLOW_MO", "0"))
_TIMEOUT = int(os.getenv("BROWSER_TIMEOUT", "15000"))

# ── Optional import guard ──────────────────────────────────────────────────────
try:
    from playwright.sync_api import (
        sync_playwright,
        BrowserContext,
        Page,
        Playwright,
        TimeoutError as PlaywrightTimeoutError,
    )
    PLAYWRIGHT_AVAILABLE = True
    logger.info("[BrowserManager] playwright.sync_api loaded OK")
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning(
        "[BrowserManager] playwright not installed. "
        "Run: pip install playwright && playwright install chromium"
    )


class BrowserManager:
    """
    Singleton browser manager.

    Usage (anywhere in DIMO):
        from app.browser.browser_manager import browser_manager
        page = browser_manager.get_page()
        page.goto("https://example.com")
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._playwright: Optional["Playwright"] = None
        self._context: Optional["BrowserContext"] = None
        self._active_page: Optional["Page"] = None

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _is_alive(self) -> bool:
        """Check whether our Playwright context is still usable."""
        if not PLAYWRIGHT_AVAILABLE:
            return False
        if self._playwright is None or self._context is None:
            return False
        try:
            # Accessing .pages raises if the browser has crashed / been closed
            _ = self._context.pages
            return True
        except Exception:
            return False

    def _launch(self) -> None:
        """
        Launch a persistent Chromium context.

        Called inside the lock — never call directly; use get_page() instead.
        """
        logger.info(f"[BrowserManager] Launching Chromium (profile: {_PROFILE_DIR})")
        Path(_PROFILE_DIR).mkdir(parents=True, exist_ok=True)

        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=_PROFILE_DIR,
            headless=_HEADLESS,
            slow_mo=_SLOW_MO,
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions-except=",   # block extension downloads
                # ── Stealth flags to avoid bot detection ──────────────────────
                "--disable-blink-features=AutomationControlled",
                "--exclude-switches=enable-automation",
                "--disable-infobars",
                "--lang=en-US,en",
                "--start-maximized",
            ],
            ignore_default_args=["--enable-automation"],
            # Give every action a sensible default timeout
            timeout=_TIMEOUT,
        )
        self._context.set_default_timeout(_TIMEOUT)
        self._context.set_default_navigation_timeout(_TIMEOUT * 2)  # nav can be slow

        # ── Patch navigator.webdriver on every page ────────────────────────────
        # This removes the primary fingerprint Google uses to block automation.
        self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            // Remove CDP leak
            delete window.__playwright;
            delete window.__pw_manual;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
        """)

        # Reuse the first existing page (persistent context always opens one)
        pages = self._context.pages
        self._active_page = pages[0] if pages else self._context.new_page()
        logger.info("[BrowserManager] Chromium context ready")

    def _ensure_alive(self) -> None:
        """Re-launch if the context is dead. Always called inside the lock."""
        if not self._is_alive():
            logger.warning("[BrowserManager] Context dead — re-launching")
            self._teardown_nolock()
            self._launch()

    def _teardown_nolock(self) -> None:
        """Tear down resources without acquiring the lock (caller holds it)."""
        for obj, name in [
            (self._context, "context"),
            (self._playwright, "playwright"),
        ]:
            if obj is not None:
                try:
                    obj.close()
                    logger.debug(f"[BrowserManager] Closed {name}")
                except Exception as exc:
                    logger.debug(f"[BrowserManager] Error closing {name}: {exc}")
        self._context = None
        self._playwright = None
        self._active_page = None

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def context(self) -> Optional["BrowserContext"]:
        """Direct access to the BrowserContext (for advanced use)."""
        return self._context

    def get_page(self, url: Optional[str] = None) -> "Page":
        """
        Return the active page, launching Chromium if needed.

        If `url` is provided and the current page is not already at that origin,
        the page is navigated there first.

        Args:
            url: Optional URL to navigate to before returning the page.

        Returns:
            A live Playwright Page ready for interaction.

        Raises:
            RuntimeError: If playwright is not installed.
        """
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "playwright not installed. "
                "Run: pip install playwright && playwright install chromium"
            )

        with self._lock:
            # We wrap the logic in a retry loop. If `context.pages` or `context.new_page()`
            # throws TargetClosedError or similar, we catch it, recreate the context, and retry once.
            for attempt in range(2):
                try:
                    self._ensure_alive()

                    # Pick a live page
                    pages = self._context.pages
                    
                    # Drop dead page references
                    if self._active_page and self._active_page.is_closed():
                        logger.debug("[BrowserManager] Active page was closed, dropping reference.")
                        self._active_page = None

                    if not pages:
                        self._active_page = self._context.new_page()
                        logger.debug("[BrowserManager] Opened new page (context was empty)")
                    else:
                        # Prefer the previously active page; fall back to last open tab
                        if self._active_page not in pages:
                            self._active_page = pages[-1]

                    page = self._active_page

                    if url:
                        current_url = page.url
                        # Only navigate if we're not already there (same origin + path)
                        if not current_url.startswith(url.split("?")[0]):
                            logger.info(f"[BrowserManager] Navigating to {url}")
                            page.goto(url, wait_until="domcontentloaded")

                    return page

                except Exception as e:
                    logger.warning(f"[BrowserManager] Error getting page on attempt {attempt+1}: {e}")
                    if attempt == 0:
                        logger.info("[BrowserManager] Forcing context teardown and retry...")
                        self._teardown_nolock()
                    else:
                        raise e

    def new_tab(self, url: Optional[str] = None) -> "Page":
        """
        Open a brand-new tab, optionally navigating to `url`.

        Returns:
            The new Page object.
        """
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("playwright not installed")

        with self._lock:
            self._ensure_alive()
            page = self._context.new_page()
            self._active_page = page
            logger.info(f"[BrowserManager] Opened new tab{' → ' + url if url else ''}")
            if url:
                page.goto(url, wait_until="domcontentloaded")
        return page

    def close_tab(self, page: "Page") -> None:
        """
        Close a specific tab.

        If it was the active page, the manager falls back to the last remaining
        open tab (or opens a blank one if none remain).
        """
        with self._lock:
            try:
                page.close()
                logger.info("[BrowserManager] Tab closed")
            except Exception as exc:
                logger.warning(f"[BrowserManager] Error closing tab: {exc}")

            pages = self._context.pages if self._context else []
            if pages:
                self._active_page = pages[-1]
            else:
                self._active_page = self._context.new_page() if self._context else None

    def set_active_page(self, page: "Page") -> None:
        """Mark a page as the active one (used by tabs.py after switch)."""
        with self._lock:
            self._active_page = page

    def list_pages(self) -> list:
        """Return all open pages in the context."""
        with self._lock:
            if not self._is_alive():
                return []
            return list(self._context.pages)

    def shutdown(self) -> None:
        """
        Gracefully shut down Chromium. Called via atexit in main.py.

        Safe to call even if the browser was never launched.
        """
        with self._lock:
            if self._context is not None or self._playwright is not None:
                logger.info("[BrowserManager] Shutting down Chromium...")
                self._teardown_nolock()
                logger.info("[BrowserManager] Shutdown complete")


# ── Module-level singleton ─────────────────────────────────────────────────────
# All browser tools import this single instance.
browser_manager = BrowserManager()


# ── Standalone smoke test ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("=== BrowserManager smoke test ===")
    try:
        page = browser_manager.get_page("https://example.com")
        title = page.title()
        print(f"✓ Page loaded — title: '{title}'")

        tab2 = browser_manager.new_tab("https://playwright.dev")
        title2 = tab2.title()
        print(f"✓ New tab loaded — title: '{title2}'")

        browser_manager.close_tab(tab2)
        print("✓ Tab closed")

        pages = browser_manager.list_pages()
        print(f"✓ Open tabs: {len(pages)}")

    except Exception as e:
        print(f"✗ Test failed: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        browser_manager.shutdown()
        print("✓ Shutdown complete")
