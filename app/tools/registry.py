"""
Tool registry for DIMO.

TOOL_CATALOG is the single source of truth for all tools available to
the planning and execution nodes. Each entry maps a tool name to its
description (used by the planner LLM), parameter schema (used by the
validator), and function reference (called by the executor).

Tool schemas are copied verbatim from Mark-XXXIX-OR-main TOOL_DECLARATIONS
so the planner LLM prompt is identical in richness. Function references
point to DIMO's thin-wrapper layer (app/actions/wrappers.py) which bridges
Mark's action modules without requiring PyQt6 or the Gemini API.

Adding a new tool:
    1. Implement or wrap it in app/actions/wrappers.py
    2. Add its catalog entry here (follow the pattern below)
    3. That's it — planner, executor, and validator pick it up automatically.
"""

from typing import Optional, Callable

from app.config.logging import logger

# ── Core headless tools ───────────────────────────────────────────────────────
from app.tools.search import web_search as _web_search_native

# ── System apps (native DIMO implementation) ──────────────────────────────────
from app.system.apps import open_app as _open_app_native

# ── Native Tools ──────────────────────────────────────────────────────────────
from app.tools.native.system import computer_settings as _native_settings, reminder as _native_reminder
from app.tools.native.external import game_updater as _native_game_updater
from app.tools.native.files import file_controller as _native_file_controller, file_processor as _native_file_processor
from app.tools.native.dev import dev_agent as _native_dev_agent, code_helper as _native_code_helper, project_scaffolder as _native_project_scaffolder

# ── Mark-bridge action wrappers ───────────────────────────────────────────────
try:
    from app.actions.wrappers import (
        weather_report       as _weather_report,
        open_app             as _open_app_mark,
        send_message         as _send_message,
        youtube_video        as _youtube_video,
        screen_process       as _screen_process,
        browser_control      as _browser_control,
        desktop_control      as _desktop_control,
        computer_control     as _computer_control,
        flight_finder        as _flight_finder,
        web_search_wrapper   as _web_search_mark,
    )
    _WRAPPERS_LOADED = True
    logger.info("[registry] Mark action wrappers loaded successfully")
except ImportError as _e:
    _WRAPPERS_LOADED = False
    logger.warning("[registry] Mark action wrappers not loaded: %s", _e)
    # Fallbacks so the catalog is always safe to import
    def _make_unavailable(name: str):
        def _unavailable(**kwargs) -> dict:
            return {"success": False, "result": "", "error": f"Tool '{name}' not available (bridge import failed)"}
        return _unavailable
    
    _weather_report = _open_app_mark = _send_message = _youtube_video = _make_unavailable("bridge")
    _screen_process = _browser_control = _desktop_control = _make_unavailable("bridge")
    _computer_control = _flight_finder = _web_search_mark = _make_unavailable("bridge")

# ── Browser subsystem tools ───────────────────────────────────────────────────
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
    logger.warning("[registry] Browser catalogs not loaded: %s", _e)


# ══════════════════════════════════════════════════════════════════════════════
# TOOL CATALOG — full 20-tool set, schemas mirror Mark's TOOL_DECLARATIONS
# ══════════════════════════════════════════════════════════════════════════════

