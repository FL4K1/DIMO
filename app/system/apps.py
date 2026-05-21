"""
apps.py — Local desktop application launching tool.
"""

import subprocess
import logging

logger = logging.getLogger("dimo")

def open_app(app_name: str) -> dict:
    """
    Launch a local desktop application using Windows start or subprocess.

    Args:
        app_name: The name of the application executable (e.g. "notepad", "calc").
    
    Returns:
        Structured result dict.
    """
    try:
        # Use shell=True to allow Windows to resolve executables from PATH
        subprocess.Popen(app_name, shell=True)
        logger.info(f"[system] Launched local app: {app_name}")
        return {"success": True, "result": f"Successfully launched local app: {app_name}", "error": None}
    except Exception as e:
        logger.error(f"[system] Failed to launch {app_name}: {e}")
        return {"success": False, "result": "", "error": f"Failed to launch {app_name}: {e}"}

# ── Tool catalog entries ───────────────────────────────────────────────────────
SYSTEM_APPS_CATALOG = {
    "open_app": {
        "name": "open_app",
        "description": (
            "Launch a local desktop application on the user's computer (e.g. Notepad, Calculator). "
            "Use this ONLY for desktop apps, NOT for opening websites."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "The name of the executable to launch (e.g., 'notepad', 'calc', 'explorer')",
                }
            },
            "required": ["app_name"],
        },
        "function": open_app,
    }
}
