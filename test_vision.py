import time
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from app.nodes.loop import execute_single_tool

def create_dummy_image() -> Path:
    img_path = Path("dummy_ocr_test.png")
    img = Image.new('RGB', (400, 200), color=(73, 109, 137))
    d = ImageDraw.Draw(img)
    # Just draw some text
    d.text((10,10), "Hello DIMO!", fill=(255,255,0))
    d.text((10,50), "This is a test image for OCR extraction.", fill=(255,255,255))
    d.text((10,90), "Vision-based analysis is working.", fill=(255,255,255))
    img.save(img_path)
    return img_path

def test_vision():
    print("\n--- TEST A & C: Vision-based UI analysis (Screenshot) ---")
    res = execute_single_tool(
        tool_name="screen_process",
        args={"text": "What do you see on the screen?", "angle": "screen"}
    )
    print("Screen Process Result:", res["result"][:150] if res["success"] else res)
    assert res["success"]

    print("\n--- TEST: Camera capture (graceful failure or success) ---")
    res = execute_single_tool(
        tool_name="screen_process",
        args={"text": "What do you see?", "angle": "camera"}
    )
    print("Camera Process Result:", res["result"][:150] if res["success"] else res)
    # Success or graceful failure "Could not capture camera image" are both fine

    print("\n--- TEST B & D: OCR & Image Understanding (DocumentService) ---")
    img_path = create_dummy_image()
    try:
        # Test OCR
        res = execute_single_tool(
            tool_name="file_processor",
            args={"file_path": str(img_path.absolute()), "action": "ocr"}
        )
        print("OCR Result:", res["result"][:150] if res["success"] else res)
        assert res["success"]
        assert "Hello DIMO!" in res["result"] or "DIMO" in res["result"]

        # Test Analysis
        res = execute_single_tool(
            tool_name="file_processor",
            args={"file_path": str(img_path.absolute()), "action": "analyze"}
        )
        print("Image Analysis Result:", res["result"][:150] if res["success"] else res)
        assert res["success"]

    finally:
        if img_path.exists():
            img_path.unlink()

if __name__ == "__main__":
    test_vision()
    print("\nAll Vision/OCR tests passed successfully!")
