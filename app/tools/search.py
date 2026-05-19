"""Web search tool using DuckDuckGo (ddgs)."""

# pyrefly: ignore [missing-import]
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS  # fallback for older installs
import logging


logger = logging.getLogger("dimo")

def web_search(query: str) -> str:
    """Search the web for information.
    
    Args:
        query: Search query string
        
    Returns:
        Formatted string with search results
    """
    logger.info(f"Executing web search: {query}")
    
    try:
        results = DDGS().text(query, max_results=3)
        
        if not results:
            logger.warning(f"No results found for query: {query}")
            return "No search results found."
        
        output = []
        for i, r in enumerate(results, 1):
            result_str = f"{i}. {r['title']}\n   {r['body'][:200]}..."
            output.append(result_str)
        
        formatted_results = "\n\n".join(output)
        logger.debug(f"Search returned {len(results)} results")
        
        return formatted_results
        
    except Exception as e:
        logger.error(f"Web search failed: {e}")
        return f"Search failed: {str(e)}"
