"""
app/actions/wrappers.py — Thin wrappers for all Mark-XXXIX-OR-main action modules.

Each function:
  1. Calls ensure_mark_on_path() to put Mark's actions/ on sys.path
  2. Lazily imports the corresponding Mark action (inside the function body)
  3. Invokes it with (parameters={...}, player=MockPlayer())
  4. Returns a normalised {success, result, error} dict via wrap_result()

DIMO's registry picks these up as the "function" field in each tool catalog entry.
"""

import logging
from app.actions.mark_bridge import ensure_mark_on_path, MockPlayer, wrap_result

logger = logging.getLogger("dimo.actions")

_player = MockPlayer()


# ── Helper ────────────────────────────────────────────────────────────────────

def _mark(module: str, fn: str, params: dict) -> dict:
    """Generic helper: import module.fn from Mark's actions/ and call it."""
    if not ensure_mark_on_path():
        return {"success": False, "result": "", "error": "Mark-XXXIX-OR-main not found"}
    try:
        import importlib
        mod = importlib.import_module(f"actions.{module}")
        action_fn = getattr(mod, fn)
        raw = action_fn(parameters=params, player=_player)
        return wrap_result(raw)
    except ImportError as e:
        logger.error("[wrappers] ImportError for actions.%s: %s", module, e)
        return {"success": False, "result": "", "error": f"Module import failed: {e}"}
    except Exception as e:
        logger.error("[wrappers] %s.%s failed: %s", module, fn, e)
        return {"success": False, "result": "", "error": str(e)}


# ── Weather ───────────────────────────────────────────────────────────────────

def weather_report(city: str) -> dict:
    """Get current weather for a city."""
    return _mark("weather_report", "weather_action", {"city": city})


# ── App launcher (upgraded over system/apps.py) ───────────────────────────────

def open_app(app_name: str) -> dict:
    """Open a desktop application by name."""
    return _mark("open_app", "open_app", {"app_name": app_name})


# ── Messaging ─────────────────────────────────────────────────────────────────

def send_message(receiver: str, message_text: str, platform: str) -> dict:
    """Send a message via WhatsApp desktop app, Telegram, or other platform (pyautogui)."""
    return _mark(
        "send_message", "send_message",
        {"receiver": receiver, "message_text": message_text, "platform": platform},
    )



# ── Reminders ─────────────────────────────────────────────────────────────────

def reminder(date: str, time: str, message: str) -> dict:
    """Set a timed Windows reminder."""
    return _mark("reminder", "reminder", {"date": date, "time": time, "message": message})


# ── YouTube ───────────────────────────────────────────────────────────────────

def youtube_video(
    action: str = "play",
    query: str = "",
    save: bool = False,
    region: str = "US",
    url: str = "",
) -> dict:
    """Control YouTube: play, summarize, get_info, or trending."""
    params = {"action": action, "query": query, "save": save, "region": region, "url": url}
    return _mark("youtube_video", "youtube_video", params)


# ── Screen capture / vision ───────────────────────────────────────────────────

def screen_process(text: str, angle: str = "screen") -> dict:
    """Capture and analyse the screen or webcam."""
    return _mark("screen_processor", "screen_process", {"text": text, "angle": angle})


# ── Computer settings ─────────────────────────────────────────────────────────

def computer_settings(
    action: str = "",
    description: str = "",
    value: str = "",
) -> dict:
    """Control system: volume, brightness, WiFi, dark mode, etc."""
    return _mark(
        "computer_settings", "computer_settings",
        {"action": action, "description": description, "value": value},
    )


# ── Browser control ───────────────────────────────────────────────────────────

def browser_control(
    action: str,
    url: str = "",
    query: str = "",
    selector: str = "",
    text: str = "",
    description: str = "",
    direction: str = "",
    key: str = "",
    incognito: bool = False,
) -> dict:
    """Control the web browser: navigate, click, type, scroll, etc."""
    params = {
        "action": action, "url": url, "query": query, "selector": selector,
        "text": text, "description": description, "direction": direction,
        "key": key, "incognito": incognito,
    }
    return _mark("browser_control", "browser_control", params)


# ── File controller ───────────────────────────────────────────────────────────

def file_controller(
    action: str,
    path: str = "",
    destination: str = "",
    new_name: str = "",
    content: str = "",
    name: str = "",
    extension: str = "",
    count: int = 10,
) -> dict:
    """Manage files and folders: list, create, delete, move, copy, read, write, find."""
    params = {
        "action": action, "path": path, "destination": destination,
        "new_name": new_name, "content": content, "name": name,
        "extension": extension, "count": count,
    }
    return _mark("file_controller", "file_controller", params)


# ── Desktop control ───────────────────────────────────────────────────────────

def desktop_control(
    action: str,
    path: str = "",
    url: str = "",
    mode: str = "",
    task: str = "",
) -> dict:
    """Control the desktop: wallpaper, organize, clean, list, stats."""
    params = {"action": action, "path": path, "url": url, "mode": mode, "task": task}
    return _mark("desktop", "desktop_control", params)


# ── Code helper ───────────────────────────────────────────────────────────────

