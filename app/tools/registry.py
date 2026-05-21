"""
Tool registry for DIMO.

TOOL_CATALOG is the single source of truth for all tools available to
the planning and execution nodes. Each entry maps a tool name to its
description (used by the planner LLM), parameter schema (used by the
validator), and function reference (called by the executor).

Adding a new tool:
    1. Implement it in app/tools/ or app/browser/
    2. Add its catalog entry (see module CATALOG dicts for the pattern)
    3. Import and merge its catalog here — that's it.
"""

from typing import Optional, Callable

from app.config.logging import logger

# ── Core headless tools ───────────────────────────────────────────────────────
from app.tools.search import web_search

# ── System tools ──────────────────────────────────────────────────────────────
from app.system.apps import SYSTEM_APPS_CATALOG

# ── Browser subsystem tools ───────────────────────────────────────────────────
# Imported lazily inside try/except so DIMO still works if playwright is
# not installed (tools will return "playwright not installed" strings).
try:
    from app.browser.tabs import TABS_CATALOG
    from app.browser.clipboard import CLIPBOARD_CATALOG
    from app.browser.search import SEARCH_BROWSER_CATALOG
    from app.browser.youtube_music import YOUTUBE_MUSIC_CATALOG
    from app.browser.whatsapp import WHATSAPP_CATALOG
    from app.browser.gemini import GEMINI_CATALOG
    _BROWSER_CATALOGS_LOADED = True
    logger.info("[registry] Browser tool catalogs loaded")
except ImportError as _e:
    _BROWSER_CATALOGS_LOADED = False
    TABS_CATALOG = {}
    CLIPBOARD_CATALOG = {}
    SEARCH_BROWSER_CATALOG = {}
    YOUTUBE_MUSIC_CATALOG = {}
    WHATSAPP_CATALOG = {}
    GEMINI_CATALOG = {}
    logger.warning(f"[registry] Browser catalogs not loaded: {_e}")


# ── Core catalog (always available) ──────────────────────────────────────────
TOOL_CATALOG: dict = {
    "web_search": {
        "name": "web_search",
        "description": (
            "Search the web for current information using DuckDuckGo (headless, no browser needed). "
            "Fast and reliable for general information lookups, news, facts."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to execute",
                }
            },
            "required": ["query"],
        },
        "function": web_search,
    },
}

# ── Merge browser catalogs ─────────────────────────────────────────────────────
TOOL_CATALOG.update(TABS_CATALOG)
TOOL_CATALOG.update(CLIPBOARD_CATALOG)
TOOL_CATALOG.update(SEARCH_BROWSER_CATALOG)
TOOL_CATALOG.update(YOUTUBE_MUSIC_CATALOG)
TOOL_CATALOG.update(WHATSAPP_CATALOG)
TOOL_CATALOG.update(GEMINI_CATALOG)

# ── Merge system catalogs ──────────────────────────────────────────────────────
TOOL_CATALOG.update(SYSTEM_APPS_CATALOG)

logger.info(f"[registry] {len(TOOL_CATALOG)} tools registered: {list(TOOL_CATALOG.keys())}")


def get_tool(tool_name: str) -> Optional[Callable]:
    """
    Retrieve a tool function by name.

    Args:
        tool_name: Name of the tool (must be a key in TOOL_CATALOG).

    Returns:
        The callable function for the tool, or None if not found.
    """
    tool_info = TOOL_CATALOG.get(tool_name)
    if not tool_info:
        logger.warning(f"[registry] Tool '{tool_name}' not found in catalog")
        return None
    return tool_info["function"]


def list_tools() -> str:
    """Return a formatted list of all registered tools and their descriptions."""
    lines = []
    for name, info in TOOL_CATALOG.items():
        desc = info.get("description", "")[:80]
        lines.append(f"  {name}: {desc}")
    return "\n".join(lines)
