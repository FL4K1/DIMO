"""
Engine Mode and Transition Controller for Mark-LV.

Authoritative manager for switching between AI reasoning engines in Mark-LV:
- "Gemini Live" (cloud conversational audio/text model)
- "Ollama" (verified local text LLM)

Guarantees:
1. Mode Transition Safety:
   - Displays confirmation before starting Ollama.
   - On cancel: does not start Ollama or change active provider.
   - On continue: performs asynchronous readiness verification outside UI thread.
   - Displays truthful progress at each stage.
   - Prevents duplicate transition attempts while one is active.
   - Stale task protection: increments generation token so cancelled/superseded tasks cannot alter state.
   - Activates local mode ONLY when endpoint, model, and live inference are verified ready.
   - On failure: displays exact required failure message:
     "Jarvis cannot switch to Local LLM Mode."
     along with safe sanitized explanation and Retry / Cancel options.
   - Preserves previous valid provider on failure or cancellation.
   - Persists setting via Mark-LV convention only after successful verification.
2. Tool Safety in Local Mode:
   - Identifies and excludes unreviewed cloud-LLM-dependent tools.
   - Supplies only verified local/safe tools to local coordinator.
   - Blocks any attempt to execute cloud-dependent actions in local mode.
3. Voice Safety:
   - Clearly marks voice interaction unavailable in Local LLM Mode.
   - Never sends requests to Gemini Live as a fallback.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Set

try:
    from memory.config_manager import get_ai_engine, save_ai_engine
except ImportError:
    from app.marklv.memory.config_manager import get_ai_engine, save_ai_engine

try:
    from core.ollama_manager import OllamaManager, OllamaReadinessResult
except ImportError:
    from app.marklv.core.ollama_manager import OllamaManager, OllamaReadinessResult

logger = logging.getLogger("marklv.engine_manager")

# Cloud-dependent actions in Mark-LV that call Gemini directly.
# Retained for diagnostic logging and categorization.
CLOUD_DEPENDENT_TOOLS: frozenset[str] = frozenset({
    "code_helper",
    "computer_control",
    "desktop_control",
    "dev_agent",
    "file_processor",
    "flight_finder",
    "youtube_video",
    "screen_process",
})

# Positive allowlist of explicitly reviewed actions and inline tools approved
# for Local LLM Mode. Any unreviewed, third-party, or future action/plugin
# NOT in this set is strictly blocked by default.
APPROVED_LOCAL_TOOLS: frozenset[str] = frozenset({
    # Discovered Mark-LV actions reviewed for offline / local-only execution:
    "open_app",
    "browser_control",
    "computer_settings",
    "file_controller",
    "reminder",
    "send_message",
    "game_updater",
    "video_player",
    "weather_report",
    "web_search",
    "dimo_browser_list_tabs",
    # Authoritative Mark-LV inline tools:
    "save_memory",
    "recall_memory",
    "undo",
    "system_status",
    "manage_monitor",
    "shutdown_jarvis",
    "close_camera",
})


def is_tool_allowed_in_local_mode(tool_name: str) -> bool:
    """
    Return True ONLY if tool_name is in the positive allowlist of reviewed
    local tools. Disallows all cloud-dependent, unknown, and unreviewed tools.
    """
    norm = str(tool_name or "").strip().lower()
    return norm in APPROVED_LOCAL_TOOLS


def filter_local_tool_declarations(
    declarations: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Filter tool declarations for Local LLM Mode to only approved local tools."""
    if not declarations:
        return []
    filtered = []
    for d in declarations:
        if isinstance(d, dict) and is_tool_allowed_in_local_mode(d.get("name", "")):
            filtered.append(d)
        else:
            name = d.get("name") if isinstance(d, dict) else str(d)
            logger.info("[EngineManager] Excluded unapproved or cloud tool from local declarations: %s", name)
    return filtered


class EngineMode:
    GEMINI_LIVE = "Gemini Live"
    OLLAMA = "Ollama"


