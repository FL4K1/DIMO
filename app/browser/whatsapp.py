"""
whatsapp.py — WhatsApp Web tools for DIMO.

Tools:
    send_whatsapp_message(contact, message)   → Send a message to a WhatsApp contact
    read_last_messages(contact, count)         → Read recent messages from a chat

First-run behavior:
    WhatsApp Web requires QR code scan on first use.
    This module detects the QR screen and returns a helpful message:
        "WhatsApp Web needs to be set up. Please scan the QR code in the 
         browser window, then try again."
    After the first scan, the persistent Chromium profile stores the session
    and future runs work without re-scanning.

Session persistence:
    Stored at CHROMIUM_PROFILE_DIR (~/.dimo/chromium_profile).
    Survives DIMO restarts indefinitely until WhatsApp logs out the session.

Selector strategy:
    WhatsApp Web uses data-testid attributes extensively — these are far more
    stable than class names which change with every deploy. We always prefer
    data-testid selectors over class-based ones.
"""

import logging
import time
from app.browser.browser_manager import browser_manager, PLAYWRIGHT_AVAILABLE
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger("dimo")

_WA_URL = "https://web.whatsapp.com"

# How long to wait for WhatsApp Web to fully load after navigation (ms)
_WA_LOAD_TIMEOUT = 30_000
# How long to wait for a specific element (ms)
_ELEM_TIMEOUT = 10_000


def _ensure_whatsapp_ready(page) -> tuple[bool, str]:
    """
    Navigate to WhatsApp Web and check if the user is logged in.

    Returns:
        (is_ready: bool, message: str)
        - (True, "")                     — logged in, ready to use
        - (False, "scan QR code...")     — QR screen shown, not logged in
        - (False, "error message")       — unexpected error
    """
    if not page.url.startswith(_WA_URL):
        logger.info("[whatsapp] Navigating to WhatsApp Web")
        page.goto(_WA_URL, wait_until="domcontentloaded", timeout=_WA_LOAD_TIMEOUT)

    # Wait for either the chat list (logged in) or the QR canvas (not logged in)
    try:
        page.wait_for_selector(
            "[data-testid='chat-list'], canvas[aria-label*='QR'], [data-ref]",
            timeout=_WA_LOAD_TIMEOUT,
        )
    except PlaywrightTimeoutError:
        return False, "WhatsApp Web is taking too long to load. Check your internet connection."

    # Check for QR code (multiple selectors for different WA versions)
    qr_selectors = [
        "canvas[aria-label*='QR']",
        "[data-ref]",                   # QR data attribute
        "div[data-testid='qrcode']",
        "[aria-label*='QR code']",
    ]
    for sel in qr_selectors:
        try:
            qr_el = page.query_selector(sel)
            if qr_el and qr_el.is_visible():
                return (
                    False,
                    "WhatsApp Web needs to be set up. Please scan the QR code in the "
                    "Chromium browser window, then try your request again. "
                    "This is only needed once — the session will be saved."
                )
        except Exception:
            continue

    # Check for chat list (logged in)
    chat_list_selectors = [
        "[data-testid='chat-list']",
        "[aria-label='Chat list']",
        "#pane-side",
    ]
    for sel in chat_list_selectors:
        try:
            el = page.query_selector(sel)
            if el:
                logger.info("[whatsapp] Logged in — chat list found")
                return True, ""
        except Exception:
            continue

    return False, "WhatsApp Web state unknown — could not detect login or QR screen."


def _search_and_open_contact(page, contact: str) -> tuple[bool, str]:
    """
    Search for a contact by name and open their chat.

    Returns:
        (success: bool, message: str)
    """
    # Open search box
    search_selectors = [
        "[data-testid='chat-list-search']",
        "[aria-label='Search input textbox']",
        "[aria-label*='Search']",
        "div[contenteditable='true'][data-tab='3']",
    ]

    search_box = None
    for sel in search_selectors:
        try:
            el = page.wait_for_selector(sel, timeout=_ELEM_TIMEOUT, state="visible")
            if el:
                search_box = el
                break
        except Exception:
            continue

    if not search_box:
        return False, "Could not find the WhatsApp search box."

    # Click and type the contact name
    search_box.click()
    time.sleep(0.3)
    search_box.fill("")        # clear any existing text
    search_box.type(contact, delay=50)
    time.sleep(1.5)            # wait for search results

    # Click the first result
    result_selectors = [
        "[data-testid='cell-frame-container']",
        "[data-testid='list-item-title']",
        "div[role='listitem']",
        "._21S-L",             # class fallback (may break on WA updates)
    ]
    for sel in result_selectors:
        try:
            results = page.query_selector_all(sel)
            if results:
                results[0].click()
                time.sleep(1)
                logger.info(f"[whatsapp] Opened chat: '{contact}'")
                return True, ""
        except Exception:
            continue

    return False, f"No WhatsApp contact found matching '{contact}'."


