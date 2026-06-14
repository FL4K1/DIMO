"""
app/services/automation/gui_service.py
Native DIMO GUI Automation Service.
Behavioral reference: Mark-XXXIX-OR-main/actions/computer_control.py
"""

import time
import random
import string

from app.config.logging import logger

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False


def _require_pyautogui():
    if not _PYAUTOGUI:
        raise RuntimeError("pyautogui is required. Run: pip install pyautogui")


# ── Random data generators (used for form-filling) ───────────────────────────

_FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Drew", "Quinn",
    "Avery", "Blake", "Cameron", "Dakota", "Emerson", "Finley", "Harper",
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson",
]
_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "proton.me", "mail.com"]


def _random_data(data_type: str) -> str:
    dt = data_type.lower().strip()
    if dt == "first_name":
        return random.choice(_FIRST_NAMES)
    if dt == "last_name":
        return random.choice(_LAST_NAMES)
    if dt == "name":
        return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"
    if dt == "email":
        first = random.choice(_FIRST_NAMES).lower()
        last  = random.choice(_LAST_NAMES).lower()
        num   = random.randint(10, 999)
        return f"{first}.{last}{num}@{random.choice(_DOMAINS)}"
    if dt == "username":
        return f"{random.choice(_FIRST_NAMES).lower()}{random.randint(100, 9999)}"
    if dt == "password":
        chars = string.ascii_letters + string.digits + "!@#$%"
        raw = (
            random.choice(string.ascii_uppercase)
            + random.choice(string.digits)
            + random.choice("!@#$%")
            + "".join(random.choices(chars, k=9))
        )
        return "".join(random.sample(raw, len(raw)))
    if dt == "phone":
        return f"+1{random.randint(200, 999)}{random.randint(1_000_000, 9_999_999)}"
    if dt == "birthday":
        y = random.randint(1980, 2000)
        m = random.randint(1, 12)
        d = random.randint(1, 28)
        return f"{m:02d}/{d:02d}/{y}"
    if dt == "address":
        num = random.randint(100, 9999)
        street = random.choice(["Main St", "Oak Ave", "Park Blvd", "Elm St", "Cedar Ln"])
        return f"{num} {street}"
    if dt == "zip_code":
        return str(random.randint(10000, 99999))
    if dt == "city":
        return random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"])
    return f"random_{data_type}_{random.randint(1000, 9999)}"


