"""LLM node for reasoning and response generation.

This is the main "thinking" step where DIMO processes context
and generates responses.

Also contains fast_chat_response() — a lightweight streaming path
that uses the small model (llama3.2:3b) for simple chat, bypassing
the full LangGraph pipeline entirely.

Streaming:
  call_llm() respects a module-level flag set by set_streaming_mode().
  When enabled, tokens are printed to stdout as they arrive so the user
  sees the response being written word-by-word (text mode) or can read
  it on screen before TTS speaks it (voice mode).
"""

import time
import os
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from ollama import Client
# pyrefly: ignore [missing-import]
from langchain_core.messages import AIMessage
from app.graph.state import DimoState
import logging


load_dotenv()
logger = logging.getLogger("dimo")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3:8b")
SMALL_MODEL = os.getenv("ROUTER_MODEL", "llama3.2:3b")  # Fast model for simple chat

# ---------------------------------------------------------------------------
# Streaming control — module-level flag so main.py can flip it once
# without touching DimoState's TypedDict schema.
# ---------------------------------------------------------------------------
_stream_to_terminal: bool = False


def set_streaming_mode(enabled: bool) -> None:
    """Enable or disable token-by-token streaming for call_llm().

    Call this once in main_text() / main_voice() before invoking the graph.
    The flag persists for the lifetime of the process.
    """
    global _stream_to_terminal
    _stream_to_terminal = enabled
    logger.info(f"[LLM] Streaming mode {'ON' if enabled else 'OFF'}")


# System prompt for fast chat — keeps responses natural and concise
_FAST_CHAT_SYSTEM = (
    "You are DIMO, a sharp and friendly AI assistant. "
    "Give direct, concise, natural responses. "
    "No markdown unless the user asks for it. No filler phrases."
)


def fast_chat_response(
    user_input: str,
    history: list[tuple[str, str]] | None = None,
    print_stream: bool = True,
) -> str:
    """Respond to a simple message using the small model with token streaming.

    This bypasses the full LangGraph graph — no router, no planner, no loop.
    Ideal for greetings, small talk, quick factual questions, and anything
    that clearly doesn't need web search or tool use.

    Args:
        user_input:   The user's message.
        history:      Optional list of (user, assistant) turn tuples for
                      multi-turn context (last 4 turns are included).
        print_stream: If True, tokens are printed to stdout as they arrive.

    Returns:
        The full generated response as a plain string.
    """
    # Build a lightweight conversation prompt
    lines = [_FAST_CHAT_SYSTEM, ""]
    if history:
        for user_turn, ai_turn in history[-4:]:   # cap context at 4 turns
            lines.append(f"User: {user_turn}")
            lines.append(f"Assistant: {ai_turn}")
    lines.append(f"User: {user_input}")
    lines.append("Assistant:")
    prompt = "\n".join(lines)

    logger.info(f"[FAST] Using {SMALL_MODEL} for simple chat")
    start = time.time()

    try:
        full_response = ""
        client = Client(host=OLLAMA_HOST)
        stream = client.generate(
            model=SMALL_MODEL,
            prompt=prompt,
            stream=True,
            options={"temperature": 0.7, "num_predict": 512},
        )
        if print_stream:
            print("\nDIMO: ", end="", flush=True)
        for chunk in stream:
            token = chunk.response or ""
            if print_stream:
                print(token, end="", flush=True)
            full_response += token
        if print_stream:
            print()  # final newline

        elapsed = time.time() - start
        full_response = full_response.strip()
        logger.info(f"[FAST] Response in {elapsed:.2f}s, {len(full_response)} chars")
        return full_response

    except Exception as e:
        logger.error(f"[FAST] fast_chat_response failed: {e}")
        fallback = f"Sorry, I hit a snag: {e}"
        if print_stream:
            print(f"\nDIMO: {fallback}")
        return fallback


