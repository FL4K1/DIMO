"""Logging configuration for DIMO."""

import io
import logging
import sys
from pathlib import Path


def setup_logging() -> logging.Logger:
    """Configure logging for the application.

    Windows terminal fix:
        PowerShell defaults to cp1252 which cannot encode characters like ✓.
        We force UTF-8 on the console handler by wrapping sys.stdout.buffer
        in a TextIOWrapper with errors='replace' so logging never raises on
        unexpected characters.
    """

    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    logger = logging.getLogger("dimo")
    logger.setLevel(logging.DEBUG)

    # ── File handler (UTF-8, all levels) ────────────────────────────────────
    fh = logging.FileHandler(log_dir / "dimo.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)

    # ── Console handler (UTF-8 forced, INFO and above) ──────────────────────
    # On Windows, sys.stdout may be backed by cp1252. We bypass that by
    # writing directly to the binary buffer with UTF-8 encoding.
    # errors='replace' ensures a bad character never kills the process.
    if hasattr(sys.stdout, "buffer"):
        utf8_stream = io.TextIOWrapper(
            sys.stdout.buffer,
            encoding="utf-8",
            errors="replace",
            line_buffering=True,
        )
    else:
        utf8_stream = sys.stdout  # Fallback (e.g. already redirected)

    ch = logging.StreamHandler(utf8_stream)
    ch.setLevel(logging.INFO)

    # ── Shared formatter ─────────────────────────────────────────────────────
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger


# Module-level logger used across the entire DIMO codebase
logger = setup_logging()