class GuiService:
    """Native GUI automation using pyautogui + pyperclip."""

    @classmethod
    def type_text(cls, text: str, interval: float = 0.03) -> str:
        """Type text character by character at the current cursor position."""
        _require_pyautogui()
        time.sleep(0.3)
        pyautogui.typewrite(text, interval=interval)
        return f"Typed: {text[:60]}{'...' if len(text) > 60 else ''}"

    @classmethod
    def smart_type(cls, text: str, clear_first: bool = True) -> str:
        """Clear the field (optional) then type, using clipboard for long text."""
        _require_pyautogui()
        if clear_first:
            cls.clear_field()
            time.sleep(0.1)
        if len(text) > 20 and _PYPERCLIP:
            pyperclip.copy(text)
            time.sleep(0.1)
            pyautogui.hotkey("ctrl", "v")
            return f"Smart-typed (clipboard): {text[:60]}{'...' if len(text) > 60 else ''}"
        pyautogui.typewrite(text, interval=0.04)
        return f"Smart-typed: {text[:60]}{'...' if len(text) > 60 else ''}"

    @classmethod
    def click(cls, x=None, y=None, button: str = "left", clicks: int = 1) -> str:
        """Click at (x, y) or at the current mouse position."""
        _require_pyautogui()
        if x is not None and y is not None:
            pyautogui.click(int(x), int(y), button=button, clicks=clicks)
            return f"{'Double-c' if clicks == 2 else 'C'}licked ({x}, {y}) [{button}]"
        pyautogui.click(button=button, clicks=clicks)
        return f"Clicked at current position [{button}]"

    @classmethod
    def double_click(cls, x=None, y=None) -> str:
        return cls.click(x, y, "left", 2)

    @classmethod
    def right_click(cls, x=None, y=None) -> str:
        return cls.click(x, y, "right", 1)

    @classmethod
    def hotkey(cls, *keys) -> str:
        """Execute a keyboard shortcut (e.g. ctrl+c)."""
        _require_pyautogui()
        pyautogui.hotkey(*keys)
        return f"Hotkey: {'+'.join(str(k) for k in keys)}"

    @classmethod
    def press(cls, key: str) -> str:
        """Press a single key."""
        _require_pyautogui()
        pyautogui.press(key)
        return f"Pressed: {key}"

    @classmethod
    def scroll(cls, direction: str = "down", amount: int = 3) -> str:
        """Scroll the mouse wheel."""
        _require_pyautogui()
        vertical = direction in ("up", "down")
        clicks   = amount if direction in ("up", "right") else -amount
        if vertical:
            pyautogui.scroll(clicks)
        else:
            pyautogui.hscroll(clicks)
        return f"Scrolled {direction} x{amount}"

    @classmethod
    def move(cls, x: int, y: int, duration: float = 0.3) -> str:
        """Move the mouse to (x, y)."""
        _require_pyautogui()
        pyautogui.moveTo(int(x), int(y), duration=duration)
        return f"Mouse moved to ({x}, {y})"

    @classmethod
    def drag(cls, x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> str:
        """Click-drag from (x1,y1) to (x2,y2)."""
        _require_pyautogui()
        pyautogui.moveTo(int(x1), int(y1), duration=0.2)
        pyautogui.dragTo(int(x2), int(y2), duration=duration, button="left")
        return f"Dragged ({x1},{y1}) -> ({x2},{y2})"

    @classmethod
    def clipboard_get(cls) -> str:
        """Read the current clipboard contents."""
        if _PYPERCLIP:
            return pyperclip.paste()
        _require_pyautogui()
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.2)
        return "(copied — pyperclip unavailable for read)"

    @classmethod
    def clipboard_paste(cls, text: str) -> str:
        """Set clipboard to text and paste it."""
        if _PYPERCLIP:
            pyperclip.copy(text)
            time.sleep(0.1)
            _require_pyautogui()
            pyautogui.hotkey("ctrl", "v")
            return f"Pasted: {text[:60]}{'...' if len(text) > 60 else ''}"
        return "pyperclip not available"

    @classmethod
    def screenshot(cls, save_path: str = None) -> str:
        """Take a screenshot and save it."""
        _require_pyautogui()
        from pathlib import Path
        if save_path:
            try:
                p = Path(save_path).expanduser().resolve()
                if p.is_relative_to(Path.home().resolve()):
                    p.parent.mkdir(parents=True, exist_ok=True)
                    pyautogui.screenshot().save(str(p))
                    return f"Screenshot saved: {p}"
            except Exception:
                pass
        fallback = Path.home() / "Desktop" / "dimo_screenshot.png"
        pyautogui.screenshot().save(str(fallback))
        return f"Screenshot saved: {fallback}"

    @classmethod
    def clear_field(cls) -> str:
        """Select all and delete to clear the current input field."""
        _require_pyautogui()
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.1)
        pyautogui.press("delete")
        return "Field cleared"

    @classmethod
    def wait(cls, seconds: float) -> str:
        """Sleep for up to 30 seconds."""
        secs = min(float(seconds), 30.0)
        time.sleep(secs)
        return f"Waited {secs}s"

    @classmethod
    def random_data(cls, data_type: str = "name") -> str:
        """Generate random form data of the given type."""
        result = _random_data(data_type)
        logger.debug("[GuiService] random_data(%s) = %s", data_type, result)
        return result