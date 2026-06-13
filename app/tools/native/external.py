"""
Native DIMO tools for External services.
Thin wrappers around app.services.external.* logic.
"""

from app.services.external.games import GameLibraryService

def game_updater(**kwargs) -> dict:
    """Manage updates for Steam and Epic games."""
    try:
        service = GameLibraryService()
        result = service.execute(kwargs)
        return {"success": True, "result": result, "error": ""}
    except Exception as e:
        return {"success": False, "result": "", "error": str(e)}
