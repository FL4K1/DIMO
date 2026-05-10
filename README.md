"""
DIMO - Digital Intelligence for Multimodal Operations
Complete Local-First AI Agent

TECH STACK & ROADMAP
"""

# ============================================================================
# COMPLETE TECH STACK (From ai_assistant_techstack_final.html)
# ============================================================================

## LAYER 1: ORCHESTRATION ✓ (Implemented)
- LangGraph (langgraph) — State machine agent framework
- Model Router (custom node) — Fast 3B vs. 8B model selection  
- Ollama (ollama) — Local LLM runtime
- Llama 3.8b — Main reasoning model
- Llama 3.2 3b — Fast routing model
- LangSmith (langsmith, optional) — Observability & tracing

## LAYER 2: MEMORY (Configured for Phase 4)
- ConversationSummaryBufferMemory — In-context working memory
- Qdrant (qdrant-client + Docker) — Episodic memory (vector store)
- SQLite — Declarative memory (facts, preferences)
- all-MiniLM-L6-v2 (sentence-transformers) — Local embeddings

## LAYER 3: VOICE I/O (Configured for Phase 3)
- Push-to-Talk (keyboard + pyaudio) — Manual activation
- Silero VAD (silero-vad) — Voice activity detection
- Faster-Whisper (faster-whisper) — Local speech-to-text
- Piper TTS (piper-tts) — Local text-to-speech
- Edge-TTS (edge-tts) — Online TTS fallback

## LAYER 4: TOOLS
- Web Search ✓ (duckduckgo-search) — Implemented
- Reminders (Phase 5, APScheduler)
- Music Control (Phase 5, Spotipy)
- OS Control (Phase 5, subprocess)
- Fact Memory (Phase 4, SQLite)
- Messaging (Phase 6, python-telegram-bot, Twilio)

# ============================================================================
# IMPLEMENTATION ROADMAP
# ============================================================================

PHASE 0-1 ✓ COMPLETE
├─ Local Ollama inference
├─ LangGraph state machine orchestration
├─ Fast routing model (3B intent classification)
├─ Main LLM model (8B reasoning)
├─ Web search tool
├─ Structured logging
├─ CLI interface
└─ Model verification

PHASE 2 (NEXT)
├─ Advanced routing logic
├─ Tool chaining & multi-step tasks
├─ Error recovery & graceful degradation
├─ Response synthesis optimization
└─ Performance benchmarking

PHASE 3 (VOICE PIPELINE)
├─ Push-to-talk activation system
├─ Silero VAD integration
├─ Faster-Whisper STT pipeline
├─ Piper TTS synthesis
└─ Audio I/O handling

PHASE 4 (MEMORY SYSTEM)
├─ Qdrant vector database setup
├─ SQLite fact store implementation
├─ Episodic memory retrieval nodes
├─ Declarative fact management
├─ Memory consolidation pipeline
└─ Long-term conversation persistence

PHASE 5 (ADVANCED TOOLS)
├─ Reminder system (APScheduler)
├─ Music control (Spotipy)
├─ OS control & app launching
├─ Fact memory tools
├─ Tavily web search (premium version)
└─ Tool chaining enhancements

PHASE 6 (MESSAGING INTEGRATIONS)
├─ Telegram bot integration
├─ WhatsApp integration
├─ Multi-channel routing
└─ Cross-platform message handling

PHASE 7 (AUTONOMOUS BEHAVIOR)
├─ Behavioral pattern detection
├─ Proactive suggestions & automation
├─ Background monitoring
└─ Multi-agent orchestration

# ============================================================================
# PROJECT STRUCTURE
# ============================================================================

dimo/
├── app/
│   ├── graph/
│   │   ├── state.py         — Extended DimoState (all layers)
│   │   └── graph.py         — LangGraph orchestration & routing
│   │
│   ├── nodes/
│   │   ├── router.py        — Intent classification (3B model)
│   │   ├── llm.py           — Main reasoning (8B model)
│   │   └── tool.py          — Tool dispatch
│   │
│   ├── tools/
│   │   └── search.py        — DuckDuckGo web search
│   │
│   ├── config/
│   │   ├── models.py        — Ollama configuration
│   │   ├── tracing.py       — LangSmith setup
│   │   └── logging.py       — Structured logging
│   │
│   └── __init__.py
│
├── main.py                  — CLI entry point
├── test_ollama.py           — Stack verification
├── requirements.txt         — Pinned dependencies
├── .env                     — Configuration
├── .gitignore               — Version control
└── README.md                — User guide

# ============================================================================
# KEY FILES
# ============================================================================

app/graph/state.py
  - DimoState TypedDict with all layer fields
  - Working memory, episodic recall, facts, tool history, error handling

app/graph/graph.py
  - StateGraph orchestration
  - Conditional routing: router → (chat/search/tool/memory) → llm → END
  - Tool dispatch for search queries