def call_llm(state: DimoState) -> DimoState:
    """Call the main LLM for reasoning and response generation.

    When streaming mode is ON (_stream_to_terminal = True), tokens are
    printed to stdout as they arrive. main.py detects this and skips
    re-printing the final response to avoid duplication.

    Args:
        state: Current DimoState

    Returns:
        Updated DimoState with LLM response added to messages
    """

    logger.info("=== LLM NODE CALLED ===")
    logger.info(f"Messages count: {len(state.get('messages', []))}")
    logger.info(f"Tool calls made: {len(state.get('tool_calls_made', []))}")
    logger.info(f"Current iteration: {state.get('current_iteration')}/{state.get('max_iterations')}")

    try:
        # Format conversation history for prompt
        messages = state.get("messages", [])
        if not messages:
            logger.warning("No messages to process")
            return state

        # ── System preamble (with memory + datetime, mirrors Mark's _build_config) ──
        from datetime import datetime as _dt
        _now = _dt.now().strftime("%A, %B %d, %Y — %I:%M %p")
        _time_ctx = f"[CURRENT DATE & TIME]\nRight now it is: {_now}\nUse this to calculate exact times for reminders.\n"
        try:
            from app.memory.memory_manager import load_memory, format_memory_for_prompt
            _mem_str = format_memory_for_prompt(load_memory())
        except Exception:
            _mem_str = ""
        system = (
            f"{_time_ctx}\n"
            + (f"{_mem_str}\n" if _mem_str else "")
            + "You are DIMO, a sharp and helpful AI assistant. "
            "Give direct, concise responses. "
            "Use memory context above naturally in conversation — never recite it like a list. "
            "CRITICAL: Never claim to have performed an action (like sending a message or playing music) "
            "UNLESS you see explicit confirmation in the TOOL RESULTS with success=True. "
            "If no tools were run, or a tool failed, clearly inform the user that the action was not performed. "
            "If a tool result shows [CONFIRMATION_PENDING], inform the user in ONE short sentence that you have requested their confirmation on the HUD/screen and need their approval before proceeding."
        )

        # ── Build conversation context ────────────────────────────────────
        conversation = [system, ""]
        for msg in messages:
            role = "User" if msg.__class__.__name__ == "HumanMessage" else "Assistant"
            content = msg.content if hasattr(msg, 'content') else str(msg)
            conversation.append(f"{role}: {content}")

        # ── Add intent and planning context if available ────────────────
        planning_context = state.get("planning_context")
        current_intent = state.get("current_intent") or state.get("router_result")
        if current_intent:
            conversation.append(f"\nDETECTED INTENT: {current_intent}")
        if planning_context:
            conversation.extend(["", "PLANNING CONTEXT:", planning_context])

        # ── Inject tool results if any tools ran ──────────────────────────
        tool_calls_made = state.get("tool_calls_made", [])
        if tool_calls_made:
            tool_section = ["\nTOOL RESULTS (actions already completed):"]
            for i, call in enumerate(tool_calls_made, 1):
                tool_name = call.get("tool", "unknown")
                # Handle both string results and the new dict results
                result_data = call.get("result", {})
                if isinstance(result_data, dict):
                    success = result_data.get("success", False)
                    result_msg = result_data.get("result", "")
                    error_msg = result_data.get("error", "")
                    if result_data.get("pending_confirmation"):
                        status = "CONFIRMATION_PENDING"
                        result_str = f"[{status}] {result_msg or error_msg}"
                    else:
                        status = "SUCCESS" if success else f"FAILED: {error_msg}"
                        result_str = f"[{status}] {result_msg}"
                else:
                    result_str = str(result_data)
                args = call.get("args", {})
                tool_section.append(f"{i}. [{tool_name}] args={args}")
                tool_section.append(f"   result: {result_str[:300]}")
            tool_section.append(
                "\nBased on these results, give the user a clear, "
                "natural confirmation of what was done."
            )
            conversation.append("\n".join(tool_section))
            logger.info(f"[LLM] Injecting {len(tool_calls_made)} tool result(s) into prompt")

        prompt = "\n".join(conversation) + "\nAssistant:"

        start_time = time.time()
        logger.debug(f"Prompt length: {len(prompt)} chars")

        llm_response = ""
        client = Client(host=OLLAMA_HOST)
        if _stream_to_terminal:
            # ── Streaming mode: print tokens as they arrive ──────────────
            print("\nDIMO: ", end="", flush=True)
            stream = client.generate(
                model=LLM_MODEL,
                prompt=prompt,
                stream=True,
            )
            for chunk in stream:
                token = chunk.response or ""
                print(token, end="", flush=True)
                llm_response += token
            print()  # newline after last token
        else:
            # ── Batch mode: wait for full response ───────────────────────
            response = client.generate(
                model=LLM_MODEL,
                prompt=prompt,
                stream=False,
            )
            llm_response = response.response or ""

        elapsed = time.time() - start_time
        llm_response = llm_response.strip() or "I couldn't generate a response."

        logger.info(f"LLM response generated (latency: {elapsed:.2f}s, length: {len(llm_response)} chars)")

        # Add to messages
        state["messages"].append(AIMessage(content=llm_response))
        logger.debug(f"Response preview: {llm_response[:200]}")

    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        state["messages"].append(AIMessage(content=f"I encountered an error: {str(e)}"))

    return state
