from app.tools.native.messaging import send_message

def test_messaging():
    # Test invalid inputs
    res_empty = send_message("", "", "whatsapp")
    assert not res_empty["success"]
    
    # We expect these to fail because we are in a test env without the actual apps open,
    # but we want to make sure the dispatch logic routes correctly without crashing
    print("Testing whatsapp dispatch...")
    res_wp = send_message("John", "Hello", "whatsapp")
    print(res_wp)
    
    print("Testing generic dispatch...")
    res_gen = send_message("Jane", "Hello", "signal")
    print(res_gen)

if __name__ == "__main__":
    test_messaging()
    print("Messaging native test complete.")
