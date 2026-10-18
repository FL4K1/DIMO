"""
Mark-LV Local Text Conversation and Tool-Call Coordinator.

Authoritative local conversation turn coordinator for Mark-LV.
Coordinates typed text turns with an explicitly local Ollama provider:
1. Validates endpoint locality (localhost/loopback only; fails closed on non-local endpoints).
2. Converts supported Mark-LV Gemini-style tool declarations to Ollama JSON schema without losing constraints.
3. Validates model-requested tool names against approved Mark-LV declarations.
4. Validates arguments against declaration schemas before dispatch.
5. Dispatches approved calls through the injected Mark-LV dispatcher.
6. Manages bounded tool round-trips without endless loops or cloud fallback.
7. Preserves Mark-LV confirmation gating and reports predictable, typed results.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, Union
from urllib.parse import urlparse

logger = logging.getLogger("marklv.local_turn_coordinator")

# Mapping from Mark-LV Gemini schema uppercase types to JSON schema lowercase types
_TYPE_MAP: Dict[str, str] = {
    "OBJECT": "object",
    "STRING": "string",
    "INTEGER": "integer",
    "NUMBER": "number",
    "BOOLEAN": "boolean",
    "ARRAY": "array",
    # Accept lowercase inputs as well
    "object": "object",
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
}


class TurnStatus(str, Enum):
    SUCCESS = "success"
    CONFIG_ERROR = "config_error"
    PROVIDER_ERROR = "provider_error"
    VALIDATION_ERROR = "validation_error"
    TOOL_ERROR = "tool_error"
    MAX_ROUNDS_REACHED = "max_rounds_reached"
    TIMEOUT = "timeout"
    CONFIRMATION_PENDING = "confirmation_pending"


@dataclass
class ToolExecutionRecord:
    tool_name: str
    arguments: Dict[str, Any]
    result: str
    round_index: int
    success: bool = True
    error: Optional[str] = None
    call_id: Optional[str] = None


@dataclass
class LocalTurnResult:
    status: TurnStatus
    content: str
    tool_calls: List[ToolExecutionRecord] = field(default_factory=list)
    rounds: int = 0
    updated_history: List[Dict[str, Any]] = field(default_factory=list)
    error_message: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.status == TurnStatus.SUCCESS


class LocalLLMClientProtocol(Protocol):
    """Protocol for local model chat inference."""

    provider: str
    endpoint: str

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: float = 60.0,
    ) -> Dict[str, Any]:
        """
        Execute chat completion.
        Returns: {"content": str, "tool_calls": List[dict]}
        """
        ...


def sanitize_message(msg: str) -> str:
    """Strip credentials, tokens, or URL basic auth from error messages."""
    if not isinstance(msg, str):
        msg = str(msg)
    msg = re.sub(r'(https?://)[^/\s]+@', r'\1***:***@', msg)
    msg = re.sub(r'(?:key|token|secret|password|api[_-]?key)=[\w\-.]+', 'token=***', msg, flags=re.IGNORECASE)
    msg = re.sub(r'Bearer\s+[\w\-.]+', 'Bearer ***', msg, flags=re.IGNORECASE)
    return msg


def is_local_endpoint(url: str) -> bool:
    """
    Verify whether the URL targets a loopback or local host.

    Fails closed on remote hosts, public IPs, or cloud endpoints to ensure
    local inference never silently contacts external servers.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        if parsed.params or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            return False
        hostname = (parsed.hostname or "").lower().strip()
        # ``0.0.0.0`` is a server bind address, never a safe client destination.
        return hostname in ("localhost", "127.0.0.1", "::1")
    except Exception:
        return False


