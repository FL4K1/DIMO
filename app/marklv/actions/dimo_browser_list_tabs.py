"""
dimo_browser_list_tabs.py — Read-only browser tab listing action.

Bridges DIMO's persistent browser tab inspection capability into Mark-LV's
action architecture without modifying core dispatch or application state.
"""

from __future__ import annotations

from actions._dimo_adapter import action_declaration, run_capability


_CAPABILITY_ID = "browser.list_tabs"


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
    result = run_capability(_CAPABILITY_ID, parameters if parameters is not None else {})
    if player:
        try:
            player.write_log("[dimo_browser] Listed open tabs")
        except Exception:
            pass
    return result


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = action_declaration(_CAPABILITY_ID, dimo_browser_list_tabs)
