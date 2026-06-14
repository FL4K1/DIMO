from app.services.browser.browser_service import BrowserService
from app.services.agents.llm_gateway import LLMGateway

def flight_finder(origin: str, destination: str, date: str, return_date: str = None, passengers: int = 1, cabin: str = "economy", save: bool = False) -> dict:
    return {"success": True, "result": f"Top flights from {origin} to {destination} on {date}:\n1. Dummy Airline, 900 USD", "error": None}
