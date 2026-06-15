import os
import sys
import traceback
import json

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.tools.registry import TOOL_CATALOG, get_tool

tools_to_test = [
    "browser_control",
    "computer_control",
    "screen_process",
    "youtube_video",
    "flight_finder",
    "send_whatsapp_desktop",
    "file_controller",
    "file_processor",
    "weather_report",
    "dev_agent",
    "code_helper",
    "project_scaffolder"
]

results = {}

def safe_call(tool_name, func, args):
    try:
        if tool_name in ["send_whatsapp_desktop"]:
            # Special tools don't have func in catalog, handled in executor.
            # We can test import of the underlying function
            from app.tools.native.messaging import send_message
            return "Partially Working", "Cannot safely send real message, but import succeeded."
            
        if not func:
            return "Broken", "No function found in registry"
            
        print(f"Testing {tool_name} with args: {args}")
        res = func(**args)
        if isinstance(res, dict) and res.get("success") is False:
            return "Broken", f"Tool returned success=False: {res.get('error', 'unknown error')}"
        return "Working", "Executed successfully"
    except Exception as e:
        err = traceback.format_exc()
        return "Broken", f"Runtime exception: {str(e)}\n{err}"

for tool in tools_to_test:
    print(f"--- Auditing {tool} ---")
    if tool not in TOOL_CATALOG:
        results[tool] = {"status": "Broken", "reason": "Not in TOOL_CATALOG"}
        continue
        
    func = get_tool(tool)
    
    # Try dry run / safe call
    status, reason = "Broken", "Unknown"
    
    if tool == "weather_report":
        status, reason = safe_call(tool, func, {"city": "New York"})
    elif tool == "flight_finder":
        status, reason = safe_call(tool, func, {"origin": "JFK", "destination": "LHR", "date": "2024-12-01"})
    elif tool == "file_controller":
        status, reason = safe_call(tool, func, {"action": "list", "path": "."})
    elif tool == "youtube_video":
        status, reason = safe_call(tool, func, {"action": "trending", "region": "US"})
    elif tool == "code_helper":
        status, reason = safe_call(tool, func, {"action": "explain", "code": "print('hello')", "language": "python"})
    elif tool == "project_scaffolder":
        status, reason = safe_call(tool, func, {"description": "A simple python script"})
    elif tool == "browser_control":
        # Safe to get title if a page is open, or do nothing? Try search maybe, or go_to a safe url
        status, reason = safe_call(tool, func, {"action": "go_to", "url": "https://example.com"})
    elif tool == "computer_control":
        status, reason = safe_call(tool, func, {"action": "move", "x": 100, "y": 100})
    elif tool == "screen_process":
        status, reason = safe_call(tool, func, {"text": "What do you see on my screen?", "angle": "screen"})
    elif tool == "dev_agent":
        # Might be heavy, just do a very simple task
        status, reason = safe_call(tool, func, {"description": "Write a python script that prints hi to desktop", "timeout": 5})
    elif tool == "file_processor":
        status, reason = safe_call(tool, func, {"file_path": "non_existent_file.txt", "action": "explain"})
    elif tool == "send_whatsapp_desktop":
        status, reason = safe_call(tool, func, {})
    else:
        status, reason = safe_call(tool, func, {})
        
    results[tool] = {"status": "Working" if status == "Working" else status, "reason": reason}

print("\n\n--- FINAL RESULTS ---")
print(json.dumps(results, indent=2))
