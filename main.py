"""
DIMO - Digital Intelligence for Multimodal Operations

Entry point for the DIMO agent system.

Tech Stack:
- Orchestration: LangGraph + Ollama (Llama3:8b + Llama3.2:3b)
- Memory: Qdrant (Phase 4) + SQLite facts (Phase 4)
- Voice: Faster-Whisper + Piper TTS (Phase 3)
- Tools: Web search + advanced tools (Phase 5)

Fast Path:
- Simple chat / greetings / quick Q&A → llama3.2:3b, streaming, no graph
- Complex / tool / search requests → full LangGraph pipeline

Usage:
    python main.py              # Text CLI mode
    python main.py --voice      # Voice I/O mode (requires microphone)
    python main.py --help       # Show options
"""

import os
import re
import sys
import argparse
from dotenv import load_dotenv

# Initialize configuration EARLY (before building graph)
load_dotenv()

# Initialize tracing (optional, requires LANGSMITH_API_KEY)
from app.config import tracing

from langchain_core.messages import HumanMessage
from app.graph.graph import build_graph
from app.config.logging import logger
from app.config.models import verify_models
from app.nodes.llm import fast_chat_response, set_streaming_mode  # fast path + streaming
from app.nodes.voice import (
    record_audio,
    record_audio_push_to_talk,
    transcribe_audio,
    stream_voice_response,
    process_voice_input,
    check_audio_devices,
    initialize_whisper,
    WHISPER_AVAILABLE,
    PIPER_AVAILABLE,
    PYAUDIO_AVAILABLE,
    KEYBOARD_AVAILABLE,
)

def initialize_state():
    """Create initial state for a new conversation."""
    return {
        "messages": [],
        "summary": "",
        "current_intent": "",
        "router_result": "",
        "summary_ask_counter": 0,
        "episodic_memory_query": None,
        "episodic_recall": None,
        "facts": None,
        "next_tool": None,
        "tool_history": [],
        "tool_output": None,
        "user_profile": None,
        "session_id": None,
        "error_message": None,
        "tool_plan": None,
        "tool_calls_made": [],
        "max_iterations": 5,
        "current_iteration": 0,
        "planning_context": None,
        "should_continue": True,
        "loop_error_count": 0
    }


# ---------------------------------------------------------------------------
# Fast-path heuristic
# ---------------------------------------------------------------------------

# Keywords that signal the user needs a tool, search, or complex reasoning.
# If ANY of these appear, we skip the fast path and run the full graph.
_TOOL_KEYWORDS = re.compile(
    r"\b("
    r"search|find|look up|google|lookup|"
    r"weather|forecast|temperature|"
    r"news|headlines|latest|"
    r"open|launch|start|run|execute|"
    r"remind|reminder|alarm|timer|schedule|"
    r"calculate|compute|solve|convert|"
    r"play|spotify|music|pause|skip|"
    r"email|send|message|notify|"
    r"file|read|write|save|create|"
    r"screenshot|clipboard|copy|paste|"
    r"install|update|download"
    r")\b",
    re.IGNORECASE,
)


def is_simple_chat(text: str) -> bool:
    """Heuristic: decide if a message is safe to handle via the fast path.

    Returns True when the message is short and contains no tool/search
    keywords — i.e., it's plain conversation that doesn't need the graph.
    """
    # Long messages likely need reasoning / tool use
    if len(text) > 150:
        return False
    # Any tool/action keyword → full graph
    if _TOOL_KEYWORDS.search(text):
        return False
    # Question marks alone don't disqualify — "how are you?" is still fast
    return True



