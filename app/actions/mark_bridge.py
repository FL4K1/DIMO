"""
app/actions/mark_bridge.py — Bridge infrastructure for Mark-XXXIX-OR-main action modules.

Provides:
  - MARK_ROOT: pathlib.Path to the embedded Mark-XXXIX-OR-main directory
  - ensure_mark_on_path(): adds MARK_ROOT to sys.path once
  - MockPlayer: no-op substitute for Mark's JarvisUI player argument

Usage (inside any wrapper in wrappers.py):
    from app.actions.mark_bridge import ensure_mark_on_path, MockPlayer
    ensure_mark_on_path()
    from actions.weather_report import weather_action
    result = weather_action(parameters={"city": city}, player=MockPlayer())
"""

import sys
import logging
from pathlib import Path

logger = logging.getLogger("dimo.mark_bridge")

# ── Locate the embedded Mark project ─────────────────────────────────────────
# Mark-XXXIX-OR-main lives at the DIMO project root, confirmed by directory
# listing: c:\...\DIMO\Mark-XXXIX-OR-main\
_DIMO_ROOT = Path(__file__).resolve().parents[2]  # DIMO project root
MARK_ROOT = _DIMO_ROOT / "Mark-XXXIX-OR-main"

_path_injected = False


def ensure_mark_on_path() -> bool:
    """
    Add Mark-XXXIX-OR-main to sys.path exactly once so its `actions/` package
    is importable.

    Returns:
        True if Mark root exists and was added (or was already present).
        False if the directory could not be found (logs a warning).
    """
    global _path_injected
    if _path_injected:
        return True

    mark_str = str(MARK_ROOT)
    if not MARK_ROOT.exists():
        logger.warning(
            "[mark_bridge] Mark-XXXIX-OR-main not found at expected path: %s", MARK_ROOT
        )
        return False

    if mark_str not in sys.path:
        sys.path.insert(0, mark_str)
        logger.info("[mark_bridge] Added Mark root to sys.path: %s", mark_str)

    _path_injected = True
    return True


class MockPlayer:
    """
    No-op substitute for Mark's JarvisUI player argument.

    Mark action modules call methods like player.write_log(), player.set_state(),
    and read player.muted / player.current_file.  This shim satisfies all of
    those without requiring PyQt6 or a real UI.
    """

    muted: bool = False
    current_file: str | None = None

    def write_log(self, msg: str) -> None:
        logger.info("[mark_action] %s", msg)

    def set_state(self, state: str) -> None:
        logger.debug("[mark_action] state → %s", state)

    # Some actions pass speak= callable — provide a default no-op
    @staticmethod
    def speak(text: str) -> None:
        logger.debug("[mark_action] speak: %s", text[:80])


def wrap_result(raw) -> dict:
    """
    Normalise whatever a Mark action returns into DIMO's standard
    {success: bool, result: str, error: str | None} format.

    Mark actions return:
    - str  (most actions)
    - None  (some actions that speak directly)
    - dict  (a few newer actions)
    """
    if raw is None:
        return {"success": True, "result": "Done.", "error": None}
    if isinstance(raw, dict):
        if "success" in raw:
            return raw
        # Mark sometimes returns {"result": "..."} without success key
        return {"success": True, "result": str(raw.get("result", raw)), "error": None}
    result_str = str(raw).strip()
    is_error = any(
        kw in result_str.lower()
        for kw in ("error", "failed", "could not", "timed out", "exception")
    )
    if is_error:
        return {"success": False, "result": result_str, "error": result_str}
    return {"success": True, "result": result_str or "Done.", "error": None}
