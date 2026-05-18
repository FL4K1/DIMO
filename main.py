"""
DIMO - Digital Intelligence for Multimodal Operations

Entry point for the DIMO agent system.

Tech Stack:
- Orchestration: LangGraph + Ollama (Llama3:8b + Llama3.2:3b)
- Memory: Qdrant (Phase 4) + SQLite facts (Phase 4)
- Voice: Faster-Whisper + Piper TTS (Phase 3)
- Tools: Web search + advanced tools (Phase 5)

Usage:
    python main.py              # Text CLI mode
    python main.py --voice      # Voice I/O mode (requires microphone)
    python main.py --help       # Show options
"""

import os
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
            
            # Prepare state
            state = initialize_state()
            state["messages"] = [HumanMessage(content=user_input)]
            
            # Execute graph
            print("\nProcessing...", end=" ", flush=True)
            result = graph.invoke(state)
            print("\n")
            
            # Extract and display response
            if result.get("messages"):
                logger.info(f"Total messages in result: {len(result['messages'])}")
                
                last_message = result["messages"][-1]
                response = last_message.content if hasattr(last_message, 'content') else str(last_message)
                
                print(f"DIMO: {response}\n")
                logger.info(f"Response generated: {response[:200]}")
            else:
                print("DIMO: I couldn't generate a response.\n")
                logger.warning("No response generated")
        
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
            logger.info("User interrupted with Ctrl+C")
            break
        
        except Exception as e:
            print(f"\n✗ Error: {e}\n")
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
            
            # Prepare state
            state = initialize_state()
            state["messages"] = [HumanMessage(content=user_text)]
            
            # Process through graph
            print("🧠 Processing...", end=" ", flush=True)
            result = graph.invoke(state)
            print("✓")
            
            # Extract response
            if result.get("messages"):
                last_message = result["messages"][-1]
                response = last_message.content if hasattr(last_message, 'content') else str(last_message)
                
                print(f"\n🤖 DIMO: {response}\n")
                logger.info(f"Generated response: {response[:200]}")
                
                # Convert response to speech and stream
                print("🔊 Speaking...", end=" ", flush=True)
                success = stream_voice_response(response)
                
                if success:
                    print("✓\n")
                else:
                    print("✗ (audio playback may have failed)\n")
            else:
                print("✗ No response generated\n")
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

