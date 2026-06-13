"""Safe DIMO test suite — runs without side effects"""
from app.tools.registry import TOOL_CATALOG
from app.nodes.loop import _resolve_placeholders, validate_tool_args
from app.memory.memory_manager import should_extract_memory
from app.utils.json_parser import extract_json_from_text
from app.actions.mark_bridge import ensure_mark_on_path

print("--- Registry ---")
print(f"Tools: {len(TOOL_CATALOG)}")
assert "compose_message" in TOOL_CATALOG, "compose_message missing!"
assert "send_whatsapp_desktop" in TOOL_CATALOG, "send_whatsapp_desktop missing!"
assert "send_message" not in TOOL_CATALOG, "send_message should be removed!"
print("[OK]")

print("--- Placeholder resolver ---")
r = _resolve_placeholders({"msg": "[result from step 1]"}, {1: "hello!"})
assert r["msg"] == "hello!", r
r2 = _resolve_placeholders({"c": "[step_1_result]"}, {1: "world"})
assert r2["c"] == "world", r2
print("[OK]")

print("--- Validation ---")
ok, _ = validate_tool_args("web_search", {"query": "test"})
assert ok, "web_search with query should be valid"
ok2, _ = validate_tool_args("web_search", {})
assert not ok2, "web_search without query should be invalid"
print("[OK]")

print("--- Memory fast-skip ---")
assert not should_extract_memory("send whatsapp message to Arman", "Sent!"), "WhatsApp send should skip"
assert not should_extract_memory("compose a message for my friend", "Here it is"), "Compose should skip"
assert not should_extract_memory("search for python tutorials", "Results..."), "Search should skip"
assert should_extract_memory("remember this: I prefer dark mode always", "Got it!"), "Explicit signal should pass"
print("[OK]")

print("--- JSON parser ---")
ok, data = extract_json_from_text('{"key": "val"}')
assert ok and data == {"key": "val"}, f"Got {data}"
ok2, _ = extract_json_from_text("some text before {\"a\": 1} after")
assert ok2
print("[OK]")

print("--- Mark bridge ---")
assert ensure_mark_on_path(), "Mark-XXXIX-OR-main should be on path"
print("[OK]")

print()
print(f"=== All safe tests passed ({len(TOOL_CATALOG)} tools registered) ===")
