from typing import Optional, Callable

from app.tools.search import web_search
from app.config.logging import logger


TOOL_CATALOG = {
    "web_search": {
        "name": "web_search",
        "description": "Search the web for current information...",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to execute"
                }
            },
            "required": ["query"]
        },
        "function": web_search  # Reference to actual function
    }
}



def get_tool(tool_name: str) -> Optional[Callable]:
    """Retrieve tool function by name.
    
    Args:
        tool_name: Name of the tool to retrieve
        
    Returns:
        Function reference for the tool, or None if not found.
    """

    tool_info = TOOL_CATALOG.get(tool_name)
    if not tool_info:
        logger.warning(f"Tool '{tool_name}' not found in catalog")
        return None
    
    return tool_info["function"]
