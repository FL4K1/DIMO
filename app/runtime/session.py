"""
app/runtime/session.py — DIMO session state machine.

Mirrors the state management from Mark-XXXIX-OR-main's JarvisLive class,
adapted for DIMO's CLI-first (no PyQt6) environment.

States:
    LISTENING  — microphone open, waiting for user input
    THINKING   — tool execution or LLM call in progress
    SPEAKING   — TTS output in progress
    MUTED      — mic disabled by user

Usage:
    from app.runtime.session import dimo_session

    dimo_session.set_state(DimoSession.THINKING)
    dimo_session.set_speaking(True)
    print(dimo_session.state)

The singleton `dimo_session` is injected into the executor loop so it can
update display state in real time.
"""

import threading
import logging

logger = logging.getLogger("dimo.session")


class DimoSession:
    """
    Lightweight session state machine.

    Provides the same state names as Mark's JarvisLive so the executor
    and voice loop can call set_state() / set_speaking() identically.
    """

    LISTENING = "LISTENING"
    THINKING  = "THINKING"
    SPEAKING  = "SPEAKING"
    MUTED     = "MUTED"

    # CLI status symbols for each state (ASCII for Windows cp1252 compatibility)
    _SYMBOLS = {
        LISTENING: "[MIC]",
        THINKING:  "[THINK]",
        SPEAKING:  "[SPEAK]",
        MUTED:     "[MUTED]",
    }

    def __init__(self):
        self._state       = self.LISTENING
        self._lock        = threading.Lock()
        self._is_speaking = False
        self.muted        = False
        self._on_state_change = None   # optional callback(state: str)

    # ── State accessors ───────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def set_state(self, new_state: str) -> None:
        """
        Transition to a new state.  Logs the change and calls the optional
        on_state_change callback (useful for future UI integration).
        """
        valid = {self.LISTENING, self.THINKING, self.SPEAKING, self.MUTED}
        if new_state not in valid:
            logger.warning("[Session] Unknown state: %s", new_state)
            return

        with self._lock:
            old = self._state
            self._state = new_state

        if old != new_state:
            symbol = self._SYMBOLS.get(new_state, "•")
            logger.debug("[Session] %s → %s", old, new_state)
            print(f"\r[DIMO] {symbol} {new_state}          ", end="\r", flush=True)
            if self._on_state_change:
                try:
                    self._on_state_change(new_state)
                except Exception as e:
                    logger.warning("[Session] on_state_change callback error: %s", e)

    def set_speaking(self, value: bool) -> None:
        """
        Convenience helper used by the voice loop — matches Mark's set_speaking().
        Transitions to SPEAKING when True, or back to LISTENING when False
        (unless muted).
        """
        with self._lock:
            self._is_speaking = value
        if value:
            self.set_state(self.SPEAKING)
        elif not self.muted:
            self.set_state(self.LISTENING)

    @property
    def is_speaking(self) -> bool:
        with self._lock:
            return self._is_speaking

    def mute(self) -> None:
        self.muted = True
        self.set_state(self.MUTED)

    def unmute(self) -> None:
        self.muted = False
        self.set_state(self.LISTENING)

    def on_state_change(self, callback) -> None:
        """Register a callback(state: str) for future UI hooks."""
        self._on_state_change = callback

    # ── write_log — matches Mark's JarvisUI.write_log() signature ─────────────

    def write_log(self, msg: str) -> None:
        """Print a log line to the terminal (used by MockPlayer in wrappers)."""
        print(f"\n[DIMO] {msg}")


# ── Module-level singleton ─────────────────────────────────────────────────────
dimo_session = DimoSession()
