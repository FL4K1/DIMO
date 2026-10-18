"""Narrow, allowlisted bridge from Mark-LV actions to selected DIMO features.

This module is deliberately prefixed with an underscore so Mark-LV's action
loader does not expose it as a model tool.  Each public DIMO action must bind a
fixed capability ID from ``CAPABILITIES``; callers cannot choose a DIMO tool by
name or reach DIMO's general tool registry through this adapter.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal


logger = logging.getLogger("marklv.dimo_adapter")

_TYPE_NAMES = {"OBJECT", "STRING", "INTEGER", "NUMBER", "BOOLEAN", "ARRAY"}
_RISK_LEVELS = {"low", "moderate", "high", "critical"}
_NETWORK_REQUIREMENTS = {"none", "optional", "required"}
_SENSITIVITY_LEVELS = {"public", "personal", "sensitive"}
_MODEL_EGRESS = {"none", "local_provider", "cloud_provider", "provider_dependent"}
_CONFIRMATION_MODES = {"none", "marklv_ui"}
_REVERSIBILITY = {"not_applicable", "undo", "partial", "irreversible", "unknown"}
_ERROR_CODES = {
    "adapter_disabled", "capability_unavailable", "dependency_unavailable",
    "invalid_outcome", "internal_error", "capability_failed", "tab_listing_failed",
    "timeout",
}


@dataclass(frozen=True)
class CapabilityOutcome:
    """The typed, adapter-local result from a selected DIMO capability."""

    ok: bool
    text: str
    error_code: str | None = None


@dataclass(frozen=True)
class CapabilitySpec:
    """Immutable policy and callable binding for one reviewed capability."""

    capability_id: str
    public_name: str
    description: str
    parameters: Mapping[str, Any]
    invoke: Callable[[dict[str, Any]], CapabilityOutcome]
    risk: Literal["low", "moderate", "high", "critical"]
    side_effects: tuple[str, ...]
    execution_network: Literal["none", "optional", "required"]
    execution_local_only: bool
    result_sensitivity: Literal["public", "personal", "sensitive"]
    model_egress: Literal["none", "local_provider", "cloud_provider", "provider_dependent"]
    confirmation: Literal["none", "marklv_ui"]
    reversibility: Literal["not_applicable", "undo", "partial", "irreversible", "unknown"]


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    """Copy immutable metadata into the ordinary dict/list API declaration."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _safe_code(code: str | None, fallback: str = "capability_failed") -> str:
    candidate = str(code or fallback).strip().lower()
    return candidate if candidate in _ERROR_CODES else fallback


def _log_capability_id(capability_id: str) -> str:
    """Keep logs to reviewed IDs; direct callers cannot inject log content."""
    return capability_id if capability_id in CAPABILITIES else "unknown"


@contextmanager
def _repository_import_path():
    """Temporarily support direct ``app/marklv/main.py`` launches.

    Root startup already puts the repository on ``sys.path``.  Direct Mark-LV
    launches do not, so retain compatibility only while resolving the lazy DIMO
    import and remove the temporary path immediately afterwards.
    """
    repo_root = str(Path(__file__).resolve().parents[3])
    inserted = False
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
        inserted = True
    try:
        yield
    finally:
        if inserted:
            try:
                sys.path.remove(repo_root)
            except ValueError:
                pass


def _list_dimo_tabs(_parameters: dict[str, Any]) -> CapabilityOutcome:
    """Call only DIMO's read-only tab-listing function, lazily."""
    try:
        with _repository_import_path():
            tabs = importlib.import_module("app.browser.tabs")
        result = tabs.list_open_tabs()
    except ImportError:
        return CapabilityOutcome(False, "", "dependency_unavailable")

    text = str(result or "No open tabs.")
    normalized = text.strip().lower()
    if normalized.startswith("playwright not installed"):
        return CapabilityOutcome(False, "", "dependency_unavailable")
    if normalized.startswith("could not list tabs:"):
        code = "timeout" if "timeout" in normalized or "timed out" in normalized else "tab_listing_failed"
        return CapabilityOutcome(False, "", code)
    # Current list_open_tabs() has no separate timeout return, but recognize a
    # direct legacy timeout string as well so it cannot become model output.
    if normalized.startswith("timed out") or normalized.startswith("timeout"):
        return CapabilityOutcome(False, "", "timeout")
    return CapabilityOutcome(True, text)


