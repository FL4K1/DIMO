from app.services.agents.vision_debugger import VisionDebugger
from pathlib import Path

def test_screenshot():
    def logger(msg):
        print(f"LOG: {msg}")
    
    path = VisionDebugger.take_screenshot(logger)
    assert path is not None
    assert path.exists()
    assert path.suffix == ".png"
    print("Screenshot successfully captured.")
    
    path.unlink()
    print("Test passed: take_screenshot works")

if __name__ == "__main__":
    test_screenshot()
    print("All VisionDebugger tests passed.")