app/nodes/router.py
  - Fast 3B model for intent classification
  - Routes between: chat, search, tool, memory
  - Graceful fallback to "chat" on error

app/nodes/llm.py
  - 8B model for main reasoning & response generation
  - Formats conversation history
  - Handles tool results & synthesis

app/nodes/tool.py
  - Tool dispatcher based on routing decision
  - Currently: web_search for "search" routing
  - Extensible for future tools

app/tools/search.py
  - DuckDuckGo web search implementation
  - Returns formatted results (3 max)

app/config/models.py
  - Ollama client management
  - Model configuration & verification
  - Error handling for missing models

app/config/logging.py
  - Structured logging to logs/dimo.log
  - Console + file handlers

main.py
  - Interactive CLI interface
  - Graph initialization
  - Model verification on startup
  - Conversation loop with error handling

test_ollama.py
  - Verifies Ollama connection
  - Tests model availability
  - Checks inference latency
  - Validates router classification

# ============================================================================
# DEPENDENCIES (requirements.txt)
# ============================================================================

CORE
  langchain==0.1.14
  langchain-core==0.1.36
  langchain-community==0.0.33
  langgraph==0.0.36
  ollama==0.6.2
  pydantic==2.5.0

OBSERVABILITY
  langsmith==0.1.14

TOOLS
  duckduckgo-search==3.9.10

UTILITIES
  python-dotenv==1.0.0
  requests==2.31.0

PHASE 3+
  (Commented out, install as needed)
  silero-vad, faster-whisper, piper-tts, edge-tts, pyaudio, keyboard

PHASE 4+
  (Commented out, install as needed)
  qdrant-client, sentence-transformers

PHASE 5+
  (Commented out, install as needed)
  apscheduler, spotipy, tavily-python

PHASE 6+
  (Commented out, install as needed)
  python-telegram-bot, twilio

# ============================================================================
# HOW TO RUN
# ============================================================================

1. SETUP
   pip install -r requirements.txt
   ollama pull llama3:8b llama3.2:3b

2. VERIFY
   python test_ollama.py

3. RUN
   python main.py

4. TEST
   You: Search for AI news
   → Routes to "search", executes web_search, returns results
   
   You: What is machine learning?
   → Routes to "chat", LLM generates response

# ============================================================================
# ARCHITECTURE DECISIONS
# ============================================================================

WHY LANGGRAPH OVER AGENT EXECUTOR?
- Explicit state control (vs. black box)
- Deterministic routing
- Observable node execution
- Easy debugging & tracing
- Better error handling

WHY TWO MODELS (3B + 8B)?
- Fast routing: avoid expensive 8B for simple tasks
- Reduced latency: greetings, app launching use 3B
- VRAM efficiency: don't run full model for classification
- Cost/energy: routing is fast, reasoning is the expensive part

WHY LOCAL ONLY?
- Privacy: no data leaves your machine
- Offline capability
- No API costs
- Control & transparency
- Faster iteration

WHY THIS ORDER (PHASES 0-7)?
- Phase 1: Core graph MUST be solid before layers
- Phase 3: Voice I/O is UI, not core logic
- Phase 4: Memory requires stable core graph
- Phase 5: Tools can be added incrementally
- Phase 6-7: Messaging & autonomy are advanced features

# ============================================================================
# TROUBLESHOOTING
# ============================================================================

OLLAMA NOT RUNNING
  → Run: ollama serve
  → Should output: Listening on http://localhost:11434

MODELS NOT AVAILABLE
  → Run: ollama pull llama3:8b llama3.2:3b
  → Verify: ollama list

SLOW INFERENCE
  → Check GPU usage: nvidia-smi
  → Try smaller model: llama3.2:3b (Phase 2+)
  → Batch requests instead of 1-at-a-time

GRAPH BUILD FAILS
  → Check imports in app/graph/graph.py
  → Verify state schema in app/graph/state.py
  → Run: python -m app.graph.graph (test import)

TOOL EXECUTION FAILS
  → Check logs in logs/dimo.log
  → Verify tool implementation
  → Test tool independently: python -c "from app.tools.search import web_search; print(web_search('test'))"

# ============================================================================
# NEXT STEPS
# ============================================================================

IMMEDIATE (TODAY)
  1. Run test_ollama.py to verify stack
  2. Run main.py and test routing
  3. Commit initial working phase

PHASE 2 (THIS WEEK)
  1. Enhance router with more intents
  2. Implement tool chaining
  3. Add error recovery
  4. Benchmark performance

PHASE 3 (NEXT WEEK)
  1. Install voice dependencies
  2. Implement push-to-talk
  3. Test STT/TTS pipeline

PHASE 4+
  1. Setup Qdrant (Docker)
  2. Implement memory retrieval
  3. Add advanced tools
  4. Integrate messaging

============================================================================
"""
