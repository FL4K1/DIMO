import os
from pathlib import Path

class PathService:
    @staticmethod
    def get_desktop() -> Path:
        return Path.home() / "Desktop"

    @staticmethod
    def get_downloads() -> Path:
        return Path.home() / "Downloads"

    @staticmethod
    def resolve_path(raw: str) -> Path:
        """
        Resolves a path from user input.
        Supports shortcuts: 'desktop', 'downloads', 'documents', 'pictures', 'music', 'videos', 'home'
        """
        shortcuts = {
            "desktop":   Path.home() / "Desktop",
            "downloads": Path.home() / "Downloads",
            "documents": Path.home() / "Documents",
            "pictures":  Path.home() / "Pictures",
            "music":     Path.home() / "Music",
            "videos":    Path.home() / "Videos",
            "home":      Path.home(),
        }
        lower = raw.strip().lower()
        if lower in shortcuts:
            return shortcuts[lower]
        return Path(raw).expanduser()

    @staticmethod
    def format_size(bytes_size: int) -> str:
        """Converts bytes to human readable format."""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if bytes_size < 1024:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024
        return f"{bytes_size:.1f} TB"