def code_helper(
    action: str = "auto",
    description: str = "",
    language: str = "python",
    output_path: str = "",
    file_path: str = "",
    code: str = "",
    args: str = "",
    timeout: int = 30,
) -> dict:
    """Write, edit, explain, run, or build code files."""
    params = {
        "action": action, "description": description, "language": language,
        "output_path": output_path, "file_path": file_path, "code": code,
        "args": args, "timeout": timeout,
    }
    # code_helper also accepts a speak= kwarg — pass MockPlayer.speak
    if not ensure_mark_on_path():
        return {"success": False, "result": "", "error": "Mark-XXXIX-OR-main not found"}
    try:
        from actions.code_helper import code_helper as _fn  # type: ignore
        raw = _fn(parameters=params, player=_player, speak=MockPlayer.speak)
        return wrap_result(raw)
    except Exception as e:
        logger.error("[wrappers] code_helper failed: %s", e)
        return {"success": False, "result": "", "error": str(e)}


# ── Dev agent ─────────────────────────────────────────────────────────────────

def dev_agent(
    description: str,
    language: str = "python",
    project_name: str = "",
    timeout: int = 30,
) -> dict:
    """Build complete multi-file projects from scratch."""
    params = {
        "description": description, "language": language,
        "project_name": project_name, "timeout": timeout,
    }
    if not ensure_mark_on_path():
        return {"success": False, "result": "", "error": "Mark-XXXIX-OR-main not found"}
    try:
        from actions.dev_agent import dev_agent as _fn  # type: ignore
        raw = _fn(parameters=params, player=_player, speak=MockPlayer.speak)
        return wrap_result(raw)
    except Exception as e:
        logger.error("[wrappers] dev_agent failed: %s", e)
        return {"success": False, "result": "", "error": str(e)}


# ── Computer control (mouse / keyboard) ───────────────────────────────────────

def computer_control(
    action: str,
    text: str = "",
    x: int = 0,
    y: int = 0,
    keys: str = "",
    key: str = "",
    direction: str = "",
    amount: int = 3,
    seconds: float = 0.0,
    title: str = "",
    description: str = "",
    type: str = "",
    field: str = "",
    clear_first: bool = True,
    path: str = "",
) -> dict:
    """Direct mouse/keyboard control: type, click, hotkey, scroll, screenshot."""
    params = {
        "action": action, "text": text, "x": x, "y": y, "keys": keys,
        "key": key, "direction": direction, "amount": amount, "seconds": seconds,
        "title": title, "description": description, "type": type,
        "field": field, "clear_first": clear_first, "path": path,
    }
    return _mark("computer_control", "computer_control", params)


# ── Game updater ──────────────────────────────────────────────────────────────

def game_updater(
    action: str = "update",
    platform: str = "both",
    game_name: str = "",
    app_id: str = "",
    hour: int = 3,
    minute: int = 0,
    shutdown_when_done: bool = False,
) -> dict:
    """Steam/Epic Games: install, update, list, schedule updates."""
    params = {
        "action": action, "platform": platform, "game_name": game_name,
        "app_id": app_id, "hour": hour, "minute": minute,
        "shutdown_when_done": shutdown_when_done,
    }
    if not ensure_mark_on_path():
        return {"success": False, "result": "", "error": "Mark-XXXIX-OR-main not found"}
    try:
        from actions.game_updater import game_updater as _fn  # type: ignore
        raw = _fn(parameters=params, player=_player, speak=MockPlayer.speak)
        return wrap_result(raw)
    except Exception as e:
        logger.error("[wrappers] game_updater failed: %s", e)
        return {"success": False, "result": "", "error": str(e)}


# ── Flight finder ─────────────────────────────────────────────────────────────

def flight_finder(
    origin: str,
    destination: str,
    date: str,
    return_date: str = "",
    passengers: int = 1,
    cabin: str = "economy",
    save: bool = False,
) -> dict:
    """Search Google Flights for the best options."""
    params = {
        "origin": origin, "destination": destination, "date": date,
        "return_date": return_date, "passengers": passengers,
        "cabin": cabin, "save": save,
    }
    return _mark("flight_finder", "flight_finder", params)


# ── File processor ────────────────────────────────────────────────────────────

def file_processor(
    file_path: str = "",
    action: str = "",
    instruction: str = "",
    format: str = "",
    width: int = 0,
    height: int = 0,
    scale: float = 1.0,
    quality: int = 85,
    start: str = "",
    end: str = "",
    timestamp: str = "",
    column: str = "",
    value: str = "",
    condition: str = "",
    ascending: bool = True,
    save: bool = True,
    destination: str = "",
) -> dict:
    """Process any uploaded file: images, PDFs, CSV, audio, video, code, etc."""
    params = {
        "file_path": file_path, "action": action, "instruction": instruction,
        "format": format, "width": width, "height": height, "scale": scale,
        "quality": quality, "start": start, "end": end, "timestamp": timestamp,
        "column": column, "value": value, "condition": condition,
        "ascending": ascending, "save": save, "destination": destination,
    }
    if not ensure_mark_on_path():
        return {"success": False, "result": "", "error": "Mark-XXXIX-OR-main not found"}
    try:
        from actions.file_processor import file_processor as _fn  # type: ignore
        raw = _fn(parameters=params, player=_player, speak=MockPlayer.speak)
        return wrap_result(raw)
    except Exception as e:
        logger.error("[wrappers] file_processor failed: %s", e)
        return {"success": False, "result": "", "error": str(e)}


# ── Web search (passthrough to existing DIMO tool) ────────────────────────────

def web_search_wrapper(query: str, mode: str = "search") -> dict:
    """Thin wrapper to call DIMO's native DuckDuckGo web_search."""
    from app.tools.search import web_search  # noqa: PLC0415
    try:
        result = web_search(query=query)
        if isinstance(result, dict):
            return result
        return {"success": True, "result": str(result), "error": None}
    except Exception as e:
        return {"success": False, "result": "", "error": str(e)}
