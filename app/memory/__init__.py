# app/memory/__init__.py
"""
Long-term memory subsystem for DIMO.

Architecture mirrors Mark-XXXIX-OR-main/memory/memory_manager.py:
  - JSON storage at app/memory/long_term.json
  - Categories: identity, preferences, projects, relationships, wishes, notes
  - Thread-safe read/write with Lock
  - Automatic trimming to MEMORY_MAX_CHARS
  - Two-stage extraction: should_extract → extract → update

The Ollama client replaces Mark's or_client for model calls.
"""
