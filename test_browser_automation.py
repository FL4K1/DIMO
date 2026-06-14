import time
from app.nodes.loop import execute_single_tool

def test_browser_automation():
    print("\n--- TEST 1: Open a webpage ---")
    res = execute_single_tool(
        tool_name="browser_control",
        args={"action": "go_to", "url": "https://example.com"}
    )
    print("GoTo Result:", res)
    assert res["success"]
    assert "example.com" in res["result"]

    time.sleep(1)
    
    print("\n--- TEST 2: Extract visible text ---")
    res = execute_single_tool(
        tool_name="browser_control",
        args={"action": "get_text"}
    )
    print("GetText Result:", res["result"][:100], "...")
    assert res["success"]
    assert "Example Domain" in res["result"]

    print("\n--- TEST 3: Navigate to a second page ---")
    res = execute_single_tool(
        tool_name="browser_control",
        args={"action": "search", "query": "Playwright Python", "engine": "duckduckgo"}
    )
    print("Search Result:", res)
    assert res["success"]
    assert "duckduckgo.com" in res["result"]

    time.sleep(2)

    print("\n--- TEST 4: Fill a simple form (DuckDuckGo search box) ---")
    # Actually we just landed on a duckduckgo search result page, let's go back to duckduckgo.com to fill the form clearly.
    execute_single_tool(tool_name="browser_control", args={"action": "go_to", "url": "https://duckduckgo.com"})
    time.sleep(2)

    # Note: DuckDuckGo search box has an ID of 'searchbox_input' usually, but let's try smart type or fill_form
    res = execute_single_tool(
        tool_name="browser_control",
        args={"action": "smart_type", "description": "search", "text": "Testing DIMO browser fill"}
    )
    print("SmartType Result:", res)
    assert res["success"]

    time.sleep(1)
    
    res = execute_single_tool(
        tool_name="browser_control",
        args={"action": "press", "key": "Enter"}
    )
    print("Press Enter Result:", res)
    assert res["success"]

    time.sleep(2)

    print("\n--- TEST 5: Close Browser ---")
    res = execute_single_tool(
        tool_name="browser_control",
        args={"action": "close"}
    )
    print("Close Result:", res)
    assert res["success"]

if __name__ == "__main__":
    test_browser_automation()
    print("\nAll Browser automation tests passed successfully!")