TOOL_CATALOG: dict = {

    # ── Web search ────────────────────────────────────────────────────────────
    "web_search": {
        "name": "web_search",
        "description": (
            "Search the web for any information. Use for ANY information retrieval, "
            "research, current data, news, facts, prices, or comparisons. "
            "Fast and reliable via DuckDuckGo (headless, no browser needed)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query":  {"type": "string", "description": "Search query"},
                "mode":   {"type": "string", "description": "search (default) or compare"},
            },
            "required": ["query"],
        },
        "function": _web_search_native,
    },

    # ── App launcher ──────────────────────────────────────────────────────────
    "open_app": {
        "name": "open_app",
        "description": (
            "Opens any application on the Windows computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "Exact name of the application (e.g. 'Notepad', 'Chrome', 'Spotify')",
                }
            },
            "required": ["app_name"],
        },
        "function": _open_app_native,
    },

    # ── Weather ───────────────────────────────────────────────────────────────
    "weather_report": {
        "name": "weather_report",
        "description": "Gets the weather report for a city and reports it to the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"},
            },
            "required": ["city"],
        },
        "function": _weather_report,
    },

    # ── Text / message composition (generates text in state, NEVER writes files) ─
    "compose_message": {
        "name": "compose_message",
        "description": (
            "Generate message text: WhatsApp message, email, letter, speech, greeting, apology, etc. "
            "Use when user says: write, compose, draft, create, generate a message/text/email. "
            "Returns the composed text directly — does NOT create files or write to disk. "
            "The output is automatically available to the next step (e.g. send_whatsapp_desktop). "
            "NEVER use code_helper or file_controller to compose a message."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subject":  {"type": "string", "description": "What the message is about, e.g. 'greeting for Arman, missing him in vacation'"},
                "tone":     {"type": "string", "description": "Tone of the message: friendly, professional, casual, formal, funny, warm"},
                "context":  {"type": "string", "description": "Any background context the user provided about recipient or situation"},
                "length":   {"type": "string", "description": "Desired length: short (1-2 sentences), medium (1 paragraph), long (2+ paragraphs)"},
            },
            "required": ["subject"],
        },
        "function": None,  # handled directly in executor
    },

    # ── Messaging: platform-specific tools so planner has zero ambiguity ────────────────────
    # send_message (Mark generic) is intentionally NOT in the catalog.
    # WhatsApp always uses send_whatsapp_desktop (pyautogui, desktop app).
    "send_whatsapp_desktop": {
        "name": "send_whatsapp_desktop",
        "description": (
            "THE ONLY tool for sending WhatsApp messages. "
            "ALWAYS use this whenever the user asks to send/message anyone on WhatsApp. "
            "Uses the WhatsApp desktop app. Works reliably without a browser."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "receiver":     {"type": "string", "description": "Contact name exactly as shown in WhatsApp"},
                "message_text": {"type": "string", "description": "The full message to send"},
            },
            "required": ["receiver", "message_text"],
        },
        "function": None,   # handled directly in executor
    },
    "send_telegram_message": {
        "name": "send_telegram_message",
        "description": "Send a message via the Telegram desktop app.",
        "parameters": {
            "type": "object",
            "properties": {
                "receiver":     {"type": "string", "description": "Contact name in Telegram"},
                "message_text": {"type": "string", "description": "The message to send"},
            },
            "required": ["receiver", "message_text"],
        },
        "function": None,   # handled directly in executor
    },
    "send_instagram_dm": {
        "name": "send_instagram_dm",
        "description": "Send an Instagram direct message via the browser.",
        "parameters": {
            "type": "object",
            "properties": {
                "receiver":     {"type": "string", "description": "Instagram username or name"},
                "message_text": {"type": "string", "description": "The message to send"},
            },
            "required": ["receiver", "message_text"],
        },
        "function": None,   # handled directly in executor
    },

    # ── Reminders ─────────────────────────────────────────────────────────────
    "reminder": {
        "name": "reminder",
        "description": "Sets a timed reminder using Windows Task Scheduler.",
        "parameters": {
            "type": "object",
            "properties": {
                "date":    {"type": "string", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "string", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "string", "description": "Reminder message text"},
            },
            "required": ["date", "time", "message"],
        },
        "function": _native_reminder,
    },

    # ── YouTube ───────────────────────────────────────────────────────────────
    "youtube_video": {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "string", "description": "Search query for play action"},
                "save":   {"type": "boolean", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "string", "description": "Country code for trending e.g. US, IN"},
                "url":    {"type": "string", "description": "Video URL for get_info action"},
            },
            "required": [],
        },
        "function": _youtube_video,
    },

    # ── Screen / vision ───────────────────────────────────────────────────────
    "screen_process": {
        "name": "screen_process",
        "description": (
            "Captures and analyses the screen or webcam image. "
            "MUST be called when user asks what is on screen, what you see, "
            "analyse my screen, look at camera, etc. "
            "You have NO visual ability without this tool."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text":  {"type": "string", "description": "The question or instruction about the captured image"},
                "angle": {"type": "string", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
            },
            "required": ["text"],
        },
        "function": _screen_process,
    },

    # ── Computer settings ─────────────────────────────────────────────────────
    "computer_settings": {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action":      {"type": "string", "description": "The action to perform"},
                "description": {"type": "string", "description": "Natural language description of what to do"},
                "value":       {"type": "string", "description": "Optional value: volume level, text to type, etc."},
            },
            "required": [],
        },
        "function": _native_settings,
    },

    # ── Browser control ───────────────────────────────────────────────────────
    "browser_control": {
        "name": "browser_control",
        "description": (
            "Controls the web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, any web-based task."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action":      {"type": "string", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | press | close"},
                "url":         {"type": "string", "description": "URL for go_to action"},
                "query":       {"type": "string", "description": "Search query for search action"},
                "selector":    {"type": "string", "description": "CSS selector for click/type"},
                "text":        {"type": "string", "description": "Text to click or type"},
                "description": {"type": "string", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "string", "description": "up or down for scroll"},
                "key":         {"type": "string", "description": "Key name for press action"},
                "incognito":   {"type": "boolean", "description": "Open in private/incognito mode"},
            },
            "required": ["action"],
        },
        "function": _browser_control,
    },

    # ── File controller ───────────────────────────────────────────────────────
    "file_controller": {
        "name": "file_controller",
        "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
        "parameters": {
            "type": "object",
            "properties": {
                "action":      {"type": "string", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "string", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "string", "description": "Destination path for move/copy"},
                "new_name":    {"type": "string", "description": "New name for rename"},
                "content":     {"type": "string", "description": "Content for create_file/write"},
                "name":        {"type": "string", "description": "File name to search for"},
                "extension":   {"type": "string", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "integer", "description": "Number of results for largest"},
            },
            "required": ["action"],
        },
        "function": _native_file_controller,
    },

    # ── Desktop control ───────────────────────────────────────────────────────
    "desktop_control": {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "string", "description": "Image path for wallpaper"},
                "url":    {"type": "string", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "string", "description": "by_type or by_date for organize"},
                "task":   {"type": "string", "description": "Natural language desktop task"},
            },
            "required": ["action"],
        },
        "function": _desktop_control,
    },

    # ── Code helper ───────────────────────────────────────────────────────────
    "code_helper": {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "object",
            "properties": {
                "action":      {"type": "string", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "string", "description": "What the code should do or what change to make"},
                "language":    {"type": "string", "description": "Programming language (default: python)"},
                "output_path": {"type": "string", "description": "Where to save the file"},
                "file_path":   {"type": "string", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "string", "description": "Raw code string for explain"},
                "args":        {"type": "string", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "integer", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"],
        },
        "function": _native_code_helper,
    },

    # ── Dev agent ─────────────────────────────────────────────────────────────
    "dev_agent": {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "object",
            "properties": {
                "description":  {"type": "string", "description": "What the project should do"},
                "language":     {"type": "string", "description": "Programming language (default: python)"},
                "project_name": {"type": "string", "description": "Optional project folder name"},
                "timeout":      {"type": "integer", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"],
        },
        "function": _native_dev_agent,
    },

    # ── Project Scaffolder ────────────────────────────────────────────────────
    "project_scaffolder": {
        "name": "project_scaffolder",
        "description": "Plans a project JSON structure based on a description and creates the skeleton.",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "What the project should do"},
                "output_dir":  {"type": "string", "description": "Optional specific output directory path"},
            },
            "required": ["description"],
        },
        "function": _native_project_scaffolder,
    },

    # ── Agent task (complex multi-step) ───────────────────────────────────────
    "agent_task": {
        "name": "agent_task",
        "description": (
            "Executes complex multi-step tasks requiring multiple different tools. "
            "Examples: 'research X and save to file', 'find and organize files'. "
            "DO NOT use for single commands."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal":     {"type": "string", "description": "Complete description of what to accomplish"},
                "priority": {"type": "string", "description": "low | normal | high (default: normal)"},
            },
            "required": ["goal"],
        },
        # Handled specially in executor — no wrapper function needed
        "function": None,
    },

    # ── Computer control (mouse / keyboard) ───────────────────────────────────
    "computer_control": {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "object",
            "properties": {
                "action":      {"type": "string", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click"},
                "text":        {"type": "string", "description": "Text to type or paste"},
                "x":           {"type": "integer", "description": "X coordinate"},
                "y":           {"type": "integer", "description": "Y coordinate"},
                "keys":        {"type": "string", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "string", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "string", "description": "up | down | left | right"},
                "amount":      {"type": "integer", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "number",  "description": "Seconds to wait"},
                "title":       {"type": "string",  "description": "Window title for focus_window"},
                "description": {"type": "string",  "description": "Element description for screen_find/screen_click"},
                "path":        {"type": "string",  "description": "Save path for screenshot"},
            },
            "required": ["action"],
        },
        "function": _computer_control,
    },

    # ── Game updater ──────────────────────────────────────────────────────────
    "game_updater": {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use agent_task, browser_control, or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action":    {"type": "string",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "string",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "string",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "string",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "integer", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "integer", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "boolean", "description": "Shut down PC when download finishes"},
            },
            "required": [],
        },
        "function": _native_game_updater,
    },

    # ── Flight finder ─────────────────────────────────────────────────────────
    "flight_finder": {
        "name": "flight_finder",
        "description": "Searches Google Flights and returns the best options.",
        "parameters": {
            "type": "object",
            "properties": {
                "origin":      {"type": "string",  "description": "Departure city or airport code"},
                "destination": {"type": "string",  "description": "Arrival city or airport code"},
                "date":        {"type": "string",  "description": "Departure date (any format)"},
                "return_date": {"type": "string",  "description": "Return date for round trips"},
                "passengers":  {"type": "integer", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "string",  "description": "economy | premium | business | first"},
                "save":        {"type": "boolean", "description": "Save results to file"},
            },
            "required": ["origin", "destination", "date"],
        },
        "function": _flight_finder,
    },

    # ── File processor ────────────────────────────────────────────────────────
    "file_processor": {
        "name": "file_processor",
        "description": (
            "Processes any uploaded file: images (describe/ocr/resize), "
            "PDFs (summarize/extract_text/to_word), Word docs (summarize/fix/reformat), "
            "CSV/Excel (analyze/stats/filter/sort), JSON/XML (validate/format), "
            "code files (explain/review/fix/run), audio (transcribe/convert), "
            "video (trim/extract_audio/compress), archives (list/extract), "
            "presentations (summarize/extract_text)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path":   {"type": "string",  "description": "Full path to the file"},
                "action":      {"type": "string",  "description": "Action to perform (depends on file type)"},
                "instruction": {"type": "string",  "description": "Free-form instruction"},
                "format":      {"type": "string",  "description": "Target format for conversion"},
                "save":        {"type": "boolean", "description": "Save result to file (default: true)"},
            },
            "required": [],
        },
        "function": _native_file_processor,
    },

    # ── Save memory (special — handled directly in executor) ──────────────────
    "save_memory": {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    ),
                },
                "key":   {"type": "string", "description": "Short snake_case key (e.g. name, favorite_food)"},
                "value": {"type": "string", "description": "Concise value in English"},
            },
            "required": ["category", "key", "value"],
        },
        # Handled directly in executor — no bridge function
        "function": None,
    },

    # ── Shutdown DIMO ─────────────────────────────────────────────────────────
    "shutdown_dimo": {
        "name": "shutdown_dimo",
        "description": (
            "Shuts down DIMO completely. "
            "Call this when the user expresses intent to end the conversation, "
            "close the assistant, or say goodbye. The user can say this in any language."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        # Handled directly in executor
        "function": None,
    },
}


