"""
Unit tests for Mark-LV / DIMO safe confirmation bridge.

Verifies:
1. Fail-closed behavior when confirmation interface is unavailable or headless.
2. Human confirmation gating for dangerous actions (restart, shutdown).
3. Immunity to model-generated token bypass attempts.
4. Immediate execution for non-dangerous system actions.
5. Loop execution halts immediately on pending_confirmation (0 retries, no replanning, no downstream steps).
6. LLM node tool result formatting recognizes CONFIRMATION_PENDING.
"""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage

from app.marklv.core import confirm
from app.services.system.windows_settings import WindowsSettingsService
from app.tools.native.system import computer_settings
from app.nodes.loop import execute_tool_loop
from app.nodes.llm import call_llm


class TestConfirmBridge(unittest.TestCase):

    def setUp(self):
        # Reset confirm state to clean unbound state
        confirm.bind(None, None, None)
        with confirm._lock:
            confirm._pending = None

    def tearDown(self):
        # Clean up confirm state
        confirm.bind(None, None, None)
        with confirm._lock:
            confirm._pending = None

    @patch("app.tools.native.system.WindowsSettingsService")
    def test_dangerous_action_headless_fails_closed(self, mock_service_cls):
        """When HUD interface is not bound (headless), dangerous actions fail closed."""
        mock_service = mock_service_cls.return_value

        res = computer_settings(action="restart")

        self.assertFalse(res["success"])
        self.assertFalse(res.get("pending_confirmation", False))
        self.assertIn("not available", res["error"])
        mock_service.execute_action.assert_not_called()

    @patch("app.tools.native.system.WindowsSettingsService")
    def test_dangerous_action_unimportable_confirm_fails_closed(self, mock_service_cls):
        """If confirm module is unavailable, dangerous actions fail closed."""
        mock_service = mock_service_cls.return_value
        import builtins
        orig_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if "confirm" in name or (fromlist and any("confirm" in str(f) for f in fromlist)):
                raise ImportError("No module named confirm")
            return orig_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=fake_import):
            res = computer_settings(action="shutdown")

            self.assertFalse(res["success"])
            self.assertFalse(res.get("pending_confirmation", False))
            self.assertIn("unavailable", res["error"])
            mock_service.execute_action.assert_not_called()

    @patch("app.tools.native.system.WindowsSettingsService")
    def test_dangerous_action_triggers_confirmation_request(self, mock_service_cls):
        """When HUD interface is bound, restart requests confirmation and does not execute."""
        mock_service = mock_service_cls.return_value
        show_mock = MagicMock()
        hide_mock = MagicMock()
        confirm.bind(show_mock, hide_mock)

        res = computer_settings(action="restart")

        self.assertFalse(res["success"])
        self.assertTrue(res.get("pending_confirmation"))
        self.assertIn("[CONFIRMATION_PENDING]", res["result"])
        show_mock.assert_called_once()
        self.assertEqual(show_mock.call_args[0][0], "Computer Restart")
        mock_service.execute_action.assert_not_called()
        self.assertEqual(confirm.pending_title(), "Computer Restart")

    @patch("app.tools.native.system.WindowsSettingsService")
    def test_pending_confirmation_blocks_concurrent_dangerous_action(self, mock_service_cls):
        """A new dangerous action cannot overwrite an existing pending confirmation banner."""
        mock_service = mock_service_cls.return_value
        show_mock = MagicMock()
        hide_mock = MagicMock()
        confirm.bind(show_mock, hide_mock)

        res1 = computer_settings(action="restart")
        self.assertTrue(res1.get("pending_confirmation"))

        res2 = computer_settings(action="shutdown")
        self.assertFalse(res2["success"])
        self.assertTrue(res2.get("pending_confirmation"))
        self.assertIn("currently pending", res2["error"])
        mock_service.execute_action.assert_not_called()
        self.assertEqual(confirm.pending_title(), "Computer Restart")

    @patch("app.tools.native.system.WindowsSettingsService")
    def test_token_parameter_cannot_bypass_confirmation(self, mock_service_cls):
        """Model cannot bypass confirmation by passing a token parameter."""
        mock_service = mock_service_cls.return_value
        show_mock = MagicMock()
        hide_mock = MagicMock()
        confirm.bind(show_mock, hide_mock)

        res = computer_settings(action="restart", token="FORGED_MODEL_TOKEN_12345")

        self.assertFalse(res["success"])
        self.assertTrue(res.get("pending_confirmation"))
        mock_service.execute_action.assert_not_called()

    @patch("app.tools.native.system.WindowsSettingsService")
    def test_human_resolution_cancel(self, mock_service_cls):
        """When human cancels, the dangerous action is abandoned and execute_action is never called."""
        mock_service = mock_service_cls.return_value
        show_mock = MagicMock()
        hide_mock = MagicMock()
        confirm.bind(show_mock, hide_mock)

        res = computer_settings(action="shutdown")
        self.assertTrue(res.get("pending_confirmation"))

        confirm.resolve(False)
        time.sleep(0.05)

        hide_mock.assert_called_once()
        mock_service.execute_action.assert_not_called()
        self.assertEqual(confirm.pending_title(), "")

    @patch("app.tools.native.system.WindowsSettingsService")
    def test_human_resolution_confirm(self, mock_service_cls):
        """When human confirms, the queued action is safely executed by the worker thread."""
        mock_service = mock_service_cls.return_value
        mock_service.execute_action.return_value = "Shutdown sequence initiated."
        show_mock = MagicMock()
        hide_mock = MagicMock()
        confirm.bind(show_mock, hide_mock)

        res = computer_settings(action="shutdown")
        self.assertTrue(res.get("pending_confirmation"))
        mock_service.execute_action.assert_not_called()

        confirm.resolve(True)

        # Worker thread executes action
        for _ in range(20):
            if mock_service.execute_action.called:
                break
            time.sleep(0.05)

        mock_service.execute_action.assert_called_once_with("shutdown", None)
        hide_mock.assert_called_once()
        self.assertEqual(confirm.pending_title(), "")

    @patch("app.tools.native.system.WindowsSettingsService")
    def test_non_dangerous_actions_execute_immediately(self, mock_service_cls):
        """Volume and non-dangerous actions execute immediately without confirmation."""
        mock_service = mock_service_cls.return_value
        mock_service.execute_action.return_value = "Volume increased."

        res = computer_settings(action="volume_up")

        self.assertTrue(res["success"])
        self.assertEqual(res["result"], "Volume increased.")
        mock_service.execute_action.assert_called_once_with("volume_up", None)
        self.assertEqual(confirm.pending_title(), "")

    @patch("app.tools.native.system.WindowsSettingsService")
    def test_production_core_confirm_import_path_shared_instance(self, mock_service_cls):
        """DIMO system tool uses the exact same core.confirm instance that Mark-LV binds to HUD."""
        mock_service = mock_service_cls.return_value
        mock_service.execute_action.return_value = "Restart sequence initiated."

        orig_sys_path = list(sys.path)
        orig_sys_modules = dict(sys.modules)

        marklv_dir = str(Path(__file__).resolve().parent.parent / "app" / "marklv")
        try:
            if marklv_dir not in sys.path:
                sys.path.insert(0, marklv_dir)

            import core.confirm as marklv_confirm

            show_mock = MagicMock()
            hide_mock = MagicMock()
            marklv_confirm.bind(show_mock, hide_mock)

            res = computer_settings(action="restart")

            self.assertFalse(res["success"])
            self.assertTrue(res.get("pending_confirmation"))
            show_mock.assert_called_once()
            self.assertEqual(show_mock.call_args[0][0], "Computer Restart")
            self.assertEqual(marklv_confirm.pending_title(), "Computer Restart")
            mock_service.execute_action.assert_not_called()

            # Confirming via the Mark-LV bound instance executes the action
            marklv_confirm.resolve(True)
            for _ in range(20):
                if mock_service.execute_action.called:
                    break
                time.sleep(0.05)

            mock_service.execute_action.assert_called_once_with("restart", None)
            self.assertEqual(marklv_confirm.pending_title(), "")

        finally:
            if "core.confirm" in sys.modules:
                sys.modules["core.confirm"].bind(None, None, None)
                with sys.modules["core.confirm"]._lock:
                    sys.modules["core.confirm"]._pending = None

            sys.path[:] = orig_sys_path
            for key in list(sys.modules.keys()):
                if key not in orig_sys_modules:
                    del sys.modules[key]

    @patch("app.tools.native.system.WindowsSettingsService")
    def test_dangerous_action_remains_pending_until_resolved(self, mock_service_cls):
        """A dangerous action remains pending and unexecuted until human confirmation callback resolves it."""
        mock_service = mock_service_cls.return_value
        mock_service.execute_action.return_value = "Computer restarted."
        show_mock = MagicMock()
        hide_mock = MagicMock()
        confirm.bind(show_mock, hide_mock)

        res = computer_settings(action="restart")
        self.assertTrue(res.get("pending_confirmation"))
        self.assertFalse(res["success"])

        # Verify action is pending and has not been executed
        self.assertEqual(confirm.pending_title(), "Computer Restart")
        mock_service.execute_action.assert_not_called()

        # Simulate time passing and intermediate activity: still pending, still not executed
        time.sleep(0.1)
        self.assertEqual(confirm.pending_title(), "Computer Restart")
        mock_service.execute_action.assert_not_called()

        # A concurrent dangerous action is rejected while this remains pending
        res2 = computer_settings(action="shutdown")
        self.assertTrue(res2.get("pending_confirmation"))
        self.assertIn("currently pending", res2["error"])
        mock_service.execute_action.assert_not_called()

        # Still pending before resolution
        self.assertEqual(confirm.pending_title(), "Computer Restart")
        mock_service.execute_action.assert_not_called()

        # Human resolves confirmation
        confirm.resolve(True)

        for _ in range(20):
            if mock_service.execute_action.called:
                break
            time.sleep(0.05)

        # Now and only now was execute_action called
        mock_service.execute_action.assert_called_once_with("restart", None)
        self.assertEqual(confirm.pending_title(), "")

    @patch("app.nodes.planning.replan")
    @patch("app.tools.native.system.WindowsSettingsService")
    def test_loop_halts_immediately_on_pending_confirmation(self, mock_service_cls, mock_replan):
        """When a tool returns pending_confirmation, loop halts with 0 retries, no replanning, and skips downstream steps."""
        mock_service = mock_service_cls.return_value
        show_mock = MagicMock()
        hide_mock = MagicMock()
        confirm.bind(show_mock, hide_mock)

        state = {
            "messages": [HumanMessage(content="Restart the PC and search the web")],
            "tool_plan": [
                {"step": 1, "tool": "computer_settings", "parameters": {"action": "restart"}, "description": "Restart PC"},
                {"step": 2, "tool": "computer_settings", "parameters": {"action": "volume_up"}, "description": "Increase volume"},
            ],
            "tool_calls_made": [],
            "step_results": {},
            "current_iteration": 0,
        }

        result_state = execute_tool_loop(state)

        # Exactly 1 tool call made
        calls = result_state.get("tool_calls_made", [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["tool"], "computer_settings")
        self.assertTrue(calls[0]["result"].get("pending_confirmation"))

        # Replan must NOT be called
        mock_replan.assert_not_called()

        # Step 2 must NOT have been executed
        self.assertNotIn(2, result_state.get("step_results", {}))

        # Tool output reflects confirmation pending
        self.assertIn("[CONFIRMATION_PENDING]", result_state.get("tool_output", ""))

    @patch("app.nodes.llm.Client")
    def test_llm_formats_confirmation_pending_status(self, mock_client_cls):
        """LLM node formats pending confirmation with CONFIRMATION_PENDING status in prompt."""
        mock_client = mock_client_cls.return_value
        mock_resp = MagicMock()
        mock_resp.response = "I have put a confirmation on screen. Please confirm on the HUD before I restart."
        mock_client.generate.return_value = mock_resp

        state = {
            "messages": [HumanMessage(content="Restart my PC")],
            "tool_calls_made": [
                {
                    "tool": "computer_settings",
                    "args": {"action": "restart"},
                    "result": {
                        "success": False,
                        "pending_confirmation": True,
                        "result": "[CONFIRMATION_PENDING] Need human confirmation.",
                        "error": "Confirmation required on HUD before action can proceed.",
                    },
                }
            ],
            "current_iteration": 1,
            "max_iterations": 5,
        }

        call_llm(state)

        # Check the prompt sent to Ollama
        self.assertTrue(mock_client.generate.called)
        call_kwargs = mock_client.generate.call_args[1]
        prompt = call_kwargs.get("prompt", "")

        self.assertIn("[CONFIRMATION_PENDING]", prompt)
        self.assertNotIn("[FAILED: Confirmation required on HUD", prompt)
        self.assertNotIn("[SUCCESS]", prompt)

    @patch("app.tools.native.system.WindowsSettingsService")
    def test_dangerous_action_aliases_require_confirmation_and_execute_only_after_approval(self, mock_service_cls):
        """Verify restart, restart_computer, shutdown, shutdown_computer and all space/hyphen/cased variants
        require confirmation, never execute without approval, and execute only after approval."""
        dangerous_aliases = [
            # Restart variants
            ("restart", "restart", "Computer Restart"),
            ("restart_computer", "restart_computer", "Computer Restart"),
            ("restart computer", "restart_computer", "Computer Restart"),
            ("restart-computer", "restart_computer", "Computer Restart"),
            ("  Restart  ", "restart", "Computer Restart"),
            ("RESTART-COMPUTER", "restart_computer", "Computer Restart"),
            # Shutdown variants
            ("shutdown", "shutdown", "Computer Shutdown"),
            ("shutdown_computer", "shutdown_computer", "Computer Shutdown"),
            ("shutdown computer", "shutdown_computer", "Computer Shutdown"),
            ("shutdown-computer", "shutdown_computer", "Computer Shutdown"),
            ("Shutdown Computer", "shutdown_computer", "Computer Shutdown"),
            ("  shutdown-computer  ", "shutdown_computer", "Computer Shutdown"),
        ]

        for raw_alias, expected_norm, expected_title in dangerous_aliases:
            with self.subTest(alias=raw_alias):
                # Clean confirm state for each subtest
                confirm.bind(None, None, None)
                with confirm._lock:
                    confirm._pending = None

                mock_service = mock_service_cls.return_value
                mock_service.reset_mock()
                mock_service.execute_action.return_value = "Action completed."

                show_mock = MagicMock()
                hide_mock = MagicMock()
                confirm.bind(show_mock, hide_mock)

                # 1. Call computer_settings with alias
                res = computer_settings(action=raw_alias)

                # 2. Verify it did NOT execute and requires confirmation
                self.assertFalse(res["success"], f"Alias '{raw_alias}' unexpectedly succeeded without confirmation")
                self.assertTrue(res.get("pending_confirmation"), f"Alias '{raw_alias}' did not set pending_confirmation")
                mock_service.execute_action.assert_not_called()
                self.assertEqual(confirm.pending_title(), expected_title)
                show_mock.assert_called_once()

                # 3. Verify it executes only after approval
                confirm.resolve(True)
                for _ in range(20):
                    if mock_service.execute_action.called:
                        break
                    time.sleep(0.05)

                mock_service.execute_action.assert_called_once_with(expected_norm, None)
                self.assertEqual(confirm.pending_title(), "")

    @patch("subprocess.run")
    def test_windows_settings_service_supports_all_aliases(self, mock_subprocess):
        """WindowsSettingsService natively supports restart, restart_computer, shutdown, shutdown_computer and variants."""
        service = WindowsSettingsService()
        for act in ("restart", "restart_computer", "restart computer", "restart-computer"):
            res = service.execute_action(act)
            self.assertIn("restarting", res)
        for act in ("shutdown", "shutdown_computer", "shutdown computer", "shutdown-computer"):
            res = service.execute_action(act)
            self.assertIn("shutting down", res)

    @patch("app.tools.native.system.WindowsSettingsService")
    def test_non_dangerous_action_normalization(self, mock_service_cls):
        """Non-dangerous action names with spaces or hyphens are normalized consistently before execution."""
        mock_service = mock_service_cls.return_value
        mock_service.execute_action.return_value = "Volume increased."

        for act in ("volume up", "volume-up", "  Volume_Up  "):
            with self.subTest(action=act):
                mock_service.reset_mock()
                res = computer_settings(action=act)
                self.assertTrue(res["success"])
                self.assertEqual(res["result"], "Volume increased.")
                mock_service.execute_action.assert_called_once_with("volume_up", None)
                self.assertEqual(confirm.pending_title(), "")


if __name__ == "__main__":
    unittest.main()
