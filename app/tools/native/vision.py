from app.services.agents.vision_debugger import VisionDebugger
from app.config.logging import logger

def screen_process(
    text: str,
    angle: str = "screen",
) -> dict:
    """
    Natively processes a screen or camera image using the VisionDebugger service.
    """
    try:
        if not text:
            return {"success": False, "result": "", "error": "No text provided for screen analysis."}

        # The VisionDebugger service will return the text response from the model
        result_text = VisionDebugger.analyze_screen(
            description=text,
            angle=angle,
            logger=logger.info
        )

        success = "Could not capture" not in result_text and "analysis failed" not in result_text
        return {"success": success, "result": result_text, "error": None if success else result_text}

    except Exception as e:
        logger.error(f"[Native] screen_process failed: {e}")
        return {"success": False, "result": "", "error": str(e)}