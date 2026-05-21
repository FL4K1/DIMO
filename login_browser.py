# -*- coding: utf-8 -*-
"""
login_browser.py — One-time login helper for DIMO browser sessions.

Run this script ONCE for each service you want DIMO to use.
It opens a Chromium window and keeps it open until you press Enter.
After logging in, your session is saved permanently to the profile.

Usage:
    python login_browser.py youtube       # Log into YouTube Music
    python login_browser.py whatsapp      # Scan WhatsApp QR code
    python login_browser.py gemini        # Log into Gemini
    python login_browser.py chatgpt       # Log into ChatGPT
    python login_browser.py all           # Do all of them one by one

After running this once per service, DIMO will never ask you to log in again.
"""

import sys
import time
from app.browser.browser_manager import browser_manager

SERVICES = {
    "youtube":  "https://accounts.google.com/ServiceLogin?service=youtube&continue=https://music.youtube.com",
    "whatsapp": "https://web.whatsapp.com",
    "gemini":   "https://gemini.google.com",
    "chatgpt":  "https://chatgpt.com",
}


def login_to(service: str):
    url = SERVICES[service]
    print(f"\n{'='*60}")
    print(f"  Opening {service.upper()} — {url}")
    print(f"{'='*60}")

    page = browser_manager.get_page(url)

    print(f"\n  [OK] Chromium is open at: {url}")
    print(f"  >>  Please log in / scan QR in the browser window.")
    print(f"  >>  When you are DONE and fully logged in, come back here.")
    input(f"\n  Press ENTER when you have finished logging into {service.upper()}...\n")

    # Brief pause so any redirect/session save completes
    time.sleep(2)
    print(f"  [OK] Session for {service} saved to profile.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    target = sys.argv[1].lower()

    if target == "all":
        for svc in SERVICES:
            login_to(svc)
    elif target in SERVICES:
        login_to(target)
    else:
        print(f"Unknown service: '{target}'")
        print(f"Available: {', '.join(SERVICES.keys())}, all")
        sys.exit(1)

    print("\n" + "="*60)
    print("  All done! Your sessions are saved.")
    print("  DIMO will now use these logins automatically.")
    print("="*60 + "\n")

    browser_manager.shutdown()


if __name__ == "__main__":
    main()
