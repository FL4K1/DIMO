"""Utility functions for parsing LLM responses."""

import json
import re
from typing import Dict, Tuple


def extract_json_from_text(text: str) -> Tuple[bool, Dict]:
    """Extract JSON from text that may contain explanatory text.
    
    Handles cases where LLM wraps JSON in text like:
    "Here is the response: {json}"
    "Let me provide this: {json}"
    
    Args:
        text: Raw LLM response
        
    Returns:
        (success: bool, parsed_dict: Dict)
    """
    text = text.strip()
    
    # Try 1: Direct JSON parse
    try:
        return True, json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try 2: Find JSON block with regex (matches {...} or [...])
    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}|\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]'
    matches = re.findall(json_pattern, text)
    
    for match in matches:
        try:
            return True, json.loads(match)
        except json.JSONDecodeError:
            continue
    
    # Try 3: Find first { and last } and try to parse
    start = text.find('{')
    end = text.rfind('}')
    
    if start != -1 and end != -1 and end > start:
        try:
            json_str = text[start:end+1]
            return True, json.loads(json_str)
        except json.JSONDecodeError:
            pass
    
    # Try 4: Find first [ and last ] for array
    start = text.find('[')
    end = text.rfind(']')
    
    if start != -1 and end != -1 and end > start:
        try:
            json_str = text[start:end+1]
            return True, json.loads(json_str)
        except json.JSONDecodeError:
            pass
    
    return False, {}
