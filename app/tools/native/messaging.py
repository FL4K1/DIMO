import time
import pyautogui
import webbrowser
import logging

logger = logging.getLogger("dimo.messaging")

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.08

def _open_app(app_name: str) -> bool:
    """Opens an app via Windows search."""
    try:
        pyautogui.press("win")
        time.sleep(0.4)
        pyautogui.write(app_name, interval=0.04)
        time.sleep(0.5)
        pyautogui.press("enter")
        time.sleep(2.0)  
        return True
    except Exception as e:
        logger.error(f"[Messaging] Could not open {app_name}: {e}")
        return False

def _send_whatsapp(receiver: str, message: str) -> str:
    """Sends a WhatsApp message via the Windows desktop app."""
    try:
        if not _open_app("WhatsApp"):
            return "Could not open WhatsApp."

        time.sleep(3.5)
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.6)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.write(receiver, interval=0.05)
        time.sleep(1.5) 
        pyautogui.press("enter")
        time.sleep(1.2) 
        pyautogui.write(message, interval=0.04)
        time.sleep(0.3)
        pyautogui.press("enter")

        return f"Message sent to {receiver} via WhatsApp."
    except Exception as e:
        return f"WhatsApp error: {e}"

def _send_instagram(receiver: str, message: str) -> str:
    """Sends an Instagram DM via browser."""
    try:
        webbrowser.open("https://www.instagram.com/direct/new/")
        time.sleep(3.5)
        pyautogui.write(receiver, interval=0.05)
        time.sleep(1.5)
        pyautogui.press("down")
        time.sleep(0.3)
        pyautogui.press("enter")
        time.sleep(0.5)

        for _ in range(3):
            pyautogui.press("tab")
            time.sleep(0.1)
        pyautogui.press("enter")
        time.sleep(1.5)

        pyautogui.write(message, interval=0.04)
        time.sleep(0.2)
        pyautogui.press("enter")

        return f"Message sent to {receiver} via Instagram."
    except Exception as e:
        return f"Instagram error: {e}"

def _send_telegram(receiver: str, message: str) -> str:
    """Sends a Telegram message via Windows desktop app."""
    try:
        if not _open_app("Telegram"):
            return "Could not open Telegram."

        time.sleep(1.5)
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.4)
        pyautogui.write(receiver, interval=0.04)
        time.sleep(1.0)
        pyautogui.press("enter")
        time.sleep(0.8)
        pyautogui.write(message, interval=0.03)
        time.sleep(0.2)
        pyautogui.press("enter")

        return f"Message sent to {receiver} via Telegram."
    except Exception as e:
        return f"Telegram error: {e}"

def _send_generic(platform: str, receiver: str, message: str) -> str:
    """For any other platform not explicitly supported."""
    try:
        if not _open_app(platform):
            return f"Could not open {platform}."

        time.sleep(1.5)
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.4)
        pyautogui.write(receiver, interval=0.04)
        time.sleep(1.0)
        pyautogui.press("enter")
        time.sleep(0.8)
        pyautogui.write(message, interval=0.03)
        time.sleep(0.2)
        pyautogui.press("enter")

        return f"Message sent to {receiver} via {platform}."
    except Exception as e:
        return f"{platform} error: {e}"

def send_message(receiver: str, message_text: str, platform: str) -> dict:
    """
    Main entry point for native DIMO messaging.
    Returns: {success: bool, result: str, error: str | None}
    """
    if not receiver:
        return {"success": False, "result": "", "error": "Missing receiver"}
    if not message_text:
        return {"success": False, "result": "", "error": "Missing message_text"}

    platform = platform.strip().lower()
    logger.info(f"[Messaging] {platform} -> {receiver}: {message_text[:40]}")

    if platform in ["whatsapp", "wp", "wapp"]:
        result = _send_whatsapp(receiver, message_text)
    elif platform in ["instagram", "ig", "insta"]:
        result = _send_instagram(receiver, message_text)
    elif platform in ["telegram", "tg"]:
        result = _send_telegram(receiver, message_text)
    else:
        result = _send_generic(platform, receiver, message_text)

    is_success = "error:" not in result.lower() and "could not open" not in result.lower()
    
    if is_success:
        return {"success": True, "result": result, "error": None}
    else:
        return {"success": False, "result": "", "error": result}
