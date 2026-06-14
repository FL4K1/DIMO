"""
app/services/system/window_service.py
Native DIMO Window Management Service.
Behavioral reference: Mark-XXXIX-OR-main/actions/computer_control.py (_focus_window)
"""

import time
import platform
import subprocess

from app.config.logging import logger


class WindowService:
    """Native window focus/minimize/maximize/close for Windows (primary), macOS, Linux."""

    @classmethod
    def focus_window(cls, title_keyword: str) -> str:
        """Bring a window matching title_keyword to the foreground."""
        if not title_keyword:
            return "No window title provided."

        system = platform.system()
        try:
            if system == "Windows":
                # Use WScript.Shell AppActivate — same approach as Mark's computer_control
                script = f'(New-Object -ComObject WScript.Shell).AppActivate("{title_keyword}")'
                subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                    capture_output=True, timeout=5,
                )
                time.sleep(0.3)
                return f"Focused window: {title_keyword}"

            elif system == "Darwin":
                script = (
                    f'tell application "System Events" to '
                    f'set frontmost of (first process whose name contains "{title_keyword}") to true'
                )
                subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
                time.sleep(0.3)
                return f"Focused window: {title_keyword}"

            elif system == "Linux":
                for cmd in [
                    ["wmctrl", "-a", title_keyword],
                    ["xdotool", "search", "--name", title_keyword, "windowactivate"],
                ]:
                    try:
                        result = subprocess.run(cmd, capture_output=True, timeout=5)
                        if result.returncode == 0:
                            time.sleep(0.3)
                            return f"Focused window: {title_keyword}"
                    except FileNotFoundError:
                        continue
                return "focus_window on Linux requires wmctrl or xdotool"

            # Fallback: pygetwindow
            return cls._pygetwindow_op("focus", title_keyword)

        except Exception as e:
            logger.warning("[WindowService] focus_window error: %s", e)
            return f"Failed to focus window: {e}"

    @classmethod
    def minimize_window(cls, title_keyword: str) -> str:
        """Minimize a window matching title_keyword."""
        return cls._pygetwindow_op("minimize", title_keyword)

    @classmethod
    def maximize_window(cls, title_keyword: str) -> str:
        """Maximize a window matching title_keyword."""
        return cls._pygetwindow_op("maximize", title_keyword)

    @classmethod
    def close_window(cls, title_keyword: str) -> str:
        """Close a window matching title_keyword."""
        return cls._pygetwindow_op("close", title_keyword)

    @classmethod
    def _pygetwindow_op(cls, op: str, title_keyword: str) -> str:
        """Perform a window operation using pygetwindow (Windows/macOS)."""
        try:
            import pygetwindow as gw
            windows = gw.getWindowsWithTitle(title_keyword)
            if not windows:
                return f"No window found matching '{title_keyword}'."
            win = windows[0]

            if op == "focus":
                if win.isMinimized:
                    win.restore()
                win.activate()
                return f"Focused window: {win.title}"
            elif op == "minimize":
                win.minimize()
                return f"Minimized window: {win.title}"
            elif op == "maximize":
                win.maximize()
                return f"Maximized window: {win.title}"
            elif op == "close":
                win.close()
                return f"Closed window: {win.title}"
            return f"Unknown op: {op}"
        except ImportError:
            return f"pygetwindow not installed. Cannot {op} window: {title_keyword}"
        except Exception as e:
            logger.warning("[WindowService] %s error: %s", op, e)
            return f"Failed to {op} window '{title_keyword}': {e}"