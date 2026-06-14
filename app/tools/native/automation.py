"""
app/tools/native/automation.py
Native DIMO computer control tool entry point.
Behavioral reference: Mark-XXXIX-OR-main/actions/computer_control.py

This module is the tool function that the registry calls.
It dispatches to GuiService (keyboard/mouse) and WindowService (windows).
"""

from app.services.automation.gui_service import GuiService
from app.services.system.window_service import WindowService
from app.services.system.app_launcher import AppLauncher
from app.config.logging import logger


def open_app(app_name: str) -> dict:
    """Launch a local desktop application natively."""
    try:
        result = AppLauncher.launch(app_name, logger_func=logger.info)
        success = "successfully" in result.lower()
        return {"success": success, "result": result, "error": None if success else result}
    except Exception as e:
        logger.error("[Native] open_app failed: %s", e)
        return {"success": False, "result": "", "error": str(e)}


def computer_control(
    action: str,
    description: str = "",
    value: str = "",
    x: int = None,
    y: int = None,
    x1: int = None,
    y1: int = None,
    x2: int = None,
    y2: int = None,
    button: str = "left",
    keys: str = "",
    key: str = "enter",
    direction: str = "down",
    amount: int = 3,
    seconds: float = 1.0,
    text: str = "",
    clear_first: bool = True,
    save_path: str = None,
    data_type: str = "name",
    title: str = "",
) -> dict:
    """
    Controls the computer via keyboard, mouse, and window management.

    Actions:
        type          — type text at cursor
        smart_type    — clear field + type (clipboard-backed for long text)
        click / left_click — left click at (x,y) or current position
        double_click  — double left click
        right_click   — right click
        move          — move mouse to (x,y)
        drag          — click-drag from (x1,y1) to (x2,y2)
        hotkey        — key combination (keys param, e.g. 'ctrl+c')
        press         — single key press (key param)
        scroll        — scroll wheel (direction, amount)
        copy          — read clipboard
        paste         — paste text via clipboard
        screenshot    — capture screen (saved to Desktop by default)
        wait          — sleep N seconds
        clear_field   — select-all + delete
        focus_window  — bring window matching title to foreground
        minimize_window / maximize_window / close_window — window management
        random_data   — generate fake form data (data_type param)
        open_app      — launch an application (value or description)
    """
    try:
        act = action.lower().strip()
        result_msg = ""

        # ── Text input ────────────────────────────────────────────────────────
        if act == "type":
            result_msg = GuiService.type_text(text or value or description)

        elif act == "smart_type":
            result_msg = GuiService.smart_type(text or value or description, clear_first=clear_first)

        # ── Mouse ─────────────────────────────────────────────────────────────
        elif act in ("click", "left_click"):
            result_msg = GuiService.click(x=x, y=y, button="left", clicks=1)

        elif act == "double_click":
            result_msg = GuiService.double_click(x=x, y=y)

        elif act == "right_click":
            result_msg = GuiService.right_click(x=x, y=y)

        elif act == "move":
            result_msg = GuiService.move(x or 0, y or 0)

        elif act == "drag":
            result_msg = GuiService.drag(x1 or 0, y1 or 0, x2 or 0, y2 or 0)

        # ── Keyboard ──────────────────────────────────────────────────────────
        elif act == "hotkey":
            raw_keys = keys or value or description
            key_list = [k.strip() for k in raw_keys.split("+")] if isinstance(raw_keys, str) else list(raw_keys)
            result_msg = GuiService.hotkey(*key_list)

        elif act == "press":
            result_msg = GuiService.press(key or value or "enter")

        # ── Scroll ────────────────────────────────────────────────────────────
        elif act == "scroll":
            result_msg = GuiService.scroll(direction=direction, amount=int(amount))

        # ── Clipboard ─────────────────────────────────────────────────────────
        elif act == "copy":
            result_msg = GuiService.clipboard_get()

        elif act == "paste":
            result_msg = GuiService.clipboard_paste(text or value or description)

        # ── Screen ────────────────────────────────────────────────────────────
        elif act == "screenshot":
            result_msg = GuiService.screenshot(save_path)

        elif act == "clear_field":
            result_msg = GuiService.clear_field()

        elif act == "wait":
            result_msg = GuiService.wait(seconds)

        # ── Window management ─────────────────────────────────────────────────
        elif act == "focus_window":
            result_msg = WindowService.focus_window(title or value or description)

        elif act == "minimize_window":
            result_msg = WindowService.minimize_window(title or value or description)

        elif act == "maximize_window":
            result_msg = WindowService.maximize_window(title or value or description)

        elif act == "close_window":
            result_msg = WindowService.close_window(title or value or description)

        # ── App launcher ──────────────────────────────────────────────────────
        elif act == "open_app":
            r = open_app(value or description)
            return r

        # ── Utility ───────────────────────────────────────────────────────────
        elif act == "random_data":
            result_msg = GuiService.random_data(data_type)

        else:
            return {"success": False, "result": "", "error": f"Unknown action: '{action}'"}

        success = not any(
            keyword in result_msg.lower()
            for keyword in ("error", "failed", "not found", "unavailable", "not installed")
        )
        return {"success": success, "result": result_msg, "error": None if success else result_msg}

    except Exception as e:
        logger.error("[Native] computer_control '%s' failed: %s", action, e)
        return {"success": False, "result": "", "error": str(e)}