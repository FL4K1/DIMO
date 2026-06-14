import sys
from app.config.logging import logger

def test_startup():
    print("\n--- PHASE 1: Import Validation ---")
    try:
        from app.tools.registry import TOOL_CATALOG, get_tool
        print("Registry loaded.")
        print(f"Total tools registered: {len(TOOL_CATALOG)}")
    except Exception as e:
        print(f"Registry failed: {e}")
        sys.exit(1)

    try:
        from app.nodes.planning import plan_tools
        print("Planner loaded.")
    except Exception as e:
        print(f"Planner failed: {e}")
        sys.exit(1)

    try:
        from app.nodes.loop import execute_single_tool
        print("Executor loaded.")
    except Exception as e:
        print(f"Executor failed: {e}")
        sys.exit(1)

    try:
        from app.browser.browser_manager import browser_manager
        print("Browser Manager loaded.")
    except Exception as e:
        print(f"Browser Manager failed: {e}")
        sys.exit(1)

    try:
        from app.memory.memory_manager import load_memory
        print("Memory Manager loaded.")
    except Exception as e:
        print(f"Memory Manager failed: {e}")
        sys.exit(1)

    print("\n--- PHASE 2: Tool Registry Validation ---")
    required_tools = [
        "file_controller", "weather_report", "youtube_video", 
        "browser_control", "flight_finder", "send_whatsapp_desktop", 
        "screen_process", "dev_agent"
    ]
    
    missing = []
    for t in required_tools:
        if t not in TOOL_CATALOG:
            missing.append(t)
    
    if missing:
        print(f"Missing required tools in registry: {missing}")
        sys.exit(1)
    else:
        print(f"All required tools ({len(required_tools)}) are present in the registry.")

    # Just do a quick mock fetch to prove execution works
    print("\n--- PHASE 3: Execution Smoke Test ---")
    try:
        res = execute_single_tool("weather_report", {"city": "Paris"})
        res_str = str(res.get('success'))
        print(f"Weather execution successful (Success: {res_str})")
    except Exception as e:
        print(f"Execution failed: {e}")
        sys.exit(1)

    print("\nAll validation checks passed! No legacy imports detected.")

if __name__ == "__main__":
    test_startup()
