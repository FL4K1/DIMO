"""
Quick sanity check for DIMO tool fixes.
Run: .venv\Scripts\python.exe test_fixes.py
"""

print("=" * 60)
print("DIMO Fix Verification")
print("=" * 60)

# ── 1. System tools ───────────────────────────────────────────
print("\n[1] Loading system tools...")
try:
    from app.tools.system_tools import SYSTEM_TOOL_CATALOG, WIN32_AVAILABLE
    print(f"    OK — {len(SYSTEM_TOOL_CATALOG)} tools loaded")
    print(f"    win32gui available: {WIN32_AVAILABLE}")
except Exception as e:
    print(f"    FAIL: {e}")

# ── 2. Browser tools ──────────────────────────────────────────
print("\n[2] Loading browser tools...")
try:
    from app.tools.browser_tools import BROWSER_TOOL_CATALOG
    print(f"    OK — {len(BROWSER_TOOL_CATALOG)} tools loaded")
except Exception as e:
    print(f"    FAIL: {e}")

# ── 3. New tools present ──────────────────────────────────────
print("\n[3] Checking new tools exist...")
new_tools = {
    "youtube_music_play": SYSTEM_TOOL_CATALOG,
    "focus_window":       SYSTEM_TOOL_CATALOG,
    "youtube_search":     BROWSER_TOOL_CATALOG,
}
all_ok = True
for tool_name, catalog in new_tools.items():
    status = "OK" if tool_name in catalog else "MISSING"
    if status == "MISSING":
        all_ok = False
    print(f"    {tool_name}: {status}")

# ── 4. Brave in APP_MAP ───────────────────────────────────────
print("\n[4] Checking Brave in APP_MAP...")
try:
    from app.tools.system_tools import APP_MAP
    brave_ok = "brave" in APP_MAP
    print(f"    brave: {'OK' if brave_ok else 'MISSING'}")
    if brave_ok:
        from app.tools.system_tools import _find_brave
        path = _find_brave()
        print(f"    brave path: {path}")
except Exception as e:
    print(f"    FAIL: {e}")

# ── 5. JSON parser robustness ─────────────────────────────────
print("\n[5] JSON parser tests...")
try:
    from app.nodes.action_agent import _parse_tool_calls

    tests = [
        ('[{"tool": "open_app", "args": {"name": "Notepad"}}]',
         "clean array"),
        ('Sure! {"tool": "media_play_pause", "args": {}}',
         "stray text + object"),
        ('```json\n[{"tool": "volume_set", "args": {"level": 50}}]\n```',
         "code-fenced"),
        ('{"tool_calls": [{"tool": "open_app", "args": {"name": "Brave"}}]}',
         "tool_calls wrapper"),
    ]

    for raw, label in tests:
        result = _parse_tool_calls(raw)
        status = "OK" if result else "FAIL (empty)"
        print(f"    {label}: {status} -> {result}")

except Exception as e:
    print(f"    FAIL: {e}")

# ── 6. Action keywords regex ──────────────────────────────────
print("\n[6] Action keyword routing tests...")
try:
    from main import is_system_action

    phrases = [
        ("open notepad and write hello",        True),
        ("play any weeknd song",                True),
        ("open brave",                          True),
        ("chat with gemini about gold",         True),
        ("search for lofi on youtube",          True),
        ("set volume to 50",                    True),
        ("type hello in notepad",               True),
        ("youtube music play shape of you",     True),
        ("what is the capital of france",       False),
        ("tell me a joke",                      False),
    ]

    for phrase, expected in phrases:
        result = is_system_action(phrase)
        status = "OK" if result == expected else "WRONG"
        marker = "  " if status == "OK" else "!!"
        print(f"    {marker} [{status}] '{phrase}' -> Tier1={result}")

except Exception as e:
    print(f"    FAIL: {e}")

print("\n" + "=" * 60)
print("Done. Fix any FAIL/MISSING items before running main.py")
print("=" * 60)
