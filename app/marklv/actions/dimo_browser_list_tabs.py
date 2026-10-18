"""
dimo_browser_list_tabs.py — Read-only browser tab listing action.

Bridges DIMO's persistent browser tab inspection capability into Mark-LV's
action architecture without modifying core dispatch or application state.
"""

from __future__ import annotations

import sys
from pathlib import Path


def dimo_browser_list_tabs(
    parameters: dict | None = None,
    player=None,
    session_memory=None,
    speak=None,
    response=None,
) -> str:
    """
    List all open browser tabs in the active DIMO browser session.

    Read-only action. Queries the browser manager for currently open pages
    and formats their 0-based indices, titles, and URLs. Does not launch
    a new browser instance or navigate existing tabs if none are open.
    """
    try:
        # Ensure repository root is on sys.path for app.* package resolution
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))

        # Lazy import of DIMO tabs implementation to avoid hard startup dependency
        from app.browser.tabs import list_open_tabs

        result = list_open_tabs()

        if player:
            try:
                player.write_log("[dimo_browser] Listed open tabs")
            except Exception:
                pass

        return result or "No open tabs."

    except ImportError as e:
        msg = f"Browser tab listing is unavailable (missing dependency: {e})."
        if player:
            try:
                player.write_log(f"ERR: {msg}")
            except Exception:
                pass
        return msg
    except Exception as e:
        msg = f"Failed to list browser tabs: {e}"
        if player:
            try:
                player.write_log(f"ERR: {msg}")
            except Exception:
                pass
        return msg


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "dimo_browser_list_tabs",
    "description": (
        "Lists all currently open browser tabs in the active browser session, "
        "including their 0-based index numbers, page titles, and URLs. "
        "Use this to inspect open web pages before switching or closing tabs."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    },
    "handler": dimo_browser_list_tabs,
}
