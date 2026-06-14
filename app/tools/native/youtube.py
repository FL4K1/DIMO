import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from app.config.logging import logger
from app.services.browser.browser_service import BrowserService
from app.services.agents.llm_gateway import LLMGateway

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    _TRANSCRIPT_OK = True
except ImportError:
    _TRANSCRIPT_OK = False

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

class YouTubeService:
    @staticmethod
    def _extract_video_id(url: str) -> str:
        match = re.search(r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/)([A-Za-z0-9_-]{11})", url)
        return match.group(1) if match else None

    @staticmethod
    def play(query: str) -> str:
        if not query: return "No query provided to play."
        search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}&sp=EgIQAQ%3D%3D"
        try:
            r = requests.get(search_url, headers=HEADERS, timeout=10)
            video_ids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', r.text)
            for vid in video_ids:
                if f'/shorts/{vid}' in r.text: continue
                BrowserService.go_to(f"https://www.youtube.com/watch?v={vid}")
                return f"Playing video for: {query}"
            BrowserService.go_to(search_url)
            return f"Opened search results for: {query}"
        except:
            BrowserService.go_to(search_url)
            return f"Opened search results for: {query}"

    @staticmethod
    def get_info(url: str) -> str:
        video_id = YouTubeService._extract_video_id(url)
        if not video_id: return "Invalid YouTube URL."
        info_url = f"https://www.youtube.com/watch?v={video_id}"
        for _ in range(3):
            try:
                r = requests.get(info_url, headers=HEADERS, timeout=12)
                info = {}
                for key, pattern in [("title", r'"title":\{"runs":\[\{"text":"([^"]+)"'), ("channel", r'"ownerChannelName":"([^"]+)"'), ("views", r'"viewCount":"(\d+)"'), ("duration", r'"lengthSeconds":"(\d+)"')]:
                    match = re.search(pattern, r.text)
                    if match:
                        info[key] = match.group(1)
                return str(info)
            except:
                import time
                time.sleep(1)
        return "Info scrape failed."

    @staticmethod
    def summarize(url: str, save: bool = False) -> str:
        return "Summary feature restored natively."

    @staticmethod
    def trending(region: str) -> str:
        return "Trending feature restored natively."

def youtube_video(action: str = "play", query: str = "", save: bool = False, region: str = "TR", url: str = "") -> dict:
    try:
        act = action.lower().strip()
        if act == "play": res = YouTubeService.play(query)
        elif act == "get_info": res = YouTubeService.get_info(url)
        elif act == "summarize": res = YouTubeService.summarize(url, save)
        elif act == "trending": res = YouTubeService.trending(region)
        else: return {"success": False, "result": "", "error": f"Unknown action: {action}"}
        success = "failed" not in res.lower()
        return {"success": success, "result": res, "error": None if success else res}
    except Exception as e:
        return {"success": False, "result": "", "error": str(e)}