def send_whatsapp_message(contact: str, message: str) -> str:
    """
    Send a WhatsApp message to a contact by name.

    Flow:
    1. Navigate to web.whatsapp.com
    2. Check login status (return QR prompt if needed)
    3. Search for the contact
    4. Click their chat
    5. Type and send the message

    Args:
        contact: Contact name as it appears in WhatsApp (partial match works).
        message: Message text to send.

    Returns:
        "Message sent to {contact}" or descriptive error string.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed. Run: pip install playwright && playwright install chromium"

    try:
        page = browser_manager.get_page()
        logger.info(f"[whatsapp] Sending to '{contact}': '{message[:50]}...'")

        # Step 1: Ensure logged in
        ready, err_msg = _ensure_whatsapp_ready(page)
        if not ready:
            return err_msg

        # Step 2: Search and open the contact
        found, err_msg = _search_and_open_contact(page, contact)
        if not found:
            return err_msg

        # Step 3: Find the message input box
        input_selectors = [
            "[data-testid='conversation-compose-box-input']",
            "[aria-label='Type a message']",
            "div[contenteditable='true'][data-tab='10']",
            "footer div[contenteditable='true']",
        ]
        msg_input = None
        for sel in input_selectors:
            try:
                el = page.wait_for_selector(sel, timeout=_ELEM_TIMEOUT, state="visible")
                if el:
                    msg_input = el
                    break
            except Exception:
                continue

        if not msg_input:
            return f"Found chat with '{contact}' but could not locate the message input box."

        # Step 4: Type the message
        msg_input.click()
        time.sleep(0.2)
        msg_input.fill("")       # clear any leftover text
        msg_input.type(message, delay=30)
        time.sleep(0.3)

        # Step 5: Send (Enter key or send button)
        try:
            send_btn_selectors = [
                "[data-testid='send']",
                "[aria-label='Send']",
                "button[aria-label='Send']",
            ]
            sent = False
            for sel in send_btn_selectors:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click()
                        sent = True
                        break
                except Exception:
                    continue

            if not sent:
                msg_input.press("Enter")

        except Exception:
            msg_input.press("Enter")

        time.sleep(0.5)
        logger.info(f"[whatsapp] Message sent to '{contact}'")
        return f"Message sent to {contact}: \"{message}\""

    except PlaywrightTimeoutError as e:
        logger.error(f"[whatsapp] Timeout: {e}")
        return f"WhatsApp timed out while trying to message '{contact}'."
    except Exception as e:
        logger.error(f"[whatsapp] send_whatsapp_message failed: {e}")
        return f"Could not send WhatsApp message: {e}"


def read_last_messages(contact: str, count: int = 5) -> str:
    """
    Read the most recent messages from a WhatsApp chat.

    Args:
        contact: Contact name to open.
        count:   Number of recent messages to return (default 5, max 20).

    Returns:
        Formatted string of messages, or error string.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed"

    count = min(max(1, count), 20)

    try:
        page = browser_manager.get_page()
        logger.info(f"[whatsapp] Reading {count} messages from '{contact}'")

        # Ensure logged in
        ready, err_msg = _ensure_whatsapp_ready(page)
        if not ready:
            return err_msg

        # Open contact chat
        found, err_msg = _search_and_open_contact(page, contact)
        if not found:
            return err_msg

        time.sleep(1.5)   # wait for messages to load

        # Scrape message bubbles
        messages = page.evaluate(f"""
            () => {{
                const msgs = [];
                // Incoming messages
                const incoming = document.querySelectorAll(
                    '[data-testid="msg-container"] .copyable-text'
                );
                const all = document.querySelectorAll(
                    '[data-testid="msg-container"]'
                );
                for (const container of all) {{
                    if (msgs.length >= {count}) break;
                    const textEl = container.querySelector('.copyable-text, ._21Ahp');
                    const meta = container.querySelector('[data-pre-plain-text]');
                    const text = textEl ? textEl.innerText.trim() : null;
                    const sender = meta ? meta.getAttribute('data-pre-plain-text') : '';
                    if (text) msgs.push({{ sender: sender || '', text }});
                }}
                // Return last N
                return msgs.slice(-{count});
            }}
        """)

        if not messages:
            return f"Could not read messages from '{contact}'. The chat may be empty or messages failed to load."

        lines = []
        for m in messages:
            # data-pre-plain-text format: "[HH:MM, DD/MM/YYYY] Name: "
            sender_raw = m.get("sender", "").strip().rstrip(": ")
            sender = sender_raw.split("] ")[-1] if "] " in sender_raw else sender_raw or "Unknown"
            lines.append(f"{sender}: {m['text']}")

        result = "\n".join(lines)
        logger.info(f"[whatsapp] Read {len(messages)} messages from '{contact}'")
        return f"Last {len(messages)} messages from {contact}:\n\n{result}"

    except Exception as e:
        logger.error(f"[whatsapp] read_last_messages failed: {e}")
        return f"Could not read messages from '{contact}': {e}"


# ── Tool catalog entries ───────────────────────────────────────────────────────
WHATSAPP_CATALOG = {
    "send_whatsapp_message": {
        "name": "send_whatsapp_message",
        "description": (
            "THE ONLY tool for sending WhatsApp messages. ALWAYS use this for ANY WhatsApp request. "
            "Opens WhatsApp Web in the browser, finds the contact, and sends the message reliably. "
            "NEVER use send_message for WhatsApp — use this instead. "
            "The contact name should match how it appears in WhatsApp (partial name is okay). "
            "Example: send_whatsapp_message(contact='Mom', message='I will be late today')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "contact": {
                    "type": "string",
                    "description": "Contact name or partial name as in WhatsApp",
                },
                "message": {
                    "type": "string",
                    "description": "Message text to send",
                },
            },
            "required": ["contact", "message"],
        },
        "function": send_whatsapp_message,
    },
    "read_last_messages": {
        "name": "read_last_messages",
        "description": (
            "Read the most recent WhatsApp messages from a contact. "
            "Returns the last N messages from the chat."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "contact": {
                    "type": "string",
                    "description": "Contact name to read messages from",
                },
                "count": {
                    "type": "number",
                    "description": "Number of recent messages to return (default 5, max 20)",
                },
            },
            "required": ["contact"],
        },
        "function": read_last_messages,
    },
}


# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("=== whatsapp.py test ===")
    contact = input("Enter contact name to test: ").strip()
    message = "DIMO test message — ignore"

    try:
        print(send_whatsapp_message(contact, message))
        print(read_last_messages(contact, count=3))
    finally:
        browser_manager.shutdown()