_EMPTY_OBJECT_SCHEMA = _freeze({"type": "OBJECT", "properties": {}})

_BROWSER_LIST_TABS = CapabilitySpec(
    capability_id="browser.list_tabs",
    public_name="dimo_browser_list_tabs",
    description=(
        "Lists all currently open browser tabs in the active browser session, "
        "including their 0-based index numbers, page titles, and URLs. "
        "Use this to inspect open web pages before switching or closing tabs."
    ),
    parameters=_EMPTY_OBJECT_SCHEMA,
    invoke=_list_dimo_tabs,
    risk="low",
    side_effects=(),
    execution_network="none",
    execution_local_only=True,
    result_sensitivity="sensitive",
    model_egress="provider_dependent",
    confirmation="none",
    reversibility="not_applicable",
)

# This mapping is intentionally the entire adapter allowlist.  Do not populate
# it from app.tools.registry or accept model-provided capability IDs.
CAPABILITIES: Mapping[str, CapabilitySpec] = MappingProxyType({
    _BROWSER_LIST_TABS.capability_id: _BROWSER_LIST_TABS,
})


def is_enabled() -> bool:
    """Return the adapter-local startup switch, enabled unless explicitly off."""
    return os.getenv("DIMO_MARKLV_ADAPTER_ENABLED", "true").strip().lower() not in {
        "0", "false", "no", "off",
    }


def validate_capability_spec(spec: CapabilitySpec) -> None:
    """Validate static metadata and the deliberately small schema subset.

    Metadata documents policy for review and tests.  It is not an automatic
    confirmation or undo mechanism; a later capability needing either must
    install and exercise the appropriate Mark-LV enforcement path.
    """
    if not isinstance(spec.capability_id, str) or not spec.capability_id:
        raise ValueError("invalid capability ID")
    if not isinstance(spec.public_name, str) or not spec.public_name.startswith("dimo_"):
        raise ValueError("invalid public action name")
    if not isinstance(spec.description, str) or not spec.description.strip():
        raise ValueError("invalid capability description")
    if not callable(spec.invoke):
        raise ValueError("capability invoker is not callable")
    if spec.risk not in _RISK_LEVELS or spec.execution_network not in _NETWORK_REQUIREMENTS:
        raise ValueError("invalid risk or network metadata")
    if spec.result_sensitivity not in _SENSITIVITY_LEVELS or spec.model_egress not in _MODEL_EGRESS:
        raise ValueError("invalid result sensitivity or egress metadata")
    if spec.confirmation not in _CONFIRMATION_MODES or spec.reversibility not in _REVERSIBILITY:
        raise ValueError("invalid confirmation or reversibility metadata")
    if not isinstance(spec.execution_local_only, bool):
        raise ValueError("execution_local_only must be boolean")
    if not isinstance(spec.side_effects, tuple) or not all(isinstance(item, str) for item in spec.side_effects):
        raise ValueError("side_effects must be a tuple of strings")
    _validate_schema(spec.parameters)


def _validate_schema(schema: Mapping[str, Any]) -> None:
    if not isinstance(schema, Mapping):
        raise ValueError("schema must be a mapping")
    allowed = {"type", "properties", "required", "description", "enum", "items"}
    if set(schema).difference(allowed):
        raise ValueError("unsupported schema field")
    schema_type = schema.get("type")
    if schema_type not in _TYPE_NAMES:
        raise ValueError("unsupported schema type")
    properties = schema.get("properties", {})
    required = schema.get("required", ())
    if schema_type == "OBJECT":
        if not isinstance(properties, Mapping) or not isinstance(required, (list, tuple)):
            raise ValueError("invalid object schema")
        if not all(isinstance(name, str) and name in properties for name in required):
            raise ValueError("invalid required property")
        for name, property_schema in properties.items():
            if not isinstance(name, str):
                raise ValueError("invalid property name")
            _validate_schema(property_schema)
    elif "properties" in schema or "required" in schema:
        raise ValueError("properties are only supported on object schemas")
    if "enum" in schema and not isinstance(schema["enum"], (list, tuple)):
        raise ValueError("invalid enum schema")
    if schema_type == "ARRAY":
        if "items" not in schema:
            raise ValueError("array schema requires items")
        _validate_schema(schema["items"])
    elif "items" in schema:
        raise ValueError("items are only supported on array schemas")