# ── Merge browser catalogs ─────────────────────────────────────────────────────
TOOL_CATALOG.update(TABS_CATALOG)
TOOL_CATALOG.update(CLIPBOARD_CATALOG)
TOOL_CATALOG.update(SEARCH_BROWSER_CATALOG)
TOOL_CATALOG.update(YOUTUBE_MUSIC_CATALOG)
TOOL_CATALOG.update(WHATSAPP_CATALOG)
TOOL_CATALOG.update(GEMINI_CATALOG)

logger.info("[registry] %d tools registered: %s", len(TOOL_CATALOG), list(TOOL_CATALOG.keys()))


# ── Accessor helpers ──────────────────────────────────────────────────────────

def get_tool(tool_name: str) -> Optional[Callable]:
    """
    Retrieve a tool function by name.

    Returns:
        The callable function for the tool, or None if not found / has no function.
    """
    tool_info = TOOL_CATALOG.get(tool_name)
    if not tool_info:
        logger.warning("[registry] Tool '%s' not found in catalog", tool_name)
        return None
    fn = tool_info.get("function")
    if fn is None:
        logger.debug("[registry] Tool '%s' has no function (handled by executor)", tool_name)
    return fn


def list_tools() -> str:
    """Return a formatted list of all registered tools and their descriptions."""
    lines = []
    for name, info in TOOL_CATALOG.items():
        desc = info.get("description", "")[:80]
        lines.append(f"  {name}: {desc}")
    return "\n".join(lines)


def get_tool_schema_text() -> str:
    """
    Return a planner-friendly text block listing every tool with its parameters.
    Used by the strict JSON planner prompt.
    """
    lines = []
    for name, info in TOOL_CATALOG.items():
        lines.append(name)
        props = info.get("parameters", {}).get("properties", {})
        for param, meta in props.items():
            required = param in info.get("parameters", {}).get("required", [])
            req_marker = " (required)" if required else " (optional)"
            lines.append(f"  {param}: {meta.get('type', 'string')}{req_marker} — {meta.get('description', '')}")
        lines.append("")
    return "\n".join(lines)
