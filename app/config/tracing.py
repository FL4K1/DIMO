"""LangSmith tracing configuration.

Enables observability and debugging of all agent decisions.
"""

''' 

import os
from dotenv import load_dotenv

load_dotenv()

# LangSmith configuration
LANGSMITH_ENABLED = bool(os.getenv("LANGSMITH_API_KEY"))
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "DIMO")

# Enable tracing by setting environment variables
if LANGSMITH_ENABLED:
    os.environ["LANGCHAIN_TRACING_V2"] = "False"  # Disable v2 tracing for compatibility for now
    os.environ["LANGCHAIN_API_KEY"] = os.getenv("LANGSMITH_API_KEY", "")
    os.environ["LANGCHAIN_PROJECT"] = LANGSMITH_PROJECT
    print(f"ON : LangSmith tracing enabled for project: {LANGSMITH_PROJECT}")
else:
    print("OFF : LangSmith not configured. Set LANGSMITH_API_KEY to enable tracing.")


'''