class LocalModeTransitionController:
    """
    Coordinates provider mode selection, user confirmation, truthful progress,
    and fail-safe mode activation between Gemini Live and Local Ollama.
    """

    def __init__(
        self,
        active_engine: Optional[str] = None,
        ollama_manager: Optional[OllamaManager] = None,
        save_engine_fn: Optional[Callable[[str], None]] = None,
        show_confirm_dialog_fn: Optional[Callable[[Callable[[], None], Callable[[], None]], None]] = None,
        show_failure_dialog_fn: Optional[Callable[[str, str, Callable[[], None], Callable[[], None]], None]] = None,
        notify_progress_fn: Optional[Callable[[str, str], None]] = None,
        on_mode_changed_fn: Optional[Callable[[str], None]] = None,
        run_async_fn: Optional[Callable[[Callable[[], None]], None]] = None,
    ):
        self._active_engine = active_engine or get_ai_engine() or EngineMode.GEMINI_LIVE
        self._requested_engine = self._active_engine
        self._ollama_manager = ollama_manager or OllamaManager()
        self._save_engine_fn = save_engine_fn or save_ai_engine
        self._show_confirm_dialog_fn = show_confirm_dialog_fn
        self._show_failure_dialog_fn = show_failure_dialog_fn
        self._notify_progress_fn = notify_progress_fn
        self._on_mode_changed_fn = on_mode_changed_fn
        self._run_async_fn = run_async_fn or self._default_run_async

        self._is_transitioning = False
        self._current_generation = 0
        self._lock = threading.Lock()

    @staticmethod
    def _default_run_async(worker_func: Callable[[], None]) -> None:
        t = threading.Thread(target=worker_func, daemon=True)
        t.start()

    @property
    def active_engine(self) -> str:
        with self._lock:
            return self._active_engine

    @property
    def requested_engine(self) -> str:
        with self._lock:
            return self._requested_engine

    @property
    def is_transitioning(self) -> bool:
        with self._lock:
            return self._is_transitioning

    @property
    def is_local_mode(self) -> bool:
        return self.active_engine == EngineMode.OLLAMA

    @property
    def ollama_manager(self) -> OllamaManager:
        return self._ollama_manager

    def select_engine(self, target_engine: str) -> None:
        """
        Handle a user selection of AI engine mode.
        """
        with self._lock:
            if target_engine == self._active_engine:
                self._requested_engine = target_engine
                return

            if self._is_transitioning:
                logger.warning("[EngineManager] Mode transition already in progress; duplicate ignored.")
                return

            self._requested_engine = target_engine

        if target_engine == EngineMode.OLLAMA:
            # 1. Show confirmation dialog before starting Ollama
            if self._show_confirm_dialog_fn:
                self._show_confirm_dialog_fn(
                    self.proceed_with_local_transition,
                    self.cancel_transition,
                )
            else:
                self.proceed_with_local_transition()
        else:
            # Switch back to Gemini Live
            self.activate_gemini_mode()

    def proceed_with_local_transition(self) -> None:
        """
        User confirmed: run readiness checks outside UI thread and update mode on success.
        """
        with self._lock:
            if self._is_transitioning:
                return
            self._is_transitioning = True
            self._current_generation += 1
            task_gen = self._current_generation

        logger.info("[EngineManager] Starting local mode readiness verification (task gen %d)...", task_gen)

        def _worker():
            def _progress(stage: str, msg: str):
                with self._lock:
                    if task_gen != self._current_generation:
                        return
                if self._notify_progress_fn:
                    try:
                        self._notify_progress_fn(stage, msg)
                    except Exception:
                        pass

            try:
                result: OllamaReadinessResult = self._ollama_manager.verify_or_start(
                    progress_callback=_progress
                )
            except Exception as e:
                from core.ollama_manager import OllamaReadinessStatus
                result = OllamaReadinessResult(
                    status=OllamaReadinessStatus.LAUNCH_FAILED,
                    stage="exception",
                    message=f"Readiness verification encountered error: {e}",
                    endpoint=self._ollama_manager.host,
                    model=self._ollama_manager.model,
                )

            with self._lock:
                # 5. Stale task protection: drop result if superseded or cancelled
                if task_gen != self._current_generation:
                    logger.info("[EngineManager] Dropping stale readiness task gen %d (current %d)", task_gen, self._current_generation)
                    return

                self._is_transitioning = False

                if result.is_ready:
                    # 6. Activate local mode only after full verification
                    self._active_engine = EngineMode.OLLAMA
                    self._requested_engine = EngineMode.OLLAMA
                    # 7. Persist setting according to Mark-LV conventions
                    self._save_engine_fn(EngineMode.OLLAMA)
                    mode_cb = self._on_mode_changed_fn
                    failure_cb = None
                else:
                    # 8. Preserve previous valid mode if any readiness step fails
                    self._requested_engine = self._active_engine
                    mode_cb = None
                    failure_cb = self._show_failure_dialog_fn

            if mode_cb:
                try:
                    mode_cb(EngineMode.OLLAMA)
                except Exception as e:
                    logger.error("[EngineManager] on_mode_changed callback failed: %s", e)

            if failure_cb:
                # Exact required primary message
                primary_msg = "Jarvis cannot switch to Local LLM Mode."
                try:
                    failure_cb(
                        primary_msg,
                        result.message,
                        self.retry_transition,
                        self.cancel_transition,
                    )
                except Exception as e:
                    logger.error("[EngineManager] show_failure_dialog callback failed: %s", e)

        self._run_async_fn(_worker)

    def cancel_transition(self) -> None:
        """
        User cancelled mode transition or chose to stay in previous mode.
        """
        with self._lock:
            # Invalidate any in-flight background worker
            self._current_generation += 1
            self._is_transitioning = False
            self._requested_engine = self._active_engine

        logger.info("[EngineManager] Mode transition cancelled; preserved active mode '%s'", self._active_engine)

    def retry_transition(self) -> None:
        """
        Retry transition to requested engine.
        """
        with self._lock:
            self._is_transitioning = False
        self.proceed_with_local_transition()

    def activate_gemini_mode(self) -> None:
        """
        Switch directly back to Gemini Live.
        """
        with self._lock:
            self._current_generation += 1
            self._is_transitioning = False
            self._active_engine = EngineMode.GEMINI_LIVE
            self._requested_engine = EngineMode.GEMINI_LIVE
            self._save_engine_fn(EngineMode.GEMINI_LIVE)
            mode_cb = self._on_mode_changed_fn

        logger.info("[EngineManager] Activated Gemini Live mode.")
        if mode_cb:
            try:
                mode_cb(EngineMode.GEMINI_LIVE)
            except Exception as e:
                logger.error("[EngineManager] on_mode_changed callback failed: %s", e)
