import time
from app.nodes.loop import execute_single_tool

def test_youtube():
    print("\n--- TEST: Search YouTube ---")
    res = execute_single_tool(
        tool_name="youtube_video",
        args={"action": "play", "query": "Never Gonna Give You Up"}
    )
    print("Search/Play Result:", res["result"][:150] if res["success"] else res)
    assert res["success"]

    # Sleep so we don't spam too fast and maybe the browser has time
    time.sleep(2)

    print("\n--- TEST: Extract video metadata ---")
    res = execute_single_tool(
        tool_name="youtube_video",
        args={"action": "get_info", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    )
    print("Get Info Result:", res["result"][:150] if res["success"] else res)
    assert res["success"]
    assert "Title: Rick Astley - Never Gonna Give You Up (Official Music Video)" in res["result"]

if __name__ == "__main__":
    test_youtube()
    print("\nAll YouTube tests passed successfully!")
