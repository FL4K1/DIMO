import urllib.parse
from app.config.logging import logger

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

def weather_report(city: str = "") -> dict:
    try:
        if not _REQUESTS_OK:
            return {"success": False, "result": "", "error": "requests library is required for native weather."}

        location = urllib.parse.quote_plus(city.strip()) if city else ""
        url = f"https://wttr.in/{location}?format=4"

        r = requests.get(url, timeout=10)
        r.raise_for_status()

        weather_text = r.text.strip()
        
        if len(weather_text) > 200 or "<html" in weather_text.lower():
            return {"success": False, "result": "", "error": "Weather service returned invalid format."}
            
        logger.info(f"[Weather] Retrieved: {weather_text}")

        return {"success": True, "result": f"Current weather report: {weather_text}", "error": None}

    except Exception as e:
        logger.error(f"[Native] weather_report failed: {e}")
        return {"success": False, "result": "", "error": f"Failed to get weather: {e}"}
