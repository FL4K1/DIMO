"""
Unit tests for Mark-LV Local Text Conversation and Tool-Call Coordinator.

Deterministic tests using mock LLM clients and mock Mark-LV dispatchers.
No real network, Ollama server, Gemini API, or hardware devices are used.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from app.marklv.core.local_turn_coordinator import (
    LocalTurnCoordinator,
    LocalTurnResult,
    TurnStatus,
    convert_marklv_to_ollama_tool,
    is_local_endpoint,
    validate_tool_arguments,
)


OPEN_APP_DECL = {
    "name": "open_app",
    "description": "Opens an application on the computer.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "app_name": {
                "type": "STRING",
                "description": "Name of application",
            }
        },
        "required": ["app_name"],
    },
}

WEB_SEARCH_DECL = {
    "name": "web_search",
    "description": "Performs a web search.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "Search query",
            },
            "num_results": {
                "type": "INTEGER",
                "description": "Max results",
            },
        },
        "required": ["query"],
    },
}

COMPUTER_SETTINGS_DECL = {
    "name": "computer_settings",
    "description": "System settings and power control.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Action name",
            }
        },
        "required": ["action"],
    },
}


class MockLocalLLMClient:
    """Mock local LLM client returning scripted responses in sequence."""

    def __init__(
        self,
        responses: Optional[List[Any]] = None,
        provider: str = "ollama",
        endpoint: str = "http://localhost:11434",
    ):
        self.responses = list(responses or [])
        self.call_history: List[Dict[str, Any]] = []
        self.provider = provider
        self.endpoint = endpoint

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: float = 60.0,
    ) -> Dict[str, Any]:
        self.call_history.append({
            "messages": [dict(m) for m in messages],
            "tools": tools,
            "timeout": timeout,
        })
        if not self.responses:
            return {"content": "Fallback answer.", "tool_calls": []}
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TestLocalTurnCoordinator(unittest.TestCase):

    def setUp(self):
        self.mock_dispatcher = MagicMock()
        self.mock_dispatcher.return_value = "Done."

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Normal typed request returns final answer without tools
    # ──────────────────────────────────────────────────────────────────────────
    def test_normal_typed_request_returns_final_answer_without_tools(self):
        """A simple question returns model answer with zero tool calls."""
        client = MockLocalLLMClient([
            {"content": "Quantum computing uses qubits.", "tool_calls": []}
        ])

        coordinator = LocalTurnCoordinator(
            llm_client=client,
            dispatcher=self.mock_dispatcher,
        )

        result = coordinator.execute_turn(
            user_text="What is quantum computing?",
            tool_declarations=[OPEN_APP_DECL],
        )

        self.assertEqual(result.status, TurnStatus.SUCCESS)
        self.assertTrue(result.is_success)
        self.assertEqual(result.content, "Quantum computing uses qubits.")
        self.assertEqual(len(result.tool_calls), 0)
        self.assertEqual(result.rounds, 1)
        self.mock_dispatcher.assert_not_called()

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Valid tool call is dispatched through injected Mark-LV dispatcher
    # ──────────────────────────────────────────────────────────────────────────
    def test_valid_tool_call_dispatched_through_marklv_dispatcher(self):
        """When model requests open_app, dispatcher is called with exact args."""
        client = MockLocalLLMClient([
            {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "open_app",
                            "arguments": {"app_name": "Chrome"},
                        }
                    }
                ],
            },
            {"content": "I have opened Chrome for you.", "tool_calls": []},
        ])
        self.mock_dispatcher.return_value = "Opened Chrome."

        coordinator = LocalTurnCoordinator(
            llm_client=client,
            dispatcher=self.mock_dispatcher,
        )

        result = coordinator.execute_turn(
            user_text="Open Chrome",
            tool_declarations=[OPEN_APP_DECL],
        )

        self.assertEqual(result.status, TurnStatus.SUCCESS)
        self.assertEqual(result.content, "I have opened Chrome for you.")
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].tool_name, "open_app")
        self.assertEqual(result.tool_calls[0].arguments, {"app_name": "Chrome"})
        self.assertTrue(result.tool_calls[0].success)
        self.mock_dispatcher.assert_called_once_with("open_app", {"app_name": "Chrome"})

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Tool result is returned to model in expected follow-up request
    # ──────────────────────────────────────────────────────────────────────────
    def test_tool_result_returned_to_model_in_follow_up_request(self):
        """The follow-up chat call must contain the tool role message with result."""
        client = MockLocalLLMClient([
            {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "open_app", "arguments": {"app_name": "Spotify"}}}
                ],
            },
            {"content": "Spotify is now open.", "tool_calls": []},
        ])
        self.mock_dispatcher.return_value = "Opened Spotify."

        coordinator = LocalTurnCoordinator(
            llm_client=client,
            dispatcher=self.mock_dispatcher,
        )

        coordinator.execute_turn("Launch spotify", tool_declarations=[OPEN_APP_DECL])

        self.assertEqual(len(client.call_history), 2)
        followup_messages = client.call_history[1]["messages"]
        tool_msg = [m for m in followup_messages if m.get("role") == "tool"]
        self.assertEqual(len(tool_msg), 1)
        self.assertEqual(tool_msg[0]["name"], "open_app")
        self.assertEqual(tool_msg[0]["content"], "Opened Spotify.")

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Final answer comes from local model after tool result
    # ──────────────────────────────────────────────────────────────────────────
    def test_final_answer_comes_from_local_model_after_tool(self):
        """Verify the coordinator returns the local model's second generation."""
        expected_final = "All set, Spotify launched."
        client = MockLocalLLMClient([
            {
                "content": "One second...",
                "tool_calls": [{"function": {"name": "open_app", "arguments": {"app_name": "Spotify"}}}],
            },
            {"content": expected_final, "tool_calls": []},
        ])
        self.mock_dispatcher.return_value = "Opened Spotify."

        coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)
        result = coordinator.execute_turn("Open spotify", tool_declarations=[OPEN_APP_DECL])

        self.assertEqual(result.content, expected_final)
        self.assertEqual(result.rounds, 2)

    # ──────────────────────────────────────────────────────────────────────────
    # 5. Unknown tool name is never dispatched
    # ──────────────────────────────────────────────────────────────────────────
    def test_unknown_tool_name_never_dispatched(self):
        """A model attempting to call an undeclared tool is rejected before dispatcher."""
        client = MockLocalLLMClient([
            {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "arbitrary_shell_command", "arguments": {"cmd": "whoami"}}}
                ],
            },
            {"content": "I cannot execute that command.", "tool_calls": []},
        ])

        coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)
        result = coordinator.execute_turn("Run whoami", tool_declarations=[OPEN_APP_DECL])

        self.mock_dispatcher.assert_not_called()
        self.assertEqual(len(result.tool_calls), 1)
        self.assertFalse(result.tool_calls[0].success)
        self.assertIn("not an approved Mark-LV tool", result.tool_calls[0].error)

    # ──────────────────────────────────────────────────────────────────────────
    # 6. Malformed JSON arguments are never dispatched
    # ──────────────────────────────────────────────────────────────────────────
    def test_malformed_json_arguments_never_dispatched(self):
        """When arguments string has malformed JSON, dispatcher is never called."""
        client = MockLocalLLMClient([
            {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "open_app", "arguments": "{'invalid_json': true"}}
                ],
            },
            {"content": "Failed to parse arguments.", "tool_calls": []},
        ])

        coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)
        result = coordinator.execute_turn("Open app", tool_declarations=[OPEN_APP_DECL])

        self.mock_dispatcher.assert_not_called()
        self.assertEqual(len(result.tool_calls), 1)
        self.assertFalse(result.tool_calls[0].success)
        self.assertIn("Malformed JSON", result.tool_calls[0].error)

    # ──────────────────────────────────────────────────────────────────────────
    # 7. Invalid argument objects are rejected according to schema
    # ──────────────────────────────────────────────────────────────────────────
    def test_invalid_argument_objects_rejected_by_schema(self):
        """Type mismatches (e.g. integer when string expected) are caught and rejected."""
        client = MockLocalLLMClient([
            {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "open_app", "arguments": {"app_name": 12345}}}
                ],
            },
            {"content": "Argument type error.", "tool_calls": []},
        ])

        coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)
        result = coordinator.execute_turn("Open app", tool_declarations=[OPEN_APP_DECL])

        self.mock_dispatcher.assert_not_called()
        self.assertFalse(result.tool_calls[0].success)
        self.assertIn("expected string", result.tool_calls[0].error)

    def test_missing_required_arguments_rejected(self):
        """Missing required arguments are rejected before dispatch."""
        client = MockLocalLLMClient([
            {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "open_app", "arguments": {}}}
                ],
            },
            {"content": "Missing parameter.", "tool_calls": []},
        ])

        coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)
        result = coordinator.execute_turn("Open app", tool_declarations=[OPEN_APP_DECL])

        self.mock_dispatcher.assert_not_called()
        self.assertFalse(result.tool_calls[0].success)
        self.assertIn("Missing required parameter", result.tool_calls[0].error)

    # ──────────────────────────────────────────────────────────────────────────
    # 8. Unsupported tool schemas do not silently lose constraints
    # ──────────────────────────────────────────────────────────────────────────
    def test_unsupported_tool_schemas_do_not_silently_lose_constraints(self):
        """A tool with an unsupported schema type is safely omitted rather than weakened."""
        unsupported_decl = {
            "name": "unsupported_tool",
            "description": "Invalid tool.",
            "parameters": {
                "type": "CUSTOM_UNSUPPORTED_TYPE",
                "properties": {},
            },
        }

        c_tool, err = convert_marklv_to_ollama_tool(unsupported_decl)
        self.assertIsNone(c_tool)
        self.assertIn("Unsupported schema type", err)

        client = MockLocalLLMClient([{"content": "No tools available.", "tool_calls": []}])
        coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)

        coordinator.execute_turn("Test", tool_declarations=[unsupported_decl])

        sent_tools = client.call_history[0]["tools"]
        self.assertIsNone(sent_tools)

    # ──────────────────────────────────────────────────────────────────────────
    # 9. Provider failure does not invoke a cloud provider
    # ──────────────────────────────────────────────────────────────────────────
    def test_provider_failure_does_not_invoke_cloud(self):
        """When local LLM raises connection error, no cloud or Gemini module is invoked."""
        client = MockLocalLLMClient([ConnectionError("Ollama offline")])

        with patch.dict("sys.modules", {"google.genai": MagicMock(), "google": MagicMock()}):
            coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)
            result = coordinator.execute_turn("Hello")

            self.assertEqual(result.status, TurnStatus.PROVIDER_ERROR)
            self.assertFalse(result.is_success)
            self.assertIn("Ollama offline", result.error_message)

    # ──────────────────────────────────────────────────────────────────────────
    # 10. Invalid configuration for local endpoint fails closed
    # ──────────────────────────────────────────────────────────────────────────
    def test_invalid_configuration_for_local_endpoint_fails_closed(self):
        """Non-localhost endpoints fail closed with CONFIG_ERROR before sending requests."""
        client = MockLocalLLMClient([{"content": "Should not be called", "tool_calls": []}])

        for remote_url in (
            "https://api.openai.com",
            "http://192.168.1.100:11434",
            "http://external-server.com:11434",
        ):
            with self.subTest(url=remote_url):
                coordinator = LocalTurnCoordinator(
                    llm_client=client,
                    dispatcher=self.mock_dispatcher,
                    host=remote_url,
                )

                result = coordinator.execute_turn("Hello")

                self.assertEqual(result.status, TurnStatus.CONFIG_ERROR)
                self.assertFalse(result.is_success)
                self.assertIn("not local", result.error_message)
                self.assertEqual(len(client.call_history), 0)

    # ──────────────────────────────────────────────────────────────────────────
    # 11. Inference error does not lead to a false success response
    # ──────────────────────────────────────────────────────────────────────────
    def test_inference_error_does_not_lead_to_false_success(self):
        """RuntimeError or HTTP error in inference returns TurnStatus.PROVIDER_ERROR."""
        client = MockLocalLLMClient([RuntimeError("CUDA error: out of memory")])

        coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)
        result = coordinator.execute_turn("Compute this")

        self.assertEqual(result.status, TurnStatus.PROVIDER_ERROR)
        self.assertFalse(result.is_success)
        self.assertEqual(result.content, "")

    # ──────────────────────────────────────────────────────────────────────────
    # 12. Failed tool execution is not reported as successful
    # ──────────────────────────────────────────────────────────────────────────
    def test_failed_tool_execution_not_reported_as_successful(self):
        """When dispatcher signals tool failure, tool record records success=False."""
        client = MockLocalLLMClient([
            {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "open_app", "arguments": {"app_name": "NonExistentApp"}}}
                ],
            },
            {"content": "Could not find that application.", "tool_calls": []},
        ])
        self.mock_dispatcher.return_value = "Tool 'open_app' failed: Application not installed."

        coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)
        result = coordinator.execute_turn("Open xyz", tool_declarations=[OPEN_APP_DECL])

        self.assertEqual(len(result.tool_calls), 1)
        self.assertFalse(result.tool_calls[0].success)
        self.assertIn("failed", result.tool_calls[0].result.lower())

    # ──────────────────────────────────────────────────────────────────────────
    # 13. Tool-call round limit prevents endless loops
    # ──────────────────────────────────────────────────────────────────────────
    def test_tool_call_round_limit_prevents_endless_loops(self):
        """Model perpetually requesting tools halts at max_tool_rounds."""
        repeated_tc = {
            "content": "",
            "tool_calls": [{"function": {"name": "open_app", "arguments": {"app_name": "Chrome"}}}],
        }
        # Provide more responses than max_tool_rounds
        client = MockLocalLLMClient([repeated_tc, repeated_tc, repeated_tc, repeated_tc])

        coordinator = LocalTurnCoordinator(
            llm_client=client,
            dispatcher=self.mock_dispatcher,
            max_tool_rounds=3,
        )

        result = coordinator.execute_turn("Loop please", tool_declarations=[OPEN_APP_DECL])

        self.assertEqual(result.status, TurnStatus.MAX_ROUNDS_REACHED)
        self.assertEqual(result.rounds, 3)
        self.assertEqual(self.mock_dispatcher.call_count, 3)

    # ──────────────────────────────────────────────────────────────────────────
    # 14. Multiple tool calls preserve relationship between calls and results
    # ──────────────────────────────────────────────────────────────────────────
    def test_multiple_tool_calls_preserve_relationships(self):
        """Multiple tool calls in a single assistant turn are each dispatched and recorded in order."""
        client = MockLocalLLMClient([
            {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "open_app", "arguments": {"app_name": "Calculator"}}},
                    {"function": {"name": "web_search", "arguments": {"query": "weather"}}},
                ],
            },
            {"content": "Opened calculator and searched the weather.", "tool_calls": []},
        ])

        def dispatcher_side_effect(name, args):
            if name == "open_app":
                return "Opened Calculator."
            elif name == "web_search":
                return "Sunny 72F."
            return "Done."

        self.mock_dispatcher.side_effect = dispatcher_side_effect

        coordinator = LocalTurnCoordinator(
            llm_client=client,
            dispatcher=self.mock_dispatcher,
        )

        result = coordinator.execute_turn(
            "Open calc and search weather",
            tool_declarations=[OPEN_APP_DECL, WEB_SEARCH_DECL],
        )

        self.assertEqual(len(result.tool_calls), 2)
        self.assertEqual(result.tool_calls[0].tool_name, "open_app")
        self.assertEqual(result.tool_calls[0].result, "Opened Calculator.")
        self.assertEqual(result.tool_calls[1].tool_name, "web_search")
        self.assertEqual(result.tool_calls[1].result, "Sunny 72F.")

        # Check that follow-up messages contains both tool results in order
        followup_msgs = client.call_history[1]["messages"]
        tool_msgs = [m for m in followup_msgs if m.get("role") == "tool"]
        self.assertEqual(len(tool_msgs), 2)
        self.assertEqual(tool_msgs[0]["name"], "open_app")
        self.assertEqual(tool_msgs[0]["content"], "Opened Calculator.")
        self.assertEqual(tool_msgs[1]["name"], "web_search")
        self.assertEqual(tool_msgs[1]["content"], "Sunny 72F.")

    # ──────────────────────────────────────────────────────────────────────────
    # 15. Final model failure does not cause side-effecting tool to run again
    # ──────────────────────────────────────────────────────────────────────────
    def test_final_model_failure_does_not_rerun_tool(self):
        """If tool succeeds but follow-up LLM fails, the tool is never re-executed."""
        client = MockLocalLLMClient([
            {
                "content": "",
                "tool_calls": [{"function": {"name": "open_app", "arguments": {"app_name": "Terminal"}}}],
            },
            ConnectionError("Server dropped after tool"),
        ])
        self.mock_dispatcher.return_value = "Opened Terminal."

        coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)
        result = coordinator.execute_turn("Open terminal", tool_declarations=[OPEN_APP_DECL])

        self.assertEqual(result.status, TurnStatus.PROVIDER_ERROR)
        self.assertEqual(self.mock_dispatcher.call_count, 1)

    # ──────────────────────────────────────────────────────────────────────────
    # 16. Existing confirmation remains responsibility of Mark-LV dispatcher
    # ──────────────────────────────────────────────────────────────────────────
    def test_confirmation_pending_stops_follow_up_inference(self):
        """Mark-LV confirmation stays pending; the coordinator must not ask the model to retry it."""
        confirm_pending_str = (
            "[CONFIRMATION_PENDING] I have put a confirmation on screen for: Computer Restart. "
            "Say ONE short sentence telling them to confirm on the HUD."
        )
        client = MockLocalLLMClient([
            {
                "content": "",
                "tool_calls": [{"function": {"name": "computer_settings", "arguments": {"action": "restart"}}}],
            },
            {"content": "This response must not be requested.", "tool_calls": []},
        ])
        self.mock_dispatcher.return_value = confirm_pending_str

        coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)
        result = coordinator.execute_turn(
            "Restart PC",
            tool_declarations=[COMPUTER_SETTINGS_DECL],
        )

        self.assertEqual(result.status, TurnStatus.CONFIRMATION_PENDING)
        self.assertEqual(len(result.tool_calls), 1)
        self.assertFalse(result.tool_calls[0].success)
        self.assertIn("[CONFIRMATION_PENDING]", result.tool_calls[0].result)
        self.assertEqual(len(client.call_history), 1)

    # ──────────────────────────────────────────────────────────────────────────
    # 17. Conversation history is handled consistently across follow-up requests
    # ──────────────────────────────────────────────────────────────────────────
    def test_conversation_history_handled_consistently(self):
        """Caller-supplied prior turns are preserved and prepended in the call history."""
        prior_history = [
            {"role": "user", "content": "My name is Alice."},
            {"role": "assistant", "content": "Nice to meet you Alice."},
        ]
        client = MockLocalLLMClient([
            {"content": "Your name is Alice.", "tool_calls": []}
        ])

        coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)
        result = coordinator.execute_turn(
            "What is my name?",
            conversation_history=prior_history,
        )

        self.assertEqual(result.status, TurnStatus.SUCCESS)
        history_sent = client.call_history[0]["messages"]
        self.assertEqual(history_sent[0], {"role": "user", "content": "My name is Alice."})
        self.assertEqual(history_sent[1], {"role": "assistant", "content": "Nice to meet you Alice."})
        self.assertEqual(history_sent[2], {"role": "user", "content": "What is my name?"})

    # ──────────────────────────────────────────────────────────────────────────
    # 18. Empty responses, malformed output, and timeouts produce safe structured errors
    # ──────────────────────────────────────────────────────────────────────────
    def test_empty_response_produces_provider_error(self):
        """Empty string output with no tool calls returns PROVIDER_ERROR."""
        client = MockLocalLLMClient([{"content": "   ", "tool_calls": []}])

        coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)
        result = coordinator.execute_turn("Ping")

        self.assertEqual(result.status, TurnStatus.PROVIDER_ERROR)
        self.assertFalse(result.is_success)
        self.assertIn("empty response content", result.error_message)

    def test_timeout_produces_timeout_status(self):
        """Timeout exception from client returns TurnStatus.TIMEOUT."""
        client = MockLocalLLMClient([TimeoutError("Connection timed out")])

        coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)
        result = coordinator.execute_turn("Slow query")

        self.assertEqual(result.status, TurnStatus.TIMEOUT)
        self.assertFalse(result.is_success)
        self.assertIn("timed out", result.error_message.lower())

    # ──────────────────────────────────────────────────────────────────────────
    # Focused safety and compatibility edge cases
    # ──────────────────────────────────────────────────────────────────────────
    def test_pending_confirmation_skips_remaining_calls_in_same_response(self):
        """A confirmation-gated call halts dispatch before any later call can run."""
        pending = "[CONFIRMATION_PENDING] Confirm shutdown in Mark-LV."
        client = MockLocalLLMClient([{
            "content": "",
            "tool_calls": [
                {"id": "pending-1", "function": {"name": "computer_settings", "arguments": {"action": "restart"}}},
                {"id": "must-not-run", "function": {"name": "web_search", "arguments": {"query": "secrets"}}},
            ],
        }])
        self.mock_dispatcher.return_value = pending
        coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)

        result = coordinator.execute_turn(
            "Restart then search", tool_declarations=[COMPUTER_SETTINGS_DECL, WEB_SEARCH_DECL]
        )

        self.assertEqual(result.status, TurnStatus.CONFIRMATION_PENDING)
        self.mock_dispatcher.assert_called_once_with("computer_settings", {"action": "restart"})
        self.assertEqual(len(client.call_history), 1)
        self.assertEqual(result.tool_calls[0].call_id, "pending-1")

    def test_client_provider_and_endpoint_must_match_verified_ollama_route(self):
        """A local URL alone cannot authorize an OpenAI-compatible or remote client."""
        cases = [
            ("openai", "http://localhost:11434"),
            ("ollama", "https://api.example.test"),
            ("ollama", "http://localhost:9999"),
        ]
        for provider, endpoint in cases:
            with self.subTest(provider=provider, endpoint=endpoint):
                client = MockLocalLLMClient(
                    [{"content": "must not run", "tool_calls": []}], provider=provider, endpoint=endpoint
                )
                coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)

                result = coordinator.execute_turn("Hello")

                self.assertEqual(result.status, TurnStatus.CONFIG_ERROR)
                self.assertEqual(client.call_history, [])

    def test_client_without_route_identity_fails_closed(self):
        """An injected client must identify its provider and endpoint before it is called."""
        client = MockLocalLLMClient([{"content": "must not run", "tool_calls": []}])
        del client.provider
        coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)

        result = coordinator.execute_turn("Hello")

        self.assertEqual(result.status, TurnStatus.CONFIG_ERROR)
        self.assertEqual(client.call_history, [])

    def test_local_endpoint_accepts_only_unambiguous_loopback_urls(self):
        """Wildcard, credentials, paths, and external addresses are not local destinations."""
        for url in ("http://localhost:11434", "https://127.0.0.1", "http://[::1]:11434"):
            with self.subTest(url=url):
                self.assertTrue(is_local_endpoint(url))
        for url in (
            "http://0.0.0.0:11434",
            "http://localhost:password@127.0.0.1:11434",
            "http://localhost:11434/api/chat",
            "http://192.168.0.2:11434",
            "http://[::2]:11434",
            "localhost:11434",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_local_endpoint(url))

    def test_unexpected_arguments_are_rejected_before_dispatch(self):
        """Arguments outside a declaration's schema cannot reach Mark-LV dispatch."""
        client = MockLocalLLMClient([
            {"content": "", "tool_calls": [{"function": {"name": "open_app", "arguments": {"app_name": "Chrome", "shell": "cmd"}}}]},
            {"content": "Rejected invalid arguments.", "tool_calls": []},
        ])
        coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)

        result = coordinator.execute_turn("Open Chrome", tool_declarations=[OPEN_APP_DECL])

        self.mock_dispatcher.assert_not_called()
        self.assertIn("Unexpected parameter 'shell'", result.tool_calls[0].error)

    def test_unsupported_schema_constraint_is_not_sent_to_model(self):
        """A constraint the adapter cannot preserve is rejected rather than silently dropped."""
        constrained = {
            "name": "limited_tool",
            "description": "Has an unsupported bound.",
            "parameters": {"type": "OBJECT", "properties": {"n": {"type": "INTEGER", "minimum": 1}}},
        }
        converted, error = convert_marklv_to_ollama_tool(constrained)

        self.assertIsNone(converted)
        self.assertIn("Unsupported schema constraint", error)

    def test_tool_result_uses_original_call_identifier_when_present(self):
        """Provider call IDs are preserved on tool result messages for correlation."""
        client = MockLocalLLMClient([
            {"content": "", "tool_calls": [{"id": "call-42", "function": {"name": "open_app", "arguments": {"app_name": "Calculator"}}}]},
            {"content": "Done.", "tool_calls": []},
        ])
        coordinator = LocalTurnCoordinator(llm_client=client, dispatcher=self.mock_dispatcher)

        result = coordinator.execute_turn("Open calculator", tool_declarations=[OPEN_APP_DECL])

        self.assertEqual(result.status, TurnStatus.SUCCESS)
        self.assertEqual(result.tool_calls[0].call_id, "call-42")
        tool_message = [m for m in client.call_history[1]["messages"] if m.get("role") == "tool"][0]
        self.assertEqual(tool_message["tool_call_id"], "call-42")


if __name__ == "__main__":
    unittest.main()
