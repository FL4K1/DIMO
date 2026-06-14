import time
from app.nodes.loop import execute_single_tool

def test_gui_automation():
    print("\n--- TEST: Open Application ---")
    res = execute_single_tool(
        tool_name="open_app",
        args={"app_name": "notepad"}
    )
    print("OpenApp Result:", res)
    assert res["success"]
    
    # Wait for notepad to fully open
    time.sleep(2)

    print("\n--- TEST: Window Management ---")
    res = execute_single_tool(
        tool_name="computer_control",
        args={"action": "minimize_window", "description": "Notepad"}
    )
    print("Minimize Result:", res)
    assert res["success"]
    
    time.sleep(1)
    
    res = execute_single_tool(
        tool_name="computer_control",
        args={"action": "maximize_window", "description": "Notepad"}
    )
    print("Maximize Result:", res)
    assert res["success"]
    
    time.sleep(1)
    
    res = execute_single_tool(
        tool_name="computer_control",
        args={"action": "focus_window", "description": "Notepad"}
    )
    print("Focus Result:", res)
    assert res["success"]
    
    print("\n--- TEST: GUI Controls (Type, Hotkey) ---")
    time.sleep(1)
    res = execute_single_tool(
        tool_name="computer_control",
        args={"action": "type", "value": "Hello from native DIMO gui service!"}
    )
    print("Type Result:", res)
    assert res["success"]
    
    time.sleep(1)
    res = execute_single_tool(
        tool_name="computer_control",
        args={"action": "hotkey", "value": "ctrl+a"}
    )
    print("Hotkey Result:", res)
    assert res["success"]

    time.sleep(1)
    print("\n--- TEST: Close Application ---")
    res = execute_single_tool(
        tool_name="computer_control",
        args={"action": "close_window", "description": "Notepad"}
    )
    print("Close Result:", res)
    assert res["success"]

    # We skip "click coordinates" because clicking random coordinates might ruin the test environment
    # but the method is mapped and available in `automation.py`

if __name__ == "__main__":
    test_gui_automation()
    print("\nAll GUI automation tests passed successfully!")