def _validate_arguments(schema: Mapping[str, Any], parameters: Any) -> dict[str, Any]:
    if not isinstance(parameters, dict):
        raise ValueError("arguments must be an object")
    properties = schema.get("properties", {})
    unknown = set(parameters).difference(properties)
    if unknown:
        raise ValueError("unexpected arguments")
    for required in schema.get("required", ()):
        if required not in parameters:
            raise ValueError("missing required argument")
    for name, value in parameters.items():
        if not _matches_schema(value, properties[name]):
            raise ValueError("invalid argument type")
    return dict(parameters)


def _matches_schema(value: Any, schema: Mapping[str, Any]) -> bool:
    schema_type = schema["type"]
    matches = {
        "STRING": isinstance(value, str),
        "INTEGER": isinstance(value, int) and not isinstance(value, bool),
        "NUMBER": isinstance(value, (int, float)) and not isinstance(value, bool),
        "BOOLEAN": isinstance(value, bool),
        "ARRAY": isinstance(value, list),
        "OBJECT": isinstance(value, dict),
    }[schema_type]
    if not matches:
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if schema_type == "ARRAY":
        return all(_matches_schema(item, schema["items"]) for item in value)
    if schema_type == "OBJECT":
        try:
            _validate_arguments(schema, value)
        except ValueError:
            return False
    return True


def get_capability(capability_id: str) -> CapabilitySpec | None:
    """Find one reviewed internal ID; this does not consult DIMO's registry."""
    return CAPABILITIES.get(capability_id)


def action_declaration(capability_id: str, handler: Callable[..., str]) -> dict[str, Any] | None:
    """Build the sole model declaration for an enabled reviewed capability."""
    if not is_enabled():
        return None
    spec = get_capability(capability_id)
    if spec is None:
        return None
    validate_capability_spec(spec)
    return {
        "name": spec.public_name,
        "description": spec.description,
        "parameters": _thaw(spec.parameters),
        "handler": handler,
    }


def run_capability(capability_id: str, parameters: Any) -> str:
    """Run a fixed, reviewed capability with validated arguments only."""
    if not is_enabled():
        logger.info("DIMO adapter capability=%s code=adapter_disabled", _log_capability_id(capability_id))
        return "DIMO capability is unavailable [adapter_disabled]."

    spec = get_capability(capability_id)
    if spec is None:
        logger.warning("DIMO adapter capability=%s code=capability_unavailable", _log_capability_id(capability_id))
        return "DIMO capability is unavailable [capability_unavailable]."

    try:
        validate_capability_spec(spec)
        args = _validate_arguments(spec.parameters, parameters)
    except ValueError:
        logger.info("DIMO adapter capability=%s code=invalid_request", _log_capability_id(capability_id))
        return "DIMO capability request was rejected [invalid_request]."

    try:
        outcome = spec.invoke(args)
    except ImportError:
        logger.info("DIMO adapter capability=%s code=dependency_unavailable", _log_capability_id(capability_id))
        return "DIMO capability is unavailable [dependency_unavailable]."
    except Exception:
        logger.error("DIMO adapter capability=%s code=internal_error", _log_capability_id(capability_id))
        return "DIMO capability failed [internal_error]."

    if not isinstance(outcome, CapabilityOutcome):
        logger.error("DIMO adapter capability=%s code=invalid_outcome", _log_capability_id(capability_id))
        return "DIMO capability failed [invalid_outcome]."
    if outcome.ok:
        return str(outcome.text or "Done.")

    code = _safe_code(outcome.error_code)
    logger.info("DIMO adapter capability=%s code=%s", _log_capability_id(capability_id), code)
    return f"DIMO capability failed [{code}]."


for _spec in CAPABILITIES.values():
    validate_capability_spec(_spec)
