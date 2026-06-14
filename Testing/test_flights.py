from app.nodes.loop import execute_single_tool

def test_flights():
    print("\n--- TEST: Flight search (JFK to LHR, date: tomorrow) ---")
    res = execute_single_tool(
        tool_name="flight_finder",
        args={"origin": "JFK", "destination": "LHR", "date": "tomorrow", "passengers": 1, "cabin": "economy"}
    )
    print("Flight Search Result:\n", res["result"] if res["success"] else res)
    assert res["success"]

if __name__ == "__main__":
    test_flights()
    print("\nFlight search test passed successfully!")
