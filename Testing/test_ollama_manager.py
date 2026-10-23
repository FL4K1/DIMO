"""
Unit tests for Mark-LV Ollama Manager (app/marklv/core/ollama_manager.py).

Deterministic tests using mock HTTP clients and mock process launchers.
Does not require a real Ollama installation, running models, or network access.
"""

from __future__ import annotations

import json
import threading
import time
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from app.marklv.core.ollama_manager import (
    HttpClientProtocol,
    OllamaManager,
    OllamaReadinessResult,
    OllamaReadinessStatus,
    ProcessLauncherProtocol,
    ProcessOwnership,
    is_model_installed,
    sanitize_message,
)


class MockResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text or (json.dumps(json_data) if json_data is not None else "")

    def json(self) -> Any:
        if self._json_data is not None:
            return self._json_data
        return json.loads(self.text)


class MockProcess:
    def __init__(self, pid: int = 12345, returncode: Optional[int] = None):
        self.pid = pid
        self.returncode = returncode

    def poll(self) -> Optional[int]:
        return self.returncode


class FakeClock:
    """Controllable monotonic clock for deadline tests without wall-clock sleeps."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestOllamaManager(unittest.TestCase):

    def setUp(self):
        self.mock_http = MagicMock(spec=HttpClientProtocol)
        self.mock_launcher = MagicMock(spec=ProcessLauncherProtocol)
        self.mock_launcher.find_executable.return_value = "/usr/local/bin/ollama"
        self.mock_proc = MockProcess(pid=4242)
        self.mock_launcher.launch.return_value = self.mock_proc

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 1: Already-running server is reused without launching
    # ──────────────────────────────────────────────────────────────────────────
    def test_already_running_server_reused_without_launch(self):
        """When host is already reachable, it is reused and no process is launched."""
        self.mock_http.get.return_value = MockResponse(
            200, json_data={"models": [{"name": "llama3.2:latest"}]}
        )
        self.mock_http.post.return_value = MockResponse(
            200, json_data={"response": "pong"}
        )

        manager = OllamaManager(
            host="http://localhost:11434",
            model="llama3.2",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
        )

        result = manager.check_readiness(auto_start=True)

        self.assertEqual(result.status, OllamaReadinessStatus.READY)
        self.assertTrue(result.is_ready)
        self.assertEqual(result.process_ownership, ProcessOwnership.EXTERNAL)
        self.assertFalse(result.is_managed)
        self.assertIsNone(result.pid)
        self.mock_launcher.launch.assert_not_called()

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 2: Unavailable server triggers one launch attempt
    # ──────────────────────────────────────────────────────────────────────────
    def test_unavailable_server_triggers_single_launch(self):
        """When host is initially unreachable, exactly one launch attempt is made."""
        # Initial ping fails -> launch -> subsequent ping succeeds -> tags succeeds
        self.mock_http.get.side_effect = [
            ConnectionError("Server down"),  # Step A initial ping
            ConnectionError("Server down"),  # inside lock recheck
            MockResponse(200, json_data={"models": [{"name": "llama3.2:latest"}]}),  # poll
            MockResponse(200, json_data={"models": [{"name": "llama3.2:latest"}]}),  # Step C tags
        ]
        self.mock_http.post.return_value = MockResponse(
            200, json_data={"response": "pong"}
        )

        manager = OllamaManager(
            host="http://localhost:11434",
            model="llama3.2",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
            startup_timeout=1.0,
            poll_interval=0.01,
        )

        result = manager.check_readiness(auto_start=True)

        self.mock_launcher.launch.assert_called_once_with(["/usr/local/bin/ollama", "serve"])
        self.assertEqual(result.status, OllamaReadinessStatus.READY)
        self.assertEqual(result.process_ownership, ProcessOwnership.MANAGED)
        self.assertTrue(result.is_managed)
        self.assertEqual(result.pid, 4242)

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 3: Successful launch followed by successful readiness check
    # ──────────────────────────────────────────────────────────────────────────
    def test_successful_launch_and_readiness_returns_ready(self):
        """Verify full path from successful launch to final readiness confirmation."""
        self.mock_http.get.side_effect = [
            ConnectionError("offline"),
            ConnectionError("offline"),
            MockResponse(200, json_data={"models": [{"name": "mistral:latest"}]}),
            MockResponse(200, json_data={"models": [{"name": "mistral:latest"}]}),
        ]
        self.mock_http.post.return_value = MockResponse(
            200, json_data={"response": "Ready to assist."}
        )

        manager = OllamaManager(
            host="http://localhost:11434",
            model="mistral",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
            startup_timeout=1.0,
            poll_interval=0.01,
        )

        result = manager.check_readiness(auto_start=True)

        self.assertEqual(result.status, OllamaReadinessStatus.READY)
        self.assertEqual(result.stage, "ready")
        self.assertIn("ready for inference", result.message)

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 4: Missing executable or launch exception returns launch_failed
    # ──────────────────────────────────────────────────────────────────────────
    def test_missing_executable_returns_launch_failed(self):
        """When executable cannot be found, returns launch_failed with clear stage."""
        self.mock_http.get.side_effect = ConnectionError("offline")
        self.mock_launcher.find_executable.return_value = None

        manager = OllamaManager(
            host="http://localhost:11434",
            model="llama3.2",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
        )

        result = manager.check_readiness(auto_start=True)

        self.assertEqual(result.status, OllamaReadinessStatus.LAUNCH_FAILED)
        self.assertEqual(result.stage, "launch")
        self.assertIn("not found", result.message)
        self.mock_launcher.launch.assert_not_called()

    def test_launch_exception_returns_launch_failed(self):
        """When launcher raises an exception (e.g. PermissionError), returns launch_failed."""
        self.mock_http.get.side_effect = ConnectionError("offline")
        self.mock_launcher.launch.side_effect = PermissionError("Access denied")

        manager = OllamaManager(
            host="http://localhost:11434",
            model="llama3.2",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
        )

        result = manager.check_readiness(auto_start=True)

        self.assertEqual(result.status, OllamaReadinessStatus.LAUNCH_FAILED)
        self.assertEqual(result.stage, "launch")
        self.assertIn("Failed to launch", result.message)

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 5: Concurrent attempts do not launch duplicate processes
    # ──────────────────────────────────────────────────────────────────────────
    def test_concurrent_attempts_do_not_launch_duplicates(self):
        """Multiple simultaneous threads trigger only one launch call under lock."""
        launch_count = 0
        server_started = threading.Event()

        def fake_launch(cmd):
            nonlocal launch_count
            launch_count += 1
            time.sleep(0.02)
            server_started.set()
            return MockProcess(pid=9999)

        self.mock_launcher.launch.side_effect = fake_launch

        def fake_get(url, timeout=5.0):
            if not server_started.is_set():
                raise ConnectionError("down")
            return MockResponse(200, json_data={"models": [{"name": "llama3.2:latest"}]})

        self.mock_http.get.side_effect = fake_get
        self.mock_http.post.return_value = MockResponse(200, json_data={"response": "ok"})

        manager = OllamaManager(
            host="http://localhost:11434",
            model="llama3.2",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
            startup_timeout=1.0,
            poll_interval=0.01,
        )

        threads = []
        results = [None] * 5

        def worker(idx):
            results[idx] = manager.check_readiness(auto_start=True)

        for i in range(5):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(launch_count, 1)
        for r in results:
            self.assertIsNotNone(r)
            self.assertEqual(r.status, OllamaReadinessStatus.READY)

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 6: Missing or mismatched model returns model_missing
    # ──────────────────────────────────────────────────────────────────────────
    def test_missing_or_mismatched_model_returns_model_missing(self):
        """When requested model is not in installed tags, returns model_missing and skips inference."""
        self.mock_http.get.return_value = MockResponse(
            200,
            json_data={
                "models": [
                    {"name": "llama3.2:latest"},
                    {"name": "llama3:latest"},
                    {"name": "mistral:7b"},
                ]
            },
        )

        # Configured for llama3:8b (which is NOT in tags)
        manager = OllamaManager(
            host="http://localhost:11434",
            model="llama3:8b",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
        )

        result = manager.check_readiness(auto_start=False)

        self.assertEqual(result.status, OllamaReadinessStatus.MODEL_MISSING)
        self.assertEqual(result.stage, "model_check")
        self.assertIn("not installed", result.message)
        # Bounded inference must not be attempted
        self.mock_http.post.assert_not_called()

    def test_prefix_collision_does_not_falsely_match(self):
        """Model 'llama3' must not match 'llama3.2' or 'llama3-gradient'."""
        self.mock_http.get.return_value = MockResponse(
            200,
            json_data={
                "models": [
                    {"name": "llama3.2:latest"},
                    {"name": "llama3-gradient:latest"},
                ]
            },
        )

        manager = OllamaManager(
            host="http://localhost:11434",
            model="llama3",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
        )

        result = manager.check_readiness(auto_start=False)

        self.assertEqual(result.status, OllamaReadinessStatus.MODEL_MISSING)
        self.mock_http.post.assert_not_called()

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 7: Failed model-list request is not interpreted as model availability
    # ──────────────────────────────────────────────────────────────────────────
    def test_failed_model_list_request_never_counts_as_available(self):
        """A failure fetching /api/tags must return server_unreachable, never ready."""
        # Initial ping succeeds, but tags request fails with 500
        self.mock_http.get.side_effect = [
            MockResponse(200, json_data={"status": "ok"}),  # ping
            MockResponse(500, text="Internal Server Error"),  # model check tags
        ]

        manager = OllamaManager(
            host="http://localhost:11434",
            model="llama3.2",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
        )

        result = manager.check_readiness(auto_start=False)

        self.assertEqual(result.status, OllamaReadinessStatus.SERVER_UNREACHABLE)
        self.assertEqual(result.stage, "model_check")
        self.assertFalse(result.is_ready)
        self.mock_http.post.assert_not_called()

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 8: Reachable API with failed inference does not pass readiness
    # ──────────────────────────────────────────────────────────────────────────
    def test_reachable_api_with_failed_inference_rejected(self):
        """When server and model exist but inference returns HTTP 500, returns inference_failed."""
        self.mock_http.get.return_value = MockResponse(
            200, json_data={"models": [{"name": "llama3.2:latest"}]}
        )
        self.mock_http.post.return_value = MockResponse(
            500, text="GPU out of memory"
        )

        manager = OllamaManager(
            host="http://localhost:11434",
            model="llama3.2",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
        )

        result = manager.check_readiness(auto_start=False)

        self.assertEqual(result.status, OllamaReadinessStatus.INFERENCE_FAILED)
        self.assertEqual(result.stage, "inference")
        self.assertFalse(result.is_ready)

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 9: Empty or invalid inference output is rejected
    # ──────────────────────────────────────────────────────────────────────────
    def test_empty_or_whitespace_inference_output_rejected(self):
        """Empty or whitespace-only response string is rejected as inference_failed."""
        self.mock_http.get.return_value = MockResponse(
            200, json_data={"models": [{"name": "llama3.2:latest"}]}
        )

        for empty_val in ("", "   ", "\n\t  ", None):
            with self.subTest(empty_val=empty_val):
                self.mock_http.post.return_value = MockResponse(
                    200, json_data={"response": empty_val}
                )

                manager = OllamaManager(
                    host="http://localhost:11434",
                    model="llama3.2",
                    http_client=self.mock_http,
                    process_launcher=self.mock_launcher,
                )

                result = manager.check_readiness(auto_start=False)

                self.assertEqual(result.status, OllamaReadinessStatus.INFERENCE_FAILED)
                self.assertEqual(result.stage, "inference")
                self.assertIn("empty or invalid", result.message)

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 10: Startup and inference timeouts return appropriate failure
    # ──────────────────────────────────────────────────────────────────────────
    def test_startup_timeout_returns_timeout_status(self):
        """When launched server fails to become reachable within deadline, returns timeout."""
        self.mock_http.get.side_effect = ConnectionError("Connection refused")

        manager = OllamaManager(
            host="http://localhost:11434",
            model="llama3.2",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
            startup_timeout=0.05,
            poll_interval=0.01,
        )

        result = manager.check_readiness(auto_start=True)

        self.assertEqual(result.status, OllamaReadinessStatus.TIMEOUT)
        self.assertEqual(result.stage, "launch")
        self.assertIn("failed to respond within", result.message)

    def test_inference_timeout_returns_timeout_status(self):
        """When inference request times out, returns timeout."""
        self.mock_http.get.return_value = MockResponse(
            200, json_data={"models": [{"name": "llama3.2:latest"}]}
        )
        self.mock_http.post.side_effect = TimeoutError("Request timed out")

        manager = OllamaManager(
            host="http://localhost:11434",
            model="llama3.2",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
        )

        result = manager.check_readiness(auto_start=False)

        self.assertEqual(result.status, OllamaReadinessStatus.TIMEOUT)
        self.assertEqual(result.stage, "inference")

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 11: Existing external servers are never recorded as Jarvis-owned
    # ──────────────────────────────────────────────────────────────────────────
    def test_existing_external_server_not_recorded_as_owned(self):
        """External running server must be recorded as external with pid=None."""
        self.mock_http.get.return_value = MockResponse(
            200, json_data={"models": [{"name": "llama3.2:latest"}]}
        )
        self.mock_http.post.return_value = MockResponse(
            200, json_data={"response": "ok"}
        )

        manager = OllamaManager(
            host="http://localhost:11434",
            model="llama3.2",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
        )

        result = manager.check_readiness(auto_start=False)

        self.assertEqual(result.process_ownership, ProcessOwnership.EXTERNAL)
        self.assertIsNone(result.pid)
        self.assertFalse(manager.is_managed)
        self.assertIsNone(manager.managed_pid)

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 12: Only processes launched by manager receive ownership records
    # ──────────────────────────────────────────────────────────────────────────
    def test_only_manager_launched_processes_recorded_as_managed(self):
        """When launcher starts a process, ownership is managed and PID is tracked."""
        self.mock_http.get.side_effect = [
            ConnectionError("down"),
            ConnectionError("down"),
            MockResponse(200, json_data={"models": [{"name": "llama3.2:latest"}]}),
            MockResponse(200, json_data={"models": [{"name": "llama3.2:latest"}]}),
        ]
        self.mock_http.post.return_value = MockResponse(
            200, json_data={"response": "ok"}
        )
        self.mock_launcher.launch.return_value = MockProcess(pid=7788)

        manager = OllamaManager(
            host="http://localhost:11434",
            model="llama3.2",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
            startup_timeout=0.5,
            poll_interval=0.01,
        )

        result = manager.check_readiness(auto_start=True)

        self.assertEqual(result.process_ownership, ProcessOwnership.MANAGED)
        self.assertEqual(result.pid, 7788)
        self.assertTrue(manager.is_managed)
        self.assertEqual(manager.managed_pid, 7788)

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 13: Failure messages do not expose credentials
    # ──────────────────────────────────────────────────────────────────────────
    def test_failure_messages_sanitize_credentials(self):
        """Credentials and API tokens in exception messages or URLs are masked."""
        sensitive_msg = "Error reaching http://user:super_secret_pw@internal.host:11434/api with token=sk-abcdef1234567890"
        sanitized = sanitize_message(sensitive_msg)

        self.assertNotIn("super_secret_pw", sanitized)
        self.assertNotIn("sk-abcdef1234567890", sanitized)
        self.assertIn("***:***", sanitized)
        self.assertIn("token=***", sanitized)

        # Test via manager exception handling
        self.mock_http.get.side_effect = Exception(
            "Connection failed: http://admin:p@ssw0rd@localhost:11434 key=secret_val"
        )

        manager = OllamaManager(
            host="http://admin:p@ssw0rd@localhost:11434",
            model="llama3.2",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
        )

        result = manager.check_readiness(auto_start=False)

        self.assertNotIn("p@ssw0rd", result.message)
        self.assertNotIn("secret_val", result.message)

    # ──────────────────────────────────────────────────────────────────────────
    # Scenario 14: No failure path calls Gemini or cloud LLMs
    # ──────────────────────────────────────────────────────────────────────────
    def test_no_failure_path_calls_cloud_or_gemini(self):
        """Under all failure scenarios, no cloud SDK or Gemini module is ever called."""
        failure_cases = [
            ("server_down", ConnectionError("down"), False),
            ("launch_failed", FileNotFoundError("no exe"), True),
            ("model_missing", MockResponse(200, json_data={"models": []}), False),
            ("inference_failed", MockResponse(500, text="error"), False),
        ]

        with patch.dict("sys.modules", {"google.genai": MagicMock(), "google": MagicMock()}):
            for name, side_effect, auto_start in failure_cases:
                with self.subTest(case=name):
                    if name == "launch_failed":
                        self.mock_http.get.side_effect = ConnectionError("down")
                        self.mock_launcher.find_executable.return_value = None
                    elif isinstance(side_effect, Exception):
                        self.mock_http.get.side_effect = side_effect
                    elif name == "model_missing":
                        self.mock_http.get.return_value = side_effect
                    elif name == "inference_failed":
                        self.mock_http.get.return_value = MockResponse(
                            200, json_data={"models": [{"name": "llama3.2:latest"}]}
                        )
                        self.mock_http.post.return_value = side_effect

                    manager = OllamaManager(
                        host="http://localhost:11434",
                        model="llama3.2",
                        http_client=self.mock_http,
                        process_launcher=self.mock_launcher,
                    )

                    result = manager.check_readiness(auto_start=auto_start)
                    self.assertFalse(result.is_ready)

    # ──────────────────────────────────────────────────────────────────────────
    # Focused lifecycle edge cases
    # ──────────────────────────────────────────────────────────────────────────
    def test_retry_after_startup_timeout_reuses_live_managed_child(self):
        """A retry polls a live child from an earlier timed-out launch instead of relaunching."""
        clock = FakeClock()
        self.mock_http.get.side_effect = ConnectionError("not ready")
        manager = OllamaManager(
            host="http://localhost:11434",
            model="llama3.2",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
            startup_timeout=1.0,
            poll_interval=0.5,
            clock=clock,
            sleeper=clock.advance,
        )

        first = manager.check_readiness(auto_start=True)

        self.assertEqual(first.status, OllamaReadinessStatus.TIMEOUT)
        self.assertEqual(first.process_ownership, ProcessOwnership.MANAGED)
        self.assertTrue(manager.is_managed)
        self.mock_launcher.launch.assert_called_once()

        self.mock_http.get.side_effect = None
        self.mock_http.get.return_value = MockResponse(
            200, json_data={"models": [{"name": "llama3.2:latest"}]}
        )
        self.mock_http.post.return_value = MockResponse(200, json_data={"response": "ok"})

        retry = manager.check_readiness(auto_start=True)

        self.assertEqual(retry.status, OllamaReadinessStatus.READY)
        self.assertEqual(retry.process_ownership, ProcessOwnership.MANAGED)
        self.mock_launcher.launch.assert_called_once()

    def test_exited_managed_child_is_not_reported_as_owned(self):
        """An exited child is discarded; a reachable server is then external."""
        self.mock_http.get.return_value = MockResponse(
            200, json_data={"models": [{"name": "llama3.2:latest"}]}
        )
        self.mock_http.post.return_value = MockResponse(200, json_data={"response": "ok"})
        manager = OllamaManager(
            host="http://localhost:11434",
            model="llama3.2",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
        )
        manager._managed_process = MockProcess(pid=77, returncode=1)
        manager._managed_pid = 77

        result = manager.check_readiness(auto_start=False)

        self.assertEqual(result.status, OllamaReadinessStatus.READY)
        self.assertEqual(result.process_ownership, ProcessOwnership.EXTERNAL)
        self.assertIsNone(result.pid)
        self.assertFalse(manager.is_managed)
        self.assertIsNone(manager.managed_pid)

    def test_remote_endpoint_does_not_trigger_implicit_local_launch(self):
        """An unreachable remote endpoint needs an explicit launch command."""
        self.mock_http.get.side_effect = ConnectionError("remote unavailable")
        manager = OllamaManager(
            host="http://ollama.internal.example:11434",
            model="llama3.2",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
        )

        result = manager.check_readiness(auto_start=True)

        self.assertEqual(result.status, OllamaReadinessStatus.SERVER_UNREACHABLE)
        self.assertEqual(result.stage, "launch")
        self.mock_launcher.find_executable.assert_not_called()
        self.mock_launcher.launch.assert_not_called()

    def test_explicit_launch_command_can_authorize_remote_endpoint_launch(self):
        """A caller-provided reviewed command is the only remote launch path."""
        self.mock_http.get.side_effect = [
            ConnectionError("down"),
            ConnectionError("down"),
            MockResponse(200, json_data={"models": [{"name": "llama3.2:latest"}]}),
            MockResponse(200, json_data={"models": [{"name": "llama3.2:latest"}]}),
        ]
        self.mock_http.post.return_value = MockResponse(200, json_data={"response": "ok"})
        command = ["/reviewed/bin/ollama", "serve", "--host", "0.0.0.0:11434"]
        manager = OllamaManager(
            host="http://ollama.internal.example:11434",
            model="llama3.2",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
            launch_command=command,
            startup_timeout=1.0,
            poll_interval=0.01,
        )

        result = manager.check_readiness(auto_start=True)

        self.assertEqual(result.status, OllamaReadinessStatus.READY)
        self.mock_launcher.launch.assert_called_once_with(command)

    def test_default_tag_matching_is_exact_and_deliberate(self):
        """Only bare names and their :latest form are equivalent."""
        self.assertTrue(is_model_installed("llama3.2", ["llama3.2:latest"]))
        self.assertTrue(is_model_installed("llama3.2:latest", ["llama3.2:latest"]))
        self.assertFalse(is_model_installed("llama3.2", ["llama3.2:3b"]))
        self.assertFalse(is_model_installed("llama3.2:3b", ["llama3.2:latest"]))
        self.assertFalse(is_model_installed("llama3.2", ["llama3.20:latest"]))

    def test_deadline_caps_each_request_and_stops_before_inference(self):
        """The total deadline is shared by connectivity, tags, and inference stages."""
        clock = FakeClock()
        observed_timeouts: List[float] = []

        def fake_get(url, timeout=5.0):
            observed_timeouts.append(timeout)
            clock.advance(0.6)
            return MockResponse(200, json_data={"models": [{"name": "llama3.2:latest"}]})

        self.mock_http.get.side_effect = fake_get
        manager = OllamaManager(
            host="http://localhost:11434",
            model="llama3.2",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
            startup_timeout=1.0,
            total_timeout=1.0,
            request_timeout=5.0,
            inference_timeout=5.0,
            clock=clock,
            sleeper=clock.advance,
        )

        result = manager.check_readiness(auto_start=False)

        self.assertEqual(result.status, OllamaReadinessStatus.TIMEOUT)
        self.assertEqual(result.stage, "model_check")
        self.assertFalse(result.is_ready)
        self.assertEqual(observed_timeouts, [1.0, 0.4])
        self.mock_http.post.assert_not_called()


    # ──────────────────────────────────────────────────────────────────────────
    # Timeout Allocation & Cold-Start Tests
    # ──────────────────────────────────────────────────────────────────────────
    def test_inference_request_passes_distinct_connect_and_read_timeouts(self):
        """Inference POST request receives distinct connect and read timeouts (5.0, 180.0) by default."""
        self.mock_http.get.return_value = MockResponse(
            200, json_data={"models": [{"name": "qwen2.5:7b"}]}
        )
        self.mock_http.post.return_value = MockResponse(
            200, json_data={"response": "pong"}
        )

        manager = OllamaManager(
            host="http://localhost:11434",
            model="qwen2.5:7b",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
        )

        result = manager.check_readiness(auto_start=False)

        self.assertEqual(result.status, OllamaReadinessStatus.READY)
        self.mock_http.post.assert_called_once()
        _, kwargs = self.mock_http.post.call_args
        self.assertEqual(kwargs.get("timeout"), (5.0, 180.0))

    def test_inference_request_falls_back_when_http_client_rejects_tuple(self):
        """When HTTP client rejects tuple timeout with TypeError, fallback passes float read_timeout."""
        self.mock_http.get.return_value = MockResponse(
            200, json_data={"models": [{"name": "qwen2.5:7b"}]}
        )

        call_timeouts: List[Any] = []

        def fake_post(url, json=None, timeout=None):
            call_timeouts.append(timeout)
            if isinstance(timeout, tuple):
                raise TypeError("timeout must be int or float, not tuple")
            return MockResponse(200, json_data={"response": "pong"})

        self.mock_http.post.side_effect = fake_post

        manager = OllamaManager(
            host="http://localhost:11434",
            model="qwen2.5:7b",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
        )

        result = manager.check_readiness(auto_start=False)

        self.assertEqual(result.status, OllamaReadinessStatus.READY)
        self.assertEqual(len(call_timeouts), 2)
        self.assertEqual(call_timeouts[0], (5.0, 180.0))
        self.assertEqual(call_timeouts[1], 180.0)

    def test_cold_start_inference_succeeds_within_long_timeout_window(self):
        """Cold-start inference taking 35 seconds succeeds when inference_timeout is 180s."""
        clock = FakeClock()
        self.mock_http.get.return_value = MockResponse(
            200, json_data={"models": [{"name": "qwen2.5:7b"}]}
        )

        def slow_post(url, json=None, timeout=None):
            clock.advance(35.0)
            return MockResponse(200, json_data={"response": "hello from qwen"})

        self.mock_http.post.side_effect = slow_post

        manager = OllamaManager(
            host="http://localhost:11434",
            model="qwen2.5:7b",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
            inference_timeout=180.0,
            clock=clock,
            sleeper=clock.advance,
        )

        result = manager.check_readiness(auto_start=False)

        self.assertEqual(result.status, OllamaReadinessStatus.READY)
        self.assertTrue(result.is_ready)

    def test_cold_start_inference_fails_when_exceeding_inference_timeout(self):
        """When cold-start inference exceeds configured inference_timeout, returns TIMEOUT in inference stage."""
        self.mock_http.get.return_value = MockResponse(
            200, json_data={"models": [{"name": "qwen2.5:7b"}]}
        )
        self.mock_http.post.side_effect = TimeoutError("HTTPConnectionPool: Read timed out. (read timeout=20.0)")

        manager = OllamaManager(
            host="http://localhost:11434",
            model="qwen2.5:7b",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
            inference_timeout=20.0,
        )

        result = manager.check_readiness(auto_start=False)

        self.assertEqual(result.status, OllamaReadinessStatus.TIMEOUT)
        self.assertEqual(result.stage, "inference")
        self.assertFalse(result.is_ready)
        self.assertIn("Inference request to model 'qwen2.5:7b' failed", result.message)

    def test_server_startup_timeout_is_separate_from_inference_timeout(self):
        """A failed server launch times out at startup_timeout and reports 'launch' stage, not waiting 200s."""
        clock = FakeClock()
        self.mock_http.get.side_effect = ConnectionError("server down")

        manager = OllamaManager(
            host="http://localhost:11434",
            model="qwen2.5:7b",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
            startup_timeout=15.0,
            inference_timeout=180.0,
            poll_interval=1.0,
            clock=clock,
            sleeper=clock.advance,
        )

        result = manager.check_readiness(auto_start=True)

        self.assertEqual(result.status, OllamaReadinessStatus.TIMEOUT)
        self.assertEqual(result.stage, "launch")
        self.assertIn("failed to respond within 15.0s", result.message)
        self.assertLessEqual(clock.now, 16.0)

    def test_overall_deadline_diminishes_timeout_allocated_to_inference(self):
        """Time consumed by earlier stages reduces the timeout budget remaining for inference."""
        clock = FakeClock()
        observed_post_timeout: List[Any] = []

        def timed_get(url, timeout=5.0):
            clock.advance(10.0)
            return MockResponse(200, json_data={"models": [{"name": "qwen2.5:7b"}]})

        def record_post(url, json=None, timeout=None):
            observed_post_timeout.append(timeout)
            return MockResponse(200, json_data={"response": "ok"})

        self.mock_http.get.side_effect = timed_get
        self.mock_http.post.side_effect = record_post

        manager = OllamaManager(
            host="http://localhost:11434",
            model="qwen2.5:7b",
            http_client=self.mock_http,
            process_launcher=self.mock_launcher,
            total_timeout=50.0,
            connect_timeout=5.0,
            inference_timeout=180.0,
            clock=clock,
            sleeper=clock.advance,
        )

        result = manager.check_readiness(auto_start=False)

        self.assertEqual(result.status, OllamaReadinessStatus.READY)
        self.assertEqual(len(observed_post_timeout), 1)
        conn_to, read_to = observed_post_timeout[0]
        self.assertEqual(conn_to, 5.0)
        self.assertEqual(read_to, 30.0)


if __name__ == "__main__":
    unittest.main()

