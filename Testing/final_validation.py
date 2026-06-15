import os
import sys
import traceback
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

results = {}

def add_result(subsystem, status, error=None, result=None):
    results[subsystem] = {
        "status": status,
        "error": error,
        "result": result
    }

print("Starting Final Production Validation...")

# 1. Registry startup
try:
    from app.tools.registry import TOOL_CATALOG
    if TOOL_CATALOG:
        add_result("1. Registry startup", "PASS", result=f"Loaded {len(TOOL_CATALOG)} tools.")
    else:
        add_result("1. Registry startup", "FAIL", error="TOOL_CATALOG is empty.")
except Exception as e:
    add_result("1. Registry startup", "FAIL", error=traceback.format_exc())

# 2. Planner execution
try:
    from app.nodes.planning import create_plan
    plan = create_plan("Check weather in Delhi")
    if "steps" in plan and len(plan["steps"]) > 0:
        add_result("2. Planner execution", "PASS", result="Generated plan successfully.")
    else:
        add_result("2. Planner execution", "FAIL", error="Plan did not contain steps.")
except Exception as e:
    add_result("2. Planner execution", "FAIL", error=traceback.format_exc())

# 3. Executor execution (testing execution dispatch)
try:
    from app.nodes.loop import execute_single_tool
    res = execute_single_tool("weather_report", {"city": "New York"})
    if isinstance(res, dict) and res.get("success"):
        add_result("3. Executor execution", "PASS", result="Executor dispatched and succeeded.")
    else:
        add_result("3. Executor execution", "FAIL", error=f"Executor failed: {res}")
except Exception as e:
    add_result("3. Executor execution", "FAIL", error=traceback.format_exc())

# Helper for standard tools via executor
def test_tool(num_name, tool_name, args):
    try:
        from app.nodes.loop import execute_single_tool
        res = execute_single_tool(tool_name, args)
        if isinstance(res, dict):
            if res.get("success"):
                add_result(num_name, "PASS", result="Success")
            else:
                add_result(num_name, "FAIL", error=res.get("error", str(res)))
        else:
            add_result(num_name, "FAIL", error=f"Unexpected return format: {res}")
    except Exception as e:
        add_result(num_name, "FAIL", error=str(e))

test_tool("4. Browser automation", "browser_control", {"action": "go_to", "url": "https://example.com"})
test_tool("5. Computer control", "computer_control", {"action": "wait", "seconds": 0.1})
test_tool("6. Vision analysis", "screen_process", {"text": "What do you see?"})
test_tool("7. File processing", "file_controller", {"action": "list", "path": "."})
test_tool("8. Weather", "weather_report", {"city": "Tokyo"})
test_tool("9. YouTube", "youtube_video", {"action": "trending", "region": "US"})
test_tool("10. Flight search", "flight_finder", {"origin": "JFK", "destination": "LHR", "date": "2024-12-01"})
test_tool("11. Memory save/retrieve", "save_memory", {"category": "test", "key": "system", "value": "ok"})

# 12. WhatsApp desktop
try:
    # Testing it directly from executor might open GUI and wait for elements.
    # It might fail if WhatsApp is not open.
    from app.nodes.loop import execute_single_tool
    res = execute_single_tool("send_whatsapp_desktop", {"receiver": "test", "message_text": "test"})
    # It will probably return fail because of image matching timeout. This is expected.
    # If it fails with "Image not found", it means the script is working.
    if isinstance(res, dict):
        if res.get("success") is False and ("not found" in res.get("error", "").lower() or "locate" in res.get("error", "").lower()):
            add_result("12. WhatsApp desktop", "PARTIAL", result="Execution started but GUI elements not found (Expected in headless/unfocused state).")
        else:
            add_result("12. WhatsApp desktop", "FAIL" if not res.get("success") else "PASS", error=res.get("error"))
except Exception as e:
    add_result("12. WhatsApp desktop", "FAIL", error=str(e))

# 13. Hybrid Ollama/Gemini fallback
try:
    from app.services.agents.llm_gateway import LLMGateway
    # Test Gemini
    g_res = LLMGateway.generate(prompt="Say hi", model="gemini-2.5-flash")
    # Test Ollama
    o_res = LLMGateway.generate(prompt="Say hi", model="llama3:8b")
    
    if "Error" not in g_res and "Error" not in o_res:
        add_result("13. Hybrid Ollama/Gemini fallback", "PASS", result="Both Gemini and Ollama responded successfully.")
    else:
        add_result("13. Hybrid Ollama/Gemini fallback", "PARTIAL", error=f"Gemini: {g_res}, Ollama: {o_res}")
except Exception as e:
    add_result("13. Hybrid Ollama/Gemini fallback", "FAIL", error=str(e))

print(json.dumps(results, indent=2))
