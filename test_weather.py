from app.nodes.loop import execute_single_tool

def test_weather():
    print("\n--- TEST: Current weather lookup (Auto IP) ---")
    res = execute_single_tool(
        tool_name="weather_report",
        args={"city": ""}
    )
    res_str = res["result"] if res["success"] else str(res)
    print("Auto Weather Result:\n", res_str.encode('ascii', 'ignore').decode())
    assert res["success"]

    print("\n--- TEST: Location-based weather lookup (London) ---")
    res = execute_single_tool(
        tool_name="weather_report",
        args={"city": "London"}
    )
    res_str = res["result"] if res["success"] else str(res)
    print("London Weather Result:\n", res_str.encode('ascii', 'ignore').decode())
    assert res["success"]
    assert "London" in res["result"]

if __name__ == "__main__":
    test_weather()
    print("\nAll Weather tests passed successfully!")
