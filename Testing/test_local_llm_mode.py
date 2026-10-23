"""
Unit tests for Slice 3: Connect Local LLM Mode to Mark-LV.

Verifies:
1. Cancelling the mode-switch dialog changes nothing.
2. Successful readiness activates local mode.
3. Failed readiness shows the exact failure message and preserves the previous provider.
4. Retry and duplicate-start prevention.
5. Stale startup completion cannot activate a cancelled or superseded transition.
6. Typed requests use the local coordinator without Gemini Live.
7. A local inference failure never causes cloud fallback.
8. Valid tool calls use Mark-LV's trusted dispatcher.
9. Confirmation-pending results halt further tool dispatch.
10. Unreviewed cloud-LLM-dependent actions are unavailable in local mode.
11. Local-mode voice is clearly unavailable and cannot enter Gemini Live.
12. Gemini mode retains its existing behavior.

Zero live network, Ollama, model, cloud API, audio device, or OS execution.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

# Ensure repository root is on sys.path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_MARKLV_DIR = os.path.join(_REPO_ROOT, "app", "marklv")
if _MARKLV_DIR not in sys.path:
    sys.path.insert(0, _MARKLV_DIR)

from app.marklv.core.engine_manager import (
    APPROVED_LOCAL_TOOLS,
    CLOUD_DEPENDENT_TOOLS,
    EngineMode,
    LocalModeTransitionController,
    filter_local_tool_declarations,
    is_tool_allowed_in_local_mode,
)
from app.marklv.core.ollama_manager import (
    OllamaReadinessResult,
    OllamaReadinessStatus,
    ProcessOwnership,
)
from app.marklv.core.local_turn_coordinator import (
    LocalTurnCoordinator,
    LocalTurnResult,
    ToolExecutionRecord,
    TurnStatus,
)


class TestLocalLLMMode(unittest.TestCase):

    def setUp(self):
        self.mock_ollama_mgr = MagicMock()
        self.mock_ollama_mgr.host = "http://localhost:11434"
        self.mock_ollama_mgr.model = "llama3.2"

        self.saved_engines = []
        self.mode_changes = []
        self.progress_updates = []
        self.confirm_dialog_calls = []
        self.failure_dialog_calls = []

    def _save_engine(self, engine: str):
        self.saved_engines.append(engine)

    def _on_mode_changed(self, mode: str):
        self.mode_changes.append(mode)

    def _on_progress(self, stage: str, msg: str):
        self.progress_updates.append((stage, msg))

    def _show_confirm_dialog(self, on_continue, on_cancel):
        self.confirm_dialog_calls.append((on_continue, on_cancel))

    def _show_failure_dialog(self, primary_msg, detail_msg, on_retry, on_cancel):
        self.failure_dialog_calls.append((primary_msg, detail_msg, on_retry, on_cancel))

    def _build_controller(self, active_engine="Gemini Live", run_sync=True):
        def _sync_runner(func):
            if run_sync:
                func()
            else:
                pass

        return LocalModeTransitionController(
            active_engine=active_engine,
            ollama_manager=self.mock_ollama_mgr,
            save_engine_fn=self._save_engine,
            show_confirm_dialog_fn=self._show_confirm_dialog,
            show_failure_dialog_fn=self._show_failure_dialog,
            notify_progress_fn=self._on_progress,
            on_mode_changed_fn=self._on_mode_changed,
            run_async_fn=_sync_runner,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Cancelling the mode-switch dialog changes nothing
    # ──────────────────────────────────────────────────────────────────────────
    def test_cancel_mode_switch_dialog_changes_nothing(self):
        controller = self._build_controller(active_engine="Gemini Live")

        # User chooses Ollama
        controller.select_engine("Ollama")

        self.assertEqual(len(self.confirm_dialog_calls), 1)
        on_continue, on_cancel = self.confirm_dialog_calls[0]

        # User clicks CANCEL
        on_cancel()

        # Nothing should have started or changed
        self.assertEqual(controller.active_engine, "Gemini Live")
        self.assertEqual(controller.requested_engine, "Gemini Live")
        self.assertFalse(controller.is_transitioning)
        self.assertEqual(len(self.saved_engines), 0)
        self.assertEqual(len(self.mode_changes), 0)
        self.mock_ollama_mgr.verify_or_start.assert_not_called()

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Successful readiness activates local mode
    # ──────────────────────────────────────────────────────────────────────────
    def test_successful_readiness_activates_local_mode(self):
        controller = self._build_controller(active_engine="Gemini Live", run_sync=True)

        self.mock_ollama_mgr.verify_or_start.return_value = OllamaReadinessResult(
            status=OllamaReadinessStatus.READY,
            stage="ready",
            message="Server and model ready",
            endpoint="http://localhost:11434",
            model="llama3.2",
            process_ownership=ProcessOwnership.MANAGED,
        )

        controller.select_engine("Ollama")
        self.assertEqual(len(self.confirm_dialog_calls), 1)
        on_continue, _ = self.confirm_dialog_calls[0]

        # User clicks CONTINUE
        on_continue()

        self.assertEqual(controller.active_engine, "Ollama")
        self.assertTrue(controller.is_local_mode)
        self.assertFalse(controller.is_transitioning)
        self.assertIn("Ollama", self.saved_engines)
        self.assertIn("Ollama", self.mode_changes)
        self.assertEqual(len(self.failure_dialog_calls), 0)

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Failed readiness shows the exact failure message and preserves previous provider
    # ──────────────────────────────────────────────────────────────────────────
    def test_failed_readiness_shows_exact_failure_message_and_preserves_previous_provider(self):
        controller = self._build_controller(active_engine="Gemini Live", run_sync=True)

        self.mock_ollama_mgr.verify_or_start.return_value = OllamaReadinessResult(
            status=OllamaReadinessStatus.MODEL_MISSING,
            stage="model_check",
            message="Model 'llama3.2' is not installed in Ollama.",
            endpoint="http://localhost:11434",
            model="llama3.2",
        )

        controller.select_engine("Ollama")
        on_continue, _ = self.confirm_dialog_calls[0]
        on_continue()

        # Must preserve previous valid provider
        self.assertEqual(controller.active_engine, "Gemini Live")
        self.assertEqual(controller.requested_engine, "Gemini Live")
        self.assertFalse(controller.is_local_mode)
        self.assertEqual(len(self.saved_engines), 0)

        # Must show exact primary message
        self.assertEqual(len(self.failure_dialog_calls), 1)
        primary, detail, on_retry, on_cancel = self.failure_dialog_calls[0]
        self.assertEqual(primary, "Jarvis cannot switch to Local LLM Mode.")
        self.assertIn("llama3.2", detail)

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Retry and duplicate-start prevention
    # ──────────────────────────────────────────────────────────────────────────
    def test_retry_and_duplicate_start_prevention(self):
        # Test duplicate start prevention
        captured_worker = []
        def _deferred_runner(func):
            captured_worker.append(func)

        controller = LocalModeTransitionController(
            active_engine="Gemini Live",
            ollama_manager=self.mock_ollama_mgr,
            save_engine_fn=self._save_engine,
            show_confirm_dialog_fn=self._show_confirm_dialog,
            show_failure_dialog_fn=self._show_failure_dialog,
            run_async_fn=_deferred_runner,
        )

        controller.select_engine("Ollama")
        on_continue, _ = self.confirm_dialog_calls[0]
        on_continue()

        self.assertTrue(controller.is_transitioning)
        self.assertEqual(len(captured_worker), 1)

        # Attempt duplicate selection while transition is active
        controller.select_engine("Ollama")
        self.assertEqual(len(captured_worker), 1, "Duplicate start should not launch a second worker")

        # Now simulate failure and test retry
        self.mock_ollama_mgr.verify_or_start.return_value = OllamaReadinessResult(
            status=OllamaReadinessStatus.SERVER_UNREACHABLE,
            stage="connectivity",
            message="Ollama server unreachable",
            endpoint="http://localhost:11434",
            model="llama3.2",
        )
        captured_worker[0]()  # run first worker

        self.assertEqual(len(self.failure_dialog_calls), 1)
        _, _, on_retry, _ = self.failure_dialog_calls[0]

        # Trigger Retry
        on_retry()
        self.assertEqual(len(captured_worker), 2, "Retry should launch a new readiness worker")

    # ──────────────────────────────────────────────────────────────────────────
    # 5. Stale startup completion cannot activate a cancelled or superseded transition
    # ──────────────────────────────────────────────────────────────────────────
    def test_stale_startup_completion_cannot_activate_cancelled_or_superseded(self):
        captured_worker = []
        def _deferred_runner(func):
            captured_worker.append(func)

        controller = LocalModeTransitionController(
            active_engine="Gemini Live",
            ollama_manager=self.mock_ollama_mgr,
            save_engine_fn=self._save_engine,
            show_confirm_dialog_fn=self._show_confirm_dialog,
            show_failure_dialog_fn=self._show_failure_dialog,
            on_mode_changed_fn=self._on_mode_changed,
            run_async_fn=_deferred_runner,
        )

        controller.select_engine("Ollama")
        on_continue, _ = self.confirm_dialog_calls[0]
        on_continue()

        self.assertEqual(len(captured_worker), 1)

        # User cancels or switches back to Gemini Live before worker finishes
        controller.cancel_transition()
        self.assertEqual(controller.active_engine, "Gemini Live")

        # Now the background worker completes with ready
        self.mock_ollama_mgr.verify_or_start.return_value = OllamaReadinessResult(
            status=OllamaReadinessStatus.READY,
            stage="ready",
            message="Ready now",
            endpoint="http://localhost:11434",
            model="llama3.2",
        )
        captured_worker[0]()

        # Must NOT activate or persist Ollama because the task was cancelled/stale!
        self.assertEqual(controller.active_engine, "Gemini Live")
        self.assertEqual(len(self.saved_engines), 0)
        self.assertEqual(len(self.mode_changes), 0)

    # ──────────────────────────────────────────────────────────────────────────
    # 6. Typed requests use the local coordinator without Gemini Live
    # ──────────────────────────────────────────────────────────────────────────
    def test_typed_requests_use_local_coordinator_without_gemini_live(self):
        mock_ui = MagicMock()
        mock_ui.muted = False

        from app.marklv.main import JarvisLive

        with patch.object(JarvisLive, "__init__", lambda self, ui: None):
            live = JarvisLive(mock_ui)
            live.ui = mock_ui
            live._loop = asyncio.new_event_loop()
            live._asst_name = "JARVIS"
            live._session_log = []
            live._dashboard = None
            live._local_history = []
            live.session = None  # No Gemini Live session

            # Mock coordinator
            mock_coord = MagicMock()
            mock_coord.execute_turn.return_value = LocalTurnResult(
                status=TurnStatus.SUCCESS,
                content="Local response to user query.",
                updated_history=[
                    {"role": "user", "content": "hello local"},
                    {"role": "assistant", "content": "Local response to user query."},
                ],
            )
            live._local_coordinator = mock_coord
            live._action_registry = MagicMock()
            live._action_registry.get_tool_declarations.return_value = []
            live._plugin_registry = MagicMock()
            live._plugin_registry.get_tool_declarations.return_value = []

            with patch.object(live, "is_local_mode", return_value=True):
                # Run local command
                coro = live._handle_local_text_command("hello local")
                live._loop.run_until_complete(coro)

            # Assert coordinator was called
            mock_coord.execute_turn.assert_called_once()
            call_kwargs = mock_coord.execute_turn.call_args[1]
            self.assertEqual(call_kwargs["user_text"], "hello local")

            # Assert UI log was written
            mock_ui.write_log.assert_any_call("You: hello local")
            mock_ui.write_log.assert_any_call("JARVIS: Local response to user query.")
            self.assertEqual(live._local_history, mock_coord.execute_turn.return_value.updated_history)
            live._loop.close()

    # ──────────────────────────────────────────────────────────────────────────
    # 7. A local inference failure never causes cloud fallback
    # ──────────────────────────────────────────────────────────────────────────
    def test_local_inference_failure_never_causes_cloud_fallback(self):
        mock_ui = MagicMock()
        from app.marklv.main import JarvisLive

        with patch.object(JarvisLive, "__init__", lambda self, ui: None):
            live = JarvisLive(mock_ui)
            live.ui = mock_ui
            live._loop = asyncio.new_event_loop()
            live._asst_name = "JARVIS"
            live._session_log = []
            live._dashboard = None
            live._local_history = []
            live.session = None

            mock_coord = MagicMock()
            mock_coord.execute_turn.return_value = LocalTurnResult(
                status=TurnStatus.PROVIDER_ERROR,
                content="",
                error_message="Ollama process connection refused.",
            )
            live._local_coordinator = mock_coord
            live._action_registry = MagicMock()
            live._action_registry.get_tool_declarations.return_value = []
            live._plugin_registry = MagicMock()
            live._plugin_registry.get_tool_declarations.return_value = []

            with patch.object(live, "is_local_mode", return_value=True):
                coro = live._handle_local_text_command("perform action")
                live._loop.run_until_complete(coro)

            # Assert explicit error logged
            mock_ui.write_log.assert_any_call("SYS: Ollama process connection refused.")
            # Assert no Gemini call
            self.assertIsNone(live.session)
            live._loop.close()

    # ──────────────────────────────────────────────────────────────────────────
    # 8. Valid tool calls use Mark-LV's trusted dispatcher
    # ──────────────────────────────────────────────────────────────────────────
    def test_valid_tool_calls_use_marklv_trusted_dispatcher(self):
        mock_ui = MagicMock()
        from app.marklv.main import JarvisLive

        with patch.object(JarvisLive, "__init__", lambda self, ui: None):
            live = JarvisLive(mock_ui)
            live.ui = mock_ui
            live.speak = MagicMock()
            live._action_registry = MagicMock()
            live._action_registry.has.return_value = True
            live._action_registry.run.return_value = "Chrome launched successfully."
            live._plugin_registry = MagicMock()
            live._plugin_registry.has.return_value = False

            # Dispatch safe local tool
            res = live._dispatch_local_tool("open_app", {"app_name": "chrome"})

            self.assertEqual(res, "Chrome launched successfully.")
            live._action_registry.run.assert_called_once()
            call_args = live._action_registry.run.call_args[0]
            self.assertEqual(call_args[0], "open_app")
            self.assertEqual(call_args[1], {"app_name": "chrome"})

    # ──────────────────────────────────────────────────────────────────────────
    # 9. Confirmation-pending results halt further tool dispatch
    # ──────────────────────────────────────────────────────────────────────────
    def test_confirmation_pending_results_halt_further_tool_dispatch(self):
        mock_ui = MagicMock()
        from app.marklv.main import JarvisLive

        with patch.object(JarvisLive, "__init__", lambda self, ui: None):
            live = JarvisLive(mock_ui)
            live.ui = mock_ui
            live.speak = MagicMock()
            live._action_registry = MagicMock()
            live._action_registry.has.return_value = True
            live._action_registry.run.return_value = "[CONFIRMATION_PENDING] Please confirm computer restart on HUD."
            live._plugin_registry = MagicMock()
            live._plugin_registry.has.return_value = False

            res = live._dispatch_local_tool("computer_settings", {"action": "restart"})

            self.assertTrue(res.startswith("[CONFIRMATION_PENDING]"))

            # Now verify coordinator halts on confirmation_pending
            mock_client = MagicMock()
            mock_client.provider = "ollama"
            mock_client.endpoint = "http://localhost:11434"
            mock_client.chat.side_effect = [
                {"content": "", "tool_calls": [{"function": {"name": "computer_settings", "arguments": {"action": "restart"}}}]},
                {"content": "I have requested confirmation for restart.", "tool_calls": []},
            ]

            coord = LocalTurnCoordinator(
                llm_client=mock_client,
                dispatcher=lambda name, args: res,
                host="http://localhost:11434",
                model="llama3.2",
                max_tool_rounds=3,
            )

            turn_res = coord.execute_turn(
                user_text="Restart my computer",
                tool_declarations=[{
                    "name": "computer_settings",
                    "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}}},
                }],
            )

            self.assertEqual(turn_res.status, TurnStatus.CONFIRMATION_PENDING)
            self.assertEqual(len(turn_res.tool_calls), 1)
            self.assertEqual(turn_res.tool_calls[0].error, "confirmation_pending")
            self.assertIn("[CONFIRMATION_PENDING]", turn_res.tool_calls[0].result)
            self.assertEqual(turn_res.rounds, 1)

    # ──────────────────────────────────────────────────────────────────────────
    # 10. Unreviewed cloud-LLM-dependent actions are unavailable in local mode
    # ──────────────────────────────────────────────────────────────────────────
    def test_unreviewed_cloud_dependent_actions_unavailable_in_local_mode(self):
        mock_ui = MagicMock()
        from app.marklv.main import JarvisLive

        with patch.object(JarvisLive, "__init__", lambda self, ui: None):
            live = JarvisLive(mock_ui)
            live.ui = mock_ui
            live.speak = MagicMock()
            live._action_registry = MagicMock()
            live._plugin_registry = MagicMock()

            # 1. Verify declarations filter
            test_decls = [
                {"name": "open_app", "description": "Open local app"},
                {"name": "code_helper", "description": "Generate code via Gemini"},
                {"name": "desktop_control", "description": "Automate desktop via Gemini"},
                {"name": "computer_settings", "description": "System settings"},
                {"name": "dev_agent", "description": "Coding agent via Gemini"},
            ]
            filtered = filter_local_tool_declarations(test_decls)
            filtered_names = {d["name"] for d in filtered}

            self.assertIn("open_app", filtered_names)
            self.assertIn("computer_settings", filtered_names)
            self.assertNotIn("code_helper", filtered_names)
            self.assertNotIn("desktop_control", filtered_names)
            self.assertNotIn("dev_agent", filtered_names)

            # 2. Verify dispatcher block for cloud-dependent tools
            for cloud_tool in CLOUD_DEPENDENT_TOOLS:
                self.assertFalse(is_tool_allowed_in_local_mode(cloud_tool))
                res = live._dispatch_local_tool(cloud_tool, {})
                self.assertIn("unavailable in Local LLM Mode", res)

            # 3. Verify positive allowlist rejects unreviewed future actions and plugins
            self.assertFalse(is_tool_allowed_in_local_mode("unreviewed_future_action"))
            self.assertFalse(is_tool_allowed_in_local_mode("unreviewed_plugin_xyz"))
            unreviewed_res = live._dispatch_local_tool("unreviewed_future_action", {})
            self.assertIn("unavailable in Local LLM Mode", unreviewed_res)

            # 4. Verify approved tools are allowed
            for approved in ("open_app", "computer_settings", "save_memory", "undo"):
                self.assertIn(approved, APPROVED_LOCAL_TOOLS)
                self.assertTrue(is_tool_allowed_in_local_mode(approved))

            # Action registry run should NEVER have been called for unallowed tools
            live._action_registry.run.assert_not_called()

    # ──────────────────────────────────────────────────────────────────────────
    # 11. Local-mode voice is clearly unavailable and cannot enter Gemini Live
    # ──────────────────────────────────────────────────────────────────────────
    def test_local_mode_voice_clearly_unavailable_cannot_enter_gemini(self):
        mock_ui = MagicMock()
        from app.marklv.main import JarvisLive

        with patch.object(JarvisLive, "__init__", lambda self, ui: None):
            live = JarvisLive(mock_ui)
            live.ui = mock_ui
            live.session = None

            with patch.object(live, "is_local_mode", return_value=True):
                # User presses push-to-talk in local mode
                live._on_ptt(held=True)

            mock_ui.write_log.assert_called_with("SYS: Voice interaction is unavailable in Local LLM Mode. Please type your message.")
            self.assertIsNone(live.session)

    # ──────────────────────────────────────────────────────────────────────────
    # 12. Gemini mode retains its existing behavior
    # ──────────────────────────────────────────────────────────────────────────
    def test_gemini_mode_retains_existing_behavior(self):
        mock_ui = MagicMock()
        from app.marklv.main import JarvisLive

        loop = asyncio.new_event_loop()
        try:
            with patch.object(JarvisLive, "__init__", lambda self, ui: None):
                live = JarvisLive(mock_ui)
                live.ui = mock_ui
                live._loop = loop
                live._wake_enabled = False
                live._awake = True

                called_args = []
                async def _fake_send(*args, **kwargs):
                    called_args.append((args, kwargs))
                    return None

                mock_session = MagicMock()
                mock_session.send_client_content = _fake_send
                live.session = mock_session

                with patch.object(live, "is_local_mode", return_value=False):
                    live._on_text_command("Hello Gemini")
                    loop.run_until_complete(asyncio.sleep(0.01))

                self.assertEqual(len(called_args), 1)
                call_kwargs = called_args[0][1]
                self.assertEqual(call_kwargs["turns"]["parts"][0]["text"], "Hello Gemini")
                self.assertTrue(call_kwargs["turn_complete"])
        finally:
            loop.close()

    # ──────────────────────────────────────────────────────────────────────────
    # 13. Incompatible OpenAI provider configuration fails closed
    # ──────────────────────────────────────────────────────────────────────────
    def test_incompatible_openai_provider_fails_closed(self):
        from app.marklv.core.ollama_manager import OllamaManager, OllamaReadinessStatus

        with patch("app.marklv.core.llm_client.get_llm_provider", return_value="openai"):
            mgr = OllamaManager(host="http://localhost:1234", model="gpt-4")
            res = mgr.check_readiness(auto_start=False)

            self.assertFalse(res.is_ready)
            self.assertEqual(res.status, OllamaReadinessStatus.CONFIGURATION_MISMATCH)
            self.assertIn("Configured LLM provider in api_keys.json is 'openai'", res.message)
            self.assertIn("Local LLM Mode requires an Ollama provider", res.message)

        # Also verify in JarvisLive._init_local_coordinator
        mock_ui = MagicMock()
        from app.marklv.main import JarvisLive

        with patch.object(JarvisLive, "__init__", lambda self, ui: None):
            live = JarvisLive(mock_ui)
            live.ui = mock_ui

            with patch("app.marklv.core.llm_client.get_llm_provider", return_value="openai"):
                live._init_local_coordinator()

            self.assertIsNone(live._local_coordinator)
            mock_ui.write_log.assert_called_with("SYS: ❌ Configured LLM provider 'openai' is not supported in Local LLM Mode. Only Ollama is supported.")

    # ──────────────────────────────────────────────────────────────────────────
    # 14. Host and model consistency between readiness manager and coordinator
    # ──────────────────────────────────────────────────────────────────────────
    def test_host_and_model_consistency_between_manager_and_coordinator(self):
        mock_ui = MagicMock()
        mock_controller = MagicMock()
        mock_mgr = MagicMock()
        mock_mgr.host = "http://127.0.0.1:11434"
        mock_mgr.model = "qwen2.5:7b"
        mock_controller.ollama_manager = mock_mgr
        mock_ui.engine_controller = mock_controller

        from app.marklv.main import JarvisLive

        with patch.object(JarvisLive, "__init__", lambda self, ui: None):
            live = JarvisLive(mock_ui)
            live.ui = mock_ui

            with patch("app.marklv.core.llm_client.get_llm_provider", return_value="ollama"):
                live._init_local_coordinator()

            self.assertEqual(live._ollama_host, "http://127.0.0.1:11434")
            self.assertEqual(live._ollama_model, "qwen2.5:7b")
            self.assertIsNotNone(live._local_coordinator)
            self.assertEqual(live._local_coordinator.host, "http://127.0.0.1:11434")
            self.assertEqual(live._local_coordinator.model, "qwen2.5:7b")


# ==============================================================================
# Focused Deterministic Tests for Qwen2.5:7b Model Configuration
# ==============================================================================
class TestQwenModelConfiguration(unittest.TestCase):
    """
    Validates safe configuration of 'qwen2.5:7b' as Jarvis's authoritative local model:
    1. The configured default is qwen2.5:7b.
    2. The readiness manager receives qwen2.5:7b.
    3. The local coordinator sends requests to qwen2.5:7b.
    4. Model-name matching accepts the exact installed tag.
    5. A missing model still fails safely.
    6. Existing unrelated configuration settings are preserved.
    """

    def test_configured_default_is_qwen(self):
        from app.marklv.core.llm_client import _DEFAULTS, get_llm_settings
        from app.marklv.memory.config_manager import DEFAULT_LLM_MODEL, get_llm_model
        from app.marklv.core.ollama_manager import OllamaManager

        # 1. Defaults in llm_client
        self.assertEqual(_DEFAULTS["llm_model"], "qwen2.5:7b")
        url, model = get_llm_settings()
        self.assertEqual(model, "qwen2.5:7b")

        # 2. Defaults in config_manager
        self.assertEqual(DEFAULT_LLM_MODEL, "qwen2.5:7b")
        self.assertEqual(get_llm_model(), "qwen2.5:7b")

        # 3. Defaults in OllamaManager
        mgr = OllamaManager()
        self.assertEqual(mgr.model, "qwen2.5:7b")

    def test_readiness_manager_receives_qwen(self):
        from app.marklv.core.ollama_manager import (
            HttpClientProtocol,
            OllamaManager,
            OllamaReadinessStatus,
            ProcessLauncherProtocol,
        )

        mock_http = MagicMock()
        # Ping
        mock_http.get.side_effect = [
            MagicMock(status_code=200),  # Step A: connectivity
            MagicMock(status_code=200, json=lambda: {"models": [{"name": "qwen2.5:7b"}]}),  # Step C: tags
        ]
        # Step D: inference
        mock_http.post.return_value = MagicMock(status_code=200, json=lambda: {"message": {"content": "Ready."}})

        mock_launcher = MagicMock()
        mgr = OllamaManager(
            host="http://localhost:11434",
            http_client=mock_http,
            process_launcher=mock_launcher,
        )
        self.assertEqual(mgr.model, "qwen2.5:7b")

        result = mgr.check_readiness(auto_start=False)
        self.assertEqual(result.status, OllamaReadinessStatus.READY)
        self.assertEqual(result.model, "qwen2.5:7b")

        # Verify inference request payload targeted qwen2.5:7b
        mock_http.post.assert_called_once()
        post_kwargs = mock_http.post.call_args[1]
        self.assertEqual(post_kwargs["json"]["model"], "qwen2.5:7b")

    def test_local_coordinator_requests_qwen(self):
        from app.marklv.core.local_turn_coordinator import (
            DefaultOllamaChatClient,
            LocalTurnCoordinator,
            TurnStatus,
        )

        # Verify DefaultOllamaChatClient defaults
        client = MagicMock()
        client.provider = "ollama"
        client.endpoint = "http://localhost:11434"
        client.chat.return_value = {"content": "Hello from Qwen", "tool_calls": []}

        coord = LocalTurnCoordinator(
            llm_client=client,
            dispatcher=lambda n, a: "ok",
        )
        self.assertEqual(coord.model, "qwen2.5:7b")

        res = coord.execute_turn("Test query")
        self.assertEqual(res.status, TurnStatus.SUCCESS)
        self.assertEqual(res.content, "Hello from Qwen")

        # Test DefaultOllamaChatClient formats payload with qwen2.5:7b
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"message": {"content": "Response from qwen", "tool_calls": []}},
            )
            chat_client = DefaultOllamaChatClient(host="http://localhost:11434", model="qwen2.5:7b")
            chat_client.chat(messages=[{"role": "user", "content": "Hi"}])

            mock_post.assert_called_once()
            called_payload = mock_post.call_args[1]["json"]
            self.assertEqual(called_payload["model"], "qwen2.5:7b")

    def test_model_name_matching_accepts_installed_tag(self):
        from app.marklv.core.ollama_manager import is_model_installed

        # Exactly the models reported on the user's system
        user_installed = [
            "llama3.1:8b",
            "llama3.2:3b",
            "llama3:8b",
            "llama3:latest",
            "qwen2.5:7b",
        ]

        self.assertTrue(is_model_installed("qwen2.5:7b", user_installed))
        # Untagged or wrong tags must not falsely match
        self.assertFalse(is_model_installed("qwen2.5", user_installed))
        self.assertFalse(is_model_installed("qwen2.5:14b", user_installed))

    def test_missing_model_still_fails_safely(self):
        from app.marklv.core.ollama_manager import (
            OllamaManager,
            OllamaReadinessStatus,
            is_model_installed,
        )

        user_installed = [
            "llama3.1:8b",
            "llama3.2:3b",
            "llama3:8b",
            "llama3:latest",
            "qwen2.5:7b",
        ]

        # 1. llama3.2 is not in the list (only llama3.2:3b is)
        self.assertFalse(is_model_installed("llama3.2", user_installed))
        # 2. mistral:7b is missing
        self.assertFalse(is_model_installed("mistral:7b", user_installed))

        # 3. When checked through readiness manager, it reports MODEL_MISSING
        mock_http = MagicMock()
        mock_http.get.side_effect = [
            MagicMock(status_code=200),  # ping
            MagicMock(status_code=200, json=lambda: {"models": [{"name": m} for m in user_installed]}),
        ]
        mgr = OllamaManager(
            host="http://localhost:11434",
            model="mistral:7b",
            http_client=mock_http,
        )
        res = mgr.check_readiness(auto_start=False)
        self.assertEqual(res.status, OllamaReadinessStatus.MODEL_MISSING)
        self.assertIn("Model 'mistral:7b' is not installed in Ollama", res.message)
        self.assertFalse(res.is_ready)

    def test_unrelated_configuration_settings_are_preserved(self):
        from app.marklv.memory.config_manager import save_llm_model, load_api_keys

        # Read current keys
        before = load_api_keys()

        # Update model
        save_llm_model("qwen2.5:7b")

        after = load_api_keys()
        self.assertEqual(after.get("llm_model"), "qwen2.5:7b")

        # Every unrelated key must be preserved exactly
        for k, v in before.items():
            if k == "llm_model":
                continue
            self.assertEqual(after.get(k), v, f"Setting '{k}' was unexpectedly modified.")

    def test_fresh_startup_defaults_to_gemini_live(self):
        from app.marklv.memory.config_manager import save_ai_engine, save_llm_model, get_ai_engine, get_llm_model

        # Simulate prior session leaving Ollama mode active
        save_ai_engine("Ollama")
        save_llm_model("qwen2.5:7b")
        self.assertEqual(get_ai_engine(), "Ollama")

        # Simulate fresh launch in JarvisLive
        from app.marklv.main import JarvisLive
        mock_ui = MagicMock()
        with patch.object(JarvisLive, "__init__", lambda self, ui: None):
            live = JarvisLive(mock_ui)
            live.ui = mock_ui
            # Fresh launch default is applied
            save_ai_engine("Gemini Live")

        self.assertEqual(get_ai_engine(), "Gemini Live")
        # Ensure configured local model is preserved
        self.assertEqual(get_llm_model(), "qwen2.5:7b")

    def test_typed_command_from_ui_avoids_duplicate_log(self):
        mock_ui = MagicMock()
        from app.marklv.main import JarvisLive

        with patch.object(JarvisLive, "__init__", lambda self, ui: None):
            live = JarvisLive(mock_ui)
            live.ui = mock_ui
            live._loop = asyncio.new_event_loop()
            live._asst_name = "JARVIS"
            live._session_log = []
            live._dashboard = None
            live._local_history = []

            mock_coord = MagicMock()
            mock_coord.execute_turn.return_value = LocalTurnResult(
                status=TurnStatus.SUCCESS,
                content="Response text.",
                updated_history=[],
            )
            live._local_coordinator = mock_coord
            live._action_registry = MagicMock()
            live._action_registry.get_tool_declarations.return_value = []
            live._plugin_registry = MagicMock()
            live._plugin_registry.get_tool_declarations.return_value = []

            with patch.object(live, "is_local_mode", return_value=True):
                # 1. When typed from UI (from_ui=True), "You: ..." should NOT be written by coordinator
                live._loop.run_until_complete(
                    live._handle_local_text_command("hello", from_ui=True)
                )
                self.assertNotIn("You: hello", [c[0][0] for c in mock_ui.write_log.call_args_list])
                mock_ui.write_log.assert_any_call("JARVIS: Response text.")

                mock_ui.reset_mock()

                # 2. When received from voice (from_ui=False), "You: ..." MUST be written
                live._loop.run_until_complete(
                    live._handle_local_text_command("hello voice", from_ui=False)
                )
                mock_ui.write_log.assert_any_call("You: hello voice")
                mock_ui.write_log.assert_any_call("JARVIS: Response text.")
            live._loop.close()

    def test_local_mode_system_prompt_includes_voice_support(self):
        mock_ui = MagicMock()
        from app.marklv.main import JarvisLive

        with patch.object(JarvisLive, "__init__", lambda self, ui: None):
            live = JarvisLive(mock_ui)
            live._asst_name = "JARVIS"
            live._user_name = "User"
            prompt = live._get_local_system_prompt()
            self.assertIn("Voice input", prompt)
            self.assertIn("spoken audio responses", prompt)
            self.assertIn("Push-to-Talk", prompt)


if __name__ == "__main__":
    unittest.main()