def main_text():
    """Run the DIMO CLI text interface."""
    
    print("\n" + "="*70)
    print("DIMO - Digital Intelligence for Multimodal Operations")
    print("="*70)
    print("Local-first AI agent with LangGraph + Ollama")
    print("Type 'exit' or 'quit' to exit")
    print("="*70 + "\n")
    
    logger.info("Starting DIMO CLI text interface")
    
    # Verify models are available
    print("Verifying local AI stack...", end=" ", flush=True)
    if not verify_models():
        print("\u2717 FAILED\n")
        print("\u2717 Error: Required models not available in Ollama")
        print("  Run: ollama pull llama3:8b llama3.2:3b")
        logger.error("Model verification failed")
        return
    print("\u2713")
    
    try:
        # Build graph
        print("Building graph...", end=" ", flush=True)
        graph = build_graph()
        print("\u2713\n")
        
    except Exception as e:
        print(f"\u2717 Failed to build graph: {e}")
        logger.error(f"Graph build failed: {e}")
        return
    
    # Conversation history for fast-path multi-turn context
    # Each entry is a (user_text, assistant_text) tuple
    fast_history: list[tuple[str, str]] = []

    # Enable streaming — tokens print to terminal as they arrive
    set_streaming_mode(True)

    # Main conversation loop
    while True:
        try:
            user_input = input("You: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ["exit", "quit"]:
                print("\nGoodbye!\n")
                logger.info("User exited DIMO")
                break
            
            logger.info(f"Processing user input: {user_input}")

            # ------------------------------------------------------------------
            # FAST PATH — simple chat: small model, streaming, no graph
            # ------------------------------------------------------------------
            if is_simple_chat(user_input):
                logger.info("[FAST PATH] Simple chat detected — skipping graph")
                response = fast_chat_response(
                    user_input,
                    history=fast_history,
                    print_stream=True,
                )
                # Keep last 10 turns of fast-path history
                fast_history.append((user_input, response))
                if len(fast_history) > 10:
                    fast_history.pop(0)
                print()  # blank line separator
                continue

            # ------------------------------------------------------------------
            # FULL PATH — tool use / search / complex reasoning: full graph
            # ------------------------------------------------------------------
            logger.info("[FULL PATH] Complex query detected — running graph")
            print("\n[Thinking...]")
            
            # Prepare state
            state = initialize_state()
            state["messages"] = [HumanMessage(content=user_input)]
            
            # Execute graph (call_llm streams tokens to terminal during invoke)
            result = graph.invoke(state)
            print()  # blank line after streamed response
            
            # Extract response for history (already printed by streaming)
            if result.get("messages"):
                logger.info(f"Total messages in result: {len(result['messages'])}")
                
                last_message = result["messages"][-1]
                response = last_message.content if hasattr(last_message, 'content') else str(last_message)
                logger.info(f"Response generated: {response[:200]}")

                # Carry full-path turns into fast-path history
                fast_history.append((user_input, response))
                if len(fast_history) > 10:
                    fast_history.pop(0)
            else:
                print("DIMO: I couldn't generate a response.\n")
                logger.warning("No response generated")
        
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
            logger.info("User interrupted with Ctrl+C")
            break
        
        except Exception as e:
            print(f"\n\u2717 Error: {e}\n")
            logger.error(f"Conversation error: {e}", exc_info=True)



def main_voice():
    """Run the DIMO voice interface."""
    
    print("\n" + "="*70)
    print("DIMO - Voice Interface (Phase 3)")
    print("="*70)
    print("Speak → Listen → Respond")
    print("Press Ctrl+C to exit")
    print("="*70 + "\n")
    
    logger.info("Starting DIMO voice interface")
    
    # Check voice capabilities
    print("Checking audio capabilities...", end=" ", flush=True)
    devices = check_audio_devices()
    
    if not devices["whisper_available"]:
        print("\n✗ FAILED\n")
        print("✗ Faster-Whisper not installed")
        print("  Run: pip install faster-whisper")
        return
    
    if not devices["piper_available"]:
        print("\n✗ FAILED\n")
        print("✗ Piper TTS not installed")
        print("  Run: pip install piper-tts")
        return
    
    if not devices["pyaudio_available"]:
        print("\n✗ FAILED\n")
        print("✗ PyAudio not installed")
        print("  Run: pip install pyaudio")
        return
    
    if not devices["input_devices"]:
        print("\n✗ FAILED\n")
        print("✗ No microphone detected")
        print("  Check: Audio device is connected and recognized")
        return
    
    print("✓")
    print(f"  Microphones: {len(devices['input_devices'])}")
    print(f"  Speakers: {len(devices['output_devices'])}\n")
    
    # Verify AI models
    print("Verifying AI models...", end=" ", flush=True)
    if not verify_models():
        print("✗ FAILED\n")
        print("✗ Error: Required models not available in Ollama")
        print("  Run: ollama pull llama3:8b llama3.2:3b")
        logger.error("Model verification failed")
        return
    print("✓")
    
    try:
        # Build graph
        print("Building graph...", end=" ", flush=True)
        graph = build_graph()
        print("✓\n")
        
    except Exception as e:
        print(f"✗ Failed to build graph: {e}")
        logger.error(f"Graph build failed: {e}")
        return
    
    # Pre-initialize Whisper model (loading happens once)
    print("Loading Whisper model (first time is slow)...", end=" ", flush=True)
    whisper_model = initialize_whisper()
    if whisper_model is None:
        print("✗ FAILED")
        logger.error("Could not initialize Whisper")
        return
    print("✓\n")
    
    print("Ready for voice input!")
    if KEYBOARD_AVAILABLE:
        print("  Mode: Push-to-talk (hold CTRL to speak, release to stop)")
        print("  Tip: Say 'exit' to quit\n")
    else:
        print("  Mode: 5-second timed recording (keyboard library not installed)")
        print("  Tip: Say 'exit' to quit\n")
        print("  Install keyboard library for PTT: pip install keyboard\n")
    
    # Conversation history for fast-path multi-turn context in voice mode
    fast_history: list[tuple[str, str]] = []

    # Enable streaming - tokens print to terminal as they arrive,
    # then TTS speaks the collected full response.
    set_streaming_mode(True)

    # Main voice loop
    while True:
        try:
            if KEYBOARD_AVAILABLE:
                print("\n[PTT] Hold CTRL to speak, release to stop...", flush=True)
                audio_data = record_audio_push_to_talk(
                    trigger_key="ctrl",
                    wait_timeout=30,
                )
            else:
                print("Listening (5 seconds)...", end=" ", flush=True)
                audio_data = record_audio(duration_seconds=5)

            if audio_data is None:
                print("Recording failed or timed out — try again.")
                continue

            print("[OK] Audio captured.")
            
            # Transcribe
            print("🔄 Transcribing...", end=" ", flush=True)
            user_text = process_voice_input(audio_data, whisper_model)
            
            if user_text.startswith("ERROR"):
                print(f"\n✗ {user_text}\n")
                continue
            
            print(f"\n\n📝 You said: {user_text}\n")
            logger.info(f"Transcribed: {user_text}")
            
            # Check for exit commands
            if user_text.lower() in ["exit", "quit", "goodbye"]:
                print("\nGoodbye!\n")
                logger.info("User exited via voice")
                break

            # ------------------------------------------------------------------
            # FAST PATH — simple chat: small model, no graph, then TTS
            # ------------------------------------------------------------------
            if is_simple_chat(user_text):
                logger.info("[FAST PATH] Simple voice query - skipping graph")
                # Stream text to screen, then speak it
                response = fast_chat_response(
                    user_text,
                    history=fast_history,
                    print_stream=True,   # stream word-by-word to terminal too
                )
                logger.info(f"Fast response: {response[:200]}")

                fast_history.append((user_text, response))
                if len(fast_history) > 10:
                    fast_history.pop(0)

                print("\n[Speaking...]", end=" ", flush=True)
                success = stream_voice_response(response)
                print("done\n" if success else "failed\n")
                continue

            # ------------------------------------------------------------------
            # FULL PATH - tool use / search / complex reasoning: full graph
            # ------------------------------------------------------------------
            logger.info("[FULL PATH] Complex voice query - running graph")
            print("\n[Thinking...] ", flush=True)

            # Prepare state
            state = initialize_state()
            state["messages"] = [HumanMessage(content=user_text)]

            # Process through graph (call_llm streams tokens to terminal)
            result = graph.invoke(state)
            print()  # blank line after streamed output

            # Extract response for TTS (already printed by streaming)
            if result.get("messages"):
                last_message = result["messages"][-1]
                response = last_message.content if hasattr(last_message, 'content') else str(last_message)
                logger.info(f"Generated response: {response[:200]}")

                fast_history.append((user_text, response))
                if len(fast_history) > 10:
                    fast_history.pop(0)

                # Speak the collected response
                print("[Speaking...]", end=" ", flush=True)
                success = stream_voice_response(response)
                if success:
                    print("done\n")
                else:
                    print("failed\n")
            else:
                print("[!] No response generated\n")
                logger.warning("No response from graph")
        
        except KeyboardInterrupt:
            print("\n\nExiting...\n")
            logger.info("User exited with Ctrl+C")
            break
        
        except Exception as e:
            print(f"\n✗ Error: {e}\n")
            logger.error(f"Voice conversation error: {e}", exc_info=True)


def main():
    """Main entry point - choose between text and voice modes."""
    
    parser = argparse.ArgumentParser(
        description="DIMO - Digital Intelligence for Multimodal Operations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py              # Text CLI mode (default)
  python main.py --voice      # Voice interface mode
  python main.py --help       # Show this message
        """
    )
    
    parser.add_argument(
        "--voice",
        action="store_true",
        help="Run in voice interface mode (requires microphone and speaker)"
    )
    
    args = parser.parse_args()
    
    if args.voice:
        main_voice()
    else:
        main_text()


if __name__ == "__main__":
    main()