def convert_schema_node(node: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Recursively convert a Mark-LV parameter schema node into standard JSON Schema.

    Fails safely if an unsupported type or constraint cannot be converted
    without weakening its guarantees.
    """
    if not isinstance(node, dict):
        return None, "Schema node must be a dictionary."

    raw_type = node.get("type", "OBJECT")
    if raw_type not in _TYPE_MAP:
        return None, f"Unsupported schema type '{raw_type}'."

    out_type = _TYPE_MAP[raw_type]
    converted: Dict[str, Any] = {"type": out_type}

    allowed_keys = {"type", "description", "enum"}
    if out_type == "object":
        allowed_keys.update({"properties", "required"})
    elif out_type == "array":
        allowed_keys.add("items")
    unsupported = set(node) - allowed_keys
    if unsupported:
        return None, f"Unsupported schema constraint(s): {', '.join(sorted(unsupported))}."

    if "description" in node and isinstance(node["description"], str):
        converted["description"] = node["description"]

    if "enum" in node:
        if not isinstance(node["enum"], list):
            return None, "Schema 'enum' constraint must be a list."
        converted["enum"] = list(node["enum"])

    if out_type == "object":
        properties = node.get("properties")
        if properties is not None:
            if not isinstance(properties, dict):
                return None, "Schema 'properties' must be a dictionary."
            c_props: Dict[str, Any] = {}
            for prop_name, prop_node in properties.items():
                c_prop, err = convert_schema_node(prop_node)
                if err:
                    return None, f"Property '{prop_name}': {err}"
                c_props[prop_name] = c_prop
            converted["properties"] = c_props

        required = node.get("required")
        if required is not None:
            if not isinstance(required, list):
                return None, "Schema 'required' must be a list."
            converted["required"] = list(required)

    elif out_type == "array":
        items = node.get("items")
        if items is None:
            return None, "Array schema must define 'items' specification."
        c_items, err = convert_schema_node(items)
        if err:
            return None, f"Array items: {err}"
        converted["items"] = c_items

    return converted, None


def convert_marklv_to_ollama_tool(decl: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Convert a Mark-LV tool declaration dict into Ollama function tool format.

    Returns:
        (tool_dict, None) on success
        (None, error_message) on rejection / unsupported constraint
    """
    if not isinstance(decl, dict):
        return None, "Declaration must be a dictionary."

    name = decl.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, "Declaration missing or invalid 'name'."

    desc = decl.get("description", "")
    params = decl.get("parameters", {"type": "OBJECT", "properties": {}})

    c_params, err = convert_schema_node(params)
    if err:
        return None, f"Declaration '{name}' has incompatible schema: {err}"

    return {
        "type": "function",
        "function": {
            "name": name.strip(),
            "description": str(desc).strip(),
            "parameters": c_params,
        },
    }, None


def validate_tool_arguments(
    schema_params: Dict[str, Any],
    arguments: Any,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """
    Validate and parse model-supplied tool arguments against parameter schema.

    Returns:
        (is_valid, error_msg, parsed_dict)
    """
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception as e:
            return False, f"Malformed JSON arguments: {e}", {}

    if not isinstance(arguments, dict):
        return False, f"Arguments must parse to a dict, got {type(arguments).__name__}", {}

    # 1. Required parameters check
    required = schema_params.get("required", [])
    if isinstance(required, list):
        for req in required:
            if req not in arguments:
                return False, f"Missing required parameter '{req}'", arguments

    # 2. Type and constraint checks
    properties = schema_params.get("properties", {})
    if isinstance(properties, dict):
        for key, val in arguments.items():
            if key not in properties:
                return False, f"Unexpected parameter '{key}'", arguments

            prop_def = properties[key]
            if not isinstance(prop_def, dict):
                continue

            raw_type = prop_def.get("type", "STRING")
            expected_type = _TYPE_MAP.get(raw_type, raw_type).lower()

            if expected_type == "string" and not isinstance(val, str):
                return False, f"Field '{key}' expected string, got {type(val).__name__}", arguments
            elif expected_type == "integer" and (not isinstance(val, int) or isinstance(val, bool)):
                return False, f"Field '{key}' expected integer, got {type(val).__name__}", arguments
            elif expected_type == "number" and (not isinstance(val, (int, float)) or isinstance(val, bool)):
                return False, f"Field '{key}' expected number, got {type(val).__name__}", arguments
            elif expected_type == "boolean" and not isinstance(val, bool):
                return False, f"Field '{key}' expected boolean, got {type(val).__name__}", arguments
            elif expected_type == "array" and not isinstance(val, list):
                return False, f"Field '{key}' expected list, got {type(val).__name__}", arguments
            elif expected_type == "object" and not isinstance(val, dict):
                return False, f"Field '{key}' expected dict, got {type(val).__name__}", arguments

            if "enum" in prop_def and isinstance(prop_def["enum"], list):
                if val not in prop_def["enum"]:
                    return False, f"Field '{key}' value '{val}' not in allowed enum {prop_def['enum']}", arguments

    return True, None, arguments


class DefaultOllamaChatClient:
    """
    Production client connecting to local Ollama /api/chat.

    Strictly targets local endpoint and never falls back to cloud providers.
    """

    def __init__(self, host: str, model: str, timeout: float = 60.0):
        if not is_local_endpoint(host):
            raise ValueError(f"Endpoint '{sanitize_message(host)}' is not a local host.")
        self._host = host.rstrip("/")
        self._model = model.strip()
        self._timeout = timeout

    @property
    def provider(self) -> str:
        return "ollama"

    @property
    def endpoint(self) -> str:
        return self._host

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        import requests

        endpoint = f"{self._host}/api/chat"
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": 400},
        }
        if tools:
            payload["tools"] = tools

        t = timeout or self._timeout
        resp = requests.post(endpoint, json=payload, timeout=t)
        resp.raise_for_status()
        data = resp.json()
        msg = data.get("message", {})

        return {
            "content": (msg.get("content") or "").strip(),
            "tool_calls": msg.get("tool_calls") or [],
        }


class LocalTurnCoordinator:
    """
    Coordinates local typed-text turns and tool-calling loops for Mark-LV.

    Uses injected dispatcher, declarations, and local chat client.
    Enforces strict locality, bounded rounds, and schema validation.
    """

    def __init__(
        self,
        llm_client: LocalLLMClientProtocol,
        dispatcher: Callable[[str, Dict[str, Any]], Any],
        host: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        max_tool_rounds: int = 3,
        request_timeout: float = 60.0,
    ):
        self._host = host.rstrip("/")
        self._model = model.strip()
        self._llm_client = llm_client
        self._dispatcher = dispatcher
        self._max_tool_rounds = max_tool_rounds
        self._request_timeout = request_timeout

    def _has_verified_local_client(self) -> bool:
        """Require the injected client to identify the exact Ollama route it uses."""
        provider = getattr(self._llm_client, "provider", None)
        endpoint = getattr(self._llm_client, "endpoint", None)
        if not isinstance(provider, str) or provider.lower() != "ollama":
            return False
        if not isinstance(endpoint, str) or not is_local_endpoint(endpoint):
            return False
        return endpoint.rstrip("/") == self._host

    @property
    def host(self) -> str:
        return self._host

    @property
    def model(self) -> str:
        return self._model

    def execute_turn(
        self,
        user_text: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        tool_declarations: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
    ) -> LocalTurnResult:
        """
        Execute one complete user turn through the local model with optional tool calling.

        Args:
            user_text: The user's input text.
            conversation_history: Prior turns as list of message dicts [{"role": ..., "content": ...}].
            tool_declarations: Approved Mark-LV tool declarations (ActionRegistry/PluginRegistry).
            system_prompt: Optional system instructions for the local model.

        Returns:
            LocalTurnResult with status, final content, executed tool calls, and updated history.
        """
        # 1. Enforce strict endpoint locality check
        if not is_local_endpoint(self._host):
            return LocalTurnResult(
                status=TurnStatus.CONFIG_ERROR,
                content="",
                error_message=(
                    f"Selected LLM endpoint '{sanitize_message(self._host)}' is not local. "
                    "Local conversation requires a localhost/loopback address."
                ),
            )

        if not self._has_verified_local_client():
            return LocalTurnResult(
                status=TurnStatus.CONFIG_ERROR,
                content="",
                error_message="Local inference client is not verified for the configured local Ollama endpoint.",
            )

        # 2. Build conversation history
        messages: List[Dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if conversation_history:
            messages.extend(list(conversation_history))

        user_text_clean = str(user_text or "").strip()
        messages.append({"role": "user", "content": user_text_clean})

        # 3. Process approved tool declarations
        approved_map: Dict[str, Dict[str, Any]] = {}
        ollama_tools: List[Dict[str, Any]] = []

        if tool_declarations:
            for decl in tool_declarations:
                if not isinstance(decl, dict) or "name" not in decl:
                    continue
                name = decl["name"]
                c_tool, err = convert_marklv_to_ollama_tool(decl)
                if err:
                    logger.warning("[LocalCoordinator] Skipping tool '%s': %s", name, err)
                    continue
                approved_map[name] = decl
                if c_tool:
                    ollama_tools.append(c_tool)

        executed_tool_records: List[ToolExecutionRecord] = []
        round_idx = 0

        # 4. Bounded tool execution loop
        while round_idx < self._max_tool_rounds:
            round_idx += 1

            # Request inference from local model
            try:
                resp = self._llm_client.chat(
                    messages=messages,
                    tools=ollama_tools if ollama_tools else None,
                    timeout=self._request_timeout,
                )
            except Exception as e:
                is_timeout = "timeout" in type(e).__name__.lower() or "timeout" in str(e).lower()
                status = TurnStatus.TIMEOUT if is_timeout else TurnStatus.PROVIDER_ERROR
                return LocalTurnResult(
                    status=status,
                    content="",
                    tool_calls=executed_tool_records,
                    rounds=round_idx,
                    updated_history=messages,
                    error_message=sanitize_message(f"Local LLM inference failed: {e}"),
                )

            if not isinstance(resp, dict):
                return LocalTurnResult(
                    status=TurnStatus.PROVIDER_ERROR,
                    content="",
                    tool_calls=executed_tool_records,
                    rounds=round_idx,
                    updated_history=messages,
                    error_message="Local model returned invalid response structure.",
                )

            content = (resp.get("content") or "").strip()
            raw_tool_calls = resp.get("tool_calls") or []

            if not isinstance(raw_tool_calls, list):
                return LocalTurnResult(
                    status=TurnStatus.PROVIDER_ERROR,
                    content="",
                    tool_calls=executed_tool_records,
                    rounds=round_idx,
                    updated_history=messages,
                    error_message="Local model returned invalid tool call structure.",
                )

            # If no tool calls requested, we have the final answer!
            if not raw_tool_calls:
                if not content:
                    return LocalTurnResult(
                        status=TurnStatus.PROVIDER_ERROR,
                        content="",
                        tool_calls=executed_tool_records,
                        rounds=round_idx,
                        updated_history=messages,
                        error_message="Local model returned empty response content.",
                    )

                messages.append({"role": "assistant", "content": content})
                return LocalTurnResult(
                    status=TurnStatus.SUCCESS,
                    content=content,
                    tool_calls=executed_tool_records,
                    rounds=round_idx,
                    updated_history=messages,
                )

            # Assistant requested tool call(s)
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": raw_tool_calls,
            })

            # Process each requested tool call
            for tc in raw_tool_calls:
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                call_name = fn.get("name", "") if isinstance(fn, dict) else ""
                call_args = fn.get("arguments", {}) if isinstance(fn, dict) else {}
                call_id = tc.get("id") if isinstance(tc, dict) and isinstance(tc.get("id"), str) else None

                def append_tool_message(message: str) -> None:
                    tool_message: Dict[str, Any] = {"role": "tool", "name": call_name, "content": message}
                    if call_id:
                        tool_message["tool_call_id"] = call_id
                    messages.append(tool_message)

                # A. Verify tool is in approved declarations
                if call_name not in approved_map:
                    err_msg = f"Tool '{call_name}' is not an approved Mark-LV tool."
                    logger.warning("[LocalCoordinator] Rejected unknown tool: %s", call_name)
                    executed_tool_records.append(
                        ToolExecutionRecord(
                            tool_name=call_name,
                            arguments=call_args if isinstance(call_args, dict) else {},
                            result=err_msg,
                            round_index=round_idx,
                            success=False,
                            error=err_msg,
                            call_id=call_id,
                        )
                    )
                    append_tool_message(err_msg)
                    continue

                decl = approved_map[call_name]
                schema_params = decl.get("parameters", {})

                # B. Validate arguments against schema
                is_valid, val_err, parsed_args = validate_tool_arguments(schema_params, call_args)
                if not is_valid:
                    err_msg = f"Invalid arguments for tool '{call_name}': {val_err}"
                    logger.warning("[LocalCoordinator] %s", err_msg)
                    executed_tool_records.append(
                        ToolExecutionRecord(
                            tool_name=call_name,
                            arguments=parsed_args,
                            result=err_msg,
                            round_index=round_idx,
                            success=False,
                            error=val_err,
                            call_id=call_id,
                        )
                    )
                    append_tool_message(err_msg)
                    continue

                # C. Dispatch through injected Mark-LV dispatcher
                try:
                    raw_res = self._dispatcher(call_name, parsed_args)
                    res_str = str(raw_res) if raw_res is not None else "Done."

                    if "[CONFIRMATION_PENDING]" in res_str:
                        executed_tool_records.append(
                            ToolExecutionRecord(
                                tool_name=call_name,
                                arguments=parsed_args,
                                result=res_str,
                                round_index=round_idx,
                                success=False,
                                error="confirmation_pending",
                                call_id=call_id,
                            )
                        )
                        append_tool_message(res_str)
                        return LocalTurnResult(
                            status=TurnStatus.CONFIRMATION_PENDING,
                            content="",
                            tool_calls=executed_tool_records,
                            rounds=round_idx,
                            updated_history=messages,
                            error_message="Action requires user confirmation through Mark-LV.",
                        )

                    # Check if dispatcher signaled failure
                    is_failed = res_str.lower().startswith("tool '") and "failed" in res_str.lower()
                    executed_tool_records.append(
                        ToolExecutionRecord(
                            tool_name=call_name,
                            arguments=parsed_args,
                            result=res_str,
                            round_index=round_idx,
                            success=not is_failed,
                            error=res_str if is_failed else None,
                            call_id=call_id,
                        )
                    )
                    append_tool_message(res_str)

                except Exception as e:
                    err_msg = f"Tool '{call_name}' failed during execution: {e}"
                    logger.error("[LocalCoordinator] %s", err_msg)
                    executed_tool_records.append(
                        ToolExecutionRecord(
                            tool_name=call_name,
                            arguments=parsed_args,
                            result=err_msg,
                            round_index=round_idx,
                            success=False,
                            error=str(e),
                            call_id=call_id,
                        )
                    )
                    append_tool_message(err_msg)

        # Loop exceeded maximum rounds
        return LocalTurnResult(
            status=TurnStatus.MAX_ROUNDS_REACHED,
            content="Tool execution reached maximum allowed rounds.",
            tool_calls=executed_tool_records,
            rounds=round_idx,
            updated_history=messages,
            error_message="Reached maximum allowed tool rounds.",
        )
