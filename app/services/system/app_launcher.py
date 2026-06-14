"""
app/services/system/app_launcher.py
Native DIMO App Launcher Service.
Behavioral reference: Mark-XXXIX-OR-main/actions/open_app.py
"""

import time
import platform
import subprocess
import shutil

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

from app.config.logging import logger

# Cross-platform alias table (key: normalized user input, value: {OS: executable})
_APP_ALIASES = {
    "whatsapp":           {"Windows": "WhatsApp",                "Darwin": "WhatsApp",             "Linux": "whatsapp"},
    "chrome":             {"Windows": "chrome",                  "Darwin": "Google Chrome",        "Linux": "google-chrome"},
    "google chrome":      {"Windows": "chrome",                  "Darwin": "Google Chrome",        "Linux": "google-chrome"},
    "firefox":            {"Windows": "firefox",                 "Darwin": "Firefox",              "Linux": "firefox"},
    "spotify":            {"Windows": "Spotify",                 "Darwin": "Spotify",              "Linux": "spotify"},
    "vscode":             {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "visual studio code": {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "discord":            {"Windows": "Discord",                 "Darwin": "Discord",              "Linux": "discord"},
    "telegram":           {"Windows": "Telegram",                "Darwin": "Telegram",             "Linux": "telegram"},
    "instagram":          {"Windows": "Instagram",               "Darwin": "Instagram",            "Linux": "instagram"},
    "tiktok":             {"Windows": "TikTok",                  "Darwin": "TikTok",               "Linux": "tiktok"},
    "notepad":            {"Windows": "notepad.exe",             "Darwin": "TextEdit",             "Linux": "gedit"},
    "calculator":         {"Windows": "calc.exe",                "Darwin": "Calculator",           "Linux": "gnome-calculator"},
    "terminal":           {"Windows": "cmd.exe",                 "Darwin": "Terminal",             "Linux": "gnome-terminal"},
    "cmd":                {"Windows": "cmd.exe",                 "Darwin": "Terminal",             "Linux": "bash"},
    "explorer":           {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "file explorer":      {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "paint":              {"Windows": "mspaint.exe",             "Darwin": "Preview",              "Linux": "gimp"},
    "word":               {"Windows": "winword",                 "Darwin": "Microsoft Word",       "Linux": "libreoffice --writer"},
    "excel":              {"Windows": "excel",                   "Darwin": "Microsoft Excel",      "Linux": "libreoffice --calc"},
    "powerpoint":         {"Windows": "powerpnt",                "Darwin": "Microsoft PowerPoint", "Linux": "libreoffice --impress"},
    "vlc":                {"Windows": "vlc",                     "Darwin": "VLC",                  "Linux": "vlc"},
    "zoom":               {"Windows": "Zoom",                    "Darwin": "zoom.us",              "Linux": "zoom"},
    "slack":              {"Windows": "Slack",                   "Darwin": "Slack",                "Linux": "slack"},
    "steam":              {"Windows": "steam",                   "Darwin": "Steam",                "Linux": "steam"},
    "task manager":       {"Windows": "taskmgr.exe",             "Darwin": "Activity Monitor",     "Linux": "gnome-system-monitor"},
    "settings":           {"Windows": "ms-settings:",           "Darwin": "System Preferences",   "Linux": "gnome-control-center"},
    "powershell":         {"Windows": "powershell.exe",          "Darwin": "Terminal",             "Linux": "bash"},
    "edge":               {"Windows": "msedge",                  "Darwin": "Microsoft Edge",       "Linux": "microsoft-edge"},
    "brave":              {"Windows": "brave",                   "Darwin": "Brave Browser",        "Linux": "brave-browser"},
    "obsidian":           {"Windows": "Obsidian",                "Darwin": "Obsidian",             "Linux": "obsidian"},
    "notion":             {"Windows": "Notion",                  "Darwin": "Notion",               "Linux": "notion"},
    "blender":            {"Windows": "blender",                 "Darwin": "Blender",              "Linux": "blender"},
    "capcut":             {"Windows": "CapCut",                  "Darwin": "CapCut",               "Linux": "capcut"},
    "postman":            {"Windows": "Postman",                 "Darwin": "Postman",              "Linux": "postman"},
    "figma":              {"Windows": "Figma",                   "Darwin": "Figma",                "Linux": "figma"},
}


class AppLauncher:
    """Native cross-platform application launcher."""

    @classmethod
    def _normalize(cls, app_name: str) -> str:
        system = platform.system()
        key = app_name.lower().strip()
        if key in _APP_ALIASES:
            return _APP_ALIASES[key].get(system, app_name)
        for alias_key, os_map in _APP_ALIASES.items():
            if alias_key in key or key in alias_key:
                return os_map.get(system, app_name)
        return app_name

    @classmethod
    def is_running(cls, app_name: str) -> bool:
        if not _PSUTIL:
            return True
        app_lower = app_name.lower().replace(" ", "").replace(".exe", "")
        try:
            for proc in psutil.process_iter(["name"]):
                try:
                    proc_name = proc.info["name"].lower().replace(" ", "").replace(".exe", "")
                    if app_lower in proc_name or proc_name in app_lower:
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        return False

    @classmethod
    def _launch_windows(cls, app_name: str) -> bool:
        try:
            import pyautogui
            pyautogui.PAUSE = 0.1
            pyautogui.press("win")
            time.sleep(0.6)
            pyautogui.write(app_name, interval=0.05)
            time.sleep(0.8)
            pyautogui.press("enter")
            time.sleep(3.0)
            return True
        except Exception as e:
            logger.warning("[AppLauncher] Windows launch failed: %s", e)
            return False

    @classmethod
    def _launch_macos(cls, app_name: str) -> bool:
        for cmd in [["open", "-a", app_name], ["open", "-a", f"{app_name}.app"]]:
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=8)
                if result.returncode == 0:
                    time.sleep(1.0)
                    return True
            except Exception:
                pass
        try:
            import pyautogui
            pyautogui.hotkey("command", "space")
            time.sleep(0.6)
            pyautogui.write(app_name, interval=0.05)
            time.sleep(0.8)
            pyautogui.press("enter")
            time.sleep(1.5)
            return True
        except Exception as e:
            logger.warning("[AppLauncher] macOS Spotlight failed: %s", e)
            return False

    @classmethod
    def _launch_linux(cls, app_name: str) -> bool:
        binary = (
            shutil.which(app_name) or
            shutil.which(app_name.lower()) or
            shutil.which(app_name.lower().replace(" ", "-"))
        )
        if binary:
            try:
                subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(1.0)
                return True
            except Exception:
                pass
        for cmd in [["xdg-open", app_name], ["gtk-launch", app_name.lower().replace(" ", "-")]]:
            try:
                subprocess.run(cmd, capture_output=True, timeout=5)
                return True
            except Exception:
                pass
        return False

    @classmethod
    def launch(cls, app_name: str, logger_func=None) -> str:
        """Launch an application by name. Returns a status string."""
        if not app_name:
            return "No application name provided."

        system = platform.system()
        launchers = {
            "Windows": cls._launch_windows,
            "Darwin":  cls._launch_macos,
            "Linux":   cls._launch_linux,
        }
        launcher = launchers.get(system)
        if launcher is None:
            return f"Unsupported OS: {system}"

        normalized = cls._normalize(app_name)
        logger.info("[AppLauncher] Launching: %s -> %s (%s)", app_name, normalized, system)
        if logger_func:
            logger_func(f"[AppLauncher] {app_name}")

        try:
            if launcher(normalized):
                return f"Opened {app_name} successfully."
            # Retry with original name if normalized differed
            if normalized != app_name and launcher(app_name):
                return f"Opened {app_name} successfully."
            return (
                f"Tried to open {app_name} but could not confirm it launched. "
                "It may still be loading or may not be installed."
            )
        except Exception as e:
            logger.error("[AppLauncher] Failed: %s", e)
            return f"Failed to open {app_name}: {e}"