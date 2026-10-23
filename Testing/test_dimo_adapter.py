"""Deterministic checks for the narrow Mark-LV-to-DIMO adapter."""
from __future__ import annotations

import importlib
import os
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
MARKLV_ROOT = ROOT / "app" / "marklv"
if str(MARKLV_ROOT) not in sys.path:
    sys.path.insert(0, str(MARKLV_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class DimoAdapterTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"DIMO_MARKLV_ADAPTER_ENABLED": "true"})
        self.env.start()
        import actions._dimo_adapter as adapter
        self.adapter = importlib.reload(adapter)
        import actions.dimo_browser_list_tabs as action
        self.action = importlib.reload(action)

    def tearDown(self):
        self.env.stop()

    def test_only_fixed_capability_is_allowlisted(self):
        self.assertEqual(set(self.adapter.CAPABILITIES), {"browser.list_tabs"})
        self.assertIsNone(self.adapter.get_capability("browser.open_url"))
        self.assertEqual(
            self.adapter.run_capability("browser.open_url", {}),
            "DIMO capability is unavailable [capability_unavailable].",
        )

    def test_declared_name_and_empty_schema_are_preserved(self):
        self.assertEqual(self.action.TOOL["name"], "dimo_browser_list_tabs")
        self.assertEqual(self.action.TOOL["parameters"], {"type": "OBJECT", "properties": {}})
        self.assertEqual(self.action.TOOL["handler"], self.action.dimo_browser_list_tabs)

    def test_action_declaration_passes_marklv_loader_validation(self):
        from core.action_loader import _validate

        record = _validate(self.action, "dimo_browser_list_tabs.py")
        self.assertTrue(record.valid, record.error)
        self.assertEqual(record.name, "dimo_browser_list_tabs")

    def test_unexpected_arguments_are_rejected_before_invocation(self):
        spec = self.adapter.get_capability("browser.list_tabs")
        invoke = Mock()
        checked = replace(spec, invoke=invoke)
        with patch.object(self.adapter, "CAPABILITIES", {"browser.list_tabs": checked}):
            result = self.adapter.run_capability("browser.list_tabs", {"unexpected": "value"})
        self.assertEqual(result, "DIMO capability request was rejected [invalid_request].")
        invoke.assert_not_called()

    def test_wrong_argument_type_is_rejected_before_invocation(self):
        spec = self.adapter.get_capability("browser.list_tabs")
        schema = {"type": "OBJECT", "properties": {"limit": {"type": "INTEGER"}}}
        checked = replace(spec, parameters=schema)
        self.adapter.validate_capability_spec(checked)
        invoke = Mock()
        checked = replace(checked, invoke=invoke)
        with patch.object(self.adapter, "CAPABILITIES", {"browser.list_tabs": checked}):
            result = self.adapter.run_capability("browser.list_tabs", {"limit": "one"})
        self.assertEqual(result, "DIMO capability request was rejected [invalid_request].")
        invoke.assert_not_called()

    def test_unsupported_schema_is_rejected(self):
        spec = self.adapter.get_capability("browser.list_tabs")
        unsupported = replace(spec, parameters={"type": "OBJECT", "properties": {}, "format": "x"})
        with self.assertRaisesRegex(ValueError, "unsupported schema field"):
            self.adapter.validate_capability_spec(unsupported)

    def test_existing_tab_output_is_preserved(self):
        spec = self.adapter.get_capability("browser.list_tabs")
        expected = "0. Example — https://example.test"
        checked = replace(spec, invoke=lambda _args: self.adapter.CapabilityOutcome(True, expected))
        with patch.object(self.adapter, "CAPABILITIES", {"browser.list_tabs": checked}):
            self.assertEqual(self.action.dimo_browser_list_tabs({}), expected)

    def test_legacy_tab_results_preserve_success_and_sanitize_errors(self):
        cases = [
            ("0. Example — https://example.test", True, None),
            ("No open tabs.", True, None),
            ("playwright not installed", False, "dependency_unavailable"),
            ("Could not list tabs: secret token in exception", False, "tab_listing_failed"),
            ("Could not list tabs: TimeoutError secret details", False, "timeout"),
            ("Timed out while listing tabs: secret details", False, "timeout"),
        ]
        for legacy_result, ok, code in cases:
            fake_tabs = SimpleNamespace(list_open_tabs=lambda value=legacy_result: value)
            with self.subTest(legacy_result=legacy_result), patch.object(
                self.adapter.importlib, "import_module", return_value=fake_tabs
            ):
                outcome = self.adapter._list_dimo_tabs({})
            self.assertEqual(outcome.ok, ok)
            self.assertEqual(outcome.error_code, code)
            if ok:
                self.assertEqual(outcome.text, legacy_result)
            else:
                self.assertEqual(outcome.text, "")

    def test_legacy_error_details_do_not_reach_action_result(self):
        secret = "private-url-and-token"
        fake_tabs = SimpleNamespace(list_open_tabs=lambda: f"Could not list tabs: {secret}")
        with patch.object(self.adapter.importlib, "import_module", return_value=fake_tabs):
            result = self.adapter.run_capability("browser.list_tabs", {})
        self.assertEqual(result, "DIMO capability failed [tab_listing_failed].")
        self.assertNotIn(secret, result)

    def test_failures_and_exceptions_are_sanitized(self):
        spec = self.adapter.get_capability("browser.list_tabs")
        secret = "secret-token-and-traceback"
        failure = replace(spec, invoke=lambda _args: self.adapter.CapabilityOutcome(False, secret, "dependency_unavailable"))
        with patch.object(self.adapter, "CAPABILITIES", {"browser.list_tabs": failure}):
            result = self.adapter.run_capability("browser.list_tabs", {})
        self.assertEqual(result, "DIMO capability failed [dependency_unavailable].")
        self.assertNotIn(secret, result)
        exploding = replace(spec, invoke=lambda _args: (_ for _ in ()).throw(RuntimeError(secret)))
        with patch.object(self.adapter, "CAPABILITIES", {"browser.list_tabs": exploding}):
            result = self.adapter.run_capability("browser.list_tabs", {})
        self.assertEqual(result, "DIMO capability failed [internal_error].")
        self.assertNotIn(secret, result)

    def test_metadata_is_validated_but_not_an_automatic_safety_gate(self):
        spec = self.adapter.get_capability("browser.list_tabs")
        self.adapter.validate_capability_spec(replace(spec, risk="critical", confirmation="none"))
        with self.assertRaisesRegex(ValueError, "invalid confirmation"):
            self.adapter.validate_capability_spec(replace(spec, confirmation="automatic"))

    def test_disabled_mode_omits_declaration_and_blocks_direct_invocation(self):
        with patch.dict(os.environ, {"DIMO_MARKLV_ADAPTER_ENABLED": "false"}):
            self.assertIsNone(self.adapter.action_declaration("browser.list_tabs", self.action.dimo_browser_list_tabs))
            self.assertEqual(
                self.action.dimo_browser_list_tabs({}),
                "DIMO capability is unavailable [adapter_disabled].",
            )
            disabled_action = importlib.reload(self.action)
            self.assertIsNone(disabled_action.TOOL)

    def test_no_dimo_catalog_is_imported_or_exposed(self):
        self.assertNotIn("app.tools.registry", sys.modules)
        self.assertFalse(hasattr(self.adapter, "TOOL_CATALOG"))
        self.assertFalse(hasattr(self.adapter, "dimo_tool"))


if __name__ == "__main__":
    unittest.main()
